"""Round-3 reliability regressions.

Each test in this file fails on the 1.8.9 build and passes after the fix it
names. They are grouped by the layer that owned the defect, and every one is a
property over a shape rather than a fact about a particular site: an SSRF guard
that has to hold for any private address, a decompression cap that has to hold
for any bomb, a wording rule that has to hold for any robots block.

Run just this file:

    python -m unittest tests.test_round3_hardening -v
"""

from __future__ import annotations

import gzip
import unittest
from urllib import error as urlerror
from urllib import request as urlrequest

import helpers
from helpers import ORIGIN, bundle, find, html_doc, page, run

from aiva import discover, recommend, report
from aiva.config import AuditConfig
from aiva.evidence import EvidenceStore
# Only stable symbols at module load, so this file imports against the
# pre-fix build too and each regression fails on its own terms rather than
# the whole module failing to import. The new helpers are imported inside the
# tests that need them.
from aiva.httpclient import _RecordingRedirectHandler, _decode_body, Response


def _resp(url: str, status: int = 200, body: str = "", error=None,
          headers=None) -> Response:
    return Response(requested_url=url, final_url=url, status=status,
                    body=body, body_bytes=len(body.encode()), error=error,
                    headers=headers or {}, content_type="text/html")


# ---------------------------------------------------------------------------
# D1 - a declared off-site anchor at a private address is never fetched
# ---------------------------------------------------------------------------

class TestAnchorSsrfGuard(unittest.TestCase):
    """`verify_anchors` used the raw client, walking past the private-host
    guard the rest of the crawl obeys. A `sameAs` to a metadata endpoint was
    fetched on exactly the kind of runner where it answers."""

    def _spy_store(self):
        config = AuditConfig(site="https://shop.example")
        store = EvidenceStore(config)
        calls = []
        real_fetch = store.client.fetch

        def spy(url, method="GET", **kw):
            calls.append(url)
            # robots.txt for the public host -> allow everything; anchor -> 200.
            return _resp(url, status=200, body="", headers={})

        store.client.fetch = spy  # type: ignore[assignment]
        return store, config, calls

    def test_private_anchor_is_not_fetched(self):
        store, config, calls = self._spy_store()
        for host in ("http://169.254.169.254/latest/meta-data/",
                     "http://127.0.0.1/", "http://10.0.0.5/", "http://[::1]/"):
            with self.subTest(host=host):
                calls.clear()
                anchor = {"url": host, "is_knowledge_host": False,
                          "sources": ["schema.org sameAs"], "declared_on": [ORIGIN + "/"]}
                results = discover.verify_anchors(store, [anchor], config)
                self.assertEqual(len(results), 1)
                self.assertFalse(results[0].get("checked"))
                self.assertNotIn(host, calls,
                                 "the private anchor host must never be requested")
                self.assertNotIn(True, [c.startswith("http://169.254")
                                        or "127.0.0.1" in c or "10.0.0.5" in c
                                        or "[::1]" in c for c in calls])

    def test_public_anchor_is_still_verified(self):
        store, config, calls = self._spy_store()
        anchor = {"url": "https://www.wikidata.org/wiki/Q42", "is_knowledge_host": True,
                  "sources": ["schema.org sameAs"], "declared_on": [ORIGIN + "/"]}
        results = discover.verify_anchors(store, [anchor], config)
        self.assertTrue(results[0].get("checked"))
        self.assertTrue(any("wikidata.org" in c for c in calls))


# ---------------------------------------------------------------------------
# D2 / D4 - redirect handler refuses non-web schemes and private hops, and a
#           redirect loop is a transport error, not a 3xx "answer"
# ---------------------------------------------------------------------------

class TestRedirectHandler(unittest.TestCase):
    def _req(self):
        return urlrequest.Request("https://shop.example/")

    def test_non_web_scheme_is_refused(self):
        h = _RecordingRedirectHandler()
        for target in ("ftp://10.0.0.5:22/", "file:///etc/passwd", "gopher://x/"):
            with self.subTest(target=target):
                with self.assertRaises(urlerror.URLError):
                    h.redirect_request(self._req(), None, 302, "Found", {}, target)

    def test_guard_refuses_private_hop(self):
        h = _RecordingRedirectHandler(
            guard=lambda u: "private" if "10.0.0" in u else None)
        with self.assertRaises(urlerror.URLError):
            h.redirect_request(self._req(), None, 302, "Found", {}, "http://10.0.0.5/x")

    def test_redirect_loop_raises_urlerror_not_httperror(self):
        h = _RecordingRedirectHandler()
        h.chain = [(301, f"https://shop.example/{i}") for i in range(6)]
        with self.assertRaises(urlerror.URLError) as ctx:
            h.redirect_request(self._req(), None, 301, "Moved", {},
                               "https://shop.example/7")
        # An HTTPError is a subclass of URLError, so the earlier build's
        # HTTPError would satisfy assertRaises(URLError). Assert it is *not*
        # an HTTPError, because an HTTPError carries a 3xx status the client
        # then recorded as an answered page.
        self.assertNotIsInstance(ctx.exception, urlerror.HTTPError)


# ---------------------------------------------------------------------------
# D3 - a bot wall is a fact about the audited origin, not its outbound links
# ---------------------------------------------------------------------------

class TestWallScopedToOrigin(unittest.TestCase):
    def test_external_anchor_refusals_do_not_manufacture_a_wall(self):
        config = AuditConfig(site="https://shop.example")
        store = EvidenceStore(config)
        # The site answered its own home page cleanly.
        store.responses["https://shop.example/"] = _resp("https://shop.example/", 200)
        # ...and declares a dozen sameAs anchors to one host that 403s them all.
        for i in range(12):
            u = f"https://blocked-cdn.test/asset-{i}"
            store.responses[u] = _resp(u, 403)
        access = discover.assess_access(store, "https://shop.example/")
        self.assertFalse(access["wall_suspected"],
                         "third-party 403s must not read as the site refusing this audit")
        self.assertEqual(access["refused_count"], 0)
        self.assertEqual(access["requests_observed"], 1)

    def test_real_origin_wall_is_still_detected(self):
        config = AuditConfig(site="https://shop.example")
        store = EvidenceStore(config)
        store.responses["https://shop.example/"] = _resp("https://shop.example/", 403)
        access = discover.assess_access(store, "https://shop.example/")
        self.assertTrue(access["wall_suspected"])
        self.assertTrue(access["home_refused"])


# ---------------------------------------------------------------------------
# D5 / D6 - gzip bodies decode; decompression is bounded against a bomb
# ---------------------------------------------------------------------------

class TestDecompression(unittest.TestCase):
    def test_gzip_body_without_content_encoding_is_decoded(self):
        xml = b'<?xml version="1.0"?><urlset><url><loc>https://x/a</loc></url></urlset>'
        text, _charset = _decode_body(gzip.compress(xml), {})  # no Content-Encoding
        self.assertIn("<urlset>", text)
        self.assertIn("https://x/a", text)

    def test_gzip_sitemap_parses_end_to_end(self):
        xml = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/'
               'sitemap/0.9"><url><loc>https://x/a</loc></url>'
               '<url><loc>https://x/b</loc></url></urlset>')
        text, _ = _decode_body(gzip.compress(xml.encode()), {})
        parsed = discover.parse_sitemap(text)
        self.assertEqual(parsed["kind"], "urlset")
        self.assertEqual(len(parsed["urls"]), 2)

    def test_decompression_is_bounded(self):
        from aiva.httpclient import _MAX_DECOMPRESSED_BYTES, _decompress_bounded
        bomb = gzip.compress(b"\0" * 40_000_000)   # ~40 MB -> tiny on the wire
        out = _decompress_bounded(bomb, gzip_stream=True)
        self.assertLessEqual(len(out), _MAX_DECOMPRESSED_BYTES)


# ---------------------------------------------------------------------------
# D7 - the AI-crawlers-blocked finding states an observation, not an outcome
# ---------------------------------------------------------------------------

class TestAiCrawlersWording(unittest.TestCase):
    ROBOTS = ("User-agent: GPTBot\nDisallow: /\n\n"
              "User-agent: ChatGPT-User\nDisallow: /\n")

    def _finding(self):
        data = bundle([page(ORIGIN + "/", html_doc(title="Shop"))], robots_raw=self.ROBOTS)
        return find(run("crawl-render-audit", data), "CR-AI-CRAWLERS-BLOCKED")

    def test_evidence_makes_no_absolute_answer_claim(self):
        item = self._finding()
        self.assertIsNotNone(item)
        low = item.evidence.lower()
        for banned in ("can never be the source", "never be the source of an answer"):
            self.assertNotIn(banned, low)

    def test_training_and_answer_time_agents_are_distinguished(self):
        item = self._finding()
        low = (item.evidence + " " + (item.interpretation or "")).lower()
        self.assertIn("live when a user's question", low)
        self.assertIn("index or training corpus", low)


# ---------------------------------------------------------------------------
# D8 - <meta robots content="none"> is a noindex
# ---------------------------------------------------------------------------

class TestNoindexNone(unittest.TestCase):
    def test_content_none_is_reported_as_noindex(self):
        url = ORIGIN + "/products/x"
        p = page(url, html_doc(canonical=url,
                               head='<meta name="robots" content="none">',
                               body="<h1>Widget</h1><p>&#8377;10 in stock</p>"
                                    "<table><tr><th>Size</th><td>M</td></tr></table>"))
        item = find(run("crawl-render-audit", bundle([p])), "CR-NOINDEX-ON-IMPORTANT-PAGES")
        self.assertIsNotNone(item, "content='none' must be treated as noindex")

    def test_is_noindexed_and_the_finding_agree(self):
        # Load the crawl specialist module to reach _is_noindexed.
        specialist = helpers.specialist("crawl-render-audit")
        url = ORIGIN + "/products/y"
        p = page(url, html_doc(canonical=url,
                               head='<meta name="robots" content="none">'))
        self.assertTrue(specialist._is_noindexed(p))


# ---------------------------------------------------------------------------
# D9 - a refused soft-404 probe is not a "success status"
# ---------------------------------------------------------------------------

class TestSoft404Refusals(unittest.TestCase):
    def _probe(self, status):
        return {"url": ORIGIN + "/nope", "checked": True, "status": status,
                "returns_404": False, "redirected_to_home": False,
                "final_url": ORIGIN + "/nope"}

    def test_refusal_statuses_do_not_fire_soft_404(self):
        for status in (401, 403, 407, 408, 429, 451, 500, 503):
            with self.subTest(status=status):
                data = bundle([], not_found=self._probe(status))
                self.assertIsNone(find(run("crawl-render-audit", data), "CR-SOFT-404"))

    def test_a_real_200_still_fires(self):
        data = bundle([], not_found=self._probe(200))
        self.assertIsNotNone(find(run("crawl-render-audit", data), "CR-SOFT-404"))


# ---------------------------------------------------------------------------
# D10 - a 5xx llms.txt probe is inconclusive, not evidence of absence
# ---------------------------------------------------------------------------

class TestAgentSurfaceRecommendation(unittest.TestCase):
    def _bundle(self, status):
        data = bundle([page(ORIGIN + "/", html_doc(title="Shop"))])
        data["well_known"]["ai_surfaces"] = {
            "llms_txt": {"url": ORIGIN + "/llms.txt", "checked": True,
                         "present": False, "status": status},
            "agents_md": {"url": ORIGIN + "/agents.md", "checked": True,
                          "present": False, "status": status},
        }
        return data

    def test_server_error_probe_does_not_recommend_publishing(self):
        for status in (500, 502, 504):
            with self.subTest(status=status):
                ids = [o["id"] for o in recommend.build_opportunities(self._bundle(status), [])]
                self.assertNotIn("OPP-AI-DISCOVERY-SURFACE", ids)

    def test_conclusive_404_still_recommends(self):
        ids = [o["id"] for o in recommend.build_opportunities(self._bundle(404), [])]
        self.assertIn("OPP-AI-DISCOVERY-SURFACE", ids)


# ---------------------------------------------------------------------------
# D12 - the count-reconciliation invariant covers every severity bucket
# ---------------------------------------------------------------------------

class TestPageBudgetCountsServedDocuments(unittest.TestCase):
    """A transport failure or a circuit-breaker skip returns a Response with an
    error and no document. Counting it against ``max_pages`` let a black-holed
    host drain the budget with fetches that parse nothing, under-sampling the
    site and making it read as thin."""

    def _store(self, outcome):
        config = AuditConfig(site="https://shop.example", allow_private_hosts=True)
        store = EvidenceStore(config)
        store.robots = store.robots  # allow_all by default in the store
        store.client.fetch = lambda url, method="GET", **kw: outcome(url)  # type: ignore
        return store

    def test_a_timed_out_fetch_does_not_spend_a_page_slot(self):
        store = self._store(lambda url: _resp(url, status=0,
                                              error="URLError: <urlopen error timed out>"))
        before = store.html_fetch_count
        store.fetch("https://shop.example/a", count_as_page=True)
        self.assertEqual(store.html_fetch_count, before,
                         "a transport failure is not a fetched page")

    def test_a_served_document_still_spends_a_slot(self):
        store = self._store(lambda url: _resp(url, status=200, body="<html></html>"))
        before = store.html_fetch_count
        store.fetch("https://shop.example/a", count_as_page=True)
        self.assertEqual(store.html_fetch_count, before + 1)


class TestValidatorReconcilesAllBuckets(unittest.TestCase):
    def test_low_and_info_are_reconciled(self):
        rep = {
            "site": "shop.example", "audited_at": "2026-01-01T00:00:00Z",
            "summary": {"total_findings": 1, "critical": 0, "high": 0,
                        "medium": 0, "low": 0, "info": 0},
            "findings": [{"id": "F-001", "title": "x", "severity": "low",
                          "evidence": "e",
                          "suggested_action": {"summary": "s", "priority": "low"}}],
        }
        errors = report.validate_report(rep)
        self.assertTrue(any("low" in e or "sum of severity buckets" in e for e in errors),
                        "a low-severity finding counted in the total but not in the "
                        "low bucket must be flagged")


if __name__ == "__main__":
    unittest.main()
