"""Product identity comes from item-scoped evidence, or not at all.

A generated question quotes its subject back to the reader. On a live site
the subjects were "Add to bag", "Shop the range" and "Product details": the
first `<h1>` of pages classified as products, read as if a heading were a
name. Every test here builds real HTML through the real extractor, so the
identity rule is exercised at the boundary it protects, and every negative
case is paired with the positive one it must not break.

Nothing here knows a brand or a phrase a call to action tends to use. The
rejections are all shape or provenance: the heading is the label of one of
the page's own controls, the site repeats it on other pages, it is shaped
like a promotion, or nothing else on the page - title, Open Graph, URL slug
- agrees that the page is about it.
"""

from __future__ import annotations

import json
import unittest

from helpers import ORIGIN, bundle, html_doc, jsonld, page, run, rule_ids
from aiva import answerability
from aiva.analysis import (item_identity, reads_as_a_promotion, site_template_strings,
                           site_vocabulary)

PRICE_AND_SPECS = ("<p>£20 - in stock.</p>"
                   "<table><tr><th>Capacity</th><td>1.7 L</td></tr>"
                   "<tr><th>Colour</th><td>Blue</td></tr></table>")

CART = "<form action='/cart/add'><button>Add to bag</button></form>"


def _shop(product_pages):
    home = page(ORIGIN + "/", html_doc(
        title="Halstow", body="<h1>Halstow</h1>"
        + "".join(f'<a href="{p["url"]}">{(p.get("h1_texts") or [p.get("title") or "?"])[0]}</a>'
                  for p in product_pages)))
    return bundle([home] + product_pages)


def _product(slug: str, *, title: str, h1: str, head: str = "", body_extra: str = "",
             og_type: str = "") -> dict:
    og = f'<meta property="og:type" content="{og_type}">' if og_type else ""
    return page(ORIGIN + f"/products/{slug}", html_doc(
        title=title, head=head + og, open_graph=not og_type,
        body=f"<main><h1>{h1}</h1>{PRICE_AND_SPECS}{CART}{body_extra}</main>"))


def _product_questions(data: dict) -> list:
    matrix = answerability.build_matrix(data)
    return [row for row in matrix["questions"] if row["kind"].startswith("product_")]


class TestGenuineNamesStillWork(unittest.TestCase):
    """The positive cases, one per identity source."""

    def test_a_declared_product_name_is_the_identity(self):
        ld = jsonld(json.dumps({"@context": "https://schema.org", "@type": "Product",
                                "name": "Halstow Kettle K1", "sku": "K1",
                                "offers": {"@type": "Offer", "price": "20",
                                           "priceCurrency": "GBP"}}))
        item = _product("k1", title="Something else entirely", h1="Add to bag", head=ld)
        identity = item_identity(item)
        self.assertEqual(identity["name"], "Halstow Kettle K1")
        self.assertEqual(identity["source"], "declared product entity")
        questions = _product_questions(_shop([item]))
        self.assertTrue(questions)
        self.assertTrue(all("Halstow Kettle K1" in q["question"] for q in questions))
        self.assertTrue(all("declared product entity" in q["subject_identity"]
                            for q in questions))

    def test_the_subject_node_wins_over_a_related_item_in_document_order(self):
        related = {"@type": "Product", "name": "Halstow Toaster T2"}
        ld = jsonld(json.dumps([
            {"@context": "https://schema.org", "@type": "Product", "name": "Halstow Kettle K1",
             "isRelatedTo": [related],
             "offers": {"@type": "Offer", "price": "20", "priceCurrency": "GBP"}}]))
        item = _product("k1", title="Halstow Kettle K1 | Halstow", h1="Halstow Kettle K1",
                        head=ld)
        self.assertEqual(item_identity(item)["name"], "Halstow Kettle K1")

    def test_a_microdata_product_item_is_the_identity(self):
        micro = ('<div itemscope itemtype="https://schema.org/Product">'
                 '<span itemprop="name">Halstow Kettle K1</span></div>')
        item = _product("k1", title="Halstow", h1="Product details", body_extra=micro)
        identity = item_identity(item)
        self.assertEqual(identity["name"], "Halstow Kettle K1")
        self.assertEqual(identity["source"], "declared product item")

    def test_an_open_graph_product_card_is_the_identity(self):
        head = '<meta property="og:title" content="Halstow Kettle K1">'
        item = _product("k1", title="Halstow", h1="Product details", head=head,
                        og_type="product")
        identity = item_identity(item)
        self.assertEqual(identity["name"], "Halstow Kettle K1")
        self.assertEqual(identity["source"], "declared product card")

    def test_a_heading_the_title_corroborates_is_the_identity(self):
        item = _product("k1", title="Halstow Kettle K1 | Halstow", h1="Halstow Kettle K1")
        identity = item_identity(item, _shop([item]))
        self.assertEqual(identity["name"], "Halstow Kettle K1")
        self.assertEqual(identity["source"], "corroborated heading")
        self.assertIn("title", identity["corroboration"])

    def test_a_heading_the_url_slug_corroborates_is_the_identity(self):
        item = _product("halstow-kettle-k1", title="Halstow", h1="Halstow Kettle K1")
        identity = item_identity(item, _shop([item]))
        self.assertEqual(identity["name"], "Halstow Kettle K1")
        self.assertIn("URL slug", identity["corroboration"])

    def test_a_page_with_no_h1_names_its_product_in_its_top_heading(self):
        # The template spent no <h1>; the product is named in an <h2> that the
        # title corroborates. A related-items <h3> below it is not top-level
        # and is never a candidate.
        item = page(ORIGIN + "/products/gas-hob-60", html_doc(
            title="Halstow 60cm gas hob | Halstow",
            body="<main><h2>Halstow 60cm gas hob</h2><p>£349 in stock</p>"
                 "<h3>Other hobs and ovens</h3>"
                 '<a href="/products/gas-hob-70">Halstow 70cm gas hob £429</a></main>'))
        identity = item_identity(item, _shop([item]))
        self.assertEqual(identity["name"], "Halstow 60cm gas hob")

    def test_an_uncorroborated_top_heading_is_still_not_an_identity(self):
        item = page(ORIGIN + "/products/k1", html_doc(
            title="Halstow", body="<main><h2>Product details</h2><p>£20 in stock</p>"
                                  + CART + "</main>"))
        self.assertIsNone(item_identity(item, _shop([item])))

    def test_a_one_word_product_name_works_through_the_slug(self):
        item = _product("kettle", title="Halstow", h1="Kettle")
        self.assertEqual(item_identity(item, _shop([item]))["name"], "Kettle")

    def test_a_product_with_a_number_in_its_name_is_not_a_promotion(self):
        for name in ("Aero Runner X9", "Kettle 1.7L", "Series 5 Blender", "Model 2026"):
            with self.subTest(name=name):
                self.assertFalse(reads_as_a_promotion(name))

    def test_variant_pages_declaring_one_name_each_keep_it(self):
        # Repetition is a fact about headings, not declarations: six variant
        # pages that each declare Product.name have each named their product.
        ld = jsonld(json.dumps({"@context": "https://schema.org", "@type": "Product",
                                "name": "VITTSKAR", "sku": "1",
                                "offers": {"@type": "Offer", "price": "40",
                                           "priceCurrency": "EUR"}}))
        items = [_product(f"vittskaer-{i}", title="VITTSKAR - Nordhaus", h1="VITTSKAR",
                          head=ld) for i in range(1, 7)]
        data = _shop(items)
        for item in items:
            self.assertEqual(item_identity(item, data)["name"], "VITTSKAR")

    def test_a_repeated_heading_is_rescued_by_a_title_segment_unique_to_the_page(self):
        items = [_product("kettle", title="Northvale Kettle | Halstow", h1="Northvale Kettle"),
                 _product("kettle-blue", title="Northvale Kettle Blue | Halstow",
                          h1="Northvale Kettle")]
        data = _shop(items)
        # The blue page's own title segment vouches for the shared heading...
        self.assertEqual(item_identity(items[1], data)["name"], "Northvale Kettle")
        # ...and the other page's slug alone does not: a repeated heading and a
        # section URL agree by construction, so the slug cannot vouch for it.
        self.assertIsNone(item_identity(items[0], data))

    def test_several_products_each_keep_their_own_identity(self):
        items = [_product(f"kettle-k{i}", title=f"Halstow Kettle K{i} | Halstow",
                          h1=f"Halstow Kettle K{i}") for i in range(1, 4)]
        data = _shop(items)
        names = {item_identity(p, data)["name"] for p in items}
        self.assertEqual(names, {"Halstow Kettle K1", "Halstow Kettle K2", "Halstow Kettle K3"})


class TestLabelsAreNotIdentities(unittest.TestCase):
    """The negative cases: each one used to become a question."""

    def _assert_no_identity(self, item: dict, data: dict = None):
        data = data or _shop([item])
        self.assertIsNone(item_identity(item, data), item.get("h1_texts"))
        questions = _product_questions(data)
        self.assertEqual(questions, [], [q["question"] for q in questions])
        notes = " ".join(answerability.build_matrix(data)["notes"])
        self.assertIn("no item-scoped evidence establishes what they are called", notes)
        self.assertIn(item["url"], notes)

    def test_cta_text_that_is_one_of_the_pages_own_controls(self):
        # The heading repeats the cart button. Whatever it says, a heading
        # that is a control label has not named the product.
        item = _product("k1", title="Add to bag | Halstow", h1="Add to bag")
        self._assert_no_identity(item)

    def test_cta_text_that_matches_a_navigation_link(self):
        item = _product("k1", title="Shop the range | Halstow", h1="Shop the range",
                        body_extra='<nav><a href="/collections/all">Shop the range</a></nav>')
        self._assert_no_identity(item)

    def test_a_ui_heading_the_title_does_not_corroborate(self):
        item = _product("k1", title="Halstow Kettle K1 | Halstow", h1="Product details")
        self._assert_no_identity(item)

    def test_a_component_label(self):
        for label in ("ProductTile__price--sale", "pdp_hero_banner_v2_primary",
                      "productDetailHeroBanner"):
            with self.subTest(label=label):
                item = _product("k1", title=f"{label} | Halstow", h1=label)
                self.assertIsNone(item_identity(item, _shop([item])))

    def test_repeated_template_text_across_pages(self):
        # Three product pages, one heading: the heading belongs to the
        # template, not to any of them - even though each title carries it.
        items = [_product(f"k{i}", title="Our products | Halstow", h1="Our products")
                 for i in range(1, 4)]
        data = _shop(items)
        self.assertIn("our products", site_template_strings(data))
        for item in items:
            self.assertIsNone(item_identity(item, data))
        self.assertEqual(_product_questions(data), [])

    def test_the_site_name_as_a_heading(self):
        item = _product("k1", title="Halstow", h1="Halstow")
        self._assert_no_identity(item)

    def test_promotional_labels(self):
        for heading in ("Save 20% on all kettles", "Free delivery on orders over £50",
                        "Up to 50% off", "Shop now!", "Ready to upgrade?",
                        "Only $9.99 today"):
            with self.subTest(heading=heading):
                self.assertTrue(reads_as_a_promotion(heading))
                item = _product("k1", title=f"{heading} | Halstow", h1=heading)
                self.assertIsNone(item_identity(item, _shop([item])))

    def test_a_heading_nothing_on_the_page_agrees_with(self):
        item = _product("k1", title="Halstow", h1="Kitchen essentials")
        self._assert_no_identity(item)

    def test_a_bad_declared_name_does_not_fall_through_to_a_label(self):
        ld = jsonld(json.dumps({"@context": "https://schema.org", "@type": "Product",
                                "name": "{{product.title}}",
                                "offers": {"@type": "Offer", "price": "20"}}))
        item = _product("k1", title="Halstow", h1="Add to bag", head=ld)
        self._assert_no_identity(item)


class TestOtherConsumersOfTheName(unittest.TestCase):

    def test_a_worked_example_never_names_a_control(self):
        item = _product("k1", title="Add to bag | Halstow", h1="Add to bag")
        self.assertIsNone(site_vocabulary(_shop([item]))["product"])
        real = _product("k1", title="Halstow Kettle K1 | Halstow", h1="Halstow Kettle K1")
        self.assertEqual(site_vocabulary(_shop([real]))["product"], "Halstow Kettle K1")

    def test_repeated_template_headings_are_not_duplicate_product_names(self):
        items = [_product(f"k{i}", title="Product details | Halstow", h1="Product details")
                 for i in range(1, 4)]
        self.assertNotIn("EN-DUPLICATE-PRODUCT-NAMES", rule_ids(run("entity-audit",
                                                                     _shop(items))))

    def test_declared_duplicate_names_are_still_reported(self):
        ld = jsonld(json.dumps({"@context": "https://schema.org", "@type": "Product",
                                "name": "Halstow Kettle", "sku": "1",
                                "offers": {"@type": "Offer", "price": "20",
                                           "priceCurrency": "GBP"}}))
        items = [_product(f"kettle-{i}", title=f"Kettle {i} | Halstow",
                          h1=f"Kettle {i}", head=ld) for i in range(1, 4)]
        self.assertIn("EN-DUPLICATE-PRODUCT-NAMES", rule_ids(run("entity-audit",
                                                                  _shop(items))))

    def test_category_headings_go_through_the_same_template_gate(self):
        listings = [page(ORIGIN + f"/collections/c{i}", html_doc(
            title="Browse | Halstow", body="<h1>Browse</h1>"
            + "".join(f'<a href="/products/k{j}">Kettle K{j} £20</a>' for j in range(6))))
            for i in range(2)]
        products = [_product(f"k{j}", title=f"Kettle K{j} | Halstow", h1=f"Kettle K{j}")
                    for j in range(2)]
        data = bundle(listings + products)
        asked = [q["question"] for q in answerability.build_matrix(data)["questions"]]
        self.assertFalse(any("cheapest item in Browse" in q for q in asked), asked)


if __name__ == "__main__":
    unittest.main()
