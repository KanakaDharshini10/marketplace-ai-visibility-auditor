"""Precision: what the auditor must report, and what it must not.

The v1.11.1 principle, stated once and asserted everywhere below:

    an auditor reports a semantic defect only when *both* the observed
    condition and its applicability are supported by evidence

Detecting a pattern establishes the first half. The second is a separate
question, and answering it with the detector's own certainty is how a
marketing page is told to add a price sort and a documentation site is asked
about its return window. Where the second half is missing the finding is
**downgraded** - kept, because the observation is real, but lowered in
severity and confidence, reworded to say what could not be assessed, and
stripped of every claim that rests on the missing half. Where the condition
itself is not established the finding is **suppressed**.

The negative assertions in this module matter as much as the positive ones. A
suite that only checks what fires cannot tell a precise auditor from a noisy
one.

Every fixture is invented (:mod:`shapes`). No test, and no line of runtime
code, knows a domain name.

Run just this file:

    python3 tests/run_tests.py false_positives -v
"""

from __future__ import annotations

import unittest

import helpers
import shapes
from helpers import bundle, find, html_doc, jsonld, page, rule_ids, run

from aiva import analysis, answerability, semantics
from aiva.analysis import DOWNGRADE, REPORT, SUPPRESS, applicability_verdict
from aiva.extract import PRICE_RE, price_confidence, price_match_parts

CONTROL_RULES = ("EG-FILTER-CONTROLS-ABSENT", "EG-SORT-CONTROLS-ABSENT")

#: Attributes that exist on exactly one page in these fixtures.
FOREIGN = ("Diameter", "Height", "Operating ambient temperature")


def annotated(build) -> dict:
    data = build() if callable(build) else build
    semantics.annotate_bundle(data)
    return data


def all_advice(data: dict) -> str:
    """Every word the whole marketplace would print for this bundle."""
    parts = []
    for _, module in helpers.load_specialists():
        for finding in module.analyze(data):
            action = finding.suggested_action
            parts.extend([finding.evidence, finding.interpretation, action.summary,
                          action.mechanism, action.example, *action.steps])
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 1. the centralised decision
# ---------------------------------------------------------------------------

class TestTheApplicabilityVerdict(unittest.TestCase):
    """One rule, in one place, so the three words mean one thing."""

    def test_both_halves_evidenced_is_reported(self):
        verdict = applicability_verdict(observed=True, applies=True,
                                        severity="high", confidence=0.9)
        self.assertEqual(verdict.action, REPORT)
        self.assertEqual((verdict.severity, verdict.confidence), ("high", 0.9))
        self.assertTrue(verdict.reported)

    def test_an_unestablished_condition_is_suppressed(self):
        verdict = applicability_verdict(observed=False, applies=True,
                                        severity="high", confidence=0.9)
        self.assertEqual(verdict.action, SUPPRESS)
        self.assertFalse(bool(verdict), "a suppressed verdict is falsy so a rule can gate on it")

    def test_uncertain_applicability_lowers_severity_and_confidence(self):
        verdict = applicability_verdict(observed=True, applies=False, severity="critical",
                                        confidence=0.95, uncertain_note="the set is unknown")
        self.assertEqual(verdict.action, DOWNGRADE)
        self.assertEqual(verdict.severity, analysis.UNCERTAIN_APPLICABILITY_CEILING)
        self.assertLessEqual(verdict.confidence, analysis.UNCERTAIN_APPLICABILITY_CONFIDENCE)
        self.assertEqual(verdict.note, "the set is unknown")

    def test_confidence_is_never_raised_by_a_downgrade(self):
        verdict = applicability_verdict(observed=True, applies=False,
                                        severity="low", confidence=0.2)
        self.assertEqual(verdict.confidence, 0.2)

    def test_a_verdict_unpacks(self):
        action, severity, confidence = applicability_verdict(
            observed=True, applies=True, severity="medium", confidence=0.7)
        self.assertEqual((action, severity, confidence), (REPORT, "medium", 0.7))


# ---------------------------------------------------------------------------
# 2. price extraction (brief section 10)
# ---------------------------------------------------------------------------

class TestPriceExtraction(unittest.TestCase):
    """The reported failure: a trial offer read as a product's price.

    ``TRY`` is the Turkish lira, the pattern was case-insensitive, and so
    "Try 7 days free" was a price of 7. The same collision exists for ``PEN``
    (a pen), ``COP`` (a cop) and ``RON`` (a name).
    """

    def prices(self, text: str):
        return [price_match_parts(m) for m in PRICE_RE.finditer(text)]

    def test_an_english_word_that_spells_a_currency_code_is_not_a_price(self):
        for text in ("Try 7 days free with the subscription.",
                     "try 7 free trials",
                     "Get a pen 5 pack for the office.",
                     "The cop 20 summit ran for two weeks.",
                     "Ron 12 was our best year.",
                     "rs. 499 written in lower case is not a currency"):
            self.assertEqual(self.prices(text), [], text)

    def test_the_currency_code_in_its_own_case_is_still_a_price(self):
        self.assertEqual(self.prices("TRY 7 covers the fare."), [("TRY", "7")])
        self.assertEqual(self.prices("Rs. 499 only"), [("Rs", "499")])

    def test_currency_symbols(self):
        for text, expected in (("₹3,490", ("₹", "3,490")), ("$29", ("$", "29")),
                               ("£99.50", ("£", "99.50")), ("€1.299,00", ("€", "1.299,00")),
                               ("¥12,000", ("¥", "12,000"))):
            self.assertEqual(self.prices(text), [expected], text)

    def test_currency_codes(self):
        for text, expected in (("USD 29", ("USD", "29")), ("INR 3490", ("INR", "3490")),
                               ("CHF 89.00", ("CHF", "89.00"))):
            self.assertEqual(self.prices(text), [expected], text)

    def test_thousands_separators_and_decimals(self):
        self.assertEqual(self.prices("$1,299.50"), [("$", "1,299.50")])
        self.assertEqual(self.prices("$1200"), [("$", "1200")])
        self.assertEqual(self.prices("19,99 €"), [("€", "19,99")])

    def test_localized_postfix_prices(self):
        self.assertEqual(self.prices("1 299 kr"), [("kr", "1 299")])
        self.assertEqual(self.prices("RM 89.00"), [("RM", "89.00")])

    def test_an_unrelated_number_beside_the_word_price_is_not_a_price(self):
        for text in ("Our price promise covers 30 days.",
                     "Price match within 14 days of purchase.",
                     "The price is right for 4 people."):
            self.assertEqual(self.prices(text), [], text)

    def test_multiple_prices_on_one_page_are_all_read(self):
        found = self.prices("Was £120, now £89. Members pay £79.")
        self.assertEqual(found, [("£", "120"), ("£", "89"), ("£", "79")])

    def test_a_subscription_price_is_read(self):
        self.assertEqual(self.prices("$12 per user per month"), [("$", "12")])

    def test_a_symbol_price_is_certain_and_a_code_price_is_not(self):
        symbol = next(PRICE_RE.finditer("₹3,490"))
        code = next(PRICE_RE.finditer("RM 89.00"))
        self.assertEqual(price_confidence(symbol), "high")
        self.assertEqual(price_confidence(code), "medium")

    def test_a_page_whose_only_number_is_a_trial_offer_publishes_no_price(self):
        product = page(helpers.ORIGIN + "/products/tag", html_doc(
            title="Locator Tag", canonical=helpers.ORIGIN + "/products/tag",
            body="<main><h1>Locator Tag</h1><p>Try 7 days free with the plan.</p></main>"))
        self.assertEqual(product["prices_in_text"], [])

    def test_an_uncertain_reading_is_stated_as_uncertain(self):
        product = page(helpers.ORIGIN + "/products/watch", html_doc(
            title="Watch", canonical=helpers.ORIGIN + "/products/watch",
            head=jsonld('{"@context":"https://schema.org","@type":"Product",'
                        '"name":"Field Watch","sku":"W-1"}'),
            body="<main><h1>Field Watch</h1><p>Model RM 55 costs RM 890.</p></main>"))
        data = annotated(bundle([shapes.home(), product, shapes.physical_product()]))
        rows = [r for r in answerability.build_matrix(data)["questions"]
                if r["kind"] == "product_price" and "watch" in r["citing_url"]]
        self.assertTrue(rows)
        self.assertIn("the reading is not certain", rows[0]["evidence"])


# ---------------------------------------------------------------------------
# 3. listings: reported, downgraded, suppressed
# ---------------------------------------------------------------------------

class TestListingApplicability(unittest.TestCase):
    """Brief sections 4-6. Cases 1-6, 12-14 of the test list."""

    def test_a_genuine_ecommerce_catalogue_is_assessed_normally(self):
        data = annotated(shapes.two_catalogue_site)
        emitted = rule_ids(run("engagement-audit", data))
        self.assertTrue(set(CONTROL_RULES) & set(emitted))
        finding = find(run("engagement-audit", data), "EG-FILTER-CONTROLS-ABSENT") \
            or find(run("engagement-audit", data), "EG-SORT-CONTROLS-ABSENT")
        self.assertEqual(finding.metrics["applicability"], REPORT)
        self.assertGreater(finding.confidence, analysis.UNCERTAIN_APPLICABILITY_CONFIDENCE)

    def test_an_ambiguous_listing_is_downgraded_not_asserted(self):
        data = annotated(bundle([shapes.home(), shapes.ambiguous_listing(),
                                 shapes.physical_product()]))
        for rule in CONTROL_RULES:
            finding = find(run("engagement-audit", data), rule)
            self.assertIsNotNone(finding, rule)
            self.assertEqual(finding.metrics["applicability"], DOWNGRADE, rule)
            self.assertEqual(finding.severity, "low", rule)
            self.assertIn("could not be assessed against a known comparable set",
                          finding.title)

    def test_an_ambiguous_listing_is_told_no_attribute_and_no_dimension(self):
        data = annotated(bundle([shapes.home(), shapes.ambiguous_listing(),
                                 shapes.instrument_product()]))
        finding = find(run("engagement-audit", data), "EG-SORT-CONTROLS-ABSENT")
        self.assertEqual(finding.metrics["evidenced_order_dimensions"], [])
        text = all_advice(data)
        for attribute in FOREIGN:
            self.assertNotIn(attribute, text, attribute)

    def test_a_product_family_page_is_not_a_catalogue(self):
        data = annotated(shapes.family_landing_site)
        family = next(p for p in data["pages"] if p["url"].endswith("/handset/"))
        self.assertFalse(analysis.collection_provenance(family, data)["established"])
        self.assertNotEqual(
            semantics.listing_record(family, data).get("subtype"), "ecommerce_listing")

    def test_a_comparison_page_is_not_asked_for_catalogue_controls(self):
        data = annotated(bundle([shapes.home(), shapes.comparison_page(),
                                 shapes.physical_product()]))
        for rule in CONTROL_RULES:
            self.assertIsNone(find(run("engagement-audit", data), rule), rule)

    def test_a_documentation_section_is_not_a_catalogue(self):
        for name in ("documentation", "publisher", "audio_publisher",
                     "knowledge_reference", "developer_platform"):
            with self.subTest(shape=name):
                build = dict(shapes.ALL_SHAPES)[name]
                data = annotated(build)
                for rule in CONTROL_RULES:
                    self.assertIsNone(find(run("engagement-audit", data), rule), name)

    def test_a_software_catalogue_and_a_saas_get_no_physical_attribute_advice(self):
        for name, build in shapes.NON_PHYSICAL_SELLERS:
            with self.subTest(shape=name):
                text = all_advice(annotated(build))
                for attribute in FOREIGN:
                    self.assertNotIn(attribute, text, name)

    def test_a_marketplace_and_service_site_are_handled_by_the_same_engine(self):
        for name in ("travel", "community", "nonprofit"):
            with self.subTest(shape=name):
                data = annotated(dict(shapes.ALL_SHAPES)[name])
                self.assertIsInstance(rule_ids(run("engagement-audit", data)), list)


# ---------------------------------------------------------------------------
# 4. product semantic subtypes (brief section 7)
# ---------------------------------------------------------------------------

class TestCommerceExpectationsFollowTheSubtype(unittest.TestCase):
    """Cases 28-29: a boot owes a delivery estimate and a download does not."""

    def test_the_subtype_vocabulary_is_unchanged(self):
        self.assertEqual(semantics.PRODUCT_SUBTYPES,
                         ("physical", "digital", "software", "subscription", "service",
                          "marketplace_listing", "informational", "ambiguous"))

    def test_a_physical_product_is_asked_for_stock_shipping_and_returns(self):
        data = annotated(shapes.shop)
        emitted = rule_ids(run("engagement-audit", data))
        self.assertTrue({"EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE"} & set(emitted),
                        f"a shop that states neither should be told: {emitted}")

    def test_a_software_or_subscription_page_is_not(self):
        for name in ("software_vendor", "subscription_saas"):
            with self.subTest(shape=name):
                data = annotated(dict(shapes.ALL_SHAPES)[name])
                emitted = rule_ids(run("engagement-audit", data))
                for rule in ("EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE",
                             "EG-STOCK-INVISIBLE"):
                    self.assertNotIn(rule, emitted, f"{name}: {rule}")

    def test_an_informational_page_gets_no_commerce_finding(self):
        for name, _ in shapes.NON_COMMERCE:
            with self.subTest(shape=name):
                data = annotated(dict(shapes.ALL_SHAPES)[name])
                emitted = rule_ids(run("engagement-audit", data))
                for rule in ("EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE",
                             "EG-STOCK-INVISIBLE") + CONTROL_RULES:
                    self.assertNotIn(rule, emitted, f"{name}: {rule}")


# ---------------------------------------------------------------------------
# 5. answerability gating (brief sections 8-9)
# ---------------------------------------------------------------------------

class TestAnswerabilityIsGrounded(unittest.TestCase):
    """Cases 25-27: no question whose subject the site does not support."""

    def kinds(self, data: dict):
        return {row["kind"] for row in answerability.build_matrix(data)["questions"]}

    def test_a_documentation_site_is_asked_no_return_question(self):
        self.assertNotIn("return_window", self.kinds(annotated(shapes.documentation)))

    def test_a_publisher_and_a_public_body_are_asked_no_payment_question(self):
        for name in ("publisher", "public_body", "knowledge_reference"):
            with self.subTest(shape=name):
                kinds = self.kinds(annotated(dict(shapes.ALL_SHAPES)[name]))
                for kind in ("payment_options", "shipping_destinations", "return_window",
                             "product_availability"):
                    self.assertNotIn(kind, kinds, name)

    def test_a_software_site_is_asked_no_shipping_or_stock_question(self):
        kinds = self.kinds(annotated(shapes.software_vendor))
        self.assertNotIn("shipping_destinations", kinds)
        self.assertNotIn("product_availability", kinds)

    def test_a_shop_is_asked_the_commerce_questions(self):
        kinds = self.kinds(annotated(shapes.shop))
        self.assertIn("product_price", kinds)
        self.assertIn("product_availability", kinds)

    def test_every_generated_question_carries_a_subject_and_a_citation(self):
        matrix = answerability.build_matrix(annotated(shapes.golden_site))
        for row in matrix["questions"]:
            self.assertTrue(row["question"], row)
            self.assertIn(row["status"], answerability.STATUSES, row)
            self.assertTrue(row.get("evidence") or row.get("missing"), row)
            if row["kind"].startswith("product_"):
                self.assertTrue(row["citing_url"], row)
                self.assertTrue(row.get("subject_identity"), row)

    def test_no_question_is_generated_about_a_product_with_no_identity(self):
        anonymous = page(helpers.ORIGIN + "/products/x", html_doc(
            title="Shop", canonical=helpers.ORIGIN + "/products/x",
            body="<main><h1>Shop</h1><p>A page with no product entity.</p></main>"))
        data = annotated(bundle([shapes.home(), anonymous]))
        for row in answerability.build_matrix(data)["questions"]:
            self.assertNotEqual(row.get("citing_url"), anonymous["url"], row)

    def test_a_comparison_pairs_items_the_site_lists_together(self):
        data = annotated(shapes.golden_site)
        rows = [r for r in answerability.build_matrix(data)["questions"]
                if r["kind"] == "product_comparison"]
        for row in rows:
            self.assertIn("subject_identity", row)
            self.assertTrue(
                'both are listed in' in row["subject_identity"]
                or "no listing was observed containing both" in row["subject_identity"],
                row["subject_identity"])


# ---------------------------------------------------------------------------
# 6. endpoints, canonicals, noindex (brief sections 15-16)
# ---------------------------------------------------------------------------

class TestEndpointsAreNotContent(unittest.TestCase):
    """Cases 23-24, and the noindex exclusions."""

    def test_a_search_endpoint_is_not_a_canonical_candidate(self):
        data = annotated(shapes.golden_site)
        crawl = helpers.specialist("crawl-render-audit")
        endpoint = next(p for p in data["pages"] if p["page_type"] == "search")
        verdict = crawl.canonical_eligibility(endpoint, {})
        self.assertNotEqual(verdict, "eligible")
        self.assertIn("endpoint", verdict)

    def test_a_facet_permutation_carrying_noindex_is_routine_not_a_defect(self):
        crawl = helpers.specialist("crawl-render-audit")
        facet = shapes.facet_permutation()
        self.assertEqual(crawl._noindex_role(facet), "utility")

    def test_a_tool_endpoint_carrying_noindex_is_routine(self):
        crawl = helpers.specialist("crawl-render-audit")
        tool = page(helpers.ORIGIN + "/planner", html_doc(
            title="Kitchen planner", canonical=helpers.ORIGIN + "/planner",
            head='<meta name="robots" content="noindex">',
            body="<main><h1>Kitchen planner</h1><p>Plan your kitchen.</p></main>"))
        tool["page_type"] = "tool"
        self.assertEqual(crawl._noindex_role(tool), "utility")

    def test_a_noindexed_product_page_is_still_reported(self):
        """The exclusions must not swallow the finding that matters."""
        crawl = helpers.specialist("crawl-render-audit")
        product = shapes.physical_product()
        product["meta_robots"] = "noindex"
        self.assertEqual(crawl._noindex_role(product), "discoverable")

    def test_the_noindex_finding_never_asserts_the_intent(self):
        crawl = helpers.specialist("crawl-render-audit")
        product = shapes.physical_product()
        product["robots_directives"] = {"noindex": True}
        product["meta_robots"] = "noindex"
        data = annotated(bundle([shapes.home(), product,
                                 shapes.physical_product("/products/b", "B", "90")]))
        finding = find(run("crawl-render-audit", data), "CR-NOINDEX-ON-CONTENT")
        if finding is not None:
            self.assertNotIn("should be indexed", finding.evidence + finding.interpretation)


# ---------------------------------------------------------------------------
# 7. entity classification (brief section 14)
# ---------------------------------------------------------------------------

class TestOutboundLinksAreNotAllProfiles(unittest.TestCase):
    """Case 22: an ordinary outbound link is not a sameAs candidate."""

    def test_documentation_knowledge_and_locale_links_are_not_profiles(self):
        for url, forbidden in (("https://docs.python.org/3/", "official_profile"),
                               ("https://en.wikipedia.org/wiki/Kestrel", "official_profile"),
                               ("https://example.org/partners", "official_profile")):
            kind = semantics.classify_outbound_link(
                url, site_origin=helpers.ORIGIN)["kind"]
            self.assertNotEqual(kind, forbidden, url)

    def test_a_rel_me_link_is_a_profile(self):
        kind = semantics.classify_outbound_link(
            "https://social.example/kestrel", site_origin=helpers.ORIGIN,
            rel="me")["kind"]
        self.assertEqual(kind, "official_profile")

    def test_a_localized_name_is_not_a_rival_trading_name(self):
        data = annotated(shapes.golden_site)
        emitted = run("entity-audit", data)
        finding = find(emitted, "EN-NAME-INCONSISTENT")
        if finding is not None:
            self.assertNotIn("Kestrel SARL", finding.evidence,
                             "a French locale variant is the same organisation")


# ---------------------------------------------------------------------------
# 8. rendered evidence is preserved (brief sections 11-13)
# ---------------------------------------------------------------------------

class TestRenderedEvidenceSurvives(unittest.TestCase):
    """Cases 17-20. The 1.11.0 feature must come through unharmed."""

    def test_the_six_visibility_states_are_unchanged(self):
        self.assertEqual(analysis.VISIBILITY_STATES,
                         ("server_and_rendered", "server_visible", "rendered_only",
                          "structured_only", "not_observed", "render_unavailable"))

    def test_a_rendered_only_fact_is_reported_as_a_response_gap(self):
        data = annotated(shapes.golden_site)
        studio = next(p for p in data["pages"] if p["url"].endswith("/products/studio"))
        self.assertEqual(analysis.render_state(studio), "rendered")
        finding = find(run("crawl-render-audit", data), "CR-RENDER-FACT-GAP")
        if finding is not None:
            self.assertIn("rendered DOM", finding.evidence)
            self.assertNotIn("missing from the website", finding.evidence)

    def test_a_raw_absence_is_not_deleted_by_a_rendered_presence(self):
        """Brief section 12: the rendering gap is itself a finding."""
        product = page(helpers.ORIGIN + "/products/lamp", html_doc(
            title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
            head=jsonld('{"@context":"https://schema.org","@type":"Product",'
                        '"name":"Halo Lamp","sku":"L-1"}'),
            body="<main><h1>Halo Lamp</h1><p>A lamp.</p></main>"))
        with_price = page(helpers.ORIGIN + "/products/lamp", html_doc(
            title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
            body="<main><h1>Halo Lamp</h1><p>&#163;42.00 In stock.</p></main>"))
        product["rendered"] = dict(with_price, ok=True)
        data = annotated(bundle([shapes.home(), product, shapes.physical_product()]))
        rows = [r for r in answerability.build_matrix(data)["questions"]
                if r["kind"] == "product_price" and "lamp" in r["citing_url"]]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["status"], "not_answerable")
        self.assertIn("absent from the server response rather than from the page",
                      rows[0]["evidence"])

    def test_no_finding_claims_a_fact_is_visible_to_every_human(self):
        text = all_advice(annotated(shapes.golden_site))
        for phrase in ("all humans", "every visitor", "human-visible", "humans can see"):
            self.assertNotIn(phrase, text.lower(), phrase)


# ---------------------------------------------------------------------------
# 9. the golden fixture, positive and negative
# ---------------------------------------------------------------------------

class TestTheGoldenFixture(unittest.TestCase):
    """One host carrying every shape, with both halves asserted."""

    @classmethod
    def setUpClass(cls):
        cls.data = annotated(shapes.golden_site)
        cls.findings = []
        for _, module in helpers.load_specialists():
            cls.findings.extend(module.analyze(cls.data))
        cls.ids = {f.rule_id for f in cls.findings}
        cls.text = " ".join(
            [f.evidence + " " + f.interpretation + " " + f.suggested_action.summary
             + " " + " ".join(f.suggested_action.steps) for f in cls.findings])

    # -- what must be reported ------------------------------------------------

    def test_every_finding_carries_evidence_a_url_and_a_confidence(self):
        for finding in self.findings:
            self.assertTrue(finding.evidence, finding.rule_id)
            self.assertTrue(0.0 < finding.confidence <= 1.0, finding.rule_id)
            self.assertIn(finding.severity,
                          ("info", "low", "medium", "high", "critical"), finding.rule_id)

    def test_the_site_is_read_as_mixed_rather_than_as_a_shop(self):
        self.assertEqual(semantics.site_context(self.data).get("site_kind"), "mixed")

    def test_the_genuine_catalogue_keeps_its_provenance(self):
        boots = next(p for p in self.data["pages"]
                     if p["url"].endswith("/collections/boots"))
        record = analysis.collection_provenance(boots, self.data)
        self.assertTrue(record["established"])
        self.assertEqual(len(record["members"]), 2)

    # -- what must NOT be reported -------------------------------------------

    def test_no_attribute_crosses_from_one_page_to_another(self):
        for attribute in FOREIGN:
            self.assertNotIn(attribute, self.text, attribute)

    def test_the_software_page_is_never_asked_for_a_delivery_estimate(self):
        for finding in self.findings:
            if "EG-SHIPPING" in finding.rule_id or "EG-RETURNS" in finding.rule_id:
                self.assertNotIn("/products/studio", " ".join(finding.affected_urls),
                                 finding.rule_id)
                self.assertNotIn("/plans/team", " ".join(finding.affected_urls),
                                 finding.rule_id)

    def test_the_search_endpoint_is_never_an_affected_url(self):
        for finding in self.findings:
            self.assertNotIn("/search?q=", " ".join(finding.affected_urls), finding.rule_id)

    def test_no_finding_claims_an_external_system_behaves_a_certain_way(self):
        from test_claim_scanner import scan
        self.assertEqual(scan(self.text), [], self.text[:200])

    def test_no_finding_states_a_site_wide_certainty_from_a_sample(self):
        """Brief section 25: a sampled observation stays a sampled observation."""
        for finding in self.findings:
            metrics = finding.metrics or {}
            if "affected" in metrics and "sampled" in metrics:
                self.assertLessEqual(metrics["affected"], metrics["sampled"],
                                     finding.rule_id)
                self.assertIn("sample_unit", metrics, finding.rule_id)


# ---------------------------------------------------------------------------
# 10. proactive recommendations (brief section 20)
# ---------------------------------------------------------------------------

class TestRecommendationsAreLabelled(unittest.TestCase):

    def test_every_opportunity_declares_its_grounding_and_why_it_applies(self):
        """Brief section 20: one of three classes, and its own reason.

        `grounding` is what stops a proactive recommendation becoming a hidden
        false positive: `generic` says plainly that no defect was observed,
        while `evidence_backed` has to point at what was.
        """
        from aiva.recommend import build_opportunities
        for name, build in shapes.ALL_SHAPES:
            with self.subTest(shape=name):
                data = annotated(build)
                for payload in build_opportunities(data):
                    self.assertIn(payload.get("grounding"),
                                  ("evidence_backed", "site_personalised", "generic"),
                                  payload.get("id"))
                    self.assertTrue(payload.get("why_now"), payload.get("id"))
                    self.assertTrue(payload.get("applicability"), payload.get("id"))

    def test_no_opportunity_claims_an_external_system_behaves_a_certain_way(self):
        from test_claim_scanner import scan
        from aiva.recommend import build_opportunities
        for name, build in shapes.ALL_SHAPES:
            with self.subTest(shape=name):
                data = annotated(build)
                for payload in build_opportunities(data):
                    text = " ".join(str(payload.get(key) or "") for key in
                                    ("mechanism", "why_now", "verification",
                                     "title"))
                    text += " " + " ".join(payload.get("steps") or [])
                    self.assertEqual(scan(text), [], f"{name}: {text[:160]}")


if __name__ == "__main__":
    unittest.main()
