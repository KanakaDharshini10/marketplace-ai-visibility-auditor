"""Rank findings so a non-expert knows what to do on Monday morning.

Priority is not the same as severity. Severity says *how broken this is*;
priority says *what to do first*, which also depends on how much of the site
the defect touches, how confident the evidence is, and how much work the fix
is. A site-wide one-line robots.txt fix outranks a deep, expensive rebuild
even when both are "high".
"""

from __future__ import annotations

from typing import Iterable, List

from .findings import SEVERITY_WEIGHT, Finding

#: How much of the site the defect touches.
SCOPE_FACTOR = {"site": 1.0, "template": 0.9, "section": 0.75, "page": 0.55}

#: Cheap fixes get a nudge up the list - they unblock value the same week.
EFFORT_FACTOR = {"low": 1.2, "medium": 1.0, "high": 0.8}

#: Pillars that gate everything downstream are worth doing first: a page that
#: is not served to a plain fetch cannot be improved by any fix further down
#: the funnel.
GATING_BONUS = {"crawl_render": 1.15, "machine_readability": 1.08}


def priority_score(finding: Finding) -> float:
    base = SEVERITY_WEIGHT.get(finding.severity, 0) * float(finding.confidence)
    scope = SCOPE_FACTOR.get(str(finding.metrics.get("scope", "template")), 0.9)
    effort = EFFORT_FACTOR.get(finding.suggested_action.effort, 1.0)
    gate = GATING_BONUS.get(finding.pillar, 1.0)
    return round(base * scope * effort * gate, 2)


def bucket(score: float) -> str:
    if score >= 70:
        return "critical"
    if score >= 40:
        return "high"
    if score >= 18:
        return "medium"
    return "low"


def prioritize(findings: Iterable[Finding]) -> List[Finding]:
    """Sort in place-ish and stamp ``priority_rank`` + action priority."""
    scored = []
    for finding in findings:
        score = priority_score(finding)
        finding.metrics = dict(finding.metrics)
        finding.metrics["priority_score"] = score
        # The analyzer's own priority is a floor: we never quietly demote a
        # fix its author considered urgent, but we may promote a cheap,
        # site-wide one.
        derived = bucket(score)
        order = ["low", "medium", "high", "critical"]
        if order.index(derived) > order.index(finding.suggested_action.priority):
            finding.suggested_action.priority = derived
        scored.append((score, finding))

    scored.sort(key=lambda pair: (
        -pair[0],
        ["critical", "high", "medium", "low", "info"].index(pair[1].severity),
        pair[1].rule_id,
    ))
    ordered: List[Finding] = []
    for rank, (_score, finding) in enumerate(scored, start=1):
        finding.priority_rank = rank
        ordered.append(finding)
    return ordered


def action_plan(findings: Iterable[Finding], limit: int = 12) -> List[dict]:
    """A flat, do-this-next list a non-expert can hand to a developer."""
    plan: List[dict] = []
    for finding in list(findings)[:limit]:
        action = finding.suggested_action
        plan.append({
            "rank": finding.priority_rank,
            "finding_id": finding.id,
            "type": "fix",
            "title": action.summary,
            "addresses": finding.title,
            "priority": action.priority,
            "severity": finding.severity,
            "pillar": finding.pillar,
            "dimension": finding.dimension,
            "effort": action.effort,
            "impact": action.impact,
            "mechanism": action.mechanism,
            "steps": list(action.steps),
            "verification": action.verification,
            "owner": action.owner,
        })
    return plan
