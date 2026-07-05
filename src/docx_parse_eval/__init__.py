"""docx_parse_eval — Docling .docx parsing evaluation harness.

Tier-2 (conservation / agreement) differential-testing harness plus its
fixture self-test tier. See ``evaluation-framework-spec.md`` at the repo root.

The public Python API mirrors the CLI verbs (``docx-parse-eval --help``):

  extract_reference(docx)          bootstrap — OOXML → silver EvaluationRecord
  get_adapter(name)                predict   — resolve a prediction adapter
  compare(gold, pred)              compare   — differential metrics
  fired_flags(results)             compare   — the defect flags that fired
  read_record / write_record       record (de)serialisation
  record_content_hash(record)      snapshot  — drift-tier content hash
  record_diff(a, b)                reconcile — field-level diff (R6)
  sha256_file(path)                R7 source-identity binding
"""

from docx_parse_eval.adapters import get_adapter
from docx_parse_eval.adapters.ooxml_reference import extract as extract_reference
from docx_parse_eval.comparator import MetricResult, compare, fired_flags
from docx_parse_eval.io import (
    read_record,
    record_content_hash,
    record_diff,
    sha256_file,
    write_record,
)
from docx_parse_eval.schema import (
    SCHEMA_VERSION,
    EvaluationRecord,
    FigureRecord,
    HeadingRecord,
    ListRecord,
    TableRecord,
)

__all__ = [
    # schema
    "SCHEMA_VERSION",
    "EvaluationRecord",
    "FigureRecord",
    "HeadingRecord",
    "ListRecord",
    "TableRecord",
    # workflow verbs (CLI-parallel)
    "extract_reference",
    "get_adapter",
    "MetricResult",
    "compare",
    "fired_flags",
    "read_record",
    "write_record",
    "record_content_hash",
    "record_diff",
    "sha256_file",
]
