"""Assemble, validate and project the single audit report.

The entrypoint skill emits exactly one report. This module owns its shape, so
there is one place where the handout's required floor is guaranteed and one
place where the extra fields live.

Three projections are available:

``full``     the default - floor plus structured evidence, scores, coverage,
             prioritised actions and proactive recommendations.
``handout``  exactly the fields the Round 3 brief lists, nothing else.
``flat``     a minimal variant with ``evidence`` as a list of strings and
             ``suggested_action`` as a single string, for consumers that want
             the flattest possible shape.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from . import evidence as ev
from . import analysis, jsonschema_lite, paths, prioritize, scoring, util
from .config import AuditConfig
from .findings import (CORROBORATED_BY, CORROBORATION, ROLE_CORROBORATION,
                       SCORING_ROLE, SEVERITIES, Finding)
from .answerability import build_matrix
from .recommend import build_opportunities
from .version import TOOL_NAME, __version__

SCHEMA_FILE = "audit-report.schema.json"


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

def observed_contexts(bundle: dict) -> List[dict]:
    """The site shapes the sampled evidence supports, not only the winner.

    `site_kind` reports one shape because an expectation has to be applied or
    not applied - there is no half-applying a return-window check. But a large
    host is routinely several things at once: a newsroom, a storefront, a
    support section and an investor page share one domain, and reporting only
    "publisher (low confidence)" hides that commerce was observed too.

    The scores behind that decision are already computed by
    :func:`aiva.semantics.site_context`; this reads them back so the coverage
    block can show the reader what else the sample contained. It is additive:
    no expectation, gate or score consults it, and `site_kind` is unchanged.
    """
    try:
        from . import semantics
        context = semantics.site_context(bundle)
    except Exception:                                       # pragma: no cover
        return []
    scores = context.get("site_kind_scores") or {}
    primary = context.get("site_kind")
    ranked = sorted(((int(score), str(kind)) for kind, score in scores.items() if score),
                    key=lambda pair: (-pair[0], pair[1]))
    # `mixed` and `unknown` are verdicts rather than scored kinds, so on such a
    # site no entry is marked primary and the list *is* the composition - which
    # is the useful reading: commerce was observed even though the headline
    # says mixed.
    return [{"context": kind, "evidence_score": score, "primary": kind == primary}
            for score, kind in ranked[:6]]


def link_corroborating(findings: List[Finding]) -> int:
    """Link findings that measure one condition twice, and charge the score once.

    Two rules may measure genuinely different things about the same page - the
    delivery architecture and the size of what it withholds - and still be
    answered by one piece of work. Both belong in the report: deleting either
    costs the reader the architecture or the magnitude. What must not happen is
    the score being charged twice for one remediation.

    A rule declares the relationship itself, in its own metrics
    (:data:`aiva.findings.CORROBORATION`). It takes effect only when the named
    rule is also present *and* the two share at least one affected URL - two
    findings about different pages are two findings, and this never silently
    collapses them.

    Mutates the findings in place, writing the relationship in both directions,
    and returns how many links were made.
    """
    by_rule = {finding.rule_id: finding for finding in findings}
    linked = 0
    for finding in findings:
        metrics = finding.metrics or {}
        target_id = metrics.get(CORROBORATION)
        primary = by_rule.get(str(target_id or ""))
        if primary is None or primary is finding:
            continue
        shared = set(finding.affected_urls) & set(primary.affected_urls)
        if not shared:
            # Same rule pair, different pages: two independent observations.
            continue
        finding.metrics = dict(metrics, **{
            SCORING_ROLE: ROLE_CORROBORATION,
            "corroborated_url_count": len(shared),
        })
        primary.metrics = dict(primary.metrics or {}, **{
            CORROBORATED_BY: finding.rule_id,
            "corroborating_url_count": len(shared),
        })
        linked += 1
    return linked


def _summary_counts(findings: Iterable[Finding]) -> Dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    total = 0
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
        total += 1
    result = {"total_findings": total}
    result.update(counts)
    return result


def _readable_pages(bundle: dict) -> list:
    """Pages the crawl actually parsed. The basis of every content claim."""
    return [p for p in ev.pages(bundle)
            if not p.get("fetch_failed") and not p.get("non_html")]


#: Statuses that mean a request was refused rather than answered.
#: How each recommendation class is named to a reader.
GROUNDING_LABEL = {
    "evidence_backed": "evidence-backed",
    "site_personalised": "site-personalised",
    "generic": "generic best practice",
}

_REFUSAL_STATUSES = frozenset({401, 403, 407, 408, 429, 451, 500, 502, 503, 504})


def _no_content_reason(bundle: dict) -> str:
    """Why the crawl came away with nothing readable, in the site's own terms.

    A report that read nothing must say *why* it read nothing, because the
    four reasons call for four different responses from the reader: the site
    disallowed us, something in front of the site refused us, the origin never
    answered, or every page errored. Collapsing them into one number is how a
    run that observed nothing ends up sounding like a verdict.
    """
    # A wall is checked first because it explains everything downstream of it,
    # robots.txt included: reporting "robots.txt could not be read" about a run
    # whose every request was refused names the symptom and hides the cause.
    access = bundle.get("access", {}) or {}
    if access.get("wall_suspected"):
        statuses = ", ".join(f"HTTP {code}"
                             for code in (access.get("refusal_statuses") or {}))
        return (f"bot mitigation refused this audit before any page was served "
                f"({statuses or 'refused'})")
    robots = bundle.get("robots", {}) or {}
    if robots.get("unreachable"):
        return ("robots.txt could not be read, so RFC 9309 requires a compliant crawler "
                "to treat the whole site as disallowed")
    blocked = len(bundle.get("blocked_by_robots", []) or [])
    errors = bundle.get("fetch_errors", []) or []
    # include_errors: a refused request is *precisely* a failed fetch, and it
    # is the one this reason exists to name.
    refusals = [p for p in ev.pages(bundle, include_errors=True)
                if p.get("status") in _REFUSAL_STATUSES]
    if refusals:
        statuses = sorted({str(p.get("status")) for p in refusals})
        return (f"every request was refused before the page was served "
                f"(HTTP {', '.join(statuses)}) - a bot wall, WAF or proxy stands "
                f"between this audit and the origin")
    if blocked and not errors:
        return f"robots.txt disallowed all {blocked} candidate URL(s) for this crawler"
    if errors:
        return f"{len(errors)} request(s) failed before the origin answered"
    utility = ev.pages(bundle, include_aliases=True, include_utility=True)
    if utility:
        kinds = sorted({p.get("page_type") or "other" for p in utility})
        return (f"the {len(utility)} page(s) read were {', '.join(kinds)} endpoints - not "
                f"content documents the site publishes to be quoted")
    return "the crawl obtained no parseable HTML document"


def _coverage_state(bundle: dict) -> str:
    """``content`` | ``transport_only`` - what class of claim this report can make."""
    return "content" if _readable_pages(bundle) else "transport_only"


# ---------------------------------------------------------------------------
# specialist coverage
# ---------------------------------------------------------------------------
#
# Two independent things bound what a report can claim. ``coverage_state`` is
# about the *evidence*: was any page read. Specialist coverage is about the
# *analysis*: did every specialist that should have read that evidence finish.
# They are reported separately because they fail separately - a crawl that
# read forty pages and a specialist that crashed on the first of them is a
# content report with one pillar missing, not a transport-only one.

SPECIALIST_COVERAGE_COMPLETE = "complete"
SPECIALIST_COVERAGE_PARTIAL = "partial"
SPECIALIST_COVERAGE_UNRECORDED = "unrecorded"


def _run_failed(run: dict) -> bool:
    status = run.get("status")
    if status is not None:
        return status != "ok"
    return not run.get("ok", True)


def _pillar_of(skill_id: str) -> str:
    """The pillar the manifest assigns to a specialist, or ``""``."""
    try:
        for entry in paths.specialist_skills():
            if entry.get("id") == skill_id:
                return str(entry.get("pillar") or "")
    except (OSError, ValueError):
        pass
    return ""


def _failed_runs(skill_runs: Optional[List[dict]]) -> List[dict]:
    """Every specialist run that did not finish, with its pillar resolved."""
    failed = []
    for run in skill_runs or []:
        if not _run_failed(run):
            continue
        failed.append({"skill": str(run.get("skill") or ""),
                       "pillar": str(run.get("pillar") or _pillar_of(str(run.get("skill") or ""))),
                       "error": str(run.get("error") or "failed before producing findings")})
    return failed


def _specialist_coverage(skill_runs: Optional[List[dict]]) -> dict:
    """What the report can say about which specialists analysed the evidence."""
    runs = list(skill_runs or [])
    failed = _failed_runs(runs)
    if not runs:
        state = SPECIALIST_COVERAGE_UNRECORDED
    elif failed:
        state = SPECIALIST_COVERAGE_PARTIAL
    else:
        state = SPECIALIST_COVERAGE_COMPLETE
    return {
        "state": state,
        "expected": len(runs),
        "completed": [str(r.get("skill") or "") for r in runs if not _run_failed(r)],
        "failed": failed,
        "unmeasured_pillars": sorted({f["pillar"] for f in failed if f["pillar"]}),
    }


def _specialist_caveat(skill_runs: Optional[List[dict]]) -> str:
    """One sentence naming what a failed specialist leaves unmeasured, or ``""``."""
    failed = _failed_runs(skill_runs)
    if not failed:
        return ""
    parts = []
    for item in failed:
        pillar = f"the {item['pillar']} pillar" if item["pillar"] else "its pillar"
        parts.append(f"{item['skill']} failed before producing findings ({item['error']}), "
                     f"so {pillar} is unmeasured")
    return "Specialist coverage is incomplete: " + "; ".join(parts) + "."


def _score_basis(bundle: dict, skill_runs: Optional[List[dict]] = None) -> str:
    """One sentence saying what the overall score was computed from.

    `transport_only` already says the crawl read nothing; this says what
    follows for the number beside it, because a score is the field a reader
    quotes and the one most likely to be quoted without its context. A failed
    specialist is named here too: its pillar is excluded from the number, and
    a reader comparing two runs must be able to see that the model shrank.
    """
    caveat = _specialist_caveat(skill_runs)
    if _readable_pages(bundle):
        sampled = len(_readable_pages(bundle))
        cap = (bundle.get("config", {}) or {}).get("max_pages")
        advertised = sum(s.get("url_count", 0) for s in bundle.get("sitemaps", []) or [])
        aside = len([p for p in ev.pages(bundle, include_aliases=True, include_utility=True)
                     if p not in _readable_pages(bundle)])
        basis = (f"content and transport evidence from {sampled} parsed content page(s)")
        if aside:
            basis += (f" ({aside} further fetched page(s) - search, account or "
                      f"navigation/reference endpoints - carry no content claim)")
        if advertised and advertised > sampled:
            basis += (f", sampled from {advertised} URL(s) the site advertises "
                      f"(page cap {cap})")
        basis += "."
    else:
        basis = ("audit reachability only: no page was parsed, so this score reflects "
                 "whether this audit could reach the site and makes no assessment of "
                 "its content quality.")
    if caveat:
        basis += " " + caveat + " Unmeasured pillars are excluded from the score, not " \
                 "assumed sound."
    return basis


def _headline(overall: dict, counts: Dict[str, int], bundle: dict,
              skill_runs: Optional[List[dict]] = None) -> str:
    host = ev.site_host(bundle) or bundle.get("site", {}).get("input", "the site")
    blocking = counts.get("critical", 0)
    caveat = _specialist_caveat(skill_runs)

    # A headline is the one sentence most readers will act on, so it must never
    # describe content the crawl never saw. "example.com is reachable but 1
    # high-severity gap(s)..." was printed over `pages_fetched: 0`; the band cap
    # added in 1.5.1 guarded the label but not this sentence.
    if not _readable_pages(bundle):
        reason = _no_content_reason(bundle)
        if blocking:
            return (f"No page of {host} could be read: {reason}. "
                    f"{blocking} critical finding(s) describe that barrier; nothing in this "
                    f"report is a claim about the site's content.")
        return (f"No page of {host} could be read: {reason}. This run reports transport "
                f"evidence only and makes no claim about the site's content, engagement "
                f"or readiness.")

    if blocking:
        # Framed around what the audit measured - conditions a crawler must
        # clear - not around a claim that any assistant failed. The audit is a
        # crawler and reads what it can reach; it queries no assistant, so a
        # blanket claim about how assistants behave is an inference the headline
        # no longer states as fact.
        headline = (f"{host} has {blocking} critical AI-visibility blocker(s): the pages "
                    f"sampled do not meet conditions a crawler must clear to reach, read or "
                    f"attribute the content.")
    elif counts.get("high", 0):
        headline = (f"{host} is reachable, but {counts['high']} high-severity gap(s) weaken "
                    f"how readily its facts can be quoted from the pages sampled.")
    elif counts.get("total_findings", 0):
        headline = (f"{host} is broadly machine-readable; the remaining findings are "
                    f"refinements rather than blockers.")
    elif caveat:
        # "No defects" is a claim about every pillar. With one specialist
        # missing it is only a claim about the pillars that ran.
        headline = (f"No defects were detected on the pages sampled from {host} by the "
                    f"specialists that completed.")
    else:
        headline = (f"No defects were detected on the pages sampled from {host}; see the "
                    f"proactive recommendations for how to extend its lead.")
    return headline + (" " + caveat if caveat else "")


#: Pillars whose rules read page content. With no readable page in the bundle
#: none of them was exercised, so none of them has been measured.
_CONTENT_PILLARS = ("machine_readability", "freshness_corroboration",
                    "entity", "engagement", "answerability")


def _unmeasured_reasons(bundle: dict, matrix: Optional[dict] = None,
                        skill_runs: Optional[List[dict]] = None) -> Dict[str, str]:
    """Pillars that were not measured, each with the reason, in precedence order.

    Only ``crawl_render`` can be assessed from transport evidence alone
    (robots.txt, host probes, status codes). Everything else needs a parsed
    document, so when the crawl obtained none, those pillars were not measured
    - a different state from "measured and found clean", and one the score
    must not silently present as the latter.

    ``answerability`` has a second, independent way of being unmeasured: the
    engine only generates a question when the site's own content supports one,
    so on a documentation or brochure site it produces none at all and reports
    ``answerability_score: None``. Scoring that pillar 100 handed such a site
    a free 15% of the model for a check that never ran, so the matrix's own
    "I could not evaluate this" signal is consumed here.

    A specialist that failed is the third way. Its pillar has evidence behind
    it that nothing analysed, which is again not "measured and found clean";
    scoring it 100 would reward the crash.
    """
    reasons: Dict[str, str] = {}
    readable = [p for p in ev.pages(bundle)
                if not p.get("fetch_failed") and not p.get("non_html")]
    if not readable:
        for pillar in _CONTENT_PILLARS:
            reasons[pillar] = "no page was parsed, so no content evidence exists for it"
    elif matrix is not None and not matrix.get("total_questions"):
        reasons["answerability"] = ("the site's content supported no question, so the "
                                    "check did not run")
    for item in _failed_runs(skill_runs):
        if item["pillar"] and item["pillar"] not in reasons:
            reasons[item["pillar"]] = (f"specialist {item['skill']} failed before producing "
                                       f"findings ({item['error']})")
    return reasons


def _unmeasured_pillars(bundle: dict, matrix: Optional[dict] = None,
                        skill_runs: Optional[List[dict]] = None) -> set:
    """Pillars the report must not score. See :func:`_unmeasured_reasons`."""
    return set(_unmeasured_reasons(bundle, matrix, skill_runs))


def _semantics_summary(bundle: dict) -> dict:
    """The applicability decisions, for the report (see :mod:`aiva.semantics`)."""
    if not _readable_pages(bundle):
        return {"site_kind": "unknown", "site_kind_confidence": "low",
                "site_kind_evidence": ["no page was read"], "expectations": []}
    try:
        from . import semantics
        return semantics.applicability_summary(bundle)
    except Exception as exc:  # noqa: BLE001 - a summary must never break a report
        return {"site_kind": "unknown", "error": f"{type(exc).__name__}: {exc}"}


def _coverage(bundle: dict) -> dict:
    by_type: Dict[str, int] = {}
    for page in bundle.get("pages", []):
        page_type = page.get("page_type") or ("error" if page.get("fetch_failed") else "unknown")
        by_type[page_type] = by_type.get(page_type, 0) + 1
    sitemaps = bundle.get("sitemaps", [])
    # What the content claims were computed over, stated beside the raw count.
    # A search results page, an account form and a second address of the home
    # page are fetched and typed, but they are not documents the site
    # publishes to be quoted, so every "N of M pages" in this report counts
    # only the content documents - and the reader can see both numbers.
    content = ev.pages(bundle)
    set_aside = [p for p in ev.pages(bundle, include_aliases=True, include_utility=True)
                 if p not in content]
    aside_by_type: Dict[str, int] = {}
    for page in set_aside:
        key = page.get("page_type") or "other"
        aside_by_type[key] = aside_by_type.get(key, 0) + 1
    summary = _semantics_summary(bundle)
    return {
        "pages_fetched": len(bundle.get("pages", [])),
        "pages_by_type": by_type,
        "content_pages": len(content),
        "non_content_pages_by_type": aside_by_type,
        "site_kind": summary.get("site_kind"),
        "site_kind_confidence": summary.get("site_kind_confidence"),
        # What else the sample contained. One host is often several things, and
        # a low-confidence primary shape is more honest read beside the
        # alternatives than alone. Additive: nothing consults this.
        "observed_contexts": observed_contexts(bundle),
        "product_subtypes": summary.get("product_subtypes") or {},
        "listing_subtypes": summary.get("listing_subtypes") or {},
        "expectations_not_applied": [
            {"expectation": d["expectation"], "applied_to": d["applied_to"],
             "product_pages": d["product_pages"], "not_applied": d["not_applied"]}
            for d in (summary.get("expectations") or []) if d.get("not_applied")],
        "sitemaps_found": len([s for s in sitemaps if s.get("kind") in ("index", "urlset")]),
        "sitemap_urls_seen": sum(s.get("url_count", 0) for s in sitemaps),
        "robots_txt_present": bundle.get("robots", {}).get("exists", False),
        "ai_discovery_surfaces": sorted(
            name for name, surface in
            (bundle.get("well_known", {}).get("ai_surfaces", {}) or {}).items()
            if surface.get("present")),
        # The market this report is about, and what was left out to keep it
        # that way. A reader must never have to infer from the URLs that the
        # ratios describe one country rather than the whole site.
        "locale_scope": bundle.get("site", {}).get("locale_scope"),
        "out_of_locale_candidates": bundle.get("site", {}).get(
            "out_of_locale_candidates", 0),
        "declared_anchors_checked": len(bundle.get("declared_anchors", [])),
        "headless_render_used": bool(bundle.get("render", {}).get("available")),
        # What the optional browser pass did, so a reader can tell an absence
        # this audit looked for in two states from one it looked for in one.
        # Present on every report: when rendering did not run it says so.
        "rendered_evidence": analysis.render_coverage(bundle),
        "blocked_by_robots": len(bundle.get("blocked_by_robots", [])),
        "fetch_errors": len(bundle.get("fetch_errors", [])),
        "limits": {
            "max_pages": bundle.get("config", {}).get("max_pages"),
            "time_budget_s": bundle.get("config", {}).get("total_time_budget_s"),
        },
        # Where the wall clock went. Two runs that read nothing can differ by
        # minutes, and the difference is the finding: an origin that answered
        # quickly and refused is not an origin that never answered.
        "transport": (bundle.get("stats", {}) or {}).get("transport", {}),
        "elapsed_s": (bundle.get("stats", {}) or {}).get("elapsed_s"),
        "requests": (bundle.get("stats", {}) or {}).get("requests"),
        "notes": bundle.get("notes", []),
    }


#: Page types a finding can claim in prose. Kept to the classifier's own
#: vocabulary so a claim and an observation are always in the same terms.
_CLAIMABLE_PAGE_TYPES = ("product", "category", "policy", "faq", "article",
                         "home", "about", "contact", "promotional", "program",
                         "support")

#: Words a rule uses for a page type that the classifier spells differently.
_PAGE_TYPE_SYNONYMS = {"listing": "category", "collection": "category",
                       "pdp": "product"}

#: "sampled product page(s)" -> {"product"}. Read from `metrics.sample_unit`
#: and nowhere else, deliberately: the unit is the machine-readable statement
#: of what population a ratio was computed over, so it is the one place a rule
#: says which page type it is talking about without ambiguity. Prose is not
#: parsed for this - "though a contact page exists" and "no product page was
#: observed" are asides, not claims about a sampled population, and treating
#: them as claims produced false rejections against rules that were correct.
_PAGE_TYPE_CLAIM_RE = re.compile(
    r"\b(" + "|".join(tuple(_CLAIMABLE_PAGE_TYPES) + tuple(_PAGE_TYPE_SYNONYMS))
    + r")\b", re.I)


def _page_type_index(bundle: dict) -> Dict[str, str]:
    """Every crawled URL and the type the crawl actually classified it as."""
    index: Dict[str, str] = {}
    for page in ev.pages(bundle, include_errors=True, include_aliases=True,
                         include_utility=True):
        page_type = page.get("page_type") or ""
        for key in (page.get("url"), page.get("final_url")):
            if key:
                index[key] = page_type
    index.update({url: page_type
                  for url, page_type in (bundle.get("page_types") or {}).items()})
    return index


def _claimed_page_types(finding: Finding) -> set:
    """Every page type this finding tells the reader it is about.

    A set, not a single value: plenty of rules legitimately speak about more
    than one type at once ("no BreadcrumbList on product or category pages"),
    and reading only the first word turned those into false rejections. What
    must not happen is citing a type the claim never mentions at all.
    """
    unit = str((finding.metrics or {}).get("sample_unit") or "")
    if "page" not in unit.lower():
        return set()
    found = {match.group(1).lower() for match in _PAGE_TYPE_CLAIM_RE.finditer(unit)}
    return {_PAGE_TYPE_SYNONYMS.get(word, word) for word in found}


def _page_type_problems(finding: Finding, page_types: Dict[str, str]) -> List[str]:
    """Refuse a finding whose cited URLs are not the page type it claims.

    Observed on a live audit: a country front door was classified `product` by
    the content-signal branch, counted among "16 identified product pages", and
    then cited as *the* product page carrying no Product schema. The claim and
    the citation disagreed, and nothing in the pipeline compared them.

    Only URLs the crawl classified are checked, so a finding citing robots.txt,
    a sitemap or an off-site anchor is unaffected. A claim about `home` pages is
    likewise exempt from the reverse direction - a home page is legitimately
    cited by site-wide rules.
    """
    claimed = _claimed_page_types(finding)
    if not claimed or claimed == {"home"}:
        return []
    # No blanket exemption for the home page: "1 of 16 identified product
    # page(s) contain no Product node", citing a country front door, is the
    # exact claim this check exists to refuse.
    cited = [item.url for item in finding.evidence_items if item.url]
    mismatched = sorted({url for url in cited
                         if url in page_types and page_types[url] not in claimed})
    if not mismatched:
        return []
    detail = ", ".join(f"{url} is {page_types[url] or 'unclassified'}"
                       for url in mismatched[:3])
    return [f"finding claims {'/'.join(sorted(claimed))} page(s) but cites "
            f"{len(mismatched)} URL(s) of another type ({detail}); cite pages of "
            f"the type the claim names"]


def build_report(bundle: dict, findings: List[Finding], config: AuditConfig,
                 *, skill_runs: Optional[List[dict]] = None) -> dict:
    """Compose the single audit report from shared evidence + findings."""
    accepted: List[Finding] = []
    rejected: List[dict] = []
    seen_rules: Dict[str, Finding] = {}

    page_types = _page_type_index(bundle)
    for finding in findings:
        issues = finding.problems() + _page_type_problems(finding, page_types)
        if issues:
            rejected.append({
                "rule_id": finding.rule_id,
                "title": finding.title,
                "source_skill": finding.source_skill,
                "reasons": issues,
            })
            continue
        # One finding per rule: analyzers aggregate, they do not spam per URL.
        existing = seen_rules.get(finding.rule_id)
        if existing is not None:
            existing.affected_urls = util.dedupe(existing.affected_urls + finding.affected_urls)
            existing.evidence_items.extend(finding.evidence_items)
            continue
        seen_rules[finding.rule_id] = finding
        accepted.append(finding)

    link_corroborating(accepted)
    ordered = prioritize.prioritize(accepted)
    for index, finding in enumerate(ordered, start=1):
        finding.id = f"F-{index:03d}"

    counts = _summary_counts(ordered)
    # Built once: the scorer needs it to know whether answerability could be
    # evaluated at all, and the report embeds the same object.
    answerability_matrix = build_matrix(bundle)
    unmeasured = _unmeasured_reasons(bundle, answerability_matrix, skill_runs)
    pillars = scoring.pillar_scores(ordered, set(unmeasured))
    for pillar, reason in unmeasured.items():
        if pillar in pillars:
            pillars[pillar]["unmeasured_reason"] = reason
    overall = scoring.overall(pillars)
    opportunities = build_opportunities(bundle, ordered)
    specialists = _specialist_coverage(skill_runs)

    # Serialise once, and remove repeated evidence deterministically: the
    # first occurrence of each observation and each URL is kept, in order,
    # and the count removed is reported rather than hidden.
    serialised = [finding.to_dict() for finding in ordered]
    duplicates_removed = sum(_dedupe_serialised(item) for item in serialised)
    # What the semantic layer decided about this site, so the reader can see
    # which expectations were applied, to which pages, and why the rest were
    # set aside. Computed here from the same functions the specialists use.
    semantics_summary = _semantics_summary(bundle)

    by_pillar: Dict[str, int] = {}
    by_dimension = {"discoverability": 0, "engagement": 0, "answerability": 0}
    for finding in ordered:
        by_pillar[finding.pillar] = by_pillar.get(finding.pillar, 0) + 1
        by_dimension[finding.dimension] = by_dimension.get(finding.dimension, 0) + 1

    site_block = bundle.get("site", {})
    report: Dict[str, Any] = {
        # ---- handout floor ----------------------------------------------
        "site": site_block.get("host") or site_block.get("input", ""),
        "audited_at": util.iso_now(),
        "summary": {
            "total_findings": counts["total_findings"],
            "critical": counts["critical"],
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "info": counts["info"],
            "overall_score": overall["score"],
            "readiness_band": overall["band"],
            "discoverability_score": overall["discoverability_score"],
            "engagement_score": overall["engagement_score"],
            "by_pillar": by_pillar,
            "by_dimension": by_dimension,
            # `content` when at least one page was parsed; `transport_only`
            # when the report can speak about reachability and nothing else.
            # Machine-readable counterpart to the headline, so a downstream
            # consumer never has to infer coverage from a score.
            "coverage_state": _coverage_state(bundle),
            # Whether every specialist finished. `partial` means at least one
            # pillar has evidence that nothing analysed; it is reported as
            # unmeasured, never as clean, and the failure is named in
            # `coverage.specialists` and `diagnostics.skill_runs`.
            "specialist_coverage": specialists["state"],
            # What the number is a number *about*. A score computed with no
            # content evidence measures whether this audit could reach the
            # site, and reading it as a verdict on the site's content is the
            # mistake the state exists to prevent.
            "score_basis": _score_basis(bundle, skill_runs),
            "headline": _headline(overall, counts, bundle, skill_runs),
        },
        "findings": serialised,
        # ---- superset ----------------------------------------------------
        "site_url": site_block.get("home_url", ""),
        "report_version": "1.0",
        "generator": {
            "tool": TOOL_NAME,
            "version": __version__,
            "mode": "read-only audit; recommendations only; no site modification",
            "entrypoint_skill": "marketplace-ai-visibility-audit",
            "specialist_skills": [run["skill"] for run in (skill_runs or [])],
        },
        "scores": {"overall": overall, "pillars": pillars},
        "prioritized_actions": prioritize.action_plan(ordered, limit=15),
        "proactive_recommendations": opportunities,
        "answerability": answerability_matrix,
        "coverage": dict(_coverage(bundle), specialists=specialists),
        "evidence_manifest": {
            "started_at": bundle.get("started_at"),
            "finished_at": bundle.get("finished_at"),
            "stats": bundle.get("stats", {}),
            "robots_url": bundle.get("robots", {}).get("url"),
            "pages": [
                {"url": page.get("url"), "type": page.get("page_type"),
                 "status": page.get("status"), "why_fetched": page.get("fetch_reason", ""),
                 # Why this *type*. A page-type mistake is the one error that
                 # propagates into every ratio in the report, and it is the one
                 # a reader could not previously check.
                 "why_type": _why_type(page)}
                for page in bundle.get("pages", [])
            ],
        },
        "diagnostics": {
            "skill_runs": skill_runs or [],
            "rejected_findings": rejected,
            "rejected_finding_count": len(rejected),
            "evidence_reuse_ratio": _reuse_ratio(bundle, skill_runs),
            "evidence_reuse": _evidence_reuse(bundle, skill_runs),
            "fetches_avoided": _fetches_avoided(bundle),
            "duplicate_evidence_entries_removed": duplicates_removed,
            "semantics": semantics_summary,
            "duplicate_urls_collapsed":
                bundle.get("stats", {}).get("duplicate_urls_collapsed", 0),
            "audit_notes": bundle.get("notes", []),
            "fetch_errors": bundle.get("fetch_errors", []),
            "blocked_by_robots": bundle.get("blocked_by_robots", []),
        },
    }
    return report


def _why_type(page: dict) -> str:
    """One line saying how this page's type was decided.

    Reads what the collector recorded; it never re-decides, because a second
    opinion in the report is how the report comes to contradict the bundle it
    was built from.
    """
    evidence = page.get("page_type_evidence") or {}
    reason = str(evidence.get("decided_by") or "")
    if not reason:
        return ""
    for label, key in (("anchored on", "anchors"),
                       ("corroborated by", "corroborating"),
                       ("presents a set", "plural")):
        values = evidence.get(key) or []
        if values:
            reason += f"; {label}: " + ", ".join(str(v) for v in values[:4])
    return reason


def _fetches_avoided(bundle: dict) -> int:
    """Requests the transport cache did not have to make.

    Two sources: a URL asked for twice and served from the cache, and a URL
    advertised by more than one discovery channel (navigation and sitemap) that
    was collapsed to a single candidate.
    """
    stats = bundle.get("stats", {})
    return int(stats.get("cache_reuses", 0) or 0) + \
        int(stats.get("duplicate_urls_collapsed", 0) or 0)


def _transport_cache_hit_ratio(bundle: dict) -> float:
    """Share of URL lookups answered without a network request.

    This is what an earlier version published as the "evidence reuse ratio".
    On a real crawl it is close to zero by design - every URL is fetched
    once - so it measured the transport cache, not the reuse of shared
    evidence, and a reader took ~0.01 to mean the specialists were not
    sharing. It is kept, under its own name.
    """
    requests = int(bundle.get("stats", {}).get("requests", 0) or 0)
    avoided = _fetches_avoided(bundle)
    if requests + avoided == 0:
        return 0.0
    return round(avoided / float(requests + avoided), 3)


def _evidence_reuse(bundle: dict, skill_runs: Optional[List[dict]]) -> dict:
    """How the one crawl was shared, stated in requests.

    The architecture's claim is that evidence is gathered once and every
    specialist reads it. The measure of that claim is the requests *not*
    made: ``N`` specialists consumed a bundle of ``R`` requests, where each
    crawling for itself would have made ``N x R``. The ratio is the share of
    that hypothetical total the shared bundle avoided - deterministic, and
    computed from the run's own numbers. The transport cache's hit ratio is
    reported beside it under its own name.
    """
    requests = int(bundle.get("stats", {}).get("requests", 0) or 0)
    runs = [run for run in (skill_runs or []) if not _run_failed(run)]
    consumers = len(runs)
    served = consumers * requests
    avoided = max(0, served - requests) if consumers else 0
    ratio = round(avoided / float(served), 3) if served else 0.0
    return {
        "network_requests": requests,
        "specialists_served_from_the_bundle": consumers,
        "specialist_network_requests": 0,
        "requests_if_each_specialist_had_crawled": served,
        "requests_avoided_by_sharing": avoided,
        "shared_evidence_reuse_ratio": ratio,
        "transport_cache_hit_ratio": _transport_cache_hit_ratio(bundle),
        "cache_reuses": int(bundle.get("stats", {}).get("cache_reuses", 0) or 0),
        "duplicate_urls_collapsed": int(
            bundle.get("stats", {}).get("duplicate_urls_collapsed", 0) or 0),
        "definition": ("shared_evidence_reuse_ratio = 1 - R / (N x R) for N specialists that "
                       "completed over a bundle of R network requests; "
                       "transport_cache_hit_ratio = (cache reuses + duplicate URLs collapsed) "
                       "/ (requests + those), the fetch-layer measure an earlier version "
                       "published as the evidence reuse ratio."),
    }


def _reuse_ratio(bundle: dict, skill_runs: Optional[List[dict]] = None) -> float:
    """The shared-evidence reuse ratio (see :func:`_evidence_reuse`)."""
    return _evidence_reuse(bundle, skill_runs)["shared_evidence_reuse_ratio"]


def _dedupe_serialised(finding: dict) -> int:
    """Remove repeated evidence items and URLs from one serialised finding.

    Works on the dictionary produced by :meth:`Finding.to_dict`, never on the
    ``Finding`` itself, so building a report twice from the same objects
    yields the same report (the specialists' output is never edited).
    Deterministic: the first occurrence of each ``(observation, url,
    locator)`` triple and of each URL is kept, in order. Returns how many
    entries were removed, so the report can say so rather than hide it.
    """
    removed = 0
    seen = set()
    items = []
    for item in finding.get("evidence_items") or []:
        key = (item.get("observation"), item.get("url"), item.get("locator"))
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        items.append(item)
    finding["evidence_items"] = items
    listed = list(finding.get("affected_urls") or [])
    urls = util.dedupe(listed)
    removed += len(listed) - len(urls)
    finding["affected_urls"] = urls
    # ``affected_url_count`` describes the whole list while the serialised
    # list is capped; when the whole list was serialised the count follows it.
    if finding.get("affected_url_count") == len(listed):
        finding["affected_url_count"] = len(urls)
    return removed


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def validate_report(report: dict, schema: Optional[dict] = None) -> List[str]:
    """Validate against the shipped JSON Schema plus two extra invariants."""
    schema = schema or paths.load_schema(SCHEMA_FILE)
    errors = jsonschema_lite.validate(report, schema)

    ids = [f.get("id") for f in report.get("findings", [])]
    if len(set(ids)) != len(ids):
        errors.append("$.findings: duplicate finding ids")

    counts = report.get("summary", {})
    actual = {level: 0 for level in SEVERITIES}
    for finding in report.get("findings", []):
        severity = finding.get("severity")
        if severity in actual:
            actual[severity] += 1
    if counts.get("total_findings") != len(report.get("findings", [])):
        errors.append("$.summary.total_findings does not match len(findings)")
    # Every severity bucket, not only the three the brief names: a summary that
    # counts low/info in the total but not in a bucket does not reconcile, and
    # the whole point of validating counts is that they add up.
    for level in SEVERITIES:
        if counts.get(level) != actual[level]:
            errors.append(f"$.summary.{level} ({counts.get(level)}) != actual ({actual[level]})")
    bucket_total = sum(actual[level] for level in SEVERITIES)
    if counts.get("total_findings") != bucket_total:
        errors.append(f"$.summary.total_findings ({counts.get('total_findings')}) != "
                      f"sum of severity buckets ({bucket_total})")
    return errors


# ---------------------------------------------------------------------------
# projections
# ---------------------------------------------------------------------------

def to_handout(report: dict) -> dict:
    """The fields the Round 3 brief lists, plus the buckets that make them add up.

    The brief names ``critical``, ``high`` and ``medium``. Emitting only those
    three alongside ``total_findings`` produced a summary that does not
    reconcile - 38 findings over buckets summing to 35, with the low-severity
    ones counted in the total and shown nowhere. ``low`` and ``info`` are
    therefore included: the projection stays a minimal superset of the brief's
    floor, exactly as the full report is, and the arithmetic closes.
    """
    summary = report["summary"]
    return {
        "site": report["site"],
        "audited_at": report["audited_at"],
        "summary": {
            "total_findings": summary["total_findings"],
            "critical": summary["critical"],
            "high": summary["high"],
            "medium": summary["medium"],
            "low": summary["low"],
            "info": summary["info"],
        },
        "findings": [
            {
                "id": finding["id"],
                "title": finding["title"],
                "severity": finding["severity"],
                "evidence": finding["evidence"],
                "suggested_action": {
                    "summary": finding["suggested_action"]["summary"],
                    "priority": finding["suggested_action"]["priority"],
                },
            }
            for finding in report["findings"]
        ],
    }


def to_flat(report: dict) -> dict:
    """Flattest possible variant: evidence as a list, action as a string."""
    return {
        "site": report["site"],
        "audited_at": report["audited_at"],
        "summary": {
            "total_findings": report["summary"]["total_findings"],
            "critical": report["summary"]["critical"],
            "high": report["summary"]["high"],
            "medium": report["summary"]["medium"],
            "low": report["summary"]["low"],
            "info": report["summary"]["info"],
        },
        "findings": [
            {
                "id": finding["id"],
                "title": finding["title"],
                "severity": finding["severity"],
                "evidence": [item["observation"] for item in finding["evidence_items"]] or
                            [finding["evidence"]],
                "suggested_action": finding["suggested_action"]["summary"],
            }
            for finding in report["findings"]
        ],
    }


def project(report: dict, variant: str) -> dict:
    if variant == "handout":
        return to_handout(report)
    if variant == "flat":
        return to_flat(report)
    return report


# ---------------------------------------------------------------------------
# human-readable rendering
# ---------------------------------------------------------------------------

_SEV_MARK = {"critical": "!!", "high": "! ", "medium": "· ", "low": "  ", "info": "  "}


#: How a verification step is introduced in the Markdown. The distinction
#: already existed in the data (`suggested_action.verification_type`); until
#: 1.10.1 the rendered report introduced all three the same way, so a step that
#: asks an assistant a question read like something the audit had checked.
VERIFICATION_LABEL = {
    "self_verifiable": "*Verify:*",
    "external_validation": ("*Optional external validation — outside this audit's measured "
                            "behaviour:*"),
    "requires_external_data": ("*Verify against your own data — not observed by this audit:*"),
}


#: Appended once to an external-validation step. A result obtained by asking an
#: assistant is real, and it is also a single observation of one model, one
#: phrasing and one day: saying so is what keeps it from being read back as
#: something this audit established.
EXTERNAL_VALIDATION_CAVEAT = (
    " (A result obtained this way is one observation, and may vary by model, "
    "phrasing, date and configuration. It is not part of the score and is not "
    "evidence this audit collected.)")


def _verification_line(action: dict) -> str:
    """``label + step``, or ``""`` when the action states no verification."""
    step = (action or {}).get("verification")
    if not step:
        return ""
    kind = (action or {}).get("verification_type", "self_verifiable")
    label = VERIFICATION_LABEL.get(kind, VERIFICATION_LABEL["self_verifiable"])
    if kind == "external_validation":
        step = step.rstrip() + EXTERNAL_VALIDATION_CAVEAT
    return f"{label} {step}"


def render_markdown(report: dict) -> str:
    lines: List[str] = []
    summary = report["summary"]
    lines.append(f"# AI visibility & recommendation-readiness audit — {report['site']}")
    lines.append("")
    lines.append(f"*Audited {report['audited_at']} by {report['generator']['tool']} "
                 f"v{report['generator']['version']} (read-only).*")
    lines.append("")
    lines.append(f"**{summary['headline']}**")
    lines.append("")
    lines.append("| Overall | Discoverability | Engagement | Findings |")
    lines.append("|---|---|---|---|")
    lines.append(f"| {summary['overall_score']}/100 ({summary['readiness_band']}) "
                 f"| {summary['discoverability_score']}/100 "
                 f"| {summary['engagement_score']}/100 "
                 f"| {summary['total_findings']} "
                 f"({summary['critical']}C / {summary['high']}H / {summary['medium']}M) |")
    lines.append("")

    lines.append("## Pillar scores")
    lines.append("")
    lines.append("| Pillar | Score | Findings |")
    lines.append("|---|---|---|")
    for key, pillar in report["scores"]["pillars"].items():
        if pillar.get("score") is None:
            reason = pillar.get("unmeasured_reason") or "no evidence"
            lines.append(f"| {pillar['label']} | unmeasured ({reason}) | - |")
        else:
            lines.append(f"| {pillar['label']} | {pillar['score']}/100 | {pillar['findings']} |")
    lines.append("")

    matrix = report.get("answerability") or {}
    if matrix.get("total_questions"):
        counts = matrix["counts"]
        lines.append("## Answerability")
        lines.append("")
        lines.append(f"Questions generated from this site's own content: "
                     f"**{matrix['total_questions']}** · answerable {counts['answerable']} · "
                     f"partial {counts['partial']} · not answerable "
                     f"{counts['not_answerable']} · score "
                     f"{matrix.get('answerability_score')}")
        lines.append("")
        lines.append("| Question | Verdict | Evidence | Cited URL |")
        lines.append("|---|---|---|---|")
        for row in matrix["questions"]:
            evidence = row["evidence"].replace("|", "\\|")
            lines.append(f"| {row['question']} | `{row['status']}` | {evidence} | "
                         f"{row['citing_url'] or '-'} |")
        lines.append("")
        for note in matrix.get("notes", []):
            lines.append(f"> {note}")
        if matrix.get("notes"):
            lines.append("")
    lines.append("## Findings")
    lines.append("")
    for finding in report["findings"]:
        mark = _SEV_MARK.get(finding["severity"], "  ")
        lines.append(f"### {mark} {finding['id']} — {finding['title']}")
        lines.append("")
        sampling = finding.get("sampling") or {}
        lines.append(f"*{finding['severity'].upper()} · {finding['pillar_label']} · "
                     f"{finding['dimension']} · confidence "
                     f"{finding.get('confidence_level', '?').upper()} "
                     f"({finding['confidence']}) · {sampling.get('basis', 'n/a')}*")
        lines.append("")
        lines.append(f"**Observed.** {finding['evidence']}")
        if finding.get("interpretation"):
            lines.append("")
            lines.append(f"**What it may mean.** {finding['interpretation']}")
        lines.append("")
        for item in finding["evidence_items"][:6]:
            where = f" — `{item['url']}`" if item.get("url") else ""
            locator = f" ({item['locator']})" if item.get("locator") else ""
            lines.append(f"- {item['observation']}{locator}{where}")
        lines.append("")
        action = finding["suggested_action"]
        lines.append(f"**Fix ({action['priority']} priority, {action['effort']} effort).** "
                     f"{action['summary']}")
        if action.get("mechanism"):
            lines.append("")
            lines.append(f"*Why it works:* {action['mechanism']}")
        if action.get("steps"):
            lines.append("")
            for step in action["steps"]:
                lines.append(f"1. {step}")
        verification = _verification_line(action)
        if verification:
            lines.append("")
            lines.append(verification)
        lines.append("")

    if report.get("proactive_recommendations"):
        lines.append("## Proactive recommendations (no defect detected)")
        lines.append("")
        lines.append("Each one says what it rests on. *Evidence-backed* was gated on "
                     "something this crawl observed; *site-personalised* is standard "
                     "practice written in this site's own nouns; *generic* is standard "
                     "practice that would read the same for any site, and is not a "
                     "deficiency found here.")
        lines.append("")
        for opportunity in report["proactive_recommendations"]:
            lines.append(f"### {opportunity['id']} — {opportunity['title']}")
            lines.append("")
            lines.append(f"*{GROUNDING_LABEL.get(opportunity.get('grounding'), 'recommendation')} "
                         f"· {opportunity['priority']} priority · {opportunity['effort']} effort "
                         f"· {opportunity['dimension']}*")
            lines.append("")
            applicability = opportunity.get("applicability") or {}
            if applicability.get("applies_because"):
                lines.append(f"*Applies because:* {applicability['applies_because']} "
                             f"(site shape: {applicability.get('site_kind', 'unknown')}).")
                lines.append("")
            if opportunity.get("why_now"):
                lines.append(f"*Why now:* {opportunity['why_now']}")
                lines.append("")
            lines.append(f"*Why it works:* {opportunity['mechanism']}")
            lines.append("")
            for step in opportunity["steps"]:
                lines.append(f"1. {step}")
            verification = _verification_line(opportunity)
            if verification:
                lines.append("")
                lines.append(verification)
            lines.append("")

    coverage = report["coverage"]
    lines.append("## Coverage")
    lines.append("")
    lines.append(f"*Score basis: {report['summary'].get('score_basis', '')}*")
    lines.append("")
    lines.append(f"- Pages fetched: {coverage['pages_fetched']} "
                 f"({', '.join(f'{k}: {v}' for k, v in coverage['pages_by_type'].items())})")
    aside = coverage.get("non_content_pages_by_type") or {}
    if "content_pages" in coverage:
        lines.append(f"- Content pages every ratio is computed over: {coverage['content_pages']}"
                     + ("; set aside as non-content endpoints: "
                        + ", ".join(f"{k}: {v}" for k, v in sorted(aside.items()))
                        if aside else ""))
    lines.append(f"- Sitemaps parsed: {coverage['sitemaps_found']}; "
                 f"URLs seen in sitemaps: {coverage['sitemap_urls_seen']}")
    transport = coverage.get("transport") or {}
    if transport:
        spent = transport.get("time_by_outcome_s", {}) or {}
        parts = ", ".join(f"{k.replace('_', ' ')} {v}s" for k, v in spent.items() if v)
        lines.append(f"- Requests: {coverage.get('requests')} in "
                     f"{coverage.get('elapsed_s')}s"
                     + (f" ({parts})" if parts else ""))
        if transport.get("hosts_stopped_early"):
            for host, why in transport["hosts_stopped_early"].items():
                lines.append(f"- Stopped requesting {host}: {why}")
        if transport.get("requests_not_attempted"):
            lines.append(f"- Requests not attempted after that: "
                         f"{transport['requests_not_attempted']}")
    lines.append(f"- robots.txt present: {coverage['robots_txt_present']}; "
                 f"URLs skipped for robots: {coverage['blocked_by_robots']}")
    contexts = coverage.get("observed_contexts") or []
    if len(contexts) > 1:
        lines.append(
            "- Site shape: **{}** ({} confidence). Other shapes observed in the sample: {}"
            .format(coverage.get("site_kind"), coverage.get("site_kind_confidence"),
                    ", ".join(f"{c['context']} ({c['evidence_score']})"
                              for c in contexts if not c["primary"])))
    # Whether an absence in this report was looked for in one state or two.
    rendered = coverage.get("rendered_evidence") or {}
    if rendered.get("available"):
        budget = rendered.get("budget") or {}
        line = (f"- Browser-rendered evidence: available "
                f"({rendered.get('render_mode')}); pages selected "
                f"{rendered.get('pages_selected')}, rendered "
                f"{rendered.get('pages_rendered')}, failed "
                f"{rendered.get('pages_failed')}; budget "
                f"{budget.get('page_limit')} page(s) / "
                f"{budget.get('total_budget_s')}s total, "
                f"{budget.get('page_timeout_s')}s per page; spent "
                f"{rendered.get('elapsed_s')}s")
        if rendered.get("budget_exhausted"):
            line += " (budget reached before every selected page was rendered)"
        lines.append(line)
    elif rendered.get("attempted"):
        lines.append("- Browser-rendered evidence: requested but unavailable"
                     + (f" ({rendered.get('unavailable_reason')})"
                        if rendered.get("unavailable_reason") else "")
                     + " - every observation below is of the server response only")
    else:
        lines.append("- Browser-rendered evidence: not measured in this run "
                     "(run with --render to compare the server response against the "
                     "browser-rendered state)")
    specialists = coverage.get("specialists") or {}
    if specialists.get("expected"):
        completed = len(specialists.get("completed") or [])
        line = f"- Specialists completed: {completed} of {specialists['expected']}"
        failed = specialists.get("failed") or []
        if failed:
            line += " - " + "; ".join(
                f"{item['skill']} FAILED ({item['error']}), "
                f"{item['pillar'] or 'its'} pillar unmeasured" for item in failed)
        lines.append(line)
    reuse = report["diagnostics"].get("evidence_reuse") or {}
    if reuse:
        lines.append(f"- Evidence reuse: {reuse.get('specialists_served_from_the_bundle', 0)} "
                     f"specialist(s) read one shared bundle of "
                     f"{reuse.get('network_requests', 0)} request(s) "
                     f"(shared-evidence reuse ratio "
                     f"{reuse.get('shared_evidence_reuse_ratio', 0.0)}; "
                     f"{reuse.get('requests_avoided_by_sharing', 0)} request(s) avoided; "
                     f"transport cache hit ratio {reuse.get('transport_cache_hit_ratio', 0.0)})")
    else:
        lines.append(f"- Evidence reuse ratio: {report['diagnostics']['evidence_reuse_ratio']}")
    if coverage.get("site_kind"):
        lines.append(f"- Site shape read as: {coverage['site_kind']} "
                     f"({coverage.get('site_kind_confidence')} confidence)"
                     + (f"; product kinds: "
                        + ", ".join(f"{k}: {v}" for k, v in
                                    sorted((coverage.get('product_subtypes') or {}).items()))
                        if coverage.get("product_subtypes") else "")
                     + (f"; listing kinds: "
                        + ", ".join(f"{k}: {v}" for k, v in
                                    sorted((coverage.get('listing_subtypes') or {}).items()))
                        if coverage.get("listing_subtypes") else ""))
    for entry in coverage.get("expectations_not_applied") or []:
        reasons = "; ".join(f"{r['pages']} ({r['reason']})" for r in entry["not_applied"][:3])
        lines.append(f"- Expectation '{entry['expectation']}' applied to {entry['applied_to']} "
                     f"of {entry['product_pages']} product page(s); not applied to: {reasons}")
    dupes = report["diagnostics"].get("duplicate_evidence_entries_removed")
    if dupes:
        lines.append(f"- Duplicate evidence entries removed: {dupes}")
    lines.append("")
    return "\n".join(lines)


def dumps(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False)
