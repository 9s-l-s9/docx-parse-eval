"""Regression: the OOXML extractor must descend into content controls (`w:sdt`)
and find block content nested inside them (distilled from docx_rich_tables_01)."""

from pathlib import Path

from docx_parse_eval.adapters.ooxml_reference import extract

FIX = Path(__file__).resolve().parent / "fixtures"


def test_table_inside_content_control_is_found():
    rec = extract(FIX / "sdt_table.docx")
    assert len(rec.tables) == 1, "table wrapped in w:sdt was not found"
    t = rec.tables[0]
    assert (t.n_rows, t.n_cols, t.cell_count) == (2, 2, 4)
    # the intro paragraph is still present and ordered before the table
    assert rec.element_sequence[:2] == ["paragraph", "table"]
    assert "120 mm" in (rec.full_text_normalized or "")
