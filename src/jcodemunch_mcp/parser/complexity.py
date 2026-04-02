"""Lightweight complexity metrics derived from symbol body text.

All metrics are computed from the raw source text — no AST required.
These are approximations suitable for ranking, not for strict formal analysis.
"""

from __future__ import annotations

import re

# Branch keywords that increment cyclomatic complexity
_BRANCH_RE = re.compile(
    r"\bif\b|\belif\b|\belse\b|\bfor\b|\bwhile\b|\bdo\b"
    r"|\bexcept\b|\bcatch\b|\bfinally\b"
    r"|\bcase\b|\bwhen\b"
    r"|\band\b|\bor\b"      # Python logical operators
    r"|\|\||&&"             # C-style logical operators
    r"|\?(?!:)",            # ternary ? (but not ?: in C#/Swift)
)

# Characters that increase nesting depth
_OPEN_BRACKETS = frozenset("{[(")
_CLOSE_BRACKETS = frozenset("}])")


def _count_params(signature: str) -> int:
    """Count parameters in the first parenthesised group of *signature*.

    Handles nested brackets (generics, tuples) by tracking bracket depth.
    Returns 0 for signatures with no parentheses or empty param lists.
    """
    m = re.search(r"\(([^)]*)\)", signature, re.DOTALL)
    if not m:
        # Try wider match when params span multiple lines / contain nested ()
        start = signature.find("(")
        if start == -1:
            return 0
        depth = 0
        end = start
        for i, ch in enumerate(signature[start:], start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        params_str = signature[start + 1 : end].strip()
    else:
        params_str = m.group(1).strip()

    if not params_str:
        return 0

    # Count top-level commas (not inside nested brackets)
    depth = 0
    commas = 0
    for ch in params_str:
        if ch in _OPEN_BRACKETS:
            depth += 1
        elif ch in _CLOSE_BRACKETS:
            depth -= 1
        elif ch == "," and depth == 0:
            commas += 1
    return commas + 1


def _max_nesting_depth(body: str) -> int:
    """Approximate max bracket-nesting depth relative to the symbol start.

    Uses bracket counting rather than indentation to stay language-agnostic.
    The opening bracket on the first line is treated as depth 0; each
    additional ``{``, ``[``, or ``(`` increments depth.
    """
    base_depth: int | None = None
    max_depth = 0
    depth = 0
    for ch in body:
        if ch in _OPEN_BRACKETS:
            depth += 1
            if base_depth is None:
                base_depth = depth
            relative = depth - base_depth
            if relative > max_depth:
                max_depth = relative
        elif ch in _CLOSE_BRACKETS:
            depth = max(0, depth - 1)
    return max_depth


def compute_complexity(body: str, signature: str = "") -> tuple[int, int, int]:
    """Compute (cyclomatic, max_nesting, param_count) for a symbol.

    Args:
        body:      Full source text of the symbol (signature + body).
        signature: Signature line used for parameter counting.

    Returns:
        Tuple of (cyclomatic, max_nesting, param_count):
        - cyclomatic: McCabe complexity — branch count + 1.  Range: [1, ∞).
        - max_nesting: Maximum bracket-nesting depth relative to the opening
          brace / bracket.  Range: [0, ∞).
        - param_count: Number of parameters extracted from the signature.
          Range: [0, ∞).
    """
    branch_count = len(_BRANCH_RE.findall(body))
    cyclomatic = branch_count + 1
    nesting = _max_nesting_depth(body)
    params = _count_params(signature or body.split("\n")[0])
    return cyclomatic, nesting, params
