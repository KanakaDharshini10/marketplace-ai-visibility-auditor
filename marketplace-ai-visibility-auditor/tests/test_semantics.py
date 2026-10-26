"""The semantic layer: what kind of thing a page is about, and what follows.

Page type is not enough. These tests pin the decisions
:mod:`aiva.semantics` makes from *evidence* - declared types, typed
properties, the page's own words - and never from the words in a URL:

* a product page's kind (physical, digital, software, subscription, service,
  marketplace listing, informational, ambiguous) and its confidence;
* what a listing page is a listing of;
* the shape of a site;
* the applicability engine every commerce rule asks;
* outbound-link and entity-relationship classification;
* the difference between "not found" and "could not be verified".

Run just this file:

    python3 tests/run_tests.py semantics -v
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, html_doc, jsonld, page

from aiva import semantics as S

PHYSICAL_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"Trail Boot",'
    '"sku":"TB-1","gtin13":"1234567890123","color":"Brown","material":"Leather",'
    '"weight":{"@type":"QuantitativeValue","value":"1.1","unitCode":"KGM"},'
    '"offers":{"@type":"Offer","price":"120","priceCurrency":"GBP",'
    '"availability":"https://schema.org/InStock",'
    '"shippingDetails":{"@type":"OfferShippingDetails","shippingRate":'
    '{"@type":"MonetaryAmount","value":"4.99","currency":"GBP"}}}}')
SOFTWARE_LD = (
    '{"@context":"https://schema.org","@type":"SoftwareApplication","name":"Kestrel Studio",'
    '"operatingSystem":"Windows, macOS","applicationCategory":"DeveloperApplication",'
    '"softwareVersion":"4.2","offers":{"@type":"Offer","price":"49","priceCurrency":"USD"}}')
SUBSCRIPTION_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"Kestrel Cloud Team",'
    '"description":"Team plan.","offers":{"@type":"Offer","priceCurrency":"USD",'
    '"priceSpecification":{"@type":"UnitPriceSpecification","price":"12",'
    '"priceCurrency":"USD","billingDuration":1,"billingIncrement":1,'
    '"referenceQuantity":{"@type":"QuantitativeValue","value":1,"unitCode":"MON"}}}}')
SERVICE_LD = (
    '{"@context":"https://schema.org","@type":"Service","name":"Boiler servicing",'
    '"serviceType":"Heating maintenance","areaServed":"Bristol",'
    '"provider":{"@type":"LocalBusiness","name":"Kestrel Heating"},'
    '"offers":{"@type":"Offer","price":"89","priceCurrency":"GBP"}}')
MARKETPLACE_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"Vintage desk lamp",'
    '"description":"Brass lamp, working order.",'
    '"offers":{"@type":"Offer","price":"35","priceCurrency":"GBP",'
    '"seller":{"@type":"Person","name":"Anna R."}}}')
EBOOK_LD = (
    '{"@context":"https://schema.org","@type":"Book","name":"Kestrel in Practice",'
    '"bookFormat":"https://schema.org/EBook","isbn":"9781234567897",'
    '"offers":{"@type":"Offer","price":"19","priceCurrency":"USD"}}')
INFO_LD = (
    '{"@context":"https://schema.org","@type":"Product","name":"Kestrel K2 Router",'
    '"description":"Dual-band router.","color":"White",'
    '"weight":{"@type":"QuantitativeValue","value":"0.4","unitCode":"KGM"}}')
BARE_LD = ('{"@context":"https://schema.org","@type":"Product","name":"Thing",'
           '"offers":{"@type":"Offer","price":"10","priceCurrency":"USD"}}')


def _product(path: str, ld: str, body: str) -> dict:
    return page(ORIGIN + path, html_doc(title=body.split("</h1>")[0].split("<h1>")[-1],
                                        head=jsonld(ld), body=body))


class TestProductSubtype(unittest.TestCase):
    def test_physical_from_typed_attributes_and_shipping(self):
        p = _product("/products/trail-boot", PHYSICAL_LD,
                     "<main><h1>Trail Boot</h1><p>£120. In stock. Weight 1.1 kg.</p></main>")
        sem = S.product_semantics(p)
        self.assertEqual(sem["subtype"], "physical")
        self.assertEqual(sem["confidence"], "high")
        self.assertTrue(sem["sells"])
        self.assertTrue(any("shippingDetails" in e for e in sem["evidence"]))

    def test_software_from_declared_type(self):
        p = _product("/products/kestrel-studio", SOFTWARE_LD,
                     "<main><h1>Kestrel Studio</h1><p>$49. Download for Windows and macOS. "
                     "System requirements below.</p></main>")
        sem = S.product_semantics(p)
        self.assertEqual(sem["subtype"], "software")
        self.assertEqual(sem["confidence"], "high")

    def test_subscription_from_billing_period(self):
        p = _product("/products/team-plan", SUBSCRIPTION_LD,
                     "<main><h1>Kestrel Cloud Team</h1><p>$12 per user per month, billed "
                     "annually. Cancel anytime.</p></main>")
        sem = S.product_semantics(p)
        self.assertEqual(sem["subtype"], "subscription")
        self.assertIn(sem["confidence"], ("high", "medium"))

    def test_service_from_service_type(self):
        p = _product("/products/boiler-servicing", SERVICE_LD,
                     "<main><h1>Boiler servicing</h1><p>From £89. Book an appointment or "
                     "request a quote.</p></main>")
        sem = S.product_semantics(p)
        self.assertEqual(sem["subtype"], "service")

    def test_marketplace_listing_from_third_party_seller(self):
        p = _product("/products/vintage-desk-lamp", MARKETPLACE_LD,
                     "<main><h1>Vintage desk lamp</h1><p>£35. Sold by Anna R. Ships from "
                     "the seller.</p></main>")
        sem = S.product_semantics(p, site_names=["Kestrel Market"])
        self.assertEqual(sem["subtype"], "marketplace_listing")

    def test_digital_from_book_format(self):
        p = _product("/products/kestrel-in-practice", EBOOK_LD,
                     "<main><h1>Kestrel in Practice</h1><p>$19. Instant download, PDF and "
                     "EPUB.</p></main>")
        self.assertEqual(S.product_semantics(p)["subtype"], "digital")

    def test_informational_when_nothing_is_for_sale(self):
        p = _product("/products/k2-router", INFO_LD,
                     "<main><h1>Kestrel K2 Router</h1><p>Dual-band router. Weight 0.4 kg. "
                     "Where to buy: find a retailer near you.</p></main>")
        sem = S.product_semantics(p)
        self.assertEqual(sem["subtype"], "informational")
        self.assertFalse(sem["sells"])
        self.assertEqual(sem["described_as"], "physical")

    def test_ambiguous_when_nothing_settles_the_kind(self):
        p = _product("/products/thing", BARE_LD, "<main><h1>Thing</h1><p>$10.</p></main>")
        sem = S.product_semantics(p)
        self.assertEqual(sem["subtype"], "ambiguous")
        self.assertEqual(sem["confidence"], "low")
        self.assertTrue(sem["sells"])

    def test_the_url_words_do_not_decide(self):
        """A software product at a 'shop' URL is software; a physical product at a
        'download' URL is physical. Only what the page declares counts."""
        soft = page(ORIGIN + "/shop/kestrel-studio", html_doc(
            title="Kestrel Studio", head=jsonld(SOFTWARE_LD),
            body="<main><h1>Kestrel Studio</h1><p>$49. Download the installer.</p></main>"))
        self.assertEqual(S.product_semantics(soft)["subtype"], "software")
        boot = page(ORIGIN + "/downloads/trail-boot", html_doc(
            title="Trail Boot", head=jsonld(PHYSICAL_LD),
            body="<main><h1>Trail Boot</h1><p>£120. In stock.</p></main>"))
        self.assertEqual(S.product_semantics(boot)["subtype"], "physical")

    def test_text_alone_only_corroborates(self):
        """Words like 'download' on a page whose markup says physical do not
        outvote the markup."""
        p = _product("/products/trail-boot", PHYSICAL_LD,
                     "<main><h1>Trail Boot</h1><p>£120. In stock. Download the care guide "
                     "and install the insoles.</p></main>")
        sem = S.product_semantics(p)
        self.assertEqual(sem["subtype"], "physical")


ARTICLE_LD = ('{"@context":"https://schema.org","@type":"NewsArticle","headline":"%s",'
              '"datePublished":"2026-08-01"}')
TECH_LD = ('{"@context":"https://schema.org","@type":"TechArticle","headline":"%s",'
           '"dateModified":"2026-08-01"}')


def _listing(path: str, title: str, links: list, head: str = "") -> dict:
    body = f"<main><h1>{title}</h1><ul>" + "".join(
        f'<li><a href="{href}">{text}</a></li>' for href, text in links) + "</ul></main>"
    return page(ORIGIN + path, html_doc(title=title, head=head, body=body))


class TestListingSubtype(unittest.TestCase):
    def _bundle_with(self, listing: dict, others: list) -> dict:
        data = bundle([listing] + others)
        S.annotate_bundle(data)
        return data

    def test_ecommerce_listing_from_linked_physical_products(self):
        products = [_product(f"/products/boot-{i}", PHYSICAL_LD.replace("Trail Boot", f"Boot {i}"),
                             f"<main><h1>Boot {i}</h1><p>£120. In stock.</p></main>")
                    for i in range(2)]
        listing = _listing("/collections/boots", "Boots",
                           [(f"/products/boot-{i}", f"Boot {i} £120") for i in range(2)])
        data = self._bundle_with(listing, products)
        self.assertEqual(listing["semantics"]["listing"]["subtype"], "ecommerce_listing")

    def test_article_index_from_linked_articles(self):
        articles = [page(ORIGIN + f"/news/story-{i}", html_doc(
            title=f"Story {i}", head=jsonld(ARTICLE_LD % f"Story {i}"),
            body=f"<main><h1>Story {i}</h1><p>{'Words. ' * 80}</p></main>")) for i in range(3)]
        listing = _listing("/category/news", "News",
                           [(f"/news/story-{i}", f"Story {i}") for i in range(3)])
        data = self._bundle_with(listing, articles)
        self.assertEqual(listing["semantics"]["listing"]["subtype"], "article_index")

    def test_documentation_section_from_linked_tech_articles(self):
        docs = [page(ORIGIN + f"/docs/guide-{i}", html_doc(
            title=f"Guide {i}", head=jsonld(TECH_LD % f"Guide {i}"),
            body=f"<main><h1>Guide {i}</h1><p>{'Steps. ' * 80}</p></main>")) for i in range(3)]
        listing = _listing("/category/docs", "Documentation",
                           [(f"/docs/guide-{i}", f"Guide {i}") for i in range(3)])
        data = self._bundle_with(listing, docs)
        self.assertEqual(listing["semantics"]["listing"]["subtype"], "documentation_section")

    def test_audio_listing_from_declared_entries(self):
        head = jsonld('{"@context":"https://schema.org","@type":"ItemList","itemListElement":['
                      '{"@type":"ListItem","position":1,"item":{"@type":"PodcastEpisode",'
                      '"name":"Episode 1"}},{"@type":"ListItem","position":2,"item":'
                      '{"@type":"PodcastEpisode","name":"Episode 2"}}]}')
        listing = _listing("/category/podcast", "Podcast", [("/podcast/1", "Episode 1")], head)
        data = self._bundle_with(listing, [])
        self.assertEqual(listing["semantics"]["listing"]["subtype"], "audio_listing")

    def test_unknown_when_nothing_settles_it(self):
        listing = _listing("/category/misc", "Misc", [("/page-a", "A"), ("/page-b", "B")])
        data = self._bundle_with(listing, [])
        self.assertEqual(listing["semantics"]["listing"]["subtype"], "unknown")


GOV_ORG = ('{"@context":"https://schema.org","@type":"GovernmentOrganization",'
           '"name":"Department for Kestrels","url":"/"}')


class TestSiteContext(unittest.TestCase):
    def test_ecommerce(self):
        from helpers import commerce_bundle
        ctx = S.site_context(commerce_bundle())
        self.assertEqual(ctx["site_kind"], "ecommerce")
        self.assertTrue(ctx["sells_physical_goods"])

    def test_software(self):
        pages = [page(ORIGIN + "/", html_doc(title="Kestrel", body="<h1>Kestrel</h1>"))]
        for i in range(2):
            pages.append(_product(f"/products/app-{i}",
                                  SOFTWARE_LD.replace("Kestrel Studio", f"App {i}"),
                                  f"<main><h1>App {i}</h1><p>$49. Download.</p></main>"))
        ctx = S.site_context(bundle(pages))
        self.assertEqual(ctx["site_kind"], "software")
        self.assertFalse(ctx["sells_physical_goods"])

    def test_documentation(self):
        pages = [page(ORIGIN + "/", html_doc(title="Kestrel", body="<h1>Kestrel</h1>"))]
        for i in range(3):
            pages.append(page(ORIGIN + f"/docs/guide-{i}", html_doc(
                title=f"Guide {i}", head=jsonld(TECH_LD % f"Guide {i}"),
                body=f"<main><h1>Guide {i}</h1><p>{'Steps. ' * 60}</p></main>")))
        ctx = S.site_context(bundle(pages))
        self.assertEqual(ctx["site_kind"], "documentation")

    def test_government_from_declared_type(self):
        pages = [page(ORIGIN + "/", html_doc(title="Department for Kestrels", head=jsonld(GOV_ORG),
                                             body="<h1>Department for Kestrels</h1>"))]
        ctx = S.site_context(bundle(pages))
        self.assertEqual(ctx["site_kind"], "government")

    def test_unknown_when_nothing_is_declared(self):
        pages = [page(ORIGIN + "/", html_doc(title="Hello", body="<h1>Hello</h1><p>Hi.</p>"))]
        self.assertEqual(S.site_context(bundle(pages))["site_kind"], "unknown")

    def test_context_is_deterministic_and_never_mutates_a_bundle_it_was_handed(self):
        """The collector records semantics in the bundle it builds; a bundle
        that arrives without them (a fixture, an older bundle file) is read
        through a shadow, so a specialist never writes into shared evidence."""
        import copy
        from helpers import commerce_bundle
        data = commerce_bundle()
        snapshot = copy.deepcopy(data)
        first = S.site_context(data)
        second = S.site_context(data)
        self.assertIs(first, second)
        self.assertEqual(first["site_kind"], "ecommerce")
        self.assertEqual(data, snapshot, "the lazy path must not mutate the bundle")
        again = S.site_context(commerce_bundle())
        self.assertEqual({k: v for k, v in again.items() if not k.startswith("_")},
                         {k: v for k, v in first.items() if not k.startswith("_")})
        # The collector's path records it in the bundle, for the report.
        recorded = S.annotate_bundle(data)
        self.assertEqual(data["semantics"]["site_kind"], "ecommerce")
        self.assertIs(S.site_context(data), data["semantics"])
        self.assertEqual(recorded["site_kind"], first["site_kind"])


class TestApplicability(unittest.TestCase):
    def setUp(self):
        self.physical = _product("/products/trail-boot", PHYSICAL_LD,
                                 "<main><h1>Trail Boot</h1><p>£120. In stock.</p></main>")
        self.software = _product("/products/kestrel-studio", SOFTWARE_LD,
                                 "<main><h1>Kestrel Studio</h1><p>$49. Download.</p></main>")
        self.info = _product("/products/k2-router", INFO_LD,
                             "<main><h1>Kestrel K2 Router</h1><p>Find a retailer.</p></main>")
        self.bare = _product("/products/thing", BARE_LD, "<main><h1>Thing</h1><p>$10.</p></main>")
        self.ctx = S.site_context(bundle([self.physical, self.software, self.info, self.bare]))

    def test_shipping_returns_stock_apply_to_physical_only(self):
        for fn in (S.is_shipping_applicable, S.is_returns_applicable, S.is_stock_applicable):
            with self.subTest(fn=fn.__name__):
                self.assertTrue(fn(self.physical, self.ctx))
                self.assertFalse(fn(self.software, self.ctx))
                self.assertFalse(fn(self.info, self.ctx))
                verdict = fn(self.bare, self.ctx)
                self.assertFalse(verdict)
                self.assertEqual(verdict["basis"], "unknown")
                self.assertIn("not asserted", verdict["reason"])

    def test_physical_specs_and_identifiers(self):
        self.assertTrue(S.is_physical_specs_applicable(self.physical, self.ctx))
        self.assertFalse(S.is_physical_specs_applicable(self.software, self.ctx))
        # An informational page *about* a physical item may still publish specs.
        self.assertTrue(S.is_physical_specs_applicable(self.info, self.ctx))
        self.assertTrue(S.is_identifier_applicable(self.physical, self.ctx))
        self.assertFalse(S.is_identifier_applicable(self.software, self.ctx))

    def test_reviews_price_and_cta(self):
        self.assertTrue(S.is_reviews_applicable(self.physical, self.ctx))
        self.assertTrue(S.is_reviews_applicable(self.software, self.ctx))
        self.assertFalse(S.is_reviews_applicable(self.info, self.ctx))
        self.assertTrue(S.is_price_applicable(self.physical, self.ctx))
        self.assertFalse(S.is_price_applicable(self.info, self.ctx))
        self.assertFalse(S.is_purchase_cta_applicable(self.software, self.ctx))
        self.assertFalse(S.is_purchase_cta_applicable(self.info, self.ctx))

    def test_a_page_that_states_the_concept_itself_owns_it(self):
        """A software page that says 'ships in 2 days' has made delivery its
        own concern; the audit may then hold it to it."""
        soft = _product("/products/boxed-edition", SOFTWARE_LD,
                        "<main><h1>Kestrel Studio</h1><p>$49. Boxed edition ships in 2 days; "
                        "free delivery.</p></main>")
        self.assertTrue(S.is_shipping_applicable(soft, self.ctx))

    def test_verdicts_are_serialisable_and_explain_themselves(self):
        import json
        verdict = S.is_shipping_applicable(self.software, self.ctx)
        json.dumps(verdict)
        self.assertEqual(set(verdict), {"applies", "reason", "basis", "confidence"})

    def test_comparison_and_search_expectations(self):
        # Comparison means two or more sellable items of the *same* kind: a
        # boot and a software licence are not alternatives to each other.
        second_boot = _product("/products/summit-boot", PHYSICAL_LD,
                               "<main><h1>Summit Boot</h1><p>$210. Add to cart.</p></main>")
        self.assertTrue(S.is_comparison_applicable(bundle([self.physical, second_boot]), None))
        mixed = S.is_comparison_applicable(bundle([self.physical, self.software]), None)
        self.assertFalse(mixed)
        self.assertIn("one kind", mixed["reason"])
        small = bundle([page(ORIGIN + "/", html_doc(title="Hi", body="<h1>Hi</h1>"))],
                       sitemaps=[])
        self.assertFalse(S.is_site_search_expected(small))
        self.assertFalse(S.is_comparison_applicable(small))

    def test_summary_lists_what_was_not_applied_and_why(self):
        summary = S.applicability_summary(
            bundle([self.physical, self.software, self.info, self.bare]))
        shipping = [d for d in summary["expectations"] if d["expectation"] == "shipping"][0]
        self.assertEqual(shipping["applied_to"], 1)
        self.assertEqual(shipping["product_pages"], 4)
        self.assertEqual(sum(r["pages"] for r in shipping["not_applied"]), 3)


class TestExpectations(unittest.TestCase):
    def test_freshness_expectation_by_page_role(self):
        home = page(ORIGIN + "/", html_doc(title="Home", body="<h1>Home</h1>"))
        article = page(ORIGIN + "/blog/post", html_doc(title="Post", body="<h1>Post</h1>"))
        contact = page(ORIGIN + "/contact", html_doc(title="Contact", body="<h1>Contact</h1>"))
        policy = page(ORIGIN + "/returns", html_doc(title="Returns", body="<h1>Returns</h1>"))
        self.assertEqual(S.freshness_expectation(home), "not_applicable")
        self.assertEqual(S.freshness_expectation(contact), "not_applicable")
        self.assertEqual(S.freshness_expectation(article), "expected")
        self.assertEqual(S.freshness_expectation(policy), "optional")
        dated = page(ORIGIN + "/", html_doc(title="Home", body="<h1>Home</h1><p>Last updated: "
                                                                 "1 September 2026</p>"))
        self.assertEqual(S.freshness_expectation(dated), "expected")

    def test_organization_fields_follow_the_site(self):
        docs = {"site_kind": "documentation", "physical_presence": False}
        shop = {"site_kind": "ecommerce", "sells_physical_goods": True, "transactions": True}
        self.assertEqual(S.organization_field_expectation("address", docs), "optional")
        self.assertEqual(S.organization_field_expectation("address", shop),
                         "required_when_applicable")
        self.assertEqual(S.organization_field_expectation("foundingDate", shop), "optional")
        self.assertEqual(S.organization_field_expectation("description", docs), "recommended")
        self.assertEqual(S.organization_field_expectation("contactPoint", docs), "optional")
        self.assertEqual(S.organization_field_expectation("contactPoint", shop), "recommended")

    def test_question_classes_by_site_kind(self):
        self.assertEqual(S.answerability_question_classes({"site_kind": "documentation"}), set())
        self.assertEqual(S.answerability_question_classes({"site_kind": "government"}), set())
        soft = S.answerability_question_classes({"site_kind": "software", "sells_software": True,
                                                 "sells_online": True})
        self.assertIn("product_price", soft)
        self.assertNotIn("product_availability", soft)
        self.assertNotIn("shipping_destinations", soft)
        shop = S.answerability_question_classes({"site_kind": "ecommerce",
                                                 "sells_physical_goods": True,
                                                 "sells_online": True, "transactions": True})
        self.assertIn("return_window", shop)

    def test_optional_metadata_ceiling(self):
        self.assertEqual(S.cap_optional("high"), "medium")
        self.assertEqual(S.cap_optional("critical"), "medium")
        self.assertEqual(S.cap_optional("low"), "low")


class TestHeadingAssessment(unittest.TestCase):
    def test_multiple_h1_with_one_naming_the_page_is_fine(self):
        p = page(ORIGIN + "/blog/kestrel-3-released", html_doc(
            title="Kestrel 3 released | Kestrel blog",
            body="<header><h1>Kestrel blog</h1></header><article><h1>Kestrel 3 released</h1>"
                 "<p>Today.</p></article>"))
        verdict = S.heading_assessment(p, template={"kestrel blog"})
        self.assertTrue(verdict["identifies_subject"])
        self.assertEqual(verdict["h1_count"], 2)

    def test_no_h1_but_an_h2_naming_the_page_is_fine(self):
        p = page(ORIGIN + "/docs/install", html_doc(
            title="Installation guide", body="<main><h2>Installation guide</h2><p>Steps.</p></main>"))
        self.assertTrue(S.heading_assessment(p)["identifies_subject"])

    def test_only_a_site_name_heading_does_not_identify(self):
        p = page(ORIGIN + "/products/x", html_doc(
            title="Trail Boot | Kestrel", body="<h1>Kestrel</h1><p>Boot.</p>"))
        verdict = S.heading_assessment(p, template={"kestrel"})
        self.assertFalse(verdict["identifies_subject"])

    def test_no_headings_at_all(self):
        p = page(ORIGIN + "/x", html_doc(title="X", body="<p>Nothing.</p>"))
        self.assertFalse(S.heading_assessment(p)["identifies_subject"])


class TestOutboundLinks(unittest.TestCase):
    def check(self, url, kind, **kwargs):
        verdict = S.classify_outbound_link(url, site_origin=ORIGIN, entity_names=["Kestrel"],
                                           **kwargs)
        self.assertEqual(verdict["kind"], kind, url)
        return verdict

    def test_profiles_versus_everything_else(self):
        self.check("https://www.linkedin.com/company/kestrel", "official_profile")
        self.check("https://x.com/kestrel", "official_profile")
        self.check("https://github.com/kestrel", "official_profile")
        self.check("https://github.com/kestrel/kestrel", "code_repository")
        self.check("https://en.wikipedia.org/wiki/Kestrel", "knowledge_reference")
        self.check("https://de.wikipedia.org/wiki/Turmfalke", "knowledge_reference")
        self.check("https://docs.example.org/en/latest/", "documentation")
        self.check("https://apps.apple.com/app/kestrel/id1", "product_listing")
        self.check("https://play.google.com/store/apps/details?id=org.kestrel", "product_listing")
        self.check("https://www.youtube.com/watch?v=abc", "unknown")
        self.check("https://www.facebook.com/sharer/sharer.php?u=http://x", "share_intent")
        self.check("https://www.trustpilot.com/review/shop.example", "review_listing")
        self.check(ORIGIN + "/de/", "language_variant")
        self.check("https://de.shop.example/", "language_variant")
        self.check(ORIGIN + "/about", "navigation")
        self.check("https://example.org/", "unknown")

    def test_rel_me_is_an_identity_claim_wherever_it_points(self):
        self.check("https://example.org/me", "official_profile", rel="me")

    def test_knowledge_reference_says_whether_it_is_about_the_entity(self):
        about = self.check("https://en.wikipedia.org/wiki/Kestrel_Foundation", "knowledge_reference")
        self.assertTrue(about["entity_match"])
        other = self.check("https://en.wikipedia.org/wiki/Bristol", "knowledge_reference")
        self.assertFalse(other["entity_match"])


def _org(name: str, extra: str = "", lang: str = "en") -> str:
    return ('{"@context":"https://schema.org","@type":"Organization","name":"%s","url":"/"%s}'
            % (name, extra))


class TestEntityRelationships(unittest.TestCase):
    def _relations(self, pages):
        return {(r["name"], r["relationship"]) for r in S.entity_relationships(bundle(pages))}

    def test_localized_name_is_a_localization_not_a_rival(self):
        home = page(ORIGIN + "/", html_doc(title="Kestrel Foundation", head=jsonld(_org("Kestrel Foundation")),
                                           body="<h1>Kestrel Foundation</h1>"))
        spanish = page(ORIGIN + "/es/", html_doc(
            title="Fundación Kestrel", lang="es", head=jsonld(_org("Fundación Kestrel")),
            body="<h1>Fundación Kestrel</h1>"))
        relations = self._relations([home, spanish])
        self.assertIn(("Kestrel Foundation", "primary_entity"), relations)
        self.assertIn(("Fundación Kestrel", "language_variant"), relations)

    def test_non_latin_rendering_is_a_localization(self):
        home = page(ORIGIN + "/", html_doc(title="Kestrel", head=jsonld(_org("Kestrel")),
                                           body="<h1>Kestrel</h1>"))
        japanese = page(ORIGIN + "/jp/", html_doc(
            title="ケストレル", head=jsonld(_org("ケストレル")), body="<h1>ケストレル</h1>"))
        self.assertIn(("ケストレル", "localization"), self._relations([home, japanese]))

    def test_department_and_subsidiary_from_parent_organization(self):
        home = page(ORIGIN + "/", html_doc(title="Kestrel Group", head=jsonld(_org("Kestrel Group")),
                                           body="<h1>Kestrel Group</h1>"))
        dept = page(ORIGIN + "/departments/finance", html_doc(
            title="Finance Department", head=jsonld(
                '{"@context":"https://schema.org","@type":"GovernmentOrganization",'
                '"name":"Department of Finance","parentOrganization":{"@type":"Organization",'
                '"name":"Kestrel Group"}}'),
            body="<h1>Department of Finance</h1>"))
        sub = page(ORIGIN + "/companies/kestrel-labs", html_doc(
            title="Kestrel Labs", head=jsonld(
                '{"@context":"https://schema.org","@type":"Organization","name":"Falcon Labs Ltd",'
                '"parentOrganization":{"@type":"Organization","name":"Kestrel Group"}}'),
            body="<h1>Falcon Labs Ltd</h1>"))
        relations = self._relations([home, dept, sub])
        self.assertIn(("Department of Finance", "department"), relations)
        self.assertIn(("Falcon Labs Ltd", "subsidiary"), relations)

    def test_product_brand_and_manufacturer_are_not_the_site(self):
        home = page(ORIGIN + "/", html_doc(title="Kestrel Outdoors", head=jsonld(_org("Kestrel Outdoors")),
                                           body="<h1>Kestrel Outdoors</h1>"))
        product = page(ORIGIN + "/products/boot", html_doc(
            title="Trail Boot", head=jsonld(
                '{"@context":"https://schema.org","@type":"Product","name":"Trail Boot",'
                '"brand":{"@type":"Brand","name":"Summit"},'
                '"manufacturer":{"@type":"Organization","name":"Summit Footwear GmbH"},'
                '"offers":{"@type":"Offer","price":"120","priceCurrency":"GBP"}}'),
            body="<main><h1>Trail Boot</h1><p>£120</p></main>"))
        relations = self._relations([home, product])
        self.assertIn(("Summit", "brand"), relations)
        self.assertIn(("Summit Footwear GmbH", "partner"), relations)

    def test_profiles_and_knowledge_links_are_told_apart(self):
        home = page(ORIGIN + "/", html_doc(title="Kestrel", head=jsonld(_org("Kestrel")),
                                           body='<h1>Kestrel</h1><footer>'
                                                '<a href="https://www.linkedin.com/company/kestrel">LinkedIn</a>'
                                                '<a href="https://en.wikipedia.org/wiki/Kestrel">Wikipedia</a>'
                                                '</footer>'))
        relations = self._relations([home])
        self.assertIn(("kestrel", "official_profile"), relations)
        self.assertIn(("https://en.wikipedia.org/wiki/Kestrel", "knowledge"), relations)


class TestTransportVerdict(unittest.TestCase):
    def test_not_found_versus_unverified(self):
        self.assertEqual(S.transport_verdict(404)["verdict"], "not_found")
        self.assertEqual(S.transport_verdict(410)["verdict"], "not_found")
        for status in (403, 429, 401, 500, 502, 503, 999):
            self.assertEqual(S.transport_verdict(status)["verdict"], "unverified", status)
        self.assertEqual(S.transport_verdict(200)["verdict"], "verified")
        self.assertEqual(S.transport_verdict(301)["verdict"], "verified")
        self.assertEqual(S.transport_verdict(0, "timed out")["verdict"], "unverified")
        self.assertEqual(S.transport_verdict(0, "blocked by robots.txt")["verdict"], "unverified")
        self.assertEqual(S.transport_verdict(None, checked=False)["verdict"], "unverified")

    def test_reasons_name_the_transport_fact(self):
        self.assertIn("403", S.transport_verdict(403)["reason"])
        self.assertIn("timed out", S.transport_verdict(0, "request timed out")["reason"])


if __name__ == "__main__":
    unittest.main()
