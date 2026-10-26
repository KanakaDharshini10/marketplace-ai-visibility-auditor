"""Answerability: can the crawled evidence actually answer a buyer's question?

Every other skill in this marketplace audits a *mechanism* - is the crawler
admitted, is the markup typed, is the entity resolvable. Those are necessary
conditions, and a site can satisfy all of them and still be useless to an
assistant, because nobody checked whether the resulting evidence answers a
question anyone would ask.

This module closes that loop. It generates questions **from the site's own
content**, resolves each one against the frozen evidence bundle, and records
what was found, where, and what was missing. The result is an answerability
matrix: a per-question verdict with a citing URL and a quoted snippet.

Three properties make it defensible rather than decorative:

* **Deterministic.** No model, no API, no randomness. The same bundle always
  produces the same questions in the same order with the same verdicts.
* **Evidence-derived.** A question is only generated when its *subject* was
  observed - a product the crawl actually saw, a category it actually
  classified, a policy page it actually fetched. There are no template
  questions about products that do not exist, which is the difference between
  simulating a buyer and inventing one.
* **Answered only from what was fetched.** A verdict of ``answerable``
  requires a citable URL and the snippet that supports it. Absence of evidence
  is reported as ``not_answerable``, never as a claim about the site.

The vocabulary is intentionally small and structural. Questions are built from
observed nouns (product names, category names, attribute labels) and observed
facts (prices, availability, policy terms), so the same code produces cocoa
questions for a chocolatier and voltage questions for an electronics shop
without knowing anything about either trade.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from . import evidence as ev
from . import analysis, lexicon, semantics, util
from .analysis import (commerce_evidence, identity_context, is_usable_entity_name,
                       item_identity, offer_availability, offer_currency, offer_price,
                       offers_of, products_on, readable_pages, reads_as_a_promotion,
                       structured_attribute_presence, visible_attribute_presence)
from .extract import (PRICE_RE, find_nodes, price_confidence, price_match_parts,
                      prop, text_of)

__all__ = ["build_matrix", "STATUSES", "QUESTION_KINDS"]

#: The three verdicts. ``partial`` is the one that matters most: it separates
#: "a reader could work this out from the page" from "a machine can read this
#: value", which is exactly the gap this marketplace exists to measure.
STATUSES = ("answerable", "partial", "not_answerable")

QUESTION_KINDS = (
    "product_price", "product_availability", "product_specifications",
    "category_cheapest", "product_comparison", "return_window",
    "shipping_destinations", "payment_options",
)

#: How many product-scoped questions to generate. The matrix is a diagnostic,
#: not a catalogue dump: a handful of products demonstrates the pattern, and
#: the findings aggregate over everything examined.
MAX_PRODUCT_SUBJECTS = 5


# ---------------------------------------------------------------------------
# subjects: the nouns this site actually gave us
# ---------------------------------------------------------------------------

def _snippet(text: str, needle: str = "", width: int = 160) -> str:
    """A short quotation from observed text, centred on ``needle`` if given.

    With no ``needle`` this returns the opening of the text, which is only
    honest when the claim being supported is about the text as a whole. It is
    never the right way to evidence a claim about a *particular* fact - see
    :func:`quote_concept`, which refuses rather than quoting the top of a page.
    """
    text = util.collapse_ws(text or "")
    if not text:
        return ""
    if needle:
        index = text.lower().find(needle.lower())
        if index >= 0:
            start = max(0, index - width // 3)
            return util.truncate(text[start:start + width], width)
    return util.truncate(text[:width], width)


def quote_concept(page: dict, concept: str, width: int = 200) -> Optional[dict]:
    """A quotation that actually contains the concept, or nothing at all.

    The bug this exists to make impossible: a question was answered "partial -
    stated in prose" and the quotation offered was the first 160 characters of
    the page, which on any modern site is the skip-link and the primary
    navigation. The reader was shown "Skip to main content Stories Jobs
    Newsroom..." as the site's statement of its return window.

    Two rules follow from that, and both are hard:

    * The quotation must contain the matched phrase. If the concept cannot be
      located in the text, there is no quotation and the caller must not claim
      the fact is stated.
    * The content region is searched before the whole document, so a match in
      the page's own prose is preferred over a match in a navigation label -
      and when only the navigation matched, the quotation says so, because
      "Returns" in a menu is a link to the answer, not the answer.

    Returns ``{"quote", "phrase", "region"}`` or ``None``.
    """
    for region, raw in (("main content", page.get("main_text") or ""),
                        ("page text", page.get("text") or "")):
        collapsed = util.collapse_ws(raw)
        located = lexicon.find(concept, collapsed)
        if not located:
            continue
        start, end, phrase = located
        # Open at the sentence the phrase sits in, so the quotation reads as a
        # statement rather than as a slice. Anchoring a fixed distance before
        # the match spent the window on whatever preceded it - on one fixture
        # the quote for "what payment methods are accepted" opened mid-way
        # through the previous answer and was truncated before reaching the
        # payment sentence, which contains the phrase and answers nothing.
        head = collapsed[max(0, start - 160):start]
        boundary = max(head.rfind(". "), head.rfind("? "), head.rfind("! "))
        window_start = (max(0, start - 160) + boundary + 2) if boundary >= 0 \
            else max(0, start - 40)
        quote = util.collapse_ws(collapsed[window_start:window_start + width])
        if phrase.lower() not in quote.lower():          # defensive: never quote without it
            quote = util.truncate(collapsed[start:start + width], width)
        found = {"quote": util.truncate(quote, width), "phrase": phrase,
                 "region": region}
        # The context rule is applied here, once, so every caller gets it.
        # Applied per caller it was applied in some of them: the policy
        # questions checked it and the product availability question did not,
        # which is how a sentence of inventory-management advice became a
        # product's stock state.
        if not _context_satisfied(concept, found):
            continue
        return found
    return None


#: Kept under its old private name for callers and tests that import it from
#: here; the implementation - and the identity rule it belongs to - lives in
#: :mod:`aiva.analysis` beside every other consumer of a product's name.
_is_usable_entity_name = is_usable_entity_name


def _product_subjects(bundle: dict) -> List[dict]:
    """Products the crawl observed, with whatever facts came with them."""
    return _product_subjects_and_skipped(bundle)[0]


def _product_subjects_and_skipped(bundle: dict) -> Tuple[List[dict], List[dict]]:
    """Question subjects, and the product pages that could not be one.

    Two gates before a page becomes a question subject: the shared
    classification must call it a product, and :func:`aiva.analysis.item_identity`
    must establish what it is called from item-scoped evidence - the declared
    product entity, or a heading the page corroborates in its title or URL.
    A page classified `product` whose only heading is a call to action, a
    section label or a string the template repeats has no identity, and no
    product-scoped question is generated for it. Those pages are returned
    second so the matrix can say so.
    """
    subjects: List[dict] = []
    skipped: List[dict] = []
    context = identity_context(bundle)
    for page in ev.product_pages(bundle):
        if page.get("fetch_failed") or page.get("non_html"):
            continue
        url = page.get("final_url") or page.get("url") or ""
        identity = item_identity(page, bundle, context)
        if not identity:
            skipped.append({"url": url, "headings": list(page.get("h1_texts") or [])[:2]})
            continue
        offer_facts: Dict[str, Any] = {}
        for node in products_on(page):
            for offer in offers_of(node):
                offer_facts.setdefault("price", offer_price(offer))
                offer_facts.setdefault("currency", offer_currency(offer))
                offer_facts.setdefault("availability", offer_availability(offer))
        subjects.append({
            "name": util.truncate(identity["name"], 80),
            "identity": identity,
            "url": url,
            "page": page,
            "offer": {k: v for k, v in offer_facts.items() if v},
        })
        if len(subjects) >= MAX_PRODUCT_SUBJECTS:
            break
    return subjects, skipped


def _category_subjects(bundle: dict) -> List[dict]:
    out: List[dict] = []
    context = identity_context(bundle)
    for page in ev.category_pages(bundle):
        if page.get("fetch_failed") or page.get("non_html"):
            continue
        headings = page.get("headings", []) or []
        names = [h.get("text") for h in headings if h.get("level") == 1]
        name = util.collapse_ws(names[0]) if names and names[0] else ""
        # The same identity gate the product subjects go through: a category
        # question quotes its subject too, and "What is the cheapest item in
        # {{collection.title}}?" is not a question - nor is one about a heading
        # the template repeats on every listing.
        if not _is_usable_entity_name(name) or reads_as_a_promotion(name):
            continue
        if lexicon.fold(name).strip().lower() in context["template"]:
            continue
        out.append({"name": util.truncate(name, 60),
                    "url": page.get("final_url") or page.get("url") or "",
                    "page": page})
        if len(out) >= 2:
            break
    return out


#: URL and title words that say a page is *about* a concept rather than merely
#: linking to it. A page at /customer-service/return-policy/ is a better source
#: for the return window than a privacy statement that happens to contain the
#: word, and ordering by page_type alone could not tell them apart - both are
#: policy pages, so the winner was decided by URL sort order.
_CONCEPT_URL_WORDS = {
    "returns": ("return", "returns", "refund", "devolucion", "retour", "ruckgabe",
                "retoure", "reso", "zwrot", "iade"),
    "shipping": ("shipping", "delivery", "deliver", "envio", "livraison", "versand",
                 "spedizion", "wysylka", "frakt", "kargo"),
    "payment": ("payment", "pay", "pago", "paiement", "zahlung", "pagamento",
                "betaal", "platnosc", "betalning", "odeme"),
}


#: Documents whose subject is not the commercial terms of a purchase. A privacy
#: statement explaining that a *payment method* is collected when booking a
#: museum tour is a true sentence about data handling and no kind of answer to
#: "what payment methods are accepted?". Terms-of-sale pages are deliberately
#: absent from this list - those often do carry the commercial terms.
_OFF_TOPIC_IDENTITY = (
    "privacy", "cookie", "gdpr", "data-protection", "datenschutz",
    "confidentialite", "privacidad", "privacidade",
    "career", "careers", "job", "jobs", "recruit", "vacancies",
    "press", "newsroom", "media-centre", "media-center",
    "museum", "investor", "sustainability", "whistleblow",
    "modern-slavery", "accessibility-statement", "code-of-conduct",
)

#: What a quotation must and must not contain before it counts as an answer.
#:
#: ``requires_all`` - every one of these vocabularies must match inside the
#: quotation. ``forbids`` - any match disqualifies it.
#:
#: For payment, an instrument alone was not enough and could never have been.
#: "I purchased an article at the store and paid through a Credit/Debit card.
#: It was returned for a refund" names an instrument in a *refund anecdote*;
#: "we collect ... a payment method in order to process the booking" names one
#: in a privacy notice. Requiring an acceptance construction as well - "we
#: accept", "you can pay with", "payment options" - is what distinguishes a
#: statement of what the site takes from a sentence that merely mentions money,
#: and the off-context vocabulary vetoes the rest.
_CONCEPT_CONTEXT = {
    "payment": {
        "requires_all": ("payment_acceptance", "payment_instrument"),
        "forbids": ("payment_off_context",),
    },
    # A site whose *subject matter* is commerce writes about returns, delivery
    # and stock on every page without stating any terms of its own. The
    # vocabulary matches because the site is about the topic, which is the one
    # case a keyword test cannot survive: "a good POS tells you when something
    # is about to run out of stock" was cited as a product's availability, and
    # "It includes a money-back guarantee. UPS Next Day Air Saver..." as the
    # site's return window. Neither sentence is a statement by this seller.
    "returns": {"forbids": ("hypothetical",)},
    "shipping": {"forbids": ("hypothetical",)},
    "in_stock": {"forbids": ("hypothetical",)},
    "out_of_stock": {"forbids": ("hypothetical",)},
    "preorder": {"forbids": ("hypothetical",)},
}


def _identity_is_off_topic(page: dict) -> bool:
    """Is this document about something other than buying from the site?"""
    haystack = lexicon.fold(f"{page.get('url', '')} {page.get('title', '')}")
    return any(token in haystack for token in _OFF_TOPIC_IDENTITY)


def _context_satisfied(concept: str, quote: dict) -> bool:
    """Is this quotation an *answer*, or a sentence that mentions the topic?

    Two live failures this closes, both of which passed a keyword test:

    * "we collect ... a payment method in order to process the booking" - a
      privacy notice about a museum tour, cited as the site's accepted payment
      methods.
    * "I purchased an article at the store and paid through a Credit/Debit
      card. It was returned for a refund" - a refund anecdote in an FAQ, cited
      the same way once an instrument was required.

    The rule is therefore compositional rather than a growing list of
    exclusions: the quotation must carry *every* vocabulary the answer is made
    of, and none of the vocabularies that mark a different subject.
    """
    rules = _CONCEPT_CONTEXT.get(concept)
    if not rules:
        return True
    text = quote["quote"]
    if any(lexicon.find(forbidden, text) for forbidden in rules.get("forbids", ())):
        return False
    return all(lexicon.find(required, text)
               for required in rules.get("requires_all", ()))


def _concept_in_identity(page: dict, concept: str) -> bool:
    """Does the page's URL or title say it is about this concept?"""
    words = _CONCEPT_URL_WORDS.get(concept, ())
    if not words:
        return False
    haystack = lexicon.fold(f"{page.get('url', '')} {page.get('title', '')} "
                            + " ".join(page.get("h1_texts", []) or []))
    return any(word in haystack for word in words)


def _policy_pages(bundle: dict, concept: str) -> List[dict]:
    """Pages that can actually be quoted for this concept, best source first.

    Only pages where the concept is locatable in the text are returned - a
    page that cannot be quoted cannot be cited - and they are ordered by how
    strongly the page presents itself as being *about* the concept: its URL or
    title naming it, then a match in the content region, then a match anywhere.
    """
    scored = []
    for page in readable_pages(bundle):
        # Two independent refusals, both before ranking. A document about
        # something else cannot be the source however well it matches, and a
        # quotation that names none of the things the answer consists of is a
        # topic hit rather than evidence.
        if _identity_is_off_topic(page):
            continue
        quote = quote_concept(page, concept)
        if not quote:
            continue
        if not _context_satisfied(concept, quote):
            continue
        rank = (
            0 if _concept_in_identity(page, concept) else 1,
            0 if quote["region"] == "main content" else 1,
            0 if page.get("page_type") in ("policy", "faq") else 1,
        )
        scored.append((rank, page.get("url", ""), page, quote))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [{"page": page, "quote": quote} for _, _, page, quote in scored]


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------

def _entry(kind: str, question: str, status: str, *, url: str = "",
           evidence: str = "", missing: str = "", action: str = "",
           source: str = "") -> dict:
    return {
        "kind": kind,
        "question": question,
        "status": status,
        "citing_url": url,
        "evidence": evidence,
        "evidence_source": source,
        "missing": missing,
        "suggested_action": action,
    }


def _rendered_addendum(page: dict, probe) -> str:
    """One clause naming a fact seen in the rendered DOM and not the response.

    The answerability question is about the document the site returns, and that
    is unchanged: a fact that arrives after hydration is still absent from the
    response, so the status stays what it was. What changes is the sentence a
    reader gets. "No price found" is false about a page whose price mounts on
    load; "no price in the response, though the browser-rendered state has one"
    is what was measured, and it points at a different fix.
    """
    from .analysis import fact_visibility
    if fact_visibility(page, probe)["state"] != "rendered_only":
        return ""
    return (" The value was observed in the browser-rendered state of this page, so it is "
            "absent from the server response rather than from the page.")


def _ask_price(subject: dict) -> dict:
    """Structured price is answerable; a price only in prose is partial."""
    name, url = subject["name"], subject["url"]
    question = f"What is the price of {name}?"
    offer = subject["offer"]
    if offer.get("price"):
        currency = offer.get("currency") or ""
        return _entry("product_price", question, "answerable", url=url,
                      source="Offer.price in JSON-LD",
                      evidence=f"Offer.price = {offer['price']}"
                               + (f" {currency}" if currency else ""),
                      action="")
    text = subject["page"].get("text", "") or ""
    match = PRICE_RE.search(text)
    if match:
        currency, amount = price_match_parts(match)
        # A symbol is unambiguous; an alphabetic code is a token that could also
        # be a model designator, so the quotation is offered as a reading rather
        # than asserted as the value. Stating an exact number recovered from an
        # ambiguous token is the failure mode this guards: a page whose only
        # match was a trial offer once reported that offer as the item's price.
        certain = price_confidence(match) == "high"
        quoted = match.group(0).strip()
        return _entry("product_price", question, "partial", url=url,
                      source="visible page text",
                      evidence=(f'price appears in visible text as "{quoted}"' if certain else
                                f'a price-shaped string appears in visible text as "{quoted}", '
                                f'read from the currency code "{currency}" rather than a '
                                f'currency symbol, so the reading is not certain'),
                      missing="no Offer.price in structured data, so the value has to be "
                              "recovered by parsing prose",
                      action="Publish the same price as Offer.price with priceCurrency "
                             "in the product's JSON-LD.")
    from .analysis import _states_price
    addendum = _rendered_addendum(subject["page"], _states_price)
    return _entry("product_price", question, "not_answerable", url=url,
                  source="product page",
                  evidence="no currency-formatted price found in the fetched HTML and no "
                           "Offer.price in structured data" + addendum,
                  missing="a price for this product in any readable form",
                  action=("Move the price into the server-rendered HTML and mirror it in "
                          "Offer.price / priceCurrency." if addendum else
                          "State the price in the server-rendered HTML and mirror it in "
                          "Offer.price / priceCurrency."))


def _ask_availability(subject: dict) -> dict:
    name, url = subject["name"], subject["url"]
    question = f"Is {name} in stock?"
    if subject["offer"].get("availability"):
        return _entry("product_availability", question, "answerable", url=url,
                      source="Offer.availability in JSON-LD",
                      evidence=f"Offer.availability = {subject['offer']['availability']}")
    for concept in ("in_stock", "out_of_stock", "preorder"):
        quote = quote_concept(subject["page"], concept)
        if quote:
            return _entry("product_availability", question, "partial", url=url,
                          source=f"visible {quote['region']}",
                          evidence=f'stock state stated in prose ({concept.replace("_", " ")}), '
                                   f'on the phrase "{quote["phrase"]}": "{quote["quote"]}"',
                          missing="no Offer.availability value, so stock state is not a "
                                  "typed fact",
                          action="Add Offer.availability (schema.org InStock / OutOfStock) "
                                 "to the product's Offer.")
    if subject["page"].get("language_supported") is False:
        return _entry("product_availability", question, "partial", url=url,
                      source="product page",
                      evidence="the page declares a language this auditor's vocabulary does "
                               "not cover, so a prose stock statement cannot be confirmed "
                               "either way",
                      missing="Offer.availability, which would state stock language-neutrally",
                      action="Add Offer.availability so stock state is readable without "
                             "depending on the reader's language.")
    from .analysis import _states_availability
    addendum = _rendered_addendum(subject["page"], _states_availability)
    return _entry("product_availability", question, "not_answerable", url=url,
                  source="product page",
                  evidence="no Offer.availability in markup and no stock statement detected "
                           "in the fetched text" + addendum,
                  missing="any statement of whether this product can be bought",
                  action=("Move the stock statement into the server response and add "
                          "Offer.availability." if addendum else
                          "State stock status on the page and in Offer.availability."))


def _ask_specifications(subject: dict) -> dict:
    name, url = subject["name"], subject["url"]
    question = f"What are the specifications of {name}?"
    structured = structured_attribute_presence(subject["page"])
    visible = visible_attribute_presence(subject["page"])
    if structured["count"] >= 2:
        return _entry("product_specifications", question, "answerable", url=url,
                      source="typed schema.org attributes",
                      evidence=f"{structured['count']} typed attribute(s): "
                               + ", ".join(structured["names"][:5]))
    if visible["count"] >= 2:
        return _entry("product_specifications", question, "partial", url=url,
                      source="; ".join(visible["sources"]) or "visible page content",
                      evidence=f"{visible['count']} attribute(s) stated in visible content: "
                               + ", ".join(visible["names"][:5]),
                      missing="the same attributes as typed Product properties or "
                              "additionalProperty entries",
                      action="Mirror the attributes already published into "
                             "additionalProperty so they can be compared across products.")
    from .analysis import page_has_spec_block
    addendum = _rendered_addendum(subject["page"], page_has_spec_block)
    return _entry("product_specifications", question, "not_answerable", url=url,
                  source="product page",
                  evidence="no specification table, definition list, label/value lines or "
                           "typed attributes found in the server response" + addendum,
                  missing="any attribute of this product beyond its name",
                  action=("Move the specification block into the server response and mirror "
                          "it in additionalProperty." if addendum else
                          "Publish the product's attributes as a specification block and "
                          "mirror them in additionalProperty."))


def _category_members(category: dict, subjects: List[dict]) -> List[dict]:
    """The sampled products this listing is observed to contain.

    Membership is read from the listing's own body links and from a product's
    declared ``category``. Without it, "the cheapest item in Boots" was
    answered from every product the crawl happened to read - which on a mixed
    site named a monthly plan as the cheapest boot.
    """
    page = category.get("page") or {}
    linked = set()
    for link in ((page.get("links") or {}).get("internal") or []):
        if link.get("in_nav") or link.get("in_footer"):
            continue
        url = str(link.get("url") or "")
        if url:
            linked.add(url.split("#")[0])
    name = util.collapse_ws(str(category.get("name") or "")).lower()
    members = []
    for subject in subjects:
        subject_page = subject.get("page") or {}
        urls = {str(subject.get("url") or ""), str(subject_page.get("url") or ""),
                str(subject_page.get("final_url") or "")} - {""}
        if urls & linked:
            members.append(subject)
            continue
        declared = ""
        for node in products_on(subject_page):
            declared = text_of(prop(node, "category")) or declared
        if name and declared and name in declared.lower():
            members.append(subject)
    return members


def _ask_cheapest(category: dict, subjects: List[dict]) -> Optional[dict]:
    """Only askable when the crawl saw a category *and* more than one product."""
    if len(subjects) < 2:
        return None
    question = f"What is the cheapest item in {category['name']}?"
    priced = [s for s in subjects if s["offer"].get("price")]
    if len(priced) >= 2:
        def _value(subject):
            try:
                return float(str(subject["offer"]["price"]).replace(",", ""))
            except (TypeError, ValueError):
                return float("inf")
        cheapest = min(priced, key=_value)
        return _entry("category_cheapest", question, "answerable", url=category["url"],
                      source="Offer.price across sampled products",
                      evidence=f"{len(priced)} sampled product(s) expose a typed price; the "
                               f"lowest observed is {cheapest['offer']['price']} on "
                               f"{cheapest['url']}")
    if len(priced) == 1:
        return _entry("category_cheapest", question, "partial", url=category["url"],
                      source="Offer.price across sampled products",
                      evidence=f"only 1 of {len(subjects)} sampled product(s) exposes a typed "
                               f"price, so the set cannot be ranked",
                      missing="a typed price on every product in the category",
                      action="Emit Offer.price on every product so the range can be ranked.")
    return _entry("category_cheapest", question, "not_answerable", url=category["url"],
                  source="category and product pages",
                  evidence=f"none of the {len(subjects)} sampled product(s) expose a typed "
                           f"price",
                  missing="typed prices to compare",
                  action="Emit Offer.price with priceCurrency on every product page.")


def _ask_comparison(subjects: List[dict]) -> Optional[dict]:
    if len(subjects) < 2:
        return None
    first, second = subjects[0], subjects[1]
    question = f"What is the difference between {first['name']} and {second['name']}?"
    a = structured_attribute_presence(first["page"])
    b = structured_attribute_presence(second["page"])
    shared = sorted(set(a["names"]) & set(b["names"]))
    if len(shared) >= 2:
        return _entry("product_comparison", question, "answerable", url=first["url"],
                      source="typed attributes shared by both products",
                      evidence=f"both products declare {len(shared)} attribute(s) in common: "
                               + ", ".join(shared[:5]))
    va = visible_attribute_presence(first["page"])
    vb = visible_attribute_presence(second["page"])
    shared_visible = sorted(set(va["names"]) & set(vb["names"]))
    if len(shared_visible) >= 2:
        return _entry("product_comparison", question, "partial", url=first["url"],
                      source="visible attributes on both products",
                      evidence=f"both products state {len(shared_visible)} attribute(s) in "
                               f"common in visible content: " + ", ".join(shared_visible[:5]),
                      missing="the shared attributes in a typed form, so values line up "
                              "across the range without parsing each page",
                      action="Use the same attribute names, as additionalProperty entries, "
                             "on every product in the category.")
    return _entry("product_comparison", question, "not_answerable", url=first["url"],
                  source="product pages",
                  evidence="the two sampled products share no attribute name in typed markup "
                           "or in visible content, so there is no common axis to compare on",
                  missing="a consistent attribute set across products in the same category",
                  action="Publish the same attribute set, with the same names, on every "
                         "product in a category.")


#: Questions whose answer is a quantity - a number of days, a cost, a
#: threshold. A sentence that mentions the concept without one ("Prices,
#: delivery and returns differ by country") is a pointer to the answer, not the
#: answer, and reporting it as "stated in prose" overstates what the page does.
_NUMERIC_POLICY_KINDS = ("return_window", "shipping_destinations")

#: A quantity: digits, or a number written out, in any of the languages the
#: lexicon covers. Bare digits are not enough on their own - see below.
_QUANTITY_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fourteen|"
    r"fifteen|twenty|thirty|sixty|ninety|dos|tres|cinco|diez|quince|treinta|"
    r"deux|trois|cinq|dix|quinze|trente|zwei|drei|funf|zehn|dreissig|"
    r"due|tre|cinque|dieci|trenta|twee|drie|vijf|tien|dertig)\b", re.I)


def _states_a_term(quote: dict) -> bool:
    """Does this sentence state a term, or only mention the topic?

    A returns or delivery term is a quantity in a unit: thirty days, 2-5
    business days, free over 2,000. The test this replaces asked whether the
    quoted window contained a digit *anywhere*, which the "2" in a courier's
    product name satisfied - "It includes a money-back guarantee. UPS Next Day
    Air Saver... UPS 2nd Day Air" was published as a site's return window.

    So a number is required *and* a unit the policy could be measured in, or
    an explicit no-charge term, which is a stated term with no number in it.
    """
    text = quote["quote"]
    unit = lexicon.find("policy_unit", text)
    if not unit:
        return False
    free_words = ("free", "no charge", "no cost", "gratis", "gratuit",
                  "kostenlos", "gratuito", "gratuita", "kosteloos",
                  "darmowa", "ucretsiz", "bezplatnie", "kostnadsfri")
    if any(word in unit[2].lower() for word in free_words):
        return True
    return bool(_QUANTITY_RE.search(text))


def _quote_answers(kind: str, page: dict, quote: dict, concept: str) -> bool:
    """Is this quote an answer, or only evidence that the topic exists?

    For a question whose answer is a quantity, the quoted sentence has to
    carry that quantity. The page being *about* the concept used to waive this
    - a URL or title naming returns admitted any sentence on the page - and
    that waiver is what published a returns page's navigation list as its
    return window, and a shipping page's feature blurb as its destinations. A
    page about returns is a reason to look there, not a reason to accept
    whatever is found.
    """
    if kind not in _NUMERIC_POLICY_KINDS:
        return True
    return _states_a_term(quote)


def _ask_policy(bundle: dict, kind: str, concept: str, question: str,
                schema_types: tuple, missing: str, action: str) -> Optional[dict]:
    """Return-window / shipping / payment questions, resolved the same way."""
    pages = _policy_pages(bundle, concept)
    typed = []
    for page in readable_pages(bundle):
        if schema_types and find_nodes(page.get("jsonld_nodes", []) or [], *schema_types):
            typed.append(page)
    if typed:
        page = typed[0]
        return _entry(kind, question, "answerable",
                      url=page.get("final_url") or page.get("url", ""),
                      source=f"{'/'.join(schema_types)} structured data",
                      evidence=f"{schema_types[0]} node present in the page's JSON-LD")
    mentioned = pages
    pages = [row for row in pages
             if _quote_answers(kind, row["page"], row["quote"], concept)]
    if pages:
        page, quote = pages[0]["page"], pages[0]["quote"]
        return _entry(kind, question, "partial",
                      url=page.get("final_url") or page.get("url", ""),
                      source=f"visible {quote['region']}",
                      evidence=f'stated in prose, on the phrase "{quote["phrase"]}": '
                               f'"{quote["quote"]}"',
                      missing=missing, action=action)
    if mentioned:
        # The topic is discussed and no terms are stated. Reporting that as
        # "no statement was detected" would be wrong in the other direction,
        # and it is the more useful finding of the two: the site has the page,
        # the page does not carry the number.
        page = mentioned[0]["page"]
        return _entry(kind, question, "not_answerable",
                      url=page.get("final_url") or page.get("url", ""),
                      source=f"visible {mentioned[0]['quote']['region']}",
                      evidence=f'the topic is discussed on {len(mentioned)} crawled page(s) '
                               f'but no page states the term itself - the closest text, on '
                               f'the phrase "{mentioned[0]["quote"]["phrase"]}", carries no '
                               f'number of days, no cost and no destination',
                      missing=missing, action=action)
    return _entry(kind, question, "not_answerable",
                  url=(ev.site_host(bundle) and bundle.get("site", {}).get("home_url", "")) or "",
                  source="all crawled pages",
                  evidence="no statement of this policy was detected in any page the crawl "
                           "fetched, in markup or in text",
                  missing=missing, action=action)


# ---------------------------------------------------------------------------
# the matrix
# ---------------------------------------------------------------------------

def build_matrix(bundle: dict) -> dict:
    """Generate and resolve the questions this site's own content supports.

    Returns a dict carrying the question rows plus the counts the report and
    the specialist both read. When the crawl obtained nothing to ask about,
    the matrix is empty and says why - it never falls back to a stock question
    list, because a question about a product that was never observed cannot be
    answered *or* fairly reported as unanswerable.

    Which questions are *askable* follows the kind of site and the kind of
    item (:mod:`aiva.semantics`). A documentation site, a publisher and a
    government department are asked no buying question and their
    answerability is reported as unmeasured; a software catalogue is asked
    about price and specifications but never about stock, delivery or
    returns; only a page selling physical goods is asked whether the item is
    in stock. A question that does not apply is not a gap, and is not scored.
    """
    pages = readable_pages(bundle)
    commerce = commerce_evidence(bundle)
    context = semantics.site_context(bundle)
    classes = semantics.answerability_question_classes(context)
    rows: List[dict] = []
    notes: List[str] = []
    not_asked: Dict[str, int] = {}

    def skip(kind: str, why: str) -> None:
        key = f"{kind}: {why}"
        not_asked[key] = not_asked.get(key, 0) + 1

    if not pages:
        notes.append("no readable page was fetched, so no question could be generated")
        return _summarise(rows, notes, commerce, context, not_asked)

    subjects, skipped = _product_subjects_and_skipped(bundle)
    categories = _category_subjects(bundle)

    for subject in subjects:
        page = subject["page"]
        identity = (f"{subject['identity']['source']}: "
                    f"{subject['identity']['corroboration']}")
        kind = semantics.product_record(page, context)
        subject["product_kind"] = kind.get("subtype")
        asked: List[dict] = []
        price = semantics.is_price_applicable(page, context)
        if price and "product_price" in classes:
            asked.append(_ask_price(subject))
        else:
            skip("product_price", price["reason"] if not price else
                 "not a question class for this kind of site")
        stock = semantics.is_stock_applicable(page, context)
        if stock and "product_availability" in classes:
            asked.append(_ask_availability(subject))
        else:
            skip("product_availability", stock["reason"] if not stock else
                 "stock is not a concept for this kind of site")
        specs = semantics.is_physical_specs_applicable(page, context)
        software = kind.get("subtype") == "software" or kind.get("described_as") == "software"
        if (specs or software) and "product_specifications" in classes:
            asked.append(_ask_specifications(subject))
        else:
            skip("product_specifications", specs["reason"])
        for row in asked:
            # How the subject's name was established. A reader who sees
            # "What is the price of X?" can check that X is a product and not
            # a heading the page happened to carry.
            row["subject_identity"] = identity
            row["subject_kind"] = kind.get("subtype")
            rows.append(row)
    if skipped:
        shown = "; ".join(
            f"{item['url']}" + (f" (heading: \"{item['headings'][0]}\")"
                                if item["headings"] else " (no heading)")
            for item in skipped[:3])
        notes.append(f"{len(skipped)} page(s) classified as products were not asked "
                     f"product questions because no item-scoped evidence establishes "
                     f"what they are called - no declared product name, and no heading "
                     f"the page's title or URL corroborates: {shown}")

    priced_subjects = [s for s in subjects if semantics.is_price_applicable(s["page"], context)]
    if categories and "category_cheapest" in classes:
        # The question names a category, so the answer must come from that
        # category's own members - the products it links to, or products that
        # declare it. A set the crawl cannot delimit is not asked about.
        for category in categories:
            # "The cheapest item in X" is a question about a catalogue. A
            # documentation section or an article index is a set too, and
            # nothing in it has a price to rank.
            listing = semantics.listing_record(category.get("page") or {}, bundle, context)
            if listing.get("subtype") not in ("ecommerce_listing", "software_catalog",
                                              "service_listing", "marketplace_listing",
                                              "unknown"):
                continue
            members = _category_members(category, priced_subjects)
            if len(members) >= 2:
                cheapest = _ask_cheapest(category, members)
                if cheapest:
                    rows.append(cheapest)
                break
            skip("category_cheapest",
                 f"fewer than two sampled products are observed to be in "
                 f"\"{category['name']}\", so the set to rank is not established")
    # A comparison is asked within one kind, and, where the site says so,
    # within one listing. Kind alone put a boot and a cable accessory in the
    # same question - both are physical goods, and nothing else connected
    # them - and then recorded "they share no attribute" as a gap, for a
    # comparison the site never invites. Membership of one listing is the
    # site's own statement that two items belong together, so it is preferred;
    # kind remains the fallback where no listing delimits a set.
    by_kind: Dict[str, List[dict]] = {}
    for subject in subjects:
        kind_key = subject.get("product_kind") or "ambiguous"
        if kind_key in ("informational", "ambiguous") and \
                semantics.is_physical_specs_applicable(subject["page"], context):
            kind_key = "physical"
        if kind_key in ("physical", "software", "subscription", "digital"):
            by_kind.setdefault(kind_key, []).append(subject)
    comparable: List[dict] = []
    shared_listing = ""
    for group in by_kind.values():
        if len(group) < 2:
            continue
        for category in categories:
            members = _category_members(category, group)
            if len(members) >= 2:
                comparable, shared_listing = members, category["name"]
                break
        if comparable:
            break
    if not comparable:
        comparable = next((group for group in by_kind.values() if len(group) >= 2), [])
    comparison = _ask_comparison(comparable) if "product_comparison" in classes else None
    if comparison:
        together = (f"; both are listed in \"{shared_listing}\"" if shared_listing else
                    "; no listing was observed containing both, so they are paired by kind")
        comparison["subject_identity"] = "; ".join(
            f"{s['name']}: {s['identity']['source']} ({s['identity']['corroboration']})"
            for s in comparable[:2]) + together
        rows.append(comparison)

    # Policy questions are asked of the whole site, and only where the site's
    # shape makes them questions about it: a return window and a delivery
    # destination are questions about a seller of physical goods; a payment
    # method is a question about anything that transacts.
    policy_kinds = {"return_window", "shipping_destinations", "payment_options"}
    if classes & policy_kinds:
        if "return_window" in classes:
            rows.append(_ask_policy(
                bundle, "return_window", "returns",
                "What is the return window?", ("MerchantReturnPolicy",),
                "a MerchantReturnPolicy node stating merchantReturnDays",
                "Add MerchantReturnPolicy with merchantReturnDays to the Offer, matching "
                "the number stated on the policy page."))
        if "shipping_destinations" in classes:
            rows.append(_ask_policy(
                bundle, "shipping_destinations", "shipping",
                "Where does this site ship to, and what does delivery cost?",
                ("OfferShippingDetails",),
                "an OfferShippingDetails node stating shippingDestination and shippingRate",
                "Add OfferShippingDetails to the Offer, naming the destinations served and "
                "the rate, so delivery can be answered without reading the policy page."))
        if "payment_options" in classes:
            rows.append(_ask_policy(
                bundle, "payment_options", "payment",
                "What payment methods are accepted?", ("PaymentMethod",),
                "an acceptedPaymentMethod value on the Offer or Organization",
                "State accepted payment methods in the page text and as "
                "acceptedPaymentMethod on the Offer."))
        left_out = sorted(policy_kinds - classes)
        if left_out:
            notes.append("not generated for a site of this shape ("
                         f"{context.get('site_kind')}): {', '.join(left_out)} - "
                         "delivery and returns are questions about a seller of physical "
                         "goods, and none was observed")
    elif commerce["is_commerce"]:
        notes.append("commerce policy questions (returns, shipping, payment) were not "
                     f"generated: the site's shape is {context.get('site_kind')} "
                     "and no page was observed selling physical goods or transacting")
    else:
        notes.append("commerce-specific questions (returns, shipping, payment) were not "
                     "generated: no product, category, commerce markup or cart affordance "
                     "was observed")

    if not subjects:
        notes.append("no product-scoped question was generated: the crawl observed no page "
                     "whose product identity is established by item-scoped evidence")
    if not categories:
        notes.append("no category-scoped question was generated: the crawl observed no "
                     "category page with a heading of its own")
    if not_asked:
        notes.append("questions not asked because the expectation does not apply to the "
                     "page's kind of item (not counted as gaps): "
                     + "; ".join(f"{k} ({n})" for k, n in sorted(not_asked.items())))
    # Every verdict above is about the document the site returns, which is the
    # evidence this matrix is built from and stays built from. Where the
    # optional browser pass saw selling facts that the response does not carry,
    # the matrix says so - otherwise a reader is told a site sells nothing when
    # the price is on the page, just not in the response.
    rendered_gaps: Dict[str, int] = {}
    for page in pages:
        for gap in analysis.rendered_fact_gaps(page):
            rendered_gaps[gap["label"]] = rendered_gaps.get(gap["label"], 0) + 1
    if rendered_gaps:
        notes.append(
            "every verdict above is about the server response; the browser-rendered state of "
            "the sampled pages additionally carried "
            + ", ".join(f"{label} ({count} page(s))"
                        for label, count in sorted(rendered_gaps.items()))
            + " - facts absent from the response rather than from the page")
    return _summarise(rows, notes, commerce, context, not_asked)


def _summarise(rows: List[dict], notes: List[str], commerce: dict,
               context: Optional[dict] = None, not_asked: Optional[Dict[str, int]] = None) -> dict:
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    total = len(rows)
    # A single number for the report header. `partial` counts as half: the
    # fact is on the page but not in a form that can be read without parsing
    # prose, which is genuinely better than absent and worse than typed.
    score = None
    if total:
        score = round(100.0 * (counts["answerable"] + 0.5 * counts["partial"]) / total, 1)
    by_kind: Dict[str, Dict[str, int]] = {}
    for row in rows:
        bucket = by_kind.setdefault(row["kind"], {s: 0 for s in STATUSES})
        bucket[row["status"]] += 1
    return {
        "questions": rows,
        "total_questions": total,
        "counts": counts,
        "by_kind": by_kind,
        "answerability_score": score,
        "commerce_evidence": commerce["signals"],
        "site_kind": (context or {}).get("site_kind"),
        "question_classes": sorted(semantics.answerability_question_classes(context or {})),
        "not_asked": dict(not_asked or {}),
        "notes": notes,
    }
