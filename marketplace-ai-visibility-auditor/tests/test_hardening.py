"""Regressions for the 1.8.0 correctness pass.

Every test here fails against 1.7.0. They fall into three groups:

* **Refusals are not defects.** A 403 from a bot wall, a proxy or a WAF is an
  observation about the path between this auditor and the origin. 1.7.0 read
  one as a canonicalisation defect and printed a `high` finding against a site
  that behaves correctly, and printed a headline claiming the site was
  "reachable" over a crawl that fetched nothing.
* **The new rules fire on the pattern and stay silent otherwise.** Assertions
  are deliberately weighted towards the negative cases, because a new rule's
  risk on an unseen site is a false positive, not a miss.
* **A broken generator must not vanish.** `build_opportunities` swallows
  exceptions so one bad generator cannot kill a report - which also meant a
  recommendation with a NameError silently produced nothing at all.
"""

from __future__ import annotations

import unittest

from helpers import (ORIGIN, bundle, html_doc, jsonld, page, rule_ids, run,
                     find, specialist)

from aiva import recommend
from aiva.config import AuditConfig
from aiva.discover import assess_access
from aiva.report import _coverage_state, _headline, _no_content_reason


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def http_probe(status: int, *, upgrades: bool = False, error=None) -> dict:
    return {"http": {"url": "http://shop.example/", "status": status,
                     "final_url": ("https://shop.example/" if upgrades
                                   else "http://shop.example/"),
                     "redirects": [], "upgrades_to_https": upgrades,
                     "error": error}}


class FakeResponse:
    """Just enough of aiva.httpclient.Response for assess_access."""

    def __init__(self, status, body="", headers=None, error=None):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.error = error


class FakeStore:
    def __init__(self, responses, config=None):
        self.responses = responses
        self.config = config or AuditConfig(site=ORIGIN)


# ---------------------------------------------------------------------------
# 1. a refusal is not a canonicalisation defect
# ---------------------------------------------------------------------------

class TestHttpsUpgradeIgnoresRefusals(unittest.TestCase):
    """The finding that started this pass.

    Observed on a real run: `GET http://example.com/` returned 403 from a
    proxy, and the report said "The http:// origin does not redirect to
    https:// ... with status 403" at `high` - about a site that redirects.
    """

    def _run(self, probes, **kw):
        data = bundle([page(ORIGIN + "/", html_doc())], host_probes=probes, **kw)
        return rule_ids(run("crawl-render-audit", data))

    def test_403_is_not_evidence_about_canonicalisation(self):
        self.assertNotIn("CR-NO-HTTPS-UPGRADE", self._run(http_probe(403)))

    def test_429_and_503_are_not_evidence_either(self):
        for status in (401, 407, 429, 451, 503, 502):
            with self.subTest(status=status):
                self.assertNotIn("CR-NO-HTTPS-UPGRADE", self._run(http_probe(status)))

    def test_transport_failure_on_robots_disqualifies_the_probe(self):
        """A run that never reached the origin cannot testify about it.

        1.7.0 already reported the robots failure honestly, as `info`, while
        this rule read the same failure as a defect of the site - two verdicts
        from one event.
        """
        ids = self._run(http_probe(200),
                        robots_status=0,
                        robots_error="URLError: <urlopen error Tunnel connection failed>")
        self.assertNotIn("CR-NO-HTTPS-UPGRADE", ids)

    def test_a_genuine_missing_upgrade_still_fires(self):
        ids = self._run(http_probe(200, upgrades=False))
        self.assertIn("CR-NO-HTTPS-UPGRADE", ids)

    def test_a_working_upgrade_stays_silent(self):
        self.assertNotIn("CR-NO-HTTPS-UPGRADE", self._run(http_probe(301, upgrades=True)))


# ---------------------------------------------------------------------------
# 2. the headline may not describe content nobody read
# ---------------------------------------------------------------------------

class TestHeadlineHonesty(unittest.TestCase):

    def test_transport_only_run_says_so(self):
        data = bundle([])
        headline = _headline({"band": "weak"}, {"critical": 0, "high": 1,
                                                "total_findings": 1}, data)
        self.assertIn("No page", headline)
        self.assertNotIn("is reachable", headline)
        self.assertEqual(_coverage_state(data), "transport_only")

    def test_a_read_site_keeps_the_ordinary_headline(self):
        data = bundle([page(ORIGIN + "/", html_doc())])
        headline = _headline({"band": "weak"}, {"critical": 0, "high": 1,
                                                "total_findings": 1}, data)
        self.assertIn("high-severity", headline)
        self.assertEqual(_coverage_state(data), "content")

    def test_the_reason_names_the_barrier(self):
        refused = bundle([])
        refused["pages"] = [{"url": ORIGIN + "/", "status": 403, "fetch_failed": True,
                             "page_type": "error"}]
        self.assertIn("refused", _no_content_reason(refused))

    def test_robots_unreachable_is_named_before_anything_else(self):
        data = bundle([], robots_status=503)
        self.assertIn("robots.txt", _no_content_reason(data))


# ---------------------------------------------------------------------------
# 3. bot walls
# ---------------------------------------------------------------------------

class TestBotWallDetection(unittest.TestCase):

    def test_clean_run_reports_no_wall(self):
        store = FakeStore({ORIGIN + "/": FakeResponse(200, "<html></html>")})
        self.assertFalse(assess_access(store, ORIGIN + "/")["wall_suspected"])

    def test_refused_home_page_is_a_wall(self):
        store = FakeStore({
            ORIGIN + "/": FakeResponse(403, "Just a moment..."),
            ORIGIN + "/about": FakeResponse(200, "<html></html>"),
        })
        access = assess_access(store, ORIGIN + "/")
        self.assertTrue(access["wall_suspected"])
        self.assertTrue(access["home_refused"])
        self.assertIn("just a moment...", access["challenge_vendors_matched"])

    def test_majority_refusals_are_a_wall_without_a_vendor_fingerprint(self):
        store = FakeStore({
            ORIGIN + "/": FakeResponse(200, "<html></html>"),
            ORIGIN + "/a": FakeResponse(429),
            ORIGIN + "/b": FakeResponse(429),
            ORIGIN + "/c": FakeResponse(403),
        })
        access = assess_access(store, ORIGIN + "/")
        self.assertTrue(access["wall_suspected"])
        self.assertEqual(access["challenge_vendors_matched"], [])

    def test_a_few_404s_are_not_a_wall(self):
        store = FakeStore({
            ORIGIN + "/": FakeResponse(200, "<html></html>"),
            ORIGIN + "/gone": FakeResponse(404),
            ORIGIN + "/old": FakeResponse(410),
        })
        self.assertFalse(assess_access(store, ORIGIN + "/")["wall_suspected"])

    def test_header_fingerprints_count(self):
        store = FakeStore({ORIGIN + "/": FakeResponse(403, "", {"CF-Ray": "abc"})})
        self.assertIn("cf-ray",
                      assess_access(store, ORIGIN + "/")["challenge_vendors_matched"])

    def test_rule_reports_critical_when_the_front_door_is_refused(self):
        data = bundle([])
        data["access"] = {"requests_observed": 4, "refused_count": 4,
                          "refused_share": 1.0, "refusal_statuses": {"403": 4},
                          "home_refused": True, "challenge_vendors_matched": ["cf-ray"],
                          "wall_suspected": True,
                          "samples": [{"url": ORIGIN + "/", "status": 403,
                                       "challenge_signals": ["cf-ray"]}],
                          "auditor_user_agent": "TestAuditor/1.0"}
        wall = find(run("crawl-render-audit", data), "CR-BOT-WALL")
        self.assertIsNotNone(wall)
        self.assertEqual(wall.severity, "critical")
        # The claim about assistant crawlers is a risk, not an observation.
        self.assertNotIn("assistant crawlers are blocked", wall.evidence)
        self.assertIn("GPTBot", " ".join(wall.suggested_action.steps))

    def test_rule_is_silent_without_a_wall(self):
        self.assertNotIn("CR-BOT-WALL",
                         rule_ids(run("crawl-render-audit",
                                      bundle([page(ORIGIN + "/", html_doc())]))))


class TestUserAgentOverride(unittest.TestCase):

    def test_honest_custom_agent_is_accepted(self):
        config = AuditConfig(site=ORIGIN,
                             user_agent="AcmeSiteAudit/2.1 (+ops@acme.example)")
        self.assertEqual(config.validate(), [])

    def test_browser_impersonation_is_refused(self):
        config = AuditConfig(site=ORIGIN,
                             user_agent="Mozilla/5.0 (Macintosh) AppleWebKit/537.36")
        self.assertTrue(any("impersonate" in e for e in config.validate()))

    def test_crawler_impersonation_is_refused(self):
        for agent in ("GPTBot/1.0", "ClaudeBot/1.0", "Googlebot/2.1", "PerplexityBot"):
            with self.subTest(agent=agent):
                config = AuditConfig(site=ORIGIN, user_agent=agent)
                self.assertTrue(any("impersonate" in e for e in config.validate()))

    def test_default_agent_still_validates(self):
        self.assertEqual(AuditConfig(site=ORIGIN).validate(), [])


# ---------------------------------------------------------------------------
# 4. new detection rules
# ---------------------------------------------------------------------------

OG_HEAD = ('<meta property="og:title" content="Velocity X9">'
           '<meta property="og:description" content="A road shoe.">'
           '<meta property="og:type" content="product">')


class TestOpenGraphCoverage(unittest.TestCase):

    def _pages(self, head):
        return [page(f"{ORIGIN}/products/p{i}", html_doc(title=f"P{i}", head=head,
                                                         open_graph=False))
                for i in range(4)]

    def test_missing_open_graph_is_reported(self):
        ids = rule_ids(run("machine-readability-audit", bundle(self._pages(""))))
        self.assertIn("MR-OPEN-GRAPH-INCOMPLETE", ids)

    def test_complete_open_graph_is_silent(self):
        ids = rule_ids(run("machine-readability-audit", bundle(self._pages(OG_HEAD))))
        self.assertNotIn("MR-OPEN-GRAPH-INCOMPLETE", ids)

    def test_a_thin_sample_is_not_a_pattern(self):
        data = bundle([page(f"{ORIGIN}/products/p1",
                            html_doc(open_graph=False))])
        self.assertNotIn("MR-OPEN-GRAPH-INCOMPLETE",
                         rule_ids(run("machine-readability-audit", data)))


DOC_LINKS = ("".join(
    f'<a href="/docs/{name}">{label}</a>'
    for name, label in (("x9-spec-sheet.pdf", "Velocity X9 specification sheet"),
                        ("price-list-2026.pdf", "2026 price list"),
                        ("catalogue.pdf", "Full catalogue"))))


class TestFactsInOpaqueDocuments(unittest.TestCase):

    def test_three_fact_bearing_documents_are_reported(self):
        pages = [page(ORIGIN + "/", html_doc(body=f"<h1>Shop</h1>{DOC_LINKS}")),
                 page(ORIGIN + "/about", html_doc())]
        found = find(run("machine-readability-audit", bundle(pages)),
                     "MR-FACTS-IN-OPAQUE-DOCS")
        self.assertIsNotNone(found)
        # Evidence must anchor to a page that was actually fetched: the
        # crawler never opens these documents and must not imply it did.
        for item in found.evidence_items:
            self.assertIn(item.url, {ORIGIN + "/", ORIGIN + "/about"})
        self.assertIn("not fetched", " ".join(i.observation for i in found.evidence_items))

    def test_two_documents_are_not_a_pattern(self):
        links = '<a href="/a-spec-sheet.pdf">Spec</a><a href="/b-catalogue.pdf">Catalogue</a>'
        pages = [page(ORIGIN + "/", html_doc(body=f"<h1>Shop</h1>{links}"))]
        self.assertNotIn("MR-FACTS-IN-OPAQUE-DOCS",
                         rule_ids(run("machine-readability-audit", bundle(pages))))

    def test_unrelated_pdfs_are_ignored(self):
        links = "".join(f'<a href="/pdf/annual-report-{y}.pdf">Annual report {y}</a>'
                        for y in (2023, 2024, 2025))
        pages = [page(ORIGIN + "/", html_doc(body=f"<h1>Investors</h1>{links}"))]
        self.assertNotIn("MR-FACTS-IN-OPAQUE-DOCS",
                         rule_ids(run("machine-readability-audit", bundle(pages))))


LOCATOR_BODY = ('<h1>Kestrel</h1><nav><a href="/stores">Find a store</a></nav>'
                '<p>Shops in Bristol, Leeds and Glasgow.</p>')

#: The locator page itself: the shape of visitable places - a telephone
#: number and opening hours per branch - in prose. A link labelled "Find a
#: store" establishes nothing on its own (a conference venue and a jobs page
#: are "locations" too); the fetched page carrying this is the evidence.
STORES_BODY = ('<main><h1>Our stores</h1>'
               '<section><h2>Bristol</h2><p>14 Park Row, Bristol. Tel 0117 496 0123. '
               'Opening hours: Monday-Saturday 9:00-17:30.</p></section>'
               '<section><h2>Leeds</h2><p>3 Briggate, Leeds. Tel 0113 496 0456. '
               'Monday-Saturday 9:00-18:00.</p></section>'
               '<section><h2>Glasgow</h2><p>9 Buchanan St, Glasgow. Tel 0141 496 0789. '
               'Monday-Saturday 9:30-17:30.</p></section></main>')

LOCAL_BUSINESS = jsonld('{"@context":"https://schema.org","@type":"Store",'
                        '"name":"Kestrel Bristol","address":{"@type":"PostalAddress",'
                        '"streetAddress":"14 Park Row","addressLocality":"Bristol",'
                        '"postalCode":"BS1 5LJ","addressCountry":"GB"}}')

ORG_WITH_ADDRESS = jsonld('{"@context":"https://schema.org","@type":"Organization",'
                          '"name":"Kestrel","address":{"@type":"PostalAddress",'
                          '"streetAddress":"1 Mill Lane","addressLocality":"Bristol"}}')


class TestLocationsUnstructured(unittest.TestCase):

    def _pages(self, head: str = ""):
        return [page(ORIGIN + "/", html_doc(body=LOCATOR_BODY, head=head)),
                page(ORIGIN + "/stores", html_doc(title="Our stores", body=STORES_BODY)),
                page(ORIGIN + "/about", html_doc())]

    def test_locator_without_any_place_entity_is_reported(self):
        pages = self._pages()
        found = find(run("entity-audit", bundle(pages)), "EN-LOCATIONS-UNSTRUCTURED")
        self.assertIsNotNone(found)
        # The consequence belongs in the interpretation, not in the evidence.
        self.assertNotIn("nothing to quote", found.evidence)
        self.assertIn("near me", found.reasoning)

    def test_a_declared_store_entity_settles_it(self):
        pages = self._pages(head=LOCAL_BUSINESS)
        self.assertNotIn("EN-LOCATIONS-UNSTRUCTURED",
                         rule_ids(run("entity-audit", bundle(pages))))

    def test_one_head_office_address_is_enough(self):
        """A single Organization with a PostalAddress is a readable location.

        The rule speaks to chains described only in prose, not to a company
        that publishes its address once and correctly.
        """
        pages = self._pages(head=ORG_WITH_ADDRESS)
        self.assertNotIn("EN-LOCATIONS-UNSTRUCTURED",
                         rule_ids(run("entity-audit", bundle(pages))))

    def test_a_site_with_no_physical_presence_is_untouched(self):
        pages = [page(ORIGIN + "/", html_doc(body="<h1>Kestrel</h1><p>Online only.</p>")),
                 page(ORIGIN + "/about", html_doc())]
        self.assertNotIn("EN-LOCATIONS-UNSTRUCTURED",
                         rule_ids(run("entity-audit", bundle(pages))))


# ---------------------------------------------------------------------------
# 5. proactive recommendations
# ---------------------------------------------------------------------------

class TestGeneratorsNeverSilentlyDie(unittest.TestCase):
    """`build_opportunities` catches every exception, by design.

    That is right - one bad generator must not cost a reader their report -
    but it also means a generator with a NameError produces silence rather
    than a failure, and a recommendation can be missing for a release without
    anyone noticing. This calls each generator directly, where nothing is
    caught.
    """

    def _bundles(self):
        product = page(
            ORIGIN + "/products/x9",
            html_doc(title="Velocity X9",
                     body='<h1>Velocity X9</h1><dl><dt>Weight</dt><dd>235 g</dd>'
                          '<dt>Drop</dt><dd>8 mm</dd></dl><p>£129.00</p>'
                          '<button>Add to cart</button>',
                     head=jsonld('{"@context":"https://schema.org","@type":"Product",'
                                 '"name":"Velocity X9","offers":{"@type":"Offer",'
                                 '"price":"129.00","priceCurrency":"GBP",'
                                 '"availability":"https://schema.org/InStock"}}')))
        return [bundle([]),
                bundle([page(ORIGIN + "/", html_doc())]),
                bundle([page(ORIGIN + "/", html_doc()), product]),
                bundle([page(ORIGIN + "/", html_doc()), product,
                        page(ORIGIN + "/products/x8", html_doc(title="Velocity X8")),
                        page(ORIGIN + "/collections/road", html_doc(title="Road"))])]

    def test_every_generator_returns_cleanly_on_every_shape(self):
        for data in self._bundles():
            for generator in recommend.GENERATORS:
                with self.subTest(generator=generator.__name__):
                    result = generator(data)
                    self.assertTrue(result is None or isinstance(result, dict))

    def test_the_new_recommendations_are_reachable(self):
        produced = set()
        for data in self._bundles():
            for generator in recommend.GENERATORS:
                result = generator(data)
                if result:
                    produced.add(result["id"])
        self.assertIn("OPP-EXPLICIT-ABSENCE", produced)
        self.assertIn("OPP-INTENT-COVERAGE", produced)


class TestExplicitAbsence(unittest.TestCase):

    def test_it_is_suppressed_when_attributes_are_already_a_defect(self):
        """Telling a site to publish negative attributes while it publishes
        none at all is advice about the wrong step."""
        self.assertIn("MR-ATTRIBUTES-THIN",
                      recommend.SUPERSEDED_BY["OPP-EXPLICIT-ABSENCE"])

    def test_it_is_skipped_for_non_commerce_sites(self):
        data = bundle([page(ORIGIN + "/", html_doc(body="<h1>News</h1><p>Reporting.</p>"))])
        self.assertIsNone(recommend._explicit_absence(data))


class TestIntentCoverage(unittest.TestCase):

    def test_it_names_what_is_missing(self):
        selling = ("<h1>Item</h1><p>£20. In stock.</p>"
                   "<form action='/cart'><button>Add to cart</button></form>")
        data = bundle([page(ORIGIN + "/", html_doc()),
                       page(ORIGIN + "/products/a", html_doc(body=selling)),
                       page(ORIGIN + "/products/b", html_doc(body=selling))])
        opportunity = recommend._intent_coverage(data)
        self.assertIsNotNone(opportunity)
        self.assertIn("no FAQ-shaped page", opportunity["why_now"])
        self.assertEqual(opportunity["verification_type"], "external_validation")

    def test_a_bare_bundle_is_left_alone(self):
        self.assertIsNone(recommend._intent_coverage(bundle([])))


# ---------------------------------------------------------------------------
# 6. the package still describes itself correctly
# ---------------------------------------------------------------------------

class TestPackageIntegrity(unittest.TestCase):

    def test_every_specialist_still_loads(self):
        for skill_id in ("crawl-render-audit", "machine-readability-audit",
                         "freshness-corroboration", "entity-audit",
                         "engagement-audit", "answerability-audit"):
            with self.subTest(skill=skill_id):
                self.assertTrue(hasattr(specialist(skill_id), "analyze"))


if __name__ == "__main__":
    unittest.main()
