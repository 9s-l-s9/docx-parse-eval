"""Phase 4 — threshold calibration, pinned as boundary tests (spec §8 / §13).

"Calibrate on fixtures" made durable: for each flag threshold we assert a
*sub-threshold* perturbation stays quiet (no false alarm on formatting-scale
noise) and a *supra-threshold* perturbation fires. This both documents the
chosen band and guards it against silent drift if a constant is later changed.

If a constant in `config.py` moves, the matching boundary test should be
updated deliberately — that is the calibration record.
"""

import sys
from pathlib import Path

from docx_parse_eval import config as C
from docx_parse_eval.comparator import compare, fired_flags
from docx_parse_eval.io import read_record

FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIX))
import mutations as mut  # noqa: E402


def _gold():
    return read_record(FIX / "synthetic.gold.json")


def _scale_chars(rec, factor):
    m = rec.model_copy(deep=True)
    m.char_count_normalized = round(rec.char_count_normalized * factor)
    return m


# --- length_ratio / duplication band (δ, ε) ---------------------------------
def test_length_ratio_quiet_within_delta():
    gold = _gold()
    sub = _scale_chars(gold, 1 + C.LENGTH_RATIO_DELTA * 0.5)  # half a band → noise
    assert "length_ratio" not in fired_flags(compare(gold, sub))


def test_length_ratio_fires_outside_delta():
    gold = _gold()
    supra = _scale_chars(gold, 1 + C.LENGTH_RATIO_DELTA * 3)  # 3× band → defect
    assert "length_ratio" in fired_flags(compare(gold, supra))


def test_duplication_quiet_below_epsilon_and_fires_above():
    gold = _gold()
    quiet = _scale_chars(gold, 1 + C.DUPLICATION_EPSILON * 0.5)
    loud = _scale_chars(gold, 2.0)  # content emitted twice
    assert "duplication_direction" not in fired_flags(compare(gold, quiet))
    assert "duplication_direction" in fired_flags(compare(gold, loud))


# --- full-text NED ----------------------------------------------------------
def test_ned_quiet_on_single_char_noise():
    gold = _gold()
    m = gold.model_copy(deep=True)
    # flip one character in a long normalised text → NED << threshold
    txt = list(m.full_text_normalized)
    txt[0] = "X" if txt[0] != "X" else "Y"
    m.full_text_normalized = "".join(txt)
    assert "full_text_ned" not in fired_flags(compare(gold, m))


def test_ned_fires_on_large_divergence():
    gold = _gold()
    m = gold.model_copy(deep=True)
    m.full_text_normalized = "completely different text " * 5
    assert "full_text_ned" in fired_flags(compare(gold, m))


# --- identifier Jaccard (a dropped/corrupted part number IS a defect) -------
def test_jaccard_quiet_on_identical_tokens():
    gold = _gold()
    assert "identifier_token_overlap" not in fired_flags(compare(gold, gold))


def test_jaccard_fires_on_one_corrupted_token():
    gold = _gold()
    mutated, _ = mut.corrupt_identifier(gold)
    assert "identifier_token_overlap" in fired_flags(compare(gold, mutated))


# --- element-sequence distance band -----------------------------------------
def test_sequence_quiet_on_single_drop_loud_on_transposition():
    gold = _gold()
    dropped, _ = mut.drop_figure(gold)        # distance 1 ≤ threshold → quiet
    reordered, _ = mut.reorder_sequence(gold)  # distance 2 > threshold → loud
    assert "element_sequence_distance" not in fired_flags(compare(gold, dropped))
    assert "element_sequence_distance" in fired_flags(compare(gold, reordered))
