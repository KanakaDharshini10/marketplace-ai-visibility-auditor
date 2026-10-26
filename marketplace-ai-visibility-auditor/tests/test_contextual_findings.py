"""Findings follow the kind of thing a page is about, not its page type.

One module, one class per area the semantic refactor changed, each a
behavioural test against the specialists' own output: what fires, what
stays silent, what the evidence says, and what severity an absence of
optional metadata is allowed to carry. The unit-level decisions live in
test_semantics; the entity and recommendation contracts in their own
modules; the end-to-end run over the mixed fixture in test_semantic_fixture.

Areas covered here:

 1. commerce findings gated by product kind (shipping, returns, stock,
    physical specifications, reviews, identifiers, purchase controls);
 2. typed policy markup (MerchantReturnPolicy, OfferShippingDetails) and
    Offer availability asked only of goods they apply to;
 3. transport uncertainty: refusals, throttles, timeouts and server errors
    are "could not be verified", never a broken URL;
 4. sitemap wording: parsing failure versus not verified;
 5. cross-host canonicals as a review item, not a collapse;
 6. legitimate cross-domain redirects;
 7. page-type-aware freshness;
 8. contextual Organization fields;
 9. contextual Open Graph;
10. noindex wording;
11. heading semantics (multiple or zero h1 are not defects);
12. site search as an evidence-based expectation, SearchAction only where a
    search is evidenced;
13. answerability gated by what the site sells;
14. severity ceilings for optional metadata and thin samples;
15. endpoint classification before content findings;
16. coverage reporting of what was and was not applied.

Run just this file:

    python3 tests/run_tests.py contextual_findings -v
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, error_page, find, html_doc, jsonld, page, run, rule_ids

from aiva import report as report_mod
from aiva import semantics as S
from aiva.analysis import classify_redirect
from aiva.answerability import build_matrix
from aiva.config import AuditConfig

ORG_LD = ('{"@context":"https://schema.org","@type":"Organization","name":"Kestrel Ltd",'
          '"url":"%s/"}' % ORIGIN)
PHYSICAL_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"%s","sku":"%s",'
    '"color":"Brown","material":"Leather",'
    '"weight":{"@type":"QuantitativeValue","value":"1.1","unitCode":"KGM"},'
    '"offers":{"@type":"Offer","price":"%s","priceCurrency":"GBP"}}')
SOFTWARE_LD = (
    '{"@context":"https://schema.org","@type":"SoftwareApplication","name":"%s",'
    '"operatingSystem":"Windows, macOS","applicationCategory":"DeveloperApplication",'
    '"softwareVersion":"4.2","offers":{"@type":"Offer","price":"%s","priceCurrency":"USD"}}')
SUBSCRIPTION_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"%s",'
    '"description":"Team plan.","offers":{"@type":"Offer","priceCurrency":"USD",'
    '"priceSpecification":{"@type":"UnitPriceSpecification","price":"12",'
    '"priceCurrency":"USD","billingDuration":1,"billingIncrement":1,'
    '"referenceQuantity":{"@type":"QuantitativeValue","value":1,"unitCode":"MON"}}}}')
SERVICE_LD = (
    '{"@context":"https://schema.org","@type":"Service","name":"%s",'
    '"serviceType":"Heating maintenance","areaServed":"Bristol",'
    '"offers":{"@type":"Offer","price":"89","priceCurrency":"GBP"}}')
TECH_LD = ('{"@context":"https://schema.org","@type":"TechArticle","headline":"%s",'
           '"dateModified":"2026-05-01"}')
NEWS_LD = ('{"@context":"https://schema.org","@type":"NewsArticle","headline":"%s",'
           '"datePublished":"2026-05-01"}')

LONG = " ".join(["The page explains the subject in some detail."] * 30)


def _home(ld: str = ORG_LD, body: str = "<h1>Kestrel Ltd</h1>", **kw) -> dict:
    return page(ORIGIN + "/", html_doc(title="Kestrel Ltd", canonical=ORIGIN + "/",
                                       head=jsonld(ld), body=body + f"<p>{LONG}</p>", **kw))


def physical(path: str = "/products/trail-boot", name: str = "Trail Boot", price: str = "120",
             extra: str = "") -> dict:
    return page(ORIGIN + path, html_doc(
        title=name, canonical=ORIGIN + path, head=jsonld(PHYSICAL_LD % (name, name[:3], price)),
        body=f"<main><h1>{name}</h1><p>£{price}.</p>{extra}"
             f"<form action='/cart'><select name='size'><option>8</option><option>9</option>"
             f"</select><button>Add to cart</button></form><p>{LONG}</p></main>"))


def software(path: str = "/products/studio", name: str = "Kestrel Studio", price: str = "49",
             extra: str = "") -> dict:
    return page(ORIGIN + path, html_doc(
        title=name, canonical=ORIGIN + path, head=jsonld(SOFTWARE_LD % (name, price)),
        body=f"<main><h1>{name}</h1><p>${price} licence. Download the installer for Windows "
             f"or macOS. System requirements: 8 GB RAM. {extra}</p><p>{LONG}</p></main>"))


def subscription(path: str = "/products/cloud-team", name: str = "Kestrel Cloud Team") -> dict:
    return page(ORIGIN + path, html_doc(
        title=name, canonical=ORIGIN + path, head=jsonld(SUBSCRIPTION_LD % name),
        body=f"<main><h1>{name}</h1><p>$12 per user per month, billed annually. Free trial, "
             f"cancel anytime.</p><p>{LONG}</p></main>"))


def service(path: str = "/services/boiler-servicing", name: str = "Boiler servicing") -> dict:
    return page(ORIGIN + path, html_doc(
        title=name, canonical=ORIGIN + path, head=jsonld(SERVICE_LD % name),
        body=f"<main><h1>{name}</h1><p>From £89. Book an appointment or request a quote.</p>"
             f"<p>{LONG}</p></main>"))


def doc(path: str, title: str, body: str = "") -> dict:
    return page(ORIGIN + path, html_doc(
        title=title, canonical=ORIGIN + path, head=jsonld(TECH_LD % title),
        body=body or f"<main><h1>{title}</h1><p>{LONG}</p></main>"))


def news(path: str, title: str, body: str = "", **kw) -> dict:
    return page(ORIGIN + path, html_doc(
        title=title, canonical=ORIGIN + path, head=jsonld(NEWS_LD % title),
        body=body or f"<main><h1>{title}</h1><p>{LONG}</p></main>", **kw))


def docs_site(*extra: dict) -> dict:
    return bundle([_home(), doc("/docs/start", "Getting started"),
                   doc("/docs/config", "Configuration"), doc("/docs/deploy", "Deploying")]
                  + list(extra))


# ---------------------------------------------------------------------------
# 1. commerce findings are gated by the kind of item
# ---------------------------------------------------------------------------

class TestCommerceFindingsFollowTheKindOfItem(unittest.TestCase):

    def test_software_and_plans_are_not_asked_for_delivery_returns_or_stock(self):
        data = bundle([_home(), software(), subscription()])
        ids = rule_ids(run("engagement-audit", data))
        for rule in ("EG-SHIPPING-INVISIBLE", "EG-RETURNS-INVISIBLE",
                     "EG-AVAILABILITY-INVISIBLE", "EG-SPECS-MISSING", "EG-CTA-NOT-IN-HTML"):
            self.assertNotIn(rule, ids, rule)

    def test_a_service_page_is_not_a_product_expectation_either(self):
        data = bundle([_home(), service()])
        ids = rule_ids(run("engagement-audit", data))
        self.assertEqual({r for r in ids if r.startswith("EG-") and "INVISIBLE" in r}, set())

    def test_the_physical_page_on_a_mixed_site_is_still_held_to_them(self):
        data = bundle([_home(), physical(), software(), subscription()])
        findings = run("engagement-audit", data)
        returns = find(findings, "EG-RETURNS-INVISIBLE")
        self.assertIsNotNone(returns)
        self.assertEqual(returns.affected_urls, [ORIGIN + "/products/trail-boot"])
        self.assertEqual(returns.metrics["not_assessed"], 2)
        self.assertIn("does not apply to a software item", returns.evidence)
        self.assertIn("does not apply to a subscription item", returns.evidence)

    def test_reviews_are_expected_of_goods_and_software_but_not_services(self):
        data = bundle([_home(), physical(), software(), service()])
        found = find(run("engagement-audit", data), "EG-REVIEWS-ABSENT")
        self.assertIsNotNone(found)
        self.assertNotIn(ORIGIN + "/services/boiler-servicing", found.affected_urls)
        self.assertLessEqual(S._SEVERITY_ORDER.index(found.severity),
                             S._SEVERITY_ORDER.index(S.OPTIONAL_METADATA_CEILING))

    def test_the_applicability_engine_is_the_only_gate(self):
        """Every commerce rule asks the same functions, so the decision for
        a page is one decision, stated once."""
        ctx = S.site_context(bundle([_home(), software()]))
        page_ = software()
        for fn in (S.is_shipping_applicable, S.is_returns_applicable, S.is_stock_applicable,
                   S.is_physical_specs_applicable, S.is_identifier_applicable,
                   S.is_purchase_cta_applicable):
            verdict = fn(page_, ctx)
            self.assertFalse(verdict, fn.__name__)
            self.assertIn("software", verdict["reason"], fn.__name__)
        self.assertTrue(S.is_price_applicable(page_, ctx))
        self.assertTrue(S.is_reviews_applicable(page_, ctx))


# ---------------------------------------------------------------------------
# 2. typed policy and offer fields
# ---------------------------------------------------------------------------

class TestTypedPolicyMarkupIsAPhysicalGoodsExpectation(unittest.TestCase):

    def test_a_download_that_states_no_terms_is_not_asked_for_merchant_return_policy(self):
        """A licence page that never mentions delivery or returns owes no
        typed policy; it is set aside by kind, not asked and found wanting."""
        data = bundle([_home(), software(), subscription(),
                       physical(extra="<p>Free returns within 30 days. Delivery in 2-3 days.</p>")])
        found = find(run("engagement-audit", data), "EG-POLICY-NOT-STRUCTURED")
        self.assertIsNotNone(found)
        self.assertEqual(found.affected_urls, [ORIGIN + "/products/trail-boot"])
        self.assertIn("not assessed", found.evidence)
        self.assertIn("does not apply to a software item", found.evidence)

    def test_a_page_that_states_its_own_return_terms_is_held_to_them_whatever_it_sells(self):
        """The basis is what the page says. A download promising a 30-day
        refund has made returns its own concern, and the typed form of that
        promise is asked for - with the evidence saying why."""
        data = bundle([_home(), physical(extra="<p>Free returns within 30 days. Delivery "
                                               "in 2-3 days.</p>"),
                       software(extra="Not happy? Returns accepted within 30 days of purchase.")])
        found = find(run("engagement-audit", data), "EG-POLICY-NOT-STRUCTURED")
        self.assertIsNotNone(found)
        self.assertEqual(sorted(found.affected_urls),
                         sorted([ORIGIN + "/products/trail-boot", ORIGIN + "/products/studio"]))
        self.assertIn("pages that state such terms themselves", found.evidence)

    def test_offer_availability_is_asked_only_where_stock_applies(self):
        data = bundle([_home(), software(), subscription()])
        found = find(run("machine-readability-audit", data), "MR-OFFER-INCOMPLETE")
        if found is not None:
            self.assertNotIn("availability", found.metrics["missing_fields"])
        with_boot = bundle([_home(), physical(), software()])
        found = find(run("machine-readability-audit", with_boot), "MR-OFFER-INCOMPLETE")
        self.assertIsNotNone(found)
        self.assertIn("availability", found.metrics["missing_fields"])
        self.assertEqual(found.affected_urls, [ORIGIN + "/products/trail-boot"])
        self.assertIn("expected only of the pages selling physical goods", found.evidence)

    def test_identifiers_are_asked_of_physical_goods_only(self):
        data = bundle([_home(), software(), subscription()])
        self.assertIsNone(find(run("machine-readability-audit", data), "MR-IDENTIFIERS-MISSING"))


# ---------------------------------------------------------------------------
# 3. transport uncertainty
# ---------------------------------------------------------------------------

class TestTransportUncertainty(unittest.TestCase):

    def _site(self, *extra):
        home = _home(body="<h1>Kestrel Ltd</h1><a href='/docs/start'>Start</a>"
                          "<a href='/members'>Members</a><a href='/api/status'>Status</a>"
                          "<a href='/gone'>Gone</a>")
        return bundle([home, doc("/docs/start", "Getting started")] + list(extra))

    def test_every_refusal_kind_is_not_verified_and_only_404_is_broken(self):
        refused = error_page(ORIGIN + "/members", 403)
        throttled = error_page(ORIGIN + "/api/status", 429)
        gone = error_page(ORIGIN + "/gone", 404)
        for record in (refused, throttled, gone):
            record["fetch_reason"] = "linked from the home page"
        data = self._site(refused, throttled, gone)
        data["fetch_errors"] = [{"url": ORIGIN + "/docs/start", "error": "TimeoutError: timed out",
                                 "reason": "linked from the home page"}]
        findings = run("crawl-render-audit", data)
        broken = find(findings, "CR-HTTP-ERRORS")
        aside = find(findings, "CR-URLS-NOT-VERIFIED")
        self.assertEqual(broken.affected_urls, [ORIGIN + "/gone"])
        self.assertEqual(aside.severity, "info")
        self.assertEqual(sorted(aside.affected_urls),
                         sorted([ORIGIN + "/members", ORIGIN + "/api/status", ORIGIN + "/docs/start"]))
        for phrase in ("could not be verified", "says nothing about whether the page exists"):
            self.assertIn(phrase, aside.title + aside.evidence)
        self.assertNotIn("broken", aside.title.lower())

    def test_the_transport_verdict_vocabulary_is_shared(self):
        for status, expected in ((401, "unverified"), (403, "unverified"), (429, "unverified"),
                                 (500, "unverified"), (503, "unverified"), (404, "not_found"),
                                 (410, "not_found"), (200, "verified"), (301, "verified")):
            self.assertEqual(S.transport_verdict(status)["verdict"], expected, status)
        self.assertEqual(S.transport_verdict(None, "robots.txt disallows")["reason"],
                         "disallowed by robots.txt")
        self.assertIn("budget", S.transport_verdict(None, checked=False)["reason"])


# ---------------------------------------------------------------------------
# 4. sitemap wording
# ---------------------------------------------------------------------------

class TestSitemapWording(unittest.TestCase):

    def _bundle(self, record: dict) -> dict:
        return bundle([_home()], robots_raw=f"User-agent: *\nDisallow:\nSitemap: {record['url']}\n",
                      sitemaps=[record])

    def test_a_served_sitemap_that_does_not_parse_says_so(self):
        record = {"url": ORIGIN + "/sitemap.xml", "source": "robots.txt Sitemap directive",
                  "status": 200, "kind": "unknown", "error": "not well-formed XML",
                  "url_count": 0, "child_count": 0, "lastmods": [], "entries": [],
                  "sample_urls": []}
        found = find(run("crawl-render-audit", self._bundle(record)), "CR-SITEMAP-BROKEN")
        self.assertIn("served but its XML does not parse", found.title)
        self.assertIn("HTTP 200 but sitemap XML parsing failed", found.evidence)
        self.assertEqual(found.severity, "medium")

    def test_a_refused_sitemap_could_not_be_verified(self):
        record = {"url": ORIGIN + "/sitemap.xml", "source": "robots.txt Sitemap directive",
                  "status": 403, "kind": "unknown", "error": None, "url_count": 0,
                  "child_count": 0, "lastmods": [], "entries": [], "sample_urls": []}
        found = find(run("crawl-render-audit", self._bundle(record)), "CR-SITEMAP-BROKEN")
        self.assertIn("could not be verified", found.title)
        self.assertIn("refused or rate-limited", found.evidence)
        self.assertEqual(found.severity, "low")
        self.assertNotIn("unreliable", found.evidence.lower())


# ---------------------------------------------------------------------------
# 5. cross-host canonicals
# ---------------------------------------------------------------------------

class TestCrossHostCanonical(unittest.TestCase):

    def test_a_syndicated_article_pointing_at_its_source_is_a_review_item(self):
        syndicated = news("/news/syndicated", "A syndicated piece")
        syndicated["canonical"] = "https://partner.example/original-piece"
        data = bundle([_home(), news("/news/one", "Local"), news("/news/two", "Other"),
                       syndicated])
        findings = run("crawl-render-audit", data)
        self.assertIsNone(find(findings, "CR-CANONICAL-WRONG-TARGET"))
        found = find(findings, "CR-CANONICAL-CROSS-HOST")
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "low")
        self.assertIn("(article)", found.evidence)
        self.assertIn("may be intentional", found.evidence)
        self.assertIn("could not be verified", found.evidence)
        text = (found.evidence + found.interpretation + found.suggested_action.mechanism).lower()
        self.assertNotIn("tells crawlers to drop", text)
        self.assertNotIn("product detail collapsed", text)

    def test_a_deep_page_canonical_to_the_home_page_is_still_a_collapse(self):
        wrong = news("/news/one", "Local")
        wrong["canonical"] = ORIGIN + "/"
        data = bundle([_home(), wrong, news("/news/two", "Other")])
        found = find(run("crawl-render-audit", data), "CR-CANONICAL-WRONG-TARGET")
        self.assertIsNotNone(found)
        self.assertIn("(article)", found.evidence)
        self.assertNotIn("Product detail", found.suggested_action.mechanism)


# ---------------------------------------------------------------------------
# 6. redirect semantics
# ---------------------------------------------------------------------------

class TestRedirectSemantics(unittest.TestCase):

    def _redirected(self, requested: str, final: str, hops=None) -> dict:
        record = doc("/docs/start", "Getting started")
        record["url"] = requested
        record["final_url"] = final
        record["redirects"] = hops or [{"from": requested, "to": final, "status": 301}]
        return record

    def test_a_section_that_moved_to_its_own_host_keeps_its_resource(self):
        verdict = classify_redirect(self._redirected(ORIGIN + "/blog/post-1",
                                                     "https://blog.shop.example/post-1"))
        self.assertEqual(verdict["kind"], "canonical_representation")
        self.assertEqual(verdict["host_relationship"], "same site")
        self.assertFalse(verdict["cross_domain"])

    def test_a_deep_link_to_another_domains_home_is_named_as_such(self):
        verdict = classify_redirect(self._redirected(ORIGIN + "/products/old-boot",
                                                     "https://newshop.example/"))
        self.assertEqual(verdict["kind"], "homepage_collapse")
        self.assertTrue(verdict["cross_domain"])
        self.assertIn("another domain", verdict["why"])

    def test_a_cross_domain_redirect_to_the_same_path_is_a_migration_not_a_collapse(self):
        verdict = classify_redirect(self._redirected(ORIGIN + "/docs/start",
                                                     "https://docs.newhost.example/docs/start"))
        self.assertNotEqual(verdict["kind"], "homepage_collapse")
        self.assertTrue(verdict["path_preserved"])


# ---------------------------------------------------------------------------
# 7. page-type-aware freshness
# ---------------------------------------------------------------------------

class TestFreshnessFollowsPageType(unittest.TestCase):

    def test_an_undated_home_contact_and_listing_are_not_a_freshness_defect(self):
        contact = page(ORIGIN + "/contact", html_doc(
            title="Contact", canonical=ORIGIN + "/contact",
            body=f"<h1>Contact</h1><p>Email us.</p><p>{LONG}</p>"))
        listing = page(ORIGIN + "/docs/", html_doc(
            title="Docs", canonical=ORIGIN + "/docs/",
            head=jsonld('{"@context":"https://schema.org","@type":"CollectionPage","name":"Docs"}'),
            body="<h1>Docs</h1><a href='/docs/start'>Start</a>"))
        data = bundle([_home(), contact, listing])
        self.assertIsNone(find(run("freshness-corroboration", data), "FC-NO-DATE-SIGNALS"))
        self.assertEqual(S.freshness_expectation(_home()), "not_applicable")
        self.assertEqual(S.freshness_expectation(contact), "not_applicable")

    def test_undated_articles_are_and_the_title_says_what_is_absent(self):
        undated = [news(f"/news/{i}", f"Story {i}") for i in range(3)]
        for record in undated:
            record["jsonld_nodes"] = [{"@type": "NewsArticle", "headline": "Story"}]
        data = bundle([_home()] + undated, sitemaps=[])
        found = find(run("freshness-corroboration", data), "FC-NO-DATE-SIGNALS")
        self.assertIsNotNone(found)
        self.assertEqual(found.title, "Machine-readable freshness metadata is absent")
        self.assertIn("where a date is expected", found.evidence)
        self.assertEqual(found.metrics.get("not_assessed"), 1)

    def test_a_visible_date_without_a_typed_one_is_a_markup_gap_not_a_content_gap(self):
        undated = [news(f"/news/{i}", f"Story {i}",
                        body=f"<main><h1>Story {i}</h1><p>Last updated: 1 September 2026</p>"
                             f"<p>{LONG}</p></main>") for i in range(3)]
        for record in undated:
            record["jsonld_nodes"] = [{"@type": "NewsArticle", "headline": "Story"}]
        data = bundle([_home()] + undated, sitemaps=[])
        found = find(run("freshness-corroboration", data), "FC-NO-DATE-SIGNALS")
        self.assertIn("visible copy but not in a machine-readable form", found.title)
        self.assertEqual(found.severity, "medium")


# ---------------------------------------------------------------------------
# 8. contextual Organization fields
# ---------------------------------------------------------------------------

class TestOrganizationFieldsFollowTheSite(unittest.TestCase):

    def test_a_documentation_site_is_not_told_it_needs_a_postal_address(self):
        found = find(run("entity-audit", docs_site()), "EN-ORG-INCOMPLETE")
        if found is not None:
            self.assertNotIn("address", found.metrics["missing_required"])
            self.assertNotIn("contactPoint", found.metrics["missing_required"])
            self.assertEqual(found.severity, "low")

    def test_a_shop_is_expected_to_say_where_it_is_and_how_to_reach_it(self):
        data = bundle([_home(), physical(), physical("/products/summit", "Summit Boot", "210")])
        found = find(run("entity-audit", data), "EN-ORG-INCOMPLETE")
        self.assertIsNotNone(found)
        self.assertIn("address", found.metrics["missing_required"])
        self.assertIn("the site sells physical goods", found.evidence)
        self.assertEqual(found.severity, "medium")

    def test_optional_fields_are_named_but_never_counted(self):
        data = bundle([_home(), physical()])
        found = find(run("entity-audit", data), "EN-ORG-INCOMPLETE")
        self.assertIn("logo", found.metrics["missing_optional"])
        self.assertIn("optional for any site and not counted", found.evidence)

    def test_the_expectation_table_is_the_semantic_layers(self):
        docs = S.site_context(docs_site())
        self.assertEqual(S.organization_field_expectation("address", docs), "optional")
        shop = S.site_context(bundle([_home(), physical()]))
        self.assertEqual(S.organization_field_expectation("address", shop),
                         "required_when_applicable")
        self.assertEqual(S.organization_field_expectation("foundingDate", shop), "optional")


# ---------------------------------------------------------------------------
# 9. contextual Open Graph
# ---------------------------------------------------------------------------

class TestOpenGraphIsOptionalMetadata(unittest.TestCase):

    def test_absence_is_never_above_the_optional_ceiling_and_claims_no_reader(self):
        pages = [_home(open_graph=False)] + [
            page(ORIGIN + f"/news/{i}", html_doc(title=f"Story {i}", canonical=ORIGIN + f"/news/{i}",
                                                head=jsonld(NEWS_LD % f"Story {i}"),
                                                body=f"<h1>Story {i}</h1><p>{LONG}</p>",
                                                open_graph=False))
            for i in range(4)]
        found = find(run("machine-readability-audit", bundle(pages)), "MR-OPEN-GRAPH-INCOMPLETE")
        self.assertIsNotNone(found)
        self.assertLessEqual(S._SEVERITY_ORDER.index(found.severity),
                             S._SEVERITY_ORDER.index(S.OPTIONAL_METADATA_CEILING))
        self.assertIn("optional metadata", found.evidence)
        text = (found.evidence + found.interpretation + found.suggested_action.mechanism).lower()
        self.assertNotIn("fetchers read", text)
        self.assertNotIn("instead of the body", text)

    def test_product_type_is_suggested_only_where_something_is_sold(self):
        self.assertEqual(S.open_graph_expectation(doc("/docs/start", "Start")), "recommended")
        self.assertEqual(S.open_graph_expectation(page(ORIGIN + "/contact",
                                                       html_doc(title="Contact",
                                                                body="<h1>Contact</h1>"))),
                         "optional")


# ---------------------------------------------------------------------------
# 10. noindex wording
# ---------------------------------------------------------------------------

class TestNoindexWording(unittest.TestCase):

    def test_a_noindexed_article_is_a_review_item_not_a_commercial_loss(self):
        archived = news("/news/archive", "Archive 2019")
        archived["meta_robots"] = "noindex"
        data = bundle([_home(), archived, news("/news/one", "Local"), news("/news/two", "Other")])
        found = find(run("crawl-render-audit", data), "CR-NOINDEX-ON-IMPORTANT-PAGES")
        self.assertIsNotNone(found)
        self.assertIn("Review whether this exclusion is intentional", found.suggested_action.summary)
        text = (found.title + found.evidence + found.interpretation).lower()
        self.assertNotIn("commercially important", text)
        self.assertIn("not something this audit can tell", found.evidence)

    def test_a_noindexed_sign_in_page_is_conventional_and_not_counted(self):
        login = page(ORIGIN + "/account/login", html_doc(
            title="Sign in", canonical=ORIGIN + "/account/login",
            body="<h1>Sign in</h1><form action='/account/login' method='post'>"
                 "<input name='email'><input type='password' name='password'>"
                 "<button>Sign in</button></form>"))
        login["meta_robots"] = "noindex"
        data = bundle([_home(), login, news("/news/one", "Local")])
        self.assertIsNone(find(run("crawl-render-audit", data), "CR-NOINDEX-ON-IMPORTANT-PAGES"))


# ---------------------------------------------------------------------------
# 11. heading semantics
# ---------------------------------------------------------------------------

class TestHeadingSemantics(unittest.TestCase):

    def test_two_h1s_that_name_the_subject_are_not_a_defect(self):
        story = news("/news/release", "Kestrel 3 released",
                     body=f"<main><h1>Kestrel 3 released</h1><p>{LONG}</p>"
                          f"<article><h1>What changed</h1><p>{LONG}</p></article></main>")
        self.assertEqual(story["h1_count"], 2)
        data = bundle([_home(), story, news("/news/one", "Local"), news("/news/two", "Other")])
        self.assertIsNone(find(run("machine-readability-audit", data), "MR-HEADING-STRUCTURE"))
        self.assertTrue(S.heading_assessment(story)["identifies_subject"])

    def test_a_page_led_by_an_h2_that_names_it_is_not_a_defect(self):
        config = doc("/docs/config", "Configuration",
                     body=f"<main><h2>Configuration</h2><p>{LONG}</p></main>")
        self.assertEqual(config["h1_count"], 0)
        verdict = S.heading_assessment(config)
        self.assertTrue(verdict["identifies_subject"])
        data = docs_site(config)
        self.assertIsNone(find(run("machine-readability-audit", data), "MR-HEADING-STRUCTURE"))

    def test_headings_that_only_repeat_the_site_name_are_reported_low(self):
        pages = [_home()] + [
            news(f"/news/{i}", f"Story {i}",
                 body=f"<main><h1>Kestrel Ltd</h1><p>{LONG}</p></main>") for i in range(3)]
        found = find(run("machine-readability-audit", bundle(pages)), "MR-HEADING-STRUCTURE")
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "low")
        self.assertIn("do not name the subject", found.title)


# ---------------------------------------------------------------------------
# 12. site search
# ---------------------------------------------------------------------------

class TestSiteSearchIsEvidenceBased(unittest.TestCase):

    def test_a_small_site_with_listings_is_not_asked_for_a_search_box(self):
        listing = page(ORIGIN + "/docs/", html_doc(
            title="Docs", canonical=ORIGIN + "/docs/",
            head=jsonld('{"@context":"https://schema.org","@type":"CollectionPage","name":"Docs"}'),
            body="<h1>Docs</h1><a href='/docs/start'>Start</a><a href='/docs/config'>Config</a>"))
        data = docs_site(listing)
        verdict = S.is_site_search_expected(data)
        self.assertFalse(verdict)
        self.assertIn("no search box is owed", verdict["reason"])
        self.assertIsNone(find(run("engagement-audit", data), "EG-NO-SITE-SEARCH"))

    def test_a_paginated_listing_makes_a_search_box_an_expectation(self):
        listing = page(ORIGIN + "/docs/", html_doc(
            title="Docs", canonical=ORIGIN + "/docs/",
            head=jsonld('{"@context":"https://schema.org","@type":"CollectionPage","name":"Docs"}'),
            body="<h1>Docs</h1><a href='/docs/start'>Start</a>"
                 "<a rel='next' href='/docs/?page=2'>Next</a>"))
        data = docs_site(listing)
        verdict = S.is_site_search_expected(data)
        self.assertTrue(verdict)
        self.assertIn("paginate", verdict["reason"])
        found = find(run("engagement-audit", data), "EG-NO-SITE-SEARCH")
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "low")
        self.assertIn("A search was expected because", found.evidence)

    def test_search_action_markup_is_recommended_only_where_a_search_exists(self):
        searchable = _home(body="<h1>Kestrel Ltd</h1><form action='/search' role='search'>"
                                "<input type='search' name='q'></form>")
        data = bundle([searchable, doc("/docs/start", "Getting started"),
                       doc("/docs/config", "Configuration")])
        findings = run("machine-readability-audit", data)
        site_schema = find(findings, "MR-SITE-SCHEMA-MISSING")
        self.assertIsNotNone(site_schema)
        self.assertTrue(any("SearchAction" in step for step in site_schema.suggested_action.steps))
        no_search = find(run("machine-readability-audit", docs_site()), "MR-SITE-SCHEMA-MISSING")
        self.assertIsNotNone(no_search)
        self.assertTrue(any("once the site has a search endpoint" in step
                            for step in no_search.suggested_action.steps))
        self.assertFalse(any("pointing at your site-search URL" in step
                             for step in no_search.suggested_action.steps))


# ---------------------------------------------------------------------------
# 13. answerability gating
# ---------------------------------------------------------------------------

class TestAnswerabilityFollowsWhatIsSold(unittest.TestCase):

    def test_a_documentation_site_is_asked_no_buying_question(self):
        matrix = build_matrix(docs_site())
        self.assertEqual(matrix["site_kind"], "documentation")
        for cls in ("return_window", "shipping_destinations", "product_availability",
                    "payment_options"):
            self.assertNotIn(cls, matrix["question_classes"])
        self.assertIsNone(matrix["answerability_score"])
        findings = run("answerability-audit", docs_site())
        self.assertEqual([f.rule_id for f in findings if f.rule_id.startswith("AN-UNANSWERABLE")], [])

    def test_a_software_vendor_is_asked_about_price_not_stock(self):
        data = bundle([_home(), software(), software("/products/pro", "Kestrel Studio Pro", "99")])
        matrix = build_matrix(data)
        kinds = {row["kind"] for row in matrix["questions"]}
        self.assertIn("product_price", kinds)
        self.assertNotIn("product_availability", kinds)
        self.assertNotIn("return_window", matrix["question_classes"])
        self.assertTrue(any("stock statement does not apply to a software item" in key
                            for key in matrix["not_asked"]))

    def test_a_shop_is_asked_the_buying_questions_and_they_are_scored(self):
        data = bundle([_home(), physical(), physical("/products/summit", "Summit Boot", "210")])
        matrix = build_matrix(data)
        kinds = {row["kind"] for row in matrix["questions"]}
        self.assertIn("product_availability", kinds)
        self.assertIn("return_window", matrix["question_classes"])
        self.assertIsNotNone(matrix["answerability_score"])

    def test_the_cheapest_in_a_category_is_answered_from_that_categorys_members(self):
        """A question that names a category must be answered from the items
        in it. Answered from every product the crawl read, "the cheapest item
        in Boots" named a monthly plan."""
        listing = page(ORIGIN + "/collections/boots", html_doc(
            title="Boots", canonical=ORIGIN + "/collections/boots",
            body="<main><h1>Boots</h1><ul>"
                 "<li><a href='/products/trail-boot'>Trail Boot £120</a></li>"
                 "<li><a href='/products/summit'>Summit Boot £210</a></li></ul></main>"))
        data = bundle([_home(), listing, physical(), physical("/products/summit", "Summit Boot",
                                                             "210"),
                       subscription()])
        matrix = build_matrix(data)
        rows = [r for r in matrix["questions"] if r["kind"] == "category_cheapest"]
        self.assertEqual(len(rows), 1)
        self.assertIn("120", rows[0]["evidence"])
        self.assertNotIn("cloud-team", rows[0]["evidence"])

    def test_a_category_whose_members_were_not_read_is_not_asked(self):
        listing = page(ORIGIN + "/collections/boots", html_doc(
            title="Boots", canonical=ORIGIN + "/collections/boots",
            body="<main><h1>Boots</h1><ul>"
                 "<li><a href='/products/unread-one'>Unread One £30</a></li>"
                 "<li><a href='/products/unread-two'>Unread Two £40</a></li></ul></main>"))
        data = bundle([_home(), listing, physical(), subscription()])
        matrix = build_matrix(data)
        self.assertEqual([r for r in matrix["questions"] if r["kind"] == "category_cheapest"], [])
        self.assertTrue(any("the set to rank is not established" in key
                            for key in matrix["not_asked"]))

    def test_a_documentation_section_is_never_asked_for_its_cheapest_item(self):
        listing = page(ORIGIN + "/docs/", html_doc(
            title="Docs", canonical=ORIGIN + "/docs/",
            head=jsonld('{"@context":"https://schema.org","@type":"CollectionPage","name":"Docs"}'),
            body="<main><h1>Docs</h1><ul><li><a href='/docs/start'>Start</a></li>"
                 "<li><a href='/docs/config'>Config</a></li></ul></main>"))
        data = bundle([_home(), listing, doc("/docs/start", "Getting started"),
                       doc("/docs/config", "Configuration"), physical(), subscription()])
        matrix = build_matrix(data)
        self.assertEqual([r for r in matrix["questions"] if r["kind"] == "category_cheapest"], [])
        self.assertFalse(any("Docs" in key for key in matrix["not_asked"]))

    def test_questions_not_asked_are_reported_not_scored(self):
        data = bundle([_home(), physical(), software()])
        matrix = build_matrix(data)
        self.assertTrue(matrix["not_asked"])
        self.assertTrue(any("not counted as gaps" in note for note in matrix["notes"]))


# ---------------------------------------------------------------------------
# 14. severity respects applicability and uncertainty
# ---------------------------------------------------------------------------

class TestSeverityCeilings(unittest.TestCase):

    OPTIONAL_ABSENCE_RULES = {"MR-OPEN-GRAPH-INCOMPLETE", "EG-REVIEWS-ABSENT",
                              "EN-CATEGORY-UNDECLARED", "MR-BREADCRUMB-MISSING",
                              "MR-SITE-SCHEMA-MISSING", "EN-ORG-INCOMPLETE",
                              "EG-NO-SITE-SEARCH", "CR-CANONICAL-CROSS-HOST",
                              "CR-URLS-NOT-VERIFIED", "MR-HEADING-STRUCTURE"}

    def test_no_optional_absence_is_ever_high(self):
        shapes = (
            docs_site(),
            bundle([_home(open_graph=False)] + [physical(f"/products/p{i}", f"Boot {i}", "10")
                                                for i in range(4)]),
            bundle([_home(), physical(), physical("/products/summit", "Summit Boot", "210")]),
        )
        for data in shapes:
            for skill in ("crawl-render-audit", "machine-readability-audit", "entity-audit",
                          "engagement-audit"):
                for finding in run(skill, data):
                    if finding.rule_id in self.OPTIONAL_ABSENCE_RULES:
                        self.assertNotIn(finding.severity, ("high", "critical"), finding.rule_id)

    def test_a_single_page_cannot_carry_a_template_verdict(self):
        data = bundle([_home(), physical()])
        returns = find(run("engagement-audit", data), "EG-RETURNS-INVISIBLE")
        self.assertIsNotNone(returns)
        self.assertEqual(returns.severity, "medium")
        self.assertLess(returns.confidence, 0.7)

    def test_unverified_transport_is_informational_with_low_confidence(self):
        home = _home(body="<h1>Kestrel Ltd</h1><a href='/members'>Members</a>")
        refused = error_page(ORIGIN + "/members", 403)
        refused["fetch_reason"] = "linked from the home page"
        found = find(run("crawl-render-audit", bundle([home, refused])), "CR-URLS-NOT-VERIFIED")
        self.assertEqual(found.severity, "info")
        self.assertLessEqual(found.confidence, 0.5)


# ---------------------------------------------------------------------------
# 15. endpoint classification before content findings
# ---------------------------------------------------------------------------

class TestEndpointClassification(unittest.TestCase):

    def test_utility_and_error_endpoints_are_classified_before_any_content_rule(self):
        login = page(ORIGIN + "/account/login", html_doc(
            title="Sign in", canonical=ORIGIN + "/account/login",
            body="<h1>Sign in</h1><form action='/account/login' method='post'>"
                 "<input name='email'><input type='password' name='password'>"
                 "<button>Sign in</button></form>"))
        results = page(ORIGIN + "/search?q=boots", html_doc(
            title="Search results", canonical=ORIGIN + "/search",
            body="<h1>Search results for boots</h1><form action='/search'>"
                 "<input type='search' name='q' value='boots'></form>"))
        self.assertEqual(S.endpoint_kind(login), "utility")
        self.assertEqual(S.endpoint_kind(results), "utility")
        self.assertEqual(S.endpoint_kind(error_page(ORIGIN + "/gone")), "error")
        self.assertEqual(S.endpoint_kind(doc("/docs/start", "Start")), "content")
        data = bundle([_home(), login, results, doc("/docs/start", "Getting started")])
        for skill in ("machine-readability-audit", "engagement-audit", "freshness-corroboration"):
            for finding in run(skill, data):
                cited = set(finding.affected_urls) | {i.url for i in finding.evidence_items if i.url}
                self.assertNotIn(login["url"], cited, finding.rule_id)
                self.assertNotIn(results["url"], cited, finding.rule_id)


# ---------------------------------------------------------------------------
# 16. coverage reporting
# ---------------------------------------------------------------------------

class TestCoverageReportsWhatWasNotApplied(unittest.TestCase):

    def test_the_report_names_the_expectations_it_set_aside(self):
        data = bundle([_home(), physical(), software(), subscription()])
        report = report_mod.build_report(data, [], AuditConfig(site=ORIGIN))
        coverage = report["coverage"]
        self.assertEqual(coverage["site_kind"], S.site_context(data)["site_kind"])
        self.assertEqual(coverage["product_subtypes"],
                         {"physical": 1, "software": 1, "subscription": 1})
        shipping = [e for e in coverage["expectations_not_applied"]
                    if e["expectation"] == "shipping"][0]
        self.assertEqual(shipping["applied_to"], 1)
        self.assertEqual(shipping["product_pages"], 3)
        reasons = {r["reason"] for r in shipping["not_applied"]}
        self.assertTrue(any("software" in r for r in reasons))
        self.assertTrue(any("subscription" in r for r in reasons))
        self.assertIn("semantics", report["diagnostics"])
        markdown = report_mod.render_markdown(report)
        self.assertIn("Expectation 'shipping' applied to 1 of 3", markdown)
        self.assertIn("Site shape", markdown)


if __name__ == "__main__":
    unittest.main()
