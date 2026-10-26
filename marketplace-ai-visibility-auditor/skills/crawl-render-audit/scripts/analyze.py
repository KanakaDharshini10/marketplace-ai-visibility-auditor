#!/usr/bin/env python3
"""crawl-render-audit - can a machine reach the content at all?

Consumes the shared evidence bundle, performs no network I/O, and returns a
list of :class:`aiva.findings.Finding`. This is stage one of the discovery
funnel: crawler admitted -> page readable -> fact extractable. Nothing
downstream can be fixed while this stage fails.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import List, Optional


def _bootstrap() -> Path:
    """Locate the marketplace root and put its shared library on sys.path."""
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "marketplace.json").is_file() and \
                (candidate / "lib" / "aiva" / "__init__.py").is_file():
            lib = str(candidate / "lib")
            if lib not in sys.path:
                sys.path.insert(0, lib)
            return candidate
    raise RuntimeError(
        "cannot locate the marketplace root: run this script from inside the "
        "marketplace-ai-visibility-auditor package")


MARKETPLACE_ROOT = _bootstrap()

from urllib.parse import urlsplit                    # noqa: E402
from aiva import evidence as ev
from aiva import semantics                            # noqa: E402                      # noqa: E402
from aiva import util                                # noqa: E402
from aiva.analysis import (crawl_yielded_evidence, commerce_evidence, absent, action, confidence_for, finding, label,   # noqa: E402
                           measured, observed, page_items,
                           render_coverage, render_state, rendered_fact_gaps,
                           sample_guard, scope_for, severity_from_ratio, severity_from_sample, redirect_index)
from aiva.config import AI_CRAWLER_AGENTS, NON_CITABLE_PATH_RE  # noqa: E402
from aiva.findings import Finding                    # noqa: E402
from aiva.robots import RobotsTxt                    # noqa: E402

SKILL = "crawl-render-audit"
PILLAR = "crawl_render"

#: Assistant-facing crawlers whose loss is a *citation* problem, ranked by how
#: directly blocking them removes the brand from an answer surface.
FIRST_ORDER_AI_AGENTS = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot",
                         "Claude-User", "PerplexityBot", "Perplexity-User",
                         "Google-Extended", "Bingbot", "Applebot-Extended")

#: Tokens that fetch a page *live, because a user asked a question that needs
#: it* - as opposed to the index/training crawlers. The distinction is the one
#: RFC-9309 diagnosis the report can make honestly: blocking an answer-time
#: fetcher most directly keeps a page out of a cited answer, while blocking a
#: training or indexing crawler governs whether it is in the corpus at all.
#: Membership comes from the site-owner-facing catalogue in config, so a token
#: added there is classified without editing this rule.
_ANSWER_TIME_AI_AGENTS = frozenset({
    "OAI-SearchBot", "ChatGPT-User", "Claude-User", "Perplexity-User",
})


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def _robots_object(bundle: dict) -> RobotsTxt:
    block = bundle.get("robots", {})
    return RobotsTxt.from_response(
        block.get("url", ""), int(block.get("status") or 0),
        block.get("raw", ""), block.get("error"))


#: Transport failures that happened on *our* side of the connection, or
#: somewhere between us and the origin. They are not observations about the
#: audited site.
_TRANSPORT_ERROR_HINTS = (
    "tunnel connection failed", "proxy", "name or service not known",
    "temporary failure in name resolution", "getaddrinfo", "nodename nor servname",
    "certificate verify failed", "ssl", "connection refused", "connection reset",
    "network is unreachable", "no route to host", "timed out", "timeout",
)


def _origin_answered(robots: dict) -> bool:
    """Did the origin actually respond, or did the request never arrive?

    The distinction matters more than it looks. A 5xx is the site's own answer
    and RFC 9309 makes it a real, reportable blocker. A blocked proxy, a DNS
    failure, a TLS error or a WAF refusing an unknown user-agent is *this
    audit's* problem - and reporting it as "robots.txt is unreachable, so the
    whole site is disallowed" blames the site at `critical` for something the
    site may be doing perfectly. Corporate proxies, geo-blocks and bot walls
    all land here, so it is not an edge case.
    """
    error = str(robots.get("error") or "").lower()
    if not error:
        return True                      # an HTTP status came back
    return not any(hint in error for hint in _TRANSPORT_ERROR_HINTS)


def rule_robots_unreachable(bundle: dict) -> Optional[Finding]:
    robots = bundle.get("robots", {})
    if not robots.get("unreachable"):
        return None
    detail = robots.get("error") or ("HTTP " + str(robots.get("status")))
    if not _origin_answered(robots):
        return finding(
            "CR-ROBOTS-NOT-REACHED",
            "This audit could not reach robots.txt, so the crawl checks below did not run",
            "info", PILLAR,
            evidence=(f"GET {robots.get('url')} failed before the origin answered: {detail}. "
                      "That is a transport failure between this auditor and the site - a "
                      "proxy, DNS, TLS or bot-wall refusal - not an observation about the "
                      "site's configuration. No claim is made here about whether assistant "
                      "crawlers can reach it."),
            items=[observed(f"request did not reach the origin: {detail}",
                            url=robots.get("url", ""), locator="robots.txt")],
            action=action(
                "Re-run the audit from a network that can reach the site, then read the report.",
                priority="low", effort="low", impact="low",
                mechanism="Nothing about the site was measured, so nothing about the site is "
                          "reported. The remaining pillars have no evidence to score.",
                steps=["Check the host resolves and answers from the machine running the audit.",
                       "If a WAF or bot wall is refusing the auditor's user-agent, allow it for "
                       "the duration of the audit - and note that assistant crawlers may be "
                       "refused the same way, which is worth checking separately.",
                       "Re-run the audit and compare."],
                verification="curl -I https://<host>/robots.txt returns a status code."),
            urls=[robots.get("url", "")], confidence=0.99,
            metrics={"scope": "audit", "status": robots.get("status")},
            tags=["coverage"])
    return finding(
        "CR-ROBOTS-UNREACHABLE",
        "robots.txt is unreachable, so compliant crawlers must treat the whole site as disallowed",
        "critical", PILLAR,
        evidence=(f"GET {robots.get('url')} returned {detail}. "
                  "RFC 9309 requires a compliant crawler to assume complete disallow when "
                  "robots.txt is unreachable; RFC 9309 tells a compliant crawler to treat "
                  "that as a complete disallow."),
        items=[observed(f"robots.txt request failed: {detail}",
                        url=robots.get("url", ""), locator="robots.txt")],
        action=action(
            "Make /robots.txt return HTTP 200 with a valid body (an empty file is valid).",
            priority="critical", effort="low", impact="high",
            mechanism="A 5xx or timeout on robots.txt is not 'no rules' - RFC 9309 tells a "
                      "crawler to treat the whole site as disallowed until the file can be "
                      "read, so a crawler that follows the standard stops here.",
            steps=["Serve /robots.txt as a static file from the edge/CDN, not from the "
                   "application, so an app outage cannot take it down.",
                   "Return 200 with `User-agent: *` and an empty `Disallow:` if you intend "
                   "to allow everything.",
                   "Add an uptime check on the robots.txt URL itself."],
            verification="curl -I https://<host>/robots.txt returns 200 from three regions."),
        urls=[robots.get("url", "")], confidence=0.99,
        metrics={"scope": "site", "status": robots.get("status")},
        tags=["robots", "blocking"])


def rule_robots_missing(bundle: dict) -> Optional[Finding]:
    robots = bundle.get("robots", {})
    if robots.get("exists") or robots.get("unreachable"):
        return None
    # A refusal is not an absence. HTTP 403 on /robots.txt means this request
    # was turned away; it says nothing about whether the file exists, and a
    # browser or an allowlisted crawler may be served it normally. Reporting
    # "no robots.txt exists" from a 403 states as fact something the audit did
    # not observe - and on a site behind bot mitigation it also reports the
    # same barrier a second time, under a heading that blames the site's
    # configuration. What *was* observed is recorded in `coverage` and, where
    # the pattern is a wall, in CR-BOT-WALL.
    if robots.get("status") in REFUSAL_STATUSES:
        return None
    return finding(
        "CR-ROBOTS-MISSING",
        "No robots.txt is published, so crawl guidance and sitemap discovery rely on guesswork",
        "low", PILLAR,
        evidence=f"GET {robots.get('url')} returned HTTP {robots.get('status')}, which is the "
                 "status a server returns for a file that is not there. Crawling is permitted "
                 "by default, but the site publishes no Sitemap directive and no explicit "
                 "permission for assistant crawlers.",
        items=[absent(f"robots.txt not found (HTTP {robots.get('status')})",
                      url=robots.get("url", ""), locator="robots.txt")],
        action=action(
            "Publish a minimal robots.txt that allows assistant crawlers and declares the sitemap.",
            priority="medium", effort="low", impact="medium",
            mechanism="RFC 9309 defines robots.txt as the file to be read before the rest "
                      "of a host, and defines what a compliant client does with it. It is "
                      "the "
                      "cheapest place to point every crawler at the sitemap and to state "
                      "explicitly that AI assistant agents are welcome.",
            steps=["Create /robots.txt with `User-agent: *` / `Disallow:` (empty).",
                   "Add `Sitemap: https://<host>/sitemap.xml`.",
                   "Add explicit `User-agent: GPTBot` / `User-agent: ClaudeBot` / "
                   "`User-agent: PerplexityBot` groups with an empty Disallow if you want "
                   "those assistants to cite you."],
            example="User-agent: *\nDisallow:\n\nUser-agent: GPTBot\nDisallow:\n\n"
                    "Sitemap: https://example.com/sitemap.xml",
            verification="curl https://<host>/robots.txt shows the Sitemap line."),
        urls=[robots.get("url", "")], confidence=0.95,
        metrics={"scope": "site"}, tags=["robots"])


def rule_ai_crawlers_blocked(bundle: dict) -> Optional[Finding]:
    robots = bundle.get("robots", {})
    if not robots.get("exists"):
        return None
    summaries = robots.get("ai_crawlers", {})
    blocked = [(agent, summary) for agent, summary in summaries.items()
               if summary.get("blocks_site")]
    if not blocked:
        return None
    first_order = [agent for agent, _ in blocked if agent in FIRST_ORDER_AI_AGENTS]
    severity = "critical" if first_order else "high"
    items = []
    for agent, summary in blocked[:8]:
        rule = summary.get("deciding_rule") or {}
        items.append(observed(
            f"{agent} ({AI_CRAWLER_AGENTS.get(agent, 'AI crawler')}) is disallowed at / by "
            f"`{rule.get('type', 'disallow')}: {rule.get('pattern', '/')}` in the "
            f"User-agent group starting at line {summary.get('matched_group_line')}",
            url=robots.get("url", ""),
            locator=f"robots.txt line {rule.get('line', '?')}"))
    blocked_agents = [agent for agent, _ in blocked]
    answer_time = [a for a in blocked_agents if a in _ANSWER_TIME_AI_AGENTS]
    indexing = [a for a in blocked_agents if a not in _ANSWER_TIME_AI_AGENTS]
    split_note = ""
    if answer_time and indexing:
        split_note = (f" Of these, {', '.join(answer_time)} fetch a page live when a user's "
                      f"question needs it, and {', '.join(indexing[:6])} build the index or "
                      f"training corpus assistants draw on.")
    elif answer_time:
        split_note = (" These fetch a page live when a user's question needs it, which is the "
                      "traffic a citation depends on.")
    elif indexing:
        split_note = (" These build the index or training corpus assistants draw on, rather "
                      "than fetching live at answer time.")
    return finding(
        "CR-AI-CRAWLERS-BLOCKED",
        "robots.txt blocks assistant crawlers, so a crawler that honours it does not fetch these pages",
        severity, PILLAR,
        evidence=(f"{len(blocked)} assistant crawler token(s) are disallowed at the site root: "
                  f"{', '.join(blocked_agents[:10])}"
                  f"{'...' if len(blocked) > 10 else ''}.{split_note}"),
        interpretation=(
            "A crawler that honours a `Disallow: /` rule for its token does not fetch the "
            "disallowed paths. A directive covering an answer-time fetcher covers the "
            "page out of a cited answer; blocking an indexing or training crawler governs "
            "whether the page is in the corpus at all. Blanket blocks are usually inherited "
            "from a copy-pasted 'block AI scrapers' snippet that does not separate the two. "
            "This audit reads the robots.txt rule; it does not query any assistant, so whether "
            "a given one honours the rule is not measured here."),
        items=items,
        action=action(
            "Allow the assistant crawler tokens you want citations from, "
            "path-scoping instead of blanket-blocking.",
            priority="critical" if first_order else "high", effort="low", impact="high",
            mechanism="Blanket blocks are usually inherited from a copy-pasted 'block AI "
                      "scrapers' snippet, which covers one directive at every token its "
                      "author listed. The tokens their operators publish for answer-time "
                      "fetching are covered by the same line as the tokens published for "
                      "corpus collection, so a decision meant for one applies to both.",
            steps=["Decide separately about training crawlers and answer-time fetchers: "
                   "their operators publish ChatGPT-User, Claude-User and Perplexity-User "
                   "as tokens used when a person asks about a specific page.",
                   "Replace `Disallow: /` with path-scoped rules that protect carts, accounts "
                   "and search result pages only.",
                   "Keep product, category, policy and brand pages allowed for every agent "
                   "listed in the finding.",
                   "If training must be excluded, block GPTBot/CCBot specifically and leave "
                   "the answer-time agents allowed."],
            example="User-agent: GPTBot\nDisallow: /cart\nDisallow: /account\nDisallow: /search\n\n"
                    "User-agent: ClaudeBot\nDisallow: /cart\nDisallow: /account\n",
            verification="Re-run this audit; CR-AI-CRAWLERS-BLOCKED should disappear. Then ask "
                         "each assistant a brand-fact question with browsing enabled and check "
                         "it cites your domain.",
            owner="whoever owns the CDN/edge config or the web server"),
        urls=[robots.get("url", "")],
        confidence=0.99,
        metrics={"scope": "site", "blocked_agents": blocked_agents,
                 "first_order_blocked": first_order,
                 "answer_time_blocked": answer_time,
                 "indexing_or_training_blocked": indexing},
        tags=["robots", "ai-crawlers", "blocking"])


def rule_ai_crawlers_path_blocked(bundle: dict) -> Optional[Finding]:
    robots_block = bundle.get("robots", {})
    if not robots_block.get("exists"):
        return None
    robots = _robots_object(bundle)
    pages = ev.pages(bundle)
    # The content pages a retrieval crawler would want. Products and listings
    # come through the shared funnels rather than a literal, so this rule and
    # the rules that audit those pages can never disagree about which they are.
    sample = (ev.product_pages(bundle) + ev.category_pages(bundle)
              + [p for p in pages if p.get("page_type") in ("faq", "policy")])
    if not sample_guard(sample, 1):
        return None

    blocked_pairs: List[tuple] = []
    for agent in FIRST_ORDER_AI_AGENTS:
        summary = robots_block.get("ai_crawlers", {}).get(agent, {})
        if summary.get("blocks_site"):
            continue  # already covered by CR-AI-CRAWLERS-BLOCKED
        for page in sample:
            allowed, rule, _group = robots.decision(agent, page["url"])
            if not allowed and rule is not None:
                blocked_pairs.append((agent, page["url"], rule))
    if not blocked_pairs:
        return None

    agents = sorted({agent for agent, _, _ in blocked_pairs})
    urls = sorted({url for _, url, _ in blocked_pairs})
    items = [observed(
        f"{agent} is disallowed from {url} by `{rule.to_dict()['type']}: {rule.pattern}`",
        url=url, locator=f"robots.txt line {rule.line_no}")
        for agent, url, rule in blocked_pairs[:6]]
    if len(blocked_pairs) > 6:
        items.append(measured(f"...and {len(blocked_pairs) - 6} further agent/page combinations",
                              value=len(blocked_pairs)))
    return finding(
        "CR-AI-CRAWLERS-PATH-BLOCKED",
        "robots.txt disallows assistant crawler tokens from content pages",
        "high", PILLAR,
        evidence=(f"{len(urls)} crawled content page(s) (product, category, FAQ or policy) are "
                  f"disallowed for {', '.join(agents)}. Those pages exist and served to this "
                  "audit; a crawler that honours the rule for its token does not fetch them."),
        items=items,
        action=action(
            "Narrow the disallow patterns so product, category, policy and FAQ paths stay open.",
            priority="high", effort="low", impact="high",
            mechanism="A pattern written to hide a faceted-search explosion (e.g. `Disallow: /*?`) "
                      "usually catches the canonical product URLs too. The crawler obeys the "
                      "pattern, not the intent.",
            steps=["List every Disallow pattern and test it against ten real product URLs.",
                   "Prefer disallowing the specific query parameter that causes the explosion "
                   "(`Disallow: /*?sort=`) over disallowing all query strings.",
                   "Never disallow a path that appears in your sitemap - that combination is "
                   "self-contradictory and is what this finding detected."],
            verification="For each URL in this finding, confirm robots.txt now allows it for "
                         "every agent listed."),
        urls=urls, confidence=0.95,
        metrics={"scope": "site", "agents": agents, "blocked_pages": len(urls)},
        tags=["robots", "ai-crawlers"])


def rule_robots_syntax(bundle: dict) -> Optional[Finding]:
    robots = bundle.get("robots", {})
    warnings = robots.get("parse_warnings", []) or []
    unknown = [d for d in robots.get("unknown_directives", []) or []
               if d.get("field") in ("noindex", "nofollow", "host", "request-rate",
                                     "visit-time", "clean-param")]
    if not warnings and not unknown:
        return None
    items = [observed(f"parse warning: {warning}", url=robots.get("url", ""),
                      locator="robots.txt") for warning in warnings[:5]]
    items += [observed(
        f"directive `{d['field']}: {d['value']}` on line {d['line']} is not part of the "
        f"robots exclusion standard and is ignored by major crawlers",
        url=robots.get("url", ""), locator=f"robots.txt line {d['line']}")
        for d in unknown[:5]]
    has_noindex = any(d.get("field") == "noindex" for d in unknown)
    return finding(
        "CR-ROBOTS-SYNTAX",
        "robots.txt contains directives that do not do what the author expects",
        "medium" if has_noindex else "low", PILLAR,
        evidence=(f"{len(warnings)} parse warning(s) and {len(unknown)} non-standard "
                  f"directive(s) were found in robots.txt"
                  + (". `Noindex:` in robots.txt has been unsupported since 2019 - pages the "
                     "author believes are hidden are being indexed." if has_noindex else ".")),
        items=items,
        action=action(
            "Remove non-standard directives and express the intent with the mechanism that works.",
            priority="medium" if has_noindex else "low", effort="low", impact="medium",
            mechanism="RFC 9309 defines robots.txt as a format whose unrecognised lines "
                      "are skipped rather than reported, so a directive outside the standard "
                      "enforces nothing and fails silently - invisible without a linter.",
            steps=["Replace `Noindex:` in robots.txt with a `<meta name=\"robots\" "
                   "content=\"noindex\">` tag or an `X-Robots-Tag: noindex` header on the "
                   "pages concerned - and make sure robots.txt still *allows* crawling them, "
                   "or the tag can never be read.",
                   "Delete `Host:` and `Request-rate:`; use canonical tags and `Crawl-delay:` "
                   "instead.",
                   "Fix any rule that appears before its `User-agent:` line."],
            verification="Re-run this audit and confirm no parse warnings remain."),
        urls=[robots.get("url", "")], confidence=0.9,
        metrics={"scope": "site", "warnings": len(warnings), "unknown": len(unknown)},
        tags=["robots", "hygiene"])


# ---------------------------------------------------------------------------
# sitemaps
# ---------------------------------------------------------------------------
#
# Three facts, three findings, and the wording of each is bounded by what the
# probe actually observed:
#
# * CR-NO-SITEMAP     - none of the locations this audit *can* look at served a
#                       sitemap. A finite probe list cannot establish that the
#                       site has no sitemap, and the finding never says it does.
# * CR-SITEMAP-BROKEN - a location the site itself declares did not yield one,
#                       with the outcome named: 404, malformed, or could not be
#                       fetched by this audit.
# * CR-SITEMAP-UNDECLARED - robots.txt was read and carries no Sitemap
#                       directive. That is a fact about robots.txt, reported on
#                       its own whether or not a sitemap was found elsewhere.

#: What happened at one probed sitemap location. ``not_found`` is the only
#: outcome that is evidence of absence *at that location*; ``unchecked``
#: outcomes say nothing about the location at all.
SITEMAP_VALID = "valid"
SITEMAP_NOT_FOUND = "not_found"
SITEMAP_MALFORMED = "malformed"
SITEMAP_UNCHECKED = "unchecked"


def sitemap_probe_outcome(record: dict) -> str:
    """Classify a sitemap record from the collector by what it observed."""
    status = int(record.get("status") or 0)
    error = str(record.get("error") or "")
    if record.get("kind") in ("index", "urlset") and not error:
        return SITEMAP_VALID
    if status in (404, 410):
        return SITEMAP_NOT_FOUND
    if 200 <= status < 300:
        # The location answered with a document; it just is not a sitemap.
        return SITEMAP_MALFORMED
    # Refused, server error, transport failure, robots-blocked, budget: the
    # location was not observed.
    return SITEMAP_UNCHECKED


def _sitemap_outcome_detail(record: dict) -> str:
    """How one probe ended, in the record's own terms."""
    outcome = sitemap_probe_outcome(record)
    status = int(record.get("status") or 0)
    error = str(record.get("error") or "")
    if outcome == SITEMAP_NOT_FOUND:
        return f"HTTP {status}"
    if outcome == SITEMAP_MALFORMED:
        return (f"HTTP {status} but sitemap XML parsing failed "
                f"({error or record.get('kind') or 'not a urlset or sitemapindex'})")
    if status >= 500:
        return f"could not be verified (HTTP {status}, server or gateway error)"
    if status >= 400:
        return f"could not be verified (HTTP {status}, refused or rate-limited)"
    return f"could not be verified (not fetched: {error or 'no response'})"


def _declared_by_the_site(record: dict, bundle: dict) -> bool:
    declared = set(bundle.get("robots", {}).get("sitemaps", []) or [])
    source = str(record.get("source") or "")
    return (source.startswith("robots.txt") or source.startswith("listed in")
            or record.get("url") in declared)


def _robots_directive_state(bundle: dict) -> str:
    """``absent`` | ``present`` | ``unknown`` | ``robots_missing``."""
    robots = bundle.get("robots", {}) or {}
    if robots.get("sitemaps"):
        return "present"
    if robots.get("exists"):
        return "absent"
    if robots.get("unreachable") or int(robots.get("status") or 0) in REFUSAL_STATUSES \
            or robots.get("error"):
        return "unknown"
    return "robots_missing"


def rule_no_sitemap(bundle: dict) -> Optional[Finding]:
    # "No sitemap" is a claim about discovery on a reachable site. When the
    # crawl read nothing at all, the sitemap probe failing is a symptom of the
    # same unreachability, not a separate defect to report.
    if not crawl_yielded_evidence(bundle):
        return None
    sitemaps = bundle.get("sitemaps", []) or []
    by_outcome = {}
    for record in sitemaps:
        by_outcome.setdefault(sitemap_probe_outcome(record), []).append(record)
    if by_outcome.get(SITEMAP_VALID):
        return None
    # The site declares a sitemap somewhere. Whatever became of it is a fact
    # about *that* sitemap - CR-SITEMAP-BROKEN reports it - and not evidence
    # that the site has none.
    if any(_declared_by_the_site(record, bundle) for record in sitemaps):
        return None
    not_found = by_outcome.get(SITEMAP_NOT_FOUND, [])
    malformed = by_outcome.get(SITEMAP_MALFORMED, [])
    unchecked = by_outcome.get(SITEMAP_UNCHECKED, [])
    # Nothing answered. No location was *observed* to lack a sitemap, so there
    # is no absence to report - only a probe that did not run.
    if not not_found and not malformed:
        return None

    directive = _robots_directive_state(bundle)
    robots = bundle.get("robots", {}) or {}
    # The evidence establishes "not discoverable unaided" only when both of
    # the mechanisms a crawler has without prior knowledge were checked and
    # came back empty: every conventional location answered, and robots.txt
    # was read and names none.
    established = not unchecked and directive == "absent"

    probed = ", ".join(f"{r.get('url')} -> {_sitemap_outcome_detail(r)}"
                       for r in sitemaps[:6]) + ("..." if len(sitemaps) > 6 else "")
    if directive == "absent":
        robots_fact = (f"robots.txt ({robots.get('url')}) was read (HTTP {robots.get('status')}) "
                       f"and declares no Sitemap directive")
    elif directive == "robots_missing":
        robots_fact = (f"robots.txt is absent (HTTP {robots.get('status')}), so it declares "
                       f"nothing")
    else:
        robots_fact = (f"robots.txt could not be read ({robots.get('error') or 'HTTP ' + str(robots.get('status'))}), so whether it "
                       f"declares a sitemap is unknown")
    evidence = (f"No valid XML sitemap was found at the {len(sitemaps)} conventional "
                f"location(s) this audit probes: {probed}. {robots_fact}.")
    if unchecked:
        evidence += (f" {len(unchecked)} of the probed location(s) could not be checked "
                     f"(refused, errored or not fetched), so their state is unknown.")
    evidence += (" This audit cannot see a sitemap submitted directly to a search console "
                 "or published at a path it does not probe, so this is a statement about "
                 "what is discoverable, not about what exists.")

    if established:
        title = "No XML sitemap is discoverable through robots.txt or the conventional paths"
        interpretation = (
            "A crawler with no prior knowledge of this site has two ways to find a sitemap "
            "unaided - a Sitemap directive in robots.txt and the conventional paths - and "
            "both came back empty, so such a crawler's discovery of URLs falls back to "
            "following internal links. That is a statement about discoverability; a "
            "sitemap that exists elsewhere is invisible to this audit and to that crawler "
            "alike.")
        severity, confidence = "high", 0.9
    else:
        title = "No XML sitemap was found at the conventional locations that answered"
        gaps = []
        if unchecked:
            gaps.append(f"{len(unchecked)} probed location(s) could not be checked")
        if directive != "absent":
            gaps.append("robots.txt could not be read for a Sitemap directive"
                        if directive == "unknown" else "robots.txt is absent")
        interpretation = (
            "Whether a sitemap is discoverable could not be settled: " + "; ".join(gaps) +
            ". The locations that answered did not carry one; nothing is claimed about the "
            "ones that did not.")
        severity, confidence = "medium", 0.6

    items = [absent(f"no valid sitemap at {r.get('url')} ({_sitemap_outcome_detail(r)})",
                    url=r.get("url", ""), locator="sitemap probe")
             for r in not_found + malformed][:5]
    items += [observed(f"could not check {r.get('url')} ({_sitemap_outcome_detail(r)})",
                       url=r.get("url", ""), locator="sitemap probe")
              for r in unchecked][:3]
    if directive == "absent":
        items.append(absent("no `Sitemap:` directive in robots.txt",
                            url=robots.get("url", ""), locator="robots.txt"))
    return finding(
        "CR-NO-SITEMAP", title, severity, PILLAR,
        evidence=evidence,
        interpretation=interpretation,
        items=items,
        action=action(
            "Publish an XML sitemap covering every canonical content URL, and declare it in "
            "robots.txt.",
            priority=severity, effort="medium", impact="high",
            mechanism="A sitemap is an explicit, complete list of the URLs a site wants read; "
                      "without one, a crawler's discovery of deep pages depends on following "
                      "links from page to page.",
            steps=["If a sitemap already exists at another path, add `Sitemap: <absolute "
                   "URL>` to robots.txt so it can be found without prior knowledge.",
                   "Otherwise generate /sitemap.xml from the catalogue at build/publish time, "
                   "not by hand.",
                   "Include <lastmod> with the true last content change per URL.",
                   "Split above 50,000 URLs or 50MB into a sitemap index.",
                   "Exclude non-canonical, redirecting and noindexed URLs - a sitemap full of "
                   "them trains crawlers to trust it less."],
            verification="curl https://<host>/sitemap.xml | head -20 shows a <urlset>, and "
                         "curl https://<host>/robots.txt | grep -i sitemap names it."),
        urls=[bundle["site"]["origin"]], confidence=confidence,
        metrics={"scope": "site", "probed": len(sitemaps), "not_found": len(not_found),
                 "malformed": len(malformed), "unchecked": len(unchecked),
                 "robots_directive": directive,
                 "discoverability_established": established,
                 "probed_locations": [r.get("url") for r in sitemaps]},
        tags=["sitemap", "discovery"])


def rule_sitemap_errors(bundle: dict) -> Optional[Finding]:
    sitemaps = bundle.get("sitemaps", []) or []
    broken = [s for s in sitemaps
              if _declared_by_the_site(s, bundle)
              and sitemap_probe_outcome(s) != SITEMAP_VALID]
    if not broken:
        return None
    outcomes = {sitemap_probe_outcome(s) for s in broken}
    # A sitemap this audit could not fetch is not a sitemap that is broken.
    # When every declared location is merely unchecked, the finding says so
    # and carries the confidence of an observation that was not made.
    only_unchecked = outcomes == {SITEMAP_UNCHECKED}
    unchecked = [s for s in broken if sitemap_probe_outcome(s) == SITEMAP_UNCHECKED]
    settled = [s for s in broken if sitemap_probe_outcome(s) != SITEMAP_UNCHECKED]
    if only_unchecked:
        title = "A declared sitemap could not be verified by this audit"
        severity, confidence = "low", 0.6
        summary = (f"{len(broken)} sitemap(s) that the site declares could not be verified "
                   f"by this audit (refused, errored or not attempted), so whether they "
                   f"parse is unknown - this says nothing about the sitemap itself: ")
    else:
        malformed = [s for s in settled if sitemap_probe_outcome(s) == SITEMAP_MALFORMED]
        title = ("A declared sitemap is served but its XML does not parse" if malformed
                 and len(malformed) == len(settled) else
                 "A declared sitemap is missing or does not parse")
        severity, confidence = "medium", 0.95
        summary = (f"{len(settled)} sitemap(s) that the site itself declares did not yield "
                   f"a valid sitemap: ")
    aside = ""
    if unchecked and not only_unchecked:
        aside = (f" A further {len(unchecked)} declared sitemap(s) could not be verified "
                 f"(refused, errored or not attempted) and are not counted as broken.")
    return finding(
        "CR-SITEMAP-BROKEN", title, severity, PILLAR,
        evidence=summary + "; ".join(f"{s['url']} -> {_sitemap_outcome_detail(s)}"
                                     for s in (broken if only_unchecked else settled)[:3])
        + aside,
        items=[observed(f"declared sitemap {s['url']}: {_sitemap_outcome_detail(s)}",
                        url=s["url"], locator=s.get("source", "sitemap")) for s in broken[:5]],
        action=action(
            "Fix or remove the broken sitemap references."
            if not only_unchecked else
            "Confirm the declared sitemap is served, then re-run the audit.",
            priority=severity, effort="low", impact="medium",
            mechanism="A declared sitemap is the site's own statement of which URLs exist; "
                      "one that does not parse, or is not there, states nothing, so the "
                      "URLs it was meant to list are discoverable only by following links.",
            steps=["Remove Sitemap: lines pointing at URLs that 404.",
                   "Validate the XML (a stray & or an unescaped < will break the whole file).",
                   "If a sitemap index lists children, make sure every child resolves.",
                   "If the sitemap is served but refuses unknown user-agents, allow crawlers "
                   "to read it - a sitemap only a browser can fetch helps no crawler."],
            verification="Every URL in every Sitemap: directive returns 200 and valid XML."),
        urls=[s["url"] for s in broken], confidence=confidence,
        metrics={"scope": "site", "broken": len(broken),
                 "outcomes": {o: len([s for s in broken if sitemap_probe_outcome(s) == o])
                              for o in sorted(outcomes)}},
        tags=["sitemap"])


def rule_sitemap_not_declared(bundle: dict) -> Optional[Finding]:
    """robots.txt was read and names no sitemap - a fact on its own.

    Reported whether or not a sitemap was found at a conventional path. In
    the first case the directive is the missing link between a working file
    and a crawler that does not guess filenames; in the second it is one of
    the two facts CR-NO-SITEMAP rests on, stated separately so that "no
    directive" is never mistaken for "no sitemap", and vice versa.
    """
    if _robots_directive_state(bundle) != "absent":
        return None      # present, or robots.txt missing/unread: nothing observed here
    if not crawl_yielded_evidence(bundle):
        return None
    robots = bundle.get("robots", {}) or {}
    sitemaps = bundle.get("sitemaps", []) or []
    usable = [s for s in sitemaps if sitemap_probe_outcome(s) == SITEMAP_VALID]
    if usable:
        title = "A working sitemap exists but robots.txt does not point to it"
        evidence = (f"{usable[0]['url']} parses correctly, yet robots.txt "
                    f"({robots.get('url')}, HTTP {robots.get('status')}) contains no Sitemap "
                    f"directive, so crawlers can only find it by guessing the conventional path.")
        items = [observed(f"valid sitemap served at {usable[0]['url']}", url=usable[0]["url"]),
                 absent("no `Sitemap:` directive in robots.txt",
                        url=robots.get("url", ""), locator="robots.txt")]
        urls = [usable[0]["url"]]
        priority_note = "Append `Sitemap: <absolute URL>` at the end of robots.txt."
    else:
        title = "robots.txt declares no Sitemap directive"
        evidence = (f"robots.txt ({robots.get('url')}) was read (HTTP {robots.get('status')}, "
                    f"{robots.get('bytes', 0)} bytes) and contains no `Sitemap:` line. This is "
                    f"a fact about robots.txt only: whether a sitemap exists at a conventional "
                    f"path is reported separately (CR-NO-SITEMAP), and a sitemap published "
                    f"elsewhere would be reachable through this directive and no other way "
                    f"a crawler has unaided.")
        items = [absent("no `Sitemap:` directive in robots.txt",
                        url=robots.get("url", ""), locator="robots.txt")]
        urls = [robots.get("url", "")]
        priority_note = ("Once a sitemap is published, append `Sitemap: <absolute URL>` at "
                         "the end of robots.txt.")
    return finding(
        "CR-SITEMAP-UNDECLARED", title, "low", PILLAR,
        evidence=evidence,
        items=items,
        action=action("Add a `Sitemap:` line to robots.txt for every sitemap you publish.",
                      priority="low", effort="low", impact="low",
                      mechanism="Sitemap discovery via robots.txt is the only path that does "
                                "not depend on a crawler guessing a filename.",
                      steps=[priority_note, "Use the absolute, canonical-host URL."],
                      verification="curl https://<host>/robots.txt | grep -i sitemap"),
        urls=urls, confidence=0.95,
        metrics={"scope": "site", "sitemap_found_elsewhere": bool(usable)},
        tags=["sitemap", "hygiene"])


def rule_http_errors(bundle: dict) -> Optional[List[Finding]]:
    """Advertised URLs that are not there, kept apart from URLs not verified.

    A 404 or 410 is the origin answering for the resource: it is not there,
    and a sitemap or internal link that still points at it is a defect the
    site can fix. A 403, 429, 5xx, timeout or DNS failure is the path between
    this auditor and the origin failing to deliver an answer; it says nothing
    about the resource and is reported under its own heading as "could not
    be verified", at informational severity, never as a broken URL.
    """
    pages = bundle.get("pages", [])
    failed = [p for p in pages if p.get("status", 0) >= 400]
    errors = [e for e in (bundle.get("fetch_errors", []) or []) if isinstance(e, dict)]
    if not failed and not errors:
        return None

    # Two filters, and the finding's own sentence is the reason for both.
    #
    # "Pages the site itself advertises" - so a URL this audit chose to fetch,
    # like the site root, is not one of them. The claim was made about every
    # failed fetch, which on a site behind bot mitigation meant the refused
    # home page was published as a broken URL in the site's own sitemap.
    #
    # "...return HTTP errors" - a refusal aimed at this auditor is not the
    # site's URL failing. Where a wall was detected, CR-BOT-WALL reports that
    # barrier once, with the right framing; repeating it here would report one
    # obstacle as two defects and score the site twice for it.
    wall = bool((bundle.get("access", {}) or {}).get("wall_suspected"))
    advertised_urls = _sitemap_urls(bundle) | _linked_from_other_pages(bundle)
    failed = [p for p in failed if (p.get("url") or "") in advertised_urls]
    errors = [e for e in errors if (e.get("url") or "") in advertised_urls]

    not_found, unverified = [], []
    for page in failed:
        verdict = semantics.transport_verdict(page.get("status"))
        if verdict["verdict"] == "not_found":
            not_found.append((page, verdict))
        elif not (wall and page.get("status") in REFUSAL_STATUSES):
            unverified.append((page, verdict))
    for entry in errors:
        verdict = semantics.transport_verdict(None, entry.get("error") or "no response")
        if verdict["verdict"] == "not_found":
            not_found.append((entry, verdict))
        elif not wall:
            unverified.append((entry, verdict))

    out: List[Finding] = []
    if not_found:
        ratio = len(not_found) / max(1, len(pages))
        out.append(finding(
            "CR-HTTP-ERRORS",
            "Pages the site itself advertises are not there",
            "high" if ratio > 0.15 else "medium", PILLAR,
            evidence=(f"{len(not_found)} of {len(pages)} fetched URL(s) answered "
                      f"{', '.join(v['reason'] for _, v in not_found[:6])}. Each of these URLs is "
                      "listed in the site's own sitemap or linked from one of its pages, so the "
                      "site is pointing at a page that its origin says does not exist."),
            items=[observed(f"{v['reason']} at {label(p)}", url=label(p),
                            locator=f"why fetched: {p.get('fetch_reason') or p.get('reason') or 'n/a'}")
                   for p, v in not_found[:6]],
            action=action(
                "Repair or remove the missing URLs from sitemaps and internal links.",
                priority="medium", effort="medium", impact="medium",
                mechanism="A URL the site advertises and then answers with 404 or 410 is a "
                          "statement the site contradicts itself on; each one is a request "
                          "spent on a page that did not serve.",
                steps=["Either restore the page or 301 it to the closest live equivalent.",
                       "Regenerate the sitemap so it no longer lists missing URLs.",
                       "Add a build-time check that every sitemap URL returns 200."],
                verification="Re-crawl: zero 404/410 among sitemap-listed and internally linked URLs."),
            urls=[label(p) for p, _ in not_found], confidence=0.98,
            metrics={"scope": "site", "failed": len(not_found), "sampled": len(pages)},
            tags=["http", "hygiene"]))
    if unverified:
        reasons = sorted({v["reason"] for _, v in unverified})
        out.append(finding(
            "CR-URLS-NOT-VERIFIED",
            "Some advertised URLs could not be verified by this audit",
            "info", PILLAR,
            evidence=(f"{len(unverified)} advertised URL(s) did not deliver an answer to this "
                      f"audit ({'; '.join(reasons[:4])}). A refusal, throttle, server error or "
                      "timeout says nothing about whether the page exists or what it contains; "
                      "these URLs are recorded as not verified, not as broken."),
            items=[observed(f"{v['reason']} at {label(p)}", url=label(p),
                            locator=f"why fetched: {p.get('fetch_reason') or p.get('reason') or 'n/a'}")
                   for p, v in unverified[:6]],
            action=action(
                "Confirm these URLs from a browser or the origin's own logs before treating "
                "them as a defect.",
                priority="low", effort="low", impact="low",
                mechanism="This audit is a single read-only pass with a modest request budget; "
                          "a refusal or timeout on that pass is a fact about this pass, not "
                          "about the page.",
                steps=["Check whether the response was aimed at automated clients (a 403 or "
                       "429 with a challenge page) and whether that is intended for the URL.",
                       "For 5xx or timeouts, re-check later and look at the origin's error log."],
                verification="Re-run the audit; a verified URL leaves this list."),
            urls=[label(p) for p, _ in unverified], confidence=0.5,
            metrics={"scope": "site", "unverified": len(unverified), "sampled": len(pages),
                     "reasons": reasons},
            tags=["http", "transport", "not-verified"]))
    return out or None


def rule_redirect_chains(bundle: dict) -> Optional[Finding]:
    """Multi-hop chains, characterised rather than merely counted.

    Two hops is two hops whether they are a scheme upgrade followed by a host
    normalisation - both of which the canonicalisation rules ask for - or two
    arbitrary rewrites. The count is the finding; what the hops *are* belongs
    in the evidence, because it decides whether there is anything to fix.

    A chain that ends at a front door is not reported here at all: that is a
    homepage collapse, `EG-DEEPLINK-REDIRECTED-HOME` owns it, and one redirect
    event reported under two headings is one obstacle scored twice.
    """
    # Every requested URL: a chained redirect is transport evidence whatever
    # document it ended on, so redirect endpoints typed `reference` count.
    pages = ev.pages(bundle, include_aliases=True, include_utility=True)
    verdicts = redirect_index(bundle)
    chained = [p for p in pages
               if len(p.get("redirects", []) or []) >= 2
               and verdicts.get(p.get("url") or "", {}).get("kind") != "homepage_collapse"]
    if not chained:
        return None
    kinds = {}
    for page in chained:
        kind = verdicts.get(page.get("url") or "", {}).get("kind", "unrelated")
        kinds[kind] = kinds.get(kind, 0) + 1
    routine = kinds.get("canonical_host", 0) + kinds.get("locale", 0)
    composition = ", ".join(f"{n} {kind.replace('_', ' ')}"
                            for kind, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
    note = ""
    if routine:
        note = (f" {routine} of them resolve to the same resource at its canonical address, "
                "so the destination is right and only the number of hops is in question.")
    return finding(
        "CR-REDIRECT-CHAINS",
        "Advertised URLs redirect through multiple hops before reaching content",
        "medium", PILLAR,
        evidence=f"{len(chained)} of {len(pages)} sampled URL(s) resolve through 2+ redirect "
                 f"hops ({composition}).{note} Each hop is an additional request.",
        items=[observed(
            f"{label(p)} -> " + " -> ".join(r.get("location", "?")
                                            for r in p.get("redirects", [])[:3])
            + f" [{verdicts.get(p.get('url') or '', {}).get('why', 'chain')}]",
            url=label(p), locator="redirect chain") for p in chained[:5]],
        interpretation="Each hop is an additional request, so a chain costs crawl budget and "
                       "adds latency to a live fetch. Whether any given fetcher gives up part "
                       "way through a chain is not something this audit measures.",
        action=action("Collapse redirect chains to a single hop to the canonical URL.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="Every hop is another request against a limited crawl budget "
                                "and another round trip in front of a live fetch.",
                      steps=["Update internal links and sitemaps to point at the final URL.",
                             "Replace chained rules (http->https->www->path) with one rule "
                             "that jumps straight to the canonical form."],
                      verification="curl -sIL <url> shows exactly one 301 before the 200."),
        urls=[label(p) for p in chained], confidence=0.9,
        metrics={"scope": "site", "affected": len(chained), "sampled": len(pages),
                 "redirect_kinds": kinds}, tags=["redirects"])


#: Statuses that mean "something refused this request", not "the site answered
#: and this is its canonicalisation behaviour". A bot wall, a corporate proxy, a
#: rate limiter or a broken origin all produce one of these, and none of them is
#: evidence about whether http:// redirects to https://. Reading a 403 as a
#: canonicalisation defect produced a `high` finding against a site that
#: redirects correctly - the exact confident-wrong-finding the brief punishes.
REFUSAL_STATUSES = frozenset({401, 403, 407, 408, 429, 451,
                              500, 502, 503, 504, 520, 521, 522, 523, 525, 530})


def _probe_is_conclusive(bundle: dict, probe: dict) -> bool:
    """Did this probe observe the *site*, or something standing in front of it?

    A probe is only evidence about canonicalisation when the origin answered
    for itself. Three things disqualify it: a transport failure, a status that
    means refusal rather than an answer, and a robots.txt on the same host that
    never reached the origin either - which is the signal that the whole audit
    is looking at a wall rather than at the site.
    """
    if not probe or probe.get("error"):
        return False
    if probe.get("status", 0) == 0:
        return False
    if probe.get("status") in REFUSAL_STATUSES:
        return False
    robots = bundle.get("robots", {}) or {}
    if not _origin_answered(robots):
        return False
    return True


def rule_https_upgrade(bundle: dict) -> Optional[Finding]:
    if bundle.get("site", {}).get("scheme") != "https":
        return None  # the audit target was explicitly http:// - not our call to make
    probe = bundle.get("host_probes", {}).get("http")
    if not _probe_is_conclusive(bundle, probe):
        return None
    if probe.get("upgrades_to_https"):
        return None
    return finding(
        "CR-NO-HTTPS-UPGRADE",
        "The http:// origin does not redirect to https://",
        "high", PILLAR,
        evidence=f"GET {probe['url']} ended at {probe.get('final_url')} with status "
                 f"{probe.get('status')} without upgrading to HTTPS, so the site is reachable "
                 "under two different origins with the same content.",
        items=[observed(f"http origin resolved to {probe.get('final_url')} "
                        f"(status {probe.get('status')})", url=probe["url"],
                        locator="http->https probe")],
        action=action("Redirect every http:// URL to its https:// equivalent with a single 301.",
                      priority="high", effort="low", impact="high",
                      mechanism="Two origins serving the same content are two addresses for one "
                                "site, so nothing states which is canonical; a single 301 makes "
                                "the https origin the explicit one.",
                      steps=["Add an edge/server rule: 301 http://<host>/* -> https://<host>/$1.",
                             "Enable HSTS once the redirect is verified.",
                             "Update sitemaps, canonical tags and internal links to https."],
                      verification="curl -sI http://<host>/ returns 301 to the https URL."),
        urls=[probe["url"]], confidence=0.95,
        metrics={"scope": "site"}, tags=["https", "canonicalisation"])


def rule_host_duplication(bundle: dict) -> Optional[Finding]:
    probe = bundle.get("host_probes", {}).get("alt_host")
    if not probe or probe.get("error") or not probe.get("resolves"):
        return None
    if probe.get("redirects_to_primary") and not probe.get("same_host_as_primary"):
        return None
    if not probe.get("same_host_as_primary") and probe.get("final_url", "").startswith(
            bundle["site"]["origin"]):
        return None
    if probe.get("final_url", "").rstrip("/") == bundle["site"]["origin"].rstrip("/"):
        return None
    return finding(
        "CR-HOST-DUPLICATION",
        "The www and apex hostnames both serve content instead of one redirecting to the other",
        "medium", PILLAR,
        evidence=f"{probe['url']} returned status {probe.get('status')} and stayed on "
                 f"{probe.get('final_url')} rather than redirecting to "
                 f"{bundle['site']['origin']}, so the same catalogue exists under two hostnames.",
        items=[observed(f"alternate host {probe['url']} served content at "
                        f"{probe.get('final_url')} (status {probe.get('status')})",
                        url=probe["url"], locator="www/apex probe")],
        action=action("Pick one canonical hostname and 301 the other to it.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="Duplicate hostnames are two addresses for one site, and a "
                                "link to either is a link to a different URL; a 301 from one to "
                                "the other states explicitly which is canonical.",
                      steps=["Choose the hostname already used in your sitemap and canonicals.",
                             "301 every request on the other hostname to the same path on the "
                             "canonical one.",
                             "Confirm canonical tags, sitemap URLs and OG urls all use it."],
                      verification="curl -sI https://<other-host>/ returns 301 to the canonical "
                                   "host."),
        urls=[probe["url"]], confidence=0.85,
        metrics={"scope": "site"}, tags=["canonicalisation", "entity-split"])


def rule_soft_404(bundle: dict) -> Optional[Finding]:
    probe = bundle.get("not_found_probe", {})
    if not probe.get("checked") or probe.get("error"):
        return None
    if probe.get("returns_404"):
        return None
    status = probe.get("status") or 0
    # A soft 404 is the site *serving a page* for a URL that does not exist -
    # a 2xx, or a redirect that dumps the probe on the home page. A refusal
    # (403, 429, 451), a timeout (408), a server error (5xx) or any other
    # non-success is not the site saying "this page exists"; reading it as one
    # produced "returns a success status instead of 404" about a 451.
    if not (200 <= status < 300) and not probe.get("redirected_to_home"):
        return None
    return finding(
        "CR-SOFT-404",
        "Unknown URLs return a success status instead of 404",
        "medium", PILLAR,
        evidence=f"A deliberately non-existent URL ({probe.get('url')}) returned HTTP {status} "
                 f"ending at {probe.get('final_url')}, the status a real page returns - so a "
                 "mistyped, retired or invented URL cannot be told from a real one by its "
                 "status code.",
        items=[observed(f"probe URL returned HTTP {status} instead of 404",
                        url=probe.get("url", ""), locator="soft-404 probe")],
        action=action("Return a real 404 (or 410) status for URLs that do not exist.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="A 404 is the one signal that says a URL does not exist. Serving "
                                "a success status instead gives a crawler near-duplicate pages "
                                "to store, and leaves a wrong or invented link indistinguishable "
                                "from a right one at the transport level.",
                      steps=["Ensure the not-found handler sets status 404, not 200.",
                             "If a URL is permanently gone, return 410.",
                             "Keep a helpful body - the status code is the part of the "
                             "response that states the outcome unambiguously."],
                      verification="curl -sI https://<host>/definitely-not-a-page returns 404."),
        urls=[probe.get("url", "")], confidence=0.9,
        metrics={"scope": "site"}, tags=["http", "hygiene"])


#: Page types whose whole purpose is to be found and cited.
DISCOVERABLE_PAGE_TYPES = ("home", "product", "category", "faq", "policy",
                           "about", "contact", "article")


#: Endpoint types that exist to run something rather than to be cited. Kept as
#: one tuple because two rules read it: a noindexed one of these is routine,
#: and an ineligible one is not a canonical candidate. They were two separate
#: lists and drifted - `tool` was in the canonical list and not this one, so a
#: noindexed configurator or planner was reported as a page losing its index
#: place when excluding it is exactly what a site should do.
UTILITY_ENDPOINT_TYPES = ("search", "tool", "account", "reference")


def _is_parameterised_variant(page: dict) -> bool:
    """Is this URL the site's own filtered/sorted permutation of another page?

    A faceted listing generates a combinatorial number of addresses -
    ``?colour=black&size=9&sort=price`` - and excluding those from an index is
    ordinary practice, not a defect. The test is the site's *own* statement
    rather than a guess about parameter names: the URL carries a query string
    and its declared canonical is a different URL. That is the page saying "the
    document worth indexing is over there", which is precisely what a thin
    permutation says about itself.
    """
    url = page.get("final_url") or page.get("url") or ""
    parts = urlsplit(url)
    if not parts.query:
        return False
    canonical = str(page.get("canonical") or "").strip()
    if not canonical:
        return False
    return util.normalize_url(canonical) != util.normalize_url(url)


def _noindex_role(page: dict) -> str:
    """Is this a page a site *wants* indexed, or one it routinely excludes?

    Carts, checkouts, accounts, logins, internal search results, tool endpoints
    and the filtered permutations of a faceted listing are conventionally
    excluded from indexes, and doing so is good practice rather than a defect.
    Reporting them alongside a noindexed product page treats a correct decision
    as a problem, and buries the one finding that matters.
    """
    url = page.get("final_url") or page.get("url") or ""
    path = urlsplit(url).path or "/"
    if NON_CITABLE_PATH_RE.search(path) or \
            page.get("page_type") in UTILITY_ENDPOINT_TYPES:
        return "utility"
    if _is_parameterised_variant(page):
        return "utility"
    if page.get("page_type") in DISCOVERABLE_PAGE_TYPES:
        return "discoverable"
    return "other"


def rule_noindex(bundle: dict) -> Optional[Finding]:
    """Report noindex where it costs the site something, and say it may be deliberate.

    Two changes from naive detection, both about not asserting more than was
    observed. First, an observed noindex is not an *accidental* noindex: this
    audit reads a directive, not an intention, so it asks the owner to confirm
    rather than telling them a staging config leaked. Second, severity follows
    the evidence - how many discoverable pages are affected, and whether the
    sample is big enough to call it a template-wide problem - instead of
    jumping to critical the moment one page matches.
    """
    # Every parsed document, so a noindexed search page or account form is
    # counted as the conventional exclusion it is rather than dropped from
    # the aside that says so.
    pages = ev.pages(bundle, include_aliases=True, include_utility=True)
    blocked = []
    for page in pages:
        directives = _index_directive_text(page)
        if _has_noindex(directives):
            blocked.append((page, directives.strip(", "), _noindex_role(page)))
    if not blocked:
        return None

    discoverable = [(p, d) for p, d, role in blocked if role == "discoverable"]
    other = [(p, d) for p, d, role in blocked if role == "other"]
    utility = [(p, d) for p, d, role in blocked if role == "utility"]
    reportable = discoverable + other
    if not reportable:
        # Everything carrying noindex is a cart, account, login or internal
        # search page. That is the conventional configuration, not a finding.
        return None

    considered = [p for p in pages if _noindex_role(p) != "utility"]
    ratio = len(discoverable) / max(1, len([p for p in considered
                                            if _noindex_role(p) == "discoverable"]))
    if not discoverable:
        severity = "low"
    elif ratio >= 0.85 and len(discoverable) >= 3:
        # Widespread across a sample big enough to mean the template, not a page.
        severity = "critical"
    elif ratio >= 0.5 or len(discoverable) >= 3:
        severity = "high"
    else:
        severity = "medium"

    aside = (f" {len(utility)} further page(s) carrying noindex are carts, accounts, logins or "
             f"internal search results, which are conventionally excluded and are not counted "
             f"here." if utility else "")
    return finding(
        "CR-NOINDEX-ON-IMPORTANT-PAGES",
        "Content pages a site would usually want indexed carry a noindex directive",
        severity, PILLAR,
        evidence=(f"{len(reportable)} of {len(considered)} sampled page(s) outside carts, "
                  f"accounts and internal search carry a noindex directive"
                  + (f", including {len(discoverable)} content page(s) of a kind a site "
                     f"usually publishes to be found "
                     f"({', '.join(sorted({p.get('page_type') or 'other' for p, _ in discoverable}))})."
                     if discoverable else ".") + aside
                  + " Whether the exclusion is intentional is not something this audit can "
                    "tell from the directive."),
        interpretation="A noindex directive asks indexes not to keep the page, so an index "
                       "that honours it does not hold the page, while a person visiting "
                       "directly reads it as normal. This audit observes the "
                       "directive, not the intent behind it: the exclusion may be deliberate, "
                       "and the point of the finding is that the decision should be a conscious "
                       "one for pages the business wants cited.",
        items=[observed(f"noindex directive `{directives}` on a "
                        f"{p.get('page_type') or 'unclassified'} page",
                        url=label(p), locator="meta robots / X-Robots-Tag")
               for p, directives in reportable[:6]],
        action=action("Review whether this exclusion is intentional on each of these pages.",
                      priority="high" if discoverable else "low", effort="low", impact="high",
                      mechanism="A page a directive asks indexes not to keep cannot be retrieved from one that honours it. "
                                "Where the exclusion is deliberate that is the correct outcome; "
                                "where it is inherited from a template or a CDN-wide header it "
                                "removes pages the business wants cited, with no visible symptom.",
                      steps=["Confirm for each listed page whether the exclusion is intended.",
                             "Where it is not, make the robots meta value explicit per page "
                             "type in the template rather than inherited.",
                             "Check the X-Robots-Tag response header as well - it overrides the "
                             "meta tag and is easy to set globally by mistake at the CDN.",
                             "Keep noindex where it belongs: carts, accounts, internal search "
                             "results and thin filter permutations."],
                      verification="For each page you decided should be indexable, curl -sI <url> "
                                   "returns no noindex X-Robots-Tag and the HTML contains no "
                                   "noindex meta.",
                      verification_type="self_verifiable"),
        urls=[label(p) for p, _ in reportable], confidence=0.98,
        metrics={"scope": "template" if len(discoverable) >= 3 else "page",
                 "affected": len(reportable), "sampled": len(considered),
                 "discoverable_pages_noindexed": len(discoverable),
                 "utility_pages_excluded_from_finding": len(utility),
                 "discoverable_ratio": round(ratio, 2)},
        tags=["indexability", "blocking"])


#: Page types whose document is *content* a canonical URL is expected to
#: identify: the pages a site publishes to be found and cited. A search
#: results page is a query endpoint, a `tool` is an application surface, and
#: `other`/unclassified is a page the classifier could not place - none of
#: them is a page whose missing canonical says anything about the site's
#: canonicalisation, and none is cited as one.
CANONICAL_CONTENT_TYPES = frozenset({
    "home", "product", "category", "policy", "faq", "article", "about",
    "contact", "support", "program", "promotional",
})

#: Redirect kinds under which the fetched document is still the requested
#: page's own document (an address normalisation), so its canonical can be
#: judged against where it landed.
_SAME_DOCUMENT_REDIRECTS = frozenset({"none", "canonical_representation",
                                      "canonical_host", "locale"})


def _index_directive_text(page: dict) -> str:
    """The page's robots-index directives, from meta and the X-Robots-Tag header.

    One reader for the whole file, so ``rule_noindex`` and canonical
    eligibility can never disagree about whether a page is noindexed - they
    did, because one stripped the comma-separated tokens before testing for
    `none` and the other did not, so `<meta name="robots" content="none">`
    (a valid noindex) was hidden from the finding but honoured by the
    canonical rule. ``headers`` is read with an ``or {}`` guard so a bundle
    that ever carries it as null cannot raise here.
    """
    return ",".join([
        str(page.get("meta_robots") or ""),
        str(page.get("meta_googlebot") or ""),
        str((page.get("headers") or {}).get("x-robots-tag") or ""),
    ]).lower()


def _has_noindex(directives: str) -> bool:
    """``noindex`` anywhere, or a bare ``none`` token (noindex+nofollow)."""
    return "noindex" in directives or "none" in [d.strip() for d in directives.split(",")]


def _is_noindexed(page: dict) -> bool:
    return _has_noindex(_index_directive_text(page))


def canonical_eligibility(page: dict, redirects: dict) -> str:
    """Why a page is, or is not, one whose canonical this audit may judge.

    Returns ``"eligible"`` or the reason it is not, in the page's own
    evidence: what the crawl classified it as, whether it asked not to be
    indexed, and whether the document fetched is even its own. Nothing here
    reads the URL's shape.
    """
    if page.get("fetch_failed") or page.get("non_html") or int(page.get("status") or 0) >= 400:
        return "not a readable document"
    page_type = page.get("page_type") or ""
    if page_type not in CANONICAL_CONTENT_TYPES:
        if page_type == "reference":
            # Another page's document at a second address. Its canonical
            # pointing at that page is the correct statement, not a defect.
            return (f"a navigation/reference address of {page.get('alias_of') or 'another page'}, "
                    f"not a document of its own")
        if page_type in UTILITY_ENDPOINT_TYPES:
            return f"{'an' if page_type == 'account' else 'a'} {page_type} endpoint, not a content page"
        return f"page type '{page_type or 'unclassified'}' is not an established content type"
    if _is_noindexed(page):
        return "carries a noindex directive, so it is not competing for a canonical URL"
    verdict = redirects.get(page.get("url") or "")
    if verdict and verdict.get("kind") not in _SAME_DOCUMENT_REDIRECTS:
        return (f"redirected elsewhere ({verdict.get('kind')}), so the document fetched "
                f"is another page's")
    return "eligible"


def rule_canonical(bundle: dict) -> List[Finding]:
    """Canonical findings, on the pages a canonical is a statement about.

    Observed on a live audit: a navigation endpoint and an unclassified page
    were counted among "pages with no canonical", and the ratio that followed
    described a template defect the content pages did not have. Eligibility
    is decided from each page's own evidence - see
    :func:`canonical_eligibility` - and the pages set aside are counted in the
    evidence so the reader can see what the ratio was computed over.
    """
    redirects = redirect_index(bundle)
    # Aliases are considered so they are *counted* among the pages set aside,
    # with the reason; eligibility is what keeps them out of the ratio.
    considered = [p for p in ev.pages(bundle, include_aliases=True, include_utility=True)
                  if p.get("page_type") not in ("error", "non_html")]
    verdicts = {label(p): canonical_eligibility(p, redirects) for p in considered}
    pages = [p for p in considered if verdicts[label(p)] == "eligible"]
    set_aside = [(p, verdicts[label(p)]) for p in considered if verdicts[label(p)] != "eligible"]
    if not sample_guard(pages, 2):
        return []
    out: List[Finding] = []
    missing = [p for p in pages if not p.get("canonical")]
    wrong: List[tuple] = []
    cross_host: List[tuple] = []
    for page in pages:
        canonical = page.get("canonical")
        if not canonical:
            continue
        own = page.get("final_url") or page.get("url")
        if canonical == own:
            continue
        if not util.same_site(canonical, own):
            # A canonical on another host is a statement that the content
            # lives there: syndication, a migration, a consolidated brand
            # domain. It may be exactly right, and this audit cannot fetch
            # the other host to check, so it is reported as an observation
            # to review rather than as a wrong target.
            cross_host.append((page, canonical, "points to a different host"))
        elif util.url_path(canonical) in ("/", "") and util.url_path(own) not in ("/", ""):
            wrong.append((page, canonical, "collapses a deep page onto the home page"))

    types_sampled = ", ".join(sorted({p.get("page_type") or "" for p in pages}))
    aside = ""
    if set_aside:
        reasons = {}
        for _, why in set_aside:
            reasons[why] = reasons.get(why, 0) + 1
        aside = (f" {len(set_aside)} further sampled page(s) were not assessed: "
                 + "; ".join(f"{count} {why}" for why, count in sorted(reasons.items()))
                 + ".")
    if missing and len(missing) / len(pages) >= 0.4:
        ratio = len(missing) / len(pages)
        out.append(finding(
            "CR-CANONICAL-MISSING",
            "Most content pages declare no canonical URL",
            severity_from_sample(ratio, len(pages), critical=1.01, high=0.8, medium=0.4), PILLAR,
            evidence=f"{len(missing)} of {len(pages)} sampled content page(s) ({types_sampled}) "
                     "have no <link rel=\"canonical\">, so any URL variant (tracking "
                     "parameters, sort orders, session ids) of those pages looks like a "
                     "separate page." + aside,
            items=page_items(missing, "no rel=canonical link element on {url}", limit=5),
            action=action("Emit a self-referencing absolute canonical on every indexable page.",
                          priority="medium", effort="low", impact="medium",
                          mechanism="Without a canonical, every parameterised variant of a URL "
                                    "competes as its own document, splitting the signals that "
                                    "would otherwise concentrate on one citable page.",
                          steps=["Add <link rel=\"canonical\" href=\"<absolute canonical URL>\"> "
                                 "to the template head.",
                                 "Use the https, canonical-host, parameter-free form.",
                                 "Make paginated pages self-canonical, not canonical to page 1."],
                          verification="Fetch a product URL with ?utm_source=test appended; the "
                                       "canonical in the response must be the clean URL."),
            urls=[label(p) for p in missing],
            confidence=confidence_for(len(missing), len(pages)),
            metrics={"scope": scope_for(len(missing), len(pages)),
                     "affected": len(missing), "sampled": len(pages),
                     "sample_unit": "sampled content page(s)",
                     "not_assessed": len(set_aside),
                     "eligible_types": sorted({p.get("page_type") or "" for p in pages})},
            tags=["canonicalisation"]))

    if wrong:
        kinds = sorted({p.get("page_type") or "" for p, _, _ in wrong})
        product_pages = [p for p, _, _ in wrong if p.get("page_type") == "product"]
        what = ("Product detail pages" if product_pages and len(product_pages) == len(wrong)
                else f"Content pages ({', '.join(kinds)})")
        out.append(finding(
            "CR-CANONICAL-WRONG-TARGET",
            "Canonical tags collapse content pages onto the home page",
            "high", PILLAR,
            evidence=f"{len(wrong)} of {len(pages)} sampled content page(s) "
                     f"({', '.join(kinds)}) declare the home "
                     "page as their canonical URL, a statement that the home page is the "
                     "preferred address for content it does not carry." + aside,
            interpretation="A canonical names the URL the site prefers for this content. When "
                           "a page with content of its own names the home page, the markup "
                           "states that this page's content is a duplicate of the front door, "
                           "which it is not. How any index acts on that statement is not "
                           "something this audit measures.",
            items=[observed(f"canonical on {label(p)} -> {canonical} ({why})",
                            url=label(p), locator="link rel=canonical")
                   for p, canonical, why in wrong[:6]],
            action=action("Make each page canonical to itself unless it is a genuine duplicate.",
                          priority="high", effort="low", impact="high",
                          mechanism=f"{what} whose canonical is the home page state that their "
                                    "content is the home page's; a self-referencing canonical "
                                    "states, explicitly, that each page is its own preferred "
                                    "address.",
                          steps=["Remove hardcoded canonicals from shared templates.",
                                 "Generate the canonical from the page's own route, not from a "
                                 "site-wide constant."],
                          verification="For each URL listed, the canonical equals the URL itself."),
            urls=[label(p) for p, _, _ in wrong], confidence=0.95,
            metrics={"scope": scope_for(len(wrong), len(pages)), "affected": len(wrong),
                     "sampled": len(pages), "sample_unit": "sampled content page(s)",
                     "not_assessed": len(set_aside)},
            tags=["canonicalisation", "blocking"]))

    if cross_host:
        hosts = sorted({util.registrable_host(c) for _, c, _ in cross_host})
        affected_types = ", ".join(sorted({p.get("page_type") or "" for p, _, _ in cross_host}))
        out.append(finding(
            "CR-CANONICAL-CROSS-HOST",
            "Canonical tags point to another host",
            "low", PILLAR,
            evidence=f"{len(cross_host)} of {len(pages)} sampled content page(s) "
                     f"({affected_types}) declare a "
                     f"canonical URL on another host ({', '.join(hosts[:3])}). This may be "
                     "intentional - syndicated content, a migrated section, a consolidated "
                     "brand domain - and this audit did not fetch the other host, so whether "
                     "the target carries the same content could not be verified." + aside,
            interpretation="A cross-host canonical states that the preferred address for this "
                           "content is on another site. Where that is the intent it is the "
                           "correct statement; where it is inherited from a template or a "
                           "staging configuration it hands this site's content to another "
                           "address. Only the site owner can say which.",
            items=[observed(f"canonical on {label(p)} -> {canonical} ({why})",
                            url=label(p), locator="link rel=canonical")
                   for p, canonical, why in cross_host[:6]],
            action=action("Review whether each cross-host canonical is intentional.",
                          priority="low", effort="low", impact="medium",
                          mechanism="A cross-host canonical is correct exactly when the other "
                                    "host genuinely carries the same content and you mean it to "
                                    "be the preferred address; confirming that is a decision, "
                                    "not a fix.",
                          steps=["For each page listed, confirm the target host carries the same "
                                 "content and is the address you want cited.",
                                 "Where it is not, generate the canonical from the page's own "
                                 "route."],
                          verification="Each cross-host canonical target loads the same content "
                                       "in a browser, or the canonical now names the page itself."),
            urls=[label(p) for p, _, _ in cross_host], confidence=0.7,
            metrics={"scope": scope_for(len(cross_host), len(pages)), "affected": len(cross_host),
                     "sampled": len(pages), "sample_unit": "sampled content page(s)",
                     "target_hosts": hosts[:6], "not_assessed": len(set_aside)},
            tags=["canonicalisation", "review"]))
    return out


#: Page types whose word count is a meaningful signal. A privacy page, a
#: contact page or a short about page is *allowed* to be brief - measuring them
#: against a flat 120-word floor turned ordinary short pages on a fully
#: server-rendered site into evidence of a blank shell. The types kept here
#: carry the content a site exists to publish, so if they are thin, something
#: really is missing; and a site that genuinely ships a shell ships it on these
#: routes too, so nothing is lost by not counting the short ones.
_VOLUME_BEARING_TYPES = ("home", "product", "category", "article")


def rule_js_dependence(bundle: dict) -> List[Finding]:
    pages = [p for p in ev.pages(bundle) if p.get("page_type") in _VOLUME_BEARING_TYPES]
    if not sample_guard(pages, 1):
        return []
    out: List[Finding] = []

    shells = []
    for page in pages:
        scripts = page.get("scripts", {}) or {}
        # ``spa_markers`` now means *empty mount point confirmed in the DOM*.
        # A hydration payload on its own is not a shell signal: every
        # server-rendered Next.js or Nuxt page ships one, and treating it as
        # sufficient reported fully server-rendered sites as blank.
        markers = scripts.get("spa_markers", []) or []
        if not markers:
            continue
        words = page.get("text_word_count", 0) or 0
        if words < 120:
            shells.append((page, markers, words))

    if shells:
        ratio = len(shells) / len(pages)
        out.append(finding(
            "CR-JS-RENDERED-SHELL",
            "Page content is delivered through an empty client-rendering shell",
            severity_from_sample(ratio, len(pages), critical=0.5, high=0.25,
                                 medium=0.0), PILLAR,
            evidence=(f"{len(shells)} of {len(pages)} sampled page(s) contain client-rendering "
                      f"markers and fewer than 120 words of text in the raw HTML "
                      f"(e.g. {label(shells[0][0])}: {shells[0][2]} words, markers: "
                      f"{', '.join(shells[0][1][:2])}). A fetch that does not execute "
                      "JavaScript receives only this raw response."),
            items=[observed(f"{words} words of text in raw HTML; client-render markers: "
                            f"{', '.join(markers[:3])}", url=label(page),
                            locator="raw HTML response")
                   for page, markers, words in shells[:5]],
            action=action(
                "Server-render (or pre-render) the facts that must be quotable.",
                priority="critical", effort="high", impact="high",
                mechanism="This is a statement about how the page is *delivered*, not about "
                          "how much is missing from it: the response contains an unfilled "
                          "mount point and almost no text, and the content is assembled "
                          "afterwards by script. A fetch that does not execute JavaScript "
                          "receives the pre-hydration HTML, so any fact that only exists after "
                          "hydration is not in the bytes it receives.",
                steps=["Move the page's name, its key facts, breadcrumbs and the JSON-LD "
                       "block into the server-rendered HTML.",
                       "If a full SSR migration is out of scope, add a pre-render/static "
                       "snapshot layer for the content routes - that is where the citable "
                       "facts live.",
                       "Verify with `curl -s <url> | grep -i '<price>'` rather than with a "
                       "browser: the browser will always look fine.",
                       "Keep interactive extras (recommendations, live chat) client-side; only "
                       "the facts need to be in the HTML."],
                verification="curl -s <product url> | grep -c 'application/ld+json' returns >= 1 "
                             "and the price string appears in the raw HTML."),
            urls=[label(p) for p, _, _ in shells],
            confidence=confidence_for(len(shells), len(pages), base=0.85),
            metrics={"scope": scope_for(len(shells), len(pages)),
                     "affected": len(shells), "sampled": len(pages),
                     "sample_unit": "sampled content page(s)",
                     "measures": "delivery architecture: an unfilled mount point and "
                                 "under 120 words in the response",
                     # Read from the raw response alone, so this stands whether
                     # or not a browser ran. `CR-JS-CONTENT-GAP` measures the
                     # size of what is missing and needs one.
                     "measured_from": "server response only"},
            tags=["rendering", "blocking", "architecture"]))

    render = bundle.get("render", {})
    if render.get("available"):
        gaps = [c for c in render.get("comparisons", [])
                if c.get("ok") and c.get("content_gain_ratio", 1) >= 2.0]
        if gaps:
            out.append(finding(
                "CR-JS-CONTENT-GAP",
                "Browser rendering reveals substantially more content than the server response",
                "high", PILLAR,
                evidence="; ".join(
                    f"{c['url']}: {c['raw_word_count']} words raw vs "
                    f"{c['rendered_word_count']} rendered ({c['content_gain_ratio']}x)"
                    for c in gaps[:3])
                + (" This measures the *size* of the difference between two states of the "
                   "same URL. Whether the response is a client-rendering shell is a separate "
                   "observation, reported as CR-JS-RENDERED-SHELL."
                   if shells else
                   " This measures the size of the difference between two states of the same "
                   "URL; the responses carry content, so this is a gap rather than an empty "
                   "shell."),
                items=[measured(f"raw {c['raw_word_count']} words vs rendered "
                                f"{c['rendered_word_count']} words "
                                f"({c['content_gain_ratio']}x gain)",
                                value=c["content_gain_ratio"], url=c["url"]) for c in gaps[:5]],
                action=action(
                    "Move the content that only appears after hydration into the server response.",
                    priority="high", effort="high", impact="high",
                    mechanism="The ratio is a quantity, and that is what this finding adds: it "
                              "says how much of the page is absent from the response, and it "
                              "goes down as the content moves server-side, so progress on the "
                              "underlying delivery change is measurable rather than asserted.",
                    steps=["Diff `curl -s <url>` against the rendered DOM and list which facts "
                           "are missing from the raw response.",
                           "Prioritise: price, availability, specs, reviews, policy text.",
                           "Re-measure after each change - the ratio is the metric."],
                    verification="Re-run the audit with --render; content_gain_ratio should "
                                 "approach 1.0 for product pages."),
                urls=[c["url"] for c in gaps], confidence=0.95,
                metrics={"scope": "template", "affected": len(gaps),
                         "sampled": len(render.get("comparisons") or []),
                         "sample_unit": "page(s) rendered in a headless browser",
                         "measures": "content magnitude: rendered words against response words",
                         "measured_from": "server response compared with the rendered DOM",
                         "largest_gain_ratio": max(c["content_gain_ratio"] for c in gaps),
                         # Same page, same remediation, different measurement.
                         # The report links the two and charges the score once;
                         # both keep their own evidence. See
                         # `aiva.findings.CORROBORATION`.
                         "corroborates": "CR-JS-RENDERED-SHELL"},
                tags=["rendering", "measured", "magnitude"]))

    fact_gap = rule_rendered_fact_gap(bundle)
    if fact_gap:
        out.append(fact_gap)
    return out


def rule_rendered_fact_gap(bundle: dict) -> Optional[Finding]:
    """Which *named facts* the server response omits and the rendered DOM has.

    `CR-JS-CONTENT-GAP` above measures the size of the difference; this one
    measures its content. The distinction matters to whoever has to act: a page
    that renders twice as many words may have added a footer, while a page
    whose price, stock and rating appear only after hydration has a specific,
    listable set of facts absent from the response a fetch receives.

    It is a *measurement*, not the static heuristic - it exists only when the
    browser pass actually ran - and it makes no claim about how anything else
    treats either state. The page is not missing the fact; the server response
    is.
    """
    coverage = render_coverage(bundle)
    if not coverage["available"]:
        return None
    rendered_pages = [p for p in (bundle.get("pages") or []) if render_state(p) == "rendered"]
    with_gaps = [(p, rendered_fact_gaps(p)) for p in rendered_pages]
    with_gaps = [(p, gaps) for p, gaps in with_gaps if gaps]
    if not with_gaps:
        return None
    every_fact = sorted({g["label"] for _, gaps in with_gaps for g in gaps})
    ratio = len(with_gaps) / max(1, len(rendered_pages))
    return finding(
        "CR-RENDER-FACT-GAP",
        "Facts are present in the browser-rendered page but not in the server HTML",
        severity_from_sample(ratio, len(rendered_pages), critical=1.01, high=0.6, medium=0.3),
        PILLAR,
        evidence=f"On {len(with_gaps)} of {len(rendered_pages)} page(s) rendered in a headless "
                 f"browser, at least one audited fact was observed in the rendered DOM and not "
                 f"in the server response: {', '.join(every_fact)}. This is a comparison of two "
                 f"states of the same URL, measured in the same run; it is not a statement "
                 f"about how any other system reads either of them.",
        interpretation="These facts are on the page - a visitor whose browser runs the scripts "
                       "sees them. What the measurement shows is that they are not in the "
                       "document the server returns, so anything reading that document without "
                       "executing JavaScript has a page missing exactly this list. Reporting "
                       "them as absent from the site would be false; reporting them as absent "
                       "from the response is what was observed.",
        items=[observed(
            "{}: {} present in the rendered DOM, absent from the server HTML".format(
                label(page), ", ".join(g["label"] for g in gaps)),
            url=label(page), locator="server response vs rendered DOM")
            for page, gaps in with_gaps[:5]],
        action=action("Serve these facts in the initial HTML response as well as in the "
                      "rendered page.",
                      priority="high", effort="high", impact="high",
                      mechanism="A fact that exists only after hydration is absent from the "
                                "document the server returns, so any reader of that document "
                                "which does not execute scripts does not receive it. Emitting "
                                "the same values server-side puts the fact in both states.",
                      steps=["Take the list above per URL - it is exactly what the response is "
                             "missing relative to the rendered page.",
                             "Server-render or pre-render those values; the client widget can "
                             "still hydrate over them.",
                             "Mirror the same values into typed markup (Offer, "
                             "AggregateRating, additionalProperty) so they are addressable "
                             "without parsing prose.",
                             "Re-run with --render: a fact fixed this way stops appearing in "
                             "this list."],
                      verification="`curl -s <url>` contains the values, and re-running the "
                                   "audit with --render lists no gap for that page.",
                      verification_type="self_verifiable"),
        urls=[label(p) for p, _ in with_gaps],
        confidence=0.95,
        metrics={"scope": scope_for(len(with_gaps), len(rendered_pages)),
                 "affected": len(with_gaps), "sampled": len(rendered_pages),
                 "sample_unit": "page(s) rendered in a headless browser",
                 "rendered_only_facts": every_fact,
                 "per_page": {label(p): [g["fact"] for g in gaps]
                              for p, gaps in with_gaps[:8]},
                 "render_mode": coverage["render_mode"],
                 "viewport": coverage["viewport"]},
        tags=["rendering", "measured", "raw-vs-rendered"])


def rule_thin_raw_html(bundle: dict) -> Optional[Finding]:
    products = ev.product_pages(bundle)
    if not sample_guard(products, 2):
        return None
    thin = [p for p in products if (p.get("text_word_count", 0) or 0) < 200
            and not (p.get("scripts", {}).get("spa_markers"))]
    if not thin or len(thin) / len(products) < 0.4:
        return None
    ratio = len(thin) / len(products)
    return finding(
        "CR-THIN-PRODUCT-HTML",
        "Product pages carry very little extractable text",
        severity_from_sample(ratio, len(products), critical=1.01, high=0.7, medium=0.4), PILLAR,
        evidence=f"{len(thin)} of {len(products)} product page(s) contain fewer than 200 words "
                 f"of text in the response body (median "
                 f"{int(statistics.median([p.get('text_word_count', 0) for p in thin]))} words).",
        interpretation="A page carrying a title, a price and a few bullet points states very "
                       "little that a question could be matched against, so a fuller "
                       "description of the same product elsewhere would state more. Whether "
                       "any system prefers the fuller page is not something this audit "
                       "measures.",
        items=[measured(f"{p.get('text_word_count', 0)} words of body text",
                        value=p.get("text_word_count", 0), url=label(p)) for p in thin[:5]],
        action=action("Give each product page enough plain-text substance to answer a question.",
                      priority="high", effort="medium", impact="high",
                      mechanism="Plain-text substance is what a question can be matched "
                                "against; a page with a title, a price and three bullet points "
                                "states almost nothing to match.",
                      steps=["Add a 100-200 word description that states what the product is, "
                             "who it is for and what makes it different - in plain sentences.",
                             "Publish the full specification as text (not an image or a PDF).",
                             "Include the questions buyers actually ask, with answers.",
                             "Keep the text in the server response, not in a tab loaded on click."],
                      verification="curl -s <url> | wc -w exceeds ~400 for a product page."),
        urls=[label(p) for p in thin],
        confidence=confidence_for(len(thin), len(products)),
        metrics={"scope": scope_for(len(thin), len(products)),
                 "affected": len(thin), "sampled": len(products),
                 "sample_unit": "sampled product page(s)"},
        tags=["content-depth"])


def rule_discovery_depth(bundle: dict) -> Optional[Finding]:
    home = ev.home_page(bundle)
    if not home or home.get("fetch_failed"):
        return None
    internal = home.get("links", {}).get("internal", []) or []
    if not internal:
        return finding(
            "CR-HOME-NO-INTERNAL-LINKS",
            "The home page exposes no crawlable internal links",
            "critical", PILLAR,
            evidence=f"The home page ({label(home)}) contains 0 same-site <a href> links in its "
                     "raw HTML, so a crawler arriving there has nowhere to go.",
            items=[absent("no internal <a href> links found in the home page response",
                          url=label(home), locator="raw HTML response")],
            action=action("Render the primary navigation as real <a href> links in the HTML.",
                          priority="critical", effort="medium", impact="high",
                          mechanism="Crawlers traverse href attributes. Navigation built from "
                                    "buttons, onclick handlers or a client-side router is "
                                    "invisible: the rest of the site is unreachable "
                                    "except via the sitemap.",
                          steps=["Replace <div onclick> / <button> navigation with <a href>.",
                                 "Ensure the header and footer links exist in the server "
                                 "response, not only after hydration.",
                                 "Link every top-level category from the home page."],
                          verification="curl -s https://<host>/ | grep -c '<a href' returns a "
                                       "number matching your visible navigation."),
            urls=[label(home)], confidence=0.95,
            metrics={"scope": "site"}, tags=["discovery", "blocking"])

    # The shared classification is authoritative for every link the crawl
    # actually fetched: a specialist must not re-derive a page type the bundle
    # already carries. A URL-only guess is consulted for the remainder, and
    # only ever to *suppress* this finding - a wrong guess can silence the rule
    # but can never manufacture it, which is the safe direction under
    # uncertainty.
    shared = bundle.get("page_types", {}) or {}
    types = {shared[link["url"]] for link in internal if link["url"] in shared}
    unfetched = [link for link in internal if link["url"] not in shared]
    if unfetched:
        from aiva.extract import classify_page
        types |= {classify_page(link["url"]) for link in unfetched}
    if types & {"product", "category"}:
        return None
    # "The catalogue is not linked from the home page" presupposes a
    # catalogue. On a documentation site, a B2B marketing site or a brochure
    # site there is nothing to link, and reporting its absence as a
    # high-severity discovery blocker is a defect of the auditor, not the site.
    commerce = commerce_evidence(bundle)
    if not commerce["is_commerce"]:
        return None

    # What this rule observed is that the home page has no *direct* link to the
    # catalogue. Whether the catalogue is therefore unreachable is a different
    # question, and the crawl already answered it: it went looking, by other
    # paths, and either found catalogue pages or did not. Reporting the absence
    # of a home-page link as "the catalogue is unreachable" states a conclusion
    # the same run refutes, on any site whose sitemap works.
    reach = _catalogue_reach(bundle)
    found = reach["catalogue_pages"]
    channels = reach["channels"]

    if not found:
        severity, confidence = "high", 0.8
        title = "No product or category page was reached from the home page or any other path"
        evidence = (f"The home page links to {len(internal)} internal URL(s), none of which "
                    "resolve to a product or category page, and no product or category page "
                    "was reached by any other discovery path this audit followed "
                    f"({reach['paths_tried']}).")
        interpretation = ("On the evidence available to this audit the catalogue may not be "
                          "reachable at all by a crawler starting at the root. A crawl that "
                          "was blocked, budget-limited or scoped to one market would look the "
                          "same from here, so confirm against the site before treating it as "
                          "an outage.")
    else:
        severity, confidence = "medium", 0.85
        title = "The home page does not link directly to any product or category page"
        evidence = (f"The home page links to {len(internal)} internal URL(s), none of which "
                    f"resolve to a product or category page. {len(found)} catalogue page(s) "
                    f"were still reached, by {channels}, so this reduces the directness of "
                    "discovery rather than preventing it.")
        interpretation = ("A crawler that follows links from the root reaches the catalogue "
                          "late or not at all, and retrieval fetchers that do not read "
                          "sitemaps depend on those links. The catalogue is discoverable; it "
                          "is one or more hops further away than the front door suggests.")

    return finding(
        "CR-COMMERCE-NOT-LINKED-FROM-HOME", title, severity, PILLAR,
        evidence=evidence,
        interpretation=interpretation,
        items=[measured(f"{len(internal)} internal links from the home page, "
                        f"0 leading to product or category pages",
                        value=len(internal), url=label(home))] +
              [observed(f"home page link: {link['url']}", url=label(home), locator="home nav")
               for link in internal[:3]] +
              [observed(f"catalogue page reached by {reach['via'][label(p)]}: {label(p)}",
                        url=label(p), locator="crawl frontier")
               for p in found[:3]],
        action=action("Link the main category hubs (and a few flagship products) from the home page.",
                      priority="high" if not found else "medium",
                      effort="low", impact="high" if not found else "medium",
                      mechanism="Crawl paths follow links. A catalogue reachable only through a "
                                "search box, a JavaScript mega-menu or the sitemap is reachable "
                                "by a crawler only if it reads sitemaps; a plain link from the "
                                "home page makes it reachable by any crawler that follows links.",
                      steps=["Add plain <a href> links to every top-level category in the header "
                             "or footer.",
                             "Feature 4-8 flagship products on the home page with real links.",
                             "Keep those links in the server-rendered HTML."],
                      verification="curl -s https://<host>/ | grep -o 'href=\"[^\"]*\"' shows "
                                   "category URLs."),
        urls=[label(home)], confidence=confidence,
        metrics={"scope": "site", "internal_links": len(internal),
                 "catalogue_pages_reached": len(found),
                 "discovery_channels": sorted(set(reach["via"].values()))},
        tags=["discovery"])


def _join(values: List[str]) -> str:
    """`a`, `a and b`, `a, b and c` - prose, not a quoted name list."""
    values = [v for v in values if v]
    if len(values) <= 1:
        return values[0] if values else ""
    return ", ".join(values[:-1]) + " and " + values[-1]


def _sitemap_urls(bundle: dict) -> set:
    """Every URL the site advertises in a sitemap it served."""
    origin = (bundle.get("site", {}) or {}).get("origin") or ""
    listed = set()
    for record in bundle.get("sitemaps", []) or []:
        for entry in record.get("entries") or []:
            normalized = util.normalize_url(str(entry.get("url") or ""), origin)
            if normalized:
                listed.add(normalized)
    return listed


def _sitemaps_with_entries(bundle: dict) -> int:
    return len([r for r in bundle.get("sitemaps", []) or [] if r.get("entries")])


def _linked_from_other_pages(bundle: dict, *, skip_home: bool = False) -> set:
    """Every internal URL some fetched page links to."""
    linked = set()
    for page in ev.pages(bundle):
        if skip_home and page.get("page_type") == "home":
            continue
        for link in (page.get("links", {}) or {}).get("internal", []) or []:
            if link.get("url"):
                linked.add(link["url"])
    return linked


def _catalogue_reach(bundle: dict) -> dict:
    """How the crawl actually reached the catalogue, if it did.

    Read from the bundle's own record of the crawl rather than from a
    provenance string: a page is in the sitemap if the sitemap lists it, and is
    linked from elsewhere if some other fetched page links to it. Both are
    observations already in evidence, which is what lets a finding about the
    home page stop short of a claim about the whole site.
    """
    catalogue = ev.product_pages(bundle) + ev.category_pages(bundle)
    listed = _sitemap_urls(bundle)
    sitemaps_read = _sitemaps_with_entries(bundle)
    linked_elsewhere = _linked_from_other_pages(bundle, skip_home=True)

    via = {}
    for page in catalogue:
        url = page.get("url") or ""
        if url in listed:
            via[label(page)] = "the sitemap"
        elif url in linked_elsewhere:
            via[label(page)] = "a link on another page"
        else:
            via[label(page)] = "another crawl path"
    channels = _join(sorted(set(via.values()))) or "another crawl path"

    tried = ["home page links"]
    if sitemaps_read:
        tried.append(f"{sitemaps_read} sitemap(s)")
    else:
        tried.append("no readable sitemap")
    return {"catalogue_pages": catalogue, "via": via, "channels": channels,
            "paths_tried": _join(tried)}


def rule_slow_responses(bundle: dict) -> Optional[Finding]:
    # Response time is transport evidence: every fetched document counts,
    # a search page or an alias as much as a product page.
    pages = ev.pages(bundle, include_aliases=True, include_utility=True)
    timings = [p.get("elapsed_ms", 0) for p in pages if p.get("elapsed_ms")]
    if len(timings) < 4:
        return None
    median = statistics.median(timings)
    if median < 2500:
        return None
    slow = sorted(pages, key=lambda p: -(p.get("elapsed_ms") or 0))[:5]
    return finding(
        "CR-SLOW-RESPONSES",
        "Pages respond slowly enough to cost crawl coverage and answer-time fetches",
        "medium", PILLAR,
        evidence=f"Median response time across {len(timings)} fetched page(s) was "
                 f"{int(median)}ms (slowest {int(max(timings))}ms).",
        interpretation="A fetch made to answer a question works to a timeout, and a response "
                       "slower than that timeout arrives too late to be used. What timeout any "
                       "given fetcher applies is not something this audit measures.",
        items=[measured(f"{p.get('elapsed_ms')}ms response time", value=p.get("elapsed_ms"),
                        url=label(p)) for p in slow],
        action=action("Bring server response time for the content routes under ~800ms.",
                      priority="medium", effort="medium", impact="medium",
                      mechanism="A response that arrives inside a fetcher's timeout is available "
                                "to it; one that arrives after it is not, whatever the page "
                                "contains.",
                      steps=["Cache rendered content HTML at the edge.",
                             "Serve a fast, cacheable response to unauthenticated requests.",
                             "Profile the slowest routes listed above first."],
                      verification="curl -w '%{time_total}' -o /dev/null -s <url> under 1s from "
                                   "two regions."),
        urls=[label(p) for p in slow], confidence=0.8,
        metrics={"scope": "site", "median_ms": int(median)}, tags=["performance"])


def rule_bot_wall(bundle: dict) -> Optional[Finding]:
    """Something in front of the origin refused this audit.

    This is the single most consequential thing that can happen on a site
    nobody designed the auditor for, and until now it was invisible: the crawl
    came back with nothing, a couple of transport findings were reported, and
    the report read as though the site had been examined.

    The claim is kept deliberately narrow. What is *observed* is that an
    unknown, honest, robots-respecting agent was refused. What is *inferred*
    is a risk - that a wall filtering on agent reputation refuses assistant
    crawlers on the same basis - and the finding says which is which, because
    only the site owner can check their edge logs and settle it.
    """
    access = bundle.get("access", {}) or {}
    if not access.get("wall_suspected"):
        return None

    statuses = ", ".join(f"HTTP {code} x{count}"
                         for code, count in (access.get("refusal_statuses") or {}).items())
    vendors = access.get("challenge_vendors_matched") or []
    vendor_note = (f" Challenge fingerprints matched: {', '.join(vendors[:3])}."
                   if vendors else
                   " No vendor fingerprint matched, so the refusal is reported from the "
                   "status pattern alone.")
    home_note = (" The home page itself was refused."
                 if access.get("home_refused") else
                 f" {access['refused_count']} of {access['requests_observed']} requests "
                 f"were refused.")

    # Refusing the front door means nothing downstream was measured; a partial
    # wall still let some evidence through, so it is serious but not decisive.
    severity = "critical" if access.get("home_refused") else "high"
    return finding(
        "CR-BOT-WALL",
        "Bot mitigation refused this audit before the origin served a page",
        severity, PILLAR,
        evidence=(f"Requests carrying an ordinary, non-browser User-Agent "
                  f"(\"{access.get('auditor_user_agent', '')[:60]}...\") were refused: "
                  f"{statuses}.{home_note}{vendor_note} This is an observation about how the "
                  f"edge treats an unknown agent, not a defect in the site's HTML - and it "
                  f"means the rest of this report had little or nothing to read."),
        interpretation=(
            "What was observed is that *this* agent was refused. This audit did not send "
            "GPTBot, ClaudeBot, PerplexityBot or any other assistant crawler's User-Agent, "
            "and impersonating one is something it will not do, so it has no evidence either "
            "way about how they are treated. Many edges allowlist named assistant crawlers by "
            "verified IP range while refusing unknown agents, in which case nothing here "
            "affects them; others score every unrecognised agent alike, in which case they "
            "are refused as this audit was. Which of the two applies is visible in your edge "
            "logs and nowhere else, so the action below starts by checking them rather than "
            "by changing a configuration."),
        items=[observed(f"HTTP {sample['status']} without a served page",
                        url=sample["url"], locator="edge refusal")
               for sample in (access.get("samples") or [])[:5]],
        action=action(
            "Confirm in your edge logs whether assistant crawlers are refused the same way, "
            "and allowlist the ones you want citations from.",
            priority=severity, effort="medium", impact="high",
            mechanism="A crawler that fetches pages live when a user asks a question gets no "
                      "content from a refused fetch, and no error is surfaced "
                      "to the user or to you. Whether that is happening here depends on "
                      "something this audit cannot see: if the edge scores unknown agents as "
                      "suspicious, they meet the refusal this audit met; if it allowlists them "
                      "by verified IP, they do not. The logs settle it in minutes.",
            steps=["Search the edge/WAF logs for GPTBot, OAI-SearchBot, ChatGPT-User, "
                   "ClaudeBot, PerplexityBot and Google-Extended, and check the disposition "
                   "of those requests over the last 30 days. If they are being served, the "
                   "rest of these steps are unnecessary and this finding describes only the "
                   "treatment of unknown agents.",
                   "If they are being refused, allowlist the ones you want citations from, verifying them "
                   "by published IP range or reverse DNS rather than by User-Agent string "
                   "alone, which is trivially spoofed.",
                   "Keep rate limiting in place for them; exempt them from JavaScript "
                   "challenges and CAPTCHA interstitials, which an automated client cannot complete.",
                   "Re-run this audit afterwards - if it reads pages, so can they."],
            verification="Edge logs show 200s for the assistant crawler user-agents you "
                         "allowlisted, and this audit reports a non-zero page count."),
        urls=[sample["url"] for sample in (access.get("samples") or [])],
        confidence=0.95 if vendors else 0.8,
        metrics={"scope": "site", "affected": access.get("refused_count", 0),
                 "sampled": access.get("requests_observed", 0)},
        tags=["bot-mitigation", "crawlability", "audit-coverage"])


RULES = (
    rule_bot_wall,
    rule_robots_unreachable,
    rule_robots_missing,
    rule_ai_crawlers_blocked,
    rule_ai_crawlers_path_blocked,
    rule_robots_syntax,
    rule_no_sitemap,
    rule_sitemap_errors,
    rule_sitemap_not_declared,
    rule_http_errors,
    rule_redirect_chains,
    rule_https_upgrade,
    rule_host_duplication,
    rule_soft_404,
    rule_noindex,
    rule_canonical,
    rule_js_dependence,
    rule_thin_raw_html,
    rule_discovery_depth,
    rule_slow_responses,
)


def analyze(bundle: dict) -> List[Finding]:
    """Entry point used by the orchestrator. Pure: no network, no mutation."""
    out: List[Finding] = []
    for rule in RULES:
        result = rule(bundle)
        if result is None:
            continue
        out.extend(result if isinstance(result, list) else [result])
    for item in out:
        item.source_skill = SKILL
        item.pillar = PILLAR
    return out


def main(argv: Optional[List[str]] = None) -> int:
    util.use_utf8_stdio()   # a report quotes the site's own text; write it as UTF-8
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True,
                        help="path to an evidence bundle JSON file")
    parser.add_argument("--out", help="write findings JSON here (default: stdout)")
    args = parser.parse_args(argv)

    with open(args.bundle, "r", encoding="utf-8") as handle:
        bundle = json.load(handle)
    findings = [f.to_dict() for f in analyze(bundle)]
    payload = json.dumps({"skill": SKILL, "pillar": PILLAR, "findings": findings},
                         indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
