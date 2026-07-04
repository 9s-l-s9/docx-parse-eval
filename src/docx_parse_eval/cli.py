"""End-to-end runner (spec §9) — thin glue over the existing modules.

Subcommands mirror the workflows:

  bootstrap  <docx>          → Script 1 → *silver* record (a human blesses it)
  bless      <silver.json>   → verified copy into the gold store (R7 hash check)
  reconcile  --gold --draft  → field-level diff for R6 adjudication
  predict    <docling.json>  → Script 2 → prediction record
  compare    --gold --pred   → Script 3 → metrics → CSV/Parquet (+ optional MLflow)
  run        --manifest      → compare over a whole corpus, one combined table
  snapshot   <record.json>   → drift tier: content hash vs the stored baseline

`compare`/`run` exit non-zero when any flag fires (CI gate); `snapshot` exits
non-zero on drift. All heavy lifting lives in the library; this module only
parses args and wires.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from docx_parse_eval.adapters import docling_adapter, ooxml_reference
from docx_parse_eval.comparator import compare, fired_flags
from docx_parse_eval.io import (
    read_record,
    record_content_hash,
    record_diff,
    sha256_file,
    write_record,
)
from docx_parse_eval.output import mlflow_log, results_to_long_df, write_results_table


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    rec = ooxml_reference.extract(args.docx)
    out = Path(args.out) / f"{rec.doc_id}.silver.json"
    write_record(rec, out)
    print(f"[bootstrap] silver record → {out}  (BLESS before using as gold)")
    return 0


def _cmd_predict(args: argparse.Namespace) -> int:
    kw: dict = {}
    if args.doc_id:
        kw["doc_id"] = args.doc_id
    if args.source:
        # Bind the prediction to the source bytes so compare's R7 identity
        # check is exact instead of informational (empty hash = unknown).
        kw["source_path"] = args.source
        kw["source_sha256"] = sha256_file(Path(args.source))
    rec = docling_adapter.extract(args.json, **kw)
    out = Path(args.out) / f"{rec.doc_id}.{rec.producer}.json"
    write_record(rec, out)
    print(f"[predict] prediction record → {out}")
    return 0


def _cmd_bless(args: argparse.Namespace) -> int:
    rec = read_record(args.silver)
    src = Path(rec.source_path) if rec.source_path else None
    if src is not None and src.exists():
        actual = sha256_file(src)
        if actual != rec.source_sha256 and not args.force:
            print(
                f"[bless] REFUSED: {src} hash {actual[:12]}… does not match the "
                f"record's source_sha256 {rec.source_sha256[:12]}… — the source "
                "changed since bootstrap (R7). Re-run bootstrap, or --force."
            )
            return 2
    elif not rec.source_sha256 and not args.force:
        print("[bless] REFUSED: record has no source_sha256 and the source is unreachable (R7); use --force.")
        return 2
    out = Path(args.out) / "gold" / f"{rec.doc_id}.json"
    write_record(rec, out)
    print(f"[bless] gold record → {out}")
    print("[bless] reminder: blessing asserts a HUMAN verified this record against the .docx (spec §5.2).")
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    gold = read_record(args.gold)
    draft = read_record(args.draft)
    diffs = record_diff(gold, draft)
    if not diffs:
        print("[reconcile] no content differences — gold already agrees with the draft.")
        return 0
    print(f"[reconcile] {len(diffs)} difference(s), gold → draft. For each: adopt into gold")
    print("[reconcile] only if the DRAFT is right against the source .docx (R3/R6); never to match a parser.")
    for d in diffs:
        print(f"  {d}")
    return 1


def _check_source_identity(gold, pred, allow_mismatch: bool) -> int | None:
    """R7 hard gate: refuse to compare records derived from different bytes."""
    if (
        gold.source_sha256
        and pred.source_sha256
        and gold.source_sha256 != pred.source_sha256
        and not allow_mismatch
    ):
        print(
            f"[compare] REFUSED: gold source_sha256 {gold.source_sha256[:12]}… ≠ "
            f"prediction {pred.source_sha256[:12]}… — these records come from "
            "different source bytes; every metric would be meaningless (R7). "
            "Use --allow-source-mismatch to override."
        )
        return 2
    return None


def _cmd_compare(args: argparse.Namespace) -> int:
    gold = read_record(args.gold)
    pred = read_record(args.pred)
    refused = _check_source_identity(gold, pred, args.allow_source_mismatch)
    if refused is not None:
        return refused
    results = compare(gold, pred)
    df = results_to_long_df(
        results, doc_id=gold.doc_id, producer=pred.producer,
        run_id=args.run_id, gold_commit=args.gold_commit,
    )
    paths = write_results_table(df, args.out, stem=f"{gold.doc_id}.{pred.producer}")
    flags = fired_flags(results)

    if args.mlflow:
        logged = mlflow_log(
            params={"doc_id": gold.doc_id, "producer": pred.producer,
                    "gold_commit": args.gold_commit, "schema_version": gold.schema_version},
            df=df, artifact_paths=list(paths.values()),
            tags={"corpus_revision": args.gold_commit},
        )
        print(f"[compare] mlflow: {'logged' if logged else 'skipped (not installed)'}")

    print(f"[compare] {gold.doc_id} × {pred.producer}: "
          f"{len(flags)} flag(s){' → ' + ', '.join(sorted(flags)) if flags else ''}")
    print(f"[compare] results → {paths['csv']} , {paths['parquet']}")
    return 1 if flags else 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Corpus run: `compare` over every entry of a manifest, one combined
    long-form table. Manifest JSON: [{"doc_id": …, "gold": path, "pred": path}, …]."""
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    frames: list[pd.DataFrame] = []
    total_flags = 0
    for entry in manifest:
        gold = read_record(entry["gold"])
        pred = read_record(entry["pred"])
        refused = _check_source_identity(gold, pred, args.allow_source_mismatch)
        if refused is not None:
            return refused
        results = compare(gold, pred)
        flags = fired_flags(results)
        total_flags += len(flags)
        frames.append(
            results_to_long_df(
                results, doc_id=entry.get("doc_id", gold.doc_id), producer=pred.producer,
                run_id=args.run_id, gold_commit=args.gold_commit,
            )
        )
        print(f"[run] {gold.doc_id:30s} {len(flags)} flag(s)"
              f"{' → ' + ', '.join(sorted(flags)) if flags else ''}")
    df = pd.concat(frames, ignore_index=True)
    paths = write_results_table(df, args.out, stem=args.stem)
    if args.mlflow:
        logged = mlflow_log(
            params={"corpus": args.manifest, "gold_commit": args.gold_commit},
            df=df, artifact_paths=list(paths.values()),
            tags={"corpus_revision": args.gold_commit},
        )
        print(f"[run] mlflow: {'logged' if logged else 'skipped (not installed)'}")
    print(f"[run] {len(manifest)} document(s), {total_flags} flag(s) total")
    print(f"[run] results → {paths['csv']} , {paths['parquet']}")
    return 1 if total_flags else 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    """Snapshot tier (spec §2, tier 1): detect UNINTENDED drift in a producer's
    output. Says nothing about correctness — only 'it changed'."""
    rec = read_record(args.record)
    digest = record_content_hash(rec)
    store = Path(args.dir) / f"{rec.doc_id}.{rec.producer}.sha256"
    if not store.exists():
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(digest + "\n", encoding="utf-8")
        print(f"[snapshot] baseline recorded → {store}")
        return 0
    baseline = store.read_text(encoding="utf-8").strip()
    if digest == baseline:
        print(f"[snapshot] unchanged ({digest[:12]}…)")
        return 0
    if args.update:
        store.write_text(digest + "\n", encoding="utf-8")
        print(f"[snapshot] CHANGED — baseline updated ({baseline[:12]}… → {digest[:12]}…)")
        return 0
    print(f"[snapshot] CHANGED: {baseline[:12]}… → {digest[:12]}… "
          "(run compare to judge whether the change is a regression; --update to accept)")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docx-parse-eval", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bootstrap", help="OOXML .docx → silver gold record (Script 1)")
    b.add_argument("docx")
    b.add_argument("--out", default=".")
    b.set_defaults(func=_cmd_bootstrap)

    pr = sub.add_parser("predict", help="DoclingDocument JSON → prediction record (Script 2)")
    pr.add_argument("json")
    pr.add_argument("--doc-id", default=None)
    pr.add_argument("--out", default=".")
    pr.add_argument(
        "--source",
        default=None,
        metavar="DOCX",
        help="the source .docx these predictions were parsed from; stamps its "
        "sha256 into the record so compare enforces source identity (R7)",
    )
    pr.set_defaults(func=_cmd_predict)

    bl = sub.add_parser("bless", help="silver → gold store, with the R7 source-hash check")
    bl.add_argument("silver")
    bl.add_argument("--out", default=".", help="root of the gold store (writes <out>/gold/<doc_id>.json)")
    bl.add_argument("--force", action="store_true")
    bl.set_defaults(func=_cmd_bless)

    rc = sub.add_parser("reconcile", help="field-level diff of blessed gold vs a re-bootstrapped draft (R6)")
    rc.add_argument("--gold", required=True)
    rc.add_argument("--draft", required=True)
    rc.set_defaults(func=_cmd_reconcile)

    c = sub.add_parser("compare", help="gold + prediction → metrics + dataset files (Script 3)")
    c.add_argument("--gold", required=True)
    c.add_argument("--pred", required=True)
    c.add_argument("--out", default=".")
    c.add_argument("--run-id", default="")
    c.add_argument("--gold-commit", default="")
    c.add_argument("--mlflow", action="store_true", help="also log an MLflow run if installed")
    c.add_argument("--allow-source-mismatch", action="store_true",
                   help="compare records from different source bytes anyway (R7 override)")
    c.set_defaults(func=_cmd_compare)

    r = sub.add_parser("run", help="compare over a corpus manifest → one combined results table")
    r.add_argument("--manifest", required=True,
                   help='JSON: [{"doc_id": …, "gold": path, "pred": path}, …]')
    r.add_argument("--out", default=".")
    r.add_argument("--stem", default="corpus")
    r.add_argument("--run-id", default="")
    r.add_argument("--gold-commit", default="")
    r.add_argument("--mlflow", action="store_true")
    r.add_argument("--allow-source-mismatch", action="store_true")
    r.set_defaults(func=_cmd_run)

    s = sub.add_parser("snapshot", help="drift check: record content hash vs stored baseline")
    s.add_argument("record")
    s.add_argument("--dir", default="snapshots")
    s.add_argument("--update", action="store_true", help="accept the change as the new baseline")
    s.set_defaults(func=_cmd_snapshot)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
