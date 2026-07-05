# `docx-parse-eval` — differential evaluation for `.docx` parsers

Differential-testing harness for `.docx` document-intelligence pipelines:
project the source (OOXML reference extraction) and any parser's native output
(Docling `DoclingDocument` JSON, or one adapter per additional model) into one
schema, then diff — conservation metrics, a TEDS/TEDS-Struct table quality
tier, a snapshot drift tier, and a fixture self-test tier beneath them.
Spec: [`evaluation-framework-spec.md`](./evaluation-framework-spec.md).

**Use it when** your `.docx` are too long to eyeball (100+ pages),
confidential (evaluation runs entirely on your machine; the corpus never
enters CI, agents, or third-party services — R8), or parsed *recurringly*
(the snapshot tier answers "did the parser upgrade change my extractions?").
**Skip it** for a few short one-off files, or for scanned PDFs/images — the
approach needs a machine-readable source format, so there is no
gold-by-construction for pixels.

**What a result means:** gold is an independent reading of the same OOXML, so
a fired flag is a guaranteed discrepancy between two readings — a defect on at
least one side, always worth inspecting — not a claim of absolute truth. The
`bless`/`reconcile` steps put a human in the arbitration seat.

## Quick start

The harness never runs Docling itself — produce the `DoclingDocument` JSON
out-of-band, wherever docling is installed (R8/R11):

```sh
docling --to json --output dl/ my_document.docx
```

Install with **uv** (or plain pip in a virtualenv — both verified):

```sh
uv sync                        # dev env: package + pytest/ruff/mypy (uv.lock pinned)
uv run docx-parse-eval --help
pip install path/to/doc-parsing-evaluation-framework   # or classic pip

# 1. reference extraction straight from the OOXML → "silver" draft record
docx-parse-eval bootstrap my_document.docx --out work/

# 2. eyeball the silver record against the document, then bless it
docx-parse-eval bless work/my_document.silver.json --out .   # → gold/my_document.json

# 3. project the Docling output into the same schema; --source binds the
#    prediction to the .docx bytes so compare enforces source identity (R7)
docx-parse-eval predict dl/my_document.json --out pred/ --source my_document.docx

# 4. diff the two sides — non-zero exit iff any defect flag fires
docx-parse-eval compare --gold gold/my_document.json \
                        --pred pred/my_document.docling-adapter.json --out results/

# 5. self-contained HTML page: flagged metrics, side-by-side table grids with
#    per-cell diffs + TEDS, caption pairs (repeat --gold/--pred per doc)
docx-parse-eval report --gold gold/my_document.json \
                       --pred pred/my_document.docling-adapter.json --out report.html
```

Remaining verbs: `reconcile --gold … --draft …` (field-level diff of blessed
gold vs a re-bootstrapped draft, R6), `run --manifest corpus.json --out …`
(compare over a whole corpus, one combined table; manifest is
`[{"doc_id": …, "gold": …, "pred": …}, …]`), and `snapshot <record.json>`
(drift tier: content hash vs stored baseline, non-zero exit on drift).
`compare`/`run` write long-form CSV + Parquet, exit non-zero when any flag
fires (CI gate), and refuse records whose `source_sha256` differ
(`--allow-source-mismatch` overrides). `--mlflow` logs a run when mlflow is
installed, no-op otherwise. Other parsers plug in via `predict --adapter NAME`:
a module with `extract(json_path, **kw) -> EvaluationRecord`, registered under
the `docx_parse_eval.adapters` entry-point group. The same verbs are importable
from Python: `from docx_parse_eval import extract_reference, compare, …`.

## Development environment

The maintained environment is **Guix** (deps pinned in
[`manifest.scm`](./manifest.scm); the profile has `python3`, no bare
`python`); `uv sync` or `pip install .[test]` also work.

```sh
guix shell -m manifest.scm -- python3 -m pytest tests -q            # test suite
guix shell ruff -- ruff check src tests                             # lint
guix shell -m manifest.scm python-mypy -- python3 -m mypy src/docx_parse_eval --ignore-missing-imports
```

## Layout

```
  manifest.scm                 # Guix harness-core deps
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

JSON records are the source of truth (`gold/<doc_id>.json`,
`pred/<doc_id>.<producer>.json`); results emit as CSV + Parquet long-form.

## Status / roadmap

The harness (adapters, comparator, calibration, CLI, report) is complete and
green on fixtures. Applying it to a real corpus is deliberately a local, human
step (R8): bootstrap each document, bless silver → gold, run the parser
out-of-band, `predict`/`compare`, and inspect every flag on the first pass —
any extractor bug found there gets distilled into a new minimal synthetic
fixture rather than debugged on the real document. Flag thresholds in
`config.py` are fixture-calibrated first passes; expect to tune them on first
real-corpus contact. Deferred: HTML export-loss diagnostic, HuggingFace
dataset bundle, per-figure image-description scoring.
