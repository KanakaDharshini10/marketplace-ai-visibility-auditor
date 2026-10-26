"""Finding, evidence and suggested-action models.

Two invariants are enforced here rather than left to reviewer discipline:

* **No finding without evidence.** A :class:`Finding` must carry at least one
  :class:`EvidenceItem`, and every evidence item must name the URL it was
  observed on. Findings that fail this are rejected by the report builder and
  listed in ``diagnostics.rejected_findings`` instead of being emitted.
* **No action without a mechanism.** A :class:`SuggestedAction` must say what
  to change, and carries the mechanism (*why this makes an assistant behave
  differently*) plus a verification step the site owner can run afterwards.
* **No inference presented as evidence.** Every finding separates three things
  that are easy to blur together and expensive to confuse:

  ``observation``
      what was directly measured in the fetched bytes. Countable, re-checkable
      with ``curl``, and free of consequence language.
  ``interpretation``
      what that observation may mean for retrieval, readability or the visitor.
      This is reasoning, and it is labelled as reasoning.
  ``suggested_action``
      what to change.

  The report emits all three as separate fields. ``evidence`` stays the
  handout-required one-line string and is derived from the observation, so the
  quotable summary can never contain a conclusion the audit did not measure.
* **No unverifiable verification.** A :class:`SuggestedAction` declares
  ``verification_type``. ``self_verifiable`` steps can be re-run by this
  auditor or by ``curl``; ``external_validation`` needs a third-party system
  (asking an assistant, a knowledge panel); ``requires_external_data`` needs
  data the audit cannot see (analytics, referrer segmentation). A reader can
  therefore tell an auditor-checkable claim from one that is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# severity
# --------------------------------------------------------------------------

SEVERITIES = ("critical", "high", "medium", "low", "info")

SEVERITY_WEIGHT = {"critical": 100, "high": 60, "medium": 30, "low": 12, "info": 0}

# ---------------------------------------------------------------------------
# corroboration between findings
# ---------------------------------------------------------------------------
#
# Two rules can measure genuinely different things about one page and still be
# fixed by one change. A page delivered as an empty client-rendering shell is a
# statement about *delivery architecture*, read from the response alone; the
# ratio between its rendered and raw word counts is a statement about
# *magnitude*, and needs a browser. Both are real, both are worth reading, and
# neither is a duplicate of the other - but a site owner performs one piece of
# work to answer them, so charging the score twice would say the page is twice
# as bad as it is.
#
# Deleting one is the wrong fix: the reader would lose either the architecture
# or the size of the gap. Instead the *corroborating* finding declares the
# relationship in its own metrics, the report links the two, and the score is
# charged once. Nothing is removed from the report.
#
# The declaration is one key, set by the rule that corroborates another:
#
#     metrics={"corroborates": "CR-JS-RENDERED-SHELL", ...}
#
# It takes effect only when the named rule is *also* present in the same report
# and the two share at least one affected URL. Two findings about different
# pages are two findings.

#: Metrics key a rule sets to name the finding it corroborates.
CORROBORATION = "corroborates"

#: ...and the keys the report writes back, so the relationship is visible in
#: both directions and a consumer can see why a penalty was not charged.
CORROBORATED_BY = "corroborated_by"
SCORING_ROLE = "scoring_role"

#: The value :data:`SCORING_ROLE` carries on a finding whose remediation is
#: already charged to the finding it corroborates.
ROLE_CORROBORATION = "corroboration"

PRIORITIES = ("critical", "high", "medium", "low")

#: The six concerns the marketplace decomposes the problem into: five
#: mechanisms and, last, the outcome those mechanisms exist to serve. Each maps
#: to exactly one specialist skill, which is what keeps the decomposition
#: honest.
PILLARS = {
    "crawl_render": "Crawl & render reachability",
    "machine_readability": "Machine readability & structured data",
    "freshness_corroboration": "Freshness & corroboration",
    "entity": "Entity clarity & disambiguation",
    "engagement": "Engagement & comparison readiness",
    "answerability": "Answerability of buyer questions",
}

#: Which half of the Round-2 problem a pillar serves. Used to prove the report
#: covers both, not just the SEO-shaped half.
PILLAR_DIMENSION = {
    "crawl_render": "discoverability",
    "machine_readability": "discoverability",
    "freshness_corroboration": "discoverability",
    "entity": "discoverability",
    "engagement": "engagement",
    "answerability": "answerability",
}


# ---------------------------------------------------------------------------
# observation hygiene
# ---------------------------------------------------------------------------

#: Language that asserts a *consequence* rather than reporting a measurement.
#:
#: A static, read-only audit can observe what a page contains. It cannot
#: observe that a visitor bounced, that they had nothing to compare, or that
#: anything was above the fold — those require behavioural analytics or a
#: rendered viewport, neither of which is in evidence. Such claims are real
#: reasoning and belong in ``interpretation``; asserting them in ``evidence``
#: is how an inference gets laundered into a fact, so the model rejects it.
UNMEASURED_CONSEQUENCE_PATTERNS = (
    r"\bbounc(?:e|es|ed|ing)\b",
    r"\b(?:the\s+)?visitors?\s+(?:will|has to|have to|must|then|ends? up|gives? up)\b",
    r"\bnothing (?:concrete )?to compare\b",
    r"\bhas nothing\b",
    r"\bforc(?:e|es|ing) the (?:visitor|user|buyer)\b",
    r"\bgoes? (?:back )?(?:elsewhere|to a competitor)\b",
    r"\bloses? the (?:sale|customer|visit)\b",
    r"\babove[- ]the[- ]fold\b",
    r"\bfirst screen\b",
    r"\bhero carousel\b",
    r"\bnewsletter modal\b",
    r"\binterstitial\b",
    r"\binformation journey\b",
    r"\bscan it manually\b",
    r"\bredo the (?:search|work)\b",
    r"\b(?:has|have) to (?:search|hunt|scroll|scan|look|guess)\b",
    r"\bstart the search again\b",
)

_UNMEASURED_RE = [(p, re.compile(p, re.I)) for p in UNMEASURED_CONSEQUENCE_PATTERNS]


def _as_count(value: Any) -> Optional[int]:
    """A non-negative integer count, or ``None``. Tolerates ``8`` / ``8.0`` / ``"8"``."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _sorted_unmeasured_phrases(text: str) -> List[str]:
    """Every unmeasured-consequence phrase present in ``text``, deterministically."""
    if not text:
        return []
    hits = []
    for pattern, compiled in _UNMEASURED_RE:
        match = compiled.search(text)
        if match:
            hits.append(match.group(0).lower())
    return sorted(set(hits))


@dataclass
class EvidenceItem:
    """One observation. Must be traceable back to a fetched artefact."""

    observation: str                 # what was actually seen
    url: str = ""                    # where it was seen
    locator: str = ""                # e.g. "robots.txt line 14", "JSON-LD block 0"
    value: Any = None                # the raw observed value, when quotable
    kind: str = "observation"        # observation | absence | measurement | quote

    def to_dict(self) -> dict:
        data = {"kind": self.kind, "observation": self.observation}
        if self.url:
            data["url"] = self.url
        if self.locator:
            data["locator"] = self.locator
        if self.value is not None:
            data["value"] = self.value
        return data


#: How a verification step can be checked.
#:
#: ``self_verifiable``      re-runnable by this auditor, or by one ``curl``.
#: ``external_validation``  needs a third-party system to answer (asking an
#:                          assistant, checking a knowledge panel). The result
#:                          is real but is *not* something this audit observed.
#: ``requires_external_data`` needs data the audit cannot see at all
#:                          (analytics, referrer segmentation, sales).
VERIFICATION_TYPES = ("self_verifiable", "external_validation", "requires_external_data")

#: Bands over the numeric confidence, highest first. Thresholds are fixed
#: constants rather than anything adaptive, so a given piece of evidence always
#: lands in the same band and two runs can be compared directly.
CONFIDENCE_BANDS = ((0.85, "high"), (0.60, "medium"), (0.0, "low"))

CONFIDENCE_LEVELS = tuple(name for _, name in CONFIDENCE_BANDS)

#: How to describe the basis when a rule declared a scope but no counts.
_SCOPE_BASIS = {
    "template": "template-wide observation",
    "section": "observed across a section of the site",
    "page": "single observation",
}


@dataclass
class SuggestedAction:
    summary: str
    priority: str = "medium"
    mechanism: str = ""              # why this changes assistant behaviour
    steps: List[str] = field(default_factory=list)
    example: str = ""                # concrete snippet the team can paste
    effort: str = "medium"           # low | medium | high
    impact: str = "medium"           # low | medium | high
    verification: str = ""           # how to confirm the fix worked
    verification_type: str = "self_verifiable"   # see VERIFICATION_TYPES
    owner: str = ""                  # who typically does this
    references: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data: Dict[str, Any] = {"summary": self.summary, "priority": self.priority}
        for key in ("mechanism", "example", "verification", "owner"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.verification:
            data["verification_type"] = self.verification_type
        data["effort"] = self.effort
        data["impact"] = self.impact
        if self.steps:
            data["steps"] = list(self.steps)
        if self.references:
            data["references"] = list(self.references)
        return data


@dataclass
class Finding:
    rule_id: str
    title: str
    severity: str
    pillar: str
    evidence: str                                   # one-line, quotable summary
    suggested_action: SuggestedAction
    interpretation: str = ""                        # what it may mean (reasoning)
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    affected_urls: List[str] = field(default_factory=list)
    confidence: float = 0.9                         # 0..1, lowers score impact
    metrics: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    source_skill: str = ""
    id: str = ""                                    # assigned by the report builder
    priority_rank: int = 0

    # -- confidence and sampling -------------------------------------------
    @property
    def confidence_level(self) -> str:
        """``high`` | ``medium`` | ``low``, banded from the numeric confidence.

        A pure threshold over a value that is itself computed deterministically
        from coverage and consistency (:func:`aiva.analysis.confidence_for`).
        Nothing here is estimated or invented: the same evidence always yields
        the same band, and the band exists because "0.63" tells a reader far
        less than "medium" about how much weight to put on the finding.
        """
        value = float(self.confidence)
        if value >= CONFIDENCE_BANDS[0][0]:
            return CONFIDENCE_BANDS[0][1]
        if value >= CONFIDENCE_BANDS[1][0]:
            return CONFIDENCE_BANDS[1][1]
        return CONFIDENCE_BANDS[2][1]

    @property
    def sampling(self) -> Dict[str, Any]:
        """What this finding was measured over, stated rather than implied.

        A rule that fired on 2 of 2 sampled pages and one that fired on 12 of
        12 are different claims, and a reader cannot tell them apart from the
        evidence sentence alone. This exposes the basis as a field so a small
        sample is never presented as a universal fact.
        """
        metrics = self.metrics if isinstance(self.metrics, dict) else {}
        affected = _as_count(metrics.get("affected"))
        sampled = _as_count(metrics.get("sampled"))
        unit = metrics.get("sample_unit") or "sampled page(s)"
        if sampled:
            # `affected` is only stated when the rule actually counted it.
            # Defaulting it to the sample size would turn "1 of 12 pages
            # returned an error" into a reported basis of "12/12", which is
            # the exact overstatement this field exists to prevent.
            if affected is None:
                return {"kind": "sample", "affected": None, "sampled": sampled,
                        "unit": unit, "coverage": None,
                        "basis": f"over {sampled} {unit}"}
            return {"kind": "sample", "affected": affected, "sampled": sampled,
                    "unit": unit,
                    "coverage": round(affected / sampled, 2),
                    "basis": f"{affected}/{sampled} {unit}"}
        # No counts declared. Fall back to the scope the rule *did* declare
        # rather than assuming one page: several rules count in their own
        # units (blocks, images, headings) and describing those as a "single
        # observation" understates them as badly as defaulting `affected` to
        # the sample size overstates the others.
        scope = metrics.get("scope")
        if scope == "site":
            return {"kind": "site_wide", "affected": affected, "sampled": None,
                    "unit": unit, "coverage": None,
                    "basis": "site-wide observation"}
        if affected:
            return {"kind": "count", "affected": affected, "sampled": None,
                    "unit": unit, "coverage": None,
                    "basis": f"{affected} {unit}"}
        if scope in _SCOPE_BASIS:
            return {"kind": "scoped", "affected": None, "sampled": None,
                    "unit": unit, "coverage": None,
                    "basis": _SCOPE_BASIS[scope]}
        return {"kind": "single", "affected": None, "sampled": None,
                "unit": unit, "coverage": None,
                "basis": "single observation"}

    # -- observation / interpretation --------------------------------------
    @property
    def observation(self) -> str:
        """The measured part. Identical to ``evidence`` by construction.

        ``evidence`` is the handout-required one-line string; keeping the two
        the same object rather than two hand-maintained strings is what stops
        them drifting into a summary that claims more than the observation.
        """
        return self.evidence

    @property
    def reasoning(self) -> str:
        """The interpretation. Falls back to the action's mechanism.

        A rule that does not state its own interpretation still has one: the
        action's ``mechanism`` field is exactly *why this observation matters
        for an assistant*. Reusing it keeps every finding three-part without
        inventing a second copy of the same sentence.
        """
        return self.interpretation or self.suggested_action.mechanism

    # -- validation --------------------------------------------------------
    def problems(self) -> List[str]:
        issues: List[str] = []
        # `affected` and `sampled` must count the same population, or the
        # ratio derived from them is meaningless. This is checked rather than
        # clamped: a coverage above 1 is always a denominator bug in the rule,
        # and clamping it to 1.0 would publish a plausible number over a
        # population that was never measured. Observed live at
        # affected=40 / sampled=38 - two observations recorded for some pages,
        # divided by a count of pages.
        metrics = self.metrics if isinstance(self.metrics, dict) else {}
        affected = _as_count(metrics.get("affected"))
        sampled = _as_count(metrics.get("sampled"))
        if affected is not None and sampled and affected > sampled:
            issues.append(
                f"metrics.affected ({affected}) exceeds metrics.sampled ({sampled}): "
                f"the two count different populations, so the sampling ratio would "
                f"be above 1. Count affected items in the same unit as the sample, "
                f"or declare the unit with metrics.sample_unit")
        for phrase in _sorted_unmeasured_phrases(self.evidence):
            issues.append(
                f"evidence summary states an unmeasured consequence ({phrase!r}); "
                "move it to `interpretation`")
        for index, item in enumerate(self.evidence_items):
            for phrase in _sorted_unmeasured_phrases(item.observation):
                issues.append(
                    f"evidence item {index} states an unmeasured consequence "
                    f"({phrase!r}); evidence items record observations only")
        if self.suggested_action and \
                self.suggested_action.verification_type not in VERIFICATION_TYPES:
            issues.append(
                f"unknown verification_type {self.suggested_action.verification_type!r}")
        if self.severity not in SEVERITIES:
            issues.append(f"unknown severity {self.severity!r}")
        if self.pillar not in PILLARS:
            issues.append(f"unknown pillar {self.pillar!r}")
        if not self.title.strip():
            issues.append("empty title")
        if not self.evidence.strip():
            issues.append("empty evidence summary")
        if not self.evidence_items:
            issues.append("no evidence items (a finding must cite an observation)")
        else:
            for index, item in enumerate(self.evidence_items):
                if not item.observation.strip():
                    issues.append(f"evidence item {index} has no observation")
                if not item.url and item.kind != "measurement":
                    issues.append(f"evidence item {index} has no source URL")
        if not self.suggested_action or not self.suggested_action.summary.strip():
            issues.append("no suggested action")
        if self.suggested_action and self.suggested_action.priority not in PRIORITIES:
            issues.append(f"unknown action priority {self.suggested_action.priority!r}")
        return issues

    @property
    def is_valid(self) -> bool:
        return not self.problems()

    @property
    def dimension(self) -> str:
        return PILLAR_DIMENSION.get(self.pillar, "discoverability")

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "pillar": self.pillar,
            "pillar_label": PILLARS.get(self.pillar, self.pillar),
            "dimension": self.dimension,
            "confidence": round(float(self.confidence), 2),
            "confidence_level": self.confidence_level,
            "sampling": self.sampling,
            "source_skill": self.source_skill,
            # Handout-required shape: a single quotable evidence string.
            "evidence": self.evidence,
            # The three-part split, emitted explicitly so a reader never has to
            # guess which sentence was measured and which one was reasoned.
            "observation": self.observation,
            "interpretation": self.reasoning,
            # Structured superset: every underlying observation.
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "affected_urls": list(self.affected_urls)[:25],
            "affected_url_count": len(self.affected_urls),
            "metrics": self.metrics,
            "tags": list(self.tags),
            "suggested_action": self.suggested_action.to_dict(),
            "priority_rank": self.priority_rank,
        }


def finding_from_dict(data: dict) -> Finding:
    """Rebuild a Finding from its serialised form (used by compose_report.py)."""
    raw_action = data.get("suggested_action") or {}
    if isinstance(raw_action, str):
        raw_action = {"summary": raw_action, "priority": "medium"}
    action = SuggestedAction(
        summary=raw_action.get("summary", ""),
        priority=raw_action.get("priority", "medium"),
        mechanism=raw_action.get("mechanism", ""),
        steps=list(raw_action.get("steps", [])),
        example=raw_action.get("example", ""),
        effort=raw_action.get("effort", "medium"),
        impact=raw_action.get("impact", "medium"),
        verification=raw_action.get("verification", ""),
        verification_type=raw_action.get("verification_type", "self_verifiable"),
        owner=raw_action.get("owner", ""),
        references=list(raw_action.get("references", [])),
    )
    raw_items = data.get("evidence_items") or []
    items = [
        EvidenceItem(observation=item.get("observation", ""), url=item.get("url", ""),
                     locator=item.get("locator", ""), value=item.get("value"),
                     kind=item.get("kind", "observation"))
        for item in raw_items if isinstance(item, dict)
    ]
    return Finding(
        rule_id=data.get("rule_id", data.get("id", "")),
        title=data.get("title", ""),
        severity=data.get("severity", "medium"),
        pillar=data.get("pillar", "crawl_render"),
        evidence=data.get("evidence", ""),
        suggested_action=action,
        interpretation=data.get("interpretation", ""),
        evidence_items=items,
        affected_urls=list(data.get("affected_urls", [])),
        confidence=float(data.get("confidence", 0.9)),
        metrics=dict(data.get("metrics", {})),
        tags=list(data.get("tags", [])),
        source_skill=data.get("source_skill", ""),
    )


def make_finding(rule_id: str, title: str, severity: str, pillar: str, *,
                 evidence: str, action: SuggestedAction,
                 items: Optional[List[EvidenceItem]] = None,
                 urls: Optional[List[str]] = None,
                 confidence: float = 0.9,
                 metrics: Optional[Dict[str, Any]] = None,
                 tags: Optional[List[str]] = None,
                 interpretation: str = "") -> Finding:
    """Terse constructor so analyzer code stays readable."""
    return Finding(
        rule_id=rule_id, title=title, severity=severity, pillar=pillar,
        evidence=evidence, suggested_action=action, interpretation=interpretation,
        evidence_items=items or [], affected_urls=urls or [],
        confidence=confidence, metrics=metrics or {}, tags=tags or [],
    )
