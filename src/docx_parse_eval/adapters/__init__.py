"""Format-specific adapters projecting native parser output into the schema.

Each adapter emits the identical ``EvaluationRecord`` shape (R1, R10). Shared,
format-agnostic projection logic lives in ``_common`` so it cannot drift between
the gold side and any prediction side.
"""
