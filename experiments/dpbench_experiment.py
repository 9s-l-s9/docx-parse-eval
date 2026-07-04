"""Experiment (NOT a CI correctness test) — exercise the harness on the real
docling-dpbench benchmark (docling-project/docling-dpbench, 200 docs).

Each row carries a ground-truth `DoclingDocument` and Docling's predicted
`DoclingDocument` (both serialized JSON). We push BOTH through Script 2 (the
docling adapter) and run Script 3 (comparator):

    GroundTruthDocument ─► docling_adapter ─► gold record  ┐
                                                           ├─► compare → flags
    PredictedDocument   ─► docling_adapter ─► pred record  ┘

What this validates: (a) the adapter survives 400 real DoclingDocuments without
crashing; (b) the comparator runs on 200 real GT-vs-prediction divergences;
(c) plausibility — flags should concentrate on rows where GT and prediction
actually differ, and stay quiet where they match.

What it does NOT do: certify metric correctness (no known-true answer for our
conservation metrics; both sides are Docling, so Script 1/OOXML is untested and
the independent-reference property is bypassed — see plan §"docling-eval"). The
by-construction synthetic fixtures remain the correctness certificate.

Usage: python3 dpbench_experiment.py <path-to-dpbench.parquet>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docx_parse_eval.adapters.docling_adapter import extract_from_dict
from docx_parse_eval.comparator import compare, fired_flags


def main(parquet_path: str) -> None:
    # Read only the two DoclingDocument string columns (skip image blobs).
    cols = ["document_id", "GroundTruthDocument", "PredictedDocument"]
    table = pq.read_table(parquet_path, columns=cols)
    gt_col = table.column("GroundTruthDocument").to_pylist()
    pred_col = table.column("PredictedDocument").to_pylist()
    ids = table.column("document_id").to_pylist()
    n = len(ids)

    parse_fail = 0
    compare_fail = 0
    flag_counter: Counter = Counter()
    rows_with_flags = 0
    identical_record_rows = 0
    identical_and_flagged = 0  # should be ~0 (a real false-alarm signal)
    diff_rows = 0
    diff_and_flagged = 0  # should be high (sensitivity on real divergence)

    for i in range(n):
        try:
            gt = extract_from_dict(json.loads(gt_col[i]), doc_id=f"{ids[i]}::gt")
            pr = extract_from_dict(json.loads(pred_col[i]), doc_id=f"{ids[i]}::pred")
        except Exception as e:  # noqa: BLE001
            parse_fail += 1
            print(f"  PARSE FAIL row {i} ({ids[i]}): {type(e).__name__}: {e}")
            continue
        try:
            results = compare(gt, pr)
        except Exception as e:  # noqa: BLE001
            compare_fail += 1
            print(f"  COMPARE FAIL row {i} ({ids[i]}): {type(e).__name__}: {e}")
            continue

        flags = fired_flags(results)
        # "records identical" = the two projected schema records are equal
        # (provenance excluded). A robust specificity proxy.
        same = gt.model_dump(exclude={"doc_id", "title", "source_path"}) == pr.model_dump(
            exclude={"doc_id", "title", "source_path"}
        )
        if same:
            identical_record_rows += 1
            if flags:
                identical_and_flagged += 1
        else:
            diff_rows += 1
            if flags:
                diff_and_flagged += 1
        if flags:
            rows_with_flags += 1
            flag_counter.update(flags)

    print("\n================ docling-dpbench experiment ================")
    print(f"rows                         : {n}")
    print(f"parse failures (adapter)     : {parse_fail}")
    print(f"compare failures             : {compare_fail}")
    print(f"rows with >=1 flag           : {rows_with_flags}")
    print(f"\n-- specificity proxy (records identical post-projection) --")
    print(f"identical-record rows        : {identical_record_rows}")
    print(f"  ...of which flagged (≈0?)  : {identical_and_flagged}")
    print(f"\n-- sensitivity proxy (records differ) --")
    print(f"differing-record rows        : {diff_rows}")
    print(f"  ...of which flagged        : {diff_and_flagged}"
          f"  ({100*diff_and_flagged/diff_rows:.0f}%)" if diff_rows else "")
    print(f"\n-- flag distribution (metric → #rows) --")
    for metric, cnt in flag_counter.most_common():
        print(f"  {metric:28} {cnt}")


if __name__ == "__main__":
    main(sys.argv[1])
