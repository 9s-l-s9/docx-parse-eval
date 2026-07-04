"""Workflow layer: R7 enforcement, table alignment, bless/reconcile (R6),
corpus runner, and the snapshot (drift) tier."""

from __future__ import annotations

import json
from pathlib import Path

from docx_parse_eval import cli
from docx_parse_eval import config as C
from docx_parse_eval.comparator import compare, fired_flags
from docx_parse_eval.io import read_record, record_content_hash, record_diff, write_record
from docx_parse_eval.schema import TableRecord

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _gold():
    return read_record(FIXTURES / "synthetic.gold.json")


# --- R7: source identity ------------------------------------------------------------
def test_source_identity_flags_on_differing_hashes():
    gold = _gold()
    pred = gold.model_copy(deep=True)
    pred.source_sha256 = "0" * 64
    assert "source_identity" in fired_flags(compare(gold, pred))


def test_source_identity_informational_when_hash_unknown():
    gold = _gold()
    pred = gold.model_copy(deep=True)
    pred.source_sha256 = ""  # e.g. prediction built from JSON alone
    assert "source_identity" not in fired_flags(compare(gold, pred))


def test_compare_cli_refuses_source_mismatch(tmp_path):
    gold = _gold()
    tampered = gold.model_copy(deep=True)
    tampered.source_sha256 = "0" * 64
    g, p = tmp_path / "g.json", tmp_path / "p.json"
    write_record(gold, g)
    write_record(tampered, p)
    assert cli.main(["compare", "--gold", str(g), "--pred", str(p), "--out", str(tmp_path)]) == 2
    # Override allowed, but source_identity then flags → exit 1, not 0.
    assert cli.main(["compare", "--gold", str(g), "--pred", str(p), "--out", str(tmp_path),
                     "--allow-source-mismatch"]) == 1


# --- table alignment: one dropped table must not cascade ---------------------------
def test_extra_table_does_not_misalign_teds():
    gold = _gold()
    pred = gold.model_copy(deep=True)
    junk = TableRecord(table_id="junk", position=0, n_rows=1, n_cols=1, cell_count=1,
                       has_header=False, cell_text_length=4, cells=None)
    pred.tables.insert(0, junk)  # spurious extra table BEFORE the real ones
    results = {r.metric: r for r in compare(gold, pred)}
    # Positional zip would score gold table A against junk; similarity
    # alignment must still pair the real tables → TEDS stays 1.0.
    assert results["table_teds"].ratio_or_score == 1.0
    assert results["table_dimensions"].flag  # the count defect is still owned here


def test_oversized_table_pair_reported_not_scored(monkeypatch):
    monkeypatch.setattr(C, "TEDS_MAX_CELLS", 5)
    gold = _gold()  # table A has 12 cells > 5
    results = {r.metric: r for r in compare(gold, gold.model_copy(deep=True))}
    assert results["table_teds"].source_value == "not-extracted"
    assert not results["table_teds"].flag


# --- bless / reconcile (R6/R7 tooling) ----------------------------------------------
def test_bless_writes_gold_and_verifies_hash(tmp_path):
    silver = _gold().model_copy(deep=True)
    silver.source_path = str(FIXTURES / "synthetic.docx")  # reachable source
    s = tmp_path / "silver.json"
    write_record(silver, s)
    assert cli.main(["bless", str(s), "--out", str(tmp_path)]) == 0
    assert (tmp_path / "gold" / f"{silver.doc_id}.json").exists()

    tampered = silver.model_copy(deep=True)
    tampered.source_sha256 = "0" * 64
    t = tmp_path / "tampered.json"
    write_record(tampered, t)
    assert cli.main(["bless", str(t), "--out", str(tmp_path)]) == 2  # R7 refusal
    assert cli.main(["bless", str(t), "--out", str(tmp_path), "--force"]) == 0


def test_reconcile_reports_field_level_diff(tmp_path):
    gold = _gold()
    draft = gold.model_copy(deep=True)
    draft.tables[0].n_rows = 99
    draft.producer_version = "999"  # provenance: must NOT count as a diff
    g, d = tmp_path / "g.json", tmp_path / "d.json"
    write_record(gold, g)
    write_record(draft, d)
    assert cli.main(["reconcile", "--gold", str(g), "--draft", str(d)]) == 1
    diffs = record_diff(gold, draft)
    assert diffs == ["tables[0].n_rows: 4 → 99"]
    # identical records → exit 0
    assert cli.main(["reconcile", "--gold", str(g), "--draft", str(g)]) == 0


# --- corpus runner -------------------------------------------------------------------
def test_run_over_manifest(tmp_path):
    gold = _gold()
    clean = gold.model_copy(deep=True)
    mutated = read_record(FIXTURES / "synthetic.mutated.json")
    paths = {}
    for name, rec in [("gold", gold), ("clean", clean), ("mutated", mutated)]:
        paths[name] = tmp_path / f"{name}.json"
        write_record(rec, paths[name])
    manifest = tmp_path / "corpus.json"

    manifest.write_text(json.dumps([
        {"doc_id": "doc-a", "gold": str(paths["gold"]), "pred": str(paths["clean"])},
    ]))
    assert cli.main(["run", "--manifest", str(manifest), "--out", str(tmp_path)]) == 0

    manifest.write_text(json.dumps([
        {"doc_id": "doc-a", "gold": str(paths["gold"]), "pred": str(paths["clean"])},
        {"doc_id": "doc-b", "gold": str(paths["gold"]), "pred": str(paths["mutated"])},
    ]))
    assert cli.main(["run", "--manifest", str(manifest), "--out", str(tmp_path)]) == 1
    import pandas as pd

    df = pd.read_csv(tmp_path / "corpus.csv")
    assert set(df["doc_id"]) == {"doc-a", "doc-b"}
    assert df[df.doc_id == "doc-b"].flag.any() and not df[df.doc_id == "doc-a"].flag.any()


# --- snapshot / drift tier -----------------------------------------------------------
def test_snapshot_lifecycle(tmp_path):
    rec = _gold()
    r = tmp_path / "rec.json"
    write_record(rec, r)
    snap = str(tmp_path / "snaps")
    assert cli.main(["snapshot", str(r), "--dir", snap]) == 0  # baseline
    assert cli.main(["snapshot", str(r), "--dir", snap]) == 0  # unchanged

    changed = rec.model_copy(deep=True)
    changed.word_count += 1
    write_record(changed, r)
    assert cli.main(["snapshot", str(r), "--dir", snap]) == 1  # drift detected
    assert cli.main(["snapshot", str(r), "--dir", snap, "--update"]) == 0
    assert cli.main(["snapshot", str(r), "--dir", snap]) == 0  # new baseline


def test_content_hash_ignores_provenance():
    rec = _gold()
    moved = rec.model_copy(deep=True)
    moved.producer_version = "999"
    moved.source_path = "/somewhere/else.docx"
    assert record_content_hash(rec) == record_content_hash(moved)
    changed = rec.model_copy(deep=True)
    changed.word_count += 1
    assert record_content_hash(rec) != record_content_hash(changed)
