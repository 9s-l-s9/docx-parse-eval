"""Record (de)serialisation + path conventions (spec §11).

JSON records are the source of truth; CSV/Parquet/HF are derived views emitted
in Phase 4. This module only handles the authoritative JSON layer + path naming.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from docx_parse_eval.schema import EvaluationRecord

#: Fields that identify WHO produced a record / WHERE it lives, not WHAT was
#: extracted. Excluded from content hashing (snapshot tier) and from
#: reconciliation diffs — a version bump or moved file is not a content change.
PROVENANCE_FIELDS = frozenset({"producer", "producer_version", "source_path"})


def sha256_file(path: str | Path) -> str:
    """SHA-256 of a file's bytes — binds gold to its source (R7)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def gold_path(root: str | Path, doc_id: str) -> Path:
    """Authoritative gold record location: ``<root>/gold/<doc_id>.json``."""
    return Path(root) / "gold" / f"{doc_id}.json"


def prediction_path(root: str | Path, doc_id: str, producer: str) -> Path:
    """Prediction record location: ``<root>/pred/<doc_id>.<producer>.json``."""
    return Path(root) / "pred" / f"{doc_id}.{producer}.json"


def write_record(record: EvaluationRecord, path: str | Path) -> Path:
    """Serialise a record as pretty JSON (stable, diff-reviewable)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def read_record(path: str | Path) -> EvaluationRecord:
    """Load + validate a record from JSON (raises on contract violation)."""
    return EvaluationRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))


def record_content_hash(record: EvaluationRecord) -> str:
    """Deterministic hash of a record's extracted CONTENT (provenance fields
    excluded) — the snapshot tier's drift signal: same document, same parser
    config, different hash ⇒ the parser's output changed."""
    payload = record.model_dump()
    for field in PROVENANCE_FIELDS:
        payload.pop(field, None)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_diff(a: EvaluationRecord, b: EvaluationRecord) -> list[str]:
    """Field-level differences between two records as ``path: a → b`` lines,
    provenance excluded. The substrate of R6 reconciliation: diff a blessed
    gold against a re-bootstrapped silver draft and adjudicate each line."""
    lines: list[str] = []

    def walk(x, y, path: str) -> None:
        if isinstance(x, dict) and isinstance(y, dict):
            for key in sorted(set(x) | set(y)):
                if not path and key in PROVENANCE_FIELDS:
                    continue
                walk(x.get(key), y.get(key), f"{path}.{key}" if path else key)
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                lines.append(f"{path}: length {len(x)} → {len(y)}")
            for i, (xi, yi) in enumerate(zip(x, y)):
                walk(xi, yi, f"{path}[{i}]")
        elif x != y:
            lines.append(f"{path}: {x!r} → {y!r}")

    walk(a.model_dump(), b.model_dump(), "")
    return lines
