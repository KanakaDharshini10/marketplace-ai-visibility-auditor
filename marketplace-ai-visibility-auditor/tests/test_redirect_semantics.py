"""A redirect is an event; several different site behaviours produce one.

Reading only the destination cannot tell them apart, and three rules each read
it their own way: a single intentional hop was reported as a duplicate host, a
broken deep link and a chain defect at once. What separates them is the
relationship between the requested URL, the hops and the destination - scheme,
host, market segment, and the path that survives.

The cases below are the ones the brief enumerates, each as a deterministic
fixture on a synthetic host, plus the downstream question that matters: which
finding, if any, does each produce.
"""

from __future__ import annotations

import unittest

from helpers import bundle, find, html_doc, page, rule_ids, run
from aiva.analysis import classify_redirect, redirect_index

SITE = "https://www.wexford-tools.example"


def redirected(url: str, final: str, hops=None, canonical: str = "") -> dict:
    """A page fact bag carrying only what the classifier reads."""
    facts = {
        "url": url, "final_url": final, "status": 200, "page_type": "other",
        "content_type": "text/html", "bytes": 100, "elapsed_ms": 10, "headers": {},
        "redirects": [{"status": 301, "location": loc} for loc in (hops or [final])],
        "fetch_reason": "test fixture",
    }
    if canonical:
        facts["canonical"] = canonical
    return facts


class TestTheSevenCases(unittest.TestCase):
    """One assertion per case in the brief, on the same synthetic host."""

    def test_a_intentional_redirect_to_the_canonical_host(self):
        verdict = classify_redirect(redirected(
            "http://wexford-tools.example/products/clamp-40",
            "https://www.wexford-tools.example/products/clamp-40",
            ["https://wexford-tools.example/products/clamp-40",
             "https://www.wexford-tools.example/products/clamp-40"]))
        self.assertEqual(verdict["kind"], "canonical_host")
        self.assertTrue(verdict["path_preserved"])
        self.assertTrue(verdict["scheme_upgraded"])

    def test_b_intentional_geographic_redirect(self):
        verdict = classify_redirect(redirected(
            SITE + "/products/clamp-40", SITE + "/in/en/products/clamp-40"))
        self.assertEqual(verdict["kind"], "locale")
        self.assertTrue(verdict["path_preserved"])

    def test_b_a_market_selector_between_front_doors(self):
        verdict = classify_redirect(redirected(SITE + "/", SITE + "/in/en/"))
        self.assertIn(verdict["kind"], ("locale", "canonical_host"))
        self.assertNotEqual(verdict["kind"], "homepage_collapse")

    def test_c_a_multi_hop_chain_is_counted_and_characterised(self):
        verdict = classify_redirect(redirected(
            SITE + "/us/shop/goto/buy_clamp", SITE + "/shop/buy-clamp",
            [SITE + "/us/shop/go/buy_clamp", SITE + "/shop/buy-clamp"]))
        self.assertEqual(verdict["hops"], 2)
        self.assertEqual(verdict["kind"], "canonical_representation")

    def test_d_an_arbitrary_deep_url_collapsing_to_the_home_page(self):
        verdict = classify_redirect(redirected(
            SITE + "/ae-ar/partners/directory/api/search", SITE + "/"))
        self.assertEqual(verdict["kind"], "homepage_collapse")

    def test_d_collapsing_to_a_market_root_is_the_same_defect(self):
        """`/in/en/` is a front door too. A deep path that ends there served
        no more of what it promised than one ending at `/`."""
        verdict = classify_redirect(redirected(SITE + "/deep/page", SITE + "/in/en/"))
        self.assertEqual(verdict["kind"], "homepage_collapse")

    def test_f_a_redirect_to_an_unrelated_destination(self):
        verdict = classify_redirect(redirected(
            SITE + "/products/clamp-40", SITE + "/blog/company-news"))
        self.assertEqual(verdict["kind"], "unrelated")

    def test_g_the_destination_is_the_canonical_representation(self):
        for requested, final in (
                (SITE + "/products/clamp-40", SITE + "/products/clamp-40/"),
                (SITE + "/products/clamp-40.html", SITE + "/products/clamp-40"),
                (SITE + "/Products/Clamp-40", SITE + "/products/clamp-40"),
                (SITE + "/products/clamp-40/index.html", SITE + "/products/clamp-40/")):
            with self.subTest(requested=requested):
                self.assertEqual(
                    classify_redirect(redirected(requested, final))["kind"],
                    "canonical_representation")

    def test_g_the_page_declares_the_destination_as_its_canonical(self):
        verdict = classify_redirect(redirected(
            SITE + "/p/c40", SITE + "/shop/clamp-40",
            canonical="/shop/clamp-40"))
        self.assertEqual(verdict["kind"], "canonical_representation")

    def test_no_redirect_is_not_a_redirect(self):
        verdict = classify_redirect({"url": SITE + "/x", "final_url": SITE + "/x",
                                     "redirects": []})
        self.assertEqual(verdict["kind"], "none")


class TestOnlyACollapseIsReportedAsOne(unittest.TestCase):
    """The deep-link rule owns exactly one interpretation.

    Every case below is a redirect. Only one of them is a page that promised a
    resource and served a front door, and only that one may produce
    `EG-DEEPLINK-REDIRECTED-HOME`.
    """

    def _rules(self, page_facts) -> list:
        home = page(SITE + "/", html_doc(title="Wexford Tools", canonical=SITE + "/",
                                         body="<h1>Wexford Tools</h1>"))
        return rule_ids(run("engagement-audit", bundle([home, page_facts], origin=SITE)))

    def test_a_canonical_host_redirect_produces_no_deep_link_finding(self):
        self.assertNotIn("EG-DEEPLINK-REDIRECTED-HOME", self._rules(redirected(
            "http://wexford-tools.example/products/clamp-40",
            "https://www.wexford-tools.example/products/clamp-40")))

    def test_a_locale_redirect_produces_no_deep_link_finding(self):
        self.assertNotIn("EG-DEEPLINK-REDIRECTED-HOME", self._rules(redirected(
            SITE + "/products/clamp-40", SITE + "/in/en/products/clamp-40")))

    def test_a_route_change_produces_no_deep_link_finding(self):
        self.assertNotIn("EG-DEEPLINK-REDIRECTED-HOME", self._rules(redirected(
            SITE + "/us/shop/goto/buy_clamp", SITE + "/shop/buy-clamp",
            [SITE + "/us/shop/go/buy_clamp", SITE + "/shop/buy-clamp"])))

    def test_a_collapse_does_produce_it(self):
        """The rule has to survive: this is what it is for."""
        self.assertIn("EG-DEEPLINK-REDIRECTED-HOME", self._rules(redirected(
            SITE + "/ae-ar/partners/directory/api/search", SITE + "/")))


class TestOneEventIsOneFinding(unittest.TestCase):
    """A chain that collapses is one defect, not two.

    The collapse is what went wrong; the hop count is incidental to it. Two
    headings for one redirect means two severities, two entries in the
    prioritized plan and a pillar scored twice for one mistake.
    """

    def _both(self, page_facts) -> tuple:
        home = page(SITE + "/", html_doc(title="Wexford Tools", canonical=SITE + "/",
                                         body="<h1>Wexford Tools</h1>"))
        data = bundle([home, page_facts], origin=SITE)
        return (rule_ids(run("crawl-render-audit", data)),
                rule_ids(run("engagement-audit", data)))

    def test_a_collapsing_chain_is_reported_only_as_a_collapse(self):
        crawl, engagement = self._both(redirected(
            SITE + "/products/retired-clamp", SITE + "/",
            [SITE + "/products/clamp-legacy", SITE + "/"]))
        self.assertIn("EG-DEEPLINK-REDIRECTED-HOME", engagement)
        self.assertNotIn("CR-REDIRECT-CHAINS", crawl)

    def test_a_chain_that_is_not_a_collapse_is_still_reported(self):
        """Suppression stays narrow: the chain rule keeps its own case."""
        crawl, engagement = self._both(redirected(
            SITE + "/us/shop/goto/buy_clamp", SITE + "/shop/buy-clamp",
            [SITE + "/us/shop/go/buy_clamp", SITE + "/shop/buy-clamp"]))
        self.assertIn("CR-REDIRECT-CHAINS", crawl)
        self.assertNotIn("EG-DEEPLINK-REDIRECTED-HOME", engagement)

    def test_the_chain_finding_says_what_the_hops_are(self):
        home = page(SITE + "/", html_doc(title="Wexford Tools", canonical=SITE + "/"))
        data = bundle([home, redirected(
            "http://wexford-tools.example/products/clamp-40",
            "https://www.wexford-tools.example/products/clamp-40",
            ["https://wexford-tools.example/products/clamp-40",
             "https://www.wexford-tools.example/products/clamp-40"])], origin=SITE)
        found = find(run("crawl-render-audit", data), "CR-REDIRECT-CHAINS")
        self.assertIsNotNone(found)
        self.assertIn("canonical host", found.evidence)
        self.assertIn("the destination is right", found.evidence)
        self.assertEqual(found.metrics.get("redirect_kinds"), {"canonical_host": 1})


class TestDownstreamReadsTheNormalisedEvidence(unittest.TestCase):

    def test_the_index_classifies_every_redirected_page_once(self):
        pages = [
            redirected(SITE + "/a/x", SITE + "/in/en/a/x"),
            redirected(SITE + "/b/y", SITE + "/"),
            redirected(SITE + "/c/z", SITE + "/c/z/"),
        ]
        index = redirect_index(bundle(pages, origin=SITE))
        self.assertEqual(
            {url.rsplit("/", 2)[-2]: v["kind"] for url, v in index.items()},
            {"a": "locale", "b": "homepage_collapse", "c": "canonical_representation"})

    def test_a_page_with_no_redirect_is_absent_from_the_index(self):
        plain = page(SITE + "/products/clamp-40",
                     html_doc(title="Clamp 40", canonical=SITE + "/products/clamp-40"))
        self.assertEqual(redirect_index(bundle([plain], origin=SITE)), {})


if __name__ == "__main__":
    unittest.main()
