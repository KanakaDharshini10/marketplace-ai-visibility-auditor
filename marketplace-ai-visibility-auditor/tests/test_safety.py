"""Guardrail tests: the marketplace must be structurally unable to misbehave.

These are the checks that back the "recommend-only, read-only, robots-respecting"
claim in the manifest. They are deliberately blunt: if any of them starts
failing, the submission has stopped being safe.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path

import helpers
from aiva import discover, httpclient, localserve, orchestrator
from aiva.config import AuditConfig
from aiva.evidence import EvidenceStore
from aiva.version import ROBOTS_UA_TOKEN, USER_AGENT

FIXTURES = helpers.ROOT / "tests" / "fixtures"


def directory_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class TestReadOnly(unittest.TestCase):
    def test_only_get_and_head_are_reachable(self):
        self.assertEqual(httpclient.HttpClient.SAFE_METHODS, ("GET", "HEAD"))

    def test_unsafe_methods_are_refused(self):
        client = httpclient.HttpClient()
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.assertRaises(ValueError):
                client.fetch("https://shop.example/", method=method)

    def test_no_credentials_are_ever_sent(self):
        """Checked against the parsed AST, so prose in docstrings cannot hide a real call."""
        tree = ast.parse(inspect.getsource(httpclient))
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for forbidden in ("HTTPBasicAuthHandler", "HTTPCookieProcessor",
                          "HTTPDigestAuthHandler", "HTTPPasswordMgrWithDefaultRealm",
                          "ProxyBasicAuthHandler", "CookieJar"):
            self.assertNotIn(forbidden, names,
                             f"httpclient must never use {forbidden}")
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        for header in ("Authorization", "Cookie", "Set-Cookie", "Proxy-Authorization"):
            self.assertNotIn(header, literals,
                             f"httpclient must never set the {header} header")

    def test_user_agent_is_honest(self):
        self.assertIn("MarketplaceAIVisibilityAuditor", USER_AGENT)
        for spoofed in ("Mozilla", "Chrome", "Safari", "Googlebot", "GPTBot"):
            self.assertNotIn(spoofed, USER_AGENT)

    def test_auditing_does_not_modify_the_target(self):
        before = directory_digest(FIXTURES / "site_weak")
        server, base = localserve.start(FIXTURES / "site_weak", soft_404=True)
        try:
            orchestrator.run_audit(AuditConfig(site=base, request_delay_s=0.1,
                                               check_external=False))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(directory_digest(FIXTURES / "site_weak"), before)


class TestConfigGuards(unittest.TestCase):
    def test_robots_compliance_cannot_be_switched_off(self):
        config = AuditConfig(site="https://shop.example", respect_robots=False)
        self.assertTrue(any("robots" in error for error in config.validate()))
        with self.assertRaises(ValueError):
            discover.collect(config)

    def test_rate_abuse_guards(self):
        self.assertTrue(AuditConfig(site="https://x.example",
                                    request_delay_s=0.0).validate())
        self.assertTrue(AuditConfig(site="https://x.example", max_pages=5000).validate())
        self.assertTrue(AuditConfig(site="https://x.example",
                                    total_time_budget_s=99999).validate())

    def test_site_is_required(self):
        self.assertTrue(AuditConfig().validate())

    def test_default_config_is_valid(self):
        self.assertEqual(AuditConfig(site="https://shop.example").validate(), [])


class TestRobotsCompliance(unittest.TestCase):
    def _serve_blocking_site(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "robots.txt").write_text(
            "User-agent: *\nDisallow: /\n", encoding="utf-8")
        (root / "index.html").write_text(
            "<!doctype html><title>Blocked</title><h1>Blocked</h1>", encoding="utf-8")
        (root / "secret.html").write_text(
            "<!doctype html><title>Secret</title><h1>Secret</h1>", encoding="utf-8")
        return tmp, root

    def test_a_site_that_disallows_us_is_not_crawled(self):
        tmp, root = self._serve_blocking_site()
        server, base = localserve.start(root)
        try:
            bundle, report = orchestrator.run_audit(
                AuditConfig(site=base, request_delay_s=0.1, check_external=False))
        finally:
            server.shutdown()
            server.server_close()
            tmp.cleanup()
        parsed = [p for p in bundle["pages"] if not p.get("fetch_failed")]
        self.assertEqual(parsed, [], "robots Disallow: / must stop the crawl")
        self.assertTrue(bundle["blocked_by_robots"])
        # ...and the audit still returns a usable, schema-valid report.
        self.assertIn("summary", report)
        self.assertTrue(report["diagnostics"]["blocked_by_robots"])

    def test_store_refuses_disallowed_urls(self):
        config = AuditConfig(site="https://shop.example", request_delay_s=0.1)
        store = EvidenceStore(config)
        from aiva.robots import RobotsTxt
        store.robots = RobotsTxt.from_response(
            "https://shop.example/robots.txt", 200,
            f"User-agent: {ROBOTS_UA_TOKEN}\nDisallow: /private\n")
        self.assertFalse(store.allowed("https://shop.example/private/x"))
        self.assertIsNone(store.fetch("https://shop.example/private/x", reason="test"))
        self.assertTrue(store.blocked_by_robots)
        self.assertEqual(store.client.request_count, 0)

    def test_crawl_delay_is_honoured(self):
        config = AuditConfig(site="https://shop.example", request_delay_s=0.4)
        store = EvidenceStore(config)
        from aiva.robots import RobotsTxt
        store.robots = RobotsTxt.from_response(
            "https://shop.example/robots.txt", 200,
            "User-agent: *\nCrawl-delay: 2\nDisallow:\n")
        delay = store.robots.crawl_delay_for(ROBOTS_UA_TOKEN)
        self.assertEqual(delay, 2.0)


class TestSpecialistIsolation(unittest.TestCase):
    NETWORK_MODULES = {
        "urllib", "urllib.request", "urllib.error", "http", "http.client",
        "socket", "ssl", "ftplib", "smtplib", "telnetlib", "asyncio",
        "requests", "httpx", "aiohttp", "selenium", "playwright",
        "aiva.httpclient", "aiva.discover", "aiva.evidence.EvidenceStore",
    }

    def test_specialists_perform_no_network_io(self):
        """A specialist that could fetch could not be trusted to reuse shared evidence.

        Verified structurally against each module's import graph rather than by
        grepping prose, so a docstring mentioning "network" cannot trip it and a
        real import cannot hide behind one.
        """
        for skill_id, module in orchestrator.load_specialists():
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
                    imported.update(f"{node.module}.{alias.name}" for alias in node.names)
            offending = imported & self.NETWORK_MODULES
            self.assertEqual(offending, set(),
                             f"{skill_id} imports network capability: {offending}")

    def test_specialists_do_not_mutate_the_bundle(self):
        from helpers import bundle, html_doc, page
        import copy
        data = bundle([page(helpers.ORIGIN + "/", html_doc(body="<h1>H</h1>"))])
        snapshot = copy.deepcopy(data)
        for skill_id, module in orchestrator.load_specialists():
            module.analyze(data)
        self.assertEqual(data, snapshot, "a specialist mutated the shared evidence")

    def test_a_failing_specialist_does_not_take_down_the_report(self):
        from helpers import bundle

        class Exploding:
            @staticmethod
            def analyze(_bundle):
                raise RuntimeError("boom")

        real = orchestrator.load_specialists()
        findings, runs = orchestrator.run_specialists(bundle([]))
        self.assertEqual(len(runs), len(real))
        # simulate one failure directly through the isolation wrapper
        import types
        module = types.ModuleType("exploding")
        module.analyze = Exploding.analyze
        original = orchestrator.load_specialists
        try:
            orchestrator.load_specialists = lambda *a, **k: [("exploding", module)]
            findings, runs = orchestrator.run_specialists(bundle([]))
        finally:
            orchestrator.load_specialists = original
        self.assertEqual(findings, [])
        self.assertFalse(runs[0]["ok"])
        self.assertIn("boom", runs[0]["error"])


if __name__ == "__main__":
    unittest.main()
