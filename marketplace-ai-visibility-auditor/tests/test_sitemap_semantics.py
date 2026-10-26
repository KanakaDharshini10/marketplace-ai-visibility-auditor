"""Sitemap evidence says what was probed and what answered - nothing more.

A finite list of probed locations cannot establish that a site has no
sitemap, and "the probed locations returned 404" is a different fact from
"the site has no sitemap". These tests pin the three sitemap rules to the
observations behind them: which locations were checked, how each one
answered, whether robots.txt was read, and whether it names a sitemap. The
consequence a reader cares about - that a crawler's discovery falls back to
internal linking - is asserted only when both discovery mechanisms were
actually checked and both came back empty.
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, find, html_doc, page, run

FORBIDDEN = ("has no sitemap", "no sitemap exists", "depends entirely",
             "the site has no", "there is no sitemap")

CONVENTIONAL = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                "/sitemap.xml.gz", "/wp-sitemap.xml")


def _probe(path: str, *, status: int = 404, error: str = None, kind: str = None,
           source: str = "well-known path probe", url_count: int = 0) -> dict:
    if error is None and status >= 400:
        error = f"HTTP {status}"
    record = {"url": ORIGIN + path, "source": source, "status": status, "kind": kind,
              "error": error, "url_count": url_count, "child_count": 0, "lastmods": [],
              "sample_urls": [], "entries": [], "entries_captured": url_count,
              "missing_lastmod": 0}
    return record


def _valid(path: str, source: str = "well-known path probe") -> dict:
    record = _probe(path, status=200, kind="urlset", source=source, url_count=3)
    record["entries"] = [{"url": ORIGIN + f"/products/p{i}", "lastmod": "2026-01-01"}
                         for i in range(3)]
    record["lastmods"] = ["2026-01-01"] * 3
    record["sample_urls"] = [e["url"] for e in record["entries"]]
    return record


def _site(sitemaps, *, robots_raw="User-agent: *\nDisallow:\n", robots_status=200,
          robots_error=None):
    home = page(ORIGIN + "/", html_doc(title="Halstow", body='<h1>Halstow</h1>'
                                       '<a href="/products/kettle">Kettle</a>'))
    pdp = page(ORIGIN + "/products/kettle", html_doc(
        title="Kettle | Halstow", body="<h1>Kettle</h1><p>£20 in stock</p>"))
    return bundle([home, pdp], sitemaps=sitemaps, robots_raw=robots_raw,
                  robots_status=robots_status, robots_error=robots_error)


def _text(item) -> str:
    return " ".join([item.title, item.evidence, item.interpretation or "",
                     " ".join(e.observation for e in item.evidence_items)]).lower()


class TestEveryProbedLocationReturned404(unittest.TestCase):

    def setUp(self):
        self.findings = run("crawl-render-audit", _site([_probe(p) for p in CONVENTIONAL]))
        self.item = find(self.findings, "CR-NO-SITEMAP")

    def test_the_finding_fires_and_is_established(self):
        self.assertIsNotNone(self.item)
        self.assertEqual(self.item.severity, "high")
        self.assertTrue(self.item.metrics["discoverability_established"])
        self.assertEqual(self.item.metrics["not_found"], len(CONVENTIONAL))
        self.assertEqual(self.item.metrics["unchecked"], 0)
        self.assertEqual(self.item.metrics["robots_directive"], "absent")

    def test_the_evidence_names_each_location_and_its_answer(self):
        for path in CONVENTIONAL:
            self.assertIn(ORIGIN + path, self.item.evidence)
        self.assertIn("HTTP 404", self.item.evidence)
        self.assertEqual(self.item.metrics["probed_locations"],
                         [ORIGIN + p for p in CONVENTIONAL])

    def test_absence_is_stated_about_discoverability_not_existence(self):
        text = _text(self.item)
        for phrase in FORBIDDEN:
            self.assertNotIn(phrase, text, phrase)
        self.assertIn("discoverable", text)
        self.assertIn("statement about what is discoverable, not about what exists", text)

    def test_the_internal_linking_consequence_is_claimed_only_here(self):
        self.assertIn("falls back to following internal links", self.item.interpretation)
        self.assertIn("no prior knowledge", self.item.interpretation)

    def test_the_missing_directive_is_a_separate_finding(self):
        undeclared = find(self.findings, "CR-SITEMAP-UNDECLARED")
        self.assertIsNotNone(undeclared)
        self.assertEqual(undeclared.title, "robots.txt declares no Sitemap directive")
        self.assertIn("fact about robots.txt only", undeclared.evidence)
        self.assertFalse(undeclared.metrics["sitemap_found_elsewhere"])
        # ...and the same fact is stated, as a fact about robots.txt, in the
        # no-sitemap finding's own evidence, so the two never contradict.
        self.assertIn("declares no Sitemap directive", self.item.evidence)


class TestOneValidSitemapDiscovered(unittest.TestCase):

    def test_no_absence_finding_and_the_directive_gap_is_reported_alone(self):
        sitemaps = [_valid("/sitemap.xml")] + [_probe(p) for p in CONVENTIONAL[1:]]
        findings = run("crawl-render-audit", _site(sitemaps))
        self.assertIsNone(find(findings, "CR-NO-SITEMAP"))
        self.assertIsNone(find(findings, "CR-SITEMAP-BROKEN"))
        undeclared = find(findings, "CR-SITEMAP-UNDECLARED")
        self.assertIsNotNone(undeclared)
        self.assertIn("working sitemap exists", undeclared.title)
        self.assertTrue(undeclared.metrics["sitemap_found_elsewhere"])


class TestSitemapDeclaredInRobots(unittest.TestCase):

    def test_a_valid_declared_sitemap_produces_no_sitemap_finding_at_all(self):
        sitemaps = [_valid("/sitemaps/catalog.xml", source="robots.txt Sitemap directive")]
        sitemaps += [_probe(p) for p in CONVENTIONAL]
        findings = run("crawl-render-audit", _site(
            sitemaps, robots_raw=f"User-agent: *\nDisallow:\nSitemap: {ORIGIN}/sitemaps/catalog.xml\n"))
        for rule in ("CR-NO-SITEMAP", "CR-SITEMAP-BROKEN", "CR-SITEMAP-UNDECLARED"):
            self.assertIsNone(find(findings, rule), rule)


class TestMalformedSitemap(unittest.TestCase):

    def test_a_declared_sitemap_that_does_not_parse_is_broken_not_absent(self):
        sitemaps = [_probe("/sitemaps/catalog.xml", status=200, kind="unknown",
                           error="XML parse error: mismatched tag: line 4, column 2",
                           source="robots.txt Sitemap directive")]
        sitemaps += [_probe(p) for p in CONVENTIONAL]
        findings = run("crawl-render-audit", _site(
            sitemaps, robots_raw=f"User-agent: *\nDisallow:\nSitemap: {ORIGIN}/sitemaps/catalog.xml\n"))
        broken = find(findings, "CR-SITEMAP-BROKEN")
        self.assertIsNotNone(broken)
        self.assertEqual(broken.severity, "medium")
        self.assertIn("does not parse", broken.title)
        self.assertIn("XML parse error", broken.evidence)
        self.assertEqual(broken.metrics["outcomes"], {"malformed": 1})
        # The site declares a sitemap; its state is that sitemap's, not an
        # absence.
        self.assertIsNone(find(findings, "CR-NO-SITEMAP"))

    def test_a_conventional_path_serving_html_is_reported_as_what_it_served(self):
        sitemaps = [_probe("/sitemap.xml", status=200, kind="unknown",
                           error="XML parse error: syntax error: line 1, column 0")]
        sitemaps += [_probe(p) for p in CONVENTIONAL[1:]]
        item = find(run("crawl-render-audit", _site(sitemaps)), "CR-NO-SITEMAP")
        self.assertIsNotNone(item)
        self.assertIn("HTTP 200 but sitemap XML parsing failed", item.evidence)
        self.assertEqual(item.metrics["malformed"], 1)


class TestTransportFailures(unittest.TestCase):

    def test_every_probe_failing_in_transport_reports_no_absence(self):
        sitemaps = [_probe(p, status=0, error="timed out after 8.0s") for p in CONVENTIONAL]
        findings = run("crawl-render-audit", _site(sitemaps))
        self.assertIsNone(find(findings, "CR-NO-SITEMAP"))
        # The robots.txt fact is still a fact.
        self.assertIsNotNone(find(findings, "CR-SITEMAP-UNDECLARED"))

    def test_a_partly_unchecked_probe_list_is_not_established(self):
        sitemaps = [_probe(CONVENTIONAL[0], status=0, error="timed out after 8.0s"),
                    _probe(CONVENTIONAL[1], status=429, error="HTTP 429")]
        sitemaps += [_probe(p) for p in CONVENTIONAL[2:]]
        item = find(run("crawl-render-audit", _site(sitemaps)), "CR-NO-SITEMAP")
        self.assertIsNotNone(item)
        self.assertFalse(item.metrics["discoverability_established"])
        self.assertEqual(item.severity, "medium")
        self.assertEqual(item.metrics["unchecked"], 2)
        self.assertIn("that answered", item.title)
        self.assertIn("could not be checked", item.evidence)
        self.assertIn("could not be settled", item.interpretation)
        self.assertNotIn("falls back to following internal links", item.interpretation)
        for phrase in FORBIDDEN:
            self.assertNotIn(phrase, _text(item))

    def test_a_declared_sitemap_that_timed_out_is_unread_not_broken(self):
        sitemaps = [_probe("/sitemaps/catalog.xml", status=0, error="timed out after 8.0s",
                           source="robots.txt Sitemap directive")]
        sitemaps += [_probe(p) for p in CONVENTIONAL]
        findings = run("crawl-render-audit", _site(
            sitemaps, robots_raw=f"User-agent: *\nDisallow:\nSitemap: {ORIGIN}/sitemaps/catalog.xml\n"))
        broken = find(findings, "CR-SITEMAP-BROKEN")
        self.assertIsNotNone(broken)
        self.assertIn("could not be verified by this audit", broken.title)
        self.assertEqual(broken.severity, "low")
        self.assertLess(broken.confidence, 0.7)
        self.assertNotIn("missing", broken.title)
        self.assertEqual(broken.metrics["outcomes"], {"unchecked": 1})
        self.assertIsNone(find(findings, "CR-NO-SITEMAP"))

    def test_a_refused_declared_sitemap_names_the_refusal(self):
        sitemaps = [_probe("/sitemaps/catalog.xml", status=403, error="HTTP 403",
                           source="robots.txt Sitemap directive")]
        broken = find(run("crawl-render-audit", _site(
            sitemaps, robots_raw=f"User-agent: *\nDisallow:\nSitemap: {ORIGIN}/sitemaps/catalog.xml\n")),
            "CR-SITEMAP-BROKEN")
        self.assertIn("could not be verified (HTTP 403, refused or rate-limited)", broken.evidence)


class TestASitemapThisAuditDidNotProbe(unittest.TestCase):
    """The site's sitemap lives at a path nobody guessed and nobody declared."""

    def test_the_finding_never_claims_the_site_has_none(self):
        # Every conventional location is a genuine 404; /sitemaps/all.xml is
        # never probed. The finding may say what it probed and that nothing
        # is discoverable unaided - and nothing stronger.
        item = find(run("crawl-render-audit", _site([_probe(p) for p in CONVENTIONAL])),
                    "CR-NO-SITEMAP")
        self.assertIsNotNone(item)
        text = _text(item)
        for phrase in FORBIDDEN:
            self.assertNotIn(phrase, text, phrase)
        self.assertIn("path it does not probe", text)
        self.assertIn("if a sitemap already exists at another path",
                      " ".join(item.suggested_action.steps).lower())

    def test_an_unreadable_robots_txt_leaves_the_directive_unknown(self):
        data = _site([_probe(p) for p in CONVENTIONAL], robots_status=403)
        findings = run("crawl-render-audit", data)
        item = find(findings, "CR-NO-SITEMAP")
        self.assertIsNotNone(item)
        self.assertEqual(item.metrics["robots_directive"], "unknown")
        self.assertFalse(item.metrics["discoverability_established"])
        self.assertIn("could not be read", item.evidence)
        self.assertIsNone(find(findings, "CR-SITEMAP-UNDECLARED"))

    def test_a_missing_robots_txt_is_not_a_missing_directive(self):
        data = _site([_probe(p) for p in CONVENTIONAL], robots_status=404)
        findings = run("crawl-render-audit", data)
        item = find(findings, "CR-NO-SITEMAP")
        self.assertIsNotNone(item)
        self.assertEqual(item.metrics["robots_directive"], "robots_missing")
        self.assertFalse(item.metrics["discoverability_established"])
        self.assertIsNone(find(findings, "CR-SITEMAP-UNDECLARED"))


if __name__ == "__main__":
    unittest.main()
