"""One canonical requirement list per RFP, extracted once and shared by every bidder.

Before this function existed, each company's AI Compliance Agent ran its own extraction
over the same tender PDF. Five LLM passes over the same document produced five different
lists, so `met / total` compared different exams -- in bid job 170a2315 UltraVideoTech
scored 0/16 while CamFaceSolution scored 1/70 on the same RFP. A denominator that moves
with the bidder is not a score, and it cannot rank anyone.

So the requirement list is a property of the RFP, not of the bidder. This function owns
it: give it an RFP url, it reads the document once, extracts what a video analytics
supplier must meet, and caches that against the url. Every later caller -- the other four
companies, and every subsequent round on the same tender -- gets the identical list back
without another token spent.

Concurrency is the whole point, not an afterthought. Five compliance agents start within
seconds of each other, so the naive cache is a race: all five miss, all five extract, and
nothing is saved. `_requirements_for` holds a per-url lock across the extraction, so the
first caller works and the rest block until it lands and then read the cache. A waiter
never starts a second extraction and never gets an answer before the in-flight one is
stored.

This is why the function is stateful and single-replica: the cache and the lock live in
this process. As a Kubernetes job -- or behind two replicas -- each caller would get its
own empty cache and its own lock, which is the bug this exists to fix.
"""
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import dspy
import requests

import rfp_scope  # vendored beside this file by build.sh

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# Module level, not instance level. The executor builds a fresh AIOSv1PolicyRule for
# each call, so anything hung off `self` is gone by the next one and every caller would
# miss the cache.
_CACHE = {}                      # rfp_url -> extracted requirements dict
_LOCKS = {}                      # rfp_url -> threading.Lock, one extraction at a time
_LOCKS_GUARD = threading.Lock()  # guards _LOCKS itself
_TEXT_CACHE = {}                 # rfp_url -> extracted PDF text


def _lock_for(url):
    """One lock per url, created once. Two callers must get the *same* lock object."""
    with _LOCKS_GUARD:
        lock = _LOCKS.get(url)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[url] = lock
        return lock


class RfpRequirementsSignature(dspy.Signature):
    """
    ### ROLE
    You are reading a real tender document on behalf of the Video Analytics suppliers
    bidding for it. Every bidder will be judged against the list you produce, so it must
    describe the RFP, not any one company.

    ### TASK
    Extract, from the RFP text only, what the buyer is asking for:

    1. `usecases` -- the video analytics capabilities the buyer wants (face recognition,
       crowd density, ANPR, intrusion detection, abandoned object, and so on). Use the
       buyer's own wording for `name`. Give each a short lowercase `id` with underscores.
    2. `total_licenses` -- the number of camera licences / channels the deployment
       covers. If the document gives several figures, use the total for the video
       analytics scope. If it genuinely does not say, use 0.
    3. `requirements` -- the specific, checkable conditions **the video analytics
       software must meet**: operating environment (indoor/outdoor), accuracy or KPI
       thresholds, certifications held by the analytics supplier, response times,
       integration demands on the analytics. One line each.

       SCOPE. A tender of this kind procures a whole system, and most of it is somebody
       else's obligation. Keep a requirement only if a video analytics software supplier
       could satisfy or fail it on its own. Leave out anything that binds another party,
       even where the same clause also mentions analytics:

         * camera, lens, housing, pole, mounting and cabling specifications
         * VMS, NVR, encoder or storage-appliance specifications
         * server, GPU, network, bandwidth or datacentre hardware supply
         * OEM obligations belonging to a camera/VMS vendor -- ONVIF membership, OEM
           certifications, OEM financial standing, country of manufacture
         * civil works, power, site preparation, physical security
         * bid process and contract administration -- EMD, bid security, turnover,
           document formats, deadlines, payment terms, penalties, manpower rosters

       Example of what to leave out: "IP CCTV System OEM for Cameras & VMS must be a
       member and/or listed in the ONVIF website" -- that is the camera OEM's
       membership, not the analytics supplier's.

       Example of what to keep: "FRS must support 1:1, 1:N and N:N matching" -- that is
       the analytics software.

       A clause that is genuinely about the analytics but expressed in hardware terms --
       "analytics shall run on GPU servers in a centralised architecture" -- is in
       scope, because it constrains how the analytics is delivered.
    4. `benchmarked_usecases` -- the ids of use cases the RFP says will be tested live
       against the vendors (an accuracy bake-off, a KPI demonstration, a provided video
       or image set). Empty if the RFP describes no live test.

    Do not invent requirements the document does not state. Do not pad the list.

    ### OUTPUT
    Output EXACTLY a JSON block:
    {"usecases": [{"id": "string", "name": "string", "outdoor": bool}],
     "total_licenses": int,
     "requirements": ["string"],
     "benchmarked_usecases": ["string"]}
    """
    rfp_text = dspy.InputField(desc="Text extracted from the RFP document")
    requirements_result = dspy.OutputField(desc="JSON block of extracted requirements")


class AIOSv1PolicyRule:

    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id or "va-rfp-requirements"
        self.settings = settings or {}
        self.parameters = parameters or {}

        self.max_chars = int(self.settings.get("max_rfp_chars") or 90000)
        self.download_timeout = float(self.settings.get("download_timeout_seconds") or 60)
        # How long a waiter will block for the in-flight extraction before giving up.
        # Generous on purpose: waiting is the cheap outcome, a duplicate extraction is
        # the expensive one, and a compliance agent has no deadline of its own here.
        self.wait_timeout = float(self.settings.get("wait_timeout_seconds") or 300)

    # --- entry point -------------------------------------------------------

    def eval(self, parameters, input_data, context):
        try:
            return self._run(parameters or {}, input_data or {})
        except Exception as e:
            # A raise here surfaces as a 500 in the compliance agent's own call, which
            # costs the round a bidder. A shaped failure lets the agent fall back.
            log.exception("%s: extraction failed", self.rule_id)
            return {"status": "extraction_failed", "error": str(e)[:500], "requirements": []}

    def _run(self, parameters, input_data):
        # The SDK also folds parameters into input_data; read either, call-time first.
        merged = dict(self.parameters)
        merged.update(input_data.get("parameters") or {})
        merged.update(parameters)

        rfp_url = input_data.get("rfp_url") or merged.get("rfp_url")
        if not rfp_url:
            return {"status": "no_rfp_url", "error": "rfp_url is required", "requirements": []}

        tool_model = merged.get("tool_model") or {}

        started = time.time()
        asked, cached = self._requirements_for(rfp_url, tool_model, input_data.get("rfp_text"))
        asked = dict(asked)
        asked["rfp_url"] = rfp_url
        asked["cached"] = cached
        asked["status"] = "ok"
        asked["elapsed_seconds"] = round(time.time() - started, 2)
        log.info("%s: %s -> %d requirements (cached=%s, %.2fs)", self.rule_id, rfp_url,
                 len(asked.get("requirements") or []), cached, asked["elapsed_seconds"])
        return asked

    # --- the cache and its lock -------------------------------------------

    def _requirements_for(self, rfp_url, tool_model, rfp_text=None):
        """The shared list for this url, extracting it at most once.

        Double-checked: the cheap read happens outside the lock so a warm url costs
        nothing, and the second read happens inside it because by the time a waiter is
        admitted the first caller has already stored the answer. Without that second
        read every queued caller would extract in turn, which is the behaviour this
        function exists to prevent.
        """
        hit = _CACHE.get(rfp_url)
        if hit is not None:
            return hit, True

        lock = _lock_for(rfp_url)
        acquired = lock.acquire(timeout=self.wait_timeout)
        if not acquired:
            # Someone has been extracting for longer than we are willing to wait. Say so
            # rather than starting a competing extraction.
            raise TimeoutError(
                f"waited {self.wait_timeout:.0f}s for the in-flight extraction of {rfp_url}")
        try:
            hit = _CACHE.get(rfp_url)
            if hit is not None:
                return hit, True

            text = rfp_text or self._rfp_text(rfp_url)
            asked = self._scope(self._extract(text, tool_model))
            _CACHE[rfp_url] = asked
            return asked, False
        finally:
            lock.release()


    @staticmethod
    def _scope(asked):
        """Drop what binds somebody other than the analytics supplier.

        The prompt already says to, and a long tender still gets clauses through -- the
        camera OEM's ONVIF membership, the EMD, the turnover floor. Every bidder fails
        those identically, so they tell the evaluator nothing and drag the whole
        compliance dimension down.

        This runs here rather than in each agent on purpose. Filtering per company would
        put a different list in front of each bidder again, which is the thing this
        function exists to prevent. What was dropped is kept on the answer so a bid can
        show it.
        """
        requirements = asked.get("requirements") or []
        kept, dropped = rfp_scope.in_scope(requirements)
        if dropped:
            log.info("scope: %d of %d requirements belong to another supplier or to the "
                     "tender process; keeping %d", len(dropped), len(requirements), len(kept))
        asked["requirements"] = kept
        asked["requirements_out_of_scope"] = dropped
        return asked

    # --- reading the document ---------------------------------------------

    def _rfp_text(self, rfp_url):
        cached = _TEXT_CACHE.get(rfp_url)
        if cached is not None:
            return cached

        resp = requests.get(rfp_url, timeout=self.download_timeout)
        resp.raise_for_status()
        body = resp.content
        log.info("%s: downloaded %s (%d bytes)", self.rule_id, rfp_url, len(body))

        text = self._pdf_text(body) if rfp_url.lower().endswith(".pdf") else body.decode(
            "utf-8", errors="replace")
        text = re.sub(r"\n{3,}", "\n\n", text)
        if len(text) > self.max_chars:
            text = text[:self.max_chars]
        _TEXT_CACHE[rfp_url] = text
        return text

    @staticmethod
    def _pdf_text(body):
        """Layout-preserving extraction.

        The clauses that decide a round -- the benchmarking-certificate requirement, the
        minimum camera-licence count -- live inside table cells, so a reader that
        discards layout loses exactly the lines worth extracting.
        """
        import pdfplumber
        fd, path = tempfile.mkstemp(suffix=".pdf", prefix="rfp-")
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        try:
            pages = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    pages.append(page.extract_text() or "")
            return "\n".join(pages)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    # --- the extraction ----------------------------------------------------

    def _extract(self, rfp_text, tool_model):
        lm = self._build_lm(tool_model)
        with dspy.context(lm=lm):
            result = dspy.ChainOfThought(RfpRequirementsSignature)(rfp_text=rfp_text)
        return self._parse(getattr(result, "requirements_result", ""))

    @staticmethod
    def _build_lm(tool_model):
        """A dspy LM from the caller's own model block.

        The block is whatever the calling agent already uses, passed through on
        `parameters.tool_model`, so this function never holds a key of its own and never
        has to agree with the agents about which model is current.
        """
        if not isinstance(tool_model, dict) or not tool_model:
            raise ValueError("parameters.tool_model is required and must carry the caller's model block")

        block = tool_model.get("llm_block_id") or tool_model.get("model") or ""
        params = dict(tool_model.get("llm_parameters") or {})
        api_key = params.pop("api_key", None) or tool_model.get("api_key")
        if not block:
            raise ValueError("tool_model has no llm_block_id")
        if not api_key:
            raise ValueError(f"tool_model for {block!r} carries no api_key")

        name = block.split(":", 1)[1] if ":" in block else block
        if block.startswith("openai:"):
            model = f"openai/{name}"
        elif block.startswith("gemini:") or block.startswith("google:"):
            model = f"gemini/{name}"
        elif block.startswith("anthropic:"):
            model = f"anthropic/{name}"
        else:
            # Already a litellm-style id, or a provider dspy knows by name.
            model = block

        # Only what dspy.LM passes through to litellm. `top_k` in particular is carried
        # in these blocks and is not a valid OpenAI argument, so an unfiltered splat
        # fails the call outright.
        allowed = ("temperature", "max_tokens", "top_p", "presence_penalty",
                   "frequency_penalty", "stop", "seed")
        kwargs = {k: v for k, v in params.items() if k in allowed}
        if "max_tokens" not in kwargs and "max_completion_tokens" in params:
            kwargs["max_tokens"] = params["max_completion_tokens"]
        return dspy.LM(model=model, api_key=api_key, **kwargs)

    @staticmethod
    def _parse(raw):
        """The signature asks for a bare JSON block; models wrap it anyway."""
        text = str(raw or "").strip()
        if not text:
            raise ValueError("the model returned nothing")

        fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
        if fenced:
            text = fenced.group(1).strip()
        else:
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                text = text[start:end + 1]

        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"expected a JSON object, got {type(data).__name__}")

        usecases = []
        for uc in data.get("usecases") or []:
            if isinstance(uc, dict) and uc.get("id"):
                usecases.append({"id": str(uc["id"]).strip().lower().replace(" ", "_"),
                                 "name": str(uc.get("name") or uc["id"]),
                                 "outdoor": bool(uc.get("outdoor"))})

        requirements, seen = [], set()
        for req in data.get("requirements") or []:
            line = " ".join(str(req).split())
            # The same clause reaches the model more than once in a long tender, and a
            # duplicate would be judged twice and counted twice in the denominator.
            key = line.lower()
            if line and key not in seen:
                seen.add(key)
                requirements.append(line)

        try:
            total_licenses = int(data.get("total_licenses") or 0)
        except (TypeError, ValueError):
            total_licenses = 0

        return {
            "usecases": usecases,
            "total_licenses": total_licenses,
            "requirements": requirements,
            "benchmarked_usecases": [str(b).strip().lower().replace(" ", "_")
                                     for b in (data.get("benchmarked_usecases") or []) if b],
        }
