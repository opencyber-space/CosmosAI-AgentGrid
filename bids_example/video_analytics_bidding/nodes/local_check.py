"""Off-cluster checks for the agent modules.

End-to-end validation belongs in Kubernetes -- that is the repo's standing rule, and
nothing here replaces it. But a bad import, a mis-tagged spec or a Bid Manager that
would consult a rival's Finance Agent should not need a cluster to catch.

So this harness stubs only what genuinely cannot exist on a developer machine (NATS,
Prometheus, the inference-server LM wrapper) and uses the real
thing for everything else: real dspy, the real `agents_sdk` schema and `KnownAgent`, and
`Subject` objects built from the example's own generated spec files. What it checks is
therefore what will actually run.

This is for code validation, simulation and unit tests only. Agent behaviour is only
truly exercised in a pod, against the live inference server, delegate system and
registries -- run the round in the cluster before believing anything about it.

Run from the repo root with the venv. `agents_sdk` is not pip-installed, so its checkout
goes on PYTHONPATH:

    PYTHONPATH=/home/cognitifai/Downloads/agent_codes \
        ./venv/bin/python bids_example/video_analytics_bidding/nodes/local_check.py

Set AGENTS_SDK_PATH to point elsewhere if the SDK checkout moves.
"""
import glob
import importlib.util
import json
import logging
import os
import sys
import threading
import time
import types

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
NODES_DIR = os.path.dirname(os.path.abspath(__file__))

COMPANIES = ["CamFaceSolution", "MultiFaceTech", "NewGenTech", "UltraVideoTech", "VideoProcTech"]


# --- stubs for what cannot exist off-cluster -------------------------------

def _package(name):
    module = types.ModuleType(name)
    module.__path__ = []          # so `import a.b` resolves
    sys.modules[name] = module
    return module


def _module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _Metric:
    """Enough of a prometheus_client metric to satisfy import-time construction."""
    def __init__(self, *a, **k): pass
    def labels(self, *a, **k): return self
    def inc(self, *a, **k): pass
    def dec(self, *a, **k): pass
    def set(self, *a, **k): pass
    def observe(self, *a, **k): pass
    def info(self, *a, **k): pass
    def state(self, *a, **k): pass
    def time(self):
        import contextlib
        return contextlib.nullcontext()


def install_stubs():
    _package("nats"); _package("nats.aio")
    _module("nats.aio.client", Client=object)
    _module("nats.aio.msg", Msg=object)
    _module("nats.errors", TimeoutError=Exception, NoServersError=Exception,
            ConnectionClosedError=Exception)
    _module("prometheus_client", Counter=_Metric, Gauge=_Metric, Histogram=_Metric,
            Summary=_Metric, Info=_Metric, Enum=_Metric,
            start_http_server=lambda *a, **k: None,
            REGISTRY=object(), CollectorRegistry=_Metric)
    _module("utils.dspy_aios_llms", AIOS_DSPy_LMs=lambda subject=None: None)

    sdk_path = os.environ.get("AGENTS_SDK_PATH", "/home/cognitifai/Downloads/agent_codes")
    if os.path.isdir(sdk_path) and sdk_path not in sys.path:
        sys.path.append(sdk_path)
    sys.path.insert(0, os.path.join(REPO_ROOT, "bids_example"))
    sys.path.insert(0, NODES_DIR)


# --- fixtures ---------------------------------------------------------------

def load_known_agents():
    """Real KnownAgent objects built from the example's own generated specs."""
    from agents_sdk.core.known_agents import KnownAgent
    from agents_sdk.core.db.schema import Subject

    by_company = {}
    pattern = os.path.join(NODES_DIR, "..", "spec", "*", "*.json")
    for path in sorted(glob.glob(pattern)):
        with open(path) as fh:
            data = json.load(fh)
        slug = data["metadata"]["subject_metadata"]["company_slug"]
        by_company.setdefault(slug, []).append(KnownAgent(Subject.from_dict(data)))
    if not by_company:
        raise SystemExit("no agent specs found -- run spec/generate_specs.py first")
    return by_company


def make_fake_known_agents(by_company):
    """Stands in for KnownAgents, filtering the way the subject DB would."""
    class FakeKnownAgents:
        def __init__(self, **kwargs):
            self._hits = []

        def query_and_add(self, query=None, **kwargs):
            tag = (query or {}).get("metadata.subject_search_tags")
            self._hits = [agent for agents in by_company.values() for agent in agents
                          if tag in (agent.subject.metadata.subject_search_tags or [])]
            return self._hits

        def list_all(self):
            return self._hits

    return FakeKnownAgents


def load_bid_manager(company):
    path = os.path.join(NODES_DIR, company, "bid_manager.py")
    spec = importlib.util.spec_from_file_location(f"bm_{company}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bare_agent(module, company, by_company):
    """A Bid Manager instance without __init__, which needs a live cluster."""
    from common import company_config

    cls = getattr(module, f"{company}BidManagerAgent")
    agent = cls.__new__(cls)
    agent.company = company
    agent.config = company_config.load(company)
    agent.slug = agent.config["company"]["slug"]
    agent.subject = types.SimpleNamespace(
        identity=types.SimpleNamespace(subject_id=f"{agent.slug}-bid-manager"))
    module.KnownAgents = make_fake_known_agents(by_company)
    return agent


# --- checks -----------------------------------------------------------------

def check_every_bid_manager_imports(by_company):
    for company in COMPANIES:
        module = load_bid_manager(company)
        assert getattr(module, "COMPANY") == company, f"{company}: wrong COMPANY constant"
        assert hasattr(module, f"{company}BidManagerAgent"), f"{company}: class name mismatch"
    print(f"  ok  all {len(COMPANIES)} bid managers import with real dspy and agents_sdk")


def check_discovery_finds_every_role(by_company):
    for company in COMPANIES:
        module = load_bid_manager(company)
        agent = bare_agent(module, company, by_company)
        found = agent._discover_subordinates()
        assert set(found) == set(module.STAGE_ROLES), f"{company}: {found}"
        assert f"{agent.slug}-bid-manager" not in found.values(), f"{company}: discovered itself"
    print("  ok  every company discovers all five subordinate roles, excluding itself")


def check_no_cross_company_leakage(by_company):
    for company in COMPANIES:
        module = load_bid_manager(company)
        agent = bare_agent(module, company, by_company)
        found = agent._discover_subordinates()
        strays = [sid for sid in found.values() if not sid.startswith(f"{agent.slug}-")]
        assert not strays, f"{company} would consult another company's agents: {strays}"
    print("  ok  no company discovers another company's agents")


def check_fallback_matches_discovery(by_company):
    """A briefly unreachable subject DB must degrade to a working round, not an empty one."""
    for company in COMPANIES:
        module = load_bid_manager(company)
        agent = bare_agent(module, company, by_company)
        discovered = agent._discover_subordinates()

        class Broken:
            def __init__(self, **kwargs):
                raise RuntimeError("subject DB unreachable")

        module.KnownAgents = Broken
        fallback = agent._discover_subordinates()
        assert fallback == discovered, f"{company}: fallback {fallback} != discovered {discovered}"
    print("  ok  fallback ids match discovered ids when the subject DB is unreachable")


def check_declining_bid_carries_credentials(by_company):
    """Pre-qualification runs on declines too; a missing block reads as a credential failure."""
    for company in COMPANIES:
        module = load_bid_manager(company)
        agent = bare_agent(module, company, by_company)
        bid = agent._declining_bid("compliance", "no coverage")
        assert bid["bid_status"] == "declined"
        assert bid["credentials"]["licenses_supplied"] is not None, company
    print("  ok  every company's declining bid carries its credentials")


def check_bid_numbers_are_normalised(by_company):
    module = load_bid_manager("CamFaceSolution")
    agent = bare_agent(module, "CamFaceSolution", by_company)
    bid = agent._assemble_bid({
        "compliance": {"met": 15, "total": 20, "live_endpoints": [
            {"function_id": "a", "verified": True}, {"function_id": "b", "verified": False}]},
        "sizing": {"totals": {"cpu_cores": "640", "ram_gb": 2560, "disk_gb": 92000, "gpu_count": 40},
                   "document_url": "http://minio/sizing.xlsx"},
        "finance": {"total_budget": "48,500,000", "document_url": "http://minio/commercials.xlsx"},
        "review": {"ready_to_bid": True},
        "approval": {"approved": True, "reason": "viable"},
    })
    assert bid["total_budget"] == 48500000.0, bid["total_budget"]
    assert bid["sizing"]["cpu_cores"] == 640.0, bid["sizing"]
    assert len(bid["live_endpoints"]) == 1, "unverified endpoints must be dropped"
    print("  ok  bid numbers normalise and unverified endpoints are dropped")


def load_agent_module(company, module_name):
    path = os.path.join(NODES_DIR, company, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(f"{module_name}_{company}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compliance_agent(company):
    """An AI Compliance Agent bound to `company`'s config, without __init__."""
    from common import company_config

    module = load_agent_module("CamFaceSolution", "ai_compliance")
    cls = module.CamFaceSolutionAiComplianceAgent
    agent = cls.__new__(cls)
    agent.company = company
    agent.config = company_config.load(company)
    agent.slug = agent.config["company"]["slug"]
    return module, agent


# The RFP asks for five capabilities. No company offers vehicle over-speeding; only
# UltraVideoTech offers video summarisation.
RFP_USECASES = [
    {"id": "face_recognition", "name": "Face Recognition System", "outdoor": True},
    {"id": "crowd_density", "name": "Crowd density estimation", "outdoor": True},
    {"id": "anpr", "name": "License plate recognition", "outdoor": True},
    {"id": "vehicle_speed", "name": "Vehicle over-speeding detection", "outdoor": True},
    {"id": "video_summarization", "name": "Video summarisation and back-search", "outdoor": True},
]


def check_coverage_ignores_generic_words(by_company):
    """"Vehicle over-speeding detection" must not match "multi-face detection in crowds".

    Sharing the word "detection" says nothing about whether two use cases are the same
    capability. A false match here is worse than declining: it produces a bid that can
    win and then cannot be delivered.
    """
    _module, agent = compliance_agent("CamFaceSolution")
    covered, uncovered = agent._coverage(RFP_USECASES)
    assert "vehicle_speed" not in covered, f"falsely covered: {covered}"
    assert "crowd_multiface" not in covered, f"generic-word false match: {covered}"
    assert any("speed" in u.lower() for u in uncovered), uncovered

    _module, ultra = compliance_agent("UltraVideoTech")
    covered_ultra, _ = ultra._coverage(RFP_USECASES)
    assert "video_summarization" in covered_ultra, "a genuine match must still land"
    print("  ok  coverage matching ignores generic words and still finds real matches")


def check_decline_paths(by_company):
    from common import company_config

    _module, videoproc = compliance_agent("VideoProcTech")
    assert not company_config.licence_count_supported(videoproc.config, 4000), \
        "VideoProcTech's ceiling must exclude a city-scale licence count"

    _module, multiface = compliance_agent("MultiFaceTech")
    covered, _ = multiface._coverage(RFP_USECASES)
    assert covered, "MultiFaceTech does offer face use cases"
    assert not any(company_config.serves_outdoor(multiface.config, uc) for uc in covered), \
        "MultiFaceTech must serve nothing outdoors"

    _module, cam = compliance_agent("CamFaceSolution")
    covered, _ = cam._coverage(RFP_USECASES)
    assert any(company_config.serves_outdoor(cam.config, uc) for uc in covered), \
        "CamFaceSolution must serve outdoors"

    report = videoproc._decline("licensing", "ceiling exceeded", RFP_USECASES, 4000)
    assert report["decline_reason"] and report["live_endpoints"] == [] and report["total"] == 0
    print("  ok  licence-ceiling and indoor-only decline paths trigger for the right companies")


def check_endpoint_cap(by_company):
    module, agent = compliance_agent("CamFaceSolution")
    seen = {}

    def fake_resolve(company_slug, usecase_ids, declared, max_endpoints=2, **kwargs):
        ids = list(usecase_ids)[:max_endpoints]
        seen["cap"] = max_endpoints
        seen["declared"] = list(declared)
        return ([{"usecase": u, "function_id": f"va-uc-{company_slug}-{u}:1.0-stable",
                  "verified": True} for u in ids], [])

    module.function_publisher = types.SimpleNamespace(resolve_usecase_endpoints=fake_resolve)

    published, _ = agent._offer_endpoints(
        ["face_recognition", "crowd_multiface", "crowd_density"], ["face_recognition"])
    assert len(published) == seen["cap"] == 2, published

    # Only what was actually built and uploaded may be offered. An id the agent invents
    # for a use case nobody packaged is called by the evaluator, 404s, and scores this
    # company 0 for an endpoint it claimed to have.
    assert all(p["usecase"] in seen["declared"] for p in published), published
    assert "crowd_density" not in [p["usecase"] for p in published], \
        "CamFaceSolution declares no crowd_density endpoint, so it must not offer one"

    # An RFP that names no live test must still leave the company with endpoints,
    # or the evaluator's endpoint dimension is dead for everyone.
    fallback, _ = agent._offer_endpoints([], ["face_recognition", "crowd_multiface"])
    assert fallback, "endpoints must fall back to the covered use cases"
    print("  ok  endpoint selection respects the cap, offers only what was uploaded, "
          "and falls back when unbenchmarked")


def check_no_answer_key_in_any_config(by_company):
    """No company config may carry what its own endpoints answer.

    The endpoint dimension is a test this company sits. An answer key committed beside
    the company being graded on it is not a benchmark, and it was read as the example
    faking its own results -- which is fair, because it was. The answers now live in an
    uncommitted functions/va-usecase-endpoint/verdicts/<slug>_verdicts.yaml, packaged
    into the endpoint at build time, and nothing in the agent can read them.
    """
    import glob as _glob
    import yaml as _yaml

    for path in sorted(_glob.glob(os.path.join(NODES_DIR, "*", "config.yaml"))):
        company = os.path.basename(os.path.dirname(path))
        config = _yaml.safe_load(open(path)) or {}
        live = config.get("live_endpoints") or {}
        assert "verdicts" not in live, \
            f"{company}: live_endpoints.verdicts is back in config.yaml"
        raw = open(path).read()
        assert ".png" not in raw, \
            f"{company}: config.yaml names evaluation images; the answer key is back"
        assert live.get("endpoints"), \
            f"{company}: live_endpoints.endpoints must say which endpoints it stands up"
    print("  ok  no company config carries the answers its own endpoints give")


def check_malformed_verdicts_are_unmet(by_company):
    """A model returning junk must score zero, not crash the bid."""
    import contextlib

    module, agent = compliance_agent("CamFaceSolution")

    class Junk:
        def __init__(self, *a, **k): pass
        def __call__(self, **kwargs):
            return types.SimpleNamespace(verdict_result="not json at all")

    module.dspy.ChainOfThought = Junk
    agent._get_lm_context = lambda *a, **k: contextlib.nullcontext()
    points = agent._verdicts(["must support outdoor", "must be NIST certified"], "s", "m")
    assert len(points) == 2 and not any(p["met"] for p in points), points
    print("  ok  malformed model output scores every requirement unmet without raising")


def _fake_store():
    """Captures what would have been uploaded, keeping a readable .xlsx behind."""
    kept = {}

    class FakeStore:
        def put_file(self, path, bucket, object_name, content_type=None):
            target = path.replace(".xlsx", "") + "-kept.xlsx"
            os.replace(path, target)
            kept[object_name] = target
            return {"bucket": bucket, "object": object_name,
                    "url": f"http://minio/{bucket}/{object_name}"}

    return FakeStore, kept


def _bound_agent(module_name, class_name, company, kept_store=None):
    from common import company_config

    module = load_agent_module("CamFaceSolution", module_name)
    if kept_store is not None:
        module.minio_store = types.SimpleNamespace(MinioStore=kept_store,
                                                   DOCS_BUCKET="va-bidding-docs")
    cls = getattr(module, class_name)
    agent = cls.__new__(cls)
    agent.company = company
    agent.config = company_config.load(company)
    agent.slug = agent.config["company"]["slug"]
    return module, agent


COMPLIANCE_FIXTURE = {"total_licenses": 4000,
                      "covered_usecases": ["face_recognition", "crowd_density", "anpr"]}


def check_sizing_asymmetry(by_company):
    """UltraVideoTech must be leaner than CamFaceSolution on every hardware dimension.

    With only two survivors each relative dimension collapses to 25/75, so if the two
    were configured alike the winner would hinge on a single field. The whole point of
    the asymmetry is that budget and sizing pull in opposite directions.
    """
    totals = {}
    for company in ("CamFaceSolution", "UltraVideoTech"):
        _module, agent = _bound_agent("sizing", "CamFaceSolutionSizingAgent", company)
        _rows, totals[company] = agent._compute(
            agent._priced_usecases(COMPLIANCE_FIXTURE), 4000)

    cam, ultra = totals["CamFaceSolution"], totals["UltraVideoTech"]
    leaner = [f for f in ("cpu_cores", "ram_gb", "disk_gb", "gpu_count") if ultra[f] < cam[f]]
    assert len(leaner) == 4, f"UltraVideoTech is not leaner on all four:\n{cam}\n{ultra}"
    assert isinstance(cam["gpu_count"], int) and cam["gpu_count"] >= 1, \
        "accelerators are whole units and a deployment needs at least one"
    print("  ok  sizing asymmetry holds and accelerators round to whole units")


def check_sizing_refuses_meaningless_input(by_company):
    """A deployment of zero would win the sizing dimension outright and mean nothing."""
    _module, agent = _bound_agent("sizing", "CamFaceSolutionSizingAgent", "CamFaceSolution")
    for bad in ({"total_licenses": 0, "covered_usecases": ["face_recognition"]},
                {"total_licenses": 4000, "covered_usecases": []}):
        try:
            agent._size(bad)
            raise AssertionError(f"sizing accepted meaningless input: {bad}")
        except ValueError:
            pass
    print("  ok  sizing refuses a zero licence count and an empty use-case set")


def check_finance_ordering(by_company):
    priced = {}
    for company in ("CamFaceSolution", "UltraVideoTech", "NewGenTech"):
        _module, agent = _bound_agent("finance", "CamFaceSolutionFinanceAgent", company)
        priced[company] = agent._price(COMPLIANCE_FIXTURE)

    cam, ultra, newgen = (priced[c] for c in ("CamFaceSolution", "UltraVideoTech", "NewGenTech"))
    assert ultra["total_budget"] > cam["total_budget"], "UltraVideoTech must be the dearer bid"
    assert newgen["total_budget"] < cam["total_budget"], \
        "NewGenTech undercuts both -- it loses on credentials, never on price"
    assert abs(cam["licence_subtotal"] + cam["one_time_cost"] + cam["amc_cost"]
               - cam["total_budget"]) < 0.01, "components must sum to the total"
    print("  ok  pricing order is as designed and the components sum to the total")


def check_workbooks_are_written_correctly(by_company):
    """The delivered files must carry this company's numbers and none of the template's."""
    fake_store, kept = _fake_store()

    sizing_mod, sizing_agent = _bound_agent(
        "sizing", "CamFaceSolutionSizingAgent", "CamFaceSolution", fake_store)
    sizing_agent._size(COMPLIANCE_FIXTURE)

    finance_mod, finance_agent = _bound_agent(
        "finance", "CamFaceSolutionFinanceAgent", "CamFaceSolution", fake_store)
    finance = finance_agent._price(COMPLIANCE_FIXTURE)

    import openpyxl
    try:
        sizing_sheet = openpyxl.load_workbook(kept["CamFaceSolution/sizing.xlsx"])[sizing_mod.SHEET]
        assert sizing_sheet["B5"].value, "the first sizing row must be written"
        assert sizing_sheet["A10"].value is None, "template leftovers must be cleared"
        assert sizing_sheet["D4"].value == "=SUM(C5:C23)", "the licence formula must survive"
        assert isinstance(sizing_sheet["E4"].value, (int, float)), "totals must be literal values"

        comm_sheet = openpyxl.load_workbook(
            kept["CamFaceSolution/commercials.xlsx"])[finance_mod.SHEET]
        assert comm_sheet["C10"].value, "the first commercial line must be written"
        assert comm_sheet["B20"].value is None, "template leftovers must be cleared"
        assert comm_sheet["D8"].value is None, "section A must be blanked to avoid double-counting"
        assert comm_sheet["H10"].value == "=(F10*D10)", "per-line formulas must survive"
        assert comm_sheet["H28"].value != "=H8", \
            "the template's broken licence-cost aggregate must be replaced"
        assert abs(comm_sheet["H34"].value - finance["total_budget"]) < 0.01, \
            "the workbook total must match the figure on the bid"
    finally:
        for path in kept.values():
            try:
                os.remove(path)
            except OSError:
                pass
    print("  ok  both workbooks carry this company's numbers, formulas intact, leftovers cleared")


AGENT_MODULES = {
    "bid_manager": "BidManagerAgent",
    "ai_compliance": "AiComplianceAgent",
    "sizing": "SizingAgent",
    "finance": "FinanceAgent",
    "bid_reviewer": "BidReviewerAgent",
    "head": "HeadAgent",
}


def check_all_thirty_modules_import(by_company):
    """Six roles x five companies, each a standalone module with its own identity."""
    count = 0
    for company in COMPANIES:
        for module_name, suffix in AGENT_MODULES.items():
            module = load_agent_module(company, module_name)
            assert getattr(module, "COMPANY", None) == company, \
                f"{company}/{module_name}.py has the wrong COMPANY constant"
            class_name = f"{company}{suffix}"
            assert hasattr(module, class_name), \
                f"{company}/{module_name}.py is missing {class_name}"
            count += 1
    print(f"  ok  all {count} agent modules import with the right company identity")


def _reports(budget=16_875_600.0, docs=True, totals=True, compliance_total=20):
    sizing_totals = ({"cpu_cores": 2040.0, "ram_gb": 8160.0, "disk_gb": 288000.0, "gpu_count": 136}
                     if totals else {})
    return {
        "compliance": {"met": 15, "total": compliance_total,
                       "covered_usecases": ["face_recognition", "crowd_density", "anpr"],
                       "uncovered_usecases": ["Vehicle over-speeding"],
                       "live_endpoints": [{"usecase": "face_recognition",
                                           "function_id": "va-uc-x:1.0-stable", "verified": True}]},
        "sizing": {"totals": sizing_totals,
                   "document_url": "http://minio/sizing.xlsx" if docs else None},
        "finance": {"total_budget": budget, "licence_subtotal": 13_720_000.0,
                    "one_time_cost": 1_920_800.0, "amc_cost": 1_234_800.0,
                    "timeline_weeks": 144.0,
                    "document_url": "http://minio/commercials.xlsx" if docs else None},
    }


def check_reviewer_catches_structural_gaps(by_company):
    """The gaps that make a bid unscoreable must be caught in code, not left to a model."""
    _module, agent = _bound_agent("bid_reviewer", "CamFaceSolutionBidReviewerAgent",
                                  "CamFaceSolution")
    complete = _reports()
    assert agent._structural_gaps(complete["compliance"], complete["sizing"],
                                  complete["finance"]) == [], "a complete bid has no gaps"

    no_docs = _reports(docs=False)
    gaps = agent._structural_gaps(no_docs["compliance"], no_docs["sizing"], no_docs["finance"])
    assert any("commercial document" in g for g in gaps), gaps
    assert any("sizing document" in g for g in gaps), gaps

    no_budget = _reports(budget=None)
    assert any("total budget" in g for g in
               agent._structural_gaps(no_budget["compliance"], no_budget["sizing"],
                                      no_budget["finance"]))

    no_totals = _reports(totals=False)
    assert any("sizing totals" in g for g in
               agent._structural_gaps(no_totals["compliance"], no_totals["sizing"],
                                      no_totals["finance"]))
    print("  ok  reviewer catches missing documents, budget and hardware totals")


def check_reviewer_reports_rather_than_vetoes(by_company):
    """ready_to_bid: false is an input to the Head Agent, never a terminal state."""
    _module, reviewer = _bound_agent("bid_reviewer", "CamFaceSolutionBidReviewerAgent",
                                     "CamFaceSolution")
    result = reviewer._review(_reports(docs=False), None, "s", "m")
    assert result["ready_to_bid"] is False
    assert result["structural_gaps"], "the gaps must be reported, not swallowed"
    # Nothing in the reviewer's own output ends the chain -- only the Head Agent can.
    assert "decline_reason" not in result and "approved" not in result
    print("  ok  reviewer reports gaps without ending the chain itself")


def check_head_approves_the_three_bidders(by_company):
    """All three companies that reach approval must pass; NewGenTech loses at PQT, not here."""
    reports = _reports()
    reports["review"] = {"ready_to_bid": True, "structural_gaps": [], "missing": []}
    for company in ("CamFaceSolution", "UltraVideoTech", "NewGenTech"):
        _module, head = _bound_agent("head", "CamFaceSolutionHeadAgent", company)
        head._write_rationale = lambda *a, **k: (None, [])      # no inference server here
        decision = head._decide(reports, "s", "m")
        assert decision["approved"], f"{company} should approve: {decision['reason']}"
        assert decision["criteria"]["margin"]["pass"], decision["criteria"]["margin"]
    print("  ok  all three bidding companies clear their own margin floors")


def check_head_refuses_an_unviable_cost_base(by_company):
    """The two companies that decline earlier are also genuinely unviable on cost.

    They never reach approval in the demonstrated round, so this only matters if their
    decline paths were removed -- but a cost base that quietly made them viable would be
    a config that says something the example does not mean.
    """
    reports = _reports()
    reports["review"] = {"ready_to_bid": True, "structural_gaps": [], "missing": []}
    for company in ("MultiFaceTech", "VideoProcTech"):
        _module, head = _bound_agent("head", "CamFaceSolutionHeadAgent", company)
        head._write_rationale = lambda *a, **k: (None, [])
        decision = head._decide(reports, "s", "m")
        assert not decision["approved"], f"{company} should not be viable: {decision['criteria']}"
        assert "margin" in decision["reason"], decision["reason"]
    print("  ok  the two declining companies are unviable on their own cost base")


def check_head_refuses_an_incomplete_bid(by_company):
    reports = _reports(docs=False)
    reports["review"] = {"ready_to_bid": False,
                         "structural_gaps": ["commercial document was not produced or uploaded"],
                         "missing": []}
    _module, head = _bound_agent("head", "CamFaceSolutionHeadAgent", "CamFaceSolution")
    head._write_rationale = lambda *a, **k: (None, [])
    decision = head._decide(reports, "s", "m")
    assert decision["approved"] is False, decision
    assert "incomplete" in decision["reason"], decision["reason"]

    no_budget = _reports(budget=None)
    no_budget["review"] = {"ready_to_bid": True, "structural_gaps": [], "missing": []}
    decision = head._decide(no_budget, "s", "m")
    assert decision["approved"] is False and "priced bid" in decision["reason"], decision
    print("  ok  head refuses an incomplete or unpriced bid")


def check_every_agent_reports_to_his(by_company):
    """All 30 agents must post what they received and what they produced.

    The dashboard reads HIS per subject id, so an agent that does not report is simply
    invisible while a round runs -- including the companies that decline before any bid
    exists, which are exactly the ones you want to watch.
    """
    for company in COMPANIES:
        for module_name, suffix in AGENT_MODULES.items():
            module = load_agent_module(company, module_name)
            assert hasattr(module, "ROLE"), f"{company}/{module_name}.py has no ROLE constant"
            cls = getattr(module, f"{company}{suffix}")
            assert hasattr(cls, "_report"), f"{company}/{module_name}.py cannot report to HIS"
    print("  ok  all 30 agents carry HIS reporting")


def check_his_reporting_never_raises(by_company):
    """Observability must never cost a bid.

    A Bid Manager that failed to log and therefore failed to submit would stall the
    round permanently, because evaluation waits on every participant and has no timeout.
    """
    sys.path.insert(0, os.path.join(NODES_DIR))
    from common import his_logger

    class ExplodingClient:
        def submit(self, **kwargs):
            raise RuntimeError("HIS is down")

    his_logger.report(ExplodingClient(), subject_id="x", company="c", role="r",
                      event="INCOMING_TASK", payload={"a": 1})
    his_logger.report(None, subject_id="x", company="c", role="r",
                      event="OUTGOING_RESULT", payload={"a": 1})

    # Unserialisable payloads must summarise rather than blow up.
    summarised = his_logger.summarise({"obj": object(), "big": "x" * 5000,
                                       "many": list(range(50))})
    assert isinstance(summarised["obj"], str)
    assert len(summarised["big"]) < 2000
    assert len(summarised["many"]) == his_logger.MAX_LIST_ITEMS + 1
    print("  ok  HIS reporting swallows failures and bounds its payloads")


def check_specs_carry_his_config(by_company):
    """HisClient.submit reads SUBJECT_ID from the pod environment, so the spec must set it."""
    for company in COMPANIES:
        for module_name in AGENT_MODULES:
            path = os.path.join(NODES_DIR, "..", "spec", company, f"{module_name}.json")
            with open(path) as fh:
                spec = json.load(fh)
            params = spec["persona"]["config"]["parameters"]
            assert params.get("HIS_CONFIG", {}).get("HIS_BASE_URL"), f"{path}: no HIS_CONFIG"
            env = spec["runtime"]["resources"]["env"]
            assert env.get("SUBJECT_ID") == spec["identity"]["subject_id"], \
                f"{path}: env SUBJECT_ID must match the subject id HisClient posts against"
    print("  ok  all 30 specs carry HIS_CONFIG and a matching SUBJECT_ID")


def check_shell_scripts_guard_empty_jq_output(by_company):
    """Every number a shell script pulls out of jq must be defaulted before it is compared.

    `jq` prints nothing for empty input and still exits 0, so `VAR=$(curl ... | jq ...)`
    leaves VAR empty when the service is unreachable -- and `[ "$VAR" -ne 2 ]` then
    reports "found ." or dies with "integer expression expected", hiding a transport
    failure behind what looks like a wrong answer. This caught us twice.
    """
    import re

    example_dir = os.path.abspath(os.path.join(NODES_DIR, ".."))
    scripts = []
    for root, _dirs, files in os.walk(example_dir):
        scripts += [os.path.join(root, f) for f in files if f.endswith(".sh")]

    offenders = []
    for path in scripts:
        with open(path) as fh:
            text = fh.read()
        # variables assigned from a jq pipeline
        from_jq = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=\$\([^)]*\bjq\b", text, re.M))
        # variables given an explicit empty-string default
        guarded = set(re.findall(r'\[\s*-z\s*"\$([A-Za-z_][A-Za-z0-9_]*)"\s*\]', text))
        # variables used in a numeric comparison
        compared = set(re.findall(r'"\$([A-Za-z_][A-Za-z0-9_]*)"\s+-(?:eq|ne|lt|le|gt|ge)\s', text))

        for name in sorted(from_jq & compared - guarded):
            offenders.append(f"{os.path.relpath(path, example_dir)}: ${name}")

    assert not offenders, (
        "numeric comparison on an unguarded jq result:\n  " + "\n  ".join(offenders))
    print(f"  ok  {len(scripts)} shell scripts default their jq-derived numbers before comparing")


def check_submission_survives_timeouts_and_pqt_rejection(by_company):
    """Every terminal outcome must leave a bid on file, or the round never resolves.

    Two failures seen in the cluster, both of which stalled a round permanently:

      * OpenArcade runs the pre-qualification function as a Kubernetes job on every
        submission, and with five companies submitting at once the call came back as a
        read timeout against the registry. One lost submission and evaluation -- which
        waits for every participant, with no timeout -- never fires.

      * Pre-qualification rejecting a bid raises, and OpenArcade does **not** keep the
        rejected bid. NewGenTech is meant to lose at PQT, so without recording that
        rejection as a declining bid it has nothing on file and the round cannot
        complete at all.

    Errors here are the real `BiddingError`, with the status codes OpenArcade answers
    with, because the agent now reads `status_code` to decide whether a retry can help.
    """
    from agents_sdk.core.bidding_client import BiddingError

    TIMEOUT = BiddingError("Request to http://x/bid-jobs/j/bids failed: "
                           "HTTPConnectionPool(host='x', port=30730): Read timed out.")
    PQT = BiddingError("Bid '5eff7443' rejected by pqt function 'va-bidding-pqt:1.0-stable'.")
    DUPLICATE = BiddingError("Subject 'x' has already applied to job 'j'.", 409)
    # The real text, from the NewGenTech pod in round 9. OpenArcade answers a
    # pre-qualification rejection with 409 -- the same status as a duplicate.
    PQT_409 = BiddingError("Bid '04b9a17c' rejected by pqt function 'va-bidding-pqt:1.0-stable'.", 409)
    NOT_ON_ROSTER = BiddingError("Subject 'x' is not in this job's roster.", 400)
    SERVER_ERROR = BiddingError("database failure", 500)

    for company in sorted(COMPANIES):
        module = load_agent_module(company, "bid_manager")
        cls = next(obj for name, obj in vars(module).items()
                   if isinstance(obj, type) and name.endswith("BidManagerAgent"))

        def run(failures, configured=True):
            agent = cls.__new__(cls)
            agent.company = company
            agent.slug = company.lower()
            agent.subject = types.SimpleNamespace(
                identity=types.SimpleNamespace(subject_id=f"{agent.slug}-bid-manager"))
            agent.SUBMIT_BACKOFF = 0.0
            calls, events = [], []
            agent._report = lambda event, payload, **kw: events.append((event, payload))
            agent._credentials = lambda: {}

            pending = list(failures)

            class Client:
                def submit_bid(self, submission):
                    calls.append(submission.bid_data.get("bid_status"))
                    assert submission.bid_job_id == "job-1"
                    assert submission.bid_subject_id == f"{agent.slug}-bid-manager"
                    if pending:
                        raise pending.pop(0)
                    return types.SimpleNamespace(bid_id="b-1", is_winner=False)

            agent._local = threading.local()
            agent._task_client = Client() if configured else None
            agent._poll_client = None

            original_sleep = module.time.sleep
            module.time.sleep = lambda _s: None
            try:
                ok = agent._submit_to_openarcade("job-1", {"bid_status": "submitted"})
            finally:
                module.time.sleep = original_sleep
            return ok, calls, [name for name, _ in events], dict(events)

        ok, calls, events, _ = run([])
        assert ok and calls == ["submitted"], f"{company}: a clean submit must not retry"

        ok, calls, events, _ = run([TIMEOUT, TIMEOUT])
        assert ok, f"{company}: gave up on a retryable timeout"
        assert len(calls) == 3, f"{company}: expected 2 retries, made {len(calls) - 1}"
        assert "SUBMISSION_FAILED" not in events, f"{company}: reported a failure it recovered from"

        ok, calls, events, _ = run([TIMEOUT] * 10)
        assert not ok, f"{company}: claimed success after exhausting every attempt"
        assert "SUBMISSION_FAILED" in events, (
            f"{company}: gave up silently -- a stalled round must say so")

        ok, calls, events, _ = run([SERVER_ERROR, SERVER_ERROR])
        assert ok and len(calls) == 3, f"{company}: a 5xx is OpenArcade's trouble, not an answer; retry it"

        ok, calls, events, _ = run([PQT])
        assert ok, f"{company}: treated a pqt rejection as an unrecoverable failure"
        assert calls == ["submitted", "declined"], (
            f"{company}: a pqt rejection must be put on file as a declining bid, got {calls}")
        assert "PQT_REJECTED" in events and "SUBMISSION_FAILED" not in events

        # A submission whose write landed but whose response timed out is retried, and
        # the retry collides with the bid it already stored. Round 8 showed OpenArcade
        # answering that with a 409. The round has what it needs, so retrying it to
        # exhaustion and then reporting SUBMISSION_FAILED would be a lie about a bid
        # that is on the job.
        ok, calls, events, _ = run([TIMEOUT, DUPLICATE])
        assert ok, f"{company}: treated a duplicate bid as a failure"
        assert len(calls) == 2, f"{company}: kept retrying after the bid was on file"
        assert "SUBMISSION_FAILED" not in events, (
            f"{company}: reported a failure for a bid OpenArcade already holds")

        # A pqt rejection also arrives as 409, so anything that reads the status code
        # before the message turns NewGenTech's rejection into a silent success and
        # leaves the round with four bids and no fifth, waiting for ever.
        ok, calls, events, _ = run([PQT_409])
        assert calls == ["submitted", "declined"], (
            f"{company}: a 409 pqt rejection must still put a declining bid on file, got {calls}")
        assert "PQT_REJECTED" in events, f"{company}: a 409 pqt rejection went unreported"

        # An answer OpenArcade will repeat is not worth four attempts and 75 seconds.
        ok, calls, events, detail = run([NOT_ON_ROSTER] * 10)
        assert not ok and len(calls) == 1, (
            f"{company}: retried a 400 that cannot change, {len(calls)} attempts")
        assert detail["SUBMISSION_FAILED"]["attempts"] == 1, f"{company}: reported the wrong attempt count"

        # No ORCADE_URL: nothing can be submitted, and saying so is the whole job.
        ok, calls, events, _ = run([], configured=False)
        assert not ok and not calls and "SUBMISSION_FAILED" in events, (
            f"{company}: an unconfigured OpenArcade URL must be reported, not crash or pass")

    print(f"  ok  {len(COMPANIES)} bid managers leave a bid on file on every outcome")


def check_the_denominator_is_the_rfps_requirement_count(by_company):
    """Every company must be scored out of the same number, and that number is the RFP's.

    Two ways it used to move. The list itself was extracted per company, so one bidder
    was judged on 16 clauses and another on 70 of the same tender -- `va-rfp-requirements`
    now owns that list. And `total` was taken from the verdicts rather than the
    requirements, so a model that answered about fewer clauses shrank its own
    denominator and looked better for it.

    This checks the second one directly: hand the agent a known requirement list and a
    verdict set that is short, padded, reordered and paraphrased, and the fraction must
    still be out of the requirement count.
    """
    REQUIREMENTS = [
        "FRS must support 1:1, 1:N and N:N matching.",
        "Analytics shall run on GPU based servers.",
        "Accuracy shall not be less than 90%.",
        "The system shall operate in outdoor conditions.",
    ]

    cases = {
        "model answered about every requirement": (
            [{"requirement": r, "met": i < 2, "reason": "x"} for i, r in enumerate(REQUIREMENTS)], 2),
        "model skipped half the list": (
            [{"requirement": REQUIREMENTS[0], "met": True, "reason": "x"},
             {"requirement": REQUIREMENTS[1], "met": True, "reason": "x"}], 2),
        "model returned nothing at all": ([], 0),
        "model invented extra verdicts": (
            [{"requirement": r, "met": True, "reason": "x"} for r in REQUIREMENTS]
            + [{"requirement": "Bidder shall submit EMD.", "met": True, "reason": "x"}], 4),
        "model paraphrased every clause": (
            [{"requirement": "supports 1:1 and 1:N matching", "met": True, "reason": "x"},
             {"requirement": "runs on GPU servers", "met": False, "reason": "x"},
             {"requirement": "90 percent accuracy", "met": True, "reason": "x"},
             {"requirement": "works outdoors", "met": False, "reason": "x"}], 2),
    }

    for company in sorted(COMPANIES):
        module = load_agent_module(company, "ai_compliance")
        cls = next(obj for name, obj in vars(module).items()
                   if isinstance(obj, type) and name.endswith("AiComplianceAgent"))
        align = cls._align_verdicts

        for label, (points, expected_met) in cases.items():
            aligned = align(REQUIREMENTS, points)
            assert len(aligned) == len(REQUIREMENTS), (
                f"{company}: {label} -- denominator became {len(aligned)}, "
                f"not {len(REQUIREMENTS)}")
            met = sum(1 for p in aligned if p.get("met"))
            assert met == expected_met, f"{company}: {label} -- met {met}, expected {expected_met}"
            assert [p["requirement"] for p in aligned] == REQUIREMENTS, (
                f"{company}: {label} -- verdicts are no longer the RFP's own clauses")

    print(f"  ok  {len(COMPANIES)} compliance agents score out of the RFP's requirement count")


def check_compliance_has_no_private_requirement_path(by_company):
    """va-rfp-requirements is the only source of requirements. There is no fallback.

    A local extraction looks like resilience and is not: it gives that one company a
    private requirement list, so its met/total is out of a different denominator than
    everybody else's and the round silently stops being a comparison. Declining is the
    honest outcome, and the agent already turns an exception into a declining bid with
    the reason attached.
    """
    for company in sorted(COMPANIES):
        path = os.path.join(NODES_DIR, company, "ai_compliance.py")
        with open(path) as fh:
            source = fh.read()
        assert "rfp_requirements.fetch(" in source, (
            f"{company}: no longer calls the shared requirements function")
        for gone in ("rfp_reader", "RfpRequirementsSignature", "_scope_requirements",
                     "local_fallback"):
            assert gone not in source, (
                f"{company}: {gone} is back -- that is a private requirement list again")

    print(f"  ok  {len(COMPANIES)} compliance agents have no private requirement path")


def check_the_dossier_answers_what_the_rfp_asks(by_company):
    """The verdict model can only confirm what it is shown.

    Every one of the 37 requirements on bid job 9a9b9f38 came back unmet with a reason
    of the form "the catalogue does not mention it", because the catalogue passed to the
    model was the use-case list alone. These are the fields the Patna RFP actually asks
    about; without them the compliance dimension scores 0 for everyone and ranks nobody.
    """
    CAPABILITY_KEYS = ("deployment", "modes", "matching_modes", "crowd",
                       "pose_tolerance_deg", "video", "search", "enrolment",
                       "integrations", "alerting", "inputs", "watchlist")
    PLATFORM_KEYS = ("model_training", "model_library", "detection", "dashboard",
                     "licensing_modes", "privacy")

    sys.path.insert(0, NODES_DIR)
    from common import company_config

    dossiers = {}
    for company in sorted(COMPANIES):
        config = company_config.load(company)
        for key in ("capabilities", "platform"):
            assert key in config, f"{company}: config.yaml has no `{key}` block"
        for key in CAPABILITY_KEYS:
            assert key in config["capabilities"], f"{company}: capabilities.{key} missing"
        for key in PLATFORM_KEYS:
            assert key in config["platform"], f"{company}: platform.{key} missing"

        # Numbers the RFP compares against must be numbers, not prose: "under 5 seconds"
        # cannot be judged against "fast".
        search = config["capabilities"]["search"]
        assert isinstance(search.get("latency_s"), (int, float)), f"{company}: search.latency_s"
        assert isinstance(search.get("max_gallery_size"), int), f"{company}: max_gallery_size"
        pose = config["capabilities"]["pose_tolerance_deg"]
        for axis in ("yaw", "pitch", "roll"):
            assert isinstance(pose.get(axis), (int, float)), f"{company}: pose_tolerance_deg.{axis}"
        assert isinstance(config["capabilities"]["crowd"].get("max_faces_per_frame"), int), company

        dossiers[company] = (search["latency_s"], search["max_gallery_size"],
                             pose["yaw"], config["capabilities"]["crowd"]["max_faces_per_frame"])

    # Five identical dossiers would score identically and rank nobody -- the same failure
    # as a moving denominator, just quieter.
    assert len(set(dossiers.values())) == len(COMPANIES), (
        f"companies are not distinguishable on the numbers the RFP asks about: {dossiers}")

    print(f"  ok  {len(COMPANIES)} dossiers answer the RFP in comparable numbers")


def check_the_dossier_reaches_the_verdict_model(by_company):
    """The blocks exist in config.yaml and are actually handed to the model."""
    for company in sorted(COMPANIES):
        module = load_agent_module(company, "ai_compliance")
        cls = next(obj for name, obj in vars(module).items()
                   if isinstance(obj, type) and name.endswith("AiComplianceAgent"))
        from common import company_config
        agent = cls.__new__(cls)
        agent.config = company_config.load(company)
        dossier = agent._dossier()
        for key in ("usecases", "capabilities", "platform", "credentials", "licensing"):
            assert key in dossier, f"{company}: the verdict model is not shown `{key}`"
    print(f"  ok  {len(COMPANIES)} agents show the verdict model the whole dossier")


def check_out_of_scope_requirements_are_filtered(by_company):
    """A video analytics supplier is scored only on what it could answer for.

    A smart-city tender procures a whole system, and most clauses bind somebody else.
    A real round scored these companies against "IP CCTV System OEM for Cameras & VMS
    must be a member and/or listed in the ONVIF website" -- the camera vendor's
    membership. Every bidder fails a clause like that, so it tells the evaluator nothing
    and drags the whole compliance dimension down.

    The filter is deliberately conservative: dropping something the company could have
    met would flatter it, so a clause survives whenever it mentions the analytics at
    all, even alongside hardware.
    """
    sys.path.insert(0, NODES_DIR)
    from common import rfp_scope

    OUT = [
        "IP CCTV System OEM for Cameras & VMS must be a member and/or listed in the ONVIF website.",
        "Bidder shall submit EMD of Rs 50 lakhs along with the technical bid.",
        "The bidder must have an average annual turnover of Rs 100 crore in the last 3 years.",
        "Cameras shall be IP66 rated with varifocal lens and shall comply with IS standards.",
        "The NVR shall provide 30 days of storage at full frame rate.",
        "Supplier shall deploy a resident engineer at site for the contract duration.",
    ]
    IN = [
        "FRS must support 1:1, 1:N and N:N matching using a CNN-based facial tracking technology.",
        "Video analytics shall run on GPU based servers in a centralized datacentre architecture.",
        "The analytics shall detect abandoned objects with accuracy not less than 90%.",
        "ANPR shall read number plates at vehicle speeds up to 80 kmph.",
        "FRS shall detect more than 20 faces in crowd and support yaw -40 to +40 degrees.",
    ]

    for text in OUT:
        assert not rfp_scope.is_in_scope(text), f"should have been dropped: {text[:70]}"
    for text in IN:
        assert rfp_scope.is_in_scope(text), f"should have been kept: {text[:70]}"

    kept, dropped = rfp_scope.in_scope(OUT + IN)
    assert len(kept) == len(IN) and len(dropped) == len(OUT)

    # The filter runs inside va-rfp-requirements, not in the agents. Filtering per
    # company would hand each bidder a differently-filtered list, which is the moving
    # denominator again -- so the canonical list has to be the scoped list.
    function_dir = os.path.join(NODES_DIR, "..", "functions", "va-rfp-requirements")
    source = open(os.path.join(function_dir, "function", "code", "function.py")).read()
    assert "rfp_scope.in_scope(" in source, (
        "va-rfp-requirements does not apply the scope filter")
    assert "self._scope(self._extract(" in source, (
        "va-rfp-requirements extracts without scoping, so out-of-scope clauses are cached")
    assert os.path.isfile(os.path.join(function_dir, "function", "code", "rfp_scope.py")), (
        "rfp_scope.py is not vendored into the function package; the import will fail "
        "in the pod (build.sh copies it)")

    print(f"  ok  out-of-scope requirements filtered ({len(OUT)} dropped, {len(IN)} kept)")


def check_stage_reports_survive_the_transport_envelope(by_company):
    """A subordinate's report must reach the next stage, not the envelope around it.

    Observed in the cluster: the delegate transport returns
    `{"data": {"is_error": false, "job_output": {...the report...}}}`. Unwrapping a
    single layer leaves the AgentResult envelope in place, so the Sizing Agent reads
    `compliance["covered_usecases"]` off a dict that has only `job_output`, `is_error`
    and `task_id`, finds nothing, and the company declines -- with a complete and
    correct compliance report sitting one level down. Every company declined this way
    before it was found, and nothing in the output said why.

    A `data` key belonging to the report itself must survive, so this checks
    over-unwrapping too.
    """
    report = {"covered_usecases": ["face_recognition", "anpr"], "met": 2, "total": 22}
    envelope = {"is_error": False, "error_data": {}, "task_id": "t", "job_output": report}

    shapes = {
        "delegate": {"data": envelope},
        "p2p": envelope,
        "nested twice": {"data": {"data": envelope}},
        "bare report": report,
    }

    for company in sorted(COMPANIES):
        module = importlib.import_module(f"{company}.bid_manager")
        agent = next(obj for name, obj in vars(module).items()
                     if isinstance(obj, type) and name.endswith("Agent"))
        for label, payload in shapes.items():
            got = agent._report_of(payload)
            assert got.get("covered_usecases") == ["face_recognition", "anpr"], (
                f"{company}: the {label} shape lost the report -- got keys {sorted(got)}")

        # The report's own `data` key is part of the report, not an envelope.
        own_data = agent._report_of({"job_output": {"covered_usecases": ["x"],
                                                    "data": {"k": 1}}})
        assert own_data.get("data") == {"k": 1}, (
            f"{company}: unwrapped past the report and ate its own 'data' key")
        assert agent._report_of("not a dict") == {}, f"{company}: non-dict must give {{}}"

    print(f"  ok  {len(COMPANIES)} bid managers unwrap every transport envelope")


def check_no_agent_imports_the_old_bidding_client(by_company):
    """video_analytics_bidding bids through agents_sdk's BiddingClient, and only that."""
    offenders = []
    for root, _dirs, files in os.walk(NODES_DIR):
        for filename in files:
            if filename.endswith(".py") and filename != "local_check.py":
                path = os.path.join(root, filename)
                with open(path) as fh:
                    if "openarcade_bidding_pysdk" in fh.read():
                        offenders.append(os.path.relpath(path, NODES_DIR))
    assert not offenders, f"still import the old OpenArcade client: {offenders}"
    for company in COMPANIES:
        with open(os.path.join(NODES_DIR, company, "bid_manager.py")) as fh:
            text = fh.read()
        assert "from agents_sdk.core.bidding_client import" in text, f"{company}: not on BiddingClient"
        assert "def on_bidding_task(" in text, f"{company}: no on_bidding_task"
    print(f"  ok  {len(COMPANIES)} bid managers use BiddingClient and none imports openarcade_bidding_pysdk")


def check_specs_carry_orcade_settings_and_topics(by_company):
    """Every spec supplies ORCADE_URL / ORCADE_POLL_SECONDS; only listeners carry topics.

    Topics live in `metadata.subject_metadata.topics`, never in `subject_search_tags`
    (generic labels for finding agents, not instructions about what to listen to). They
    come from the company's own config.yaml, so what XChange is told and what the agent
    polls for cannot disagree.
    """
    import yaml

    spec_dir = os.path.abspath(os.path.join(NODES_DIR, "..", "spec"))
    seen = listeners = 0
    for company in COMPANIES:
        with open(os.path.join(NODES_DIR, company, "config.yaml")) as fh:
            wanted_topics = (yaml.safe_load(fh)["company"].get("topics") or [])
        for filename in sorted(os.listdir(os.path.join(spec_dir, company))):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(spec_dir, company, filename)) as fh:
                spec = json.load(fh)
            where = f"{company}/{filename}"
            params = spec["persona"]["config"]["parameters"]
            assert params.get("ORCADE_URL") == "${OPENARCADE_BIDDING_URL}", f"{where}: ORCADE_URL"
            assert float(params.get("ORCADE_POLL_SECONDS", 0)) > 0, f"{where}: ORCADE_POLL_SECONDS"
            assert "OPENARCADE_BIDDING_URL" not in params, f"{where}: still carries the old name"
            meta = spec["metadata"]["subject_metadata"]
            if filename == "bid_manager.json":
                assert meta.get("topics", []) == wanted_topics, (
                    f"{where}: topics {meta.get('topics')} do not match config.yaml {wanted_topics}")
                listeners += bool(wanted_topics)
            else:
                assert "topics" not in meta, f"{where}: only a Bid Manager listens on topics"
            for topic in wanted_topics:
                assert topic not in spec["metadata"]["subject_search_tags"], (
                    f"{where}: topic {topic!r} is smuggled in as a search tag")
            seen += 1
    assert seen == 30 and listeners == 2, (seen, listeners)
    print(f"  ok  {seen} specs carry ORCADE_URL/ORCADE_POLL_SECONDS; {listeners} Bid Managers listen on topics")


def check_orcade_settings_resolve_env_then_spec(by_company):
    from common import orcade

    def subject(**params):
        return types.SimpleNamespace(
            persona=types.SimpleNamespace(config={"parameters": params}),
            metadata=types.SimpleNamespace(subject_metadata=params.pop("_meta", {})))

    saved = {k: os.environ.pop(k, None) for k in ("ORCADE_URL", "ORCADE_POLL_SECONDS")}
    try:
        spec = subject(ORCADE_URL="http://from-spec:5000", ORCADE_POLL_SECONDS="7")
        assert orcade.url(spec) == "http://from-spec:5000"
        assert orcade.poll_seconds(spec) == 7.0
        os.environ["ORCADE_URL"], os.environ["ORCADE_POLL_SECONDS"] = "http://from-pod:5000", "3"
        assert orcade.url(spec) == "http://from-pod:5000", "the pod's own value must win"
        assert orcade.poll_seconds(spec) == 3.0
        del os.environ["ORCADE_URL"], os.environ["ORCADE_POLL_SECONDS"]

        # `register.sh` ran without the key in .env: the placeholder is not an address.
        assert orcade.url(subject(ORCADE_URL="${OPENARCADE_BIDDING_URL}")) is None
        assert orcade.url(subject()) is None and orcade.url(types.SimpleNamespace()) is None
        for bad in ("soon", "0", "-5", ""):
            assert orcade.poll_seconds(subject(ORCADE_POLL_SECONDS=bad)) == orcade.DEFAULT_POLL_SECONDS, bad
        assert orcade.poll_seconds(subject()) == orcade.DEFAULT_POLL_SECONDS
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value

    def listening(topics):
        return types.SimpleNamespace(metadata=types.SimpleNamespace(
            subject_metadata={"topics": topics}, subject_search_tags=["ignored-tag"]))

    assert orcade.topics(listening(["a", " b ", "a", "", "c,d"])) == ["a", "b"]
    assert orcade.topics(listening("a, b")) == ["a", "b"]
    assert orcade.topics(listening(None)) == [] and orcade.topics(listening(7)) == []
    assert orcade.topics(types.SimpleNamespace()) == []
    assert orcade.topics(listening([])) == [], "search tags must never be read as topics"
    print("  ok  ORCADE_URL / ORCADE_POLL_SECONDS / topics resolve pod-first, spec-second, safely")


def check_discovery_claims_and_admits(by_company):
    from agents_sdk.core.bidding_client import BidJob
    from common.orcade import Discovery

    me = "ultravideotech-bid-manager"

    def job(job_id, mode, roster=()):
        return BidJob(bid_job_id=job_id, bid_job_mode=mode, bid_job_subject_ids=list(roster))

    d = Discovery(me, ["t"], grace=0.2, tick=0.01)
    assert d.claim("j1") and not d.claim("j1") and d.claim(None) and d.claim(None)

    assert d.admit(job("o1", "open")) is None and d.is_claimed("o1"), "an open job is applied to"
    assert d.admit(job("o1", "open")), "an open job is claimed once"
    assert d.admit(job("o2", "open", [me])), "an open job already applied to is left alone"
    assert d.admit(job("c1", "closed", ["other"])), "not on the roster: OpenArcade would refuse"
    assert d.admit(job("m1", "mixed", ["other"]))

    # A roster job: the bid_request is the primary route, so the poller waits for it...
    d.claim("m2")
    started = time.monotonic()
    assert d.admit(job("m2", "mixed", [me])), "bid_request got there first"
    assert time.monotonic() - started < 0.15, "should notice the claim at once, not run out the grace"

    # ...and takes over only when it never comes.
    started = time.monotonic()
    assert d.admit(job("m3", "mixed", [me])) is None, "bid_request never came; poll takes over"
    assert time.monotonic() - started >= 0.2, "must wait out the grace before taking over"
    assert not d.claim("m3"), "and the late bid_request now loses"

    # A bid_request arriving DURING the grace wins it.
    timer = threading.Timer(0.05, lambda: d.claim("m4"))
    timer.start()
    assert d.admit(job("m4", "mixed", [me])), "a bid_request that lands mid-grace must win"
    timer.join()
    print("  ok  one claim per job; open jobs applied to, roster jobs taken over only if the bid_request never came")


def check_polling_ignores_history_not_new_jobs(by_company):
    """The first poll is the baseline, or every restart re-runs every past round."""
    from agents_sdk.core.bidding_client import BiddingError, BidJob
    from common.orcade import Discovery

    me = "ultravideotech-bid-manager"

    def job(job_id, mode="mixed", roster=(me,), status="open"):
        return BidJob(bid_job_id=job_id, bid_job_mode=mode, bid_job_subject_ids=list(roster),
                      bid_job_status=status)

    class Server:
        def __init__(self):
            self.jobs = [job("old-mixed"), job("old-closed", "closed"), job("old-open", "open", ()),
                         job("old-done", "open", (), status="closed")]
            self.down = 2                 # an OpenArcade that does not have /by-tags yet
            self.queries = []

        def find_bid_jobs_by_tags(self, query):
            self.queries.append(query)
            if self.down:
                self.down -= 1
                raise BiddingError("No document found", 404)
            return list(self.jobs)

    class Agent:
        def __init__(self): self.heard = []
        def on_bidding_task(self, j): self.heard.append(j.bid_job_id)

    server, agent = Server(), Agent()
    discovery = Discovery(me, ["videoanalytics_bidding"], interval=0.03, grace=0, tick=0.01)
    assert discovery.start(agent, server)

    def wait_for(condition, what):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.02)
        raise AssertionError(f"timed out waiting for: {what}")

    wait_for(lambda: discovery._poller._thread.is_alive(), "polling to begin after the server came up")
    assert discovery.ignored == {"old-mixed", "old-closed"}, discovery.ignored
    query = server.queries[-1]
    assert set(query.effective_tags()) == {"videoanalytics_bidding", f"subject::{me}"}
    assert query.match == "any", "a topic OR a roster naming: either is reason to look"

    server.jobs.append(job("new-mixed"))
    server.jobs.append(job("new-open", "open", ()))
    wait_for(lambda: {"new-mixed", "new-open"} <= set(agent.heard), "new jobs to be delivered")
    time.sleep(0.15)
    assert sorted(agent.heard) == ["new-mixed", "new-open", "old-open"], (
        f"history must not be re-run, and an open job still open must be: {agent.heard}")
    assert len(agent.heard) == len(set(agent.heard)), "a job must be delivered once"
    discovery.stop(timeout=2)

    assert not Discovery(me, [], 1).start(agent, server), "no topics, no polling"
    assert not Discovery(me, ["t"], 1).start(agent, None), "topics but no URL: say so, do not crash"
    print("  ok  polling ignores rounds that already existed, retries until the server can answer, bids on new jobs once")


def check_polled_and_requested_jobs_run_once(by_company):
    """Both routes lead to the same pipeline, and a job must go through it once."""
    from agents_sdk.core.bidding_client import BidJob
    from agents_sdk.core.types import AgentResult, AgentTask
    from common.orcade import Discovery

    for company in COMPANIES:
        module = load_agent_module(company, "bid_manager")
        cls = next(obj for name, obj in vars(module).items()
                   if isinstance(obj, type) and name.endswith("BidManagerAgent"))
        me = f"{company.lower()}-bid-manager"

        def make():
            agent = cls.__new__(cls)
            agent.company, agent.slug, agent.default_model = company, company.lower(), "m"
            agent.subject = types.SimpleNamespace(identity=types.SimpleNamespace(subject_id=me))
            agent.task_registry = {}
            agent._report = lambda *a, **k: None
            agent._local = threading.local()
            agent._bid_lock = threading.Lock()
            agent._task_client, agent._poll_client = "task-client", "poll-client"
            agent.discovery = Discovery(me, ["t"], grace=0.1, tick=0.01)
            agent.runs, agent.clients = [], []

            def handle(task, task_id, session_id, comm_type, model_name):
                agent.runs.append(agent._task_entry(session_id, task_id).get("bid_job_id"))
                agent.clients.append(agent._client())
                return AgentResult(task_id=task_id, job_output={"ran": True})
            agent._handle_bid_request = handle
            return agent

        def request(job_id):
            return AgentTask(task_id="t", job_data={
                "type": "bid_request", "bid_job_id": job_id,
                "bid_job": {"bid_job_id": job_id, "bid_job_description": {"text": "x"}}})

        def polled(job_id, mode, roster=()):
            return BidJob(bid_job_id=job_id, bid_job_mode=mode, bid_job_subject_ids=list(roster),
                          bid_job_description={"text": "x", "rfp_url": "http://rfp"})

        # bid_request first, then the same job found by polling
        a = make()
        assert a.on_data(request("j1")).job_output == {"ran": True}
        a.on_bidding_task(polled("j1", "mixed", [me]))
        assert a.runs == ["j1"], f"{company}: ran {a.runs}"

        # found by polling first (an open job), then a bid_request for it
        a = make()
        a.on_bidding_task(polled("j2", "open"))
        assert a.runs == ["j2"]
        assert a.on_data(request("j2")).job_output["status"] == "duplicate", f"{company}: not deduped"
        assert a.runs == ["j2"]

        # a roster job whose bid_request is lost: the poller takes over
        a = make()
        a.on_bidding_task(polled("j3", "mixed", [me]))
        assert a.runs == ["j3"], f"{company}: polling did not rescue a lost bid_request"

        # not on the roster / already applied: no run
        a = make()
        a.on_bidding_task(polled("j4", "closed", ["someone-else"]))
        a.on_bidding_task(polled("j5", "open", [me]))
        assert a.runs == [], f"{company}: bid on a job it could not bid on"

        # each thread uses its own client (doc 7.5): the poller thread its poll client,
        # the Redis worker its task client -- on_data is not told which it is on
        a = make()
        a.on_data(request("j6"))
        worker = threading.Thread(target=a.on_bidding_task, args=(polled("j7", "open"),))
        worker.start(); worker.join()
        assert a.clients == ["task-client", "poll-client"], f"{company}: {a.clients}"

        # the HIS record says how the job arrived
        seen = []
        a = make()
        a._report = lambda event, payload, **k: seen.append((event, payload.get("source")))
        a.on_bidding_task(polled("j8", "open"))
        assert ("INCOMING_TASK", "poll") in seen, f"{company}: polled work is not marked as polled"

    print(f"  ok  {len(COMPANIES)} bid managers run a job once however it is found, each thread on its own client")


def check_every_spec_uses_openai_and_one_key(by_company):
    """Every agent runs an OpenAI model on OPENAI_API_KEY, in both examples.

    The VA template once paired `openai:gpt-5.4-mini` with `${GEMINI_API_KEY}`. OpenAI
    answered 401 to the Gemini key, every Bid Manager failed its first model call, and all
    five companies declined at qualification: the round "worked" and produced no winner.
    Nothing in a spec checks that the key belongs to the model, so this does.
    """
    repo = os.path.abspath(os.path.join(NODES_DIR, "..", ".."))
    patterns = [os.path.join(NODES_DIR, "..", "spec", "*", "*.json"),
                os.path.join(repo, "bids_processing", "spec", "*.json")]
    checked = 0
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            name = os.path.relpath(path, repo)
            with open(path) as fh:
                spec = json.load(fh)
            params = spec["persona"]["config"]["parameters"]
            assert params.get("api_key") == "${OPENAI_API_KEY}", f"{name}: persona api_key is {params.get('api_key')!r}"
            assert str(params.get("AGENT_SELECTOR_LLM", "")).startswith("openai:"), f"{name}: selector model"
            models = spec["integrations"]["models"]
            assert models, f"{name}: no model block"
            for block in models:
                assert block["llm_type"] == "openai" and block["llm_block_id"].startswith("openai:"), (
                    f"{name}: {block['llm_block_id']} is not an OpenAI model")
                assert block["llm_parameters"].get("api_key") == "${OPENAI_API_KEY}", (
                    f"{name}: {block['llm_block_id']} carries api_key {block['llm_parameters'].get('api_key')!r}")
            with open(path) as fh:
                assert "GEMINI" not in fh.read().upper(), f"{name}: still mentions Gemini"
            checked += 1
    assert checked >= 48, f"expected 30 VA + 18 bids_processing specs, checked {checked}"
    print(f"  ok  all {checked} specs (both examples) use OpenAI models with ${{OPENAI_API_KEY}}")


def check_secrets_never_reach_the_logs(by_company):
    """No API key, MinIO key or token may reach a container log.

    A mesh `join`/`presence` message carries the sender's whole subject spec, credentials
    included, and the SDK logged every one in full -- 68 times in one Bid Manager's log,
    plus once more when the model pool was built. This drives the real code paths with a
    fake key and reads what they actually wrote.
    """
    import asyncio
    import io

    from agents_sdk.core.db.schema import Subject
    from agents_sdk.core.log_safe import redact, scrub

    FAKE = "sk-FAKE-0123456789-abcdefghijklmnopqrstuvwxyz"
    MINIO = "minio-FAKE-secret-9876543210"
    with open(os.path.join(NODES_DIR, "..", "spec", "UltraVideoTech", "bid_manager.json")) as fh:
        raw = fh.read().replace("${OPENAI_API_KEY}", FAKE).replace("${MINIO_SECRET_KEY}", MINIO)
    spec = json.loads(raw)
    message = {"event": "join", "peer": spec, "n": 3}

    # -- the redactor itself ------------------------------------------------------------
    for shape, value in (("dict", message), ("bytes", json.dumps(message).encode()),
                         ("str", json.dumps(message)), ("Subject", Subject.from_dict(spec)),
                         ("list", [message, {"x": [message]}])):
        out = str(redact(value))
        assert FAKE not in out and MINIO not in out, f"redact leaked a secret from a {shape}"
    out = str(redact(message))
    for kept in ("max_completion_tokens", "openai:gpt-5.4-mini", "ultravideotech-bid-manager", "'n': 3"):
        assert kept in out, f"redact threw away something that is not a secret: {kept}"
    assert message["peer"]["persona"]["config"]["parameters"]["api_key"] == FAKE, "redact mutated its input"
    assert scrub("api_key='abc' max_tokens=5 PASSWORD: \"x\"") == "api_key='***' max_tokens=5 PASSWORD: \"***\""

    # -- the real model pool: the log is clean, the OpenAI client still gets the key ----
    try:
        import google.genai  # noqa: F401
        stubbed = False
    except ImportError:
        import google
        stub = types.ModuleType("google.genai")
        stub.types = types.ModuleType("google.genai.types")
        sys.modules["google.genai"], google.genai = stub, stub
        stubbed = True

    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        path = os.path.join(REPO_ROOT, "bids_example", "utils", "dspy_aios_llms.py")
        module_spec = importlib.util.spec_from_file_location("real_dspy_aios_llms", path)
        real = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(real)

        handed_over = {}
        original = real.OpenAIBlockInferenceSystem

        class Spy(original):
            def __init__(self, **kwargs):
                handed_over["api_key"] = kwargs.get("api_key")
                super().__init__(**kwargs)
        real.OpenAIBlockInferenceSystem = Spy
        pool = real.AIOS_DSPy_LMs(Subject.from_dict(spec)).model_pool
        assert "openai:gpt-5.4-mini" in pool
        assert handed_over.get("api_key") == FAKE, "redaction must not touch the key the client uses"

        # -- the real mesh publish path ------------------------------------------------
        from agents_sdk.core import p2p
        try:
            asyncio.run(p2p.PeersManager._publish_raw(
                types.SimpleNamespace(_meshes={}), "mesh-a", "subject", message))
        except ValueError:
            pass            # no such mesh -- the log line is written before that is noticed
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
        if stubbed:
            del sys.modules["google.genai"]
            del google.genai

    written = buffer.getvalue()
    assert "Adding model openai:gpt-5.4-mini" in written, "the model-pool line was not written"
    assert "[p2p raw publish]" in written, "the publish line was not written"
    assert FAKE not in written and MINIO not in written, "a secret reached the log"

    # -- and it stays that way: no unwrapped payload in a log call -----------------------
    watched = {
        os.path.join(REPO_ROOT, "bids_example", "agents_sdk", "core", "p2p.py"):
            ("{payload}", "{obj}", "{msg.data"),
        os.path.join(REPO_ROOT, "bids_example", "utils", "dspy_aios_llms.py"):
            ("{llm_params}", "{blockDetails}", "{oneBlock}", "{api_key}"),
    }
    for path, names in watched.items():
        with open(path) as fh:
            for number, line in enumerate(fh, 1):
                if ("log." in line or "logger." in line) and any(n in line for n in names):
                    assert "redact(" in line, f"{os.path.basename(path)}:{number} logs {line.strip()[:90]}"
    print("  ok  secrets never reach a log: redactor, model pool and mesh publish checked with a fake key")


def check_specs_supply_every_setting_the_agents_need(by_company):
    """Every setting an agent reads must arrive from its spec, or from the pod.

    The agent image carries only a few keys out of the repo `.env`, so anything else --
    MinIO, the function registry, HIS -- has to come from `persona.config.parameters`,
    which `spec_env.apply()` copies into the environment at start-up.

    A setting that is in neither place does not break the build and does not break
    start-up. The pod comes up healthy and fails much later, mid-round, as
    "INTERNAL_IP and MINIO_INTERNAL_PORT must be set". That cost a full
    build-deploy-run cycle to find, which is why it is checked here.
    """
    import re

    sys.path.insert(0, NODES_DIR)
    from common import spec_env

    # Set by the deployer on the pod itself; never present in a spec.
    INJECTED = {"SUBJECT_ID", "INSTANCE_ID", "MESH_LIST", "AGENT",
                "JOB_EXCHANGE_API_URL", "SUBJECT_DB_URL", "AGENT_DELEGATE_URL"}
    # Developer-machine only: the off-cluster checks in this file, never a pod.
    OFF_CLUSTER = {"AGENTS_SDK_PATH", "PYTHONPATH"}
    # Documented overrides with working defaults -- absence is not a failure.
    OPTIONAL = {"VA_MINIO_CONNECT_TIMEOUT", "VA_MINIO_READ_TIMEOUT"}
    # Reached only when MINIO_CONFIG is absent, which the spec check below rules out.
    FALLBACK = {"INTERNAL_IP", "EXTERNAL_IP"}

    wanted = set()
    for root, _dirs, files in os.walk(NODES_DIR):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            with open(os.path.join(root, filename)) as fh:
                text = fh.read()
            wanted |= set(re.findall(r'os\.environ(?:\.get\(|\[)"([A-Z][A-Z0-9_]*)"', text))
            for pair in re.findall(
                    r'_addr\(\s*"([A-Z][A-Z0-9_]*)"\s*,\s*"([A-Z][A-Z0-9_]*)"', text):
                wanted |= set(pair)

    wanted -= INJECTED | OFF_CLUSTER | OPTIONAL | FALLBACK
    assert wanted, "found no environment keys to check -- the matcher is broken"

    supplied = set(spec_env.MINIO_KEYS.values()) | set(spec_env.PASSTHROUGH) | {"HIS_BASE_URL"}
    unsupplied = sorted(wanted - supplied)
    assert not unsupplied, (
        "the agents read settings nothing supplies: " + ", ".join(unsupplied) + ".\n"
        "    Add them to the spec template and map them in common/spec_env.py.")

    # And the specs must actually carry what spec_env expects to find.
    spec_dir = os.path.abspath(os.path.join(NODES_DIR, "..", "spec"))
    required = {"MINIO_URL", "MINIO_EXTERNAL_URL", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"}
    checked = 0
    for company in sorted(os.listdir(spec_dir)):
        company_dir = os.path.join(spec_dir, company)
        if not os.path.isdir(company_dir):
            continue
        for filename in sorted(os.listdir(company_dir)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(company_dir, filename)) as fh:
                params = json.load(fh)["persona"]["config"]["parameters"]
            where = f"{company}/{filename}"
            minio = params.get("MINIO_CONFIG")
            assert isinstance(minio, dict), f"{where}: no MINIO_CONFIG"
            missing = sorted(required - set(minio))
            assert not missing, f"{where}: MINIO_CONFIG missing {', '.join(missing)}"
            checked += 1

    assert checked == 30, f"expected 30 specs, checked {checked}"
    print(f"  ok  {checked} specs supply every setting the agents read "
          f"({len(wanted)} keys)")


def main():
    logging.basicConfig(level=logging.ERROR)
    install_stubs()
    by_company = load_known_agents()
    print(f"\nloaded {sum(len(v) for v in by_company.values())} specs "
          f"across {len(by_company)} companies\n")

    for check in (check_every_bid_manager_imports,
                  check_discovery_finds_every_role,
                  check_no_cross_company_leakage,
                  check_fallback_matches_discovery,
                  check_declining_bid_carries_credentials,
                  check_bid_numbers_are_normalised,
                  check_coverage_ignores_generic_words,
                  check_decline_paths,
                  check_endpoint_cap,
                  check_no_answer_key_in_any_config,
                  check_malformed_verdicts_are_unmet,
                  check_sizing_asymmetry,
                  check_sizing_refuses_meaningless_input,
                  check_finance_ordering,
                  check_workbooks_are_written_correctly,
                  check_all_thirty_modules_import,
                  check_reviewer_catches_structural_gaps,
                  check_reviewer_reports_rather_than_vetoes,
                  check_head_approves_the_three_bidders,
                  check_head_refuses_an_incomplete_bid,
                  check_head_refuses_an_unviable_cost_base,
                  check_every_agent_reports_to_his,
                  check_his_reporting_never_raises,
                  check_specs_carry_his_config,
                  check_shell_scripts_guard_empty_jq_output,
                  check_out_of_scope_requirements_are_filtered,
                  check_the_denominator_is_the_rfps_requirement_count,
                  check_compliance_has_no_private_requirement_path,
                  check_the_dossier_answers_what_the_rfp_asks,
                  check_the_dossier_reaches_the_verdict_model,
                  check_stage_reports_survive_the_transport_envelope,
                  check_submission_survives_timeouts_and_pqt_rejection,
                  check_no_agent_imports_the_old_bidding_client,
                  check_specs_carry_orcade_settings_and_topics,
                  check_orcade_settings_resolve_env_then_spec,
                  check_discovery_claims_and_admits,
                  check_polling_ignores_history_not_new_jobs,
                  check_polled_and_requested_jobs_run_once,
                  check_every_spec_uses_openai_and_one_key,
                  check_secrets_never_reach_the_logs,
                  check_specs_supply_every_setting_the_agents_need):
        check(by_company)

    print("\nall local checks passed -- end-to-end validation still belongs in the cluster\n")


if __name__ == "__main__":
    main()
