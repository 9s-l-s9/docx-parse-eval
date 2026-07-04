"""Phase 4 — portable dataset artifacts (spec §11).

The portable, tool-inspectable dataset is the source of truth, independent of
MLflow: JSON records (authoritative) + a tidy long-form comparison table emitted
as **CSV** (Excel) and **Parquet** (pandas/Polars/DuckDB). MLflow run tracking
(§10) is an *optional* overlay handled in `mlflow_log` — import-guarded so the
harness and CI never depend on it (mlflow is not a Guix-provisioned dep).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from docx_parse_eval.comparator import MetricResult

#: Column order of the long-form comparison table (one row per metric).
RESULT_COLUMNS = [
    "doc_id",
    "producer",
    "metric",
    "source_value",
    "prediction_value",
    "ratio_or_score",
    "flag",
    "run_id",
    "gold_commit",
]


def results_to_long_df(
    results: list[MetricResult],
    *,
    doc_id: str,
    producer: str,
    run_id: str = "",
    gold_commit: str = "",
) -> pd.DataFrame:
    """One row per `(doc_id, producer, metric)` — the table you actually browse
    (filter by `flag`, sort by `ratio_or_score`)."""
    rows = [
        {
            "doc_id": doc_id,
            "producer": producer,
            "metric": r.metric,
            "source_value": r.source_value,
            "prediction_value": r.prediction_value,
            "ratio_or_score": r.ratio_or_score,
            "flag": r.flag,
            "run_id": run_id,
            "gold_commit": gold_commit,
        }
        for r in results
    ]
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def write_results_table(df: pd.DataFrame, out_dir: str | Path, stem: str = "results") -> dict[str, Path]:
    """Emit the long-form table as both CSV and Parquet (derived views; JSON
    records remain authoritative)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{stem}.csv"
    parquet_path = out_dir / f"{stem}.parquet"
    df.to_csv(csv_path, index=False)
    df.to_parquet(parquet_path, index=False)
    return {"csv": csv_path, "parquet": parquet_path}


def mlflow_log(*, params: dict, df: pd.DataFrame, artifact_paths: list[str | Path], tags: dict | None = None) -> bool:
    """Optional MLflow run logging (§10). Returns False (no-op) when mlflow is
    not installed, so callers never hard-depend on it. Per-document and
    aggregate metrics are logged; the §11 files are attached as artifacts."""
    try:
        import mlflow  # noqa: PLC0415
    except ImportError:
        return False

    with mlflow.start_run():
        mlflow.log_params(params)
        for _, row in df.iterrows():
            if row["ratio_or_score"] is not None:
                key = f"{row['metric']}__{row['doc_id']}"
                mlflow.log_metric(key, float(row["ratio_or_score"]))
        mlflow.log_metric("flag_count", int(df["flag"].sum()))
        for p in artifact_paths:
            mlflow.log_artifact(str(p))
        if tags:
            mlflow.set_tags(tags)
    return True
