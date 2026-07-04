"""HTML failure report: self-contained output, flags surfaced, content escaped."""

from pathlib import Path

from docx_parse_eval.cli import main
from docx_parse_eval.io import read_record
from docx_parse_eval.report import render_report
from docx_parse_eval.schema import TableCellRecord

FIX = Path(__file__).resolve().parent / "fixtures"


def _gold():
    return read_record(FIX / "synthetic.gold.json")


def test_green_report_says_no_flags():
    html = render_report([(_gold(), _gold())])
    assert "no flags" in html
    assert "0 with fired flags" in html


def test_red_report_surfaces_flag_badges():
    mutated = read_record(FIX / "synthetic.mutated.json")
    html = render_report([(_gold(), mutated)])
    assert "1 with fired flags" in html
    assert 'class="badge"' in html


def test_report_escapes_document_text():
    rec = _gold()
    rec.headings[0].text = "<script>alert(1)</script>"
    rec.tables[0].cells = [TableCellRecord(row=0, col=0, text="<img src=x>")]
    html = render_report([(rec, rec)])
    assert "<script>" not in html
    assert "<img" not in html


def test_report_is_self_contained():
    html = render_report([(_gold(), _gold())])
    for marker in ("http://", "https://", "<script"):
        assert marker not in html


def test_cli_report_writes_file(tmp_path):
    out = tmp_path / "r.html"
    rc = main(["report", "--gold", str(FIX / "synthetic.gold.json"),
               "--pred", str(FIX / "synthetic.mutated.json"), "--out", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_cli_report_pair_mismatch_exits_2(tmp_path):
    rc = main(["report", "--gold", str(FIX / "synthetic.gold.json"),
               "--gold", str(FIX / "synthetic.gold.json"),
               "--pred", str(FIX / "synthetic.mutated.json"),
               "--out", str(tmp_path / "r.html")])
    assert rc == 2
