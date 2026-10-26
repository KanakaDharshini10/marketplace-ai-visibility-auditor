"""Canonical findings are made about content pages, chosen by page evidence.

A canonical URL is a statement a *content* document makes about which
address identifies it. A search endpoint, an application surface, a page the
classifier could not place, a page that asked not to be indexed, or a URL
that redirected onto another page's document has no such statement to make,
and its missing canonical is not evidence about the site's canonicalisation.
On a live audit two such pages were counted, and the ratio that followed
described a template defect the content pages did not have.

Eligibility is decided from what the crawl recorded about each page - its
classified type, its robots directives, how it was reached - and never from
the shape of its URL. Each class the brief names has a test here, and the
finding's own evidence says how many pages were set aside and why.
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, find, html_doc, page, run
from aiva.analysis import redirect_index

SPECIALIST = "crawl-render-audit"


def _content(path: str, title: str, body: str, *, canonical=None, head: str = "",
             page_type: str = None, **kwargs) -> dict:
    facts = page(ORIGIN + path, html_doc(title=title, body=body, canonical=canonical,
                                         head=head), **kwargs)
    if page_type:
        facts["page_type"] = page_type
    return facts


def _eligibility(findings, rule="CR-CANONICAL-MISSING"):
    return find(findings, rule)


class TestEligibilityByPageClass(unittest.TestCase):
    """Each class the brief names, one at a time, against a control set."""

    def _control(self):
        # Three content pages, none with a canonical: the finding fires on
        # them, and the question is whether the page under test joins them.
        return [
            _content("/products/kettle", "Kettle | Halstow", "<h1>Kettle</h1><p>£20 in stock</p>"
                     "<form action='/cart/add'><button>Add</button></form>"),
            _content("/collections/kettles", "Kettles | Halstow",
                     "<h1>Kettles</h1>" + "".join(
                         f'<a href="/products/k{i}">Kettle K{i} £20</a>' for i in range(6))),
            _content("/pages/returns", "Returns | Halstow",
                     "<h1>Returns</h1><p>Free returns within 30 days.</p>"),
        ]

    def _cited(self, extra: dict) -> tuple:
        pages = self._control() + [extra]
        item = _eligibility(run(SPECIALIST, bundle(pages)))
        self.assertIsNotNone(item)
        return item, {e.url for e in item.evidence_items}

    def test_a_navigation_endpoint_is_not_assessed(self):
        # A search results page: a query endpoint, not a content document.
        endpoint = _content("/search", "Search | Halstow",
                            "<h1>Search</h1><form action='/search'><input name='q'></form>")
        self.assertEqual(endpoint["page_type"], "search")
        item, cited = self._cited(endpoint)
        self.assertNotIn(endpoint["url"], cited)
        self.assertNotIn(endpoint["url"], item.affected_urls)
        self.assertEqual(item.metrics["sampled"], 3)
        self.assertEqual(item.metrics["not_assessed"], 1)
        self.assertIn("a search endpoint, not a content page", item.evidence)

    def test_a_genuine_product_page_is_assessed(self):
        item, cited = self._cited(_content(
            "/products/toaster", "Toaster | Halstow",
            "<h1>Toaster</h1><p>£30 in stock</p>"
            "<form action='/cart/add'><button>Add</button></form>"))
        self.assertIn(ORIGIN + "/products/toaster", item.affected_urls)
        self.assertEqual(item.metrics["sampled"], 4)
        self.assertIn("product", item.metrics["eligible_types"])

    def test_a_genuine_category_page_is_assessed(self):
        item, cited = self._cited(_content(
            "/collections/toasters", "Toasters | Halstow",
            "<h1>Toasters</h1>" + "".join(
                f'<a href="/products/t{i}">Toaster T{i} £30</a>' for i in range(6))))
        self.assertIn(ORIGIN + "/collections/toasters", item.affected_urls)
        self.assertIn("category", item.metrics["eligible_types"])

    def test_a_policy_page_is_assessed(self):
        item, cited = self._cited(_content(
            "/pages/shipping", "Shipping | Halstow",
            "<h1>Shipping</h1><p>We deliver across the UK in 2-3 days.</p>"))
        self.assertIn(ORIGIN + "/pages/shipping", item.affected_urls)
        self.assertIn("policy", item.metrics["eligible_types"])

    def test_a_redirect_target_is_not_assessed(self):
        # /old-kettle was requested; the site answered with the home page.
        # The document fetched is the home page's, so /old-kettle's canonical
        # is nobody's statement.
        collapsed = _content("/old-kettle", "Halstow", "<h1>Halstow</h1><p>Welcome.</p>",
                             redirects=[(301, ORIGIN + "/")])
        collapsed["final_url"] = ORIGIN + "/"
        collapsed["page_type"] = "home"
        data = bundle(self._control() + [collapsed])
        self.assertEqual(redirect_index(data)[collapsed["url"]]["kind"], "homepage_collapse")
        item = _eligibility(run(SPECIALIST, data))
        self.assertIsNotNone(item)
        self.assertNotIn(collapsed["url"], item.affected_urls)
        self.assertIn("redirected elsewhere (homepage_collapse)", item.evidence)

    def test_an_address_normalising_redirect_is_still_the_pages_own_document(self):
        normalised = _content("/products/toaster", "Toaster | Halstow",
                              "<h1>Toaster</h1><p>£30 in stock</p>"
                              "<form action='/cart/add'><button>Add</button></form>",
                              redirects=[(301, ORIGIN + "/products/toaster/")])
        normalised["final_url"] = ORIGIN + "/products/toaster/"
        data = bundle(self._control() + [normalised])
        item = _eligibility(run(SPECIALIST, data))
        self.assertIn(normalised["url"], item.affected_urls)

    def test_an_ambiguous_page_is_not_assessed(self):
        ambiguous = _content("/x/7f3a", "Halstow", "<p>3 items</p>")
        ambiguous["page_type"] = "other"
        item, cited = self._cited(ambiguous)
        self.assertNotIn(ambiguous["url"], item.affected_urls)
        self.assertIn("page type 'other' is not an established content type", item.evidence)

    def test_a_noindexed_content_page_is_not_assessed(self):
        excluded = _content("/pages/press-kit", "Press kit | Halstow",
                            "<h1>Press kit</h1><p>Logos and photography.</p>",
                            head='<meta name="robots" content="noindex">')
        item, cited = self._cited(excluded)
        self.assertNotIn(excluded["url"], item.affected_urls)
        self.assertIn("noindex directive", item.evidence)


class TestTheRatioIsOverEligiblePagesOnly(unittest.TestCase):

    def test_ineligible_pages_cannot_create_or_inflate_the_finding(self):
        # Two content pages with canonicals, three endpoints without: no
        # canonical finding, because no content page lacks one.
        content = [
            page(ORIGIN + "/products/kettle", html_doc(
                title="Kettle | Halstow", canonical=ORIGIN + "/products/kettle",
                body="<h1>Kettle</h1><p>£20 in stock</p>"
                     "<form action='/cart/add'><button>Add</button></form>")),
            page(ORIGIN + "/pages/returns", html_doc(
                title="Returns | Halstow", canonical=ORIGIN + "/pages/returns",
                body="<h1>Returns</h1><p>Free returns within 30 days.</p>")),
        ]
        endpoints = []
        for i in range(3):
            facts = page(ORIGIN + f"/search?q={i}", html_doc(
                title="Search | Halstow", body="<h1>Search</h1>"))
            facts["page_type"] = "search"
            endpoints.append(facts)
        findings = run(SPECIALIST, bundle(content + endpoints))
        self.assertIsNone(find(findings, "CR-CANONICAL-MISSING"))
        self.assertIsNone(find(findings, "CR-CANONICAL-WRONG-TARGET"))

    def test_a_wrong_target_on_an_endpoint_is_not_reported(self):
        content = [
            page(ORIGIN + "/products/kettle", html_doc(
                title="Kettle | Halstow", canonical=ORIGIN + "/products/kettle",
                body="<h1>Kettle</h1><p>£20 in stock</p>"
                     "<form action='/cart/add'><button>Add</button></form>")),
            page(ORIGIN + "/pages/returns", html_doc(
                title="Returns | Halstow", canonical=ORIGIN + "/pages/returns",
                body="<h1>Returns</h1><p>Free returns within 30 days.</p>")),
        ]
        tool = page(ORIGIN + "/compare", html_doc(title="Compare | Halstow",
                                                  canonical="https://elsewhere.example/",
                                                  body="<h1>Compare</h1>"))
        tool["page_type"] = "tool"
        findings = run(SPECIALIST, bundle(content + [tool]))
        self.assertIsNone(find(findings, "CR-CANONICAL-WRONG-TARGET"))

    def test_a_wrong_target_on_a_content_page_is_still_reported(self):
        content = [
            page(ORIGIN + "/products/kettle", html_doc(
                title="Kettle | Halstow", canonical=ORIGIN + "/",
                body="<h1>Kettle</h1><p>£20 in stock</p>"
                     "<form action='/cart/add'><button>Add</button></form>")),
            page(ORIGIN + "/pages/returns", html_doc(
                title="Returns | Halstow", canonical=ORIGIN + "/pages/returns",
                body="<h1>Returns</h1><p>Free returns within 30 days.</p>")),
        ]
        item = find(run(SPECIALIST, bundle(content)), "CR-CANONICAL-WRONG-TARGET")
        self.assertIsNotNone(item)
        self.assertEqual(item.affected_urls, [ORIGIN + "/products/kettle"])
        self.assertIn("collapses a deep page onto the home page", item.evidence_items[0].observation)


if __name__ == "__main__":
    unittest.main()
