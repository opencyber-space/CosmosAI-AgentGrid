"""Local checks for the evaluator, per contracts/evaluator-function.md.

Run from this directory:  ../../../venv/bin/python test.py

The live endpoint calls are made through a fake AgentFunctions, so these run with no
cluster. The fake honours the same contract as the real one -- `add()` before `call()`,
`shutdown()` at the end -- so a change that breaks that order fails here.
"""
import json

from function.code.function import AIOSv1PolicyRule
from function.code import va_bid_utils as V

GROUND_TRUTH = {
    "face_01.png": True, "face_02.png": False, "face_03.png": True, "face_04.png": True,
    "face_05.png": False, "face_06.png": True, "face_07.png": False, "face_08.png": True,
    "face_09.png": True, "face_10.png": False,
}
SAMPLE_IMAGES = [
    {"name": n, "url": f"http://minio/va-bidding-eval/eval/{n}", "ground_truth": gt}
    for n, gt in GROUND_TRUTH.items()
]


class FakeAgentFunctions:
    """Stands in for the registry. `verdicts` maps function_id -> {image: bool}."""

    def __init__(self, verdicts, unresolvable=(), raises_on=(), never_answers=()):
        self.verdicts = verdicts
        self.unresolvable = set(unresolvable)
        self.raises_on = set(raises_on)
        # (function_id, image_name) pairs whose handle never produces a result -- the
        # registry being slow, which is what the probe budget exists to survive.
        self.never_answers = set(never_answers)
        self.added = set()
        self.calls = 0
        self.shutdown_called = False
        self.removed = []

    def add(self, function_id):
        if function_id in self.unresolvable:
            raise RuntimeError(f"no such function {function_id}")
        self.added.add(function_id)

    def call(self, function_id, input_data):
        if function_id not in self.added:
            raise ValueError(f"Function '{function_id}' not found locally. Add it first.")
        self.calls += 1
        name = input_data.get("image_name")
        if (function_id, name) in self.raises_on:
            raise RuntimeError("endpoint unreachable")
        return {"result": bool(self.verdicts.get(function_id, {}).get(name, False))}

    def execute_async(self, function_id, input_data, **kwargs):
        """The real one queues onto a worker pool and hands back a ResultHandle."""
        if function_id not in self.added:
            raise ValueError(f"Function '{function_id}' not found locally. Add it first.")
        name = input_data.get("image_name")
        outer = self

        class Handle:
            def wait(self, timeout=None):
                if (function_id, name) in outer.never_answers:
                    raise TimeoutError("no result within the probe budget")
                return outer.call(function_id, input_data)

        return Handle()

    def remove(self, function_id, *, remove_deployment=False):
        self.removed.append((function_id, remove_deployment))
        return True

    def shutdown(self, wait=True):
        self.shutdown_called = True


def bid(subject, company, budget, sizing, met, endpoints=(), status="submitted", rejected=False):
    data = {"bid_status": status, "company": company, "credentials": {}}
    if status != "declined":
        data.update({"total_budget": budget, "sizing": sizing,
                     "compliance": {"met": met, "total": 20},
                     "live_endpoints": list(endpoints)})
    if rejected:
        data["bid_rejected"] = True
    return {"bid_subject_id": subject, "bid_data": data}


CAM_FR = "va-uc-camfacesolution-face-recognition:1.0-stable"
CAM_CM = "va-uc-camfacesolution-crowd-multiface:1.0-stable"
ULT_FR = "va-uc-ultravideotech-face-recognition:1.0-stable"
ULT_CM = "va-uc-ultravideotech-crowd-multiface:1.0-stable"

# Verdicts lifted from the two companies' config.yaml: 14/20 and 18/20.
VERDICTS = {
    CAM_FR: {"face_01.png": True, "face_02.png": True, "face_03.png": True, "face_04.png": True,
             "face_05.png": True, "face_06.png": True, "face_07.png": True, "face_08.png": True,
             "face_09.png": True, "face_10.png": False},
    CAM_CM: {"face_01.png": True, "face_02.png": False, "face_03.png": False, "face_04.png": True,
             "face_05.png": False, "face_06.png": False, "face_07.png": False, "face_08.png": True,
             "face_09.png": True, "face_10.png": True},
    ULT_FR: {"face_01.png": True, "face_02.png": False, "face_03.png": True, "face_04.png": True,
             "face_05.png": False, "face_06.png": True, "face_07.png": True, "face_08.png": True,
             "face_09.png": True, "face_10.png": False},
    ULT_CM: {"face_01.png": True, "face_02.png": False, "face_03.png": True, "face_04.png": True,
             "face_05.png": False, "face_06.png": True, "face_07.png": False, "face_08.png": True,
             "face_09.png": True, "face_10.png": True},
}


def full_round():
    return [
        bid("camfacesolution-bid-manager", "CamFaceSolution", 48_500_000,
            {"cpu_cores": 640, "ram_gb": 2560, "disk_gb": 92000, "gpu_count": 40}, 15,
            [{"usecase": "face_recognition", "function_id": CAM_FR, "verified": True},
             {"usecase": "crowd_multiface", "function_id": CAM_CM, "verified": True}]),
        bid("multifacetech-bid-manager", "MultiFaceTech", None, None, None, status="declined"),
        bid("newgentech-bid-manager", "NewGenTech", 31_000_000,
            {"cpu_cores": 780, "ram_gb": 3100, "disk_gb": 105000, "gpu_count": 52}, 14,
            [], rejected=True),
        bid("ultravideotech-bid-manager", "UltraVideoTech", 52_000_000,
            {"cpu_cores": 520, "ram_gb": 2080, "disk_gb": 74000, "gpu_count": 28}, 16,
            [{"usecase": "face_recognition", "function_id": ULT_FR, "verified": True},
             {"usecase": "crowd_multiface", "function_id": ULT_CM, "verified": True}]),
        bid("videoproctech-bid-manager", "VideoProcTech", None, None, None, status="declined"),
    ]


def run(bids, fake=None, settings=None):
    rule = AIOSv1PolicyRule("va-bid-eval:1.2-stable", settings or {}, {})
    job = {"bid_job_id": "job-1",
           "bid_job_metadata": {"evaluation": {"sample_images": SAMPLE_IMAGES}}}
    fake = fake or FakeAgentFunctions(VERDICTS)
    # Inject the fake the same way the real path constructs one.
    rule._open_registry = lambda bid_job: (fake, True)
    return rule.eval({}, {"bid_job": job, "bids": bids}, {}), fake


# --- filtering ---

def test_five_bids_reduce_to_two_survivors():
    out, _ = run(full_round())
    assert set(out["result_data"]["scores"]) == {
        "camfacesolution-bid-manager", "ultravideotech-bid-manager"}
    why = {e["subject_id"]: e["why"] for e in out["result_data"]["excluded"]}
    assert why == {"multifacetech-bid-manager": "declined",
                   "videoproctech-bid-manager": "declined",
                   "newgentech-bid-manager": "bid_rejected"}


def test_rejected_bid_cannot_win_even_when_cheapest():
    """NewGenTech is by far the cheapest; being rejected must keep it out entirely."""
    out, _ = run(full_round())
    assert out["winner_subject_id"] != "newgentech-bid-manager"
    assert "newgentech-bid-manager" not in out["result_data"]["scores"]


def test_all_declined_returns_no_valid_bids():
    bids = [bid("a", "A", None, None, None, status="declined"),
            bid("b", "B", None, None, None, status="declined")]
    out, _ = run(bids)
    assert out["status"] == "no_valid_bids"
    assert "winner_subject_id" not in out


# --- the demonstrated round ---

def test_the_round_resolves_as_designed():
    out, _ = run(full_round())
    scores = out["result_data"]["scores"]
    cam = scores["camfacesolution-bid-manager"]
    ult = scores["ultravideotech-bid-manager"]
    assert (cam["budget"], cam["sizing"], cam["compliance"], cam["endpoint"]) == (75.0, 25.0, 75.0, 70.0)
    assert (ult["budget"], ult["sizing"], ult["compliance"], ult["endpoint"]) == (25.0, 75.0, 80.0, 90.0)
    assert cam["total"] == 245.0 and ult["total"] == 270.0
    assert out["winner_subject_id"] == "ultravideotech-bid-manager"
    assert out["result_data"]["tie_break"] is None


def test_winner_is_a_topic_listener():
    """SC-003a: topic-based participation must be able to decide the round."""
    out, _ = run(full_round())
    assert out["result_data"]["scores"][out["winner_subject_id"]]["company"] == "UltraVideoTech"


# --- percentile maths ---

def test_percentile_matches_the_worked_example():
    assert V.get_percentile_ranks([10, 3, 8, 5, 8]) == [90.0, 10.0, 50.0, 30.0, 50.0]


def test_sizing_weights_stay_in_range_and_apply():
    out, _ = run(full_round())
    for entry in out["result_data"]["scores"].values():
        assert 0.0 <= entry["sizing"] <= 100.0
    assert out["result_data"]["weights"] == {"cpu": 0.2, "ram": 0.2, "disk": 0.1, "gpu": 0.5}


def test_custom_weights_are_honoured():
    rule = AIOSv1PolicyRule("x", {}, {})
    fake = FakeAgentFunctions(VERDICTS)
    rule._open_registry = lambda bid_job: (fake, True)
    job = {"bid_job_id": "j", "bid_job_metadata": {"evaluation": {
        "sample_images": SAMPLE_IMAGES, "weights": {"cpu": 1.0, "ram": 0, "disk": 0, "gpu": 0}}}}
    out = rule.eval({}, {"bid_job": job, "bids": full_round()}, {})
    # cpu alone: Ultra is leaner (520 vs 640), so it takes the whole dimension.
    assert out["result_data"]["scores"]["ultravideotech-bid-manager"]["sizing"] == 75.0


# --- endpoint robustness ---

def test_endpoint_call_failure_counts_wrong_not_fatal():
    fake = FakeAgentFunctions(VERDICTS, raises_on={(ULT_FR, "face_01.png"), (ULT_FR, "face_03.png")})
    out, _ = run(full_round(), fake)
    assert out["status"] == "resolved"
    # Ultra loses two of its eighteen correct answers.
    assert out["result_data"]["scores"]["ultravideotech-bid-manager"]["endpoint"] == 80.0


def test_slow_endpoint_counts_wrong_rather_than_stranding_the_round():
    """A probe that never answers must not hold the evaluator past its caller's timeout.

    OpenArcade calls this evaluator with a 60-second read timeout and does not retry: a
    round it gives up on stays unevaluated for good. That is exactly how a real round
    was lost -- twenty serial probes at ~7s each against a 60s budget, then
    "Evaluator function failed ... Read timed out" in the Orcade log. Returning a
    harsher score beats returning nothing.
    """
    fake = FakeAgentFunctions(VERDICTS, never_answers={(ULT_FR, "face_01.png"),
                                                       (ULT_FR, "face_02.png")})
    out, _ = run(full_round(), fake)
    assert out["status"] == "resolved", "a slow endpoint must not stop the round resolving"
    # The two unanswered images count wrong, exactly as a raised call would.
    assert out["result_data"]["scores"]["ultravideotech-bid-manager"]["endpoint"] == 80.0


def test_probes_are_dispatched_before_any_is_collected():
    """Serial probing is what blew the caller's timeout; the calls must overlap."""
    fake = FakeAgentFunctions(VERDICTS)
    order = []
    original_async, original_call = fake.execute_async, fake.call

    def traced_async(function_id, input_data, **kwargs):
        order.append(("dispatch", input_data.get("image_name")))
        return original_async(function_id, input_data, **kwargs)

    def traced_call(function_id, input_data):
        order.append(("collect", input_data.get("image_name")))
        return original_call(function_id, input_data)

    fake.execute_async, fake.call = traced_async, traced_call
    out, _ = run(full_round(), fake)
    assert out["status"] == "resolved"

    # Within an endpoint, every dispatch must precede the first collection.
    first_collect = next(i for i, (kind, _) in enumerate(order) if kind == "collect")
    dispatches_before = sum(1 for kind, _ in order[:first_collect] if kind == "dispatch")
    assert dispatches_before > 1, (
        f"probes were collected one at a time ({dispatches_before} dispatched before the "
        "first collection) -- that is the serial behaviour that lost a round")


def test_unresolvable_endpoint_counts_every_image_wrong():
    fake = FakeAgentFunctions(VERDICTS, unresolvable={CAM_FR})
    out, _ = run(full_round(), fake)
    assert out["status"] == "resolved"
    # CamFaceSolution keeps only its crowd_multiface answers: 7 of 20.
    assert out["result_data"]["scores"]["camfacesolution-bid-manager"]["endpoint"] == 35.0


def test_endpoint_deployments_are_released_after_scoring():
    """Each endpoint is a live pod for the round; nothing else reclaims it.

    The endpoints are stateful so the evaluator calls a deployment that is already up
    rather than spawning a Kubernetes job per image -- twenty of those cost ~7s each and
    blew OpenArcade's 60s read timeout. The price is that the pods outlive the bid
    unless this function gives them back.
    """
    fake = FakeAgentFunctions(VERDICTS)
    out, _ = run(full_round(), fake)
    assert out["status"] == "resolved"
    released = {fid for fid, with_deployment in fake.removed if with_deployment}
    assert CAM_FR in released and ULT_FR in released, (
        f"deployments left running: released only {released}")


def test_deployments_are_released_even_when_an_endpoint_fails():
    """A failed probe must not leak the pod it was probing."""
    fake = FakeAgentFunctions(VERDICTS, raises_on={(ULT_FR, "face_01.png")})
    out, _ = run(full_round(), fake)
    assert out["status"] == "resolved"
    assert ULT_FR in {fid for fid, dep in fake.removed if dep}


def test_company_with_no_endpoints_scores_zero_not_excluded():
    bids = full_round()
    bids[0]["bid_data"]["live_endpoints"] = []
    out, _ = run(bids)
    assert out["result_data"]["scores"]["camfacesolution-bid-manager"]["endpoint"] == 0.0
    assert "camfacesolution-bid-manager" in out["result_data"]["scores"]


def test_add_is_called_before_call():
    """The real AgentFunctions raises ValueError otherwise."""
    _, fake = run(full_round())
    assert fake.added == {CAM_FR, CAM_CM, ULT_FR, ULT_CM}
    assert fake.calls == 40           # 2 companies x 2 endpoints x 10 images


def test_shutdown_is_always_called():
    """AgentFunctions starts a worker pool; without this the job never exits."""
    _, fake = run(full_round())
    assert fake.shutdown_called is True


def test_no_sample_images_scores_endpoint_zero_for_everyone():
    rule = AIOSv1PolicyRule("x", {}, {})
    out = rule.eval({}, {"bid_job": {"bid_job_id": "j"}, "bids": full_round()}, {})
    assert out["status"] == "resolved"
    for entry in out["result_data"]["scores"].values():
        assert entry["endpoint"] == 0.0


# --- ties and junk ---

def test_tie_breaks_on_budget_then_subject_id():
    assert V.pick_winner({"a": {"total": 200.0, "total_budget": 9},
                          "b": {"total": 200.0, "total_budget": 5}})[0] == "b"
    winner, reason = V.pick_winner({"zz": {"total": 200.0, "total_budget": 5},
                                    "aa": {"total": 200.0, "total_budget": 5}})
    assert winner == "aa" and "subject id" in reason


def test_non_numeric_budget_sinks_that_company_without_raising():
    bids = full_round()
    bids[0]["bid_data"]["total_budget"] = "4.85 Cr"
    out, _ = run(bids)
    assert out["status"] == "resolved"
    assert out["result_data"]["scores"]["camfacesolution-bid-manager"]["budget"] == 25.0


def test_missing_sizing_sinks_that_dimension_without_raising():
    bids = full_round()
    del bids[0]["bid_data"]["sizing"]
    out, _ = run(bids)
    assert out["status"] == "resolved"


def test_zero_compliance_total_does_not_divide_by_zero():
    bids = full_round()
    bids[0]["bid_data"]["compliance"] = {"met": 5, "total": 0}
    out, _ = run(bids)
    assert out["result_data"]["scores"]["camfacesolution-bid-manager"]["compliance"] == 0.0


def test_empty_and_garbage_input_do_not_raise():
    rule = AIOSv1PolicyRule("x", {}, {})
    for bad in ({}, {"bids": []}, {"bids": [{}]}, None):
        out = rule.eval({}, bad, {})
        assert isinstance(out, dict) and "status" in out



def test_a_broken_his_config_does_not_strand_the_round():
    """Observability must never cost a round.

    OpenArcade waits on the evaluator with no timeout, so an exception raised while
    reading a misshapen HIS_CONFIG would leave the round unresolved for good.
    """
    out, _ = run(full_round(), settings={"HIS_CONFIG": "not-a-dict"})
    assert out["status"] == "resolved", out
    assert out["winner_subject_id"] == "ultravideotech-bid-manager", out


def test_the_endpoint_percentage_records_the_tally_behind_it():
    """70 on its own is not explainable; 7 of 10 is."""
    rule = AIOSv1PolicyRule("va-bid-eval:1.2-stable", {}, {})
    rule._open_registry = lambda bid_job: (FakeAgentFunctions(VERDICTS), True)
    rule.eval({}, {"bid_job": {"bid_job_id": "job-1",
                               "bid_job_metadata": {"evaluation": {"sample_images": SAMPLE_IMAGES}}},
                   "bids": full_round()}, {})
    cam = rule.endpoint_detail["camfacesolution-bid-manager"]
    assert cam["correct"] == 14 and cam["total"] == 20, rule.endpoint_detail
    assert len(cam["endpoints"]) == 2, cam


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    out, _ = run(full_round())
    print("\n" + json.dumps(out, indent=2))
