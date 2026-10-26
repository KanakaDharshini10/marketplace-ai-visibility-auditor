"""Proactive recommendations apply only where their conditions are observed.

Every entry in :data:`aiva.recommend.LIBRARY` carries applicability
metadata - the kinds of site it is for, the pages it concerns, the evidence
it needs - and every opportunity a report emits says, in its own record,
why it applied to *this* site. These tests pin that contract on the shapes
where ecommerce assumptions used to leak: a documentation site, a publisher,
a public body, a software vendor and a mixed site.

Run just this file:

    python3 tests/run_tests.py recommendation_applicability -v
"""

from __future__ import annotations

import json
import unittest

from helpers import ORIGIN, bundle, html_doc, jsonld, page

from aiva import examples, recommend
from aiva import semantics as S
from aiva.analysis import site_vocabulary
from aiva.findings import Finding, SuggestedAction

ORG_LD = ('{"@context":"https://schema.org","@type":"Organization","name":"Kestrel Ltd",'
          '"url":"%s/"}' % ORIGIN)
GOV_LD = ('{"@context":"https://schema.org","@type":"GovernmentOrganization",'
          '"name":"Water Regulator","url":"%s/"}' % ORIGIN)
NEWS_ORG_LD = ('{"@context":"https://schema.org","@type":"NewsMediaOrganization",'
               '"name":"The Kestrel Times","url":"%s/"}' % ORIGIN)

PHYSICAL_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"%s","sku":"%s",'
    '"color":"Brown","material":"Leather",'
    '"weight":{"@type":"QuantitativeValue","value":"1.1","unitCode":"KGM"},'
    '"offers":{"@type":"Offer","price":"%s","priceCurrency":"GBP",'
    '"availability":"https://schema.org/InStock"}}')
SOFTWARE_LD = (
    '{"@context":"https://schema.org","@type":"SoftwareApplication","name":"%s",'
    '"operatingSystem":"Windows, macOS","applicationCategory":"DeveloperApplication",'
    '"softwareVersion":"4.2","offers":{"@type":"Offer","price":"%s","priceCurrency":"USD"}}')
TECH_LD = ('{"@context":"https://schema.org","@type":"TechArticle","headline":"%s",'
           '"dateModified":"2026-05-01"}')
NEWS_LD = ('{"@context":"https://schema.org","@type":"NewsArticle","headline":"%s",'
           '"datePublished":"2026-05-01"}')

LONG = " ".join(["The page explains the subject in some detail."] * 30)


def _home(ld: str = ORG_LD, name: str = "Kestrel Ltd") -> dict:
    return page(ORIGIN + "/", html_doc(title=name, canonical=ORIGIN + "/", head=jsonld(ld),
                                       body=f"<h1>{name}</h1><p>{LONG}</p>"))


def _physical(path: str, name: str, price: str) -> dict:
    return page(ORIGIN + path, html_doc(
        title=name, canonical=ORIGIN + path, head=jsonld(PHYSICAL_LD % (name, name[:3], price)),
        body=f"<main><h1>{name}</h1><p>£{price}. In stock. Ships in 2 days.</p>"
             f"<table><tr><th>Weight</th><td>1.1 kg</td></tr></table>"
             f"<form action='/cart'><select name='size'><option>8</option><option>9</option>"
             f"</select><button>Add to cart</button></form><p>{LONG}</p></main>"))


def _software(path: str, name: str, price: str) -> dict:
    return page(ORIGIN + path, html_doc(
        title=name, canonical=ORIGIN + path, head=jsonld(SOFTWARE_LD % (name, price)),
        body=f"<main><h1>{name}</h1><p>${price} licence. Download the installer for Windows "
             f"or macOS. System requirements: 8 GB RAM.</p><p>{LONG}</p></main>"))


def _doc(path: str, title: str) -> dict:
    return page(ORIGIN + path, html_doc(
        title=title, canonical=ORIGIN + path, head=jsonld(TECH_LD % title),
        body=f"<main><h1>{title}</h1><p>{LONG}</p></main>"))


def _news(path: str, title: str) -> dict:
    return page(ORIGIN + path, html_doc(
        title=title, canonical=ORIGIN + path, head=jsonld(NEWS_LD % title),
        body=f"<main><h1>{title}</h1><p>{LONG}</p></main>"))


def _doc_index() -> dict:
    return page(ORIGIN + "/docs/", html_doc(
        title="Docs", canonical=ORIGIN + "/docs/",
        head=jsonld('{"@context":"https://schema.org","@type":"CollectionPage","name":"Docs"}'),
        body="<main><h1>Docs</h1><ul><li><a href='/docs/start'>Start</a></li>"
             "<li><a href='/docs/config'>Config</a></li>"
             "<li><a href='/docs/deploy'>Deploy</a></li></ul></main>"))


def documentation_site() -> dict:
    return bundle([_home(), _doc_index(), _doc("/docs/start", "Getting started"),
                   _doc("/docs/config", "Configuration"), _doc("/docs/deploy", "Deploying")])


def publisher_site() -> dict:
    return bundle([_home(NEWS_ORG_LD, "The Kestrel Times"),
                   _news("/news/one", "Council approves plan"),
                   _news("/news/two", "River levels rise"),
                   _news("/news/three", "Festival returns")])


def government_site() -> dict:
    return bundle([_home(GOV_LD, "Water Regulator"),
                   page(ORIGIN + "/apply", html_doc(
                       title="Apply for a licence", canonical=ORIGIN + "/apply",
                       body=f"<main><h1>Apply for a licence</h1><p>{LONG}</p></main>")),
                   page(ORIGIN + "/guidance", html_doc(
                       title="Guidance", canonical=ORIGIN + "/guidance",
                       body=f"<main><h1>Guidance</h1><p>{LONG}</p></main>"))])


def software_site() -> dict:
    return bundle([_home(), _software("/products/studio", "Kestrel Studio", "49"),
                   _software("/products/studio-pro", "Kestrel Studio Pro", "99")])


def shop_site() -> dict:
    return bundle([_home(), _physical("/products/trail-boot", "Trail Boot", "120"),
                   _physical("/products/summit-boot", "Summit Boot", "210")])


def mixed_site() -> dict:
    return bundle([_home(), _physical("/products/trail-boot", "Trail Boot", "120"),
                   _software("/products/studio", "Kestrel Studio", "49"),
                   _doc_index(), _doc("/docs/start", "Getting started"),
                   _doc("/docs/config", "Configuration")])


def _ids(data: dict, findings=None) -> dict:
    return {o["id"]: o for o in recommend.build_opportunities(data, findings or [])}


COMMERCE_ONLY = {"OPP-PRODUCT-GROUP", "OPP-POLICY-AS-DATA", "OPP-PRODUCT-FEED",
                 "OPP-EXPLICIT-ABSENCE"}
SELLING_ONLY = COMMERCE_ONLY | {"OPP-ANSWER-PAGES", "OPP-INTENT-COVERAGE"}


class TestLibraryContract(unittest.TestCase):

    def test_every_entry_carries_the_applicability_metadata(self):
        for oid, spec in recommend.LIBRARY.items():
            for key in ("title", "site_kinds", "page_contexts", "evidence_requirement",
                        "grounding", "priority", "effort", "impact", "dimension"):
                self.assertIn(key, spec, f"{oid} lacks {key}")
            self.assertIn(spec["grounding"], recommend.GROUNDING)
            kinds = spec["site_kinds"]
            if kinds != "any":
                self.assertTrue(set(kinds) <= set(S.SITE_KINDS), oid)

    def test_every_entry_has_exactly_one_generator(self):
        generated = set(recommend._GENERATOR_IDS.values())
        self.assertEqual(generated, set(recommend.LIBRARY))
        self.assertEqual(len(recommend._GENERATOR_IDS), len(recommend.LIBRARY))

    def test_every_emitted_opportunity_explains_why_it_applied(self):
        for data in (documentation_site(), publisher_site(), government_site(),
                     software_site(), shop_site(), mixed_site()):
            for opportunity in recommend.build_opportunities(data, []):
                applicability = opportunity["applicability"]
                self.assertEqual(
                    set(applicability),
                    {"site_kind", "applies_because", "conditions", "evidence_requirement",
                     "site_kinds", "page_contexts"}, opportunity["id"])
                self.assertTrue(applicability["applies_because"].strip(), opportunity["id"])
                self.assertTrue(applicability["conditions"], opportunity["id"])
                self.assertIn(applicability["site_kind"], S.SITE_KINDS)
                json.dumps(opportunity)

    def test_applicability_of_reports_the_site_kind_gate(self):
        verdict = recommend.applicability_of("OPP-PRODUCT-GROUP", documentation_site())
        self.assertEqual(verdict["site_kind"], "documentation")
        self.assertFalse(verdict["site_kind_allowed"])
        self.assertIn("not one of", verdict["reason"])
        verdict = recommend.applicability_of("OPP-MONITORING", documentation_site())
        self.assertTrue(verdict["site_kind_allowed"])
        self.assertIn("every kind", verdict["reason"])


class TestNonSellingSitesGetNoCommerceAdvice(unittest.TestCase):
    """The leak that mattered: variant markup, product feeds, return-policy
    data and comparison pages recommended to sites that sell nothing."""

    def test_a_documentation_site(self):
        ids = _ids(documentation_site())
        self.assertEqual(set(ids) & SELLING_ONLY, set())
        self.assertEqual(S.site_context(documentation_site())["site_kind"], "documentation")

    def test_a_publisher(self):
        data = publisher_site()
        self.assertEqual(S.site_context(data)["site_kind"], "publisher")
        self.assertEqual(set(_ids(data)) & SELLING_ONLY, set())

    def test_a_public_body(self):
        data = government_site()
        self.assertEqual(S.site_context(data)["site_kind"], "government")
        ids = _ids(data)
        self.assertEqual(set(ids) & SELLING_ONLY, set())
        # What a public body *is* offered names it as one.
        for opportunity in ids.values():
            self.assertEqual(opportunity["applicability"]["site_kind"], "government")

    def test_a_software_vendor_is_not_asked_for_physical_goods_markup(self):
        data = software_site()
        self.assertEqual(S.site_context(data)["site_kind"], "software")
        ids = _ids(data)
        self.assertEqual(set(ids) & COMMERCE_ONLY, set(),
                         "ProductGroup, feeds, return policies and negative physical "
                         "attributes are physical-goods advice")

    def test_a_shop_is_offered_the_commerce_recommendations_it_qualifies_for(self):
        ids = _ids(shop_site())
        self.assertIn("OPP-PRODUCT-GROUP", ids)
        self.assertIn("OPP-POLICY-AS-DATA", ids)
        self.assertIn("OPP-PRODUCT-FEED", ids)
        self.assertIn("physical", ids["OPP-PRODUCT-FEED"]["applicability"]["applies_because"])


class TestComparisonPagesNeedARange(unittest.TestCase):

    def test_two_physical_items_make_a_range(self):
        ids = _ids(shop_site())
        self.assertIn("OPP-ANSWER-PAGES", ids)
        self.assertIn("physical: 2", ids["OPP-ANSWER-PAGES"]["applicability"]["applies_because"])

    def test_two_software_editions_make_a_range_and_the_advice_says_plans(self):
        ids = _ids(software_site())
        self.assertIn("OPP-ANSWER-PAGES", ids)
        self.assertTrue(any("plan-comparison" in step for step in ids["OPP-ANSWER-PAGES"]["steps"]))

    def test_one_boot_and_one_licence_are_not_a_range(self):
        data = bundle([_home(), _physical("/products/trail-boot", "Trail Boot", "120"),
                       _software("/products/studio", "Kestrel Studio", "49")])
        self.assertNotIn("OPP-ANSWER-PAGES", _ids(data))
        verdict = S.is_comparison_applicable(data)
        self.assertFalse(verdict)
        self.assertIn("one kind", verdict["reason"])

    def test_a_single_item_is_not_a_range(self):
        data = bundle([_home(), _physical("/products/trail-boot", "Trail Boot", "120")])
        self.assertNotIn("OPP-ANSWER-PAGES", _ids(data))


class TestScopedGenericRecommendations(unittest.TestCase):

    def test_referral_continuity_needs_deep_pages(self):
        one_page = bundle([_home()])
        self.assertNotIn("OPP-REFERRAL-CONTINUITY", _ids(one_page))
        ids = _ids(documentation_site())
        self.assertIn("OPP-REFERRAL-CONTINUITY", ids)
        self.assertIn("deep content pages", ids["OPP-REFERRAL-CONTINUITY"]["applicability"]["applies_because"])

    def test_brand_facts_is_scoped_to_undescribed_organisations(self):
        thin = documentation_site()
        self.assertIn("OPP-BRAND-FACTS", _ids(thin))
        full = ('{"@context":"https://schema.org","@type":"Organization","name":"Kestrel Ltd",'
                '"url":"%s/","description":"Makes things.","foundingDate":"1990",'
                '"address":{"@type":"PostalAddress","addressLocality":"Bristol"},'
                '"sameAs":["https://www.linkedin.com/company/kestrel-ltd"],'
                '"logo":"%s/logo.png"}' % (ORIGIN, ORIGIN))
        described = bundle([_home(full), _doc_index(), _doc("/docs/start", "Getting started"),
                            _doc("/docs/config", "Configuration")])
        self.assertNotIn("OPP-BRAND-FACTS", _ids(described))

    def test_brand_facts_is_suppressed_when_the_organisation_node_is_already_a_finding(self):
        finding = Finding(rule_id="EN-ORG-INCOMPLETE", title="t", severity="medium",
                          pillar="entity", evidence="e",
                          suggested_action=SuggestedAction(summary="fill it in"))
        self.assertNotIn("OPP-BRAND-FACTS", _ids(documentation_site(), [finding]))

    def test_third_party_sync_needs_an_organisation(self):
        anonymous = bundle([page(ORIGIN + "/", html_doc(title="Hello", body="<h1>Hello</h1>")),
                            _doc("/docs/start", "Getting started"),
                            _doc("/docs/config", "Configuration")])
        self.assertNotIn("OPP-THIRD-PARTY-SYNC", _ids(anonymous))
        self.assertIn("OPP-THIRD-PARTY-SYNC", _ids(documentation_site()))

    def test_llms_txt_example_follows_the_site_shape(self):
        for data, must, must_not in (
                (documentation_site(), "## Documentation", "## Products"),
                (government_site(), "## Services", "in stock"),
                (publisher_site(), "## Sections", "## Products"),
                (software_site(), "## Product", "in stock"),
                (shop_site(), "## Products", "## Services")):
            context = S.site_context(data)
            text = examples.llms_txt(site_vocabulary(data), context)
            self.assertIn(must, text, context["site_kind"])
            self.assertNotIn(must_not, text, context["site_kind"])

    def test_the_agent_index_recommendation_shows_the_shaped_example(self):
        ids = _ids(documentation_site())
        self.assertIn("OPP-AI-DISCOVERY-SURFACE", ids)
        self.assertIn("## Documentation", ids["OPP-AI-DISCOVERY-SURFACE"]["example"])
        self.assertNotIn("Returns", ids["OPP-AI-DISCOVERY-SURFACE"]["example"])

    def test_the_product_markup_example_matches_what_the_site_sells(self):
        software = examples.product_jsonld(site_vocabulary(software_site()),
                                           S.site_context(software_site()))
        self.assertIn('"SoftwareApplication"', software)
        self.assertNotIn("gtin13", software)
        self.assertNotIn("InStock", software)
        physical = examples.product_jsonld(site_vocabulary(shop_site()), S.site_context(shop_site()))
        self.assertIn("gtin13", physical)
        self.assertIn("InStock", physical)

    def test_the_monitoring_probe_asks_what_the_site_is_for(self):
        probe = examples.monitoring_probe(site_vocabulary(government_site()),
                                          S.site_context(government_site()))
        self.assertIn("services", probe)
        self.assertNotIn("cost", probe)


class TestTransportOnlyRuns(unittest.TestCase):

    def test_a_run_that_read_nothing_keeps_only_generic_advice(self):
        data = bundle([])
        for opportunity in recommend.build_opportunities(data, []):
            self.assertEqual(opportunity["grounding"], "generic", opportunity["id"])
            self.assertEqual(opportunity["applicability"]["site_kind"], "unknown")


class TestWordingIsScopedToWhatWasMeasured(unittest.TestCase):
    """The library states what a change *provides*; it never asserts how any
    assistant behaves. The source-level guard lives in test_compliance; this
    checks the rendered output on every shape."""

    FORBIDDEN = ("assistants weight", "fetchers read", "guarantees retrieval",
                 "makes the assistant cite", "rank you higher", "causes hallucinations",
                 "assistants will ignore", "machines treat", "almost no storefront")

    def test_rendered_recommendations_carry_no_behavioural_claims(self):
        for data in (documentation_site(), publisher_site(), government_site(),
                     software_site(), shop_site(), mixed_site()):
            for opportunity in recommend.build_opportunities(data, []):
                text = json.dumps(opportunity).lower()
                for phrase in self.FORBIDDEN:
                    self.assertNotIn(phrase, text, opportunity["id"])

    def test_external_verification_is_labelled_as_such(self):
        for data in (shop_site(), software_site()):
            for opportunity in recommend.build_opportunities(data, []):
                if "assistant" in opportunity["verification"].lower():
                    self.assertEqual(opportunity["verification_type"], "external_validation",
                                     opportunity["id"])


if __name__ == "__main__":
    unittest.main()
