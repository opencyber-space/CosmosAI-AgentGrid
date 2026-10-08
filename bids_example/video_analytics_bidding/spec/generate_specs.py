"""Generate the 30 agent specs (6 roles x 5 companies) from `_template.json`.

Run from this directory:  ../../../venv/bin/python generate_specs.py

The specs are generated rather than hand-written because they differ only in identity
and wording -- the structure is identical, and thirty hand-maintained copies would drift.
The *agent modules* under `nodes/` are a different matter: those are deliberately
standalone so a company can behave differently in ways `config.yaml` cannot express.

Re-running overwrites the specs in place, so edit this script (or the template) rather
than the generated files.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
NODES_DIR = os.path.abspath(os.path.join(HERE, "..", "nodes"))
TEMPLATE = os.path.join(HERE, "_template.json")

COMPANIES = [
    ("CamFaceSolution", "camfacesolution"),
    ("MultiFaceTech", "multifacetech"),
    ("NewGenTech", "newgentech"),
    ("UltraVideoTech", "ultravideotech"),
    ("VideoProcTech", "videoproctech"),
]

# Roles in the order the Bid Manager consults them. `module` is the file under
# nodes/<Company>/ that the pod runs.
ROLES = {
    "bid_manager": {
        "module": "bid_manager",
        "suffix": "bid-manager",
        "description": (
            "Bid Manager for {company}. Receives bid requests from the bidding system, decides "
            "whether the work is Video Analytics, coordinates the company's subordinate agents in "
            "sequence, and submits or declines the bid. The only agent that speaks outside the company."
        ),
        "goal": (
            "Qualify incoming bid requests, drive compliance, sizing, finance, review and approval "
            "in order, and submit exactly one bid -- priced or declining -- for every request."
        ),
        "persona": "Decisive coordinator. Answers every request, never leaves one unanswered.",
        "system_message": "You are the Bid Manager for {company}.",
        "traits": ["orchestrator", "decisive", "accountable"],
        "tags": ["bid-manager", "video-analytics", "coordinator", "openarcade"],
        "llm_task": "classification",
        "cpu": 2,
        "memory_mb": 4096,
    },
    "ai_compliance": {
        "module": "ai_compliance",
        "suffix": "ai-compliance",
        "description": (
            "AI Compliance Agent for {company}. Reads the RFP, compares its use cases, operating "
            "conditions, accuracy and certification requirements against the company's catalogue, "
            "scores compliance, and stands up the live use-case endpoints the evaluator will call."
        ),
        "goal": (
            "Produce a per-requirement compliance verdict with a met/total summary, and register up "
            "to two verified live use-case endpoints."
        ),
        "persona": "Exacting analyst. Reports what the catalogue actually covers, not what it might.",
        "system_message": "You are the AI Compliance Agent for {company}.",
        "traits": ["analytical", "literal", "thorough"],
        "tags": ["compliance", "video-analytics", "usecase-matching", "rfp"],
        "llm_task": "analysis",
        "cpu": 2,
        "memory_mb": 6144,
    },
    "sizing": {
        "module": "sizing",
        "suffix": "sizing",
        "description": (
            "Sizing Agent for {company}. Scales the company's per-licence hardware ratios by the "
            "licence counts the RFP asks for, fills the buyer's sizing template, and reports single "
            "totals for CPU, RAM, disk and accelerators."
        ),
        "goal": "Produce a filled sizing workbook and four authoritative hardware totals.",
        "persona": "Methodical engineer. Numbers are computed, never estimated in prose.",
        "system_message": "You are the Sizing Agent for {company}.",
        "traits": ["methodical", "quantitative", "precise"],
        "tags": ["sizing", "hardware", "capacity-planning", "video-analytics"],
        "llm_task": "analysis",
        "cpu": 1,
        "memory_mb": 4096,
    },
    "finance": {
        "module": "finance",
        "suffix": "finance",
        "description": (
            "Finance Agent for {company}. Prices the RFP's use cases and licence counts against the "
            "company's rate card, fills the buyer's commercial template, and reports a single total "
            "budget alongside one-time and recurring costs."
        ),
        "goal": "Produce a filled commercial workbook and one authoritative total budget figure.",
        "persona": "Careful commercial lead. States one number and stands behind it.",
        "system_message": "You are the Finance Agent for {company}.",
        "traits": ["commercial", "precise", "conservative"],
        "tags": ["finance", "pricing", "commercials", "video-analytics"],
        "llm_task": "analysis",
        "cpu": 1,
        "memory_mb": 4096,
    },
    "bid_reviewer": {
        "module": "bid_reviewer",
        "suffix": "bid-reviewer",
        "description": (
            "Bid Reviewer Agent for {company}. Checks that every requirement the RFP states has a "
            "corresponding artifact in the assembled bid. Verifies coverage, not numeric correctness, "
            "and reports rather than vetoes."
        ),
        "goal": (
            "State plainly what the bid covers and what it is missing, so the Head Agent can decide "
            "with the gaps in front of it."
        ),
        "persona": "Diligent reviewer. Lists what is missing without deciding whether it is fatal.",
        "system_message": "You are the Bid Reviewer Agent for {company}.",
        "traits": ["diligent", "systematic", "plain-spoken"],
        "tags": ["bid-review", "coverage", "quality-gate", "video-analytics"],
        "llm_task": "analysis",
        "cpu": 1,
        "memory_mb": 4096,
    },
    "head": {
        "module": "head",
        "suffix": "head",
        "description": (
            "Head Agent for {company}. Final authority on whether the company bids: weighs financial "
            "viability, certification evidence and past-project track record against the RFP, and "
            "approves or refuses."
        ),
        "goal": "Approve the bid only when it is commercially viable and evidentially supportable.",
        "persona": "Accountable approver. Refuses when the evidence is not there.",
        "system_message": "You are the Head Agent for {company}, the final approver.",
        "traits": ["authoritative", "risk-aware", "decisive"],
        "tags": ["approval", "governance", "head-agent", "video-analytics"],
        "llm_task": "reasoning",
        "cpu": 1,
        "memory_mb": 4096,
    },
}


def subject_id(company_slug, role_key):
    return f"{company_slug}-{ROLES[role_key]['suffix']}"


def render(company, company_slug, role_key, topics=()):
    with open(TEMPLATE) as fh:
        text = fh.read()

    role = ROLES[role_key]
    sid = subject_id(company_slug, role_key)

    replacements = {
        "__SUBJECT_ID__": sid,
        "__COMPANY__": company,
        "__COMPANY_SLUG__": company_slug,
        "__ROLE__": role_key,
        "__DESCRIPTION__": role["description"].format(company=company),
        "__GOAL__": role["goal"].format(company=company),
        "__PERSONA__": role["persona"],
        "__SYSTEM_MESSAGE__": role["system_message"].format(company=company),
        "__LLM_TASK__": role["llm_task"],
        "__CPU_CORES__": str(role["cpu"]),
        "__MEMORY_MB__": str(role["memory_mb"]),
        "__SEARCH_TAGS__": json.dumps(role["tags"] + [company_slug]),
        "__TRAITS__": json.dumps(role["traits"]),
    }
    for placeholder, value in replacements.items():
        # JSON-escape string substitutions; the list/number ones are already literal.
        if placeholder in ("__SEARCH_TAGS__", "__TRAITS__", "__CPU_CORES__", "__MEMORY_MB__"):
            text = text.replace(placeholder, value)
        else:
            text = text.replace(placeholder, json.dumps(value)[1:-1])

    spec = json.loads(text)   # parse, so a bad substitution fails here rather than at registration

    # The topics an agent listens on live in `metadata.subject_metadata.topics` -- not in
    # `subject_search_tags`, which are generic labels for searching and querying agents.
    # Only a Bid Manager listens: it is the one agent that bids. The list is the company's
    # own `company.topics` from config.yaml, the same one register_subjects_in_Exchange.sh
    # registers with XChange, so the marketplace and the agent cannot disagree. A company
    # that listens on nothing gets no key at all.
    if role_key == "bid_manager" and topics:
        spec["metadata"]["subject_metadata"]["topics"] = list(topics)
    return sid, spec


def main():
    written = 0
    for company, company_slug in COMPANIES:
        out_dir = os.path.join(HERE, company)
        os.makedirs(out_dir, exist_ok=True)

        # Cross-check against the company's own config, so a spec can never claim a
        # subject id the agents do not use.
        config_path = os.path.join(NODES_DIR, company, "config.yaml")
        expected_manager = None
        topics = []
        if os.path.exists(config_path):
            import yaml
            with open(config_path) as fh:
                company_block = (yaml.safe_load(fh) or {}).get("company", {})
            expected_manager = company_block.get("subject_id")
            topics = company_block.get("topics") or []

        for role_key, role in ROLES.items():
            sid, spec = render(company, company_slug, role_key, topics)
            if role_key == "bid_manager" and expected_manager and sid != expected_manager:
                raise SystemExit(
                    f"{company}: spec subject_id {sid!r} does not match config.yaml "
                    f"company.subject_id {expected_manager!r}"
                )
            path = os.path.join(out_dir, f"{role['module']}.json")
            with open(path, "w") as fh:
                json.dump(spec, fh, indent=4)
                fh.write("\n")
            written += 1
        print(f"  {company}: {len(ROLES)} specs")

    print(f"\n{written} agent specs written under {HERE}")


if __name__ == "__main__":
    main()
