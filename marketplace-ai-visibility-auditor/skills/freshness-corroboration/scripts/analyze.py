#!/usr/bin/env python3
"""freshness-corroboration - is the machine-readable version current, self-consistent
and supported by more than one source?

Stage three. A page can be crawlable and perfectly marked up and still produce
wrong answers, because the markup disagrees with the visible text, because the
dates say nothing, or because the fact exists in exactly one place on the whole
web and has nothing corroborating it.

Consumes the shared evidence bundle. Performs no network I/O: the off-site
anchor checks were made once during collection and are read from the bundle.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _bootstrap() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "marketplace.json").is_file() and \
                (candidate / "lib" / "aiva" / "__init__.py").is_file():
            lib = str(candidate / "lib")
            if lib not in sys.path:
                sys.path.insert(0, lib)
            return candidate
    raise RuntimeError("cannot locate the marketplace root")


MARKETPLACE_ROOT = _bootstrap()

from aiva import evidence as ev
from aiva import semantics                            # noqa: E402
from aiva import util                                # noqa: E402
from aiva.analysis import (cap_severity, crawl_yielded_evidence, absent, action, confidence_for, finding, jsonld_nodes,  # noqa: E402
                           label, measured, observed, offer_availability,
                           offer_price, offers_of, page_items,
                           products_on, sample_guard, scope_for,
                           visible_prices)
from aiva.extract import find_nodes, parse_amount, prop, text_of   # noqa: E402
from aiva.findings import Finding                    # noqa: E402

SKILL = "freshness-corroboration"
PILLAR = "freshness_corroboration"

IN_STOCK_TOKENS = {"instock", "inStock", "instoreonly", "onlineonly", "limitedavailability",
                   "preorder", "presale", "backorder"}
OUT_TOKENS = {"outofstock", "soldout", "discontinued"}


def _config(bundle: dict, key: str, default):
    return (bundle.get("config") or {}).get(key, default)


def _visible_freshness(page: dict) -> List[dict]:
    """Last-updated dates the page states in visible copy.

    A human-readable freshness signal is a real signal. It is not the same as
    a machine-readable one - it has no fixed location, no fixed format and no
    declared meaning - but a page that prints "This data was last updated on
    2026-09-01" has published its currency, and calling that page undated is a
    claim it visibly refutes. The two are measured separately and reported
    separately, and the recommendation acknowledges what is already there.
    """
    return (page.get("dates", {}) or {}).get("visible_updated", []) or []


def _page_dates(page: dict) -> Dict[str, Optional[dt.datetime]]:
    """Every date signal a machine could read off this page."""
    out: Dict[str, Optional[dt.datetime]] = {}
    for node in jsonld_nodes(page):
        for key in ("dateModified", "datePublished", "uploadDate", "releaseDate"):
            value = text_of(prop(node, key))
            parsed = util.parse_date(value)
            if parsed and (out.get(key) is None or parsed > out[key]):
                out[key] = parsed
    header = page.get("headers", {}).get("last-modified")
    if header:
        out["last_modified_header"] = util.parse_date(header)
    for entry in (page.get("dates", {}) or {}).get("time_elements", []) or []:
        parsed = util.parse_date(entry.get("datetime") or entry.get("text"))
        if parsed and (out.get("time_element") is None or parsed > out["time_element"]):
            out["time_element"] = parsed
    return {k: v for k, v in out.items() if v}


def _newest(dates: Dict[str, Optional[dt.datetime]]) -> Optional[dt.datetime]:
    values = [v for v in dates.values() if v]
    return max(values) if values else None


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def rule_no_date_signals(bundle: dict) -> Optional[Finding]:
    """Machine-readable freshness metadata, measured where a date is expected.

    A home page, a contact page and a category listing do not carry a dated
    fact, and counting them as "undated" turned every small site into a
    freshness defect. The population here is the pages where a date is
    expected (articles, FAQs, support documents, anything stating a date in
    its copy) or at least useful (policies, product pages, about pages); the
    pages where a date is beside the point are set aside and named.
    """
    if not crawl_yielded_evidence(bundle):
        return None
    all_pages = ev.pages(bundle)
    expectation = {label(p): semantics.freshness_expectation(p) for p in all_pages}
    pages = [p for p in all_pages if expectation[label(p)] != "not_applicable"]
    aside = len(all_pages) - len(pages)
    if not sample_guard(pages, 2):
        return None
    undated = [p for p in pages if not _page_dates(p)]
    if len(undated) / len(pages) < 0.6:
        return None
    expected_undated = [p for p in undated if expectation[label(p)] == "expected"]
    lastmods = any(s.get("lastmods") for s in bundle.get("sitemaps", []))

    # Which of those pages state a date in visible copy anyway. This changes
    # what the finding says, what it recommends, and how severe it is - a site
    # that already publishes the date and only needs to mark it up is one
    # template change away, not a content problem.
    visible = {label(p): _visible_freshness(p) for p in undated}
    with_visible = [p for p in undated if visible[label(p)]]
    sample_quote = ""
    if with_visible:
        first = visible[label(with_visible[0])][0]
        sample_quote = f" e.g. \"{first.get('text', '')}\" on {label(with_visible[0])};"
        contrast = (f" {len(with_visible)} of those page(s) do state a last-updated date in "
                    f"visible content -{sample_quote} the date is present to a reader but is "
                    f"not exposed through any of the machine-readable mechanisms this rule "
                    f"checks.")
        title = ("Last-updated dates are stated in visible copy but not in a machine-readable "
                 "form")
        severity = "medium"
    else:
        contrast = " No last-updated date was detected in their visible copy either."
        title = "Machine-readable freshness metadata is absent"
        # `high` only where a date is genuinely expected of most of the
        # affected pages and nothing else (a sitemap lastmod) stands in; an
        # undated policy or product page is a gap, not a blocker.
        if expected_undated and len(expected_undated) >= max(2, len(undated) * 0.5) \
                and not lastmods:
            severity = "high"
        else:
            severity = semantics.cap_optional("medium")

    kinds = {}
    for p in undated:
        kinds[expectation[label(p)]] = kinds.get(expectation[label(p)], 0) + 1
    population = ", ".join(f"{n} where a date is {k}" for k, n in sorted(kinds.items()))
    return finding(
        "FC-NO-DATE-SIGNALS",
        title, severity, PILLAR,
        evidence=f"{len(undated)} of {len(pages)} sampled page(s) where a date is expected or "
                 f"useful ({population}) expose no dateModified, no <time datetime> element "
                 "and no Last-Modified header"
                 + ("; sitemap lastmod values are also absent." if not lastmods
                    else "; only sitemap lastmod is available.")
                 + contrast
                 + (f" {aside} further page(s) - home, contact, listing and utility pages - "
                    f"were not counted, because a date is not a fact they carry."
                    if aside else ""),
        interpretation="A machine-readable date has a declared meaning and a fixed location; a "
                       "date in a sentence has neither, and has to be found and interpreted "
                       "before it can be used. Where two versions of the same fact are in "
                       "circulation, recency is one of the few tiebreakers available, and only "
                       "the machine-readable form participates in it reliably.",
        items=[observed(
            ("no dateModified, <time datetime> element or Last-Modified header on {}; "
             "visible last-updated text present: \"{}\"").format(
                 label(p), visible[label(p)][0].get("text", ""))
            if visible[label(p)] else
            "no dateModified, <time datetime> element, Last-Modified header or visible "
            "last-updated text on {}".format(label(p)),
            url=label(p), locator="JSON-LD, <time> elements, response headers, body text")
            for p in undated[:5]],
        action=action(
            "Expose the last-updated date in a machine-readable form as well as in copy."
            if with_visible else
            "Publish an explicit, machine-readable last-updated date on every page.",
            priority="high", effort="low", impact="high",
            mechanism="dateModified, a <time datetime> attribute and a Last-Modified header "
                      "each state the same fact in a place with a defined meaning, so it can "
                      "be read without parsing a sentence in a particular language.",
            steps=(["Keep the visible date - it is doing real work for readers - and wrap it in "
                    "a <time datetime=\"YYYY-MM-DD\"> element so the same string is typed.",
                    "Emit the same value as dateModified in the page's JSON-LD."]
                   if with_visible else
                   ["Emit dateModified in the page's JSON-LD, set from the real content change "
                    "time - not the deploy time.",
                    "Render a visible 'Last updated: <date>' inside a <time datetime> element "
                    "on the pages that state dated facts (articles, FAQs, policies)."])
            + ["Send a truthful Last-Modified response header.",
               "Do not touch the date when nothing changed: an always-today date carries no "
               "information about when the content last changed."],
            verification="curl -sI <url> shows Last-Modified, and the page's JSON-LD contains "
                         "dateModified matching the visible date.",
            verification_type="self_verifiable"),
        urls=[label(p) for p in undated],
        confidence=confidence_for(len(undated), len(pages)),
        metrics={"scope": "site", "affected": len(undated), "sampled": len(pages),
                 "sample_unit": "sampled page(s) where a date is expected or useful",
                 "not_assessed": aside,
                 "expected_undated": len(expected_undated),
                 "machine_readable_freshness_signal": 0,
                 "visible_freshness_signal": len(with_visible),
                 "sitemap_lastmod_available": bool(lastmods)},
        tags=["freshness"])


def rule_sitemap_lastmod(bundle: dict) -> List[Finding]:
    sitemaps = [s for s in bundle.get("sitemaps", []) if s.get("kind") == "urlset"]
    if not sitemaps:
        return []
    out: List[Finding] = []
    captured = sum(s.get("entries_captured", 0) for s in sitemaps)
    missing = sum(s.get("missing_lastmod", 0) for s in sitemaps)
    if captured and missing / captured >= 0.5:
        out.append(finding(
            "FC-SITEMAP-NO-LASTMOD",
            "Sitemap entries omit <lastmod>, so the sitemap says nothing about what changed",
            "medium", PILLAR,
            evidence=f"{missing} of {captured} sitemap URL(s) have no <lastmod> value.",
            items=[measured(f"{s.get('missing_lastmod')} of {s.get('entries_captured')} entries "
                            f"without <lastmod>", value=s.get("missing_lastmod"), url=s["url"])
                   for s in sitemaps[:4]],
            action=action("Emit a truthful <lastmod> for every sitemap URL.",
                          priority="medium", effort="low", impact="medium",
                          mechanism="lastmod is the sitemap's own statement of what changed "
                                    "and when. Without it the sitemap gives a reader no basis "
                                    "to tell a page that changed this morning from one "
                                    "untouched for two years.",
                          steps=["Set lastmod from the content's real modification timestamp.",
                                 "Use W3C datetime format with a timezone.",
                                 "Update it whenever a stated fact on the page changes, not only "
                                 "on copy edits."],
                          verification="Change one page, regenerate the sitemap, and confirm "
                                       "only that URL's lastmod moved."),
            urls=[s["url"] for s in sitemaps], confidence=0.95,
            metrics={"scope": "site", "missing": missing, "captured": captured},
            tags=["freshness", "sitemap"]))

    all_lastmods = [util.parse_date(value) for s in sitemaps for value in (s.get("lastmods") or [])]
    all_lastmods = [d for d in all_lastmods if d]
    if len(all_lastmods) >= 10:
        distinct = {d.date() for d in all_lastmods}
        if len(distinct) == 1:
            out.append(finding(
                "FC-SITEMAP-LASTMOD-UNIFORM",
                "Every sitemap entry claims the same modification date",
                "medium", PILLAR,
                evidence=f"All {len(all_lastmods)} captured <lastmod> values resolve to the same "
                         f"date ({list(distinct)[0].isoformat()}), which means the field is set "
                         "from the sitemap build time rather than from content changes.",
                items=[measured(f"{len(all_lastmods)} lastmod values, {len(distinct)} distinct "
                                f"date(s)", value=len(distinct), url=sitemaps[0]["url"])],
                action=action("Derive lastmod per URL from that URL's content, not from the "
                              "generation run.",
                              priority="medium", effort="low", impact="medium",
                              mechanism="A uniformly-stamped sitemap states the same date for "
                                        "every URL, which carries no information about which "
                                        "pages changed - including on the pages where the date "
                                        "would have been true.",
                              steps=["Store a content_updated_at per entity and emit that.",
                                     "Never fall back to now() when the value is unknown; omit "
                                     "the element instead."],
                              verification="Two consecutive sitemap builds with no content change "
                                           "produce identical lastmod values."),
                urls=[s["url"] for s in sitemaps], confidence=0.9,
                metrics={"scope": "site", "distinct_dates": len(distinct)},
                tags=["freshness", "sitemap"]))

        future = [d for d in all_lastmods if d > util.utc_now() + dt.timedelta(days=1)]
        if future:
            out.append(finding(
                "FC-SITEMAP-LASTMOD-FUTURE",
                "Sitemap entries claim modification dates in the future",
                "medium", PILLAR,
                evidence=f"{len(future)} <lastmod> value(s) are dated after today "
                         f"(latest {max(future).date().isoformat()}), which invalidates the "
                         "field as a freshness signal.",
                items=[measured(f"future lastmod {d.isoformat()}", value=d.isoformat(),
                                url=sitemaps[0]["url"]) for d in future[:4]],
                action=action("Clamp lastmod to the actual modification time.",
                              priority="medium", effort="low", impact="low",
                              mechanism="A modification date in the future cannot be true, so "
                                        "the field states something a reader cannot rely on - "
                                        "and gives no reason to rely on the values beside it.",
                              steps=["Fix the timezone handling that produced the offset.",
                                     "Never emit a scheduled publish date as lastmod before it "
                                     "publishes."],
                              verification="No lastmod value exceeds the current UTC date."),
                urls=[s["url"] for s in sitemaps], confidence=0.95,
                metrics={"scope": "site", "future_count": len(future)},
                tags=["freshness", "sitemap"]))
    return out


def _independent_freshness(bundle: dict, pages: List[dict]) -> Tuple[Optional[int], int]:
    """The newest date signal the site carries other than a copyright year.

    Returns ``(days_since_newest, signals_seen)``. ``dateModified``, a
    ``Last-Modified`` header, a ``<time>`` element, a visible "updated" line,
    ``datePublished`` and every sitemap ``lastmod`` count; the copyright year
    is deliberately not one of them, because this is what the year is being
    weighed against.
    """
    newest = None
    seen = 0
    for page in pages:
        for value in _page_dates(page).values():
            if value is None:
                continue
            seen += 1
            if newest is None or value > newest:
                newest = value
    for record in bundle.get("sitemaps", []) or []:
        for raw in record.get("lastmods") or []:
            parsed = util.parse_date(str(raw))
            if parsed is None:
                continue
            seen += 1
            if newest is None or parsed > newest:
                newest = parsed
    if newest is None:
        return None, seen
    return util.days_since(newest), seen


def rule_stale_copyright(bundle: dict) -> Optional[Finding]:
    """An old copyright year, weighed against every other date signal.

    A footer year is a weak signal: it is hardcoded in a template on many
    maintained sites and says nothing on its own about whether the content is
    current. So the finding reports the observation, and says which of three
    situations it sits in - contradicted by fresher signals elsewhere on the
    site, uncorroborated because there are no other signals at all, or
    consistent with old maintenance dates reported separately - and never
    infers abandonment, lost ranking or a competitor's advantage from it.
    """
    pages = ev.pages(bundle)
    current_year = util.utc_now().year
    stale: List[Tuple[dict, int]] = []
    for page in pages:
        years = (page.get("dates", {}) or {}).get("copyright_years") or []
        if not years:
            continue
        newest = max(years)
        if newest < current_year - 1:
            stale.append((page, newest))
    if not stale:
        return None

    threshold = int(_config(bundle, "stale_page_days", 365))
    newest_days, signals_seen = _independent_freshness(bundle, pages)
    span = (f"{min(y for _, y in stale)}-{max(y for _, y in stale)}"
            if len({y for _, y in stale}) > 1 else str(stale[0][1]))
    observed_sentence = (f"{len(stale)} sampled page(s) show a copyright year of {span} "
                         f"against a current year of {current_year}.")
    if newest_days is not None and newest_days <= threshold:
        situation = "contradicted"
        severity = "info"
        context = (f" The site carries fresher signals elsewhere - its newest machine-readable "
                   f"date is {newest_days} day(s) old - so the year is a template artefact "
                   f"rather than evidence about the content.")
        interpretation = ("A copyright year is a weak freshness signal, and here fresher "
                          "signals on the same site contradict it. It may warrant a template "
                          "fix; it does not suggest the content is unmaintained.")
    elif newest_days is None:
        situation = "uncorroborated"
        severity = "low"
        context = (" No other machine-readable or visible date signal was detected on the "
                   "sampled pages, so there is nothing to corroborate or contradict the year.")
        interpretation = ("A copyright year is a weak freshness signal on its own. With no "
                          "other date signal on the sampled pages it is neither confirmed nor "
                          "contradicted, and may warrant a review of whether the content is "
                          "current - which this audit cannot establish from the year alone.")
    else:
        situation = "consistent"
        severity = "low" if len(stale) < 2 else "medium"
        context = (f" The site's newest other date signal is also {newest_days} day(s) old "
                   f"(see FC-STALE-CONTENT where reported), so the year is consistent with "
                   f"the maintenance dates rather than contradicted by them.")
        interpretation = ("A copyright year is a weak freshness signal on its own; here it "
                          "agrees with old maintenance dates reported separately, which "
                          "together suggest the content may not have been reviewed recently. "
                          "That is a possibility to check, not a measured outcome.")
    interpretation += (" This audit does not measure how any assistant or index weighs the "
                       "year.")
    return finding(
        "FC-STALE-COPYRIGHT",
        "The footer copyright year is out of date",
        severity, PILLAR,
        evidence=observed_sentence + context,
        interpretation=interpretation,
        items=[observed(f"footer copyright year {year}", url=label(page), locator="page footer")
               for page, year in stale[:5]],
        action=action("Render the copyright year dynamically, and treat it as a prompt to "
                      "review whether the page's facts are still current.",
                      priority="low", effort="low", impact="low",
                      mechanism="An old year is a signal a reader - human or machine - may "
                                "weigh when there is nothing better to go on; publishing "
                                "explicit freshness signals (dateModified, a visible "
                                "reviewed-on date) gives them something better.",
                      steps=["Generate the year server-side rather than hardcoding it.",
                             "Publish dateModified and a visible 'Reviewed on <date>' on pages "
                             "whose facts change, so freshness is stated explicitly.",
                             "Treat the year as a symptom: check whether the page's facts "
                             "are still true before changing anything else."],
                      verification="Footer shows the current year on every template."),
        urls=[label(p) for p, _ in stale], confidence=0.9 if situation != "uncorroborated" else 0.7,
        metrics={"scope": "template", "affected": len(stale), "sampled": len(pages),
                 "situation": situation, "newest_other_signal_days": newest_days,
                 "other_signals_seen": signals_seen},
        tags=["freshness"])


#: Page types where an old date is the *correct* answer rather than a defect.
#: A news story published in 2019 is correctly dated 2019; so is a press
#: release, a journal paper, a court opinion or an archived announcement.
#: Reporting those as stale fires on every media site, blog, university news
#: section and research archive - and the "fix" would be to falsify the date.
_ARCHIVAL_PAGE_TYPES = {"article"}


def rule_stale_content(bundle: dict) -> Optional[Finding]:
    pages = [p for p in ev.pages(bundle)
             if (p.get("page_type") or "") not in _ARCHIVAL_PAGE_TYPES]
    if not pages:
        return None
    threshold = int(_config(bundle, "stale_page_days", 365))
    very = int(_config(bundle, "very_stale_page_days", 730))
    stale: List[Tuple[dict, int]] = []
    for page in pages:
        dates = _page_dates(page)
        # `datePublished` on its own says when the page was written, not
        # whether it is maintained. Only treat a page as stale when the site
        # itself claims a last-changed date - dateModified, a Last-Modified
        # header, or a visible "updated" line - and that claim is old.
        maintenance = {k: v for k, v in dates.items()
                       if k in ("dateModified", "last_modified_header", "time_element")}
        newest = _newest(maintenance) or (_newest(dates) if len(dates) > 1 else None)
        if not newest:
            continue
        age = util.days_since(newest)
        if age is not None and age > threshold:
            stale.append((page, age))
    # One old page is not a stale site. Escalation needs a share of the sample
    # behind it, not a single outlier.
    if not stale or len(stale) / len(pages) < 0.34:
        return None
    worst = max(age for _, age in stale)
    ratio = len(stale) / len(pages)
    severity = "high" if (worst >= very and ratio >= 0.6) else "medium"
    return finding(
        "FC-STALE-CONTENT",
        "Dated pages have not been updated for a long time",
        cap_severity(severity, len(pages)), PILLAR,
        evidence=f"{len(stale)} of {len(pages)} sampled non-archival page(s) carry a newest "
                 f"maintenance date older than {threshold} days "
                 f"(oldest {worst} days). Where a third-party copy of the same fact exists, "
                 "the site's own page offers no recency signal to prefer it by.",
        items=[measured(f"newest machine-readable date is {age} days old", value=age,
                        url=label(page)) for page, age in
               sorted(stale, key=lambda pair: -pair[1])[:5]],
        action=action("Review and re-date the stale pages, starting with anything stating a "
                      "fact that changes over time.",
                      priority="medium", effort="medium", impact="medium",
                      mechanism="Recency is one signal a reader may use to choose between "
                                "competing versions of a fact. A page whose own dates say it "
                                "has not been touched in two years offers none in its favour "
                                "for a fact that changed last quarter.",
                      steps=["Prioritise the pages that state facts a reader would act on.",
                             "Correct anything that is no longer true, then update dateModified.",
                             "Add a visible 'Reviewed on <date>' line so the freshness is "
                             "legible to humans as well as machines.",
                             "Do not bump dates without changing content."],
                      verification="No page stating a time-sensitive fact has a dateModified "
                                   "older than your review cycle."),
        urls=[label(p) for p, _ in stale], confidence=0.85,
        metrics={"scope": "section", "affected": len(stale), "oldest_days": worst},
        tags=["freshness"])


def _price_values(page: dict) -> List[float]:
    return [entry["value"] for entry in visible_prices(page)]


def rule_price_conflict(bundle: dict) -> Optional[Finding]:
    products = [p for p in ev.product_pages(bundle) if products_on(p)]
    if not sample_guard(products, 1):
        return None
    conflicts: List[Tuple[dict, str, List[float]]] = []
    for page in products:
        visible = _price_values(page)
        if not visible:
            continue
        for node in products_on(page):
            for offer in offers_of(node):
                raw = offer_price(offer)
                if not raw:
                    continue
                markup_value = parse_amount(str(raw))
                if markup_value is None:
                    continue
                if any(abs(markup_value - value) < 0.01 for value in visible):
                    continue
                conflicts.append((page, str(raw), visible[:6]))
                break
    if not conflicts:
        return None
    return finding(
        "FC-PRICE-CONFLICT",
        "The price in the markup does not match any price shown on the page",
        "high", PILLAR,
        evidence=f"On {len(conflicts)} of {len(products)} product page(s) the Offer.price in "
                 "structured data appears nowhere in the visible text "
                 f"(e.g. markup says {conflicts[0][1]}, page shows "
                 f"{', '.join(str(v) for v in conflicts[0][2])}).",
        items=[observed(f"Offer.price={raw} but visible prices are "
                        f"{', '.join(str(v) for v in visible)}",
                        url=label(page), locator="JSON-LD Offer vs page text")
               for page, raw, visible in conflicts[:5]],
        action=action("Generate the markup and the visible price from the same value at render time.",
                      priority="high", effort="medium", impact="high",
                      mechanism="When the machine-readable value and the human-readable value "
                                "disagree, one of them is wrong, and a reader of the markup has "
                                "no way to tell which. Generating both from one value removes "
                                "the contradiction at its source.",
                      steps=["Render both from one server-side variable; never let a cached "
                             "JSON-LD block outlive the price it describes.",
                             "If you show a sale price, put the sale price in Offer.price and the "
                             "list price in a PriceSpecification - do not put the list price in "
                             "the markup and the sale price on the page.",
                             "Invalidate page caches on price change.",
                             "Add a regression test asserting markup price == rendered price."],
                      verification="For 10 random products, the number in Offer.price appears "
                                   "verbatim in the rendered page text."),
        urls=[label(p) for p, _, _ in conflicts],
        confidence=confidence_for(len(conflicts), len(products), base=0.85),
        metrics={"scope": scope_for(len(conflicts), len(products)),
                 "affected": len(conflicts), "sampled": len(products),
                 "sample_unit": "sampled product page(s)"},
        tags=["consistency", "price"])


def rule_availability_conflict(bundle: dict) -> Optional[Finding]:
    products = [p for p in ev.product_pages(bundle) if products_on(p)]
    if not sample_guard(products, 1):
        return None
    conflicts: List[Tuple[dict, str, str]] = []
    for page in products:
        text_flags = page.get("availability_text", {}) or {}
        says_out = bool(text_flags.get("out_of_stock"))
        says_in = bool(text_flags.get("in_stock"))
        for node in products_on(page):
            for offer in offers_of(node):
                declared = offer_availability(offer)
                if not declared:
                    continue
                token = declared.lower()
                if token in {t.lower() for t in IN_STOCK_TOKENS} and says_out and not says_in:
                    conflicts.append((page, declared, "page text says out of stock / sold out"))
                elif token in {t.lower() for t in OUT_TOKENS} and says_in and not says_out:
                    conflicts.append((page, declared, "page text says in stock"))
    if not conflicts:
        return None
    return finding(
        "FC-AVAILABILITY-CONFLICT",
        "Declared availability contradicts what the page says",
        "high", PILLAR,
        evidence=f"{len(conflicts)} product page(s) declare an availability value that "
                 "contradicts the visible stock message "
                 f"(e.g. markup '{conflicts[0][1]}' while {conflicts[0][2]}).",
        items=[observed(f"Offer.availability={declared} but {why}", url=label(page),
                        locator="JSON-LD Offer vs page text")
               for page, declared, why in conflicts[:5]],
        action=action("Drive availability markup from live inventory, and cache it with the page.",
                      priority="high", effort="medium", impact="high",
                      mechanism="Availability is the fact most likely to change between "
                                "renders, and a declared value that contradicts the page's own "
                                "stock message states something the page itself says is wrong.",
                      steps=["Emit availability from the same inventory read that renders the "
                             "stock badge.",
                             "Use OutOfStock, BackOrder or PreOrder honestly rather than "
                             "omitting the field.",
                             "Purge the page cache on stock transitions.",
                             "For variant-level stock, model variants as separate Products under "
                             "a ProductGroup so each has its own availability."],
                      verification="Take a product out of stock in the admin and confirm the "
                                   "rendered JSON-LD flips within your cache TTL."),
        urls=[label(p) for p, _, _ in conflicts],
        confidence=confidence_for(len(conflicts), len(products), base=0.85),
        metrics={"scope": scope_for(len(conflicts), len(products)), "affected": len(conflicts)},
        tags=["consistency", "availability"])


def rule_cross_page_price(bundle: dict) -> Optional[Finding]:
    # Every page that quotes a price for a product it is not itself: the
    # listings, through the shared funnel, plus the home page, which shows the
    # same tiles. Neither set is re-derived here.
    listings = ev.category_pages(bundle) + ev.pages(bundle, "home")
    products = {p.get("url"): p for p in ev.product_pages(bundle)}
    if not listings or not products:
        return None
    conflicts: List[Tuple[str, str, str, str]] = []
    for listing in listings:
        listing_base = listing.get("final_url") or listing.get("url") or ""
        for node in products_on(listing):
            # JSON-LD may carry a relative url; resolve it against the page.
            url = util.normalize_url(text_of(prop(node, "url")) or "", listing_base)
            if not url or url not in products:
                continue
            listing_prices = [offer_price(o) for o in offers_of(node)]
            listing_prices = [p for p in listing_prices if p]
            if not listing_prices:
                continue
            target = products[url]
            target_prices = []
            for target_node in products_on(target):
                target_prices.extend([p for p in (offer_price(o) for o in offers_of(target_node))
                                      if p])
            if not target_prices:
                continue
            def _num(value: str) -> Optional[float]:
                return parse_amount(str(value))
            listing_values = {_num(v) for v in listing_prices} - {None}
            target_values = {_num(v) for v in target_prices} - {None}
            if listing_values and target_values and not (listing_values & target_values):
                conflicts.append((label(listing), url, sorted(listing_prices)[0],
                                  sorted(target_prices)[0]))
    if not conflicts:
        return None
    return finding(
        "FC-CROSS-PAGE-PRICE-CONFLICT",
        "The same product is priced differently on the listing and on its own page",
        "high", PILLAR,
        evidence=f"{len(conflicts)} product(s) carry different Offer.price values on a listing "
                 f"page and on the product page itself (e.g. {conflicts[0][2]} on "
                 f"{conflicts[0][0]} vs {conflicts[0][3]} on {conflicts[0][1]}).",
        items=[observed(f"listing price {listing_price} vs product-page price {product_price}",
                        url=listing_url, locator=f"compared against {product_url}")
               for listing_url, product_url, listing_price, product_price in conflicts[:5]],
        action=action("Serve one price per product from a single source, on every surface.",
                      priority="high", effort="medium", impact="high",
                      mechanism="Two prices for one product is an internal contradiction: "
                                "nothing in the markup says which is current, so a reader of "
                                "either page has no basis to pick. One source removes the "
                                "disagreement.",
                      steps=["Render listing tiles and product pages from the same pricing "
                             "service call, not from a denormalised copy.",
                             "Invalidate listing caches when a product price changes.",
                             "Add a nightly consistency job that diffs listing vs detail prices."],
                      verification="A crawl of every category page reports zero price mismatches "
                                   "against the linked product pages."),
        urls=util.dedupe([c[0] for c in conflicts] + [c[1] for c in conflicts]),
        confidence=0.9,
        metrics={"scope": "site", "conflicts": len(conflicts)},
        tags=["consistency", "price"])


def rule_price_valid_until(bundle: dict) -> Optional[Finding]:
    products = [p for p in ev.product_pages(bundle) if products_on(p)]
    if not sample_guard(products, 1):
        return None
    expired: List[Tuple[dict, str]] = []
    for page in products:
        for node in products_on(page):
            for offer in offers_of(node):
                value = text_of(prop(offer, "priceValidUntil"))
                parsed = util.parse_date(value)
                if parsed and parsed < util.utc_now():
                    expired.append((page, value))
    if not expired:
        return None
    return finding(
        "FC-PRICE-VALID-UNTIL-EXPIRED",
        "Offers declare a price validity date that has already passed",
        "medium", PILLAR,
        evidence=f"{len(expired)} offer(s) carry a priceValidUntil in the past "
                 f"(e.g. {expired[0][1]}), which tells consumers the quoted price is no longer "
                 "guaranteed.",
        items=[observed(f"priceValidUntil={value} is in the past", url=label(page),
                        locator="JSON-LD Offer") for page, value in expired[:5]],
        action=action("Roll priceValidUntil forward automatically, or remove it.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="An expired validity date is an explicit statement that the "
                                "quoted price is no longer guaranteed, made about a price the "
                                "page still shows.",
                      steps=["Set it from the real promotion end date when one exists.",
                             "Otherwise emit today + 90 days, regenerated on each render.",
                             "Never hardcode a literal date in a template."],
                      verification="No rendered page contains a priceValidUntil earlier than "
                                   "today."),
        urls=[label(p) for p, _ in expired], confidence=0.95,
        metrics={"scope": "template", "affected": len(expired)},
        tags=["freshness", "price"])


def rule_review_freshness(bundle: dict) -> Optional[Finding]:
    pages = ev.pages(bundle)
    dates: List[Tuple[dict, dt.datetime]] = []
    review_pages = []
    for page in pages:
        reviews = find_nodes(jsonld_nodes(page), "Review", "UserReview")
        if not reviews:
            continue
        review_pages.append(page)
        for review in reviews:
            parsed = util.parse_date(text_of(prop(review, "datePublished", "dateCreated")))
            if parsed:
                dates.append((page, parsed))
    if not review_pages:
        return None
    threshold = int(_config(bundle, "stale_review_days", 540))
    if not dates:
        return finding(
            "FC-REVIEWS-UNDATED",
            "Reviews are marked up but carry no publication date",
            "medium", PILLAR,
            evidence=f"{len(review_pages)} page(s) publish Review structured data with no "
                     "datePublished value on any Review node.",
            interpretation="An undated review states a judgement without stating when it was "
                           "made, so nothing on the page says whether the opinions are recent. "
                           "How any reader weighs that is not something this audit measures.",
            items=[absent("Review nodes have no datePublished", url=label(p), locator="JSON-LD "
                                                                                      "Review")
                   for p in review_pages[:5]],
            action=action("Emit datePublished on every Review node.",
                          priority="medium", effort="low", impact="medium",
                          mechanism="A datePublished on each Review is the explicit, "
                                    "machine-readable statement of when the opinion was given; "
                                    "without it nothing on the page supports 'well reviewed "
                                    "recently'.",
                          steps=["Populate datePublished from the review's submission timestamp.",
                                 "Show the date visibly next to each review as well."],
                          verification="Every Review node in the rendered HTML has a "
                                       "datePublished."),
            urls=[label(p) for p in review_pages], confidence=0.9,
            metrics={"scope": "template", "affected": len(review_pages)},
            tags=["reviews", "freshness"])

    newest = max(date for _, date in dates)
    age = util.days_since(newest) or 0
    if age <= threshold:
        return None
    return finding(
        "FC-REVIEWS-STALE",
        "The most recent marked-up review is old",
        "medium", PILLAR,
        evidence=f"The newest datePublished across {len(dates)} marked-up review(s) is "
                 f"{newest.date().isoformat()} ({age} days ago). Either no newer review "
                 "exists or newer reviews are not published in the markup; the crawl cannot "
                 "tell which.",
        items=[measured(f"newest review datePublished is {age} days old",
                        value=newest.date().isoformat(), url=label(dates[0][0]))],
        action=action("Resume publishing dated reviews into the page markup.",
                      priority="medium", effort="medium", impact="medium",
                      mechanism="Dated recent reviews in the markup are explicit evidence that "
                                "the item is still being bought and rated; a body of reviews "
                                "whose newest date is years old states nothing about the "
                                "present. How any reader weighs that is not measured here.",
                      steps=["Check whether new reviews exist but are only rendered client-side "
                             "by a widget - that is the usual cause.",
                             "Publish the most recent reviews server-side with datePublished.",
                             "Prompt for reviews post-delivery to keep the stream flowing."],
                      verification="The newest Review datePublished in the HTML is within the "
                                   "last quarter."),
        urls=[label(p) for p, _ in dates[:5]], confidence=0.85,
        metrics={"scope": "template", "newest_age_days": age},
        tags=["reviews", "freshness"])


#: Link kinds that count as an anchor for the *organisation*: an account the
#: site claims, a knowledge-base entry, or anything the site itself declared
#: as sameAs / rel=me. A documentation host, an app-store listing, a
#: platform video and a language variant of the site are links, not anchors.
_ANCHOR_KINDS = frozenset({"official_profile", "knowledge_reference", "review_listing"})


def _is_entity_anchor(anchor: dict) -> bool:
    if anchor.get("declared_as_sameas") or "rel=me link" in (anchor.get("sources") or []):
        return True
    kind = anchor.get("link_kind")
    if kind is None:
        # A bundle written before links were classified: every collected
        # anchor was a profile/knowledge link by construction.
        return True
    if kind == "knowledge_reference":
        return bool(anchor.get("entity_match")) or bool(anchor.get("in_site_chrome"))
    return kind in _ANCHOR_KINDS


def _entity_anchors(bundle: dict) -> Tuple[List[dict], int]:
    """The anchors that are about the organisation, and how many were declared.

    A bundle whose anchors carry ``link_kind`` is filtered by kind; an older
    bundle's anchors were all profile/knowledge links by construction, and
    its recorded total is used as-is.
    """
    raw = bundle.get("declared_anchors") or []
    if raw and all("link_kind" in a for a in raw):
        anchors = [a for a in raw if _is_entity_anchor(a)]
        return anchors, len(anchors)
    return list(raw), int(bundle.get("declared_anchors_total", len(raw)) or 0)


def rule_corroboration_anchors(bundle: dict) -> List[Finding]:
    anchors, total_declared = _entity_anchors(bundle)
    out: List[Finding] = []

    if total_declared == 0:
        # "No anchors were declared anywhere" is an absence read off page
        # content. With no readable page in the bundle it is vacuously true and
        # says nothing about the site, so it follows the same gate as the other
        # absence rules. The broken-anchor branch below is a positive
        # observation about anchors the site did declare and is not gated: it
        # holds whether or not any page body was readable.
        if not crawl_yielded_evidence(bundle):
            return []
        home = ev.home_page(bundle)
        out.append(finding(
            "FC-NO-CORROBORATION-ANCHORS",
            "The site declares no independent sources that corroborate its facts",
            "high", PILLAR,
            evidence="No schema.org sameAs values, rel=me links, official profile links or "
                     "knowledge-base entries about the organisation were found on any crawled "
                     "page. Documentation links, app-store listings and platform content links "
                     "are not counted: they are links, not claims of identity.",
            interpretation="This audit reads one site and cannot see how the wider web describes "
                           "the brand. What it can say is that the site declares no independent "
                           "source itself, so nothing on the site points at a second place where "
                           "its facts could be checked. Whether any system checks them, and how "
                           "it treats a single-source claim, is not something this audit measures.",
            items=[absent("no sameAs, rel=me, official profile or knowledge-base links about the "
                          "organisation found across the crawl",
                          url=label(home) if home else bundle["site"]["origin"],
                          locator="JSON-LD sameAs / outbound links")],
            action=action("Declare and cultivate independent corroboration for the brand entity.",
                          priority="high", effort="medium", impact="high",
                          mechanism="A sameAs value is an explicit, machine-readable statement "
                                    "that an account or a knowledge-base entry is this "
                                    "organisation, which is what lets a fact stated there be "
                                    "matched to a fact stated here.",
                          steps=["Add sameAs to the Organization node listing every official "
                                 "profile you control.",
                                 "Ensure the same legal name, logo and description appear on "
                                 "those profiles verbatim.",
                                 "Where a third party already describes the brand, make sure it "
                                 "links back to the canonical domain.",
                                 "Prefer a small number of authoritative, genuinely independent "
                                 "sources over volume."],
                          verification="Ask an assistant who this organization is and check "
                                       "the answer cites at least one source that is not "
                                       "this site.",
                          verification_type="external_validation"),
            urls=[bundle["site"]["origin"]], confidence=0.9,
            metrics={"scope": "site"}, tags=["corroboration", "entity"]))
        return out

    # Three outcomes for a checked anchor, and only one of them is a
    # broken link: the platform answered "not found". A refusal, a rate
    # limit, a timeout or a server error is the platform declining to answer
    # this auditor, which social platforms do routinely, and says nothing
    # about the profile - so those are reported as *not verified*, at low
    # severity, and never as "dead".
    def _verdict(anchor: dict) -> str:
        if anchor.get("verification"):
            return anchor["verification"]
        return semantics.transport_verdict(anchor.get("status"), anchor.get("error"))["verdict"]

    checked = [a for a in anchors if a.get("checked")]
    not_found = [a for a in checked if _verdict(a) == "not_found"]
    unverified = [a for a in checked if _verdict(a) == "unverified"]
    if not_found:
        out.append(finding(
            "FC-BROKEN-CORROBORATION-ANCHOR",
            "Declared corroboration links return not-found",
            "medium", PILLAR,
            evidence=f"{len(not_found)} of {len(checked)} checked off-site anchor(s) declared by "
                     "the site (sameAs / profile links) returned HTTP 404/410 "
                     f"(e.g. {not_found[0]['url']} -> {not_found[0].get('status')})."
                     + (f" A further {len(unverified)} could not be verified by this audit "
                        f"(refused, rate-limited, timed out or errored) and are not counted as "
                        f"broken." if unverified else ""),
            items=[observed(f"declared anchor returned HTTP {anchor.get('status')}",
                            url=anchor["url"],
                            locator=f"declared via {', '.join(anchor.get('sources', []))}")
                   for anchor in not_found[:5]],
            action=action("Correct or remove the sameAs and profile links that return not-found.",
                          priority="medium", effort="low", impact="medium",
                          mechanism="A sameAs value asserts that a URL is this organisation; a "
                                    "URL that returns not-found asserts it about nothing, so "
                                    "the declaration provides no corroboration for the facts "
                                    "stated here.",
                          steps=["Verify every sameAs URL resolves to a live page you control.",
                                 "Remove profiles you have closed rather than leaving them "
                                 "declared.",
                                 "Add a link-check to the release pipeline for sameAs values."],
                          verification="Every sameAs URL returns 200 to a browser."),
            urls=[a["url"] for a in not_found], confidence=0.9,
            metrics={"scope": "site", "broken": len(not_found), "unverified": len(unverified),
                     "checked": len(checked)},
            tags=["corroboration"]))
    elif unverified:
        reasons = {}
        for anchor in unverified:
            why = anchor.get("verification_reason") or semantics.transport_verdict(
                anchor.get("status"), anchor.get("error"))["reason"]
            reasons[why] = reasons.get(why, 0) + 1
        out.append(finding(
            "FC-BROKEN-CORROBORATION-ANCHOR",
            "Declared corroboration links could not be verified by this audit",
            "low", PILLAR,
            evidence=f"{len(unverified)} of {len(checked)} checked off-site anchor(s) declared by "
                     "the site could not be verified: "
                     + "; ".join(f"{n} ({why})" for why, n in sorted(reasons.items())) + ". "
                     "The platforms declined to answer an automated request; this says nothing "
                     "about whether the profiles exist, and none is reported as broken.",
            interpretation="An unverified anchor is an observation about the path between this "
                           "auditor and the platform, not about the profile. A browser may well "
                           "load it; this audit did not, and does not claim otherwise.",
            items=[observed(f"could not be verified: "
                            f"{anchor.get('verification_reason') or anchor.get('error') or anchor.get('status')}",
                            url=anchor["url"],
                            locator=f"declared via {', '.join(anchor.get('sources', []))}")
                   for anchor in unverified[:5]],
            action=action("Confirm in a browser that each declared profile is live; no change is "
                          "needed if it is.",
                          priority="low", effort="low", impact="low",
                          mechanism="A declared profile that exists corroborates the "
                                    "organisation whether or not this auditor could fetch it; "
                                    "the check is only whether the declaration is current.",
                          steps=["Open each declared sameAs URL in a browser.",
                                 "Remove any that no longer exist."],
                          verification="Each declared sameAs URL loads in a browser."),
            urls=[a["url"] for a in unverified], confidence=0.5,
            metrics={"scope": "site", "unverified": len(unverified), "checked": len(checked)},
            tags=["corroboration", "unverified"]))
    return out


RULES = (
    rule_no_date_signals,
    rule_sitemap_lastmod,
    rule_stale_copyright,
    rule_stale_content,
    rule_price_conflict,
    rule_availability_conflict,
    rule_cross_page_price,
    rule_price_valid_until,
    rule_review_freshness,
    rule_corroboration_anchors,
)


def analyze(bundle: dict) -> List[Finding]:
    # No blanket gate here: this specialist also reasons about sitemap
    # <lastmod> values and the declared-anchor probe, which are real evidence
    # gathered independently of page content. The rules that read page bodies
    # carry the gate individually.
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
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    with open(args.bundle, "r", encoding="utf-8") as handle:
        bundle = json.load(handle)
    payload = json.dumps({"skill": SKILL, "pillar": PILLAR,
                          "findings": [f.to_dict() for f in analyze(bundle)]},
                         indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
