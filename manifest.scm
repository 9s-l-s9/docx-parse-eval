;; Harness-core dependency manifest for the Docling .docx evaluation framework.
;;
;; Scope: the eval HARNESS only (schema, normalisation, adapters, comparator,
;; metrics, output). Deliberately excludes Docling itself — Docling predictions
;; are produced out-of-band as DoclingDocument JSON (R8/R11) and never imported
;; here as a runtime dependency.
;;
;; Deferred (added in later phases): mlflow (Phase 4), the HuggingFace `datasets`
;; bundle (optional, §11).
;;
;; Usage:
;;   guix shell -m evaluation/manifest.scm -- pytest -q
(specifications->manifest
 '("python"            ; >= 3.11
   "python-pydantic"   ; v2 — schema (de)serialisation + validation
   "python-docx"       ; Script 1: OOXML reference extractor (Phase 2)
   "python-levenshtein"; comparator edit-distance metrics (Phase 3, R4)
   "python-apted"      ; tree edit distance for TEDS (quality tier, R4)
   "python-pandas"     ; long-form results table (Phase 4)
   "python-pyarrow"    ; Parquet emit (Phase 4)
   "python-pytest"))   ; test runner
