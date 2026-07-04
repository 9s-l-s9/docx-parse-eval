"""Phase 2.d acceptance: both adapters honour the identical schema *shape* (R1).

Shape, not values — values are the comparator's job (Phase 3). This guards
against either adapter drifting from the contract: same field set, same types,
``element_sequence`` drawn from the one frozen alphabet."""

from pathlib import Path

from docx_parse_eval.adapters.docling_adapter import extract as docling_extract
from docx_parse_eval.adapters.ooxml_reference import extract as ooxml_extract
from docx_parse_eval.schema import EvaluationRecord

FIX = Path(__file__).resolve().parent / "fixtures"
_ALPHABET = {"heading", "paragraph", "table", "figure", "list", "caption"}


def test_both_adapters_emit_same_field_set():
    gold_fields = set(EvaluationRecord.model_fields)
    a = ooxml_extract(FIX / "synthetic.docx").model_dump()
    b = docling_extract(FIX / "docling" / "mini.docling.json").model_dump()
    assert set(a) == gold_fields == set(b)


def test_both_adapters_produce_valid_records():
    for rec in (
        ooxml_extract(FIX / "synthetic.docx"),
        docling_extract(FIX / "docling" / "mini.docling.json"),
    ):
        # round-trips through the schema → shape conforms to the contract
        EvaluationRecord.model_validate_json(rec.model_dump_json())
        assert set(rec.element_sequence) <= _ALPHABET
