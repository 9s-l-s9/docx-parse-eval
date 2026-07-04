# Docling fixture provenance

## `mini.docling.json` — synthetic, authored

A hand-authored, minimal `DoclingDocument` JSON (v2-style native serialisation)
used as the agent-safe oracle for the Docling adapter (Script 2). It mirrors the
DoclingDocument JSON shape — `body`/`furniture` reading-order refs, `texts` with
`label`/`level`, `groups` for lists, `tables.data.table_cells` with
`column_header`, and `pictures.captions` refs — without depending on the
`docling` / `docling-core` packages (kept out of the harness per R8/R11).

It deliberately exercises: a title + a levelled section header, a paragraph with
identifiers, an **ordered list group**, a **table with header cells**, a
**picture with an associated caption**, and a **furniture-layer `page_header`
that must be excluded** from the projection.

## Public upstream fixtures (vendored) — `../public/`

Real `.docx` sources + their maintainer-blessed `DoclingDocument` groundtruth
JSON, vendored from **docling-project/docling @ `6395151e271277d4a154e7e7f01c71fd72829482`**,
`tests/data/docx/{sources,groundtruth}/` (schema **v1.10.0**). **All 26** docx
fixtures with groundtruth are vendored as `<name>.docx` + `<name>.docling.json`
(checkboxes, comments, external/grouped/VML/EMF images, lists, rich cells/tables,
drawingml, OMML equations, textbox, formatting, headers, …). Upstream licence: MIT.

These drive `tests/test_public_docling.py`. **They caught a real bug** the
authored `mini.docling.json` missed: a real DoclingDocument is a deep **tree**
(`body.children` is a single group; tables/headings nest several levels down),
whereas the authored fixture was flat — the adapter's original one-level walk
extracted nothing. The adapter now does recursive DFS traversal; the public
fixtures are the regression guard.

`mini.docling.json` is retained as a small, fully-controlled projection unit
test (known expected counts); the public fixtures are the real-schema check.
