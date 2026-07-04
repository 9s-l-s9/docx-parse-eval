# Implementation Plan — Docling `.docx` Eval Harness

Companion to `evaluation-framework-spec.md`. Sequencing is dictated by **R8 (sensitive-corpus isolation)**: everything is built and proven on fixtures first; the real 100+ page documents are quarantined to the final phase and never enter an agent/CI context.

**Legend**
- ✅ **agent-safe** — synthetic or public fixtures only; fine to build with an AI agent / in CI.
- 🔒 **local-only** — touches the real, confidential corpus; runs solely in the maintainer's controlled environment. No agent, no third-party service.

---

## Phase 0 — The contract ✅  ✔ **DONE** (13 tests green via `guix shell -m evaluation/manifest.scm -- python3 -m pytest`)
Decide before writing adapters, because the schema is what keeps the comparator dumb.
- [x] Finalise the **model-agnostic `EvaluationRecord`** schema (+ sub-records); freeze `schema_version = "0.1"`. → `src/docx_parse_eval/schema.py` (Pydantic v2, `extra="forbid"`, `ElementType` closed alphabet).
- [x] Implement the **shared normalisation** function (Unicode NFC, whitespace collapse). → `src/docx_parse_eval/normalize.py` (+ shared `word_count`/`char_count_normalized`/`extract_identifier_tokens`). Residual-syntax strip is adapter-local, deferred to Phase 2.
- [x] Decide the **output dataset format** (spec §11): JSON records source-of-truth (`io.py` path helpers); CSV/Parquet in Phase 4; HF deferred. Recorded in `README.md`.
- [x] First-pass §13 decisions centralised in `src/docx_parse_eval/config.py` (identifier regex, figure policy + `GroupedShapePolicy`, matching constants, flag thresholds — all `CALIBRATE-PHASE-4`).

**Provisioning note (resolved):** all harness deps exist in Guix — no packaging needed. `manifest.scm` pins them; **the interpreter inside the profile is `python3`, not `python`** (README documents this).

<details><summary>Phase 0 detailed breakdown (as built)</summary>

### Phase 0 — detailed breakdown

**Outcome of this phase:** a Python package that *imports cleanly and round-trips a record through JSON*, with zero adapter/comparator logic yet. Everything downstream depends only on what is frozen here. No fixtures, no real data.

#### 0.a — Environment & dependency provisioning (Guix-aware)
The repo is a Guix environment; current `manifest.scm` carries only `typst`. The harness needs its own reproducible env, kept **separate** from the Docling container (R8/R11: Docling prediction JSON is produced out-of-band by the `docling-render`/document-intelligence container, never imported as a runtime dep here).
- [ ] Add `evaluation/manifest.scm` (or `guix.scm`) pinning the **harness-core** deps. Triage against Guix availability:
  - Almost certainly in Guix: `python` (≥3.11), `python-pytest`, `python-pandas`, `python-pyarrow`, `python-lxml`.
  - Verify / may need packaging via the `guix-packaging` skill: `python-docx`, `python-levenshtein` (or `python-rapidfuzz`), `python-pydantic` (v2).
  - **Deferred, not Phase 0:** `mlflow` (Phase 4), `datasets`/HF (optional), `docling` (never a harness dep).
- [ ] Run `guix shell -m evaluation/manifest.scm -- python -c "import pydantic, Levenshtein, pandas, pyarrow, docx"` as the env smoke-test. Any import that fails → package it (guix-packaging skill) before proceeding. Record the resolved env (channels/commit) for reproducibility.
- [ ] Pick the test runner invocation (`guix shell -m … -- pytest -q`) and note it in a short `evaluation/README.md`.

**Decision — schema representation:** use **Pydantic v2 `BaseModel`** (not stdlib `@dataclass`), field-for-field identical to spec §7. Rationale: free, validated JSON (de)serialisation (`model_dump_json` / `model_validate_json`) is exactly the §11 "JSON is source of truth" requirement, and validation catches malformed adapter output early. The spec's `@dataclass` listing is the field contract, not a mandate to use stdlib dataclasses. *(If `python-pydantic` proves painful to package in Guix, fall back to stdlib dataclasses + a hand-written `to_dict`/`from_dict`; revisit only if 0.a blocks.)*

#### 0.b — Package layout
- [ ] Create the package skeleton (names provisional, adjust on first commit):
  ```
  evaluation/
    manifest.scm                  # 0.a
    README.md                     # env + run instructions
    pyproject.toml                # metadata + tool config (ruff/pytest), even if Guix provides deps
    src/docx_parse_eval/
      __init__.py
      schema.py                   # 0.c — EvaluationRecord + sub-records, SCHEMA_VERSION = "0.1"
      normalize.py                # 0.d — normalize_text() + helpers
      config.py                   # 0.e — frozen first-pass constants for §13 open items
      io.py                       # 0.f — record (de)serialisation helpers, path conventions
    tests/
      test_schema_roundtrip.py    # 0.c acceptance
      test_normalize.py           # 0.d acceptance
  ```
  (`adapters/`, `comparator.py`, `metrics.py`, `output.py` are created in Phases 2–4, not now.)

#### 0.c — Freeze the schema (`schema.py`)
- [ ] Transcribe §7 exactly: `EvaluationRecord`, `TableRecord`, `FigureRecord`, `HeadingRecord`, `ListRecord` as Pydantic models. Field names/types must match §7 verbatim so the spec stays the readable contract.
- [ ] Module constant `SCHEMA_VERSION = "0.1"`; `EvaluationRecord.schema_version` defaults to it. **Freeze** — any later field change bumps this and is a breaking event (R1, R2).
- [ ] Decision — `full_text_normalized` (§13): **keep it, typed `str | None`, default `None`.** Lets Phase 3 add NED without a schema bump; adapters may omit it (lighter records) without violating the contract.
- [ ] Decision — `element_sequence` allowed values: freeze the literal set `{"heading","paragraph","table","figure","list","caption"}` (spec §7) as an enum/`Literal`, so both adapters and the edit-distance metric share one alphabet.
- [ ] **Acceptance (`test_schema_roundtrip.py`):** construct a fully-populated record by hand → `model_dump_json()` → `model_validate_json()` → assert deep-equal; assert `schema_version == "0.1"`; assert an out-of-alphabet `element_sequence` value raises.

#### 0.d — Shared normalisation (`normalize.py`)
The single function every adapter and the comparator import (spec §7 "Normalisation"), so differences reflect extraction, not formatting.
- [ ] `normalize_text(s: str) -> str`: Unicode **NFC**, collapse internal whitespace runs to a single space, strip leading/trailing whitespace. (Residual-syntax stripping for lossy-format values is adapter-local and parameterised, not baked into the core function — keep core deterministic and side-effect-free.)
- [ ] Helpers reused by adapters/metrics so the *tokeniser is identical on both sides* (§13): `char_count_normalized(s)`, `word_count(s)` (single shared definition), and a placeholder `extract_identifier_tokens(s)` driven by the 0.e regex.
- [ ] **Acceptance (`test_normalize.py`):** NFC idempotence (decomposed é == composed é), whitespace collapse incl. tabs/newlines/NBSP, empty/whitespace-only → `""`, and `normalize_text(normalize_text(x)) == normalize_text(x)` (idempotent).

#### 0.e — First-pass §13 decisions, frozen as config (`config.py`)
Placeholders are fine — they get *calibrated* in Phase 4, but they must be **named and centralised now** so nothing hardcodes them.
- [ ] `IDENTIFIER_REGEX` — first pass: tokens matching numbers w/ optional unit or part-style IDs, e.g. `r"\b\d+(?:[.,]\d+)?\s?(?:mm|cm|m|kg|°|×|±|µ|%)?\b|\b[A-Z]{1,4}-?\d{2,}\b"`. Marked "calibrate in Phase 4"; deliberately conservative to start.
- [ ] `FIGURE_COUNTING_POLICY` — first pass: count `PictureItem`/embedded image parts; **exclude** header/footer (furniture-layer) images; **grouped vector shapes → flag, never silently fail** (spec §13). Encode as named booleans/enums, not inline logic.
- [ ] Matching strategy constants — `MATCH_BY_POSITION_FIRST = True`; similarity-fallback thresholds (`CAPTION_SIM_THRESHOLD`, `TABLE_TEXT_SIM_THRESHOLD`) as named placeholders.
- [ ] Flag thresholds — `LENGTH_RATIO_DELTA (δ)`, `DUPLICATION_EPSILON (ε)`, `NED_THRESHOLD`, `JACCARD_THRESHOLD`, `SEQ_EDIT_DISTANCE_THRESHOLD` — all named placeholders with a `# CALIBRATE-PHASE-4` marker.
- [ ] **Tokeniser decision (§13):** word/identifier tokenisation lives in `normalize.py` and is imported by both sides — settle it here as "shared module, no per-adapter copies."

#### 0.f — Output format decision (lightweight; real emit is Phase 4)
- [ ] Record the §11 decision in `README.md` + path helpers in `io.py` — JSON records are source of truth (`gold/<doc_id>.json`, `pred/<doc_id>.<producer>.json`); comparison results emit as **CSV + Parquet** long-form in Phase 4; **HF packaging deferred** until a second adapter exists (§13). No emit code beyond path/(de)serialise helpers in this phase.

#### Phase 0 exit criteria
- `guix shell -m evaluation/manifest.scm -- pytest -q` is **green** (schema round-trip + normalisation tests pass).
- `schema.py`, `normalize.py`, `config.py` import without error; `SCHEMA_VERSION == "0.1"` is frozen.
- Every §13 open item has a *named, centralised* first-pass value (calibrated later, never hardcoded downstream).
- **Next:** Phase 1 — author the synthetic `.docx` fixture + its gold-by-construction record.

</details>

## Phase 1 — Fixtures (build the self-test layer first) ✅  ✔ **DONE (1.a–1.d)** · 1.e deferred to Phase 2 · 23 tests green
- [x] **Author the synthetic `.docx`** with known structure → `tests/fixtures/build_synthetic.py` builds it: 2 tables (Table A 4×3 + header row; Table B 3×3 with a merged spanning row, `cell_count`=7), 3 figures (2 captioned + 1 uncaptioned), 7 headings (2×H1/3×H2/2×H3), an ordered list, seeded part-numbers/units/special chars. **Byte-stable** (zip timestamps zeroed → reproducible `source_sha256`).
- [x] **Gold record by construction** — emitted from the *same* construction pass (`synthetic.gold.json`), text fields via shared `normalize.py`. No blessing needed (R9).
- [x] **Mutated red case** + full mutation menu → `tests/fixtures/mutations.py`: each mutation is a pure `record → (mutated, expected_flags)` (drop_figure, corrupt_identifier, duplicate_block, alter_table_dims, reorder_sequence). Canonical `synthetic.mutated.json` = `corrupt_identifier`. Flag names are the Phase-3 metric-id contract.
- [ ] **Public Docling fixtures (1.e)** — deferred to **start of Phase 2** (only needed there; plan allows). Vendor 1–2 `tests/data/*.docx` + `tests/data/groundtruth/docling_v2/*.json` into `tests/fixtures/public/` with `SOURCE.md` provenance.

Acceptance (`tests/test_fixtures.py`): gold schema-valid + known-structure-by-construction, `source_sha256` matches the `.docx` (R7), canonical mutation differs on exactly one axis, every mutation changes the record and declares flags.

### Phase 1 — detailed breakdown

**Outcome of this phase:** a small, permanent set of fixtures (committed, agent-safe) whose answers are known *by construction* — the substrate Phases 2–3 are built against and the regression net they keep. No adapter/comparator code yet; this phase produces **data + the generator that makes it deterministic**.

**Why a generator, not a hand-saved binary.** The `.docx` must be reproducible and diff-reviewable, and its gold must be provably the known answer. So author it programmatically with `python-docx` and emit the matching gold record from the *same* construction parameters — the fixture and its gold are two outputs of one script, which is what "gold by construction, no blessing" actually means (R9).

#### 1.a — Fixture layout
- [ ] Create the fixtures tree (committed; tiny):
  ```
  evaluation/tests/fixtures/
    build_synthetic.py        # 1.b — authors synthetic.docx + emits synthetic.gold.json
    synthetic.docx            # generated, committed (small, agent-safe)
    synthetic.gold.json       # gold-by-construction EvaluationRecord (producer="fixture-construction")
    synthetic.mutated.json    # 1.d — gold with ONE injected defect
    mutations.py              # 1.d — pure functions: gold record -> mutated record (+ expected flags)
    public/                   # 1.e — vendored Docling public fixtures (see caveat)
      <name>.docx
      <name>.docling_v2.json
      SOURCE.md               # provenance + upstream commit/licence note
  ```

#### 1.b — Author the synthetic `.docx` (`build_synthetic.py`)
Construct with `python-docx` so structure is exact and known. Must exercise every schema field group and the *hard* cases the public fixtures won't (§6.2):
- [ ] **Headings:** 3 levels (e.g. 2× H1, 3× H2, 2× H3) — exercises heading-count-by-level (§8.1).
- [ ] **Tables (2):**
  - Table A: plain, with a **header row** (`has_header=True`), e.g. 4×3.
  - Table B: contains a **merged cell** (`gridSpan`/`vMerge`) — the structure-metric stress case (§8.2). Record its *true* `(n_rows, n_cols, cell_count)` accounting for the merge per the figure-counting/cell-counting policy frozen in `config.py` (0.e).
- [ ] **Figures (2–3):** embed small raster images, each with a **caption paragraph** (Word caption style) → exercises caption count + association (§8.1). Include **one figure without a caption** to make `has_caption` non-trivial.
- [ ] **List (1):** an ordered or bulleted list with a known `n_items` → exercises list-item-count (catches list→paragraph flattening).
- [ ] **Identifier tokens / special chars:** sprinkle a few part numbers and measurements (e.g. `PN-12345`, `120 mm`, `±0.5°`, `24 V`) so `identifier_tokens` and `special_chars` are populated and the 0.e regex has something to bite on.
- [ ] **Paragraphs:** enough body text that `word_count` / `char_count_normalized` / length-ratio are meaningful.
- [ ] Set a fixed image payload + deterministic content so `synthetic.docx` is byte-stable across runs (reproducible `source_sha256`).

#### 1.c — Gold-by-construction record (`synthetic.gold.json`)
- [ ] In the *same* script, build the `EvaluationRecord` from the construction parameters (the script *knows* it made 2 tables, 3 figures, 7 headings, …) — not by parsing the `.docx` back. This is the known answer.
- [ ] Run it through the shared `normalize.py` (0.d) so the gold's text fields are already normalised exactly as adapters will produce.
- [ ] `producer="fixture-construction"`, `source_sha256` = hash of the emitted `.docx`, `schema_version="0.1"`.
- [ ] **Acceptance:** validates against the Pydantic schema (`model_validate_json`) and `element_sequence` uses only the frozen alphabet (0.c).

#### 1.d — Mutated red case (`mutations.py` → `synthetic.mutated.json`)
The sensitivity half (§6.1) — usually the missing one. Each mutation is a **pure function** `gold_record -> mutated_record` paired with the **exact metric(s) expected to fire**, so Phase 3's red test asserts *that specific flag*, not just "something flagged."
- [ ] Implement a small menu, each isolating one metric:
  - `drop_figure` → figure-count + caption-count flags.
  - `corrupt_identifier` (e.g. `PN-12345`→`PN-12745`) → identifier-token Jaccard flag.
  - `duplicate_block` (repeat a table's text in body flow) → duplication-direction (length ratio > 1+ε) flag.
  - `merge_table_dims` (alter `(n_rows,n_cols,cell_count)`) → per-table dimension flag.
  - `reorder_sequence` → element-sequence edit-distance flag.
- [ ] Ship the **primary** mutated fixture as `synthetic.mutated.json` (pick `corrupt_identifier` as the canonical single-defect red case); keep the rest callable for Phase 3's parametrised red tests.
- [ ] Each mutation function returns `(record, expected_flags: set[str])` — the contract Phase 3 asserts against.

#### 1.e — Public Docling fixtures (plumbing check, secondary)
- [ ] Vendor 1–2 small `.docx` from upstream `docling` `tests/data/` **plus** their committed `tests/data/groundtruth/docling_v2/*.json` into `tests/fixtures/public/`. Record upstream commit + licence in `SOURCE.md`.
- [ ] These feed Phase 2's plumbing test: `.docx`→Script 1 and the committed JSON→Script 2 should project to consistent schema shape. **Caveat (spec §6.2):** minimal — proves plumbing, *not* the figure/merged-cell hard path. The synthetic fixture remains primary.
- [ ] If upstream fetch is awkward in this env, defer to start of Phase 2 (it's only needed there); note the chosen file names here.

#### Phase 1 exit criteria
- `build_synthetic.py` regenerates a byte-stable `synthetic.docx` + a schema-valid `synthetic.gold.json` deterministically.
- `synthetic.mutated.json` exists and differs from gold in exactly one defect, with its expected-flag set recorded.
- At least one public `.docx` + its `docling_v2.json` are vendored with provenance (or explicitly deferred to Phase 2 with names chosen).
- **Next:** Phase 2 — build Script 1 (OOXML reference extractor) until it reproduces `synthetic.gold.json`, then Script 2 against the Docling JSON.

## Phase 2 — Adapters (fixture-first / TDD) ✅  ✔ **DONE** · 34 tests green
- [x] **Script 1 — OOXML reference extractor (gold adapter)** → `src/docx_parse_eval/adapters/ooxml_reference.py`. Reproduces `synthetic.gold.json` exactly (structure; `title`/provenance excluded). Walks `doc.element.body` in reading order; classifies blocks (figure = paragraph w/ `w:drawing`; `Caption`/`Heading N`/`List *` by style; empty paragraphs skipped as layout whitespace); collapses consecutive list items; dedupes merged `<w:tc>` for true `cell_count`; derives `has_header` from `<w:tblHeader/>`. Shared text/token projection via `adapters/_common.py`.
  - **TDD-surfaced fixes:** (1) `build_synthetic.py` now writes the real `<w:tblHeader/>` marker so `has_header` is *derivable*, not asserted; (2) `title` is human metadata, not conservation structure → excluded from the structural comparison (like provenance).
- [x] **Script 2 — Docling adapter (`DoclingDocument` JSON → schema)** → `src/docx_parse_eval/adapters/docling_adapter.py`. **Design choice:** parses the native JSON as a **portable dict** (zero-dep) rather than importing `docling-core` — keeps Docling fully out of the harness (R8/R11), and `docling-core` isn't in Guix anyway. Walks `body.children` refs in reading order, excludes the `furniture` layer, maps `title`/`section_header`→headings, list `groups`→list, `tables.data.table_cells` (dedupe by grid origin, `column_header`→`has_header`), `pictures.captions`→figure caption. Reuses `_common.py`.
- [x] **Oracle fixtures:** authored `mini.docling.json` (small controlled projection test) **and vendored the real public corpus** → `tests/fixtures/public/` (4 real `.docx` + real groundtruth `DoclingDocument` JSON, docling @ 6395151, schema v1.10; `test_public_docling.py`).
  - ⚠️ **Real data caught a real bug.** A real DoclingDocument is a deep **tree** (`body.children` = one group; tables/headings nest levels down), not the flat list `mini.docling.json` assumed. The adapter's original one-level walk extracted **nothing** from real input (0 tables where there are 5). **Fixed:** `docling_adapter` now does recursive DFS traversal (section-header texts parent their section body). Also fixed an OOXML crash (`Part` has no `_element`) on `word_sample`. Both adapters now parse real inputs and **agree on coarse content** (word_tables: both 5 tables / 164 words); the comparator surfaces genuine fine-grained disagreements (header detection, a heading level) per spec §3.
- [x] **`test_adapter_shape_equivalence.py`** — both adapters emit the identical schema field set + frozen `element_sequence` alphabet, round-trip-valid (R1 guard).

**Next:** Phase 3 — Script 3 comparator + metric set (§8); green test = synthetic gold vs the OOXML extraction (all-match), red test = `mutations.py` cases each firing exactly their declared flag.

### Phase 2 — detailed breakdown

**Outcome of this phase:** two adapters that each project a *native* format into the frozen `EvaluationRecord`, each developed TDD against a known-answer fixture (R9), and a shape-equivalence test proving the contract holds across both. Still no comparator/metrics — that's Phase 3.

**Method (both scripts).** Red→green against fixtures: write the failing test that asserts the adapter reproduces the fixture's known record, then build the adapter until green. The synthetic fixture (Phase 1) is the hard-path oracle for Script 1; the public Docling groundtruth JSON is the oracle for Script 2.

#### 2.a — Module layout
- [ ] Add to the package (created empty-of-logic in Phase 0):
  ```
  src/docx_parse_eval/adapters/
    __init__.py
    ooxml_reference.py     # Script 1 — gold adapter   (producer="ooxml-reference")
    docling_adapter.py     # Script 2 — Docling adapter (producer="docling-adapter")
    _common.py             # shared projection helpers (sequence builder, token/char counting)
  tests/
    test_ooxml_adapter.py
    test_docling_adapter.py
    test_adapter_shape_equivalence.py
  ```
- [ ] Both adapters import `normalize.py` (0.d) and `config.py` (0.e) — **no private copies** of normalisation, tokenisation, or thresholds. `_common.py` holds projection logic that is genuinely format-agnostic (building `element_sequence`, computing `identifier_tokens`/`special_chars` from already-extracted text) so it cannot drift between the two sides.

#### 2.b — Script 1: OOXML reference extractor (`ooxml_reference.py`)
- **Input:** a `.docx`. **Output:** a **silver** `EvaluationRecord`, `producer="ooxml-reference"`. (Silver, not gold — a human blesses it for the *real* corpus in Phase 5; for the synthetic fixture the construction record is already gold.)
- [ ] Read structure directly from OOXML via `python-docx` + raw XML traversal where needed (spec §5.1). **Document order in the XML *is* reading order** — iterate the body in order to build `element_sequence`.
- [ ] **Tables:** read the grid; honour `gridSpan`/`vMerge` for the *true* `(n_rows, n_cols, cell_count)`; detect header row (`<w:tblHeader>` / first-row heuristic) → `has_header`; sum normalised cell text → `cell_text_length`. This is the merged-cell hard case the synthetic Table B exists to prove.
- [ ] **Figures:** count embedded image parts per the `FIGURE_COUNTING_POLICY` (0.e) — exclude header/footer furniture; associate the adjacent caption paragraph (Word `Caption` style / `SEQ` field) → `caption_text`, `has_caption`. Grouped vector shapes → **flag-worthy, not silently dropped** (record per policy).
- [ ] **Headings:** map `w:pStyle` heading levels → `HeadingRecord(level, text, position)`.
- [ ] **Lists:** detect `numPr` (numbering) → `ListRecord(n_items, is_ordered)`; distinguish ordered vs bulleted via the numbering definition.
- [ ] **Scalars:** `hyperlink_count` (`w:hyperlink`), `footnote_count`/`endnote_count` (footnotes/endnotes parts), `word_count`/`char_count_normalized` via shared helpers.
- [ ] **Tokens:** `identifier_tokens` (sorted multiset via 0.e regex), `special_chars` set.
- [ ] **Acceptance (`test_ooxml_adapter.py`):** run on `synthetic.docx` → assert deep-equal to `synthetic.gold.json` **except** provenance fields (`producer`, `producer_version`). Any diff = an extractor bug → fix until green. This is the green/specificity proof for Script 1.

#### 2.c — Script 2: Docling adapter (`docling_adapter.py`)
- **Input:** the **`DoclingDocument` JSON** (lossless native), **never** HTML/Markdown (R11). **Output:** `EvaluationRecord`, `producer="docling-adapter"`, **never hand-edited** (R2).
- [ ] Parse via the `docling-core` types (`DoclingDocument.model_validate(json)`), iterating `iterate_items()` (spec §5.3). Prefer the typed API over raw-dict spelunking so the adapter tracks Docling's schema.
- [ ] **Tables:** `TableItem` exposes `num_rows`, `num_cols`, the cell list, and `column_header` → map directly to `TableRecord`; sum cell text for `cell_text_length`.
- [ ] **Figures:** `PictureItem` is first-class; captions via `item.caption_text(doc)` / caption refs → `FigureRecord`.
- [ ] **Layers:** use body-vs-furniture (`content_layer`) to exclude header/footer per the same 0.e policy Script 1 uses — the two sides must apply the *identical* figure/furniture rule or the count metric flags on policy, not on Docling.
- [ ] **Sequence/headings/lists/scalars/tokens:** same `_common.py` projection as Script 1, fed from Docling labels (`SectionHeaderItem` level, `ListItem`, etc.).
- [ ] **Obtaining the input JSON for the test (R8-safe):** use the **public Docling groundtruth JSON** (Phase 1.e) as the primary oracle — it is maintainer-blessed and needs no local Docling run. Optionally, the maintainer can run Docling locally on `synthetic.docx` to get a second JSON, but that is not required to build/test the adapter and stays out of CI.
- [ ] **Acceptance (`test_docling_adapter.py`):** feed the public `*.docling_v2.json` → assert the projected record is schema-valid and matches a small **expected-projection record** committed alongside it (counts/sequence the public fixture is known to contain). This proves the Docling→schema projection independently of Script 1.

#### 2.d — Cross-adapter shape equivalence
- [ ] **`test_adapter_shape_equivalence.py`:** on the shared public `.docx`/JSON pair, assert both adapters emit the **same record *shape*** — identical field set, identical types, `element_sequence` drawn from the same frozen alphabet (0.c). This is the R1 guard: it checks *shape*, not values (values are the comparator's job in Phase 3). A shape mismatch here means one adapter diverged from the contract.
- [ ] Note: shape-equal ≠ value-equal. The public fixtures are minimal (§6.2 caveat) and may legitimately differ in *values* between the OOXML and Docling views; Phase 3 decides whether such differences should flag.

#### Phase 2 exit criteria
- `test_ooxml_adapter.py` green: Script 1 reproduces `synthetic.gold.json` (provenance aside) — incl. the merged-cell table and caption association.
- `test_docling_adapter.py` green: Script 2 projects the public Docling JSON to a schema-valid, expected record.
- `test_adapter_shape_equivalence.py` green: both adapters honour the identical schema shape (R1).
- No threshold/normalisation logic duplicated across adapters (all via `normalize.py`/`config.py`).
- **Next:** Phase 3 — Script 3 comparator + metric set, with the green (synthetic gold vs itself) and red (`synthetic.mutated.json`) tests.

## Phase 3 — Comparator + metrics ✅  ✔ **DONE** · 42 tests green
- [x] **Script 3** → `src/docx_parse_eval/comparator.py`. Pure, model-agnostic (R4); `compare(gold, pred) -> list[MetricResult]` + `fired_flags()`. Tables matched position-first by index (a count/dim mismatch is itself the flag). `MetricResult(metric, source_value, prediction_value, ratio_or_score, flag)` (Pydantic, JSON/Parquet-ready for Phase 4).
- [x] **Metric set (§8.1–§8.4):** figure/caption/list-item/hyperlink/foot-/endnote counts; heading-count-by-level histogram; per-table `(rows,cols,cell_count)` dims + header detection; `element_sequence` Levenshtein distance; identifier-token Jaccard; table-text-length & length ratios; duplication direction (`>1+ε`); special-char survival; optional full-text NED. Edit distance via `Levenshtein` (R4) — element types encoded to single chars.
- [x] **Green test (specificity):** gold vs OOXML extraction of the same `.docx`, and gold vs itself → **zero flags**.
- [x] **Red test (sensitivity):** every `mutations.py` case fires its declared flag; `corrupt_identifier` is **isolated to exactly `identifier_token_overlap`**.
- [x] **Threshold tuned by TDD:** `SEQ_EDIT_DISTANCE_THRESHOLD` → 1 (transposition=dist 2 fires; single drop=dist 1 stays quiet so the count metric is that defect's signal).

**Next:** Phase 4 — emit dataset artifacts (JSON records + CSV/Parquet long-form, §11), wire MLflow run (params/metrics/artifacts/tags), calibrate thresholds on fixtures. *Note: `mlflow` is not yet in `manifest.scm` (deferred dep) — add it / check Guix availability at Phase 4 start; the §11 file emit (pandas/pyarrow) needs no new deps.*

## Phase 4 — Output, MLflow + calibration ✅  ✔ **DONE (agent-safe scope)**; HF/flattened/snapshot deferred · 58 tests green
- [x] **Dataset artifacts (§11)** → `src/docx_parse_eval/output.py`. JSON records via `io.py` (authoritative); comparison results as a **tidy long-form table** (`results_to_long_df`, one row per `doc_id×producer×metric` with `RESULT_COLUMNS`) emitted as **CSV + Parquet** (`write_results_table`). Tested: emit + Parquet round-trip + flag column fidelity (green→0 flags, `corrupt_identifier`→1).
- [x] **MLflow wired as an *optional, import-guarded* hook** (`mlflow_log`): logs params + per-doc metrics + `flag_count` + the §11 files as artifacts when mlflow is present, **no-ops otherwise**. `mlflow` is **not in Guix** (heavy dep tree) → not added to `manifest.scm`; it stays a local/maintainer overlay, consistent with §11 (files are source of truth). Per spec §10, the deterministic checks stay plain tracking (no `mlflow.genai`).
- [x] **Calibrate flag thresholds (δ, ε, NED, Jaccard, seq-distance) on fixtures** → `tests/test_calibration.py` pins each threshold's boundary (sub-threshold stays quiet = no false alarm on formatting-scale noise; supra-threshold fires). `config.py` now points to this calibration record. Values stay first-pass until real-corpus-derived synthetic fixtures refine them (Phase 5 feedback loop, R8).
- [ ] **HF dataset bundle** — deferred until a 2nd adapter/producer is added (§13).
- [ ] **(Optional) Flattened element-level table** (§11) + **snapshot tier** — deferred.
- [x] **End-to-end runner** → `src/docx_parse_eval/cli.py` (`docx-parse-eval` console script). Subcommands `bootstrap` (Script 1 → silver), `predict` (Script 2 → prediction), `compare` (Script 3 → CSV/Parquet + optional `--mlflow`). `compare` **exits non-zero when any flag fires** → CI flag gate. Tested (`test_cli.py`) + smoke-run verified. Documented in `README.md`.

### Known gaps surfaced by the full public corpus (26 fixtures) — feed Phase 2 maintenance
Both adapters parse all 26 real `.docx`/JSON **without crashing** (87 tests green). The broad set exposed real **OOXML reference-extractor coverage gaps** (the gold side). Per R8/§6.3 each is **distilled into a minimal synthetic fixture and fixed there**, not hand-patched on the real docs:
- [x] **Content-control nested tables (`w:sdt`) — FIXED.** `docx_rich_tables_01` was OOXML 0 tables/147 words vs Docling 2/1558. Distilled → `build_sdt_table.py`/`test_sdt_table.py`; `_raw_blocks` now descends into `w:sdtContent`. Result: real doc now **2 tables/1591 words** (matches Docling). `body.iterchildren()` previously saw only top-level `w:tbl`.
- [x] **Text-box content (`txbxContent`) — FIXED.** `textbox` was OOXML 18 figures/19 words. Distilled → `build_textbox.py`/`test_textbox.py` (DrawingML text box). Fix: `_paragraph_is_figure` excludes drawings carrying `w:txbxContent`; `_walk_block_container` extracts text-box block content in order. Real doc now **5 figs/527 words** (text extracted; the residual 527-vs-273 gap is now legit parser disagreement over 18 nested boxes, not a clear bug — left for human triage per §3). **Bonus:** figure detection now also recognises legacy VML `w:pict` → `docx_vml_images` aligns at 2 figs/43 words (was 0).
- [x] **Smaller divergences — triaged (2026-07-02).** Systematic investigation of every remaining public-corpus divergence found **six more harness bugs** (fixed, pinned in `test_hard_cases.py`, adapters at `producer_version=2`):
  - *Docling adapter:* rich-cell content double-counted (in `table_cells` AND the table's `children` tree → `docx_rich_cells` 376-vs-227 words; now table subtrees emit only pictures/nested tables); list-item children dropped (`list_after_num_headers`'s "Term N: Definition N" vanished; now recursed); comments leaked in (`content_layer:"notes"` ≠ furniture; `docx_comments` now 38/38); `enumerated` field ignored → `is_ordered` always False (`word_sample` ordered lists).
  - *OOXML:* inline/cell-level `w:sdt` text invisible to `Paragraph.text`/`_Cell.text` (`docx_checkboxes`); figures inside table cells uncounted (`docx_rich_cells` 0-vs-2); `Title` style ↔ Docling `title` label policy aligned (heading level 1; `unit_test_headers` now 0 flags); bare `List *` style-*name* fallback removed (misclassified un-numbered "List Paragraph" continuations in `word_sample` — `numPr` is the only reliable signal).
  - **Remaining divergences are genuine parser disagreements** (correct flags, human-triage territory): `tablecell` — Docling collapses nested tables to 1 table + a list (OOXML sees 3; words agree 18/18); `docx_checkboxes` — Docling drops the checkbox state glyphs (☒/☐ ×12) OOXML extracts from sdt content; `word_sample` — Docling fails to label/associate a Caption-styled+SEQ caption; `drawingml` — Docling counts 3 vector shapes as pictures (source has 1 raster image), inconsistent with `textbox` where it counts 0; OMML fixtures — math is representational (Docling → LaTeX tokens, OOXML drops `m:t`); a future policy could exclude formula content from both sides.

### Adjudication round 2 (2026-07-02) — schema 0.3: figure = raster image; enumeration & inline-split policies
Adjudicating each divergence against the source XML (R3) flipped two verdicts AGAINST the reference and produced three policy fixes (public-corpus flags 38 → 29, all remaining ones genuine; 112 tests):
- [x] **Raster-based figure counting.** `docx_vml_images`'s "third image" was a VML shape with no `v:imagedata`; `docx_grouped_images`'s "missing figure" was one `w:drawing` holding two `a:blip`s. Figures are now counted per raster reference (`a:blip`/`v:imagedata`), matching what parsers' picture inventories mean — both fixtures now agree exactly.
- [x] **`vector_shape_count` (schema 0.3).** Shapes/connectors/text-box frames tracked as a separate `int | None` diagnostic so shape-built workflow diagrams (spec §13's core worry) stay measurable: `textbox` now reports figs 0/0 + **27 shapes** instead of a false 11-vs-0 figure flag. Docling side is `None` (no shape inventory) → informational row.
- [x] **Heading enumeration stripped symmetrically** (`normalize.strip_enumeration`, both adapters): Docling materialises Word's computed outline numbers ("1.2 Scope"), the source can't. `unit_test_headers_numbered` words now 85/85; the two spurious `identifier_token_overlap` flags are gone (aided by tightening `IDENTIFIER_REGEX`: unit required / decimal / ≥3 digits — bare small integers no longer pollute the token set).
- [x] **Docling `inline` groups project as ONE paragraph** — they are a single source paragraph split at formatting boundaries; `unit_test_formatting`'s sequence went from 23 blocks (dist 14) to 12 (dist 3, residual = Docling splitting one list into two groups).

### Standalone-package hardening (post-Phase-4 review) — schema 0.2, producer_version 2 · 101 tests green
Review pass reframing the harness as a **general `.docx` parser-comparison package** (multiple producers, not just Docling). Each fix pinned by `tests/test_hard_cases.py` (in-test by-construction fixtures, R9):
- [x] **Schema 0.2 — `None` ≠ 0 for scalar counts.** `hyperlink/footnote/endnote_count` are now `int | None`; `None` = "this producer's adapter does not extract this feature" and the comparator emits a non-flagging `not-extracted` row. Fixes the guaranteed false flags from the Docling adapter's hardcoded zeros (it now declares `None`).
- [x] **Locale-independent OOXML classification.** Headings via effective `w:outlineLvl` (direct + `basedOn` style chain; English `Heading N` name as fallback); captions via `SEQ` fields (what Insert-Caption emits in every locale) + style name/id; lists via effective `w:numPr`, ordered-ness resolved from the numbering part's `numFmt` (not `"Number" in style-name`). German-authored documents ("Überschrift 1", "Beschriftung", toolbar lists on "Listenabsatz") previously extracted **zero** headings/captions/lists.
- [x] **Inline images.** A paragraph with text + drawings keeps its text and yields one figure per non-text-box drawing (was: text swallowed, N drawings = 1 figure). Caption association now also accepts an adjacent *preceding* caption (captions-above convention).
- [x] **Adjacent lists stay distinct** (collapse breaks on `numId`/ordered change; was: ordered+bulleted merged into one list with the first list's ordered flag).
- [x] **Nested tables** (table inside a cell) emitted as separate table blocks recursively — matches tree-shaped parsers; their text (invisible to `cell.text`) is conserved.
- [x] **`mc:AlternateContent` dedup.** `mc:Fallback` repeats the `mc:Choice` content as VML; both were processed → text boxes double-counted. The `textbox` fixture's "residual 527-vs-273 word gap" (previously filed as parser disagreement) was exactly this bug: now **273/273 exact agreement**. `drawingml` figures now 4/4. Per-drawing figure counting also exposed a real Docling gap on `docx_vml_images` (3 picts in source, Docling reports 2 — correct flag).
- [x] **Comparator:** multiset (not set) identifier-token Jaccard per spec §7; caption association falls back to greedy similarity matching when figure counts differ (no zip-misalignment cascade); length metrics flag on gold-empty/pred-nonempty; full-text NED uses `score_cutoff` (banded early-exit) so it stays feasible on 100+-page documents; `NON_GATING_METRICS` tier (`table_header_detection` — OOXML `w:tblHeader` vs parser-inferred headers are different definitions) excluded from `fired_flags()`/the CLI exit gate but still visible in results.

### Real-data validation on docling-dpbench (HF benchmark) — experiment, not CI
`experiments/dpbench_experiment.py` runs the harness over **200 real benchmark docs** from `docling-project/docling-dpbench` (each row has a ground-truth + predicted `DoclingDocument`; both pushed through Script 2, then Script 3). Parquet (~263 MB) lives in scratch, **not committed**.
- **Robustness:** 0 parse failures over **400** real DoclingDocuments, 0 compare failures over 200 pairs (validates the tree-traversal adapter at scale).
- **Specificity:** of 9 rows projecting to identical records, **0 flagged** (no false alarms).
- **Sensitivity:** of 191 differing rows, **151 (79%) flagged**; the unflagged remainder is mostly correct sub-threshold text noise (within δ/NED bands).
- **⚠️ Found a missing metric → FIXED.** The differing-but-unflagged rows exposed that the spec §8.1 **caption-association** metric (matched figure → caption-text similarity) was not implemented. Added `caption_association` to `comparator.py` (Levenshtein ratio vs `CAPTION_SIM_THRESHOLD`) + `corrupt_caption` red mutation. It now fires on **24 real rows**; green/specificity preserved. 90 tests green.
- **Scope (honest):** this exercises the comparator + Docling adapter and is a *robustness/plausibility* check — it does **not** certify metric correctness (no known-true answer; both sides Docling → Script 1/OOXML untested; circularity per §3). The by-construction synthetic fixtures remain the correctness certificate. This is the `docling-eval`-format real-data check anticipated by §11/§12.

## Phase 5 — Real corpus 🔒
Only after the harness is green on fixtures. Performed locally; the agent is not involved.
- [ ] (local) Run **Script 1** on each real `.docx` → silver record.
- [ ] (local) **Human-bless** silver → gold; commit gold (with `source_sha256`) to the private/controlled store.
- [ ] (local) Run Docling on the real docs → **Script 2** → prediction records.
- [ ] (local) Run **Script 3** → metrics → MLflow; **inspect every row** (N=4).
- [ ] (local) Any extractor bug found here → **distil into a NEW minimal synthetic fixture**, fix against that (back in Phase 2/3, ✅), never debug on the 100-page doc.

## Phase 6 — Quality tier & diagnostics (future)
- [ ] (Optional, cheap) **HTML export-loss diagnostic:** add a second Docling adapter reading the HTML export; compare `native` vs `html` records to quantify what HTML drops (empirically justifies R11). ✅ runs on fixtures.
- [x] **Tables: TEDS / TEDS-Struct — DONE (2026-07-02, schema 0.4, 120 tests).** `TableRecord.cells` (per-cell grid: origin, spans, text — structured, no HTML round-trip; `None` = grid unrecoverable → skipped) emitted by both adapters + gold-by-construction. `src/docx_parse_eval/teds.py` implements the PubTabNet metric definition (arXiv:1911.10683, same as docling-eval's scorer) with the tree-edit core from **`python-apted`** (in Guix — added to `manifest.scm`), text similarity via Levenshtein (R4: no algorithm reimplemented). Comparator emits `table_teds` + `table_teds_struct` (worst matched pair; `TEDS_THRESHOLD`/`TEDS_STRUCT_THRESHOLD` = 0.95, boundary-pinned). Red mutations: `corrupt_table_cell` (TEDS fires, Struct quiet — isolation) and `merge_table_cells` (same rows×cols, both fire — invisible to the dims metric). **Public-corpus payoff:** clean tables certify at exactly 1.0 (`word_tables`, `docx_rich_tables_01`, `docx_rich_cells`); `tablecell`'s nested-table collapse is now *quantified* (TEDS 0.16/Struct 0.23); `table_with_equations` reads as "structure 1.0, text 0.71" (math representation). docling-eval itself was evaluated and rejected as a dependency: its scorer is the same PubTabNet+apted stack but drags the full docling dep tree into the harness (R8/R11).
### Workflow hardening (2026-07-02, follow-up pass) — R7 enforced, alignment, Phase-5 tooling, snapshot tier · 130 tests
- [x] **R7 enforced, not just documented.** Comparator emits a `source_identity` metric (flags when both records carry a `source_sha256` and they differ; informational when a side is unknown); `compare`/`run` **refuse** (exit 2) on mismatch unless `--allow-source-mismatch`.
- [x] **Table alignment fallback (spec §5.4, finally).** `_align_tables` greedy-matches by cell-text similarity when counts differ (`TABLE_TEXT_SIM_THRESHOLD`, previously unused) — a dropped/extra table no longer shifts every later TEDS pair onto the wrong partner; unmatched tables stay a count defect owned by `table_dimensions`. Plus `TEDS_MAX_CELLS` guard: oversized pairs report not-scored instead of stalling (APTED ~O(n²)).
- [x] **Phase-5 tooling:** `bless` (silver → gold store with the R7 hash check against the source file; `--force` override) and `reconcile` (field-level `record_diff` of blessed gold vs re-bootstrapped draft, provenance excluded — the R6 adjudication substrate).
- [x] **Corpus runner:** `run --manifest corpus.json` → per-doc compare, one combined long-form CSV/Parquet, exit-code gate over the whole corpus.
- [x] **Snapshot tier (spec tier 1):** `snapshot <record.json>` — `record_content_hash` (provenance-excluded canonical JSON) vs stored baseline; exit 1 on drift, `--update` to accept. Detects unintended output change between Docling versions before any metric runs.
- [x] **Sequence metric calibrated (same pass):** `element_sequence_distance` now compares **run-length-collapsed** sequences — it measures block-type *ordering*, not segmentation granularity (parsers legitimately split one paragraph/list into several blocks; that noise fired on 12/26 real fixtures). Threshold stays >1; `reorder_sequence` mutation upgraded to a true cross-type reorder (figure↔table). Corpus flags: 29 → **22**, every survivor adjudicated genuine.
- [ ] **Images:** re-enable the description model; add per-figure **fact-coverage** + an **LLM-as-judge** scoring grounding / completeness / **hallucinated elements**, via `mlflow.genai.evaluate()`.
- [ ] (Optional) **CLIPScore** as a cheap reference-free image–text signal.

---

### The one property that makes this safe
Because the scripts emit a schema and the comparator is dumb, the **only** thing the real documents uniquely need is the human-blessing step (Phase 5). Every line of code can be written, tested, and calibrated without ever seeing them — which is exactly why Phases 0–4 are agent-safe and Phase 5 is a short local epilogue.
