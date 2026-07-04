"""Phase 0.c acceptance: the schema round-trips losslessly and enforces the
frozen contract (R1)."""

import pytest
from pydantic import ValidationError

from docx_parse_eval.schema import (
    SCHEMA_VERSION,
    EvaluationRecord,
    FigureRecord,
    HeadingRecord,
    ListRecord,
    TableRecord,
)


def _full_record() -> EvaluationRecord:
    return EvaluationRecord(
        doc_id="wh-spec-001",
        title="Synthetic Warehouse Spec",
        source_path="/fixtures/synthetic.docx",
        source_sha256="0" * 64,
        producer="fixture-construction",
        producer_version="test",
        word_count=42,
        char_count_normalized=210,
        full_text_normalized="some normalised text",
        tables=[
            TableRecord(
                table_id="t0",
                position=3,
                n_rows=4,
                n_cols=3,
                cell_count=12,
                has_header=True,
                cell_text_length=88,
            )
        ],
        figures=[
            FigureRecord(figure_id="f0", position=5, caption_text="Figure 1.", has_caption=True)
        ],
        headings=[HeadingRecord(text="Overview", level=1, position=0)],
        lists=[ListRecord(list_id="l0", position=7, n_items=3, is_ordered=True)],
        hyperlink_count=2,
        footnote_count=1,
        endnote_count=0,
        element_sequence=["heading", "paragraph", "table", "figure", "caption", "list"],
        identifier_tokens=["120 mm", "PN-12345"],
        special_chars=["°", "±"],
    )


def test_roundtrip_is_lossless():
    rec = _full_record()
    restored = EvaluationRecord.model_validate_json(rec.model_dump_json())
    assert restored == rec


def test_schema_version_frozen():
    assert SCHEMA_VERSION == "0.4"
    assert _full_record().schema_version == "0.4"


def test_element_sequence_alphabet_is_closed():
    with pytest.raises(ValidationError):
        EvaluationRecord.model_validate(
            {**_full_record().model_dump(), "element_sequence": ["heading", "bogus"]}
        )


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        EvaluationRecord.model_validate({**_full_record().model_dump(), "surprise": 1})


def test_optional_fulltext_may_be_omitted():
    data = _full_record().model_dump()
    data.pop("full_text_normalized")
    rec = EvaluationRecord.model_validate(data)
    assert rec.full_text_normalized is None
