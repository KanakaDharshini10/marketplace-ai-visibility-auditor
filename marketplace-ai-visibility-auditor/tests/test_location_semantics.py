"""Location semantics: a "location" is only a store when the evidence says so.

A live audit of a documentation site reported that its shops existed nowhere
as machine-readable entities. It has no shops. It has a conference with a
venue, a jobs page listing the cities it hires in, and a directory of user
groups - and the rule fired on a link labelled "Locations" alone. Every
fixture here is a shape a site of any kind can take; none is that site, and
nothing in the rule matches its paths or its vocabulary as an exception.

The rule now needs a *fetched* page that presents itself as being about
places and carries the shape of visitable places - street addresses, or a
telephone number with opening hours, or several telephone numbers - and not
an event, a job listing or an article. A link whose target the crawl never read is recorded as not
assessed, never as a store.

Run just this file:

    python3 tests/run_tests.py location_semantics -v
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, find, html_doc, page, run, specialist

RULE = "EN-LOCATIONS-UNSTRUCTURED"


def _home(*links: str) -> dict:
    body = "<h1>Kestrel</h1><nav>" + "".join(links) + "</nav><p>Welcome.</p>"
    return page(ORIGIN + "/", html_doc(title="Kestrel", body=body))


def _finding(pages):
    return find(run("entity-audit", bundle(pages)), RULE)


# ---------------------------------------------------------------------------
# positive: places you can turn up at
# ---------------------------------------------------------------------------

class TestVisitableLocationsAreReported(unittest.TestCase):
    def test_retail_store_locator(self):
        locator = page(ORIGIN + "/stores", html_doc(title="Our stores", body=(
            "<main><h1>Our stores</h1>"
            "<p>Bristol - 14 Park Row. Tel 0117 496 0123. Mon-Sat 9:00-17:30.</p>"
            "<p>Leeds - 3 Briggate. Tel 0113 496 0456. Mon-Sat 9:00-18:00.</p>"
            "<p>Glasgow - 9 Buchanan St. Tel 0141 496 0789. Mon-Sat 9:30-17:30.</p>"
            "<p>York - 8 Stonegate. Tel 01904 496 0123. Mon-Sat 9:00-17:30.</p></main>")))
        found = _finding([_home('<a href="/stores">Find a store</a>'), locator,
                          page(ORIGIN + "/about", html_doc())])
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "high")
        self.assertIn(ORIGIN + "/stores", found.affected_urls)
        self.assertGreaterEqual(found.metrics["telephone_numbers_observed"], 3)

    def test_single_business_branch_with_hours(self):
        branch = page(ORIGIN + "/branch", html_doc(title="Visit us", body=(
            "<main><h1>Visit us</h1><p>Kestrel Bristol, 14 Park Row, BS1 5LJ. "
            "Tel 0117 496 0123. Opening hours: Monday to Saturday 9:00-17:30.</p></main>")))
        found = _finding([_home('<a href="/branch">Visit us</a>'), branch,
                          page(ORIGIN + "/about", html_doc())])
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "medium", "one branch is a narrower claim")

    def test_street_addresses_with_prose_hours_and_no_phone(self):
        """The bundled weak fixture's shape: three shops, addresses and hours
        in prose, not one telephone number. A locator does not need a phone
        to be a locator."""
        locator = page(ORIGIN + "/stores", html_doc(title="Our stores", body=(
            "<main><h2>Our stores</h2><p>Come and try a pair on.</p>"
            "<p>Bristol: 14 Park Row, open weekdays until six.</p>"
            "<p>Leeds: Unit 3, Merrion Centre, open weekdays until six.</p>"
            "<p>Glasgow: 208 Sauchiehall Street, open weekdays until five thirty.</p></main>")))
        found = _finding([_home('<a href="/stores">Our stores</a>'), locator,
                          page(ORIGIN + "/about", html_doc())])
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "high")
        self.assertGreaterEqual(found.metrics["street_addresses_observed"], 3)

    def test_a_declared_place_entity_still_settles_it(self):
        store = ('<script type="application/ld+json">{"@context":"https://schema.org",'
                 '"@type":"Store","name":"Kestrel Bristol","address":{"@type":"PostalAddress",'
                 '"addressLocality":"Bristol"}}</script>')
        locator = page(ORIGIN + "/stores", html_doc(title="Our stores", head=store, body=(
            "<main><h1>Our stores</h1><p>Bristol. Tel 0117 496 0123. Mon-Sat 9:00-17:30.</p>"
            "<p>Leeds. Tel 0113 496 0456. Mon-Sat 9:00-18:00.</p></main>")))
        self.assertIsNone(_finding([_home('<a href="/stores">Find a store</a>'), locator,
                                    page(ORIGIN + "/about", html_doc())]))


# ---------------------------------------------------------------------------
# negative: locations that are not places to shop
# ---------------------------------------------------------------------------

class TestOtherLocationsAreNotStores(unittest.TestCase):
    def test_event_venue(self):
        event = ('<script type="application/ld+json">{"@context":"https://schema.org",'
                 '"@type":"Event","name":"KestrelConf 2026","startDate":"2026-06-12",'
                 '"location":{"@type":"Place","name":"Riverside Convention Centre"}}</script>')
        venue = page(ORIGIN + "/conference/venue", html_doc(title="Venue", head=event, body=(
            "<main><h1>Venue and locations</h1><p>KestrelConf takes place at the Riverside "
            "Convention Centre, 12-14 June 2026. Registration desk: 0117 496 0123. "
            "Doors open Friday 8:30-18:00.</p></main>")))
        # Even with a phone and hours on the page, a declared Event is about
        # the event; its venue is not a shop the brand runs.
        self.assertIsNone(_finding([_home('<a href="/conference/venue">Locations</a>'), venue,
                                    page(ORIGIN + "/about", html_doc())]))

    def test_job_locations(self):
        jobs = page(ORIGIN + "/jobs/locations", html_doc(title="Where we hire", body=(
            "<main><h1>Locations</h1><p>We hire in Bristol, Leeds, Glasgow, Berlin and "
            "remote. Browse open roles and apply online.</p>"
            "<ul><li>Senior engineer - Bristol</li><li>Designer - remote</li></ul></main>")))
        self.assertIsNone(_finding([_home('<a href="/jobs/locations">Locations</a>'), jobs,
                                    page(ORIGIN + "/about", html_doc())]))

    def test_geographic_article(self):
        article = ('<script type="application/ld+json">{"@context":"https://schema.org",'
                   '"@type":"Article","headline":"The best locations for a winter walk"}</script>')
        post = page(ORIGIN + "/blog/winter-walk-locations", html_doc(
            title="The best locations for a winter walk", head=article, body=(
                "<main><h1>The best locations for a winter walk</h1><p>From the Quantocks "
                "to the Cairngorms, our pick of the country's finest walking locations. "
                "Park at the visitor centre (open 9:00-17:00) and follow the marked trail; "
                "the ranger station is on 01643 496 0123.</p></main>")))
        self.assertIsNone(_finding([_home('<a href="/blog/winter-walk-locations">Locations</a>'),
                                    post, page(ORIGIN + "/about", html_doc())]))

    def test_service_area_page(self):
        area = page(ORIGIN + "/service-area", html_doc(title="Areas we serve", body=(
            "<main><h1>Areas we serve</h1><p>We install and repair across Bristol, Bath, "
            "Weston-super-Mare and North Somerset. Call 0117 496 0123 for a quote.</p></main>")))
        # One phone, no opening hours, no place presented: a service area is
        # not a set of locations a machine could be handed as entities.
        self.assertIsNone(_finding([_home('<a href="/service-area">Our locations</a>'), area,
                                    page(ORIGIN + "/about", html_doc())]))

    def test_ambiguous_location_link_whose_target_was_not_fetched(self):
        """The link alone establishes nothing, and is never counted as a store."""
        self.assertIsNone(_finding([_home('<a href="/locations">Locations</a>'),
                                    page(ORIGIN + "/about", html_doc()),
                                    page(ORIGIN + "/pages/faq", html_doc(title="FAQ"))]))

    def test_documentation_site_with_a_venue_and_a_jobs_page(self):
        """The shape that produced the false positive: no shop anywhere, and
        three pages that legitimately use the word."""
        venue = page(ORIGIN + "/events/venue", html_doc(title="Venue", body=(
            "<main><h1>Conference venue</h1><p>The 2026 conference is held at the "
            "Riverside Centre, 12-14 June.</p></main>")))
        jobs = page(ORIGIN + "/jobs", html_doc(title="Jobs", body=(
            "<main><h1>Jobs</h1><p>Open roles in our locations: Bristol, Berlin, remote. "
            "Apply online.</p></main>")))
        groups = page(ORIGIN + "/community/locations", html_doc(title="User groups", body=(
            "<main><h1>User groups by location</h1><ul><li>Bristol</li><li>Leeds</li>"
            "<li>Glasgow</li><li>Berlin</li></ul></main>")))
        self.assertIsNone(_finding([_home('<a href="/community/locations">Locations</a>'),
                                    venue, jobs, groups]))


# ---------------------------------------------------------------------------
# wording: observed, interpreted, and what is not measured
# ---------------------------------------------------------------------------

class TestLocationWording(unittest.TestCase):
    def test_no_claim_that_a_model_invents_an_address(self):
        locator = page(ORIGIN + "/stores", html_doc(title="Our stores", body=(
            "<main><h1>Our stores</h1><p>Bristol. Tel 0117 496 0123. Mon-Sat 9:00-17:30.</p>"
            "<p>Leeds. Tel 0113 496 0456. Mon-Sat 9:00-18:00.</p>"
            "<p>York. Tel 01904 496 0123. Mon-Sat 9:00-17:30.</p></main>")))
        found = _finding([_home('<a href="/stores">Find a store</a>'), locator,
                          page(ORIGIN + "/about", html_doc())])
        text = " ".join([found.evidence, found.interpretation or "",
                         found.suggested_action.mechanism or ""]).lower()
        for banned in ("hallucinat", "invented branch", "produces a plausible address",
                       "indistinguishable from a real one", "working from no location data"):
            self.assertNotIn(banned, text)
        self.assertIn("does not measure", text)
        self.assertNotIn("hallucination-risk", found.tags)

    def test_unfetched_locator_links_are_reported_as_not_counted(self):
        locator = page(ORIGIN + "/stores", html_doc(title="Our stores", body=(
            "<main><h1>Our stores</h1><p>Bristol. Tel 0117 496 0123. Mon-Sat 9:00-17:30.</p>"
            "<p>Leeds. Tel 0113 496 0456.</p><p>York. Tel 01904 496 0123.</p></main>")))
        found = _finding([_home('<a href="/stores">Find a store</a>',
                                '<a href="/dealers">Where to buy</a>'),
                          locator, page(ORIGIN + "/about", html_doc())])
        self.assertIsNotNone(found)
        self.assertEqual(found.metrics["unassessed_location_links"], 1)
        self.assertIn("not counted", found.evidence)


if __name__ == "__main__":
    unittest.main()
