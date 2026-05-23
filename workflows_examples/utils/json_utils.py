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

    # 6. Last resort: just try ast.literal_eval on the whole string if it's small
    try:
        import ast
        return ast.literal_eval(content)
    except Exception:
        pass

    log.error(f"Failed to extract JSON from string: {content[:100]}...")
    raise ValueError(f"Could not parse JSON from: {content}")
