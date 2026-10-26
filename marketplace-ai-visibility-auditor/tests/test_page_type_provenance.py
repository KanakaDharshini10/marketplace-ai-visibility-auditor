"""One classification, consumed by everything downstream.

`page_type` is decided once, by the collector, and frozen into the bundle.
Every rule that samples a page type reads that answer. The failure this suite
exists for is a rule deciding for itself what a listing is: a product detail
page was asked why it published no filter controls and no sort controls,
questions that only make sense about a *set*, and a reader seeing them cannot
tell whether the auditor misread one page or misunderstands catalogues.

The assertions here are about behaviour, not wiring. They put pages into a
bundle, run the real specialists over it, and read the findings that come
back - so they keep holding if the plumbing underneath is rewritten, and they
fail if any future rule starts guessing again.

Five unrelated synthetic domains, one per shape the classifier has to
separate: a genuine product detail page, a product listing, a multi-product
collection, a promotional page quoting prices, and an ambiguous landing page
written in product vocabulary.
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, find, html_doc, page, run, rule_ids
from aiva import evidence as ev


# ---------------------------------------------------------------------------
# the five shapes, on five domains
# ---------------------------------------------------------------------------

PDP_ORIGIN = "https://www.calderwell-tools.example"
PDP_URL = PDP_ORIGIN + "/products/bench-vice-150"

PDP_LD = """<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Bench vice 150mm",
 "sku":"BV-150","brand":{"@type":"Brand","name":"Calderwell"},
 "description":"Cast iron bench vice with a 150mm jaw.","image":"/img/bv150.jpg",
 "offers":{"@type":"Offer","price":"129","priceCurrency":"GBP",
           "availability":"https://schema.org/InStock"}}
</script>"""


def product_detail_page(origin: str = PDP_ORIGIN) -> dict:
    """A genuine PDP: one entity, named by the markup and by the heading."""
    url = origin + "/products/bench-vice-150"
    body = ("<header><nav><a href='/'>Home</a></nav></header>"
            "<main><nav aria-label='breadcrumb'><a href='/'>Home</a> / "
            "<a href='/workshop'>Workshop</a> / Bench vice</nav>"
            "<h1>Bench vice 150mm</h1><p>&pound;129.00 &mdash; in stock.</p>"
            "<form action='/cart/add'><button>Add to basket</button></form>"
            "<table><tr><th>Jaw width</th><td>150 mm</td></tr>"
            "<tr><th>Weight</th><td>11 kg</td></tr></table></main>")
    return page(url, html_doc(title="Bench vice 150mm | Calderwell",
                              canonical=url, head=PDP_LD, body=body))


LISTING_ORIGIN = "https://www.marchmont-ceramics.example"
LISTING_URL = LISTING_ORIGIN + "/category/tableware"


def product_listing_page() -> dict:
    """A category page, declared and shaped as one."""
    body = ("<main><h1>Tableware</h1>"
            "<label>Sort <select name='sort_by'><option>Price</option></select></label>"
            "<ul>"
            "<li><a href='/p/rye-bowl'>Rye bowl &pound;22</a></li>"
            "<li><a href='/p/rye-plate'>Rye plate &pound;18</a></li>"
            "<li><a href='/p/heath-mug'>Heath mug &pound;14</a></li>"
            "<li><a href='/p/heath-jug'>Heath jug &pound;36</a></li>"
            "<li><a href='/p/coll-platter'>Coll platter &pound;58</a></li>"
            "<li><a href='/p/coll-bowl'>Coll bowl &pound;24</a></li>"
            "<li><a href='/p/skye-cup'>Skye cup &pound;12</a></li>"
            "<li><a href='/p/skye-saucer'>Skye saucer &pound;9</a></li>"
            "<li><a href='/p/mull-vase'>Mull vase &pound;44</a></li>"
            "</ul></main>")
    return page(LISTING_URL, html_doc(title="Tableware | Marchmont",
                                      canonical=LISTING_URL, body=body))


COLLECTION_ORIGIN = "https://www.stanmere-outdoors.example"
COLLECTION_URL = COLLECTION_ORIGIN + "/collections/winter-kit"

COLLECTION_LD = """<script type="application/ld+json">
{"@context":"https://schema.org","@type":"CollectionPage","name":"Winter kit"}
</script>"""


def multi_product_collection_page() -> dict:
    body = ("<main><h1>Winter kit</h1><p>What our guides carry from November.</p>"
            "<ol><li><a href='/products/down-jacket'>Down jacket</a> &mdash; &pound;240</li>"
            "<li><a href='/products/wool-base'>Wool base layer</a> &mdash; &pound;65</li>"
            "<li><a href='/products/gaiters'>Gaiters</a> &mdash; &pound;40</li></ol></main>")
    return page(COLLECTION_URL, html_doc(title="Winter kit | Stanmere",
                                         canonical=COLLECTION_URL,
                                         head=COLLECTION_LD, body=body))


PROMO_ORIGIN = "https://www.havenbrook-beauty.example"
PROMO_URL = PROMO_ORIGIN + "/autumn-edit"


def promotional_page_with_prices() -> dict:
    body = ("<header><nav><a href='/'>Home</a></nav>"
            "<form action='/cart'><button>Bag</button></form></header>"
            "<main><h1>The autumn edit</h1>"
            "<p>Two weeks only. Balms &pound;16, oils &pound;28, sets &pound;54, "
            "refills &pound;11, gift boxes &pound;72.</p></main>")
    return page(PROMO_URL, html_doc(title="The autumn edit | Havenbrook",
                                    canonical=PROMO_URL, body=body))


AMBIGUOUS_ORIGIN = "https://www.pentlow-goods.example"
AMBIGUOUS_URL = AMBIGUOUS_ORIGIN + "/made-to-order"


def ambiguous_landing_page() -> dict:
    """Product vocabulary, a price, one heading, a link to a product.

    Nothing here fixes the identity of an item, and nothing here presents a
    set. It is neither, and the classifier is expected to say so.
    """
    body = ("<header><nav><a href='/'>Home</a></nav>"
            "<form action='/cart'><button>Cart</button></form></header>"
            "<main><h1>Made to order</h1>"
            "<p>Every piece is built to order. Add to cart and we start work; "
            "lead times run to eight weeks. Deposits from &pound;150.</p>"
            "<a href='/products/enquiry'>Start an order</a></main>")
    return page(AMBIGUOUS_URL, html_doc(title="Made to order | Pentlow",
                                        canonical=AMBIGUOUS_URL, body=body))


RAIL_URL = "https://www.ashgrove-appliances.example/products/gas-hob-60"


def detail_page_with_a_priced_rail(url: str = RAIL_URL) -> dict:
    """A product detail page that also shows five priced related items.

    No reader would call this a listing, and no listing rule should. It is
    here because it is the shape that reached a live report: an item-shaped
    URL and one subject, but enough prices on the page that "presents a set"
    was assumed, after which it was asked why it published no filters.
    """
    rail = "".join(f"<li><a href='/products/hob-{n}'>Hob {n} &pound;{p}</a></li>"
                   for n, p in (("60", 349), ("70", 429), ("80", 519),
                                ("90", 629), ("induction", 749)))
    return page(url, html_doc(
        title="Ashgrove 60cm gas hob", canonical=url,
        body=("<header><nav><a href='/'>Home</a></nav>"
              "<form action='/cart'><button>Bag</button></form></header>"
              "<main><h2>Ashgrove 60cm gas hob</h2><p>&pound;349.00, in stock.</p>"
              f"<h3>Other hobs</h3><ul>{rail}</ul></main>")))


def storefront_home(origin: str) -> dict:
    return page(origin + "/", html_doc(
        title="Shop", canonical=origin + "/",
        body="<h1>Shop</h1><a href='/category/tableware'>Tableware</a>"))


# ---------------------------------------------------------------------------
# 1 + 2. category-only rules never see a product page
# ---------------------------------------------------------------------------

class TestListingRulesNeverSampleAProductPage(unittest.TestCase):
    """The reported defect, as behaviour.

    The bundle carries one real listing with neither filtering nor sorting, so
    both rules genuinely fire - a test in which they stay silent would pass for
    the wrong reason. It also carries product pages, which have no filters and
    no sorting either, because they are not listings. The assertion is that the
    findings are about the listing and only the listing.
    """

    def setUp(self):
        # Nine entries: a set large enough that sorting and filtering are
        # affordances the listing can be expected to offer.
        listing = page(LISTING_URL, html_doc(
            title="Tableware | Marchmont", canonical=LISTING_URL,
            body="<main><h1>Tableware</h1><ul>"
                 "<li><a href='/p/rye-bowl'>Rye bowl &pound;22</a></li>"
                 "<li><a href='/p/rye-plate'>Rye plate &pound;18</a></li>"
                 "<li><a href='/p/heath-mug'>Heath mug &pound;14</a></li>"
                 "<li><a href='/p/heath-jug'>Heath jug &pound;36</a></li>"
                 "<li><a href='/p/coll-platter'>Coll platter &pound;58</a></li>"
                 "<li><a href='/p/coll-bowl'>Coll bowl &pound;24</a></li>"
                 "<li><a href='/p/skye-cup'>Skye cup &pound;12</a></li>"
                 "<li><a href='/p/skye-saucer'>Skye saucer &pound;9</a></li>"
                 "<li><a href='/p/mull-vase'>Mull vase &pound;44</a></li>"
                 "</ul></main>"))
        self.listing_url = listing["url"]
        self.products = [product_detail_page(), product_detail_page(ORIGIN),
                         detail_page_with_a_priced_rail()]
        self.product_urls = {p["url"] for p in self.products}
        self.bundle = bundle([storefront_home(LISTING_ORIGIN), listing] + self.products,
                             origin=LISTING_ORIGIN)
        self.findings = run("engagement-audit", self.bundle)

    def _finding(self, rule_id: str):
        found = find(self.findings, rule_id)
        self.assertIsNotNone(found, f"{rule_id} did not fire; the fixture no longer "
                                    "exercises the rule this test is about")
        return found

    def test_a_product_page_never_enters_the_filter_check(self):
        found = self._finding("EG-FILTER-CONTROLS-ABSENT")
        cited = set(found.affected_urls) | {i.url for i in found.evidence_items if i.url}
        self.assertEqual(cited & self.product_urls, set(),
                         f"a product page was asked why it has no filters: {found.evidence}")
        self.assertIn(self.listing_url, found.affected_urls)

    def test_a_product_page_never_enters_the_sort_check(self):
        found = self._finding("EG-SORT-CONTROLS-ABSENT")
        cited = set(found.affected_urls) | {i.url for i in found.evidence_items if i.url}
        self.assertEqual(cited & self.product_urls, set(),
                         f"a product page was asked why it has no sorting: {found.evidence}")
        self.assertIn(self.listing_url, found.affected_urls)

    def test_the_counts_are_over_listings_only(self):
        """A ratio computed over the wrong population is wrong even when the
        URLs it names are right."""
        for rule_id in ("EG-FILTER-CONTROLS-ABSENT", "EG-SORT-CONTROLS-ABSENT"):
            with self.subTest(rule=rule_id):
                metrics = self._finding(rule_id).metrics or {}
                self.assertEqual(metrics.get("sampled"), 1,
                                 "sampled should be the one listing, not the whole crawl")

    def test_a_bundle_of_only_product_pages_produces_no_listing_findings(self):
        """With no listing to audit, the listing rules have nothing to say."""
        only_products = bundle([storefront_home(PDP_ORIGIN)] + self.products,
                               origin=PDP_ORIGIN)
        ids = rule_ids(run("engagement-audit", only_products))
        self.assertNotIn("EG-FILTER-CONTROLS-ABSENT", ids)
        self.assertNotIn("EG-SORT-CONTROLS-ABSENT", ids)


# ---------------------------------------------------------------------------
# 3. downstream specialists consume the canonical classification
# ---------------------------------------------------------------------------

class TestSpecialistsConsumeTheCanonicalPageType(unittest.TestCase):
    """The same bytes, classified two ways, audited two ways.

    This is the behavioural form of "downstream consumes the shared
    classification". One page, unchanged, is stamped `category` in one bundle
    and `product` in another. If the rules read the canonical value, the
    listing rules follow the stamp; if any of them re-derives a type from the
    page's own content, the two runs come out the same and this fails.
    """

    def _bundle_with(self, page_type: str) -> dict:
        subject = product_listing_page()
        subject["page_type"] = page_type
        home = storefront_home(LISTING_ORIGIN)
        return bundle([home, subject], origin=LISTING_ORIGIN)

    def test_listing_rules_follow_the_stamp_not_the_content(self):
        as_category = rule_ids(run("engagement-audit", self._bundle_with("category")))
        as_product = rule_ids(run("engagement-audit", self._bundle_with("product")))
        self.assertIn("EG-FILTER-CONTROLS-ABSENT", as_category)
        self.assertNotIn("EG-FILTER-CONTROLS-ABSENT", as_product)

    def test_product_rules_follow_the_stamp_too(self):
        as_product = rule_ids(run("machine-readability-audit", self._bundle_with("product")))
        as_category = rule_ids(run("machine-readability-audit", self._bundle_with("category")))
        self.assertIn("MR-PRODUCT-SCHEMA-MISSING", as_product)
        self.assertNotIn("MR-PRODUCT-SCHEMA-MISSING", as_category)

    def test_the_funnels_are_complementary(self):
        """No page is ever both a product and a listing, whatever it contains."""
        data = bundle([storefront_home(LISTING_ORIGIN), product_detail_page(),
                       product_listing_page(), multi_product_collection_page(),
                       promotional_page_with_prices(), ambiguous_landing_page()],
                      origin=LISTING_ORIGIN)
        products = {p["url"] for p in ev.product_pages(data)}
        listings = {p["url"] for p in ev.category_pages(data)}
        self.assertEqual(products & listings, set())
        self.assertIn(PDP_URL, products)
        self.assertIn(LISTING_URL, listings)

    def test_every_specialist_agrees_with_the_bundle_about_every_url(self):
        """No finding may describe a URL as a page type the bundle does not.

        The report builder already rejects a finding whose `sample_unit` names
        a type its citations are not. This is the same invariant checked from
        the other end, across all six specialists at once.
        """
        data = bundle([storefront_home(LISTING_ORIGIN), product_detail_page(),
                       product_listing_page(), multi_product_collection_page(),
                       promotional_page_with_prices(), ambiguous_landing_page()],
                      origin=LISTING_ORIGIN)
        types = {p["url"]: p.get("page_type") for p in data["pages"]}
        skills = ("crawl-render-audit", "machine-readability-audit",
                  "freshness-corroboration", "entity-audit", "engagement-audit",
                  "answerability-audit")
        for skill in skills:
            for item in run(skill, data):
                unit = str((item.metrics or {}).get("sample_unit") or "").lower()
                for keyword, expected in (("product page", "product"),
                                          ("category page", "category"),
                                          ("listing", "category")):
                    if keyword not in unit:
                        continue
                    for url in item.affected_urls:
                        if url not in types:
                            continue
                        with self.subTest(skill=skill, rule=item.rule_id, url=url):
                            self.assertEqual(types[url], expected)


# ---------------------------------------------------------------------------
# 4. ambiguity is not promoted
# ---------------------------------------------------------------------------

class TestAmbiguityIsNotPromoted(unittest.TestCase):
    """Neither type is assigned on partial evidence - in either direction.

    Promotion to `product` was the first three false positives. Promotion to
    `category` is the same mistake wearing the other hat, and it is what put a
    detail page into the filter and sort checks: the page showed several
    prices, nothing said it was one item, and "listing" was assumed.
    """

    def test_an_ambiguous_landing_page_becomes_neither(self):
        facts = ambiguous_landing_page()
        self.assertEqual(facts["page_type"], "other")

    def test_a_promotional_page_of_prices_is_not_a_product(self):
        self.assertNotEqual(promotional_page_with_prices()["page_type"], "product")

    def test_a_detail_page_that_also_looks_plural_is_neither(self):
        """The shape that produced the report this suite was written for.

        A product page with a related-items rail: an item-shaped URL says one
        thing, six prices say another, and the markup names nothing. Both
        readings have support, so neither type is assigned - which is what
        keeps it out of both the product checks and the listing checks.
        """
        rail = "".join(
            f"<li><a href='/products/hob-{n}'>Hob {n} &pound;{p}</a></li>"
            for n, p in (("60", 349), ("70", 429), ("80", 519),
                         ("90", 629), ("induction", 749)))
        url = "https://www.ashgrove-appliances.example/products/gas-hob-60"
        facts = page(url, html_doc(
            title="Ashgrove 60cm gas hob", canonical=url,
            body=("<header><nav><a href='/'>Home</a></nav>"
                  "<form action='/cart'><button>Bag</button></form></header>"
                  "<main><h2>Ashgrove 60cm gas hob</h2><p>&pound;349.00, in stock.</p>"
                  f"<h3>Other hobs</h3><ul>{rail}</ul></main>")))
        self.assertEqual(facts["page_type"], "other")

        from aiva.extract import product_evidence
        verdict = product_evidence(url, facts)
        self.assertEqual(verdict["verdict"], "uncertain")
        self.assertTrue(verdict["anchors"] and verdict["plural"],
                        "the fixture should exercise the conflict, not a blank page")
        self.assertTrue(verdict["conflict"])

    def test_item_scoped_evidence_settles_the_conflict(self):
        """Conservative is not the same as silent.

        The same page as above, plus a specification table. A heading, a price
        and a URL fit a catalogue index as well as a detail page, but the
        dimensions of one appliance do not: a page presenting a set does not
        publish the width and burner count of one of them. So this resolves to
        a product, and a whole catalogue of pages like it is audited instead of
        being filed under "unknown" for showing its related items with prices.
        """
        rail = "".join(
            f"<li><a href='/products/hob-{n}'>Hob {n} &pound;{p}</a></li>"
            for n, p in (("70", 429), ("80", 519), ("90", 629), ("induction", 749)))
        url = "https://www.ashgrove-appliances.example/products/gas-hob-60"
        facts = page(url, html_doc(
            title="Ashgrove 60cm gas hob", canonical=url,
            body=("<main><h2>Ashgrove 60cm gas hob</h2><p>&pound;349.00, in stock.</p>"
                  "<table><tr><th>Width</th><td>60 cm</td></tr>"
                  "<tr><th>Burners</th><td>4</td></tr></table>"
                  f"<h3>Other hobs</h3><ul>{rail}</ul></main>")))
        self.assertEqual(facts["page_type"], "product")

    def test_page_scoped_evidence_does_not_settle_it(self):
        """And the control: more of the ambiguous kind of evidence is not more
        evidence. A second heading and another price still describe a page,
        not an item."""
        rail = "".join(
            f"<li><a href='/products/hob-{n}'>Hob {n} &pound;{p}</a></li>"
            for n, p in (("70", 429), ("80", 519), ("90", 629), ("induction", 749)))
        url = "https://www.ashgrove-appliances.example/products/hob-range"
        facts = page(url, html_doc(
            title="Ashgrove hobs", canonical=url,
            body=("<main><h1>Ashgrove hobs</h1><p>From &pound;349.00.</p>"
                  f"<ul>{rail}</ul></main>")))
        self.assertNotEqual(facts["page_type"], "product")

    def test_and_the_same_page_with_its_identity_declared_is_a_product(self):
        """Detection survives: the conflict is resolved by the markup.

        Not a weakening of the rule but the point of it - a page that names
        its subject, and whose heading names the same subject, is a product
        page however many related items it lists.
        """
        rail = "".join(
            f"<li><a href='/products/hob-{n}'>Hob {n} &pound;{p}</a></li>"
            for n, p in (("70", 429), ("80", 519), ("90", 629), ("induction", 749)))
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"Product",'
                '"name":"Ashgrove 60cm gas hob","sku":"AG-60",'
                '"offers":{"@type":"Offer","price":"349","priceCurrency":"GBP"}}</script>')
        url = "https://www.ashgrove-appliances.example/products/gas-hob-60"
        facts = page(url, html_doc(
            title="Ashgrove 60cm gas hob", canonical=url, head=head,
            body=("<main><h1>Ashgrove 60cm gas hob</h1><p>&pound;349.00, in stock.</p>"
                  f"<h3>Other hobs</h3><ul>{rail}</ul></main>")))
        self.assertEqual(facts["page_type"], "product")

    def test_an_unpromoted_page_is_audited_as_neither(self):
        """And the consequence, which is the reason any of this matters."""
        data = bundle([storefront_home(AMBIGUOUS_ORIGIN), ambiguous_landing_page()],
                      origin=AMBIGUOUS_ORIGIN)
        self.assertEqual(ev.product_pages(data), [])
        self.assertEqual(ev.category_pages(data), [])
        ids = rule_ids(run("engagement-audit", data))
        for rule_id in ("EG-FILTER-CONTROLS-ABSENT", "EG-SORT-CONTROLS-ABSENT"):
            self.assertNotIn(rule_id, ids)


# ---------------------------------------------------------------------------
# 5. a missing home-page link is not an unreachable catalogue
# ---------------------------------------------------------------------------

CATALOGUE_ORIGIN = "https://www.brackenfield-supply.example"


def _sitemap(origin: str, urls) -> list:
    return [{"url": origin + "/sitemap.xml", "source": "robots.txt Sitemap directive",
             "status": 200, "kind": "urlset", "error": None, "url_count": len(urls),
             "child_count": 0, "lastmods": [], "sample_urls": list(urls)[:2],
             "entries": [{"url": u, "lastmod": None} for u in urls]}]


def _brochure_home(origin: str) -> dict:
    """A home page that links only to non-catalogue pages."""
    return page(origin + "/", html_doc(
        title="Brackenfield Supply", canonical=origin + "/",
        body="<h1>Brackenfield Supply</h1><p>Trade tools since 1974.</p>"
             "<form action='/cart'><button>Cart</button></form>"
             "<a href='/about.html'>About us</a>"
             "<a href='/pages/contact'>Contact</a>"
             "<a href='/blog/2026-catalogue'>The 2026 catalogue is out</a>"))


class TestHomePageLinkingIsNotAnUnreachabilityClaim(unittest.TestCase):
    """"Not linked from the home page" and "unreachable" are different claims.

    The crawl that reports the first has usually just disproved the second: it
    found the catalogue through the sitemap. A finding that says the catalogue
    cannot be reached, in a report listing the pages it reached, teaches a
    reader to discount the whole document.
    """

    RULE = "CR-COMMERCE-NOT-LINKED-FROM-HOME"

    def _run(self, pages, sitemap_urls):
        data = bundle(pages, sitemaps=_sitemap(CATALOGUE_ORIGIN, sitemap_urls),
                      origin=CATALOGUE_ORIGIN)
        return find(run("crawl-render-audit", data), self.RULE)

    def test_the_finding_still_fires_when_the_home_page_does_not_link_out(self):
        product = product_detail_page(CATALOGUE_ORIGIN)
        found = self._run([_brochure_home(CATALOGUE_ORIGIN), product],
                          [CATALOGUE_ORIGIN + "/", product["url"]])
        self.assertIsNotNone(found, "the finding must still be raised")

    def test_it_does_not_claim_the_catalogue_is_unreachable(self):
        product = product_detail_page(CATALOGUE_ORIGIN)
        found = self._run([_brochure_home(CATALOGUE_ORIGIN), product],
                          [CATALOGUE_ORIGIN + "/", product["url"]])
        text = f"{found.title} {found.evidence}".lower()
        for overclaim in ("cannot reach", "unreachable", "is not reachable",
                          "no way to reach"):
            self.assertNotIn(overclaim, text,
                             f"claims unreachability while citing a page it reached: {text}")

    def test_it_says_which_path_did_reach_the_catalogue(self):
        product = product_detail_page(CATALOGUE_ORIGIN)
        found = self._run([_brochure_home(CATALOGUE_ORIGIN), product],
                          [CATALOGUE_ORIGIN + "/", product["url"]])
        self.assertIn("sitemap", found.evidence.lower())
        self.assertEqual(found.metrics.get("catalogue_pages_reached"), 1)
        self.assertEqual(found.severity, "medium")

    def test_the_stronger_claim_survives_when_nothing_reached_the_catalogue(self):
        """The rule must not become toothless: with no catalogue page found by
        any path, the serious reading is the right one."""
        found = self._run([_brochure_home(CATALOGUE_ORIGIN)], [CATALOGUE_ORIGIN + "/"])
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "high")
        self.assertIn("any other discovery path", found.evidence.lower())

    def test_even_then_the_claim_is_scoped_to_what_the_audit_could_see(self):
        """A crawl budget, a bot wall and a genuinely unreachable catalogue
        look alike from here, and the finding says so instead of asserting an
        outage."""
        found = self._run([_brochure_home(CATALOGUE_ORIGIN)], [CATALOGUE_ORIGIN + "/"])
        self.assertIn("this audit", found.evidence.lower())
        self.assertIn("confirm", found.interpretation.lower())

    def test_a_catalogue_linked_from_another_page_is_reported_as_indirect(self):
        """The second way the strong claim is wrong: links do work, one hop
        further along."""
        product = product_detail_page(CATALOGUE_ORIGIN)
        hub = page(CATALOGUE_ORIGIN + "/blog/2026-catalogue", html_doc(
            title="The 2026 catalogue", canonical=CATALOGUE_ORIGIN + "/blog/2026-catalogue",
            body=f"<main><h1>The 2026 catalogue is out</h1>"
                 f"<a href='{product['url']}'>Bench vice 150mm</a></main>"))
        found = self._run([_brochure_home(CATALOGUE_ORIGIN), hub, product],
                          [CATALOGUE_ORIGIN + "/"])
        self.assertEqual(found.severity, "medium")
        self.assertIn("a link on another page", found.metrics.get("discovery_channels", []))

    def test_the_home_page_linking_directly_says_nothing_at_all(self):
        """The negative case: a home page that does link to the catalogue must
        not produce this finding in any wording."""
        product = product_detail_page(CATALOGUE_ORIGIN)
        home = page(CATALOGUE_ORIGIN + "/", html_doc(
            title="Brackenfield Supply", canonical=CATALOGUE_ORIGIN + "/",
            body=f"<h1>Brackenfield Supply</h1>"
                 f"<a href='{product['url']}'>Bench vice 150mm</a>"))
        self.assertIsNone(self._run([home, product], [CATALOGUE_ORIGIN + "/"]))


if __name__ == "__main__":
    unittest.main()
