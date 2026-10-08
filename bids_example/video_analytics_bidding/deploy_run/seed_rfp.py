"""Upload the RFP to MinIO and print its reference.

The RFP travels as a URL, never as inlined text. The task carries only the reference;
every agent that needs the document downloads and reads it itself. That is what keeps
the RFP *input data* rather than embedded knowledge -- swap the file and the round
changes, with no edit to any agent.

Two real tender extracts ship with the example:

  patna (default)  Patna Smart City MSI. Carries the bars pre-qualification needs --
                   "The Vendor should have any performance benchmarking certificate.
                   NIST certificate will be preferred" and "OEM of VMS should have
                   supplied at least 10,000 cameras Licenses". This is the round the
                   example demonstrates.

  chennai          A shorter Video Analytics feature extract with no certification or
                   track-record clauses. Useful for showing that a different RFP drops
                   in cleanly -- but pre-qualification has nothing to reject against,
                   so the round resolves differently.

Both are selected inline rather than from .env, because which tender you seed is a
property of the run, not of the deployment:

    ./venv/bin/python deploy_run/seed_rfp.py                 patna, the default
    RFP=chennai ./venv/bin/python deploy_run/seed_rfp.py     the other one
    SEED_FORCE=1 ./venv/bin/python deploy_run/seed_rfp.py    re-upload over what
                                                             MinIO already holds

One manual step in MinIO, once per cluster: set **va-bidding-rfp**, **va-bidding-eval**
and **va-bidding-docs** to anonymous *download* (read-only) access. Everything this
example produces travels as a URL rather than as inlined bytes -- the RFP on the task,
the sample images on the bid job, the commercial and sizing workbooks on each bid --
and those URLs are opened by things holding no MinIO credentials: a reviewer clicking
through the dashboard, and anyone reading the bid record afterwards. Without the
policy the objects upload fine and every link 403s.

    MinIO Console -> Buckets -> <bucket> -> Anonymous -> Add Access Rule
    Prefix: /     Access: readonly

Prints one JSON line on stdout for va_bidding_request.sh:
    {"bucket", "object", "url", "rfp_name", "rfp_key"}
Progress goes to stderr.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "nodes")))

from common.minio_store import RFP_BUCKET, MinioStore, external_address  # noqa: E402

RFPS = {
    "patna": {
        "file": "RFP_Extract_Patna.pdf",
        "name": "Patna Smart City - Master System Integrator, Integrated Smart Solutions",
        "note": "primary round; states the certification and supplied-licence bars",
    },
    "chennai": {
        "file": "RFP_Chennai_Extract.pdf",
        "name": "Chennai Command & Control Centre - Video Analytics scope",
        "note": "alternative RFP; no certification or track-record clauses",
    },
}


def log(msg):
    print(f"[seed_rfp] {msg}", file=sys.stderr, flush=True)


def main():
    key = (os.environ.get("RFP") or "patna").strip().lower()
    if key not in RFPS:
        log(f"unknown RFP {key!r}; choose one of {sorted(RFPS)}")
        return 1

    entry = RFPS[key]
    path = os.path.join(HERE, entry["file"])
    if not os.path.exists(path):
        log(f"RFP not found at {path}")
        return 1

    log(f"using {key}: {entry['file']} ({entry['note']})")

    # Run from a developer's machine, so connect on the external address rather than
    # the in-cluster one the agents use.
    store = MinioStore(connect_address=external_address())
    object_name = f"rfp/{entry['file']}"

    if store.exists(RFP_BUCKET, object_name) and os.environ.get("SEED_FORCE") != "1":
        log(f"{object_name} already present (SEED_FORCE=1 to re-upload)")
        ref = store.ref(RFP_BUCKET, object_name)
    else:
        ref = store.put_file(path, RFP_BUCKET, object_name, content_type="application/pdf")
        log(f"uploaded {object_name} ({os.path.getsize(path)} bytes)")

    ref = dict(ref)
    ref["rfp_name"] = entry["name"]
    ref["rfp_key"] = key
    log(f"url {ref['url']}")
    print(json.dumps(ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
