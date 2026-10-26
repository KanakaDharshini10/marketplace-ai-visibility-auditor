"""The shared evidence layer.

Every byte the marketplace looks at passes through :class:`EvidenceStore`.
It is a *fetch-once* cache: asking for the same URL twice returns the first
recorded :class:`~aiva.httpclient.Response` and increments a reuse counter
instead of hitting the network again. Specialist skills never get a client -
they get the serialised bundle - so "reuse shared evidence instead of
repeatedly downloading pages" is a property of the architecture, not a rule
somebody has to remember.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import util
from .config import AuditConfig
from .extract import (LISTING_PAGE_TYPES, NON_LISTING_PAGE_TYPES,
                      NON_PRODUCT_PAGE_TYPES, classify_page_verbose,
                      extract_page)
from .httpclient import HttpClient, Response
from .robots import RobotsTxt
from .version import ROBOTS_UA_TOKEN, TOOL_NAME, USER_AGENT, __version__

BUNDLE_SCHEMA_VERSION = "1.0"

_MAX_JSONLD_NODES = 120
_MAX_STRING = 600
_MAX_LIST = 60


def prune(value: Any, depth: int = 0) -> Any:
    """Bound the size of arbitrary parsed JSON so bundles stay dumpable."""
    if depth > 10:
        return "…"
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING else value[:_MAX_STRING] + "…"
    if isinstance(value, list):
        return [prune(v, depth + 1) for v in value[:_MAX_LIST]]
    if isinstance(value, dict):
        return {k: prune(v, depth + 1) for k, v in list(value.items())[:80]}
    return value


class EvidenceStore:
    """Single source of observed truth for one audit run."""

    def __init__(self, config: AuditConfig) -> None:
        self.config = config
        self.client = HttpClient(
            user_agent=config.user_agent or USER_AGENT,
            timeout=config.timeout_s,
            delay=config.request_delay_s,
            max_bytes=config.max_bytes_per_response,
            max_retries=config.max_retries,
        )
        # Refuse redirects that leave for a non-public address mid-chain, not
        # only when the final URL is private. A page can 302 through loopback
        # or a metadata endpoint and bounce back to a public URL, which the
        # final-URL check alone would never see.
        self.client.redirect_guard = self._redirect_blocked
        self.robots: RobotsTxt = RobotsTxt.allow_all()
        #: robots.txt for hosts other than the audited origin, reached through
        #: a redirect or a declared off-site anchor. Fetched once each.
        self._host_robots: Dict[str, RobotsTxt] = {}
        self._primary_origin: str = util.origin(config.site) if config.site else ""
        self.responses: Dict[str, Response] = {}
        self.pages: Dict[str, dict] = {}
        self.page_types: Dict[str, str] = {}
        self.blocked_by_robots: List[dict] = []
        self.errors: List[dict] = []
        self.notes: List[str] = []
        self.reuse_count = 0
        self.started_at = time.monotonic()
        self.html_fetch_count = 0
        self.duplicate_candidates = 0
        self._budget_exhausted = False

    # -- budget ------------------------------------------------------------
    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def time_left(self) -> float:
        return self.config.total_time_budget_s - self.elapsed_s

    def budget_available(self, *, html: bool = True) -> bool:
        if self.time_left() <= 5:
            if not self._budget_exhausted:
                self.note("time budget exhausted; crawl stopped early")
                self._budget_exhausted = True
            return False
        if html and self.html_fetch_count >= self.config.max_pages:
            return False
        return True

    def note(self, message: str) -> None:
        self.notes.append(message)

    # -- robots ------------------------------------------------------------
    def load_robots(self, origin: str) -> RobotsTxt:
        url = origin.rstrip("/") + "/robots.txt"
        self._primary_origin = util.origin(url) or origin.rstrip("/")
        response = self.client.fetch(url)
        self.responses[url] = response
        self.robots = RobotsTxt.from_response(
            url, response.status, response.body, response.error)
        delay = self.robots.crawl_delay_for(ROBOTS_UA_TOKEN)
        if delay and delay > self.client.delay:
            # Obey a stricter Crawl-delay, capped so one hostile value cannot
            # blow the 5-minute budget.
            self.client.delay = min(delay, 5.0)
            self.note(f"honouring Crawl-delay: {self.client.delay}s between requests")
        return self.robots

    def robots_for(self, url: str) -> RobotsTxt:
        """The robots.txt that governs ``url`` - fetched once per host.

        The audited origin's robots.txt is loaded up front. Any other host is
        resolved on demand, because a redirect can carry us somewhere this
        store holds no policy for, and "we have no policy for that host" must
        mean *go and read it*, never *assume yes*.
        """
        target = util.origin(url)
        if not target or target == self._primary_origin:
            return self.robots
        cached = self._host_robots.get(target)
        if cached is not None:
            return cached
        robots_url = target + "/robots.txt"
        if not self.budget_available(html=False):
            # Out of budget to vet it, so it does not get fetched.
            robots = RobotsTxt.from_response(robots_url, 0, "", "budget exhausted")
            robots.unreachable = True
        else:
            response = self.client.fetch(robots_url)
            robots = RobotsTxt.from_response(
                robots_url, response.status, response.body, response.error)
        self._host_robots[target] = robots
        return robots

    def private_refused(self, url: str) -> bool:
        """True when ``url`` points at a non-public address we must not fetch.

        Auditing a private address is legitimate when the operator named it:
        a staging box, a dev server, the bundled fixture server on loopback.
        What is never legitimate is the *audited site's own markup* steering
        outbound requests at a different internal address - a declared
        ``sameAs`` anchor pointing at cloud instance metadata, or a redirect
        into RFC 1918 space. So the rule is not "no private hosts", it is
        "no private host other than the one the operator asked for".
        """
        if self.config.allow_private_hosts:
            return False
        if not util.is_private_host(url):
            return False
        return util.registrable_host(url) != util.registrable_host(self.config.site)

    def _redirect_blocked(self, url: str) -> Optional[str]:
        """Per-hop redirect guard for the HTTP client: a reason, or ``None``.

        Refuses a redirect target that resolves to a non-public address the
        operator did not ask for - the same rule :meth:`private_refused`
        applies to a URL this store fetches directly, extended to the
        intermediate hops the store never sees.
        """
        if self.private_refused(url):
            return "redirect target resolves to a non-public address"
        return None

    def allowed(self, url: str) -> bool:
        if not self.config.respect_robots:  # unreachable: validate() forbids it
            return True
        if self.private_refused(url):
            return False
        return self.robots_for(url).can_fetch(ROBOTS_UA_TOKEN, url)

    def _record_block(self, url: str, reason: str, *, via: str = "") -> None:
        if self.private_refused(url):
            entry = {"url": url, "reason": reason, "rule": None, "group_agents": [],
                     "robots_unreachable": False,
                     "refused": "host is not a public address"}
            if via:
                entry["reached_via"] = via
            self.blocked_by_robots.append(entry)
            return
        allowed, rule, group = self.robots_for(url).decision(ROBOTS_UA_TOKEN, url)
        entry = {
            "url": url,
            "reason": reason,
            "rule": rule.to_dict() if rule else None,
            "group_agents": list(group.agents) if group else [],
            "robots_unreachable": self.robots.unreachable,
        }
        if via:
            entry["reached_via"] = via
        self.blocked_by_robots.append(entry)

    # -- fetching ----------------------------------------------------------
    def fetch(self, url: str, *, reason: str = "", method: str = "GET",
              force: bool = False, count_as_page: bool = False,
              timeout: Optional[float] = None) -> Optional[Response]:
        """Fetch once, then serve from cache forever."""
        normalized = util.normalize_url(url) or url
        cached = self.responses.get(normalized)
        if cached is not None and not force:
            self.reuse_count += 1
            reused = Response(**{**cached.__dict__})
            reused.from_cache = True
            return reused

        if not self.allowed(normalized):
            self._record_block(normalized, reason)
            return None

        if count_as_page and not self.budget_available(html=True):
            return None
        if not self.budget_available(html=False):
            return None

        # No single request may outlive the audit's declared budget. The
        # budget guard above runs *before* a fetch, so without this a request
        # begun with four seconds left could still spend the full timeout twice
        # over - which is how a run that promised 240 seconds took several
        # minutes and could not say why.
        remaining = max(1.0, self.time_left())
        effective = min(timeout or self.client.timeout, remaining)
        response = self.client.fetch(normalized, method=method, timeout=effective)

        # Re-authorise the URL that actually served the bytes. Checking only
        # the requested URL leaves an open door: a permitted URL that 302s into
        # a disallowed path hands us content robots.txt refused, and the report
        # would then simultaneously list that URL as blocked and quote its body.
        # A redirect that lands on another host is checked against *that* host's
        # robots.txt, fetched on demand - never against this one's.
        final = util.normalize_url(response.final_url or normalized) or normalized
        if final != normalized and not self.allowed(final):
            self._record_block(final, reason, via=normalized)
            return None

        self.responses[normalized] = response
        if response.error:
            self.errors.append({"url": normalized, "error": response.error, "reason": reason})
        # The page budget counts documents actually served, not attempts. A
        # timeout, a connection reset or a circuit-breaker skip returns a
        # Response carrying an error and no document, and counting it spent a
        # slot the crawl could have used on a page that answers - so a
        # black-holed host quietly shrank the sample and read as a thin site.
        if count_as_page and not response.error:
            self.html_fetch_count += 1
        return response

    def get_page(self, url: str, *, reason: str = "") -> Optional[dict]:
        """Fetch (once) and parse an HTML document into its fact bag."""
        normalized = util.normalize_url(url) or url
        if normalized in self.pages:
            self.reuse_count += 1
            return self.pages[normalized]

        response = self.fetch(normalized, reason=reason, count_as_page=True)
        if response is None:
            return None
        if response.error:
            return None
        if response.status >= 400:
            # Still evidence: record the transport facts without parsing.
            facts = {
                "url": normalized,
                "final_url": response.final_url,
                "status": response.status,
                "content_type": response.content_type,
                "bytes": response.body_bytes,
                "elapsed_ms": response.elapsed_ms,
                "redirects": [{"status": s, "location": loc} for s, loc in response.redirects],
                "headers": dict(response.headers),
                "fetch_failed": True,
                "page_type": "error",
                "fetch_reason": reason,
            }
            self.pages[normalized] = facts
            self.page_types[normalized] = "error"
            return facts
        if not response.is_html and "xml" not in (response.content_type or ""):
            facts = {
                "url": normalized, "final_url": response.final_url,
                "status": response.status, "content_type": response.content_type,
                "bytes": response.body_bytes, "non_html": True,
                "headers": dict(response.headers), "redirects": [],
                "page_type": "non_html",
                "fetch_reason": reason,
            }
            self.pages[normalized] = facts
            self.page_types[normalized] = "non_html"
            return facts

        facts = extract_page(response)
        facts["jsonld_nodes"] = [prune(n) for n in facts["jsonld_nodes"][:_MAX_JSONLD_NODES]]
        facts["fetch_reason"] = reason
        # Classify on the URL that actually served the content: a retired
        # product URL that redirects to the home page is a home page, and
        # counting it as a product page would poison every product-page ratio.
        landed_on = response.final_url or normalized
        verdict = classify_page_verbose(landed_on, facts)
        page_type = verdict["page_type"]
        facts["page_type"] = page_type
        if landed_on != normalized:
            # Otherwise a retired product URL that redirects to the home page
            # is reported as "the site root" with no hint of why.
            verdict["decided_by"] += f" (this URL redirected to {landed_on})"
        # Why, not only what. Three rounds of page-type work each started with
        # a reader asking why a page had been called a product and having to
        # reconstruct the answer from the code. It travels with the page.
        facts["page_type_evidence"] = {k: v for k, v in verdict.items()
                                       if k != "page_type" and v}
        self.pages[normalized] = facts
        self.page_types[normalized] = page_type
        return facts

    # -- bundle ------------------------------------------------------------
    def stats(self) -> dict:
        return {
            "requests": self.client.request_count,
            "bytes_downloaded": self.client.bytes_downloaded,
            "unique_urls_fetched": len(self.responses),
            "html_pages_parsed": len([p for p in self.pages.values()
                                      if not p.get("fetch_failed") and not p.get("non_html")]),
            "cache_reuses": self.reuse_count,
            "duplicate_urls_collapsed": self.duplicate_candidates,
            "blocked_by_robots": len(self.blocked_by_robots),
            "errors": len(self.errors),
            "elapsed_s": round(self.elapsed_s, 2),
            "effective_delay_s": self.client.delay,
            # Where the wall clock went. A zero-page audit that finished in 15
            # seconds and one that took four minutes look identical in every
            # other field, and they are entirely different situations: one
            # origin answered quickly and refused, the other never answered.
            "transport": {
                "time_by_outcome_s": {k: round(v, 2)
                                      for k, v in self.client.time_by_outcome.items()},
                "transport_failures": self.client.transport_failures,
                "retries_spent": self.client.retries_spent,
                "requests_not_attempted": self.client.skipped_by_circuit,
                "hosts_stopped_early": dict(self.client.open_circuits),
                "request_timeout_s": self.client.timeout,
                "max_retries": self.client.max_retries,
            },
        }


# ---------------------------------------------------------------------------
# bundle accessors - the only API specialist skills use
# ---------------------------------------------------------------------------

#: Parsed pages that are not content documents: a search results page, an
#: account/auth endpoint, a planner or configurator. They are read, typed and
#: listed in the manifest, but they are not samples for any claim about the
#: site's content - "N of M pages carry no structured data" computed over a
#: search results page and a sign-in form describes no document the site
#: publishes. Asked for by type, or with ``include_utility``, they come back.
UTILITY_PAGE_TYPES = frozenset({"search", "account", "tool"})


def pages(bundle: dict, *types: str, include_errors: bool = False,
          include_aliases: bool = False, include_utility: bool = False) -> List[dict]:
    """The parsed **content documents**, optionally filtered by page type.

    This is the population every content rule samples, so what it leaves out
    is the point:

    * ``fetch_failed`` / ``non_html`` records - transport evidence, not a
      document (``include_errors`` brings them back);
    * ``reference`` pages - another fetched page's document reached at a second
      address, via a redirect, a declared canonical or an identical copy. Not a
      distinct sample: counted once as itself and once under the alias, the
      home page sat in every ratio twice and its correct canonical was reported
      as a defect (``include_aliases``);
    * ``search``, ``account`` and ``tool`` endpoints - read and typed, but not
      content the site publishes to be quoted (``include_utility``).

    Naming a type explicitly always returns it: ``pages(bundle, "search")`` is
    a request for the search pages, not a content sample.
    """
    wanted = {t.lower() for t in types} if types else None
    out = []
    for page in bundle.get("pages", []):
        if not include_errors and (page.get("fetch_failed") or page.get("non_html")):
            continue
        page_type = (page.get("page_type") or "").lower()
        asked_for = bool(wanted and page_type in wanted)
        if page_type == "reference" and not include_aliases and not asked_for:
            continue
        if page_type in UTILITY_PAGE_TYPES and not include_utility and not asked_for:
            continue
        if wanted and page_type not in wanted:
            continue
        out.append(page)
    return out


def page_by_url(bundle: dict, url: str) -> Optional[dict]:
    target = util.normalize_url(url) or url
    for page in bundle.get("pages", []):
        if page.get("url") == target or page.get("final_url") == target:
            return page
    return None


def home_page(bundle: dict) -> Optional[dict]:
    """The verified home page, or ``None``.

    Returns a page only when it really is the site root: the URL recorded as
    ``site.home_url``, or a page the classifier typed as ``home``. The previous
    fallback to ``pages(bundle)[0]`` meant that when the root fetch failed, an
    arbitrary product or policy page was handed to every rule that says "the
    home page" - so findings named a URL that was not the home page, and
    site-identity checks were run against a document that never claimed to
    carry the site's identity. An unfetchable home page is missing evidence,
    and the rules that need it now suppress instead of guessing.
    """
    home_url = bundle.get("site", {}).get("home_url")
    if home_url:
        found = page_by_url(bundle, home_url)
        if found and not found.get("fetch_failed"):
            return found
    for candidate in pages(bundle, "home"):
        if not candidate.get("fetch_failed"):
            return candidate
    return None


def product_pages(bundle: dict) -> List[dict]:
    """The single funnel every product-specific rule goes through.

    The positive filter alone would be enough today, but stating the exclusion
    as well is what makes the invariant checkable: a promotional listing, a
    membership programme, a support hub or a policy page can never be handed to
    a rule that is about to say "N of M product pages".
    """
    return [page for page in pages(bundle, "product")
            if (page.get("page_type") or "") not in NON_PRODUCT_PAGE_TYPES]


def category_pages(bundle: dict) -> List[dict]:
    """The single funnel every listing-only rule goes through.

    The twin of :func:`product_pages`, and it exists for the same reason. The
    listing rules ask why a page has no filtering, no sorting and no comparison
    support - questions that only make sense about a set. Asked of a product
    detail page they are nonsense, and a reader who sees one cannot tell
    whether the auditor misread the page or misunderstands catalogues.

    Every rule that samples listings goes through here, so "which pages are
    listings?" is answered once, by the collector, from the classification
    frozen in the bundle. A rule that answers it for itself is a second
    opinion, and a second opinion is how one report comes to contradict
    itself about the same URL.
    """
    return [page for page in pages(bundle, *sorted(LISTING_PAGE_TYPES))
            if (page.get("page_type") or "") not in NON_LISTING_PAGE_TYPES]


def site_host(bundle: dict) -> str:
    return bundle.get("site", {}).get("host", "")


def bundle_meta(bundle: dict) -> dict:
    return {
        "generator": bundle.get("generator", {}),
        "site": bundle.get("site", {}),
        "stats": bundle.get("stats", {}),
    }


def generator_block(config: AuditConfig) -> dict:
    return {
        "tool": TOOL_NAME,
        "version": __version__,
        "user_agent": config.user_agent or USER_AGENT,
        "robots_token": ROBOTS_UA_TOKEN,
        "mode": "read-only (GET/HEAD only, no authentication, no site modification)",
    }
