# Contributing

Thanks for considering a contribution. Ground rules are few but firm.

## Setup

```sh
uv sync            # package + pytest/ruff/mypy (uv.lock pinned)
uv run pytest -q   # 137+ tests, all must stay green
```

(Guix users: `guix shell -m manifest.scm -- python3 -m pytest tests -q`.)

## Quality gates (CI enforces all three)

```sh
uv run ruff check src tests
uv run mypy src/docx_parse_eval --ignore-missing-imports
uv run pytest -q
```

## Design invariants — read before changing code

- **The schema is the contract.** `EvaluationRecord` (`schema.py`) is frozen;
  any field change bumps `SCHEMA_VERSION` and is a breaking event. Adapters
  and the comparator only meet through it.
- **The comparator stays dumb and model-agnostic.** No parser-specific logic
  in `comparator.py`; parser knowledge lives in one adapter per producer.
- **No parser dependencies in the harness.** Docling (or any parser) output
  arrives as JSON produced out-of-band. Do not add `docling` to the deps.
- **No reimplemented algorithms.** Edit distance is `Levenshtein`, tree edit
  distance is `apted` (R4). Wire libraries, don't rewrite them.
- **Fixtures first.** New behaviour ships with a fixture the test suite can
  see: a *green* case that must not flag and, for defect detection, a *red*
  mutation that must. Public/synthetic fixtures only — never commit real or
  confidential documents (R8).

## Adding an adapter for a new parser

1. New module in `src/docx_parse_eval/adapters/` that projects the parser's
   native output into an `EvaluationRecord` (see `docling_adapter.py`, which
   is a plain-dict traversal with zero parser deps).
2. Set `producer` / `producer_version` distinctly.
3. Add public fixtures: the parser's raw output for documents whose gold
   records already exist, plus shape-equivalence tests against the OOXML
   adapter (see `test_adapter_shape_equivalence.py`).

## Commit style

Small, self-contained commits; message says *why*, not just what. All three
gates green before pushing.
