"""Phase 1.d — the sensitivity half (spec §6.1).

Each mutation is a PURE function `EvaluationRecord -> (mutated, expected_flags)`,
injecting exactly one defect and naming the metric(s) that MUST fire for it. The
flag names are the contract Phase 3's red tests assert against — so a mutation
isn't "something changed", it's "this specific metric should catch this".

The canonical single-defect red fixture (`synthetic.mutated.json`) is
`corrupt_identifier`; the rest stay callable for Phase 3's parametrised tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from docx_parse_eval.io import read_record, write_record  # noqa: E402
from docx_parse_eval.schema import EvaluationRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
GOLD_PATH = HERE / "synthetic.gold.json"
MUTATED_PATH = HERE / "synthetic.mutated.json"

# Flag names — must match the metric ids Script 3 (Phase 3) emits.
FLAG_FIGURE_COUNT = "figure_count"
FLAG_CAPTION_COUNT = "caption_count"
FLAG_IDENTIFIER_JACCARD = "identifier_token_overlap"
FLAG_DUPLICATION = "duplication_direction"
FLAG_TABLE_DIMS = "table_dimensions"
FLAG_SEQUENCE = "element_sequence_distance"
FLAG_CAPTION_ASSOC = "caption_association"
FLAG_TEDS = "table_teds"
FLAG_TEDS_STRUCT = "table_teds_struct"


def drop_figure(rec: EvaluationRecord) -> tuple[EvaluationRecord, set[str]]:
    m = rec.model_copy(deep=True)
    dropped = m.figures.pop()  # remove last figure
    # keep element_sequence consistent: drop one "figure" (+ its caption if any)
    m.element_sequence = _drop_last(m.element_sequence, "figure")
    if dropped.has_caption:
        m.element_sequence = _drop_last(m.element_sequence, "caption")
    flags = {FLAG_FIGURE_COUNT}
    if dropped.has_caption:
        flags.add(FLAG_CAPTION_COUNT)
    return m, flags


def corrupt_identifier(rec: EvaluationRecord) -> tuple[EvaluationRecord, set[str]]:
    m = rec.model_copy(deep=True)
    m.identifier_tokens = [
        t.replace("PN-12345", "PN-12745") if "PN-12345" in t else t
        for t in m.identifier_tokens
    ]
    if m.full_text_normalized:
        m.full_text_normalized = m.full_text_normalized.replace("PN-12345", "PN-12745")
    return m, {FLAG_IDENTIFIER_JACCARD}


def corrupt_caption(rec: EvaluationRecord) -> tuple[EvaluationRecord, set[str]]:
    m = rec.model_copy(deep=True)
    for f in m.figures:
        if f.has_caption:
            f.caption_text = "completely unrelated caption text"
            break
    return m, {FLAG_CAPTION_ASSOC}


def duplicate_block(rec: EvaluationRecord) -> tuple[EvaluationRecord, set[str]]:
    m = rec.model_copy(deep=True)
    # emit a table's text twice (table + body flow) → length grows past 1+ε
    if m.full_text_normalized:
        m.full_text_normalized = m.full_text_normalized + " " + m.full_text_normalized
    m.char_count_normalized = (
        len(m.full_text_normalized) if m.full_text_normalized else m.char_count_normalized * 2
    )
    return m, {FLAG_DUPLICATION}


def alter_table_dims(rec: EvaluationRecord) -> tuple[EvaluationRecord, set[str]]:
    m = rec.model_copy(deep=True)
    t = m.tables[0]
    t.n_cols += 1
    t.cell_count += t.n_rows
    return m, {FLAG_TABLE_DIMS}


def corrupt_table_cell(rec: EvaluationRecord) -> tuple[EvaluationRecord, set[str]]:
    """Garble ONE cell's text, leaving the grid intact: only full TEDS may
    fire — TEDS-Struct must stay quiet (its isolation proof)."""
    m = rec.model_copy(deep=True)
    m.tables[0].cells[4].text = "garbled-beyond-recognition-xxxxx"
    return m, {FLAG_TEDS}


def merge_table_cells(rec: EvaluationRecord) -> tuple[EvaluationRecord, set[str]]:
    """Fuse two adjacent cells into one span — the (rows, cols) grid is
    unchanged, so only cell_count hints at it; both TEDS variants must fire."""
    m = rec.model_copy(deep=True)
    t = m.tables[0]
    a = t.cells[0]
    b = next(c for c in t.cells if c.row == a.row and c.col == a.col + a.col_span)
    a.col_span += b.col_span
    a.text = f"{a.text} {b.text}".strip()
    t.cells.remove(b)
    t.cell_count -= 1
    return m, {FLAG_TEDS, FLAG_TEDS_STRUCT}


def reorder_sequence(rec: EvaluationRecord) -> tuple[EvaluationRecord, set[str]]:
    """Emit the figure before the table it follows — a genuine block-type
    reordering. (A plain swap of the first two blocks can create an adjacent
    same-type pair, which the run-length-collapsed metric rightly reads as
    segmentation, not reordering.)"""
    m = rec.model_copy(deep=True)
    i = m.element_sequence.index("table")
    j = m.element_sequence.index("figure")
    m.element_sequence[i], m.element_sequence[j] = (
        m.element_sequence[j],
        m.element_sequence[i],
    )
    return m, {FLAG_SEQUENCE}


MUTATIONS = {
    "drop_figure": drop_figure,
    "corrupt_caption": corrupt_caption,
    "corrupt_identifier": corrupt_identifier,
    "duplicate_block": duplicate_block,
    "alter_table_dims": alter_table_dims,
    "corrupt_table_cell": corrupt_table_cell,
    "merge_table_cells": merge_table_cells,
    "reorder_sequence": reorder_sequence,
}

CANONICAL = "corrupt_identifier"


def _drop_last(seq: list[str], value: str) -> list[str]:
    out = seq[:]
    for i in range(len(out) - 1, -1, -1):
        if out[i] == value:
            del out[i]
            break
    return out


def main() -> None:
    gold = read_record(GOLD_PATH)
    mutated, flags = MUTATIONS[CANONICAL](gold)
    mutated.producer = f"mutated-{CANONICAL}"
    write_record(mutated, MUTATED_PATH)
    print(f"wrote {MUTATED_PATH.name} via {CANONICAL}; expected flags: {sorted(flags)}")


if __name__ == "__main__":
    main()
