"""Format-agnostic projection helpers shared by every adapter.

These compute the derived *text* fields of an ``EvaluationRecord`` from an
ordered list of per-block text fragments. Keeping this in one place is what
guarantees the tokeniser and counting are identical on both sides (R10, §13) —
no adapter recomputes them privately.
"""

from __future__ import annotations

from docx_parse_eval.config import GROUPED_SHAPE_POLICY, GroupedShapePolicy  # noqa: F401
from docx_parse_eval.normalize import (
    char_count_normalized,
    extract_identifier_tokens,
    normalize_text,
    word_count,
)

#: Units / symbols whose survival we track (spec §7 ``special_chars``).
SPECIAL_CANDIDATES = ["°", "×", "±", "µ", "%"]


def derived_text_fields(text_blocks: list[str]) -> dict:
    """Project an ordered list of block texts into the schema's text fields.

    ``text_blocks`` is the reading-order sequence of text fragments (heading
    texts, paragraph texts, list-item texts, table cell texts in order, caption
    texts). ``word_count`` is summed per block to match construction granularity.
    """
    full_text = normalize_text(" ".join(text_blocks))
    return {
        "word_count": sum(word_count(b) for b in text_blocks),
        "char_count_normalized": char_count_normalized(full_text),
        "full_text_normalized": full_text,
        "identifier_tokens": extract_identifier_tokens(full_text),
        "special_chars": [c for c in SPECIAL_CANDIDATES if c in full_text],
    }
