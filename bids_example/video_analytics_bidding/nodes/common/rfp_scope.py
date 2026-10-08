"""Which RFP requirements a video analytics supplier can actually answer.

A smart-city tender procures a whole system. Most of its clauses bind somebody else --
the camera OEM, the VMS vendor, the server supplier, the civil contractor -- and a
video analytics company can neither satisfy nor fail them. Scored against them it looks
non-compliant for things that were never its to provide, and the compliance dimension
stops saying anything about the bidders.

The extraction prompt already asks for analytics-only requirements. This is the second
line: prompts drift, and a clause like "IP CCTV System OEM for Cameras & VMS must be a
member and/or listed in the ONVIF website" came back scored against the analytics
catalogue in a real round.

Deliberately conservative. Dropping a requirement the company could have met would
flatter it, so a clause is only dropped when it names another party's obligation and
says nothing about the analytics itself.
"""
import re

# Clauses that belong to another supplier or to the tender process. Each is matched
# against the whole requirement, and only fires when no analytics subject is present.
OUT_OF_SCOPE = (
    # Somebody else's equipment
    r"\b(camera|lens|housing|enclosure|pole|mount(ing)?|cabl(e|ing)|conduit|junction box)\b.*\b(shall|must|should|specification|comply)",
    r"\b(OEM|manufacturer)\b.*\b(ONVIF|membership|listed|empanel|country of origin|make in india|turnover|financial)",
    r"\bONVIF\b.*\b(member|website|listed)\b",
    r"\b(NVR|VMS|encoder|decoder|storage appliance|SAN|NAS)\b.*\b(shall|must|supply|provide|specification)",
    r"\b(switch|router|firewall|bandwidth|fibre|fiber|UPS|power|earthing|rack)\b.*\b(shall|must|supply|provide)",
    r"\b(civil work|site preparation|foundation|physical security|air ?condition)",
    # Tender process and contract administration
    r"\b(EMD|earnest money|bid security|performance bank guarantee|PBG|tender fee)\b",
    r"\b(turnover|net worth|balance sheet|audited|ITR|GST registration|solvency)\b",
    r"\b(submit|enclose|furnish)\b.*\b(document|certificate copy|undertaking|affidavit|format|annexure)\b",
    r"\b(payment term|penalty|liquidated damages|arbitration|jurisdiction|termination)\b",
    r"\b(manpower|deployment of staff|resident engineer|shift roster|helpdesk staff)\b",
)

# If a requirement talks about the analytics itself, it stays -- even when it also
# mentions hardware. "analytics shall run on GPU servers" constrains how the analytics
# is delivered and is the supplier's to answer.
ANALYTICS_SUBJECT = (
    r"\b(video analytics|analytics|VA software|FRS|facial recognition|face recognition|"
    r"ANPR|number plate|intrusion|loitering|crowd|abandoned object|behaviour|behavior|"
    r"detection|recognition|classification|tracking|re-?identification|inference|"
    r"model|algorithm|accuracy|false (accept|reject|alarm)|precision|recall)\b"
)

_OUT = [re.compile(p, re.I) for p in OUT_OF_SCOPE]
_ANALYTICS = re.compile(ANALYTICS_SUBJECT, re.I)


def is_in_scope(requirement):
    """True when a video analytics supplier could satisfy or fail this on its own."""
    text = str(requirement or "").strip()
    if not text:
        return False
    for pattern in _OUT:
        if pattern.search(text):
            # Another party's obligation -- unless the clause is also about the
            # analytics, in which case the analytics part is ours to answer.
            return bool(_ANALYTICS.search(text))
    return True


def in_scope(requirements):
    """Split requirements into (kept, dropped). Order is preserved."""
    kept, dropped = [], []
    for requirement in requirements or []:
        (kept if is_in_scope(requirement) else dropped).append(requirement)
    return kept, dropped
