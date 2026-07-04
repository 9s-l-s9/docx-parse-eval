"""Phase 4 acceptance: the long-form comparison table emits as CSV + Parquet,
round-trips, and faithfully carries the flags (spec §11)."""

import sys
from pathlib import Path

import pandas as pd

from docx_parse_eval.adapters.ooxml_reference import extract
from docx_parse_eval.comparator import compare
from docx_parse_eval.io import read_record
from docx_parse_eval.output import RESULT_COLUMNS, results_to_long_df, write_results_table

FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIX))
import mutations as mut  # noqa: E402


def _results_for(record_mutator=None):
    gold = read_record(FIX / "synthetic.gold.json")
    pred = extract(FIX / "synthetic.docx") if record_mutator is None else record_mutator(gold)[0]
    return gold, compare(gold, pred)


def test_long_df_shape_and_columns():
    gold, results = _results_for()
    df = results_to_long_df(results, doc_id=gold.doc_id, producer="docling-adapter")
    assert list(df.columns) == RESULT_COLUMNS
    assert len(df) == len(results)
    assert (df["doc_id"] == gold.doc_id).all()


def test_emit_and_roundtrip(tmp_path):
    gold, results = _results_for()
    df = results_to_long_df(results, doc_id=gold.doc_id, producer="ooxml-reference",
                            run_id="r1", gold_commit="abc123")
    paths = write_results_table(df, tmp_path)
    assert paths["csv"].exists() and paths["parquet"].exists()

    back = pd.read_parquet(paths["parquet"])
    assert list(back.columns) == RESULT_COLUMNS
    assert len(back) == len(df)
    assert (back["gold_commit"] == "abc123").all()


def test_flag_column_reflects_mutation():
    gold, results = _results_for(mut.corrupt_identifier)
    df = results_to_long_df(results, doc_id=gold.doc_id, producer="mutated")
    flagged = set(df.loc[df["flag"], "metric"])
    assert flagged == {"identifier_token_overlap"}


def test_green_pair_has_no_flags_in_table():
    gold, results = _results_for()
    df = results_to_long_df(results, doc_id=gold.doc_id, producer="ooxml-reference")
    assert df["flag"].sum() == 0
