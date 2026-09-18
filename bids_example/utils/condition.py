import re
from dataclasses import dataclass
from typing import List, Literal, Dict

BUG_KEYWORDS = [
    "error", "exception", "crash", "crashes", "panic", "fail", "failed", "failing",
    "bug", "regression", "timeout", "hang", "stuck", "unexpected", "wrong result",
    "segfault", "stack trace", "traceback", "null pointer", "oom", "out of memory",
    "issue", "broken", "fix", "fixme", "refactor bug", "handle bug", "problem", "incorrect", "repro", "reproduction",
    "bad", "not working", "fails", "failing", "erroring", "crashing"
]

FEATURE_KEYWORDS = [
    "add", "support", "allow", "enable", "implement", "introduce", "enhance",
    "improve", "feature", "request", "proposal", "rfc", "capability", "option",
    "flag", "configurable", "setting", "new", "update", "optimization"
]

ENV_HINTS = [
    "ubuntu", "debian", "windows", "macos", "rhel", "centos", "kubernetes",
    "docker", "gpu", "nvidia", "amd", "intel", "python", "node", "java",
    "vllm", "qwen", "redis", "postgres"
]

@dataclass
class RouteResult:
    route: Literal["bug", "feature"]
    reasons: List[str]
    scores: Dict[str, int]

def _count_hits(text: str, keywords: List[str]) -> int:
    total = 0
    for kw in keywords:
        # word boundary for single words; substring for phrases
        if " " in kw:
            total += len(re.findall(re.escape(kw), text))
        else:
            total += len(re.findall(rf"\b{re.escape(kw)}\b", text))
    return total

def route(normalized_text: str) -> RouteResult:
    t = normalized_text.lower()
    bug_hits = _count_hits(t, BUG_KEYWORDS)
    feat_hits = _count_hits(t, FEATURE_KEYWORDS)
    env_hits = _count_hits(t, ENV_HINTS)

    # simple scoring with tie-breakers
    score_bug = bug_hits * 3 + env_hits
    score_feat = feat_hits * 3

    if score_bug > score_feat:
        route_choice = "bug"
    elif score_feat > score_bug:
        route_choice = "feature"
    else:
        # default to feature if strictly tied and no hard bug words
        route_choice = "bug" if bug_hits > 0 else "feature"

    reasons = []
    if bug_hits:
        reasons.append(f"bug_hits={bug_hits}")
    if feat_hits:
        reasons.append(f"feature_hits={feat_hits}")
    if env_hits:
        reasons.append(f"env_context={env_hits}")

    return RouteResult(
        route=route_choice,
        reasons=reasons or ["no strong signals"],
        scores={"bug": score_bug, "feature": score_feat}
    )