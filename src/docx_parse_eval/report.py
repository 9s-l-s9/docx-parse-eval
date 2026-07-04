"""Static HTML failure report — the visual layer over the comparator.

One self-contained HTML file (inline CSS, no scripts, no external requests):
open it in any browser, attach it to CI artifacts, mail it around. It renders,
per document pair, the full metric table with fired flags highlighted, the
aligned tables side-by-side with per-cell diffs and TEDS scores, the caption
pairs, and the element sequences — everything needed to go from "a flag fired"
to "here is the defect" without re-running anything.

No new dependencies: rendering is string assembly + ``html.escape``. All
document-derived text is escaped."""

from __future__ import annotations

from html import escape

from docx_parse_eval import config as C
from docx_parse_eval.comparator import (
    MetricResult,
    _align_captions,
    _align_tables,
    _encode_seq,
    compare,
    fired_flags,
)
from docx_parse_eval.schema import EvaluationRecord, TableCellRecord, TableRecord
from docx_parse_eval.teds import teds

_CSS = """
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 72rem;
       padding: 0 1rem; color: #1a1a1a; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.15rem; margin-top: 2.5rem;
     border-bottom: 2px solid #1a1a1a; padding-bottom: .3rem; }
h3 { font-size: 1rem; margin-top: 1.6rem; }
table { border-collapse: collapse; margin: .8rem 0; font-size: .85rem; }
th, td { border: 1px solid #bbb; padding: .25rem .55rem; text-align: left;
         vertical-align: top; }
th { background: #f0f0f0; }
tr.flag td { background: #ffe3e3; }
tr.info td { color: #777; }
td.diff { background: #ffe3e3; outline: 2px solid #d33; }
.ok    { color: #0a7a2f; font-weight: 600; }
.bad   { color: #c22; font-weight: 600; }
.muted { color: #777; }
.badge { display: inline-block; background: #c22; color: #fff;
         border-radius: .6rem; padding: .05rem .55rem; font-size: .8rem;
         margin-right: .35rem; }
.pair  { display: flex; gap: 1.5rem; flex-wrap: wrap; }
.pair > div { flex: 1 1 20rem; min-width: 0; overflow-x: auto; }
code { background: #f4f4f4; padding: .1rem .3rem; border-radius: .2rem;
       font-size: .85em; word-break: break-all; }
@media (prefers-color-scheme: dark) {
  body { background: #161616; color: #e4e4e4; }
  th { background: #262626; } th, td { border-color: #555; }
  tr.flag td, td.diff { background: #4a2020; }
  tr.info td, .muted { color: #999; }
  code { background: #262626; }
  h2 { border-color: #e4e4e4; }
}
"""


def _cell_map(cells: list[TableCellRecord]) -> dict[tuple[int, int], TableCellRecord]:
    return {(c.row, c.col): c for c in cells}


def _grid_html(t: TableRecord, other: TableRecord | None) -> str:
    """One table as an HTML grid; cells whose text differs from the cell at the
    same origin in ``other`` (or that have no counterpart) are marked."""
    if t.cells is None:
        return '<p class="muted">grid unrecoverable — no cell coordinates</p>'
    own = _cell_map(t.cells)
    them = _cell_map(other.cells) if other and other.cells is not None else None
    covered: set[tuple[int, int]] = set()  # origins hidden under a span
    rows = []
    for r in range(t.n_rows):
        tds = []
        for c in range(t.n_cols):
            if (r, c) in covered:
                continue
            cell = own.get((r, c))
            if cell is None:
                tds.append("<td></td>")
                continue
            for dr in range(cell.row_span):
                for dc in range(cell.col_span):
                    if (dr, dc) != (0, 0):
                        covered.add((r + dr, c + dc))
            span = ""
            if cell.row_span > 1:
                span += f' rowspan="{cell.row_span}"'
            if cell.col_span > 1:
                span += f' colspan="{cell.col_span}"'
            counterpart = them.get((r, c)) if them is not None else cell
            differs = counterpart is None or counterpart.text != cell.text or (
                (counterpart.row_span, counterpart.col_span)
                != (cell.row_span, cell.col_span)
            )
            cls = ' class="diff"' if differs else ""
            tds.append(f"<td{span}{cls}>{escape(cell.text)}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f'<table>{"".join(rows)}</table>'


def _metrics_html(results: list[MetricResult]) -> str:
    rows = []
    for r in results:
        cls = ""
        note = ""
        if r.flag and r.metric in C.NON_GATING_METRICS:
            cls, note = ' class="info"', " (informational)"
        elif r.flag:
            cls = ' class="flag"'
        score = "" if r.ratio_or_score is None else f"{r.ratio_or_score:.3f}"
        rows.append(
            f"<tr{cls}><td>{escape(r.metric)}{note}</td>"
            f"<td>{escape(r.source_value)}</td>"
            f"<td>{escape(r.prediction_value)}</td>"
            f"<td>{score}</td><td>{'⚑' if r.flag else ''}</td></tr>"
        )
    return (
        "<table><tr><th>metric</th><th>gold</th><th>prediction</th>"
        "<th>ratio / score</th><th>flag</th></tr>" + "".join(rows) + "</table>"
    )


def _tables_html(gold: EvaluationRecord, pred: EvaluationRecord) -> str:
    if not gold.tables and not pred.tables:
        return ""
    out = [f"<h3>Tables — {len(gold.tables)} gold / {len(pred.tables)} predicted</h3>"]
    for g, p in _align_tables(gold.tables, pred.tables):
        if g.cells is not None and p.cells is not None:
            t = teds(g.cells, p.cells)
            ts = teds(g.cells, p.cells, structure_only=True)
            verdict = "ok" if t >= C.TEDS_THRESHOLD and ts >= C.TEDS_STRUCT_THRESHOLD else "bad"
            score = f'<span class="{verdict}">TEDS {t:.2f} · TEDS-Struct {ts:.2f}</span>'
        else:
            score = '<span class="muted">TEDS not scorable (grid unrecoverable)</span>'
        out.append(
            f"<p><b>{escape(g.table_id)}</b> ({g.n_rows}×{g.n_cols}) ↔ "
            f"<b>{escape(p.table_id)}</b> ({p.n_rows}×{p.n_cols}) — {score}</p>"
            f'<div class="pair"><div><h4>gold</h4>{_grid_html(g, p)}</div>'
            f"<div><h4>prediction</h4>{_grid_html(p, g)}</div></div>"
        )
    matched_g = {id(g) for g, _ in _align_tables(gold.tables, pred.tables)}
    matched_p = {id(p) for _, p in _align_tables(gold.tables, pred.tables)}
    for side, tables, matched in (
        ("gold", gold.tables, matched_g),
        ("prediction", pred.tables, matched_p),
    ):
        for tbl in tables:
            if id(tbl) not in matched:
                out.append(
                    f'<p class="bad">unmatched {side} table <b>{escape(tbl.table_id)}</b> '
                    f"({tbl.n_rows}×{tbl.n_cols})</p>{_grid_html(tbl, None)}"
                )
    return "".join(out)


def _captions_html(gold: EvaluationRecord, pred: EvaluationRecord) -> str:
    pairs = _align_captions(gold.figures, pred.figures)
    if not pairs:
        return ""
    rows = "".join(
        f"<tr{' class=' + chr(34) + 'flag' + chr(34) if a != b else ''}>"
        f"<td>{escape(a)}</td><td>{escape(b)}</td></tr>"
        for a, b in pairs
    )
    return (
        "<h3>Caption pairs</h3><table><tr><th>gold</th><th>prediction</th></tr>"
        + rows
        + "</table>"
    )


def _doc_section(gold: EvaluationRecord, pred: EvaluationRecord) -> str:
    results = compare(gold, pred)
    fired = sorted(fired_flags(results))
    badges = (
        "".join(f'<span class="badge">{escape(f)}</span>' for f in fired)
        if fired
        else '<span class="ok">no flags — all gates clean</span>'
    )
    seq_g, seq_p = _encode_seq(gold.element_sequence), _encode_seq(pred.element_sequence)
    seq_cls = "ok" if seq_g == seq_p else "bad"
    return (
        f"<h2>{escape(gold.doc_id)} × {escape(pred.producer)}</h2>"
        f"<p>{badges}</p>"
        f"<p class='muted'>gold: {escape(gold.producer)} {escape(gold.producer_version)}"
        f" · prediction: {escape(pred.producer)} {escape(pred.producer_version)}"
        f" · source sha256 <code>{escape(gold.source_sha256[:12] or 'unknown')}</code>"
        f" / <code>{escape(pred.source_sha256[:12] or 'unknown')}</code></p>"
        + _metrics_html(results)
        + f"<h3>Element sequence (runs collapsed)</h3>"
        f"<p class='{seq_cls}'><code>{escape(seq_g)}</code> → "
        f"<code>{escape(seq_p)}</code></p>"
        + _tables_html(gold, pred)
        + _captions_html(gold, pred)
    )


def render_report(pairs: list[tuple[EvaluationRecord, EvaluationRecord]]) -> str:
    """All document pairs → one self-contained HTML page."""
    body = "".join(_doc_section(g, p) for g, p in pairs)
    n_flagged = sum(bool(fired_flags(compare(g, p))) for g, p in pairs)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>docx-parse-eval report</title><style>{_CSS}</style></head><body>"
        f"<h1>docx-parse-eval — {len(pairs)} document(s), "
        f"{n_flagged} with fired flags</h1>"
        + body
        + "</body></html>"
    )
