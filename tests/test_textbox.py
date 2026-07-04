"""Regression: a DrawingML text box is not a figure, and its text is extracted
(distilled from the real `textbox` fixture)."""

from pathlib import Path

from docx_parse_eval.adapters.ooxml_reference import extract

FIX = Path(__file__).resolve().parent / "fixtures"


def test_textbox_text_extracted_and_not_a_figure():
    rec = extract(FIX / "textbox.docx")
    assert len(rec.figures) == 0, "text box was miscounted as a figure"
    assert "Boxed warehouse note 42 mm." in (rec.full_text_normalized or "")
    assert any("42 mm" in t for t in rec.identifier_tokens)
    # intro paragraph + the boxed paragraph, both as paragraphs in order
    assert rec.element_sequence == ["paragraph", "paragraph"]
