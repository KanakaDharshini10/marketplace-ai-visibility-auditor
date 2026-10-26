"""Advice about a page must be evidenced on that page, or on its own items.

A listing page and the product pages elsewhere in a crawl are different
entities. Until the link between them was carried explicitly, "filter on the
attributes these product pages already publish" meant "on attributes some
product page, anywhere on this host, publishes" - and a handset family page
came back recommending filters on a locator tag's diameter, height and
operating ambient temperature. Both readings of the sentence are about real
observations; only one of them is about the page being advised.

Two defects produced that, and this module holds both shut:

1. **Attribute provenance.** Attributes for a listing's recommendation were
   read from the whole crawl. They are now read only from the product pages
   that listing itself links to, and where none was read the advice names no
   attribute at all.

2. **Listing applicability.** A page cleared the "is this a set worth
   filtering" test by *counting* product links and prices, which a product
   family page, a marketing page and a comparison page all do. The set itself
   must now be evidenced - members read, an ItemList declared, pagination, or
   catalogue controls already present - and a page whose set cannot be
   delimited is set aside and named rather than advised.

Every fixture here is invented (:mod:`shapes`). No test, and no line of
runtime code, knows a domain name.

Run just this file:

    python3 tests/run_tests.py provenance -v
"""

from __future__ import annotations

import unittest

import helpers
import shapes
from helpers import bundle, find, html_doc, jsonld, page, rule_ids, run

from aiva import analysis, semantics

#: Attributes that exist on exactly one page in the leak fixtures. Their
#: appearance anywhere else is the defect.
FOREIGN = ("Diameter", "Height", "Operating ambient temperature")

CONTROL_RULES = ("EG-FILTER-CONTROLS-ABSENT", "EG-SORT-CONTROLS-ABSENT")


def engagement(data: dict):
    return run("engagement-audit", data)


def advice_text(finding) -> str:
    """Everything a reader is told to do, as one searchable string."""
    action = finding.suggested_action
    return " ".join([action.summary, action.mechanism, action.example,
                     *action.steps, finding.evidence, finding.interpretation])


def commerce_advice(data: dict) -> str:
    """Every word of advice the whole marketplace emits for a bundle."""
    out = []
    for _, module in helpers.load_specialists():
        for finding in module.analyze(data):
            out.append(advice_text(finding))
    return " ".join(out)


# ---------------------------------------------------------------------------
# 1. the reported failure, reproduced generically
# ---------------------------------------------------------------------------

class TestTheCrossPageAttributeLeak(unittest.TestCase):
    """A product family page and an unrelated accessory on one host."""

    def setUp(self):
        self.data = shapes.family_landing_site()
        semantics.annotate_bundle(self.data)

    def test_the_family_page_alone_would_have_cleared_the_size_threshold(self):
        """Proof the fixture reproduces the original path rather than dodging
        it: the page still counts as large enough; what it lacks is a set."""
        family = next(p for p in self.data["pages"] if p["url"].endswith("/handset/"))
        expected, why = analysis.listing_controls_expected(family)
        self.assertTrue(expected, why)
        self.assertGreaterEqual(analysis.listing_entry_count(family), 8)

    def test_no_attribute_of_an_unrelated_product_reaches_the_family_page(self):
        text = commerce_advice(self.data)
        for attribute in FOREIGN:
            self.assertNotIn(attribute, text,
                             f"{attribute!r} belongs to the accessory page alone")

    def test_the_finding_describes_no_item_it_did_not_read(self):
        """The missing control is an observation and stays reportable; the
        *items* are not, so nothing in the advice describes them."""
        finding = find(engagement(self.data), "EG-FILTER-CONTROLS-ABSENT")
        self.assertIsNotNone(finding, "the observed absence is still a finding")
        self.assertEqual(finding.metrics["attribute_provenance"], [])
        self.assertEqual(finding.metrics["listings_with_no_delimitable_set"], 1)
        self.assertIn("the set could not be delimited", finding.evidence)

    def test_no_ordering_dimension_is_named_for_an_undelimited_set(self):
        """Tightened in 1.11.1. This page prints its own prices, and until
        1.11.1 that was accepted as evidence for "sort by price". It is not
        enough: the prices may belong to items this page does not represent,
        so a dimension is named only where the chain listing -> member ->
        observed value exists. Here it does not, and none is named."""
        finding = find(engagement(self.data), "EG-SORT-CONTROLS-ABSENT")
        self.assertIsNotNone(finding, "the observed absence is still reported")
        self.assertEqual(finding.metrics["evidenced_order_dimensions"], [])
        action = finding.suggested_action
        steps = " ".join(action.steps)
        # Tightened again in 1.11.2: on a downgraded finding the *recommendation*
        # is conditional too, not just the title. It names no dimension and
        # gives the reader back the premise the evidence could not establish.
        self.assertEqual(action.summary,
                         "Establish the item set before deciding whether ordering applies.")
        self.assertIn("If this page is intended to function as", steps)
        self.assertIn("only for values actually published by its members", steps)
        self.assertNotIn("covering at least", steps)
        self.assertNotIn("Add a sort control on", steps)

    def test_an_undelimited_set_lowers_severity_and_confidence(self):
        """Confidence follows applicability, not the detector: the control is
        certainly absent, and what that means is not established."""
        for rule in CONTROL_RULES:
            finding = find(engagement(self.data), rule)
            self.assertIsNotNone(finding, rule)
            self.assertEqual(finding.metrics["applicability"], "downgrade", rule)
            self.assertEqual(finding.severity, "low", rule)
            self.assertLessEqual(finding.confidence, 0.4, rule)
            self.assertIn("could not be assessed against a known comparable set",
                          finding.title + finding.evidence)

    def test_the_undelimited_set_is_stated_not_silent(self):
        """A gap the reader cannot see is indistinguishable from a rule that
        never ran, so the evidence names it."""
        family = next(p for p in self.data["pages"] if p["url"].endswith("/handset/"))
        record = analysis.collection_provenance(family, self.data)
        self.assertFalse(record["established"])
        self.assertEqual(record["members"], [])
        evidence = find(engagement(self.data), "EG-FILTER-CONTROLS-ABSENT").evidence
        for phrase in ("no product page", "no ItemList is declared", "do not paginate",
                       "says nothing about what the items are"):
            self.assertIn(phrase, evidence)


# ---------------------------------------------------------------------------
# 2. attributes come from the listing's own items
# ---------------------------------------------------------------------------

class TestAttributesComeFromTheListingsOwnItems(unittest.TestCase):

    def setUp(self):
        self.data = shapes.two_catalogue_site()
        semantics.annotate_bundle(self.data)

    def _listing(self, path: str) -> dict:
        return next(p for p in self.data["pages"] if p["url"].endswith(path))

    def test_members_are_the_product_pages_the_listing_links_to(self):
        boots = self._listing("/collections/boots")
        members = {p["url"] for p in analysis.listing_members(boots, self.data)}
        self.assertEqual(len(members), 2)
        self.assertTrue(all("boot" in url for url in members), members)

    def test_a_listings_vocabulary_excludes_products_it_does_not_list(self):
        boots = self._listing("/collections/boots")
        names = analysis.catalogue_vocabulary(self.data, [boots])["comparable_attributes"]
        for attribute in FOREIGN:
            self.assertNotIn(attribute, names)

    def test_multiple_products_of_one_listing_all_contribute(self):
        """Item 5 of the brief: membership is a set, not a first match."""
        accessories = self._listing("/collections/accessories")
        members = analysis.listing_members(accessories, self.data)
        self.assertEqual(len(members), 2)
        names = analysis.catalogue_vocabulary(self.data, [accessories])["comparable_attributes"]
        self.assertTrue(set(FOREIGN) & set(names), names)

    def test_a_products_attributes_do_not_cross_to_the_other_listing(self):
        """Item 2 and item 6: A's attributes are not B's, in either direction."""
        boots = analysis.catalogue_vocabulary(
            self.data, [self._listing("/collections/boots")])["comparable_attributes"]
        accessories = analysis.catalogue_vocabulary(
            self.data, [self._listing("/collections/accessories")])["comparable_attributes"]
        self.assertTrue(boots and accessories)
        self.assertEqual(set(boots) & set(accessories), set(),
                         "the two catalogues share no attribute, so neither may quote the "
                         "other's")

    def test_a_genuine_catalogue_still_receives_its_findings(self):
        """Item 4: the fix suppresses guesses, not findings."""
        emitted = rule_ids(engagement(self.data))
        self.assertTrue(set(CONTROL_RULES) & set(emitted),
                        f"a real catalogue lost its findings: {emitted}")

    def test_the_finding_states_what_makes_the_page_a_set(self):
        finding = find(engagement(self.data), "EG-FILTER-CONTROLS-ABSENT") \
            or find(engagement(self.data), "EG-SORT-CONTROLS-ABSENT")
        self.assertIsNotNone(finding)
        self.assertIn("The set each listing represents is established by:", finding.evidence)
        self.assertTrue(finding.metrics.get("comparable_items_basis"))


# ---------------------------------------------------------------------------
# 3. what makes a page a comparable collection
# ---------------------------------------------------------------------------

class TestCollectionProvenance(unittest.TestCase):
    """Four observations delimit a set; counting links and prices does not."""

    def _one_listing(self, listing_page: dict, *rest: dict) -> dict:
        data = bundle([shapes.home(), listing_page, *rest])
        semantics.annotate_bundle(data)
        return data

    def test_read_members_delimit_the_set(self):
        data = shapes.two_catalogue_site()
        page_ = next(p for p in data["pages"] if p["url"].endswith("/collections/boots"))
        record = analysis.collection_provenance(page_, data)
        self.assertTrue(record["established"])
        self.assertEqual(len(record["members"]), 2)
        self.assertIn("product page(s) the listing links to were read", record["basis"])

    def test_a_declared_itemlist_delimits_the_set(self):
        listing_page = page(helpers.ORIGIN + "/range/", html_doc(
            title="Range", canonical=helpers.ORIGIN + "/range/",
            head=jsonld('{"@context":"https://schema.org","@type":"ItemList",'
                        '"numberOfItems":24,"itemListElement":['
                        '{"@type":"ListItem","position":1},'
                        '{"@type":"ListItem","position":2}]}'),
            body="<h1>Range</h1><a href='/products/a'>A &#163;10</a>"))
        data = self._one_listing(listing_page)
        record = analysis.collection_provenance(listing_page, data)
        self.assertTrue(record["established"])
        self.assertIn("ItemList", record["basis"])

    def test_pagination_delimits_the_set(self):
        listing_page = shapes.catalogue_listing(
            "/collections/all", "All", [("/products/x", "X", "10")], paginates=True)
        data = self._one_listing(listing_page)
        record = analysis.collection_provenance(listing_page, data)
        self.assertTrue(record["established"])
        self.assertIn("paginates", record["basis"])

    def test_controls_the_page_already_has_delimit_the_set(self):
        listing_page = page(helpers.ORIGIN + "/shop/", html_doc(
            title="Shop", canonical=helpers.ORIGIN + "/shop/",
            body="<h1>Shop</h1><form><label>Sort by<select name='sort'>"
                 "<option>Price</option></select></label></form>"
                 "<a href='/products/a'>A &#163;10</a>"))
        data = self._one_listing(listing_page)
        self.assertTrue(analysis.collection_provenance(listing_page, data)["established"])

    def test_links_and_prices_alone_do_not_delimit_a_set(self):
        family = shapes.product_family()
        data = self._one_listing(family)
        record = analysis.collection_provenance(family, data)
        self.assertFalse(record["established"], record["basis"])
        self.assertEqual(record["basis"], "")

    def test_ambiguous_provenance_names_nothing_rather_than_guessing(self):
        """Item 7: the outcome of "cannot tell" is an empty vocabulary and an
        empty dimension list, not a default set of either."""
        data = shapes.family_landing_site()
        semantics.annotate_bundle(data)
        family = next(p for p in data["pages"] if p["url"].endswith("/handset/"))
        self.assertEqual(analysis.listing_members(family, data), [])
        self.assertEqual(
            analysis.catalogue_vocabulary(data, [family])["comparable_attributes"], [])
        # The page prints its own prices, so ordering by price is observed on
        # the very page being advised. A rating is not, and is never asserted.
        self.assertEqual(analysis.orderable_dimensions(data, [family]), ["price"])

    def test_an_evidenced_dimension_is_named_and_an_unevidenced_one_is_not(self):
        """Price is observed across both catalogues; no product carries a
        rating, so "sort by rating" is never asserted."""
        data = shapes.two_catalogue_site()
        semantics.annotate_bundle(data)
        listings = [p for p in data["pages"] if p["url"].startswith(helpers.ORIGIN
                                                                   + "/collections/")]
        self.assertEqual(analysis.orderable_dimensions(data, listings), ["price"])


# 4. negative proof, one site shape at a time
# ---------------------------------------------------------------------------

class TestPagesThatAreNotCatalogues(unittest.TestCase):
    """Item 3 and item 8, plus section 9's list, each shape proved separately."""

    def test_a_product_family_page_is_not_an_ecommerce_listing(self):
        data = shapes.family_landing_site()
        semantics.annotate_bundle(data)
        family = next(p for p in data["pages"] if p["url"].endswith("/handset/"))
        record = semantics.listing_record(family, data)
        self.assertNotEqual(record.get("subtype"), "ecommerce_listing")
        self.assertFalse(analysis.collection_provenance(family, data)["established"])

    def test_a_marketing_page_receives_no_catalogue_advice(self):
        data = bundle([shapes.home(), shapes.marketing_page(),
                       shapes.physical_product()])
        semantics.annotate_bundle(data)
        emitted = rule_ids(engagement(data))
        for rule in CONTROL_RULES:
            self.assertNotIn(rule, emitted)

    def test_a_physical_product_elsewhere_does_not_describe_an_unrelated_page(self):
        """The last line of section 9. A boot sits on the same host as a
        handset family page and is not linked from it; the boot's colour,
        material and weight are facts about the boot and about nothing else."""
        data = bundle([shapes.home(), shapes.physical_product(),
                       shapes.product_family()])
        semantics.annotate_bundle(data)
        family = next(p for p in data["pages"] if p["url"].endswith("/handset/"))
        self.assertFalse(analysis.collection_provenance(family, data)["established"])
        self.assertNotEqual(
            semantics.listing_record(family, data).get("subtype"), "ecommerce_listing")
        self.assertEqual(
            analysis.catalogue_vocabulary(data, [family])["comparable_attributes"], [])
        filtering = find(engagement(data), "EG-FILTER-CONTROLS-ABSENT")
        self.assertIsNotNone(filtering, "the observed absence remains reportable")
        for attribute in ("Colour", "Material", "Weight", "Brown", "Leather"):
            self.assertNotIn(attribute, advice_text(filtering), attribute)

    def test_non_commerce_sites_receive_no_commerce_advice(self):
        for name, build in shapes.NON_COMMERCE:
            with self.subTest(shape=name):
                data = build()
                semantics.annotate_bundle(data)
                emitted = rule_ids(engagement(data))
                for rule in CONTROL_RULES:
                    self.assertNotIn(rule, emitted, name)

    def test_sites_that_sell_no_parcel_receive_no_catalogue_filter_advice(self):
        """A SaaS plan list and a software catalogue are sets, but a plan page
        is not filtered on colour and material."""
        for name, build in shapes.NON_PHYSICAL_SELLERS:
            with self.subTest(shape=name):
                data = build()
                semantics.annotate_bundle(data)
                text = commerce_advice(data)
                for attribute in FOREIGN:
                    self.assertNotIn(attribute, text, name)


# ---------------------------------------------------------------------------
# 5. answerability keeps to one entity
# ---------------------------------------------------------------------------

class TestAnswerabilityStaysWithinOneEntity(unittest.TestCase):
    """Item 9: a question about one product is resolved from that product."""

    def setUp(self):
        from aiva import answerability
        self.answerability = answerability
        self.data = shapes.two_catalogue_site()
        semantics.annotate_bundle(self.data)
        self.matrix = answerability.build_matrix(self.data)

    def test_every_product_row_cites_the_page_it_is_about(self):
        by_url = {p["url"]: p for p in self.data["pages"]}
        product_kinds = ("product_price", "product_availability", "product_specifications")
        rows = [r for r in self.matrix["questions"] if r["kind"] in product_kinds]
        self.assertTrue(rows)
        for row in rows:
            page_ = by_url.get(row["citing_url"])
            self.assertIsNotNone(page_, row["citing_url"])
            self.assertEqual(page_.get("page_type"), "product", row)

    def test_a_specification_answer_quotes_only_its_own_products_attributes(self):
        rows = [r for r in self.matrix["questions"] if r["kind"] == "product_specifications"]
        self.assertTrue(rows)
        for row in rows:
            about_the_accessory = "locator" in row["citing_url"]
            mentions_foreign = any(a in (row.get("evidence") or "") for a in FOREIGN)
            self.assertEqual(mentions_foreign, about_the_accessory,
                             f"{row['citing_url']} quoted attributes that are not its own: {row}")

    def test_a_category_question_is_ranked_over_that_categorys_members(self):
        rows = [r for r in self.matrix["questions"] if r["kind"] == "category_cheapest"]
        for row in rows:
            listing_page = next(p for p in self.data["pages"] if p["url"] == row["citing_url"])
            members = {p["url"] for p in analysis.listing_members(listing_page, self.data)}
            cited = [url for url in members if url in (row.get("evidence") or "")]
            if "£" in (row.get("evidence") or "") or cited:
                self.assertTrue(cited, f"ranked from outside its own members: {row}")

    def test_a_comparison_names_both_products_it_compares(self):
        rows = [r for r in self.matrix["questions"] if r["kind"] == "product_comparison"]
        for row in rows:
            self.assertIn(" and ", row["question"])
            self.assertTrue(row["citing_url"], row)

    def test_a_comparison_prefers_two_items_the_site_lists_together(self):
        """Kind alone paired an accessory with a boot - both physical goods,
        and nothing else connecting them - and then recorded "they share no
        attribute" as a gap for a comparison the site never invites."""
        data = bundle([
            shapes.home(),
            shapes.instrument_product(),                       # crawled first, on purpose
            shapes.physical_product(),
            shapes.physical_product("/products/summit-boot", "Summit Boot", "210"),
            shapes.catalogue_listing("/collections/boots", "Boots",
                                     [("/products/trail-boot", "Trail Boot", "120"),
                                      ("/products/summit-boot", "Summit Boot", "210")]),
            shapes.catalogue_listing("/collections/accessories", "Accessories",
                                     [("/products/locator-tag", "Locator Tag", "35")])])
        semantics.annotate_bundle(data)
        rows = [r for r in self.answerability.build_matrix(data)["questions"]
                if r["kind"] == "product_comparison"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn("Trail Boot", row["question"])
        self.assertIn("Summit Boot", row["question"])
        self.assertNotIn("Locator Tag", row["question"])
        self.assertIn('both are listed in "Boots"', row["subject_identity"])

    def test_a_comparison_says_so_when_no_listing_pairs_the_items(self):
        """The fallback is kind, and the row states that it is the fallback."""
        data = bundle([shapes.home(), shapes.instrument_product(),
                       shapes.physical_product()])
        semantics.annotate_bundle(data)
        rows = [r for r in self.answerability.build_matrix(data)["questions"]
                if r["kind"] == "product_comparison"]
        for row in rows:
            self.assertIn("no listing was observed containing both",
                          row["subject_identity"])


# ---------------------------------------------------------------------------
# 6. nothing that already worked stopped working
# ---------------------------------------------------------------------------

class TestExistingBehaviourIsUnchanged(unittest.TestCase):
    """Item 10: where the evidence was already sufficient, nothing moved."""

    def test_the_ordinary_commerce_bundle_is_unaffected(self):
        data = helpers.commerce_bundle()
        semantics.annotate_bundle(data)
        listing_page = next(p for p in data["pages"] if p.get("page_type") == "category")
        members = analysis.listing_members(listing_page, data)
        self.assertEqual(len(members), 2)
        record = analysis.collection_provenance(listing_page, data)
        self.assertTrue(record["established"], record["basis"])

    def test_the_shop_shape_still_reads_as_a_catalogue(self):
        data = shapes.shop()
        semantics.annotate_bundle(data)
        listing_page = next(p for p in data["pages"]
                            if p["url"].endswith("/collections/boots"))
        self.assertTrue(analysis.collection_provenance(listing_page, data)["established"])
        record = semantics.listing_record(listing_page, data)
        self.assertEqual(record.get("subtype"), "ecommerce_listing")

    def test_chrome_links_are_not_members(self):
        """A footer link to a product is site chrome, not a listing entry."""
        listing_page = page(helpers.ORIGIN + "/collections/x", html_doc(
            title="X", canonical=helpers.ORIGIN + "/collections/x",
            body="<main><h1>X</h1></main>"
                 "<footer><a href='/products/trail-boot'>Trail Boot</a></footer>"))
        data = bundle([shapes.home(), listing_page, shapes.physical_product()])
        semantics.annotate_bundle(data)
        self.assertEqual(analysis.listing_members(listing_page, data), [])

    def test_specialists_still_perform_no_network_io(self):
        """The provenance walk reads the bundle and nothing else."""
        data = shapes.two_catalogue_site()
        before = helpers.util.json_dumps(data) if hasattr(helpers.util, "json_dumps") else None
        engagement(data)
        if before is not None:
            self.assertEqual(before, helpers.util.json_dumps(data),
                             "a specialist mutated the shared evidence bundle")


if __name__ == "__main__":
    unittest.main()
