"""The answerability skill, and the Priority-1 correctness regressions.

Two suites in one file because they share fixtures: the correctness fixes are
mostly about *not* asserting things the crawl did not observe, which is the
same principle the answerability engine is built on.
"""

from __future__ import annotations

import unittest

import helpers
from helpers import ORIGIN, bundle, find, html_doc, jsonld, page, run

from aiva import answerability, util
from aiva.analysis import commerce_evidence, crawl_yielded_evidence
from aiva.extract import PRICE_RE, classify_page, parse_amount, price_match_parts

FULL_LD = ('{"@context":"https://schema.org","@type":"Product","name":"Ledger Pad",'
           '"color":"Blue","material":"Paper",'
           '"additionalProperty":[{"@type":"PropertyValue","name":"Sheets","value":"80"},'
           '{"@type":"PropertyValue","name":"Weight","value":"200"}],'
           '"offers":{"@type":"Offer","price":"12.50","priceCurrency":"GBP",'
           '"availability":"https://schema.org/InStock"}}')

THIN_LD = ('{"@context":"https://schema.org","@type":"Product","name":"Sketch Pad"}')


def _product(path: str, ld: str, body: str) -> dict:
    url = ORIGIN + path
    return page(url, html_doc(canonical=url, head=jsonld(ld) if ld else "", body=body))


def shop_bundle() -> dict:
    home = page(ORIGIN + "/", html_doc(title="Quire", canonical=ORIGIN + "/",
                                       body='<h1>Quire</h1><a href="/collections/pads">Pads</a>'))
    listing = page(ORIGIN + "/collections/pads", html_doc(
        canonical=ORIGIN + "/collections/pads",
        body='<h1>Note Pads</h1><a href="/products/ledger">Ledger Pad</a>'
             '<a href="/products/sketch">Sketch Pad</a>'))
    rich = _product("/products/ledger", FULL_LD,
                    "<h1>Ledger Pad</h1><p>£12.50 — in stock.</p>"
                    "<table><tr><th>Sheets</th><td>80</td></tr>"
                    "<tr><th>Weight</th><td>200 gsm</td></tr></table>")
    thin = _product("/products/sketch", THIN_LD, "<h1>Sketch Pad</h1><p>A pad.</p>")
    return bundle([home, listing, rich, thin])


# ---------------------------------------------------------------------------
# Priority 1: correctness
# ---------------------------------------------------------------------------

class TestPriceExtraction(unittest.TestCase):
    """`$1200` read as 120 fabricated price conflicts against correct markup."""

    CASES = {
        "$1200": ("$", 1200.0), "₹1299": ("₹", 1299.0), "$25000": ("$", 25000.0),
        "19,99 €": ("€", 19.99), "1 299 kr": ("kr", 1299.0), "CHF 89.00": ("CHF", 89.0),
        "$1,299.50": ("$", 1299.5), "€5.499": ("€", 5499.0), "Rs. 499": ("Rs", 499.0),
        "USD 25000": ("USD", 25000.0), "120 kr": ("kr", 120.0), "$0.99": ("$", 0.99),
        "89,00 zł": ("zł", 89.0), "฿1500": ("฿", 1500.0),
    }

    def test_every_common_currency_format_parses_exactly(self):
        for raw, (currency, value) in self.CASES.items():
            matches = list(PRICE_RE.finditer(raw))
            self.assertTrue(matches, f"no match for {raw!r}")
            got_currency, amount = price_match_parts(matches[0])
            self.assertEqual(got_currency, currency, raw)
            self.assertEqual(parse_amount(amount), value, raw)

    def test_no_digits_are_truncated(self):
        """The original defect: a grouped alternative matching a prefix."""
        for raw, expected in (("$1200", 1200.0), ("$25000", 25000.0),
                              ("₹1299", 1299.0), ("$999999", 999999.0)):
            match = PRICE_RE.search(raw)
            self.assertEqual(parse_amount(price_match_parts(match)[1]), expected, raw)

    def test_a_symbol_belongs_to_the_number_that_follows_it(self):
        """Product names ending in digits must not absorb the next price."""
        for raw, expected in (("Cafetera Vento 300 €5.499", 5499.0),
                              ("Model 3 $42,000", 42000.0),
                              ("Pack of 12 £9.99", 9.99)):
            values = [parse_amount(price_match_parts(m)[1])
                      for m in PRICE_RE.finditer(raw)]
            self.assertEqual(values, [expected], raw)

    def test_ordinary_numbers_are_not_prices(self):
        for raw in ("call 555 1234", "no price here", "80 sheets", "200 gsm"):
            self.assertIsNone(PRICE_RE.search(raw), raw)


class TestUnicodeWordCount(unittest.TestCase):
    """Cyrillic and Japanese counted as zero words, firing every thin-content rule."""

    def test_non_latin_scripts_are_counted(self):
        for text in ("Привет мир как дела", "これは日本語のテキストです",
                     "مرحبا بالعالم", "Το κείμενο είναι ελληνικό", "यह हिंदी पाठ है"):
            self.assertGreater(util.word_count(text), 0, text)

    def test_latin_counting_is_unchanged(self):
        self.assertEqual(util.word_count("Hello world"), 2)
        self.assertEqual(util.word_count("Grüße aus München"), 3)
        self.assertEqual(util.word_count(""), 0)

    def test_a_substantial_non_latin_page_is_not_thin(self):
        body = "<h1>製品</h1><p>" + ("この製品は高品質な素材で作られています。" * 30) + "</p>"
        product = _product("/products/jp", THIN_LD, body)
        self.assertGreater(product["text_word_count"], 200)
        self.assertIsNone(find(run("crawl-render-audit", bundle([product])),
                               "CR-THIN-PRODUCT-HTML"))


class TestCrawlCompletenessGate(unittest.TestCase):
    """Absence is only meaningful when something was actually read."""

    def test_zero_pages_yields_no_absence_findings(self):
        empty = bundle([])
        self.assertFalse(crawl_yielded_evidence(empty))
        for skill in ("machine-readability-audit", "entity-audit",
                      "engagement-audit", "answerability-audit"):
            self.assertEqual(run(skill, empty), [], skill)

    def test_no_sitemap_is_not_reported_when_nothing_was_crawled(self):
        empty = bundle([], sitemaps=[{"url": ORIGIN + "/sitemap.xml", "source": "probe",
                                      "status": 404, "kind": None, "error": "HTTP 404"}])
        self.assertIsNone(find(run("crawl-render-audit", empty), "CR-NO-SITEMAP"))

    def test_a_partial_crawl_still_produces_findings(self):
        one = _product("/products/sketch", THIN_LD,
                       "<h1>Sketch Pad</h1><p>A pad. £4.00</p>"
                       "<form action='/cart'><button>Add to cart</button></form>")
        self.assertTrue(crawl_yielded_evidence(bundle([one])))
        self.assertTrue(run("machine-readability-audit", bundle([one])))

    def test_a_successful_crawl_is_unaffected(self):
        data = shop_bundle()
        self.assertTrue(crawl_yielded_evidence(data))
        self.assertTrue(run("engagement-audit", data))


class TestHomePageIsNeverSubstituted(unittest.TestCase):
    """A findings that says "the home page" must mean the home page."""

    def test_a_failed_home_fetch_yields_no_home_page(self):
        from aiva import evidence as ev
        product = _product("/products/ledger", FULL_LD, "<h1>Ledger Pad</h1>")
        data = bundle([product])
        data["site"]["home_url"] = ORIGIN + "/"
        self.assertIsNone(ev.home_page(data),
                          "an unfetchable home page is missing evidence, not the "
                          "first page that happened to be crawled")

    def test_home_identity_rules_suppress_rather_than_guess(self):
        product = _product("/products/ledger", FULL_LD, "<h1>Ledger Pad</h1>")
        data = bundle([product])
        data["site"]["home_url"] = ORIGIN + "/"
        self.assertIsNone(find(run("machine-readability-audit", data),
                               "MR-SITE-SCHEMA-MISSING"))

    def test_a_real_home_page_is_still_found(self):
        from aiva import evidence as ev
        data = shop_bundle()
        home = ev.home_page(data)
        self.assertIsNotNone(home)
        self.assertEqual(home.get("page_type"), "home")


class TestCommerceApplicability(unittest.TestCase):
    """A documentation site is not a broken shop."""

    def _docs(self):
        home = page(ORIGIN + "/", html_doc(
            title="Acme Docs", canonical=ORIGIN + "/",
            body="<h1>Acme Docs</h1><p>" + "The SDK. " * 60 + "</p>"
                 + "".join(f'<a href="/docs/g{i}">G{i}</a>' for i in range(8))))
        guides = [page(f"{ORIGIN}/docs/g{i}", html_doc(
            canonical=f"{ORIGIN}/docs/g{i}",
            body=f"<h1>Guide {i}</h1><p>" + "Call the API. " * 60 + "</p>"
                 + "".join(f'<a href="/docs/g{j}">G{j}</a>' for j in range(6))))
            for i in range(4)]
        return bundle([home] + guides)

    def test_commerce_evidence_distinguishes_the_three_site_types(self):
        self.assertFalse(commerce_evidence(self._docs())["is_commerce"])
        self.assertTrue(commerce_evidence(shop_bundle())["is_commerce"])

    def test_a_docs_site_gets_no_commerce_finding(self):
        found = run("crawl-render-audit", self._docs())
        self.assertIsNone(find(found, "CR-COMMERCE-NOT-LINKED-FROM-HOME"))

    def test_a_docs_site_is_asked_no_commerce_questions(self):
        matrix = answerability.build_matrix(self._docs())
        kinds = {row["kind"] for row in matrix["questions"]}
        for commerce_kind in ("return_window", "shipping_destinations", "payment_options"):
            self.assertNotIn(commerce_kind, kinds)
        self.assertTrue(any("commerce-specific" in note for note in matrix["notes"]))

    def test_a_shop_is_asked_commerce_questions(self):
        kinds = {row["kind"] for row in answerability.build_matrix(shop_bundle())["questions"]}
        self.assertIn("return_window", kinds)


class TestSampleSizeCeiling(unittest.TestCase):
    """One sampled URL cannot establish a site-wide blocker."""

    def test_severity_is_capped_by_sample_size(self):
        from aiva.analysis import cap_severity, scope_for, severity_from_sample
        self.assertEqual(severity_from_sample(1.0, 1), "medium")
        self.assertEqual(severity_from_sample(1.0, 2), "high")
        self.assertEqual(severity_from_sample(1.0, 3), "critical")
        self.assertEqual(cap_severity("critical", 1), "medium")
        self.assertEqual(cap_severity("low", 1), "low")

    def test_scope_is_not_template_wide_from_one_page(self):
        from aiva.analysis import scope_for
        self.assertEqual(scope_for(1, 1), "page")
        self.assertEqual(scope_for(2, 2), "section")
        self.assertEqual(scope_for(3, 3), "template")


class TestPageClassification(unittest.TestCase):
    """URL shape alone misclassifies documentation and misses unusual products."""

    def test_a_doc_page_under_a_product_shaped_url_is_an_article(self):
        art = '{"@context":"https://schema.org","@type":"TechArticle","headline":"Start"}'
        url = "https://x.example/docs/p/getting-started"
        self.assertEqual(page(url, html_doc(canonical=url, head=jsonld(art),
                                            body="<h1>Start</h1>"))["page_type"], "article")

    def test_a_product_at_an_opaque_url_is_still_a_product(self):
        url = "https://x.example/item.php?id=42"
        self.assertEqual(page(url, html_doc(canonical=url, head=jsonld(FULL_LD),
                                            body="<h1>Ledger</h1>"))["page_type"], "product")

    def test_a_listing_with_embedded_products_is_still_a_category(self):
        url = "https://x.example/collections/all"
        self.assertEqual(page(url, html_doc(canonical=url, head=jsonld(FULL_LD),
                                            body="<h1>All</h1>"))["page_type"], "category")


class TestSmallerFalsePositives(unittest.TestCase):
    def test_a_brand_first_title_is_not_two_brands(self):
        org = ('{"@context":"https://schema.org","@type":"Organization",'
               '"name":"Acme","url":"https://shop.example/"}')
        for title in ("Acme | Organic Coffee Roasters", "Organic Coffee Roasters | Acme"):
            home = page(ORIGIN + "/", html_doc(
                title=title, canonical=ORIGIN + "/",
                head='<meta property="og:site_name" content="Acme">' + jsonld(org),
                body="<h1>Acme</h1>"))
            self.assertIsNone(find(run("entity-audit", bundle([home])),
                                   "EN-NAME-INCONSISTENT"), title)

    def test_an_explicit_empty_alt_is_not_a_missing_alt(self):
        body = "<h1>P</h1>" + "".join(
            f'<img src="/i{i}.jpg" alt="">' for i in range(6))
        pages = [_product(f"/products/p{i}", THIN_LD, body) for i in range(3)]
        self.assertIsNone(find(run("machine-readability-audit", bundle(pages)),
                               "MR-IMAGE-ALT-COVERAGE"))

    def test_images_with_no_alt_attribute_are_still_reported(self):
        body = "<h1>P</h1>" + "".join(f'<img src="/i{i}.jpg">' for i in range(6))
        pages = [_product(f"/products/p{i}", THIN_LD, body) for i in range(3)]
        self.assertIsNotNone(find(run("machine-readability-audit", bundle(pages)),
                                   "MR-IMAGE-ALT-COVERAGE"))

    def test_a_full_width_question_mark_is_a_question(self):
        from aiva.extract import QUESTION_RE
        for q in ("どうやって返品しますか？", "How do I return an item?", "كيف أرجع المنتج؟"):
            self.assertTrue(QUESTION_RE.match(q), q)


# ---------------------------------------------------------------------------
# the answerability skill
# ---------------------------------------------------------------------------

class TestQuestionGeneration(unittest.TestCase):
    """Questions come from the site, never from a stock list."""

    def test_no_questions_without_evidence(self):
        matrix = answerability.build_matrix(bundle([]))
        self.assertEqual(matrix["questions"], [])
        self.assertEqual(matrix["total_questions"], 0)
        self.assertIsNone(matrix["answerability_score"])
        self.assertTrue(matrix["notes"])

    def test_questions_name_products_the_crawl_actually_saw(self):
        matrix = answerability.build_matrix(shop_bundle())
        asked = " ".join(row["question"] for row in matrix["questions"])
        self.assertIn("Ledger Pad", asked)
        self.assertIn("Sketch Pad", asked)
        self.assertNotIn("<Product", asked)

    def test_comparison_needs_two_products(self):
        one = shop_bundle()
        one["pages"] = [p for p in one["pages"] if "sketch" not in (p.get("url") or "")]
        kinds = {r["kind"] for r in answerability.build_matrix(one)["questions"]}
        self.assertNotIn("product_comparison", kinds)
        self.assertIn("product_comparison",
                      {r["kind"] for r in
                       answerability.build_matrix(shop_bundle())["questions"]})

    def test_generation_is_deterministic(self):
        first = answerability.build_matrix(shop_bundle())
        second = answerability.build_matrix(shop_bundle())
        self.assertEqual([r["question"] for r in first["questions"]],
                         [r["question"] for r in second["questions"]])
        self.assertEqual(first["counts"], second["counts"])


class TestQuestionResolution(unittest.TestCase):
    def setUp(self):
        self.matrix = answerability.build_matrix(shop_bundle())
        self.rows = {(r["kind"], r["question"]): r for r in self.matrix["questions"]}

    def _row(self, kind: str, needle: str) -> dict:
        for (row_kind, question), row in self.rows.items():
            if row_kind == kind and needle in question:
                return row
        self.fail(f"no {kind} question mentioning {needle!r}")

    def test_typed_price_is_answerable_and_cites_its_source(self):
        row = self._row("product_price", "Ledger Pad")
        self.assertEqual(row["status"], "answerable")
        self.assertIn("12.50", row["evidence"])
        self.assertTrue(row["citing_url"])
        self.assertEqual(row["evidence_source"], "Offer.price in JSON-LD")

    def test_a_missing_fact_is_not_answerable_and_says_what_is_missing(self):
        row = self._row("product_price", "Sketch Pad")
        self.assertEqual(row["status"], "not_answerable")
        self.assertTrue(row["missing"])
        self.assertTrue(row["suggested_action"])

    def test_every_row_carries_the_required_fields(self):
        for row in self.matrix["questions"]:
            for field in ("kind", "question", "status", "citing_url",
                          "evidence", "evidence_source", "missing", "suggested_action"):
                self.assertIn(field, row)
            self.assertIn(row["status"], answerability.STATUSES)
            self.assertTrue(row["question"].endswith("?"))
            self.assertTrue(row["evidence"].strip())

    def test_prose_only_facts_are_partial_not_answerable(self):
        prose = _product("/products/prose", THIN_LD,
                         "<h1>Prose Pad</h1><p>£4.00 — in stock now.</p>")
        matrix = answerability.build_matrix(bundle([prose]))
        price = [r for r in matrix["questions"] if r["kind"] == "product_price"][0]
        self.assertEqual(price["status"], "partial")
        self.assertIn("visible", price["evidence_source"])

    def test_the_score_reflects_the_verdicts(self):
        matrix = self.matrix
        counts = matrix["counts"]
        expected = round(100.0 * (counts["answerable"] + 0.5 * counts["partial"])
                         / matrix["total_questions"], 1)
        self.assertEqual(matrix["answerability_score"], expected)


class TestAnswerabilityFindings(unittest.TestCase):
    def test_findings_are_produced_and_valid(self):
        found = run("answerability-audit", shop_bundle())
        self.assertTrue(found)
        for item in found:
            self.assertEqual(item.problems(), [])
            self.assertEqual(item.pillar, "answerability")
            self.assertEqual(item.source_skill, "answerability-audit")
            self.assertTrue(item.reasoning.strip())

    def test_findings_cite_the_question_and_the_url(self):
        found = run("answerability-audit", shop_bundle())
        for item in found:
            self.assertTrue(item.evidence_items)
            self.assertTrue(any("?" in e.observation for e in item.evidence_items))

    def test_a_well_answered_site_scores_higher_than_a_thin_one(self):
        rich_only = bundle([_product("/products/ledger", FULL_LD,
                                     "<h1>Ledger Pad</h1><p>£12.50 — in stock.</p>")])
        thin_only = bundle([_product("/products/sketch", THIN_LD,
                                     "<h1>Sketch Pad</h1><p>A pad.</p>"
                                     "<form action='/cart'><button>Add to cart</button></form>")])
        rich = answerability.build_matrix(rich_only)
        thin = answerability.build_matrix(thin_only)
        self.assertGreater(rich["answerability_score"], thin["answerability_score"])
        self.assertLess(rich["counts"]["not_answerable"],
                        thin["counts"]["not_answerable"])

    def test_the_skill_performs_no_network_io(self):
        import ast
        from pathlib import Path
        source = (helpers.ROOT / "skills/answerability-audit/scripts/analyze.py").read_text()
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for banned in ("urllib", "http", "requests", "socket", "httpx"):
            self.assertNotIn(banned, imported)


class TestAPolicyQuoteStatesATerm(unittest.TestCase):
    """A sentence that mentions the topic is not a statement of the terms.

    Every case here comes from one live report, of a site whose *subject
    matter* is commerce. The vocabulary matched everywhere, because the site
    writes about shipping and returns on every page, and three questions were
    reported as answered in prose by sentences that state nothing:

    * a return window evidenced by "It includes a money-back guarantee. UPS
      Next Day Air Saver... UPS 2nd Day Air" - which passed the numeric test
      on the "2" in a courier's product name;
    * shipping destinations evidenced by a feature blurb, because the page's
      URL contained "shipping" and that waived the test entirely;
    * a product's stock state evidenced by advice about when inventory runs
      low.

    None of them is a wrong conclusion. Each is a wrong citation, which is
    worse: a reader who opens the page finds the sentence and no answer.
    """

    from aiva.answerability import _states_a_term as _term      # noqa: N805

    def _quote(self, text):
        return {"quote": text, "phrase": "x", "region": "main content"}

    def test_a_courier_product_name_is_not_a_return_window(self):
        text = ("It includes a money-back guarantee. UPS Next Day Air Saver This service "
                "is an overnight, economical air service. UPS 2nd Day Air is an "
                "economical option")
        self.assertFalse(TestAPolicyQuoteStatesATerm._term(self._quote(text)))

    def test_a_stated_window_is_an_answer(self):
        for text in ("You can return any item within 30 days of delivery.",
                     "Returns are accepted for thirty days from delivery.",
                     "Devoluciones gratuitas en 30 dias desde la entrega.",
                     "Free returns, always."):
            with self.subTest(text=text):
                self.assertTrue(TestAPolicyQuoteStatesATerm._term(self._quote(text)))

    def test_a_topic_mention_with_no_term_is_not(self):
        for text in ("Returns and claims Return Policy Exchange and Returns Policy "
                     "Discover the full details of our generous return policy",
                     "Shipping, included. All the rates and tools you need, no apps.",
                     "Learn more about our shipping options and delivery partners."):
            with self.subTest(text=text):
                self.assertFalse(TestAPolicyQuoteStatesATerm._term(self._quote(text)))

    def test_the_page_being_about_the_topic_does_not_waive_the_test(self):
        """A returns page is a reason to look there, not to accept a menu."""
        from aiva.answerability import _quote_answers
        chrome = self._quote("Returns and claims Return Policy Exchange and Returns Policy")
        page_about_returns = {"url": ORIGIN + "/customer-service/returns/return-policy",
                              "title": "Return policy", "h1_texts": ["Return policy"]}
        self.assertFalse(_quote_answers("return_window", page_about_returns,
                                        chrome, "returns"))


class TestHypotheticalProseIsNotAStatement(unittest.TestCase):
    """What a reader *could* see is not what this seller *does*."""

    def test_inventory_advice_does_not_state_a_products_stock(self):
        prose = ("A good POS system will share insights like when something's about to "
                 "run out of stock or what products need to move and should be put on sale.")
        self.assertIsNone(answerability.quote_concept({"main_text": prose, "text": prose}, "out_of_stock"))

    def test_a_how_to_guide_does_not_state_a_return_window(self):
        prose = ("Learn how to set up returns for your store. Tips for handling a refund "
                 "request when a customer changes their mind within 30 days.")
        self.assertIsNone(answerability.quote_concept({"main_text": prose, "text": prose}, "returns"))

    def test_a_real_stock_statement_still_matches(self):
        prose = "Kallvik shelf unit. In stock in Bengaluru, ready for collection today."
        self.assertIsNotNone(answerability.quote_concept({"main_text": prose, "text": prose}, "in_stock"))

    def test_a_real_return_statement_still_matches(self):
        prose = "We accept returns within 30 days of delivery, free of charge."
        self.assertIsNotNone(answerability.quote_concept({"main_text": prose, "text": prose}, "returns"))


class TestTheTopicWithoutTermsIsReportedHonestly(unittest.TestCase):
    """Three states, not two: stated, discussed-without-terms, and absent."""

    def _matrix(self, policy_body):
        home = page(ORIGIN + "/", html_doc(
            title="Shop", canonical=ORIGIN + "/",
            body="<h1>Shop</h1><a href='/products/x9'>X9</a>"))
        product = page(ORIGIN + "/products/x9", html_doc(
            title="X9", canonical=ORIGIN + "/products/x9",
            body="<main><h1>X9</h1><p>INR 5,499</p>"
                 "<form action='/cart/add'><button>Add to cart</button></form>"
                 "<table><tr><th>Weight</th><td>245 g</td></tr></table></main>"))
        policy = page(ORIGIN + "/pages/returns", html_doc(
            title="Returns", canonical=ORIGIN + "/pages/returns",
            body=f"<main><h1>Returns</h1>{policy_body}</main>"))
        return answerability.build_matrix(bundle([home, product, policy]))

    def _row(self, matrix):
        rows = [q for q in matrix["questions"] if q["kind"] == "return_window"]
        return rows[0] if rows else None

    def test_a_page_that_discusses_returns_without_terms_is_not_answerable(self):
        row = self._row(self._matrix("<p>Read our generous returns policy.</p>"))
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "not_answerable")

    def test_and_it_says_the_topic_was_discussed(self):
        row = self._row(self._matrix("<p>Read our generous returns policy.</p>"))
        self.assertIn("no page states the term", row["evidence"])

    def test_a_page_that_states_the_window_is_answerable_in_prose(self):
        row = self._row(self._matrix("<p>Return anything within 30 days for a refund.</p>"))
        self.assertEqual(row["status"], "partial")
        self.assertIn("30 days", row["evidence"])


class TestAQuestionNeedsAValidatedEntity(unittest.TestCase):
    """A generated question quotes its subject back to the reader.

    "What is the price of {{product.title}}?" cited to a live URL is worse
    than asking nothing: it looks exactly like a question about a product, and
    a reader has no way to tell the two apart. Where identity cannot be
    established the question is not asked - a missing question is a gap, an
    invented one is a wrong answer.
    """

    def _matrix_names(self, heading: str, ld: str = "") -> list:
        home = page(ORIGIN + "/", html_doc(
            title="Shop", canonical=ORIGIN + "/",
            body="<h1>Shop</h1><a href='/products/x9'>Item</a>"))
        product = page(ORIGIN + "/products/x9", html_doc(
            title=heading, canonical=ORIGIN + "/products/x9",
            head=jsonld(ld) if ld else "",
            body=f"<main><h1>{heading}</h1><p>INR 5,499 - in stock.</p>"
                 "<form action='/cart/add'><button>Add to cart</button></form>"
                 "<table><tr><th>Weight</th><td>245 g</td></tr></table></main>"))
        matrix = answerability.build_matrix(bundle([home, product]))
        return [q["question"] for q in matrix["questions"]]

    def test_a_real_product_name_produces_questions(self):
        questions = self._matrix_names("Aero Runner X9")
        self.assertTrue(any("Aero Runner X9" in q for q in questions),
                        f"a valid entity produced no product question: {questions}")

    def test_a_template_token_produces_none(self):
        for heading in ("{{product.title}}", "{product_name}", "${title}"):
            with self.subTest(heading=heading):
                questions = self._matrix_names(heading)
                self.assertFalse(any(heading in q for q in questions),
                                 f"a template token became a question: {questions}")

    def test_a_component_name_produces_none(self):
        for heading in ("ProductTile__price--sale", "productDetailHeroBanner",
                        "hero-banner-primary-cta-v2", "data-testid"):
            with self.subTest(heading=heading):
                self.assertFalse(any(heading in q for q in self._matrix_names(heading)))

    def test_a_placeholder_produces_none(self):
        for heading in ("Product Name", "Untitled", "lorem ipsum", "TBD", "N/A"):
            with self.subTest(heading=heading):
                self.assertFalse(any(heading in q for q in self._matrix_names(heading)))

    def test_markup_with_a_bad_name_falls_through_to_the_heading(self):
        """A template token in the markup does not poison a valid heading."""
        ld = ('{"@context":"https://schema.org","@type":"Product",'
              '"name":"{{product.title}}","offers":{"@type":"Offer","price":"5499"}}')
        questions = self._matrix_names("Aero Runner X9", ld)
        self.assertTrue(any("Aero Runner X9" in q for q in questions))
        self.assertFalse(any("{{product.title}}" in q for q in questions))

    def test_no_valid_identity_means_no_product_question_at_all(self):
        matrix_questions = self._matrix_names("{{product.title}}")
        product_scoped = [q for q in matrix_questions
                          if "price of" in q or "specifications of" in q]
        self.assertEqual(product_scoped, [])


class TestRecommendationsDoNotClaimMeasuredBehaviour(unittest.TestCase):
    """The audit generates questions from a catalogue, not from anyone's
    behaviour, and its wording has to say which."""

    def _texts(self):
        product = page(ORIGIN + "/products/aero", html_doc(
            title="Aero Runner", canonical=ORIGIN + "/products/aero",
            body="<main><h1>Aero Runner</h1><p>INR 5,499</p>"
                 "<table><tr><th>Weight</th><td>245 g</td></tr>"
                 "<tr><th>Drop</th><td>8 mm</td></tr></table></main>"))
        home = page(ORIGIN + "/", html_doc(title="Shop", canonical=ORIGIN + "/"))
        from aiva.recommend import build_opportunities
        for opportunity in build_opportunities(bundle([home, product]), []):
            yield opportunity["id"], " ".join(
                [opportunity["mechanism"], opportunity["why_now"]] + opportunity["steps"])

    def test_no_recommendation_claims_to_know_what_buyers_ask(self):
        banned = ("buyers most often ask", "the questions people actually ask",
                  "customers most often ask")
        for oid, text in self._texts():
            for phrase in banned:
                with self.subTest(recommendation=oid, phrase=phrase):
                    self.assertNotIn(phrase, text.lower())

    def test_asking_the_reader_for_their_own_data_is_still_allowed(self):
        """The useful version of the advice survives: the site owner *does*
        have this data, and pointing them at it is the recommendation."""
        texts = dict(self._texts())
        if "OPP-ANSWER-PAGES" in texts:
            self.assertIn("support tickets", texts["OPP-ANSWER-PAGES"])


if __name__ == "__main__":
    unittest.main()
