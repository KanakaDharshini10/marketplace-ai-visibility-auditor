"""Optional browser-rendered evidence, collected under the crawler's own rules.

The audit's primary evidence is the server response: what a fetch that does not
run scripts receives. That is deliberate and unchanged. But "not in the server
HTML" and "not on the page" are two different observations, and reporting the
first as the second is wrong in a way a site owner can see with their own eyes -
the rating *is* there, it arrives after hydration.

So when Playwright is installed and ``--render`` is passed, a small, bounded
subset of pages is also opened in a headless browser and the resulting DOM is
put through :func:`aiva.extract.extract_page` - the *same* extractor the raw
fetch uses. That yields a rendered fact bag of the same shape as the raw one,
which is what lets every downstream rule compare the two with one helper
(:func:`aiva.analysis.fact_visibility`) instead of learning about browsers.

Nothing here is a second crawler:

* every navigation target is checked by the same :class:`aiva.evidence.EvidenceStore`
  gate the fetcher uses - robots.txt for this auditor's own token, and the
  private-address rule - and a target the store refuses is never opened;
* a request-level route guard applies the same rule to every subresource and
  client-side navigation the page attempts, so a page cannot use the browser to
  reach an address the fetcher would have refused;
* the URL the browser actually ended on is re-checked after navigation, so a
  redirect cannot land the render somewhere the audit may not read;
* it is strictly read-only: navigate, wait, read. No click, no form submission,
  no typing, no downloads, no stored credentials, no cookies carried in.

Absent Playwright, absent a browser binary, or on any failure or timeout, the
audit is unaffected: the raw findings stand, and the rendered evidence is
recorded as unavailable rather than invented.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from . import util
from .config import AuditConfig
from .extract import LISTING_PAGE_TYPES, extract_page
from .httpclient import Response

#: Page-type vocabularies this module orders by. Named tuples rather than
#: literals so the render order follows the classifier's vocabulary instead of
#: keeping a second opinion about what a listing is.
PRODUCT_PAGE_TYPES = ("product",)
HOME_PAGE_TYPES = ("home",)

#: The page types worth rendering. Named rather than written inline so the type
#: vocabulary lives in one place and can be read off by grep.
RENDER_COMPARISON_TYPES = PRODUCT_PAGE_TYPES + tuple(sorted(LISTING_PAGE_TYPES)) \
    + HOME_PAGE_TYPES

#: Resource kinds a rendered *fact* never depends on. Aborting them cuts the
#: bandwidth and the wall clock of a render by most of its weight, and no rule
#: in this marketplace reads a pixel.
SKIPPED_RESOURCE_TYPES = ("image", "media", "font")

#: How much rendered text is kept per page. The rendered fact bag exists to be
#: compared against the raw one, not to be a second copy of the site, and an
#: unbounded ``inner_text`` on a long listing is megabytes of evidence nobody
#: reads. Long enough that every fact the rules look for is inside it.
RENDERED_TEXT_LIMIT = 20_000

#: Per-page and whole-run ceilings, used when the config does not name its own.
DEFAULT_PAGE_TIMEOUT_S = 15.0
DEFAULT_TOTAL_BUDGET_S = 60.0


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401  (probe only)
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# selection - deterministic, bounded, and documented
# ---------------------------------------------------------------------------

def _priority(page: dict) -> int:
    """Render order. Lower sorts first.

    The pages where a raw/rendered difference is *likely* come first, so a
    budget that runs out has spent itself where the answer was in doubt:

    0. a page already showing client-rendering signals - the audit has static
       evidence that this page assembles content after the response, and the
       render is the confirmation of exactly that;
    1. product pages - price, availability, specifications and ratings, the
       facts most often injected by a widget;
    2. category pages - filter and sort controls, often mounted by script;
    3. the home page;
    4. anything else eligible.
    """
    from .analysis import shows_client_rendering_signals
    if shows_client_rendering_signals(page):
        return 0
    page_type = page.get("page_type")
    if page_type in PRODUCT_PAGE_TYPES:
        return 1
    if page_type in LISTING_PAGE_TYPES:
        return 2
    if page_type in HOME_PAGE_TYPES:
        return 3
    return 4


def selectable_pages(pages: List[dict], config: AuditConfig,
                     allowed: Optional[Callable[[str], bool]] = None) -> List[dict]:
    """The pages eligible for rendering, in the order they would be rendered.

    Eligibility is: a page the crawl actually read (not an error, not a
    non-HTML document), of a type a rendered comparison says anything about,
    and - when a store gate is supplied - a URL that gate still allows. The
    order is :func:`_priority` then URL, so it never depends on dict ordering,
    crawl timing or the filesystem: two runs over one site select the same
    pages in the same order.
    """
    eligible = []
    for page in pages:
        if page.get("fetch_failed") or page.get("non_html"):
            continue
        if page.get("page_type") not in RENDER_COMPARISON_TYPES and \
                not _has_client_render_signals(page):
            continue
        url = page.get("final_url") or page.get("url") or ""
        if not url:
            continue
        if allowed is not None and not allowed(url):
            continue
        eligible.append(page)
    eligible.sort(key=lambda p: (_priority(p), str(p.get("url") or "")))
    return eligible[: max(0, int(config.render_page_limit))]


def _has_client_render_signals(page: dict) -> bool:
    from .analysis import shows_client_rendering_signals
    return shows_client_rendering_signals(page)


# ---------------------------------------------------------------------------
# the rendered fact bag
# ---------------------------------------------------------------------------

def rendered_facts(raw_page: dict, html: str, final_url: str) -> Dict[str, Any]:
    """Put the rendered DOM through the *same* extractor the raw fetch uses.

    This is the whole reason no rule downstream needs to know a browser was
    involved: the rendered fact bag has the same keys as the raw one, so
    ``listing_controls``, ``structured_attribute_presence``, ``products_on``
    and every other reader works on it unchanged.

    Only the fields a rule actually reads are kept, and the text is capped, so
    a bundle with rendering enabled stays a document a person can open.
    """
    response = Response(requested_url=raw_page.get("url") or final_url,
                        final_url=final_url, status=200, body=html,
                        content_type="text/html", charset="utf-8")
    facts = extract_page(response, html=html)
    keep = ("headings", "links", "forms", "jsonld_blocks", "jsonld_types", "microdata",
            "mentions", "prices_in_text", "text_word_count", "open_graph", "meta",
            "scripts", "images", "tables", "definition_lists", "attribute_pairs",
            "language", "language_supported", "canonical", "title", "hreflang_alternates")
    out: Dict[str, Any] = {key: facts[key] for key in keep if key in facts}
    for field in ("text", "main_text", "block_text"):
        value = facts.get(field)
        if isinstance(value, str):
            out[field] = value[:RENDERED_TEXT_LIMIT]
    out["final_url"] = final_url
    return out


# ---------------------------------------------------------------------------
# collection
# ---------------------------------------------------------------------------

def _report(config: AuditConfig, **extra: Any) -> Dict[str, Any]:
    """The render block, with every field a consumer reads always present."""
    report: Dict[str, Any] = {
        "attempted": True,
        "available": False,
        "render_mode": "static-fetch",
        "viewport": None,
        "comparisons": [],
        "error": None,
        "pages_selected": 0,
        "pages_rendered": 0,
        "pages_failed": 0,
        "budget": {
            "page_limit": int(config.render_page_limit),
            "page_timeout_s": float(getattr(config, "render_timeout_s",
                                            DEFAULT_PAGE_TIMEOUT_S)),
            "total_budget_s": float(getattr(config, "render_budget_s",
                                            DEFAULT_TOTAL_BUDGET_S)),
        },
        "budget_exhausted": False,
        "elapsed_s": 0.0,
    }
    report.update(extra)
    return report


def render_pages(pages: List[dict], config: AuditConfig,
                 allowed: Optional[Callable[[str], bool]] = None) -> Dict[str, Any]:
    """Render the selected pages and attach a rendered fact bag to each.

    ``allowed`` is :meth:`aiva.evidence.EvidenceStore.allowed` - robots.txt for
    this auditor's own product token, plus the private-address rule. It is not
    optional in a real audit: it is passed in rather than reimplemented so
    there is exactly one place in this package that decides whether a URL may
    be opened, and rendering obeys it.

    Mutates each rendered page in place with ``page["rendered"]`` and returns
    the render block for the bundle. Never raises: every failure path records
    itself and leaves the raw evidence untouched.
    """
    report = _report(config)
    if not playwright_available():
        report["error"] = "playwright not installed; static heuristics used instead"
        report["unavailable_reason"] = "playwright_not_installed"
        return report

    targets = selectable_pages(pages, config, allowed)
    report["pages_selected"] = len(targets)
    report["selected_urls"] = [p.get("final_url") or p.get("url") for p in targets]
    if not targets:
        report["error"] = "no page was eligible for rendering"
        report["unavailable_reason"] = "no_eligible_page"
        return report

    from playwright.sync_api import sync_playwright  # type: ignore

    viewport = {"width": int(config.render_viewport_width),
                "height": int(config.render_viewport_height)}
    page_timeout = float(getattr(config, "render_timeout_s", DEFAULT_PAGE_TIMEOUT_S))
    total_budget = float(getattr(config, "render_budget_s", DEFAULT_TOTAL_BUDGET_S))
    started = time.monotonic()

    def route_guard(route, request):
        """The fetcher's rule, applied to everything the browser asks for.

        A rendered page requests subresources and may navigate itself. Neither
        goes through the store, so without this the browser would be a way
        around the guard the fetcher obeys. Anything the store refuses is
        aborted here; images, media and fonts are aborted too, because no rule
        reads them and they are most of the bytes.
        """
        try:
            if allowed is not None and not allowed(request.url):
                route.abort()
                return
            if request.resource_type in SKIPPED_RESOURCE_TYPES:
                route.abort()
                return
            route.continue_()
        except Exception:                                   # pragma: no cover
            try:
                route.abort()
            except Exception:
                pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--disable-dev-shm-usage"])
            report["available"] = True
            report["render_mode"] = "headless-chromium"
            report["viewport"] = dict(viewport)
            try:
                context = browser.new_context(
                    user_agent=config.user_agent or "MarketplaceAIVisibilityAuditor",
                    java_script_enabled=True,
                    viewport=dict(viewport),
                    # No stored state is carried in: the render sees the site as
                    # a first-time anonymous visitor does, never as anyone
                    # signed in. There is no credential in this process to use.
                    storage_state=None,
                )
                context.route("**/*", route_guard)
                browser_page = context.new_page()
                for facts in targets:
                    if time.monotonic() - started >= total_budget:
                        report["budget_exhausted"] = True
                        break
                    report["comparisons"].append(
                        _render_one(browser_page, facts, page_timeout, allowed))
            finally:
                browser.close()
    except Exception as exc:                                # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
        if not report["available"]:
            report["unavailable_reason"] = "browser_launch_failed"

    report["elapsed_s"] = round(time.monotonic() - started, 2)
    report["pages_rendered"] = sum(1 for c in report["comparisons"] if c.get("ok"))
    report["pages_failed"] = sum(1 for c in report["comparisons"] if not c.get("ok"))
    return report


def _render_one(browser_page, facts: dict, page_timeout: float,
                allowed: Optional[Callable[[str], bool]]) -> Dict[str, Any]:
    """One page: navigate, re-check where we landed, read, extract."""
    url = facts.get("final_url") or facts.get("url")
    entry: Dict[str, Any] = {"url": url}
    started = time.monotonic()
    try:
        response = browser_page.goto(url, wait_until="networkidle",
                                     timeout=int(page_timeout * 1000))
        landed = browser_page.url or url
        # A redirect the browser followed is a navigation the store never saw.
        # If it ended somewhere the audit may not read, the render is discarded
        # rather than reported: evidence obtained past the guard is not evidence
        # this audit is entitled to.
        if allowed is not None and not allowed(landed):
            entry.update({"ok": False, "error": "redirect_target_refused",
                          "detail": "the render redirected to a URL the audit may not "
                                    "read; the rendered evidence was discarded",
                          "final_url": landed})
            return entry
        html = browser_page.content()
        rendered_text = util.collapse_ws(browser_page.inner_text("body"))
        raw_words = int(facts.get("text_word_count") or 0)
        rendered_words = util.word_count(rendered_text)
        facts["rendered"] = rendered_facts(facts, html, landed)
        facts["rendered"]["ok"] = True
        entry.update({
            "ok": True,
            "final_url": landed,
            "status": getattr(response, "status", None),
            "raw_word_count": raw_words,
            "rendered_word_count": rendered_words,
            "content_gain_ratio": round(rendered_words / max(1, raw_words), 2),
            "jsonld_after_render": html.count("application/ld+json"),
            "jsonld_before_render": len(facts.get("jsonld_blocks", [])),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        })
    except Exception as exc:                                # noqa: BLE001
        name = type(exc).__name__
        entry.update({
            "ok": False,
            "error": "timeout" if "Timeout" in name else f"{name}: {exc}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        })
    return entry


def compare_rendered(pages: List[dict], config: AuditConfig,
                     allowed: Optional[Callable[[str], bool]] = None) -> Dict[str, Any]:
    """Backwards-compatible name for :func:`render_pages`."""
    return render_pages(pages, config, allowed)
