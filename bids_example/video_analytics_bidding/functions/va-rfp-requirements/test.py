"""Off-cluster tests for va-rfp-requirements.

The cache and the single-flight lock are the whole point of this function, and both are
concurrency behaviour -- the kind that looks fine in a single-threaded read of the code
and races in the pod. So the tests below actually start threads and assert on how many
extractions happened, rather than on what the code appears to do.

    ./venv/bin/python bids_example/video_analytics_bidding/functions/va-rfp-requirements/test.py

dspy and pdfplumber are stubbed: they are installed in the function pod from
function/code/requirements.txt, not on a developer machine, and nothing here needs a
real model.
"""
import json
import os
import sys
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.join(HERE, "function", "code")


# --- stubs, installed before function.py is imported ------------------------

class _FakeSignature:
    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)


def _install_stubs():
    dspy = types.ModuleType("dspy")

    class InputField:
        def __init__(self, **kw): pass

    class OutputField:
        def __init__(self, **kw): pass

    class Signature:
        def __init_subclass__(cls, **kw):
            super().__init_subclass__(**kw)

    class LM:
        instances = []

        def __init__(self, model=None, api_key=None, **kwargs):
            self.model, self.api_key, self.kwargs = model, api_key, kwargs
            LM.instances.append(self)

    class _Ctx:
        def __init__(self, **kw): self.kw = kw
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class ChainOfThought:
        # Set by each test: what the "model" returns, and how long it pretends to take.
        answer = '{"usecases": [], "total_licenses": 0, "requirements": [], "benchmarked_usecases": []}'
        delay = 0.0
        calls = 0
        lock = threading.Lock()

        def __init__(self, signature): self.signature = signature

        def __call__(self, **kwargs):
            with ChainOfThought.lock:
                ChainOfThought.calls += 1
            if ChainOfThought.delay:
                time.sleep(ChainOfThought.delay)
            return types.SimpleNamespace(requirements_result=ChainOfThought.answer)

    dspy.InputField = InputField
    dspy.OutputField = OutputField
    dspy.Signature = Signature
    dspy.LM = LM
    dspy.context = _Ctx
    dspy.ChainOfThought = ChainOfThought
    sys.modules["dspy"] = dspy

    pdfplumber = types.ModuleType("pdfplumber")
    pdfplumber.open = lambda path: (_ for _ in ()).throw(
        AssertionError("no test should reach a real PDF"))
    sys.modules["pdfplumber"] = pdfplumber
    return dspy


dspy = _install_stubs()
sys.path.insert(0, CODE)
import function as F  # noqa: E402


MODEL = {"llm_block_id": "openai:gpt-5.4-mini",
         "llm_parameters": {"api_key": "sk-test", "temperature": 0.2, "top_k": 50}}

FULL_ANSWER = json.dumps({
    "usecases": [{"id": "face_recognition", "name": "Face Recognition", "outdoor": True}],
    "total_licenses": 1200,
    "requirements": ["FRS must support 1:1, 1:N and N:N matching.",
                     "Analytics shall run on GPU based servers."],
    "benchmarked_usecases": ["face_recognition"],
})


def reset(answer=FULL_ANSWER, delay=0.0):
    F._CACHE.clear()
    F._LOCKS.clear()
    F._TEXT_CACHE.clear()
    dspy.ChainOfThought.calls = 0
    dspy.ChainOfThought.answer = answer
    dspy.ChainOfThought.delay = delay
    dspy.LM.instances = []


def rule(settings=None):
    return F.AIOSv1PolicyRule("va-rfp-requirements", settings or {}, {})


def call(r, url="http://minio/rfp/patna.pdf", text="RFP BODY", **params):
    p = {"tool_model": MODEL}
    p.update(params)
    return r.eval(p, {"rfp_url": url, "rfp_text": text}, {})


# --- tests ------------------------------------------------------------------

def test_extracts_and_shapes_the_result():
    reset()
    out = call(rule())
    assert out["status"] == "ok", out
    assert out["cached"] is False
    assert out["total_licenses"] == 1200
    assert len(out["requirements"]) == 2
    assert out["usecases"][0]["id"] == "face_recognition"
    assert out["benchmarked_usecases"] == ["face_recognition"]


def test_second_caller_for_the_same_url_hits_the_cache():
    reset()
    first = call(rule())
    second = call(rule())          # a *different* instance, as the executor builds one per call
    assert first["cached"] is False and second["cached"] is True
    assert second["requirements"] == first["requirements"]
    assert dspy.ChainOfThought.calls == 1, "the second caller re-extracted"


def test_a_different_url_is_extracted_separately():
    reset()
    call(rule(), url="http://minio/rfp/patna.pdf")
    other = call(rule(), url="http://minio/rfp/chennai.pdf")
    assert other["cached"] is False
    assert dspy.ChainOfThought.calls == 2


def test_five_concurrent_callers_extract_once():
    """The real shape: five compliance agents start within seconds of each other."""
    reset(delay=0.4)
    results, errors = [], []

    def worker():
        try:
            results.append(call(rule()))
        except Exception as e:      # noqa: BLE001 - recorded and asserted on below
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.monotonic() - started

    assert not errors, errors
    assert len(results) == 5
    assert dspy.ChainOfThought.calls == 1, (
        f"{dspy.ChainOfThought.calls} extractions for one url -- the lock did not hold")
    assert sum(1 for r in results if r["cached"] is False) == 1, "more than one caller paid"
    assert all(r["requirements"] == results[0]["requirements"] for r in results), (
        "callers got different lists for the same RFP -- the denominator still moves")
    # One extraction of 0.4s, not five of them serialised.
    assert elapsed < 1.5, f"took {elapsed:.2f}s; callers look serialised behind separate extractions"


def test_a_waiter_never_returns_before_the_extraction_is_stored():
    """A waiter admitted to the lock must read the cache, not start its own pass."""
    reset(delay=0.3)
    order = []

    def first():
        call(rule())
        order.append("first-done")

    def second():
        time.sleep(0.05)            # ensure it arrives mid-extraction
        out = call(rule())
        order.append("second-done")
        assert out["cached"] is True, "the waiter extracted again instead of reusing"

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert order == ["first-done", "second-done"], order
    assert dspy.ChainOfThought.calls == 1


def test_concurrent_callers_on_different_urls_do_not_block_each_other():
    reset(delay=0.5)
    done = []

    def worker(url):
        call(rule(), url=url)
        done.append(url)

    threads = [threading.Thread(target=worker, args=(f"http://minio/rfp/{n}.pdf",))
               for n in ("a", "b", "c")]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.monotonic() - started
    assert len(done) == 3
    assert dspy.ChainOfThought.calls == 3
    assert elapsed < 1.2, f"took {elapsed:.2f}s; separate urls are sharing one lock"


def test_model_block_becomes_a_dspy_lm():
    reset()
    call(rule())
    lm = dspy.LM.instances[-1]
    assert lm.model == "openai/gpt-5.4-mini", lm.model
    assert lm.api_key == "sk-test"
    assert lm.kwargs.get("temperature") == 0.2
    assert "top_k" not in lm.kwargs, "top_k is not a valid OpenAI argument and would fail the call"
    assert "api_key" not in lm.kwargs


def test_gemini_block_maps_to_the_gemini_provider():
    reset()
    call(rule(), tool_model={"llm_block_id": "gemini:gemini-2.5-flash",
                             "llm_parameters": {"api_key": "k"}})
    assert dspy.LM.instances[-1].model == "gemini/gemini-2.5-flash"


def test_missing_model_block_fails_without_raising():
    reset()
    out = rule().eval({}, {"rfp_url": "http://minio/rfp/x.pdf", "rfp_text": "body"}, {})
    assert out["status"] == "extraction_failed"
    assert "tool_model" in out["error"]
    assert out["requirements"] == []


def test_missing_api_key_fails_without_raising():
    reset()
    out = call(rule(), tool_model={"llm_block_id": "openai:gpt-4o-mini", "llm_parameters": {}})
    assert out["status"] == "extraction_failed"
    assert "api_key" in out["error"]


def test_missing_url_is_reported_not_raised():
    reset()
    out = rule().eval({"tool_model": MODEL}, {}, {})
    assert out["status"] == "no_rfp_url"
    assert out["requirements"] == []


def test_a_failed_extraction_is_not_cached():
    """Caching a failure would poison the url for every later caller and every round."""
    reset(answer="not json at all")
    first = call(rule())
    assert first["status"] == "extraction_failed"
    dspy.ChainOfThought.answer = FULL_ANSWER
    second = call(rule())
    assert second["status"] == "ok" and second["cached"] is False
    assert len(second["requirements"]) == 2


def test_fenced_and_prose_wrapped_json_are_both_read():
    for wrapped in (f"```json\n{FULL_ANSWER}\n```",
                    f"Here is the extraction:\n{FULL_ANSWER}\nThat is all."):
        reset(answer=wrapped)
        out = call(rule())
        assert out["status"] == "ok", out
        assert len(out["requirements"]) == 2


def test_duplicate_requirements_are_collapsed():
    """A repeated clause would otherwise be judged twice and counted twice in total."""
    reset(answer=json.dumps({
        "usecases": [], "total_licenses": 0, "benchmarked_usecases": [],
        "requirements": ["FRS must support 1:1 matching.",
                         "frs must support 1:1   matching.",
                         "Accuracy shall not be less than 90%."]}))
    out = call(rule())
    assert len(out["requirements"]) == 2, out["requirements"]


def test_every_company_gets_an_identical_denominator():
    """The bug this function exists to fix: 0/16 for one bidder and 1/70 for another."""
    reset()
    totals = {c: len(call(rule())["requirements"]) for c in
              ("CamFaceSolution", "MultiFaceTech", "NewGenTech",
               "UltraVideoTech", "VideoProcTech")}
    assert len(set(totals.values())) == 1, totals
    assert dspy.ChainOfThought.calls == 1


def test_non_numeric_licence_count_does_not_raise():
    reset(answer=json.dumps({"usecases": [], "total_licenses": "twelve hundred",
                             "requirements": ["x"], "benchmarked_usecases": []}))
    out = call(rule())
    assert out["status"] == "ok" and out["total_licenses"] == 0


if __name__ == "__main__":
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok  {name}")
        except Exception as e:                      # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
