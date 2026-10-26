"""Regression suite for the generalization pass.

Every test here failed before the fix it names. Together they answer a
question the rest of the suite does not ask.

The existing suites prove the rules *fire* on sites that are broken. They say
almost nothing about whether the rules stay *quiet* on sites that are fine but
unfamiliar - a fully server-rendered React site, a quote-on-request industrial
catalogue, a Polish storefront, a newspaper, an Indian price. Those are the
sites a submission graded on unseen websites actually meets, and each one below
produced a confident wrong finding, several of them at `critical`, which is the
severity that writes the report headline.

So the assertions are mostly negative. A false positive on a healthy site is
more expensive than a miss on a broken one: the miss costs a line in a report,
the false positive costs the reader's trust in every other line. Where a rule
is silenced, a paired test asserts the genuine defect is still caught, because
a guard that suppresses everything is not a fix.
"""

from __future__ import annotations

import unittest

from helpers import ORIGIN, bundle, find, html_doc, jsonld, page, run

from aiva import extract, lexicon, robots, util
from aiva.analysis import commerce_evidence
from aiva.config import AI_CRAWLER_AGENTS, MUTATING_QUERY_RE

NEXT_PAYLOAD = ('<script id="__NEXT_DATA__" type="application/json">'
                '{"props":{"pageProps":{}}}</script>')


# ---------------------------------------------------------------------------
# robots.txt correctness
# ---------------------------------------------------------------------------

class TestRobotsMatching(unittest.TestCase):
    """RFC 9309 §2.2.1: the product token is matched by prefix, not substring."""

    def _robots(self, body: str) -> robots.RobotsTxt:
        return robots.RobotsTxt.from_response("https://x/robots.txt", 200, body, None)

    def test_short_generic_token_does_not_capture_every_assistant(self):
        """`User-agent: bot` names one crawler, not ten.

        Substring matching made this block GPTBot, ClaudeBot, PerplexityBot and
        seven more, and `rule_ai_crawlers_blocked` is hardcoded to `critical` -
        so a common blanket-scraper block fabricated the report's headline.
        """
        parsed = self._robots("User-agent: bot\nDisallow: /\n")
        blocked = [a for a in AI_CRAWLER_AGENTS if parsed.agent_summary(a)["blocks_site"]]
        self.assertEqual(blocked, [])

    def test_prefix_match_still_works(self):
        parsed = self._robots("User-agent: GPTBot\nDisallow: /\n")
        blocked = [a for a in AI_CRAWLER_AGENTS if parsed.agent_summary(a)["blocks_site"]]
        self.assertEqual(blocked, ["GPTBot"])

    def test_repeated_groups_for_one_agent_are_merged(self):
        """A duplicated record's rules are not silently dropped.

        The failure direction was "fetch something the site disallowed", which
        is the one direction a read-only auditor must never fail in.
        """
        parsed = self._robots("User-agent: X\nDisallow: /private/\n\n"
                              "User-agent: X\nDisallow: /secret/\n")
        self.assertFalse(parsed.can_fetch("X", "/private/a"))
        self.assertFalse(parsed.can_fetch("X", "/secret/a"))

    def test_merged_group_keeps_the_politest_crawl_delay(self):
        parsed = self._robots("User-agent: X\nCrawl-delay: 1\n\n"
                              "User-agent: X\nCrawl-delay: 4\n")
        self.assertEqual(parsed.crawl_delay_for("X"), 4.0)

    def test_empty_allow_is_not_a_rule(self):
        """An empty `Allow:` built a zero-length pattern matching every path.

        It never overrode a real disallow, but it became the cited
        `deciding_rule` - so the report offered `allow: ''` as evidence.
        """
        parsed = self._robots("User-agent: *\nAllow:\nDisallow: /x/\n")
        self.assertIsNone(parsed.decision("*", "/y")[1])
        self.assertTrue(parsed.can_fetch("*", "/y"))
        self.assertFalse(parsed.can_fetch("*", "/x/a"))


# ---------------------------------------------------------------------------
# client-rendering detection
# ---------------------------------------------------------------------------

class TestRenderShellDetection(unittest.TestCase):

    def _ssr_page(self, path: str, heading: str, words: str) -> dict:
        return page(ORIGIN + path,
                    html_doc(title=heading,
                             body=f'<div id="__next"><h1>{heading}</h1><p>{words}</p></div>'
                                  + NEXT_PAYLOAD))

    def test_server_rendered_next_js_is_not_an_empty_shell(self):
        """`__NEXT_DATA__` is on every Next.js page, SSR ones included.

        Treating it as sufficient, with a flat 120-word floor, reported a
        fully server-rendered site as blank at `critical` and prescribed an
        SSR migration to a site that already does SSR.
        """
        pages = [
            self._ssr_page("/", "Acme Legal", "We advise on corporate transactions. " * 40),
            self._ssr_page("/privacy", "Privacy Policy",
                           "We collect no personal data beyond what you submit through the "
                           "contact form, and we never sell it."),
            self._ssr_page("/contact", "Contact",
                           "Call 555-0100 or email hello@example.com; the office is open "
                           "on weekdays."),
        ]
        self.assertIsNone(find(run("crawl-render-audit", bundle(pages)),
                               "CR-JS-RENDERED-SHELL"))

    def test_a_genuinely_empty_mount_point_is_still_reported(self):
        pages = [page(ORIGIN + "/", html_doc(body='<div id="root"></div>' + NEXT_PAYLOAD)),
                 page(ORIGIN + "/products/a",
                      html_doc(body='<div id="root"><p>Loading…</p></div>' + NEXT_PAYLOAD)),
                 page(ORIGIN + "/products/b",
                      html_doc(body='<div id="app"></div>' + NEXT_PAYLOAD))]
        item = find(run("crawl-render-audit", bundle(pages)), "CR-JS-RENDERED-SHELL")
        self.assertIsNotNone(item)

    def test_hydration_payload_is_recorded_separately_from_an_empty_mount(self):
        facts = page(ORIGIN + "/", html_doc(
            body='<div id="__next"><h1>Full</h1><p>' + ("content " * 200) + '</p></div>'
                 + NEXT_PAYLOAD))
        self.assertEqual(facts["scripts"]["spa_markers"], [])
        self.assertTrue(facts["scripts"]["hydration_markers"])


# ---------------------------------------------------------------------------
# is this site even a shop?
# ---------------------------------------------------------------------------

class TestCommerceGuard(unittest.TestCase):

    def _archive(self, slug: str) -> dict:
        url = f"{ORIGIN}/category/{slug}/"
        body = (f'<h1>{slug.title()}</h1>'
                f'<a href="/2019/03/one-story">One story</a>'
                f'<a href="/2020/07/another-story">Another story</a>')
        return page(url, html_doc(title=slug.title(), body=body,
                                  head=jsonld('{"@context":"https://schema.org",'
                                              '"@type":"NewsArticle","headline":"X"}')))

    def test_wordpress_archives_are_not_a_catalogue(self):
        """`/category/<slug>/` is the default WordPress archive path.

        `commerce_guard` existed, was documented, and was never called, so a
        newspaper was told its category pages expose no filters - with a
        remediation naming "the attributes these product pages already publish".
        """
        news = bundle([self._archive(s) for s in ("politics", "sport", "culture")])
        self.assertFalse(commerce_evidence(news)["is_commerce"])
        found = run("engagement-audit", news)
        for rule in ("EG-FILTER-CONTROLS-ABSENT", "EG-SORT-CONTROLS-ABSENT",
                     "EG-COMPARISON-UNSUPPORTED", "EG-POLICY-NOT-STRUCTURED"):
            self.assertIsNone(find(found, rule), f"{rule} fired on a news archive")

    def test_a_storefront_collection_page_is_still_a_catalogue(self):
        """The guard must not silence shops whose crawl reached only listings."""
        url = ORIGIN + "/collections/all"
        grid = "".join(f'<a href="/products/{c}">{c.upper()}</a>' for c in "abcdefghij")
        listing = page(url, html_doc(body='<h1>All</h1>' + grid))
        shop = bundle([listing])
        self.assertTrue(commerce_evidence(shop)["is_commerce"])
        self.assertIsNotNone(find(run("engagement-audit", shop),
                                  "EG-FILTER-CONTROLS-ABSENT"))


# ---------------------------------------------------------------------------
# language
# ---------------------------------------------------------------------------

class TestNonEnglishSites(unittest.TestCase):

    POLISH_BODY = ('<h1>Kubek Ceramiczny</h1>'
                   '<p>Produkt dostępny od ręki. Wysyłka w 24 godziny. '
                   'Zwroty do 30 dni.</p>'
                   '<p>Opinie klientów: 4,8 na 5 (127 ocen)</p>'
                   '<p><a href="/porownaj">Porównaj z innymi modelami</a></p>'
                   '<p>149,00 zł</p><button>Dodaj do koszyka</button>')

    def _polish_shop(self):
        pages = [page(ORIGIN + "/", html_doc(title="Sklep", lang="pl",
                                             body='<h1>Sklep</h1><a href="/products/a">A</a>'))]
        pages += [page(f"{ORIGIN}/products/kubek-{i}",
                       html_doc(title=f"Kubek {i}", lang="pl", body=self.POLISH_BODY))
                  for i in range(3)]
        return bundle(pages)

    def test_polish_storefront_is_not_told_it_states_nothing(self):
        """Three engagement rules skipped the guard their siblings applied.

        Each produced an evidence string the page in front of the reader
        refutes - the worst class of false positive, because it is checkable.
        """
        found = run("engagement-audit", self._polish_shop())
        for rule in ("EG-REVIEWS-ABSENT", "EG-AVAILABILITY-INVISIBLE",
                     "EG-COMPARISON-UNSUPPORTED"):
            self.assertIsNone(find(found, rule), f"{rule} fired on a Polish storefront")

    def test_localized_home_label_is_not_a_second_brand(self):
        """"Inicio" is not a trading name.

        With an English-only noise list the word-count tiebreak returned the
        localized "Home" as the brand, and the site was reported as calling
        itself two different things at `high`.
        """
        for title, lang in (("Bodegas Ejemplo S.L. | Inicio", "es"),
                            ("Cabinet Dupont et Associes - Accueil", "fr"),
                            ("Moebel Schmidt | Startseite", "de"),
                            ("Winkel Jansen | Startpagina", "nl")):
            with self.subTest(title=title):
                name = title.split("|")[0].split(" - ")[0].strip()
                org = jsonld('{"@context":"https://schema.org","@type":"Organization",'
                             '"name":"%s","url":"%s/","description":"A company.",'
                             '"logo":"%s/l.png"}' % (name, ORIGIN, ORIGIN))
                home = page(ORIGIN + "/", html_doc(title=title, lang=lang, head=org,
                                                   body="<h1>X</h1><p>We make things.</p>"))
                self.assertIsNone(
                    find(run("entity-audit", bundle([home])), "EN-NAME-INCONSISTENT"))

    def test_localized_search_form_is_recognised(self):
        for action in ("/recherche", "/buscar", "/suche", "/ricerca", "/ara", "/szukaj"):
            with self.subTest(action=action):
                facts = page(ORIGIN + "/", html_doc(
                    body=f'<form action="{action}"><input type="text" name="q"></form>'))
                self.assertTrue(facts["forms"]["has_site_search"])

    def test_footer_boilerplate_is_not_a_returns_policy(self):
        """"Return to top" is a scroll link; "return on investment" is a metric."""
        self.assertFalse(lexicon.mentions("returns", "Return to top"))
        self.assertFalse(lexicon.mentions("returns", "Return on investment (ROI)"))
        self.assertFalse(lexicon.mentions("shipping", "Content delivery network"))
        self.assertFalse(lexicon.mentions("reviews", "Energy rating A++"))
        self.assertTrue(lexicon.mentions("returns", "Free returns within 30 days"))
        self.assertTrue(lexicon.mentions("shipping", "Free shipping over $50"))

    def test_non_latin_names_survive_normalisation(self):
        """ASCII folding collapsed a catalogue into one name, or into none.

        Three distinct Chinese products all normalised to their Latin trim
        marker and were reported as duplicates; Cyrillic and Greek names
        normalised to the empty string, which switched the entity rules off
        without the report ever saying so.
        """
        self.assertNotEqual(util.normalize_name("小米手机 Pro"),
                            util.normalize_name("小米平板 Pro"))
        self.assertTrue(util.normalize_name("Ромашка"))
        self.assertTrue(util.normalize_name("Καφές"))
        self.assertEqual(util.normalize_name("Café Nero™"), "cafe nero")


# ---------------------------------------------------------------------------
# prices
# ---------------------------------------------------------------------------

class TestPriceParsing(unittest.TestCase):

    def test_indian_lakh_grouping(self):
        """`₹1,20,000` is 120000, not 1.2.

        Requiring three-digit groups made the grouped branch fail and the plain
        branch match `1,20` - fabricating an `FC-PRICE-CONFLICT` reading
        "markup says 120000, page shows 1.2" on a page where the text and the
        JSON-LD agreed exactly.
        """
        for text, expected in (("₹1,20,000", 120000.0), ("₹12,34,567", 1234567.0),
                               ("Rs. 1,20,000", 120000.0), ("1,20,000 INR", 120000.0)):
            with self.subTest(text=text):
                found = extract._extract_prices(text)
                self.assertTrue(found, f"no price parsed from {text}")
                self.assertEqual(found[0]["value"], expected)

    def test_western_grouping_is_unchanged(self):
        for text, expected in (("$1,299.00", 1299.0), ("€1.299,00", 1299.0),
                               ("$1200", 1200.0), ("19,99 €", 19.99),
                               ("12,345,678 JPY", 12345678.0)):
            with self.subTest(text=text):
                self.assertEqual(extract._extract_prices(text)[0]["value"], expected)

    def test_south_east_asian_spellings_are_recognised(self):
        for text in ("₱1,299", "Rp 150.000", "RM 89.00", "S$149.90"):
            with self.subTest(text=text):
                self.assertTrue(extract._extract_prices(text), f"no price parsed from {text}")

    def test_model_numbers_are_not_prices(self):
        self.assertEqual(extract._extract_prices("Vento 300"), [])
        self.assertEqual(extract._extract_prices("Model 400 Centrifuge"), [])


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------

class TestStaleContent(unittest.TestCase):

    def _story(self, slug: str, published: str) -> dict:
        url = f"{ORIGIN}/news/{slug}"
        return page(url, html_doc(
            title=slug, body=f"<h1>{slug}</h1><p>" + ("Reporting. " * 60) + "</p>",
            head=jsonld('{"@context":"https://schema.org","@type":"NewsArticle",'
                        '"headline":"%s","datePublished":"%s"}' % (slug, published))))

    def test_a_correctly_dated_archive_is_not_stale(self):
        """A 2019 news story is correctly dated 2019.

        With no page-type gate and no ratio gate, one old page promoted the
        whole finding to `high` - and the implied fix was to falsify the date.
        """
        pages = [page(ORIGIN + "/", html_doc(body="<h1>The Example Herald</h1>"
                                                  "<p>" + ("News. " * 60) + "</p>")),
                 self._story("one", "2019-03-04"),
                 self._story("two", "2018-11-20")]
        self.assertIsNone(find(run("freshness-corroboration", bundle(pages)),
                               "FC-STALE-CONTENT"))

    def test_an_unmaintained_policy_page_is_still_reported(self):
        pages = []
        for slug in ("returns", "shipping", "terms"):
            url = f"{ORIGIN}/policies/{slug}"
            pages.append(page(url, html_doc(
                title=slug, body=f"<h1>{slug}</h1><p>" + ("Policy text. " * 40) + "</p>",
                head=jsonld('{"@context":"https://schema.org","@type":"WebPage",'
                            '"name":"%s","dateModified":"2018-01-05"}' % slug))))
        self.assertIsNotNone(find(run("freshness-corroboration", bundle(pages)),
                                  "FC-STALE-CONTENT"))


# ---------------------------------------------------------------------------
# coverage honesty
# ---------------------------------------------------------------------------

class TestCoverageHonesty(unittest.TestCase):

    def test_absence_claims_name_the_paths_robots_hid(self):
        """`blocked_by_robots` was recorded and no rule read it.

        A site whose robots.txt disallows `/faq` was told it "answers no
        questions in question form" - an assertion about the site made from
        pages the audit was never allowed to see.
        """
        pages = [page(f"{ORIGIN}/p{i}", html_doc(body=f"<h1>P{i}</h1><p>Text here.</p>"))
                 for i in range(3)]
        blocked = bundle(pages)
        blocked["blocked_by_robots"] = [
            {"url": ORIGIN + "/faq", "reason": "frontier", "rule": None},
            {"url": ORIGIN + "/help/returns", "reason": "frontier", "rule": None},
        ]
        item = find(run("engagement-audit", blocked), "EG-FAQ-MISSING")
        if item is not None:
            self.assertIn("robots.txt", item.evidence)
            self.assertEqual(item.severity, "low")

    def test_a_clean_crawl_carries_no_caveat(self):
        # The site declares an organisation, which is what gives the FAQ rule
        # an intent family to name; the caveat is what this test is about.
        org = ('{"@context":"https://schema.org","@type":"Organization",'
               '"name":"Laxton Supply","url":"%s/"}' % ORIGIN)
        pages = [page(ORIGIN + "/", html_doc(head=jsonld(org),
                                             body="<h1>Laxton Supply</h1><p>Text here.</p>"))]
        pages += [page(f"{ORIGIN}/p{i}", html_doc(body=f"<h1>P{i}</h1><p>Text here.</p>"))
                  for i in range(3)]
        item = find(run("engagement-audit", bundle(pages)), "EG-FAQ-MISSING")
        self.assertIsNotNone(item)
        self.assertNotIn("robots.txt", item.evidence)

    def test_a_site_the_audit_cannot_characterise_is_asked_for_no_questions(self):
        """The intents a finding names have to be earned. Three untyped pages
        that sell nothing, publish no articles and declare no organisation
        give the audit no basis for saying what this site's readers ask."""
        pages = [page(f"{ORIGIN}/p{i}", html_doc(body=f"<h1>P{i}</h1><p>Text here.</p>"))
                 for i in range(3)]
        self.assertIsNone(find(run("engagement-audit", bundle(pages)), "EG-FAQ-MISSING"))


# ---------------------------------------------------------------------------
# frontier hygiene
# ---------------------------------------------------------------------------

class TestFrontierFiltering(unittest.TestCase):

    def test_cart_mutating_query_strings_are_excluded(self):
        """One document fetched under three query strings counted as three pages.

        The politeness cost is small (no cookies are ever sent, so nothing
        actually mutates); the arithmetic cost is not, because every
        "N of M product pages" ratio is computed from that count.
        """
        for query in ("add-to-cart=5", "remove_item=5&_wpnonce=abc",
                      "add_to_wishlist=12", "wc-ajax=add_to_cart"):
            with self.subTest(query=query):
                self.assertTrue(MUTATING_QUERY_RE.search(query))

    def test_ordinary_query_strings_are_kept(self):
        for query in ("page=2", "colour=blue", "sort_by=price-ascending", "q=kettle"):
            with self.subTest(query=query):
                self.assertIsNone(MUTATING_QUERY_RE.search(query))

    def test_private_addresses_are_refused(self):
        """The audited site controls the anchors this tool verifies.

        Without a guard, a `sameAs` pointing at cloud instance metadata sent
        real requests to it - on exactly the kind of runner where it answers.
        """
        for host in ("169.254.169.254", "127.0.0.1", "10.0.0.5", "localhost",
                     "metadata.google.internal", "[::1]"):
            with self.subTest(host=host):
                self.assertTrue(util.is_private_host(host))
        self.assertFalse(util.is_private_host("example.com"))


if __name__ == "__main__":
    unittest.main()
