"""Report assembly, scoring, prioritisation, projections and schema validation."""

from __future__ import annotations

import json
import unittest

import helpers
from helpers import bundle, commerce_bundle, error_page, html_doc, page
from aiva import findings as findings_mod, prioritize, recommend, report as report_mod, scoring
from aiva.config import AuditConfig
from aiva.findings import EvidenceItem, Finding, SuggestedAction, finding_from_dict


def make_finding(rule_id="X-1", severity="high", pillar="crawl_render", *,
                 items=None, effort="medium", scope="template",
                 priority="high", confidence=0.9) -> Finding:
    return Finding(
        rule_id=rule_id, title=f"title for {rule_id}", severity=severity, pillar=pillar,
        confidence=confidence,
        evidence="something observable was observed",
        suggested_action=SuggestedAction(summary="do the thing", priority=priority,
                                         mechanism="because machines read text",
                                         steps=["step one"], effort=effort,
                                         verification="check it"),
        evidence_items=items if items is not None else [
            EvidenceItem(observation="observed a thing", url=helpers.ORIGIN + "/x")],
        affected_urls=[helpers.ORIGIN + "/x"],
        metrics={"scope": scope},
    )


class TestReportBuild(unittest.TestCase):
    def setUp(self):
        self.bundle = bundle([page(helpers.ORIGIN + "/",
                                   html_doc(canonical=helpers.ORIGIN + "/",
                                            body="<h1>Home</h1>"))])
        self.config = AuditConfig(site=helpers.ORIGIN)

    def build(self, findings, **kwargs):
        return report_mod.build_report(self.bundle, findings, self.config, **kwargs)

    def test_required_floor_is_present(self):
        report = self.build([make_finding()])
        for field in ("site", "audited_at", "summary", "findings"):
            self.assertIn(field, report)
        for field in ("total_findings", "critical", "high", "medium"):
            self.assertIn(field, report["summary"])
        finding = report["findings"][0]
        for field in ("id", "title", "severity", "evidence", "suggested_action"):
            self.assertIn(field, finding)

    def test_ids_are_sequential_in_priority_order(self):
        report = self.build([make_finding("A", severity="low"),
                             make_finding("B", severity="critical")])
        self.assertEqual([f["id"] for f in report["findings"]], ["F-001", "F-002"])
        self.assertEqual(report["findings"][0]["rule_id"], "B")

    def test_findings_without_evidence_are_rejected_not_emitted(self):
        report = self.build([make_finding("GOOD"), make_finding("BAD", items=[])])
        self.assertEqual([f["rule_id"] for f in report["findings"]], ["GOOD"])
        self.assertEqual(report["diagnostics"]["rejected_finding_count"], 1)
        self.assertIn("no evidence items",
                      " ".join(report["diagnostics"]["rejected_findings"][0]["reasons"]))

    def test_duplicate_rule_ids_are_merged(self):
        one = make_finding("DUP")
        two = make_finding("DUP")
        two.affected_urls = [helpers.ORIGIN + "/y"]
        report = self.build([one, two])
        self.assertEqual(len(report["findings"]), 1)
        self.assertEqual(report["findings"][0]["affected_url_count"], 2)

    def test_summary_counts_match_findings(self):
        report = self.build([make_finding("A", severity="critical"),
                             make_finding("B", severity="high"),
                             make_finding("C", severity="medium"),
                             make_finding("D", severity="medium")])
        self.assertEqual(report["summary"]["total_findings"], 4)
        self.assertEqual(report["summary"]["critical"], 1)
        self.assertEqual(report["summary"]["medium"], 2)

    def test_validates_against_the_shipped_schema(self):
        report = self.build([make_finding("A", severity="critical"),
                             make_finding("B", severity="medium", pillar="engagement")])
        self.assertEqual(report_mod.validate_report(report), [])

    def test_validation_catches_a_tampered_summary(self):
        report = self.build([make_finding()])
        report["summary"]["critical"] = 99
        self.assertTrue(report_mod.validate_report(report))

    def test_both_dimensions_are_reported(self):
        report = self.build([make_finding("A", pillar="crawl_render"),
                             make_finding("B", pillar="engagement")])
        self.assertEqual(report["summary"]["by_dimension"],
                         {"discoverability": 1, "engagement": 1, "answerability": 0})

    def test_empty_audit_still_produces_a_valid_report(self):
        report = self.build([])
        self.assertEqual(report["summary"]["total_findings"], 0)
        self.assertEqual(report["summary"]["overall_score"], 100.0)
        self.assertEqual(report_mod.validate_report(report), [])
        self.assertTrue(report["proactive_recommendations"])


class TestProjections(unittest.TestCase):
    def setUp(self):
        self.report = report_mod.build_report(
            bundle([]), [make_finding("A", severity="critical")],
            AuditConfig(site=helpers.ORIGIN))

    def test_handout_projection_matches_the_brief_exactly(self):
        projected = report_mod.to_handout(self.report)
        self.assertEqual(sorted(projected), ["audited_at", "findings", "site", "summary"])
        self.assertEqual(sorted(projected["summary"]),
                         ["critical", "high", "info", "low", "medium", "total_findings"])
        finding = projected["findings"][0]
        self.assertEqual(sorted(finding),
                         ["evidence", "id", "severity", "suggested_action", "title"])
        self.assertIsInstance(finding["evidence"], str)
        self.assertEqual(sorted(finding["suggested_action"]), ["priority", "summary"])

    def test_flat_projection_uses_a_list_and_a_string(self):
        projected = report_mod.to_flat(self.report)
        finding = projected["findings"][0]
        self.assertIsInstance(finding["evidence"], list)
        self.assertIsInstance(finding["suggested_action"], str)

    def test_severity_buckets_sum_to_the_total_in_every_projection(self):
        """A summary whose numbers do not add up is indefensible.

        Regression: the handout projection reported total_findings=38 over
        buckets summing to 35, because low-severity findings were counted in
        the total and omitted from the breakdown.
        """
        report = report_mod.build_report(
            bundle([page(helpers.ORIGIN + "/",
                         html_doc(canonical=helpers.ORIGIN + "/", body="<h1>H</h1>"))]),
            [make_finding("A", severity="critical"), make_finding("B", severity="high"),
             make_finding("C", severity="medium"), make_finding("D", severity="low"),
             make_finding("E", severity="low"), make_finding("F", severity="info")],
            AuditConfig(site=helpers.ORIGIN))
        for variant in ("full", "handout", "flat"):
            summary = report_mod.project(report, variant)["summary"]
            buckets = sum(summary.get(s, 0) for s in
                          ("critical", "high", "medium", "low", "info"))
            self.assertEqual(buckets, summary["total_findings"],
                             f"{variant} projection: buckets {buckets} != total "
                             f"{summary['total_findings']}")

    def test_projections_are_json_serialisable(self):
        for variant in ("full", "handout", "flat"):
            json.dumps(report_mod.project(self.report, variant))


class TestScoringAndPriority(unittest.TestCase):
    def test_pillar_scores_drop_with_severity(self):
        clean = scoring.pillar_scores([])
        hurt = scoring.pillar_scores([make_finding(severity="critical")])
        self.assertEqual(clean["crawl_render"]["score"], 100.0)
        self.assertLess(hurt["crawl_render"]["score"], 60.0)

    def test_overall_covers_both_dimensions(self):
        pillars = scoring.pillar_scores([make_finding(pillar="engagement",
                                                      severity="critical")])
        overall = scoring.overall(pillars)
        self.assertLess(overall["engagement_score"], 60)
        self.assertEqual(overall["discoverability_score"], 100.0)
        self.assertEqual(overall["weakest_pillar"], "engagement")

    def test_cheap_sitewide_fix_outranks_expensive_page_fix(self):
        cheap = make_finding("CHEAP", severity="high", effort="low", scope="site")
        costly = make_finding("COSTLY", severity="high", effort="high", scope="page")
        ordered = prioritize.prioritize([costly, cheap])
        self.assertEqual(ordered[0].rule_id, "CHEAP")

    def test_priority_is_never_demoted_below_the_analyst_view(self):
        item = make_finding("X", severity="low", priority="high", effort="high", scope="page")
        prioritize.prioritize([item])
        self.assertEqual(item.suggested_action.priority, "high")

    def test_action_plan_shape(self):
        ordered = prioritize.prioritize([make_finding("A")])
        ordered[0].id = "F-001"
        plan = prioritize.action_plan(ordered)
        self.assertEqual(plan[0]["finding_id"], "F-001")
        self.assertIn("mechanism", plan[0])


class TestScoreIsDerivedNotAsserted(unittest.TestCase):
    """The score has to fall out of the findings, arithmetically and every time.

    A number a reader cannot reproduce is a number they cannot argue with, and
    an auditor whose score can be nudged by hand is not measuring anything. So
    these tests re-derive the arithmetic independently of the implementation:
    penalty from severity and confidence, pillar from penalties, overall from
    weighted pillars.
    """

    def _expected_penalty(self, severity: str, confidence: float) -> float:
        return (findings_mod.SEVERITY_WEIGHT[severity] * confidence
                * scoring.PENALTY_SCALE)

    def test_penalty_is_severity_times_confidence_times_scale(self):
        for severity, weight in findings_mod.SEVERITY_WEIGHT.items():
            for confidence in (1.0, 0.75, 0.5):
                item = make_finding(severity=severity, confidence=confidence)
                pillars = scoring.pillar_scores([item])
                expected = max(0.0, 100.0 - weight * confidence * scoring.PENALTY_SCALE)
                self.assertAlmostEqual(pillars["crawl_render"]["score"],
                                       round(expected, 1), places=1,
                                       msg=f"{severity} @ {confidence}")

    def test_pillar_penalties_accumulate(self):
        items = [make_finding("A", severity="high", confidence=1.0),
                 make_finding("B", severity="medium", confidence=1.0)]
        pillars = scoring.pillar_scores(items)
        expected = 100.0 - (self._expected_penalty("high", 1.0)
                            + self._expected_penalty("medium", 1.0))
        self.assertAlmostEqual(pillars["crawl_render"]["score"], round(expected, 1), places=1)

    def test_pillar_score_floors_at_zero(self):
        items = [make_finding(f"C{i}", severity="critical", confidence=1.0)
                 for i in range(4)]
        self.assertEqual(scoring.pillar_scores(items)["crawl_render"]["score"], 0.0)

    def test_overall_is_the_weighted_mean_of_the_pillars(self):
        items = [make_finding("A", pillar="crawl_render", severity="high", confidence=1.0),
                 make_finding("B", pillar="engagement", severity="medium", confidence=0.8),
                 make_finding("C", pillar="entity", severity="critical", confidence=1.0)]
        pillars = scoring.pillar_scores(items)
        weights = scoring.PILLAR_WEIGHTS
        expected = (sum(pillars[p]["score"] * weights[p] for p in weights)
                    / sum(weights.values()))
        self.assertAlmostEqual(scoring.overall(pillars)["score"],
                               round(expected, 1), places=1)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(scoring.PILLAR_WEIGHTS.values()), 1.0, places=6)

    def test_no_findings_is_exactly_one_hundred(self):
        self.assertEqual(scoring.overall(scoring.pillar_scores([]))["score"], 100.0)

    def test_band_boundaries_are_inclusive_lower_bounds(self):
        for threshold, name, _ in scoring.BANDS:
            self.assertEqual(scoring.band_for(float(threshold))[0], name)

    def test_score_is_reproducible_across_runs(self):
        items = [make_finding("A", severity="high"), make_finding("B", pillar="entity")]
        first = scoring.overall(scoring.pillar_scores(items))["score"]
        second = scoring.overall(scoring.pillar_scores(list(reversed(items))))["score"]
        self.assertEqual(first, second)

    def test_partial_sample_coverage_lowers_confidence_and_the_penalty(self):
        """A defect on 2 of 8 pages must not weigh the same as one on 8 of 8.

        Coverage feeds confidence, confidence multiplies the penalty, and the
        penalty sets the pillar score. This walks that whole chain rather than
        asserting the endpoint, so a change anywhere in it is caught.
        """
        from aiva.analysis import confidence_for
        partial = confidence_for(2, 8)
        universal = confidence_for(8, 8)
        self.assertLess(partial, universal)
        weak = scoring.pillar_scores(
            [make_finding(severity="high", confidence=partial)])["crawl_render"]["score"]
        strong = scoring.pillar_scores(
            [make_finding(severity="high", confidence=universal)])["crawl_render"]["score"]
        self.assertGreater(weak, strong, "a thinner sample must cost the site less")

    def test_confidence_is_a_deterministic_function_of_coverage(self):
        from aiva.analysis import confidence_for
        for affected, sampled in ((1, 1), (2, 8), (8, 8), (3, 12), (0, 4)):
            self.assertEqual(confidence_for(affected, sampled),
                             confidence_for(affected, sampled))
        # More of the sample affected, and a bigger sample, both raise it.
        self.assertLess(confidence_for(2, 8), confidence_for(6, 8))
        self.assertLess(confidence_for(2, 2), confidence_for(8, 8))

    def test_confidence_level_bands_are_fixed_thresholds(self):
        cases = ((0.95, "high"), (0.85, "high"), (0.84, "medium"),
                 (0.60, "medium"), (0.59, "low"), (0.35, "low"))
        for value, expected in cases:
            self.assertEqual(make_finding(confidence=value).confidence_level, expected,
                             f"confidence {value}")

    def test_sampling_basis_states_what_was_measured(self):
        sampled = make_finding()
        sampled.metrics = {"scope": "template", "affected": 3, "sampled": 12,
                           "sample_unit": "sampled product page(s)"}
        self.assertEqual(sampled.sampling["basis"], "3/12 sampled product page(s)")
        self.assertEqual(sampled.sampling["kind"], "sample")
        self.assertEqual(sampled.sampling["coverage"], 0.25)

        site_wide = make_finding()
        site_wide.metrics = {"scope": "site"}
        self.assertEqual(site_wide.sampling["basis"], "site-wide observation")
        self.assertEqual(site_wide.sampling["kind"], "site_wide")

        single = make_finding()
        single.metrics = {"scope": "page"}
        self.assertEqual(single.sampling["basis"], "single observation")

    def test_sampling_never_overstates_an_uncounted_sample(self):
        """`affected` absent must not be filled in with the sample size.

        A rule that counted 1 failure across 12 pages but only recorded the 12
        was being reported as "12/12", in the very field added to stop a small
        sample reading as a universal one.
        """
        item = make_finding()
        item.metrics = {"scope": "site", "failed": 1, "sampled": 12}
        self.assertEqual(item.sampling["basis"], "over 12 sampled page(s)")
        self.assertIsNone(item.sampling["affected"])
        self.assertIsNone(item.sampling["coverage"])

    def test_sampling_never_understates_a_scoped_observation(self):
        """A template-wide finding must not be described as one page."""
        item = make_finding()
        item.metrics = {"scope": "template", "no_h1": 6}
        self.assertEqual(item.sampling["basis"], "template-wide observation")
        item.metrics = {"scope": "section"}
        self.assertEqual(item.sampling["basis"],
                         "observed across a section of the site")

    def test_sampling_tolerates_non_integer_counts(self):
        item = make_finding()
        item.metrics = {"affected": "3", "sampled": 8.0}
        self.assertEqual(item.sampling["basis"], "3/8 sampled page(s)")
        item.metrics = {"affected": None, "sampled": "not a number"}
        self.assertEqual(item.sampling["kind"], "single")

    def test_every_reported_finding_carries_a_level_and_a_basis(self):
        from aiva.findings import CONFIDENCE_LEVELS
        report = report_mod.build_report(
            bundle([]), [make_finding("A", severity="high"),
                         make_finding("B", pillar="engagement", severity="medium")],
            AuditConfig(site=helpers.ORIGIN))
        for finding in report["findings"]:
            self.assertIn(finding["confidence_level"], CONFIDENCE_LEVELS)
            self.assertTrue(finding["sampling"]["basis"].strip())

    def test_reported_score_matches_a_recomputation_from_the_reported_findings(self):
        """End to end: rebuild the score from the emitted report and compare."""
        items = [make_finding("A", severity="high"),
                 make_finding("B", pillar="engagement", severity="medium"),
                 make_finding("C", pillar="freshness_corroboration", severity="low")]
        # A shop bundle, so every pillar including answerability is measured
        # and the recomputation below sees the same inputs the report did.
        data = commerce_bundle()
        report = report_mod.build_report(data, items, AuditConfig(site=helpers.ORIGIN))
        rebuilt = [findings_mod.finding_from_dict(f) for f in report["findings"]]
        for original, restored in zip(items, rebuilt):
            restored.pillar = original.pillar
            restored.confidence = original.confidence
        unmeasured = report["scores"]["overall"]["unmeasured_pillars"]
        self.assertEqual(unmeasured, [])
        recomputed = scoring.overall(scoring.pillar_scores(rebuilt, unmeasured))["score"]
        self.assertEqual(report["summary"]["overall_score"], recomputed)


class TestUnmeasuredPillars(unittest.TestCase):
    """"Nothing found" and "nothing looked at" must not produce the same number."""

    def test_a_pillar_with_no_evidence_scores_none_not_one_hundred(self):
        pillars = scoring.pillar_scores([], unmeasured=["engagement"])
        self.assertIsNone(pillars["engagement"]["score"])
        self.assertEqual(pillars["engagement"]["band"], "unmeasured")
        self.assertFalse(pillars["engagement"]["measured"])
        self.assertEqual(pillars["crawl_render"]["score"], 100.0)

    def test_unmeasured_pillars_are_excluded_from_the_weighted_mean(self):
        """Weights are renormalised, not reweighted: an unseen pillar neither
        inflates the total by counting as 100 nor deflates it by counting as 0."""
        findings = [make_finding("A", pillar="crawl_render", severity="critical",
                                 confidence=1.0)]
        unmeasured = [p for p in scoring.PILLAR_WEIGHTS if p != "crawl_render"]
        pillars = scoring.pillar_scores(findings, unmeasured=unmeasured)
        result = scoring.overall(pillars)
        self.assertEqual(result["score"], pillars["crawl_render"]["score"])
        self.assertEqual(result["measured_pillars"], ["crawl_render"])
        self.assertEqual(result["unmeasured_pillars"], sorted(unmeasured))
        self.assertIn("excluded rather than assumed sound", result["interpretation"])

    def test_nothing_measured_reports_no_score_at_all(self):
        pillars = scoring.pillar_scores([], unmeasured=list(scoring.PILLAR_WEIGHTS))
        result = scoring.overall(pillars)
        self.assertIsNone(result["score"])
        self.assertEqual(result["band"], "unmeasured")
        self.assertIsNone(result["discoverability_score"])

    def test_a_crawl_that_read_nothing_does_not_report_a_reassuring_score(self):
        """Regression: a zero-page crawl scored 72.4/"workable"."""
        empty = bundle([])
        report = report_mod.build_report(
            empty, [make_finding("A", pillar="crawl_render", severity="critical")],
            AuditConfig(site=helpers.ORIGIN))
        scores = report["scores"]["pillars"]
        for pillar in ("machine_readability", "entity", "engagement",
                       "freshness_corroboration"):
            self.assertIsNone(scores[pillar]["score"], pillar)
        self.assertLess(report["summary"]["overall_score"], 50)
        self.assertEqual(report_mod.validate_report(report), [])

    def test_a_normal_crawl_still_scores_every_pillar(self):
        report = report_mod.build_report(commerce_bundle(), [],
                                         AuditConfig(site=helpers.ORIGIN))
        for pillar, entry in report["scores"]["pillars"].items():
            self.assertIsNotNone(entry["score"], pillar)
            self.assertTrue(entry["measured"], pillar)
        self.assertEqual(report["summary"]["overall_score"], 100.0)


CAP_PHRASE = "readiness band is capped"


class TestReadinessBandRequiresCoverage(unittest.TestCase):
    """A band is a claim about the site; it needs most of the model behind it.

    Regression: renormalising over one measured pillar kept the arithmetic
    honest but left the *label* free. A crawl that read nothing scored 93.2 on
    a healthy robots.txt alone and was labelled "strong - machines can find,
    read, attribute and act on this site", about a site the auditor never read.
    The score is reported unchanged; only the band is capped.
    """

    def audit(self, data) -> dict:
        return report_mod.build_report(data, [], AuditConfig(site=helpers.ORIGIN))

    def test_zero_fetched_pages_cannot_be_called_strong(self):
        overall = self.audit(bundle([]))["scores"]["overall"]
        self.assertLess(overall["weight_measured"],
                        scoring.MIN_WEIGHT_FOR_CONFIDENT_BAND)
        self.assertGreaterEqual(overall["score"], 85)          # arithmetic unchanged
        self.assertEqual(overall["band"], scoring.BAND_CAP_WITHOUT_COVERAGE)
        self.assertIn(CAP_PHRASE, overall["interpretation"])

    def test_zero_readable_pages_cannot_be_called_strong(self):
        """Pages were fetched, but none parsed: same state, same cap."""
        data = bundle([error_page(helpers.ORIGIN + "/", status=500),
                       error_page(helpers.ORIGIN + "/a", status=500)])
        overall = self.audit(data)["scores"]["overall"]
        self.assertEqual(overall["measured_pillars"], ["crawl_render"])
        self.assertNotEqual(overall["band"], "strong")

    def test_the_score_itself_is_never_altered_by_the_cap(self):
        pillars = scoring.pillar_scores(
            [], unmeasured=[p for p in scoring.PILLAR_WEIGHTS if p != "crawl_render"])
        overall = scoring.overall(pillars)
        self.assertEqual(overall["score"], 100.0)
        self.assertEqual(overall["band"], scoring.BAND_CAP_WITHOUT_COVERAGE)
        self.assertEqual(scoring.band_for(overall["score"])[0], "strong")

    def test_error_pages_keep_the_band_the_score_already_earned(self):
        """The common error-page case already produced "weak"; it must not move.

        A site whose pages all return 403 lands below the cap on its own
        arithmetic. The cap only ever lowers a band, so this run is untouched
        and carries no capping note.
        """
        data = bundle([error_page(helpers.ORIGIN + "/", status=403),
                       error_page(helpers.ORIGIN + "/a", status=403)])
        findings = [make_finding("A", pillar="crawl_render", severity="critical",
                                 confidence=1.0),
                    make_finding("B", pillar="crawl_render", severity="high",
                                 confidence=1.0)]
        overall = report_mod.build_report(
            data, findings, AuditConfig(site=helpers.ORIGIN))["scores"]["overall"]
        self.assertLess(overall["score"], 85)
        self.assertEqual(overall["band"], scoring.band_for(overall["score"])[0])
        self.assertNotIn(CAP_PHRASE, overall["interpretation"])

    def test_a_healthy_crawl_is_banded_on_its_score_alone(self):
        overall = self.audit(commerce_bundle())["scores"]["overall"]
        self.assertEqual(overall["weight_measured"], 1.0)
        self.assertEqual(overall["band"], "strong")
        self.assertNotIn(CAP_PHRASE, overall["interpretation"])

    def test_the_cap_applies_exactly_below_the_coverage_threshold(self):
        """Boundary: at the threshold the band is earned, below it is capped."""
        half = ["crawl_render", "machine_readability", "engagement"]  # 0.578
        self.assertGreaterEqual(sum(scoring.PILLAR_WEIGHTS[p] for p in half),
                                scoring.MIN_WEIGHT_FOR_CONFIDENT_BAND)
        at = scoring.overall(scoring.pillar_scores(
            [], unmeasured=[p for p in scoring.PILLAR_WEIGHTS if p not in half]))
        self.assertEqual(at["band"], "strong")

        thin = ["crawl_render", "entity"]                              # 0.340
        self.assertLess(sum(scoring.PILLAR_WEIGHTS[p] for p in thin),
                        scoring.MIN_WEIGHT_FOR_CONFIDENT_BAND)
        below = scoring.overall(scoring.pillar_scores(
            [], unmeasured=[p for p in scoring.PILLAR_WEIGHTS if p not in thin]))
        self.assertEqual(below["band"], scoring.BAND_CAP_WITHOUT_COVERAGE)

    def test_a_band_worse_than_the_cap_is_never_raised_to_it(self):
        """The cap is a ceiling, not a floor: it must never flatter a run."""
        pillars = scoring.pillar_scores(
            [make_finding("A", pillar="crawl_render", severity="critical",
                          confidence=1.0)] * 3,
            unmeasured=[p for p in scoring.PILLAR_WEIGHTS if p != "crawl_render"])
        overall = scoring.overall(pillars)
        self.assertLess(overall["score"], 50)
        self.assertIn(overall["band"], ("poor", "critical"))
        self.assertNotIn(CAP_PHRASE, overall["interpretation"])


class TestAnswerabilityIsMeasuredOnlyWhenAsked(unittest.TestCase):
    """Zero questions evaluated is not a perfect score.

    Regression: `_unmeasured_pillars` only looked at whether pages parsed, so a
    site that raised no question - a docs or brochure site - scored
    answerability 100.0 off an empty matrix and carried 0.15 of free weight
    into the overall.
    """

    def docs_bundle(self) -> dict:
        return bundle([
            page(helpers.ORIGIN + "/", html_doc(
                title="Acme Docs", canonical=helpers.ORIGIN + "/",
                body='<h1>Acme Docs</h1><a href="/guide/install">Install</a>')),
            page(helpers.ORIGIN + "/guide/install", html_doc(
                title="Install", canonical=helpers.ORIGIN + "/guide/install",
                body="<h1>Install</h1><p>Run the installer.</p>")),
        ])

    def audit(self, data) -> dict:
        return report_mod.build_report(data, [], AuditConfig(site=helpers.ORIGIN))

    def test_zero_questions_leaves_the_pillar_unmeasured(self):
        report = self.audit(self.docs_bundle())
        self.assertEqual(report["answerability"]["total_questions"], 0)
        entry = report["scores"]["pillars"]["answerability"]
        self.assertIsNone(entry["score"])
        self.assertEqual(entry["band"], "unmeasured")
        self.assertFalse(entry["measured"])
        self.assertIn("answerability",
                      report["scores"]["overall"]["unmeasured_pillars"])

    def test_a_docs_site_is_not_charged_for_questions_it_never_raised(self):
        """Unmeasured is not zero either: the other pillars are untouched."""
        report = self.audit(self.docs_bundle())
        overall = report["scores"]["overall"]
        self.assertNotIn("answerability", overall["measured_pillars"])
        self.assertEqual(overall["weight_measured"],
                         round(1 - scoring.PILLAR_WEIGHTS["answerability"], 4))
        self.assertEqual(report_mod.validate_report(report), [])

    def test_an_ecommerce_site_measures_the_pillar(self):
        report = self.audit(commerce_bundle())
        self.assertGreater(report["answerability"]["total_questions"], 0)
        entry = report["scores"]["pillars"]["answerability"]
        self.assertIsNotNone(entry["score"])
        self.assertTrue(entry["measured"])
        self.assertEqual(report["scores"]["overall"]["unmeasured_pillars"], [])

    def test_the_overall_gets_no_free_points_from_an_unmeasured_pillar(self):
        """The defect that mattered: 0.15 of weight scoring 100 unearned.

        Compare the reported overall against the same run with answerability
        counted as a measured 100 - the old behaviour. It must be the lower,
        renormalised figure.
        """
        data = self.docs_bundle()
        findings = [make_finding("A", pillar="crawl_render", severity="critical",
                                 confidence=1.0)]
        report = report_mod.build_report(data, findings, AuditConfig(site=helpers.ORIGIN))
        reported = report["summary"]["overall_score"]

        measured = report["scores"]["overall"]["measured_pillars"]
        weight = sum(scoring.PILLAR_WEIGHTS[p] for p in measured)
        expected = sum(report["scores"]["pillars"][p]["score"]
                       * scoring.PILLAR_WEIGHTS[p] for p in measured) / weight
        self.assertEqual(reported, round(expected, 1))

        as_if_perfect = ((expected * weight
                          + 100.0 * scoring.PILLAR_WEIGHTS["answerability"])
                         / (weight + scoring.PILLAR_WEIGHTS["answerability"]))
        self.assertGreater(round(as_if_perfect, 1), reported)

    def test_an_empty_matrix_explains_itself_rather_than_scoring_silently(self):
        matrix = self.audit(self.docs_bundle())["answerability"]
        self.assertIsNone(matrix["answerability_score"])
        self.assertTrue(matrix["notes"])


class TestRecommendations(unittest.TestCase):
    def test_opportunities_are_gated_on_evidence(self):
        data = bundle([], llms_txt={"checked": True, "status": 200, "present": True,
                                    "url": helpers.ORIGIN + "/llms.txt"})
        ids = [o["id"] for o in recommend.build_opportunities(data, [])]
        self.assertNotIn("OPP-AI-DISCOVERY-SURFACE", ids)

    def test_agents_md_also_satisfies_the_agent_facing_index(self):
        """Two conventions exist; shipping either one solves the problem."""
        data = bundle([])
        data["well_known"]["ai_surfaces"] = {
            "llms_txt": {"url": helpers.ORIGIN + "/llms.txt", "checked": True,
                         "present": False, "status": 404},
            "agents_md": {"url": helpers.ORIGIN + "/agents.md", "checked": True,
                          "present": True, "status": 200, "link_count": 12},
        }
        ids = [o["id"] for o in recommend.build_opportunities(data, [])]
        self.assertNotIn("OPP-AI-DISCOVERY-SURFACE", ids)

    def test_agent_facing_index_recommended_when_neither_convention_exists(self):
        """Evidence-backed, so it needs a crawl that read something.

        `bundle([])` is a run with no pages — the transport-only shape — and a
        recommendation whose wording says "neither convention was served
        during this audit" has no business appearing there.
        """
        data = bundle([page(helpers.ORIGIN + "/", html_doc(title="Shop"))])
        ids = [o["id"] for o in recommend.build_opportunities(data, [])]
        self.assertIn("OPP-AI-DISCOVERY-SURFACE", ids)

    def test_a_refused_probe_does_not_recommend_publishing_the_file(self):
        """403 on /llms.txt means this request was turned away, not that no
        agent index exists — the same distinction robots.txt needed."""
        data = bundle([page(helpers.ORIGIN + "/", html_doc(title="Shop"))])
        data["well_known"]["ai_surfaces"] = {
            "llms_txt": {"url": helpers.ORIGIN + "/llms.txt", "checked": True,
                         "present": False, "status": 403},
            "agents_md": {"url": helpers.ORIGIN + "/agents.md", "checked": True,
                          "present": False, "status": 403},
        }
        ids = [o["id"] for o in recommend.build_opportunities(data, [])]
        self.assertNotIn("OPP-AI-DISCOVERY-SURFACE", ids)

    def test_opportunity_is_suppressed_when_a_finding_covers_it(self):
        covering = make_finding("EN-VARIANTS-UNMODELLED", pillar="entity")
        product = page(helpers.ORIGIN + "/products/x", html_doc(
            body='<h1>X</h1><p>£40. In stock.</p>'
                 '<select name="size"><option>8</option></select>'))
        data = bundle([product])
        with_finding = [o["id"] for o in recommend.build_opportunities(data, [covering])]
        without = [o["id"] for o in recommend.build_opportunities(data, [])]
        self.assertIn("OPP-PRODUCT-GROUP", without)
        self.assertNotIn("OPP-PRODUCT-GROUP", with_finding)

    def test_every_opportunity_states_a_mechanism_and_steps(self):
        for opportunity in recommend.build_opportunities(bundle([]), []):
            self.assertTrue(opportunity["mechanism"].strip(), opportunity["id"])
            self.assertTrue(opportunity["steps"], opportunity["id"])
            self.assertIn(opportunity["dimension"], ("discoverability", "engagement"))


class TestEvidenceReuseMetric(unittest.TestCase):
    """The reuse ratio measures the sharing of one crawl among the specialists.

    An earlier version published the transport cache's hit ratio under this
    name. On a real crawl every URL is fetched once by design, so that number
    was ~0.01 and read as "the specialists are not sharing evidence" - the
    opposite of what the architecture does. The cache figure is still
    reported, under its own name; the reuse ratio is now the share of the
    requests that N specialists crawling separately would have made and did
    not, computed from the run's own numbers.
    """

    def _runs(self, n: int) -> list:
        return [{"skill": f"s{i}", "status": "ok", "ok": True, "findings": 0}
                for i in range(n)]

    def test_ratio_measures_sharing_among_specialists(self):
        data = bundle([])
        data["stats"].update({"requests": 26, "cache_reuses": 0,
                              "duplicate_urls_collapsed": 74})
        report = report_mod.build_report(data, [], AuditConfig(site=helpers.ORIGIN),
                                         skill_runs=self._runs(6))
        reuse = report["diagnostics"]["evidence_reuse"]
        self.assertEqual(reuse["network_requests"], 26)
        self.assertEqual(reuse["specialists_served_from_the_bundle"], 6)
        self.assertEqual(reuse["requests_if_each_specialist_had_crawled"], 156)
        self.assertEqual(reuse["requests_avoided_by_sharing"], 130)
        self.assertEqual(reuse["shared_evidence_reuse_ratio"], 0.833)
        self.assertEqual(report["diagnostics"]["evidence_reuse_ratio"], 0.833)
        # The transport cache figure survives under its own name.
        self.assertEqual(reuse["transport_cache_hit_ratio"], 0.74)
        self.assertEqual(report["diagnostics"]["fetches_avoided"], 74)
        self.assertIn("definition", reuse)

    def test_ratio_is_deterministic_and_counts_only_completed_specialists(self):
        data = bundle([])
        data["stats"].update({"requests": 10, "cache_reuses": 0, "duplicate_urls_collapsed": 0})
        runs = self._runs(5) + [{"skill": "broken", "status": "failed", "ok": False,
                                 "findings": None, "error": "boom"}]
        first = report_mod.build_report(data, [], AuditConfig(site=helpers.ORIGIN), skill_runs=runs)
        second = report_mod.build_report(data, [], AuditConfig(site=helpers.ORIGIN), skill_runs=runs)
        self.assertEqual(first["diagnostics"]["evidence_reuse"],
                         second["diagnostics"]["evidence_reuse"])
        self.assertEqual(first["diagnostics"]["evidence_reuse"]
                         ["specialists_served_from_the_bundle"], 5)
        self.assertEqual(first["diagnostics"]["evidence_reuse_ratio"], 0.8)

    def test_ratio_is_zero_when_nothing_was_discovered(self):
        data = bundle([])
        data["stats"].update({"requests": 0, "cache_reuses": 0,
                              "duplicate_urls_collapsed": 0})
        report = report_mod.build_report(data, [], AuditConfig(site=helpers.ORIGIN))
        self.assertEqual(report["diagnostics"]["evidence_reuse_ratio"], 0.0)
        self.assertEqual(report["diagnostics"]["evidence_reuse"]["transport_cache_hit_ratio"], 0.0)

    def test_duplicate_evidence_entries_are_removed_deterministically(self):
        from aiva.findings import EvidenceItem, Finding, SuggestedAction
        item = EvidenceItem(observation="seen", url=helpers.ORIGIN + "/x", locator="body")
        finding = Finding(rule_id="DUP", title="t", severity="low", pillar="crawl_render",
                          evidence="seen twice",
                          suggested_action=SuggestedAction(summary="do", mechanism="m"),
                          evidence_items=[item, EvidenceItem(observation="seen",
                                                             url=helpers.ORIGIN + "/x",
                                                             locator="body"),
                                          EvidenceItem(observation="other",
                                                       url=helpers.ORIGIN + "/y")],
                          affected_urls=[helpers.ORIGIN + "/x", helpers.ORIGIN + "/x",
                                         helpers.ORIGIN + "/y"])
        report = report_mod.build_report(bundle([]), [finding], AuditConfig(site=helpers.ORIGIN))
        serialised = report["findings"][0]
        self.assertEqual(len(serialised["evidence_items"]), 2)
        self.assertEqual(serialised["affected_urls"], [helpers.ORIGIN + "/x", helpers.ORIGIN + "/y"])
        self.assertEqual(report["diagnostics"]["duplicate_evidence_entries_removed"], 2)
        again = report_mod.build_report(bundle([]), [finding], AuditConfig(site=helpers.ORIGIN))
        self.assertEqual(again["findings"][0]["evidence_items"], serialised["evidence_items"])
        # The Finding handed in is never edited: a second report over the same
        # objects removes the same duplicates again rather than finding none.
        self.assertEqual(again["diagnostics"]["duplicate_evidence_entries_removed"], 2)
        self.assertEqual(len(finding.evidence_items), 3)


class TestRoundTrip(unittest.TestCase):
    def test_finding_survives_serialisation(self):
        original = make_finding("RT", severity="medium")
        restored = finding_from_dict(original.to_dict())
        self.assertEqual(restored.rule_id, "RT")
        self.assertEqual(restored.severity, "medium")
        self.assertEqual(restored.suggested_action.mechanism,
                         original.suggested_action.mechanism)
        self.assertEqual(len(restored.evidence_items), len(original.evidence_items))

    def test_markdown_rendering_mentions_every_finding(self):
        report = report_mod.build_report(bundle([]), [make_finding("A"), make_finding("B")],
                                         AuditConfig(site=helpers.ORIGIN))
        markdown = report_mod.render_markdown(report)
        self.assertIn("F-001", markdown)
        self.assertIn("F-002", markdown)
        self.assertIn("Proactive recommendations", markdown)


if __name__ == "__main__":
    unittest.main()
