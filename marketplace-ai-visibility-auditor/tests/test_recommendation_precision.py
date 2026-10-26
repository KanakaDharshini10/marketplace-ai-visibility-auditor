"""A cautious title must not carry an assertive recommendation.

v1.11.1 made a finding's *title* follow its applicability: a listing whose item
set could not be delimited was retitled "sort controls could not be assessed
against a known comparable set", lowered to `low`/0.4, and stripped of named
attributes and dimensions. Its *recommendation* still said "Add a sort control
to category listings" - an instruction that presumes exactly the thing the
title says was not established. A reader acts on the recommendation, so that is
where the caution has to arrive.

The rule this module holds shut:

    a DOWNGRADE finding's recommendation may describe what was observed, and
    may not introduce a dimension, an attribute, an intent or a business
    requirement that was not

`analysis.conditional_advice` is the one place that enforces it. On a downgrade
it swaps the assertive action body for a conditional one phrased against what
the page would have to be intended as, which puts the premise back in the
reader's hands where the evidence left it.

The second half of this module covers finding corroboration: two rules that
measure genuinely different properties of one page - delivery architecture and
the size of what it withholds - stay separately visible with their own evidence
while the score is charged once, because a site owner does one piece of work to
answer both.

Every fixture is invented (:mod:`shapes`). No test, and no line of runtime
code, knows a domain name.

Run just this file:

    python3 tests/run_tests.py recommendation_precision -v
"""

from __future__ import annotations

import unittest

import helpers
import shapes
from helpers import bundle, find, html_doc, page, rule_ids, run

from aiva import analysis, report, scoring, semantics
from aiva.analysis import DOWNGRADE, REPORT, applicability_verdict, conditional_advice
from aiva.findings import (CORROBORATED_BY, CORROBORATION, ROLE_CORROBORATION,
                           SCORING_ROLE, SuggestedAction, make_finding)

FILTER = "EG-FILTER-CONTROLS-ABSENT"
SORT = "EG-SORT-CONTROLS-ABSENT"

#: Every dimension and attribute name a recommendation could reach for. On an
#: undelimited set none of them may appear in the advice.
NEVER_INVENTED = ("price", "rating", "popularity", "newest", "storage", "size",
                  "colour", "color", "display", "diameter", "height", "material",
                  "weight")


def annotated(build) -> dict:
    data = build() if callable(build) else build
    semantics.annotate_bundle(data)
    return data


def advice_of(finding) -> str:
    """What the reader is told to do - not what was observed."""
    action = finding.suggested_action
    return " ".join([action.summary, action.mechanism, action.example, *action.steps])


# ---------------------------------------------------------------------------
# fixtures for the seven cases
# ---------------------------------------------------------------------------

def catalogue_without_controls(*, priced: bool = True, rated: bool = False,
                               attributes: bool = True) -> dict:
    """A genuine catalogue - members readable - that exposes no controls.

    The positive control for every case below: applicability is established, so
    the recommendation is allowed to name what the members actually publish.
    """
    def member(path: str, name: str, price: str) -> dict:
        offer = (f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"GBP",'
                 f'"availability":"https://schema.org/InStock"}},' if priced else "")
        rating = ('"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.5",'
                  '"reviewCount":"20"},' if rated else "")
        props = ('"color":"Brown","material":"Leather",' if attributes else "")
        ld = ('{"@context":"https://schema.org","@type":"Product","name":"%s","sku":"%s",'
              '%s%s%s"description":"An invented item."}'
              % (name, name[:3].upper(), props, offer, rating))
        body = f"<main><h1>{name}</h1>"
        if priced:
            body += f"<p>&#163;{price}. In stock.</p>"
        if attributes:
            body += ("<table><tr><th>Material</th><td>Leather</td></tr>"
                     "<tr><th>Colour</th><td>Brown</td></tr></table>")
        body += f"<p>{shapes.LONG}</p></main>"
        return page(helpers.ORIGIN + path,
                    html_doc(title=name, canonical=helpers.ORIGIN + path,
                             head=helpers.jsonld(ld), body=body))

    entries = "".join(
        f'<li><a href="/products/item-{n}">Item {n}</a>'
        + (f' <span>&#163;{n}0</span>' if priced else "") + "</li>"
        for n in range(1, 10))
    listing = page(helpers.ORIGIN + "/collections/all", html_doc(
        title="All", canonical=helpers.ORIGIN + "/collections/all",
        body=f"<main><h1>All</h1><ul>{entries}</ul></main>"))
    return annotated(bundle([shapes.home(), listing,
                             member("/products/item-1", "Item One", "10"),
                             member("/products/item-2", "Item Two", "20")]))


def undelimited_listing(extra=()) -> dict:
    """A page that reads as a listing and whose members were never read."""
    return annotated(bundle([shapes.home(), shapes.ambiguous_listing(), *extra]))


# ---------------------------------------------------------------------------
# the seven cases from the brief
# ---------------------------------------------------------------------------

class TestSortRecommendationFollowsApplicability(unittest.TestCase):

    def test_case_1_known_catalogue_with_an_observed_price_may_name_price(self):
        data = catalogue_without_controls(priced=True)
        finding = find(run("engagement-audit", data), SORT)
        self.assertIsNotNone(finding, "a genuine catalogue is still assessed")
        self.assertEqual(finding.metrics["applicability"], REPORT)
        self.assertIn("price", finding.metrics["evidenced_order_dimensions"])
        self.assertIn("price", advice_of(finding).lower())

    def test_case_2_known_catalogue_with_no_ordering_value_names_none(self):
        data = catalogue_without_controls(priced=False, rated=False)
        finding = find(run("engagement-audit", data), SORT)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.metrics["evidenced_order_dimensions"], [])
        steps = " ".join(finding.suggested_action.steps)
        self.assertIn("No price or rating was observed", steps)

    def test_case_3_unknown_item_set_gets_conditional_advice_naming_nothing(self):
        finding = find(run("engagement-audit", undelimited_listing()), SORT)
        self.assertIsNotNone(finding, "the observed absence is still reported")
        self.assertEqual(finding.metrics["applicability"], DOWNGRADE)
        advice = advice_of(finding)
        self.assertIn("If this page is intended to function as", advice)
        self.assertIn("cannot be recommended", advice)
        for word in NEVER_INVENTED:
            self.assertNotIn(word, advice.lower(), f"{word!r} was never observed")

    def test_a_rating_is_never_named_unless_a_member_publishes_one(self):
        priced_only = catalogue_without_controls(priced=True, rated=False)
        self.assertNotIn("rating",
                         analysis.orderable_dimensions(
                             priced_only,
                             [p for p in priced_only["pages"]
                              if p["url"].endswith("/collections/all")]))
        both = catalogue_without_controls(priced=True, rated=True)
        self.assertEqual(
            analysis.orderable_dimensions(
                both, [p for p in both["pages"]
                       if p["url"].endswith("/collections/all")]),
            ["price", "rating"])


class TestFilterRecommendationFollowsApplicability(unittest.TestCase):

    def test_case_4_known_catalogue_may_name_its_members_attributes(self):
        data = catalogue_without_controls(attributes=True)
        finding = find(run("engagement-audit", data), FILTER)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.metrics["applicability"], REPORT)
        self.assertTrue(finding.metrics["attribute_provenance"],
                        "the members the attributes came from are named")
        advice = advice_of(finding).lower()
        self.assertTrue("material" in advice or "colour" in advice or "color" in advice,
                        advice[:200])

    def test_case_5_unknown_item_set_names_no_attribute(self):
        finding = find(run("engagement-audit", undelimited_listing()), FILTER)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.metrics["applicability"], DOWNGRADE)
        advice = advice_of(finding)
        self.assertIn("no specific filter attribute can be recommended", advice)
        for word in NEVER_INVENTED:
            self.assertNotIn(word, advice.lower(), f"{word!r} was never observed")

    def test_case_6_an_unrelated_products_attributes_never_appear(self):
        data = undelimited_listing(extra=[shapes.instrument_product()])
        for rule in (FILTER, SORT):
            advice = advice_of(find(run("engagement-audit", data), rule))
            for attribute in ("Diameter", "Height", "Operating ambient temperature"):
                self.assertNotIn(attribute, advice, f"{rule}: {attribute}")

    def test_case_7_a_product_family_page_gets_no_specific_ecommerce_advice(self):
        data = annotated(shapes.family_landing_site)
        for rule in (FILTER, SORT):
            finding = find(run("engagement-audit", data), rule)
            self.assertIsNotNone(finding, rule)
            self.assertEqual(finding.metrics["applicability"], DOWNGRADE, rule)
            advice = advice_of(finding).lower()
            for word in NEVER_INVENTED:
                self.assertNotIn(word, advice, f"{rule}: {word}")


class TestTitleAndRecommendationAgree(unittest.TestCase):
    """The inconsistency 1.11.2 exists to close, asserted as an invariant."""

    def test_no_downgraded_finding_carries_an_imperative_about_the_missing_half(self):
        for name, build in shapes.ALL_SHAPES + (
                ("golden", shapes.golden_site),
                ("family", shapes.family_landing_site),
                ("ambiguous", lambda: undelimited_listing())):
            with self.subTest(shape=name):
                data = annotated(build)
                for _, module in helpers.load_specialists():
                    for finding in module.analyze(data):
                        if (finding.metrics or {}).get("applicability") != DOWNGRADE:
                            continue
                        advice = advice_of(finding)
                        self.assertIn("intended to function as", advice,
                                      f"{name}/{finding.rule_id} is downgraded but its "
                                      f"advice is not conditional")
                        for word in NEVER_INVENTED:
                            self.assertNotIn(word, advice.lower(),
                                             f"{name}/{finding.rule_id}: {word}")

    def test_a_downgraded_finding_is_never_high_priority(self):
        for rule in (FILTER, SORT):
            finding = find(run("engagement-audit", undelimited_listing()), rule)
            self.assertEqual(finding.suggested_action.priority, "low", rule)

    def test_the_helper_leaves_a_reported_finding_assertive(self):
        verdict = applicability_verdict(observed=True, applies=True,
                                        severity="high", confidence=0.9)
        body = conditional_advice(
            verdict, intended_as="a catalogue",
            assertive=dict(summary="Do the thing.", mechanism="Because.",
                           steps=["Step one."], priority="high"),
            conditional=dict(summary="Maybe do it.", mechanism="If {intended_as}.",
                             steps=["Only if {intended_as}."]))
        self.assertEqual(body["summary"], "Do the thing.")
        self.assertEqual(body["priority"], "high")

    def test_the_helper_makes_a_downgraded_finding_conditional(self):
        verdict = applicability_verdict(observed=True, applies=False,
                                        severity="high", confidence=0.9)
        body = conditional_advice(
            verdict, intended_as="a catalogue",
            assertive=dict(summary="Do the thing.", mechanism="Because.",
                           steps=["Step one."], priority="high"),
            conditional=dict(summary="Maybe do it.", mechanism="If {intended_as}.",
                             steps=["Only if {intended_as}."]))
        self.assertEqual(body["summary"], "Maybe do it.")
        self.assertEqual(body["mechanism"], "If a catalogue.")
        self.assertEqual(body["steps"], ["Only if a catalogue."])
        self.assertEqual(body["priority"], "low")


# ---------------------------------------------------------------------------
# corroboration: two measurements, one remediation
# ---------------------------------------------------------------------------

def _finding(rule_id: str, severity: str, urls, metrics=None):
    return make_finding(
        rule_id, rule_id, severity, "crawl_render",
        evidence="observed", action=SuggestedAction(summary="fix it"),
        urls=list(urls), confidence=0.9, metrics=dict(metrics or {}))


class TestCorroboratingFindings(unittest.TestCase):
    """Different measurements of one condition stay visible and cost once."""

    def test_two_findings_on_one_page_are_linked_in_both_directions(self):
        shell = _finding("CR-JS-RENDERED-SHELL", "critical", ["https://x.example/a"])
        gap = _finding("CR-JS-CONTENT-GAP", "high", ["https://x.example/a"],
                       {CORROBORATION: "CR-JS-RENDERED-SHELL"})
        self.assertEqual(report.link_corroborating([shell, gap]), 1)
        self.assertEqual(gap.metrics[SCORING_ROLE], ROLE_CORROBORATION)
        self.assertEqual(shell.metrics[CORROBORATED_BY], "CR-JS-CONTENT-GAP")

    def test_neither_finding_is_removed(self):
        shell = _finding("CR-JS-RENDERED-SHELL", "critical", ["https://x.example/a"])
        gap = _finding("CR-JS-CONTENT-GAP", "high", ["https://x.example/a"],
                       {CORROBORATION: "CR-JS-RENDERED-SHELL"})
        findings = [shell, gap]
        report.link_corroborating(findings)
        self.assertEqual(len(findings), 2)
        self.assertEqual(gap.severity, "high", "severity and evidence are untouched")
        self.assertTrue(gap.evidence)

    def test_the_score_is_charged_once(self):
        shell = _finding("CR-JS-RENDERED-SHELL", "critical", ["https://x.example/a"])
        gap = _finding("CR-JS-CONTENT-GAP", "high", ["https://x.example/a"],
                       {CORROBORATION: "CR-JS-RENDERED-SHELL"})
        alone = scoring.pillar_scores([shell])["crawl_render"]["score"]
        report.link_corroborating([shell, gap])
        together = scoring.pillar_scores([shell, gap])["crawl_render"]["score"]
        self.assertEqual(alone, together,
                         "one remediation must cost the pillar once")

    def test_findings_about_different_pages_are_not_linked(self):
        """Never collapse on rule id alone: two pages are two observations."""
        shell = _finding("CR-JS-RENDERED-SHELL", "critical", ["https://x.example/a"])
        gap = _finding("CR-JS-CONTENT-GAP", "high", ["https://x.example/b"],
                       {CORROBORATION: "CR-JS-RENDERED-SHELL"})
        self.assertEqual(report.link_corroborating([shell, gap]), 0)
        self.assertNotIn(SCORING_ROLE, gap.metrics)
        both = scoring.pillar_scores([shell, gap])["crawl_render"]["score"]
        self.assertLess(both, scoring.pillar_scores([shell])["crawl_render"]["score"])

    def test_a_declaration_whose_target_is_absent_does_nothing(self):
        gap = _finding("CR-JS-CONTENT-GAP", "high", ["https://x.example/a"],
                       {CORROBORATION: "CR-JS-RENDERED-SHELL"})
        self.assertEqual(report.link_corroborating([gap]), 0)
        self.assertNotIn(SCORING_ROLE, gap.metrics)

    def test_the_two_rendering_findings_measure_different_things(self):
        """They are not duplicates: one reads the response alone, the other
        compares two states, and each says which in its own metrics."""
        crawl = helpers.specialist("crawl-render-audit")
        source = (helpers.ROOT / "skills" / "crawl-render-audit" / "scripts"
                  / "analyze.py").read_text(encoding="utf-8")
        self.assertIn("Page content is delivered through an empty client-rendering shell",
                      source)
        self.assertIn("Browser rendering reveals substantially more content than the "
                      "server response", source)
        self.assertIn('"measured_from": "server response only"', source)
        self.assertIn('"measured_from": "server response compared with the rendered DOM"',
                      source)
        self.assertTrue(hasattr(crawl, "rule_js_dependence"))

    def test_a_shell_page_and_a_measured_gap_both_appear(self):
        """End to end on a synthetic bundle carrying both conditions."""
        shell_html = html_doc(
            title="App", canonical=helpers.ORIGIN + "/products/app",
            body='<main><h1>App</h1><div id="root"></div></main>')
        target = page(helpers.ORIGIN + "/products/app", shell_html)
        target["scripts"] = dict(target.get("scripts") or {},
                                 spa_markers=["empty #root mount point"])
        target["text_word_count"] = 3
        data = annotated(bundle([shapes.home(), target, shapes.physical_product()]))
        data["render"] = {
            "attempted": True, "available": True, "render_mode": "headless-chromium",
            "pages_selected": 1, "pages_rendered": 1, "pages_failed": 0,
            "comparisons": [{"url": target["url"], "ok": True, "raw_word_count": 3,
                             "rendered_word_count": 271, "content_gain_ratio": 90.3,
                             "jsonld_before_render": 0, "jsonld_after_render": 1}],
        }
        emitted = run("crawl-render-audit", data)
        ids = rule_ids(emitted)
        self.assertIn("CR-JS-RENDERED-SHELL", ids)
        self.assertIn("CR-JS-CONTENT-GAP", ids)
        gap = find(emitted, "CR-JS-CONTENT-GAP")
        shell = find(emitted, "CR-JS-RENDERED-SHELL")
        self.assertNotEqual(gap.title, shell.title)
        self.assertNotEqual(gap.metrics["measured_from"], shell.metrics["measured_from"])
        # And the evidence points the reader at the other observation.
        self.assertIn("CR-JS-RENDERED-SHELL", gap.evidence)
        report.link_corroborating(emitted)
        self.assertEqual(gap.metrics[SCORING_ROLE], ROLE_CORROBORATION)


class TestRenderedEvidenceIsUnchanged(unittest.TestCase):
    """1.11.0's feature must come through this patch untouched."""

    def test_the_six_states_and_the_coverage_block_survive(self):
        self.assertEqual(analysis.VISIBILITY_STATES,
                         ("server_and_rendered", "server_visible", "rendered_only",
                          "structured_only", "not_observed", "render_unavailable"))
        coverage = analysis.render_coverage(helpers.commerce_bundle())
        for key in ("attempted", "available", "pages_selected", "pages_rendered",
                    "pages_failed", "budget", "budget_exhausted"):
            self.assertIn(key, coverage)

    def test_a_render_failure_stays_a_visible_coverage_limitation(self):
        """The real Apple run selected 3, rendered 2, failed 1. That third page
        is a coverage limit the report must keep showing, not round away."""
        data = helpers.commerce_bundle()
        rendered_ok = [p for p in data["pages"] if p.get("page_type") == "product"][:2]
        for page_dict in rendered_ok:
            page_dict["rendered"] = dict(page_dict, ok=True)
        data["render"] = {"attempted": True, "available": True,
                          "render_mode": "headless-chromium",
                          "pages_selected": 3, "pages_rendered": 2, "pages_failed": 1,
                          "comparisons": [{"url": "https://x.example/a", "ok": False,
                                           "error": "timeout"}]}
        coverage = analysis.render_coverage(data)
        self.assertEqual(coverage["pages_selected"], 3)
        self.assertEqual(coverage["pages_rendered"], 2)
        self.assertEqual(coverage["pages_failed"], 1)
        self.assertIn("2 page(s)", analysis.rendered_note(data))

    def test_a_rendered_only_fact_is_still_a_response_gap_not_a_missing_fact(self):
        product = page(helpers.ORIGIN + "/products/lamp", html_doc(
            title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
            body="<main><h1>Lamp</h1><p>A lamp.</p></main>"))
        with_price = page(helpers.ORIGIN + "/products/lamp", html_doc(
            title="Lamp", canonical=helpers.ORIGIN + "/products/lamp",
            body="<main><h1>Lamp</h1><p>&#163;42.00 In stock.</p></main>"))
        product["rendered"] = dict(with_price, ok=True)
        verdict = analysis.fact_visibility(product, analysis._states_price)
        self.assertEqual(verdict["state"], "rendered_only")
        self.assertIn("not observed in the server HTML", verdict["phrase"])
class TestObservedContextsAreShown(unittest.TestCase):
    """A single site shape is a decision; the sample is often several things.

    `site_kind` must stay one value - an expectation is applied or it is not -
    but a large host is routinely several things at once, and reporting only
    "publisher (low confidence)" hides that commerce was observed too. The
    scores behind the decision already exist; this surfaces them.
    """

    def test_a_mixed_site_lists_the_shapes_that_composed_it(self):
        """`mixed` is a verdict rather than a scored kind, so no entry is
        marked primary - the list *is* the composition, which is the useful
        reading: commerce was observed even though the headline says mixed."""
        data = annotated(shapes.golden_site)
        contexts = report.observed_contexts(data)
        self.assertEqual(semantics.site_context(data)["site_kind"], "mixed")
        self.assertGreater(len(contexts), 1)
        self.assertIn("ecommerce", [c["context"] for c in contexts])
        self.assertEqual([c for c in contexts if c["primary"]], [])
        scores = [c["evidence_score"] for c in contexts]
        self.assertEqual(scores, sorted(scores, reverse=True), "ranked by evidence")

    def test_a_single_shape_site_lists_only_itself_and_marks_it_primary(self):
        data = annotated(shapes.publisher)
        contexts = report.observed_contexts(data)
        self.assertEqual([c["context"] for c in contexts], ["publisher"])
        self.assertTrue(contexts[0]["primary"],
                        "a concrete site kind is marked as the one that was chosen")

    def test_it_changes_no_expectation_and_no_score(self):
        """Additive only: the site kind and every gate are untouched."""
        data = annotated(shapes.golden_site)
        before = semantics.site_context(data)["site_kind"]
        report.observed_contexts(data)
        self.assertEqual(semantics.site_context(data)["site_kind"], before)

    def test_a_bundle_with_no_readable_page_yields_nothing(self):
        self.assertEqual(report.observed_contexts(bundle([])), [])


if __name__ == "__main__":
    unittest.main()
