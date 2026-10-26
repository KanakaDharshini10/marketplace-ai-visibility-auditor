"""Specialist reliability: data-shape contracts at the bundle boundary, and
what the report says when a specialist does not finish.

Both halves come from one live regression. The entity specialist read the
page's ``microdata`` field - a *list* of item records - as a mapping, raised
``'list' object has no attribute 'get'`` on the first page that carried any
microdata, and the run was reported as ``entity-audit: 0 finding(s)
[FAILED: ...]``: a crash presented as a clean pillar.

The shape tests here exercise the producer, not a hand-written stand-in, so
they fail if the extractor and a consumer ever disagree again. The failure
tests pin down the other half: a specialist that raises is recorded as
failed, its pillar is unmeasured rather than scored, every other specialist's
findings survive, and the report's coverage says so in every projection a
reader might quote.
"""

from __future__ import annotations

import json
import types
import unittest

import helpers
from helpers import ORIGIN, bundle, commerce_bundle, html_doc, jsonld, page, run, rule_ids
from aiva import orchestrator, report as report_mod
from aiva.config import AuditConfig
from aiva.extract import microdata_items, microdata_props, microdata_types, prop, text_of

LOCATOR_HOME = ('<h1>Halstow</h1><a href="/store-locator">Find a store</a>'
                '<a href="/products/kettle">Kettle</a>')

PRODUCT_MICRODATA = ('<div itemscope itemtype="https://schema.org/Product">'
                     '<span itemprop="name">Kettle</span>'
                     '<span itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
                     '<span itemprop="price">20</span></span></div>')

PLACE_MICRODATA = ('<div itemscope itemtype="https://schema.org/LocalBusiness">'
                   '<span itemprop="name">Halstow Leeds</span>'
                   '<div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">'
                   '<span itemprop="addressLocality">Leeds</span></div></div>')

ORG_WITH_ADDRESS_MICRODATA = ('<div itemscope itemtype="https://schema.org/Organization">'
                              '<span itemprop="name">Halstow</span>'
                              '<span itemprop="address">1 Mill Lane, Leeds</span></div>')


#: The locator page the home page links to: branches with a telephone number
#: and opening hours in prose. The link alone establishes nothing; the page
#: carrying this shape is what makes the locations finding legitimate.
LOCATOR_PAGE = ('<main><h1>Find a store</h1>'
                '<p>Halstow Leeds - 3 Briggate. Tel 0113 496 0456. Mon-Sat 9:00-18:00.</p>'
                '<p>Halstow York - 8 Stonegate. Tel 01904 496 0123. Mon-Sat 9:00-17:30.</p>'
                '</main>')


def _site(home_extra: str = "", product_extra: str = "") -> dict:
    """A three-page site: a home page linking to a store locator, the locator
    itself (branches with phone and hours in prose), and a product."""
    home = page(ORIGIN + "/", html_doc(title="Halstow", body=LOCATOR_HOME + home_extra))
    locator = page(ORIGIN + "/store-locator", html_doc(title="Find a store", body=LOCATOR_PAGE))
    pdp = page(ORIGIN + "/products/kettle", html_doc(
        title="Kettle", body="<h1>Kettle</h1><p>£20 in stock</p>" + product_extra))
    return bundle([home, locator, pdp])


# ---------------------------------------------------------------------------
# 1. the microdata contract, read through the real producer
# ---------------------------------------------------------------------------

class TestMicrodataShapeContract(unittest.TestCase):

    def test_the_producer_emits_a_list_of_item_records(self):
        facts = page(ORIGIN + "/", html_doc(body=PRODUCT_MICRODATA + PLACE_MICRODATA))
        self.assertIsInstance(facts["microdata"], list)
        self.assertGreaterEqual(len(facts["microdata"]), 2)
        for record in facts["microdata"]:
            self.assertEqual(set(record), {"itemtype", "types", "props"})
            self.assertIsInstance(record["types"], list)
            self.assertIsInstance(record["props"], dict)

    def test_the_accessor_reads_every_record_the_producer_wrote(self):
        facts = page(ORIGIN + "/", html_doc(body=PRODUCT_MICRODATA + PLACE_MICRODATA))
        self.assertEqual(len(microdata_items(facts)), len(facts["microdata"]))

    def test_types_share_the_jsonld_spelling(self):
        facts = page(ORIGIN + "/", html_doc(body=PLACE_MICRODATA))
        self.assertIn("localbusiness", microdata_types(facts))
        self.assertIn("postaladdress", microdata_types(facts))

    def test_a_bare_record_is_accepted_as_one_item(self):
        record = {"itemtype": "https://schema.org/Store", "types": ["Store"], "props": {}}
        self.assertEqual(microdata_items({"microdata": record}), [record])
        self.assertEqual(microdata_items(record), [record])
        self.assertIn("store", microdata_types({"microdata": record}))

    def test_foreign_shapes_yield_nothing_rather_than_raising(self):
        for value in (None, "", 3, "Product", [1, "x", None], {"microdata": None},
                      {"microdata": "Product"}, {"microdata": [["nested"]]}):
            self.assertEqual(microdata_items(value), [], repr(value))
            self.assertEqual(microdata_types(value), [], repr(value))
        self.assertEqual(microdata_props("not a record"), {})
        self.assertEqual(microdata_props({"props": ["not", "a", "mapping"]}), {})

    def test_props_are_normalised_to_lists_of_strings(self):
        facts = page(ORIGIN + "/", html_doc(body=ORG_WITH_ADDRESS_MICRODATA))
        org = [r for r in microdata_items(facts) if "organization" in microdata_types([r])]
        self.assertEqual(len(org), 1)
        self.assertEqual(microdata_props(org[0]).get("address"), ["1 Mill Lane, Leeds"])


# ---------------------------------------------------------------------------
# 2. the entity specialist over that contract
# ---------------------------------------------------------------------------

class TestEntitySpecialistReadsMicrodata(unittest.TestCase):

    def test_microdata_on_a_page_no_longer_crashes_the_specialist(self):
        # The exact live shape: a locator link plus a Product itemscope.
        findings = run("entity-audit", _site(home_extra=PRODUCT_MICRODATA))
        self.assertIsInstance(findings, list)

    def test_the_legitimate_location_finding_is_preserved(self):
        # A Product itemscope is not a place; the locator link still has no
        # readable location behind it, so the finding must still fire.
        findings = run("entity-audit", _site(home_extra=PRODUCT_MICRODATA))
        self.assertIn("EN-LOCATIONS-UNSTRUCTURED", rule_ids(findings))

    def test_a_microdata_place_entity_satisfies_the_rule(self):
        findings = run("entity-audit", _site(home_extra=PLACE_MICRODATA))
        self.assertNotIn("EN-LOCATIONS-UNSTRUCTURED", rule_ids(findings))

    def test_a_microdata_organization_with_an_address_counts_as_grounding(self):
        findings = run("entity-audit", _site(home_extra=ORG_WITH_ADDRESS_MICRODATA))
        self.assertNotIn("EN-LOCATIONS-UNSTRUCTURED", rule_ids(findings))

    def test_an_online_store_type_is_not_mistaken_for_a_physical_one(self):
        # The old substring test matched "store" inside "OnlineStore". An
        # online shop with a locator link and no place entity is exactly the
        # case the rule exists for.
        online = ('<div itemscope itemtype="https://schema.org/OnlineStore">'
                  '<span itemprop="name">Halstow</span></div>')
        findings = run("entity-audit", _site(home_extra=online))
        self.assertIn("EN-LOCATIONS-UNSTRUCTURED", rule_ids(findings))

    def test_the_jsonld_branch_is_unchanged(self):
        place = jsonld(json.dumps({"@context": "https://schema.org", "@type": "Store",
                                   "name": "Halstow Leeds",
                                   "address": {"@type": "PostalAddress",
                                               "addressLocality": "Leeds"}}))
        home = page(ORIGIN + "/", html_doc(title="Halstow", head=place, body=LOCATOR_HOME))
        pdp = page(ORIGIN + "/products/kettle", html_doc(title="Kettle",
                                                          body="<h1>Kettle</h1><p>£20</p>"))
        findings = run("entity-audit", bundle([home, pdp]))
        self.assertNotIn("EN-LOCATIONS-UNSTRUCTURED", rule_ids(findings))

    def test_a_legacy_mapping_shaped_field_is_still_read(self):
        data = _site()
        data["pages"][0]["microdata"] = {"itemtype": "https://schema.org/LocalBusiness",
                                         "types": ["LocalBusiness"], "props": {}}
        findings = run("entity-audit", data)
        self.assertNotIn("EN-LOCATIONS-UNSTRUCTURED", rule_ids(findings))


# ---------------------------------------------------------------------------
# 3. every specialist, over every shape schema.org permits
# ---------------------------------------------------------------------------

def _listify(value):
    """Wrap every property value in a list - schema.org allows it anywhere."""
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            if key in ("@context", "@id"):
                out[key] = inner
            elif key == "@type":
                out[key] = [inner] if isinstance(inner, str) else inner
            else:
                wrapped = _listify(inner)
                out[key] = wrapped if isinstance(wrapped, list) else [wrapped]
        return out
    if isinstance(value, list):
        return [_listify(v) for v in value]
    return value


ORG = {"@context": "https://schema.org", "@type": "Organization", "@id": ORIGIN + "/#org",
       "name": "Halstow", "legalName": "Halstow Appliances Ltd", "url": ORIGIN + "/",
       "logo": ORIGIN + "/logo.png", "description": "A kitchen appliance maker.",
       "sameAs": ["https://www.instagram.com/halstow"], "foundingDate": "2001",
       "address": {"@type": "PostalAddress", "addressLocality": "Leeds"},
       "contactPoint": {"@type": "ContactPoint", "contactType": "customer service"}}

PRODUCT = {"@context": "https://schema.org", "@type": "Product", "name": "Kettle K1",
           "sku": "K1", "brand": {"@id": ORIGIN + "/#org"}, "category": "Kettles",
           "image": ORIGIN + "/k1.jpg", "color": "Blue", "material": "Steel",
           "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.5",
                               "reviewCount": "12"},
           "additionalProperty": [{"@type": "PropertyValue", "name": "Capacity",
                                   "value": "1.7 L"}],
           "offers": {"@type": "Offer", "price": "20", "priceCurrency": "GBP",
                      "availability": "https://schema.org/InStock",
                      "priceSpecification": {"@type": "PriceSpecification", "price": "20",
                                             "priceCurrency": "GBP"}}}

GROUP = {"@context": "https://schema.org", "@type": "ProductGroup", "name": "Kettle K2",
         "productGroupID": "K2", "brand": {"@type": "Brand", "name": "Halstow"},
         "variesBy": "color",
         "hasVariant": [{"@type": "Product", "name": "Kettle K2 - Red", "sku": "K2-R",
                         "offers": {"@type": "Offer", "price": "25", "priceCurrency": "GBP",
                                    "availability": "https://schema.org/InStock"}},
                        {"@type": "Product", "name": "Kettle K2 - Blue", "sku": "K2-B",
                         "offers": [{"@type": "Offer", "price": "25", "priceCurrency": "GBP",
                                     "availability": "https://schema.org/OutOfStock"}]}]}


def _shaped_site(transform) -> dict:
    """The same small shop with its structured data passed through ``transform``."""
    def ld(payload):
        return jsonld(json.dumps(transform(payload)))
    home = page(ORIGIN + "/", html_doc(
        title="Halstow", head=ld(ORG),
        body='<h1>Halstow</h1><a href="/store-locator">Find a store</a>'
             '<a href="/collections/kettles">Kettles</a><a href="/pages/returns">Returns</a>'
             + PRODUCT_MICRODATA + PLACE_MICRODATA))
    listing = page(ORIGIN + "/collections/kettles", html_doc(
        title="Kettles", body='<h1>Kettles</h1><a href="/products/k1">Kettle K1</a>'
                              '<a href="/products/k2">Kettle K2</a>'))
    k1 = page(ORIGIN + "/products/k1", html_doc(
        title="Kettle K1", head=ld(PRODUCT),
        body="<h1>Kettle K1</h1><p>£20 - in stock.</p>"
             "<table><tr><th>Capacity</th><td>1.7 L</td></tr></table>"))
    k2 = page(ORIGIN + "/products/k2", html_doc(
        title="Kettle K2", head=ld(GROUP),
        body="<h1>Kettle K2</h1><p>£25 - in stock.</p>"
             '<select name="color"><option>Red</option><option>Blue</option></select>'))
    policy = page(ORIGIN + "/pages/returns", html_doc(
        title="Returns", body="<h1>Returns</h1><p>Free returns within 30 days.</p>"))
    return bundle([home, listing, k1, k2, policy])


class TestEverySpecialistSurvivesPermittedShapes(unittest.TestCase):
    """No specialist may crash on a shape the producer or schema.org permits."""

    SHAPES = {
        "as written": lambda d: d,
        "every value a list": _listify,
        "@graph wrapped": lambda d: {"@context": "https://schema.org", "@graph": [d]},
        "top-level list": lambda d: [d],
        "@graph of listified": lambda d: {"@context": "https://schema.org",
                                          "@graph": [_listify(d)]},
    }

    def test_no_specialist_fails_on_any_shape(self):
        for name, transform in self.SHAPES.items():
            with self.subTest(shape=name):
                findings, runs = orchestrator.run_specialists(_shaped_site(transform))
                failed = {r["skill"]: r.get("error") for r in runs if r["status"] != "ok"}
                self.assertEqual(failed, {}, f"shape '{name}' crashed a specialist")
                self.assertTrue(findings)

    def test_list_valued_properties_are_still_read_not_skipped(self):
        # The fix must read the data, not step around it: a listified brand
        # reference still resolves, so the product-brand rules still see it.
        data = _shaped_site(_listify)
        entity = run("entity-audit", data)
        self.assertNotIn("EN-PRODUCT-BRAND-MISSING", rule_ids(entity))
        k1 = [p for p in data["pages"] if p["url"].endswith("/products/k1")][0]
        node = [n for n in k1["jsonld_nodes"] if "Product" in (n.get("@type") or [])][0]
        self.assertEqual(text_of(prop(node, "name")), "Kettle K1")

    def test_the_report_builds_and_validates_for_every_shape(self):
        for name, transform in self.SHAPES.items():
            with self.subTest(shape=name):
                data = _shaped_site(transform)
                findings, runs = orchestrator.run_specialists(data)
                built = report_mod.build_report(data, findings, AuditConfig(site=ORIGIN),
                                                skill_runs=runs)
                self.assertEqual(report_mod.validate_report(built), [])
                self.assertEqual(built["summary"]["specialist_coverage"], "complete")
                report_mod.render_markdown(built)


# ---------------------------------------------------------------------------
# 4. a specialist that does not finish
# ---------------------------------------------------------------------------

class _Exploding:
    @staticmethod
    def analyze(_bundle):
        raise AttributeError("'list' object has no attribute 'get'")


_REAL_LOAD = orchestrator.load_specialists


def _with_failing(skill_to_break: str):
    """The real specialists, with one replaced by a module that raises."""
    broken = types.ModuleType("exploding")
    broken.analyze = _Exploding.analyze
    return [(skill, broken if skill == skill_to_break else module)
            for skill, module in _REAL_LOAD()]


class TestAFailedSpecialistIsNeverZeroFindings(unittest.TestCase):

    def setUp(self):
        self.data = commerce_bundle()
        self.original = orchestrator.load_specialists
        orchestrator.load_specialists = lambda *a, **k: _with_failing("entity-audit")
        try:
            self.findings, self.runs = orchestrator.run_specialists(self.data)
        finally:
            orchestrator.load_specialists = self.original
        self.failed = [r for r in self.runs if r["skill"] == "entity-audit"][0]
        self.report = report_mod.build_report(self.data, self.findings, AuditConfig(site=ORIGIN),
                                              skill_runs=self.runs)

    def test_the_run_record_says_failed_and_carries_the_error(self):
        self.assertEqual(self.failed["status"], "failed")
        self.assertFalse(self.failed["ok"])
        self.assertIn("AttributeError", self.failed["error"])
        self.assertIn("'list' object has no attribute 'get'", self.failed["error"])
        self.assertEqual(self.failed["pillar"], "entity")

    def test_findings_is_null_not_zero(self):
        self.assertIsNone(self.failed["findings"])

    def test_the_progress_line_never_reads_as_a_count(self):
        line = orchestrator.describe_run(self.failed)
        self.assertNotIn("0 finding", line)
        self.assertIn("FAILED", line)
        self.assertIn("entity pillar is not measured", line)
        ok_line = orchestrator.describe_run([r for r in self.runs if r["status"] == "ok"][0])
        self.assertIn("finding(s) [ok]", ok_line)

    def test_every_other_specialist_still_ran_and_kept_its_findings(self):
        others = [r for r in self.runs if r["skill"] != "entity-audit"]
        self.assertEqual(len(others), 5)
        self.assertTrue(all(r["status"] == "ok" for r in others))
        self.assertEqual(sum(r["findings"] for r in others), len(self.findings))
        self.assertEqual(self.report["summary"]["total_findings"], len(self.findings))
        self.assertEqual({f["source_skill"] for f in self.report["findings"]},
                         {r["skill"] for r in others if r["findings"]})

    def test_the_failed_pillar_is_unmeasured_not_clean(self):
        entity = self.report["scores"]["pillars"]["entity"]
        self.assertIsNone(entity["score"])
        self.assertEqual(entity["band"], "unmeasured")
        self.assertFalse(entity["measured"])
        self.assertIn("entity-audit", entity["unmeasured_reason"])
        self.assertIn("entity", self.report["scores"]["overall"]["unmeasured_pillars"])
        for pillar, entry in self.report["scores"]["pillars"].items():
            if pillar != "entity":
                self.assertIsNotNone(entry["score"], pillar)

    def test_the_summary_declares_partial_specialist_coverage(self):
        self.assertEqual(self.report["summary"]["specialist_coverage"], "partial")
        # ...without disturbing the evidence-level state: pages were read.
        self.assertEqual(self.report["summary"]["coverage_state"], "content")

    def test_the_coverage_block_names_the_failure(self):
        block = self.report["coverage"]["specialists"]
        self.assertEqual(block["state"], "partial")
        self.assertEqual(block["expected"], 6)
        self.assertEqual(len(block["completed"]), 5)
        self.assertEqual(block["failed"], [{"skill": "entity-audit", "pillar": "entity",
                                            "error": self.failed["error"]}])
        self.assertEqual(block["unmeasured_pillars"], ["entity"])

    def test_the_headline_and_score_basis_say_coverage_is_incomplete(self):
        headline = self.report["summary"]["headline"]
        self.assertIn("Specialist coverage is incomplete", headline)
        self.assertIn("entity-audit", headline)
        basis = self.report["summary"]["score_basis"]
        self.assertIn("entity-audit failed", basis)
        self.assertIn("excluded from the score", basis)

    def test_the_markdown_projection_shows_it_too(self):
        text = report_mod.render_markdown(self.report)
        self.assertIn("Specialists completed: 5 of 6", text)
        self.assertIn("entity-audit FAILED", text)
        self.assertIn("unmeasured (specialist entity-audit failed", text)
        self.assertNotIn("entity-audit: 0", text)

    def test_the_report_still_validates(self):
        self.assertEqual(report_mod.validate_report(self.report), [])
        self.assertIn(self.failed, self.report["diagnostics"]["skill_runs"])


class TestCompleteAndUnrecordedCoverage(unittest.TestCase):

    def test_every_specialist_finishing_is_complete(self):
        data = commerce_bundle()
        findings, runs = orchestrator.run_specialists(data)
        self.assertTrue(all(r["status"] == "ok" and isinstance(r["findings"], int)
                            for r in runs))
        built = report_mod.build_report(data, findings, AuditConfig(site=ORIGIN),
                                        skill_runs=runs)
        self.assertEqual(built["summary"]["specialist_coverage"], "complete")
        self.assertEqual(built["coverage"]["specialists"]["failed"], [])
        self.assertNotIn("incomplete", built["summary"]["headline"])
        self.assertNotIn("failed", built["summary"]["score_basis"])

    def test_run_records_carry_the_manifest_pillar(self):
        _, runs = orchestrator.run_specialists(commerce_bundle())
        expected = orchestrator.specialist_pillars()
        self.assertEqual({r["skill"]: r["pillar"] for r in runs}, expected)
        self.assertEqual(set(expected.values()),
                         set(report_mod.scoring.PILLAR_WEIGHTS))

    def test_no_run_records_is_unrecorded_not_complete(self):
        data = commerce_bundle()
        built = report_mod.build_report(data, [], AuditConfig(site=ORIGIN))
        self.assertEqual(built["summary"]["specialist_coverage"], "unrecorded")
        self.assertEqual(built["coverage"]["specialists"]["state"], "unrecorded")

    def test_a_failure_in_a_transport_only_run_is_still_named(self):
        # coverage_state stays transport_only; the specialist failure is a
        # second, independent caveat rather than a replacement for it.
        data = bundle([])
        runs = [{"skill": "crawl-render-audit", "pillar": "crawl_render", "status": "failed",
                 "ok": False, "findings": None, "error": "RuntimeError: boom"}]
        built = report_mod.build_report(data, [], AuditConfig(site=ORIGIN), skill_runs=runs)
        self.assertEqual(built["summary"]["coverage_state"], "transport_only")
        self.assertEqual(built["summary"]["specialist_coverage"], "partial")
        self.assertIsNone(built["scores"]["pillars"]["crawl_render"]["score"])
        self.assertIn("crawl-render-audit", built["summary"]["score_basis"])


class TestEndToEndWithAFailingSpecialist(unittest.TestCase):
    """The entrypoint's own progress output, over a real (local) crawl."""

    @classmethod
    def setUpClass(cls):
        from aiva import localserve
        server, base = localserve.start(helpers.ROOT / "tests" / "fixtures" / "site_strong")
        original = orchestrator.load_specialists
        orchestrator.load_specialists = lambda *a, **k: _with_failing("engagement-audit")
        cls.messages = []
        try:
            config = AuditConfig(site=base, request_delay_s=0.1, check_external=False)
            cls.bundle, cls.report = orchestrator.run_audit(
                config, on_progress=cls.messages.append)
        finally:
            orchestrator.load_specialists = original
            server.shutdown()
            server.server_close()

    def test_the_progress_output_never_prints_a_failure_as_zero_findings(self):
        failed = [m for m in self.messages if "engagement-audit" in m]
        self.assertTrue(failed)
        self.assertTrue(all("0 finding" not in m for m in failed), failed)
        self.assertTrue(any("FAILED before producing findings" in m for m in failed))
        self.assertTrue(any("specialist coverage is incomplete" in m for m in self.messages))

    def test_the_report_is_marked_partial_and_valid(self):
        self.assertEqual(self.report["summary"]["specialist_coverage"], "partial")
        self.assertIsNone(self.report["scores"]["pillars"]["engagement"]["score"])
        self.assertTrue(self.report["diagnostics"]["schema_validation"]["valid"])
        self.assertIn("engagement-audit", self.report["generator"]["specialist_skills"])


if __name__ == "__main__":
    unittest.main()
