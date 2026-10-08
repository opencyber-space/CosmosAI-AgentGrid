"""Local checks for the use-case endpoint, per contracts/usecase-endpoint-function.md.

The answers no longer arrive in `function_settings`; they are packaged beside the code
as endpoint_responses.json by functions/build_endpoints.py, from an uncommitted
per-company file. These tests write that file, import the module fresh so it re-reads it,
and delete it again -- the same lifecycle the build has.

Run from this directory:  ../../../venv/bin/python test.py
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.join(HERE, "function", "code")
PACKAGED = os.path.join(CODE_DIR, "endpoint_responses.json")

RESPONSES = {
    "company": "CamFaceSolution",
    "usecase": "face_recognition",
    "default_verdict": False,
    "image_verdicts": {"face_01.png": True, "face_02.png": False, "face_03.png": True},
}


def load(responses=RESPONSES):
    """The endpoint as it would come out of a package carrying `responses`.

    The module reads the file once at import, because the file cannot change under a
    running pod -- so a test that changes it has to re-import.
    """
    if responses is None:
        if os.path.exists(PACKAGED):
            os.remove(PACKAGED)
    else:
        with open(PACKAGED, "w") as fh:
            json.dump(responses, fh)
    sys.path.insert(0, CODE_DIR)
    try:
        module = importlib.import_module("function")
        module = importlib.reload(module)
    finally:
        sys.path.remove(CODE_DIR)
        if os.path.exists(PACKAGED):
            os.remove(PACKAGED)
    return module.AIOSv1PolicyRule


def rule(responses=RESPONSES, settings=None):
    cls = load(responses)
    return cls("va-uc-camfacesolution-face-recognition:1.0-stable",
               settings if settings is not None else {"usecase": "face_recognition",
                                                      "default_verdict": False}, {})


def test_packaged_name_returns_packaged_verdict():
    r = rule()
    assert r.eval({}, {"image_name": "face_01.png"}, {})["result"] is True
    assert r.eval({}, {"image_name": "face_02.png"}, {})["result"] is False


def test_unpackaged_name_returns_default():
    assert rule().eval({}, {"image_name": "unknown.png"}, {})["result"] is False


def test_no_packaged_file_answers_false_to_everything():
    """The point of the whole change: a company with no answers scores 0, not 100.

    False for every image is 0 correct out of 20, and the endpoint dimension is absolute
    rather than ranked -- so 0 for everyone adds 0 to everyone's total and the live
    bake-off drops out of the ranking. A default of true would instead hand all five a
    perfect score and make a missing file look like success.
    """
    r = rule(responses=None)
    for image in ("face_01.png", "face_02.png", "anything.png"):
        assert r.eval({}, {"image_name": image}, {})["result"] is False


def test_a_missing_file_does_not_take_the_endpoint_down():
    out = rule(responses=None).eval({}, {"image_name": "face_01.png"}, {})
    assert out == {"result": False, "usecase": "face_recognition", "image_name": "face_01.png"}


def test_falls_back_to_url_basename():
    """The evaluator always sends image_name; a hand-rolled call may not."""
    out = rule().eval({}, {"image_url": "http://minio:9000/va-bidding-eval/eval/face_01.png"}, {})
    assert out["image_name"] == "face_01.png"
    assert out["result"] is True


def test_result_is_a_real_boolean():
    """A truthy string would compare unequal to a boolean ground truth and score wrong."""
    out = rule(dict(RESPONSES, image_verdicts={"a.png": "yes"})).eval(
        {}, {"image_name": "a.png"}, {})
    assert out["result"] is True and isinstance(out["result"], bool)


def test_empty_input_does_not_raise():
    out = rule().eval({}, {}, {})
    assert out["result"] is False and out["image_name"] == ""


def test_usecase_is_echoed_from_the_package():
    assert rule().eval({}, {"image_name": "face_01.png"}, {})["usecase"] == "face_recognition"


def test_settings_still_name_the_usecase_when_no_file_was_packaged():
    """`function_settings` keeps the use case and the default -- but never the answers."""
    r = rule(responses=None, settings={"usecase": "crowd_density", "default_verdict": False})
    assert r.eval({}, {"image_name": "face_01.png"}, {})["usecase"] == "crowd_density"


def test_the_answers_never_sit_in_the_tree_after_a_build():
    """build_endpoints.py deletes the packaged file; nothing may leave one behind."""
    rule()
    assert not os.path.exists(PACKAGED), f"{PACKAGED} was left in the source tree"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("\nva-usecase-endpoint:",
          json.dumps(rule().eval({}, {"image_name": "face_03.png"}, {})))
