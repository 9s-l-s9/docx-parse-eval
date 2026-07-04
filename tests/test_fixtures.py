"""Phase 1 acceptance: the synthetic fixtures are well-formed, the gold matches
its `.docx` source (R7), and every mutation injects a real, single defect with a
named expected-flag set."""

import sys
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIX))

from docx_parse_eval.io import read_record, sha256_file  # noqa: E402
from docx_parse_eval.schema import SCHEMA_VERSION  # noqa: E402

import mutations as mut  # noqa: E402


def _gold():
    return read_record(FIX / "synthetic.gold.json")


def test_fixture_files_exist():
    for name in ("synthetic.docx", "synthetic.gold.json", "synthetic.mutated.json"):
        assert (FIX / name).exists(), f"missing fixture {name}; run build_synthetic.py + mutations.py"


def test_gold_is_schema_valid_and_versioned():
    gold = _gold()
    assert gold.schema_version == SCHEMA_VERSION
    assert all(b in {"heading", "paragraph", "table", "figure", "list", "caption"}
               for b in gold.element_sequence)


def test_gold_known_structure_by_construction():
    gold = _gold()
    assert len(gold.tables) == 2
    assert len(gold.figures) == 3
    assert len(gold.headings) == 7
    assert [h.level for h in gold.headings].count(1) == 2  # two H1
    assert [h.level for h in gold.headings].count(3) == 2  # two H3
    assert sum(t.cell_count for t in gold.tables) == 12 + 7  # plain + merged
    assert sum(f.has_caption for f in gold.figures) == 2     # one uncaptioned
    assert "±" in gold.special_chars and "°" in gold.special_chars


def test_gold_source_sha_matches_docx():
    gold = _gold()
    assert gold.source_sha256 == sha256_file(FIX / "synthetic.docx")


def test_canonical_mutated_differs_in_one_axis():
    gold = _gold()
    mutated = read_record(FIX / "synthetic.mutated.json")
    assert mutated.identifier_tokens != gold.identifier_tokens
    assert mutated.figures == gold.figures  # only the identifier axis changed
    assert mutated.tables == gold.tables


@pytest.mark.parametrize("name", sorted(mut.MUTATIONS))
def test_each_mutation_changes_record_and_declares_flags(name):
    gold = _gold()
    mutated, flags = mut.MUTATIONS[name](gold)
    assert flags, f"{name} declared no expected flags"
    assert mutated != gold, f"{name} did not change the record"
