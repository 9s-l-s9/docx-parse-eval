"""Real-data plumbing check (spec §6.2 secondary) against the official Docling
test corpus: real `.docx` sources + their maintainer-blessed `DoclingDocument`
groundtruth JSON (docling-project/docling @ 6395151, schema v1.10).

This is NOT a quality assertion — public fixtures are minimal and the two
parsers legitimately disagree on fine structure. It proves the *plumbing*:
both adapters parse real inputs without error and **agree on coarse content**
(the strongest like-for-like signal: identical word_count + table count on the
table fixture). Genuine fine-grained disagreements are expected and are exactly
what the comparator surfaces (spec §3).
"""

from pathlib import Path

import pytest

from docx_parse_eval.adapters import docling_adapter, ooxml_reference

PUB = Path(__file__).resolve().parent / "fixtures" / "public"
# Every vendored fixture that has both a .docx and its groundtruth JSON.
CASES = sorted(
    p.stem for p in PUB.glob("*.docx") if (PUB / f"{p.stem}.docling.json").exists()
)

pytestmark = pytest.mark.skipif(
    not CASES, reason="public Docling fixtures not vendored (network-fetched; see fixtures/docling/SOURCE.md)"
)


@pytest.mark.parametrize("name", CASES)
def test_both_adapters_parse_real_inputs(name):
    ox = ooxml_reference.extract(PUB / f"{name}.docx")
    dl = docling_adapter.extract(PUB / f"{name}.docling.json")
    # Real Docling output is a deep tree — a broken traversal yields an empty
    # record. Require non-trivial extraction from both sides.
    assert dl.element_sequence, f"docling adapter extracted nothing from {name}"
    assert ox.element_sequence, f"ooxml adapter extracted nothing from {name}"


def test_word_tables_coarse_agreement():
    """On the rich-tables fixture both parsers must agree on table count and the
    total word_count — the like-for-like content signal."""
    ox = ooxml_reference.extract(PUB / "word_tables.docx")
    dl = docling_adapter.extract(PUB / "word_tables.docling.json")
    assert len(ox.tables) == len(dl.tables) == 5
    assert ox.word_count == dl.word_count


def test_docling_tree_traversal_reaches_nested_tables():
    """Regression guard for the tree-vs-flat bug: real `body.children` holds a
    single group, so a flat (one-level) walk would find zero tables."""
    dl = docling_adapter.extract(PUB / "word_tables.docling.json")
    assert len(dl.tables) == 5
