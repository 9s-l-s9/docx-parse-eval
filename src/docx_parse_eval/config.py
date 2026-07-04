"""Frozen first-pass decisions for the spec §13 open items.

Everything here is a *named, centralised* placeholder so nothing downstream
hardcodes it. Flag thresholds carry a ``CALIBRATE-PHASE-4`` marker: they are set
to plausible starting values and tuned on FIXTURES in Phase 4 (R8 — never on the
real corpus).
"""

from __future__ import annotations

import re
from enum import Enum

# --- Identifier tokenisation (§13: "identifier regex") -----------------------
# Calibrated on the public corpus: the first pass made the unit OPTIONAL, so
# every bare small integer (page/list/heading numbers, "Section 1") entered the
# token set and produced spurious Jaccard flags on numbering-representation
# differences. An identifier is now: a number WITH a unit, a decimal number,
# a long (≥3-digit) number, or a part-style ID.
_UNIT = r"(?:mm|cm|m|kg|°|×|±|µ|%|V|A|W|Hz)"
IDENTIFIER_REGEX = re.compile(
    rf"\b\d+(?:[.,]\d+)?\s?{_UNIT}\b"  # measurements (unit required)
    rf"|\b\d+[.,]\d+\b"  # decimal numbers
    rf"|\b\d{{3,}}\b"  # long numbers (part of codes, years, dimensions)
    rf"|\b[A-Z]{{1,4}}-?\d{{2,}}\b"  # part-style IDs
)


# --- Figure-counting policy (§13) --------------------------------------------
class GroupedShapePolicy(str, Enum):
    """How to treat grouped vector shapes (warehouse diagrams may be grouped
    shapes, not single rasters). Spec §13: flag rather than fail."""

    FLAG = "flag"
    COUNT_AS_ONE = "count_as_one"
    IGNORE = "ignore"


#: Count embedded images / PictureItems; exclude header/footer (furniture-layer)
#: images. Both adapters MUST apply this identical policy or the figure-count
#: metric flags on policy rather than on Docling.
COUNT_FURNITURE_FIGURES = False
GROUPED_SHAPE_POLICY = GroupedShapePolicy.FLAG


# --- Matching strategy (§13 / spec §5.4) -------------------------------------
MATCH_BY_POSITION_FIRST = True
CAPTION_SIM_THRESHOLD = 0.85  # CALIBRATE-PHASE-4: caption-text match fallback
#: When table counts differ, pairs are greedy-matched by cell-text similarity;
#: a pair below this floor stays UNMATCHED (a count defect, owned by the
#: dimension metric) rather than being force-paired into a bogus TEDS score.
TABLE_TEXT_SIM_THRESHOLD = 0.85


# --- Flag thresholds (§8 / §13) ----------------------------------------------
# Boundaries are PINNED by tests/test_calibration.py (sub-threshold stays quiet,
# supra-threshold fires). Change a value here ⇒ update its boundary test; that
# pairing is the calibration record. Values remain first-pass until exercised
# against real-corpus-derived synthetic fixtures (Phase 5 feedback loop).
LENGTH_RATIO_DELTA = 0.05  # δ: char-count length-ratio band [1-δ, 1+δ] (§8.4)
DUPLICATION_EPSILON = 0.05  # ε: duplication when pred/source > 1+ε (§8.3)
NED_THRESHOLD = 0.10  # normalised edit distance over full text (§8.4)
JACCARD_THRESHOLD = 0.95  # identifier-token overlap floor (§8.3)
SEQ_EDIT_DISTANCE_THRESHOLD = 1  # element_sequence edit distance (§8.2): flag when > 1
# (a transposition reads as distance 2 → fires; a single dropped block is
# distance 1 → stays quiet so the count metric is that defect's signal.)
# CALIBRATED on the public corpus: the distance is computed over the
# RUN-LENGTH-COLLAPSED sequence ("p p p l" → "p l"), so the metric measures
# block-type ORDERING, not segmentation granularity — parsers legitimately
# split one paragraph/list into several blocks, and that noise fired the
# metric on 12/26 real fixtures while true reorderings still read ≥ 2.


# --- Quality tier: TEDS (spec §12) --------------------------------------------
# Score = worst (min) TEDS over matched table pairs; skipped when a side has
# no cell grid. CALIBRATE against blessed real-corpus gold.
TEDS_THRESHOLD = 0.95  # full TEDS: structure + cell text
TEDS_STRUCT_THRESHOLD = 0.95  # TEDS-Struct: grid topology only
#: APTED is ~O(n²) in nodes: a pair whose larger table exceeds this many cells
#: is reported as not-scored (informational) instead of stalling a corpus run.
TEDS_MAX_CELLS = 1500


# --- Metric gating ------------------------------------------------------------
#: Metrics whose flag is INFORMATIONAL, not gating: they compare signals whose
#: definitions legitimately differ between producers, so a tripped flag means
#: "policy disagreement worth a look", not "guaranteed defect". `fired_flags()`
#: and the CLI exit gate exclude them by default.
#: - table_header_detection: OOXML reads the explicit `w:tblHeader` property
#:   (rarely set even on visually-headed tables) while parsers like Docling
#:   *infer* column headers — two different definitions of "has a header".
NON_GATING_METRICS = frozenset({"table_header_detection"})
