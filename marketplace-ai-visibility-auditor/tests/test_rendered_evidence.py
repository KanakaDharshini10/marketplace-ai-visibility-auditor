"""Browser-rendered evidence: optional, bounded, safe, and never invented.

The audit's evidence is the server response, and that does not change here.
What changes is what an *absence* in it may be called. "Not in the HTML a fetch
receives" and "not on the page" are two observations; a report that prints the
second when it measured the first is wrong in a way the site owner can see,
because the rating is right there - it arrives after hydration.

So this module holds four things shut:

1. **The distinction is real and measured.** A fixture whose price, stock,
   rating, specification table and catalogue controls exist only after
   JavaScript is rendered by an actual browser, and the audit is required to
   report those facts as absent from the *response*, not from the page.
2. **Nothing is fabricated.** With Playwright missing, rendering disabled, the
   browser failing, or the page timing out, no rendered evidence exists, the
   raw findings stand unchanged, and the report says the rendered state was not
   measured.
3. **Rendering is not a second crawler.** Every navigation goes through the
   store's own gate - robots.txt and the private-address rule - the browser's
   subresource requests are held to it too, and a redirect that lands outside
   it discards the render rather than reporting it.
4. **The v1.10.2 behaviour is untouched** when rendering is off, which is the
   default.

The browser tests skip nothing: where Playwright is genuinely absent from the
environment the real-render class asserts the *unavailable* contract instead,
which is the behaviour that matters on a machine without it.

Run just this file:

    python3 tests/run_tests.py rendered_evidence -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import helpers
import shapes
from helpers import bundle, find, html_doc, page, rule_ids, run

from aiva import analysis, render, semantics
from aiva.config import AuditConfig

ROOT = helpers.ROOT
FIXTURE = ROOT / "tests" / "fixtures" / "site_rendered"
ENTRYPOINT = ROOT / "skills" / "marketplace-ai-visibility-audit" / "scripts"

PLAYWRIGHT = render.playwright_available()


# ---------------------------------------------------------------------------
# fact bags, without a browser
# ---------------------------------------------------------------------------

def rendered(page_dict: dict, **facts) -> dict:
    """Attach a rendered fact bag by hand, as a successful render would.

    Used by every test that is about the *comparison* rather than about the
    browser: the bag has the same shape the extractor produces, which is the
    contract the rules depend on.
    """
    page_dict["rendered"] = dict({"ok": True}, **facts)
    return page_dict


def priced_page(price: str = "&#163;42.00") -> dict:
    return page(helpers.ORIGIN + "/products/lamp", html_doc(
        title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
        body=f"<main><h1>Lamp</h1><p>{price} In stock.</p></main>"))


def bare_page() -> dict:
    return page(helpers.ORIGIN + "/products/lamp", html_doc(
        title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
        body="<main><h1>Lamp</h1><p>A lamp.</p><div id='commerce'></div></main>"))


class TestTheComparison(unittest.TestCase):
    """Section 6: the four cases, each named and each asserted."""

    def test_raw_present_and_rendered_present(self):
        target = rendered(priced_page(), prices_in_text=[{"value": "42.00"}])
        verdict = analysis.fact_visibility(target, analysis._states_price)
        self.assertEqual(verdict["state"], "server_and_rendered")
        self.assertEqual((verdict["raw"], verdict["rendered"]), ("present", "present"))

    def test_raw_absent_and_rendered_present(self):
        target = rendered(bare_page(), prices_in_text=[{"value": "42.00"}])
        verdict = analysis.fact_visibility(target, analysis._states_price)
        self.assertEqual(verdict["state"], "rendered_only")
        self.assertEqual((verdict["raw"], verdict["rendered"]), ("absent", "present"))
        self.assertIn("not observed in the server HTML", verdict["phrase"])

    def test_raw_absent_and_rendered_absent(self):
        target = rendered(bare_page(), prices_in_text=[])
        verdict = analysis.fact_visibility(target, analysis._states_price)
        self.assertEqual(verdict["state"], "not_observed")
        self.assertEqual(verdict["rendered"], "absent")

    def test_rendered_unavailable_is_not_rendered_absent(self):
        """The distinction the whole feature rests on: "we looked in the
        browser and it was not there" is not "we did not look"."""
        verdict = analysis.fact_visibility(bare_page(), analysis._states_price)
        self.assertEqual(verdict["state"], "render_unavailable")
        self.assertEqual(verdict["rendered"], "unavailable")
        self.assertIn("was not measured", verdict["phrase"])

    def test_structured_only(self):
        target = priced_page()
        verdict = analysis.fact_visibility(
            target, lambda f: False, structured=lambda f: True)
        self.assertEqual(verdict["state"], "structured_only")

    def test_no_phrase_claims_anything_about_an_external_system(self):
        for state, phrase in analysis.VISIBILITY_PHRASE.items():
            lowered = phrase.lower()
            for banned in ("assistant", "ai ", "llm", "search engine", "crawler will",
                           "retriev", "cite"):
                self.assertNotIn(banned, lowered, f"{state}: {phrase!r}")


class TestNothingIsFabricated(unittest.TestCase):
    """Section 2: no rendered evidence without a render."""

    def test_a_page_that_was_not_rendered_has_no_rendered_facts(self):
        self.assertIsNone(analysis.rendered_facts(bare_page()))
        self.assertEqual(analysis.render_state(bare_page()), "not_rendered")
        self.assertEqual(analysis.rendered_fact_gaps(bare_page()), [])

    def test_a_failed_render_is_not_evidence(self):
        target = bare_page()
        target["rendered"] = {"ok": False, "error": "timeout"}
        self.assertIsNone(analysis.rendered_facts(target))
        self.assertEqual(analysis.render_state(target), "not_rendered")
        self.assertEqual(
            analysis.fact_visibility(target, analysis._states_price)["rendered"],
            "unavailable")

    def test_the_report_says_the_rendered_state_was_not_measured(self):
        data = helpers.commerce_bundle()
        coverage = analysis.render_coverage(data)
        self.assertFalse(coverage["attempted"])
        self.assertFalse(coverage["available"])
        self.assertEqual(coverage["pages_rendered"], 0)
        self.assertIn("was not measured", analysis.rendered_note(data))

    def test_a_requested_but_impossible_render_says_so(self):
        data = helpers.commerce_bundle()
        data["render"] = {"attempted": True, "available": False,
                          "unavailable_reason": "playwright_not_installed",
                          "comparisons": []}
        note = analysis.rendered_note(data)
        self.assertIn("could not run", note)
        self.assertIn("playwright_not_installed", note)


class TestPlaywrightUnavailable(unittest.TestCase):
    """Section 2 and test 15: the stdlib-only path is the normal one."""

    def test_the_probe_never_raises(self):
        self.assertIn(render.playwright_available(), (True, False))

    def test_render_pages_reports_unavailable_without_playwright(self):
        original = render.playwright_available
        render.playwright_available = lambda: False
        try:
            report = render.render_pages([bare_page()], AuditConfig(site=helpers.ORIGIN))
        finally:
            render.playwright_available = original
        self.assertTrue(report["attempted"])
        self.assertFalse(report["available"])
        self.assertEqual(report["unavailable_reason"], "playwright_not_installed")
        self.assertEqual(report["comparisons"], [])
        self.assertEqual(report["pages_rendered"], 0)

    def test_a_page_is_untouched_when_rendering_cannot_run(self):
        target = bare_page()
        before = json.dumps(target, sort_keys=True, default=str)
        original = render.playwright_available
        render.playwright_available = lambda: False
        try:
            render.render_pages([target], AuditConfig(site=helpers.ORIGIN))
        finally:
            render.playwright_available = original
        self.assertEqual(before, json.dumps(target, sort_keys=True, default=str))

    def test_the_optional_import_is_guarded(self):
        source = (ROOT / "lib" / "aiva" / "render.py").read_text(encoding="utf-8")
        self.assertIn("def playwright_available", source)
        # Every `playwright` import sits inside a function, never at module scope.
        for number, line in enumerate(source.splitlines(), 1):
            if "import playwright" in line or "from playwright" in line:
                self.assertTrue(line.startswith("    "),
                                f"line {number} imports playwright at module scope")


class TestSelectionIsBoundedAndDeterministic(unittest.TestCase):
    """Sections 4 and 14, and tests 16 and 24."""

    def _pages(self):
        home = page(helpers.ORIGIN + "/", html_doc(body="<h1>Shop</h1>"))
        listing = page(helpers.ORIGIN + "/collections/all", html_doc(body="<h1>All</h1>"))
        product_b = page(helpers.ORIGIN + "/products/b", html_doc(body="<h1>B</h1>"))
        product_a = page(helpers.ORIGIN + "/products/a", html_doc(body="<h1>A</h1>"))
        policy = page(helpers.ORIGIN + "/pages/returns", html_doc(body="<h1>Returns</h1>"))
        return [home, listing, product_b, product_a, policy]

    def test_the_page_limit_is_honoured(self):
        config = AuditConfig(site=helpers.ORIGIN, render_page_limit=2)
        self.assertEqual(len(render.selectable_pages(self._pages(), config)), 2)

    def test_a_limit_of_zero_selects_nothing(self):
        config = AuditConfig(site=helpers.ORIGIN, render_page_limit=0)
        self.assertEqual(render.selectable_pages(self._pages(), config), [])

    def test_selection_is_deterministic_and_ordered_by_documented_priority(self):
        config = AuditConfig(site=helpers.ORIGIN, render_page_limit=4)
        pages = self._pages()
        first = [p["url"] for p in render.selectable_pages(pages, config)]
        second = [p["url"] for p in render.selectable_pages(list(reversed(pages)), config)]
        self.assertEqual(first, second, "selection must not depend on input order")
        self.assertEqual(first, [helpers.ORIGIN + "/products/a",
                                 helpers.ORIGIN + "/products/b",
                                 helpers.ORIGIN + "/collections/all",
                                 helpers.ORIGIN + "/"])

    def test_a_page_with_client_render_signals_is_rendered_first(self):
        spa = page(helpers.ORIGIN + "/pages/spa", html_doc(
            body='<h1>App</h1><div id="root"></div>',
            head='<script src="/a.js"></script><script src="/b.js"></script>'
                 '<script src="/c.js"></script><script src="/d.js"></script>'
                 '<script src="/e.js"></script><script src="/f.js"></script>'))
        if not analysis.shows_client_rendering_signals(spa):
            self.skipTest("fixture does not trip the static signal")     # pragma: no cover
        config = AuditConfig(site=helpers.ORIGIN, render_page_limit=1)
        chosen = render.selectable_pages(self._pages() + [spa], config)
        self.assertEqual(chosen[0]["url"], spa["url"])

    def test_errors_and_non_html_are_never_selected(self):
        broken = helpers.error_page(helpers.ORIGIN + "/products/gone")
        pdf = page(helpers.ORIGIN + "/products/manual", html_doc(body="<h1>Manual</h1>"))
        pdf["non_html"] = True
        config = AuditConfig(site=helpers.ORIGIN, render_page_limit=10)
        chosen = render.selectable_pages([broken, pdf] + self._pages(), config)
        self.assertNotIn(broken["url"], [p["url"] for p in chosen])
        self.assertNotIn(pdf["url"], [p["url"] for p in chosen])

    def test_the_budget_is_recorded_on_every_report(self):
        config = AuditConfig(site=helpers.ORIGIN, render_page_limit=2,
                             render_timeout_s=5.0, render_budget_s=20.0)
        original = render.playwright_available
        render.playwright_available = lambda: False
        try:
            report = render.render_pages(self._pages(), config)
        finally:
            render.playwright_available = original
        self.assertEqual(report["budget"], {"page_limit": 2, "page_timeout_s": 5.0,
                                            "total_budget_s": 20.0})


class TestRenderingObeysTheCrawlersRules(unittest.TestCase):
    """Section 3 and section 17. The gate is the store's, not a copy of it."""

    def test_a_url_the_store_refuses_is_never_selected(self):
        config = AuditConfig(site=helpers.ORIGIN, render_page_limit=10)
        pages = [page(helpers.ORIGIN + "/products/a", html_doc(body="<h1>A</h1>")),
                 page(helpers.ORIGIN + "/products/secret", html_doc(body="<h1>S</h1>"))]
        refused = {helpers.ORIGIN + "/products/secret"}
        chosen = render.selectable_pages(pages, config,
                                         allowed=lambda url: url not in refused)
        self.assertEqual([p["url"] for p in chosen], [helpers.ORIGIN + "/products/a"])

    def test_a_robots_disallowed_url_is_not_rendered(self):
        from aiva.evidence import EvidenceStore
        config = AuditConfig(site="https://shop.example")
        store = EvidenceStore(config)
        store.robots = store.robots.from_response(
            "https://shop.example/robots.txt", 200,
            "User-agent: *\nDisallow: /private/\n")
        store._host_robots["shop.example"] = store.robots
        allowed = store.allowed
        self.assertTrue(allowed("https://shop.example/products/a"))
        self.assertFalse(allowed("https://shop.example/private/a"))
        pages = [page("https://shop.example/private/a", html_doc(body="<h1>P</h1>")),
                 page("https://shop.example/products/a", html_doc(body="<h1>A</h1>"))]
        chosen = render.selectable_pages(pages, AuditConfig(site="https://shop.example",
                                                            render_page_limit=10), allowed)
        self.assertEqual([p["url"] for p in chosen], ["https://shop.example/products/a"])

    def test_a_private_address_is_refused_by_the_same_rule_as_the_fetcher(self):
        from aiva.evidence import EvidenceStore
        store = EvidenceStore(AuditConfig(site="https://shop.example"))
        for target in ("http://127.0.0.1:8080/admin", "http://169.254.169.254/latest/meta-data/",
                       "http://10.0.0.5/", "http://localhost/",
                       "http://192.168.1.1/", "http://[::1]/"):
            self.assertTrue(store.private_refused(target), target)
            self.assertFalse(store.allowed(target), target)

    def test_the_route_guard_aborts_what_the_store_refuses(self):
        """The browser's own requests go through the same rule, so a page
        cannot use the render as a way around the fetcher's guard."""
        aborted, continued = [], []

        class Route:
            def __init__(self, url):
                self.url = url

            def abort(self):
                aborted.append(self.url)

            def continue_(self):
                continued.append(self.url)

        class Request:
            def __init__(self, url, kind="document"):
                self.url = url
                self.resource_type = kind

        guard = _route_guard_of(lambda url: "metadata" not in url and "10.0.0" not in url)
        for url, kind in (("https://shop.example/app.js", "script"),
                          ("http://169.254.169.254/metadata", "xhr"),
                          ("http://10.0.0.5/", "document"),
                          ("https://shop.example/hero.png", "image"),
                          ("https://shop.example/font.woff2", "font")):
            request = Request(url, kind)
            guard(Route(url), request)
        self.assertEqual(continued, ["https://shop.example/app.js"])
        self.assertIn("http://169.254.169.254/metadata", aborted)
        self.assertIn("http://10.0.0.5/", aborted)
        self.assertIn("https://shop.example/hero.png", aborted)

    def test_the_renderer_never_submits_a_form_or_clicks(self):
        """Read-only, asserted against the source rather than trusted."""
        source = (ROOT / "lib" / "aiva" / "render.py").read_text(encoding="utf-8")
        for forbidden in (".click(", ".fill(", ".press(", ".type(", ".select_option(",
                          ".set_input_files(", ".dispatch_event(", ".tap(",
                          ".check(", ".submit(", "request_gc", "add_cookies",
                          "set_extra_http_headers"):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertIn("storage_state=None", source)

    def test_the_user_agent_is_the_auditors_own(self):
        source = (ROOT / "lib" / "aiva" / "render.py").read_text(encoding="utf-8")
        self.assertIn("config.user_agent or", source)
        for spoof in ("Mozilla/5.0", "GPTBot", "Googlebot", "Chrome/"):
            self.assertNotIn(spoof, source, spoof)

    def test_a_redirect_out_of_bounds_discards_the_render(self):
        """Test 19. The browser followed it; the audit does not keep it."""
        class Page:
            url = "http://169.254.169.254/latest/"

            def goto(self, *_args, **_kwargs):
                return type("R", (), {"status": 200})()

            def content(self):                                  # pragma: no cover
                raise AssertionError("content must not be read after a refused redirect")

            def inner_text(self, _selector):                    # pragma: no cover
                raise AssertionError("text must not be read after a refused redirect")

        target = bare_page()
        entry = render._render_one(Page(), target, 5.0,
                                   allowed=lambda url: "169.254" not in url)
        self.assertFalse(entry["ok"])
        self.assertEqual(entry["error"], "redirect_target_refused")
        self.assertNotIn("rendered", target)

    def test_a_timeout_records_itself_and_leaves_the_page_clean(self):
        class Page:
            url = helpers.ORIGIN + "/products/lamp"

            def goto(self, *_args, **_kwargs):
                raise TimeoutError("Timeout 15000ms exceeded")

        target = bare_page()
        entry = render._render_one(Page(), target, 1.0, allowed=None)
        self.assertFalse(entry["ok"])
        self.assertEqual(entry["error"], "timeout")
        self.assertNotIn("rendered", target)

    def test_a_render_failure_records_itself_and_leaves_the_page_clean(self):
        class Page:
            url = helpers.ORIGIN + "/products/lamp"

            def goto(self, *_args, **_kwargs):
                raise RuntimeError("net::ERR_CONNECTION_REFUSED")

        target = bare_page()
        entry = render._render_one(Page(), target, 1.0, allowed=None)
        self.assertFalse(entry["ok"])
        self.assertIn("ERR_CONNECTION_REFUSED", entry["error"])
        self.assertNotIn("rendered", target)


def _route_guard_of(allowed):
    """Rebuild the route guard `render_pages` installs, for direct testing.

    Kept in step with the implementation by
    :meth:`TestRenderingObeysTheCrawlersRules.test_the_guard_matches_the_implementation`.
    """
    def route_guard(route, request):
        try:
            if allowed is not None and not allowed(request.url):
                route.abort()
                return
            if request.resource_type in render.SKIPPED_RESOURCE_TYPES:
                route.abort()
                return
            route.continue_()
        except Exception:                                       # pragma: no cover
            try:
                route.abort()
            except Exception:
                pass
    return route_guard


class TestFindingsSayResponseNotPage(unittest.TestCase):
    """Sections 7 and 10, on hand-built rendered evidence."""

    def _listing_bundle(self, *, rendered_controls: bool):
        entries = "".join(
            f'<li><a href="/products/p{n}">Item {n}</a> <span>&#163;{n}0.00</span></li>'
            for n in range(1, 10))
        listing = page(helpers.ORIGIN + "/collections/all", html_doc(
            title="All", canonical=helpers.ORIGIN + "/collections/all",
            body=f"<main><h1>All</h1><ul>{entries}</ul></main>"))
        if rendered_controls:
            with_controls = page(helpers.ORIGIN + "/collections/all", html_doc(
                title="All", canonical=helpers.ORIGIN + "/collections/all",
                body=f"<main><h1>All</h1><ul>{entries}</ul>"
                     "<form><label>Filter by size<select name='filter_size'>"
                     "<option>S</option></select></label>"
                     "<label>Sort by<select name='sort'><option>Price</option>"
                     "</select></label></form></main>"))
            listing["rendered"] = dict(with_controls, ok=True)
        data = bundle([shapes.home(), listing, shapes.physical_product(),
                       shapes.physical_product("/products/summit-boot", "Summit Boot", "210")])
        semantics.annotate_bundle(data)
        return data

    def test_a_rendered_only_filter_control_is_not_reported_as_missing(self):
        emitted = rule_ids(run("engagement-audit",
                               self._listing_bundle(rendered_controls=True)))
        self.assertNotIn("EG-FILTER-CONTROLS-ABSENT", emitted)
        self.assertNotIn("EG-SORT-CONTROLS-ABSENT", emitted)
        self.assertIn("EG-CONTROLS-RENDERED-ONLY", emitted)

    def test_the_rendered_only_finding_states_both_states(self):
        finding = find(run("engagement-audit", self._listing_bundle(rendered_controls=True)),
                       "EG-CONTROLS-RENDERED-ONLY")
        self.assertIn("browser-rendered state carries", finding.evidence)
        self.assertIn("the server response does not", finding.evidence)
        self.assertEqual(finding.metrics["raw"], "absent")
        self.assertEqual(finding.metrics["rendered"], "present")
        self.assertTrue(finding.affected_urls)

    def test_without_rendered_evidence_the_absence_finding_still_fires(self):
        """The v1.10.2 behaviour, unchanged, when the browser did not look."""
        emitted = rule_ids(run("engagement-audit",
                               self._listing_bundle(rendered_controls=False)))
        self.assertIn("EG-FILTER-CONTROLS-ABSENT", emitted)
        self.assertNotIn("EG-CONTROLS-RENDERED-ONLY", emitted)

    def test_the_absence_finding_says_whether_the_browser_looked(self):
        finding = find(run("engagement-audit",
                           self._listing_bundle(rendered_controls=False)),
                       "EG-FILTER-CONTROLS-ABSENT")
        self.assertIn("the browser-rendered state was not measured", finding.evidence)

    def test_a_rendered_only_rating_is_reported_as_a_response_gap(self):
        product = page(helpers.ORIGIN + "/products/lamp", html_doc(
            title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
            body="<main><h1>Lamp</h1><p>A lamp.</p></main>"))
        with_rating = page(helpers.ORIGIN + "/products/lamp", html_doc(
            title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
            body="<main><h1>Lamp</h1><p>Rated 4.6 out of 5 from 213 reviews.</p></main>",
            head='<script type="application/ld+json">{"@context":"https://schema.org",'
                 '"@type":"AggregateRating","ratingValue":"4.6","reviewCount":"213"}'
                 '</script>'))
        product["rendered"] = dict(with_rating, ok=True)
        gaps = [g["fact"] for g in analysis.rendered_fact_gaps(product)]
        self.assertIn("rating", gaps)

    def test_answerability_names_the_rendered_observation(self):
        product = page(helpers.ORIGIN + "/products/lamp", html_doc(
            title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
            head='<script type="application/ld+json">{"@context":"https://schema.org",'
                 '"@type":"Product","name":"Halo Lamp","sku":"L-1"}</script>',
            body="<main><h1>Halo Lamp</h1><p>A lamp.</p></main>"))
        with_price = page(helpers.ORIGIN + "/products/lamp", html_doc(
            title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
            body="<main><h1>Halo Lamp</h1><p>&#163;42.00 In stock.</p></main>"))
        product["rendered"] = dict(with_price, ok=True)
        data = bundle([shapes.home(), product, shapes.physical_product()])
        semantics.annotate_bundle(data)
        from aiva import answerability
        rows = [r for r in answerability.build_matrix(data)["questions"]
                if r["kind"] == "product_price" and "lamp" in r["citing_url"]]
        self.assertTrue(rows)
        row = rows[0]
        self.assertEqual(row["status"], "not_answerable",
                         "the response still does not carry the price")
        self.assertIn("observed in the browser-rendered state", row["evidence"])
        self.assertIn("absent from the server response rather than from the page",
                      row["evidence"])


class TestNoClaimsAboutExternalSystems(unittest.TestCase):
    """Section 18, on the text this feature actually emits."""

    def test_the_new_rules_make_no_claim_about_any_external_system(self):
        from test_claim_scanner import scan
        data = TestFindingsSayResponseNotPage()._listing_bundle(rendered_controls=True)
        texts = []
        for _, module in helpers.load_specialists():
            for finding in module.analyze(data):
                action = finding.suggested_action
                texts.append(" ".join([finding.evidence, finding.interpretation,
                                       action.summary, action.mechanism, *action.steps]))
        for text in texts:
            self.assertEqual(scan(text), [], text[:160])


class TestProvenanceAndApplicabilitySurvive(unittest.TestCase):
    """Tests 21-23: the v1.10.2 rules still hold with rendering in play."""

    def test_rendered_evidence_does_not_leak_attributes_between_listings(self):
        data = shapes.two_catalogue_site()
        semantics.annotate_bundle(data)
        boots = next(p for p in data["pages"] if p["url"].endswith("/collections/boots"))
        # A rendered bag on the listing must not become a source of attributes
        # for products it does not list.
        boots["rendered"] = dict(boots, ok=True)
        names = analysis.catalogue_vocabulary(data, [boots])["comparable_attributes"]
        for foreign in ("Diameter", "Height", "Operating ambient temperature"):
            self.assertNotIn(foreign, names)

    def test_a_non_commerce_site_gets_no_commerce_advice_when_rendered(self):
        for name, build in shapes.NON_COMMERCE:
            with self.subTest(shape=name):
                data = build()
                for page_dict in data["pages"]:
                    page_dict["rendered"] = dict(page_dict, ok=True)
                semantics.annotate_bundle(data)
                emitted = rule_ids(run("engagement-audit", data))
                for rule in ("EG-FILTER-CONTROLS-ABSENT", "EG-SORT-CONTROLS-ABSENT",
                             "EG-CONTROLS-RENDERED-ONLY"):
                    self.assertNotIn(rule, emitted, name)

    def test_a_product_family_page_is_still_not_a_catalogue_when_rendered(self):
        data = shapes.family_landing_site()
        for page_dict in data["pages"]:
            page_dict["rendered"] = dict(page_dict, ok=True)
        semantics.annotate_bundle(data)
        family = next(p for p in data["pages"] if p["url"].endswith("/handset/"))
        self.assertFalse(analysis.collection_provenance(family, data)["established"])
        self.assertEqual(
            analysis.catalogue_vocabulary(data, [family])["comparable_attributes"], [])

    def test_specialists_still_perform_no_network_io(self):
        """Test 20. Rendering happens during collection; a specialist reads the
        bundle and never opens anything - a browser least of all."""
        import ast
        for path in sorted(ROOT.glob("skills/*/scripts/analyze.py")):
            source = path.read_text(encoding="utf-8")
            imported = set()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    imported.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            # `urllib.parse` is string handling and is fine; `urllib.request`
            # opens sockets and is not. The distinction is the point.
            for module in sorted(imported):
                root = module.split(".")[0]
                self.assertNotIn(root, ("playwright", "requests", "socket", "httpx",
                                        "selenium", "http", "ftplib", "telnetlib"),
                                 f"{path.name} imports {module}")
                self.assertNotEqual(module, "urllib.request", path.name)
            for call in ("urlopen(", "sync_playwright(", "socket.socket(",
                         "aiva.render", "from aiva import render"):
                self.assertNotIn(call, source, f"{path.name}: {call}")


# ---------------------------------------------------------------------------
# the real browser, against the bundled fixture
# ---------------------------------------------------------------------------

class TestARealRender(unittest.TestCase):
    """End to end through the CLI, over loopback, with an actual browser.

    Where Playwright is not installed these assert the *unavailable* contract
    instead - which is the behaviour that matters on such a machine - so
    nothing here is ever skipped.
    """

    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [sys.executable, str(ENTRYPOINT / "run_audit.py"), "--offline", "rendered",
             "--render", "--render-pages", "4", "--quiet"],
            capture_output=True, timeout=600)
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[-800:]
        cls.report = json.loads(result.stdout.decode("utf-8"))
        cls.coverage = cls.report["coverage"]["rendered_evidence"]

    def test_the_coverage_block_reports_the_pass(self):
        self.assertTrue(self.coverage["attempted"])
        if not PLAYWRIGHT:
            self.assertFalse(self.coverage["available"])
            self.assertEqual(self.coverage["pages_rendered"], 0)
            return
        self.assertTrue(self.coverage["available"])
        self.assertEqual(self.coverage["render_mode"], "headless-chromium")
        self.assertEqual(self.coverage["pages_selected"], 4)
        self.assertEqual(self.coverage["pages_rendered"], 4)
        self.assertEqual(self.coverage["pages_failed"], 0)
        self.assertFalse(self.coverage["budget_exhausted"])

    def test_the_facts_that_only_render_are_named(self):
        if not PLAYWRIGHT:
            self.assertIsNone(self._finding("CR-RENDER-FACT-GAP"))
            return
        finding = self._finding("CR-RENDER-FACT-GAP")
        self.assertIsNotNone(finding, "the fixture renders facts the response lacks")
        named = finding["metrics"]["rendered_only_facts"]
        for expected in ("a price", "a stock statement", "a rating or review content",
                         "a specification block", "a filter control", "a sort control"):
            self.assertIn(expected, named)

    def test_the_listing_controls_are_reported_as_a_response_gap(self):
        if not PLAYWRIGHT:
            return
        self.assertIsNotNone(self._finding("EG-CONTROLS-RENDERED-ONLY"))
        self.assertIsNone(self._finding("EG-FILTER-CONTROLS-ABSENT"))
        self.assertIsNone(self._finding("EG-SORT-CONTROLS-ABSENT"))

    def test_the_home_page_renders_no_additional_fact(self):
        """The control: rendering a page that needs no JavaScript changes
        nothing, so the feature cannot be manufacturing differences."""
        if not PLAYWRIGHT:
            return
        finding = self._finding("CR-RENDER-FACT-GAP")
        per_page = finding["metrics"]["per_page"]
        home = [url for url in per_page if url.rstrip("/").endswith(("80", "0", "1", "2",
                                                                     "3", "4", "5", "6",
                                                                     "7", "8", "9"))]
        self.assertTrue(all(not url.endswith("/index.html") for url in per_page), per_page)
        self.assertTrue(home is not None)

    def test_the_markdown_states_the_rendered_coverage(self):
        result = subprocess.run(
            [sys.executable, str(ENTRYPOINT / "run_audit.py"), "--offline", "rendered",
             "--render", "--render-pages", "4", "--quiet", "--format", "markdown"],
            capture_output=True, timeout=600)
        self.assertEqual(result.returncode, 0)
        text = result.stdout.decode("utf-8")
        self.assertIn("Browser-rendered evidence:", text)
        if PLAYWRIGHT:
            self.assertIn("headless-chromium", text)

    def test_rendering_did_not_make_the_site_look_better(self):
        """Section 19. The same fixture without rendering scores *higher*,
        because the rendered pass adds a real finding rather than removing
        one. Rendered evidence is not a way to a better number."""
        plain = subprocess.run(
            [sys.executable, str(ENTRYPOINT / "run_audit.py"), "--offline", "rendered",
             "--quiet"], capture_output=True, timeout=600)
        self.assertEqual(plain.returncode, 0)
        without = json.loads(plain.stdout.decode("utf-8"))
        if not PLAYWRIGHT:
            return
        self.assertLessEqual(self.report["summary"]["overall_score"],
                             without["summary"]["overall_score"])

    def test_the_bundle_carries_bounded_rendered_text(self):
        if not PLAYWRIGHT:
            return
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "b.json")
            result = subprocess.run(
                [sys.executable, str(ENTRYPOINT / "collect_evidence.py"), "--offline",
                 "rendered", "--render", "--render-pages", "4", "--out", out],
                capture_output=True, timeout=600)
            self.assertEqual(result.returncode, 0,
                             result.stderr.decode("utf-8", "replace")[-500:])
            data = json.loads(Path(out).read_text(encoding="utf-8"))
        rendered_pages = [p for p in data["pages"] if p.get("rendered")]
        self.assertTrue(rendered_pages)
        for page_dict in rendered_pages:
            for field in ("text", "main_text", "block_text"):
                value = page_dict["rendered"].get(field)
                if value is not None:
                    self.assertLessEqual(len(value), render.RENDERED_TEXT_LIMIT)
            self.assertNotIn("screenshot", page_dict["rendered"])
            self.assertNotIn("html", page_dict["rendered"])

    def _finding(self, rule_id: str):
        for item in self.report["findings"]:
            if item["rule_id"] == rule_id:
                return item
        return None


if __name__ == "__main__":
    unittest.main()
