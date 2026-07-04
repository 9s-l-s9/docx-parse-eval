"""Script 1 — OOXML reference extractor (the gold adapter), spec §5.1.

Reads structure directly from OOXML via python-docx. **Document order in the XML
*is* reading order**, so we walk the body in order and classify each block. The
output is a *silver* ``EvaluationRecord`` (``producer="ooxml-reference"``) — for
the real corpus a human blesses it into gold (Phase 5); for the synthetic
fixture the construction record is already the known answer, and this adapter is
built (TDD) until it reproduces that record exactly.

Classification policy (deterministic, fixture-driven, locale-independent):
- Empty paragraphs (no text, no embedded drawing) are layout whitespace → skipped.
- Every non-text-box ``w:drawing``/``w:pict`` is a *figure* (N drawings in one
  paragraph = N figures); a paragraph's own text survives alongside its figures.
- *Caption*: style named/id'd ``Caption`` **or** the paragraph carries a ``SEQ``
  field — the field is what Word's Insert-Caption emits and is
  locale-independent (localized style names like "Beschriftung" defeat
  name matching).
- *Heading*: effective ``w:outlineLvl`` (direct or via the ``basedOn`` style
  chain; Word's built-in heading styles always define it, in every locale) →
  level = outlineLvl+1; English ``Heading N`` style name as fallback.
- *List item*: effective ``w:numPr`` (direct or via style chain); ordered-ness
  from the numbering part's ``numFmt``; ``List *`` style name as fallback.
  Consecutive items collapse into one list block, breaking on a numbering
  (numId / ordered-ness) change so adjacent distinct lists stay distinct.
- Anything else with text → paragraph.
- Nested tables (table inside a cell, inside ``w:sdt`` content controls, or in
  text boxes) are emitted as their own table blocks, matching how tree-shaped
  parsers (e.g. Docling) report them.
"""

from __future__ import annotations

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from docx_parse_eval.adapters._common import derived_text_fields
from docx_parse_eval.io import sha256_file
from docx_parse_eval.normalize import char_count_normalized, normalize_text, strip_enumeration
from docx_parse_eval.schema import (
    EvaluationRecord,
    FigureRecord,
    HeadingRecord,
    ListRecord,
    TableCellRecord,
    TableRecord,
)

PRODUCER = "ooxml-reference"
PRODUCER_VERSION = "2"

#: numFmt values that mean "not an ordered sequence".
_UNORDERED_NUMFMTS = {"bullet", "none"}


# --- block model -------------------------------------------------------------
class _Block:
    __slots__ = ("kind", "texts", "obj", "extra")

    def __init__(self, kind: str, texts: list[str], obj=None, extra: dict | None = None):
        self.kind = kind  # heading|paragraph|table|figure|caption|list
        self.texts = texts  # text fragments this block contributes (in order)
        self.obj = obj  # underlying python-docx object where useful
        self.extra = extra or {}


# --- style / numbering resolution (locale-independent signals) ---------------
class _DocContext:
    """Resolves style-chain properties (outlineLvl, numPr) and numbering
    formats once per document, so paragraph classification does not depend on
    localized style *names*."""

    def __init__(self, doc: docx.Document):
        self.doc = doc
        self._styles: dict[str, object] = {}
        styles_el = doc.styles.element
        for st in styles_el.findall(qn("w:style")):
            sid = st.get(qn("w:styleId"))
            if sid:
                self._styles[sid] = st
        self._num_fmt = _numbering_formats(doc)

    def _style_chain(self, style_id: str | None):
        seen: set[str] = set()
        while style_id and style_id in self._styles and style_id not in seen:
            seen.add(style_id)
            st = self._styles[style_id]
            yield st
            based = st.find(qn("w:basedOn"))
            style_id = based.get(qn("w:val")) if based is not None else None

    def outline_level(self, p: Paragraph) -> int | None:
        """Effective w:outlineLvl (0-8; 9 = body text), direct formatting
        winning over the style chain."""
        candidates = []
        p_pr = p._p.pPr
        if p_pr is not None:
            candidates.append(p_pr)
        style_id = p.style.style_id if p.style is not None else None
        for st in self._style_chain(style_id):
            st_pr = st.find(qn("w:pPr"))
            if st_pr is not None:
                candidates.append(st_pr)
        for pr in candidates:
            lvl = pr.find(qn("w:outlineLvl"))
            if lvl is not None:
                val = int(lvl.get(qn("w:val"), 9))
                return val if 0 <= val <= 8 else None
        return None

    def num_id(self, p: Paragraph) -> int | None:
        """Effective numbering id (w:numPr → w:numId), direct or via style
        chain. numId 0 explicitly removes numbering."""
        candidates = []
        p_pr = p._p.pPr
        if p_pr is not None:
            candidates.append(p_pr)
        style_id = p.style.style_id if p.style is not None else None
        for st in self._style_chain(style_id):
            st_pr = st.find(qn("w:pPr"))
            if st_pr is not None:
                candidates.append(st_pr)
        for pr in candidates:
            num_pr = pr.find(qn("w:numPr"))
            if num_pr is not None:
                nid = num_pr.find(qn("w:numId"))
                if nid is None:
                    continue
                val = int(nid.get(qn("w:val"), 0))
                return val if val > 0 else None
        return None

    def is_ordered_num(self, num_id: int | None, style_name: str) -> bool:
        """Ordered vs bulleted from the numbering definition; style-name
        heuristic only when the numbering part can't answer."""
        if num_id is not None and num_id in self._num_fmt:
            return self._num_fmt[num_id] not in _UNORDERED_NUMFMTS
        return "Number" in style_name


def _numbering_formats(doc: docx.Document) -> dict[int, str]:
    """numId → level-0 numFmt, resolved through abstractNum indirection."""
    try:
        part = doc.part.part_related_by(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
        )
    except KeyError:
        return {}
    el = getattr(part, "element", None)
    if el is None:
        el = getattr(part, "_element", None)
    if el is None:
        from docx.oxml import parse_xml

        el = parse_xml(part.blob)
    abstract_fmt: dict[str, str] = {}
    for an in el.findall(qn("w:abstractNum")):
        aid = an.get(qn("w:abstractNumId"))
        lvl0 = an.find(qn("w:lvl"))
        if aid is None or lvl0 is None:
            continue
        fmt = lvl0.find(qn("w:numFmt"))
        if fmt is not None:
            abstract_fmt[aid] = fmt.get(qn("w:val"), "")
    out: dict[int, str] = {}
    for num in el.findall(qn("w:num")):
        nid = num.get(qn("w:numId"))
        aref = num.find(qn("w:abstractNumId"))
        if nid is None or aref is None:
            continue
        fmt = abstract_fmt.get(aref.get(qn("w:val")))
        if fmt is not None:
            out[int(nid)] = fmt
    return out


# --- paragraph classification --------------------------------------------------
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _has_ancestor(root, node, tag: str) -> bool:
    anc = node.getparent()
    while anc is not None and anc is not root:
        if anc.tag == tag:
            return True
        anc = anc.getparent()
    return False


def _textbox_contents(element) -> list:
    """All `w:txbxContent` block containers within an element (DrawingML or VML
    text boxes). Their inner `w:p`/`w:tbl` are real content, not figures.
    Word wraps shapes in `mc:AlternateContent` whose `mc:Fallback` repeats the
    same content as VML — processing the fallback too would duplicate every
    text box's text, so only the primary (`mc:Choice`/plain) copy is kept."""
    return [
        box
        for box in element.findall(".//" + qn("w:txbxContent"))
        if not _has_ancestor(element, box, _MC_FALLBACK)
    ]


#: Raster-image references: DrawingML blip + VML imagedata. Counting THESE —
#: not their `w:drawing`/`w:pict` containers — is what parsers' picture
#: inventories mean by "figure": a group drawing holding two images is two
#: figures; a positioned VML shape with no imagedata is none.
_RASTER_TAGS = (
    "{http://schemas.openxmlformats.org/drawingml/2006/main}blip",
    "{urn:schemas-microsoft-com:vml}imagedata",
)


def _figure_count(el, *, exclude_nested_tables: bool = False) -> int:
    """Number of raster images this element hosts. Text-box content is walked
    separately; `mc:Fallback` repeats the `mc:Choice` image as VML; with
    ``exclude_nested_tables`` (cell scanning), images inside a nested table
    are skipped — the nested table's own block accounts for them."""
    count = 0
    for tag in _RASTER_TAGS:
        for node in el.findall(".//" + tag):
            if _has_ancestor(el, node, qn("w:txbxContent")):
                continue
            if _has_ancestor(el, node, _MC_FALLBACK):
                continue
            if exclude_nested_tables and _has_ancestor(el, node, qn("w:tbl")):
                continue
            count += 1
    return count


def _vector_shape_count(body_el) -> int:
    """Graphic containers with no raster image: shapes, connectors, text-box
    frames. Diagrams built from grouped shapes live here — invisible to most
    parsers' picture inventories, so this is a reference-side diagnostic
    (compared only between producers that extract it)."""
    count = 0
    for tag in ("w:drawing", "w:pict"):
        for node in body_el.findall(".//" + qn(tag)):
            if _has_ancestor(body_el, node, _MC_FALLBACK):
                continue
            if _has_ancestor(body_el, node, qn("w:txbxContent")):
                continue  # a shape drawn inside a text box counts via its host
            if not any(node.findall(".//" + t) for t in _RASTER_TAGS):
                count += 1
    return count


#: Literal-text carriers inside a paragraph; the non-None values substitute
#: whitespace so tab/break-separated words don't fuse.
_TEXT_TAGS = {qn("w:t"): None, qn("w:tab"): " ", qn("w:br"): " ", qn("w:cr"): " "}


def _paragraph_text(p_el) -> str:
    """All literal text of a paragraph in document order — unlike python-docx
    `Paragraph.text`, this includes runs wrapped in inline `w:sdt` content
    controls (form fields, checkbox labels), which otherwise vanish from the
    record. Text-box content and `mc:Fallback` duplicates are excluded."""
    parts: list[str] = []
    for node in p_el.iter(*_TEXT_TAGS):
        if _has_ancestor(p_el, node, qn("w:txbxContent")) or _has_ancestor(p_el, node, _MC_FALLBACK):
            continue
        sub = _TEXT_TAGS[node.tag]
        parts.append(sub if sub is not None else (node.text or ""))
    return "".join(parts)


def _cell_text(tc) -> str:
    """A cell's own text: every paragraph in the cell (including ones wrapped
    in `w:sdt` content controls, invisible to python-docx `_Cell.text`), but
    not nested tables (they get their own blocks) or text boxes."""
    paras: list[str] = []
    for p in tc.iter(qn("w:p")):
        if (
            _has_ancestor(tc, p, qn("w:tbl"))
            or _has_ancestor(tc, p, qn("w:txbxContent"))
            or _has_ancestor(tc, p, _MC_FALLBACK)
        ):
            continue
        text = _paragraph_text(p)
        if text.strip():
            paras.append(text)
    return " ".join(paras)


def _is_caption(p: Paragraph) -> bool:
    """Caption style (name or styleId — the id survives some localizations) or
    a SEQ field, which Word's Insert-Caption always emits and no localization
    touches."""
    style = p.style
    if style is not None and ("Caption" in (style.name or "", style.style_id or "")):
        return True
    el = p._p
    for instr in el.findall(".//" + qn("w:instrText")):
        if instr.text and "SEQ" in instr.text.split():
            return True
    for fld in el.findall(".//" + qn("w:fldSimple")):
        if "SEQ" in (fld.get(qn("w:instr")) or "").split():
            return True
    return False


def _heading_level_from_name(style_name: str) -> int | None:
    if style_name and style_name.startswith("Heading "):
        try:
            return int(style_name.split()[1])
        except (IndexError, ValueError):
            return None
    return None


def _classify_paragraph(p: Paragraph, ctx: _DocContext) -> list[_Block]:
    """A paragraph may yield several blocks: its text block (if any) followed by
    one figure block per embedded drawing — inline images must not swallow the
    paragraph's words, and N images are N figures."""
    blocks: list[_Block] = []
    text = normalize_text(_paragraph_text(p._p))
    style_name = p.style.name if p.style is not None else ""
    style_id = p.style.style_id if p.style is not None else ""

    if text:
        if _is_caption(p):
            blocks.append(_Block("caption", [text]))
        else:
            # Heading text is enumeration-stripped on every adapter: Word
            # computes outline numbers at render time, so materialising
            # parsers would disagree with the source on every numbered heading.
            level = ctx.outline_level(p)
            if level is not None:
                blocks.append(_Block("heading", [strip_enumeration(text)], extra={"level": level + 1}))
            elif (name_level := _heading_level_from_name(style_name)) is not None:
                blocks.append(_Block("heading", [strip_enumeration(text)], extra={"level": name_level}))
            elif "Title" in (style_name, style_id):
                # The document title is a level-1 heading structurally — tree
                # parsers (Docling `title` label) report it as one. Best-effort:
                # the Title style carries no outlineLvl, so localized names
                # still fall through to paragraph.
                blocks.append(_Block("heading", [strip_enumeration(text)], extra={"level": 1}))
            else:
                num_id = ctx.num_id(p)
                if num_id is not None:
                    # numPr (direct or via style chain) is the only reliable
                    # list signal. A bare "List *" style NAME is not one:
                    # "List Paragraph" is also applied to un-numbered
                    # continuation paragraphs (misclassified in word_sample).
                    blocks.append(
                        _Block(
                            "list_item",
                            [text],
                            extra={
                                "num_id": num_id,
                                "ordered": ctx.is_ordered_num(num_id, style_name),
                            },
                        )
                    )
                else:
                    blocks.append(_Block("paragraph", [text]))

    for _ in range(_figure_count(p._p)):
        blocks.append(_Block("figure", [], obj=p))
    return blocks


# --- tables --------------------------------------------------------------------
def _table_blocks(t: Table, doc: docx.Document) -> list[_Block]:
    """The table's own block followed by blocks for any tables nested inside
    its cells (recursively) — tree-shaped parsers report nested tables as
    separate tables, and their text is invisible to `cell.text`, so flattening
    them keeps both sides comparable and conserves their content."""
    n_rows, n_cols = len(t.rows), len(t.columns)
    # Distinct underlying cells (merged cells share one <w:tc>): dedupe by id,
    # preserving reading order. The grid positions each tc covers give the
    # per-cell spans for the TEDS tree (schema 0.4).
    seen: dict[int, int] = {}  # id(tc) → index into cell_spans
    distinct_texts: list[str] = []
    cell_spans: list[dict] = []  # {"rows": [..], "cols": [..], "text": str}
    nested: list[_Block] = []
    cell_figures = 0
    grid = t._cells
    grid_ok = len(grid) == n_rows * n_cols and n_cols > 0
    for i, cell in enumerate(grid):
        r, c = divmod(i, n_cols) if grid_ok else (0, 0)
        key = id(cell._tc)
        if key in seen:
            cell_spans[seen[key]]["rows"].append(r)
            cell_spans[seen[key]]["cols"].append(c)
            continue
        seen[key] = len(cell_spans)
        text = normalize_text(_cell_text(cell._tc))
        distinct_texts.append(text)
        cell_spans.append({"rows": [r], "cols": [c], "text": text})
        cell_figures += _figure_count(cell._tc, exclude_nested_tables=True)
        # Nested tables anywhere in the cell (incl. inside content controls);
        # depth-1 findall would miss `w:sdt`-wrapped ones.
        for tbl_el in cell._tc.iter(qn("w:tbl")):
            if not _has_ancestor(cell._tc, tbl_el, qn("w:tbl")):
                nested.extend(_table_blocks(Table(tbl_el, doc), doc))
    cells = (
        [
            TableCellRecord(
                row=min(s["rows"]),
                col=min(s["cols"]),
                row_span=max(s["rows"]) - min(s["rows"]) + 1,
                col_span=max(s["cols"]) - min(s["cols"]) + 1,
                text=s["text"],
            )
            for s in cell_spans
        ]
        if grid_ok
        else None
    )
    has_header = t.rows[0]._tr.find(qn("w:trPr")) is not None and (
        t.rows[0]._tr.find(qn("w:trPr")).find(qn("w:tblHeader")) is not None
    )
    outer = _Block(
        "table",
        distinct_texts,
        extra={
            "n_rows": n_rows,
            "n_cols": n_cols,
            "cell_count": len(distinct_texts),
            "has_header": has_header,
            "cell_text_length": sum(char_count_normalized(c) for c in distinct_texts),
            "cells": cells,
        },
    )
    # Images embedded inside cells: emitted as figure blocks after the table,
    # mirroring how tree parsers report in-cell pictures as table children.
    figures = [_Block("figure", []) for _ in range(cell_figures)]
    return [outer, *nested, *figures]


# --- document walk ---------------------------------------------------------------
def _raw_blocks(doc: docx.Document) -> list[_Block]:
    ctx = _DocContext(doc)
    blocks: list[_Block] = []
    _walk_block_container(doc.element.body, doc, ctx, blocks)
    return blocks


def _walk_block_container(parent, doc: docx.Document, ctx: _DocContext, blocks: list[_Block]) -> None:
    """Iterate block-level children in document order, descending into content
    controls (`w:sdt` → `w:sdtContent`) so block content nested inside them
    (e.g. a table in a content control) is not missed. Does **not** descend into
    a table's own cells (handled by the table extractor) or a paragraph's runs.
    """
    for child in parent.iterchildren():
        if child.tag == qn("w:p"):
            # Text boxes hosted by this paragraph carry real block content:
            # walk it in document order. The host paragraph is still classified
            # afterwards — it may carry its own text and non-text-box drawings.
            for box in _textbox_contents(child):
                _walk_block_container(box, doc, ctx, blocks)
            blocks.extend(_classify_paragraph(Paragraph(child, doc), ctx))
        elif child.tag == qn("w:tbl"):
            blocks.extend(_table_blocks(Table(child, doc), doc))
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                _walk_block_container(content, doc, ctx, blocks)


def _collapse_lists(blocks: list[_Block]) -> list[_Block]:
    """Collapse runs of consecutive list items into list blocks, starting a new
    block whenever the numbering identity (numId, ordered-ness) changes — an
    ordered list followed by a bulleted list is two lists, not one."""
    out: list[_Block] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind == "list_item":
            key = (b.extra.get("num_id"), b.extra["ordered"])
            j = i
            items: list[str] = []
            while (
                j < len(blocks)
                and blocks[j].kind == "list_item"
                and (blocks[j].extra.get("num_id"), blocks[j].extra["ordered"]) == key
            ):
                items.extend(blocks[j].texts)
                j += 1
            out.append(
                _Block("list", items, extra={"ordered": b.extra["ordered"], "n_items": len(items)})
            )
            i = j
        else:
            out.append(b)
            i += 1
    return out


def _assign_captions(blocks: list[_Block]) -> dict[int, str]:
    """Figure block index → caption text. Adjacent *following* caption wins
    (Word's figure convention); an unconsumed adjacent *preceding* caption is
    the fallback (captions above are common in technical documents). Each
    caption block captions at most one figure."""
    assigned: dict[int, str] = {}
    used: set[int] = set()
    fig_idx = [i for i, b in enumerate(blocks) if b.kind == "figure"]
    for i in fig_idx:
        if i + 1 < len(blocks) and blocks[i + 1].kind == "caption" and i + 1 not in used:
            assigned[i] = blocks[i + 1].texts[0]
            used.add(i + 1)
    for i in fig_idx:
        if i in assigned:
            continue
        if i - 1 >= 0 and blocks[i - 1].kind == "caption" and i - 1 not in used:
            assigned[i] = blocks[i - 1].texts[0]
            used.add(i - 1)
    return assigned


def extract(docx_path: str | Path) -> EvaluationRecord:
    docx_path = Path(docx_path)
    doc = docx.Document(str(docx_path))
    blocks = _collapse_lists(_raw_blocks(doc))
    captions = _assign_captions(blocks)

    headings: list[HeadingRecord] = []
    tables: list[TableRecord] = []
    figures: list[FigureRecord] = []
    lists: list[ListRecord] = []
    element_sequence: list[str] = []
    text_blocks: list[str] = []

    for pos, b in enumerate(blocks):
        element_sequence.append(b.kind)
        text_blocks.extend(b.texts)
        if b.kind == "heading":
            headings.append(HeadingRecord(text=b.texts[0], level=b.extra["level"], position=pos))
        elif b.kind == "table":
            tables.append(
                TableRecord(
                    table_id=f"t{len(tables)}",
                    position=pos,
                    n_rows=b.extra["n_rows"],
                    n_cols=b.extra["n_cols"],
                    cell_count=b.extra["cell_count"],
                    has_header=b.extra["has_header"],
                    cell_text_length=b.extra["cell_text_length"],
                    cells=b.extra["cells"],
                )
            )
        elif b.kind == "figure":
            caption = captions.get(pos, "")
            figures.append(
                FigureRecord(
                    figure_id=f"f{len(figures)}",
                    position=pos,
                    caption_text=caption,
                    has_caption=bool(caption),
                )
            )
        elif b.kind == "list":
            lists.append(
                ListRecord(
                    list_id=f"l{len(lists)}",
                    position=pos,
                    n_items=b.extra["n_items"],
                    is_ordered=b.extra["ordered"],
                )
            )

    body_xml = doc.element.body
    hyperlink_count = len(body_xml.findall(".//" + qn("w:hyperlink")))

    return EvaluationRecord(
        doc_id=docx_path.stem,
        title=_title(doc, fallback=docx_path.stem),
        source_path=str(docx_path),
        source_sha256=sha256_file(docx_path),
        producer=PRODUCER,
        producer_version=PRODUCER_VERSION,
        tables=tables,
        figures=figures,
        headings=headings,
        lists=lists,
        hyperlink_count=hyperlink_count,
        footnote_count=_part_count(doc, "footnotes"),
        endnote_count=_part_count(doc, "endnotes"),
        vector_shape_count=_vector_shape_count(body_xml),
        element_sequence=element_sequence,
        **derived_text_fields(text_blocks),
    )


def _title(doc: docx.Document, fallback: str) -> str:
    ctx = _DocContext(doc)
    for p in doc.paragraphs:
        if not normalize_text(p.text):
            continue
        level = ctx.outline_level(p)
        if level == 0 or _heading_level_from_name(p.style.name if p.style else "") == 1:
            return normalize_text(p.text)
    return fallback


def _part_count(doc: docx.Document, kind: str) -> int:
    """Count footnotes/endnotes (excluding the default separator entries)."""
    try:
        part = doc.part.part_related_by(
            f"http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}"
        )
    except KeyError:
        return 0
    # A generic `Part` exposes no `.element`; parse its XML blob directly.
    el = getattr(part, "_element", None)
    if el is None:
        from docx.oxml import parse_xml

        el = parse_xml(part.blob)
    tag = qn("w:footnote") if kind == "footnotes" else qn("w:endnote")
    notes = el.findall(tag)
    # types "separator"/"continuationSeparator" are furniture, not real notes.
    real = [n for n in notes if n.get(qn("w:type")) not in {"separator", "continuationSeparator"}]
    return len(real)
