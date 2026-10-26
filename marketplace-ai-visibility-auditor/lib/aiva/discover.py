"""Collection phase: turn a URL into a shared evidence bundle.

This is the *only* module that talks to the network. It performs the crawl
once, records everything it saw, and hands the specialist skills a frozen
JSON document. Ordering matters:

    robots.txt  ->  host canonicalisation  ->  sitemaps  ->  home page
                ->  frontier + sampling    ->  404 probe ->  declared-anchor
                                                             corroboration
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from . import semantics, util
from .config import (AI_CRAWLER_AGENTS, MUTATING_QUERY_RE, NON_CITABLE_PATH_RE,
                     AuditConfig)
from .evidence import BUNDLE_SCHEMA_VERSION, EvidenceStore, generator_block
from .extract import (KNOWLEDGE_HOSTS, LISTING_PAGE_TYPES, classify_page,
                      prop, same_document, text_of)
from .version import ROBOTS_UA_TOKEN, USER_AGENT

WELL_KNOWN_SITEMAPS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                       "/sitemap.xml.gz", "/wp-sitemap.xml")


# ---------------------------------------------------------------------------
# entry normalisation
# ---------------------------------------------------------------------------

def normalize_site_input(raw: str) -> Tuple[str, str, str]:
    """Return ``(origin, home_url, entry_url)`` for whatever the user typed.

    The *home page* is always the origin root: site-wide identity checks
    (Organization/WebSite markup, navigation reachability, self-description)
    are only meaningful against the real front door. A deeper URL the caller
    supplied is kept separately as the **entry point** - it is crawled first
    and seeds the frontier, but it is classified on its merits (a collection
    URL is a category page, not a home page).
    """
    value = (raw or "").strip()
    if not value:
        raise ValueError("a site URL or domain is required")
    if "://" not in value:
        value = "https://" + value.lstrip("/")
    parts = urlsplit(value)
    origin = urlunsplit((parts.scheme, parts.netloc.lower(), "", "", ""))
    home = origin + "/"
    entry = util.normalize_url(value) or home
    return origin, home, entry


# ---------------------------------------------------------------------------
# sitemaps
# ---------------------------------------------------------------------------

def _localname(tag: str) -> str:
    return tag.split("}")[-1].lower()


def parse_sitemap(xml_text: str) -> dict:
    """Parse a urlset or sitemapindex. Never raises."""
    result = {"kind": "unknown", "urls": [], "sitemaps": [], "error": None,
              "entry_count": 0}
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as exc:
        result["error"] = f"XML parse error: {exc}"
        return result
    kind = _localname(root.tag)
    if kind == "sitemapindex":
        result["kind"] = "index"
        for child in root:
            if _localname(child.tag) != "sitemap":
                continue
            loc = lastmod = None
            for leaf in child:
                name = _localname(leaf.tag)
                if name == "loc":
                    loc = (leaf.text or "").strip()
                elif name == "lastmod":
                    lastmod = (leaf.text or "").strip()
            if loc:
                result["sitemaps"].append({"url": loc, "lastmod": lastmod})
    elif kind == "urlset":
        result["kind"] = "urlset"
        for child in root:
            if _localname(child.tag) != "url":
                continue
            entry: Dict[str, Optional[str]] = {"url": None, "lastmod": None,
                                               "changefreq": None, "priority": None}
            for leaf in child:
                name = _localname(leaf.tag)
                if name in entry:
                    entry[name] = (leaf.text or "").strip()
                elif name == "loc":
                    entry["url"] = (leaf.text or "").strip()
            if entry["url"]:
                result["urls"].append(entry)
    else:
        result["error"] = f"unexpected root element <{kind}>"
    result["entry_count"] = len(result["urls"]) + len(result["sitemaps"])
    return result


def collect_sitemaps(store: EvidenceStore, origin: str,
                     declared: Iterable[str],
                     scope: Optional[str] = None) -> List[dict]:
    """Follow sitemap declarations (and the well-known paths) breadth-first.

    When the audit is scoped to one market, entries outside it are dropped
    here rather than at the frontier. A sitemap is also *evidence* - the
    lastmod-uniformity and coverage rules read these records - so a
    market-scoped audit whose sitemap statistics were computed over another
    country's catalogue would describe a site nobody asked about.
    """
    config = store.config
    queue: List[Tuple[str, str]] = []
    seen: set = set()

    for url in declared:
        normalized = util.normalize_url(url, origin)
        if normalized and normalized not in seen:
            seen.add(normalized)
            queue.append((normalized, "robots.txt Sitemap directive"))
    for path in WELL_KNOWN_SITEMAPS:
        normalized = util.normalize_url(origin + path)
        if normalized and normalized not in seen:
            seen.add(normalized)
            queue.append((normalized, "well-known path probe"))

    records: List[dict] = []
    total_urls = 0
    while queue and len(records) < config.max_sitemaps:
        url, source = queue.pop(0)
        response = store.fetch(url, reason=f"sitemap ({source})")
        record = {"url": url, "source": source, "status": 0, "kind": None,
                  "error": None, "url_count": 0, "child_count": 0,
                  "lastmods": [], "sample_urls": []}
        if response is None:
            record["error"] = "blocked by robots.txt or budget exhausted"
            records.append(record)
            continue
        record["status"] = response.status
        record["content_type"] = response.content_type
        if response.error:
            record["error"] = response.error
            records.append(record)
            continue
        if response.status >= 400:
            record["error"] = f"HTTP {response.status}"
            records.append(record)
            continue
        # A `.xml.gz` sitemap is already gunzipped by the HTTP client, which
        # decompresses any body whose bytes are a gzip stream regardless of the
        # Content-Encoding header. Re-encoding the decoded text and gunzipping
        # that (an earlier approach) could not recover the original bytes and
        # reported valid sitemaps as malformed.
        parsed = parse_sitemap(response.body)
        record["kind"] = parsed["kind"]
        record["error"] = parsed["error"]
        if parsed["kind"] == "index":
            record["child_count"] = len(parsed["sitemaps"])
            for child in parsed["sitemaps"]:
                normalized = util.normalize_url(child["url"], origin)
                if normalized and normalized not in seen and len(seen) < config.max_sitemaps * 2:
                    seen.add(normalized)
                    queue.append((normalized, f"listed in sitemap index {url}"))
        elif parsed["kind"] == "urlset":
            in_scope = [e for e in parsed["urls"] if in_locale_scope(e.get("url") or "", scope)]
            record["url_count_out_of_scope"] = len(parsed["urls"]) - len(in_scope)
            entries = in_scope[: max(0, config.max_sitemap_urls - total_urls)]
            total_urls += len(entries)
            record["url_count"] = len(in_scope)
            record["entries_captured"] = len(entries)
            record["lastmods"] = [e["lastmod"] for e in entries if e.get("lastmod")]
            record["missing_lastmod"] = len([e for e in entries if not e.get("lastmod")])
            record["sample_urls"] = [e["url"] for e in entries[:2000]]
            record["entries"] = entries[:2000]
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# host canonicalisation probes
# ---------------------------------------------------------------------------

def probe_host_variants(store: EvidenceStore, origin: str) -> dict:
    parts = urlsplit(origin)
    host = parts.netloc
    other_host = host[4:] if host.startswith("www.") else "www." + host
    probes = {}

    http_origin = urlunsplit(("http", host, "/", "", ""))
    # Only meaningful when the audited origin is itself https; auditing an
    # explicitly http:// target (or a local fixture) must not manufacture a
    # "no HTTPS upgrade" finding.
    # A short timeout: a host that simply drops plain HTTP should cost a few
    # seconds of the budget, not the full per-request allowance.
    response = (store.fetch(http_origin, reason="HTTP->HTTPS canonicalisation probe",
                            method="GET", timeout=min(6.0, store.config.timeout_s))
                if parts.scheme == "https" else None)
    if response is not None:
        probes["http"] = {
            "url": http_origin,
            "status": response.status,
            "final_url": response.final_url,
            "redirects": [{"status": s, "location": loc} for s, loc in response.redirects],
            "upgrades_to_https": response.final_url.startswith("https://"),
            "error": response.error,
        }

    # An IP literal or a single-label host has no www/apex pair to compare.
    bare_host = host.split(":")[0]
    is_ip_or_local = bool(re.fullmatch(r"[\d.]+|\[[0-9a-f:]+\]|localhost", bare_host, re.I))
    alt_origin = urlunsplit((parts.scheme, other_host, "/", "", ""))
    response = (store.fetch(alt_origin, reason="www/apex canonicalisation probe", method="GET")
                if not is_ip_or_local else None)
    if response is not None:
        probes["alt_host"] = {
            "url": alt_origin,
            "status": response.status,
            "final_url": response.final_url,
            "resolves": bool(response.status and response.status < 400 and not response.error),
            "redirects_to_primary": util.registrable_host(response.final_url or "") ==
                                    util.registrable_host(origin) and
                                    (response.final_url or "").startswith(parts.scheme),
            "same_host_as_primary": (urlsplit(response.final_url or "").netloc == host),
            "error": response.error,
        }
    return probes


#: Statuses that mean "refused", not "answered". 429 and 503 are included
#: because rate limiters and challenge pages routinely use them; 404 and 410
#: are deliberately absent - those are answers about a URL, not refusals.
REFUSAL_STATUSES = frozenset({401, 403, 407, 408, 429, 451, 503})

#: Fingerprints of the common bot-mitigation vendors, in markup and in headers.
#: Matching is a hint that raises confidence, never the deciding signal - the
#: status pattern is what decides, so an unrecognised vendor is still caught.
_CHALLENGE_BODY_HINTS = (
    "just a moment...", "checking your browser", "cf-browser-verification",
    "__cf_chl", "attention required! | cloudflare", "cloudflare ray id",
    "pardon our interruption", "request unsuccessful. incapsula",
    "access to this page has been denied", "enable javascript and cookies to continue",
    "captcha", "are you a robot", "unusual traffic from your computer network",
)
_CHALLENGE_HEADER_HINTS = ("cf-ray", "cf-mitigated", "x-datadome", "x-iinfo",
                           "x-akamai-transformed", "x-sucuri-id", "server-timing-bot")


def assess_access(store: EvidenceStore, home_url: str) -> dict:
    """Did anything stand between this audit and the origin?

    A read-only auditor sends an honest, unknown User-Agent, and a growing
    share of sites answer unknown agents with a challenge instead of a page.
    Left unmodelled, that produced the worst possible report: a crawl that
    fetched nothing, a couple of transport-derived findings, and a score - all
    of it phrased as though the site had been read.

    This records the pattern rather than guessing at intent. Nothing here says
    the site is misconfigured; the rule that reads it is careful to separate
    "this auditor was refused" (certain) from "assistant crawlers are refused"
    (a risk the site owner alone can confirm).
    """
    refused, statuses, vendors = [], {}, set()
    total = 0
    # Only the audited site's own responses answer "did anything stand between
    # this audit and the origin?". By the time this runs the store also holds
    # the off-site anchor responses and their robots.txt, and a brand that
    # declares a dozen `sameAs` links to a host that 403s them would otherwise
    # manufacture a bot wall against a site that answered every one of its own
    # pages cleanly.
    primary = util.registrable_host(home_url)
    for url, response in store.responses.items():
        if primary and util.registrable_host(url) != primary:
            continue
        if response.error:
            continue
        total += 1
        if response.status not in REFUSAL_STATUSES:
            continue
        statuses[response.status] = statuses.get(response.status, 0) + 1
        body = (response.body or "")[:4000].lower()
        matched = [hint for hint in _CHALLENGE_BODY_HINTS if hint in body]
        header_keys = {k.lower() for k in (response.headers or {})}
        matched += [h for h in _CHALLENGE_HEADER_HINTS if h in header_keys]
        if matched:
            vendors.update(matched)
        refused.append({"url": url, "status": response.status,
                        "challenge_signals": sorted(set(matched))[:3]})

    refused_count = len(refused)
    home_normalized = util.normalize_url(home_url) or home_url
    home_refused = any(r["url"] == home_normalized for r in refused)
    share = (refused_count / total) if total else 0.0

    # Two independent ways to be sure, so an unrecognised vendor still trips it:
    # the front door itself was refused, or refusals dominate the whole run.
    wall = bool(refused_count and (home_refused or share >= 0.5))
    return {
        "requests_observed": total,
        "refused_count": refused_count,
        "refused_share": round(share, 3),
        "refusal_statuses": {str(k): v for k, v in sorted(statuses.items())},
        "home_refused": home_refused,
        "challenge_vendors_matched": sorted(vendors),
        "wall_suspected": wall,
        "samples": refused[:8],
        "auditor_user_agent": store.config.user_agent or USER_AGENT,
    }


def probe_not_found(store: EvidenceStore, origin: str) -> dict:
    # Seeded from the origin alone, not the clock. A wall-clock seed made the
    # probe URL - and therefore the evidence bundle - different on every run of
    # the same site, so "deterministic" was a claim nobody could check with
    # `diff`. The token still cannot collide with a real path: no site routes
    # `/aiva-probe-<hash>`.
    token = "aiva-probe-%s" % util.short_hash(origin, length=10)
    url = f"{origin}/{token}"
    response = store.fetch(url, reason="soft-404 probe")
    if response is None:
        return {"url": url, "checked": False,
                "note": "not probed (blocked by robots.txt or budget)"}
    body_len = len(response.body or "")
    return {
        "url": url,
        "checked": True,
        "status": response.status,
        "final_url": response.final_url,
        "returns_404": response.status == 404,
        "returns_200": response.status == 200,
        "redirected_to_home": util.url_path(response.final_url or "") in ("/", ""),
        "body_bytes": body_len,
        "error": response.error,
    }


#: Conventional "here is what an AI agent should read" files. They are the one
#: surface a site publishes *for* assistants rather than for people, so their
#: presence (or absence) belongs in the evidence regardless of which convention
#: a site has adopted.
AI_SURFACE_PATHS = {
    "llms_txt": "/llms.txt",
    "agents_md": "/agents.md",
}

_MD_LINK_RE = re.compile(r"\]\(\s*((?:https?://|/)[^)\s]+)\s*\)")


def probe_ai_surfaces(store: EvidenceStore, origin: str) -> Dict[str, dict]:
    """Record which agent-facing discovery files the site publishes.

    Fetch-once applies: if a surface was already reached through the sitemap,
    this reads the cached response instead of asking for it again.
    """
    surfaces: Dict[str, dict] = {}
    for name, path in AI_SURFACE_PATHS.items():
        url = origin + path
        response = store.fetch(url, reason=f"AI discovery surface probe ({path})")
        if response is None:
            surfaces[name] = {"url": url, "checked": False, "present": False}
            continue
        body = response.body or ""
        present = response.status == 200 and bool(body.strip())
        surfaces[name] = {
            "url": url,
            "checked": True,
            "status": response.status,
            "present": present,
            "bytes": response.body_bytes,
            "content_type": response.content_type,
            "link_count": len(_MD_LINK_RE.findall(body)) if present else 0,
            "excerpt": util.truncate(body, 400) if present else "",
        }
    return surfaces


# ---------------------------------------------------------------------------
# frontier
# ---------------------------------------------------------------------------

#: Paths that can never be a citable source and only burn crawl budget:
#: carts, checkouts and account areas. Excluded from the frontier entirely.
#: Binary assets a text auditor cannot read anything useful out of.
ASSET_SUFFIXES = (".css", ".js", ".mjs", ".jpg", ".jpeg", ".png", ".webp", ".gif",
                  ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".webm",
                  ".mp3", ".zip", ".gz", ".pdf")


#: Market segments that belong to every locale rather than to one. A
#: multi-market retailer's `/global/en/...` corporate and support pages are
#: the pattern: they are not
#: the market under audit, but they are not another market either.
_NEUTRAL_MARKETS = frozenset({"global", "int", "intl", "corporate", "group"})

#: `/in/en/...` -> `/in/en`; `/ee/et/p/x/` -> `/ee/et`; `/products/x` -> None.
_LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2})?$", re.I)


def locale_prefix(path: str) -> Optional[str]:
    """The leading country[/language] portion of a path, or None.

    Only a leading *pair* of locale-shaped segments, or a single country
    segment followed by more path, counts. This is deliberately conservative:
    misreading an ordinary first segment as a locale would silently shrink a
    crawl, which is a worse failure than not recognising a locale at all.
    """
    segments = [s for s in (path or "").split("/") if s]
    if not segments:
        return None
    first = segments[0].lower()
    if first in _NEUTRAL_MARKETS:
        return "/" + first
    if not _LOCALE_SEGMENT_RE.match(first):
        return None
    if len(segments) > 1 and _LOCALE_SEGMENT_RE.match(segments[1]):
        return f"/{first}/{segments[1].lower()}"
    return "/" + first


def in_locale_scope(url: str, scope: Optional[str]) -> bool:
    """Is this URL inside the market the audit was pointed at?

    With no scope everything passes. With one, a URL passes when it carries no
    locale at all (`/robots.txt`, `/sitemaps/...`, a global search page), when
    its locale is a market-neutral segment, or when its locale is the audited
    one.

    The audit that prompted this was entered at one market root (`/in/en/`)
    of a multi-market retailer and reported another country's product pages,
    two further front doors and a fourth market's storefront as findings
    about one site. Those are different
    markets with different catalogues, prices and policies; aggregating them
    into "33 of 38 sampled pages" describes no site that exists.
    """
    if not scope:
        return True
    prefix = locale_prefix(util.url_path(url))
    if prefix is None:
        return True
    if prefix.strip("/").split("/")[0] in _NEUTRAL_MARKETS:
        return True
    return prefix.lower() == scope.lower()


def build_frontier(bundle_site: dict, seed_pages: List[Optional[dict]],
                   sitemap_records: List[dict],
                   config: AuditConfig) -> Tuple[List[Tuple[str, str]], int]:
    """Candidate URLs as ``(url, why_we_picked_it)``, best-first.

    Returns the candidates plus the number of duplicate candidate URLs that
    were collapsed - the same URL advertised by both the navigation and the
    sitemap is discovered once and fetched once.
    """
    origin = bundle_site["origin"]
    scope = bundle_site.get("locale_scope")
    entry_host = urlsplit(bundle_site.get("entry_url") or origin).netloc.lower()
    candidates: List[Tuple[str, str]] = []
    seen = {bundle_site["home_url"], bundle_site.get("entry_url", "")}
    collapsed = 0
    out_of_scope = 0

    def add(url: Optional[str], reason: str) -> None:
        nonlocal collapsed, out_of_scope
        normalized = util.normalize_url(url, origin)
        if not normalized:
            return
        if normalized in seen:
            collapsed += 1
            return
        if not util.same_site(normalized, origin):
            return
        if scope:
            # A market-scoped audit stays on the host it was pointed at. A
            # sibling subdomain (a corporate site, a franchise portal) is a
            # different property with different content, and folding it into
            # this report's ratios describes neither.
            if urlsplit(normalized).netloc.lower() != entry_host:
                out_of_scope += 1
                return
            if not in_locale_scope(normalized, scope):
                out_of_scope += 1
                return
        path = util.url_path(normalized)
        if NON_CITABLE_PATH_RE.search(path) or path.lower().endswith(ASSET_SUFFIXES):
            return
        # The query matters as much as the path. WooCommerce writes its
        # add-to-cart and cart-removal links as plain GETs on an otherwise
        # citable product URL, so a path-only filter queued them - and the same
        # document arrived three times under three query strings, counted as
        # three product pages, skewing every "N of M product pages" ratio.
        if MUTATING_QUERY_RE.search(util.url_query(normalized)):
            return
        seen.add(normalized)
        candidates.append((normalized, reason))

    # 1. Links discovered on the pages we already hold carry the site's own
    #    idea of what matters, so they come first.
    for facts in seed_pages:
        if not facts:
            continue
        source = "home page" if facts.get("page_type") == "home" else "audit entry page"
        for link in facts.get("links", {}).get("internal", []):
            add(link["url"], f"linked from the {source}")

    # 2. Sitemap URLs - authoritative list of what the site wants indexed.
    for record in sitemap_records:
        for entry in record.get("entries", []) or []:
            add(entry.get("url"), f"listed in {record['url']}")

    if out_of_scope:
        bundle_site["out_of_locale_candidates"] = out_of_scope
    return candidates, collapsed


#: Bucket order for the quota round, best-understood page type first. Any
#: bucket key not listed here is appended in sorted order, so adding a page
#: type to ``PAGE_TYPE_HINTS`` can never make a page unfetchable.
SAMPLE_ORDER = ("product", "category", "faq", "policy", "about", "contact",
                "article", "search", "home", "other")


def sample_frontier(candidates: List[Tuple[str, str]], config: AuditConfig,
                    already: Iterable[str]) -> List[Tuple[str, str, str]]:
    """Pick a bounded, type-balanced sample: ``(url, reason, predicted_type)``.

    Two rounds. The first fills each type's quota, which is what keeps the
    sample balanced rather than 40 product pages and nothing else. The second
    spends whatever the quotas left over, because the quotas are keyed on a
    *guess*.

    ``classify_page(url)`` here sees the URL and nothing else - no page has
    been fetched yet. A site that writes ``/shop/blue-mug`` instead of
    ``/products/blue-mug`` matches no product hint, so its entire catalogue is
    filed under ``other`` (quota 4) while the 12 product slots go unspent, and
    the function used to return at that point: **5 pages fetched against a
    budget of 40**, with every ratio in the report - "8 of 12 product pages
    have no price" - computed over almost nothing. Worse, the sample-size
    guards then correctly refuse to generalise from three pages, so a broken
    site produces a near-empty report that reads as clean. The quotas also sum
    to less than ``max_pages``, so even a correctly-classified site left slots
    unused.

    A page the URL failed to describe costs nothing but the fetch, and
    ``classify_page`` re-reads the type from the markup once the page is in
    hand. So the leftover round hands the unspent budget back out, round-robin
    across buckets so that one large bucket - a blog, a paginated archive -
    cannot crowd out the catalogue the first round was starving.
    """
    targets = dict(config.sample_targets)
    picked: List[Tuple[str, str, str]] = []
    seen = set(already)
    buckets: Dict[str, List[Tuple[str, str]]] = {}

    for url, reason in candidates:
        if url in seen:
            continue
        page_type = classify_page(url)
        buckets.setdefault(page_type, []).append((url, reason))

    # Shallow URLs first inside each bucket: they are the pages the site itself
    # puts closest to its front door, and they keep the sample representative.
    for items in buckets.values():
        items.sort(key=lambda pair: (util.url_depth(pair[0]), len(pair[0])))

    order = list(SAMPLE_ORDER) + sorted(k for k in buckets if k not in SAMPLE_ORDER)

    def take(url: str, reason: str, page_type: str) -> None:
        picked.append((url, reason, page_type))
        seen.add(url)

    # Round 1: the type quotas.
    cursors: Dict[str, int] = {}
    for page_type in order:
        items = buckets.get(page_type, [])
        quota = max(0, targets.get(page_type, 0))
        for url, reason in items[:quota]:
            take(url, reason, page_type)
        cursors[page_type] = min(quota, len(items))

    # Round 2: the unspent remainder, round-robin so no bucket monopolises it.
    remaining = max(0, config.max_pages - len(seen))
    while remaining > 0:
        progressed = False
        for page_type in order:
            if remaining <= 0:
                break
            items = buckets.get(page_type, [])
            index = cursors.get(page_type, 0)
            if index >= len(items):
                continue
            url, reason = items[index]
            cursors[page_type] = index + 1
            take(url, reason, page_type)
            remaining -= 1
            progressed = True
        if not progressed:
            break
    return picked


# ---------------------------------------------------------------------------
# alias resolution: one document, several addresses
# ---------------------------------------------------------------------------

#: How a page came to be recognised as another page's document, in the
#: words the manifest prints beside it.
_ALIAS_WHY = {
    "redirect": "redirects to {target}, which the crawl holds as a page of its own",
    "canonical": "declares {target} as its canonical URL and serves that page's document "
                 "(same title and headings)",
    "duplicate": "serves the same document as {target} (same title, headings, length and "
                 "internal links) under a different address",
}


def _is_readable(page: dict) -> bool:
    return (not page.get("fetch_failed") and not page.get("non_html")
            and int(page.get("status") or 0) < 400)


def _self_canonical(url: str, page: dict) -> bool:
    canonical = util.normalize_url(page.get("canonical") or "") if page.get("canonical") else None
    return bool(canonical) and canonical == url


def _mark_alias(url: str, page: dict, page_types: Dict[str, str],
                target: str, how: str) -> None:
    previous = page.get("page_type") or ""
    page["alias_of"] = target
    page["alias_kind"] = how
    page["page_type"] = "reference"
    page_types[url] = "reference"
    evidence = dict(page.get("page_type_evidence") or {})
    evidence["decided_by"] = (
        "a navigation/reference address rather than a document of its own: it "
        + _ALIAS_WHY[how].format(target=target)
        + (f" (its content alone had read as {previous})" if previous else ""))
    evidence["alias_of"] = target
    page["page_type_evidence"] = evidence


def resolve_aliases(pages: Dict[str, dict], page_types: Dict[str, str],
                    home_url: str) -> int:
    """Mark every fetched page that is another fetched page's document.

    Three shapes, each read from the pages' own evidence and none from the
    shape of a URL:

    * a URL that **redirected** onto a page the crawl also holds;
    * a URL whose document **declares** a canonical the crawl also holds, and
      whose title and headings agree with that page's;
    * a URL whose document is **indistinguishable** from an earlier page's -
      same title, same headings, same length and the same internal links -
      with no declaration either way.

    Such a page is typed ``reference``: a navigation/reference address, not a
    content document of its own. It stays in the manifest with the reason,
    and every content population skips it. A tracking suffix on the home
    page's logo link, served as the home page with a canonical pointing at
    the root, is therefore neither a second home page in every ratio nor a
    "content page whose canonical points elsewhere" - it is the front door,
    reached by another name.

    The home page is never an alias of anything. Returns how many pages were
    marked.
    """
    home = util.normalize_url(home_url) or home_url
    ordered = [(url, page) for url, page in pages.items() if _is_readable(page)]
    by_address: Dict[str, dict] = {}
    for url, page in ordered:
        by_address.setdefault(url, page)
        landed = util.normalize_url(page.get("final_url") or "")
        if landed:
            by_address.setdefault(landed, page)

    marked = 0
    for index, (url, page) in enumerate(ordered):
        if url == home or page.get("page_type") == "reference":
            continue
        landed = util.normalize_url(page.get("final_url") or "") or url
        declared: List[Tuple[str, str]] = []
        if landed != url:
            declared.append((landed, "redirect"))
        canonical = util.normalize_url(page.get("canonical") or "") if page.get("canonical") else None
        if canonical and canonical != url and canonical != landed:
            declared.append((canonical, "canonical"))
        done = False
        for target, how in declared:
            other = by_address.get(target)
            if other is None or other is page or other.get("page_type") == "reference":
                continue
            if same_document(page, other, declared=True):
                _mark_alias(url, page, page_types, target, how)
                marked += 1
                done = True
                break
        if done or _self_canonical(url, page):
            # A page that names itself as the canonical address is claiming
            # to be the original; it is not demoted to a copy of an earlier
            # fetch on content similarity alone.
            continue
        for other_url, other in ordered[:index]:
            if other is page or other.get("page_type") == "reference":
                continue
            if same_document(page, other, declared=False):
                _mark_alias(url, page, page_types, other_url, "duplicate")
                marked += 1
                break
    return marked


# ---------------------------------------------------------------------------
# declared-anchor corroboration (read-only, robots-respecting)
# ---------------------------------------------------------------------------

def collect_declared_anchors(pages_facts: List[dict], site_origin: str = "",
                             entity_names: Optional[List[str]] = None) -> List[dict]:
    """Off-site anchors *the site itself declares* - sameAs, rel=me, knowledge
    graph links. We verify these resolve; we never search the web.

    Each anchor carries what kind of link it is (``link_kind``, from
    :func:`aiva.semantics.classify_outbound_link`): an official profile the
    site controls, a knowledge-base entry, a documentation host, a product
    listing on someone else's store. Only the first is a claim of identity a
    site could declare as ``sameAs``; the others are links, and a rule that
    counted every one of them as a "profile" told sites their documentation
    links were undeclared social accounts.
    """
    anchors: Dict[str, dict] = {}
    entity_names = list(entity_names or [])

    def add(url: Optional[str], source: str, page_url: str, *, rel: str = "",
            text: str = "", in_chrome: bool = False) -> None:
        normalized = util.normalize_url(url or "")
        if not normalized:
            return
        if normalized not in anchors:
            verdict = semantics.classify_outbound_link(
                normalized, site_origin=site_origin, text=text, rel=rel,
                entity_names=entity_names)
            anchors[normalized] = {
                "url": normalized, "sources": [], "declared_on": [],
                "is_knowledge_host": any(h in normalized for h in KNOWLEDGE_HOSTS),
                "link_kind": verdict["kind"],
                "link_kind_reason": verdict["why"],
                "entity_match": bool(verdict.get("entity_match")),
                "declared_as_sameas": False,
                "in_site_chrome": False,
            }
        record = anchors[normalized]
        if source not in record["sources"]:
            record["sources"].append(source)
        if page_url not in record["declared_on"]:
            record["declared_on"].append(page_url)
        if source == "schema.org sameAs":
            record["declared_as_sameas"] = True
        if in_chrome:
            record["in_site_chrome"] = True

    for facts in pages_facts:
        page_url = facts.get("url", "")
        for node in facts.get("jsonld_nodes", []) or []:
            same_as = prop(node, "sameAs")
            values = same_as if isinstance(same_as, list) else ([same_as] if same_as else [])
            for value in values:
                add(text_of(value), "schema.org sameAs", page_url)
            # `url` and `@id` are deliberately not read here: a node pointing
            # at itself is not a second source, and counting it would let a
            # site corroborate its own claims.
        external = facts.get("links", {}).get("external", []) or []
        by_url = {str(link.get("url")): link for link in external if isinstance(link, dict)}
        for link in external:
            rel = link.get("rel", "")
            if "me" in rel.split():
                add(link["url"], "rel=me link", page_url, rel=rel,
                    text=str(link.get("text") or ""),
                    in_chrome=bool(link.get("in_nav") or link.get("in_footer")))
        for url in facts.get("links", {}).get("sameas_like", []) or []:
            link = by_url.get(str(url), {})
            add(url, "outbound profile/knowledge link", page_url,
                rel=str(link.get("rel") or ""), text=str(link.get("text") or ""),
                in_chrome=bool(link.get("in_nav") or link.get("in_footer")))
    return list(anchors.values())


def verify_anchors(store: EvidenceStore, anchors: List[dict],
                   config: AuditConfig) -> List[dict]:
    if not config.check_external or not anchors:
        return []
    # Knowledge-graph hosts first: they are the ones that actually help an
    # assistant disambiguate an entity.
    anchors = sorted(anchors, key=lambda a: (not a["is_knowledge_host"], a["url"]))
    results: List[dict] = []

    for anchor in anchors[: config.max_external_checks]:
        if store.time_left() < 20:
            break
        record = dict(anchor)
        # The audited site controls these URLs, so a `sameAs` pointing at
        # loopback, RFC 1918 space or a cloud metadata endpoint is refused
        # before a socket opens - the same rule the main crawl obeys. Fetching
        # it through the raw client, as an earlier version did, walked straight
        # past this guard.
        if store.private_refused(anchor["url"]):
            record.update({"checked": False, "skipped": "host is not a public address"})
            results.append(record)
            continue
        # Route through the store, not the raw client: it applies robots.txt
        # for the anchor's own host, the private-address guard, the per-hop
        # redirect guard and the budget cap, and records the response once so
        # nothing is fetched twice.
        response = store.fetch(anchor["url"], method="HEAD",
                               reason="external corroboration: does the anchor resolve?")
        if response is None:
            # robots.txt for that host disallowed it, the address guard refused
            # it, or the budget is spent. None of those is "resolves".
            record.update({"checked": False,
                           "skipped": "not fetched (robots.txt, address guard, or budget)"})
            results.append(record)
            continue
        if response.error or response.status in (403, 405, 501):
            got = store.fetch(anchor["url"], method="GET", force=True,
                              reason="external corroboration: does the anchor resolve?")
            if got is not None:
                response = got
        # Three outcomes, not two. A 404/410 is the platform saying the
        # profile is not there. A 403, a 429, a 999, a timeout or a server
        # error is the platform declining to answer an automated request -
        # which social platforms do routinely - and says nothing about
        # whether the profile exists. Reading the second as the first told
        # sites their live accounts were "dead".
        verdict = semantics.transport_verdict(response.status, response.error)
        record.update({
            "checked": True,
            "status": response.status,
            "final_url": response.final_url,
            "resolves": verdict["verdict"] == "verified",
            "verification": verdict["verdict"],
            "verification_reason": verdict["reason"],
            "error": response.error,
        })
        results.append(record)
    return results


# ---------------------------------------------------------------------------
# orchestrated collection
# ---------------------------------------------------------------------------

def collect(config: AuditConfig) -> dict:
    """Run the whole collection phase and return the evidence bundle."""
    errors = config.validate()
    if errors:
        raise ValueError("invalid audit configuration: " + "; ".join(errors))

    origin, home_url, entry_url = normalize_site_input(config.site)
    store = EvidenceStore(config)
    started_wall = util.iso_now()

    site: Dict[str, object] = {
        "input": config.site,
        "origin": origin,
        "host": urlsplit(origin).netloc,
        "registrable_host": util.registrable_host(origin),
        "home_url": util.normalize_url(home_url) or home_url,
        "entry_url": entry_url,
        "entry_is_home": entry_url == (util.normalize_url(home_url) or home_url),
        "scheme": urlsplit(origin).scheme,
        # The market this audit is about, taken from the URL the caller gave.
        # None for a site that does not partition itself by locale, in which
        # case nothing below changes behaviour at all.
        "locale_scope": locale_prefix(util.url_path(entry_url)),
    }

    # 1. robots.txt - before anything else is fetched.
    robots = store.load_robots(origin)
    ai_agent_summary = {agent: robots.agent_summary(agent) for agent in AI_CRAWLER_AGENTS}
    self_summary = robots.agent_summary(ROBOTS_UA_TOKEN)

    # 2. host canonicalisation + well-known probes
    host_probes = probe_host_variants(store, origin)
    ai_surfaces = probe_ai_surfaces(store, origin)

    # 3. sitemaps
    sitemap_records = collect_sitemaps(store, origin, robots.sitemaps,
                                       scope=site.get("locale_scope"))

    # 4a. the real home page - site-wide identity is only meaningful here
    home_facts = store.get_page(site["home_url"], reason="home page (site root)")
    if home_facts is None:
        store.note("home page could not be fetched; audit continues on transport evidence only")
    elif not home_facts.get("fetch_failed") and not home_facts.get("non_html"):
        home_facts["page_type"] = "home"
        store.page_types[home_facts["url"]] = "home"

    # 4b. the URL the caller actually supplied, when it is deeper than the root.
    #     It is crawled first and seeds the frontier, but it is classified on
    #     its merits rather than being relabelled as the home page.
    entry_facts = None
    if not site["entry_is_home"]:
        entry_facts = store.get_page(entry_url,
                                     reason="audit entry point (URL supplied to the audit)")
        if entry_facts is None:
            store.note(f"the supplied URL {entry_url} could not be fetched")

    # 5. frontier + sampling
    candidates, collapsed = build_frontier(site, [home_facts, entry_facts],
                                           sitemap_records, config)
    store.duplicate_candidates = collapsed
    plan = sample_frontier(candidates, config, already=list(store.pages))
    for url, reason, _predicted in plan:
        if not store.budget_available(html=True):
            break
        store.get_page(url, reason=reason)

    # 5b. second pass: if the first sample found no product page, follow one
    # category page's links (depth 2) rather than reporting a false negative.
    if not any(p.get("page_type") == "product" for p in store.pages.values()):
        for page in list(store.pages.values()):
            if page.get("page_type") not in LISTING_PAGE_TYPES:
                continue
            deeper: List[Tuple[str, str]] = [
                (link["url"], f"linked from category page {page['url']}")
                for link in page.get("links", {}).get("internal", [])
            ]
            extra = sample_frontier(deeper, config, already=list(store.pages))
            for url, reason, predicted in extra:
                if predicted not in ("product", "other"):
                    continue
                if not store.budget_available(html=True):
                    break
                store.get_page(url, reason=reason)
            if any(p.get("page_type") == "product" for p in store.pages.values()):
                break

    # 5c. alias resolution. One document reached at several addresses is one
    #     document: the copies are typed `reference` and kept out of every
    #     content population, with the reason recorded beside each.
    aliases = resolve_aliases(store.pages, store.page_types, str(site["home_url"]))
    if aliases:
        store.note(f"{aliases} fetched URL(s) served another fetched page's document "
                   f"(a redirect, a declared canonical, or an identical copy) and are "
                   f"recorded as reference endpoints rather than as content pages")

    # 6. 404 behaviour
    not_found = probe_not_found(store, origin)

    # 7. declared-anchor corroboration
    parsed_pages = [p for p in store.pages.values()
                    if not p.get("fetch_failed") and not p.get("non_html")]
    anchors = collect_declared_anchors(parsed_pages, origin,
                                       semantics.site_organization_names(parsed_pages))
    anchor_results = verify_anchors(store, anchors, config)
    checked_urls = {record["url"] for record in anchor_results}
    declared_anchors = anchor_results + [
        {**anchor, "checked": False} for anchor in anchors
        if anchor["url"] not in checked_urls]

    # 8. optional browser-rendered evidence
    #
    # Off by default. When it runs, every navigation target goes through
    # `store.allowed` - the same robots.txt and private-address gate the
    # fetcher obeys - so rendering can never reach a URL the crawl would have
    # refused, and the browser's own subresource requests are held to it too.
    render_report = {"attempted": False, "available": False,
                     "render_mode": "static-fetch", "viewport": None,
                     "comparisons": [], "pages_selected": 0, "pages_rendered": 0,
                     "pages_failed": 0}
    if config.use_headless_render:
        from .render import render_pages  # imported lazily: optional dep
        render_report = render_pages(parsed_pages, config, store.allowed)

    bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "generator": generator_block(config),
        "config": config.to_dict(),
        "site": site,
        "started_at": started_wall,
        "finished_at": util.iso_now(),
        "robots": {
            **robots.to_dict(),
            "auditor_agent": ROBOTS_UA_TOKEN,
            "auditor_summary": self_summary,
            "ai_crawlers": ai_agent_summary,
            "ai_crawler_catalog": AI_CRAWLER_AGENTS,
        },
        "host_probes": host_probes,
        "well_known": {
            # kept as a named field because several rules read it directly
            "llms_txt": ai_surfaces.get("llms_txt", {}),
            "ai_surfaces": ai_surfaces,
        },
        "sitemaps": sitemap_records,
        "not_found_probe": not_found,
        "pages": sorted(parsed_pages + [p for p in store.pages.values()
                                        if p.get("fetch_failed") or p.get("non_html")],
                        key=lambda p: (p.get("page_type") != "home", p.get("url", ""))),
        "page_types": dict(store.page_types),
        "declared_anchors": declared_anchors,
        "declared_anchors_total": len(anchors),
        "render": render_report,
        "blocked_by_robots": store.blocked_by_robots,
        "fetch_errors": store.errors,
        "access": assess_access(store, str(site["home_url"])),
        "notes": store.notes,
        "stats": store.stats(),
    }
    # 9. semantics. What kind of thing each product page is about, what each
    #    listing lists, and the shape of the site - decided once, from the
    #    pages read, and recorded so the report can show how. Every commerce
    #    expectation downstream asks this record rather than the page type.
    context = semantics.annotate_bundle(bundle)
    if context.get("site_kind") not in (None, "unknown"):
        store.note(f"site shape read as {context['site_kind']} "
                   f"({context.get('site_kind_confidence')} confidence): "
                   + "; ".join(context.get("site_kind_evidence") or [])[:300])
    bundle["notes"] = store.notes
    return bundle
