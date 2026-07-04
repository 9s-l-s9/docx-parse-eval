"""Phase 3 acceptance — the two halves of the self-test (spec §6.1):

- GREEN / specificity: gold vs the OOXML extraction of the same `.docx` → no flag.
- RED / sensitivity: each mutation fires its *declared* flag (and the green pair
  stays clean), so the harness both never false-alarms and actually catches defects.
"""

import sys
from pathlib import Path

import pytest

from docx_parse_eval.adapters.ooxml_reference import extract
from docx_parse_eval.comparator import compare, fired_flags
from docx_parse_eval.io import read_record

FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIX))
import mutations as mut  # noqa: E402


def _gold():
    return read_record(FIX / "synthetic.gold.json")


# --- GREEN: specificity ------------------------------------------------------
def test_green_gold_vs_extraction_no_flags():
    gold = _gold()
    pred = extract(FIX / "synthetic.docx")
    flags = fired_flags(compare(gold, pred))
    assert flags == set(), f"spurious flags on a known-good pair: {flags}"


def test_green_gold_vs_itself_no_flags():
    gold = _gold()
    assert fired_flags(compare(gold, gold)) == set()


# --- RED: sensitivity --------------------------------------------------------
@pytest.mark.parametrize("name", sorted(mut.MUTATIONS))
def test_red_each_mutation_fires_declared_flag(name):
    gold = _gold()
    mutated, expected = mut.MUTATIONS[name](gold)
    flags = fired_flags(compare(gold, mutated))
    assert expected <= flags, (
        f"{name}: expected {expected} to fire, got {flags}"
    )


def test_red_corrupt_identifier_is_isolated():
    """The canonical single-defect case fires *only* its metric — proof the
    identifier check is specific, not a blanket alarm."""
    gold = _gold()
    mutated, _ = mut.corrupt_identifier(gold)
    assert fired_flags(compare(gold, mutated)) == {"identifier_token_overlap"}
