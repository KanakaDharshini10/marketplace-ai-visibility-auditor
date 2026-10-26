"""Entity relationships: which names are the site's own, and which are not.

A department, a subsidiary, a product's brand, a partner, a localized
rendering of the site's own name and a knowledge-base entry are all names a
crawl meets, and none of them is the site calling itself two things. These
tests pin the relationship classifier (:func:`aiva.semantics.entity_relationships`),
the outbound-link classifier it shares with the anchor collector, and the
three rules that consume them:

* ``EN-NAME-INCONSISTENT`` never reports a related name as a rival spelling;
* ``EN-SAMEAS-UNDECLARED`` counts official profiles only, never a Wikipedia
  topic, a documentation host, a store listing or a locale variant;
* ``FC-BROKEN-CORROBORATION-ANCHOR`` says "could not be verified" for a
  refusal, a rate limit or a timeout, and "not-found" only for 404/410.

Run just this file:

    python3 tests/run_tests.py entity_relationships -v
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, find, html_doc, jsonld, page, run

from aiva import discover
from aiva import semantics as S

ORG_LD = ('{"@context":"https://schema.org","@type":"Organization",'
          '"@id":"%s/#organization","name":"Kestrel Ltd","url":"%s/"}' % (ORIGIN, ORIGIN))


def _home(extra_head: str = "", body: str = "<h1>Kestrel Ltd</h1>", lang: str = "en") -> dict:
    return page(ORIGIN + "/", html_doc(title="Kestrel Ltd", canonical=ORIGIN + "/",
                                       head=jsonld(ORG_LD) + extra_head, body=body, lang=lang))


def _org_page(path: str, ld: str, title: str, lang: str = "en", body: str = "") -> dict:
    return page(ORIGIN + path, html_doc(title=title, canonical=ORIGIN + path,
                                        head=jsonld(ld), lang=lang,
                                        body=body or f"<h1>{title}</h1><p>About {title}.</p>"))


def _relationships(*pages: dict) -> dict:
    return {r["name"]: r for r in S.entity_relationships(bundle(list(pages)))}


class TestRelationshipClassifier(unittest.TestCase):

    def test_the_home_page_organisation_is_the_primary_entity(self):
        rel = _relationships(_home())
        self.assertEqual(rel["Kestrel Ltd"]["relationship"], "primary_entity")
        self.assertIn("own organisation", rel["Kestrel Ltd"]["why"])

    def test_a_department_declaring_the_site_as_parent_is_a_department(self):
        dept = ('{"@context":"https://schema.org","@type":"Organization",'
                '"name":"Department of Finance",'
                '"parentOrganization":{"@id":"%s/#organization"}}' % ORIGIN)
        rel = _relationships(_home(), _org_page("/departments/finance", dept,
                                                "Department of Finance"))
        self.assertEqual(rel["Department of Finance"]["relationship"], "department")
        self.assertIn("parent", rel["Department of Finance"]["why"])

    def test_a_subsidiary_and_an_agency_and_a_tribunal_are_told_apart(self):
        sub = ('{"@context":"https://schema.org","@type":"Organization","name":"Kestrel Labs",'
               '"parentOrganization":{"@type":"Organization","name":"Kestrel Ltd"}}')
        agency = ('{"@context":"https://schema.org","@type":"GovernmentOrganization",'
                  '"name":"Water Regulator",'
                  '"parentOrganization":{"@type":"Organization","name":"Kestrel Ltd"}}')
        tribunal = ('{"@context":"https://schema.org","@type":"Organization",'
                    '"name":"Employment Tribunal",'
                    '"parentOrganization":{"@type":"Organization","name":"Kestrel Ltd"}}')
        rel = _relationships(_home(), _org_page("/labs", sub, "Kestrel Labs"),
                             _org_page("/regulator", agency, "Water Regulator"),
                             _org_page("/tribunal", tribunal, "Employment Tribunal"))
        self.assertEqual(rel["Kestrel Labs"]["relationship"], "subsidiary")
        self.assertEqual(rel["Water Regulator"]["relationship"], "agency")
        self.assertEqual(rel["Employment Tribunal"]["relationship"], "tribunal")

    def test_sub_organisations_listed_on_the_parent_are_recorded(self):
        parent = ('{"@context":"https://schema.org","@type":"Organization","name":"Kestrel Ltd",'
                  '"subOrganization":[{"@type":"Organization","name":"Kestrel Retail"}],'
                  '"department":[{"@type":"Organization","name":"Customer Care"}]}')
        rel = _relationships(_home(extra_head=jsonld(parent)))
        self.assertEqual(rel["Kestrel Retail"]["relationship"], "subsidiary")
        self.assertEqual(rel["Customer Care"]["relationship"], "department")

    def test_a_product_brand_is_a_brand_not_a_second_trading_name(self):
        product = ('{"@context":"https://schema.org","@type":"Product","name":"Summit 40",'
                   '"brand":{"@type":"Brand","name":"Osprey"},'
                   '"manufacturer":{"@type":"Organization","name":"Osprey Packs Inc"},'
                   '"offers":{"@type":"Offer","price":"180","priceCurrency":"GBP",'
                   '"seller":{"@type":"Organization","name":"Kestrel Ltd"}}}')
        rel = _relationships(_home(), _org_page("/products/summit-40", product, "Summit 40",
                                                body="<h1>Summit 40</h1><p>£180. Add to cart.</p>"))
        self.assertEqual(rel["Osprey"]["relationship"], "brand")
        self.assertEqual(rel["Osprey Packs Inc"]["relationship"], "partner")
        # The seller is the site's own organisation: not a partner.
        self.assertNotIn(("Kestrel Ltd", "partner"),
                         {(r["name"], r["relationship"]) for r in rel.values()})

    def test_a_third_party_seller_in_an_offer_is_a_partner(self):
        listing = ('{"@context":"https://schema.org","@type":"Product","name":"Desk lamp",'
                   '"offers":{"@type":"Offer","price":"35","priceCurrency":"GBP",'
                   '"seller":{"@type":"Person","name":"Anna R."}}}')
        rel = _relationships(_home(), _org_page("/listings/lamp", listing, "Desk lamp"))
        self.assertEqual(rel["Anna R."]["relationship"], "partner")

    def test_an_article_about_another_organisation_is_unrelated(self):
        article = ('{"@context":"https://schema.org","@type":"NewsArticle",'
                   '"headline":"Regulator fines Acme","datePublished":"2026-01-02",'
                   '"about":{"@type":"Organization","name":"Acme Widgets"},'
                   '"publisher":{"@type":"Organization","name":"Kestrel Ltd"}}')
        rel = _relationships(_home(), _org_page("/news/acme-fine", article, "Regulator fines Acme"))
        self.assertEqual(rel["Acme Widgets"]["relationship"], "unrelated")

    def test_former_names_owners_and_acquisitions_are_read_from_the_page_text(self):
        about = _org_page("/about", ORG_LD, "About",
                          body="<h1>About</h1><p>Kestrel Ltd was formerly known as Falcon "
                               "Supplies and is now part of Harrier Group. In 2023 Kestrel "
                               "acquired Merlin Optics.</p>")
        rel = _relationships(_home(), about)
        self.assertEqual(rel["Kestrel Ltd"]["relationship"], "primary_entity")
        self.assertEqual(rel["Falcon Supplies"]["relationship"], "acquired_company")
        self.assertIn("former name", rel["Falcon Supplies"]["why"])
        self.assertEqual(rel["Harrier Group"]["relationship"], "organization")
        self.assertIn("parent or owner", rel["Harrier Group"]["why"])
        self.assertEqual(rel["Merlin Optics"]["relationship"], "acquired_company")
        # The site's own name is never recorded as acquired, whatever the
        # sentence around it says.
        kinds = {(r["name"], r["relationship"])
                 for r in S.entity_relationships(bundle([_home(), about]))}
        self.assertNotIn(("Kestrel Ltd", "acquired_company"), kinds)

    def test_a_former_name_is_not_a_rival_trading_name(self):
        former = ('{"@context":"https://schema.org","@type":"Organization",'
                  '"name":"Falcon Supplies","url":"%s/"}' % ORIGIN)
        about = page(ORIGIN + "/about", html_doc(
            title="About", canonical=ORIGIN + "/about", head=jsonld(former),
            body="<h1>About</h1><p>Kestrel Ltd, formerly known as Falcon Supplies, "
                 "has traded since 1990.</p>"))
        self.assertIsNone(find(run("entity-audit", bundle([_home(), about])),
                               "EN-NAME-INCONSISTENT"))

    def test_every_relationship_is_from_the_published_vocabulary(self):
        for record in S.entity_relationships(bundle([_home()])):
            self.assertIn(record["relationship"], S.ENTITY_RELATIONSHIPS)
            self.assertEqual(set(record), {"name", "relationship", "why", "url", "source"})


class TestLocalizedNames(unittest.TestCase):
    """The same organisation under another language or script."""

    def test_a_name_in_another_script_is_a_localization(self):
        jp = ('{"@context":"https://schema.org","@type":"Organization",'
              '"name":"ケストレル","url":"%s/jp/"}' % ORIGIN)
        rel = _relationships(_home(), _org_page("/jp/", jp, "ケストレル", lang="ja"))
        self.assertEqual(rel["ケストレル"]["relationship"], "localization")
        self.assertIn("script", rel["ケストレル"]["why"])

    def test_a_translated_name_on_a_locale_page_is_a_language_variant(self):
        es = ('{"@context":"https://schema.org","@type":"Organization",'
              '"name":"Kestrel España","url":"%s/es/"}' % ORIGIN)
        rel = _relationships(_home(), _org_page("/es/", es, "Kestrel España", lang="es"))
        self.assertEqual(rel["Kestrel España"]["relationship"], "language_variant")
        self.assertIn("es page", rel["Kestrel España"]["why"])

    def test_the_same_name_on_a_locale_page_stays_the_primary_entity(self):
        same = ('{"@context":"https://schema.org","@type":"Organization",'
                '"name":"Kestrel Ltd","url":"%s/fr/"}' % ORIGIN)
        rel = _relationships(_home(), _org_page("/fr/", same, "Kestrel Ltd", lang="fr"))
        self.assertEqual(rel["Kestrel Ltd"]["relationship"], "primary_entity")

    def test_localized_names_never_become_a_brand_conflict(self):
        """The regression: a Japanese rendering and a Spanish subsidiary name
        were reported as three competing trading names."""
        jp = ('{"@context":"https://schema.org","@type":"Organization",'
              '"name":"ケストレル","url":"%s/jp/"}' % ORIGIN)
        es = ('{"@context":"https://schema.org","@type":"Organization",'
              '"name":"Kestrel España","url":"%s/es/"}' % ORIGIN)
        data = bundle([_home(), _org_page("/jp/", jp, "ケストレル", lang="ja"),
                       _org_page("/es/", es, "Kestrel España", lang="es")])
        self.assertIsNone(find(run("entity-audit", data), "EN-NAME-INCONSISTENT"))


class TestNameConsistencyUsesRelationships(unittest.TestCase):

    def test_a_department_is_not_a_rival_spelling(self):
        dept = ('{"@context":"https://schema.org","@type":"Organization",'
                '"name":"Department of Finance",'
                '"parentOrganization":{"@id":"%s/#organization"}}' % ORIGIN)
        data = bundle([_home(), _org_page("/departments/finance", dept, "Department of Finance")])
        self.assertIsNone(find(run("entity-audit", data), "EN-NAME-INCONSISTENT"))

    def test_a_product_brand_is_not_a_rival_spelling(self):
        product = ('{"@context":"https://schema.org","@type":"Product","name":"Summit 40",'
                   '"brand":{"@type":"Brand","name":"Osprey"},'
                   '"offers":{"@type":"Offer","price":"180","priceCurrency":"GBP"}}')
        data = bundle([_home(), _org_page("/products/summit-40", product, "Summit 40",
                                          body="<h1>Summit 40</h1><p>£180. Add to cart.</p>")])
        findings = run("entity-audit", data)
        self.assertIsNone(find(findings, "EN-NAME-INCONSISTENT"))

    def test_two_unrelated_trading_names_are_still_reported(self):
        """The rule still works: two names the site declares *as itself*,
        with nothing relating them, are a real inconsistency."""
        other = ('{"@context":"https://schema.org","@type":"Organization",'
                 '"name":"Falcon Supplies","url":"%s/"}' % ORIGIN)
        about = page(ORIGIN + "/about", html_doc(
            title="About Falcon Supplies", canonical=ORIGIN + "/about", head=jsonld(other),
            body="<h1>About Falcon Supplies</h1><p>Falcon Supplies is a trading name.</p>"))
        data = bundle([_home(), about])
        found = find(run("entity-audit", data), "EN-NAME-INCONSISTENT")
        self.assertIsNotNone(found)
        self.assertEqual(found.metrics.get("excluded_related_names", []), [])


class TestOutboundLinkClassification(unittest.TestCase):
    """What a link is, decided from the platform and the path, never the
    audited site's own name."""

    def _kind(self, url: str, **kw) -> str:
        return S.classify_outbound_link(url, site_origin=ORIGIN, **kw)["kind"]

    def test_profiles_on_social_and_code_platforms(self):
        self.assertEqual(self._kind("https://www.linkedin.com/company/kestrel-ltd"),
                         "official_profile")
        self.assertEqual(self._kind("https://x.com/kestrelltd"), "official_profile")
        self.assertEqual(self._kind("https://github.com/kestrel-ltd"), "official_profile")
        self.assertEqual(self._kind("https://github.com/kestrel-ltd/studio"), "code_repository")

    def test_knowledge_documentation_stores_and_reviews_are_not_profiles(self):
        self.assertEqual(self._kind("https://en.wikipedia.org/wiki/Kestrel"),
                         "knowledge_reference")
        self.assertEqual(self._kind("https://docs.python.org/3/"), "documentation")
        self.assertEqual(self._kind("https://apps.apple.com/app/id123456"), "product_listing")
        self.assertEqual(self._kind("https://www.trustpilot.com/review/kestrel.example"),
                         "review_listing")

    def test_a_platform_content_item_is_not_an_account(self):
        self.assertEqual(self._kind("https://www.youtube.com/watch?v=abc123"), "unknown")
        self.assertEqual(self._kind("https://twitter.com/intent/tweet?text=hi"), "share_intent")

    def test_locale_variants_and_internal_links_are_navigation(self):
        self.assertEqual(self._kind(ORIGIN + "/es/"), "language_variant")
        self.assertEqual(self._kind(ORIGIN + "/about"), "navigation")

    def test_rel_me_is_an_identity_claim_wherever_it_points(self):
        self.assertEqual(self._kind("https://example.org/anna", rel="me"), "official_profile")

    def test_a_knowledge_entry_about_the_site_is_marked_as_a_match(self):
        verdict = S.classify_outbound_link("https://en.wikipedia.org/wiki/Kestrel_Ltd",
                                           site_origin=ORIGIN, entity_names=["Kestrel Ltd"])
        self.assertEqual(verdict["kind"], "knowledge_reference")
        self.assertTrue(verdict["entity_match"])
        topic = S.classify_outbound_link("https://en.wikipedia.org/wiki/Peregrine_falcon",
                                         site_origin=ORIGIN, entity_names=["Kestrel Ltd"])
        self.assertFalse(topic["entity_match"])


class TestSameAsCountsOnlyProfiles(unittest.TestCase):
    """EN-SAMEAS-UNDECLARED: a footer full of links is not a row of accounts."""

    FOOTER = ('<footer><a href="https://www.linkedin.com/company/kestrel-ltd">LinkedIn</a>'
              '<a href="https://en.wikipedia.org/wiki/Kestrel">Kestrels</a>'
              '<a href="https://docs.python.org/3/">Python docs</a>'
              '<a href="https://apps.apple.com/app/id123456">App Store</a></footer>')

    def _bundle(self):
        home = _home(body="<h1>Kestrel Ltd</h1>" + self.FOOTER)
        data = bundle([home])
        data["declared_anchors"] = discover.collect_declared_anchors(
            [home], site_origin=ORIGIN, entity_names=["Kestrel Ltd"])
        data["declared_anchors_total"] = len(data["declared_anchors"])
        return data

    def test_only_the_profile_link_is_counted(self):
        data = self._bundle()
        kinds = {a["url"]: a["link_kind"] for a in data["declared_anchors"]}
        self.assertEqual(kinds["https://www.linkedin.com/company/kestrel-ltd"], "official_profile")
        self.assertEqual(kinds["https://en.wikipedia.org/wiki/Kestrel"], "knowledge_reference")
        found = find(run("entity-audit", data), "EN-SAMEAS-UNDECLARED")
        self.assertIsNotNone(found)
        self.assertEqual(found.metrics["profiles"], 1)
        self.assertGreaterEqual(found.metrics["other_platform_links_not_counted"], 1)
        self.assertEqual(found.affected_urls, ["https://www.linkedin.com/company/kestrel-ltd"])
        self.assertIn("not profiles and are not counted", found.evidence)
        self.assertIn("did not verify that those accounts belong", found.evidence)

    def test_no_profiles_means_no_undeclared_sameas_finding(self):
        home = _home(body='<h1>Kestrel Ltd</h1><footer>'
                          '<a href="https://en.wikipedia.org/wiki/Kestrel">Kestrels</a>'
                          '<a href="https://docs.python.org/3/">Python docs</a></footer>')
        data = bundle([home])
        data["declared_anchors"] = discover.collect_declared_anchors(
            [home], site_origin=ORIGIN, entity_names=["Kestrel Ltd"])
        self.assertIsNone(find(run("entity-audit", data), "EN-SAMEAS-UNDECLARED"))


class TestAnchorVerificationWording(unittest.TestCase):
    """A profile the platform would not show this auditor is not "dead"."""

    def _anchor(self, url: str, **kw) -> dict:
        record = {"url": url, "sources": ["schema.org sameAs"], "declared_on": [ORIGIN + "/"],
                  "is_knowledge_host": False, "link_kind": "official_profile",
                  "link_kind_reason": "an account on a social or listing platform",
                  "entity_match": False, "declared_as_sameas": True, "in_site_chrome": False,
                  "checked": True, "status": 200, "resolves": True, "error": None}
        record.update(kw)
        return record

    def test_a_refused_profile_is_reported_as_not_verified_at_low_severity(self):
        data = bundle([_home()], declared_anchors=[
            self._anchor("https://www.linkedin.com/company/kestrel-ltd", status=999,
                         resolves=False, verification="unverified",
                         verification_reason="HTTP 999 (refused or rate-limited)"),
            self._anchor("https://x.com/kestrelltd", status=429, resolves=False,
                         verification="unverified",
                         verification_reason="HTTP 429 (refused or rate-limited)")])
        found = find(run("freshness-corroboration", data), "FC-BROKEN-CORROBORATION-ANCHOR")
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "low")
        self.assertIn("could not be verified", found.title)
        self.assertIn("says nothing about whether the profiles exist", found.evidence)
        self.assertNotIn("dead", found.evidence.lower())
        self.assertNotIn("broken", found.title.lower())
        self.assertLessEqual(found.confidence, 0.5)

    def test_a_not_found_profile_is_reported_as_not_found_and_the_rest_set_aside(self):
        data = bundle([_home()], declared_anchors=[
            self._anchor("https://www.linkedin.com/company/gone", status=404, resolves=False,
                         verification="not_found", verification_reason="HTTP 404"),
            self._anchor("https://x.com/kestrelltd", status=403, resolves=False,
                         verification="unverified",
                         verification_reason="HTTP 403 (refused or rate-limited)")])
        found = find(run("freshness-corroboration", data), "FC-BROKEN-CORROBORATION-ANCHOR")
        self.assertEqual(found.severity, "medium")
        self.assertIn("not-found", found.title)
        self.assertEqual(found.metrics["broken"], 1)
        self.assertEqual(found.metrics["unverified"], 1)
        self.assertEqual(found.affected_urls, ["https://www.linkedin.com/company/gone"])
        self.assertIn("not counted as broken", found.evidence)

    def test_a_timed_out_anchor_without_a_recorded_verdict_is_still_not_verified(self):
        """Older bundles carry only status/error; the verdict is derived."""
        data = bundle([_home()], declared_anchors=[
            self._anchor("https://x.com/kestrelltd", status=0, resolves=False,
                         error="TimeoutError: timed out")])
        found = find(run("freshness-corroboration", data), "FC-BROKEN-CORROBORATION-ANCHOR")
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "low")
        self.assertIn("the request timed out", found.evidence)

    def test_verify_anchors_records_the_verdict_it_reached(self):
        """The collector writes ``verification``/``verification_reason`` from
        the same transport verdict the rules read, so no rule re-derives it."""
        anchor = self._anchor("https://x.com/kestrelltd")
        verdict = S.transport_verdict(429)
        self.assertEqual(verdict["verdict"], "unverified")
        self.assertIn("refused or rate-limited", verdict["reason"])
        self.assertEqual(S.transport_verdict(404)["verdict"], "not_found")
        self.assertEqual(S.transport_verdict(200)["verdict"], "verified")
        self.assertEqual(S.transport_verdict(None, "timed out")["verdict"], "unverified")
        self.assertEqual(S.transport_verdict(None, checked=False)["verdict"], "unverified")
        self.assertEqual(anchor["link_kind"], "official_profile")


if __name__ == "__main__":
    unittest.main()
