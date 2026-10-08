"""How a company's live endpoint is named, and which ones it stands up.

Both sides of the round need this and must agree exactly: `functions/build_endpoints.py`
builds and uploads `va-uc-{company}-{usecase}` before the round, and the AI Compliance
Agent resolves that same id at bid time to put it on its bid. A mismatch is invisible
until the evaluator calls an id nobody registered and scores the company 0.

Deliberately dependency-free -- the build script runs outside the agent image.
"""
import os
import re

# Kubernetes object names cap at 63 characters, and AgentFunctions derives a deployment
# name from function_name.
MAX_FUNCTION_NAME = 63

# Bumped from 1.0 when the answers moved out of `function_settings` and into the code
# zip. A re-upload under the same id is not enough: the policies system resolves a
# function's artifact once and keeps serving it, so the registry held the new package
# (4a19989a, with endpoint_responses.json in it) while every deployment created from
# "va-uc-*:1.0-stable" was still fetching the previous artifact (eafcc714) and reading
# the answer key out of its settings. Deleting the function and the deployment did not
# dislodge it; only a new id does. va-bid-eval hit exactly this and was bumped to 1.1
# for the same reason.
#
# Read from the environment so the next bump does not need five agent images rebuilt.
# This one did: the agents were rebuilt while the endpoints were still 1.0, so every
# compliance agent asked the registry for "va-uc-*:1.0-stable", which upload.sh had just
# retired, and reported `live_endpoints: []` with "not found in registry" against a
# working set of 1.1 endpoints. With the version in the spec's parameters instead, the
# same change is a redeploy.
ENDPOINT_VERSION = os.environ.get("VA_ENDPOINT_VERSION") or "1.1"
ENDPOINT_RELEASE_TAG = os.environ.get("VA_ENDPOINT_RELEASE_TAG") or "stable"

# Ids the round no longer uses but the registry still holds. delete.sh clears them, so a
# deployment cannot be created from a stale one by accident.
RETIRED_VERSIONS = ("1.0-stable",)


def slug(text):
    """Lowercase, non-alphanumerics collapsed to '-', trimmed.

    Mirrors AgentFunctions._compose_deployment_name so a name built here stays valid
    wherever the registry uses it.
    """
    s = re.sub(r"[^a-z0-9-]", "-", str(text).lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def function_name_for(company_slug, usecase_id):
    name = f"va-uc-{slug(company_slug)}-{slug(usecase_id)}"
    if len(name) > MAX_FUNCTION_NAME:
        name = name[:MAX_FUNCTION_NAME].rstrip("-")
    return name


def function_id_for(company_slug, usecase_id, version=ENDPOINT_VERSION,
                    release_tag=ENDPOINT_RELEASE_TAG):
    return f"{function_name_for(company_slug, usecase_id)}:{version}-{release_tag}"


def declared_endpoints(config):
    """The use cases this company stands up, honouring its own cap.

    `endpoints` says which; `max_live_endpoints` caps how many, so every company brings
    the same number to the bake-off and none can win by answering more questions than
    its rivals.
    """
    live = (config or {}).get("live_endpoints") or {}
    declared = [str(u) for u in (live.get("endpoints") or [])]
    cap = live.get("max_live_endpoints")
    return declared[:cap] if isinstance(cap, int) and cap >= 0 else declared
