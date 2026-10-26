"""Page eligibility and provenance: a rule only ever sees the pages it is about.

Prompted by a live audit of a large marketplace in which a search results
page (`/s/?k=...`) was cited by product-only and listing-only findings, and two
navigation addresses that serve the home page (`/ref=nav_logo`,
`/ref=footer_logo`) were reported as content pages whose canonical points
elsewhere. Neither is a fact about that site; both are shapes any site can
take, and every test here is written against the shape:

* a **search results page** read as a listing (many prices) or as a product (a
  quick-add button on every result counted as *the* purchase affordance);
* a **navigation/reference address** - a second URL that serves a document the
  crawl already holds - read as a page of its own.

Nothing here matches a URL string. The search page is recognised from what the
page says about the URL it was fetched at (its own search box pre-filled with
the query, or its own parameter name in the query); the alias from the page's
declared canonical, its redirect, or its identity with an earlier page.
Positive controls sit beside every negative: a real product stays a product, a
real listing stays a listing, a real deep page canonicalised to the home page
is still the defect it always was, and a collapsed deep link is still reported.

Run just this file:

    python3 tests/run_tests.py page_eligibility -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import ORIGIN, bundle, find, html_doc, page, run

from aiva import discover, evidence as ev, localserve, orchestrator
from aiva.config import AuditConfig
from aiva.extract import classify_page, classify_page_verbose


# ---------------------------------------------------------------------------
# page builders - shapes, not sites
# ---------------------------------------------------------------------------

def _grid(n: int, cart_forms: bool = True) -> str:
    tiles = []
    for i in range(n):
        tiles.append(
            f'<article class="tile"><a href="/products/item-{i}">Item {i}</a>'
            f'<span>&#8377;{1000 + i * 100}</span>'
            + (f'<form action="/cart/add" method="post"><button>Add to cart</button></form>'
               if cart_forms else "")
            + "</article>")
    return "".join(tiles)


def _search_header(value: str = "", param: str = "field-keywords",
                   action: str = "/results") -> str:
    return (f'<header><form role="search" action="{action}">'
            f'<input type="text" name="{param}" value="{value}">'
            f'<button>Search</button></form></header>')


def _site_nav() -> str:
    return ("<nav>" + "".join(f'<a href="/section-{i}">Section {i}</a>' for i in range(8))
            + "</nav>")


def search_results_page(url: str, *, prefilled: str, param: str = "field-keywords") -> dict:
    return page(url, html_doc(
        title="Results", canonical=None,
        body=_search_header(prefilled, param) + _site_nav()
             + "<main><h1>Results</h1>" + _grid(12) + "</main>"))


def listing_page(url: str, *, tiles: int = 8, cart_forms: bool = True) -> dict:
    return page(url, html_doc(
        title="Kitchen", canonical=url,
        body=_search_header() + _site_nav() + "<main><h1>Kitchen</h1>"
             + _grid(tiles, cart_forms=cart_forms) + "</main>"))


PRODUCT_LD = ('{"@context":"https://schema.org","@type":"Product","name":"Northvale Kettle",'
              '"sku":"NV-1","brand":{"@type":"Brand","name":"Northvale"},'
              '"offers":{"@type":"Offer","price":"2499","priceCurrency":"INR",'
              '"availability":"https://schema.org/InStock"}}')


def product_page(url: str, *, cart_forms: int = 1, with_ld: bool = True,
                 extra_body: str = "") -> dict:
    forms = "".join('<form action="/cart/add" method="post"><button>Add to cart</button></form>'
                    for _ in range(cart_forms))
    return page(url, html_doc(
        title="Northvale Kettle", canonical=url,
        head=(f'<script type="application/ld+json">{PRODUCT_LD}</script>' if with_ld else ""),
        body=_search_header() + _site_nav()
             + "<main><h1>Northvale Kettle</h1><p>&#8377;2,499 - in stock.</p>"
             + forms + "<table><tr><th>Capacity</th><td>1.7 L</td></tr>"
             "<tr><th>Power</th><td>2200 W</td></tr></table>" + extra_body + "</main>"))


def home_document(canonical: str = None, title: str = "Northvale") -> str:
    return html_doc(
        title=title, canonical=canonical,
        body=_search_header() + _site_nav()
             + "<main><h1>Northvale</h1><p>Kettles, grinders and toasters for the home.</p>"
             + "".join(f'<a href="/products/item-{i}">Item {i} &#8377;{900 + i}</a>'
                       for i in range(6)) + "</main>")


# ---------------------------------------------------------------------------
# 1. a search results page is a search page, whatever it looks like
# ---------------------------------------------------------------------------

class TestSearchResultsAreSearch(unittest.TestCase):
    def test_prefilled_search_box_makes_the_page_a_search(self):
        """The URL has no search word in it and its parameter is nothing the
        auditor knows; the page's own search box holds the query."""
        url = ORIGIN + "/results?k=kettle"
        verdict = classify_page_verbose(url, search_results_page(url, prefilled="kettle"))
        self.assertEqual(verdict["page_type"], "search")
        self.assertIn("pre-filled", verdict["decided_by"])

    def test_own_parameter_name_makes_the_page_a_search(self):
        url = ORIGIN + "/find?term=kettle"
        facts = search_results_page(url, prefilled="", param="term")
        verdict = classify_page_verbose(url, facts)
        self.assertEqual(verdict["page_type"], "search")
        self.assertIn("own search parameter", verdict["decided_by"])

    def test_declared_search_results_page_is_search_not_category(self):
        url = ORIGIN + "/browse?x=1"
        facts = page(url, html_doc(
            title="Browse", body="<h1>Browse</h1>" + _grid(6),
            head='<script type="application/ld+json">{"@context":"https://schema.org",'
                 '"@type":"SearchResultsPage","name":"Browse"}</script>'))
        self.assertEqual(classify_page(url, facts), "search")

    def test_a_search_page_without_the_echo_is_still_never_a_product(self):
        """Twelve quick-add buttons are twelve items, not one purchase."""
        url = ORIGIN + "/results?k=kettle"
        facts = search_results_page(url, prefilled="")   # no echo, no param match
        facts["forms"]["search_param_names"] = []           # and nothing to match on
        verdict = classify_page_verbose(url, facts)
        self.assertNotEqual(verdict["page_type"], "product")
        self.assertTrue(any("purchase controls" in s for s in verdict["plural"]),
                        verdict)

    def test_search_page_enters_no_product_or_listing_population(self):
        search = search_results_page(ORIGIN + "/results?k=kettle", prefilled="kettle")
        data = bundle([search,
                       product_page(ORIGIN + "/products/kettle", with_ld=False),
                       listing_page(ORIGIN + "/collections/kitchen")])
        self.assertNotIn(search, ev.product_pages(data))
        self.assertNotIn(search, ev.category_pages(data))
        for skill in ("machine-readability-audit", "engagement-audit",
                      "crawl-render-audit", "entity-audit", "freshness-corroboration"):
            for item in run(skill, data):
                cited = set(item.affected_urls) | {e.url for e in item.evidence_items}
                self.assertNotIn(search["url"], cited,
                                 f"{item.rule_id} cited the search page")

    def test_the_product_and_the_listing_are_still_reported(self):
        """Positive control for the test above: the same bundle still produces
        the product-only and listing-only findings, cited to the right pages."""
        data = bundle([search_results_page(ORIGIN + "/results?k=kettle", prefilled="kettle"),
                       product_page(ORIGIN + "/products/kettle", with_ld=False),
                       listing_page(ORIGIN + "/collections/kitchen")])
        schema = find(run("machine-readability-audit", data), "MR-PRODUCT-SCHEMA-MISSING")
        self.assertIsNotNone(schema)
        self.assertIn(ORIGIN + "/products/kettle", schema.affected_urls)


# ---------------------------------------------------------------------------
# 2. a grid of purchase controls is plurality, one is an anchor
# ---------------------------------------------------------------------------

class TestPurchaseControlCardinality(unittest.TestCase):
    def test_a_listing_with_quick_add_on_every_tile_is_not_a_product(self):
        url = ORIGIN + "/k/kitchen"               # no product or listing hint
        verdict = classify_page_verbose(url, listing_page(url, tiles=8))
        self.assertNotEqual(verdict["page_type"], "product")
        self.assertTrue(any("purchase controls" in s for s in verdict["plural"]))
        self.assertFalse(any(s.startswith("purchase:") for s in verdict["anchors"]))

    def test_a_product_with_add_and_buy_now_forms_is_still_a_product(self):
        url = ORIGIN + "/products/kettle"
        verdict = classify_page_verbose(url, product_page(url, cart_forms=2))
        self.assertEqual(verdict["page_type"], "product")

    def test_an_opaque_product_with_one_cart_form_is_still_a_product(self):
        """The anchor a single purchase control provides is kept."""
        url = ORIGIN + "/item.php?id=42"
        verdict = classify_page_verbose(url, product_page(url, cart_forms=1, with_ld=False))
        self.assertEqual(verdict["page_type"], "product")
        self.assertTrue(any(s.startswith("purchase:") for s in verdict["anchors"]))


# ---------------------------------------------------------------------------
# 3. account/auth endpoints
# ---------------------------------------------------------------------------

class TestAccountEndpoints(unittest.TestCase):
    def test_a_sign_in_page_is_account(self):
        url = ORIGIN + "/portal"
        facts = page(url, html_doc(
            title="Sign in", canonical=url,
            body='<main><h1>Sign in</h1><form action="/portal" method="post">'
                 '<input type="email" name="email"><input type="password" name="pw">'
                 '<button>Sign in</button></form></main>'))
        self.assertEqual(classify_page(url, facts), "account")
        self.assertNotIn(facts, ev.product_pages(bundle([facts])))
        self.assertNotIn(facts, ev.category_pages(bundle([facts])))

    def test_a_rich_product_page_with_a_login_widget_is_not_account(self):
        url = ORIGIN + "/products/kettle"
        filler = "<p>" + " ".join(["Stainless steel body with a concealed element."] * 40) + "</p>"
        widget = ('<form action="/login" method="post"><input type="password" name="pw">'
                  '<button>Log in for trade price</button></form>')
        verdict = classify_page_verbose(url, product_page(url, extra_body=filler + widget))
        self.assertEqual(verdict["page_type"], "product")

    def test_account_page_is_not_canonical_eligible(self):
        from helpers import specialist
        crawl = specialist("crawl-render-audit")
        url = ORIGIN + "/portal"
        facts = page(url, html_doc(
            title="Sign in", canonical=url,
            body='<main><h1>Sign in</h1><form action="/portal" method="post">'
                 '<input type="password" name="pw"></form></main>'))
        self.assertIn("account endpoint", crawl.canonical_eligibility(facts, {}))


# ---------------------------------------------------------------------------
# 4. navigation/reference addresses: one document, several URLs
# ---------------------------------------------------------------------------

def _pages_dict(*facts):
    return {f["url"]: f for f in facts}


class TestAliasResolution(unittest.TestCase):
    def setUp(self):
        self.home = page(ORIGIN + "/", home_document(canonical=ORIGIN + "/"))
        self.home["page_type"] = "home"

    def _resolve(self, *others):
        pages = _pages_dict(self.home, *others)
        types = {u: p["page_type"] for u, p in pages.items()}
        marked = discover.resolve_aliases(pages, types, ORIGIN + "/")
        return marked, pages, types

    def test_home_served_at_a_reference_address_is_reference(self):
        alias = page(ORIGIN + "/ref-logo", home_document(canonical=ORIGIN + "/"))
        before = alias["page_type"]
        marked, pages, types = self._resolve(alias)
        self.assertEqual(marked, 1)
        self.assertEqual(pages[ORIGIN + "/ref-logo"]["page_type"], "reference")
        self.assertEqual(pages[ORIGIN + "/ref-logo"]["alias_kind"], "canonical")
        self.assertEqual(pages[ORIGIN + "/ref-logo"]["alias_of"], ORIGIN + "/")
        self.assertEqual(types[ORIGIN + "/ref-logo"], "reference")
        self.assertIn("reference address", pages[ORIGIN + "/ref-logo"]["page_type_evidence"]["decided_by"])
        self.assertNotEqual(before, "reference", "the content alone had read as something else")

    def test_identical_copy_without_a_canonical_is_reference(self):
        alias = page(ORIGIN + "/ref-footer", home_document(canonical=None))
        marked, pages, _ = self._resolve(alias)
        self.assertEqual(marked, 1)
        self.assertEqual(pages[ORIGIN + "/ref-footer"]["page_type"], "reference")
        self.assertEqual(pages[ORIGIN + "/ref-footer"]["alias_kind"], "duplicate")

    def test_the_home_page_is_never_an_alias(self):
        self.home["final_url"] = ORIGIN + "/en/"
        locale = page(ORIGIN + "/en/", home_document(canonical=ORIGIN + "/en/"))
        marked, pages, _ = self._resolve(locale)
        self.assertEqual(pages[ORIGIN + "/"]["page_type"], "home")
        self.assertNotIn("alias_of", pages[ORIGIN + "/"])

    def test_a_redirect_endpoint_onto_a_held_page_is_reference(self):
        real = product_page(ORIGIN + "/products/kettle")
        endpoint = product_page(ORIGIN + "/go/kettle")
        endpoint["final_url"] = ORIGIN + "/products/kettle"
        marked, pages, _ = self._resolve(real, endpoint)
        self.assertEqual(pages[ORIGIN + "/go/kettle"]["page_type"], "reference")
        self.assertEqual(pages[ORIGIN + "/go/kettle"]["alias_kind"], "redirect")
        self.assertEqual(pages[ORIGIN + "/products/kettle"]["page_type"], "product")
        data = bundle(list(pages.values()))
        self.assertEqual([p["url"] for p in ev.product_pages(data)], [ORIGIN + "/products/kettle"])

    def test_a_genuine_deep_page_canonicalised_to_home_is_not_an_alias(self):
        """Positive control: a product whose template hardcodes canonical=/ is
        a different document from the home page, and stays a defect."""
        product = page(ORIGIN + "/products/kettle", html_doc(
            title="Northvale Kettle", canonical=ORIGIN + "/",
            body="<main><h1>Northvale Kettle</h1><p>&#8377;2,499 in stock</p>"
                 "<table><tr><th>Capacity</th><td>1.7 L</td></tr>"
                 "<tr><th>Power</th><td>2200 W</td></tr></table></main>"))
        second = page(ORIGIN + "/products/grinder", html_doc(
            title="Northvale Grinder", canonical=ORIGIN + "/products/grinder",
            body="<main><h1>Northvale Grinder</h1><p>&#8377;1,299 in stock</p>"
                 "<table><tr><th>Blades</th><td>4</td></tr>"
                 "<tr><th>Power</th><td>500 W</td></tr></table></main>"))
        marked, pages, _ = self._resolve(product, second)
        self.assertEqual(marked, 0)
        self.assertEqual(pages[ORIGIN + "/products/kettle"]["page_type"], "product")
        data = bundle(list(pages.values()))
        wrong = find(run("crawl-render-audit", data), "CR-CANONICAL-WRONG-TARGET")
        self.assertIsNotNone(wrong, "a real collapse onto the home page must still be reported")
        self.assertIn(ORIGIN + "/products/kettle", wrong.affected_urls)

    def test_page_two_of_a_listing_is_not_an_alias_of_page_one(self):
        def listing(url, first):
            tiles = "".join(f'<a href="/products/item-{i}">Item {i} &#8377;{900 + i}</a>'
                            for i in range(first, first + 8))
            return page(url, html_doc(title="Kitchen", canonical=url,
                                      body=_site_nav() + "<main><h1>Kitchen</h1>" + tiles
                                      + '<a rel="next" href="?page=2">Next</a></main>'))
        one = listing(ORIGIN + "/collections/kitchen", 0)
        two = listing(ORIGIN + "/collections/kitchen?page=2", 8)
        marked, pages, _ = self._resolve(one, two)
        self.assertEqual(marked, 0)
        self.assertNotEqual(pages[ORIGIN + "/collections/kitchen?page=2"]["page_type"], "reference")

    def test_alias_is_kept_out_of_content_populations_and_canonical_analysis(self):
        alias = page(ORIGIN + "/ref-logo", home_document(canonical=ORIGIN + "/"))
        product = product_page(ORIGIN + "/products/kettle")
        second = product_page(ORIGIN + "/products/grinder")
        marked, pages, _ = self._resolve(alias, product, second)
        data = bundle(list(pages.values()))
        self.assertNotIn(pages[ORIGIN + "/ref-logo"], ev.pages(data))
        self.assertIn(pages[ORIGIN + "/ref-logo"], ev.pages(data, include_aliases=True))
        self.assertNotIn(pages[ORIGIN + "/ref-logo"], ev.category_pages(data))
        findings = run("crawl-render-audit", data)
        self.assertIsNone(find(findings, "CR-CANONICAL-WRONG-TARGET"),
                          "the alias's canonical pointing at the root is correct, not a defect")
        for item in findings:
            self.assertNotIn(ORIGIN + "/ref-logo", item.affected_urls, item.rule_id)


# ---------------------------------------------------------------------------
# 5. ambiguity is not promoted
# ---------------------------------------------------------------------------

class TestAmbiguityStaysAmbiguous(unittest.TestCase):
    def test_a_price_and_a_spec_table_with_no_anchor_is_other(self):
        url = ORIGIN + "/notes/choosing-a-kettle"   # no route hint of any kind
        facts = page(url, html_doc(
            title="Choosing a kettle", canonical=url,
            body="<main><h1>Choosing a kettle</h1><p>Expect to pay around &#8377;2,000.</p>"
                 "<table><tr><th>Capacity</th><td>1.5-1.7 L</td></tr>"
                 "<tr><th>Power</th><td>1800-2200 W</td></tr></table></main>"))
        self.assertEqual(classify_page(url, facts), "other")


# ---------------------------------------------------------------------------
# 6. the whole lifecycle, over HTTP: fetch -> classify -> alias -> specialists
# ---------------------------------------------------------------------------

def _write_site(root: Path) -> None:
    (root / "products").mkdir(parents=True)
    (root / "collections").mkdir()
    home = html_doc(
        title="Northvale", canonical="/",
        body=_search_header() + _site_nav()
             + '<main><h1>Northvale</h1><p>Kettles, grinders and toasters for the home.</p>'
               '<a href="/ref-logo.html">Northvale</a>'
               '<a href="/results.html?k=kettle">Search: kettle</a>'
               '<a href="/products/kettle.html">Northvale Kettle &#8377;2,499</a>'
               '<a href="/collections/kitchen.html">Kitchen</a>'
               '<a href="/signin.html">Sign in</a></main>')
    (root / "index.html").write_text(home, encoding="utf-8")
    # The same document at a navigation address, canonical to the root.
    (root / "ref-logo.html").write_text(home, encoding="utf-8")
    (root / "results.html").write_text(html_doc(
        title="Results", body=_search_header("kettle") + _site_nav()
        + "<main><h1>Results</h1>" + _grid(10) + "</main>"), encoding="utf-8")
    (root / "products" / "kettle.html").write_text(html_doc(
        title="Northvale Kettle", canonical="/products/kettle.html",
        body=_search_header() + _site_nav()
        + "<main><h1>Northvale Kettle</h1><p>&#8377;2,499 - in stock.</p>"
          '<form action="/cart/add" method="post"><button>Add to cart</button></form>'
          "<table><tr><th>Capacity</th><td>1.7 L</td></tr>"
          "<tr><th>Power</th><td>2200 W</td></tr></table></main>"), encoding="utf-8")
    (root / "collections" / "kitchen.html").write_text(html_doc(
        title="Kitchen", canonical="/collections/kitchen.html",
        head='<script type="application/ld+json">{"@context":"https://schema.org",'
             '"@type":"CollectionPage","name":"Kitchen"}</script>',
        body=_search_header() + _site_nav() + "<main><h1>Kitchen</h1>"
        + '<a href="/products/kettle.html">Northvale Kettle &#8377;2,499</a>'
        + _grid(6, cart_forms=False) + "</main>"), encoding="utf-8")
    (root / "signin.html").write_text(html_doc(
        title="Sign in", body='<main><h1>Sign in</h1><form action="/signin.html" method="post">'
        '<input type="password" name="pw"><button>Sign in</button></form></main>'),
        encoding="utf-8")
    (root / "robots.txt").write_text("User-agent: *\nDisallow:\n", encoding="utf-8")


class TestLifecycleOverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        _write_site(root)
        server, base = localserve.start(root)
        try:
            # Canonicals in the fixture are relative; the extractor resolves
            # them against the base the local server is serving from.
            config = AuditConfig(site=base, request_delay_s=0.1, check_external=False,
                                 allow_private_hosts=True)
            cls.bundle, cls.report = orchestrator.run_audit(config)
        finally:
            server.shutdown()
            server.server_close()
        cls.types = {p["url"].split(base, 1)[-1]: p["page_type"] for p in cls.bundle["pages"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_page_is_typed_by_what_it_is(self):
        self.assertEqual(self.types.get("/"), "home")
        self.assertEqual(self.types.get("/results.html?k=kettle"), "search")
        self.assertEqual(self.types.get("/ref-logo.html"), "reference")
        self.assertEqual(self.types.get("/signin.html"), "account")
        self.assertEqual(self.types.get("/products/kettle.html"), "product")
        self.assertEqual(self.types.get("/collections/kitchen.html"), "category")

    def test_no_finding_cites_a_non_content_endpoint(self):
        for finding in self.report["findings"]:
            cited = set(finding.get("affected_urls") or []) | {
                item.get("url") for item in finding.get("evidence_items") or []}
            for marker in ("/results.html", "/ref-logo.html", "/signin.html"):
                self.assertFalse(any(marker in (u or "") for u in cited),
                                 f"{finding['rule_id']} cited {marker}")

    def test_the_content_findings_still_fire_on_the_content_pages(self):
        rules = {f["rule_id"]: f for f in self.report["findings"]}
        self.assertIn("MR-PRODUCT-SCHEMA-MISSING", rules)
        self.assertTrue(any("/products/kettle.html" in u
                            for u in rules["MR-PRODUCT-SCHEMA-MISSING"]["affected_urls"]))
        self.assertNotIn("CR-CANONICAL-WRONG-TARGET", rules)

    def test_the_manifest_explains_the_alias_and_the_search(self):
        why = {p["url"].split(self.bundle["site"]["origin"], 1)[-1]: p["why_type"]
               for p in self.report["evidence_manifest"]["pages"]}
        self.assertIn("reference address", why["/ref-logo.html"])
        self.assertIn("search", why["/results.html?k=kettle"].lower())

    def test_specialists_all_completed_and_the_report_validates(self):
        self.assertEqual(self.report["summary"]["specialist_coverage"], "complete")
        self.assertEqual(self.report["diagnostics"]["schema_validation"]["errors"], [])


if __name__ == "__main__":
    unittest.main()
