"""Phase 0.d acceptance: shared normalisation is NFC, whitespace-collapsing,
and idempotent (spec §7)."""

import unicodedata

from docx_parse_eval.normalize import (
    char_count_normalized,
    extract_identifier_tokens,
    normalize_text,
    word_count,
)


def test_nfc_composes_decomposed():
    decomposed = "é"  # e + combining acute
    composed = "é"  # é
    assert decomposed != composed
    assert normalize_text(decomposed) == normalize_text(composed) == composed


def test_whitespace_collapsed_across_kinds():
    assert normalize_text("a\t b\n\nc   d") == "a b c d"


def test_strips_leading_trailing():
    assert normalize_text("   hi   ") == "hi"


def test_empty_and_whitespace_only():
    assert normalize_text("") == ""
    assert normalize_text("   \t\n ") == ""


def test_idempotent():
    s = "  PN-12345 \t weighs  120 mm \n"
    once = normalize_text(s)
    assert normalize_text(once) == once


def test_char_and_word_count_use_normalised():
    s = "  two   words  "
    assert word_count(s) == 2
    assert char_count_normalized(s) == len("two words")


def test_identifier_tokens_sorted_multiset():
    toks = extract_identifier_tokens("Part PN-12345 weighs 120 mm at 24 V, also PN-99")
    assert toks == sorted(toks)
    assert "PN-12345" in toks
    assert any("120" in t for t in toks)


def test_nfc_is_actually_applied():
    out = normalize_text("é")
    assert unicodedata.is_normalized("NFC", out)
