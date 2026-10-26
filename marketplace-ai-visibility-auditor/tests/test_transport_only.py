"""What a report may say when it was refused before it read anything.

A live audit of a storefront behind bot mitigation came back with 39 requests,
zero pages, and three findings: the barrier, correctly described - then "pages
the site itself advertises return HTTP errors", citing the home page the wall
had refused, and "no robots.txt is published", from a 403. One obstacle, three
findings, two of them claims about a site nobody had read.

The distinctions this suite holds:

1. an observed fact (this agent received HTTP 403) is not an inference (other
   agents receive it too);
2. a refusal is not an absence - 403 on /robots.txt says the request was
   turned away, not that the file is missing;
3. a recommendation resting on an inference is framed as conditional;
4. one barrier is one finding, not one per rule that trips over it;
5. a run that read no page emits no claim about content, and the pillars it
   could not measure score `None` rather than zero.

The fixtures are synthetic hosts; nothing here knows the name of any real
site, and the assertions are about the report's language and structure.
"""

from __future__ import annotations

import unittest

from helpers import bundle, page, html_doc, response, run, find, rule_ids
from aiva.config import AuditConfig
from aiva.discover import assess_access
from aiva import report as report_mod
from aiva.report import build_report

WALLED = "https://www.thornbury-outfitters.example"
OPEN_SITE = "https://www.laxton-supply.example"


class _FakeStore:
    """What `assess_access` reads: the responses and the config."""

    def __init__(self, responses, config):
        self.responses = responses
        self.config = config


def walled_bundle(origin: str = WALLED, *, status: int = 403,
                  body: str = "<html><body>Access Denied</body></html>") -> dict:
    """Every request answered by the edge, no page served."""
    config = AuditConfig(site=origin)
    urls = [origin + path for path in ("/robots.txt", "/", "/llms.txt", "/agents.md",
                                       "/sitemap.xml", "/sitemap_index.xml")]
    responses = {url: response(url, body, status=status) for url in urls}
    data = bundle([], origin=origin, robots_status=status, robots_raw="")
    data["access"] = assess_access(_FakeStore(responses, config), origin + "/")
    data["sitemaps"] = []
    data["pages"] = [{
        "url": origin + "/", "final_url": origin + "/", "status": status,
        "content_type": "text/html", "bytes": 0, "elapsed_ms": 10, "redirects": [],
        "headers": {}, "fetch_failed": True, "page_type": "error",
        "fetch_reason": "home page (site root)",
    }]
    return data


SKILLS = ("crawl-render-audit", "machine-readability-audit", "freshness-corroboration",
          "entity-audit", "engagement-audit", "answerability-audit")


def full_report(data: dict, origin: str = WALLED) -> dict:
    findings, runs = [], []
    for skill in SKILLS:
        got = run(skill, data)
        runs.append({"skill": skill, "findings": len(got), "status": "ok"})
        findings += got
    return build_report(data, findings, AuditConfig(site=origin), skill_runs=runs)


# ---------------------------------------------------------------------------
# 1. one barrier, one finding
# ---------------------------------------------------------------------------

class TestOneBarrierIsOneFinding(unittest.TestCase):

    def setUp(self):
        self.report = full_report(walled_bundle())
        self.rules = [f["rule_id"] for f in self.report["findings"]]

    def test_the_barrier_is_reported(self):
        self.assertIn("CR-BOT-WALL", self.rules)

    def test_the_same_refusal_is_not_also_a_broken_url_finding(self):
        """The home page the wall refused is not a URL the site advertised."""
        self.assertNotIn("CR-HTTP-ERRORS", self.rules)

    def test_the_same_refusal_is_not_also_a_missing_robots_finding(self):
        self.assertNotIn("CR-ROBOTS-MISSING", self.rules)

    def test_the_barrier_is_reported_exactly_once(self):
        self.assertEqual(self.rules.count("CR-BOT-WALL"), 1)
        self.assertEqual(len(self.rules), 1,
                         f"one obstacle produced {len(self.rules)} findings: {self.rules}")

    def test_the_score_is_not_penalised_once_per_rule_that_tripped(self):
        """Duplicates do not just read badly, they move the number.

        Three findings against one pillar scored the site as though it had
        three separate defects. The pillar is entitled to reflect the barrier
        once.
        """
        pillars = self.report["scores"]["pillars"]
        self.assertEqual(pillars["crawl_render"]["findings"], 1)


# ---------------------------------------------------------------------------
# 2. a refusal is not an absence
# ---------------------------------------------------------------------------

class TestARefusalIsNotAnAbsence(unittest.TestCase):
    """403 on /robots.txt says the request was refused. Nothing more.

    A browser, or a crawler the edge allowlists, may be served the file
    normally. "No robots.txt is published" is a claim about the site's
    configuration, and a refused request is not evidence for it.
    """

    def _rules(self, status: int) -> list:
        data = walled_bundle(status=status)
        return rule_ids(run("crawl-render-audit", data))

    def test_a_refused_robots_txt_is_not_reported_as_missing(self):
        for status in (401, 403, 429, 451):
            with self.subTest(status=status):
                self.assertNotIn("CR-ROBOTS-MISSING", self._rules(status))

    def test_a_genuinely_absent_robots_txt_is_still_reported(self):
        """404 is the status for a file that is not there, and only 404.

        The rule has to survive: a site with no robots.txt gets no sitemap
        discovery and no way to say assistant crawlers are welcome, and that
        is worth reporting.
        """
        home = page(OPEN_SITE + "/", html_doc(
            title="Laxton Supply", canonical=OPEN_SITE + "/",
            body="<h1>Laxton Supply</h1><a href='/about.html'>About</a>"))
        data = bundle([home], origin=OPEN_SITE, robots_status=404, robots_raw="")
        found = find(run("crawl-render-audit", data), "CR-ROBOTS-MISSING")
        self.assertIsNotNone(found, "a real 404 must still be reported")
        self.assertNotIn("no robots.txt exists", found.evidence.lower())

    def test_the_missing_finding_never_says_a_403_proves_absence(self):
        home = page(OPEN_SITE + "/", html_doc(title="Laxton Supply",
                                              canonical=OPEN_SITE + "/"))
        data = bundle([home], origin=OPEN_SITE, robots_status=404, robots_raw="")
        found = find(run("crawl-render-audit", data), "CR-ROBOTS-MISSING")
        self.assertIn("404", found.evidence)


# ---------------------------------------------------------------------------
# 3. observed vs inferred, and conditional recommendations
# ---------------------------------------------------------------------------

class TestObservedAndInferredAreSeparated(unittest.TestCase):
    """The auditor observed its own refusal. It did not test any other agent.

    Impersonating GPTBot to find out is refused by the tool on principle, so
    the disposition of assistant crawlers is genuinely unknown to this audit -
    and a finding that reads as though it were measured invites a site owner
    to change an edge configuration on evidence nobody has.
    """

    def setUp(self):
        self.finding = find(run("crawl-render-audit", walled_bundle()), "CR-BOT-WALL")
        self.assertIsNotNone(self.finding)

    def test_the_evidence_states_only_what_was_observed(self):
        evidence = self.finding.evidence.lower()
        self.assertIn("403", evidence)
        for agent in ("gptbot", "claudebot", "perplexitybot"):
            self.assertNotIn(agent, evidence,
                             "the evidence sentence must not name an agent the audit "
                             "never sent")

    def test_the_inference_is_carried_as_an_interpretation(self):
        interpretation = self.finding.interpretation.lower()
        self.assertTrue(interpretation, "the risk must be stated somewhere")
        self.assertIn("did not send", interpretation)
        self.assertTrue(any(word in interpretation
                            for word in ("no evidence", "cannot see", "unknown")),
                        interpretation)

    def test_the_recommendation_checks_before_it_changes_anything(self):
        """The first step is reading the logs, not allowlisting."""
        steps = self.finding.suggested_action.steps
        self.assertTrue(steps)
        self.assertIn("log", steps[0].lower())

    def test_the_allowlist_step_is_conditional(self):
        blob = " ".join(self.finding.suggested_action.steps).lower()
        self.assertIn("if they are being refused", blob)

    def test_the_mechanism_does_not_assert_the_unmeasured_half(self):
        """"They are refused on the same basis" was stated as a mechanism, and
        a mechanism reads as a fact."""
        mechanism = self.finding.suggested_action.mechanism.lower()
        self.assertTrue(any(word in mechanism for word in ("if ", "whether", "depends")),
                        mechanism)


# ---------------------------------------------------------------------------
# 4. a report that read nothing claims nothing about content
# ---------------------------------------------------------------------------

class TestTransportOnlyMakesNoContentClaim(unittest.TestCase):

    def setUp(self):
        self.report = full_report(walled_bundle())

    def test_the_state_is_declared(self):
        self.assertEqual(self.report["summary"]["coverage_state"], "transport_only")

    def test_the_headline_says_no_claim_is_made_about_content(self):
        headline = self.report["summary"]["headline"].lower()
        self.assertIn("403", headline)
        self.assertIn("content", headline)

    def test_no_content_specialist_produced_a_finding(self):
        for skill in SKILLS[1:]:
            with self.subTest(skill=skill):
                self.assertEqual(run(skill, walled_bundle()), [])

    def test_the_pillars_that_were_not_measured_score_none_not_zero(self):
        """Zero is a measurement. None is the absence of one, and the
        difference is the whole point of the state."""
        pillars = self.report["scores"]["pillars"]
        for name in ("machine_readability", "freshness_corroboration", "entity",
                     "engagement", "answerability"):
            with self.subTest(pillar=name):
                self.assertIsNone(pillars[name]["score"])

    def test_no_finding_describes_the_site_html(self):
        for item in self.report["findings"]:
            with self.subTest(rule=item["rule_id"]):
                self.assertEqual(item["pillar"], "crawl_render")


# ---------------------------------------------------------------------------
# 5. the rules that were suppressed still work when they are earned
# ---------------------------------------------------------------------------

class TestSuppressionIsNarrow(unittest.TestCase):
    """Every filter above can silence a real defect if it is drawn too wide.

    These are the paired positives: the same rules, on a site that served its
    pages, still reporting what they are for.
    """

    def _site(self, extra_pages=(), sitemap_urls=()):
        home = page(OPEN_SITE + "/", html_doc(
            title="Laxton Supply", canonical=OPEN_SITE + "/",
            body="<h1>Laxton Supply</h1>"
                 "<a href='/products/clamp-40'>Clamp 40</a>"
                 "<a href='/pages/about.html'>About</a>"))
        sitemaps = [{
            "url": OPEN_SITE + "/sitemap.xml", "source": "robots.txt Sitemap directive",
            "status": 200, "kind": "urlset", "error": None,
            "url_count": len(sitemap_urls), "child_count": 0, "lastmods": [],
            "sample_urls": list(sitemap_urls)[:2],
            "entries": [{"url": u, "lastmod": None} for u in sitemap_urls],
        }] if sitemap_urls else []
        return bundle([home] + list(extra_pages), origin=OPEN_SITE, sitemaps=sitemaps)

    def test_a_sitemap_url_that_404s_is_still_reported(self):
        dead = {"url": OPEN_SITE + "/products/retired-clamp", "final_url": "",
                "status": 404, "content_type": "text/html", "bytes": 0,
                "elapsed_ms": 10, "redirects": [], "headers": {},
                "fetch_failed": True, "page_type": "error",
                "fetch_reason": "listed in " + OPEN_SITE + "/sitemap.xml"}
        data = self._site([dead], sitemap_urls=[OPEN_SITE + "/",
                                                OPEN_SITE + "/products/retired-clamp"])
        found = find(run("crawl-render-audit", data), "CR-HTTP-ERRORS")
        self.assertIsNotNone(found, "a dead sitemap URL is exactly what this rule is for")
        self.assertIn(OPEN_SITE + "/products/retired-clamp", found.affected_urls)

    def test_a_linked_url_that_404s_is_still_reported(self):
        dead = {"url": OPEN_SITE + "/products/clamp-40", "final_url": "",
                "status": 404, "content_type": "text/html", "bytes": 0,
                "elapsed_ms": 10, "redirects": [], "headers": {},
                "fetch_failed": True, "page_type": "error",
                "fetch_reason": "linked from the home page"}
        found = find(run("crawl-render-audit", self._site([dead])), "CR-HTTP-ERRORS")
        self.assertIsNotNone(found)

    def test_a_url_the_audit_chose_itself_is_not_called_advertised(self):
        """The probe URLs and the root are the auditor's choices, not the
        site's claims, and the finding's own sentence says "advertises"."""
        probe = {"url": OPEN_SITE + "/aiva-probe-abc123", "final_url": "",
                 "status": 404, "content_type": "text/html", "bytes": 0,
                 "elapsed_ms": 10, "redirects": [], "headers": {},
                 "fetch_failed": True, "page_type": "error",
                 "fetch_reason": "soft-404 probe"}
        self.assertIsNone(find(run("crawl-render-audit", self._site([probe])),
                               "CR-HTTP-ERRORS"))

    def test_a_403_without_a_wall_is_not_verified_rather_than_broken(self):
        """A refusal says nothing about the page. One refused URL among many
        served ones is recorded as "could not be verified" at informational
        severity, under its own heading, never as an advertised URL that is
        not there - the 404 rule is keyed to the origin's answer for the
        resource, not to "status >= 400"."""
        refused = {"url": OPEN_SITE + "/products/clamp-40", "final_url": "",
                   "status": 403, "content_type": "text/html", "bytes": 0,
                   "elapsed_ms": 10, "redirects": [], "headers": {},
                   "fetch_failed": True, "page_type": "error",
                   "fetch_reason": "linked from the home page"}
        data = self._site([refused])
        self.assertFalse((data.get("access") or {}).get("wall_suspected"))
        findings = run("crawl-render-audit", data)
        self.assertIsNone(find(findings, "CR-HTTP-ERRORS"))
        aside = find(findings, "CR-URLS-NOT-VERIFIED")
        self.assertIsNotNone(aside)
        self.assertEqual(aside.severity, "info")
        self.assertIn("could not be verified", aside.title)
        self.assertIn("refused or rate-limited", aside.evidence)
        self.assertIn(OPEN_SITE + "/products/clamp-40", aside.affected_urls)

    def test_timeouts_and_server_errors_are_not_verified_either(self):
        """5xx and timeouts are the path failing, not the resource answering."""
        flaky = {"url": OPEN_SITE + "/products/clamp-40", "final_url": "",
                 "status": 503, "content_type": "text/html", "bytes": 0,
                 "elapsed_ms": 10, "redirects": [], "headers": {},
                 "fetch_failed": True, "page_type": "error",
                 "fetch_reason": "linked from the home page"}
        data = self._site([flaky])
        data["fetch_errors"] = [{"url": OPEN_SITE + "/pages/about.html",
                                 "error": "TimeoutError: timed out",
                                 "reason": "linked from the home page"}]
        findings = run("crawl-render-audit", data)
        self.assertIsNone(find(findings, "CR-HTTP-ERRORS"))
        aside = find(findings, "CR-URLS-NOT-VERIFIED")
        self.assertIsNotNone(aside)
        self.assertEqual(aside.metrics["unverified"], 2)
        self.assertIn("the request timed out", aside.evidence)
        self.assertIn("server or gateway error", aside.evidence)
        self.assertNotIn("broken", aside.title)

    def test_a_404_and_a_403_on_one_site_are_kept_apart(self):
        dead = {"url": OPEN_SITE + "/products/clamp-40", "final_url": "",
                "status": 404, "content_type": "text/html", "bytes": 0,
                "elapsed_ms": 10, "redirects": [], "headers": {},
                "fetch_failed": True, "page_type": "error",
                "fetch_reason": "linked from the home page"}
        refused = {"url": OPEN_SITE + "/pages/about.html", "final_url": "",
                   "status": 429, "content_type": "text/html", "bytes": 0,
                   "elapsed_ms": 10, "redirects": [], "headers": {},
                   "fetch_failed": True, "page_type": "error",
                   "fetch_reason": "linked from the home page"}
        findings = run("crawl-render-audit", self._site([dead, refused]))
        broken = find(findings, "CR-HTTP-ERRORS")
        aside = find(findings, "CR-URLS-NOT-VERIFIED")
        self.assertEqual(broken.affected_urls, [OPEN_SITE + "/products/clamp-40"])
        self.assertEqual(aside.affected_urls, [OPEN_SITE + "/pages/about.html"])
        self.assertIn("does not exist", broken.evidence)


# ---------------------------------------------------------------------------
# 6. bounded, explained failure
# ---------------------------------------------------------------------------

class TestFailureIsBoundedAndExplained(unittest.TestCase):
    """Two zero-page audits can differ by minutes, and that is the finding.

    One origin answered every request quickly and refused; the other never
    answered at all. Both produce `pages_fetched: 0`, and until the time was
    accounted for they were indistinguishable in the report - a run that spent
    four minutes discovering nothing looked exactly like one that spent
    fifteen seconds.
    """

    def test_a_host_that_never_answers_is_stopped_after_three_failures(self):
        """The bound. Without it, one dead origin costs one timeout per queued
        URL and spends the entire wall-clock budget learning the same fact."""
        from aiva.httpclient import HttpClient
        client = HttpClient(timeout=0.05, delay=0.1, max_retries=0)
        host = "https://192.0.2.1"          # TEST-NET-1: guaranteed unroutable
        attempted = 0
        for index in range(8):
            response = client.fetch(f"{host}/page-{index}")
            self.assertTrue(response.error)
            if "not attempted" not in (response.error or ""):
                attempted += 1
        self.assertEqual(attempted, client.CIRCUIT_THRESHOLD,
                         "the client kept asking a host that had stopped answering")
        self.assertTrue(client.open_circuits)
        self.assertEqual(client.skipped_by_circuit, 8 - client.CIRCUIT_THRESHOLD)

    def test_a_host_that_answers_again_is_not_penalised(self):
        """The counter is consecutive, not cumulative: a blip must not shut a
        working host out of the rest of the crawl."""
        from aiva.httpclient import HttpClient
        client = HttpClient(timeout=0.05, delay=0.0, max_retries=0)
        client._record_failure("example.test")
        client._record_failure("example.test")
        client._record_success("example.test")
        client._record_failure("example.test")
        self.assertEqual(client.open_circuits, {})

    def test_an_answered_refusal_costs_nothing_like_a_timeout(self):
        """Why the two zero-page runs differ, stated as the accounting does."""
        from aiva.httpclient import HttpClient
        client = HttpClient()
        self.assertIn("answered", client.time_by_outcome)
        self.assertIn("transport_failure", client.time_by_outcome)
        self.assertIn("throttle", client.time_by_outcome)

    def test_the_report_says_where_the_time_went(self):
        data = walled_bundle()
        data["stats"] = {
            "requests": 14, "elapsed_s": 15.5,
            "transport": {
                "time_by_outcome_s": {"refused_or_error_status": 1.2, "throttle": 13.9},
                "transport_failures": 0, "retries_spent": 0,
                "requests_not_attempted": 0, "hosts_stopped_early": {},
                "request_timeout_s": 12.0, "max_retries": 1,
            },
        }
        report = full_report(data)
        transport = report["coverage"]["transport"]
        self.assertEqual(transport["time_by_outcome_s"]["throttle"], 13.9)
        markdown = report_mod.render_markdown(report)
        self.assertIn("Requests: 14 in 15.5s", markdown)

    def test_a_run_stopped_early_names_the_host_and_the_reason(self):
        data = walled_bundle()
        data["stats"] = {
            "requests": 3, "elapsed_s": 74.0,
            "transport": {
                "time_by_outcome_s": {"transport_failure": 72.0},
                "transport_failures": 3, "retries_spent": 0,
                "requests_not_attempted": 11,
                "hosts_stopped_early": {
                    "www.thornbury-outfitters.example":
                        "3 consecutive transport failures; no further requests "
                        "were made to this host"},
                "request_timeout_s": 12.0, "max_retries": 1,
            },
        }
        markdown = report_mod.render_markdown(full_report(data))
        self.assertIn("Stopped requesting www.thornbury-outfitters.example", markdown)
        self.assertIn("Requests not attempted after that: 11", markdown)

    def test_no_single_request_may_outlive_the_declared_budget(self):
        """The budget guard runs before a fetch, so without a cap a request
        begun with four seconds left could still spend the full timeout."""
        from aiva.config import AuditConfig
        from aiva.evidence import EvidenceStore
        store = EvidenceStore(AuditConfig(site=WALLED, total_time_budget_s=240.0,
                                          timeout_s=12.0))
        store.started_at -= 232.0                      # eight seconds remain
        captured = {}

        def fake_fetch(url, method="GET", timeout=None):
            captured["timeout"] = timeout
            from aiva.httpclient import Response
            return Response(requested_url=url, method=method, final_url=url,
                            status=200, body="", content_type="text/html")

        store.client.fetch = fake_fetch
        store.fetch(WALLED + "/robots.txt", reason="test")
        self.assertLessEqual(captured["timeout"], 8.1)


if __name__ == "__main__":
    unittest.main()
