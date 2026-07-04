# `docx-parse-eval` — differential evaluation for `.docx` parsers

Differential-testing harness for `.docx` document-intelligence pipelines:
project the source (OOXML reference extraction) and any parser's native output
(Docling `DoclingDocument` JSON, or one adapter per additional model) into one
schema, then diff — conservation metrics (tier 2), a TEDS/TEDS-Struct table
quality tier, a snapshot drift tier, and the fixture self-test tier beneath
them. See
[`evaluation-framework-spec.md`](./evaluation-framework-spec.md) for the spec and
[`implementation-plan.md`](./implementation-plan.md) for build sequencing.

## Quick start (pip)

You have a handful of `.docx` files, parse them with Docling, and want to know
what the parse got wrong. The harness never runs Docling itself — you produce
the `DoclingDocument` JSON out-of-band (e.g. in the environment where docling
is installed):

```sh
docling --to json --output dl/ my_document.docx     # out-of-band, not a harness dep
```

Then, with **uv** (or plain pip in a virtualenv — both are verified):

```sh
uv sync                       # dev env: package + pytest/ruff/mypy (uv.lock pinned)
uv run docx-parse-eval --help
# or, as a dependency of your own project:
uv add path/to/doc-parsing-evaluation-framework
# or classic:
pip install path/to/doc-parsing-evaluation-framework   # installs the docx-parse-eval CLI

# 1. reference extraction straight from the OOXML (the "silver" draft record)
docx-parse-eval bootstrap my_document.docx --out work/

# 2. eyeball work/my_document.silver.json against the document, then bless it
docx-parse-eval bless work/my_document.silver.json --out .     # → gold/my_document.json

# 3. project the Docling output into the same schema; --source binds the
#    prediction to the .docx bytes so compare enforces source identity (R7)
docx-parse-eval predict dl/my_document.json --out pred/ --source my_document.docx

# 4. diff the two sides — non-zero exit iff any defect flag fires
docx-parse-eval compare --gold gold/my_document.json \
                        --pred pred/my_document.docling-adapter.json --out results/

# 5. one self-contained HTML page: flagged metrics, side-by-side table grids
#    with per-cell diffs + TEDS, caption pairs (repeat --gold/--pred per doc)
docx-parse-eval report --gold gold/my_document.json \
                       --pred pred/my_document.docling-adapter.json --out report.html
```

A typical `compare` line looks like:

```
[compare] my_document × docling-adapter: 2 flag(s) → caption_association, caption_count
[compare] results → results/my_document.docling-adapter.csv , …parquet
```

Every fired flag is a guaranteed discrepancy between the OOXML source and the
parser's output on at least one side — worth a look, one row per metric in the
CSV. This walkthrough is exercised verbatim on the repo's public fixtures
(`tests/fixtures/public/word_sample.docx`).

## Environment

The maintained development environment is **Guix** (reproducible): the harness
deps are pinned in [`manifest.scm`](./manifest.scm). A plain
`pip install .[test]` also works (the test suite is verified against
pip-resolved current versions). Either way the deps exclude Docling itself —
Docling predictions arrive as `DoclingDocument` JSON produced out-of-band (R8/R11).

> Inside the Guix profile the interpreter is `python3` (there is no bare `python`).

```sh
# run the test suite
guix shell -m manifest.scm -- python3 -m pytest tests -q

# env import smoke-test
guix shell -m manifest.scm -- python3 -c \
  "import pydantic, docx, Levenshtein, pandas, pyarrow; print('OK')"

# static checks (both must stay clean)
guix shell ruff -- ruff check src tests
guix shell -m manifest.scm python-mypy -- python3 -m mypy src/docx_parse_eval --ignore-missing-imports
```

## Runner (CLI)

```sh
G="guix shell -m manifest.scm -- env PYTHONPATH=src python3 -m docx_parse_eval.cli"

$G bootstrap path/to.docx --out work/          # Script 1 → <doc>.silver.json
$G bless     work/<doc>.silver.json --out .    # human-verified → gold/<doc>.json (R7 hash check)
$G reconcile --gold gold/<doc>.json --draft work/<doc>.silver.json   # R6 field-level diff
$G predict   path/to.docling.json --out pred/  # Script 2 → <doc>.<producer>.json
$G compare --gold gold/<doc>.json --pred pred/<doc>.<producer>.json --out results/ [--mlflow]
$G run --manifest corpus.json --out results/   # compare over the whole corpus, one table
$G snapshot pred/<doc>.<producer>.json         # drift tier: content hash vs baseline
```

`compare`/`run` write the long-form `*.csv` + `*.parquet` and **exit non-zero if
any flag fires** — usable as a CI gate; both refuse to compare records whose
`source_sha256` differ (R7; `--allow-source-mismatch` overrides). `snapshot`
exits non-zero on drift. `--mlflow` logs a run when mlflow is installed (no-op
otherwise). The `run` manifest is JSON:
`[{"doc_id": "...", "gold": "gold/x.json", "pred": "pred/x.docling.json"}, …]`.

First invocation downloads substitutes; subsequent runs are instant.

## Layout

```
.
  manifest.scm                 # Guix harness-core deps
  pyproject.toml               # metadata + pytest config (src layout)
  src/docx_parse_eval/
    schema.py                  # EvaluationRecord (Pydantic v2); SCHEMA_VERSION="0.4"
    normalize.py               # shared NFC/whitespace normalisation + tokenisation
    config.py                  # policy decisions + flag thresholds (calibration record)
    io.py                      # JSON records, content hashing, R6 record diff
    teds.py                    # TEDS/TEDS-Struct (PubTabNet metric on python-apted)
    comparator.py              # Script 3 — metrics + flags, model-agnostic
    output.py                  # CSV/Parquet long-form emit + optional MLflow hook
    report.py                  # self-contained HTML failure report
    cli.py                     # bootstrap/bless/reconcile/predict/compare/run/snapshot/report
    adapters/
      ooxml_reference.py       # Script 1 — gold/reference adapter (python-docx)
      docling_adapter.py       # Script 2 — DoclingDocument JSON adapter (zero-dep)
  tests/                       # fixture self-test tier (green/red mutations, hard cases)
```

## Output format (spec §11)

JSON records are the **source of truth** (`gold/<doc_id>.json`,
`pred/<doc_id>.<producer>.json`). Comparison results emit as **CSV + Parquet**
long-form in Phase 4; HuggingFace packaging is deferred until a second adapter
exists.
