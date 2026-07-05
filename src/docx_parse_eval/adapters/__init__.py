"""Format-specific adapters projecting native parser output into the schema.

Each adapter emits the identical ``EvaluationRecord`` shape (R1, R10). Shared,
format-agnostic projection logic lives in ``_common`` so it cannot drift between
the gold side and any prediction side.

Prediction adapters are looked up by name (``predict --adapter NAME``): built-ins
first, then the ``docx_parse_eval.adapters`` entry-point group, so third-party
packages can register a model adapter without touching this repo. An adapter is
any module/object exposing ``extract(json_path, **kw) -> EvaluationRecord``.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Protocol

from docx_parse_eval.schema import EvaluationRecord


class Adapter(Protocol):
    """What ``predict`` needs from an adapter (R1: emit the shared schema)."""

    def extract(self, json_path, **kw) -> EvaluationRecord: ...


def get_adapter(name: str) -> Adapter:
    """Resolve an adapter by name: built-ins, then entry points."""
    from docx_parse_eval.adapters import docling_adapter

    builtin: dict[str, Adapter] = {"docling": docling_adapter}
    if name in builtin:
        return builtin[name]
    eps = entry_points(group="docx_parse_eval.adapters")
    for ep in eps:
        if ep.name == name:
            loaded = ep.load()
            if not callable(getattr(loaded, "extract", None)):
                raise TypeError(
                    f"adapter entry point {name!r} ({ep.value}) does not expose "
                    "extract(json_path, **kw) -> EvaluationRecord"
                )
            return loaded
    known = sorted(set(builtin) | {ep.name for ep in eps})
    raise KeyError(f"unknown adapter {name!r}; available: {', '.join(known)}")
