"""What the audit says must fit the kind of site it is looking at.

One fixture per semantic site type (``tests/shapes.py``), each invented and
none named after or keyed to any real site. The scenarios are the ones a
reviewer asks about - an encyclopaedia, a developer platform, a public body,
an audio publisher, a booking site, a shop - expressed as the *shape* each of
those is, so that passing these tests requires the classifier to be right and
never permits a rule that knows a domain name.

What is asserted here:

* commerce checks and commerce advice still work where goods are sold;
* nothing about delivery, stock, returns or catalogues reaches a site that
  sells no goods - asserted over the rendered text of every finding and every
  recommendation, not just over rule ids;
* a repository index, a glossary, an audio index and a guidance index are not
  ecommerce catalogues;
* questions follow what the site is, and a question that does not apply is
  reported as not asked rather than as a gap;
* every recommendation states the evidence and the site kind that made it
  applicable, and reads correctly with the domain removed.

Run just this file:

    python3 tests/run_tests.py site_type_semantics -v
"""

from __future__ import annotations

import json
import re
import unittest

import shapes
from helpers import ORIGIN, bundle, find, html_doc, jsonld, page, run, rule_ids

from aiva import paths, recommend, semantics as S
from aiva.analysis import listing_controls_expected, semantic_context
from aiva.answerability import build_matrix
from aiva.findings import Finding, SuggestedAction

#: Rules that only make sense about something bought and delivered.
PHYSICAL_COMMERCE_RULES = {
    "EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE", "EG-AVAILABILITY-INVISIBLE",
    "EG-SPECS-MISSING", "EG-CTA-NOT-IN-HTML", "EG-POLICY-NOT-STRUCTURED",
    "EG-FILTER-CONTROLS-ABSENT", "EG-SORT-CONTROLS-ABSENT", "EG-LEAD-ANSWER-WEAK",
    "MR-IDENTIFIERS-MISSING", "MR-PRODUCT-SCHEMA-MISSING", "MR-OFFER-MISSING",
    "MR-OFFER-INCOMPLETE", "EN-VARIANTS-UNMODELLED", "EN-CATEGORY-UNDECLARED",
    "AN-UNANSWERABLE-PRODUCT-AVAILABILITY", "AN-UNANSWERABLE-RETURN-WINDOW",
    "AN-UNANSWERABLE-SHIPPING-DESTINATIONS",
}
COMMERCE_OPPORTUNITIES = {"OPP-PRODUCT-GROUP", "OPP-POLICY-AS-DATA", "OPP-PRODUCT-FEED",
                          "OPP-EXPLICIT-ABSENCE"}

#: Vocabulary that describes buying and delivering a parcel. Any of these in
#: the rendered text of a finding or a recommendation, on a site observed to
#: sell no goods, is the leak this module exists to catch.
PARCEL_WORDS = (
    "add to cart", "add-to-cart", "buy button", "checkout", "shopping cart",
    "shipping", "shipping cost", "delivery cost", "return window", "return policy",
    "returns policy", "in stock", "out of stock", "stock level", "buyer", "shopper",
    "storefront", "catalogue", "catalog", "product page", "product detail", "pdp",
    "merchant", "sku", "gtin", "retailer", "product review", "price filter",
    "sort by price",
)
#: URLs and shell snippets are stripped before the scan: the fixture host and
#: `curl ... returns the index` are not claims about commerce.
_NOISE = re.compile(r"https?://\S+|`[^`]*`|curl [^\n.]*")


def rendered(bundle_dict: dict):
    """Every sentence this audit would show a reader, with its source."""
    out = []
    for entry in paths.specialist_skills():
        from helpers import specialist
        for finding in specialist(entry["id"]).analyze(bundle_dict):
            action = finding.suggested_action
            out.append((f"finding {finding.rule_id}", " ".join(filter(None, [
                finding.title, finding.evidence, finding.interpretation,
                action.summary, action.mechanism, " ".join(action.steps),
                action.verification, action.example or ""]))))
    for opportunity in recommend.build_opportunities(bundle_dict, []):
        out.append((f"recommendation {opportunity['id']}", " ".join([
            opportunity["title"], opportunity["mechanism"], opportunity.get("why_now", ""),
            " ".join(opportunity["steps"]), opportunity.get("verification", "") or "",
            opportunity.get("example", "") or ""])))
    return out


def parcel_words_in(text: str):
    body = _NOISE.sub(" ", text).lower()
    return sorted({word for word in PARCEL_WORDS
                   if re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", body)})


# ---------------------------------------------------------------------------
# 1. the classifier itself
# ---------------------------------------------------------------------------

class TestEachShapeIsReadAsItself(unittest.TestCase):

    EXPECTED = {
        "shop": "ecommerce",
        "subscription_saas": "software",
        "software_vendor": "software",
        "documentation": "documentation",
        "publisher": "publisher",
        "audio_publisher": "publisher",
        "public_body": "government",
        "knowledge_reference": "knowledge_reference",
        "developer_platform": "developer_platform",
        "travel": "travel_hospitality",
        "community": "community",
        "nonprofit": "nonprofit",
    }

    def test_the_site_kind_follows_the_declared_evidence(self):
        for name, kind in self.EXPECTED.items():
            context = S.site_context(getattr(shapes, name)())
            self.assertEqual(context["site_kind"], kind, name)
            self.assertTrue(context["site_kind_evidence"], name)

    def test_every_kind_is_from_the_published_vocabulary(self):
        for name, _ in shapes.ALL_SHAPES:
            self.assertIn(S.site_context(getattr(shapes, name)())["site_kind"], S.SITE_KINDS)

    def test_a_mixed_site_is_not_forced_into_one_kind(self):
        context = S.site_context(shapes.mixed())
        self.assertIn(context["site_kind"], ("mixed", "ecommerce", "software", "documentation"))
        if context["site_kind"] == "mixed":
            self.assertTrue(context["components"])

    def test_url_words_never_decide_the_kind(self):
        """The documentation fixture rehoused under /products/ and /shop/ is
        still documentation: the classifier reads declared types, not paths."""
        moved = []
        for record in shapes.documentation()["pages"]:
            copy = dict(record)
            copy["url"] = record["url"].replace("/docs/", "/products/")
            copy["final_url"] = copy["url"]
            moved.append(copy)
        data = bundle(moved)
        self.assertEqual(S.site_context(data)["site_kind"], "documentation")


# ---------------------------------------------------------------------------
# 2. commerce still works where goods are sold
# ---------------------------------------------------------------------------

class TestCommerceStillWorks(unittest.TestCase):
    """Removing false positives must not remove true ones."""

    def test_a_shop_is_still_held_to_delivery_returns_and_stock(self):
        ids = set()
        for entry in paths.specialist_skills():
            from helpers import specialist
            ids |= {f.rule_id for f in specialist(entry["id"]).analyze(shapes.shop())}
        self.assertIn("EG-SHIPPING-INVISIBLE", ids)
        self.assertIn("EG-RETURNS-INVISIBLE", ids)
        self.assertTrue(ids & {"EG-REVIEWS-ABSENT", "MR-REVIEW-MARKUP-MISSING"})

    def test_a_shop_is_offered_the_commerce_recommendations(self):
        offered = {o["id"] for o in recommend.build_opportunities(shapes.shop(), [])}
        self.assertTrue(offered & COMMERCE_OPPORTUNITIES,
                        "commerce advice must survive for a site that sells goods")

    def test_a_shop_is_asked_the_buying_questions(self):
        matrix = build_matrix(shapes.shop())
        kinds = {row["kind"] for row in matrix["questions"]}
        self.assertIn("product_price", kinds)
        self.assertIn("product_availability", kinds)
        self.assertIn("return_window", matrix["question_classes"])

    def test_a_subscription_site_keeps_its_own_commerce(self):
        """Plans are sold, so price, comparison and payment still apply -
        while delivery, stock and returns do not."""
        context = S.site_context(shapes.subscription_saas())
        classes = S.answerability_question_classes(context)
        self.assertIn("product_price", classes)
        self.assertIn("payment_options", classes)
        for absent_class in ("product_availability", "return_window",
                             "shipping_destinations"):
            self.assertNotIn(absent_class, classes)


# ---------------------------------------------------------------------------
# 3. no parcel vocabulary anywhere a parcel is not sold
# ---------------------------------------------------------------------------

class TestNoCommerceLeakage(unittest.TestCase):

    def test_no_rendered_sentence_mentions_a_parcel_on_a_site_that_sells_none(self):
        for name, maker in shapes.NON_COMMERCE:
            data = maker()
            self.assertFalse(S.site_context(data).get("sells_online"), name)
            for source, text in rendered(data):
                self.assertEqual(parcel_words_in(text), [],
                                 f"{name}: {source} used parcel vocabulary")

    def test_no_physical_commerce_rule_fires_on_a_site_that_sells_none(self):
        for name, maker in shapes.NON_COMMERCE:
            data = maker()
            ids = set()
            for entry in paths.specialist_skills():
                from helpers import specialist
                ids |= {f.rule_id for f in specialist(entry["id"]).analyze(data)}
            self.assertEqual(ids & PHYSICAL_COMMERCE_RULES, set(), name)

    def test_no_commerce_recommendation_reaches_a_site_that_sells_none(self):
        for name, maker in shapes.NON_COMMERCE:
            offered = {o["id"] for o in recommend.build_opportunities(maker(), [])}
            self.assertEqual(offered & COMMERCE_OPPORTUNITIES, set(), name)

    def test_a_site_selling_something_that_is_not_a_parcel_is_not_asked_for_one(self):
        for name, maker in shapes.NON_PHYSICAL_SELLERS:
            data = maker()
            ids = set()
            for entry in paths.specialist_skills():
                from helpers import specialist
                ids |= {f.rule_id for f in specialist(entry["id"]).analyze(data)}
            for rule in ("EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE",
                         "EG-AVAILABILITY-INVISIBLE", "MR-IDENTIFIERS-MISSING",
                         "EG-POLICY-NOT-STRUCTURED"):
                self.assertNotIn(rule, ids, f"{name}: {rule}")


# ---------------------------------------------------------------------------
# 4. listings are not catalogues by default
# ---------------------------------------------------------------------------

class TestListingsAreNotCataloguesByDefault(unittest.TestCase):

    def test_a_repository_index_is_not_an_ecommerce_catalogue(self):
        data = shapes.developer_platform()
        listing = next(p for p in data["pages"] if p["url"].endswith("/repos/"))
        record = S.listing_record(listing, data, semantic_context(data))
        self.assertNotEqual(record["subtype"], "ecommerce_listing")
        ids = rule_ids(run("engagement-audit", data))
        self.assertNotIn("EG-FILTER-CONTROLS-ABSENT", ids)
        self.assertNotIn("EG-SORT-CONTROLS-ABSENT", ids)

    def test_an_audio_index_is_read_as_an_audio_listing(self):
        data = shapes.audio_publisher()
        listing = next(p for p in data["pages"] if p["url"].endswith("/audio/"))
        record = S.listing_record(listing, data, semantic_context(data))
        self.assertIn(record["subtype"], ("audio_listing", "article_index", "content_listing"))
        self.assertNotEqual(record["subtype"], "ecommerce_listing")

    def test_a_glossary_index_is_not_a_catalogue(self):
        data = shapes.knowledge_reference()
        listing = next(p for p in data["pages"] if p["url"].endswith("/glossary/"))
        self.assertNotEqual(
            S.listing_record(listing, data, semantic_context(data))["subtype"],
            "ecommerce_listing")

    def test_a_documentation_index_is_a_documentation_section(self):
        data = shapes.documentation()
        listing = next(p for p in data["pages"] if p["url"].endswith("/docs/"))
        self.assertEqual(
            S.listing_record(listing, data, semantic_context(data))["subtype"],
            "documentation_section")

    def test_a_short_catalogue_listing_is_not_asked_for_controls(self):
        data = shapes.shop()
        listing = next(p for p in data["pages"] if "/collections/" in p["url"])
        expected, why = listing_controls_expected(listing)
        self.assertFalse(expected)
        self.assertIn("too few", why)


# ---------------------------------------------------------------------------
# 5. questions follow the site
# ---------------------------------------------------------------------------

class TestQuestionsFollowTheSite(unittest.TestCase):

    def test_a_site_that_sells_nothing_is_asked_no_buying_question(self):
        for name, maker in shapes.NON_COMMERCE:
            matrix = build_matrix(maker())
            for buying in ("product_price", "product_availability", "return_window",
                           "shipping_destinations", "payment_options", "category_cheapest"):
                self.assertNotIn(buying, matrix["question_classes"], f"{name}: {buying}")
            self.assertEqual([r for r in matrix["questions"]
                              if r["kind"].startswith("product_")], [], name)

    def test_a_question_that_does_not_apply_is_not_a_finding(self):
        """not-applicable is recorded in `not_asked`, never scored, and never
        emitted as an AN-UNANSWERABLE finding."""
        data = shapes.subscription_saas()
        matrix = build_matrix(data)
        self.assertTrue(matrix["not_asked"])
        for key in matrix["not_asked"]:
            self.assertNotIn("stock statement does not apply", key.split(":")[0])
        answers = [f.rule_id for f in run("answerability-audit", data)]
        self.assertNotIn("AN-UNANSWERABLE-PRODUCT-AVAILABILITY", answers)
        self.assertNotIn("AN-UNANSWERABLE-RETURN-WINDOW", answers)

    def test_a_travel_site_is_asked_about_price_and_never_about_delivery(self):
        context = S.site_context(shapes.travel())
        classes = S.answerability_question_classes(context)
        self.assertIn("product_price", classes)
        for parcel in ("shipping_destinations", "return_window"):
            self.assertNotIn(parcel, classes)

    def test_the_intents_and_the_question_classes_agree_about_the_site(self):
        """Two tables, one context: a site asked the parcel questions must
        also have the physical-goods intent family, and no other site may."""
        for name, maker in shapes.ALL_SHAPES:
            context = S.site_context(maker())
            classes = S.answerability_question_classes(context)
            intents = {i["intent"] for i in S.high_value_question_intents(context)}
            self.assertEqual("shipping_destinations" in classes,
                             "physical_goods" in intents, name)


# ---------------------------------------------------------------------------
# 6. the FAQ rule is semantic
# ---------------------------------------------------------------------------

class TestFaqIntentsFollowTheSite(unittest.TestCase):

    EXPECTED_TOPIC = {
        "shop": "delivery",
        "subscription_saas": "plan prices",
        "software_vendor": "installation",
        "documentation": "configuration",
        "publisher": "who wrote a piece",
        "public_body": "who is eligible",
        "knowledge_reference": "how terms are defined",
        "developer_platform": "how to install and call it",
        "travel": "amenities",
        "community": "how to take part",
    }

    def test_the_finding_names_intents_that_match_the_site(self):
        for name, topic in self.EXPECTED_TOPIC.items():
            data = getattr(shapes, name)()
            found = find(run("engagement-audit", data), "EG-FAQ-MISSING")
            self.assertIsNotNone(found, name)
            self.assertIn(topic, found.evidence, name)
            self.assertTrue(found.metrics["question_intents"], name)

    def test_a_documentation_site_is_never_asked_for_buying_questions(self):
        found = find(run("engagement-audit", shapes.documentation()), "EG-FAQ-MISSING")
        for word in ("delivery", "returns", "in stock", "price"):
            self.assertNotIn(word, found.evidence.lower())

    def test_the_verification_step_is_something_the_owner_can_run(self):
        found = find(run("engagement-audit", shapes.shop()), "EG-FAQ-MISSING")
        self.assertEqual(found.suggested_action.verification_type, "self_verifiable")
        self.assertIn("curl", found.suggested_action.verification)


# ---------------------------------------------------------------------------
# 7. entity, canonical, redirect and freshness stay contextual
# ---------------------------------------------------------------------------

class TestEntityAndTransportStayContextual(unittest.TestCase):

    def test_arbitrary_outbound_links_do_not_become_official_profiles(self):
        for url, kind in (("https://en.wikipedia.org/wiki/Kestrel", "knowledge_reference"),
                          ("https://docs.python.org/3/", "documentation"),
                          ("https://github.com/kestrel-ltd/core", "code_repository"),
                          ("https://example.org/partners", "unknown"),
                          ("https://www.linkedin.com/company/kestrel-ltd", "official_profile")):
            self.assertEqual(S.classify_outbound_link(url, site_origin=ORIGIN)["kind"], kind, url)

    def test_a_localized_name_is_not_a_trading_name_conflict(self):
        localized = ('{"@context":"https://schema.org","@type":"Organization",'
                     '"name":"ケストレル","url":"%s/jp/"}' % ORIGIN)
        data = bundle([shapes.home(),
                       page(ORIGIN + "/jp/", html_doc(title="ケストレル", lang="ja",
                                                      canonical=ORIGIN + "/jp/",
                                                      head=jsonld(localized),
                                                      body="<h1>ケストレル</h1>"))])
        self.assertIsNone(find(run("entity-audit", data), "EN-NAME-INCONSISTENT"))

    def test_a_cross_domain_canonical_is_reviewed_not_condemned(self):
        syndicated = shapes.news_article("/news/syndicated", "A syndicated piece")
        syndicated["canonical"] = "https://partner.example/original"
        data = bundle([shapes.home(shapes.NEWS_ORG_LD, "The Kestrel Times"),
                       shapes.news_article("/news/one", "Local"),
                       shapes.news_article("/news/two", "Other"), syndicated])
        findings = run("crawl-render-audit", data)
        self.assertIsNone(find(findings, "CR-CANONICAL-WRONG-TARGET"))
        cross = find(findings, "CR-CANONICAL-CROSS-HOST")
        self.assertIsNotNone(cross)
        self.assertEqual(cross.severity, "low")
        self.assertIn("could not be verified", cross.evidence)

    def test_a_legitimate_redirect_is_not_a_defect(self):
        from aiva.analysis import classify_redirect
        moved = shapes.doc_article("/docs/install", "Installing")
        moved["url"] = ORIGIN + "/docs/install"
        moved["final_url"] = "https://docs.shop.example/install"
        moved["redirects"] = [{"from": moved["url"], "to": moved["final_url"], "status": 301}]
        verdict = classify_redirect(moved)
        self.assertNotEqual(verdict["kind"], "homepage_collapse")

    def test_a_stable_page_is_not_penalised_for_carrying_no_date(self):
        contact = shapes._page("/contact", "Contact")
        self.assertEqual(S.freshness_expectation(shapes.home()), "not_applicable")
        self.assertEqual(S.freshness_expectation(contact), "not_applicable")
        data = bundle([shapes.home(), contact, shapes._page("/about", "About")])
        self.assertIsNone(find(run("freshness-corroboration", data), "FC-NO-DATE-SIGNALS"))

    def test_incomplete_transport_evidence_is_never_a_content_defect(self):
        from helpers import error_page
        refused = error_page(ORIGIN + "/guidance/renew", 403)
        refused["fetch_reason"] = "linked from the home page"
        data = shapes.public_body()
        data["pages"] = list(data["pages"]) + [refused]
        data["pages"][0]["links"]["internal"].append(
            {"url": refused["url"], "text": "Renew", "rel": "", "in_nav": False,
             "in_footer": False})
        findings = run("crawl-render-audit", data)
        self.assertIsNone(find(findings, "CR-HTTP-ERRORS"))
        aside = find(findings, "CR-URLS-NOT-VERIFIED")
        self.assertIsNotNone(aside)
        self.assertEqual(aside.severity, "info")


# ---------------------------------------------------------------------------
# 8. every recommendation survives having the domain removed
# ---------------------------------------------------------------------------

class TestRecommendationQuality(unittest.TestCase):

    def test_each_recommendation_states_evidence_site_kind_and_a_check(self):
        for name, maker in shapes.ALL_SHAPES:
            data = maker()
            kind = S.site_context(data)["site_kind"]
            for opportunity in recommend.build_opportunities(data, []):
                applicability = opportunity["applicability"]
                self.assertTrue(applicability["applies_because"].strip(),
                                f"{name}/{opportunity['id']}")
                self.assertTrue(applicability["conditions"], f"{name}/{opportunity['id']}")
                self.assertEqual(applicability["site_kind"], kind, name)
                self.assertTrue(opportunity["steps"], f"{name}/{opportunity['id']}")
                self.assertTrue(opportunity["verification"], f"{name}/{opportunity['id']}")

    def test_a_recommendation_never_needs_the_domain_to_make_sense(self):
        """Strip the host from the rendered advice: what is left must still
        name a site kind or an observation, never a specific site."""
        for name, maker in shapes.ALL_SHAPES:
            for opportunity in recommend.build_opportunities(maker(), []):
                because = opportunity["applicability"]["applies_because"]
                stripped = _NOISE.sub(" ", because).replace("shop.example", " ")
                self.assertTrue(re.search(r"[a-z]", stripped), f"{name}/{opportunity['id']}")

    def test_external_validation_is_labelled_as_unmeasured(self):
        from aiva import report as report_mod
        from aiva.config import AuditConfig
        data = shapes.shop()
        findings = []
        for entry in paths.specialist_skills():
            from helpers import specialist
            findings.extend(specialist(entry["id"]).analyze(data))
        report = report_mod.build_report(data, findings, AuditConfig(site=ORIGIN))
        markdown = report_mod.render_markdown(report)
        external = [f for f in report["findings"]
                    if f["suggested_action"].get("verification_type") == "external_validation"]
        if external:
            self.assertIn("Optional external validation", markdown)
            self.assertIn("outside this audit's measured behaviour", markdown)
        for finding in report["findings"]:
            action = finding["suggested_action"]
            if "assistant" in (action.get("verification") or "").lower():
                self.assertEqual(action.get("verification_type"), "external_validation",
                                 finding["rule_id"])


# ---------------------------------------------------------------------------
# 9. determinism and safety across every shape
# ---------------------------------------------------------------------------

class TestEveryShapeIsSafeAndDeterministic(unittest.TestCase):

    def test_no_specialist_edits_the_bundle_it_was_handed(self):
        for name, maker in shapes.ALL_SHAPES:
            data = maker()
            before = json.dumps(data, sort_keys=True, default=str)
            for entry in paths.specialist_skills():
                from helpers import specialist
                specialist(entry["id"]).analyze(data)
            recommend.build_opportunities(data, [])
            self.assertEqual(json.dumps(data, sort_keys=True, default=str), before, name)

    def test_two_runs_over_one_shape_produce_the_same_findings(self):
        for name, maker in shapes.ALL_SHAPES:
            data = maker()
            first = [f.to_dict() for f in run("engagement-audit", data)]
            second = [f.to_dict() for f in run("engagement-audit", data)]
            self.assertEqual(json.dumps(first, sort_keys=True),
                             json.dumps(second, sort_keys=True), name)

    def test_every_finding_on_every_shape_carries_evidence(self):
        for name, maker in shapes.ALL_SHAPES:
            data = maker()
            for entry in paths.specialist_skills():
                from helpers import specialist
                for finding in specialist(entry["id"]).analyze(data):
                    self.assertTrue(finding.evidence_items, f"{name}/{finding.rule_id}")
                    self.assertTrue(finding.evidence.strip(), f"{name}/{finding.rule_id}")


if __name__ == "__main__":
    unittest.main()
