"""Reading the RFP.

The RFP travels as a URL, never as inlined text: the submission script uploads it to
MinIO and puts only the reference on the task, and every agent that needs it downloads
and reads it itself.

The supplied documents are genuine tender extracts, not prepared fixtures -- the Patna
volume is over a thousand lines of numbered clauses, tables and KPI criteria. Nothing
here parses requirements out of that. Text extraction is all this module does; deciding
what the RFP *asks for* is the agents' job, done by an LLM over this text, so the example
keeps working when a different RFP is dropped in.

`pdfplumber` is used rather than a lighter reader because the qualification criteria that
matter here -- the benchmarking-certificate clause, the minimum camera-licence count --
sit inside table cells, and layout-preserving extraction is what keeps them readable.
"""
import logging
import os
import re
import tempfile

import pdfplumber

from .minio_store import MinioStore, parse_url

log = logging.getLogger(__name__)

# Extracted text keyed by URL. Six agents share a pod in some deployments, and the
# same agent is called once per stage, so without this the same PDF is parsed
# repeatedly for no reason.
_TEXT_CACHE = {}


def _download(url, store=None):
    """Fetch the PDF to a temp path, over MinIO's internal address."""
    bucket, object_name = parse_url(url)
    if not bucket:
        raise ValueError(f"RFP url is not a MinIO object url: {url!r}")
    store = store or MinioStore()
    data = store.get_bytes(bucket, object_name)
    fd, path = tempfile.mkstemp(suffix=".pdf", prefix="rfp-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    log.info("downloaded RFP %s/%s (%d bytes)", bucket, object_name, len(data))
    return path


def text(url, store=None):
    """The RFP's full text, extracted once per URL and cached.

    Pages that yield nothing are skipped rather than contributing empty strings, so a
    document with image-only pages still produces usable text for the pages that have
    a text layer.
    """
    if url in _TEXT_CACHE:
        return _TEXT_CACHE[url]

    path = _download(url, store)
    try:
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text(layout=True)
                if extracted:
                    pages.append(extracted)
        body = "\n".join(pages)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if not body.strip():
        raise ValueError(
            f"RFP at {url} yielded no text -- it may be a scanned document with no text layer"
        )

    log.info("extracted %d characters of RFP text from %s", len(body), url)
    _TEXT_CACHE[url] = body
    return body


def sections(url, pattern, store=None, context_lines=40):
    """Lines matching `pattern`, each with the lines that follow it.

    A narrowing aid for agents that only care about part of a long document -- the
    sizing agent does not need the signage specifications. It returns raw text for the
    model to read; it does not decide what any clause means.
    """
    body = text(url, store)
    lines = body.splitlines()
    regex = re.compile(pattern, re.IGNORECASE)
    out = []
    for i, line in enumerate(lines):
        if regex.search(line):
            out.append("\n".join(lines[i:i + context_lines]))
    return out


def excerpt(url, max_chars=120000, store=None):
    """The RFP text, truncated to fit a model's context window.

    Truncation is explicit and logged rather than silent: an agent reasoning over a
    quietly clipped document would produce a confidently wrong compliance report.
    """
    body = text(url, store)
    if len(body) <= max_chars:
        return body
    log.warning(
        "RFP text is %d chars; truncating to %d for the model. "
        "Use sections() to target the relevant clauses instead.",
        len(body), max_chars,
    )
    return body[:max_chars] + "\n\n[... RFP truncated ...]"


def clear_cache():
    """Drop cached text. Used by tests; agents have no reason to call it."""
    _TEXT_CACHE.clear()
