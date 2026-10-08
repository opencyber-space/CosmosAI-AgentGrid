"""Make a value safe to write to a log: credentials removed, everything else kept.

An agent's whole subject spec travels in its mesh `join` and `presence` messages, and the
spec carries credentials -- `persona.config.parameters.api_key`, every
`integrations.models[].llm_parameters.api_key`, the MinIO keys. Logging such a message,
or a model block, therefore writes those secrets into the container log, where anyone who
can run `kubectl logs` reads them. This is the one place that decides what may be logged.

`redact` works on a value and returns a **copy** with every credential-looking key
dropped, so the original -- which the caller still needs -- is never touched. Strings are
scrubbed too, because a payload often carries another payload as text.
"""
import dataclasses
import re
from typing import Any

# A key is sensitive if it is one of these, or ends in one of the suffixes. The suffixes
# catch api_key, secret_key, minio_access_key, access_token... and deliberately not
# max_tokens / max_completion_tokens, which are settings, not secrets.
_EXACT = frozenset({
    "api_key", "apikey", "authorization", "password", "passwd", "secret", "token",
    "bearer", "private_key", "client_secret",
})
_SUFFIXES = ("_key", "_secret", "_password", "_passwd", "_token")

_MAX_DEPTH = 10

# `"api_key": "sk-..."`, `'api_key': 'sk-...'`, `api_key='sk-...'`, `PASSWORD: "..."` --
# a quoted value after a credential-looking name inside a piece of text.
_IN_TEXT = re.compile(
    r"""(?P<name>['"]?[A-Za-z0-9_\-]*(?:api[_\-]?key|secret|password|passwd|token|authorization)"""
    r"""[A-Za-z0-9_\-]*['"]?\s*[:=]\s*)(?P<quote>['"])(?P<value>.*?)(?P=quote)""",
    re.IGNORECASE | re.DOTALL,
)


def is_sensitive(name: Any) -> bool:
    lowered = str(name).strip().lower().replace("-", "_")
    return lowered in _EXACT or lowered.endswith(_SUFFIXES)


def scrub(text: str) -> str:
    """Blank the quoted value of any credential-looking name in a piece of text."""
    return _IN_TEXT.sub(lambda m: f"{m.group('name')}{m.group('quote')}***{m.group('quote')}", text)


def redact(value: Any, _depth: int = 0) -> Any:
    """A loggable copy of `value`: dicts, lists, dataclasses and plain objects are walked,
    credential-named keys are dropped, and strings and bytes are scrubbed."""
    if _depth > _MAX_DEPTH:
        return "<...>"
    if isinstance(value, dict):
        return {k: redact(v, _depth + 1) for k, v in value.items() if not is_sensitive(k)}
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v, _depth + 1) for v in value)
    if isinstance(value, (set, frozenset)):
        return [redact(v, _depth + 1) for v in value]
    if isinstance(value, bytes):
        return scrub(value.decode("utf-8", "replace"))
    if isinstance(value, str):
        return scrub(value)
    if value is None or isinstance(value, (int, float, bool)) or isinstance(value, type):
        return value
    if dataclasses.is_dataclass(value):
        return redact({f.name: getattr(value, f.name, None) for f in dataclasses.fields(value)},
                      _depth + 1)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return redact(to_dict(), _depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return redact(vars(value), _depth + 1)
    return scrub(repr(value))
