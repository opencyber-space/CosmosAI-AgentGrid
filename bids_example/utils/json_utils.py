import json
import re
import logging
from typing import Any

log = logging.getLogger(__name__)

def extract_json(s: Any):
    """
    Safely extracts and parses JSON from a string that might contain 
    surrounding text or markdown blocks.
    """
    if not isinstance(s, str):
        return s
        
    content = s.strip()
    if not content:
        return None

    # 1. Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. Try to find JSON block in markdown (```json ... ```)
    match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
            
    # 3. Try generic markdown block (``` ... ```)
    match = re.search(r'```\s*(.*?)\s*```', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 4. Try brace matching to find the first complete JSON object/array
    start_idx = -1
    for i, char in enumerate(content):
        if char in ('{', '['):
            start_idx = i
            break
            
    if start_idx != -1:
        open_char = content[start_idx]
        close_char = '}' if open_char == '{' else ']'
        open_count = 0
        in_string = False
        escape = False
        
        for i in range(start_idx, len(content)):
            char = content[i]
            
            if in_string:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == open_char:
                    open_count += 1
                elif char == close_char:
                    open_count -= 1
                    
                if open_count == 0:
                    json_str = content[start_idx:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        # If the parse failed but we're at a balanced state, 
                        # continue traversing in case this was a false positive
                        # (e.g., mismatched internal brackets somehow)
                        pass

    # 5. Try greedy match as fallback
    match = re.search(r'(\[.*\]|\{.*\})', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            # If it still fails, it might be single quotes
            try:
                # Use string replacement carefully for simple cases
                # or better: ast.literal_eval for simple lists/dicts
                import ast
                return ast.literal_eval(match.group(0))
            except Exception:
                pass

    # 6. Try ast.literal_eval on the whole string if it's small
    try:
        import ast
        return ast.literal_eval(content)
    except Exception:
        pass

    # 7. Repair a truncated object/array by closing any brackets the model left
    #    open (a common failure when the model hits its token limit).
    repaired = _close_unbalanced(content)
    if repaired is not None:
        return repaired

    # Every caller uses the `extract_json(...) or {default}` idiom, so return a
    # falsy value rather than raising: an exception propagates past `or`, past
    # the node's handler, and turns a recoverable parse miss into is_error=True.
    log.error(f"Failed to extract JSON, falling back to caller default: {content[:200]}...")
    return None


def _close_unbalanced(content: str):
    """Best-effort repair of output truncated mid-object/array.

    Walks the text tracking bracket depth outside of strings, drops any partial
    trailing token, and appends the closers still owed. Returns the parsed value
    or None; never raises.
    """
    start = -1
    for i, ch in enumerate(content):
        if ch in "{[":
            start = i
            break
    if start == -1:
        return None

    stack = []
    in_string = False
    escape = False
    for ch in content[start:]:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()

    if not stack and not in_string:
        return None  # balanced already - nothing here to repair

    candidate = content[start:]
    if in_string:
        candidate += '"'
    # Drop a dangling separator or half-written key before closing.
    candidate = candidate.rstrip().rstrip(",")
    for closer in reversed(stack):
        candidate += closer

    try:
        return json.loads(candidate)
    except Exception:
        return None
