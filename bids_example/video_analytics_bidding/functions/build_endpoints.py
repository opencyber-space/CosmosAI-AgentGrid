"""Build one live-endpoint package per company per use case, before the round.

These used to be built and uploaded from inside the AI Compliance Agent, mid-bid. That
put a registry upload *and* a first-ever deployment creation inside the bidding window,
which is the cold start that broke bid job 9db948a0, and `warmup.sh` could not cover
them because they did not exist until the round was already running. They are built here
instead, uploaded by upload.sh and warmed by warmup.py; the agent still chooses which of
its endpoints to put on a bid from the RFP it just read, it simply no longer publishes.

Which use cases a company stands up is committed, in `live_endpoints.endpoints` of its
config.yaml, capped by `max_live_endpoints`. What those endpoints answer is not: it comes
from verdicts/<slug>_verdicts.yaml, which is gitignored. The file is packaged into
`code/endpoint_responses.json` for the duration of the zip and deleted immediately after,
so it never lingers in the tree -- and, because it rides in the code rather than in
`function_settings`, `GET /functions/{id}` no longer serves the answer key either.

A company with no such file still gets a package. Its endpoint then answers false to
every image and scores 0, which is the safe direction: the endpoint dimension is
absolute, so 0 for everyone adds 0 to everyone's total and drops out of the comparison.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(EXAMPLE_DIR, "nodes"))

from common.endpoint_names import (ENDPOINT_RELEASE_TAG, ENDPOINT_VERSION,  # noqa: E402
                                   declared_endpoints, function_id_for,
                                   function_name_for)

TEMPLATE_DIR = os.path.join(HERE, "va-usecase-endpoint")
CODE_DIR = os.path.join(TEMPLATE_DIR, "function", "code")
VERDICTS_DIR = os.path.join(TEMPLATE_DIR, "verdicts")
BUILD_DIR = os.path.join(TEMPLATE_DIR, "build")
NODES_DIR = os.path.join(EXAMPLE_DIR, "nodes")

# The file the endpoint reads at run time. JSON, not YAML: the endpoint is stdlib-only
# today, and adding PyYAML would put a pip install in front of ten container starts that
# warmup.sh has to wait through. The file a person writes stays YAML.
PACKAGED_NAME = "endpoint_responses.json"

VERSION, RELEASE_TAG = ENDPOINT_VERSION, ENDPOINT_RELEASE_TAG


def log(msg):
    print(f"[build-endpoints] {msg}")


def companies():
    for name in sorted(os.listdir(NODES_DIR)):
        config = os.path.join(NODES_DIR, name, "config.yaml")
        if os.path.isfile(config):
            yield name, yaml.safe_load(open(config)) or {}


def responses_for(company_slug):
    """The uncommitted answers for this company, or None when the file is absent."""
    path = os.path.join(VERDICTS_DIR, f"{company_slug}_verdicts.yaml")
    if not os.path.exists(path):
        return None
    loaded = yaml.safe_load(open(path)) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a mapping of use case -> image -> bool")
    return loaded


def package(company, company_slug, usecase_id, image_verdicts, default_verdict):
    """One outer zip: function.json + function.zip, where function.zip holds code/."""
    name = function_name_for(company_slug, usecase_id)

    manifest = json.load(open(os.path.join(TEMPLATE_DIR, "function.json")))
    manifest["function_name"] = name
    manifest["function_version"] = VERSION
    manifest["function_release_tag"] = RELEASE_TAG
    # Stateful, so the registry stands the endpoint up as a deployment instead of
    # spawning a Kubernetes job per call. As jobs, twenty probes cost ~7 seconds each and
    # blew OpenArcade's 60-second read timeout twice, which leaves the round unevaluated
    # for good because it does not retry.
    manifest["is_stateful"] = True
    # No image_verdicts here on purpose -- the answers travel inside the code zip.
    manifest["function_settings"] = {"usecase": usecase_id,
                                     "default_verdict": bool(default_verdict)}
    manifest.setdefault("function_metadata", {})["company"] = company
    manifest["function_metadata"].pop("note", None)      # the template's caveat, not this one's

    packaged = os.path.join(CODE_DIR, PACKAGED_NAME)
    staged = tempfile.mkdtemp()
    try:
        with open(packaged, "w") as fh:
            json.dump({"company": company, "usecase": usecase_id,
                       "default_verdict": bool(default_verdict),
                       "image_verdicts": {k: bool(v) for k, v in (image_verdicts or {}).items()}},
                      fh, indent=2, sort_keys=True)

        subprocess.run(["zip", "-qr", os.path.join(staged, "function.zip"), "code/",
                        "-x", "*__pycache__*", "-x", "*.pyc"],
                       cwd=os.path.join(TEMPLATE_DIR, "function"), check=True)
    finally:
        # Out of the tree the moment the zip has it, whatever happened above. Leaving it
        # behind would put the answers back where the team asked for them not to be, and
        # a later `build.sh` for some other function would sweep them into its package.
        if os.path.exists(packaged):
            os.remove(packaged)

    try:
        with open(os.path.join(staged, "function.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)
        out = os.path.join(BUILD_DIR, f"{name}.zip")
        if os.path.exists(out):
            os.remove(out)
        subprocess.run(["zip", "-q", out, "function.json", "function.zip"],
                       cwd=staged, check=True)
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    return name, out


def endpoint_names():
    """Every `va-uc-*` name this repo's configs imply, in build order.

    delete.sh and warmup.py both ask for this rather than deriving it themselves: three
    places guessing at the same naming rule is how a deployment gets left running with
    the previous round's answers in it.
    """
    names = []
    for company, config in companies():
        for usecase_id in declared_endpoints(config):
            names.append(function_name_for(company.lower(), usecase_id))
    return names


def endpoint_ids():
    """The same list as function ids, version included -- what warmup.py calls."""
    ids = []
    for company, config in companies():
        for usecase_id in declared_endpoints(config):
            ids.append(function_id_for(company.lower(), usecase_id))
    return ids


def main():
    if "--list" in sys.argv[1:]:
        print("\n".join(endpoint_names()))
        return 0

    os.makedirs(BUILD_DIR, exist_ok=True)
    for stale in os.listdir(BUILD_DIR):
        if stale.endswith(".zip"):
            os.remove(os.path.join(BUILD_DIR, stale))

    built, unsourced = 0, []
    for company, config in companies():
        company_slug = company.lower()
        usecases = declared_endpoints(config)
        if not usecases:
            log(f"{company}: no live_endpoints.endpoints declared; nothing to build")
            continue
        default_verdict = ((config.get("live_endpoints") or {}).get("default_verdict") or False)

        responses = responses_for(company_slug)
        if responses is None:
            unsourced.append(company)

        for usecase_id in usecases:
            verdicts = (responses or {}).get(usecase_id) or {}
            name, out = package(company, company_slug, usecase_id, verdicts, default_verdict)
            built += 1
            log(f"{name}: {len(verdicts)} verdict(s) -> {os.path.relpath(out, HERE)}")

    if unsourced:
        log("")
        log(f"No verdicts file for: {', '.join(unsourced)}.")
        log(f"Those endpoints answer {False} to every image and score 0 -- see warmup.sh "
            f"for the format if that is not what you wanted.")
    log(f"Built {built} endpoint package(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
