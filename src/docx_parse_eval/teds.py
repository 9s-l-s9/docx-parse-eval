"""TEDS — Tree-Edit-Distance-based Similarity for table structure (quality tier).

Metric per Zhong, ShafieiBavani & Jimeno Yepes, "Image-based table recognition:
data, model, and evaluation" (arXiv:1911.10683 — the PubTabNet metric), the
same definition docling-eval and the wider doc-intelligence ecosystem use:

    TEDS(Ta, Tb) = 1 − TED(Ta, Tb) / max(|Ta|, |Tb|)

where the trees are ``table → tr → td`` with per-``td`` spans and cell text,
and TED is exact tree edit distance. Per R4 the algorithmic core is NOT
reimplemented: TED comes from the ``apted`` library (Pawlik & Augsten's APTED)
and text similarity from ``Levenshtein``. This module only builds the trees
from the schema's ``TableCellRecord`` grid (no HTML round-trip needed — the
adapters already hold structured cells) and defines the standard cost model:

- insert / delete: cost 1 per node;
- rename ``td``: cost 1 if colspan/rowspan differ, else the normalised
  Levenshtein distance between cell texts (0 in structure-only mode).
"""

from __future__ import annotations

import Levenshtein
from apted import APTED, Config

from docx_parse_eval.schema import TableCellRecord


class _Node:
    __slots__ = ("tag", "colspan", "rowspan", "text", "children")

    def __init__(self, tag: str, colspan: int = 1, rowspan: int = 1, text: str = ""):
        self.tag = tag
        self.colspan = colspan
        self.rowspan = rowspan
        self.text = text
        self.children: list[_Node] = []

    def size(self) -> int:
        return 1 + sum(c.size() for c in self.children)


class _TedsConfig(Config):
    def __init__(self, structure_only: bool):
        self.structure_only = structure_only

    def children(self, node: _Node):
        return node.children

    def insert(self, node: _Node) -> float:
        return 1.0

    def delete(self, node: _Node) -> float:
        return 1.0

    def rename(self, a: _Node, b: _Node) -> float:
        if a.tag != b.tag or a.colspan != b.colspan or a.rowspan != b.rowspan:
            return 1.0
        if a.tag != "td" or self.structure_only:
            return 0.0
        if not a.text and not b.text:
            return 0.0
        return 1.0 - Levenshtein.ratio(a.text, b.text)


def build_table_tree(cells: list[TableCellRecord]) -> _Node:
    """``table → tr → td`` tree; a cell belongs to the row where it starts,
    rows and cells ordered by grid position."""
    root = _Node("table")
    rows: dict[int, list[TableCellRecord]] = {}
    for c in cells:
        rows.setdefault(c.row, []).append(c)
    for r in sorted(rows):
        tr = _Node("tr")
        for c in sorted(rows[r], key=lambda c: c.col):
            tr.children.append(_Node("td", colspan=c.col_span, rowspan=c.row_span, text=c.text))
        root.children.append(tr)
    return root


def teds(
    gold_cells: list[TableCellRecord],
    pred_cells: list[TableCellRecord],
    *,
    structure_only: bool = False,
) -> float:
    """TEDS score in [0, 1]; 1.0 = identical tables. ``structure_only`` scores
    grid topology alone (TEDS-Struct), ignoring cell text."""
    a, b = build_table_tree(gold_cells), build_table_tree(pred_cells)
    denom = max(a.size(), b.size())
    if denom <= 1:  # both tables empty
        return 1.0
    dist = APTED(a, b, _TedsConfig(structure_only)).compute_edit_distance()
    return 1.0 - dist / denom
