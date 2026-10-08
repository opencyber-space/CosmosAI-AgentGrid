"""A company's live use-case endpoint.

The RFP demands a live vendor bake-off -- "all vendors will be provided with a live
stream with similar Field of View to ensure common ground ... outcomes will be measured
and compared among all vendors to check the accuracy". This function is a company's
answer to that: the evaluator calls it once per sample image and compares the result
against a shared ground truth.

It exists to demonstrate live evaluation, not model quality. It performs no inference --
the image URL is accepted because that is what a real endpoint receives, and ignoring it
is honest about what this stand-in does. Its answers come from `endpoint_responses.json`,
packaged beside this file at build time from an uncommitted per-company file (see
functions/build.sh and functions/warmup.sh).

Nothing here is committed with the answers in it, and there is no fallback that invents
them: with no packaged file every image gets `default_verdict`, which is false. That
company then scores 0 on the endpoint dimension. Because the dimension is absolute
rather than ranked, 0 for everyone adds 0 to everyone's total and the live bake-off
simply drops out of the comparison -- where a default of true would hand all five a
perfect score and make a misconfiguration look like success.

One of these is registered per use case a company declares under
`live_endpoints.endpoints`, capped at `max_live_endpoints`.
"""
import json
import logging
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RESPONSES_FILE = os.path.join(HERE, "endpoint_responses.json")


def _load_responses():
    """The packaged answers, or {} when this endpoint was built without a source file."""
    if not os.path.exists(RESPONSES_FILE):
        logging.warning("va-usecase-endpoint: no %s in the package; every image will get "
                        "the default verdict", os.path.basename(RESPONSES_FILE))
        return {}
    try:
        with open(RESPONSES_FILE) as fh:
            return json.load(fh) or {}
    except Exception as e:                                          # noqa: BLE001
        # A malformed package must not take the endpoint down: it answers the default,
        # scores badly, and says why in the log.
        logging.error("va-usecase-endpoint: %s is unreadable (%s); using the default "
                      "verdict for every image", RESPONSES_FILE, e)
        return {}


# Read once per container rather than per call: the file cannot change under a running
# pod, and the evaluator makes ten calls per endpoint in a burst.
_RESPONSES = _load_responses()


class AIOSv1PolicyRule:

    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id
        self.settings = settings or {}
        self.parameters = parameters or {}

    def eval(self, parameters, input_data, context):
        input_data = input_data or {}

        verdicts = _RESPONSES.get("image_verdicts") or {}
        usecase = _RESPONSES.get("usecase") or self.settings.get("usecase", "")
        default_verdict = bool(_RESPONSES.get("default_verdict",
                                              self.settings.get("default_verdict", False)))

        name = input_data.get("image_name")
        if not name:
            # Fall back to the object name at the end of the URL. The evaluator always
            # sends image_name, but a caller poking the endpoint by hand may not.
            url = input_data.get("image_url") or ""
            name = url.rstrip("/").split("/")[-1] if url else ""

        if name in verdicts:
            result = bool(verdicts[name])
        else:
            logging.info(
                "%s: no packaged verdict for %r; using default %s",
                self.rule_id, name, default_verdict,
            )
            result = default_verdict

        # bool(), not the raw value: the evaluator compares identity against a boolean
        # ground truth, and a truthy string would silently score as wrong.
        return {"result": bool(result), "usecase": usecase, "image_name": name}
