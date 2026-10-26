"""Test helpers: build realistic evidence bundles without touching a network."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "lib"))

from aiva import util                                  # noqa: E402
from aiva.config import AI_CRAWLER_AGENTS, AuditConfig  # noqa: E402
from aiva.evidence import BUNDLE_SCHEMA_VERSION, generator_block  # noqa: E402
from aiva.extract import classify_page, extract_page   # noqa: E402
from aiva.httpclient import Response                   # noqa: E402
from aiva.orchestrator import load_specialists         # noqa: E402
from aiva.robots import RobotsTxt                      # noqa: E402
from aiva.version import ROBOTS_UA_TOKEN               # noqa: E402

ORIGIN = "https://shop.example"


def response(url: str, html: str = "", status: int = 200,
             headers: Optional[Dict[str, str]] = None,
             redirects: Optional[List] = None,
             content_type: str = "text/html",
             elapsed_ms: int = 120) -> Response:
    return Response(
        requested_url=url, final_url=url, status=status, reason="OK",
        headers=headers or {}, body=html, body_bytes=len(html.encode("utf-8")),
        content_type=content_type, charset="utf-8", elapsed_ms=elapsed_ms,
        redirects=redirects or [])


def page(url: str, html: str, **kwargs) -> dict:
    """Extract a page fact-bag from real HTML, exactly as the crawler would."""
    resp = response(url, html, **kwargs)
    facts = extract_page(resp)
    facts["page_type"] = classify_page(resp.final_url or url, facts)
    facts["fetch_reason"] = "test fixture"
    return facts


def error_page(url: str, status: int = 404) -> dict:
    return {"url": util.normalize_url(url) or url, "final_url": url, "status": status,
            "content_type": "text/html", "bytes": 0, "elapsed_ms": 10, "redirects": [],
            "headers": {}, "fetch_failed": True, "page_type": "error"}


def html_doc(title: str = "Example", body: str = "<h1>Example</h1>", head: str = "",
             lang: str = "en", canonical: Optional[str] = None,
             description: str = "An example page.", open_graph: bool = True) -> str:
    """A synthetic page that is *ordinary*, not minimal.

    Every stub built here stands in for a page a competent team shipped, so it
    carries what such a page carries. Open Graph is included by default for
    that reason: without it every synthetic bundle in the suite trips
    MR-OPEN-GRAPH-INCOMPLETE, and a stub's own thinness starts reading as a
    defect of whatever the test was actually about. Pass ``open_graph=False``
    to build a page that genuinely lacks it.

    ``og:site_name`` is deliberately not emitted: the entity rules compare it
    against the brand name, and a helper-invented value would quietly become a
    second trading name.
    """
    canonical_tag = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    og_tags = ""
    if open_graph:
        og_tags = (f'<meta property="og:title" content="{title}">'
                   f'<meta property="og:description" content="{description}">'
                   f'<meta property="og:type" content="website">')
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{title}</title>'
            f'<meta name="description" content="{description}">'
            f'{og_tags}{canonical_tag}{head}</head><body>{body}</body></html>')


def jsonld(payload: str) -> str:
    return f'<script type="application/ld+json">{payload}</script>'


def _well_known(origin: str, llms_txt: Optional[dict]) -> dict:
    """Mirror what discover.probe_ai_surfaces produces."""
    llms = llms_txt or {"checked": True, "status": 404, "present": False,
                        "url": origin + "/llms.txt", "link_count": 0}
    agents = {"checked": True, "status": 404, "present": False,
              "url": origin + "/agents.md", "link_count": 0}
    return {"llms_txt": llms, "ai_surfaces": {"llms_txt": llms, "agents_md": agents}}


def bundle(pages: Optional[List[dict]] = None, *, robots_raw: Optional[str] = None,
           robots_status: int = 200, robots_error: Optional[str] = None,
           sitemaps: Optional[List[dict]] = None,
           host_probes: Optional[dict] = None,
           not_found: Optional[dict] = None,
           declared_anchors: Optional[List[dict]] = None,
           declared_total: Optional[int] = None,
           llms_txt: Optional[dict] = None,
           render: Optional[dict] = None,
           config: Optional[AuditConfig] = None,
           origin: str = ORIGIN) -> dict:
    pages = pages or []
    config = config or AuditConfig(site=origin)
    robots = RobotsTxt.from_response(origin + "/robots.txt", robots_status,
                                     robots_raw if robots_raw is not None else "",
                                     robots_error)
    if robots_raw is None and robots_status == 200:
        robots = RobotsTxt.from_response(origin + "/robots.txt", 200,
                                         "User-agent: *\nDisallow:\n")
    anchors = declared_anchors if declared_anchors is not None else []
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "generator": generator_block(config),
        "config": config.to_dict(),
        "site": {
            "input": origin, "origin": origin,
            "host": origin.split("//", 1)[-1],
            "registrable_host": util.registrable_host(origin),
            "home_url": origin + "/",
            "scheme": origin.split(":", 1)[0],
        },
        "started_at": util.iso_now(),
        "finished_at": util.iso_now(),
        "robots": {
            **robots.to_dict(),
            "auditor_agent": ROBOTS_UA_TOKEN,
            "auditor_summary": robots.agent_summary(ROBOTS_UA_TOKEN),
            "ai_crawlers": {agent: robots.agent_summary(agent) for agent in AI_CRAWLER_AGENTS},
            "ai_crawler_catalog": AI_CRAWLER_AGENTS,
        },
        "host_probes": host_probes or {},
        "well_known": _well_known(origin, llms_txt),
        "sitemaps": sitemaps if sitemaps is not None else [{
            "url": origin + "/sitemap.xml", "source": "well-known path probe", "status": 200,
            "kind": "urlset", "error": None, "url_count": len(pages),
            "entries_captured": len(pages),
            "missing_lastmod": 0,
            "lastmods": [util.iso_now()[:10]] * max(1, len(pages)),
            "entries": [{"url": p.get("url"), "lastmod": util.iso_now()[:10]} for p in pages],
            "sample_urls": [p.get("url") for p in pages],
        }],
        "not_found_probe": not_found or {"url": origin + "/aiva-probe", "checked": True,
                                         "status": 404, "returns_404": True,
                                         "final_url": origin + "/aiva-probe"},
        "pages": pages,
        "page_types": {p.get("url"): p.get("page_type") for p in pages},
        "declared_anchors": anchors,
        "declared_anchors_total": declared_total if declared_total is not None else len(anchors),
        "render": render or {"attempted": False, "available": False, "comparisons": []},
        "blocked_by_robots": [],
        "fetch_errors": [],
        "notes": [],
        "stats": {"requests": len(pages) + 3, "bytes_downloaded": 10_000,
                  "unique_urls_fetched": len(pages) + 3,
                  "html_pages_parsed": len(pages), "cache_reuses": 2,
                  "blocked_by_robots": 0, "errors": 0, "elapsed_s": 1.0,
                  "effective_delay_s": 0.4},
    }


SHOP_PRODUCT_LD = (
    '{{"@context":"https://schema.org","@type":"Product","name":"{name}",'
    '"sku":"{sku}","brand":{{"@type":"Brand","name":"Acme"}},'
    '"color":"Blue","material":"Mesh",'
    '"additionalProperty":[{{"@type":"PropertyValue","name":"Weight","value":"{weight}"}}],'
    '"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"INR",'
    '"availability":"https://schema.org/InStock"}}}}')


def commerce_bundle(origin: str = ORIGIN) -> dict:
    """A small but complete shop: home, category, two products.

    Enough for every pillar to be measurable - in particular answerability,
    which needs an observed subject before it will generate a question. Used by
    suites that need "a normal crawl" rather than the minimum parseable page.
    """
    home = page(origin + "/", html_doc(
        title="Acme", canonical=origin + "/",
        body='<h1>Acme</h1><a href="/collections/shoes">Shoes</a>'
             '<a href="/pages/returns">Returns</a>'))
    listing = page(origin + "/collections/shoes", html_doc(
        title="Shoes", canonical=origin + "/collections/shoes",
        body='<h1>Shoes</h1><a href="/products/aero">Aero Runner</a>'
             '<a href="/products/terra">Terra Trail</a>'))
    products = [
        page(origin + "/products/aero", html_doc(
            title="Aero Runner", canonical=origin + "/products/aero",
            head=jsonld(SHOP_PRODUCT_LD.format(name="Aero Runner", sku="SKU-1",
                                               weight="245", price="5499")),
            body="<h1>Aero Runner</h1><p>&#8377;5,499 - in stock.</p>"
                 "<table><tr><th>Weight</th><td>245 g</td></tr></table>")),
        page(origin + "/products/terra", html_doc(
            title="Terra Trail", canonical=origin + "/products/terra",
            head=jsonld(SHOP_PRODUCT_LD.format(name="Terra Trail", sku="SKU-2",
                                               weight="310", price="6999")),
            body="<h1>Terra Trail</h1><p>&#8377;6,999 - in stock.</p>"
                 "<table><tr><th>Weight</th><td>310 g</td></tr></table>")),
    ]
    policy = page(origin + "/pages/returns", html_doc(
        title="Returns", canonical=origin + "/pages/returns",
        body="<h1>Returns</h1><p>Free returns within 30 days of delivery. "
             "We ship across India. We accept Visa, Mastercard and UPI.</p>"))
    return bundle([home, listing, policy] + products, origin=origin)


_SPECIALISTS = None


def specialist(skill_id: str):
    """Load a specialist module through the manifest, as the entrypoint does."""
    global _SPECIALISTS
    if _SPECIALISTS is None:
        _SPECIALISTS = dict(load_specialists())
    return _SPECIALISTS[skill_id]


def rule_ids(findings) -> List[str]:
    return [f.rule_id for f in findings]


def run(skill_id: str, bundle_dict: dict):
    return specialist(skill_id).analyze(bundle_dict)


def find(findings, rule_id: str):
    for item in findings:
        if item.rule_id == rule_id:
            return item
    return None
