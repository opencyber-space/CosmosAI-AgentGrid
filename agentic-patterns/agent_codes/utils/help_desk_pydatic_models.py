from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional, Dict, Literal, Any, Type, TypeVar
import json
import logging

# reusable small models
class Step(BaseModel):
    who: Literal["user", "system", "agent"]
    action: str
    estimated_time_minutes: int
    priority: Literal["low", "medium", "high"]
    actor: Optional[str] = None

class Escalation(BaseModel):
    escalate_to: str
    reason: str

# Router output
class RouterOutput(BaseModel):
    selected_agents: List[str]
    reasoning: Dict[str, str]
    confidence: Dict[str, float]

# Tech agent output
class TechOutput(BaseModel):
    domain: Literal["tech"]
    summary: str
    diagnosis: List[str]
    steps: List[Step]
    evidence_needed: List[str]
    can_resolve: bool
    escalation_recommendation: Optional[Escalation] = None

# Billing agent output
class BillingOutput(BaseModel):
    domain: Literal["billing"]
    summary: str
    findings: List[str] = []
    actions: List[Step] = []
    refund_possible: Literal["yes", "no", "unknown"]
    required_info: List[str] = []
    escalation: Optional[Escalation] = None

# Account agent output
class AccountOutput(BaseModel):
    domain: Literal["account"]
    summary: str
    current_account_state: str
    actions: List[Step] = []
    security_notes: List[str] = []
    required_info: List[str] = []
    escalation: Optional[Escalation] = None

# Combined action used by Synthesizer
class CombinedAction(BaseModel):
    who: Literal["user", "system", "agent"]
    action: str
    estimated_time_minutes: int
    priority: Literal["low", "medium", "high"]
    source: List[str]  # list of agent names recommending this
    actor: Optional[str] = None

# Synthesizer output
class SynthesizerOutput(BaseModel):
    final_summary: str
    sections: Dict[str, Any] = {}  # will contain keys like "tech","billing","account" with their agent outputs
    combined_actions: List[CombinedAction] = []
    questions_for_user: List[str] = []
    next_steps: List[str] = []
    confidence: float = Field(0.8, ge=0.0, le=1.0)
    needs_escalation: bool
    escalation_targets: List[str] = []

class SecurityOutput(BaseModel):
    domain: Literal["security"]
    summary: str
    risk_level: Literal["low", "medium", "high"]
    indicators: List[str] = []
    recommended_actions: List[Step] = []
    required_info: List[str] = []
    escalation: Optional[Escalation] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

class ComplianceOutput(BaseModel):
    domain: Literal["compliance"]
    summary: str
    issue_type: Literal["gdpr", "dmca", "subpoena", "other"]
    allowed_actions: List[str] = []
    blocked_actions: List[str] = []
    required_documents: List[str] = []
    recommended_process: List[Step] = []
    escalation: Optional[Escalation] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

class CXOutput(BaseModel):
    domain: Literal["cx"]
    summary: str
    sentiment: Literal["neutral", "positive", "negative", "angry", "upset"]
    csat_risk: Literal["low", "medium", "high"]
    recommended_actions: List[Step] = []
    proposed_compensation: Optional[str] = None
    escalation: Optional[Escalation] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

T = TypeVar("T")

logger = logging.getLogger("helpdesk_validator")
logger.setLevel(logging.INFO)
# configure handler if not already set in your app
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

def _normalize_who_value(who_raw: Any) -> (str, str | None):
    """
    Normalize a single who value.
    Returns (normalized_who, actor_if_any)
    """
    if not isinstance(who_raw, str):
        return who_raw, None

    low = who_raw.strip().lower()
    if low in ("user", "system", "agent"):
        return low, None

    # heuristics: treat anything containing 'agent' or a dash as an agent name
    if "agent" in low or "-" in who_raw:
        return "agent", who_raw

    # fallback: if it's short like 'admin' treat as system, else agent
    if low in ("admin", "support", "system"):
        return "system", who_raw
    # default to agent but preserve original
    return "agent", who_raw

def fill_synthesizer_defaults(obj: dict) -> dict:
    """
    Ensure minimum required keys exist and that combined_actions entries include 'source'.
    Mutates and returns obj.
    """
    # Top-level defaults
    obj.setdefault("final_summary", "")
    obj.setdefault("sections", {})
    obj.setdefault("combined_actions", [])
    obj.setdefault("questions_for_user", [])
    obj.setdefault("next_steps", [])
    # default confidence (0.0-1.0)
    obj.setdefault("confidence", 0.0)
    obj.setdefault("needs_escalation", False)
    obj.setdefault("escalation_targets", [])

    # Ensure combined_actions items have required fields and correct types
    ca = obj["combined_actions"]
    if not isinstance(ca, list):
        obj["combined_actions"] = []
    else:
        new_ca = []
        for item in ca:
            if not isinstance(item, dict):
                continue
            # fill minimal CombinedAction fields if missing
            item.setdefault("who", "agent")
            item.setdefault("action", "no-op")
            item.setdefault("estimated_time_minutes", 0)
            item.setdefault("priority", "low")
            # fill or infer source: prefer existing, else use [actor] if present, else empty list
            if "source" not in item or not isinstance(item["source"], list):
                inferred = []
                if item.get("actor"):
                    inferred = [item["actor"]]
                item["source"] = inferred
            new_ca.append(item)
        obj["combined_actions"] = new_ca

    return obj

def normalize_all_who_fields(obj: Any) -> Any:
    """
    Recursively walk JSON-like structure and normalize any dict that has a 'who' key.
    For each dict with a 'who' key:
      - replace dict['who'] with normalized literal 'user'|'system'|'agent'
      - if original value wasn't one of the literals, add dict['actor'] = original_value
    Returns the normalized object (mutates in-place but also returns it).
    """
    if isinstance(obj, dict):
        # If dict has a 'who' key, normalize it
        if "who" in obj:
            original = obj.get("who")
            normalized, actor = _normalize_who_value(original)
            obj["who"] = normalized
            if actor is not None:
                # only add actor if it doesn't already exist
                if "actor" not in obj:
                    obj["actor"] = actor

        # Recurse into all values
        for k, v in list(obj.items()):
            obj[k] = normalize_all_who_fields(v)
        return obj

    elif isinstance(obj, list):
        return [normalize_all_who_fields(item) for item in obj]

    else:
        return obj

def validate_helpdesk_llm_output(raw_text: str, model: Type[T]) -> T:
    """
    Parse raw JSON from LLM, normalize 'who' fields, then validate with Pydantic model.
    Raises ValueError for invalid JSON and ValidationError for Pydantic validation issues.
    """
    # 1) parse JSON
    try:
        parsed_json = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON from LLM: %s", exc)
        raise ValueError(f"Invalid JSON from LLM: {exc}")

    # 2) log raw (shortened) for debug
    try:
        logger.info("Raw LLM JSON (truncated): %s", json.dumps(parsed_json)[:1000])
    except Exception:
        logger.info("Raw LLM JSON could not be serialized for logging.")

    # 3) normalize all 'who' fields recursively
    normalized = normalize_all_who_fields(parsed_json)

    # 4) log normalized (shortened)
    try:
        logger.info("Normalized LLM JSON (truncated): %s", json.dumps(normalized)[:1000])
    except Exception:
        logger.info("Normalized LLM JSON could not be serialized for logging.")

    # 5) validate using pydantic
    try:
        normalized = fill_synthesizer_defaults(normalized)
        validated = model.parse_raw(json.dumps(normalized))
        return validated
    except ValidationError as ve:
        # include normalized json in the error log to help debugging
        logger.error("Pydantic validation failed. Normalized JSON: %s", json.dumps(normalized, indent=2)[:4000])
        raise

# Example usage:
# router_parsed = validate_llm_output(router_llm_text, RouterOutput)
# if "billing-agent" in router_parsed.selected_agents:
#     billing_parsed = validate_llm_output(billing_llm_text, BillingOutput)