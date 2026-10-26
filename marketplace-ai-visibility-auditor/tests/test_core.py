"""Unit tests for the shared library primitives."""

from __future__ import annotations

import datetime as dt
import unittest

import helpers  # noqa: F401 - sets up sys.path
from aiva import frontmatter, jsonschema_lite, util
from aiva.config import AuditConfig
from aiva.discover import (ASSET_SUFFIXES, NON_CITABLE_PATH_RE, SAMPLE_ORDER,
                           build_frontier, normalize_site_input, parse_sitemap,
                           sample_frontier)
from aiva.extract import classify_page, find_nodes, flatten_jsonld, prop, text_of
from aiva.htmldom import parse_html
from aiva.robots import RobotsTxt


class TestUtil(unittest.TestCase):
    def test_normalize_url_strips_tracking_and_fragment(self):
        self.assertEqual(
            util.normalize_url("https://Shop.Example:443/a//b?utm_source=x&id=3#frag"),
            "https://shop.example/a/b?id=3")

    def test_normalize_url_rejects_non_http(self):
        for value in ("mailto:a@b.com", "javascript:void(0)", "tel:+1", "data:text/plain,x", ""):
            self.assertIsNone(util.normalize_url(value))

    def test_normalize_url_resolves_relative(self):
        self.assertEqual(util.normalize_url("../c", "https://x.example/a/b/"),
                         "https://x.example/a/c")

    def test_same_site(self):
        self.assertTrue(util.same_site("https://www.x.example/a", "https://x.example/b"))
        self.assertFalse(util.same_site("https://x.example", "https://y.example"))

    def test_parse_date_variants(self):
        self.assertEqual(util.parse_date("2024-03-05").year, 2024)
        self.assertEqual(util.parse_date("2024-03-05T10:00:00Z").month, 3)
        self.assertEqual(util.parse_date("Tue, 05 Mar 2024 10:00:00 GMT").day, 5)
        self.assertEqual(util.parse_date("2019").year, 2019)
        self.assertIsNone(util.parse_date("not a date"))
        self.assertIsNone(util.parse_date(None))

    def test_days_since(self):
        now = dt.datetime(2026, 1, 11, tzinfo=dt.timezone.utc)
        then = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        self.assertEqual(util.days_since(then, now), 10)

    def test_normalize_name_folds_punctuation_and_accents(self):
        self.assertEqual(util.normalize_name("Garuda  Footwear™ (Pvt.)"),
                         "garuda footwear pvt")


class TestSiteInput(unittest.TestCase):
    """A deep entry URL must not be mistaken for the site's home page."""

    def test_bare_domain(self):
        origin, home, entry = normalize_site_input("shop.example")
        self.assertEqual((origin, home, entry),
                         ("https://shop.example", "https://shop.example/",
                          "https://shop.example/"))

    def test_deep_url_keeps_the_root_as_home(self):
        origin, home, entry = normalize_site_input(
            "https://shop.example/collections/cocoa?srsltid=AfmBOo123")
        self.assertEqual(origin, "https://shop.example")
        self.assertEqual(home, "https://shop.example/")
        # tracking parameters are stripped from the entry point
        self.assertEqual(entry, "https://shop.example/collections/cocoa")

    def test_empty_input_is_refused(self):
        with self.assertRaises(ValueError):
            normalize_site_input("   ")


class TestFrontier(unittest.TestCase):
    SITE = {"origin": "https://shop.example", "home_url": "https://shop.example/",
            "entry_url": "https://shop.example/"}

    def frontier(self, links):
        facts = {"page_type": "home",
                 "links": {"internal": [{"url": u} for u in links]}}
        return build_frontier(self.SITE, [facts], [], None)

    def test_transactional_paths_are_never_crawled(self):
        candidates, _ = self.frontier([
            "https://shop.example/cart",
            "https://shop.example/checkout/step-1",
            "https://shop.example/account/login",
            "https://shop.example/collections/all",
        ])
        self.assertEqual([url for url, _ in candidates],
                         ["https://shop.example/collections/all"])

    def test_binary_assets_are_skipped(self):
        candidates, _ = self.frontier([
            "https://shop.example/assets/app.js",
            "https://shop.example/img/hero.jpg",
            "https://shop.example/catalogue.pdf",
            "https://shop.example/pages/about",
        ])
        self.assertEqual([url for url, _ in candidates],
                         ["https://shop.example/pages/about"])

    def test_duplicate_candidates_are_collapsed_and_counted(self):
        candidates, collapsed = self.frontier([
            "https://shop.example/pages/about",
            "https://shop.example/pages/about?utm_source=nav",
            "https://shop.example/",
        ])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(collapsed, 2)

    def test_non_citable_regex_is_anchored(self):
        self.assertIsNotNone(NON_CITABLE_PATH_RE.search("/cart"))
        self.assertIsNotNone(NON_CITABLE_PATH_RE.search("/account/addresses"))
        self.assertIsNone(NON_CITABLE_PATH_RE.search("/collections/cart-bags"))
        # A transactional path is excluded wherever it sits, not only at the root.
        self.assertIsNotNone(NON_CITABLE_PATH_RE.search("/us/shop/goto/account"))
        self.assertIsNotNone(NON_CITABLE_PATH_RE.search("/de/warenkorb"))
        self.assertIsNone(NON_CITABLE_PATH_RE.search("/products/shopping-bag-leather"))
        self.assertIn(".css", ASSET_SUFFIXES)


class TestFrontierSampling(unittest.TestCase):
    """The crawl budget must be spent, not abandoned when a quota is full.

    Regression: the per-type quotas are keyed on `classify_page(url)` - a guess
    made before anything is fetched. A site writing /shop/blue-mug filed its
    whole catalogue under "other" (quota 4) while the 12 product slots went
    unspent, and the sampler returned: **5 pages against a budget of 40**.
    Every ratio in the report is then computed over almost nothing, and the
    sample-size guards correctly refuse to generalise from it - so a broken
    site produced a near-empty report that read as clean.
    """

    B = "https://shop.example"

    def plan(self, urls, **overrides):
        config = AuditConfig(site=self.B)
        for key, value in overrides.items():
            setattr(config, key, value)
        return sample_frontier([(u, "sitemap") for u in urls], config,
                               already=[self.B + "/"])

    def counts(self, plan):
        counter = {}
        for _, _, page_type in plan:
            counter[page_type] = counter.get(page_type, 0) + 1
        return counter

    def catalogue(self, product_seg, category_seg, products=25, categories=6):
        return ([f"{self.B}/{product_seg}/item-{i}" for i in range(products)]
                + [f"{self.B}/{category_seg}/c-{i}" for i in range(categories)])

    def test_an_unrecognised_url_scheme_no_longer_starves_the_crawl(self):
        recognised = self.plan(self.catalogue("products", "collections"))
        opaque = self.plan(self.catalogue("shop", "range"))
        self.assertEqual(len(recognised), len(opaque), "same site, same sample size")
        self.assertEqual(len(opaque), 31)
        # The prediction is still wrong - that is fine, it is only a queue hint.
        self.assertEqual(self.counts(opaque), {"other": 31})

    def test_the_quota_round_still_balances_a_recognisable_site(self):
        """Round 1 is unchanged: types are drawn in quota order first."""
        plan = self.plan(self.catalogue("products", "collections", products=99,
                                        categories=99), max_pages=17)
        counts = self.counts(plan)
        self.assertEqual(counts["product"], 12)
        self.assertEqual(counts["category"], 5)
        self.assertEqual(len(plan), 17)

    def test_the_sample_never_exceeds_the_page_budget(self):
        plan = self.plan([f"{self.B}/shop/item-{i}" for i in range(500)])
        # One page (the home page) is already fetched and counts against it.
        self.assertEqual(len(plan), AuditConfig(site=self.B).max_pages - 1)

    def test_a_large_bucket_cannot_crowd_out_the_catalogue_it_hides(self):
        """The leftover round is round-robin, not a flat sort.

        A blog with hundreds of shallow URLs would otherwise absorb the whole
        remainder, and the catalogue it was hiding stays unseen.
        """
        plan = self.plan([f"{self.B}/blog/post-{i}" for i in range(200)]
                         + [f"{self.B}/shop/item-{i}" for i in range(25)])
        counts = self.counts(plan)
        self.assertGreaterEqual(counts.get("other", 0), 15,
                                "the opaque catalogue must survive the blog")
        self.assertLessEqual(counts.get("article", 0), 25)

    def test_a_small_site_is_crawled_whole_without_padding(self):
        urls = self.catalogue("products", "collections", products=3, categories=1)
        self.assertEqual(len(self.plan(urls)), 4)

    def test_pages_already_held_are_never_queued_twice(self):
        config = AuditConfig(site=self.B)
        urls = [f"{self.B}/shop/item-{i}" for i in range(10)]
        plan = sample_frontier([(u, "sitemap") for u in urls], config,
                               already=[self.B + "/", urls[0], urls[1]])
        planned = [u for u, _, _ in plan]
        self.assertNotIn(urls[0], planned)
        self.assertEqual(len(planned), len(set(planned)))
        self.assertEqual(len(planned), 8)

    def test_an_unknown_bucket_is_still_reachable(self):
        """A page type added to PAGE_TYPE_HINTS must not become unfetchable."""
        self.assertIn("other", SAMPLE_ORDER)
        plan = self.plan([f"{self.B}/shop/x"])
        self.assertEqual(len(plan), 1)


class TestPageClassification(unittest.TestCase):
    """A page's own declaration counts, whatever channel it is written in."""

    URL = "https://shop.example/x/y-42"

    #: What an ordinary page carries besides its declared type: a heading and
    #: a price in its own content. The declaration is the *second* signal here,
    #: never the only one.
    PAGE = {"h1_count": 1, "h1_texts": ["Aero Runner"], "title": "Aero Runner",
            "prices_in_text": [{"value": "5499"}],
            "main_text": "Aero Runner ₹5,499 - in stock."}

    def _with(self, **over):
        facts = dict(self.PAGE)
        facts.update(over)
        return facts

    def test_a_declared_type_is_read_from_microdata_and_open_graph(self):
        """JSON-LD is not the only place a page states what it is.

        A site that does not write Shopify-style URLs is no more likely to
        write Shopify-style JSON-LD, and it was being filed as "other" while
        declaring itself plainly in another vocabulary.
        """
        microdata = self._with(microdata=[{"itemtype": "https://schema.org/Product",
                                           "types": ["Product"], "props": {}}])
        self.assertEqual(classify_page(self.URL, microdata), "product")

        open_graph = self._with(open_graph={"og:type": "product"})
        self.assertEqual(classify_page(self.URL, open_graph), "product")

        listing = self._with(microdata=[{"itemtype": "https://schema.org/CollectionPage",
                                         "types": ["CollectionPage"], "props": {}}])
        self.assertEqual(classify_page(self.URL, listing), "category")

    def test_a_declared_type_on_its_own_is_not_enough(self):
        """The other half of the same rule, and the reason it is a rule.

        `og:type=product` is one line of a template. On a storefront the
        template that emits it runs on gift-card pages, membership pages and
        promotional hubs too, so the declaration says the site sells things -
        it does not say this page is one of them. Read as a whole signal it
        turns every such page into a product detail page; read as one signal
        among several it does what it is for.
        """
        for facts in ({"microdata": [{"itemtype": "https://schema.org/Product",
                                      "types": ["Product"], "props": {}}]},
                      {"open_graph": {"og:type": "product"}},
                      {"jsonld_types": ["Product"]}):
            with self.subTest(facts=facts):
                self.assertNotEqual(classify_page(self.URL, facts), "product")

    def test_a_recognisable_url_still_wins_over_a_declared_type(self):
        """No regression: declared types are consulted only as a fallback.

        A listing whose og:type says "product" is still a listing - the URL
        segment is the more reliable statement about the *page's* role.
        """
        facts = {"open_graph": {"og:type": "product"}}
        self.assertEqual(
            classify_page("https://shop.example/collections/running", facts), "category")

    def test_an_ordinary_page_is_not_promoted_by_one_commerce_phrase(self):
        """The 2-of-3 guard is intact."""
        self.assertEqual(classify_page(self.URL, {"prices_in_text": ["£10"]}), "other")
        self.assertEqual(
            classify_page(self.URL, {"forms": {"has_cart_action": True}}), "other")
        self.assertEqual(classify_page(self.URL, {"open_graph": {"og:type": "website"}}),
                         "other")

    def test_a_comparison_page_is_not_a_product_page(self):
        """Regression: adding `availability_text` as a fourth signal broke this.

        A comparison page carries the prices and the stock lines of two
        products without being either of them. Stock phrasing reads from the
        same prose as the price, so counting both counts one observation twice.
        """
        facts = {"prices_in_text": ["£10", "£12"],
                 "availability_text": ["in stock", "in stock"],
                 "mentions": {"compare": True}}
        self.assertEqual(classify_page("https://shop.example/compare/a-vs-b", facts),
                         "other")


class TestHtmlDom(unittest.TestCase):
    def test_parses_malformed_html(self):
        doc = parse_html("<html><body><p>one<p>two<div><span>three</div></body>")
        self.assertEqual(len(doc.find_all("p")), 2)
        self.assertIn("three", doc.get_text(" "))

    def test_skips_script_and_style_from_text(self):
        doc = parse_html("<body><style>.a{color:red}</style><script>var x=1;</script>"
                         "<p>visible</p></body>")
        self.assertEqual(doc.get_text(" ").strip(), "visible")

    def test_script_body_is_concatenated_not_space_joined(self):
        payload = '{"a": "b c"}'
        doc = parse_html(f'<script type="application/ld+json">{payload}</script>')
        self.assertEqual(doc.find("script").raw_text.strip(), payload)

    def test_class_attribute_matching(self):
        doc = parse_html('<div class="a breadcrumb c">x</div>')
        self.assertIsNotNone(doc.find(attrs={"class": "breadcrumb"}))

    def test_void_elements_do_not_nest(self):
        doc = parse_html("<body><img src='a'><p>after</p></body>")
        self.assertEqual(doc.find("p").parent.tag, "body")


class TestRobots(unittest.TestCase):
    SAMPLE = """
    User-agent: *
    Disallow: /cart
    Allow: /cart/help

    User-agent: GPTBot
    Disallow: /

    User-agent: ClaudeBot
    Crawl-delay: 3
    Disallow: /private

    Sitemap: https://shop.example/sitemap.xml
    """

    def parsed(self) -> RobotsTxt:
        return RobotsTxt.from_response("https://shop.example/robots.txt", 200, self.SAMPLE)

    def test_group_selection_and_longest_match(self):
        robots = self.parsed()
        self.assertFalse(robots.can_fetch("SomeBot", "/cart"))
        self.assertTrue(robots.can_fetch("SomeBot", "/cart/help"))
        self.assertTrue(robots.can_fetch("SomeBot", "/products/x"))

    def test_specific_agent_group_wins(self):
        robots = self.parsed()
        self.assertFalse(robots.can_fetch("GPTBot", "/products/x"))
        self.assertTrue(robots.blocks_everything_for("GPTBot"))
        self.assertFalse(robots.blocks_everything_for("ClaudeBot"))
        self.assertFalse(robots.can_fetch("ClaudeBot", "/private/x"))

    def test_crawl_delay_and_sitemaps(self):
        robots = self.parsed()
        self.assertEqual(robots.crawl_delay_for("ClaudeBot"), 3.0)
        self.assertEqual(robots.sitemaps, ["https://shop.example/sitemap.xml"])

    def test_wildcards_and_anchors(self):
        robots = RobotsTxt.from_response("u", 200,
                                         "User-agent: *\nDisallow: /*?sort=\nDisallow: /tmp$\n")
        self.assertFalse(robots.can_fetch("x", "/a/b?sort=asc"))
        self.assertTrue(robots.can_fetch("x", "/a/b?colour=red"))
        self.assertFalse(robots.can_fetch("x", "/tmp"))
        self.assertTrue(robots.can_fetch("x", "/tmp/file"))

    def test_empty_disallow_allows_everything(self):
        robots = RobotsTxt.from_response("u", 200, "User-agent: *\nDisallow:\n")
        self.assertTrue(robots.can_fetch("x", "/anything"))

    def test_missing_robots_allows_everything(self):
        robots = RobotsTxt.from_response("u", 404, "")
        self.assertTrue(robots.can_fetch("x", "/anything"))
        self.assertFalse(robots.exists)

    def test_unreachable_robots_disallows_everything(self):
        robots = RobotsTxt.from_response("u", 503, "")
        self.assertTrue(robots.unreachable)
        self.assertFalse(robots.can_fetch("x", "/"))

    def test_reports_non_standard_directives(self):
        robots = RobotsTxt.from_response("u", 200,
                                         "User-agent: *\nNoindex: /x\nHost: example.com\n")
        fields = {field for _, field, _ in robots.other_directives}
        self.assertIn("noindex", fields)
        self.assertIn("host", fields)


class TestExtract(unittest.TestCase):
    def test_jsonld_parsing_and_types(self):
        html = helpers.html_doc(head=helpers.jsonld(
            '{"@context":"https://schema.org","@type":"Product","name":"X",'
            '"offers":{"@type":"Offer","price":"10","priceCurrency":"INR"}}'))
        facts = helpers.page("https://shop.example/products/x", html)
        self.assertIn("Product", facts["jsonld_types"])
        self.assertIn("Offer", facts["jsonld_types"])
        self.assertEqual(facts["jsonld_invalid_count"], 0)

    def test_invalid_jsonld_is_recorded_not_raised(self):
        html = helpers.html_doc(head=helpers.jsonld('{"a": 1,}'))
        facts = helpers.page("https://shop.example/x", html)
        self.assertEqual(facts["jsonld_invalid_count"], 1)
        self.assertIsNotNone(facts["jsonld_blocks"][0]["error"])

    def test_price_extraction(self):
        facts = helpers.page("https://shop.example/p",
                             helpers.html_doc(body="<p>&#8377;5,499 or $79.99</p>"))
        values = sorted(entry["value"] for entry in facts["prices_in_text"])
        self.assertEqual(values, [79.99, 5499.0])

    def test_amount_parsing_is_locale_aware(self):
        """"EUR 5.499" is 5499, not 5.499 - getting this wrong invents a
        price conflict on every site that groups thousands with a dot."""
        from aiva.extract import parse_amount
        cases = {
            "1,234.56": 1234.56,   # en
            "1.234,56": 1234.56,   # es / de / it / pt / nl
            "1 234,56": 1234.56,   # fr
            "5.499": 5499.0,
            "5,499": 5499.0,
            "79.99": 79.99,
            "79,99": 79.99,
            "1234": 1234.0,
            "12.345.678,90": 12345678.90,
        }
        for raw, expected in cases.items():
            self.assertEqual(parse_amount(raw), expected, raw)
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount("abc"))

    def test_european_price_is_extracted_whole(self):
        facts = helpers.page("https://tienda.example/p",
                             helpers.html_doc(body="<p>&euro;5.499 y &euro;79,99</p>"))
        self.assertEqual(sorted(e["value"] for e in facts["prices_in_text"]),
                         [79.99, 5499.0])

    def test_title_is_read_even_though_head_is_non_content(self):
        facts = helpers.page("https://shop.example/x", helpers.html_doc(title="Hello World"))
        self.assertEqual(facts["title"], "Hello World")

    def test_spec_table_detection(self):
        body = ("<table><tr><th>Weight</th><td>245 g</td></tr>"
                "<tr><th>Drop</th><td>8 mm</td></tr>"
                "<tr><th>Colour</th><td>Blue</td></tr></table>")
        facts = helpers.page("https://shop.example/p", helpers.html_doc(body=body))
        self.assertTrue(facts["tables"][0]["looks_like_spec_table"])

    def test_page_classification_prefers_url_over_embedded_markup(self):
        html = helpers.html_doc(head=helpers.jsonld(
            '{"@context":"https://schema.org","@type":"ItemList","itemListElement":'
            '[{"@type":"Product","name":"A"}]}'))
        facts = helpers.page("https://shop.example/collections/all", html)
        self.assertEqual(facts["page_type"], "category")

    def test_page_classification_falls_back_to_markup(self):
        html = helpers.html_doc(head=helpers.jsonld(
            '{"@context":"https://schema.org","@type":"Product","name":"A"}'))
        facts = helpers.page("https://shop.example/item.php?id=9", html)
        self.assertEqual(facts["page_type"], "product")

    def test_share_buttons_are_not_profile_links(self):
        body = ('<a href="https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fx.example%2Fa">'
                'Share</a>'
                '<a href="https://twitter.com/intent/tweet?url=https://x.example/a">Tweet</a>'
                '<a href="https://pinterest.com/pin/create/button/?url=https://x.example">Pin</a>'
                '<a href="https://www.facebook.com/cocoacraft.chocolate">Facebook</a>'
                '<a href="https://www.instagram.com/cocoacraft.chocolate/">Instagram</a>')
        facts = helpers.page("https://shop.example/blogs/post", helpers.html_doc(body=body))
        profiles = facts["links"]["sameas_like"]
        self.assertEqual(sorted(profiles), [
            "https://www.facebook.com/cocoacraft.chocolate",
            "https://www.instagram.com/cocoacraft.chocolate/"])

    def test_spa_marker_detection(self):
        facts = helpers.page("https://shop.example/p",
                             helpers.html_doc(body='<div id="root"></div>'))
        self.assertTrue(facts["scripts"]["spa_markers"])

    def test_flatten_and_find_nodes(self):
        data = {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "name": "Acme"},
            {"@type": "Product", "name": "P", "offers": {"@type": "Offer", "price": "1"}}]}
        nodes = flatten_jsonld(data)
        self.assertEqual(len(find_nodes(nodes, "Organization")), 1)
        self.assertEqual(text_of(prop(find_nodes(nodes, "Offer")[0], "price")), "1")


class TestSitemapParsing(unittest.TestCase):
    def test_urlset(self):
        xml = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               '<url><loc>https://a.example/1</loc><lastmod>2026-01-01</lastmod></url>'
               '<url><loc>https://a.example/2</loc></url></urlset>')
        parsed = parse_sitemap(xml)
        self.assertEqual(parsed["kind"], "urlset")
        self.assertEqual(len(parsed["urls"]), 2)
        self.assertEqual(parsed["urls"][0]["lastmod"], "2026-01-01")

    def test_index(self):
        xml = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               '<sitemap><loc>https://a.example/s1.xml</loc></sitemap></sitemapindex>')
        parsed = parse_sitemap(xml)
        self.assertEqual(parsed["kind"], "index")
        self.assertEqual(parsed["sitemaps"][0]["url"], "https://a.example/s1.xml")

    def test_malformed_xml_is_reported_not_raised(self):
        parsed = parse_sitemap("<urlset><url><loc>broken")
        self.assertIsNotNone(parsed["error"])


class TestLexicon(unittest.TestCase):
    def test_concepts_match_across_languages(self):
        from aiva import lexicon
        for text in ("Free shipping", "Env\u00edo gratis", "Livraison gratuite",
                     "Kostenloser Versand", "Frete gr\u00e1tis", "Spedizione gratuita",
                     "Gratis verzending"):
            self.assertTrue(lexicon.mentions("shipping", text), text)
        for text in ("30-day returns", "Devoluciones en 30 d\u00edas",
                     "Retours sous 30 jours", "30 Tage R\u00fcckgabe",
                     "Devolu\u00e7\u00e3o em 30 dias", "Resi entro 30 giorni",
                     "30 dagen retourneren"):
            self.assertTrue(lexicon.mentions("returns", text), text)
        for text in ("In stock", "En stock", "Auf Lager", "Disponibile",
                     "Em estoque", "Op voorraad"):
            self.assertTrue(lexicon.mentions("in_stock", text), text)

    def test_diacritics_are_folded_both_ways(self):
        from aiva import lexicon
        self.assertTrue(lexicon.mentions("shipping", "ENV\u00cdO"))
        self.assertTrue(lexicon.mentions("shipping", "envio"))

    def test_word_boundaries_prevent_substring_hits(self):
        from aiva import lexicon
        self.assertFalse(lexicon.mentions("returns", "returnstoprevious"))
        self.assertFalse(lexicon.mentions("shipping", "battleship"))

    def test_language_support_is_declared_honestly(self):
        from aiva import lexicon
        self.assertTrue(lexicon.language_supported("es-ES"))
        self.assertTrue(lexicon.language_supported(""))      # undeclared -> assume readable
        self.assertFalse(lexicon.language_supported("ja"))
        self.assertFalse(lexicon.language_supported("zh-Hans"))


class TestFrontmatter(unittest.TestCase):
    def test_multiline_plain_scalar(self):
        text = ("---\n"
                "name: my-skill\n"
                "description: Does a thing\n"
                "  across two lines.\n"
                "license: Apache-2.0\n"
                "metadata:\n"
                "  author: acme\n"
                "  version: \"1.0\"\n"
                "---\n"
                "# Body\n")
        data, body = frontmatter.load(text)
        self.assertEqual(data["name"], "my-skill")
        self.assertEqual(data["description"], "Does a thing across two lines.")
        self.assertEqual(data["metadata"], {"author": "acme", "version": "1.0"})
        self.assertTrue(body.startswith("# Body"))

    def test_block_scalar(self):
        text = "---\nname: x\ndescription: >\n  one\n  two\n---\nbody\n"
        data, _ = frontmatter.load(text)
        self.assertEqual(data["description"], "one two")

    def test_no_frontmatter(self):
        data, body = frontmatter.load("# just markdown")
        self.assertEqual(data, {})
        self.assertIn("just markdown", body)


class TestJsonSchemaLite(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "required": ["a"],
        "properties": {
            "a": {"type": "string", "minLength": 1},
            "b": {"type": "integer", "minimum": 0},
            "c": {"type": "array", "items": {"$ref": "#/$defs/item"}},
            "d": {"type": "string", "enum": ["x", "y"]},
        },
        "$defs": {"item": {"type": "object", "required": ["k"],
                           "properties": {"k": {"type": "string"}}}},
    }

    def test_valid(self):
        self.assertEqual(jsonschema_lite.validate(
            {"a": "hi", "b": 2, "c": [{"k": "v"}], "d": "x"}, self.SCHEMA), [])

    def test_missing_required(self):
        errors = jsonschema_lite.validate({}, self.SCHEMA)
        self.assertTrue(any("missing required property 'a'" in e for e in errors))

    def test_type_and_enum_errors(self):
        errors = jsonschema_lite.validate({"a": 1, "d": "z"}, self.SCHEMA)
        self.assertTrue(any("expected type string" in e for e in errors))
        self.assertTrue(any("not in enum" in e for e in errors))

    def test_bool_is_not_integer(self):
        errors = jsonschema_lite.validate({"a": "x", "b": True}, self.SCHEMA)
        self.assertTrue(errors)

    def test_ref_items(self):
        errors = jsonschema_lite.validate({"a": "x", "c": [{"nope": 1}]}, self.SCHEMA)
        self.assertTrue(any("missing required property 'k'" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
