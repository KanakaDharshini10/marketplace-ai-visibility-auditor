"""Regression suite for the correctness pass, on a real-shaped storefront.

Every assertion here exists because the auditor once got that exact thing
wrong on a live site. The fixture is a deliberately faithful reconstruction of
a small speciality-food storefront: a collection page that offers nine sort
options and no filters, a visible "last updated" line, and product pages that
state a dozen attributes in prose while exposing almost none of them as typed
schema.org properties.

That combination is what produced the original false positives:

* "Category pages offer no filtering or sorting" - on a page with nine sort
  options.
* "Products expose almost no machine-readable attributes" - on pages listing
  cocoa butter content, origin, processing method and ingredients.
* "A visitor comparing options has nothing concrete to compare" - on pages
  full of things to compare.
* "Pages carry no machine-readable date" recommended as though no date
  existed - on a page printing one.
* Recommendations naming a footwear brand and running shoes.

The site is not the subject of the test. The auditor is. Nothing here asserts
a *good* score - the fixture has real defects and should be reported as
having them - only that what is reported is what was observed.
"""

from __future__ import annotations

import re
import unittest

from helpers import ORIGIN, bundle, find, html_doc, jsonld, page, run

# ---------------------------------------------------------------------------
# the fixture
# ---------------------------------------------------------------------------

SITE = "https://cocoacraft.example"

#: Nine sort options, no filter control. This is the shape that mattered.
SORT_FORM = (
    '<form method="get" action="/collections/cocoa-powders">'
    '<label for="SortBy">Sort by</label>'
    '<select name="sort_by" id="SortBy">'
    '<option value="manual">Featured</option>'
    '<option value="best-selling">Best selling</option>'
    '<option value="title-ascending">Alphabetically, A-Z</option>'
    '<option value="title-descending">Alphabetically, Z-A</option>'
    '<option value="price-ascending">Price, low to high</option>'
    '<option value="price-descending">Price, high to low</option>'
    '<option value="created-ascending">Date, old to new</option>'
    '<option value="created-descending">Date, new to old</option>'
    '</select></form>')

COLLECTION_BODY = (
    '<h1>Cocoa Powders</h1>'
    + SORT_FORM +
    '<ul>'
    '<li><a href="/products/natural-cocoa-powder">Natural Cocoa Powder</a></li>'
    '<li><a href="/products/dutch-cocoa-powder">Dutch Processed Cocoa Powder</a></li>'
    '</ul>'
    '<p>This data was last updated on 2026-09-01.</p>')

#: Attributes stated in visible copy, none of them typed.
PRODUCT_BODY = (
    '<h1>Natural Cocoa Powder</h1>'
    '<p>INR 450.00</p>'
    '<div>'
    '<p>Cocoa butter content: 22%</p>'
    '<p>Origin: Idukki, Kerala</p>'
    '<p>Processing method: Natural, unalkalised</p>'
    '<p>Colour: Deep reddish brown</p>'
    '<p>Net weight: 250 g</p>'
    '<p>Ingredients: 100% cocoa solids</p>'
    '<p>Suitable for: Baking, beverages, ice cream</p>'
    '</div>'
    '<p>In stock. Free shipping on orders over INR 999. '
    'Returns accepted within 7 days of delivery.</p>'
    '<button>Add to cart</button>'
    '<a href="/collections/cocoa-powders">Back to Cocoa Powders</a>'
    '<a href="/products/dutch-cocoa-powder">Dutch Processed Cocoa Powder</a>'
    '<a href="/pages/shipping">Shipping</a><a href="/pages/returns">Returns</a>'
    '<a href="/pages/about">About</a><a href="/pages/contact">Contact</a>')

#: A Product node with a price and nothing else typed - the common real case.
THIN_PRODUCT_LD = ('{"@context":"https://schema.org","@type":"Product",'
                   '"name":"Natural Cocoa Powder",'
                   '"offers":{"@type":"Offer","price":"450.00",'
                   '"priceCurrency":"INR",'
                   '"availability":"https://schema.org/InStock"}}')

ORG_LD = ('{"@context":"https://schema.org","@type":"Organization",'
          '"@id":"https://cocoacraft.example/#organization",'
          '"name":"CocoaCraft","url":"https://cocoacraft.example/"}')


def cocoacraft_bundle() -> dict:
    home = page(SITE + "/", html_doc(title="CocoaCraft", canonical=SITE + "/",
                                     head=jsonld(ORG_LD),
                                     body='<h1>CocoaCraft</h1>'
                                          '<a href="/collections/cocoa-powders">Cocoa Powders</a>'))
    collection = page(SITE + "/collections/cocoa-powders",
                      html_doc(title="Cocoa Powders",
                               canonical=SITE + "/collections/cocoa-powders",
                               body=COLLECTION_BODY))
    product_one = page(SITE + "/products/natural-cocoa-powder",
                       html_doc(title="Natural Cocoa Powder",
                                canonical=SITE + "/products/natural-cocoa-powder",
                                head=jsonld(THIN_PRODUCT_LD), body=PRODUCT_BODY))
    product_two = page(SITE + "/products/dutch-cocoa-powder",
                       html_doc(title="Dutch Processed Cocoa Powder",
                                canonical=SITE + "/products/dutch-cocoa-powder",
                                head=jsonld(THIN_PRODUCT_LD.replace(
                                    "Natural Cocoa Powder",
                                    "Dutch Processed Cocoa Powder")),
                                body=PRODUCT_BODY.replace(
                                    "Natural Cocoa Powder",
                                    "Dutch Processed Cocoa Powder")))
    data = bundle([home, collection, product_one, product_two])
    data["site"] = {"input": SITE, "origin": SITE, "host": "cocoacraft.example",
                    "registrable_host": "cocoacraft.example",
                    "home_url": SITE + "/", "entry_url": SITE + "/collections/cocoa-powders",
                    "entry_is_home": False, "scheme": "https"}
    return data


def all_findings(data: dict):
    out = []
    for skill in ("crawl-render-audit", "machine-readability-audit",
                  "freshness-corroboration", "entity-audit", "engagement-audit"):
        out.extend(run(skill, data))
    return out


# ---------------------------------------------------------------------------
# extraction: the facts the rules depend on
# ---------------------------------------------------------------------------

class TestCocoaCraftExtraction(unittest.TestCase):

    def setUp(self):
        self.data = cocoacraft_bundle()
        self.collection = self.data["pages"][1]
        self.product = self.data["pages"][2]

    def test_collection_has_sorting_and_no_filtering(self):
        forms = self.collection["forms"]
        self.assertTrue(forms["has_sort_controls"],
                        "nine sort options must register as sort controls")
        self.assertFalse(forms["has_filter_controls"],
                         "this collection genuinely offers no filtering")

    def test_visible_freshness_date_is_detected(self):
        visible = self.collection["dates"]["visible_updated"]
        self.assertTrue(visible, "the visible last-updated line must be observed")
        self.assertEqual(visible[0]["date"], "2026-09-01")

    def test_no_machine_readable_freshness_signal(self):
        self.assertEqual(self.collection["dates"]["time_elements"], [])
        self.assertNotIn("last-modified", {k.lower() for k in self.collection["headers"]})

    def test_product_states_attributes_in_visible_copy(self):
        labels = {p["label"].lower() for p in self.product["visible_attribute_pairs"]}
        for expected in ("cocoa butter content", "origin", "processing method",
                         "net weight", "ingredients"):
            self.assertIn(expected, labels)

    def test_product_structured_attributes_are_absent(self):
        from aiva.analysis import structured_attribute_presence
        self.assertEqual(structured_attribute_presence(self.product)["count"], 0)


# ---------------------------------------------------------------------------
# the findings themselves
# ---------------------------------------------------------------------------

class TestCocoaCraftFindings(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = cocoacraft_bundle()
        cls.findings = all_findings(cls.data)

    # -- ISSUE 1 ---------------------------------------------------------
    def test_no_finding_claims_sorting_is_absent(self):
        self.assertIsNone(find(self.findings, "EG-SORT-CONTROLS-ABSENT"),
                          "sorting is present on the only category page")
        self.assertIsNone(find(self.findings, "EG-FILTERS-MISSING"),
                          "the conflated filter/sort rule must be retired")

    def test_a_two_item_collection_is_not_asked_for_filters(self):
        """The collection lists two products. Filtering is an affordance of a
        set large enough to need it; asking a two-item page for facets is the
        page-type-is-enough mistake, so the listing is set aside instead."""
        self.assertIsNone(find(self.findings, "EG-FILTER-CONTROLS-ABSENT"))

    def test_missing_filtering_is_reported_and_names_the_sorting(self):
        """On a collection large enough to need filtering, its absence is
        reported and the evidence names the sorting the page does offer."""
        data = cocoacraft_bundle()
        grid = "".join(f'<li><a href="/products/cocoa-{i}">Cocoa {i}</a></li>'
                       for i in range(1, 10))
        big = page(SITE + "/collections/cocoa-powders",
                   html_doc(title="Cocoa Powders", canonical=SITE + "/collections/cocoa-powders",
                            body=COLLECTION_BODY.replace("</ul>", grid + "</ul>")))
        data["pages"][1] = big
        item = find(all_findings(data), "EG-FILTER-CONTROLS-ABSENT")
        self.assertIsNotNone(item, "filtering really is absent and should be reported")
        self.assertIn("do expose sort controls", item.evidence)

    # -- ISSUE 2 ---------------------------------------------------------
    def test_attributes_finding_does_not_claim_information_is_absent(self):
        item = find(self.findings, "MR-ATTRIBUTES-THIN")
        self.assertIsNotNone(item)
        self.assertIn("visible content", item.evidence)
        self.assertIn("additionalProperty", item.evidence)
        for banned in ("almost no", "nothing to filter", "nothing to compare"):
            self.assertNotIn(banned, item.evidence.lower())
        # It must name attributes it actually saw on this site.
        observed_names = " ".join(item.metrics["observed_visible_attributes"]).lower()
        self.assertIn("cocoa butter", observed_names)

    # -- ISSUE 3 ---------------------------------------------------------
    def test_spec_finding_is_about_structure_not_absence(self):
        item = find(self.findings, "EG-SPECS-MISSING")
        if item is None:
            return  # suppressed by sampling; nothing to assert
        self.assertIn("specification structure", item.title.lower())
        self.assertIn("do state attributes in visible copy", item.evidence)
        self.assertNotIn("nothing concrete to compare", item.evidence.lower())

    # -- ISSUE 4 ---------------------------------------------------------
    def test_freshness_finding_acknowledges_the_visible_date(self):
        item = find(self.findings, "FC-NO-DATE-SIGNALS")
        if item is None:
            return
        self.assertGreaterEqual(item.metrics["visible_freshness_signal"], 1)
        self.assertIn("visible content", item.evidence)
        joined = " ".join(step.lower() for step in item.suggested_action.steps)
        self.assertIn("keep the visible date", joined)

    # -- ISSUE 5 ---------------------------------------------------------
    def test_lead_finding_makes_no_viewport_or_behaviour_claim(self):
        item = find(self.findings, "EG-LEAD-ANSWER-WEAK")
        if item is None:
            return
        self.assertEqual(item.metrics["render_mode"], "static-fetch")
        self.assertIsNone(item.metrics["viewport"])
        text = (item.evidence + " " + item.title).lower()
        for banned in ("carousel", "modal", "bounce", "above the fold", "first screen"):
            self.assertNotIn(banned, text)

    # -- ISSUE 8 ---------------------------------------------------------
    def test_every_finding_separates_observation_from_interpretation(self):
        for item in self.findings:
            with self.subTest(rule=item.rule_id):
                self.assertTrue(item.observation.strip())
                self.assertTrue(item.reasoning.strip(),
                                "a finding must say what its observation may mean")
                self.assertEqual(item.problems(), [])

    # -- ISSUE 9 ---------------------------------------------------------
    def test_verification_steps_declare_how_they_can_be_checked(self):
        from aiva.findings import VERIFICATION_TYPES
        for item in self.findings:
            action = item.suggested_action
            if not action.verification:
                continue
            with self.subTest(rule=item.rule_id):
                self.assertIn(action.verification_type, VERIFICATION_TYPES)
                lowered = action.verification.lower()
                if "ask an assistant" in lowered or "segment analytics" in lowered:
                    self.assertNotEqual(
                        action.verification_type, "self_verifiable",
                        "a step the auditor cannot run must not be labelled self-verifiable")


# ---------------------------------------------------------------------------
# ISSUE 6 - nothing from another website may appear in the output
# ---------------------------------------------------------------------------

#: Text from the running-shoe worked examples that used to be hardcoded into
#: the rule set. If any of it reaches a report about a cocoa storefront, the
#: examples are not being derived from evidence.
FOREIGN_DOMAIN_MARKERS = (
    "garuda", "velocity x9", "vx9", "running shoe", "running shoes",
    "flat feet", "waterproof", "cushioned", "footwear", "uk 9",
    "engineered mesh", "under 6000", "250g", "lightest", "aero sports",
    "acme footwear", "bengaluru",
)


class TestNoForeignDomainContamination(unittest.TestCase):
    """A report about one site must not describe another one."""

    @classmethod
    def setUpClass(cls):
        from aiva.recommend import build_opportunities
        cls.data = cocoacraft_bundle()
        cls.findings = all_findings(cls.data)
        cls.opportunities = build_opportunities(cls.data, cls.findings)

    def _scan(self, text: str, where: str):
        lowered = text.lower()
        for marker in FOREIGN_DOMAIN_MARKERS:
            if re.search(r"\b" + re.escape(marker) + r"\b", lowered):
                self.fail(f"{where} mentions {marker!r}, which belongs to a different "
                          f"website than the one audited")

    def test_findings_contain_no_foreign_examples(self):
        for item in self.findings:
            payload = json_dump(item.to_dict())
            self._scan(payload, f"finding {item.rule_id}")

    def test_proactive_recommendations_contain_no_foreign_examples(self):
        for opportunity in self.opportunities:
            self._scan(json_dump(opportunity), f"opportunity {opportunity['id']}")

    def test_examples_name_this_site(self):
        """Worked examples must be about the audited catalogue."""
        from aiva import examples
        from aiva.analysis import site_vocabulary
        vocab = site_vocabulary(self.data)
        self.assertEqual(vocab["organization"], "CocoaCraft")
        self.assertIn("Cocoa Powder", vocab["product"] or "")
        snippet = examples.product_jsonld(vocab)
        self.assertIn("CocoaCraft", snippet)
        self._scan(snippet, "the Product JSON-LD example")

    def test_placeholders_are_used_when_nothing_was_observed(self):
        """With no evidence to draw on, examples fall back to blanks - not to guesses."""
        from aiva import examples
        from aiva.analysis import site_vocabulary
        vocab = site_vocabulary({"pages": [], "site": {}})
        snippet = examples.product_jsonld(vocab)
        self.assertIn("<Product Name>", snippet)
        self.assertIn("<Attribute>", snippet)
        self._scan(snippet, "the empty-bundle example")


def json_dump(value) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# v1.4.0 correctness pass: a storefront with a separate legal entity
# ---------------------------------------------------------------------------

#: The second regression storefront. Its distinguishing feature is entirely
#: structural and common: the trading name is short, the registered company
#: behind it is different, the footer names the company rather than the brand,
#: and the utility pages are correctly excluded from indexing. Every one of
#: those is good practice, and each of them produced a false positive.
LEGAL_SITE = "https://plimsole.example"

LEGAL_ORG_LD = ('{"@context":"https://schema.org","@type":"Organization",'
                '"@id":"https://plimsole.example/#organization",'
                '"name":"Plimsole","legalName":"PL DNAM LLC",'
                '"url":"https://plimsole.example/",'
                '"logo":"https://plimsole.example/logo.png"}')

LEGAL_FOOTER = ('<footer><p>PL DNAM LLC &copy; 2026 . All Rights Reserved &reg;</p>'
                '</footer>')


def legal_entity_bundle() -> dict:
    """A site whose legal name, trading name and footer holder all differ."""
    home = page(LEGAL_SITE + "/", html_doc(
        title="Plimsole", canonical=LEGAL_SITE + "/", head=jsonld(LEGAL_ORG_LD),
        body='<h1>Plimsole</h1><a href="/collections/all">Shop</a>' + LEGAL_FOOTER))
    collection = page(LEGAL_SITE + "/collections/all", html_doc(
        title="All | Plimsole", canonical=LEGAL_SITE + "/collections/all",
        body='<h1>All</h1><a href="/products/one">One</a>' + LEGAL_FOOTER))
    # Utility pages correctly excluded from indexing - the conventional setup.
    utility = [page(LEGAL_SITE + path, html_doc(
        title="Utility", canonical=LEGAL_SITE + path,
        head='<meta name="robots" content="noindex">',
        body='<h1>Utility</h1>' + LEGAL_FOOTER))
        for path in ("/cart", "/account", "/search?q=x")]
    data = bundle([home, collection] + utility)
    data["site"] = {"input": LEGAL_SITE, "origin": LEGAL_SITE,
                    "host": "plimsole.example", "registrable_host": "plimsole.example",
                    "home_url": LEGAL_SITE + "/", "entry_url": LEGAL_SITE + "/",
                    "entry_is_home": True, "scheme": "https"}
    return data


class TestEmptyStateDoesNotLeakIntoExamples(unittest.TestCase):
    """An empty-state listing page must not name the site's category.

    Regression: a collection page served 200 with an ordinary <h1> reading
    "Uh-Oh, Nothing To See Here!" had that string read as the site's category
    noun, and it then appeared as the <Category> value in every generic
    example in the report.
    """

    EMPTY_SITE = "https://quire.example"

    def _bundle(self, listing_body: str, extra=()):
        home = page(self.EMPTY_SITE + "/", html_doc(
            title="Quire", canonical=self.EMPTY_SITE + "/", body="<h1>Quire</h1>"))
        listing = page(self.EMPTY_SITE + "/collections/all", html_doc(
            title="All", canonical=self.EMPTY_SITE + "/collections/all",
            body=listing_body))
        data = bundle([home, listing] + list(extra))
        data["site"] = {"origin": self.EMPTY_SITE, "host": "quire.example",
                        "home_url": self.EMPTY_SITE + "/"}
        return data

    def test_empty_state_heading_is_not_adopted_as_the_category(self):
        from aiva.analysis import site_vocabulary
        vocab = site_vocabulary(self._bundle(
            "<h1>Uh-Oh, Nothing To See Here!</h1><p>Try another search.</p>"))
        self.assertIsNone(vocab["category"])

    def test_the_generic_example_falls_back_to_a_placeholder(self):
        from aiva import examples
        from aiva.analysis import site_vocabulary
        snippet = examples.breadcrumb_jsonld(site_vocabulary(self._bundle(
            "<h1>Uh-Oh, Nothing To See Here!</h1>")))
        self.assertIn("<Category>", snippet)
        self.assertNotIn("Uh-Oh", snippet)
        self.assertNotIn("Nothing To See Here", snippet)

    def test_a_populated_listing_is_still_used(self):
        from aiva.analysis import site_vocabulary
        product_ld = ('{"@context":"https://schema.org","@type":"Product",'
                      '"name":"Ledger Pad"}')
        product = page(self.EMPTY_SITE + "/products/ledger-pad", html_doc(
            canonical=self.EMPTY_SITE + "/products/ledger-pad",
            head=jsonld(product_ld), body="<h1>Ledger Pad</h1>"))
        vocab = site_vocabulary(self._bundle(
            '<h1>Paper Goods</h1><a href="/products/ledger-pad">Ledger Pad</a>',
            extra=[product]))
        self.assertEqual(vocab["category"], "Paper Goods")


class TestReviewFindingsAreDisjoint(unittest.TestCase):
    """Two review findings, two pillars, and never the same page in both.

    They are genuinely independent dimensions - one is a retrieval-visibility
    problem, the other a structured-data problem - so both are kept. What was
    wrong was that the machine-readability rule did not test the visibility its
    own title claimed, so a client-rendered page was reported by both rules and
    the same absence was scored against two pillars.
    """

    SCRIPTS = "".join(f'<script src="https://cdn{i}.example/w.js"></script>'
                      for i in range(6))
    PRODUCT_LD = '{"@context":"https://schema.org","@type":"Product","name":"Pad"}'

    def setUp(self):
        deferred = page(ORIGIN + "/products/deferred", html_doc(
            canonical=ORIGIN + "/products/deferred",
            head=jsonld(self.PRODUCT_LD) + self.SCRIPTS,
            body="<h1>Pad</h1><p>Read our customer reviews and ratings.</p>"))
        untyped = page(ORIGIN + "/products/untyped", html_doc(
            canonical=ORIGIN + "/products/untyped", head=jsonld(self.PRODUCT_LD),
            body="<h1>Pad B</h1><p>Rated 4.5 from 12 customer reviews.</p>"))
        self.data = bundle([deferred, untyped])
        self.mr = find(run("machine-readability-audit", self.data),
                       "MR-REVIEW-MARKUP-MISSING")
        self.eg = find(run("engagement-audit", self.data),
                       "EG-REVIEWS-CLIENT-RENDERED")

    def test_both_findings_are_kept(self):
        self.assertIsNotNone(self.mr, "the untyped page is a real markup finding")
        self.assertIsNotNone(self.eg, "the scripted page is a real visibility finding")
        self.assertNotEqual(self.mr.pillar, self.eg.pillar)

    def test_no_page_is_counted_by_both(self):
        overlap = set(self.mr.affected_urls) & set(self.eg.affected_urls)
        self.assertEqual(overlap, set(),
                         "one observation must not be scored against two pillars")

    def test_the_relationship_is_stated_not_implied(self):
        self.assertEqual(self.mr.metrics["excluded_as_client_rendered"], 1)
        self.assertEqual(self.mr.metrics["related_rule"], "EG-REVIEWS-CLIENT-RENDERED")
        self.assertIn("reported separately", self.mr.evidence)


class TestLegalEntityStorefront(unittest.TestCase):
    """Correct practice must not be reported as a defect."""

    @classmethod
    def setUpClass(cls):
        cls.data = legal_entity_bundle()
        cls.findings = all_findings(cls.data)

    def test_separate_legal_entity_is_not_a_brand_inconsistency(self):
        self.assertIsNone(find(self.findings, "EN-NAME-INCONSISTENT"),
                          "a registered company name differing from the trading "
                          "name is normal, not a naming defect")

    def test_noindexed_utility_pages_are_not_reported(self):
        self.assertIsNone(find(self.findings, "CR-NOINDEX-ON-IMPORTANT-PAGES"),
                          "carts, accounts and internal search are conventionally "
                          "excluded from indexes")

    def test_the_findings_it_does_produce_are_all_valid(self):
        for item in self.findings:
            with self.subTest(rule=item.rule_id):
                self.assertEqual(item.problems(), [])
                self.assertTrue(item.reasoning.strip())

    def test_no_foreign_domain_language_in_this_report(self):
        import json as _json
        for item in self.findings:
            lowered = _json.dumps(item.to_dict(), ensure_ascii=False).lower()
            for marker in FOREIGN_DOMAIN_MARKERS:
                self.assertNotIn(marker, lowered, f"{item.rule_id} mentions {marker!r}")
