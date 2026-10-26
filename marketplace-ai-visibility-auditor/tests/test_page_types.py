"""Page-type classification, as a general property rather than a site fix.

Every false positive this auditor has shipped had the same shape: a page that
carries product-*like* information - a price, a cart control, a `Product`
token, `/shop/` in its URL - was read as *being* one product. That is a
cardinality error, not a vocabulary error, so the fix is not another word list
and the regression suite is not another site.

The pages below are ordinary HTML from six unrelated synthetic domains,
extracted by the real extractor and classified by the real classifier. They
cover the taxonomy the classifier has to separate:

1. an individual product detail page - one entity, unambiguous identity;
2. a multi-product shopping page - tiles and prices, no listing markup at all;
3. a product category page - the same, declared;
4. a collection page - a curated set;
5. a promotional landing page that quotes product prices;
6. a page that is genuinely ambiguous, where the answer is "not a product".

The Apple `/us/shop/goto/*` routes appear as one fixture among these, not as a
rule: nothing in the classifier knows what apple.com is, and the assertion
that matters is the general one directly above it.
"""

from __future__ import annotations

import unittest

from helpers import bundle, html_doc, page, run
from aiva import evidence as ev
from aiva.extract import classify_page, product_evidence


# ---------------------------------------------------------------------------
# 1. an individual product detail page - Harrowgate Audio
# ---------------------------------------------------------------------------

PDP_ORIGIN = "https://www.harrowgate-audio.example"
PDP_URL = PDP_ORIGIN + "/products/hg-300-open-back-headphones"

PDP_LD = """<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"HG-300 open-back headphones","sku":"HG-300","mpn":"HG300-2026",
 "brand":{"@type":"Brand","name":"Harrowgate"},
 "description":"Open-back reference headphones, 300 ohm.",
 "image":"/img/hg-300.jpg",
 "additionalProperty":[{"@type":"PropertyValue","name":"Impedance","value":"300 ohm"}],
 "offers":{"@type":"Offer","price":"429","priceCurrency":"GBP",
           "availability":"https://schema.org/InStock"}}
</script>"""

PDP_BODY = """
<header><nav><a href="/">Home</a><a href="/headphones">Headphones</a></nav>
  <form action="/cart"><button>Bag</button></form></header>
<main>
  <nav aria-label="breadcrumb"><a href="/">Home</a> / <a href="/headphones">Headphones</a>
    / HG-300</nav>
  <h1>HG-300 open-back headphones</h1>
  <p><strong>&pound;429.00</strong> &mdash; in stock, ships in two days.</p>
  <label>Cable <select name="variant"><option>1.5 m</option><option>3 m</option></select></label>
  <form action="/cart/add"><button type="submit">Add to bag</button></form>
  <h2>Specifications</h2>
  <table>
    <tr><th>Impedance</th><td>300 ohm</td></tr>
    <tr><th>Driver</th><td>50 mm dynamic</td></tr>
    <tr><th>Weight</th><td>330 g</td></tr>
  </table>
  <h2>You may also like</h2>
  <ul>
    <li><a href="/products/hg-100-closed-back">HG-100 closed back</a></li>
    <li><a href="/products/hg-arm-stand">HG arm stand</a></li>
    <li><a href="/products/hg-cable-3m">HG 3 m cable</a></li>
    <li><a href="/products/hg-pads-velour">HG velour pads</a></li>
    <li><a href="/products/hg-case">HG carry case</a></li>
    <li><a href="/products/hg-dac-one">HG DAC One</a></li>
  </ul>
</main>
"""


def product_detail_page() -> dict:
    return page(PDP_URL, html_doc(title="HG-300 open-back headphones | Harrowgate",
                                  canonical=PDP_URL, head=PDP_LD, body=PDP_BODY))


# ---------------------------------------------------------------------------
# 2. a multi-product shopping page with no listing markup - Northfield Bikes
# ---------------------------------------------------------------------------

SHOP_ORIGIN = "https://www.northfield-bikes.example"
SHOP_URL = SHOP_ORIGIN + "/shop/bikes"

SHOP_BODY = """
<header><nav><a href="/">Home</a></nav><form action="/cart"><button>Cart</button></form></header>
<main>
  <h1>Shop bikes</h1>
  <p>Every Northfield frame, built in Sheffield.</p>
  <label>Sort <select name="sort_by"><option>Price</option><option>Newest</option></select></label>
  <ul>
    <li><a href="/products/harrier-1">Harrier 1 &mdash; &pound;899</a></li>
    <li><a href="/products/harrier-2">Harrier 2 &mdash; &pound;1,099</a></li>
    <li><a href="/products/kestrel-gravel">Kestrel Gravel &mdash; &pound;1,449</a></li>
    <li><a href="/products/pennine-tourer">Pennine Tourer &mdash; &pound;1,299</a></li>
    <li><a href="/products/city-one">City One &mdash; &pound;649</a></li>
    <li><a href="/products/city-two">City Two &mdash; &pound;749</a></li>
  </ul>
</main>
"""


def multi_product_shopping_page() -> dict:
    return page(SHOP_URL, html_doc(title="Shop bikes | Northfield",
                                   canonical=SHOP_URL, body=SHOP_BODY))


# ---------------------------------------------------------------------------
# 3. a product category page - Verdant Garden
# ---------------------------------------------------------------------------

CATEGORY_ORIGIN = "https://www.verdant-garden.example"
CATEGORY_URL = CATEGORY_ORIGIN + "/category/planters"

CATEGORY_LD = """<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
  {"@type":"Product","name":"Ridge planter","offers":{"@type":"Offer","price":"39"}},
  {"@type":"Product","name":"Hollow planter","offers":{"@type":"Offer","price":"45"}},
  {"@type":"Product","name":"Tallow planter","offers":{"@type":"Offer","price":"52"}}]}
</script>"""

CATEGORY_BODY = """
<main>
  <h1>Planters</h1>
  <label>Material <select name="filter_material"><option>Terracotta</option></select></label>
  <label>Sort <select name="sort"><option>Price low to high</option></select></label>
  <ul>
    <li><a href="/p/ridge-planter">Ridge planter &euro;39</a></li>
    <li><a href="/p/hollow-planter">Hollow planter &euro;45</a></li>
    <li><a href="/p/tallow-planter">Tallow planter &euro;52</a></li>
    <li><a href="/p/burnt-planter">Burnt planter &euro;61</a></li>
    <li><a href="/p/wide-planter">Wide planter &euro;74</a></li>
  </ul>
</main>
"""


def product_category_page() -> dict:
    return page(CATEGORY_URL, html_doc(title="Planters | Verdant",
                                       canonical=CATEGORY_URL,
                                       head=CATEGORY_LD, body=CATEGORY_BODY))


# ---------------------------------------------------------------------------
# 4. a curated collection page - Paperlane Books
# ---------------------------------------------------------------------------

COLLECTION_ORIGIN = "https://www.paperlane-books.example"
COLLECTION_URL = COLLECTION_ORIGIN + "/collections/autumn-reading"

COLLECTION_LD = """<script type="application/ld+json">
{"@context":"https://schema.org","@type":"CollectionPage",
 "name":"Autumn reading","url":"/collections/autumn-reading"}
</script>"""

COLLECTION_BODY = """
<main>
  <h1>Autumn reading</h1>
  <p>Twelve books our booksellers are pressing on everyone this month.</p>
  <ol>
    <li><a href="/books/the-long-field">The Long Field</a> &mdash; &pound;10.99</li>
    <li><a href="/books/winter-papers">Winter Papers</a> &mdash; &pound;14.00</li>
    <li><a href="/books/salt-houses">Salt Houses</a> &mdash; &pound;9.99</li>
  </ol>
</main>
"""


def collection_page() -> dict:
    return page(COLLECTION_URL, html_doc(title="Autumn reading | Paperlane",
                                         canonical=COLLECTION_URL,
                                         head=COLLECTION_LD, body=COLLECTION_BODY))


# ---------------------------------------------------------------------------
# 5. a promotional landing page carrying product prices - Lumen Cosmetics
# ---------------------------------------------------------------------------

PROMO_ORIGIN = "https://www.lumen-cosmetics.example"
PROMO_URL = PROMO_ORIGIN + "/spring-event"

PROMO_BODY = """
<header><nav><a href="/">Home</a></nav><form action="/cart"><button>Bag</button></form></header>
<main>
  <h1>The spring event</h1>
  <p>Three weeks only. Free delivery over &pound;30.</p>
  <p>Serums from &pound;24. Cleansers from &pound;18. Sets from &pound;55.
     Gift boxes &pound;40. Refills &pound;12.</p>
  <p><a href="/shop">Shop the event</a></p>
</main>
"""


def promotional_landing_page() -> dict:
    return page(PROMO_URL, html_doc(title="The spring event | Lumen",
                                    canonical=PROMO_URL, body=PROMO_BODY))


# ---------------------------------------------------------------------------
# 6. a genuinely ambiguous product-like page - Tilden Outfitters
# ---------------------------------------------------------------------------

AMBIGUOUS_ORIGIN = "https://www.tilden-outfitters.example"
AMBIGUOUS_URL = AMBIGUOUS_ORIGIN + "/gift-guide"

AMBIGUOUS_BODY = """
<header><nav><a href="/">Home</a></nav><form action="/cart"><button>Cart</button></form></header>
<main>
  <h1>The Tilden gift guide</h1>
  <p>A gift card starts at &pound;25 and never expires.</p>
  <p>Waxed cotton, wool and leather, made to last. Free returns for 60 days.</p>
  <a href="/products/gift-card">Buy a gift card</a>
</main>
"""


def ambiguous_page() -> dict:
    return page(AMBIGUOUS_URL, html_doc(title="Gift guide | Tilden",
                                        canonical=AMBIGUOUS_URL, body=AMBIGUOUS_BODY))


# ---------------------------------------------------------------------------
# 7. a storefront buying landing page under a /shop/ route - Orchard Devices
# ---------------------------------------------------------------------------

BUYING_ORIGIN = "https://www.orchard-devices.example"
BUYING_URL = BUYING_ORIGIN + "/uk/shop/goto/buy_handset"

BUYING_BODY = """
<header><nav><a href="/">Home</a></nav><form action="/cart"><button>Bag</button></form></header>
<main>
  <h1>Buy a handset</h1>
  <p>Choose a model. Trade in and save. Pay monthly at 0% APR.</p>
  <ul>
    <li><a href="/uk/shop/goto/handset/orb-9">Orb 9 &mdash; from &pound;799</a></li>
    <li><a href="/uk/shop/goto/handset/orb-9-pro">Orb 9 Pro &mdash; from &pound;999</a></li>
    <li><a href="/uk/shop/goto/handset/orb-8">Orb 8 &mdash; from &pound;599</a></li>
    <li><a href="/uk/shop/goto/handset/orb-mini">Orb Mini &mdash; from &pound;499</a></li>
    <li><a href="/uk/shop/goto/handset/orb-se">Orb SE &mdash; from &pound;399</a></li>
  </ul>
</main>
"""


def buying_landing_page() -> dict:
    return page(BUYING_URL, html_doc(title="Buy a handset | Orchard",
                                     canonical=BUYING_URL, body=BUYING_BODY))


# ---------------------------------------------------------------------------
# 8. a small category page at a URL that says nothing - Kilnbrook Clothing
# ---------------------------------------------------------------------------
#
# The hard case for a rule built on affordance counting: three items is few
# enough that the page shows one heading and only three prices, and the size
# filter every clothing listing carries is the same `<select>` a detail page
# uses for its sizes. Under a rule of "a price plus one more affordance,
# singular, money in the content" this page is an individual product, and the
# URL offers nothing to correct it.

SMALL_CATEGORY_ORIGIN = "https://www.kilnbrook-clothing.example"
SMALL_CATEGORY_URL = SMALL_CATEGORY_ORIGIN + "/womens/jackets"

SMALL_CATEGORY_LD = """<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
  {"@type":"Product","name":"Marle jacket"},
  {"@type":"Product","name":"Ferrier jacket"},
  {"@type":"Product","name":"Ossett jacket"}]}
</script>"""

SMALL_CATEGORY_BODY = """
<main>
  <h1>Jackets</h1>
  <label>Size <select name="size"><option>8</option><option>10</option></select></label>
  <ul>
    <li><a href="/products/marle-jacket">Marle jacket &pound;180</a></li>
    <li><a href="/products/ferrier-jacket">Ferrier jacket &pound;240</a></li>
    <li><a href="/products/ossett-jacket">Ossett jacket &pound;165</a></li>
  </ul>
</main>
"""


def small_category_page() -> dict:
    return page(SMALL_CATEGORY_URL, html_doc(title="Jackets | Kilnbrook",
                                             canonical=SMALL_CATEGORY_URL,
                                             head=SMALL_CATEGORY_LD,
                                             body=SMALL_CATEGORY_BODY))


# ---------------------------------------------------------------------------
# 9. a comparison page - Pellow Cycles
# ---------------------------------------------------------------------------
#
# Two products' prices, two products' specifications, one heading, no hub
# word in the title, money in the content region. Everything a detail page
# has except an item: the page is *about* the difference between two things.

COMPARE_ORIGIN = "https://www.pellow-cycles.example"
COMPARE_URL = COMPARE_ORIGIN + "/harrier-1-or-harrier-2"

COMPARE_BODY = """
<main>
  <h1>Harrier 1 or Harrier 2</h1>
  <p>The Harrier 1 is &pound;899 and the Harrier 2 is &pound;1,099.</p>
  <table>
    <tr><th>Frame</th><td>6061 alloy</td><td>Reynolds 725</td></tr>
    <tr><th>Weight</th><td>11.2 kg</td><td>10.1 kg</td></tr>
    <tr><th>Gears</th><td>9 speed</td><td>11 speed</td></tr>
  </table>
  <p>Both are in stock in every size.</p>
</main>
"""


def comparison_page() -> dict:
    return page(COMPARE_URL, html_doc(title="Harrier 1 or Harrier 2 | Pellow",
                                      canonical=COMPARE_URL, body=COMPARE_BODY))


# ---------------------------------------------------------------------------
# 10. a priced service page - Pellow Cycles
# ---------------------------------------------------------------------------

SERVICE_URL = COMPARE_ORIGIN + "/bike-fitting"

SERVICE_BODY = """
<main>
  <h1>Bike fitting at Pellow</h1>
  <p>A two-hour session with a fitter. &pound;75, redeemable against a frame.</p>
  <label>Store <select name="variant"><option>Sheffield</option><option>Leeds</option></select></label>
  <p>Sessions run Thursday to Sunday.</p>
</main>
"""


def priced_service_page() -> dict:
    return page(SERVICE_URL, html_doc(title="Bike fitting | Pellow",
                                      canonical=SERVICE_URL, body=SERVICE_BODY))


NON_PRODUCT_FIXTURES = {
    "multi-product shopping page": multi_product_shopping_page,
    "product category page": product_category_page,
    "collection page": collection_page,
    "promotional landing page": promotional_landing_page,
    "ambiguous product-like page": ambiguous_page,
    "storefront buying landing page": buying_landing_page,
    "small category page at a plain URL": small_category_page,
    "comparison page": comparison_page,
    "priced service page": priced_service_page,
}


class TestTheTaxonomy(unittest.TestCase):
    """One assertion per category, on six unrelated synthetic domains."""

    def test_an_individual_product_page_is_a_product(self):
        facts = product_detail_page()
        self.assertEqual(facts["page_type"], "product")
        self.assertEqual(product_evidence(PDP_URL, facts)["verdict"], "individual")

    def test_none_of_the_others_is_an_individual_product(self):
        for label, build in NON_PRODUCT_FIXTURES.items():
            with self.subTest(page=label):
                facts = build()
                self.assertNotEqual(
                    facts["page_type"], "product",
                    f"a {label} was classified as an individual product: "
                    f"{product_evidence(facts['url'], facts)}")

    def test_the_sets_are_recognised_as_sets(self):
        """A page presenting several products is a listing, not merely unknown."""
        for label, build in (("multi-product shopping page", multi_product_shopping_page),
                             ("product category page", product_category_page),
                             ("collection page", collection_page),
                             ("small category page", small_category_page)):
            with self.subTest(page=label):
                self.assertEqual(build()["page_type"], "category")

    def test_a_page_about_two_products_is_about_neither(self):
        """The clearest statement of the cardinality rule.

        A comparison page has one heading, a specification table and money in
        its own content - every affordance a detail page has. What it does not
        have is an item, and no amount of product-like information supplies
        one.
        """
        self.assertNotEqual(comparison_page()["page_type"], "product")

    def test_a_priced_service_is_not_a_product(self):
        """A price and an option control are not an identity either."""
        self.assertNotEqual(priced_service_page()["page_type"], "product")

    def test_the_ambiguous_page_is_left_unknown_rather_than_guessed(self):
        """Conservative under uncertainty, stated as an outcome.

        The gift guide has product vocabulary, a price, an H1 and a link to a
        product. Not one of those fixes an identity, so the honest answer is
        that this page's type is not known - and `other` is the type that no
        product rule and no answerability question is allowed to sample.
        """
        facts = ambiguous_page()
        self.assertEqual(facts["page_type"], "other")
        self.assertEqual(product_evidence(AMBIGUOUS_URL, facts)["verdict"], "uncertain")


class TestNoIsolatedSignalDecides(unittest.TestCase):
    """The specific signals that must never, alone, produce a product page.

    Each case is a page carrying exactly one of them and nothing else that
    identifies an item. These are written against a URL with no hint of its
    own, so the signal under test is the only thing the classifier can read.
    """

    URL = "https://www.wren-supply.example/x/y-42"

    def _facts(self, body: str, head: str = "") -> dict:
        return page(self.URL, html_doc(title="Wren Supply", canonical=self.URL,
                                       head=head, body=body))

    def test_product_vocabulary_alone(self):
        body = ("<main><p>Shop our products. Add to cart. Buy now. In stock. "
                "Free delivery on every order.</p></main>")
        self.assertNotEqual(self._facts(body)["page_type"], "product")

    def test_a_price_alone(self):
        self.assertNotEqual(
            self._facts("<main><p>Delivery is &pound;4.95.</p></main>")["page_type"],
            "product")

    def test_a_heading_alone(self):
        self.assertNotEqual(
            self._facts("<main><h1>The Wren Mk II</h1></main>")["page_type"], "product")

    def test_product_links_alone(self):
        body = ("<main><h1>Our makers</h1>"
                + "".join(f'<a href="/products/item-{i}">Item {i}</a>' for i in range(9))
                + "</main>")
        self.assertNotEqual(self._facts(body)["page_type"], "product")

    def test_a_bare_product_schema_token_alone(self):
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"Product"}</script>')
        self.assertNotEqual(self._facts("<main><p>Hello.</p></main>", head)["page_type"],
                            "product")

    def test_shop_and_buy_in_the_url_alone(self):
        for url in ("https://www.wren-supply.example/shop/",
                    "https://www.wren-supply.example/buy/",
                    "https://www.wren-supply.example/shop/goto/anything",
                    "https://www.wren-supply.example/en/buy-online/"):
            with self.subTest(url=url):
                self.assertNotEqual(classify_page(url), "product")

    def test_two_of_them_together_still_need_an_anchor(self):
        """Two corroborators are not two independent signals about identity.

        A price and a specification table are both true of a comparison page,
        a shipping policy and a promotional hub. Something has to say *which*
        item the page is about before the rest of it counts.
        """
        body = ("<main><h1>How our jackets compare</h1>"
                "<p>From &pound;120.</p>"
                "<table><tr><th>Weight</th><td>420 g</td></tr>"
                "<tr><th>Fabric</th><td>Waxed cotton</td></tr></table></main>")
        self.assertNotEqual(self._facts(body)["page_type"], "product")


class TestDetectionSurvives(unittest.TestCase):
    """The other direction: the shapes a real product page comes in.

    A rule that is only ever tested for silence gets quieter every release
    until it says nothing at all. Each of these is a product detail page built
    differently, and each must still be found.
    """

    def test_a_page_whose_only_evidence_is_its_markup(self):
        """A JavaScript storefront: the server sends schema and little else."""
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"Product",'
                '"name":"Alder side table","sku":"ALD-01",'
                '"offers":{"@type":"Offer","price":"219","priceCurrency":"EUR"}}</script>')
        url = "https://www.fennel-home.example/item.php?id=7741"
        facts = page(url, html_doc(title="Alder side table", head=head,
                                   body="<main><h1>Alder side table</h1></main>"))
        self.assertEqual(facts["page_type"], "product")

    def test_a_page_with_no_markup_at_all(self):
        """A hand-built shop: a heading, a price and a buy button in the copy."""
        body = ("<header><nav><a href='/'>Home</a></nav></header>"
                "<main><h1>Copper kettle, 1.7 litre</h1>"
                "<p>&pound;58.00 &mdash; in stock.</p>"
                "<form action='/cart/add'><button>Add to basket</button></form>"
                "<table><tr><th>Capacity</th><td>1.7 l</td></tr></table></main>")
        url = "https://www.brasslane-kitchen.example/kettles/copper-17"
        facts = page(url, html_doc(title="Copper kettle", canonical=url, body=body))
        self.assertEqual(facts["page_type"], "product")

    def test_a_product_page_that_recommends_five_other_products(self):
        """A related-items rail is not a catalogue.

        Six item-shaped links sit in the fixture at the top of this module,
        which is what a detail page looks like on any large storefront.
        """
        self.assertEqual(product_detail_page()["page_type"], "product")

    def test_a_product_page_whose_related_rail_shows_prices(self):
        """The risk the plural signals themselves create.

        "Customers also bought" tiles carry prices, so counting priced links
        makes the busiest detail pages look like catalogues. The page's own
        markup names one entity and its heading repeats that name, and that
        agreement is what settles it.
        """
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"Product",'
                '"name":"Sirocco cast pan 26 cm","sku":"SIR-26",'
                '"offers":{"@type":"Offer","price":"89","priceCurrency":"GBP"}}</script>')
        rail = "".join(f'<li><a href="/products/sirocco-{n}">Sirocco {n} &pound;{p}</a></li>'
                       for n, p in (("20 cm", 69), ("24 cm", 79), ("28 cm", 99),
                                    ("30 cm", 109), ("lid", 25), ("trivet", 19)))
        body = (f"<main><h1>Sirocco cast pan 26 cm</h1><p>&pound;89.00, in stock.</p>"
                f"<form action='/cart/add'><button>Add to basket</button></form>"
                f"<h2>Complete the set</h2><ul>{rail}</ul></main>")
        url = "https://www.sirocco-cookware.example/products/cast-pan-26"
        facts = page(url, html_doc(title="Sirocco cast pan 26 cm", canonical=url,
                                   head=head, body=body))
        self.assertEqual(facts["page_type"], "product")

    def test_a_product_page_that_marks_up_its_related_items_as_an_itemlist(self):
        """`ItemList` is a container, not a statement about the document.

        A detail page carries one for its related items, its gallery or its
        reviews. Treating it as a declaration of "this page is a listing" made
        a page's own good markup the reason it stopped being a product page,
        while `CollectionPage` - which *is* a statement about the document -
        still settles the question outright.
        """
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@graph":['
                '{"@type":"Product","name":"Larch reading lamp","sku":"LRL-1",'
                ' "offers":{"@type":"Offer","price":"140","priceCurrency":"EUR"}},'
                '{"@type":"ItemList","name":"Related","itemListElement":['
                '{"@type":"ListItem","position":1,"url":"/products/larch-shade"},'
                '{"@type":"ListItem","position":2,"url":"/products/larch-bulb"}]}'
                ']}</script>')
        url = "https://www.thornbury-lighting.example/products/larch-reading-lamp"
        facts = page(url, html_doc(title="Larch reading lamp", canonical=url, head=head,
                                   body="<main><h1>Larch reading lamp</h1>"
                                        "<p>&euro;140.00, in stock.</p></main>"))
        self.assertEqual(facts["page_type"], "product")

    def test_but_a_declared_collection_page_still_settles_it(self):
        """The control for the case above."""
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"CollectionPage",'
                '"name":"Lamps"}</script>')
        url = "https://www.thornbury-lighting.example/products/lamps"
        facts = page(url, html_doc(title="Lamps", canonical=url, head=head,
                                   body="<main><h1>Lamps</h1><p>From &euro;90.</p></main>"))
        self.assertEqual(facts["page_type"], "category")

    def test_a_correctly_marked_up_variant_family_is_one_product(self):
        """A ProductGroup and its sizes are one subject, not three.

        Counting product-typed nodes made the best-marked-up pages on a site
        the ones most likely to be misread as listings - the exact inversion of
        what the audit is for.
        """
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"ProductGroup",'
                '"name":"Fell running vest","productGroupID":"FRV",'
                '"hasVariant":['
                '{"@type":"Product","name":"Fell running vest, S",'
                ' "sku":"FRV-S","offers":{"@type":"Offer","price":"75"}},'
                '{"@type":"Product","name":"Fell running vest, M",'
                ' "sku":"FRV-M","offers":{"@type":"Offer","price":"75"}},'
                '{"@type":"Product","name":"Fell running vest, L",'
                ' "sku":"FRV-L","offers":{"@type":"Offer","price":"75"}}]}</script>')
        url = "https://www.moorfoot-kit.example/products/fell-running-vest"
        facts = page(url, html_doc(title="Fell running vest", canonical=url, head=head,
                                   body="<main><h1>Fell running vest</h1>"
                                        "<p>&pound;75.00</p></main>"))
        self.assertEqual(facts["page_type"], "product")


class TestAHubHintStopsAtTheHub(unittest.TestCase):
    """A buying hub is a page; it is not a prefix over everything beneath it.

    `/shop/buy-ipad` is a model chooser and `/shop/buy-ipad/ipad-air` is one
    item inside it. Unanchored, the hint that recognised the first swallowed
    the second, and a live audit of a storefront came back with no product
    pages at all - after which its product rules reported full marks over a
    population of zero. This is the same anchoring `/products/` needed against
    `/products/velocity-x9`, on the other side of the question.
    """

    HUBS = ("https://www.orchard-devices.example/shop/buy-handset",
            "https://www.orchard-devices.example/us/shop/goto/buy_handset",
            "https://www.orchard-devices.example/gift-cards/",
            "https://www.orchard-devices.example/en/buy-laptops")

    ITEMS = ("https://www.orchard-devices.example/shop/buy-handset/orb-9-pro",
             "https://www.orchard-devices.example/shop/buy-laptop/orb-book-14",
             "https://www.orchard-devices.example/gift-cards/birthday-50")

    def test_the_hub_itself_is_recognised(self):
        for url in self.HUBS:
            with self.subTest(url=url):
                self.assertNotEqual(classify_page(url), "product")

    def test_the_hint_does_not_reach_the_items_underneath(self):
        for url in self.ITEMS:
            with self.subTest(url=url):
                self.assertNotEqual(
                    classify_page(url), "promotional",
                    "the hub hint swallowed an item inside the hub")

    def test_an_item_under_a_buying_route_is_decided_by_its_content(self):
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"Product",'
                '"name":"Orb 9 Pro","sku":"ORB9P",'
                '"offers":{"@type":"Offer","price":"999","priceCurrency":"GBP",'
                '"availability":"https://schema.org/InStock"}}</script>')
        url = "https://www.orchard-devices.example/shop/buy-handset/orb-9-pro"
        facts = page(url, html_doc(
            title="Orb 9 Pro", canonical=url, head=head,
            body="<main><h1>Orb 9 Pro</h1><p>&pound;999.00, in stock.</p>"
                 "<table><tr><th>Display</th><td>6.3 in</td></tr></table></main>"))
        self.assertEqual(facts["page_type"], "product")


class TestCommerceHubsAreNotListings(unittest.TestCase):
    """Non-product and non-listing are different exemptions.

    A gift-card page, a model chooser and a seasonal promotion are not
    products - that was fixed by filing them as `category`, which made them
    listings, and a listing is asked why it publishes no filtering, no sorting
    and no comparison support. Owing a facet navigation is not an improvement
    on being audited as a shoe.
    """

    HUBS = {
        "a model chooser": "https://www.orchard-devices.example/shop/buy-handset",
        "a gift-card hub": "https://www.tilden-outfitters.example/gift-cards/",
        "a seasonal promotion": "https://www.lumen-cosmetics.example/offers/spring/",
    }

    def test_none_of_them_is_a_listing(self):
        from aiva.extract import LISTING_PAGE_TYPES
        for label, url in self.HUBS.items():
            with self.subTest(page=label):
                self.assertNotIn(classify_page(url), LISTING_PAGE_TYPES)

    def test_none_of_them_is_a_product(self):
        for label, url in self.HUBS.items():
            with self.subTest(page=label):
                self.assertNotEqual(classify_page(url), "product")

    def test_they_reach_neither_funnel(self):
        pages = [page(url, html_doc(title=label, canonical=url,
                                    body=f"<main><h1>{label}</h1>"
                                         "<p>From &pound;25.</p></main>"))
                 for label, url in self.HUBS.items()]
        data = bundle(pages, origin="https://www.orchard-devices.example")
        self.assertEqual(ev.product_pages(data), [])
        self.assertEqual(ev.category_pages(data), [])

    def test_a_real_catalogue_index_is_still_a_listing(self):
        """The control: `/shop-all` and `/all-models` name a set and stay one."""
        for url in ("https://www.orchard-devices.example/shop-all",
                    "https://www.orchard-devices.example/all-models",
                    "https://www.orchard-devices.example/collections/handsets"):
            with self.subTest(url=url):
                self.assertEqual(classify_page(url), "category")


class TestASectionWordIsAPredictionNotAVerdict(unittest.TestCase):
    """`/shop` names a catalogue index on most sites and a product on one.

    Read as a verdict it made a software feature page a listing and asked it
    for filters. It is still useful before anything has been fetched, where a
    wrong guess costs a sampling slot; once the page is in hand, the page
    decides.
    """

    URL = "https://www.laxton-supply.example/shop"

    def test_it_predicts_a_listing_before_anything_is_fetched(self):
        self.assertEqual(classify_page(self.URL), "category")

    def test_but_the_content_overrides_it(self):
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"Product","name":"Shop",'
                '"sku":"SHOP-1","offers":{"@type":"Offer","price":"0",'
                '"priceCurrency":"USD"}}</script>')
        facts = page(self.URL, html_doc(
            title="Shop", canonical=self.URL, head=head,
            body="<main><h1>Shop</h1><p>Our buyer app, free to install.</p>"
                 "<table><tr><th>Platform</th><td>iOS, Android</td></tr></table></main>"))
        self.assertEqual(facts["page_type"], "product")

    def test_and_a_page_that_is_neither_stays_neither(self):
        facts = page(self.URL, html_doc(
            title="Shop", canonical=self.URL,
            body="<main><h1>Shop</h1><p>Coming soon.</p></main>"))
        self.assertNotEqual(facts["page_type"], "category")


class TestAppleShapedRoutesAreOneFixtureNotARule(unittest.TestCase):
    """The live report that exposed the general defect, kept as a witness.

    Five `/us/shop/goto/*` routes were audited as individual product pages.
    Nothing in the classifier knows about apple.com: the general assertion is
    the one above it, and this exists so the specific case cannot come back.
    """

    def test_the_general_shape_first(self):
        self.assertNotEqual(buying_landing_page()["page_type"], "product")

    def test_and_the_urls_that_exposed_it(self):
        for path in ("/us/shop/goto/buy_iphone", "/us/shop/goto/buy_mac",
                     "/us/shop/goto/buy_ipad", "/us/shop/goto/trade_in",
                     "/us/shop/goto/payment_plan"):
            with self.subTest(path=path):
                self.assertNotEqual(classify_page("https://www.apple.com" + path),
                                    "product")


class TestDownstreamConsumesTheSharedClassification(unittest.TestCase):
    """The classification is decided once and every rule reads that answer.

    A specialist that re-derives a page type is how two halves of one report
    come to disagree about the same URL. These assertions are about the
    *report*, not the classifier: no product-specific finding and no product
    answerability question may be raised about a page that is not a product.
    """

    SKILLS = ("crawl-render-audit", "machine-readability-audit",
              "freshness-corroboration", "entity-audit", "engagement-audit",
              "answerability-audit")

    def setUp(self):
        home = page(SHOP_ORIGIN + "/", html_doc(
            title="Northfield", canonical=SHOP_ORIGIN + "/",
            body="<h1>Northfield</h1><a href='/shop/bikes'>Shop</a>"))
        self.pages = [home] + [build() for build in NON_PRODUCT_FIXTURES.values()]
        self.bundle = bundle(self.pages, origin=SHOP_ORIGIN)
        self.findings = [f for skill in self.SKILLS
                         for f in run(skill, self.bundle)]

    def test_no_page_reaches_the_product_funnel(self):
        self.assertEqual([p["url"] for p in ev.product_pages(self.bundle)], [])

    def test_no_product_specific_rule_fires(self):
        product_rules = [f.rule_id for f in self.findings
                         if "PRODUCT" in f.rule_id or "OFFER" in f.rule_id
                         or "VARIANTS" in f.rule_id]
        self.assertEqual(product_rules, [],
                         f"product rules fired with no product page: {product_rules}")

    def test_no_finding_calls_any_of_these_pages_a_product_page(self):
        for finding in self.findings:
            unit = str((finding.metrics or {}).get("sample_unit") or "")
            with self.subTest(rule=finding.rule_id):
                self.assertNotIn("product", unit.lower())

    def test_the_same_bundle_with_a_real_product_page_does_reach_the_funnel(self):
        """The control. Otherwise this class passes by classifying nothing."""
        data = bundle(self.pages + [product_detail_page()], origin=SHOP_ORIGIN)
        self.assertEqual([p["url"] for p in ev.product_pages(data)], [PDP_URL])


class TestFragmentsAndMetadataAreNotProducts(unittest.TestCase):
    """The shapes a modern storefront serves that are not pages at all.

    A component fragment, a partial rendered for a lazy-loaded rail, a page
    whose only heading is a template token: each carries prices, product
    vocabulary and product links, and none of them is a product page. The
    classifier has no idea what a framework is, so the test is the same one it
    applies everywhere - is there an anchor, and are there two independent
    families - and these fail it for the right reason.
    """

    ORIGIN = "https://www.deverell-supply.example"

    def _page(self, path: str, body: str, head: str = "") -> dict:
        url = self.ORIGIN + path
        return page(url, html_doc(title="Deverell", canonical=url, head=head, body=body))

    def test_an_internal_fragment_is_not_a_product(self):
        """A rail partial: three priced tiles, no document around them."""
        body = ("<div class='ProductRail'>"
                + "".join(f"<a href='/products/item-{i}'>Item {i} &pound;{40 + i}</a>"
                          for i in range(4))
                + "</div>")
        self.assertNotEqual(self._page("/_partials/product-rail", body)["page_type"],
                            "product")

    def test_a_component_metadata_page_is_not_a_product(self):
        body = ("<main><h1>ProductTile__container--v2</h1>"
                "<p>&pound;49.00</p><p>data-testid: product-tile</p></main>")
        self.assertNotEqual(self._page("/styleguide/product-tile", body)["page_type"],
                            "product")

    def test_a_template_token_heading_is_not_a_product(self):
        body = "<main><h1>{{product.title}}</h1><p>{{product.price}}</p></main>"
        self.assertNotEqual(self._page("/templates/pdp", body)["page_type"], "product")

    def test_a_regional_duplicate_classifies_the_same_as_its_original(self):
        """Two markets, one template. Whatever the page is, it is the same
        thing in both - a classifier that disagrees with itself across a
        locale prefix would report the same template as two different types.
        """
        head = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@type":"Product",'
                '"name":"Alder bench","sku":"ALD-1",'
                '"offers":{"@type":"Offer","price":"219","priceCurrency":"EUR"}}</script>')
        body = ("<main><h1>Alder bench</h1><p>&euro;219.00, in stock.</p>"
                "<table><tr><th>Length</th><td>120 cm</td></tr></table></main>")
        first = self._page("/products/alder-bench", body, head)
        second = self._page("/de/de/products/alder-bench", body, head)
        self.assertEqual(first["page_type"], "product")
        self.assertEqual(second["page_type"], first["page_type"])

    def test_none_of_them_reaches_either_funnel(self):
        fragments = [
            self._page("/_partials/product-rail",
                       "".join(f"<a href='/products/item-{i}'>Item {i} &pound;{40 + i}</a>"
                               for i in range(4))),
            self._page("/styleguide/product-tile",
                       "<main><h1>ProductTile__container--v2</h1><p>&pound;49</p></main>"),
            self._page("/templates/pdp",
                       "<main><h1>{{product.title}}</h1><p>{{product.price}}</p></main>"),
        ]
        data = bundle(fragments, origin=self.ORIGIN)
        self.assertEqual(ev.product_pages(data), [])
        self.assertEqual(ev.category_pages(data), [])


if __name__ == "__main__":
    unittest.main()
