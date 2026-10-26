"""Evidence-provenance regressions from a live multi-market audit.

An audit entered at ``https://www.ikea.com/in/en/`` produced three findings
whose evidence did not support what they claimed. None of them was a wrong
*conclusion* - each was a wrong *citation*, which is worse, because a reader
who checks the cited page finds nothing there and stops trusting the report.

1. **The quotation did not contain the fact.** "What is the return window?"
   was answered ``partial - stated in prose`` and quoted
   ``"Skip to main content Stories Jobs Newsroom Our business ... Privacy and
   Cookie statement"`` from a privacy page - the first 160 characters of the
   document, because the snippet helper was called with no needle. The site's
   actual return-policy page had been crawled and was not cited. Separately,
   "What payment methods are accepted?" was resolved against the
   ``add_to_cart`` concept, so a page with a cart button "answered" it.

2. **The citation was not the page type claimed.** ``MR-PRODUCT-SCHEMA-MISSING``
   reported "1 of 16 identified product page(s)" and cited
   ``https://www.ikea.com/in/en/`` - a country front door, classified
   ``product`` because it carries prices, a cart control and variant swatches.

3. **The scope was not the site.** The crawl followed the market selector into
   Estonia, the Emirates, Canada and Morocco, then aggregated "33 of 38 sampled
   pages" across all of them. Those are different catalogues, prices and
   policies; the ratio described no site that exists.

The fixture ``site_locales`` reproduces all three shapes.
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, html_doc, page, rule_ids, run, find

from aiva import localserve, orchestrator
from aiva.answerability import build_matrix, quote_concept
from aiva.config import AuditConfig
from aiva.discover import build_frontier, in_locale_scope, locale_prefix
from aiva import evidence as ev
from aiva.extract import NON_PRODUCT_PAGE_TYPES, classify_page
from aiva.findings import Finding, SuggestedAction, EvidenceItem
from aiva.paths import MARKETPLACE_ROOT
from aiva.report import _page_type_problems, _page_type_index, build_report

FIXTURE = MARKETPLACE_ROOT / "tests" / "fixtures" / "site_locales"

#: The exact text that was quoted as IKEA's statement of its return window.
IKEA_PRIVACY_CHROME = (
    "Skip to main content Stories Jobs Newsroom Our business Open main menu "
    "Close main menu Stories Jobs Newsroom Our business Privacy and Cookie "
    "statement Updated 1")

#: The exact text that was quoted as its statement of accepted payment methods.
IKEA_HOME_CHROME = (
    "Skip to main content EN AE English Select store Products Rooms Offers "
    "Design & ideas Services Clear the search input field Search Search Hej! "
    "Log in or sign up")


# ---------------------------------------------------------------------------
# 1. a quotation must contain the fact it is offered as evidence of
# ---------------------------------------------------------------------------

class TestQuotationsContainTheFact(unittest.TestCase):

    def test_navigation_chrome_cannot_evidence_a_return_window(self):
        page_facts = {"main_text": "", "text": IKEA_PRIVACY_CHROME}
        self.assertIsNone(quote_concept(page_facts, "returns"))

    def test_navigation_chrome_cannot_evidence_payment_methods(self):
        page_facts = {"main_text": "", "text": IKEA_HOME_CHROME}
        self.assertIsNone(quote_concept(page_facts, "payment"))

    def test_a_real_statement_is_quoted_around_the_phrase(self):
        prose = ("Delivery and assembly. You can return any item within 365 days of "
                 "delivery, unused and in its original packaging, for a full refund.")
        quote = quote_concept({"main_text": prose, "text": prose}, "returns")
        self.assertIsNotNone(quote)
        self.assertIn(quote["phrase"].lower(), quote["quote"].lower())
        self.assertIn("365 days", quote["quote"])
        # ...and it opens at the sentence, not a fixed distance before the word.
        self.assertTrue(quote["quote"].startswith("You can return"),
                        quote["quote"])

    def test_the_content_region_is_preferred_over_the_chrome(self):
        facts = {"main_text": "We accept credit card and UPI on all orders.",
                 "text": IKEA_HOME_CHROME + " We accept credit card and UPI on all orders."}
        quote = quote_concept(facts, "payment")
        self.assertEqual(quote["region"], "main content")
        self.assertNotIn("Skip to main content", quote["quote"])

    def test_a_returns_sentence_does_not_answer_a_shipping_question(self):
        """The residual case found by reading the fixed report's own evidence.

        "You can return any item within 365 days of delivery" contains a
        shipping word and answers nothing about where the site ships or what it
        costs. It was quoted for `shipping_destinations` because the concept
        matched; the collocation is now an anti-phrase.
        """
        returns_prose = ("Return policy. You can return any item within 365 days of "
                         "delivery, unused and in its original packaging.")
        self.assertIsNone(quote_concept({"main_text": returns_prose,
                                         "text": returns_prose}, "shipping"))

    def test_a_real_shipping_statement_still_matches(self):
        prose = "Standard delivery is free over 2,000 and takes 2-5 business days."
        quote = quote_concept({"main_text": prose, "text": prose}, "shipping")
        self.assertIsNotNone(quote)
        self.assertIn("free over", quote["quote"])

    def test_diacritics_survive_the_match(self):
        prose = "Devoluciones gratuitas en 30 días desde la entrega."
        quote = quote_concept({"main_text": prose, "text": prose}, "returns")
        self.assertIn("días", quote["quote"])


class TestPaymentIsNotACartButton(unittest.TestCase):
    """`payment_options` used to be resolved against the `add_to_cart` concept."""

    def _matrix(self, pages):
        return build_matrix(bundle(pages))

    def test_a_cart_page_does_not_answer_the_payment_question(self):
        product = page(ORIGIN + "/products/x9", html_doc(
            title="X9", body='<h1>X9</h1><p>INR 5,499</p>'
                             '<button name="add-to-cart">Add to cart</button>'))
        matrix = self._matrix([page(ORIGIN + "/", html_doc()), product])
        payment = [q for q in matrix["questions"] if q["kind"] == "payment_options"]
        if payment:                      # only generated for commerce sites
            self.assertEqual(payment[0]["status"], "not_answerable", payment[0])
            self.assertNotIn("Add to cart", payment[0]["evidence"])

    def test_a_real_payment_statement_is_accepted(self):
        policy = page(ORIGIN + "/pages/payment", html_doc(
            title="Payment", body="<h1>Payment</h1><p>We accept credit card, "
                                  "debit card and UPI.</p>"))
        product = page(ORIGIN + "/products/x9", html_doc(
            title="X9", body='<h1>X9</h1><p>INR 5,499</p>'
                             '<button name="add-to-cart">Add to cart</button>'))
        matrix = self._matrix([page(ORIGIN + "/", html_doc()), product, policy])
        payment = [q for q in matrix["questions"] if q["kind"] == "payment_options"]
        if payment:
            self.assertEqual(payment[0]["status"], "partial")
            self.assertIn("We accept", payment[0]["evidence"])


# ---------------------------------------------------------------------------
# 2. a citation must be the page type the finding claims
# ---------------------------------------------------------------------------

class TestLocaleRootIsNotAProductPage(unittest.TestCase):

    def test_country_front_doors_classify_as_home(self):
        for url in ("https://example.com/in/en/", "https://example.com/ae/ar/",
                    "https://example.com/ca/fr/", "https://example.com/global/en/",
                    "https://example.com/en-gb/", "https://example.com/de/"):
            with self.subTest(url=url):
                self.assertEqual(classify_page(url), "home")

    def test_commerce_affordances_do_not_override_a_locale_root(self):
        """The signal combination that produced the misclassification."""
        facts = {"prices_in_text": ["3499"],
                 "variants": {"variant_selects": 1},
                 "forms": {"has_cart_action": True},
                 "mentions": {"add_to_cart": True},
                 "jsonld_types": []}
        self.assertEqual(classify_page("https://example.com/in/en/", facts), "home")

    def test_a_real_product_url_is_unaffected(self):
        self.assertEqual(
            classify_page("https://example.com/in/en/p/kallvik.html"), "product")

    def test_a_deeper_locale_path_is_not_a_home_page(self):
        self.assertNotEqual(classify_page("https://example.com/in/en/kitchen/"), "home")


class TestFindingsCiteThePageTypeTheyClaim(unittest.TestCase):

    def _finding(self, unit, cited_url):
        return Finding(
            rule_id="MR-PRODUCT-SCHEMA-MISSING",
            title="Product pages carry no Product structured data",
            severity="low", pillar="machine_readability",
            evidence="1 of 16 identified product page(s) contain no Product node.",
            evidence_items=[EvidenceItem(kind="absence", observation="no Product node",
                                         url=cited_url)],
            suggested_action=SuggestedAction(summary="Add Product JSON-LD."),
            metrics={"sample_unit": unit})

    def test_a_product_claim_citing_a_home_page_is_refused(self):
        index = {ORIGIN + "/in/en/": "home"}
        problems = _page_type_problems(
            self._finding("sampled product page(s)", ORIGIN + "/in/en/"), index)
        self.assertTrue(problems)
        self.assertIn("product", problems[0])

    def test_a_product_claim_citing_a_product_page_passes(self):
        index = {ORIGIN + "/p/x": "product"}
        self.assertEqual(
            _page_type_problems(self._finding("sampled product page(s)", ORIGIN + "/p/x"),
                                index), [])

    def test_a_rule_claiming_no_page_type_is_not_second_guessed(self):
        index = {ORIGIN + "/in/en/": "home"}
        self.assertEqual(
            _page_type_problems(self._finding("sampled page(s)", ORIGIN + "/in/en/"),
                                index), [])

    def test_listing_is_understood_as_category(self):
        index = {ORIGIN + "/collections/all": "category"}
        self.assertEqual(
            _page_type_problems(self._finding("sampled listing page(s)",
                                              ORIGIN + "/collections/all"), index), [])

    def test_a_url_the_crawl_never_classified_is_not_judged(self):
        """robots.txt, sitemaps and off-site anchors have no page type."""
        self.assertEqual(
            _page_type_problems(self._finding("sampled product page(s)",
                                              ORIGIN + "/robots.txt"), {}), [])

    def test_the_check_runs_inside_build_report(self):
        data = bundle([page(ORIGIN + "/", html_doc())])
        report = build_report(data, [self._finding("sampled product page(s)", ORIGIN + "/")],
                              AuditConfig(site=ORIGIN))
        self.assertEqual(report["summary"]["total_findings"], 0)
        self.assertEqual(report["diagnostics"]["rejected_finding_count"], 1)


# ---------------------------------------------------------------------------
# 3. one market per audit
# ---------------------------------------------------------------------------

class TestLocaleScope(unittest.TestCase):

    def test_locale_prefixes_are_recognised(self):
        self.assertEqual(locale_prefix("/in/en/"), "/in/en")
        self.assertEqual(locale_prefix("/ee/et/p/x/"), "/ee/et")
        self.assertEqual(locale_prefix("/global/en/support/"), "/global")
        self.assertIsNone(locale_prefix("/products/x9"))
        self.assertIsNone(locale_prefix("/"))

    def test_other_markets_are_out_of_scope(self):
        for url in ("https://x.example/ee/et/p/a/", "https://x.example/ae/ar/",
                    "https://x.example/ca/fr/"):
            with self.subTest(url=url):
                self.assertFalse(in_locale_scope(url, "/in/en"))

    def test_the_audited_market_neutral_and_unscoped_paths_stay_in(self):
        for url in ("https://x.example/in/en/p/a.html",
                    "https://x.example/global/en/support/",
                    "https://x.example/robots.txt",
                    "https://x.example/sitemaps/all.xml"):
            with self.subTest(url=url):
                self.assertTrue(in_locale_scope(url, "/in/en"))

    def test_a_site_without_locales_is_unaffected(self):
        self.assertTrue(in_locale_scope("https://x.example/products/x9", None))

    def test_the_frontier_drops_other_markets(self):
        site = {"origin": "https://x.example", "home_url": "https://x.example/",
                "entry_url": "https://x.example/in/en/", "locale_scope": "/in/en"}
        seed = {"page_type": "home", "links": {"internal": [
            {"url": "https://x.example/in/en/p/a.html"},
            {"url": "https://x.example/ee/et/p/b.html"},
            {"url": "https://x.example/ae/en/"},
            {"url": "https://x.example/global/en/privacy.html"},
        ]}}
        candidates, _ = build_frontier(site, [seed], [], AuditConfig(site=site["origin"]))
        urls = {url for url, _ in candidates}
        self.assertIn("https://x.example/in/en/p/a.html", urls)
        self.assertIn("https://x.example/global/en/privacy.html", urls)
        self.assertNotIn("https://x.example/ee/et/p/b.html", urls)
        self.assertNotIn("https://x.example/ae/en/", urls)
        self.assertEqual(site["out_of_locale_candidates"], 2)

    def test_a_sibling_subdomain_is_out_of_a_market_scoped_audit(self):
        """`www.inter.ikea.com` was crawled and folded into the ratios."""
        site = {"origin": "https://www.x.example", "home_url": "https://www.x.example/",
                "entry_url": "https://www.x.example/in/en/", "locale_scope": "/in/en"}
        seed = {"page_type": "home", "links": {"internal": [
            {"url": "https://corporate.x.example/"},
            {"url": "https://www.x.example/in/en/p/a.html"},
        ]}}
        candidates, _ = build_frontier(site, [seed], [],
                                       AuditConfig(site=site["origin"]))
        urls = {url for url, _ in candidates}
        self.assertNotIn("https://corporate.x.example/", urls)
        self.assertIn("https://www.x.example/in/en/p/a.html", urls)


# ---------------------------------------------------------------------------
# end to end, over the fixture that reproduces all three
# ---------------------------------------------------------------------------

class TestMultiMarketFixture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server, base = localserve.start(FIXTURE)
        try:
            config = AuditConfig(site=base + "/in/en/", request_delay_s=0.1,
                                 check_external=False)
            cls.bundle, cls.report = orchestrator.run_audit(config)
        finally:
            cls.server.shutdown()
            cls.server.server_close()
        cls.base = base

    def crawled(self):
        return [p.get("url", "") for p in self.bundle["pages"]]

    def test_the_audit_records_the_market_it_is_about(self):
        self.assertEqual(self.bundle["site"]["locale_scope"], "/in/en")
        self.assertEqual(self.report["coverage"]["locale_scope"], "/in/en")

    def test_no_other_market_was_crawled(self):
        strayed = [u for u in self.crawled() if "/ee/et" in u or "/ae/en" in u]
        self.assertEqual(strayed, [], f"crawled another market: {strayed}")

    def test_the_audited_market_was_crawled(self):
        self.assertTrue([u for u in self.crawled() if "/in/en/p/" in u],
                        "the market's own catalogue was not reached")

    def test_the_locale_root_is_not_counted_as_a_product_page(self):
        products = [p["url"] for p in self.bundle["pages"]
                    if p.get("page_type") == "product"]
        self.assertNotIn(self.base + "/in/en/", products)
        self.assertTrue(products)

    def test_the_return_question_cites_the_return_policy_page(self):
        rows = [q for q in self.report["answerability"]["questions"]
                if q["kind"] == "return_window"]
        self.assertTrue(rows)
        row = rows[0]
        self.assertIn("return-policy", row["citing_url"],
                      f"cited {row['citing_url']} instead of the return policy")
        self.assertIn("365 days", row["evidence"])

    def test_no_answerability_row_quotes_navigation_chrome(self):
        for row in self.report["answerability"]["questions"]:
            self.assertNotIn("Skip to main content", row.get("evidence", ""))
            self.assertNotIn("Choose your country", row.get("evidence", ""))

    def test_every_prose_answer_names_the_phrase_it_matched(self):
        for row in self.report["answerability"]["questions"]:
            if "stated in prose" in row.get("evidence", ""):
                self.assertIn("on the phrase", row["evidence"], row)

    def test_no_finding_was_rejected(self):
        self.assertEqual(self.report["diagnostics"]["rejected_finding_count"], 0,
                         self.report["diagnostics"]["rejected_findings"])

    def test_every_cited_url_belongs_to_the_audited_market(self):
        for finding in self.report["findings"]:
            for url in finding["affected_urls"]:
                if "/ee/et" in url or "/ae/en" in url:
                    self.fail(f"{finding['rule_id']} cites another market: {url}")


# ---------------------------------------------------------------------------
# 4. semantic page types — a second live report, after the first fix round
# ---------------------------------------------------------------------------

class TestNonProductPagesAreNotProducts(unittest.TestCase):
    """The live audit still called these product pages after 1.8.1.

    Neither URL matched a hint, so both fell to the content-signal branch,
    where "a price somewhere on the page" plus "a cart control" was enough.
    On a country site both are true of nearly every page: the cart lives in
    the site-wide header and a promotional strip carries a price.
    """

    def test_a_brand_programme_page_is_not_a_product(self):
        self.assertNotEqual(
            classify_page("https://www.ikea.com/in/en/ikea-family/"), "product")
        self.assertEqual(
            classify_page("https://www.ikea.com/in/en/ikea-family/"), "program")

    def test_the_brand_programme_rule_generalises(self):
        for url in ("https://www.tesco.com/uk/en/tesco-clubcard/",
                    "https://www.nike.com/gb/en/nike-membership/"):
            with self.subTest(url=url):
                self.assertEqual(classify_page(url), "program")

    def test_a_brand_prefixed_product_path_is_still_a_product(self):
        """The brand rule must not swallow `/ikea-products/…`."""
        self.assertEqual(
            classify_page("https://www.ikea.com/in/en/products/kallvik/"), "product")

    def test_generic_membership_vocabulary_also_lands_on_program(self):
        for url in ("https://shop.example/in/en/membership/",
                    "https://shop.example/loyalty/", "https://shop.example/rewards/"):
            with self.subTest(url=url):
                self.assertEqual(classify_page(url), "program")

    def test_an_offers_page_is_a_promotional_listing(self):
        self.assertEqual(
            classify_page("https://www.ikea.com/in/en/offers/"), "promotional")
        self.assertNotEqual(
            classify_page("https://www.ikea.com/in/en/offers/"), "product")

    def test_many_prices_and_a_header_cart_are_not_a_product_page(self):
        """The content-signal branch, given the shape it used to accept."""
        listing = {
            "prices_in_text": [{"value": v} for v in
                               ("999", "1299", "1499", "1999", "2499", "2999")],
            "h1_count": 1,
            "main_text": "Deals ₹999 ₹1299 ₹1499 ₹1999 ₹2499 ₹2999",
            "variants": {"variant_selects": 1},
            "forms": {"has_cart_action": True},
            "mentions": {"add_to_cart": True},
            "jsonld_types": [],
        }
        self.assertNotEqual(classify_page("https://x.example/in/en/weekly/", listing),
                            "product")

    def test_a_price_only_outside_the_content_region_is_not_a_product_page(self):
        """A promotional strip in a site-wide header put a price on every page."""
        facts = {
            "prices_in_text": [{"value": "2000"}], "h1_count": 1,
            "main_text": "Join our membership programme and get member benefits.",
            "variants": {"variant_selects": 1},
            "forms": {"has_cart_action": True},
            "mentions": {"add_to_cart": True}, "jsonld_types": [],
        }
        self.assertNotEqual(classify_page("https://x.example/in/en/join/", facts),
                            "product")

    def test_a_genuine_product_page_still_classifies_on_content_alone(self):
        """No URL hint, no markup: the content has to carry the whole decision.

        The buy control is *in the content region* and the heading names one
        item. Those two, with a single price and a swatch set, are what a
        detail page looks like when the site publishes no schema at all. The
        earlier version of this test put the cart control anywhere on the page,
        which on a storefront means the site-wide header - the signal that made
        `/in/en/offers/` and `/in/en/ikea-family/` products.
        """
        pdp = {
            "prices_in_text": [{"value": "3499"}], "h1_count": 1,
            "h1_texts": ["KALLVIK shelf unit"], "title": "KALLVIK shelf unit",
            "main_text": "KALLVIK shelf ₹3,499. In stock in Bengaluru.",
            "variants": {"variant_swatches": 2},
            "forms": {"has_cart_action": True, "has_cart_action_in_main": True},
            "mentions": {"add_to_cart": True}, "jsonld_types": [],
        }
        self.assertEqual(classify_page("https://x.example/in/en/kallvik-shelf/", pdp),
                         "product")


class TestSupportSectionIsNotAnFaq(unittest.TestCase):
    """`/support/` names a section, not a document type."""

    def test_a_complaint_form_under_support_is_a_contact_page(self):
        url = "https://www.ikea.com/global/en/support/contact-ikea-submit-complaint/"
        self.assertEqual(classify_page(url), "contact")
        self.assertNotEqual(classify_page(url), "faq")

    def test_a_real_faq_under_support_is_still_an_faq(self):
        self.assertEqual(
            classify_page("https://www.ikea.com/global/en/support/faq/"), "faq")

    def test_a_bare_support_hub_is_neither(self):
        self.assertEqual(
            classify_page("https://www.ikea.com/global/en/support/"), "support")

    def test_a_return_policy_under_customer_service_is_still_a_policy(self):
        """The generic tier must never outrank a specific one."""
        self.assertEqual(classify_page(
            "https://www.ikea.com/in/en/customer-service/returns-claims/return-policy/"),
            "policy")

    def test_declared_faq_markup_still_wins(self):
        self.assertEqual(
            classify_page("https://x.example/support/anything/",
                          {"jsonld_types": ["FAQPage"]}), "faq")


class TestKeywordAloneIsNotEvidence(unittest.TestCase):
    """A concept match is a pointer to the topic; an answer names a thing."""

    MUSEUM = ("If you book an event or a tour at the IKEA Museum, we collect your "
              "name, your contact details and a payment method in order to process "
              "the booking. We keep those records for seven years.")

    def _bundle_with_privacy_only(self):
        privacy = page(ORIGIN + "/global/en/legal/privacy-cookie-statement/",
                       html_doc(title="Privacy and cookie statement",
                                body=f"<h1>Privacy and cookie statement</h1><p>{self.MUSEUM}</p>"))
        product = page(ORIGIN + "/products/x9", html_doc(
            title="X9", body='<h1>X9</h1><p>INR 5,499</p>'
                             '<button name="add-to-cart">Add to cart</button>'))
        return bundle([page(ORIGIN + "/", html_doc()), product, privacy])

    def test_museum_payment_text_cannot_answer_the_purchase_question(self):
        matrix = build_matrix(self._bundle_with_privacy_only())
        rows = [q for q in matrix["questions"] if q["kind"] == "payment_options"]
        self.assertTrue(rows, "the payment question should still be generated")
        row = rows[0]
        self.assertEqual(row["status"], "not_answerable", row)
        self.assertNotIn("Museum", row["evidence"])
        self.assertNotIn("privacy-cookie-statement", row["citing_url"])

    def test_the_topic_matches_but_the_answer_set_does_not(self):
        """Both halves of the guard, stated directly."""
        from aiva import lexicon
        self.assertIsNotNone(lexicon.find("payment", self.MUSEUM))
        self.assertIsNone(lexicon.find("payment_instrument", self.MUSEUM))

    def test_a_real_acceptance_statement_satisfies_both(self):
        from aiva import lexicon
        real = "We accept credit card, debit card, UPI and net banking on all orders."
        self.assertIsNotNone(lexicon.find("payment", real))
        self.assertIsNotNone(lexicon.find("payment_instrument", real))

    def test_a_privacy_page_is_excluded_by_identity_as_well(self):
        """Belt and braces: even with an instrument in it, a privacy statement
        is not the site's statement of what it accepts at checkout."""
        privacy = page(ORIGIN + "/legal/privacy/", html_doc(
            title="Privacy statement",
            body="<h1>Privacy</h1><p>We store the last four digits of your "
                 "credit card so that payment methods can be reconciled.</p>"))
        product = page(ORIGIN + "/products/x9", html_doc(
            title="X9", body='<h1>X9</h1><p>INR 5,499</p>'
                             '<button name="add-to-cart">Add to cart</button>'))
        matrix = build_matrix(bundle([page(ORIGIN + "/", html_doc()), product, privacy]))
        rows = [q for q in matrix["questions"] if q["kind"] == "payment_options"]
        if rows:
            self.assertNotIn("privacy", rows[0]["citing_url"])


class TestProductRulesDoNotRunOnNonProductPages(unittest.TestCase):
    """Requirement 4, asserted end to end over the reconstructed shapes."""

    PRODUCT_RULES = frozenset({
        "AN-UNANSWERABLE-PRODUCT-AVAILABILITY",
        "AN-UNANSWERABLE-PRODUCT-SPECIFICATIONS",
        "EG-AVAILABILITY-INVISIBLE", "MR-PRODUCT-SCHEMA-MISSING",
        "EG-LEAD-ANSWER-WEAK", "EG-SPECS-MISSING", "MR-BREADCRUMB-MISSING",
        "EG-COMPARISON-UNSUPPORTED", "MR-OFFER-MISSING", "MR-IDENTIFIERS-MISSING",
        "CR-THIN-PRODUCT-HTML", "EG-CTA-NOT-IN-HTML", "EG-REVIEWS-ABSENT",
    })

    NON_PRODUCT_PATHS = ("/in/en/offers/", "/in/en/membership/",
                         "/global/en/support/contact-us-complaint.html",
                         "/global/en/privacy.html", "/in/en/")

    @classmethod
    def setUpClass(cls):
        cls.server, base = localserve.start(FIXTURE)
        try:
            config = AuditConfig(site=base + "/in/en/", request_delay_s=0.1,
                                 check_external=False)
            cls.bundle, cls.report = orchestrator.run_audit(config)
        finally:
            cls.server.shutdown()
            cls.server.server_close()
        cls.base = base

    def page_type(self, path):
        for page_facts in self.bundle["pages"]:
            if page_facts.get("url") == self.base + path:
                return page_facts.get("page_type")
        return None

    def test_the_reconstructed_shapes_classify_correctly(self):
        self.assertEqual(self.page_type("/in/en/offers/"), "promotional")
        self.assertEqual(self.page_type("/in/en/membership/"), "program")
        self.assertEqual(
            self.page_type("/global/en/support/contact-us-complaint.html"), "contact")

    def test_no_product_rule_cites_a_non_product_page(self):
        for finding in self.report["findings"]:
            if finding["rule_id"] not in self.PRODUCT_RULES:
                continue
            for url in finding["affected_urls"]:
                path = url.replace(self.base, "")
                self.assertNotIn(path, self.NON_PRODUCT_PATHS,
                                 f"{finding['rule_id']} sampled {path} as a product")

    def test_product_subjects_are_only_product_pages(self):
        for row in self.report["answerability"]["questions"]:
            if not row["kind"].startswith("product_"):
                continue
            path = (row["citing_url"] or "").replace(self.base, "")
            self.assertNotIn(path, self.NON_PRODUCT_PATHS,
                             f"{row['kind']} treated {path} as a product")

    def test_no_answerability_row_cites_the_privacy_page(self):
        for row in self.report["answerability"]["questions"]:
            self.assertNotIn("privacy", row.get("citing_url", ""),
                             f"{row['kind']} cited the privacy statement")

    def test_the_payment_answer_comes_from_a_real_acceptance_statement(self):
        rows = [q for q in self.report["answerability"]["questions"]
                if q["kind"] == "payment_options"]
        self.assertTrue(rows)
        if rows[0]["status"] != "not_answerable":
            self.assertIn("accept", rows[0]["evidence"].lower())
            self.assertNotIn("Museum", rows[0]["evidence"])

    def test_nothing_was_rejected(self):
        self.assertEqual(self.report["diagnostics"]["rejected_finding_count"], 0,
                         self.report["diagnostics"]["rejected_findings"])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# 5. conservative under uncertainty — the principle, as assertions
# ---------------------------------------------------------------------------

class TestConservativeUnderUncertainty(unittest.TestCase):
    """A page becomes an individual product on evidence, never on a hint.

    The live sequence that produced this class: `/in/en/ikea-family/` and
    `/in/en/offers/` were products, then they were not and `/in/en/planners/`
    was. Each fix removed one shape; none of them changed the underlying rule,
    which was "a price somewhere plus a cart control somewhere". On a
    storefront the cart control is in the header of every page, so that rule
    reduces to "mentions a price" - and a planner landing page, an offers hub
    and a loyalty programme all mention a price.
    """

    def _facts(self, **over):
        base = {
            "prices_in_text": [{"value": "4999"}], "h1_count": 1,
            "title": "Something", "h1_texts": ["Something"],
            "main_text": "Something ₹4,999", "variants": {},
            "forms": {"has_cart_action": True, "has_cart_action_in_main": True},
            "mentions": {"add_to_cart": True}, "jsonld_types": [],
        }
        base.update(over)
        return base

    # -- the false positives, one per live report ---------------------------

    def test_a_planner_landing_page_is_not_a_product(self):
        self.assertEqual(classify_page("https://www.ikea.com/in/en/planners/"), "tool")

    def test_the_planner_rule_generalises_beyond_one_word(self):
        for url in ("https://x.example/kitchen-planner/",
                    "https://x.example/en/configurator/",
                    "https://x.example/build-your-own/",
                    "https://x.example/room-planner/"):
            with self.subTest(url=url):
                self.assertNotEqual(classify_page(url), "product")

    def test_a_planner_at_an_unrecognisable_url_is_still_not_a_product(self):
        """No URL hint, so only the content branch can decide."""
        facts = self._facts(title="Design and planning | Nordhaus",
                            h1_texts=["Design and planning"],
                            main_text="Plan your kitchen. Appointments from ₹1,499.",
                            forms={"has_cart_action": True,
                                   "has_cart_action_in_main": False})
        self.assertNotEqual(classify_page("https://x.example/in/en/dp-2024/", facts),
                            "product")

    def test_a_header_cart_control_is_not_evidence_about_the_page(self):
        """The signal that made every page of a storefront look like a product."""
        facts = self._facts(forms={"has_cart_action": True,
                                   "has_cart_action_in_main": False},
                            variants={})
        self.assertNotEqual(classify_page("https://x.example/in/en/anything/", facts),
                            "product")

    def test_a_hub_heading_vetoes_the_content_branch(self):
        for heading in ("Our range", "Explore ideas", "Shop all", "Services",
                        "How to measure", "Book an appointment"):
            with self.subTest(heading=heading):
                facts = self._facts(title=heading, h1_texts=[heading])
                self.assertNotEqual(
                    classify_page("https://x.example/x/y/", facts), "product")

    # -- and the other direction: detection must survive --------------------

    def test_an_explicit_product_url_is_still_a_product(self):
        for url in ("https://x.example/products/x9", "https://x.example/p/12345",
                    "https://x.example/in/en/p/kallvik-s123/"):
            with self.subTest(url=url):
                self.assertEqual(classify_page(url), "product")

    def test_a_hub_heading_and_a_product_token_conflict_so_neither_wins(self):
        """Conflicting signals resolve to the conservative answer.

        A page whose own H1 says "Explore ideas" and whose markup says
        `Product` is making two incompatible statements about itself. Taking
        the machine-readable one because it is machine-readable is how a
        storefront's inspiration hub - which the template stamps with the same
        product markup as everything else in the shop - was audited as an
        individual product. Nothing is lost by declining to decide: the page is
        still crawled, still scored, and simply not sampled as a product.
        """
        facts = self._facts(title="Explore ideas", h1_texts=["Explore ideas"],
                            jsonld_types=["Product"])
        self.assertNotEqual(classify_page("https://x.example/x/y/", facts), "product")

    def test_declared_product_markup_wins_when_it_names_the_page(self):
        """And the resolution when the signals *agree*.

        The same URL and the same markup channel, but the declared entity's
        name is the page's heading. That is one thing said twice, by the
        template and by the copy, and it is a product page.
        """
        facts = self._facts(
            title="Kallvik shelf unit", h1_texts=["Kallvik shelf unit"],
            jsonld_types=["Product"],
            jsonld_nodes=[{"@type": "Product", "name": "Kallvik shelf unit",
                           "sku": "104.567.89",
                           "offers": {"@type": "Offer", "price": "4999",
                                      "priceCurrency": "INR"}}])
        self.assertEqual(classify_page("https://x.example/x/y/", facts), "product")

    def test_an_opaque_url_product_page_is_still_detected(self):
        """The property `TestVerdictDoesNotDependOnUrlVocabulary` guards."""
        facts = self._facts(title="model-00", h1_texts=["model-00"],
                            main_text="model-00 A running shoe. ₹4999 Add to cart")
        self.assertEqual(classify_page("https://x.example/shop/model-00.html", facts),
                         "product")

    def test_the_non_product_set_covers_every_non_pdp_type_the_classifier_emits(self):
        """The principle, stated where it cannot drift.

        Every page type the hint tables can produce, other than `product`
        itself, must be in the set that `ev.product_pages` refuses - otherwise
        a new type silently becomes eligible for product sampling.
        """
        from aiva.config import GENERIC_PAGE_TYPE_HINTS, PAGE_TYPE_HINTS
        emitted = {name for name, _ in PAGE_TYPE_HINTS}
        emitted |= {name for name, _ in GENERIC_PAGE_TYPE_HINTS}
        emitted |= {"home", "other", "error", "non_html"}
        for page_type in emitted - {"product", "other"}:
            with self.subTest(page_type=page_type):
                self.assertIn(page_type, NON_PRODUCT_PAGE_TYPES)

    def test_product_pages_refuses_a_mislabelled_page(self):
        """Belt and braces: even if a type leaked through, the funnel holds."""
        data = bundle([page(ORIGIN + "/", html_doc())])
        data["pages"].append({"url": ORIGIN + "/in/en/planners/", "page_type": "tool",
                              "final_url": ORIGIN + "/in/en/planners/", "status": 200})
        self.assertEqual([p["url"] for p in ev.product_pages(data)], [])


class TestPaymentNeedsAcceptanceContext(unittest.TestCase):
    """An instrument name is not a statement that the instrument is accepted."""

    REFUND_ANECDOTE = ("I purchased an article at the store and paid through a "
                       "Credit/Debit card. It was returned for a refund and the "
                       "amount was credited back to the same card.")
    MUSEUM = ("If you book an event or a tour at the Museum, we collect your name, "
              "your contact details and a payment method in order to process the "
              "booking.")
    ACCEPTANCE = "We accept Credit/Debit cards, UPI and net banking for all purchases."
    INSTRUMENT_ONLY = "Your credit card details are stored securely on our servers."

    def _matrix_for(self, policy_body, policy_url="/customer-service/faq/"):
        policy = page(ORIGIN + policy_url,
                      html_doc(title="Customer service",
                               body=f"<h1>Customer service</h1><p>{policy_body}</p>"))
        product = page(ORIGIN + "/products/x9", html_doc(
            title="X9", body='<h1>X9</h1><p>INR 5,499</p>'
                             '<button name="add-to-cart">Add to cart</button>'))
        return build_matrix(bundle([page(ORIGIN + "/", html_doc()), product, policy]))

    def _payment_row(self, matrix):
        rows = [q for q in matrix["questions"] if q["kind"] == "payment_options"]
        self.assertTrue(rows, "the payment question should still be generated")
        return rows[0]

    def test_a_refund_anecdote_does_not_answer_it(self):
        row = self._payment_row(self._matrix_for(self.REFUND_ANECDOTE))
        self.assertEqual(row["status"], "not_answerable", row)
        self.assertNotIn("refund", row["evidence"].lower())

    def test_a_museum_booking_notice_does_not_answer_it(self):
        row = self._payment_row(self._matrix_for(self.MUSEUM))
        self.assertEqual(row["status"], "not_answerable", row)

    def test_an_instrument_with_no_acceptance_language_does_not_answer_it(self):
        row = self._payment_row(self._matrix_for(self.INSTRUMENT_ONLY))
        self.assertEqual(row["status"], "not_answerable", row)

    def test_an_explicit_acceptance_statement_does_answer_it(self):
        row = self._payment_row(self._matrix_for(self.ACCEPTANCE))
        self.assertEqual(row["status"], "partial", row)
        self.assertIn("accept", row["evidence"].lower())

    def test_the_two_halves_are_independently_necessary(self):
        from aiva import lexicon
        # acceptance without an instrument
        self.assertIsNone(lexicon.find("payment_instrument", "We accept all major methods."))
        # an instrument without acceptance
        self.assertIsNone(lexicon.find("payment_acceptance", self.INSTRUMENT_ONLY))
        # both, in a real statement
        self.assertIsNotNone(lexicon.find("payment_acceptance", self.ACCEPTANCE))
        self.assertIsNotNone(lexicon.find("payment_instrument", self.ACCEPTANCE))

    def test_off_context_vetoes_even_when_both_halves_are_present(self):
        from aiva import lexicon
        mixed = ("We accept credit cards. Refunds are returned for a refund to the "
                 "original card.")
        self.assertIsNotNone(lexicon.find("payment_off_context", mixed))

    def test_past_tense_narration_is_not_acceptance_language(self):
        from aiva import lexicon
        for narration in ("I paid by credit card.", "The order was paid with a debit card.",
                          "She paid through UPI."):
            with self.subTest(narration=narration):
                self.assertIsNone(lexicon.find("payment_acceptance", narration))


# ---------------------------------------------------------------------------
# 6. commerce utility routes are not products (live Apple audit)
# ---------------------------------------------------------------------------

class TestCommerceUtilityRoutesAreNotProducts(unittest.TestCase):
    """Five storefront utility routes classified as individual products.

    All five matched one pattern in the *product* hint tuple:
    ``/shop/[^/]+/[^/]+$``. That is a guess about URL layout, and it fits
    ``/us/shop/goto/account`` exactly as well as it fits a real product page.
    A URL shape now has to be corroborated by markup or content before it can
    name a page a product, and commerce *functions* are settled before any
    product heuristic runs.
    """

    APPLE = {
        "/us/shop/goto/account": "an account page",
        "/us/shop/goto/buy_accessories": "a buying landing page",
        "/us/shop/goto/buy_iphone": "a buying landing page",
        "/us/shop/goto/giftcards": "a gift-card hub",
        "/us/shop/goto/payment_plan": "a payment-plan page",
    }

    def test_none_of_the_five_is_an_individual_product(self):
        for path, what in self.APPLE.items():
            with self.subTest(path=path):
                self.assertNotEqual(
                    classify_page("https://www.apple.com" + path), "product",
                    f"{path} is {what}")

    def test_the_url_shape_alone_never_decides(self):
        """`/shop/x/y` is a layout guess, not evidence about content."""
        self.assertNotEqual(classify_page("https://x.example/shop/goto/anything"),
                            "product")
        self.assertNotEqual(classify_page("https://x.example/shop/help/returns"),
                            "product")

    def test_the_same_shape_with_real_product_content_is_still_a_product(self):
        """Detection must survive: this is the corroborated case."""
        pdp = {"prices_in_text": [{"value": "999"}], "h1_count": 1,
               "title": "Velocity X9", "h1_texts": ["Velocity X9"],
               "main_text": "Velocity X9 £999 Add to cart", 
               "variants": {"variant_swatches": 3},
               "forms": {"has_cart_action": True, "has_cart_action_in_main": True},
               "mentions": {"add_to_cart": True}, "jsonld_types": []}
        self.assertEqual(classify_page("https://x.example/shop/shoes/velocity-x9", pdp),
                         "product")

    def test_declared_product_markup_still_wins_on_that_shape(self):
        """A described entity on that shape is a product page.

        The declaration has to describe something: a name, an identifier and a
        priced offer are three assertions about one thing. The bare token
        `{"@type":"Product"}` is one line of a template - see the negative
        case below, which is the same URL shape with nothing behind it.
        """
        described = {
            "jsonld_types": ["Product", "Offer"],
            "jsonld_nodes": [{"@type": "Product", "name": "Velocity X9",
                              "sku": "KA-VX9", "brand": {"@type": "Brand", "name": "K"},
                              "offers": {"@type": "Offer", "price": "999",
                                         "priceCurrency": "GBP"}}],
            "h1_count": 1, "h1_texts": ["Velocity X9"], "title": "Velocity X9",
        }
        self.assertEqual(classify_page("https://x.example/shop/a/b", described),
                         "product")

    def test_a_bare_product_token_on_that_shape_is_not(self):
        """`/shop/x/y` plus one schema token is two isolated signals.

        Neither says which item the page is about, and on the storefronts that
        produced this class both were true of a payment-plan page.
        """
        self.assertNotEqual(
            classify_page("https://x.example/shop/a/b", {"jsonld_types": ["Product"]}),
            "product")

    # -- the categories the brief enumerates --------------------------------

    def test_transactional_routes_are_never_crawled_at_all(self):
        """Account, cart and bag are excluded from the frontier wherever they
        sit - the exclusion used to be anchored at the site root only, so a
        locale- or shop-prefixed path slipped past it."""
        from aiva.config import NON_CITABLE_PATH_RE
        for path in ("/us/shop/goto/account", "/us/shop/bag", "/de/warenkorb",
                     "/fr/panier", "/en/checkout", "/uk/my-account/orders"):
            with self.subTest(path=path):
                self.assertIsNotNone(NON_CITABLE_PATH_RE.search(path))

    def test_an_ordinary_page_whose_name_contains_a_transactional_word_is_kept(self):
        from aiva.config import NON_CITABLE_PATH_RE
        for path in ("/products/shopping-bag-leather", "/blog/my-account-guide",
                     "/collections/cart-bags"):
            with self.subTest(path=path):
                self.assertIsNone(NON_CITABLE_PATH_RE.search(path))

    def test_the_enumerated_non_product_shapes(self):
        cases = {
            # A model chooser and a gift-card hub are non-product *and*
            # non-listing: neither owes filtering, sorting or comparison
            # support, and filing them under `category` is what put them in
            # front of the listing rules.
            "https://x.example/us/buy_laptops": "promotional",
            "https://x.example/gift-cards/": "promotional",
            "https://x.example/en/payment-plan/": "policy",
            "https://x.example/financing/": "policy",
            "https://x.example/trade-in/": "policy",
            "https://x.example/collections/running": "category",
            "https://x.example/help/": "support",
            "https://x.example/support/": "support",
            "https://x.example/offers/": "promotional",
            "https://x.example/store-locator/": "contact",
            "https://x.example/planners/": "tool",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(classify_page(url), expected)
                self.assertNotEqual(classify_page(url), "product")


class TestNonProductPagesDriveNoProductFindings(unittest.TestCase):
    """The downstream half: the shared page type is the only source of truth."""

    PRODUCT_ONLY_RULES = frozenset({
        "MR-PRODUCT-SCHEMA-MISSING", "MR-OFFER-MISSING", "MR-OFFER-INCOMPLETE",
        "MR-IDENTIFIERS-MISSING", "MR-ATTRIBUTES-THIN", "EG-AVAILABILITY-INVISIBLE",
        "EG-LEAD-ANSWER-WEAK", "EG-SPECS-MISSING", "EG-REVIEWS-ABSENT",
        "EG-CTA-NOT-IN-HTML", "EG-PRODUCT-DEAD-END", "CR-THIN-PRODUCT-HTML",
        "EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE",
    })

    def _bundle(self):
        """One real product, five storefront utility routes."""
        utility = [
            page("https://shop.example/us/shop/goto/buy_iphone",
                 html_doc(title="Buy iPhone", body="<h1>Buy iPhone</h1>"
                          "<p>From $799. Trade in and save.</p>"
                          '<form action="/cart"><button>Add to Bag</button></form>')),
            page("https://shop.example/us/shop/goto/giftcards",
                 html_doc(title="Gift Cards", body="<h1>Gift Cards</h1>"
                          "<p>From $25 to $500.</p>")),
            page("https://shop.example/us/shop/goto/payment_plan",
                 html_doc(title="Payment plan", body="<h1>Monthly payments</h1>"
                          "<p>Pay over 12 months at 0% APR.</p>")),
            page("https://shop.example/support/",
                 html_doc(title="Support", body="<h1>Support</h1><p>Get help.</p>")),
            page("https://shop.example/offers/",
                 html_doc(title="Offers", body="<h1>Offers</h1><p>Save $100.</p>")),
        ]
        product = page("https://shop.example/products/velocity-x9", html_doc(
            title="Velocity X9", body='<h1>Velocity X9</h1><p>$999</p>'
                                      '<button name="add-to-cart">Add to cart</button>'))
        return bundle([page("https://shop.example/", html_doc())] + utility + [product])

    def setUp(self):
        self.data = self._bundle()
        self.utility_urls = {p["url"] for p in self.data["pages"]
                             if "goto" in p["url"] or p["url"].rstrip("/").endswith(
                                 ("support", "offers"))}

    def test_none_of_the_utility_routes_classified_as_product(self):
        for page_facts in self.data["pages"]:
            if page_facts["url"] in self.utility_urls:
                with self.subTest(url=page_facts["url"]):
                    self.assertNotEqual(page_facts.get("page_type"), "product")

    def test_the_product_funnel_returns_only_the_real_product(self):
        self.assertEqual([p["url"] for p in ev.product_pages(self.data)],
                         ["https://shop.example/products/velocity-x9"])

    def test_no_product_rule_cites_a_utility_route(self):
        for skill in ("machine-readability-audit", "engagement-audit",
                      "crawl-render-audit", "entity-audit", "freshness-corroboration"):
            for item in run(skill, self.data):
                if item.rule_id not in self.PRODUCT_ONLY_RULES:
                    continue
                for url in item.affected_urls:
                    with self.subTest(rule=item.rule_id, url=url):
                        self.assertNotIn(url, self.utility_urls)

    def test_no_product_question_is_generated_for_a_utility_route(self):
        matrix = build_matrix(self.data)
        for row in matrix["questions"]:
            if row["kind"].startswith("product_"):
                with self.subTest(kind=row["kind"]):
                    self.assertNotIn(row["citing_url"], self.utility_urls)


class TestSamplingCoverageIsAlwaysAProportion(unittest.TestCase):
    """`affected=40, sampled=38, coverage=1.05` - and a schema violation.

    The rule counted *observations* (a page can contribute two) against a
    population of *pages*. Clamping the ratio would have published a plausible
    number over a population that was never measured, so the mismatch is
    rejected instead and the rule's arithmetic was corrected.
    """

    def _finding(self, affected, sampled):
        return Finding(
            rule_id="XX-TEST", title="t", severity="low", pillar="entity",
            evidence="e",
            evidence_items=[EvidenceItem(kind="observation", observation="o",
                                         url=ORIGIN + "/")],
            suggested_action=SuggestedAction(summary="s"),
            metrics={"affected": affected, "sampled": sampled})

    def test_a_ratio_above_one_is_refused_not_clamped(self):
        problems = self._finding(40, 38).problems()
        self.assertTrue(problems)
        self.assertIn("exceeds", problems[0])

    def test_an_ordinary_ratio_passes(self):
        self.assertEqual(self._finding(12, 38).problems(), [])
        self.assertEqual(self._finding(38, 38).problems(), [])

    def test_the_sampling_record_never_reports_coverage_above_one(self):
        self.assertLessEqual(self._finding(38, 38).sampling["coverage"], 1.0)

    def test_no_fixture_produces_a_coverage_above_one(self):
        """The invariant across every bundled site, end to end."""
        for name in ("weak", "mixed", "strong"):
            with self.subTest(fixture=name):
                directory = MARKETPLACE_ROOT / "tests" / "fixtures" / f"site_{name}"
                server, base = localserve.start(directory)
                try:
                    config = AuditConfig(site=base, request_delay_s=0.1,
                                         check_external=False)
                    _, report = orchestrator.run_audit(config)
                finally:
                    server.shutdown()
                    server.server_close()
                for item in report["findings"]:
                    coverage = (item.get("sampling") or {}).get("coverage")
                    if coverage is not None:
                        self.assertLessEqual(coverage, 1.0,
                                             f"{item['rule_id']} on site_{name}")

    def test_the_location_rule_counts_pages_not_observations(self):
        """The rule that produced 40/38: a page linking to a locator *and*
        being one contributed twice."""
        locator = page(ORIGIN + "/stores/", html_doc(
            title="Our stores",
            body='<h1>Our stores</h1><nav><a href="/stores/">Find a store</a></nav>'
                 "<p>Shops in Bristol and Leeds.</p>"))
        data = bundle([page(ORIGIN + "/", html_doc()), locator])
        for item in run("entity-audit", data):
            if item.rule_id == "EN-LOCATIONS-UNSTRUCTURED":
                self.assertLessEqual(item.metrics["affected"], item.metrics["sampled"])
