"""
Shared fixtures and the CSS reader the stylesheet tests work from.

Every test in this suite exists because the corresponding bug actually shipped
during the 2026-08 rewrite. Where that is not obvious from the assertion, the
test says which one.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DOCS = ROOT / "docs"
CSS = DOCS / "assets" / "css" / "custom.css"

sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def css_text() -> str:
    return CSS.read_text(encoding="utf-8")


def split_rules(css: str):
    """[(selector, declarations)] for every top-level rule, media blocks kept.

    Deliberately not a real CSS parser: it only needs enough structure to ask
    "does this selector set this property", which is the question the dark-mode
    audit turns on.
    """
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, body = match.group(1), match.group(2)
        # strip comments and any leading at-rule opener
        selectors = re.sub(r"/\*.*?\*/", "", selectors, flags=re.S)
        selectors = selectors.split("{")[-1]
        for sel in selectors.split(","):
            sel = normalise_selector(sel)
            if sel and not sel.startswith("@"):
                out.append((sel, body))
    return out


def normalise_selector(sel: str) -> str:
    """Canonical form, so `a>b` and `a > b` compare equal.

    They are the same selector to a browser, and treating them as different
    made the dark-mode audit report a false positive against a rule that was
    in fact overridden.
    """
    sel = " ".join(sel.split())
    return re.sub(r"\s*([>+~])\s*", r" \1 ", sel)


# Any at-rule whose condition mentions the dark scheme, not just the bare
# `@media (prefers-color-scheme: dark)`. A width-scoped one —
# `@media (max-width: 767px) and (prefers-color-scheme: dark)`, which is how
# the phone nav states are written — was read as *light* CSS by an exact-string
# match, so its rules were audited against the dark grounds they already sit on
# and could not count as anyone's dark counterpart.
_DARK_AT_RULE = re.compile(r"@media[^{}]*prefers-color-scheme:\s*dark[^{}]*\{")


def _dark_spans(css: str):
    """(start of the at-rule, index of its `{`, index of its closing `}`)."""
    spans = []
    for match in _DARK_AT_RULE.finditer(css):
        start = match.end() - 1
        depth, k = 0, start
        while k < len(css):
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        spans.append((match.start(), start, k))
    return spans


def dark_block(css: str) -> str:
    """Everything inside prefers-color-scheme: dark blocks, concatenated."""
    return "\n".join(css[start + 1:end] for _, start, end in _dark_spans(css))


def light_block(css: str) -> str:
    """Everything OUTSIDE prefers-color-scheme: dark blocks.

    Not `css[:first dark block]` — the stylesheet has several dark blocks, so
    slicing at the first one silently skipped every rule defined after it,
    which is most of the components carried over from the fantasy site.
    """
    out, i = [], 0
    for at_rule, _, end in _dark_spans(css):
        out.append(css[i:at_rule])
        i = end + 1
    out.append(css[i:])
    return "".join(out)


def declared(body: str, prop: str):
    """Value of `prop` in a declaration block, or None.

    The negative lookbehind matters: without it `border-color` matches a search
    for `color`, which is exactly the mistake that made an early dark-mode
    audit report the ADP table as covered when it only set a border.
    """
    m = re.search(rf"(?<![-\w]){re.escape(prop)}\s*:\s*([^;}}]+)", body)
    return m.group(1).strip() if m else None
