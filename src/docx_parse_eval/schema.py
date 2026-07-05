"""The contract: the model-agnostic ``EvaluationRecord`` schema (spec §7).

Both the gold/reference adapter and every model adapter emit this *identical*
shape (R1). The comparator only ever sees this schema — never a model-native or
exported format (R5). Field names and types mirror spec §7 verbatim so that
document stays the readable contract.

Represented as Pydantic v2 models (not stdlib dataclasses) so JSON round-trips
are validated for free — which is exactly the §11 "JSON records are the source
of truth" requirement. ``schema_version`` is frozen at ``SCHEMA_VERSION``; any
field change is a breaking event that bumps it (R1, R2).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Frozen schema version. Bump on ANY change to the field set below.
#: 0.2: scalar counts became ``int | None`` — ``None`` means "this producer does
#: not extract this feature", which the comparator must skip rather than treat
#: as an extraction failure (essential once multiple parsers are compared).
#: 0.3: added ``vector_shape_count`` — figures now mean *raster images*
#: (Docling-comparable); vector shapes/diagrams are tracked separately so
#: shape-built workflow diagrams stay visible without false figure flags.
#: 0.4: added ``TableRecord.cells`` (per-cell grid with spans + text) — the
#: substrate for the TEDS quality tier. Optional: adapters that cannot
#: recover a coherent grid emit ``None`` and TEDS is skipped for that table.
#: (0.4, no bump: value constraints — non-negative counts/positions, spans ≥ 1,
#: heading level ≥ 1. The field set is unchanged; records these reject were
#: never meaningful, so this is not a breaking event.)
SCHEMA_VERSION = "0.4"

#: The closed alphabet of block types allowed in ``element_sequence`` (spec §7).
#: Shared by adapters (which build the sequence) and the comparator's
#: element-type edit-distance metric (§8.2), so both sides use one alphabet.
ElementType = Literal[
    "heading",
    "paragraph",
    "table",
    "figure",
    "list",
    "caption",
]


class _Record(BaseModel):
    """Base config shared by every record: reject unknown fields so an adapter
    that drifts from the contract fails loudly rather than silently."""

    model_config = ConfigDict(extra="forbid")


class TableCellRecord(_Record):
    """One grid cell: origin + spans + normalised text. Together these are the
    ``table → tr → td`` tree TEDS scores — kept structured (not HTML) so the
    record stays tool-inspectable and adapters skip a serialisation round-trip."""

    row: int = Field(ge=0)  # 0-based grid origin
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    text: str = ""


class TableRecord(_Record):
    table_id: str  # positional or content-hash based
    position: int = Field(ge=0)  # index in reading order
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    cell_count: int = Field(ge=0)
    has_header: bool  # header row detected
    cell_text_length: int = Field(ge=0)  # total normalised chars across all cells
    # Per-cell grid (0.4, quality tier). None = producer can't recover a
    # coherent grid for this table → TEDS is skipped, conservation metrics
    # above still apply. Deliberately NOT validated against (n_rows, n_cols):
    # a parser that emits an out-of-bounds span is exactly the defect this
    # harness exists to record and score — TEDS penalises it, validation
    # refusing the record would hide it.
    cells: list[TableCellRecord] | None = None


class FigureRecord(_Record):
    figure_id: str
    position: int = Field(ge=0)
    caption_text: str  # normalised; "" if none
    has_caption: bool


class HeadingRecord(_Record):
    text: str  # normalised
    level: int = Field(ge=1)  # 1-based
    position: int = Field(ge=0)


class ListRecord(_Record):
    list_id: str
    position: int = Field(ge=0)
    n_items: int = Field(ge=0)
    is_ordered: bool


class EvaluationRecord(_Record):
    # --- identity & provenance ---
    doc_id: str  # stable slug, e.g. "wh-spec-001"
    title: str  # human-readable
    source_path: str  # path to the .docx
    # Hash of the .docx — guards gold validity (R7). Either a real sha256
    # (64 lowercase hex) or "" = unbound; nothing else, so a placeholder like
    # "unknown" can never satisfy compare's equality gate by accident.
    source_sha256: str = Field(pattern=r"^(|[0-9a-f]{64})$")
    schema_version: str = SCHEMA_VERSION  # bump on any schema change
    producer: str  # adapter id, e.g. "ooxml-reference" | "docling-adapter"
    producer_version: str  # adapter/pipeline version for traceability

    # --- text ---
    word_count: int = Field(ge=0)
    char_count_normalized: int = Field(ge=0)  # after whitespace + Unicode (NFC) normalisation
    # Optional: kept nullable so NED (§8.4) can be added later without a schema
    # bump; adapters may omit it for lighter, count-only records (§13).
    full_text_normalized: str | None = None

    # --- structural inventories ---
    tables: list[TableRecord] = Field(default_factory=list)
    figures: list[FigureRecord] = Field(default_factory=list)
    headings: list[HeadingRecord] = Field(default_factory=list)
    lists: list[ListRecord] = Field(default_factory=list)

    # --- scalar counts ---
    # ``None`` = the producer's adapter does not extract this feature (distinct
    # from 0 = "extracted, none found"). The comparator emits a non-flagging
    # "not-extracted" row when either side is None.
    hyperlink_count: Annotated[int, Field(ge=0)] | None
    footnote_count: Annotated[int, Field(ge=0)] | None
    endnote_count: Annotated[int, Field(ge=0)] | None
    # Vector shapes / connectors / text-box frames (graphic objects with no
    # raster image). Diagrams built from grouped shapes are invisible to most
    # parsers' picture inventories — this keeps their presence measurable
    # without polluting figure_count. None = producer doesn't extract it.
    vector_shape_count: Annotated[int, Field(ge=0)] | None = None

    # --- ordering ---
    element_sequence: list[ElementType] = Field(default_factory=list)

    # --- content tokens ---
    identifier_tokens: list[str] = Field(default_factory=list)  # multiset, sorted
    special_chars: list[str] = Field(default_factory=list)  # e.g. ["°","×","±","µ"]

    @field_validator("schema_version")
    @classmethod
    def _pin_schema_version(cls, v: str) -> str:
        # R1/R2: any field change bumps SCHEMA_VERSION, so a record claiming a
        # different version was written against a different contract — refuse
        # rather than compare across contracts. (Not a Literal so the accepted
        # value has a single source of truth in SCHEMA_VERSION.)
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"record schema_version {v!r} != supported {SCHEMA_VERSION!r}; "
                "re-run its adapter against this version of the harness"
            )
        return v
