"""Script 2 — Docling adapter (`DoclingDocument` JSON → schema), spec §5.3.

Consumes the **lossless native `DoclingDocument` JSON** (R11), never HTML/Markdown.
Parses it as a portable data format (plain dict traversal) so the harness carries
**no dependency on `docling`/`docling-core`** — Docling stays entirely out of the
harness (R8). Reading order is `body.children` (a list of `$ref`s); the
`furniture` layer (page headers/footers) is excluded, matching the OOXML
adapter's furniture policy so the figure/heading counts compare like-for-like.
"""

from __future__ import annotations

import json
from pathlib import Path

from docx_parse_eval.adapters._common import derived_text_fields
from docx_parse_eval.normalize import char_count_normalized, normalize_text, strip_enumeration
from docx_parse_eval.schema import (
    ElementType,
    EvaluationRecord,
    FigureRecord,
    HeadingRecord,
    ListRecord,
    TableCellRecord,
    TableRecord,
)

PRODUCER = "docling-adapter"
PRODUCER_VERSION = "2"

_LIST_GROUP_LABELS = {"list", "ordered_list", "unordered_list"}


def _ref_target(ref: str) -> tuple[str, int]:
    """'#/texts/3' -> ('texts', 3)."""
    parts = ref.lstrip("#/").split("/")
    return parts[-2], int(parts[-1])


def _resolve(data: dict, ref: str) -> tuple[str, dict]:
    kind, idx = _ref_target(ref)
    return kind, data[kind][idx]


def _is_list_group(label: str) -> bool:
    return "list" in label  # list / ordered_list / unordered_list


class _Doc:
    """Thin resolver over the DoclingDocument dict."""

    def __init__(self, data: dict):
        self.data = data
        self.texts = data.get("texts", [])
        self.tables = data.get("tables", [])
        self.pictures = data.get("pictures", [])
        self.groups = data.get("groups", [])

    def resolve(self, child: dict) -> tuple[str, dict]:
        ref = child.get("$ref") or child.get("cref") or ""
        kind, idx = _ref_target(ref)
        return kind, self.data[kind][idx]

    def text_of(self, ref: str) -> str:
        kind, idx = _ref_target(ref)
        return normalize_text(self.data[kind][idx].get("text", ""))


def _is_excluded_layer(item: dict) -> bool:
    """Only the body layer is document content. `furniture` = page headers/
    footers; `notes` = comment/annotation text (docx_comments showed comments
    leaking into word counts when only furniture was excluded). Items without
    a content_layer default to body."""
    return item.get("content_layer", "body") not in (None, "body")


def _table_record(item: dict, position: int, n: int) -> tuple[TableRecord, list[str]]:
    data = item.get("data", {})
    cells = data.get("table_cells", [])
    # Dedupe spanned cells by their grid origin when offsets are present.
    seen: set[tuple] = set()
    texts: list[str] = []
    cell_records: list[TableCellRecord] = []
    grid_ok = True
    has_header = False
    for c in cells:
        origin = (c.get("start_row_offset_idx"), c.get("start_col_offset_idx"))
        if origin != (None, None):
            if origin in seen:
                continue
            seen.add(origin)
        text = normalize_text(c.get("text", ""))
        texts.append(text)
        if c.get("column_header"):
            has_header = True
        r0, c0 = origin
        if r0 is None or c0 is None:
            grid_ok = False  # no grid coordinates → TEDS not scorable
        else:
            r1 = c.get("end_row_offset_idx") or r0 + 1  # end offsets exclusive
            c1 = c.get("end_col_offset_idx") or c0 + 1
            cell_records.append(
                TableCellRecord(
                    row=r0, col=c0,
                    row_span=max(r1 - r0, 1), col_span=max(c1 - c0, 1),
                    text=text,
                )
            )
    rec = TableRecord(
        table_id=f"t{n}",
        position=position,
        n_rows=data.get("num_rows", 0),
        n_cols=data.get("num_cols", 0),
        cell_count=len(texts),
        has_header=has_header,
        cell_text_length=sum(char_count_normalized(t) for t in texts),
        cells=cell_records if grid_ok and cell_records else None,
    )
    return rec, texts


def _ref_of(child: dict) -> str:
    return child.get("$ref") or child.get("cref") or ""


def extract_from_dict(data: dict, doc_id: str = "docling", source_path: str = "",
                      source_sha256: str = "") -> EvaluationRecord:
    doc = _Doc(data)

    headings: list[HeadingRecord] = []
    tables: list[TableRecord] = []
    figures: list[FigureRecord] = []
    lists: list[ListRecord] = []
    element_sequence: list[ElementType] = []
    text_blocks: list[str] = []
    visited: set[str] = set()

    def pos() -> int:
        return len(element_sequence)

    def visit(kind: str, item: dict) -> None:
        # A DoclingDocument is a TREE: every node carries `children` refs and is
        # visited in document order (DFS). Section-header texts parent their
        # section body, so we emit a node THEN descend into its children.
        sref = item.get("self_ref", "")
        if sref in visited:
            return
        visited.add(sref)
        if _is_excluded_layer(item):
            return
        label = item.get("label", "")

        if kind == "groups":
            if _is_list_group(label):
                _emit_list(item, label)
            elif label == "inline":
                # An inline group is ONE source paragraph split at formatting
                # boundaries — emitting each fragment as its own paragraph
                # inflates the element sequence (one paragraph became 23
                # blocks on unit_test_formatting).
                _emit_inline(item)
            else:
                _recurse(item)  # transparent container (section / etc.)
            return
        if kind == "tables":
            rec, cell_texts = _table_record(item, pos(), len(tables))
            tables.append(rec)
            element_sequence.append("table")
            text_blocks.extend(cell_texts)
            # Rich-cell content items are referenced BOTH from `table_cells`
            # (as flattened text, already counted above) and as the table's
            # `children` tree — recursing normally would double-count every
            # word in the cells. Descend only to pick up the elements the
            # flat cell text cannot represent: pictures and nested tables.
            _visit_table_subtree(item)
            return
        elif kind == "pictures":
            caps = item.get("captions", [])
            caption = doc.text_of(_ref_of(caps[0])) if caps else ""
            figures.append(FigureRecord(figure_id=f"f{len(figures)}", position=pos(),
                                        caption_text=caption, has_caption=bool(caption)))
            element_sequence.append("figure")
        elif kind == "texts":
            _emit_text(item, label)
        _recurse(item)

    def _recurse(item: dict) -> None:
        for ch in item.get("children", []):
            ref = _ref_of(ch)
            if ref:
                k, it = _resolve(data, ref)
                visit(k, it)

    def _visit_table_subtree(item: dict) -> None:
        """Within a table's children tree, emit only pictures and nested
        tables; text/group nodes are the cell content already flattened into
        `table_cells` — mark them visited so nothing re-emits them."""
        for ch in item.get("children", []):
            ref = _ref_of(ch)
            if not ref:
                continue
            k, it = _resolve(data, ref)
            if it.get("self_ref", "") in visited:
                continue
            if k in ("pictures", "tables"):
                visit(k, it)
            else:
                visited.add(it.get("self_ref", ""))
                _visit_table_subtree(it)

    def _emit_inline(item: dict) -> None:
        parts: list[str] = []
        others: list[tuple[str, dict]] = []
        for ch in item.get("children", []):
            ref = _ref_of(ch)
            if not ref:
                continue
            k, it = _resolve(data, ref)
            if k == "texts":
                visited.add(it.get("self_ref", ""))
                t = normalize_text(it.get("text", ""))
                if t:
                    parts.append(t)
            else:
                others.append((k, it))
        text = " ".join(parts)
        if text:
            element_sequence.append("paragraph")
            text_blocks.append(text)
        for k, it in others:
            visit(k, it)

    def _emit_text(item: dict, label: str) -> None:
        text = normalize_text(item.get("text", ""))
        if label == "title":
            # Heading text is enumeration-stripped on every adapter: Docling
            # materialises Word's computed outline numbers ("1.2 Scope"),
            # the OOXML source cannot.
            text = strip_enumeration(text)
            headings.append(HeadingRecord(text=text, level=1, position=pos()))
            element_sequence.append("heading")
            text_blocks.append(text)
        elif label == "section_header":
            text = strip_enumeration(text)
            headings.append(HeadingRecord(text=text, level=item.get("level", 1), position=pos()))
            element_sequence.append("heading")
            text_blocks.append(text)
        elif label == "caption":
            element_sequence.append("caption")
            text_blocks.append(text)
        elif label == "list_item":
            lists.append(ListRecord(list_id=f"l{len(lists)}", position=pos(), n_items=1,
                                    is_ordered=bool(item.get("enumerated", False))))
            element_sequence.append("list")
            text_blocks.append(text)
        elif text:
            element_sequence.append("paragraph")
            text_blocks.append(text)

    def _emit_list(item: dict, label: str) -> None:
        li_texts: list[str] = []
        li_items: list[dict] = []
        others: list[tuple[str, dict]] = []
        for ch in item.get("children", []):
            ref = _ref_of(ch)
            k, it = _resolve(data, ref)
            if k == "texts" and it.get("label") == "list_item":
                li_texts.append(normalize_text(it.get("text", "")))
                li_items.append(it)
                visited.add(it.get("self_ref", ""))
            else:
                others.append((k, it))
        # Group labels are usually just "list"; ordered-ness lives per-item in
        # the `enumerated` field.
        ordered = "ordered" in label or (
            bool(li_items) and all(it.get("enumerated", False) for it in li_items)
        )
        lists.append(ListRecord(list_id=f"l{len(lists)}", position=pos(),
                                n_items=len(li_texts), is_ordered=ordered))
        element_sequence.append("list")
        text_blocks.extend(li_texts)
        # List items can parent nested content (inline groups, definition
        # bodies, sub-lists) — without this recursion that content is dropped
        # (caught by list_after_num_headers: "Term N: Definition N" vanished).
        for it in li_items:
            _recurse(it)
        for k, it in others:
            visit(k, it)

    body = data.get("body", {})
    for ch in body.get("children", []):
        ref = _ref_of(ch)
        if ref:
            k, it = _resolve(data, ref)
            visit(k, it)

    return EvaluationRecord(
        doc_id=doc_id,
        title=headings[0].text if headings else doc_id,
        source_path=source_path,
        source_sha256=source_sha256,
        producer=PRODUCER,
        producer_version=PRODUCER_VERSION,
        tables=tables,
        figures=figures,
        headings=headings,
        lists=lists,
        # Not extracted by this adapter (None ≠ 0): hyperlinks/footnotes are
        # represented differently in DoclingDocument (per-text `hyperlink`
        # fields, footnote labels) and do not map 1:1 onto the OOXML element
        # counts — emitting 0 would make the count metrics flag on an adapter
        # gap on every real document. Implement per-feature when a faithful
        # mapping is established; until then the comparator skips None.
        hyperlink_count=None,
        footnote_count=None,
        endnote_count=None,
        vector_shape_count=None,  # DoclingDocument has no shape inventory
        element_sequence=element_sequence,
        **derived_text_fields(text_blocks),
    )


def extract(json_path: str | Path, **kw) -> EvaluationRecord:
    json_path = Path(json_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    kw.setdefault("doc_id", json_path.stem.split(".")[0])
    kw.setdefault("source_path", str(json_path))
    return extract_from_dict(data, **kw)
