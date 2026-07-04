"""Phase 2.b acceptance: Script 1 reproduces the synthetic gold by construction
(provenance fields aside). Any diff is an extractor bug (specificity)."""

from pathlib import Path

from docx_parse_eval.adapters.ooxml_reference import extract
from docx_parse_eval.io import read_record

FIX = Path(__file__).resolve().parent / "fixtures"

# Fields that legitimately differ between the construction record and the
# extractor (provenance / id), excluded from the deep comparison.
_PROVENANCE = {"producer", "producer_version", "doc_id", "source_path", "title"}


def test_ooxml_reproduces_gold():
    gold = read_record(FIX / "synthetic.gold.json")
    pred = extract(FIX / "synthetic.docx")

    g = gold.model_dump(exclude=_PROVENANCE)
    p = pred.model_dump(exclude=_PROVENANCE)
    assert p == g, _first_diff(g, p)


def test_ooxml_source_sha_matches():
    pred = extract(FIX / "synthetic.docx")
    gold = read_record(FIX / "synthetic.gold.json")
    assert pred.source_sha256 == gold.source_sha256


def _first_diff(g: dict, p: dict) -> str:
    lines = []
    for k in g:
        if g[k] != p.get(k):
            lines.append(f"  {k}:\n    gold={g[k]!r}\n    pred={p.get(k)!r}")
    return "mismatch:\n" + "\n".join(lines)
