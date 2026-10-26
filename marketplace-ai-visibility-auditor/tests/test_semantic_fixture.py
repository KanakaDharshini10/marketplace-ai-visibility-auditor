"""One mixed site, audited end to end, with every semantic decision asserted.

``tests/fixtures/site_semantic`` is a generic site that carries, on one
host: a physical product, a software product, a subscription plan, a
service, a documentation section, a publisher section, an ecommerce
listing, a content listing, a department with a parent organisation,
localized organisation names in two scripts, official profiles beside
knowledge, documentation and ambiguous external links, a cross-domain
canonical, a redirect chain, a 403, a 429, a timeout, a noindexed public
page, a noindexed private page, a visible date with no machine date, a
partial Organization node, a page with two ``<h1>`` elements, a page with
none, and no site search.

This module runs the real pipeline over it - collection, six specialists,
report - and asserts what each of those elements must produce. It is the
regression test for "page type is not enough": every assertion here failed,
or asserted the opposite, before the semantic layer existed.

Run just this file:

    python3 tests/run_tests.py semantic_fixture -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

import helpers

from aiva import localserve, orchestrator, paths, recommend
from aiva import report as report_mod
from aiva import semantics as S
from aiva.config import AuditConfig

FIXTURE = helpers.ROOT / "tests" / "fixtures" / "site_semantic"

#: The pipeline runs once for the whole module: every class reads the same
#: bundle and the same report, which is also the determinism these tests
#: assert - a second run over one bundle must be indistinguishable.
_AUDIT = None


def _audit():
    global _AUDIT
    if _AUDIT is not None:
        return _AUDIT
    server, base = localserve.start(FIXTURE)
    try:
        config = AuditConfig(site=base, request_delay_s=0.1, check_external=False)
        # The fixture serves one deliberately slow URL; a short timeout keeps
        # the suite quick and is exactly the transport case being tested.
        config.timeout_s = 1.5
        config.max_retries = 0
        _AUDIT = orchestrator.run_audit(config)
        return _AUDIT
    finally:
        server.shutdown()
        server.server_close()


class SemanticFixtureCase(unittest.TestCase):
    """Shared audit: the pipeline runs once for the whole module."""

    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.report = _audit()
        cls.base = (cls.bundle.get("site") or {}).get("origin") or ""
        cls.pages = {p["url"][len(cls.base):] or "/": p for p in cls.bundle["pages"]}
        cls.findings = {f["rule_id"]: f for f in cls.report["findings"]}
        cls.context = S.site_context(cls.bundle)

    def page(self, path: str) -> dict:
        self.assertIn(path, self.pages, f"{path} was not fetched")
        return self.pages[path]

    def urls_of(self, rule_id: str):
        finding = self.findings.get(rule_id)
        self.assertIsNotNone(finding, f"{rule_id} did not fire")
        return [u[len(self.base):] for u in finding["affected_urls"]]

    def cited_anywhere(self, path: str) -> bool:
        url = self.base + path
        for finding in self.report["findings"]:
            cited = set(finding["affected_urls"]) | {i.get("url") for i in finding["evidence_items"]}
            if url in cited:
                return True
        return False


class TestTheRunItself(SemanticFixtureCase):

    def test_the_report_is_valid_and_every_specialist_contributed(self):
        self.assertEqual(report_mod.validate_report(self.report), [])
        self.assertTrue(self.report["diagnostics"]["schema_validation"]["valid"])
        skills = {run["skill"] for run in self.report["diagnostics"]["skill_runs"]}
        self.assertEqual(len(skills), 6)
        for run in self.report["diagnostics"]["skill_runs"]:
            self.assertEqual(run.get("status"), "ok", run)

    def test_the_site_is_read_as_mixed_and_says_why(self):
        self.assertEqual(self.report["coverage"]["site_kind"], "mixed")
        evidence = " ".join(self.report["diagnostics"]["semantics"]["site_kind_evidence"])
        for expected in ("sell physical goods", "sell software or subscriptions",
                         "documentation", "article"):
            self.assertIn(expected, evidence)


class TestProductSubtypes(SemanticFixtureCase):
    """Four sellable things of four different kinds, told apart from their
    own markup and words - never from the words in their URLs."""

    EXPECTED = {
        "/products/trail-boot.html": "physical",
        "/products/kestrel-studio.html": "software",
        "/products/cloud-team.html": "subscription",
        "/services/boiler-servicing.html": "service",
    }

    def test_each_page_is_read_as_the_kind_of_thing_it_describes(self):
        for path, subtype in self.EXPECTED.items():
            record = S.product_record(self.page(path), self.context)
            self.assertEqual(record["subtype"], subtype, path)
            self.assertTrue(record["evidence"], path)
            self.assertTrue(record["sells"], path)

    def test_the_coverage_block_counts_the_kinds(self):
        self.assertEqual(self.report["coverage"]["product_subtypes"],
                         {"physical": 1, "software": 1, "subscription": 1})

    def test_the_service_page_is_not_typed_as_a_product_page(self):
        """Its page type is `other`; its *kind* is still read, and the
        commerce rules ask the kind, not the type."""
        self.assertEqual(self.page("/services/boiler-servicing.html")["page_type"], "other")
        self.assertEqual(S.product_record(self.page("/services/boiler-servicing.html"),
                                          self.context)["subtype"], "service")


class TestCommerceExpectationsFollowTheKind(SemanticFixtureCase):

    def test_delivery_returns_stock_and_specs_are_asked_of_the_boot_alone(self):
        for rule in ("EG-RETURNS-INVISIBLE",):
            self.assertEqual(self.urls_of(rule), ["/products/trail-boot.html"])
        for rule in ("EG-SHIPPING-INVISIBLE", "EG-AVAILABILITY-INVISIBLE", "EG-SPECS-MISSING"):
            for url in self.urls_of(rule) if rule in self.findings else []:
                self.assertEqual(url, "/products/trail-boot.html", rule)

    def test_the_evidence_names_the_pages_it_set_aside_and_why(self):
        returns = self.findings["EG-RETURNS-INVISIBLE"]
        self.assertEqual(returns["metrics"]["not_assessed"], 2)
        self.assertIn("does not apply to a software item", returns["evidence"])
        self.assertIn("does not apply to a subscription item", returns["evidence"])

    def test_the_coverage_block_reports_every_expectation_it_did_not_apply(self):
        by_name = {e["expectation"]: e
                   for e in self.report["coverage"]["expectations_not_applied"]}
        for name in ("shipping", "returns", "stock", "physical_specifications",
                     "identifiers", "purchase_cta"):
            entry = by_name[name]
            self.assertEqual(entry["product_pages"], 3, name)
            self.assertEqual(entry["applied_to"], 1, name)
            reasons = " ".join(r["reason"] for r in entry["not_applied"])
            self.assertIn("software", reasons, name)
            self.assertIn("subscription", reasons, name)
        # Reviews and price apply to everything sold here, so nothing is aside.
        self.assertEqual(by_name.get("price", {"not_applied": []})["not_applied"], [])

    def test_no_finding_asks_the_software_or_the_plan_a_physical_question(self):
        for rule in ("EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE", "EG-AVAILABILITY-INVISIBLE",
                     "EG-SPECS-MISSING", "MR-IDENTIFIERS-MISSING", "EG-CTA-NOT-IN-HTML"):
            if rule not in self.findings:
                continue
            for url in self.urls_of(rule):
                self.assertNotIn(url, ("/products/kestrel-studio.html",
                                       "/products/cloud-team.html",
                                       "/services/boiler-servicing.html"), rule)


class TestListingSubtypes(SemanticFixtureCase):

    EXPECTED = {
        "/collections/boots.html": "ecommerce_listing",
        "/docs/": "documentation_section",
        "/news/": "article_index",
    }

    def test_each_listing_is_read_as_a_listing_of_what_it_lists(self):
        for path, subtype in self.EXPECTED.items():
            record = S.listing_record(self.page(path), self.bundle, self.context)
            self.assertEqual(record["subtype"], subtype, path)

    def test_only_the_catalogue_listing_is_asked_for_sort_and_filter_controls(self):
        for rule in ("EG-SORT-CONTROLS-ABSENT", "EG-FILTER-CONTROLS-ABSENT"):
            for url in (self.urls_of(rule) if rule in self.findings else []):
                self.assertEqual(url, "/collections/boots.html", rule)

    def test_a_department_page_is_not_read_as_a_listing_at_all(self):
        """`/departments/finance.html` is an organisation page. It was typed
        `category` by a URL-word hint, and asked why it had no price sort."""
        finance = self.page("/departments/finance.html")
        self.assertEqual(finance["page_type"], "other")
        self.assertNotIn("/departments/finance.html",
                         self.urls_of("EG-FILTER-CONTROLS-ABSENT")
                         if "EG-FILTER-CONTROLS-ABSENT" in self.findings else [])

    def test_the_coverage_block_counts_the_listing_kinds(self):
        self.assertEqual(self.report["coverage"]["listing_subtypes"],
                         {"ecommerce_listing": 1, "documentation_section": 1,
                          "article_index": 1})


class TestEntityRelationships(SemanticFixtureCase):

    def setUp(self):
        self.relationships = {r["name"]: r["relationship"]
                              for r in S.entity_relationships(self.bundle)}

    def test_the_localized_names_are_localizations_not_rival_brands(self):
        self.assertEqual(self.relationships.get("Kestrel Ltd"), "primary_entity")
        self.assertEqual(self.relationships.get("Kestrel España"), "language_variant")
        self.assertEqual(self.relationships.get("ケストレル"), "localization")

    def test_the_department_is_a_department(self):
        self.assertEqual(self.relationships.get("Department of Finance"), "department")

    def test_no_brand_conflict_is_reported_on_a_site_with_three_renderings_of_one_name(self):
        self.assertNotIn("EN-NAME-INCONSISTENT", self.findings)

    def test_only_the_profile_links_are_counted_as_undeclared_sameas(self):
        found = self.findings["EN-SAMEAS-UNDECLARED"]
        self.assertEqual(found["metrics"]["profiles"], 3)
        self.assertGreaterEqual(found["metrics"]["other_platform_links_not_counted"], 1)
        self.assertIn("did not verify that those accounts belong", found["evidence"])
        hosts = {u.split("/")[2] for u in found["affected_urls"]}
        self.assertNotIn("en.wikipedia.org", hosts)
        self.assertNotIn("docs.python.org", hosts)

    def test_the_declared_anchors_carry_their_link_kind(self):
        kinds = {a["url"]: a["link_kind"] for a in self.bundle["declared_anchors"]}
        self.assertEqual(kinds["https://www.linkedin.com/company/kestrel-ltd"],
                         "official_profile")
        self.assertEqual(kinds["https://x.com/kestrelltd"], "official_profile")
        self.assertEqual(kinds["https://en.wikipedia.org/wiki/Kestrel"], "knowledge_reference")


class TestTransportOutcomes(SemanticFixtureCase):

    def test_the_refusal_the_throttle_and_the_timeout_are_not_verified(self):
        found = self.findings["CR-URLS-NOT-VERIFIED"]
        self.assertEqual(found["severity"], "info")
        self.assertEqual(sorted(self.urls_of("CR-URLS-NOT-VERIFIED")),
                         ["/api/status.html", "/members/report.html", "/slow/page.html"])
        for reason in ("HTTP 403 (refused or rate-limited)",
                       "HTTP 429 (refused or rate-limited)", "the request timed out"):
            self.assertIn(reason, found["metrics"]["reasons"])
        self.assertIn("could not be verified", found["title"])

    def test_nothing_on_this_site_is_reported_as_a_broken_advertised_url(self):
        self.assertNotIn("CR-HTTP-ERRORS", self.findings)

    def test_the_timeout_is_recorded_as_a_fetch_error_not_as_a_page(self):
        errors = {e["url"][len(self.base):] for e in self.bundle["fetch_errors"]}
        self.assertEqual(errors, {"/slow/page.html"})
        self.assertNotIn("/slow/page.html", self.pages)

    def test_the_redirect_chain_is_read_as_one_resource_at_a_new_address(self):
        chain = self.findings["CR-REDIRECT-CHAINS"]
        self.assertEqual(self.urls_of("CR-REDIRECT-CHAINS"), ["/old/boot"])
        self.assertEqual(chain["metrics"]["redirect_kinds"], {"canonical_representation": 1})
        self.assertEqual(len(self.page("/old/boot")["redirects"]), 2)
        self.assertNotIn("EG-DEEPLINK-REDIRECTED-HOME", self.findings)


class TestCanonicalAndIndexing(SemanticFixtureCase):

    def test_the_syndicated_article_is_a_review_item_not_a_collapse(self):
        self.assertNotIn("CR-CANONICAL-WRONG-TARGET", self.findings)
        found = self.findings["CR-CANONICAL-CROSS-HOST"]
        self.assertEqual(found["severity"], "low")
        self.assertEqual(self.urls_of("CR-CANONICAL-CROSS-HOST"), ["/news/syndicated.html"])
        self.assertIn("may be intentional", found["evidence"])
        self.assertIn("(article)", found["evidence"])

    def test_the_public_noindex_is_reported_and_the_private_one_is_not(self):
        found = self.findings["CR-NOINDEX-ON-IMPORTANT-PAGES"]
        self.assertEqual(self.urls_of("CR-NOINDEX-ON-IMPORTANT-PAGES"),
                         ["/news/archive-2019.html"])
        self.assertEqual(found["metrics"]["utility_pages_excluded_from_finding"], 1)
        self.assertIn("Review whether this exclusion is intentional",
                      found["suggested_action"]["summary"])
        self.assertNotIn("commercially important", found["evidence"].lower())

    def test_the_private_page_is_classified_before_any_content_rule_sees_it(self):
        dashboard = self.page("/members/dashboard.html")
        self.assertEqual(dashboard["page_type"], "account")
        self.assertEqual(S.endpoint_kind(dashboard), "utility")
        self.assertFalse(self.cited_anywhere("/members/dashboard.html"))


class TestFreshnessFollowsPageType(SemanticFixtureCase):

    def test_the_undated_home_and_contact_pages_are_not_a_freshness_defect(self):
        self.assertEqual(S.freshness_expectation(self.page("/")), "not_applicable")
        self.assertEqual(S.freshness_expectation(self.page("/contact.html")), "not_applicable")
        self.assertNotIn("FC-NO-DATE-SIGNALS", self.findings)

    def test_a_visible_date_makes_a_machine_date_expected_of_that_page(self):
        changelog = self.page("/docs/changelog.html")
        self.assertTrue((changelog.get("dates") or {}).get("visible_updated"))
        self.assertEqual(S.freshness_expectation(changelog), "expected")

    def test_the_uniform_sitemap_lastmod_is_still_reported(self):
        self.assertIn("FC-SITEMAP-LASTMOD-UNIFORM", self.findings)

    def test_no_corroboration_anchor_is_called_broken(self):
        anchors = self.findings.get("FC-BROKEN-CORROBORATION-ANCHOR")
        if anchors is not None:
            self.assertIn("could not be verified", anchors["title"])


class TestHeadingsAndOptionalMetadata(SemanticFixtureCase):

    def test_two_h1s_and_no_h1_are_both_accepted(self):
        two = self.page("/news/kestrel-3-released.html")
        none = self.page("/docs/configuration.html")
        self.assertEqual(two["h1_count"], 2)
        self.assertEqual(none["h1_count"], 0)
        for record in (two, none):
            self.assertTrue(S.heading_assessment(record)["identifies_subject"], record["url"])
        self.assertNotIn("MR-HEADING-STRUCTURE", self.findings)

    def test_the_partial_organization_node_is_a_medium_finding_that_names_its_reasons(self):
        found = self.findings["EN-ORG-INCOMPLETE"]
        self.assertEqual(found["severity"], "medium")
        self.assertIn("address", found["metrics"]["missing_required"])
        self.assertIn("the site sells physical goods", found["evidence"])
        self.assertIn("optional for any site and not counted", found["evidence"])
        self.assertEqual(found["metrics"]["site_kind"], "mixed")

    def test_no_optional_metadata_absence_is_reported_high(self):
        optional = {"MR-OPEN-GRAPH-INCOMPLETE", "EG-REVIEWS-ABSENT", "EN-CATEGORY-UNDECLARED",
                    "MR-BREADCRUMB-MISSING", "MR-SITE-SCHEMA-MISSING", "EN-ORG-INCOMPLETE",
                    "EG-NO-SITE-SEARCH", "CR-CANONICAL-CROSS-HOST", "CR-URLS-NOT-VERIFIED",
                    "MR-HEADING-STRUCTURE"}
        for rule_id in optional & set(self.findings):
            self.assertNotIn(self.findings[rule_id]["severity"], ("high", "critical"), rule_id)


class TestSiteSearch(SemanticFixtureCase):

    def test_a_site_this_size_is_not_asked_for_a_search_box(self):
        verdict = S.is_site_search_expected(self.bundle)
        self.assertFalse(verdict)
        self.assertIn("no search box is owed", verdict["reason"])
        self.assertNotIn("EG-NO-SITE-SEARCH", self.findings)

    def test_search_action_is_not_recommended_where_no_search_exists(self):
        schema = self.findings.get("MR-SITE-SCHEMA-MISSING")
        if schema is not None:
            steps = " ".join(schema["suggested_action"]["steps"])
            self.assertNotIn("pointing at your site-search URL", steps)


class TestAnswerability(SemanticFixtureCase):

    def test_questions_follow_what_the_site_sells(self):
        answerability = self.report["answerability"]
        self.assertEqual(answerability["site_kind"], "mixed")
        kinds = {row["kind"] for row in answerability["questions"]}
        self.assertIn("product_price", kinds)
        self.assertIn("product_availability", kinds)

    def test_questions_that_do_not_apply_are_reported_not_scored(self):
        answerability = self.report["answerability"]
        not_asked = " ".join(answerability["not_asked"])
        self.assertIn("stock statement does not apply to a software item", not_asked)
        self.assertIn("does not apply to a subscription item", not_asked)
        self.assertTrue(any("not counted as gaps" in note for note in answerability["notes"]))
        # Only the questions actually asked are in the denominator.
        self.assertEqual(answerability["total_questions"], len(answerability["questions"]))

    def test_availability_is_asked_of_the_boot_and_of_nothing_else(self):
        rows = [r for r in self.report["answerability"]["questions"]
                if r["kind"] == "product_availability"]
        self.assertEqual(len(rows), 1)
        self.assertIn("trail-boot", str(rows[0]))


class TestRecommendations(SemanticFixtureCase):

    def setUp(self):
        self.opportunities = {o["id"]: o for o in self.report["proactive_recommendations"]}

    def test_every_recommendation_states_why_it_applied_to_this_site(self):
        self.assertTrue(self.opportunities)
        for oid, opportunity in self.opportunities.items():
            applicability = opportunity["applicability"]
            self.assertTrue(applicability["applies_because"].strip(), oid)
            self.assertTrue(applicability["conditions"], oid)
            self.assertEqual(applicability["site_kind"], "mixed", oid)

    def test_the_physical_goods_recommendation_quotes_a_physical_pages_attributes(self):
        explicit = self.opportunities.get("OPP-EXPLICIT-ABSENCE")
        if explicit is not None:
            because = explicit["applicability"]["applies_because"]
            self.assertIn("physical goods", because)
            self.assertNotIn("applicationCategory", because)
            self.assertNotIn("operatingSystem", because)

    def test_the_agent_index_example_is_shaped_like_this_site(self):
        surface = self.opportunities.get("OPP-AI-DISCOVERY-SURFACE")
        self.assertIsNotNone(surface)
        self.assertIn("[", surface["example"])

    def test_a_recommendation_is_never_offered_against_its_own_site_kinds(self):
        for oid, opportunity in self.opportunities.items():
            kinds = recommend.LIBRARY[oid]["site_kinds"]
            if kinds == "any":
                continue
            allowed = set(kinds) | {"mixed"}
            self.assertIn("mixed", allowed, oid)
            verdict = recommend.applicability_of(oid, self.bundle)
            self.assertTrue(verdict["site_kind_allowed"], oid)


class TestEvidenceAccounting(SemanticFixtureCase):

    def test_the_reuse_ratio_describes_shared_evidence(self):
        reuse = self.report["diagnostics"]["evidence_reuse"]
        ratio = reuse["shared_evidence_reuse_ratio"]
        self.assertGreater(ratio, 0.5)
        self.assertLessEqual(ratio, 1.0)
        self.assertEqual(self.report["diagnostics"]["evidence_reuse_ratio"], ratio)
        self.assertEqual(reuse["specialists_served_from_the_bundle"], 6)
        self.assertEqual(reuse["specialist_network_requests"], 0)
        self.assertIn("shared_evidence_reuse_ratio = 1 - R", reuse["definition"])

    def test_no_finding_carries_a_repeated_evidence_entry_or_url(self):
        for finding in self.report["findings"]:
            keys = [(i.get("observation"), i.get("url"), i.get("locator"))
                    for i in finding["evidence_items"]]
            self.assertEqual(len(keys), len(set(keys)), finding["rule_id"])
            self.assertEqual(len(finding["affected_urls"]), len(set(finding["affected_urls"])),
                             finding["rule_id"])

    def test_every_finding_still_carries_observable_evidence(self):
        for finding in self.report["findings"]:
            self.assertTrue(finding["evidence_items"], finding["rule_id"])
            self.assertTrue(finding["evidence"].strip(), finding["rule_id"])


class TestNoUnsupportedClaims(SemanticFixtureCase):
    """The rendered report, not the source: whatever this fixture produced,
    it must not assert how an assistant behaves."""

    FORBIDDEN = ("assistants weight", "fetchers read", "guarantees retrieval",
                 "makes the assistant cite", "rank you higher", "causes hallucinations",
                 "assistants will ignore", "machines treat", "commercially important",
                 "tells crawlers to drop", "product detail collapsed", "dead profile",
                 "invisible to assistants", "unusable as a source")

    def test_neither_the_json_nor_the_markdown_carries_a_behavioural_claim(self):
        import json
        rendered = (json.dumps(self.report) + report_mod.render_markdown(self.report)).lower()
        for phrase in self.FORBIDDEN:
            self.assertNotIn(phrase, rendered)


class TestDeterminism(SemanticFixtureCase):

    def test_the_specialists_never_edit_the_bundle_they_were_handed(self):
        import copy
        import json
        before = json.dumps(copy.deepcopy(self.bundle), sort_keys=True, default=str)
        for entry in paths.specialist_skills():
            helpers.specialist(entry["id"]).analyze(self.bundle)
        self.assertEqual(json.dumps(self.bundle, sort_keys=True, default=str), before)

    def test_two_reports_from_one_bundle_are_identical(self):
        import json
        findings = []
        for entry in paths.specialist_skills():
            findings.extend(helpers.specialist(entry["id"]).analyze(self.bundle))
        config = AuditConfig(site=self.base)
        first = report_mod.build_report(self.bundle, list(findings), config)
        second = report_mod.build_report(self.bundle, list(findings), config)
        for report in (first, second):
            report.pop("audited_at", None)
            report.get("evidence_manifest", {}).pop("collected_at", None)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
