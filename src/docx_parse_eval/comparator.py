"""Script 3 — the comparator (gold + prediction → metrics), spec §5.4 / §8.

Pure and model-agnostic: it matches elements across the two records, compares
attributes, and applies flag thresholds. No parsing, no structural algorithms,
no reimplementation (R4) — edit distance comes from the `Levenshtein` library.
It has no knowledge of which model produced the prediction.

Each metric yields a `MetricResult(metric, source_value, prediction_value,
ratio_or_score, flag)`. A `flag=True` means a threshold tripped → a guaranteed
defect on at least one side, always worth inspecting (spec §3).
"""

from __future__ import annotations

from collections import Counter
from itertools import groupby

import Levenshtein
from pydantic import BaseModel

from docx_parse_eval import config as C
from docx_parse_eval.schema import EvaluationRecord, ElementType
from docx_parse_eval.teds import teds

# Stable single-char encoding of element types so Levenshtein (a string metric)
# can score the element-type sequence (§8.2).
_SEQ_ALPHABET: dict[str, str] = {
    "heading": "h",
    "paragraph": "p",
    "table": "t",
    "figure": "f",
    "list": "l",
    "caption": "c",
}


class MetricResult(BaseModel):
    metric: str
    source_value: str
    prediction_value: str
    ratio_or_score: float | None = None
    flag: bool


def _ratio(num: float, den: float) -> float | None:
    return None if den == 0 else num / den


def _count_metric(name: str, src: int | None, pred: int | None) -> MetricResult:
    # None = the producer's adapter does not extract this feature (schema 0.2):
    # emit a visible but non-flagging row — an adapter gap is not a parser defect.
    if src is None or pred is None:
        return MetricResult(
            metric=name,
            source_value="not-extracted" if src is None else str(src),
            prediction_value="not-extracted" if pred is None else str(pred),
            ratio_or_score=None,
            flag=False,
        )
    return MetricResult(
        metric=name,
        source_value=str(src),
        prediction_value=str(pred),
        ratio_or_score=_ratio(pred, src),
        flag=src != pred,
    )


def _band_flag(num: int, den: int) -> tuple[float | None, bool]:
    """Length-ratio band check that still fires when the gold side is empty but
    the prediction is not (ratio undefined, yet clearly out of band)."""
    ratio = _ratio(num, den)
    if ratio is None:
        return None, num > 0
    return ratio, not (1 - C.LENGTH_RATIO_DELTA <= ratio <= 1 + C.LENGTH_RATIO_DELTA)


def _align_captions(gold_figs, pred_figs) -> list[tuple[str, str]]:
    """Caption pairs for the association metric. Position-first (zip) when the
    figure counts agree; when they differ, greedy best-similarity matching over
    captioned figures so one spurious extra figure does not cascade a
    misalignment over every later caption (spec §5.4 fallback)."""
    if len(gold_figs) == len(pred_figs):
        return [
            (g.caption_text, p.caption_text)
            for g, p in zip(gold_figs, pred_figs)
            if g.has_caption or p.has_caption
        ]
    g_caps = [f.caption_text for f in gold_figs if f.has_caption]
    p_caps = [f.caption_text for f in pred_figs if f.has_caption]
    pairs: list[tuple[str, str]] = []
    remaining = list(p_caps)
    for g in g_caps:
        if not remaining:
            break
        best = max(remaining, key=lambda p: Levenshtein.ratio(g, p))
        remaining.remove(best)
        pairs.append((g, best))
    # Unmatched leftovers are a COUNT defect (figure_count / caption_count
    # already flag it); association only judges the matched pairs.
    return pairs


def _align_tables(gold_tables, pred_tables) -> list[tuple]:
    """Table pairs for the quality metrics. Position-first (zip) when counts
    agree; when they differ, greedy cell-text similarity matching — a parser
    dropping table 2 of 5 must not shift every later TEDS pair onto the wrong
    partner. Pairs below TABLE_TEXT_SIM_THRESHOLD stay unmatched: that is a
    count defect (the dimension metric owns it), not a quality score."""
    if len(gold_tables) == len(pred_tables):
        return list(zip(gold_tables, pred_tables))

    def text(t) -> str:
        return " ".join(c.text for c in t.cells) if t.cells else ""

    remaining = list(pred_tables)
    pairs: list[tuple] = []
    for g in gold_tables:
        if not remaining:
            break
        best = max(remaining, key=lambda p: Levenshtein.ratio(text(g), text(p)))
        if Levenshtein.ratio(text(g), text(best)) >= C.TABLE_TEXT_SIM_THRESHOLD:
            remaining.remove(best)
            pairs.append((g, best))
    return pairs


def _encode_seq(seq: list[ElementType]) -> str:
    """Single-char encoding with runs collapsed ("p p p l l" → "p l"): the
    metric scores block-type ORDERING; how finely a parser segments one
    paragraph or list into blocks is representational, not a defect."""
    return "".join(k for k, _ in groupby(_SEQ_ALPHABET[s] for s in seq))


def compare(gold: EvaluationRecord, pred: EvaluationRecord) -> list[MetricResult]:
    results: list[MetricResult] = []

    # --- R7: gold is bound to its source -------------------------------------
    # Comparing records derived from DIFFERENT source bytes invalidates every
    # metric below. Flag when both sides carry a hash and they differ; an
    # empty hash (e.g. a prediction built from JSON alone) is informational.
    g_sha, p_sha = gold.source_sha256, pred.source_sha256
    results.append(
        MetricResult(
            metric="source_identity",
            source_value=g_sha[:12] if g_sha else "unknown",
            prediction_value=p_sha[:12] if p_sha else "unknown",
            ratio_or_score=None,
            flag=bool(g_sha) and bool(p_sha) and g_sha != p_sha,
        )
    )

    # --- §8.1 Completeness ---------------------------------------------------
    results.append(_count_metric("figure_count", len(gold.figures), len(pred.figures)))
    results.append(
        _count_metric(
            "caption_count",
            sum(f.has_caption for f in gold.figures),
            sum(f.has_caption for f in pred.figures),
        )
    )
    # Caption association (§8.1): match figures position-first; a matched
    # figure whose caption text diverges is a defect even if the caption COUNT
    # is unchanged. Similarity via Levenshtein ratio (R4).
    cap_pairs = _align_captions(gold.figures, pred.figures)
    min_sim = min((Levenshtein.ratio(a, b) for a, b in cap_pairs), default=1.0)
    results.append(
        MetricResult(
            metric="caption_association",
            source_value=str(sum(f.has_caption for f in gold.figures)),
            prediction_value=str(sum(f.has_caption for f in pred.figures)),
            ratio_or_score=min_sim,
            flag=min_sim < C.CAPTION_SIM_THRESHOLD,
        )
    )

    results.append(
        _count_metric(
            "list_item_count",
            sum(l.n_items for l in gold.lists),
            sum(l.n_items for l in pred.lists),
        )
    )
    results.append(_count_metric("hyperlink_count", gold.hyperlink_count, pred.hyperlink_count))
    results.append(_count_metric("footnote_count", gold.footnote_count, pred.footnote_count))
    results.append(_count_metric("endnote_count", gold.endnote_count, pred.endnote_count))
    # Vector shapes (diagrams built from grouped shapes): most parsers have no
    # shape inventory (None → informational row), but between two producers
    # that do extract it, a lost diagram is a real defect.
    results.append(
        _count_metric("vector_shape_count", gold.vector_shape_count, pred.vector_shape_count)
    )

    g_levels = Counter(h.level for h in gold.headings)
    p_levels = Counter(h.level for h in pred.headings)
    results.append(
        MetricResult(
            metric="heading_count_by_level",
            source_value=str(dict(sorted(g_levels.items()))),
            prediction_value=str(dict(sorted(p_levels.items()))),
            flag=g_levels != p_levels,
        )
    )

    # --- §8.2 Structure ------------------------------------------------------
    g_dims = [(t.n_rows, t.n_cols, t.cell_count) for t in gold.tables]
    p_dims = [(t.n_rows, t.n_cols, t.cell_count) for t in pred.tables]
    results.append(
        MetricResult(
            metric="table_dimensions",
            source_value=str(g_dims),
            prediction_value=str(p_dims),
            flag=g_dims != p_dims,
        )
    )
    # Quality tier (spec §12): TEDS + TEDS-Struct over matched table pairs
    # (similarity-aligned when counts differ). Reported as the WORST pair
    # (regression signal); a pair without a cell grid on either side — or one
    # too large to score in reasonable time (TEDS_MAX_CELLS) — is skipped,
    # and if nothing is scorable the row is informational (not-extracted),
    # mirroring the None-count convention.
    table_pairs = _align_tables(gold.tables, pred.tables)
    scorable = [
        (g, p)
        for g, p in table_pairs
        if g.cells is not None
        and p.cells is not None
        and max(len(g.cells), len(p.cells)) <= C.TEDS_MAX_CELLS
    ]
    if table_pairs:
        for metric, struct_only, threshold in (
            ("table_teds", False, C.TEDS_THRESHOLD),
            ("table_teds_struct", True, C.TEDS_STRUCT_THRESHOLD),
        ):
            if scorable:
                score = min(
                    teds(g.cells, p.cells, structure_only=struct_only) for g, p in scorable
                )
                results.append(
                    MetricResult(
                        metric=metric,
                        source_value=str(len(gold.tables)),
                        prediction_value=str(len(pred.tables)),
                        ratio_or_score=score,
                        flag=score < threshold,
                    )
                )
            else:
                results.append(
                    MetricResult(
                        metric=metric,
                        source_value="not-extracted",
                        prediction_value="not-extracted",
                        ratio_or_score=None,
                        flag=False,
                    )
                )

    g_hdr = [t.has_header for t in gold.tables]
    p_hdr = [t.has_header for t in pred.tables]
    results.append(
        MetricResult(
            metric="table_header_detection",
            source_value=str(g_hdr),
            prediction_value=str(p_hdr),
            flag=g_hdr != p_hdr,
        )
    )
    seq_dist = Levenshtein.distance(_encode_seq(gold.element_sequence), _encode_seq(pred.element_sequence))
    results.append(
        MetricResult(
            metric="element_sequence_distance",
            source_value=str(len(gold.element_sequence)),
            prediction_value=str(len(pred.element_sequence)),
            ratio_or_score=float(seq_dist),
            flag=seq_dist > C.SEQ_EDIT_DISTANCE_THRESHOLD,
        )
    )

    # --- §8.3 Content preservation ------------------------------------------
    # Multiset (not set) Jaccard, per spec §7/§8.3: a token appearing 10× and
    # surviving once is a defect a set comparison would hide.
    g_tok, p_tok = Counter(gold.identifier_tokens), Counter(pred.identifier_tokens)
    union = sum((g_tok | p_tok).values())
    jaccard = 1.0 if not union else sum((g_tok & p_tok).values()) / union
    results.append(
        MetricResult(
            metric="identifier_token_overlap",
            source_value=str(sum(g_tok.values())),
            prediction_value=str(sum(p_tok.values())),
            ratio_or_score=jaccard,
            flag=jaccard < C.JACCARD_THRESHOLD,
        )
    )

    g_cell = sum(t.cell_text_length for t in gold.tables)
    p_cell = sum(t.cell_text_length for t in pred.tables)
    cell_ratio, cell_flag = _band_flag(p_cell, g_cell)
    results.append(
        MetricResult(
            metric="table_text_length",
            source_value=str(g_cell),
            prediction_value=str(p_cell),
            ratio_or_score=cell_ratio,
            flag=cell_flag,
        )
    )

    dup_ratio = _ratio(pred.char_count_normalized, gold.char_count_normalized)
    results.append(
        MetricResult(
            metric="duplication_direction",
            source_value=str(gold.char_count_normalized),
            prediction_value=str(pred.char_count_normalized),
            ratio_or_score=dup_ratio,
            flag=dup_ratio is not None and dup_ratio > 1 + C.DUPLICATION_EPSILON,
        )
    )

    missing_chars = sorted(set(gold.special_chars) - set(pred.special_chars))
    results.append(
        MetricResult(
            metric="special_char_survival",
            source_value=str(sorted(gold.special_chars)),
            prediction_value=str(sorted(pred.special_chars)),
            flag=bool(missing_chars),
        )
    )

    # --- §8.4 Text fidelity --------------------------------------------------
    len_ratio, len_flag = _band_flag(pred.char_count_normalized, gold.char_count_normalized)
    results.append(
        MetricResult(
            metric="length_ratio",
            source_value=str(gold.char_count_normalized),
            prediction_value=str(pred.char_count_normalized),
            ratio_or_score=len_ratio,
            flag=len_flag,
        )
    )

    if gold.full_text_normalized is not None and pred.full_text_normalized is not None:
        g_t, p_t = gold.full_text_normalized, pred.full_text_normalized
        denom = max(len(g_t), len(p_t))
        if denom == 0:
            ned = 0.0
        else:
            # Full O(n·m) edit distance is infeasible on 100+-page documents
            # (hundreds of kchars per side). We only need to know whether NED
            # exceeds the threshold, so cap the search: distance() early-exits
            # once the cutoff is exceeded and returns cutoff+1.
            cutoff = int(C.NED_THRESHOLD * denom) + 1
            ned = Levenshtein.distance(g_t, p_t, score_cutoff=cutoff) / denom
        results.append(
            MetricResult(
                metric="full_text_ned",
                source_value=str(len(g_t)),
                prediction_value=str(len(p_t)),
                ratio_or_score=ned,
                flag=ned > C.NED_THRESHOLD,
            )
        )

    return results


def fired_flags(results: list[MetricResult], *, include_non_gating: bool = False) -> set[str]:
    """The set of metric names whose flag tripped. Informational metrics
    (config.NON_GATING_METRICS — policy disagreements, not defects) are
    excluded unless ``include_non_gating`` is set; they stay visible in the
    emitted results table either way."""
    fired = {r.metric for r in results if r.flag}
    return fired if include_non_gating else fired - C.NON_GATING_METRICS
