"""Shared text normalisation & tokenisation (spec §7 "Normalisation").

Every adapter and the comparator import these functions, so that any difference
the metrics see reflects *extraction*, not formatting — and so the tokeniser is
provably identical on both sides (§13). No adapter keeps a private copy.

The core ``normalize_text`` is deterministic and side-effect-free. Residual
lossy-format syntax stripping is intentionally NOT baked in here; it is
adapter-local (only adapters deriving values from a lossy format need it), so
the shared core stays a single, predictable transform.
"""

from __future__ import annotations

import re
import unicodedata

from docx_parse_eval.config import IDENTIFIER_REGEX

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """Unicode NFC, collapse internal whitespace runs to a single space, strip
    leading/trailing whitespace. Idempotent."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = _WHITESPACE_RUN.sub(" ", s)
    return s.strip()


def char_count_normalized(s: str) -> int:
    """Character count of the *normalised* string — the single definition both
    sides use for ``char_count_normalized`` and the length-ratio metric."""
    return len(normalize_text(s))


def word_count(s: str) -> int:
    """Whitespace-delimited word count over the normalised string. One shared
    definition so the count is comparable across adapters."""
    n = normalize_text(s)
    return len(n.split()) if n else 0


_ENUMERATION_PREFIX = re.compile(r"^\d+(?:\.\d+)*\.?\s+")


def strip_enumeration(s: str) -> str:
    """Remove a leading outline number ("1 ", "1.1 ", "2.1.3. ") from heading
    text. Word computes these at render time, so parsers that materialise them
    (Docling) and sources that don't (OOXML) would disagree on every numbered
    heading. Applied to heading text by EVERY adapter — symmetric, so a
    heading that genuinely starts with a number loses it on both sides alike."""
    return _ENUMERATION_PREFIX.sub("", s)


def extract_identifier_tokens(s: str) -> list[str]:
    """Numbers, measurements, and part-style IDs as a *sorted multiset* (spec
    §7 ``identifier_tokens``). Pattern lives in ``config.py`` (§13 open item,
    calibrated in Phase 4)."""
    tokens = IDENTIFIER_REGEX.findall(normalize_text(s))
    # findall may yield tuples if the pattern grows capture groups; guard now.
    flat = [t if isinstance(t, str) else next((g for g in t if g), "") for t in tokens]
    return sorted(t for t in flat if t)
