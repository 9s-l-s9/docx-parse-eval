"""Phase 2.c acceptance: Script 2 projects DoclingDocument JSON to a schema-valid
record matching the authored mini fixture's known structure, with furniture
excluded and captions/lists/headers handled."""

from pathlib import Path

from docx_parse_eval.adapters.docling_adapter import extract
from docx_parse_eval.schema import EvaluationRecord

FIX = Path(__file__).resolve().parent / "fixtures" / "docling"


def _rec() -> EvaluationRecord:
    return extract(FIX / "mini.docling.json")


def test_projection_is_schema_valid():
    rec = _rec()
    assert isinstance(rec, EvaluationRecord)
    assert rec.producer == "docling-adapter"


def test_reading_order_and_counts():
    rec = _rec()
    assert rec.element_sequence == [
        "heading", "heading", "paragraph", "list", "table", "figure", "caption"
    ]
    assert len(rec.headings) == 2
    assert [h.level for h in rec.headings] == [1, 2]  # title→1, section_header→2
    assert len(rec.tables) == 1 and len(rec.figures) == 1 and len(rec.lists) == 1


def test_table_header_and_dims():
    t = _rec().tables[0]
    assert (t.n_rows, t.n_cols, t.cell_count) == (2, 2, 4)
    assert t.has_header is True
    assert t.cell_text_length == len("Name") + len("Qty") + len("Bolt") + len("5")


def test_caption_associates_to_figure():
    f = _rec().figures[0]
    assert f.has_caption is True
    assert f.caption_text == "Figure 1: Layout."


def test_ordered_list_items():
    lst = _rec().lists[0]
    assert lst.n_items == 2 and lst.is_ordered is True


def test_furniture_excluded():
    rec = _rec()
    assert "CONFIDENTIAL" not in (rec.full_text_normalized or "")


def test_identifiers_extracted():
    toks = _rec().identifier_tokens
    assert any("PN-12345" in t for t in toks)
    assert any("24 V" in t for t in toks)
