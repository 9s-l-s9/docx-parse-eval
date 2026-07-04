# Specification — Docling `.docx` Parsing Evaluation Framework

**Status:** Draft v0.3
**Scope:** Tier-2 (correctness / conservation) evaluation of a Docling-based `.docx` parsing pipeline, plus the self-test / fixture tier beneath it.
**Architecture in one line:** model-agnostic `EvaluationRecord` schema + model-specific adapters; the comparator only ever sees the schema, never a model-native or exported format.
**Out of scope (for now):** structural-quality metrics (TEDS/GriTS) and image-description quality. See [§12 Future tiers](#12-future-tiers).

---

## 1. Purpose

Evaluate whether a Docling parsing pipeline correctly extracts the content of complex `.docx` technical specifications (focus: **tables** and **embedded figures / workflow diagrams**). The corpus is intentionally small (currently 4 documents), so this is **not** a statistical study — it is a **high-resolution regression harness**.

The corpus is also **large per document (100+ pages each) and confidential**, which shapes the whole workflow: the harness is built and validated **entirely on fixtures**, and the real documents are touched **only locally and only at the end** (see [§6.3](#63-development-workflow--data-handling-normative)).

A first-class goal is that the result is a **portable, tool-inspectable dataset** — not only an MLflow view, but JSON / CSV / Parquet (and optionally a HuggingFace dataset) that opens in Excel, pandas, DuckDB, or the HF viewer (§11).

The method is **differential testing against a reference parser**: project the original `.docx` (the reference) and the Docling output (the system under test) into one common schema via adapters, then diff them. Mismatches are guaranteed defects somewhere; matches are a *lower bound* on quality, not a certificate of it (see §3).

## 2. What this framework is and is not

| | |
|---|---|
| **Is** | A fast green/red **smoke test** that detects when extraction is *broken* — content dropped, duplicated, mis-structured, or mis-ordered. |
| **Is** | A **regression tracker** across Docling versions / configs, with per-document drill-down. |
| **Is** | **Portable across parsers** — any model can be evaluated by writing one adapter to the schema (§5.6). |
| **Is not** | A measure of extraction *quality*. A table can have the exact right `(rows, cols, cell_count)` and still have every cell's text wrong; none of these metrics will see that. |
| **Is not** | A statistical estimate of population performance. N is tiny by design; every record is meant to be read by a human. |

**Tiered model.** Four layers, each cheaper than the one below it and gating whether the next is worth running. This spec is tier 2; tier 0 is its prerequisite:

0. **Self-test / fixture tier** (§6) — validates the *harness* itself (adapters, schema projection, comparator, thresholds), **not** the parser. Runs on synthetic + public fixtures, in CI, in milliseconds. It is also the substrate the scripts are **developed** against.
1. **Snapshot tier** (optional) — "did Docling's output change since last commit?" Catches *unintended* drift. Says nothing about correctness.
2. **Conservation / agreement tier** — *this spec.* Catches breakage relative to the reference.
3. **Quality tier** (future) — TEDS / TEDS-Struct for table structure, an LLM-as-judge + fact-coverage for image descriptions. Measures whether the extraction is actually *good*.

## 3. Core principle: agreement ≠ accuracy

The reference is **silver until a human blesses it into gold** (§5). Until then the metrics measure *agreement between two parsers*, which means both are right **or** both are wrong in the same way. Therefore:

- A **mismatch** = at least one side is wrong → always worth inspecting.
- A **match** = no information about correctness on its own; it only becomes evidence of correctness to the degree the reference has been human-verified.

The transition from "agreement smoke test" to "accuracy evaluation" is **purely a function of how much human blessing the gold has received** — not a code change. The architecture below supports both ends of that spectrum without a rewrite.

## 4. Design rules (normative)

These are the rules that separate a real eval dataset from a throwaway script. They are requirements, not suggestions.

- **R1 — Schema is the contract.** Both sides emit the *identical* `EvaluationRecord` shape (§7). Adapters project model-native output into it; the comparator stays a dumb diff. If the two sides emit different shapes, all complexity migrates into the comparator — the worst place for it.
- **R2 — Two artifact lifecycles.** Gold and prediction live on different clocks:
  - **Gold** is materialised, version-controlled, human-blessed, and **frozen**. It is **never regenerated automatically**.
  - **Prediction** is **regenerated on every Docling change** and is **never hand-edited**.
- **R3 — Adjudicate against the source, never against Docling.** When gold and prediction disagree, open the actual `.docx` and decide who is right *from the source*. Editing gold to match Docling makes the gold a copy of the system under test and renders the eval vacuous.
- **R4 — No algorithm reimplementation.** The comparator reuses existing metric implementations (e.g. `Levenshtein` for edit distance) and never reimplements parsing or structural recognition.
- **R5 — Compare on the schema, not on export artifacts.** The comparator never sees Markdown or HTML. Markdown/HTML inject syntax and conversion decisions that skew every metric; all of that is absorbed inside the adapters (see R11).
- **R6 — Bootstrapper fixes are reconciled, not auto-applied.** When the reference adapter (Script 1) is later fixed, re-bootstrap into a *new draft*, diff it against the blessed gold, adopt genuine corrections, reject regressions. Gold remains the authority.
- **R7 — Gold is bound to its source.** Each gold record stores the SHA-256 of its `.docx`. If the source file changes, the gold is invalidated and must be re-blessed.
- **R8 — Sensitive-corpus isolation.** The real corpus is large and confidential and **never** enters script development, any AI/agent session, or any third-party service. All building, debugging, and threshold calibration use **synthetic and public fixtures** (§6). The real documents are processed **only** in the maintainer's controlled local environment, and **only after** the harness is validated on fixtures. Bugs surfaced by real data are reproduced as *new synthetic fixtures*, not debugged in place.
- **R9 — Fixture-first development.** Each adapter is built to reproduce a fixture whose gold is known *by construction*; the comparator is built against a green pair and a mutated red pair. Fixtures are written with the code and remain as permanent regression tests.
- **R10 — Model-agnostic schema, model-specific adapters.** The `EvaluationRecord` is the portable contract. Each parser/model gets its own adapter that projects its *native* output into the schema. The schema and comparator are portable; only adapters are format-specific. This is the clean compromise: portability across models **without** sacrificing the exactness of any one model's test.
- **R11 — Authoritative input is the lossless native representation.** *Normative input for Docling predictions is `DoclingDocument` JSON, because it is the lossless serialization of Docling's native representation. HTML and Markdown exports may be used for portability experiments or downstream baselines, but they are not authoritative inputs for the conservation (Tier-2) metrics.* Rationale and the list of what lossy exports cannot represent: §5.5.

## 5. Architecture

The schema is the hub. Two kinds of adapter feed it: a **gold/reference adapter** on the source side, and **one prediction adapter per model** on the system-under-test side. The comparator is downstream of the schema and is identical for every model.

```
  ┌─ gold side ─────────────────────────────────────────────────────────────────┐
  │  .docx ─► OOXML reference extractor ─► silver ─► HUMAN ─► GOLD EvaluationRecord │
  │           (Script 1 = gold adapter)            review     (frozen, in git)     │
  └───────────────────────────────────────────────────────────────────┬──────────┘
                                                                        │
  ┌─ prediction side (Docling) ───────────────────────────────┐        │
  │  .docx ─► Docling ─► DoclingDocument / .json ─► docling     │        │
  │           (pipeline)   (lossless, native)       _adapter   │        │
  │                                                (Script 2)  │        │
  │                                                     │      │        │
  │                                        prediction EvaluationRecord   │
  └─────────────────────────────────────────────────────┬─────┘        │
                                                         │              │
                                                         ▼              ▼
                                          Script 3  —  comparator (model-agnostic)
                                                         │
                                                         ▼
                          metrics ─► MLflow (run tracking, §10)  +  dataset files (§11)
```

All adapters and the comparator are built and exercised against fixtures (§6) before the real corpus is involved (R8, R9).

### 5.1 Script 1 — OOXML reference extractor (the gold adapter)
- **Input:** a `.docx` file.
- **Output:** a **silver** `EvaluationRecord` (§7).
- **Cadence:** run **once per document** to bootstrap; re-run only to reconcile after a fix (R6).
- **Implementation note:** read structure directly from OOXML (`python-docx` / XML traversal). Document order in the XML *is* the reading order. Table grids, `gridSpan`/`vMerge`, heading levels, captions, and embedded image parts are all directly available.
- **Status of output:** a *helper* artifact. It may contain bugs; that is expected and acceptable because a human adjudicates it.

### 5.2 Human review — silver → gold
- A human compares the silver record against the actual `.docx` and corrects it.
- The result is **committed to version control** and treated as the authority.
- The source `.docx` — never Docling — is the arbiter (R3).
- This is the single most valuable step; the trustworthiness of every metric is proportional to the care taken here. For the real corpus this step is performed **locally** (R8).

### 5.3 Script 2 — Docling adapter (`DoclingDocument` JSON → schema)
- **Input:** the **`DoclingDocument` JSON** produced by the pipeline under test — the lossless native representation, **not** HTML or Markdown (R11).
- **Output:** an `EvaluationRecord` conforming to the **same** schema (R1).
- **Cadence:** run on **every new Docling parse / config change**.
- **Implementation note:** iterate `DoclingDocument` via `iterate_items()`; tables expose `num_rows`, `num_cols`, the cell list, and `column_header`; pictures and their captions are first-class items; body-vs-furniture layers, labels, and provenance are available.
- **Never hand-edited** (R2).

### 5.4 Script 3 — comparator (gold + prediction → metrics)
- **Input:** one frozen gold record + one fresh prediction record for the same `doc_id`.
- **Output:** the metric set (§8) as `{metric, source_value, prediction_value, ratio_or_score, flag}` per document, plus aggregates; emitted to MLflow (§10) and to dataset files (§11).
- **Pure & model-agnostic.** No parsing, no structural algorithms, no reimplementation (R4), and no knowledge of which model produced the prediction. It matches elements across the two sides, compares attributes, and applies flag thresholds.
- **Element matching strategy:** match tables/figures/headings across sides **by reading-order position** first; fall back to content similarity (caption text for figures, cell-text for tables) when counts differ. A count mismatch or an ambiguous match is itself a flag, not an error to silently resolve.

### 5.5 Why `DoclingDocument` JSON, not HTML/Markdown
Docling's own documentation is explicit that `DoclingDocument` is the rich internal representation — texts, tables, pictures, hierarchy, body-vs-header/footer layers, layout info, provenance ([concepts](https://docling-project.github.io/docling/concepts/docling_document/)) — and that **JSON serialization is lossless while Markdown and HTML are lossy exports** that cannot retain all meta-information ([technical report](https://arxiv.org/html/2501.17887v1)). That answers "how exact is HTML?" directly: fine for RAG/preview/portable export, **not** exact enough as a source for conservation metrics.

HTML can express tables, headings, lists, and links well. But the moment you need to know whether an element was truly a `PictureItem`, a caption, a header/footer (furniture) element, a body element, a grouped structure, or a specific Docling element in reading order, HTML becomes a derived, flatter format. Specifically, lossy exports cannot reliably carry:

`element_sequence` · caption association · content layer / furniture · figure position · table-cell metadata · provenance · body hierarchy · Docling-specific labels

Routing through HTML would also add a **second error source** — `DoclingDocument → HTML → schema`. When a metric then flags, you cannot cleanly tell whether *Docling was wrong*, *the HTML export was lossy*, *your HTML parser was wrong*, or *HTML simply couldn't represent the information*. For a smoke/regression test that ambiguity is poison. The adapter consumes the lossless native JSON so the test isolates Docling's actual recognition.

### 5.6 Adding another model
Portability is concrete: to evaluate a different parser (Azure Document Intelligence, Google Document AI, Unstructured, Marker, …), write one adapter from its native output into the schema. Nothing else changes.

```
  Azure DI / Google DocAI / Unstructured / Marker / …
        └─ native output (preferably lossless; HTML/Markdown only if nothing richer exists)
             └─ <model>_adapter.py
                  └─ EvaluationRecord (prediction)  ──►  same Script 3, same metrics
```

The same R11 logic applies per model: feed each adapter the richest/most-lossless representation that model offers; fall back to HTML/Markdown only when no structured output exists, and treat such records as lower-fidelity.

## 6. Framework self-test, fixtures & development workflow

This is the layer *beneath* the snapshot tier: it validates the **harness itself** — the adapters, the schema projection, the comparator, and the thresholds — **not** Docling. A pair whose correct answer is already known is exactly what proves the harness behaves. It is also the **substrate the scripts are developed against**: build each component until it reproduces a known-answer fixture, then keep that fixture as a permanent regression test (R9).

Critically, this layer is what makes it possible to build the scripts **without the real corpus ever entering the loop** (§6.3).

> **Note on circularity.** "Fully correct Docling output" cannot validate *Docling* — if the output is correct by definition, there is nothing left to measure. A known-good pair validates the **harness**, not the parser. Keep the two purposes distinct.

### 6.1 What the fixtures validate (two halves)
A baseline must test both, not just the first:
- **Specificity (known-good pair):** the harness must report all-match. A spurious flag means an adapter or a threshold is wrong — not Docling.
- **Sensitivity (known-bad pair):** inject a known defect (drop a table, corrupt a part number, duplicate a block) and confirm the *correct* metric fires. A harness that never false-alarms but also never catches anything is worthless; this is the half that is usually missing.

### 6.2 Fixture sources
- **Synthetic, authored (primary).** A tiny `.docx` whose structure is known *by construction* — e.g. a known count of tables (one with a merged cell + a header row), figures with captions, two or three heading levels, a list, and a few part-numbers/units. Because it is authored, the gold needs no human blessing and carries no circularity, and it can be made to stress exactly the hard cases (figures-with-captions, merged cells). Produce one **green** copy and one **mutated** copy (the red case).
- **Public Docling test data (secondary — plumbing check).** Docling's repo ships `.docx` inputs under `tests/data/` (e.g. `word_sample.docx`) with maintainer-blessed expected outputs under `tests/data/groundtruth/docling_v2/` as lossless `DoclingDocument` JSON, Markdown, and an indented-text tree. Feed the `.docx` to Script 1 and the committed JSON to Script 2; if Script 3 reports match, the projection + comparator are internally consistent on a case the project treats as correct. **Caveat:** these fixtures are deliberately minimal and will *not* exercise the figure/diagram complexity of the real corpus — they prove plumbing, not the hard path.

### 6.3 Development workflow & data handling (normative)
The real corpus is large (100+ pages each) and confidential, so it is isolated from the build process entirely (R8):

- All script development, debugging, and threshold calibration happen against **synthetic and public fixtures** — never the real documents, and never inside any AI/agent or third-party context.
- This is *possible* precisely because of the architecture: the adapters emit a schema and the comparator is dumb, so the only thing the real documents uniquely require is the **human-blessing step** (§9.1), performed locally by the maintainer. **No code development needs to see them.**
- The real corpus is processed **only** in the maintainer's controlled local environment, and **only after** the harness is green on fixtures.
- **Bugs found on real data are distilled into new synthetic fixtures.** If a real `.docx` reveals an OOXML construct the fixtures didn't cover, reproduce it as a *new minimal synthetic fixture*, fix against that, and keep it — never debug against the 100-page document. This keeps real data out of the dev loop even for maintenance.

## 7. `EvaluationRecord` schema (the contract)

One record per document **per producer** (the gold adapter and each model adapter emit the same shape). Model-agnostic. Serialise as JSON (one file per `doc_id` × `producer`). Normative typed definition:

```python
@dataclass
class EvaluationRecord:
    # --- identity & provenance ---
    doc_id: str                     # stable slug, e.g. "wh-spec-001"
    title: str                      # human-readable
    source_path: str                # path to the .docx
    source_sha256: str              # hash of the .docx — guards gold validity (R7)
    schema_version: str             # bump on any schema change
    producer: str                   # adapter id, e.g. "ooxml-reference" | "docling-adapter" | "azure-di-adapter"
    producer_version: str           # adapter/pipeline version for traceability

    # --- text ---
    word_count: int
    char_count_normalized: int      # after whitespace + Unicode (NFC) normalisation
    full_text_normalized: str       # optional; enables NED later. May be large.

    # --- structural inventories ---
    tables:   list[TableRecord]
    figures:  list[FigureRecord]
    headings: list[HeadingRecord]
    lists:    list[ListRecord]

    # --- scalar counts ---
    hyperlink_count: int
    footnote_count: int
    endnote_count: int

    # --- ordering ---
    element_sequence: list[str]     # ordered block types:
                                    # "heading"|"paragraph"|"table"|"figure"|"list"|"caption"

    # --- content tokens ---
    identifier_tokens: list[str]    # numbers, measurements, part-style IDs (multiset, sorted)
    special_chars: list[str]        # units/symbols present, e.g. ["°","×","±","µ"]


@dataclass
class TableRecord:
    table_id: str                   # positional or content-hash based
    position: int                   # index in reading order
    n_rows: int
    n_cols: int
    cell_count: int
    has_header: bool                # header row detected
    cell_text_length: int           # total normalised chars across all cells


@dataclass
class FigureRecord:
    figure_id: str
    position: int
    caption_text: str               # normalised; "" if none
    has_caption: bool


@dataclass
class HeadingRecord:
    text: str                       # normalised
    level: int                      # 1-based
    position: int


@dataclass
class ListRecord:
    list_id: str
    position: int
    n_items: int
    is_ordered: bool
```

**Normalisation (applies to every text field before it is stored or compared):** Unicode NFC, collapse runs of whitespace, strip leading/trailing whitespace, and — for any value an adapter derives from a lossy format — remove residual syntax. The normalisation function is shared by all adapters so that differences reflect extraction, not formatting.

## 8. Metrics (computed by Script 3)

Each metric yields `source_value`, `prediction_value`, a `ratio` or `score`, and a boolean `flag` (threshold tripped). Thresholds below are **placeholders to be calibrated on fixtures** (R8 — not on the real corpus). Grouped by the failure each one catches.

### 8.1 Completeness — did things silently disappear?
| Metric | Compared from | Flag when |
|---|---|---|
| Figure count | `len(figures)` | counts differ |
| List-item count | `sum(n_items)` over `lists` | counts differ (catches lists flattened to paragraphs) |
| Heading count **by level** | histogram over `headings.level` | any level's count differs (catches collapsed hierarchy) |
| Hyperlink count | `hyperlink_count` | counts differ |
| Footnote / endnote count | `footnote_count`, `endnote_count` | counts differ |
| Caption count | `sum(has_caption)` over `figures` | counts differ |
| Caption **association** | matched figure → caption text similarity | matched figure's caption mismatches |

### 8.2 Structure — counts match but content is mangled
| Metric | Compared from | Flag when |
|---|---|---|
| Per-table dimensions | matched `(n_rows, n_cols, cell_count)` | any component differs (precursor to TEDS; catches split/merged/nested cells) |
| Table header detection | matched `has_header` | differs |
| Element-type sequence distance | edit distance over `element_sequence` | distance > threshold (catches reordering **and** dropped blocks — a poor-man's reading-order metric) |

### 8.3 Content preservation
| Metric | Compared from | Flag when |
|---|---|---|
| Identifier-token overlap | set/multiset compare of `identifier_tokens` | Jaccard < threshold (a dropped/corrupted part number or dimension is a real defect) |
| Text-inside-tables length | `sum(cell_text_length)` over `tables` | ratio outside band (tables are where text is most often lost or duplicated) |
| **Duplication direction** | length ratio `prediction / source` | ratio **> 1 + ε** (content emitted twice — e.g. in the table *and* the body flow) |
| Special-char survival | set compare of `special_chars` | any expected symbol missing |

### 8.4 Text fidelity (upgrade of raw word count)
| Metric | Compared from | Flag when |
|---|---|---|
| Length ratio | `char_count_normalized` ratio | outside `[1-δ, 1+δ]` |
| Full-text NED *(optional)* | normalised edit distance over `full_text_normalized` | NED > threshold |

> A raw word count can coincidentally match while text is garbled. The **length ratio** plus optional **NED** catch corruption that a matching count would hide, at the same cost.

## 9. Workflows

> Workflows **§9.1–§9.4 operate on the real corpus** and therefore run **locally** in the maintainer's environment (R8). The fixture-based development loop lives in §6.3 and is the only thing an agent or CI touches.

### 9.1 First-time gold creation (once per `.docx`, local)
1. Run **Script 1** → silver record.
2. Human reviews silver against the `.docx`, corrects it (R3).
3. Commit the corrected record as **gold**, with `source_sha256` set, to a controlled/private location.

### 9.2 Evaluation run (every Docling change, local)
1. Run the Docling pipeline → `DoclingDocument` JSON.
2. Run **Script 2** (Docling adapter) → prediction record.
3. Run **Script 3** (gold + prediction) → metrics → MLflow run + dataset files.
4. Inspect flagged rows; with N=4, skim every row regardless.

### 9.3 Reconciliation after a Script 1 fix (R6)
1. Fix the reference adapter (against fixtures, R8).
2. Re-run Script 1 → **new draft** (do not overwrite gold).
3. Diff draft against blessed gold.
4. Adopt genuine corrections; reject anything that is actually a regression.
5. Re-commit gold; bump `producer_version`.

### 9.4 Disagreement adjudication (R3)
- Gold vs prediction differ → open the `.docx`.
- If the **reference** was wrong → correct gold, commit.
- If **Docling** was wrong → leave gold; the flag stands as a recorded defect.
- Never "fix" gold merely to make a test pass.

## 10. MLflow integration

MLflow covers **run tracking over time**; for portable inspection use the dataset files (§11). The two coexist. For this tier the metrics are deterministic code metrics (no LLM), so plain MLflow tracking suffices:

- **Run = one evaluation** (one Docling config over the corpus).
- **Params:** Docling version, pipeline config (table mode, OCR flags, etc.), gold `schema_version`, gold git commit hash.
- **Metrics:** every comparison metric, logged **per-document** (`figure_count_match__wh-spec-001`) **and** aggregated, so regressions are visible across runs.
- **Artifacts:** the dataset files from §11 (records + comparison tables) attached to the run for traceability.
- **Tags:** gold version, corpus revision.

When the quality tier arrives, the image-description judge moves to `mlflow.genai.evaluate()` with `@scorer` / `make_judge()` (the deterministic checks here stay as plain tracking; the two systems are not interoperable, so keep them separate).

## 11. Output artifacts & dataset format

Goal: a **portable, tool-inspectable dataset**, independent of MLflow, that opens in Excel, pandas, Polars, DuckDB, or the HuggingFace viewer. Three layers:

- **Records (source of truth).** Each `EvaluationRecord` as **JSON**, one file per `doc_id` × `producer` (`gold/wh-spec-001.json`, `pred/wh-spec-001.docling.json`). Universally loadable; nested structure (lists of tables/figures) preserved.
- **Comparison results (the thing you actually browse).** A **tidy / long-form table**, one row per `(doc_id, producer, metric)` with columns `source_value, prediction_value, ratio_or_score, flag, run_id, gold_commit`. Emit as **CSV** (Excel) **and Parquet** (typed, columnar — pandas / Polars / DuckDB). This is the "dataset I can view in other tools" in the most practical sense: filter by `flag`, sort by `ratio`.
- **Optional ecosystem packaging.** Bundle records + results as a **HuggingFace `datasets`** dataset (Parquet-backed). Then it opens in the HF dataset viewer and is **format-compatible with docling-eval and the wider doc-intelligence ecosystem**, which already standardise on HF/Parquet — useful if you later plug into those tools.

Notes:
- Records are nested; for flat tools that dislike nesting, optionally also emit a **flattened element-level table** (one row per table/figure/heading) alongside the document-level results.
- Keep JSON records authoritative; CSV/Parquet/HF are **derived views** regenerated from them.

## 12. Future tiers (forward-compatibility)

Deferred, but the schema is built so they slot in without rework:

- **HTML export-loss diagnostic (optional, cheap).** Add a *second* Docling adapter that reads the **HTML export** (`html_adapter.py`), and compare `docling_native_record` vs `docling_html_record`. This quantifies how much information the HTML export drops for this document type; large divergence ⇒ HTML is not trustworthy here. A nice extra metric that also empirically justifies R11.
- **Table structure quality → TEDS / TEDS-Struct (and optionally GriTS).** The `tables` inventory + corrected structure already in gold is the precursor; add gold table HTML/OTSL and reuse an existing TEDS implementation. Do **not** reimplement TEDS.
- **Image-description quality → LLM-as-judge + fact-coverage.** The `figures` inventory (with positions and captions) is already the anchor; when the description model is re-enabled, add per-figure salient-fact lists and score grounding/completeness/correctness, with **hallucinated elements** as a first-class metric. Optionally add CLIPScore as a cheap reference-free signal.
- **Not applicable:** formula metrics (CDM) — the corpus contains no math; OCR metrics — source is digital `.docx`.

## 13. Open decisions (to settle during implementation)

- **Identifier regex** — exact pattern for "numbers, measurements, part-style IDs"; over-broad patterns create noisy token sets.
- **Figure-counting policy** — how to treat header/footer logos, decorative images, and **grouped vector shapes** (warehouse workflow diagrams may be grouped shapes, not single rasters). Likely: exclude decorative, flag rather than fail on count mismatch.
- **Matching strategy & thresholds** — position-first vs content-similarity fallback; similarity thresholds for caption/table matching.
- **Flag thresholds (δ, ε, NED, Jaccard)** — calibrate on fixtures so flags fire on real defects, not formatting noise.
- **`full_text_normalized`** — store it (enables NED, larger records) or omit it (lighter, count-only) for now.
- **Tokeniser** — must be identical on both sides; decide once and share.
- **Gold storage location** — the private/controlled repo or store that holds gold for the real corpus (kept separate from the agent-developed code).
- **HF dataset packaging** — produce the HuggingFace dataset bundle (§11) now or only once a second model/adapter is added.
- **Flattened element table** — emit the per-element flat view (§11) or keep only document-level results.
