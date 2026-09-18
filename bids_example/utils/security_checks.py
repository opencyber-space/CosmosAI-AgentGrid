"""Security acceptance checks measured in code, shared by the security agents.

Lifted from Manager1SecurityAuditAgent so the solo sub-agent gates its own work with the
exact same rules: a model is never trusted to judge what a program can check - vulnerable
pins, required config values, forbidden literals, syntax and undefined names.
"""
import ast
import builtins
import json
import logging
import os
import re

import yaml

log = logging.getLogger(__name__)


def original_files(job_desc):
    """Files supplied in the brief as '=== FILE: <path> ===' sections."""
    files = {}
    for m in re.finditer(r"^=== FILE: (\S+)[^\n]*===\n(.*?)(?=^=== |\Z)", job_desc or "", re.S | re.M):
        files[m.group(1)] = m.group(2).rstrip("\n")
    return files


def effective_files(files, originals):
    """What the delivery really contains: returned files laid over the originals.

    A file no implementer returned is still part of the delivery - unchanged - so its
    original defects are checked instead of silently skipped.
    """
    effective = dict(originals)
    by_name = {os.path.basename(p): p for p in originals}
    for path, content in files.items():
        effective.pop(by_name.get(os.path.basename(path), path), None)
        effective[path] = content
    return effective


def config_lookup(doc, dotted):
    """(found, value) for a dotted key such as 'session.cookie_secure'."""
    node = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def undefined_names(tree):
    """[(name, first_line)] for names read in the module but bound nowhere in it.

    Deliberately loose about scope - a name bound anywhere in the file counts as defined -
    so it never flags valid code; it catches the runtime NameError class such as
    `except binascii.Error` without `import binascii`. Skipped for star imports.
    """
    bound = set(dir(builtins)) | {"__file__", "__builtins__", "__path__", "__annotations__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            return []
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif type(node).__name__ in ("MatchAs", "MatchStar") and getattr(node, "name", None):
            bound.add(node.name)
        elif type(node).__name__ == "MatchMapping" and getattr(node, "rest", None):
            bound.add(node.rest)
    missing = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store) and node.id not in bound:
            missing[node.id] = min(missing.get(node.id, node.lineno), node.lineno)
    return sorted(missing.items(), key=lambda item: item[1])


def measure_solution(files, criteria, job_desc=""):
    """Facts checked in code, including the job's security acceptance criteria.

    The model is never trusted to judge anything a program can check: vulnerable pins,
    required config values and forbidden literals are gated here and override any verdict.
    """
    facts = {"files_present": sorted(files), "python_syntax": {}}
    hard = []
    if not files:
        hard.append("No modified files were returned - return complete corrected files in modified_files.")
    for path, content in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(content)
            facts["python_syntax"][path] = "ok"
        except SyntaxError as e:
            facts["python_syntax"][path] = f"SyntaxError at line {e.lineno}: {e.msg}"
            hard.append(f"{path} does not parse (SyntaxError at line {e.lineno}: {e.msg}) - return the complete, valid file.")
            continue
        undefined = undefined_names(tree)
        if undefined:
            facts.setdefault("undefined_names", {})[path] = [name for name, _ in undefined]
            hard.append(f"{path} uses names that are never imported or defined, so it fails at runtime: "
                        + ", ".join(f"'{name}' (line {line})" for name, line in undefined)
                        + " - add the missing imports or definitions to that file.")

    effective = effective_files(files, original_files(job_desc))
    facts["files_unchanged"] = sorted(p for p in effective if p not in files)

    # 1. vulnerable pins that must not remain
    forbidden = {re.sub(r"\s+", "", pin).lower(): pin for pin in criteria.get("forbidden_pins") or []}
    if forbidden:
        present = []
        for path, content in effective.items():
            if not re.match(r"requirements.*\.txt$", os.path.basename(path)):
                continue
            for line in content.splitlines():
                norm = re.sub(r"\s+", "", line.split("#", 1)[0]).lower()
                if norm in forbidden:
                    present.append(f"{path}: {forbidden[norm]}")
        facts["forbidden_pins_present"] = present
        if present:
            hard.append("Vulnerable dependency pins are still present and must be upgraded to safe versions: "
                        + ", ".join(present) + ".")

    # 2. required configuration values
    required_config = criteria.get("required_config") or {}
    if required_config:
        docs = {}
        for path, content in effective.items():
            if not path.endswith((".yaml", ".yml")):
                continue
            try:
                docs[path] = yaml.safe_load(content) or {}
            except yaml.YAMLError as e:
                hard.append(f"{path} is not valid YAML ({str(e).splitlines()[0]}) - return the complete, valid file.")
        checks = {}
        for key, want in required_config.items():
            found = [(path, value) for path, doc in docs.items()
                     for ok, value in [config_lookup(doc, key)] if ok]
            if not found:
                checks[key] = {"required": want, "actual": None}
                hard.append(f"Config setting '{key}' is missing; it must be set to {json.dumps(want)}.")
                continue
            path, got = found[0]
            checks[key] = {"required": want, "actual": got, "file": path}
            if got != want:
                hard.append(f"{path}: '{key}' is {json.dumps(got)}; it must be {json.dumps(want)}.")
        facts["required_config"] = checks

    # 3. literals that must not appear anywhere in the delivery
    literals = criteria.get("forbidden_code") or []
    if literals:
        hits = [f"{path}: '{lit}'" for lit in literals for path, content in effective.items() if lit in content]
        facts["forbidden_code_present"] = hits
        if hits:
            hard.append("Forbidden literals are still present: " + ", ".join(hits) + ".")

    return facts, hard
