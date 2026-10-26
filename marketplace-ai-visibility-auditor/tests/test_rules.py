"""Rule-level tests over synthetic evidence bundles.

Each test builds the smallest bundle that should (or should not) trigger one
rule, then runs the real specialist skill through the manifest - the same code
path the entrypoint uses.
"""

from __future__ import annotations

import datetime as dt
import unittest

import helpers
from helpers import bundle, find, html_doc, jsonld, page, rule_ids, run

ORIGIN = helpers.ORIGIN


def days_ago(n: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).strftime("%Y-%m-%d")


PRODUCT_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"Aero Runner",'
    '"sku":"SKU-1","gtin13":"8901234567890","brand":{"@type":"Brand","name":"Acme"},'
    '"category":"Shoes","color":"Blue","material":"Mesh",'
    '"additionalProperty":[{"@type":"PropertyValue","name":"Weight","value":"245"}],'
    '"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.5","reviewCount":"10"},'
    '"offers":{"@type":"Offer","price":"5499","priceCurrency":"INR",'
    '"availability":"https://schema.org/InStock",'
    '"hasMerchantReturnPolicy":{"@type":"MerchantReturnPolicy","merchantReturnDays":30},'
    '"shippingDetails":{"@type":"OfferShippingDetails","shippingRate":'
    '{"@type":"MonetaryAmount","value":"0","currency":"INR"}}}}')

PRODUCT_BODY = (
    '<nav aria-label="breadcrumb"><a href="/">Home</a></nav>'
    "<h1>Aero Runner</h1><p>&#8377;5,499 - in stock. Free shipping. 30-day returns.</p>"
    "<table><tr><th>Weight</th><td>245 g</td></tr><tr><th>Drop</th><td>8 mm</td></tr>"
    "<tr><th>Colour</th><td>Blue</td></tr></table>"
    "<p>Rated 4.5 from 10 reviews.</p><button>Add to cart</button>"
    "<a href='/a'>a</a><a href='/b'>b</a><a href='/c'>c</a><a href='/d'>d</a>"
    "<a href='/e'>e</a><a href='/f'>f</a><a href='/g'>g</a>")


def good_product(url: str = ORIGIN + "/products/aero") -> dict:
    return page(url, html_doc(title="Aero Runner | Acme", canonical=url,
                              head=jsonld(PRODUCT_LD), body=PRODUCT_BODY))


# ---------------------------------------------------------------------------
# crawl-render-audit
# ---------------------------------------------------------------------------

class TestCrawlRules(unittest.TestCase):
    def test_unreachable_robots_is_critical(self):
        found = run("crawl-render-audit",
                    bundle([], robots_raw="", robots_status=503))
        item = find(found, "CR-ROBOTS-UNREACHABLE")
        self.assertIsNotNone(item)
        self.assertEqual(item.severity, "critical")

    def test_missing_robots_is_low(self):
        found = run("crawl-render-audit", bundle([], robots_raw="", robots_status=404))
        self.assertEqual(find(found, "CR-ROBOTS-MISSING").severity, "low")
        self.assertIsNone(find(found, "CR-AI-CRAWLERS-BLOCKED"))

    def test_blanket_ai_block_is_critical_and_names_agents(self):
        robots = "User-agent: *\nDisallow:\n\nUser-agent: GPTBot\nDisallow: /\n"
        item = find(run("crawl-render-audit", bundle([], robots_raw=robots)),
                    "CR-AI-CRAWLERS-BLOCKED")
        self.assertEqual(item.severity, "critical")
        self.assertIn("GPTBot", item.metrics["blocked_agents"])
        self.assertTrue(all(e.url for e in item.evidence_items))

    def test_path_scoped_ai_block(self):
        robots = ("User-agent: *\nDisallow:\n\n"
                  "User-agent: GPTBot\nDisallow: /products\n")
        found = run("crawl-render-audit", bundle([good_product()], robots_raw=robots))
        item = find(found, "CR-AI-CRAWLERS-PATH-BLOCKED")
        self.assertIsNotNone(item)
        self.assertIn("GPTBot", item.metrics["agents"])
        self.assertIsNone(find(found, "CR-AI-CRAWLERS-BLOCKED"))

    def test_no_finding_when_ai_agents_are_welcome(self):
        robots = ("User-agent: *\nDisallow: /cart\n\n"
                  "User-agent: GPTBot\nDisallow: /cart\n")
        found = run("crawl-render-audit", bundle([good_product()], robots_raw=robots))
        self.assertIsNone(find(found, "CR-AI-CRAWLERS-BLOCKED"))
        self.assertIsNone(find(found, "CR-AI-CRAWLERS-PATH-BLOCKED"))

    def test_sitemap_undeclared(self):
        found = run("crawl-render-audit", bundle([good_product()]))
        self.assertIsNotNone(find(found, "CR-SITEMAP-UNDECLARED"))

    def test_no_sitemap_at_all(self):
        found = run("crawl-render-audit", bundle([good_product()], sitemaps=[
            {"url": ORIGIN + "/sitemap.xml", "source": "well-known path probe",
             "status": 404, "kind": None, "error": "HTTP 404"}]))
        self.assertEqual(find(found, "CR-NO-SITEMAP").severity, "high")

    def test_https_upgrade_missing(self):
        probes = {"http": {"url": "http://shop.example/", "status": 200,
                           "final_url": "http://shop.example/", "redirects": [],
                           "upgrades_to_https": False, "error": None}}
        item = find(run("crawl-render-audit", bundle([], host_probes=probes)),
                    "CR-NO-HTTPS-UPGRADE")
        self.assertEqual(item.severity, "high")

    def test_https_upgrade_rule_silent_for_http_targets(self):
        data = bundle([], host_probes={"http": {"url": "http://x/", "status": 200,
                                                "final_url": "http://x/", "redirects": [],
                                                "upgrades_to_https": False, "error": None}},
                      origin="http://shop.example")
        self.assertIsNone(find(run("crawl-render-audit", data), "CR-NO-HTTPS-UPGRADE"))

    def test_host_duplication(self):
        probes = {"alt_host": {"url": "https://www.shop.example/", "status": 200,
                               "final_url": "https://www.shop.example/", "resolves": True,
                               "redirects_to_primary": False, "same_host_as_primary": False,
                               "error": None}}
        self.assertIsNotNone(find(run("crawl-render-audit", bundle([], host_probes=probes)),
                                  "CR-HOST-DUPLICATION"))

    def test_alt_host_redirecting_is_not_a_finding(self):
        probes = {"alt_host": {"url": "https://www.shop.example/", "status": 200,
                               "final_url": ORIGIN + "/", "resolves": True,
                               "redirects_to_primary": True, "same_host_as_primary": False,
                               "error": None}}
        self.assertIsNone(find(run("crawl-render-audit", bundle([], host_probes=probes)),
                               "CR-HOST-DUPLICATION"))

    def test_soft_404(self):
        probe = {"url": ORIGIN + "/nope", "checked": True, "status": 200,
                 "returns_404": False, "final_url": ORIGIN + "/nope"}
        self.assertIsNotNone(find(run("crawl-render-audit", bundle([], not_found=probe)),
                                  "CR-SOFT-404"))

    # -- noindex: observed, not diagnosed ---------------------------------
    #
    # An observed noindex is a directive, not an intention. These assert that
    # severity tracks how much is affected, that utility pages excluded by
    # convention are not reported as defects, and that the finding asks the
    # owner to confirm rather than telling them a staging config leaked.

    NOINDEX_META = '<meta name="robots" content="noindex">'

    def _noindexed(self, path: str, body: str = None) -> dict:
        url = ORIGIN + path
        return page(url, html_doc(canonical=url, head=self.NOINDEX_META,
                                  body=body if body is not None else PRODUCT_BODY))

    def test_noindex_on_one_commercial_page_is_high_not_critical(self):
        """One page in a sample of one is not evidence of a template-wide fault."""
        item = find(run("crawl-render-audit", bundle([self._noindexed("/products/x")])),
                    "CR-NOINDEX-ON-IMPORTANT-PAGES")
        self.assertIsNotNone(item)
        self.assertEqual(item.severity, "high")
        self.assertEqual(item.metrics["discoverable_pages_noindexed"], 1)

    def test_noindex_across_a_whole_template_is_critical(self):
        """Widespread across a sample big enough to mean the template."""
        pages = [self._noindexed(f"/products/{i}") for i in range(4)]
        item = find(run("crawl-render-audit", bundle(pages)),
                    "CR-NOINDEX-ON-IMPORTANT-PAGES")
        self.assertEqual(item.severity, "critical")
        self.assertEqual(item.metrics["scope"], "template")

    def test_noindex_on_utility_pages_is_not_a_finding(self):
        """Carts, accounts, logins and internal search are excluded by convention."""
        utility = [self._noindexed(p, "<h1>Utility</h1>") for p in
                   ("/cart", "/account", "/login", "/checkout", "/search?q=x")]
        self.assertIsNone(find(run("crawl-render-audit", bundle(utility)),
                               "CR-NOINDEX-ON-IMPORTANT-PAGES"))

    def test_utility_noindex_does_not_inflate_a_real_finding(self):
        pages = [self._noindexed("/products/x")] + \
                [self._noindexed(p, "<h1>Utility</h1>") for p in ("/cart", "/account")]
        item = find(run("crawl-render-audit", bundle(pages)),
                    "CR-NOINDEX-ON-IMPORTANT-PAGES")
        self.assertEqual(item.metrics["discoverable_pages_noindexed"], 1)
        self.assertEqual(item.metrics["utility_pages_excluded_from_finding"], 2)
        self.assertIn("conventionally excluded", item.evidence)

    def test_noindex_finding_does_not_diagnose_intent(self):
        item = find(run("crawl-render-audit", bundle([self._noindexed("/products/x")])),
                    "CR-NOINDEX-ON-IMPORTANT-PAGES")
        blob = (item.evidence + " " + item.reasoning + " " +
                item.suggested_action.mechanism).lower()
        for phrase in ("usually left over", "staging config", "by mistake at the cdn"):
            self.assertNotIn(phrase, blob,
                             "the audit observes a directive, not the intent behind it")
        self.assertIn("review", item.suggested_action.summary.lower())

    def test_x_robots_tag_header_is_detected(self):
        url = ORIGIN + "/products/x"
        blocked = page(url, html_doc(canonical=url, body=PRODUCT_BODY),
                       headers={"x-robots-tag": "noindex, nofollow"})
        self.assertIsNotNone(find(run("crawl-render-audit", bundle([blocked])),
                                  "CR-NOINDEX-ON-IMPORTANT-PAGES"))

    def test_home_with_no_internal_links(self):
        home = page(ORIGIN + "/", html_doc(canonical=ORIGIN + "/",
                                           body="<h1>Welcome</h1><div>no links</div>"))
        item = find(run("crawl-render-audit", bundle([home])), "CR-HOME-NO-INTERNAL-LINKS")
        self.assertEqual(item.severity, "critical")

    def test_home_without_commerce_links(self):
        """A catalogue that exists but is unreachable from the home page."""
        home = page(ORIGIN + "/", html_doc(
            canonical=ORIGIN + "/",
            body='<h1>Welcome</h1><a href="/blog/one">Blog</a><a href="/careers">Jobs</a>'))
        # The crawl found the catalogue via the sitemap, so a catalogue
        # demonstrably exists - which is what makes its absence from the home
        # page a discovery problem rather than an inapplicable rule.
        self.assertIsNotNone(
            find(run("crawl-render-audit", bundle([home, good_product()])),
                 "CR-COMMERCE-NOT-LINKED-FROM-HOME"))

    def test_commerce_linkage_rule_is_silent_on_a_non_commerce_site(self):
        """A documentation or brochure site has no catalogue to link."""
        home = page(ORIGIN + "/", html_doc(
            canonical=ORIGIN + "/",
            body='<h1>Docs</h1><a href="/docs/one">Guide</a><a href="/careers">Jobs</a>'))
        docs = page(ORIGIN + "/docs/one", html_doc(
            canonical=ORIGIN + "/docs/one", body="<h1>Guide</h1><p>" + "Text. " * 60 + "</p>"))
        self.assertIsNone(find(run("crawl-render-audit", bundle([home, docs])),
                               "CR-COMMERCE-NOT-LINKED-FROM-HOME"))

    def test_home_with_category_link_is_clean(self):
        home = page(ORIGIN + "/", html_doc(
            canonical=ORIGIN + "/",
            body='<h1>Welcome</h1><a href="/collections/all">Shop</a>'))
        self.assertIsNone(find(run("crawl-render-audit", bundle([home])),
                               "CR-COMMERCE-NOT-LINKED-FROM-HOME"))

    def test_slow_responses(self):
        pages = [page(f"{ORIGIN}/products/p{i}",
                      html_doc(canonical=f"{ORIGIN}/products/p{i}", body=PRODUCT_BODY),
                      elapsed_ms=4000) for i in range(5)]
        self.assertIsNotNone(find(run("crawl-render-audit", bundle(pages)),
                                  "CR-SLOW-RESPONSES"))

    def test_redirect_chain(self):
        url = ORIGIN + "/products/x"
        chained = page(url, html_doc(canonical=url, body=PRODUCT_BODY),
                       redirects=[(301, ORIGIN + "/a"), (301, url)])
        self.assertIsNotNone(find(run("crawl-render-audit", bundle([chained])),
                                  "CR-REDIRECT-CHAINS"))

    def test_headless_render_gap(self):
        render = {"attempted": True, "available": True, "comparisons": [
            {"url": ORIGIN + "/products/x", "ok": True, "raw_word_count": 40,
             "rendered_word_count": 800, "content_gain_ratio": 20.0,
             "jsonld_before_render": 0, "jsonld_after_render": 1}]}
        self.assertIsNotNone(find(run("crawl-render-audit",
                                      bundle([good_product()], render=render)),
                                  "CR-JS-CONTENT-GAP"))

    def test_healthy_site_produces_no_crawl_findings_except_sitemap_declaration(self):
        robots = ("User-agent: *\nDisallow: /cart\n\nSitemap: " + ORIGIN + "/sitemap.xml\n")
        home = page(ORIGIN + "/", html_doc(canonical=ORIGIN + "/",
                                           body='<h1>Shop</h1><a href="/collections/all">All</a>'))
        found = run("crawl-render-audit", bundle([home, good_product()], robots_raw=robots))
        self.assertEqual(rule_ids(found), [])


# ---------------------------------------------------------------------------
# machine-readability-audit
# ---------------------------------------------------------------------------

class TestMachineReadabilityRules(unittest.TestCase):
    def test_no_structured_data_anywhere(self):
        pages = [page(f"{ORIGIN}/x{i}", html_doc(canonical=f"{ORIGIN}/x{i}",
                                                 body="<h1>Page</h1><p>Some words here.</p>"))
                 for i in range(3)]
        item = find(run("machine-readability-audit", bundle(pages)), "MR-NO-STRUCTURED-DATA")
        self.assertEqual(item.severity, "critical")

    def _no_structured_data(self, pages):
        item = find(run("machine-readability-audit", bundle(pages)),
                    "MR-NO-STRUCTURED-DATA")
        self.assertIsNotNone(item)
        return item

    def test_the_structured_data_recommendation_follows_the_site_type(self):
        """Regression: every site was told to add "Product + Offer".

        The finding is site-agnostic - no structured data anywhere is a real
        gap wherever it occurs - but the fix is not. A documentation site has
        no product page to put a Product node on, and a recommendation that
        describes a catalogue the crawl never observed is unactionable.
        """
        docs = [page(f"{ORIGIN}/guide/{name}", html_doc(
            title=name, canonical=f"{ORIGIN}/guide/{name}",
            body=f"<h1>{name}</h1><p>Instructions for {name}.</p>"))
            for name in ("install", "configure", "upgrade")]
        item = self._no_structured_data(docs)
        self.assertEqual(item.metrics["site_type"], "non-commerce")
        blob = " ".join([item.suggested_action.summary] + item.suggested_action.steps)
        self.assertNotIn("Product", blob)
        self.assertNotIn("Offer", blob)
        self.assertIn("Organization", blob)
        self.assertNotIn("Offer", item.suggested_action.example or "")
        self.assertIn("no product page", item.evidence.lower())

    def test_the_structured_data_recommendation_still_covers_a_catalogue(self):
        """The commerce branch is unchanged: observed catalogue, catalogue fix."""
        pages = [
            page(ORIGIN + "/", html_doc(canonical=ORIGIN + "/",
                                        body='<h1>Shop</h1><a href="/products/a">A</a>')),
            page(ORIGIN + "/collections/all", html_doc(
                canonical=ORIGIN + "/collections/all",
                body='<h1>All</h1><a href="/products/a">A</a><a href="/products/b">B</a>')),
            page(ORIGIN + "/products/a", html_doc(canonical=ORIGIN + "/products/a",
                                                  body="<h1>A</h1><p>&#8377;499</p>")),
            page(ORIGIN + "/products/b", html_doc(canonical=ORIGIN + "/products/b",
                                                  body="<h1>B</h1><p>&#8377;799</p>")),
        ]
        item = self._no_structured_data(pages)
        self.assertEqual(item.metrics["site_type"], "commerce")
        blob = " ".join([item.suggested_action.summary] + item.suggested_action.steps)
        self.assertIn("Product", blob)
        self.assertIn("Offer", blob)
        self.assertTrue(item.metrics["commerce_signals"])
        self.assertIn("Offer", item.suggested_action.example or "")

    def test_offer_missing(self):
        url = ORIGIN + "/products/x"
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"X","sku":"1",'
              '"brand":{"@type":"Brand","name":"Acme"},"category":"Shoes","color":"Blue",'
              '"material":"Mesh"}')
        product = page(url, html_doc(canonical=url, head=jsonld(ld), body=PRODUCT_BODY))
        found = run("machine-readability-audit", bundle([product]))
        self.assertIsNotNone(find(found, "MR-OFFER-MISSING"))

    def test_offer_incomplete_lists_missing_fields(self):
        url = ORIGIN + "/products/x"
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"X","sku":"1",'
              '"brand":{"@type":"Brand","name":"Acme"},"category":"Shoes","color":"Blue",'
              '"material":"Mesh","offers":{"@type":"Offer","price":"10"}}')
        product = page(url, html_doc(canonical=url, head=jsonld(ld), body=PRODUCT_BODY))
        item = find(run("machine-readability-audit", bundle([product])), "MR-OFFER-INCOMPLETE")
        self.assertIn("availability", item.metrics["missing_fields"])
        self.assertIn("priceCurrency", item.metrics["missing_fields"])

    def test_aggregate_offer_low_high_price_counts_as_priced(self):
        url = ORIGIN + "/products/x"
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"X","sku":"1",'
              '"brand":{"@type":"Brand","name":"Acme"},"category":"Shoes","color":"Blue",'
              '"material":"Mesh","offers":{"@type":"AggregateOffer","lowPrice":"10",'
              '"highPrice":"20","priceCurrency":"INR","availability":"https://schema.org/InStock"}}')
        product = page(url, html_doc(canonical=url, head=jsonld(ld), body=PRODUCT_BODY))
        found = run("machine-readability-audit", bundle([product]))
        self.assertIsNone(find(found, "MR-OFFER-MISSING"))
        self.assertIsNone(find(found, "MR-OFFER-INCOMPLETE"))

    def test_microdata_only(self):
        body = ('<div itemscope itemtype="https://schema.org/Product">'
                '<span itemprop="name">X</span></div>' + PRODUCT_BODY)
        pages = [page(f"{ORIGIN}/x{i}", html_doc(canonical=f"{ORIGIN}/x{i}", body=body))
                 for i in range(3)]
        self.assertIsNotNone(find(run("machine-readability-audit", bundle(pages)),
                                  "MR-MICRODATA-ONLY"))

    def test_title_missing(self):
        pages = [page(f"{ORIGIN}/x{i}",
                      '<!doctype html><html lang="en"><head></head><body><h1>H</h1>'
                      '<p>words words words</p></body></html>') for i in range(3)]
        self.assertIsNotNone(find(run("machine-readability-audit", bundle(pages)),
                                  "MR-TITLE-MISSING"))

    #: A page that shows images and states no price anywhere.
    _PRICELESS_BODY = ("<h1>{name}</h1><img src='/a.jpg' alt='a'><img src='/b.jpg' alt='b'>"
                       "<p>See the banner for the price.</p>")

    def _priceless_product(self, slug: str, name: str = "Shoe") -> dict:
        url = f"{ORIGIN}/products/{slug}"
        return page(url, html_doc(canonical=url,
                                  body=self._PRICELESS_BODY.format(name=name)))

    def test_facts_not_in_text(self):
        """Fires, and reaches `critical` when the template-wide claim is earned."""
        products = [self._priceless_product(f"x{i}", f"Shoe {i}") for i in range(4)]
        item = find(run("machine-readability-audit", bundle(products)), "MR-FACTS-NOT-IN-TEXT")
        self.assertIsNotNone(item)
        self.assertEqual(item.severity, "critical")

    def test_facts_not_in_text_is_capped_on_a_single_page(self):
        """One page cannot establish a site-wide blocker.

        1-of-1 is 100% by construction. Reporting `critical` off a sample of
        one is how a single quote-on-request page became the top finding of a
        whole report.
        """
        item = find(run("machine-readability-audit", bundle([self._priceless_product("x")])),
                    "MR-FACTS-NOT-IN-TEXT")
        self.assertIsNotNone(item)
        self.assertEqual(item.severity, "medium")

    def test_quote_on_request_catalogue_is_not_a_hidden_price(self):
        """"Contact us for pricing" is a commercial decision, not a defect.

        Industrial, medical, wholesale and made-to-order sellers publish no
        number on purpose. Reporting that as "the price is locked inside an
        image" is a confident wrong answer, and it was reaching `critical`.
        """
        url = ORIGIN + "/products/model-400"
        body = ("<h1>Model 400 Centrifuge</h1><img src='/m.jpg' alt='Model 400'>"
                "<p>Rotor capacity 4x750ml. Max speed 15000 rpm. "
                "Contact us for pricing and lead times.</p>")
        product = page(url, html_doc(canonical=url, body=body))
        found = run("machine-readability-audit", bundle([product]))
        self.assertIsNone(find(found, "MR-FACTS-NOT-IN-TEXT"))

    def test_priced_catalogue_still_reports_the_pages_that_hide_a_price(self):
        """The inconsistent case is the real defect, and must survive the gate."""
        priced = page(ORIGIN + "/products/g",
                      html_doc(canonical=ORIGIN + "/products/g",
                               body="<h1>Gadget</h1><p>$49.00 in stock. Add to cart.</p>"))
        found = run("machine-readability-audit",
                    bundle([priced] + [self._priceless_product(f"x{i}") for i in range(3)]))
        self.assertIsNotNone(find(found, "MR-FACTS-NOT-IN-TEXT"))

    def test_clean_product_page_produces_no_machine_findings(self):
        home = page(ORIGIN + "/", html_doc(
            canonical=ORIGIN + "/",
            head=jsonld('{"@context":"https://schema.org","@graph":['
                        '{"@type":"Organization","@id":"/#org","name":"Acme","url":"/"},'
                        '{"@type":"WebSite","@id":"/#site","url":"/","name":"Acme"}]}'),
            body='<h1>Acme</h1><a href="/collections/all">Shop</a>'))
        import json as _json
        graph = {"@context": "https://schema.org", "@graph": [
            _json.loads(PRODUCT_LD),
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": "/"}]}]}
        graph["@graph"][0].pop("@context", None)
        product = page(ORIGIN + "/products/aero", html_doc(
            title="Aero Runner | Acme", canonical=ORIGIN + "/products/aero",
            head=jsonld(_json.dumps(graph)), body=PRODUCT_BODY))
        found = run("machine-readability-audit", bundle([home, product]))
        self.assertEqual(rule_ids(found), [])


# ---------------------------------------------------------------------------
# freshness-corroboration
# ---------------------------------------------------------------------------

class TestFreshnessRules(unittest.TestCase):
    def test_no_date_signals(self):
        pages = [page(f"{ORIGIN}/x{i}", html_doc(canonical=f"{ORIGIN}/x{i}",
                                                 body="<h1>H</h1><p>text</p>"))
                 for i in range(4)]
        self.assertIsNotNone(find(run("freshness-corroboration", bundle(pages)),
                                  "FC-NO-DATE-SIGNALS"))

    def test_last_modified_header_counts_as_a_date_signal(self):
        pages = [page(f"{ORIGIN}/x{i}", html_doc(canonical=f"{ORIGIN}/x{i}",
                                                 body="<h1>H</h1><p>text</p>"),
                      headers={"last-modified": "Tue, 05 Mar 2026 10:00:00 GMT"})
                 for i in range(4)]
        self.assertIsNone(find(run("freshness-corroboration", bundle(pages)),
                               "FC-NO-DATE-SIGNALS"))

    def test_sitemap_lastmod_uniform(self):
        sitemap = [{"url": ORIGIN + "/sitemap.xml", "source": "robots.txt Sitemap directive",
                    "status": 200, "kind": "urlset", "error": None, "url_count": 12,
                    "entries_captured": 12, "missing_lastmod": 0,
                    "lastmods": ["2026-01-01"] * 12, "entries": [], "sample_urls": []}]
        self.assertIsNotNone(find(run("freshness-corroboration",
                                      bundle([], sitemaps=sitemap)),
                                  "FC-SITEMAP-LASTMOD-UNIFORM"))

    def test_sitemap_lastmod_future(self):
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=40)).strftime("%Y-%m-%d")
        lastmods = [days_ago(i + 1) for i in range(11)] + [future]
        sitemap = [{"url": ORIGIN + "/sitemap.xml", "source": "robots.txt Sitemap directive",
                    "status": 200, "kind": "urlset", "error": None, "url_count": 12,
                    "entries_captured": 12, "missing_lastmod": 0,
                    "lastmods": lastmods, "entries": [], "sample_urls": []}]
        self.assertIsNotNone(find(run("freshness-corroboration",
                                      bundle([], sitemaps=sitemap)),
                                  "FC-SITEMAP-LASTMOD-FUTURE"))

    def test_stale_content(self):
        url = ORIGIN + "/pages/returns"
        stale = page(url, html_doc(canonical=url, head=jsonld(
            '{"@context":"https://schema.org","@type":"WebPage","name":"Returns",'
            '"dateModified":"' + days_ago(800) + '"}'), body="<h1>Returns</h1><p>text</p>"))
        item = find(run("freshness-corroboration", bundle([stale])), "FC-STALE-CONTENT")
        self.assertIsNotNone(item)
        self.assertGreater(item.metrics["oldest_days"], 700)

    def test_price_conflict(self):
        url = ORIGIN + "/products/x"
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"X",'
              '"offers":{"@type":"Offer","price":"9999","priceCurrency":"INR",'
              '"availability":"https://schema.org/InStock"}}')
        product = page(url, html_doc(canonical=url, head=jsonld(ld), body=PRODUCT_BODY))
        self.assertIsNotNone(find(run("freshness-corroboration", bundle([product])),
                                  "FC-PRICE-CONFLICT"))

    def test_matching_price_is_not_a_conflict(self):
        self.assertIsNone(find(run("freshness-corroboration", bundle([good_product()])),
                               "FC-PRICE-CONFLICT"))

    def test_availability_conflict(self):
        url = ORIGIN + "/products/x"
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"X",'
              '"offers":{"@type":"Offer","price":"5499","priceCurrency":"INR",'
              '"availability":"https://schema.org/InStock"}}')
        body = "<h1>X</h1><p>&#8377;5,499</p><p>Sold out</p>"
        product = page(url, html_doc(canonical=url, head=jsonld(ld), body=body))
        self.assertIsNotNone(find(run("freshness-corroboration", bundle([product])),
                                  "FC-AVAILABILITY-CONFLICT"))

    def test_reviews_stale(self):
        url = ORIGIN + "/products/x"
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"X",'
              '"review":[{"@type":"Review","author":{"@type":"Person","name":"A"},'
              '"datePublished":"' + days_ago(900) + '","reviewBody":"old"}],'
              '"offers":{"@type":"Offer","price":"5499","priceCurrency":"INR",'
              '"availability":"https://schema.org/InStock"}}')
        product = page(url, html_doc(canonical=url, head=jsonld(ld), body=PRODUCT_BODY))
        self.assertIsNotNone(find(run("freshness-corroboration", bundle([product])),
                                  "FC-REVIEWS-STALE"))

    def test_broken_corroboration_anchor(self):
        anchors = [{"url": "https://www.wikidata.org/wiki/Q1", "sources": ["schema.org sameAs"],
                    "declared_on": [ORIGIN + "/"], "is_knowledge_host": True,
                    "checked": True, "status": 404, "resolves": False, "error": None}]
        self.assertIsNotNone(find(run("freshness-corroboration",
                                      bundle([], declared_anchors=anchors)),
                                  "FC-BROKEN-CORROBORATION-ANCHOR"))

    def test_no_corroboration_anchors(self):
        home = page(ORIGIN + "/", html_doc(canonical=ORIGIN + "/", body="<h1>Acme</h1>"))
        item = find(run("freshness-corroboration",
                        bundle([home], declared_anchors=[], declared_total=0)),
                    "FC-NO-CORROBORATION-ANCHORS")
        self.assertEqual(item.severity, "high")

    def test_no_corroboration_anchors_is_gated_on_the_crawl_yielding_evidence(self):
        """Regression: "no sameAs on any crawled page" over zero crawled pages.

        The evidence string says the absence was read off the pages; with no
        readable page it is vacuously true and describes the crawl, not the
        site. The gate the other absence rules use applies here too.
        """
        empty = find(run("freshness-corroboration",
                         bundle([], declared_anchors=[], declared_total=0)),
                     "FC-NO-CORROBORATION-ANCHORS")
        self.assertIsNone(empty)

        errored = find(run("freshness-corroboration",
                           bundle([helpers.error_page(ORIGIN + "/", status=403)],
                                  declared_anchors=[], declared_total=0)),
                       "FC-NO-CORROBORATION-ANCHORS")
        self.assertIsNone(errored)

    def test_broken_anchors_are_reported_without_a_readable_page(self):
        """The gate covers absence, not observation.

        A declared anchor that returned 404 was observed directly; it does not
        become unknowable because no page body parsed.
        """
        anchors = [{"url": "https://www.wikidata.org/wiki/Q1", "sources": ["schema.org sameAs"],
                    "declared_on": [ORIGIN + "/"], "is_knowledge_host": True,
                    "checked": True, "status": 404, "resolves": False, "error": None}]
        self.assertIsNotNone(find(run("freshness-corroboration",
                                      bundle([], declared_anchors=anchors)),
                                  "FC-BROKEN-CORROBORATION-ANCHOR"))


# ---------------------------------------------------------------------------
# entity-audit
# ---------------------------------------------------------------------------

class TestEntityRules(unittest.TestCase):
    ORG_LD = ('{"@context":"https://schema.org","@type":"Organization","@id":"/#org",'
              '"name":"Acme","legalName":"Acme Pvt Ltd","url":"/",'
              '"description":"Shoes.","logo":"/logo.png","foundingDate":"2016",'
              '"address":{"@type":"PostalAddress","addressLocality":"Pune",'
              '"addressCountry":"IN"},"sameAs":["https://www.linkedin.com/company/acme"]}')

    def home(self, extra_ld: str = "") -> dict:
        return page(ORIGIN + "/", html_doc(
            title="Shoes | Acme", canonical=ORIGIN + "/",
            head='<meta property="og:site_name" content="Acme">' + jsonld(extra_ld or self.ORG_LD),
            body='<h1>Acme</h1><a href="/collections/all">Shop</a>'
                 '<footer><p>&copy; 2026 Acme</p></footer>'))

    def test_brand_reference_by_id_is_not_a_name_conflict(self):
        """Regression: {"@id": ...} must resolve, not be read as a brand name."""
        product_ld = ('{"@context":"https://schema.org","@type":"Product","name":"Aero",'
                      '"sku":"1","category":"Shoes","brand":{"@id":"/#org"},'
                      '"offers":{"@type":"Offer","price":"5499","priceCurrency":"INR",'
                      '"availability":"https://schema.org/InStock"}}')
        product = page(ORIGIN + "/products/aero", html_doc(
            title="Aero | Acme", canonical=ORIGIN + "/products/aero",
            head=jsonld(product_ld), body=PRODUCT_BODY))
        found = run("entity-audit", bundle([self.home(), product]))
        self.assertIsNone(find(found, "EN-NAME-INCONSISTENT"))
        self.assertIsNone(find(found, "EN-PRODUCT-BRAND-DRIFT"))
        self.assertIsNone(find(found, "EN-PRODUCT-BRAND-MISSING"))

    def test_name_inconsistency_is_detected(self):
        home = page(ORIGIN + "/", html_doc(
            title="Shoes | Zephyr Sports", canonical=ORIGIN + "/",
            head='<meta property="og:site_name" content="Zephyr Sports">' +
                 jsonld(self.ORG_LD),
            body='<h1>Acme</h1><a href="/collections/all">Shop</a>'))
        item = find(run("entity-audit", bundle([home])), "EN-NAME-INCONSISTENT")
        self.assertIsNotNone(item)
        self.assertGreaterEqual(item.metrics["distinct_names"], 2)

    # -- a business is allowed more than one name -------------------------
    #
    # Regression suite for a false positive on a real storefront: the trading
    # name and the legal entity in the footer copyright were pooled and
    # reported as the brand being "called different things". A registered
    # company name differing from the consumer brand is normal practice, and
    # is in fact what this rule's own advice tells sites to do.

    def _named_home(self, org_ld: str, footer: str, title: str = "Shop | Vellum",
                    og: str = "Vellum") -> dict:
        return page(ORIGIN + "/", html_doc(
            title=title, canonical=ORIGIN + "/",
            head=f'<meta property="og:site_name" content="{og}">' + jsonld(org_ld),
            body=f'<h1>Vellum</h1><a href="/collections/all">Shop</a>'
                 f'<footer><p>{footer}</p></footer>'))

    ORG_VELLUM = ('{"@context":"https://schema.org","@type":"Organization",'
                  '"name":"Vellum","url":"https://shop.example/"}')

    def test_legal_entity_name_is_not_a_brand_conflict(self):
        """`legalName` differing from `name` is correct practice, not a defect."""
        org = ('{"@context":"https://schema.org","@type":"Organization",'
               '"name":"Vellum","legalName":"VLM Holdings LLC",'
               '"url":"https://shop.example/"}')
        found = run("entity-audit", bundle([self._named_home(org, "&copy; 2026 Vellum")]))
        self.assertIsNone(find(found, "EN-NAME-INCONSISTENT"))

    def test_copyright_footer_holder_is_not_a_brand_conflict(self):
        """A rights holder in the footer is a legal entity, not a second brand."""
        found = run("entity-audit", bundle([self._named_home(
            self.ORG_VELLUM, "VLM DNAM LLC &copy; 2026 . All Rights Reserved &reg;")]))
        self.assertIsNone(find(found, "EN-NAME-INCONSISTENT"))

    def test_rights_boilerplate_is_never_read_as_a_name(self):
        from aiva import util
        import importlib.util as iu
        spec = iu.spec_from_file_location(
            "en_mod", helpers.ROOT / "skills/entity-audit/scripts/analyze.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for line, expected in (
                ("VLM DNAM LLC © 2026 . All Rights Reserved ®", "VLM DNAM LLC"),
                ("© 2026 Vellum, Inc. All Rights Reserved", "Vellum Inc"),
                ("Copyright 2026 Vellum", "Vellum"),
                ("© 2026 Tienda Vento S.L. Todos los derechos reservados",
                 "Tienda Vento S L")):
            holders = mod._copyright_holders(line)
            self.assertEqual(holders, [expected], line)
            for holder in holders:
                self.assertNotIn("rights", util.normalize_name(holder))

    def test_capitalisation_only_differences_are_not_a_conflict(self):
        """"Vellum", "VELLUM" and "VeLLuM" are one name, not three."""
        org = ('{"@context":"https://schema.org","@type":"Organization",'
               '"name":"VELLUM","url":"https://shop.example/"}')
        found = run("entity-audit", bundle([self._named_home(
            org, "&copy; 2026 VeLLuM", title="Shop | Vellum", og="vellum")]))
        self.assertIsNone(find(found, "EN-NAME-INCONSISTENT"))

    def test_genuinely_conflicting_trading_names_are_still_reported(self):
        """The detection must survive the fix: two real trading names still fire."""
        product_ld = ('{"@context":"https://schema.org","@type":"Product","name":"Ledger",'
                      '"sku":"1","category":"Paper","brand":{"@type":"Brand","name":"Otherbirds"},'
                      '"offers":{"@type":"Offer","price":"12","priceCurrency":"GBP",'
                      '"availability":"https://schema.org/InStock"}}')
        product = page(ORIGIN + "/products/ledger", html_doc(
            title="Ledger | Vellum", canonical=ORIGIN + "/products/ledger",
            head=jsonld(product_ld), body=PRODUCT_BODY))
        found = run("entity-audit", bundle(
            [self._named_home(self.ORG_VELLUM, "&copy; 2026 Vellum"), product]))
        # A product's brand that differs from the organisation is a *product
        # brand* - a related entity, not the site calling itself two things -
        # so it is reported as brand drift, at low severity, with the
        # relationship named, and never as a trading-name conflict.
        self.assertIsNone(find(found, "EN-NAME-INCONSISTENT"))
        drift = find(found, "EN-PRODUCT-BRAND-DRIFT")
        self.assertIsNotNone(drift, "Organization.name vs Product.brand.name is brand drift")
        self.assertEqual(drift.severity, "low")
        self.assertIn("manufacturer or seller", drift.evidence)

    def test_a_declared_manufacturer_explains_a_different_product_brand(self):
        """A retailer that names the maker has said whose brand it is."""
        product_ld = ('{"@context":"https://schema.org","@type":"Product","name":"Ledger",'
                      '"sku":"1","category":"Paper","brand":{"@type":"Brand","name":"Otherbirds"},'
                      '"manufacturer":{"@type":"Organization","name":"Otherbirds GmbH"},'
                      '"offers":{"@type":"Offer","price":"12","priceCurrency":"GBP",'
                      '"availability":"https://schema.org/InStock"}}')
        product = page(ORIGIN + "/products/ledger", html_doc(
            title="Ledger | Vellum", canonical=ORIGIN + "/products/ledger",
            head=jsonld(product_ld), body=PRODUCT_BODY))
        found = run("entity-audit", bundle(
            [self._named_home(self.ORG_VELLUM, "&copy; 2026 Vellum"), product]))
        self.assertIsNone(find(found, "EN-NAME-INCONSISTENT"))
        self.assertIsNone(find(found, "EN-PRODUCT-BRAND-DRIFT"))

    def test_legal_names_are_reported_as_context_not_as_conflicts(self):
        """When the rule does fire, legal names appear as an aside, not a count."""
        org = ('{"@context":"https://schema.org","@type":"Organization",'
               '"name":"Vellum","legalName":"VLM Holdings LLC",'
               '"url":"https://shop.example/"}')
        found = run("entity-audit", bundle([self._named_home(
            org, "&copy; 2026 Vellum", title="Shop | Quire Papers", og="Quire Papers")]))
        item = find(found, "EN-NAME-INCONSISTENT")
        self.assertIsNotNone(item)
        self.assertIn("not counted as conflicting", item.evidence)
        self.assertIn("VLM Holdings LLC", item.evidence)

    def test_social_profile_handles_are_not_brand_conflicts(self):
        """A platform handle follows the platform's naming rules, not the brand's."""
        home = page(ORIGIN + "/", html_doc(
            title="Shop | Vellum", canonical=ORIGIN + "/",
            head='<meta property="og:site_name" content="Vellum">' + jsonld(self.ORG_VELLUM),
            body='<h1>Vellum</h1><a href="/collections/all">Shop</a>'
                 '<a href="https://www.linkedin.com/company/vellum-supplies-uk">LinkedIn</a>'
                 '<a href="https://instagram.com/vellumshop">Instagram</a>'
                 '<footer><p>&copy; 2026 Vellum</p></footer>'))
        self.assertIsNone(find(run("entity-audit", bundle([home])),
                               "EN-NAME-INCONSISTENT"))

    def test_all_four_name_roles_are_classified(self):
        import importlib.util as iu
        spec = iu.spec_from_file_location(
            "en_roles", helpers.ROOT / "skills/entity-audit/scripts/analyze.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        org = ('{"@context":"https://schema.org","@type":"Organization",'
               '"name":"Vellum","legalName":"VLM Holdings LLC",'
               '"url":"https://shop.example/"}')
        home = page(ORIGIN + "/", html_doc(
            title="Shop | Vellum", canonical=ORIGIN + "/",
            head='<meta property="og:site_name" content="Vellum">' + jsonld(org),
            body='<h1>Vellum</h1>'
                 '<a href="https://www.linkedin.com/company/vellum-supplies-uk">LinkedIn</a>'
                 '<footer><p>Vellum Trading Ltd &copy; 2026. All Rights Reserved</p></footer>'))
        roles = {entry["role"] for entry in
                 mod.brand_name_candidates(bundle([home])).values()}
        self.assertIn("brand", roles)
        self.assertIn("legal", roles)
        self.assertIn("social", roles)
        # Only trading names are ever compared against each other.
        self.assertIsNone(find(run("entity-audit", bundle([home])),
                               "EN-NAME-INCONSISTENT"))

    # -- the review pass: a role must never silence a real conflict -------

    def test_a_trading_name_ending_in_a_corporate_word_still_conflicts(self):
        """"Bliss Spa" and "The Honest Company" are trading names, not registers.

        Reclassifying any name that ends in a register word as a legal entity
        excluded it from conflict detection, silencing a genuine high-severity
        finding to avoid a false one. Role comes from the declaration site.
        """
        for org_name, site_name in (("Blissful Skincare", "Bliss Spa"),
                                    ("Honest Beauty", "The Honest Company"),
                                    ("Northvale Kitchenware", "Northvale Group")):
            with self.subTest(org=org_name):
                org = ('{"@context":"https://schema.org","@type":"Organization",'
                       '"name":"%s","url":"https://shop.example/"}' % org_name)
                home = page(ORIGIN + "/", html_doc(
                    title=f"Shop | {site_name}", canonical=ORIGIN + "/",
                    head=f'<meta property="og:site_name" content="{site_name}">'
                         + jsonld(org),
                    body=f'<h1>{org_name}</h1><a href="/collections/all">Shop</a>'))
                self.assertIsNotNone(
                    find(run("entity-audit", bundle([home])), "EN-NAME-INCONSISTENT"),
                    f"{org_name!r} vs {site_name!r} is a real conflict")

    def test_handles_are_read_as_identities_not_url_tails(self):
        import importlib.util as iu
        spec = iu.spec_from_file_location(
            "en_h", helpers.ROOT / "skills/entity-audit/scripts/analyze.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cases = {
            "/company/acme-supplies/about/": "acme-supplies",
            "/company/acme/careers": "acme",
            "/user/AcmeTV/videos": "AcmeTV",
            "/acmesupplies/status/1234567890": "acmesupplies",
            "/coffeeclub": "coffeeclub",              # must not lose the "c"
            "/organization/cocoacraft": "cocoacraft",  # nor here
            "/pages/Acme-Supplies/123456789": "Acme-Supplies",
            "/profile.php": None,
        }
        for path, expected in cases.items():
            self.assertEqual(mod._handle_from_path(path), expected, path)

    def test_copyright_holder_does_not_absorb_the_rest_of_the_footer(self):
        import importlib.util as iu
        spec = iu.spec_from_file_location(
            "en_c", helpers.ROOT / "skills/entity-audit/scripts/analyze.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cases = {
            "Privacy Terms © 2026 Northvale Ltd": ["Northvale Ltd"],
            "Sign up for our newsletter © 2026 Northvale": ["Northvale"],
            "All prices include VAT. Copyright 2026 Northvale.": ["Northvale"],
            "VLM DNAM LLC © 2026 . All Rights Reserved ®": ["VLM DNAM LLC"],
            "Copyright and licensing": [],
        }
        for line, expected in cases.items():
            self.assertEqual(mod._copyright_holders(line), expected, line)

    def test_org_identity_finding_asserts_no_proven_causation(self):
        """An absent Organization node is not proof that a brand was misread."""
        home = page(ORIGIN + "/", html_doc(canonical=ORIGIN + "/", body="<h1>Shop</h1>"))
        item = find(run("machine-readability-audit", bundle([home, home])),
                    "MR-SITE-SCHEMA-MISSING")
        self.assertIsNotNone(item)
        blob = (item.evidence + " " + item.reasoning + " " +
                item.suggested_action.mechanism).lower()
        for phrase in ("root cause", "anchor every other fact",
                       "brand not recognised", "confused with a similarly-named"):
            self.assertNotIn(phrase, blob,
                             "an observed absence is not a demonstrated failure")
        self.assertIn("does not test", item.reasoning.lower())

    def test_brand_drift(self):
        product_ld = ('{"@context":"https://schema.org","@type":"Product","name":"Aero",'
                      '"sku":"1","category":"Shoes","brand":{"@type":"Brand","name":"Zephyr"},'
                      '"offers":{"@type":"Offer","price":"5499","priceCurrency":"INR",'
                      '"availability":"https://schema.org/InStock"}}')
        product = page(ORIGIN + "/products/aero", html_doc(
            title="Aero | Acme", canonical=ORIGIN + "/products/aero",
            head=jsonld(product_ld), body=PRODUCT_BODY))
        self.assertIsNotNone(find(run("entity-audit", bundle([self.home(), product])),
                                  "EN-PRODUCT-BRAND-DRIFT"))

    def test_org_incomplete(self):
        thin = '{"@context":"https://schema.org","@type":"Organization","name":"Acme","url":"/"}'
        item = find(run("entity-audit", bundle([self.home(thin)])), "EN-ORG-INCOMPLETE")
        self.assertIsNotNone(item)
        # A description is recommended of any organisation; a logo and a
        # founding date are optional everywhere and are named as such rather
        # than counted, and a site of unknown shape is not asked for an address.
        self.assertIn("description", item.metrics["missing_recommended"])
        self.assertIn("logo", item.metrics["missing_optional"])
        self.assertNotIn("address", item.metrics["missing_required"])
        self.assertEqual(item.severity, "low")

    def test_org_address_is_required_only_where_the_site_has_a_place(self):
        thin = '{"@context":"https://schema.org","@type":"Organization","name":"Acme","url":"/"}'
        store = page(ORIGIN + "/stores", html_doc(title="Our stores", body=(
            "<main><h1>Our stores</h1><p>Bristol - 14 Park Row. Tel 0117 496 0123. "
            "Mon-Sat 9:00-17:30.</p><p>Leeds - 3 Briggate. Tel 0113 496 0456.</p></main>")))
        docs_home = self.home(thin)
        item = find(run("entity-audit", bundle([docs_home])), "EN-ORG-INCOMPLETE")
        self.assertNotIn("address", item.metrics["missing_required"])
        from aiva import semantics
        shop = bundle([self.home(thin), store])
        context = semantics.site_context(shop)
        self.assertEqual(semantics.organization_field_expectation(
            "address", dict(context, physical_presence=True)), "required_when_applicable")

    def test_duplicate_product_names(self):
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"Aero","sku":"1",'
              '"category":"Shoes","brand":{"@id":"/#org"},'
              '"offers":{"@type":"Offer","price":"5499","priceCurrency":"INR",'
              '"availability":"https://schema.org/InStock"}}')
        pages = [self.home()] + [
            page(f"{ORIGIN}/products/aero-{i}", html_doc(
                title=f"Aero {i} | Acme", canonical=f"{ORIGIN}/products/aero-{i}",
                head=jsonld(ld), body=PRODUCT_BODY)) for i in range(3)]
        self.assertIsNotNone(find(run("entity-audit", bundle(pages)),
                                  "EN-DUPLICATE-PRODUCT-NAMES"))

    def test_variants_unmodelled(self):
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"Aero","sku":"1",'
              '"category":"Shoes","brand":{"@id":"/#org"},'
              '"offers":{"@type":"Offer","price":"5499","priceCurrency":"INR",'
              '"availability":"https://schema.org/InStock"}}')
        body = PRODUCT_BODY + '<select name="size"><option>UK 8</option></select>'
        product = page(ORIGIN + "/products/aero", html_doc(
            title="Aero | Acme", canonical=ORIGIN + "/products/aero",
            head=jsonld(ld), body=body))
        self.assertIsNotNone(find(run("entity-audit", bundle([self.home(), product])),
                                  "EN-VARIANTS-UNMODELLED"))

    def test_sameas_undeclared_when_profiles_are_only_footer_links(self):
        thin = ('{"@context":"https://schema.org","@type":"Organization","@id":"/#org",'
                '"name":"Acme","url":"/","description":"Shoes.","logo":"/l.png",'
                '"foundingDate":"2016","address":{"@type":"PostalAddress",'
                '"addressCountry":"IN"}}')
        anchors = [{"url": "https://www.linkedin.com/company/acme",
                    "sources": ["outbound profile/knowledge link"],
                    "declared_on": [ORIGIN + "/"], "is_knowledge_host": True, "checked": False}]
        found = run("entity-audit", bundle([self.home(thin)], declared_anchors=anchors))
        self.assertIsNotNone(find(found, "EN-SAMEAS-UNDECLARED"))


# ---------------------------------------------------------------------------
# engagement-audit
# ---------------------------------------------------------------------------

class TestEngagementRules(unittest.TestCase):
    def test_good_product_page_produces_no_engagement_findings(self):
        home = page(ORIGIN + "/", html_doc(
            canonical=ORIGIN + "/",
            body='<h1>Acme</h1><a href="/collections/all">Shop</a>'
                 '<form action="/search"><input type="search" name="q"></form>'
                 '<a href="/pages/faq">FAQ</a>'))
        faq = page(ORIGIN + "/pages/faq", html_doc(
            canonical=ORIGIN + "/pages/faq",
            body="<h1>FAQ</h1><h2>How do I return an item?</h2><p>Within 30 days.</p>"))
        products = [good_product(f"{ORIGIN}/products/p{i}") for i in range(2)]
        found = run("engagement-audit", bundle([home, faq] + products))
        self.assertEqual(rule_ids(found), [])

    def test_missing_shipping_and_returns(self):
        """No policy prose and no policy markup - the fact is stated nowhere."""
        import json as _json
        bare = _json.loads(PRODUCT_LD)
        bare["offers"].pop("hasMerchantReturnPolicy", None)
        bare["offers"].pop("shippingDetails", None)
        bare_ld = _json.dumps(bare)
        url = ORIGIN + "/products/x"
        body = ('<nav aria-label="breadcrumb"><a href="/">Home</a></nav><h1>X</h1>'
                "<p>&#8377;5,499 in stock</p><table><tr><th>W</th><td>1</td></tr>"
                "<tr><th>D</th><td>2</td></tr><tr><th>C</th><td>3</td></tr></table>"
                "<p>4.5 from 10 reviews</p><button>Add to cart</button>"
                "<a href='/a'>a</a><a href='/b'>b</a><a href='/c'>c</a>"
                "<a href='/d'>d</a><a href='/e'>e</a><a href='/f'>f</a><a href='/g'>g</a>")
        product = page(url, html_doc(canonical=url, head=jsonld(bare_ld), body=body))
        found = run("engagement-audit", bundle([product]))
        self.assertIsNotNone(find(found, "EG-SHIPPING-INVISIBLE"))
        self.assertIsNotNone(find(found, "EG-RETURNS-INVISIBLE"))

    def test_policy_markup_counts_as_stating_the_policy(self):
        """OfferShippingDetails states delivery in any language; believe it."""
        url = ORIGIN + "/products/y"
        body = ('<nav aria-label="breadcrumb"><a href="/">Home</a></nav><h1>Y</h1>'
                "<p>&#8377;5,499 in stock</p><table><tr><th>W</th><td>1</td></tr>"
                "<tr><th>D</th><td>2</td></tr><tr><th>C</th><td>3</td></tr></table>"
                "<p>4.5 from 10 reviews</p><button>Add to cart</button>"
                "<a href='/a'>a</a><a href='/b'>b</a><a href='/c'>c</a>"
                "<a href='/d'>d</a><a href='/e'>e</a><a href='/f'>f</a><a href='/g'>g</a>")
        product = page(url, html_doc(canonical=url, head=jsonld(PRODUCT_LD), body=body))
        found = run("engagement-audit", bundle([product]))
        self.assertIsNone(find(found, "EG-SHIPPING-INVISIBLE"))
        self.assertIsNone(find(found, "EG-RETURNS-INVISIBLE"))

    # -- filtering and sorting are two affordances, not one -----------------
    #
    # The four cases below are the regression suite for a real false positive:
    # a category page that offered nine sort options was reported as offering
    # "no filtering or sorting". Each case asserts both what fires and what
    # must not, because the bug was an over-fire, and a test that only checks
    # the positive direction would not have caught it.

    FILTER_HTML = ('<form action="/collections/all">'
                   '<select name="filter.p.price"><option>Any</option>'
                   '<option>Under 300</option></select></form>')
    SORT_HTML = ('<form action="/collections/all">'
                 '<select name="sort_by"><option value="manual">Featured</option>'
                 '<option value="price-ascending">Price, low to high</option>'
                 '<option value="created-descending">Date, new to old</option>'
                 '</select></form>')

    #: Enough entries that sorting and filtering are affordances the listing
    #: can be expected to offer; a page of two items is scanned, not sorted.
    GRID = "".join(f'<a href="/products/{c}">{c.upper()} $1{i}</a>'
                   for i, c in enumerate("abcdefghij"))

    def _category(self, extra: str = "", grid: str = None) -> dict:
        url = ORIGIN + "/collections/all"
        return page(url, html_doc(canonical=url,
                                  body='<h1>All</h1>' + extra +
                                       (self.GRID if grid is None else grid)))

    def test_a_listing_of_a_few_items_is_not_asked_for_controls(self):
        """Controls are an expectation of a *set* large enough to need them.

        A category page listing two products - most small shops - is not
        told it lacks filters; it lacks nothing a visitor would use. The
        page is set aside with the entry count as the reason.
        """
        small = self._category(grid='<a href="/products/a">A</a><a href="/products/b">B</a>')
        found = run("engagement-audit", bundle([small]))
        self.assertIsNone(find(found, "EG-FILTER-CONTROLS-ABSENT"))
        self.assertIsNone(find(found, "EG-SORT-CONTROLS-ABSENT"))
        from aiva.analysis import listing_controls_expected, listing_entry_count
        self.assertEqual(listing_entry_count(small), 2)
        expected, why = listing_controls_expected(small)
        self.assertFalse(expected)
        self.assertIn("only 2 entries", why)

    def test_a_paginated_listing_is_a_set_whatever_one_page_shows(self):
        paginated = self._category(
            grid='<a href="/products/a">A</a><a href="/products/b">B</a>'
                 '<a rel="next" href="/collections/all?page=2">Next</a>')
        from aiva.analysis import listing_controls_expected
        self.assertTrue(listing_controls_expected(paginated)[0])
        self.assertIsNotNone(find(run("engagement-audit", bundle([paginated])),
                                  "EG-FILTER-CONTROLS-ABSENT"))

    def test_case_a_neither_filter_nor_sort(self):
        found = run("engagement-audit", bundle([self._category()]))
        self.assertIsNotNone(find(found, "EG-FILTER-CONTROLS-ABSENT"))
        self.assertIsNotNone(find(found, "EG-SORT-CONTROLS-ABSENT"))

    def test_case_b_filter_only(self):
        found = run("engagement-audit", bundle([self._category(self.FILTER_HTML)]))
        self.assertIsNone(find(found, "EG-FILTER-CONTROLS-ABSENT"))
        self.assertIsNotNone(find(found, "EG-SORT-CONTROLS-ABSENT"))

    def test_case_c_sort_only(self):
        """The CocoaCraft shape: sorting present, filtering absent."""
        category = self._category(self.SORT_HTML)
        self.assertTrue(category["forms"]["has_sort_controls"])
        self.assertFalse(category["forms"]["has_filter_controls"])
        found = run("engagement-audit", bundle([category]))
        self.assertIsNone(find(found, "EG-SORT-CONTROLS-ABSENT"))
        item = find(found, "EG-FILTER-CONTROLS-ABSENT")
        self.assertIsNotNone(item)
        # The evidence must not deny the affordance the page plainly has.
        self.assertNotIn("sorting", item.evidence.lower().replace("sort controls", ""))
        self.assertIn("do expose sort controls", item.evidence)

    def test_case_d_both_filter_and_sort(self):
        found = run("engagement-audit",
                    bundle([self._category(self.FILTER_HTML + self.SORT_HTML)]))
        self.assertIsNone(find(found, "EG-FILTER-CONTROLS-ABSENT"))
        self.assertIsNone(find(found, "EG-SORT-CONTROLS-ABSENT"))

    def test_evidence_names_the_sort_options_it_observed(self):
        """A boolean is not evidence; the reader must be able to check the claim."""
        category = self._category(self.SORT_HTML)
        self.assertIn("Price, low to high", category["forms"]["sort_options"])
        item = find(run("engagement-audit", bundle([category])),
                    "EG-FILTER-CONTROLS-ABSENT")
        self.assertIn("Featured", item.evidence)
        self.assertIn("Price, low to high", item.metrics["observed_sort_options"])
        self.assertIn("sort controls present", item.evidence_items[0].observation)

    def test_evidence_names_the_filter_controls_it_observed(self):
        category = self._category(self.FILTER_HTML)
        item = find(run("engagement-audit", bundle([category])),
                    "EG-SORT-CONTROLS-ABSENT")
        self.assertTrue(item.metrics["observed_filter_controls"],
                        "the filter controls that were found must be named")
        self.assertIn("do expose filter controls", item.evidence)

    def test_product_slugs_are_not_read_as_filter_controls(self):
        """"Refined Coconut Oil" is a product, not a refinement facet."""
        category = self._category(
            "<a href='/products/refined-coconut-oil'>Refined Coconut Oil</a>"
            "<a href='/products/unrefined-shea'>Unrefined Shea Butter</a>")
        self.assertEqual(category["forms"]["filter_controls"], 0)
        self.assertEqual(category["forms"]["filter_control_names"], [])
        self.assertIsNotNone(find(run("engagement-audit", bundle([category])),
                                  "EG-FILTER-CONTROLS-ABSENT"))

    def test_real_query_parameters_are_still_read_as_controls(self):
        category = self._category(
            "<a href='/collections/all?filter.p.price=0-30'>Under 30</a>"
            "<a href='/collections/all?sort_by=price-ascending'>Price low to high</a>")
        self.assertEqual(category["forms"]["filter_controls"], 1)
        self.assertIn("Price low to high", category["forms"]["sort_options"])

    def test_an_unlabelled_sort_control_does_not_produce_a_dangling_list(self):
        category = self._category(
            "<a href='/collections/all?sort_by=price-ascending'>"
            "<img src='a.png' alt=''></a>")
        item = find(run("engagement-audit", bundle([category])),
                    "EG-FILTER-CONTROLS-ABSENT")
        observation = item.evidence_items[0].observation
        self.assertFalse(observation.rstrip().endswith(":"), observation)
        self.assertIn("none carrying a text label", observation)

    def test_sort_links_count_as_sort_controls(self):
        """Not every listing uses a <select>; link-based sorting counts too."""
        category = self._category(
            '<a href="/collections/all?sort_by=price-ascending">Price low to high</a>')
        self.assertTrue(category["forms"]["has_sort_controls"])
        self.assertIsNone(find(run("engagement-audit", bundle([category])),
                               "EG-SORT-CONTROLS-ABSENT"))

    def test_deeplink_redirected_to_home(self):
        url = ORIGIN + "/products/retired"
        redirected = page(url, html_doc(canonical=ORIGIN + "/", body="<h1>Home</h1>"),
                          redirects=[(301, ORIGIN + "/")])
        redirected["final_url"] = ORIGIN + "/"
        item = find(run("engagement-audit", bundle([redirected])),
                    "EG-DEEPLINK-REDIRECTED-HOME")
        self.assertEqual(item.severity, "high")

    def test_no_site_search(self):
        """Reported where a search would be expected - a site whose sitemap
        advertises many URLs - and as a `low` observation, not a defect."""
        pages = [page(f"{ORIGIN}/x{i}", html_doc(canonical=f"{ORIGIN}/x{i}",
                                                 body="<h1>H</h1><p>text</p>"))
                 for i in range(3)]
        data = bundle(pages)
        data["sitemaps"][0]["url_count"] = 120
        data["sitemaps"][0]["entries"] = [{"url": f"{ORIGIN}/x{i}"} for i in range(120)]
        item = find(run("engagement-audit", data), "EG-NO-SITE-SEARCH")
        self.assertIsNotNone(item)
        self.assertEqual(item.severity, "low")
        self.assertIn("expected because", item.evidence)

    def test_a_small_site_is_not_asked_for_a_search_box(self):
        pages = [page(f"{ORIGIN}/x{i}", html_doc(canonical=f"{ORIGIN}/x{i}",
                                                 body="<h1>H</h1><p>text</p>"))
                 for i in range(3)]
        self.assertIsNone(find(run("engagement-audit", bundle(pages)), "EG-NO-SITE-SEARCH"))


# ---------------------------------------------------------------------------
# generalization: the audit must not penalise a site for not being English
# ---------------------------------------------------------------------------

SPANISH_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"Cafetera Vento 300",'
    '"sku":"CV-300","gtin13":"8901234567890","brand":{"@type":"Brand","name":"Kestrel"},'
    '"category":"Calzado","color":"Azul","material":"Malla",'
    '"additionalProperty":[{"@type":"PropertyValue","name":"Peso","value":"245"}],'
    '"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.6","reviewCount":"128"},'
    '"offers":{"@type":"Offer","price":"5499","priceCurrency":"EUR",'
    '"availability":"https://schema.org/InStock",'
    '"hasMerchantReturnPolicy":{"@type":"MerchantReturnPolicy","merchantReturnDays":30},'
    '"shippingDetails":{"@type":"OfferShippingDetails","shippingRate":'
    '{"@type":"MonetaryAmount","value":"0","currency":"EUR"}}}}')

SPANISH_BODY = (
    '<nav aria-label="breadcrumb"><a href="/">Inicio</a></nav>'
    '<h1>Cafetera Vento 300</h1>'
    '<p>&euro;5.499 &mdash; En stock. Env&iacute;o gratis. Devoluciones en 30 d&iacute;as.</p>'
    '<table><tr><th>Peso</th><td>245 g</td></tr><tr><th>Drop</th><td>8 mm</td></tr>'
    '<tr><th>Color</th><td>Azul</td></tr></table>'
    '<p>Valorado 4,6 sobre 5 con 128 opiniones de clientes.</p>'
    '<button>A&ntilde;adir al carrito</button>'
    + "".join(f"<a href='/p/{i}'>p{i}</a>" for i in range(8)))

SPANISH_ORIGIN = "https://tienda.example"


def spanish_bundle():
    home = page(SPANISH_ORIGIN + "/", html_doc(
        title="Cafeteras | Kestrel", lang="es", canonical=SPANISH_ORIGIN + "/",
        body='<h1>Kestrel</h1><a href="/colecciones/todo">Tienda</a>'
             '<form action="/buscar"><input type="search" name="q"></form>'))
    faq = page(SPANISH_ORIGIN + "/paginas/preguntas-frecuentes", html_doc(
        title="Preguntas frecuentes | Kestrel", lang="es",
        canonical=SPANISH_ORIGIN + "/paginas/preguntas-frecuentes",
        body="<h1>Preguntas frecuentes</h1>"
             "<h2>&iquest;C&oacute;mo devuelvo un art&iacute;culo?</h2><p>En 30 d&iacute;as.</p>"
             "<h2>&iquest;Cu&aacute;nto tarda el env&iacute;o?</h2><p>2-5 d&iacute;as.</p>"))
    products = [page(f"{SPANISH_ORIGIN}/productos/vento-x{i}", html_doc(
        title=f"Vento {300 + i} | Kestrel", lang="es",
        canonical=f"{SPANISH_ORIGIN}/productos/vento-x{i}",
        head=jsonld(SPANISH_LD), body=SPANISH_BODY)) for i in range(3)]
    return bundle([home, faq] + products, origin=SPANISH_ORIGIN)


class TestNonEnglishSite(unittest.TestCase):
    """A well-built Spanish storefront must not be reported as broken.

    Regression for the original English-only heuristics, which read
    "Envio gratis. Devoluciones en 30 dias. En stock." as *none of those facts
    being present* - the worst class of false positive, because it fires
    precisely because the site is not the kind of site the author imagined.
    """

    def test_urls_classify_without_english_path_segments(self):
        data = spanish_bundle()
        types = {p["url"].rsplit("/", 1)[-1]: p["page_type"] for p in data["pages"]}
        self.assertEqual(types["vento-x0"], "product")
        self.assertEqual(types["preguntas-frecuentes"], "faq")

    def test_no_engagement_false_positives(self):
        found = rule_ids(run("engagement-audit", spanish_bundle()))
        self.assertEqual(found, [], f"false positives on a good Spanish site: {found}")

    def test_no_machine_readability_or_freshness_false_positives(self):
        data = spanish_bundle()
        for skill in ("machine-readability-audit", "freshness-corroboration"):
            # These three are true of the minimal synthetic bundle itself
            # (no WebSite node, no dates, no declared anchors), not artefacts
            # of the page being Spanish - the English equivalents report them
            # too. Everything else must be silent.
            expected_of_a_stub = ("MR-SITE-SCHEMA-MISSING", "FC-NO-DATE-SIGNALS",
                                  "FC-NO-CORROBORATION-ANCHORS")
            found = [f for f in rule_ids(run(skill, data))
                     if f not in expected_of_a_stub]
            self.assertEqual(found, [], f"{skill}: {found}")

    def test_structured_markup_answers_for_prose_we_cannot_read(self):
        """Japanese prose is unreadable to the lexicon; the markup is not."""
        data = spanish_bundle()
        for page_facts in data["pages"]:
            page_facts["language_supported"] = False
            page_facts["mentions"] = {k: False for k in page_facts.get("mentions", {})}
        found = rule_ids(run("engagement-audit", data))
        for rule in ("EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE",
                     "EG-CTA-NOT-IN-HTML"):
            self.assertNotIn(rule, found,
                             "an unreadable language must not become a finding")


# ---------------------------------------------------------------------------
# cross-cutting invariants
# ---------------------------------------------------------------------------

class TestFindingInvariants(unittest.TestCase):
    def all_findings(self):
        robots = "User-agent: *\nDisallow:\n\nUser-agent: GPTBot\nDisallow: /\n"
        data = bundle([page(ORIGIN + "/", html_doc(canonical=ORIGIN + "/", body="<h1>H</h1>")),
                       page(ORIGIN + "/products/x",
                            html_doc(canonical=ORIGIN + "/products/x", body="<h1>X</h1>"))],
                      robots_raw=robots)
        out = []
        for skill in ("crawl-render-audit", "machine-readability-audit",
                      "freshness-corroboration", "entity-audit", "engagement-audit"):
            out.extend(run(skill, data))
        return out

    def test_every_finding_is_self_valid(self):
        found = self.all_findings()
        self.assertTrue(found, "expected the deliberately broken bundle to produce findings")
        for item in found:
            self.assertEqual(item.problems(), [], f"{item.rule_id}: {item.problems()}")

    def test_every_finding_cites_evidence_with_a_source(self):
        for item in self.all_findings():
            self.assertTrue(item.evidence_items, f"{item.rule_id} has no evidence items")
            for evidence in item.evidence_items:
                self.assertTrue(evidence.observation.strip())
                if evidence.kind != "measurement":
                    self.assertTrue(evidence.url, f"{item.rule_id}: evidence without a URL")

    def test_every_action_has_a_mechanism_and_verification(self):
        for item in self.all_findings():
            action = item.suggested_action
            self.assertTrue(action.summary.strip(), item.rule_id)
            self.assertTrue(action.mechanism.strip(), f"{item.rule_id} has no mechanism")
            self.assertTrue(action.steps, f"{item.rule_id} has no steps")
            self.assertTrue(action.verification.strip(), f"{item.rule_id} has no verification")

    def test_rule_ids_are_unique_within_a_run(self):
        ids = [item.rule_id for item in self.all_findings()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_finding_states_an_interpretation(self):
        """Three parts, always: what was seen, what it may mean, what to do."""
        for item in self.all_findings():
            self.assertTrue(item.observation.strip(), f"{item.rule_id} has no observation")
            self.assertTrue(item.reasoning.strip(),
                            f"{item.rule_id} states no interpretation of its observation")
            self.assertTrue(item.suggested_action.summary.strip(), item.rule_id)

    def test_no_evidence_string_asserts_an_unmeasured_consequence(self):
        """The guard that stops an inference being laundered into a fact.

        A static audit does not observe bounces, viewports or what a visitor
        had to do. Those claims are interpretation; asserting them in the
        evidence line is the specific failure this checks for.
        """
        from aiva.findings import _sorted_unmeasured_phrases
        for item in self.all_findings():
            self.assertEqual(_sorted_unmeasured_phrases(item.evidence), [],
                             f"{item.rule_id} evidence claims an unmeasured consequence")
            for evidence in item.evidence_items:
                self.assertEqual(_sorted_unmeasured_phrases(evidence.observation), [],
                                 f"{item.rule_id} evidence item claims a consequence")

    #: Claims a single-site, read-only, static audit is not in a position to
    #: make. Each of these was found in a shipped evidence string: a statement
    #: about the wider web, about a competitor, or about what a reader could
    #: or could not do. They are all reasonable *interpretations* and all
    #: unsupportable as *observations*.
    OVERCLAIMS = (
        "exists in exactly one place on the web",
        "nothing links this page to the same product",
        "there is no way to tell",
        "not enough prose",
        "loses to competitors",
    )

    def test_no_evidence_string_claims_more_than_one_site_was_read(self):
        for item in self.all_findings():
            lowered = item.evidence.lower()
            for phrase in self.OVERCLAIMS:
                self.assertNotIn(phrase, lowered,
                                 f"{item.rule_id} evidence asserts something this audit "
                                 f"cannot observe: {phrase!r}")

    #: Claims that the audited pages are *categorically excluded* from an
    #: outcome. Observing that a relationship is absent from the markup does
    #: not establish that every system fails to resolve it by other means, so
    #: the finding says what is missing and what that can make harder — not
    #: that the product is disqualified. Distinct from a general statement
    #: about how a mechanism works, which stays allowed.
    CATEGORICAL_EXCLUSION = (
        "ineligible",
        "is not a member of anything",
        "disqualified",
        "excluded from the comparison by default",
        "cannot appear at all",
        "will not be considered",
    )

    #: The "not detected, therefore cannot" step. An absence in the fetched
    #: bytes is a fact about the bytes; what any given system then does with
    #: the page is not something a single read-only fetch establishes. These
    #: phrases make the leap inside the *observation*, where it reads as
    #: measurement. Stated in `interpretation` the same reasoning is fine —
    #: which is where each of these was moved.
    ASSERTED_INCAPACITY = (
        r"\bassistants? (?:cannot|can't|will not|won't)\b",
        r"\bmachines? cannot\b",
        r"\bany assistant\b",
        r"\bevery assistant\b",
        r"\bcannot be (?:answered|resolved|matched|cited|found)\b",
        r"\bnothing (?:answers|supports|tells|links|marks|states)\b",
        r"\bhas to be guessed\b",
    )

    def test_no_observation_turns_an_absence_into_an_incapacity(self):
        import re as _re
        for item in self.all_findings():
            for pattern in self.ASSERTED_INCAPACITY:
                match = _re.search(pattern, item.evidence, _re.I)
                if match is not None:
                    self.fail(f"{item.rule_id} observation asserts an incapacity "
                              f"({match.group(0)!r} in `evidence`); an absence in the "
                              f"response is a fact, what a system does with it is "
                              f"interpretation")

    def test_no_finding_claims_the_site_is_categorically_excluded(self):
        for item in self.all_findings():
            blob = " ".join([item.evidence, item.reasoning,
                             item.suggested_action.mechanism,
                             " ".join(item.suggested_action.steps)]).lower()
            for phrase in self.CATEGORICAL_EXCLUSION:
                self.assertNotIn(phrase, blob,
                                 f"{item.rule_id} claims categorical exclusion ({phrase!r}); "
                                 f"an absence in the markup is not proof of an outcome")

    def test_every_verification_declares_how_it_can_be_checked(self):
        from aiva.findings import VERIFICATION_TYPES
        for item in self.all_findings():
            self.assertIn(item.suggested_action.verification_type, VERIFICATION_TYPES,
                          item.rule_id)

    def test_each_specialist_declares_its_own_pillar(self):
        expected = {"crawl-render-audit": "crawl_render",
                    "machine-readability-audit": "machine_readability",
                    "freshness-corroboration": "freshness_corroboration",
                    "entity-audit": "entity",
                    "engagement-audit": "engagement"}
        for item in self.all_findings():
            self.assertEqual(item.pillar, expected[item.source_skill])


if __name__ == "__main__":
    unittest.main()
