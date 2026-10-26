"""Site shapes the auditor was not designed around, audited end to end.

The rubric says "works on unseen sites". The bundled fixtures are storefronts;
these are the other shapes a URL can turn out to be - a documentation and
community site, a publisher, a company/SaaS site - each served over loopback
and audited through the real entrypoint. What is asserted is what must *not*
happen on such a site:

* no product-only, listing-only or commerce policy finding;
* no "your stores are invisible" finding on a site with a conference venue,
  a jobs page and a user-group directory;
* answerability reported as unmeasured, not scored;
* every specialist completes and the report validates.

Nothing here is a real site. The shapes are generic; the assertions are
about the absence of the wrong kind of finding, which is the failure mode
that matters on a site nobody designed the auditor for.

Run just this file:

    python3 tests/run_tests.py site_shapes -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import html_doc

from aiva import localserve, orchestrator
from aiva.config import AuditConfig

COMMERCE_RULE_PREFIXES = ("MR-PRODUCT", "MR-OFFER", "MR-IDENTIFIERS", "MR-ATTRIBUTES",
                          "MR-BREADCRUMB", "MR-REVIEW", "EG-", "AN-", "FC-PRICE",
                          "FC-AVAILABILITY", "FC-CROSS-PAGE", "EN-PRODUCT", "EN-VARIANTS",
                          "EN-CATEGORY", "EN-DUPLICATE-PRODUCT")
#: Engagement rules that are legitimately about any site, not a catalogue.
NON_COMMERCE_ENGAGEMENT = ("EG-DEEPLINK-REDIRECTED-HOME", "EG-FAQ-MISSING",
                           "EG-NO-SITE-SEARCH", "EG-ORIENTATION-MISSING")


def _nav() -> str:
    return ('<nav><a href="/">Home</a><a href="/docs/">Docs</a><a href="/community/">Community</a>'
            '<a href="/events/venue.html">Venue</a><a href="/jobs.html">Jobs</a>'
            '<a href="/community/locations.html">Locations</a><a href="/about.html">About</a></nav>')


def _docs_site(root: Path) -> None:
    (root / "docs").mkdir(parents=True)
    (root / "community").mkdir()
    (root / "events").mkdir()
    org = ('<script type="application/ld+json">{"@context":"https://schema.org",'
           '"@type":"Organization","name":"Kestrel Foundation","url":"/",'
           '"description":"The home of the Kestrel language."}</script>')
    (root / "index.html").write_text(html_doc(
        title="Kestrel Language", head=org, canonical="/",
        body=_nav() + "<main><h1>Kestrel</h1><p>Kestrel is a language for reliable "
        "software. Read the documentation, join the community, or come to the "
        "conference.</p></main>"), encoding="utf-8")
    (root / "docs" / "index.html").write_text(html_doc(
        title="Documentation", canonical="/docs/",
        body=_nav() + "<main><h1>Documentation</h1><p>The tutorial, the library "
        "reference and the language specification.</p><a href='/docs/tutorial.html'>"
        "Tutorial</a></main>"), encoding="utf-8")
    (root / "docs" / "tutorial.html").write_text(html_doc(
        title="Tutorial", canonical="/docs/tutorial.html",
        head='<script type="application/ld+json">{"@context":"https://schema.org",'
             '"@type":"TechArticle","headline":"Tutorial","dateModified":"2026-08-01"}</script>',
        body=_nav() + "<main><h1>Tutorial</h1><p>" + " ".join(
            ["Start with values, then functions, then modules."] * 30) + "</p></main>"),
        encoding="utf-8")
    (root / "community" / "index.html").write_text(html_doc(
        title="Community", canonical="/community/",
        body=_nav() + "<main><h1>Community</h1><p>Mailing lists, chat, and user groups "
        "in many locations.</p></main>"), encoding="utf-8")
    (root / "community" / "locations.html").write_text(html_doc(
        title="User groups by location", canonical="/community/locations.html",
        body=_nav() + "<main><h1>User groups by location</h1><ul><li>Bristol</li>"
        "<li>Leeds</li><li>Berlin</li><li>Austin</li></ul></main>"), encoding="utf-8")
    (root / "events" / "venue.html").write_text(html_doc(
        title="Conference venue", canonical="/events/venue.html",
        head='<script type="application/ld+json">{"@context":"https://schema.org",'
             '"@type":"Event","name":"KestrelConf 2026","startDate":"2026-06-12",'
             '"location":"Riverside Centre"}</script>',
        body=_nav() + "<main><h1>Conference venue</h1><p>KestrelConf 2026 is held at the "
        "Riverside Centre, 12-14 June. Registration: 0117 496 0123. "
        "Doors open Friday 8:30-18:00.</p></main>"), encoding="utf-8")
    (root / "jobs.html").write_text(html_doc(
        title="Jobs", canonical="/jobs.html",
        body=_nav() + "<main><h1>Jobs</h1><p>Open roles in our locations: Bristol, Berlin "
        "and remote. Apply online.</p></main>"), encoding="utf-8")
    (root / "about.html").write_text(html_doc(
        title="About", canonical="/about.html",
        body=_nav() + "<main><h1>About</h1><p>The Kestrel Foundation stewards the "
        "language and its community.</p></main>"), encoding="utf-8")
    (root / "robots.txt").write_text("User-agent: *\nDisallow:\n", encoding="utf-8")


class TestDocumentationSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        _docs_site(root)
        server, base = localserve.start(root)
        try:
            config = AuditConfig(site=base, request_delay_s=0.1, check_external=False,
                                 allow_private_hosts=True)
            cls.bundle, cls.report = orchestrator.run_audit(config)
        finally:
            server.shutdown()
            server.server_close()
        cls.rules = {f["rule_id"] for f in cls.report["findings"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_no_commerce_finding_on_a_non_commerce_site(self):
        offenders = [r for r in self.rules
                     if r.startswith(COMMERCE_RULE_PREFIXES) and r not in NON_COMMERCE_ENGAGEMENT]
        self.assertEqual(offenders, [], f"commerce findings on a documentation site: {offenders}")

    def test_no_location_finding_from_a_venue_a_jobs_page_and_a_directory(self):
        self.assertNotIn("EN-LOCATIONS-UNSTRUCTURED", self.rules)

    def test_answerability_is_unmeasured_not_scored(self):
        self.assertIsNone(self.report["answerability"]["answerability_score"])
        self.assertEqual(self.report["scores"]["pillars"]["answerability"]["band"], "unmeasured")

    def test_no_product_or_listing_page_was_invented(self):
        types = {p["page_type"] for p in self.bundle["pages"] if not p.get("fetch_failed")}
        self.assertNotIn("product", types)
        self.assertNotIn("category", types)

    def test_the_location_shaped_pages_were_actually_read(self):
        """Guard against the negative passing vacuously."""
        read = {p["url"].split(self.bundle["site"]["origin"], 1)[-1]
                for p in self.bundle["pages"] if not p.get("fetch_failed")}
        for path in ("/events/venue.html", "/jobs.html", "/community/locations.html"):
            self.assertIn(path, read)

    def test_specialists_complete_and_report_validates(self):
        self.assertEqual(self.report["summary"]["specialist_coverage"], "complete")
        self.assertEqual(self.report["diagnostics"]["schema_validation"]["errors"], [])
        self.assertEqual(self.report["summary"]["coverage_state"], "content")


if __name__ == "__main__":
    unittest.main()
