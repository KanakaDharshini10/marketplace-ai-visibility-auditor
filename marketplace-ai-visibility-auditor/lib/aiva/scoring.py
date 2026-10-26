"""Turn findings into pillar scores and an overall readiness score.

Scores are a *communication* device, not the product: the findings and the
evidence are. They exist so a non-expert can see at a glance which of the six
concerns is dragging the site down, and so two runs can be compared over time.

A score is only ever reported over the pillars that had evidence behind them.
A pillar the crawl could not measure scores ``None`` and is excluded from the
weighted mean, and a band better than ``BAND_CAP_WITHOUT_COVERAGE`` requires a
majority of the model to have been measured at all.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from .findings import (PILLAR_DIMENSION, PILLARS, ROLE_CORROBORATION,
                       SCORING_ROLE, SEVERITY_WEIGHT, Finding)
from .util import clamp

#: How much each pillar contributes to the overall readiness score.
#: The five mechanism pillars keep the ratios they always had (24:24:16:16:20);
#: they are scaled by 0.85 to make room for the outcome pillar. Answerability
#: is deliberately the smallest weight: it is the check that matters most to a
#: reader, but it is derived from the same evidence the other five measure, so
#: giving it a large share would count that evidence twice.
PILLAR_WEIGHTS = {
    "crawl_render": 0.204,          # if a machine can't reach it, nothing else matters
    "machine_readability": 0.204,   # ...and if it can't parse it, nothing else matters
    "entity": 0.136,                # who is this, and is it the right "who"?
    "freshness_corroboration": 0.136,
    "engagement": 0.170,            # the on-site half of the Round-2 problem
    "answerability": 0.150,         # can the evidence answer a buyer's question?
}

#: A single critical finding should hurt, but not zero a pillar outright -
#: real sites usually have more than one thing wrong and the ranking between
#: them must stay legible.
PENALTY_SCALE = 0.6

#: A readiness band above this one is a claim the whole model has to support.
#: Below MIN_WEIGHT_FOR_CONFIDENT_BAND of measured weight the band is capped
#: here, while the score itself is reported unchanged.
BAND_CAP_WITHOUT_COVERAGE = "weak"

#: Fraction of total pillar weight that must be measured before a band better
#: than the cap may be assigned. A majority of the model, so a single measured
#: pillar can never characterise the site on its own.
MIN_WEIGHT_FOR_CONFIDENT_BAND = 0.5

#: Band descriptions describe the *evidence* the site publishes - what a
#: machine can find, read and attribute from it - never what any assistant
#: does with it, which this audit does not measure.
BANDS = (
    (85, "strong", "The site's pages publish explicit, machine-readable evidence for the "
                   "facts it states; few gaps were observed."),
    (70, "workable", "Mostly readable; specific, named gaps leave some facts without "
                     "machine-readable evidence."),
    (50, "weak", "The site can be reached and read, but many of the facts it states are "
                 "not published in a form that can be read without interpretation."),
    (30, "poor", "Substantial parts of the site publish no machine-readable evidence for "
                 "the facts they state, or could not be read by this audit."),
    (0, "critical", "Little of the site's content was readable, reachable or stated in a "
                    "form a machine can quote; the findings say which."),
)


def _penalty(finding: Finding) -> float:
    """What this finding costs its pillar.

    A finding marked as corroborating another (see
    :func:`aiva.report.link_corroborating`) costs nothing on its own: it
    measures a second property of a condition already charged, and the site
    owner performs one piece of work to answer both. It keeps its severity, its
    evidence and its place in the report - only the second charge is dropped,
    because the score is a statement about how much is wrong, not about how
    many ways the audit found to say it.
    """
    if (finding.metrics or {}).get(SCORING_ROLE) == ROLE_CORROBORATION:
        return 0.0
    base = SEVERITY_WEIGHT.get(finding.severity, 0)
    return base * float(finding.confidence) * PENALTY_SCALE


def pillar_scores(findings: Iterable[Finding],
                  unmeasured: Iterable[str] = ()) -> Dict[str, dict]:
    """Score each pillar, and refuse to score one whose evidence was never gathered.

    "No findings" and "nothing was looked at" are different states that used to
    produce the same number. A crawl that fetched zero pages reported four
    pillars at 100.0 and an overall of 72.4 - a reassuring score for a site the
    auditor never read, which is a stronger claim than any finding in the
    report makes. A pillar with no evidence behind it now scores ``None`` and
    is excluded from the weighted mean rather than counted as perfect.
    """
    unmeasured = set(unmeasured)
    buckets: Dict[str, List[Finding]] = {pillar: [] for pillar in PILLARS}
    for finding in findings:
        buckets.setdefault(finding.pillar, []).append(finding)

    out: Dict[str, dict] = {}
    for pillar, label in PILLARS.items():
        items = buckets.get(pillar, [])
        counts: Dict[str, int] = {}
        for finding in items:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        entry = {
            "label": label,
            "dimension": PILLAR_DIMENSION[pillar],
            "weight": PILLAR_WEIGHTS[pillar],
            "findings": len(items),
            "by_severity": counts,
            "measured": pillar not in unmeasured,
        }
        if pillar in unmeasured:
            entry.update({"score": None, "band": "unmeasured"})
        else:
            score = clamp(100.0 - sum(_penalty(f) for f in items))
            entry.update({"score": round(score, 1), "band": band_for(score)[0]})
        out[pillar] = entry
    return out


def _band_rank(name: str) -> int:
    """Higher is better. ``unmeasured`` sits below every real band."""
    order = [b[1] for b in reversed(BANDS)]        # critical .. strong
    return order.index(name) if name in order else -1


def band_for(score: float):
    for threshold, name, description in BANDS:
        if score >= threshold:
            return name, description
    return BANDS[-1][1], BANDS[-1][2]


def overall(pillars: Dict[str, dict]) -> dict:
    """Weighted mean over the pillars that were actually measured.

    Weights are unchanged; they are simply renormalised across the measured
    pillars, so an unmeasured one neither inflates the total (by counting as
    100) nor deflates it (by counting as 0). If nothing was measured there is
    no score to report, and the report says so rather than printing a number.
    """
    measured = [p for p in PILLAR_WEIGHTS if pillars.get(p, {}).get("score") is not None]
    total_weight = sum(PILLAR_WEIGHTS[p] for p in measured)
    if not measured or total_weight <= 0:
        return {
            "score": None,
            "band": "unmeasured",
            "interpretation": "No pillar had enough evidence to score. The crawl did not "
                              "obtain readable content, so this run reports what it "
                              "observed and makes no claim about the site's readiness.",
            "discoverability_score": None,
            "engagement_score": None,
            "measured_pillars": [],
            "unmeasured_pillars": sorted(PILLAR_WEIGHTS),
            "weight_measured": 0.0,
            "weakest_pillar": None,
        }
    score = sum(pillars[p]["score"] * PILLAR_WEIGHTS[p] for p in measured) / total_weight

    def dimension_score(name: str):
        members = [p for p in measured if PILLAR_DIMENSION[p] == name]
        weight = sum(PILLAR_WEIGHTS[p] for p in members)
        if not members or weight <= 0:
            return None
        return round(
            sum(pillars[p]["score"] * PILLAR_WEIGHTS[p] for p in members) / weight, 1)

    band, description = band_for(score)
    unmeasured = sorted(p for p in PILLAR_WEIGHTS if p not in measured)
    if unmeasured:
        description += (f" Scored over {len(measured)} of {len(PILLAR_WEIGHTS)} pillars; "
                        f"{', '.join(unmeasured)} had no evidence to score and are "
                        f"excluded rather than assumed sound.")

    # A readiness band is a claim about the whole site. Renormalising the score
    # over one measured pillar keeps the arithmetic honest but leaves the label
    # free to say "strong" on the strength of a healthy robots.txt alone - a
    # crawl that read nothing scored 93.2 and was labelled "Machines can find, read,
    # attribute and act on this site". The score is left exactly as
    # computed; only the *label* is capped, so a band better than
    # BAND_CAP_WITHOUT_COVERAGE requires a majority of the model to have been
    # measured. A site whose pages all errored already lands at or below the
    # cap and is unaffected.
    if total_weight < MIN_WEIGHT_FOR_CONFIDENT_BAND and \
            _band_rank(band) > _band_rank(BAND_CAP_WITHOUT_COVERAGE):
        band = BAND_CAP_WITHOUT_COVERAGE
        description += (f" The readiness band is capped at '{BAND_CAP_WITHOUT_COVERAGE}': "
                        f"only {round(100 * total_weight)}% of the scoring model had "
                        f"evidence behind it, which is not enough coverage to claim a "
                        f"better one.")
    return {
        "score": round(score, 1),
        "band": band,
        "interpretation": description,
        "discoverability_score": dimension_score("discoverability"),
        "engagement_score": dimension_score("engagement"),
        "measured_pillars": sorted(measured),
        "unmeasured_pillars": unmeasured,
        "weight_measured": round(total_weight, 4),
        "weakest_pillar": min(measured, key=lambda p: pillars[p]["score"]),
    }
