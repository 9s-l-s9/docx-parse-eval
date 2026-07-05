"""Phase 4 — end-to-end runner (§9.1–§9.2): bootstrap → predict → compare wires
together and the compare exit code doubles as a CI flag gate."""

from pathlib import Path

from docx_parse_eval.cli import main

FIX = Path(__file__).resolve().parent / "fixtures"


def test_bootstrap_writes_silver_record(tmp_path):
    rc = main(["bootstrap", str(FIX / "synthetic.docx"), "--out", str(tmp_path)])
    assert rc == 0
    out = list(tmp_path.glob("*.silver.json"))
    assert len(out) == 1


def test_predict_writes_prediction_record(tmp_path):
    rc = main(["predict", str(FIX / "docling" / "mini.docling.json"),
               "--out", str(tmp_path), "--allow-unknown-source"])
    assert rc == 0
    assert list(tmp_path.glob("*.docling-adapter.json"))


def test_predict_without_source_refuses(tmp_path, capsys):
    # R7: an unbound prediction (no source hash) must be an explicit choice,
    # never the silent default.
    rc = main(["predict", str(FIX / "docling" / "mini.docling.json"), "--out", str(tmp_path)])
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.json"))


def test_predict_unknown_adapter_refuses(tmp_path, capsys):
    rc = main(["predict", str(FIX / "docling" / "mini.docling.json"),
               "--out", str(tmp_path), "--allow-unknown-source", "--adapter", "nope"])
    assert rc == 2
    assert "unknown adapter" in capsys.readouterr().out


def test_predict_source_stamps_sha256(tmp_path):
    from docx_parse_eval.io import read_record, sha256_file

    rc = main(["predict", str(FIX / "docling" / "mini.docling.json"),
               "--out", str(tmp_path), "--source", str(FIX / "synthetic.docx")])
    assert rc == 0
    rec = read_record(next(tmp_path.glob("*.docling-adapter.json")))
    assert rec.source_sha256 == sha256_file(FIX / "synthetic.docx")
    assert rec.source_path == str(FIX / "synthetic.docx")


def test_compare_green_exits_zero_and_emits_files(tmp_path):
    # bootstrap a record, then compare it against itself → no flags → rc 0
    main(["bootstrap", str(FIX / "synthetic.docx"), "--out", str(tmp_path)])
    silver = next(tmp_path.glob("*.silver.json"))
    rc = main(["compare", "--gold", str(FIX / "synthetic.gold.json"),
               "--pred", str(silver), "--out", str(tmp_path)])
    assert rc == 0
    assert list(tmp_path.glob("*.csv")) and list(tmp_path.glob("*.parquet"))


def test_compare_red_exits_nonzero(tmp_path):
    main(["bootstrap", str(FIX / "synthetic.docx"), "--out", str(tmp_path)])
    # gold vs the mutated red fixture → flags fire → rc 1
    rc = main(["compare", "--gold", str(FIX / "synthetic.gold.json"),
               "--pred", str(FIX / "synthetic.mutated.json"), "--out", str(tmp_path)])
    assert rc == 1


def test_get_adapter_rejects_entry_point_without_extract(monkeypatch):
    """A registered but malformed plug-in must fail with a clean message,
    not an AttributeError at extract time."""
    import pytest

    from docx_parse_eval import adapters

    class _EP:
        name = "broken"
        value = "some_pkg:thing"

        def load(self):
            return object()  # no .extract

    monkeypatch.setattr(adapters, "entry_points", lambda group: [_EP()])
    with pytest.raises(TypeError, match="does not expose extract"):
        adapters.get_adapter("broken")
