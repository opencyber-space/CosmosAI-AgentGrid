"""Loading and validating a company's declared reality.

`config.yaml` says what a company *offers*. It never says what the RFP *asks* -- those
requirements are extracted from the RFP document at run time. Keeping the two apart is
what lets a reviewer change whether a company declines, what it prices and how it sizes
by editing one file, with no change to any agent.

Validation is deliberately loud. A config with a typo'd use-case id would otherwise
produce a company that silently prices nothing and still submits a bid, and the round
would look like it worked. Failing at load surfaces it where it is cheap to fix.
"""
import logging
import os

import yaml

log = logging.getLogger(__name__)

NODES_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Every company stands up the same number of live endpoints, so the evaluator's endpoint
# dimension compares like with like. A company that stood up more would be answering more
# questions than its rivals.
REQUIRED_MAX_LIVE_ENDPOINTS = 2

_CACHE = {}


class ConfigError(ValueError):
    """A company config that cannot be trusted to produce a meaningful bid."""


def config_path(company):
    return os.path.join(NODES_DIR, company, "config.yaml")


def load(company, force=False):
    """Load and validate `nodes/<company>/config.yaml`.

    Cached per company: the six agents of one company each load it, and in some
    deployments share a process.
    """
    if company in _CACHE and not force:
        return _CACHE[company]

    path = config_path(company)
    if not os.path.exists(path):
        raise ConfigError(f"no config.yaml for company {company!r} at {path}")

    with open(path) as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} did not parse to a mapping")

    validate(raw, path)
    _CACHE[company] = raw
    log.info("loaded config for %s (%d use cases)", company, len(raw.get("usecases", [])))
    return raw


def _require(cfg, key, path):
    if key not in cfg:
        raise ConfigError(f"{path}: missing required top-level key {key!r}")
    return cfg[key]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(cfg, path="<config>"):
    """Raise `ConfigError` on anything that would make this company's bid meaningless."""
    for key in ("company", "usecases", "licensing", "hardware", "pricing",
                "credentials", "live_endpoints", "approval"):
        _require(cfg, key, path)

    company = cfg["company"]
    for key in ("name", "slug", "subject_id"):
        if not company.get(key):
            raise ConfigError(f"{path}: company.{key} is required")
    if not isinstance(company.get("topics", []), list):
        raise ConfigError(f"{path}: company.topics must be a list")

    usecases = cfg["usecases"]
    if not isinstance(usecases, list) or not usecases:
        raise ConfigError(f"{path}: usecases must be a non-empty list")
    ids = []
    for uc in usecases:
        uc_id = uc.get("id")
        if not uc_id:
            raise ConfigError(f"{path}: every usecase needs an id")
        if uc_id in ids:
            raise ConfigError(f"{path}: duplicate usecase id {uc_id!r}")
        ids.append(uc_id)
        if not isinstance(uc.get("operating_conditions", {}), dict):
            raise ConfigError(f"{path}: usecase {uc_id!r} operating_conditions must be a mapping")

    licensing = cfg["licensing"]
    lo, hi = licensing.get("min_licenses"), licensing.get("max_licenses")
    if not _is_number(lo) or not _is_number(hi):
        raise ConfigError(f"{path}: licensing.min_licenses and max_licenses must be numbers")
    if lo > hi:
        raise ConfigError(f"{path}: licensing.min_licenses ({lo}) exceeds max_licenses ({hi})")

    _check_usecase_keys(cfg["hardware"], ids, "hardware", path)
    for uc_id, ratios in cfg["hardware"].items():
        for field in ("cpu_cores", "ram_gb", "disk_gb", "gpu_count"):
            value = ratios.get(field)
            if not _is_number(value) or value < 0:
                raise ConfigError(
                    f"{path}: hardware.{uc_id}.{field} must be a non-negative number, got {value!r}"
                )

    pricing = cfg["pricing"]
    priced = {k: v for k, v in pricing.items() if isinstance(v, dict)}
    _check_usecase_keys(priced, ids, "pricing", path)
    for uc_id, terms in priced.items():
        price = terms.get("unit_price")
        if not _is_number(price) or price < 0:
            raise ConfigError(
                f"{path}: pricing.{uc_id}.unit_price must be a non-negative number, got {price!r}"
            )
    for field in ("one_time_implementation_pct", "amc_pct"):
        if not _is_number(pricing.get(field)):
            raise ConfigError(f"{path}: pricing.{field} must be a number")

    credentials = cfg["credentials"]
    if not isinstance(credentials.get("certifications", []), list):
        raise ConfigError(f"{path}: credentials.certifications must be a list")
    for field in ("projects_served", "licenses_supplied"):
        value = credentials.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{path}: credentials.{field} must be an integer, got {value!r}")

    endpoints = cfg["live_endpoints"]
    cap = endpoints.get("max_live_endpoints")
    if cap != REQUIRED_MAX_LIVE_ENDPOINTS:
        raise ConfigError(
            f"{path}: live_endpoints.max_live_endpoints must be "
            f"{REQUIRED_MAX_LIVE_ENDPOINTS} for every company so the evaluator's endpoint "
            f"dimension stays comparable, got {cap!r}"
        )
    if "verdicts" in endpoints:
        raise ConfigError(
            f"{path}: live_endpoints.verdicts is not configuration, it is the answer key to "
            f"the live bake-off this company is scored on. It belongs in an uncommitted "
            f"functions/va-usecase-endpoint/verdicts/<slug>_verdicts.yaml, which build.sh "
            f"packages into the endpoint; see functions/warmup.sh for the format."
        )
    declared = endpoints.get("endpoints")
    if not isinstance(declared, list) or not declared:
        raise ConfigError(
            f"{path}: live_endpoints.endpoints must list the use cases this company stands "
            f"an endpoint up for, got {declared!r}. build_endpoints.py builds one function "
            f"per entry, so a use case missing here is an endpoint that never exists."
        )
    if not all(isinstance(uc, str) for uc in declared):
        raise ConfigError(f"{path}: live_endpoints.endpoints must be a list of use case ids")
    _check_usecase_keys({uc: {} for uc in declared}, ids, "live_endpoints.endpoints", path)

    approval = cfg["approval"]
    if not _is_number(approval.get("min_margin_pct")):
        raise ConfigError(f"{path}: approval.min_margin_pct must be a number")
    cost_ratio = approval.get("cost_ratio")
    if not _is_number(cost_ratio) or cost_ratio < 0:
        raise ConfigError(
            f"{path}: approval.cost_ratio must be a non-negative number -- delivery cost as a "
            f"fraction of the licence subtotal, which the Head Agent needs to judge margin"
        )

    return True


def _check_usecase_keys(mapping, known_ids, label, path):
    if not isinstance(mapping, dict):
        raise ConfigError(f"{path}: {label} must be a mapping keyed by usecase id")
    unknown = [k for k in mapping if k not in known_ids]
    if unknown:
        raise ConfigError(
            f"{path}: {label} refers to unknown usecase id(s) {unknown!r}; "
            f"known ids are {known_ids!r}"
        )


# --- convenience accessors, so agents do not each re-derive the same lookups ---

def usecase(cfg, usecase_id):
    for uc in cfg["usecases"]:
        if uc["id"] == usecase_id:
            return uc
    return None


def serves_outdoor(cfg, usecase_id):
    uc = usecase(cfg, usecase_id) or {}
    return bool(uc.get("operating_conditions", {}).get("outdoor", False))


def licence_count_supported(cfg, count):
    """Whether this company can supply `count` licences at all.

    A count outside the configured range is a decline, not a discount -- it is the
    licence-ceiling path the example demonstrates.
    """
    licensing = cfg["licensing"]
    return licensing["min_licenses"] <= count <= licensing["max_licenses"]


def clear_cache():
    _CACHE.clear()
