# `docx-parse-eval` — differential evaluation for `.docx` parsers

Differential-testing harness for `.docx` document-intelligence pipelines:
project the source (OOXML reference extraction) and any parser's native output
(Docling `DoclingDocument` JSON, or one adapter per additional model) into one
schema, then diff — conservation metrics (tier 2), a TEDS/TEDS-Struct table
quality tier, a snapshot drift tier, and the fixture self-test tier beneath
them. See
[`evaluation-framework-spec.md`](./evaluation-framework-spec.md) for the spec and
[`implementation-plan.md`](./implementation-plan.md) for build sequencing.

## Environment

Dependencies are provisioned via **Guix** (reproducible), not pip. The harness
deps are pinned in [`manifest.scm`](./manifest.scm) and exclude Docling itself —
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
    cli.py                     # bootstrap/bless/reconcile/predict/compare/run/snapshot
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
