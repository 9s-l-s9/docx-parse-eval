"""docx_parse_eval — Docling .docx parsing evaluation harness.

Tier-2 (conservation / agreement) differential-testing harness plus its
fixture self-test tier. See ``evaluation/evaluation-framework-spec.md``.
"""

from docx_parse_eval.schema import (
    SCHEMA_VERSION,
    EvaluationRecord,
    FigureRecord,
    HeadingRecord,
    ListRecord,
    TableRecord,
)

__all__ = [
    "SCHEMA_VERSION",
    "EvaluationRecord",
    "FigureRecord",
    "HeadingRecord",
    "ListRecord",
    "TableRecord",
]
