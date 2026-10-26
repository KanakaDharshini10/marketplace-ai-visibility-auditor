#!/usr/bin/env python3
"""engagement-audit - does the visitor an assistant sends land on the answer?

The on-site half of the Round-2 problem. Discoverability gets the brand into
the answer; this decides whether the click that follows is worth anything. The
recurring failure is a *continuity* failure: the assistant answered something
specific, and the landing page makes the visitor start the search again.

Everything here is checked against what a plain fetch can see, because that is
the evidence the page itself serves to a reader that does not run JavaScript -
if the fact is not in the HTML, the page does not state it to such a reader.

Every commerce expectation - stock, delivery, returns, a specification block,
reviews, a buy control - is asked of a page only when the shared semantic
layer (:mod:`aiva.semantics`) establishes that it applies to the kind of item
the page is about. A software download, a subscription plan, a service and a
manufacturer's information page are product pages too, and none of them owes
anyone a delivery estimate; each finding names the pages set aside and why.

Consumes the shared evidence bundle. Performs no network I/O.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


def _bootstrap() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "marketplace.json").is_file() and \
                (candidate / "lib" / "aiva" / "__init__.py").is_file():
            lib = str(candidate / "lib")
            if lib not in sys.path:
                sys.path.insert(0, lib)
            return candidate
    raise RuntimeError("cannot locate the marketplace root")


MARKETPLACE_ROOT = _bootstrap()

from aiva import evidence as ev                      # noqa: E402
from aiva import util                                # noqa: E402
from aiva.analysis import (cap_severity, coverage_caveat, step_down, commerce_guard, crawl_yielded_evidence, absent, action, attribute_phrase, confidence_for, listing_controls_expected,  # noqa: E402
                           example_attributes, finding, jsonld_nodes, label,
                           listing_controls, measured, name_list, named, observed,
                           shows_client_rendering_signals,
                           offer_availability, offers_of, page_has_spec_block,
                           page_items, products_on, sample_guard, scope_for,
                           severity_from_ratio, severity_from_sample, site_vocabulary, PLACEHOLDER,
                           structured_attribute_presence,
                           visible_attribute_presence, redirect_index,
                           catalogue_listing_pages, product_pages_where,
                           catalogue_vocabulary, collection_provenance, listing_members,
                           orderable_dimensions, rendered_facts, rendered_note, rendered_only,
                           applicability_verdict, conditional_advice,
                           semantic_context, set_aside_note)
from aiva import lexicon                              # noqa: E402
from aiva import semantics                            # noqa: E402
from aiva.extract import PRICE_RE, find_nodes         # noqa: E402
from aiva.findings import Finding                    # noqa: E402

SKILL = "engagement-audit"
PILLAR = "engagement"

def _states_availability(page: dict, text: str) -> bool:
    """Is stock state knowable here, in any language or as typed data?"""
    if any(lexicon.mentions(concept, text)
           for concept in ("in_stock", "out_of_stock", "preorder")):
        return True
    return any(offer_availability(offer) for node in products_on(page)
               for offer in offers_of(node))


def _states_purchase_action(page: dict) -> bool:
    """A buy affordance, read from words *or* from a cart form."""
    if (page.get("mentions", {}) or {}).get("add_to_cart"):
        return True
    return bool((page.get("forms", {}) or {}).get("has_cart_action"))


def _policy_stated(page: dict, concept: str, *schema_types: str) -> bool:
    """Structured markup first, prose second - markup is language-neutral."""
    if find_nodes(jsonld_nodes(page), *schema_types):
        return True
    return bool((page.get("mentions", {}) or {}).get(concept))


def _unreadable_pages(pages) -> list:
    """Pages whose prose is in a language the lexicon does not cover."""
    return [p for p in pages if p.get("language_supported") is False]


def _sort_aside(page: dict) -> str:
    """Name the sort controls a page does have, or say nothing at all.

    A trailing "sort controls present:" with an empty list is worse than no
    aside: it looks like the auditor lost the values. Icon-only sort links
    have no text to quote, so in that case only the count is stated.
    """
    controls = listing_controls(page)
    if not controls["has_sort_controls"]:
        return ""
    names = name_list(controls["sort_options"] or controls["sort_control_names"])
    if names:
        return f"; sort controls present: {names}"
    return f"; {controls['sort_controls']} sort control(s) present, none carrying a text label"


def _spec_table_example(vocab: dict) -> str:
    """A spec table built from attributes this site actually publishes.

    When the crawl saw no attributes at all the rows fall back to neutral
    placeholders. What never happens is a row naming an attribute from some
    other trade: an example that does not describe the audited catalogue tells
    the reader nothing and undermines every measured statement around it.
    """
    rows = example_attributes(vocab, 3)
    body = "\n".join(
        f"  <tr><th scope=\"row\">{name}</th><td>&lt;value&gt;</td></tr>" for name in rows)
    return f"<table>\n{body}\n</table>"


#: What a reader is told when the observation stands but its meaning does not.
#: `collection_note` above has already said *why* the set could not be delimited;
#: this states the consequence, which is the part that governs how the finding
#: should be read.
UNDELIMITED_NOTE = (
    " These controls therefore could not be assessed against a known comparable set: the "
    "affordance is genuinely absent from the response, and whether this page is a set that "
    "needs it is not established, so the severity and confidence are lowered and nothing "
    "below names an attribute or an ordering value.")


def _has_filter(facts: dict) -> bool:
    return listing_controls(facts)["has_filter_controls"]


def _has_sort(facts: dict) -> bool:
    return listing_controls(facts)["has_sort_controls"]


def _rendered_controls_finding(bundle: dict, filter_pages: List[dict],
                               sort_pages: List[dict], total: int) -> Finding:
    """A catalogue control that exists in the browser but not in the response.

    Reported instead of - never alongside - "this listing exposes no filter
    control", because that sentence is false about a page whose facets mount
    after hydration. What is true, and what this says, is that the control is
    not in the document the server returns.
    """
    affected = []
    for page in filter_pages + sort_pages:
        if page not in affected:
            affected.append(page)
    kinds = []
    if filter_pages:
        kinds.append(f"a filter control on {len(filter_pages)} listing(s)")
    if sort_pages:
        kinds.append(f"a sort control on {len(sort_pages)} listing(s)")
    names = name_list([n for page in filter_pages
                       for n in listing_controls(rendered_of(page))["filter_control_names"]]
                      + [o for page in sort_pages
                         for o in listing_controls(rendered_of(page))["sort_options"]])
    return finding(
        "EG-CONTROLS-RENDERED-ONLY",
        "Catalogue controls are present in the browser-rendered page but not in the server HTML",
        "medium", PILLAR,
        evidence=f"Of {total} catalogue listing page(s), the browser-rendered state carries "
                 f"{' and '.join(kinds)} that the server response does not"
                 + (f" ({names})." if names else ".")
                 + " Both states of the same URL were measured in this run.",
        interpretation="The affordance exists on the page. What the measurement shows is that "
                       "it is mounted after the response, so the document the server returns "
                       "carries neither the control nor the filtered or sorted URLs it would "
                       "produce. A filtered view that has no server-rendered URL cannot be "
                       "linked to; that is a property of the markup, and this audit does not "
                       "measure how any external system treats either state.",
        items=[observed(
            "{}: {} present in the rendered DOM, absent from the server HTML".format(
                label(page),
                "filter control" if page in filter_pages else "sort control"),
            url=label(page), locator="server response vs rendered DOM")
            for page in affected[:5]],
        action=action("Render the catalogue controls, and their result set, server-side.",
                      priority="medium", effort="medium", impact="medium",
                      mechanism="A control mounted after hydration is absent from the initial "
                                "document, and so is every URL it would generate. Rendering "
                                "the controls and the default result set server-side puts both "
                                "in the response, and the client can hydrate over them.",
                      steps=["Emit the filter and sort controls in the server-rendered HTML, "
                             "with the default result set already applied.",
                             "Give each filter and sort state a crawlable, linkable URL that "
                             "returns that state to a plain fetch.",
                             "Keep the hydrated behaviour as an enhancement of the rendered "
                             "markup rather than a replacement for it."],
                      verification="`curl -s <listing-url>` contains the control markup, and a "
                                   "filtered URL returns the filtered set to curl.",
                      verification_type="self_verifiable"),
        urls=[label(p) for p in affected],
        confidence=0.95,
        metrics={"scope": scope_for(len(affected), total),
                 "affected": len(affected), "sampled": total,
                 "sample_unit": "sampled catalogue listing page(s)",
                 "filter_rendered_only": len(filter_pages),
                 "sort_rendered_only": len(sort_pages),
                 "raw": "absent", "rendered": "present"},
        tags=["navigation", "rendering", "raw-vs-rendered"])


def rendered_of(page: dict) -> dict:
    """The page's rendered fact bag, or the page itself when it has none."""
    facts = rendered_facts(page)
    return facts if facts is not None else page


def _members_of(bundle: dict, listings: List[dict]) -> List[dict]:
    """Every product page these listings link to, deduplicated in order."""
    out: List[dict] = []
    seen = set()
    for page in listings:
        for member in listing_members(page, bundle):
            key = str(member.get("url") or id(member))
            if key not in seen:
                seen.add(key)
                out.append(member)
    return out


def _derived_filter_step(bundle: dict, listings: List[dict]) -> str:
    """Name the attributes to filter on, taken from *these listings'* own items.

    An attribute is named only where it was observed on a product page one of
    the affected listings actually links to. Read from the whole crawl instead,
    the step named a locator tag's diameter on a handset family page: both
    products are on one host, and nothing else connected them. Where no member
    page was read, the step names no attribute at all rather than guessing -
    an unrelated product's attribute is worse than none.
    """
    vocab = catalogue_vocabulary(bundle, listings)
    names = example_attributes(vocab, 3)
    # `catalogue_vocabulary` already reads only from members, so an
    # undelimited listing yields nothing here - but stating the rule at the
    # point of use keeps the guarantee readable: an attribute is named only
    # where the chain listing -> member -> observed attribute exists.
    if names != [PLACEHOLDER["attribute"]]:
        return ("Filter on the attributes the product pages in these listings already publish: "
                + ", ".join(f"'{n}'" for n in names) + ".")
    # Nothing to name. Which of the two reasons it is matters to the reader:
    # "we could not read your products" is a statement about this crawl, and
    # "your products state no attributes" is a statement about the pages.
    if _members_of(bundle, listings):
        return ("Filter on attributes these products publish - the product pages in these "
                "listings state no attribute label/value pair or typed property to filter on, "
                "so publishing the attributes comes first.")
    return ("Filter on the attributes this catalogue publishes on the product pages these "
            "listings link to (none of those pages were read in this crawl, so start from "
            "the attributes buyers ask about most).")


def _readable(dimensions: List[str]) -> str:
    """"price", or "price and rating" - a prose list, not a quoted control name."""
    if len(dimensions) == 1:
        return dimensions[0]
    return ", ".join(dimensions[:-1]) + " and " + dimensions[-1]


def _sort_summary(dimensions: List[str]) -> str:
    """The headline, naming only dimensions the items were seen to carry."""
    if dimensions:
        return f"Add sorting by {_readable(dimensions)} on category listings."
    return "Add a sort control to category listings."


def _derived_sort_step(dimensions: List[str]) -> str:
    """Which order to offer, decided by what the items publish.

    "Sort by price and by rating" is a claim about the items: it says both
    values exist across the set. On a listing whose products carry no rating
    that is advice to sort on a field nobody has, and where the items were
    never read it is advice about items the audit never saw. So each dimension
    is named only where the value behind it was observed, and where none was,
    the step says how to choose one instead of asserting two.
    """
    if dimensions:
        return (f"Add a sort control covering at least {_readable(dimensions)} - "
                f"{'these are the values' if len(dimensions) > 1 else 'this is the value'} "
                f"the items in these listings publish.")
    return ("Add a sort control on a value the items in these listings publish. No price or "
            "rating was observed on them or on the product pages they link to, so publishing "
            "the value to order on comes first.")


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def rule_lead_answer(bundle: dict) -> Optional[Finding]:
    """Are the two decisive facts in the opening block of the *fetched* HTML?

    This is a document-order measurement, not a viewport one. Without a
    headless render at a known viewport the audit cannot see what is above the
    fold, cannot see a carousel or a modal, and certainly cannot see a visitor
    bounce - so it claims none of those. What it can state exactly is where
    price and availability appear in the byte stream an assistant fetcher
    reads, which is a real and checkable property of the template.
    """
    # Which facts a page owes depends on what it sells: a stock statement is
    # asked of physical goods, a price of anything offered for sale, and
    # nothing of a page that describes an item without selling it.
    parts = product_pages_where(bundle, semantics.is_price_applicable)
    products = parts.pages
    if not sample_guard(products, 1):
        return None
    context = semantic_context(bundle)
    weak = []
    for page in products:
        lead = page.get("block_text_excerpt") or (page.get("text", "")[:1200])
        full_text = page.get("text", "") or ""
        wants_stock = bool(semantics.is_stock_applicable(page, context))
        has_price = bool(PRICE_RE.search(lead))
        has_availability = _states_availability(page, lead) if wants_stock else True
        if not (has_price and has_availability):
            # Distinguish "stated later in the document" from "not stated at
            # all" - a different problem with a different fix.
            weak.append({
                "page": page,
                "lead_price": has_price,
                "lead_availability": has_availability,
                "stock_expected": wants_stock,
                "price_later": bool(PRICE_RE.search(full_text)) and not has_price,
                "availability_later": wants_stock and _states_availability(page, full_text)
                and not has_availability,
            })
    # Availability is read from prose, so a page in an uncovered language can
    # look silent when it is not. Its price is still measurable, so the page is
    # only kept when the *price* is what is missing from the lead block.
    weak = [w for w in weak
            if w["page"].get("language_supported") is not False or not w["lead_price"]]
    if not weak:
        return None
    ratio = len(weak) / len(products)
    if ratio < 0.4:
        return None

    render = bundle.get("render", {}) or {}
    rendered = bool(render.get("available")) and not render.get("error")
    viewport = render.get("viewport") if rendered else None
    mode = (render.get("render_mode") or "static-fetch") if rendered else "static-fetch"
    if rendered and viewport:
        basis = (f"Measured after a headless render ({mode}) at a "
                 f"{viewport.get('width')}x{viewport.get('height')} viewport.")
    else:
        basis = ("Measured on the server-rendered HTML in document order; no headless "
                 "render was performed, so this finding makes no claim about what is "
                 "visible without scrolling.")

    later = sum(1 for w in weak if w["price_later"] or w["availability_later"])
    also = (f" On {later} of them the missing fact does appear further down the same "
            "document." if later else "")

    def _describe(entry) -> str:
        missing = []
        if not entry["lead_price"]:
            missing.append("price")
        if not entry["lead_availability"]:
            missing.append("an availability statement")
        where = []
        if entry["price_later"]:
            where.append("price appears later in the document")
        if entry["availability_later"]:
            where.append("availability appears later in the document")
        tail = f"; {', '.join(where)}" if where else ""
        return f"opening block contains no {' and no '.join(missing)}{tail}"

    stock_pages = sum(1 for w in weak if w["stock_expected"])
    what = ("price and availability" if stock_pages else "the price")
    return finding(
        "EG-LEAD-ANSWER-WEAK",
        f"{what[0].upper() + what[1:]} {'are' if stock_pages else 'is'} not in the opening "
        f"block of the product HTML",
        severity_from_sample(ratio, len(products), critical=1.01, high=0.75, medium=0.4), PILLAR,
        evidence=f"On {len(weak)} of {len(products)} product page(s) offered for sale, the "
                 f"first ~1,200 characters of readable content in the fetched HTML contain no "
                 f"price"
                 + (" and/or no availability statement" if stock_pages else "")
                 + f".{also} {basis}"
                 + (" A stock statement was expected only of the pages selling physical "
                    "goods." if stock_pages and stock_pages < len(weak) else "")
                 + parts.note(),
        interpretation="A reader that takes the document in order meets the opening block "
                       "first, and one that works from a bounded window may not reach facts "
                       "placed further down, or may not associate them with this product. This "
                       "is an observation about document order; how any particular fetcher "
                       "windows a page, and the effect on any individual visit, are not things "
                       "this audit measures.",
        items=[observed(_describe(entry), url=label(entry["page"]),
                        locator="first ~1200 characters of block text, document order")
               for entry in weak[:5]],
        action=action(f"Order the product template so {what} come{'' if stock_pages else 's'} "
                      f"first.",
                      priority="high", effort="low", impact="high",
                      mechanism="A reader that takes a bounded window of the document gets "
                                "the facts that appear early. Putting the name and the "
                                "decisive facts at the top of the markup puts them inside any "
                                "such window regardless of how the page is laid out visually.",
                      steps=["Emit the name, the price" + (", the stock position, the delivery "
                                                          "estimate and the return window"
                                                          if stock_pages else
                                                          " and the key facts a buyer asks about")
                             + " early in the product template's markup, before long-form "
                               "marketing copy.",
                             "Server-render those facts so they are in the HTML a fetcher "
                             "receives, not added afterwards by script.",
                             "Keep the visible layout free to differ - this is about the "
                             "order of the markup, not the order on screen."],
                      verification=f"curl -s <product-url> | head -c 4000 contains {what}.",
                      verification_type="self_verifiable"),
        urls=[label(w["page"]) for w in weak],
        confidence=confidence_for(len(weak), len(products), base=0.85),
        metrics={"scope": scope_for(len(weak), len(products)),
                 "affected": len(weak), "sampled": len(products),
                 "sample_unit": "sampled product page(s) offered for sale",
                 "not_assessed": parts.not_assessed,
                 "kind_inferred_from_site": parts.inferred,
                 "stock_statement_expected_on": stock_pages,
                 "render_mode": mode,
                 "viewport": viewport,
                 "measured_on": "server-rendered HTML in document order"
                 if not rendered else "rendered DOM",
                 "stated_later_in_document": later},
        tags=["continuity", "landing", "document-order"])


def rule_specs_missing(bundle: dict) -> Optional[Finding]:
    # Catalogue-shaped check: it describes filters, comparisons, specs or
    # buying affordances, none of which a non-commerce site owes anyone.
    if not commerce_guard(bundle):
        return None
    # A specification block is a physical-goods expectation. A plan, a
    # download, a service and a listing are asked nothing here.
    parts = product_pages_where(bundle, semantics.is_physical_specs_applicable)
    products = parts.pages
    if not sample_guard(products, 1):
        return None
    without = [p for p in products if not page_has_spec_block(p)]
    if not without or len(without) / len(products) < 0.4:
        return None
    ratio = len(without) / len(products)
    # The step below says "the attributes these pages already publish", so the
    # attributes have to come from these pages. Read from the whole crawl, the
    # sentence quietly becomes "attributes some other page publishes".
    vocab = site_vocabulary(bundle, pages=products)

    # How much *is* published in visible copy on those same pages. Saying "no
    # specification structure" while a page states a dozen attributes in prose
    # would be true and useless; saying "no product information" would be
    # false. The evidence has to carry both halves.
    visible_counts = [visible_attribute_presence(p)["count"] for p in without]
    with_visible = [c for c in visible_counts if c]
    if with_visible:
        stated = (f" {len(with_visible)} of those page(s) do state attributes in visible copy "
                  f"(median {sorted(with_visible)[len(with_visible) // 2]} label/value pair(s) "
                  f"per page), but not inside a specification structure.")
    else:
        stated = " No attribute label/value pairs were detected in their visible copy either."

    return finding(
        "EG-SPECS-MISSING",
        "Product attributes are not presented in a standardized specification structure",
        severity_from_sample(ratio, len(products), critical=1.01, high=0.7, medium=0.4), PILLAR,
        evidence=f"{len(without)} of {len(products)} physical-goods product page(s) contain "
                 f"no two-column specification table, no <dl> definition list and no typed "
                 f"attribute set.{stated}" + parts.note(),
        interpretation="A standardized structure is what makes attributes line up across "
                       "products: the same rows, in the same order, with units. Attributes "
                       "stated as running copy have to be located and parsed per page before "
                       "any two products can be set side by side, and the parse is the step "
                       "that goes wrong. This is about the shape of the presentation, not "
                       "about whether the information exists.",
        items=[observed(
            "no specification table, <dl> or typed attribute block on {}; "
            "{} attribute label/value pair(s) detected in visible copy".format(
                label(p), visible_attribute_presence(p)["count"]),
            url=label(p), locator="product page body")
            for p in without[:5]],
        action=action("Move the attributes already published into a specification structure.",
                      priority="high", effort="medium", impact="high",
                      mechanism="A two-column structure with one row per attribute makes the "
                                "same attribute addressable at the same place on every product "
                                "page, so values can be compared across the range without "
                                "interpreting a sentence differently on each page.",
                      steps=[f"Use a real <table> or <dl> with one row per attribute, including "
                             f"units - starting with the attributes these pages already "
                             f"publish: {attribute_phrase(vocab)}.",
                             "Keep the same attribute set, in the same order, across the "
                             "category so rows line up between products.",
                             "State the negative values too, not only the positive ones - an "
                             "explicitly absent property cannot be inferred as present.",
                             "Mirror the same values in additionalProperty markup so the "
                             "visible table and the typed data agree."],
                      example=_spec_table_example(vocab),
                      verification="curl -s <product-url> shows a <table> or <dl> whose rows "
                                   "are the attribute names.",
                      verification_type="self_verifiable"),
        urls=[label(p) for p in without],
        confidence=confidence_for(len(without), len(products)),
        metrics={"scope": scope_for(len(without), len(products)),
                 "affected": len(without), "sampled": len(products),
                 "visible_attribute_counts": visible_counts[:10],
                 "observed_attributes": example_attributes(vocab, 6),
                 "sample_unit": "sampled physical-goods product page(s)",
                 "not_assessed": parts.not_assessed,
                 "kind_inferred_from_site": parts.inferred},
        tags=["specs", "comparison", "structure"])


def rule_listing_controls(bundle: dict) -> List[Finding]:
    """Filtering and sorting, audited as two separate affordances.

    A listing can offer sorting and no filtering, filtering and no sorting,
    both, or neither. Reporting "no filtering or sorting" whenever either one
    is missing produces a claim the page visibly contradicts, so each
    affordance gets its own rule id, its own evidence and its own severity.

    ==========================  ======================================
    observed                    emitted
    ==========================  ======================================
    neither                     EG-FILTER-CONTROLS-ABSENT + EG-SORT-CONTROLS-ABSENT
    filtering only              EG-SORT-CONTROLS-ABSENT
    sorting only                EG-FILTER-CONTROLS-ABSENT
    both                        nothing
    ==========================  ======================================
    """
    # Catalogue-shaped check: it describes filters, comparisons, specs or
    # buying affordances, none of which a non-commerce site owes anyone.
    if not commerce_guard(bundle):
        return []
    # `ev.category_pages` is the only way in. Filtering and sorting are
    # affordances a *set* needs, so asking a product detail page for them is
    # not a finding, it is a category error - and the way one reached a live
    # report was a rule deciding for itself which pages were listings.
    # Among listings, only a *catalogue* listing - goods, software, third-party
    # listings - is asked for them: an article index or a documentation
    # section is a set too, and owes nobody a price sort.
    categories, set_aside = catalogue_listing_pages(bundle)
    # A listing of a handful of items is scanned, not sorted: controls are
    # an expectation only of a listing that shows a set large enough to
    # need them, or that paginates. The rest are set aside and named.
    sized = []
    for page in categories:
        expected, why = listing_controls_expected(page)
        if expected:
            sized.append(page)
        else:
            set_aside[why] = set_aside.get(why, 0) + 1
    categories = sized
    if not sample_guard(categories, 1):
        return []
    aside_note = set_aside_note(set_aside, "listing page(s)")
    # Size is not the same question as *set*. The absence of a filter control on
    # a page showing this many entries is an observation either way, so the
    # finding stands; what does not stand is any claim about the items. A
    # product-family page, a marketing page and a storefront collection whose
    # products the crawl never reached are indistinguishable by shape - all
    # three are links and prices - so the audit states which of them it could
    # delimit instead of guessing between them, and describes the items only
    # for the ones it could.
    provenance = {label(p): collection_provenance(p, bundle) for p in categories}
    bases = sorted({r["basis"] for r in provenance.values() if r["established"]})
    undelimited = [p for p in categories if not provenance[label(p)]["established"]]
    collection_note = ""
    if bases:
        collection_note += (" The set each listing represents is established by: "
                            + "; ".join(bases[:3]) + ".")
    if undelimited:
        collection_note += (
            f" For {len(undelimited)} of them the set could not be delimited - no product page "
            f"they link to was read, no ItemList is declared, they do not paginate and they "
            f"expose no catalogue controls - so this finding reports the missing affordance "
            f"and says nothing about what the items are.")
    controls = [(p, listing_controls(p)) for p in categories]
    no_filter = [p for p, c in controls if not c["has_filter_controls"]]
    no_sort = [p for p, c in controls if not c["has_sort_controls"]]
    # A control the server response does not carry may still be on the page: a
    # listing that mounts its facets after hydration has them, and calling that
    # "no filter control" is false to anyone looking at the site. Where the
    # browser-rendered state was measured and the control is in it, the page is
    # reported separately, as a rendering gap rather than an absence.
    filter_rendered = rendered_only(no_filter, _has_filter)
    sort_rendered = rendered_only(no_sort, _has_sort)
    no_filter = [p for p in no_filter if p not in filter_rendered]
    no_sort = [p for p in no_sort if p not in sort_rendered]
    total = len(categories)
    out: List[Finding] = []
    if filter_rendered or sort_rendered:
        out.append(_rendered_controls_finding(bundle, filter_rendered, sort_rendered, total))

    if no_filter:
        ratio = len(no_filter) / total
        # Say what *was* found as well as what was not, so the reader can see
        # the auditor looked at both affordances independently.
        with_sort = sum(1 for p, c in controls
                        if not c["has_filter_controls"] and c["has_sort_controls"])
        observed_sorts = name_list([o for p, c in controls
                                    if not c["has_filter_controls"]
                                    for o in (c["sort_options"] or c["sort_control_names"])])
        also = ""
        if with_sort:
            also = f" {with_sort} of those page(s) do expose sort controls"
            also += f" ({observed_sorts})." if observed_sorts else "."
        # Two halves, decided in one place: the control is genuinely absent
        # (observed), and this listing is a comparable set worth filtering
        # (applies). Where the second cannot be established the observation
        # stands but its meaning does not, so it is reported at a lowered
        # severity and confidence and says what could not be assessed.
        delimited = [p for p in no_filter if provenance[label(p)]["established"]]
        verdict = applicability_verdict(
            observed=True, applies=bool(delimited),
            severity=severity_from_sample(ratio, total, critical=1.01, high=0.7, medium=0.3),
            confidence=confidence_for(len(no_filter), total, base=0.85),
            uncertain_note=UNDELIMITED_NOTE)
        out.append(finding(
            "EG-FILTER-CONTROLS-ABSENT",
            "Category pages expose no filter controls in the HTML"
            if verdict.reported else
            "Filter controls could not be assessed against a known comparable set",
            verdict.severity, PILLAR,
            evidence=f"{len(no_filter)} of {total} catalogue listing page(s) expose no filter, "
                     f"facet or refine control in the server-rendered HTML.{also}"
                     + collection_note + verdict.note + rendered_note(bundle) + aside_note,
            interpretation="Filtering and sorting answer different questions. A request that "
                           "carries a constraint (a price ceiling, an attribute, a variant) "
                           "needs the non-matching products removed; re-ordering the same set "
                           "does not satisfy it. Where each filter combination also has its own "
                           "crawlable URL, that filtered view becomes a page an assistant can "
                           "link to directly instead of sending the reader to a full grid.",
            items=[observed(
                "no filter, facet or refine control found in the HTML of {}{}".format(
                    label(p), _sort_aside(p)),
                url=label(p), locator="category page forms and links")
                for p in no_filter[:5]],
            action=action(**conditional_advice(
                verdict, intended_as="a catalogue of comparable items",
                assertive=dict(
                    summary="Add filtering on the attributes this catalogue actually publishes.",
                    priority="high", effort="medium", impact="high",
                    mechanism="A constrained request can only be satisfied by removing "
                              "the products that do not match. A listing with no filter "
                              "affordance cannot express the constraint, and has no "
                              "filtered URL to link to.",
                    steps=[_derived_filter_step(bundle, no_filter),
                           "Give each filter combination a crawlable, linkable URL so a "
                           "filtered view can be deep-linked.",
                           "Render the controls and the default result set server-side, "
                           "so the affordance is present in the fetched HTML."],
                    verification="A filtered URL can be shared, opens with the filter "
                                 "already applied, and returns 200 to curl.",
                    verification_type="self_verifiable"),
                conditional=dict(
                    summary="Establish the item set before deciding whether filters apply.",
                    effort="medium", impact="medium",
                    mechanism="Because the comparable item set could not be established, no "
                              "specific filter attribute can be recommended: an attribute is "
                              "a property of items, and none of this page's items were read. "
                              "What was observed is that the server response carries no "
                              "filter, facet or refine control.",
                    steps=["If this page is intended to function as {intended_as}, make its "
                           "members readable - link each item to its own page, declare an "
                           "ItemList, or paginate - so the set it represents can be "
                           "established.",
                           "Once the set is established, expose filters only for attributes "
                           "shared by those members. Until then this audit has no basis for "
                           "naming one.",
                           "If the page is not intended as a catalogue, no filter control is "
                           "expected of it and this observation needs no action."],
                    verification="Re-run the audit: once the item set is established the "
                                 "finding is assessed against it rather than reported as "
                                 "unassessable.",
                    verification_type="self_verifiable"))),
            urls=[label(p) for p in no_filter],
            confidence=verdict.confidence,
            metrics={"scope": scope_for(len(no_filter), total),
                     "affected": len(no_filter), "sampled": total,
                     "applicability": verdict.action,
                     "has_filter_controls": False,
                     "pages_with_sort_controls": sum(
                         1 for _, c in controls if c["has_sort_controls"]),
                     "observed_sort_options": sorted({
                         o for _, c in controls for o in c["sort_options"]})[:12],
                     "comparable_items_basis": bases[:4],
                     "listings_with_no_delimitable_set": len(undelimited),
                     # Where the attribute names in the action came from. An
                     # attribute is quotable here only when a page one of these
                     # listings links to was read and published it.
                     "attribute_provenance": [label(m) for m in _members_of(bundle,
                                                                           no_filter)][:8],
                     "sample_unit": "sampled catalogue listing page(s)",
                     "not_assessed": sum(set_aside.values())},
            tags=["navigation", "comparison", "filtering"]))

    if no_sort:
        ratio = len(no_sort) / total
        # An ordering dimension is a claim about the items, so it is named only
        # where the chain listing -> members -> observed value exists. On a
        # listing whose set could not be delimited the page's own printed
        # prices are not enough: they may belong to items this page does not
        # represent, and "add sorting by price" would be advice about a set
        # nobody has established.
        sort_delimited = [p for p in no_sort if provenance[label(p)]["established"]]
        orderable = orderable_dimensions(bundle, sort_delimited) if sort_delimited else []
        with_filter = sum(1 for p, c in controls
                          if not c["has_sort_controls"] and c["has_filter_controls"])
        observed_filters = name_list([n for p, c in controls
                                      if not c["has_sort_controls"]
                                      for n in c["filter_control_names"]])
        also = ""
        if with_filter:
            also = f" {with_filter} of those page(s) do expose filter controls"
            also += f" ({observed_filters})." if observed_filters else "."
        sort_verdict = applicability_verdict(
            observed=True, applies=bool(sort_delimited),
            severity=severity_from_sample(ratio, total, critical=1.01, high=1.01, medium=0.5),
            confidence=confidence_for(len(no_sort), total, base=0.85),
            uncertain_note=UNDELIMITED_NOTE)
        out.append(finding(
            "EG-SORT-CONTROLS-ABSENT",
            "Category pages expose no sort controls in the HTML"
            if sort_verdict.reported else
            "Sort controls could not be assessed against a known comparable set",
            sort_verdict.severity, PILLAR,
            evidence=f"{len(no_sort)} of {total} catalogue listing page(s) expose no sort or "
                     f"order control in the server-rendered HTML.{also}"
                     + collection_note + sort_verdict.note + rendered_note(bundle) + aside_note,
            interpretation="Sorting is what a superlative request rests on - cheapest, "
                           "highest-rated, newest. Without it the listing has one fixed order, "
                           "and a ranked answer has to be assembled from the individual product "
                           "pages instead of read off the listing.",
            items=page_items(no_sort, "no sort or order control found in the HTML of {url}",
                             limit=5),
            action=action(**conditional_advice(
                sort_verdict, intended_as="a catalogue of comparable items",
                assertive=dict(
                    summary=_sort_summary(orderable), priority="medium", effort="low",
                    impact="medium",
                    mechanism="A listing that can be ordered by a value its items publish "
                              "states a ranking explicitly. Without one, the ranking has "
                              "to be inferred from separate pages, which is slower and "
                              "easier to get wrong.",
                    steps=[_derived_sort_step(orderable),
                           "Reflect the active sort in the URL so a sorted view is "
                           "linkable and crawlable.",
                           "Render the default order server-side."],
                    verification="A sorted URL opens with the order already applied and "
                                 "returns 200 to curl.",
                    verification_type="self_verifiable"),
                conditional=dict(
                    summary="Establish the item set before deciding whether ordering applies.",
                    effort="low", impact="medium",
                    mechanism="Because the comparable item set could not be established, a "
                              "specific ordering dimension cannot be recommended: an ordering "
                              "value is a property of items, and none of this page's items "
                              "were read. What was observed is that the server response "
                              "carries no sort or order control.",
                    steps=["If this page is intended to function as {intended_as}, make its "
                           "members readable - link each item to its own page, declare an "
                           "ItemList, or paginate - so the set it represents can be "
                           "established.",
                           "Once the set is established, expose ordering controls only for "
                           "values actually published by its members. Until then this audit "
                           "has no basis for naming one.",
                           "If the page is not intended as a catalogue, no ordering control is "
                           "expected of it and this observation needs no action."],
                    verification="Re-run the audit: once the item set is established the "
                                 "finding is assessed against it rather than reported as "
                                 "unassessable.",
                    verification_type="self_verifiable"))),
            urls=[label(p) for p in no_sort],
            confidence=sort_verdict.confidence,
            metrics={"scope": scope_for(len(no_sort), total),
                     "affected": len(no_sort), "sampled": total,
                     "applicability": sort_verdict.action,
                     "has_sort_controls": False,
                     "pages_with_filter_controls": sum(
                         1 for _, c in controls if c["has_filter_controls"]),
                     "observed_filter_controls": sorted({
                         n for _, c in controls for n in c["filter_control_names"]})[:12],
                     "comparable_items_basis": bases[:4],
                     "listings_with_no_delimitable_set": len(undelimited),
                     # The order dimensions named in the action, and nothing
                     # else: each one is a value observed on these listings or
                     # on the product pages they link to.
                     "evidenced_order_dimensions": orderable,
                     "sample_unit": "sampled catalogue listing page(s)",
                     "not_assessed": sum(set_aside.values())},
            tags=["navigation", "comparison", "sorting"]))
    return out


def rule_reviews_absent(bundle: dict) -> Optional[Finding]:
    # Review content is an expectation of goods and software people buy and
    # rate. A service page, a manufacturer's information page and a plan
    # comparison are asked nothing here, and the finding says so.
    parts = product_pages_where(bundle, semantics.is_reviews_applicable)
    products = parts.pages
    if not sample_guard(products, 2):
        return None
    without = []
    for page in products:
        has_markup = bool(find_nodes(jsonld_nodes(page), "Review", "AggregateRating"))
        mentions = (page.get("mentions", {}) or {}).get("reviews")
        if not has_markup and not mentions:
            without.append(page)
    # Never assert an absence from prose we cannot read. Two sibling rules
    # already apply this guard; leaving it off here meant a Polish page
    # printing "Opinie klientow: 4,8 na 5" was told it mentions no reviews.
    without = [p for p in without if p.get("language_supported") is not False]
    if not without or len(without) / len(products) < 0.6:
        return None
    # The absence of optional content is capped: no review is a gap worth
    # naming, not a blocker, and rating it `high` said more than the evidence.
    return finding(
        "EG-REVIEWS-ABSENT",
        ("Product pages carry no review or rating content" if len(without) == len(products)
         else "Most product pages carry no review or rating content"),
        semantics.cap_optional(cap_severity("high", len(products))), PILLAR,
        evidence=f"{len(without)} of {len(products)} product page(s) selling goods or software "
                 "contain no review markup and no reference to reviews or ratings anywhere in "
                 "their text." + parts.note(),
        interpretation="Where a page carries no review content, nothing on it states how the "
                       "item was received by buyers, so a question about that has no stated "
                       "fact on this page to be answered from. Whether reviews exist elsewhere, "
                       "and how any system weighs them, is not something this audit measures.",
        items=page_items(without, "no review/rating markup and no review text on {url}", limit=5),
        action=action("Collect and publish reviews server-side, with ratings marked up.",
                      priority="medium", effort="medium", impact="medium",
                      mechanism="Review text and a typed AggregateRating in the server HTML "
                                "provide explicit, machine-readable evidence of how the item "
                                "was received, on the page that describes it.",
                      steps=["Request reviews after purchase and publish them with dates.",
                             "Render review text in the server HTML, not only in a widget.",
                             "Mark up aggregateRating and a sample of Review nodes.",
                             "Publish negative reviews too, so the rating describes what "
                             "buyers actually said."],
                      verification="curl a product page and find review text and a rating value "
                                   "in the response."),
        urls=[label(p) for p in without],
        confidence=confidence_for(len(without), len(products)),
        metrics={"scope": scope_for(len(without), len(products)),
                 "affected": len(without), "sampled": len(products),
                 "sample_unit": "sampled product page(s) selling goods or software",
                 "not_assessed": parts.not_assessed,
                 "kind_inferred_from_site": parts.inferred},
        tags=["reviews", "social-proof"])


def rule_reviews_widget_only(bundle: dict) -> Optional[Finding]:
    products = ev.product_pages(bundle)
    if not sample_guard(products, 1):
        return None
    widget_only = []
    for page in products:
        mentions = (page.get("mentions", {}) or {}).get("reviews")
        has_markup = bool(find_nodes(jsonld_nodes(page), "Review", "AggregateRating"))
        if mentions and not has_markup and shows_client_rendering_signals(page):
            widget_only.append(page)
    if not widget_only:
        return None
    return finding(
        "EG-REVIEWS-CLIENT-RENDERED",
        "Reviews appear to be loaded by a client-side widget, so the proof is invisible to a fetch",
        "high", PILLAR,
        evidence=f"{len(widget_only)} product page(s) reference reviews in their text and load "
                 "many external scripts, but no review text or rating value is present in the "
                 "server response - the pattern of a rating assembled after load by a "
                 "client-side widget, in a form a fetch that does not run scripts cannot read.",
        items=[observed(f"{(p.get('scripts') or {}).get('external_count', 0)} external scripts, "
                        "review wording present, no Review/AggregateRating node in the HTML",
                        url=label(p), locator="raw HTML response") for p in widget_only[:5]],
        action=action("Render at least the aggregate rating and a few reviews server-side.",
                      priority="high", effort="medium", impact="high",
                      mechanism="Third-party review widgets inject their content after load, "
                                "so the rating exists in the rendered page and not in the "
                                "server response; rendering it server-side puts the same "
                                "value in the bytes a fetch receives.",
                      steps=["Ask the review vendor for their SEO/server-rendered snippet or API.",
                             "Fetch the aggregate at build/render time and emit it in the HTML "
                             "plus AggregateRating markup.",
                             "Render the newest 3-5 review bodies server-side; keep pagination "
                             "client-side.",
                             "Never mark up a rating the page does not actually display."],
                      verification="curl -s <product url> | grep -i 'ratingValue' returns a "
                                   "value."),
        urls=[label(p) for p in widget_only], confidence=0.75,
        metrics={"scope": "template", "affected": len(widget_only)},
        tags=["reviews", "rendering"])


def rule_faq_missing(bundle: dict) -> Optional[Finding]:
    pages = ev.pages(bundle)
    if not sample_guard(pages, 3):
        return None
    has_faq_page = any(p.get("page_type") == "faq" for p in pages)
    has_faq_markup = any(find_nodes(jsonld_nodes(p), "FAQPage", "QAPage", "Question")
                         for p in pages)
    has_faq_blocks = any((p.get("details_faq_blocks") or 0) >= 2 or
                         len(p.get("question_headings") or []) >= 2 for p in pages)
    if has_faq_page or has_faq_markup or has_faq_blocks:
        return None
    if all(p.get("language_supported") is False for p in pages):
        return None
    # Which questions a site can be expected to answer follows what the site
    # is observed to be. A documentation set is not asked to publish delivery
    # answers and a shop is not asked to publish API usage: the intents come
    # from the same site context every other rule reads, and the finding names
    # them so the reader can see which ones were derived and from what.
    context = semantic_context(bundle)
    intents = semantics.high_value_question_intents(context)
    if not intents:
        return None
    topics = "; ".join(i["topics"] for i in intents[:3])
    grounds = "; ".join(f"{i['topics']} ({i['why']})" for i in intents[:3])
    caveat = coverage_caveat(bundle, "faq", "help", "support", "question")
    return finding(
        "EG-FAQ-MISSING",
        "No page states an answer in the form of the question it answers",
        step_down("medium", caveat), PILLAR,
        evidence=f"Across {len(pages)} sampled page(s) there is no FAQ page, no FAQPage/Question "
                 f"markup, and no question-shaped headings. On the evidence of what this site "
                 f"publishes, the questions its readers arrive with are about {grounds}." + caveat,
        interpretation="A question-shaped heading with its answer immediately below states one "
                       "fact in the form the question takes, in one place, where the same fact "
                       "spread through prose has to be assembled. Which questions are worth "
                       "publishing follows what this site is; whether any system matches on "
                       "that shape is not something this audit measures.",
        items=[absent("no FAQ page found among the crawled pages",
                      url=bundle["site"]["origin"]),
               absent("no FAQPage/QAPage/Question structured data on any sampled page",
                      url=bundle["site"]["origin"], locator="JSON-LD"),
               absent("no question-shaped headings or <details>/<summary> Q&A blocks",
                      url=bundle["site"]["origin"], locator="page headings"),
               observed(f"question intents derived from this site's own evidence: {grounds}",
                        url=bundle["site"]["origin"], locator="site semantics")],
        action=action("Publish the questions your readers actually arrive with, each answered "
                      "directly beneath it, on the page that owns the answer.",
                      priority="medium", effort="medium", impact="high",
                      mechanism="A heading that is the question, with the answer in the next "
                                "sentence, states that answer explicitly and in one place. "
                                "Where no page does that, the answer has to be assembled from "
                                "prose that was written for a different purpose.",
                      steps=[f"Start from the subjects this site publishes: {topics}.",
                             "Take the real wording from your own sources - support tickets, "
                             "on-site search logs, the questions people send you. This audit "
                             "derives intents from your content, not from anyone's behaviour.",
                             "Answer each in 2-3 sentences immediately under the question "
                             "heading; no preamble.",
                             "Keep each question on the page that owns the answer, and general "
                             "ones on a single FAQ page.",
                             "Add FAQPage markup, and keep the marked-up text identical to what "
                             "is displayed."],
                      verification="Fetch the page with curl and confirm each question appears "
                                   "as a heading with its answer in the following element, and "
                                   "that FAQPage markup quotes the same text.",
                      verification_type="self_verifiable"),
        urls=[bundle["site"]["origin"]], confidence=0.85,
        metrics={"scope": "site", "sampled": len(pages),
                 "question_intents": [i["intent"] for i in intents],
                 "site_kind": context.get("site_kind")},
        tags=["content", "answerability"])


def rule_policy_facts_invisible(bundle: dict) -> List[Finding]:
    out: List[Finding] = []
    pages = ev.pages(bundle)
    policy_pages = [p for p in pages if p.get("page_type") == "policy"]

    for key, predicate, schema_types, title, mechanism in (
        ("shipping", semantics.is_shipping_applicable,
         ("OfferShippingDetails", "ShippingDeliveryTime"),
         "Delivery information is missing from physical-goods product pages",
         "A delivery statement on the page is an explicit, quotable answer to 'when will it "
         "arrive?' on the page that describes the item; without it the page states no "
         "delivery expectation on your behalf."),
        ("returns", semantics.is_returns_applicable, ("MerchantReturnPolicy",),
         "Return information is missing from physical-goods product pages",
         "A stated return window on the page is an explicit, quotable answer to 'can I "
         "send it back?' on the page that describes the item; without it the page states "
         "no return terms on your behalf."),
    ):
        # Delivery and returns are physical-goods expectations. The
        # applicability engine decides per page - a download, a plan, a
        # service or an information page is set aside and named as such.
        parts = product_pages_where(bundle, predicate)
        products = parts.pages
        if not sample_guard(products, 1):
            continue
        missing = [p for p in products if not _policy_stated(p, key, *schema_types)]
        # Never assert an absence from prose we cannot read.
        missing = [p for p in missing if p.get("language_supported") is not False]
        if not missing or len(missing) / len(products) < 0.6:
            continue
        out.append(finding(
            f"EG-{key.upper()}-INVISIBLE", title,
            # Universal absence is high only when enough pages were read to
            # call it universal; one page cannot carry a template verdict.
            cap_severity("high" if len(missing) == len(products) else "medium", len(products)),
            PILLAR,
            evidence=f"{len(missing)} of {len(products)} product page(s) selling physical goods "
                     f"state nothing about {key}: no wording in any language the audit reads, "
                     f"and no {'/'.join(schema_types)} markup"
                     + (f", although {len(policy_pages)} policy page(s) exist elsewhere on the "
                        "site." if policy_pages else ", and no policy page was found.")
                     + parts.note(),
            items=page_items(missing, f"no {key} information in the text or markup of {{url}}",
                             limit=5),
            action=action(f"State the {key} terms on the product page itself, not only in a "
                          "linked policy.",
                          priority="high", effort="low", impact="high",
                          mechanism=mechanism,
                          steps=[f"Add a short {key} line near the buy button with the actual "
                                 "numbers (days, cost, destinations).",
                                 "Link to the full policy for detail, but do not rely on the "
                                 "link to carry the fact.",
                                 f"Mirror the numbers in structured data "
                                 f"({'OfferShippingDetails' if key == 'shipping' else 'MerchantReturnPolicy'}) "
                                 "on the Offer.",
                                 "Keep the page text and the policy page in agreement."],
                          verification=f"curl a product page and find the {key} terms in the "
                                       "response text."),
            urls=[label(p) for p in missing],
            confidence=confidence_for(len(missing), len(products)),
            metrics={"scope": scope_for(len(missing), len(products)),
                     "affected": len(missing), "sampled": len(products),
                     "sample_unit": "sampled product page(s) selling physical goods",
                     "not_assessed": parts.not_assessed,
                     "kind_inferred_from_site": parts.inferred},
            tags=["policy", key]))
    return out


def rule_policy_not_structured(bundle: dict) -> Optional[Finding]:
    # Catalogue-shaped check: it describes filters, comparisons, specs or
    # buying affordances, none of which a non-commerce site owes anyone.
    if not commerce_guard(bundle):
        return None
    # Typed delivery and return terms are an expectation of goods that are
    # delivered and can be sent back. The applicability engine decides per
    # page; a download's refund line or a plan's cancellation terms are not
    # asked for MerchantReturnPolicy markup, and are set aside by name.
    parts = product_pages_where(
        bundle, lambda page, ctx: (semantics.is_shipping_applicable(page, ctx)
                                   or semantics.is_returns_applicable(page, ctx)))
    products = parts.pages
    if not sample_guard(products, 1):
        return None
    mentions_policy = [p for p in products
                       if (p.get("mentions", {}) or {}).get("shipping")
                       or (p.get("mentions", {}) or {}).get("returns")]
    if not mentions_policy:
        return None  # covered by EG-*-INVISIBLE
    structured = [p for p in mentions_policy
                  if find_nodes(jsonld_nodes(p), "MerchantReturnPolicy", "OfferShippingDetails")]
    if structured:
        return None
    return finding(
        "EG-POLICY-NOT-STRUCTURED",
        "Shipping and return terms are prose only, not typed data",
        "medium", PILLAR,
        evidence=f"{len(mentions_policy)} product page(s) to which delivery or return terms "
                 "apply (physical goods, or pages that state such terms themselves) mention "
                 "shipping and/or returns in prose, but none declares MerchantReturnPolicy or "
                 "OfferShippingDetails, so the actual numbers (days, cost, destinations) are "
                 "not addressable." + parts.note(),
        items=[absent("shipping/returns mentioned in text but no MerchantReturnPolicy or "
                      "OfferShippingDetails markup", url=label(p), locator="JSON-LD Offer")
               for p in mentions_policy[:5]],
        action=action("Add MerchantReturnPolicy and OfferShippingDetails to the Offer.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="Prose has to be interpreted; typed fields are read. "
                                "merchantReturnDays is a number that can be read and quoted directly; "
                                "'hassle-free returns' is not.",
                      steps=["Add hasMerchantReturnPolicy with merchantReturnDays, "
                             "returnPolicyCategory, returnFees and returnMethod.",
                             "Add shippingDetails with shippingRate and deliveryTime "
                             "(handlingTime + transitTime) per shippingDestination.",
                             "Keep the numbers identical to the policy page."],
                      example='"hasMerchantReturnPolicy":{"@type":"MerchantReturnPolicy",'
                              '"merchantReturnDays":30,"returnPolicyCategory":'
                              '"https://schema.org/MerchantReturnFiniteReturnWindow",'
                              '"returnFees":"https://schema.org/FreeReturn"}',
                      verification="Ask an assistant what this organization's return window "
                                   "is and check it returns the exact number of days stated "
                                   "on the policy page.",
                      verification_type="external_validation"),
        urls=[label(p) for p in mentions_policy], confidence=0.9,
        metrics={"scope": "template", "affected": len(mentions_policy)},
        tags=["policy", "structured-data"])


def rule_availability_invisible(bundle: dict) -> Optional[Finding]:
    # Stock is a physical-goods concept. A download is never out of stock, a
    # plan has no inventory, and a page that describes an item without
    # selling it owes no stock position; each is set aside and named.
    parts = product_pages_where(bundle, semantics.is_stock_applicable)
    products = parts.pages
    if not sample_guard(products, 1):
        return None
    silent = []
    for page in products:
        flags = page.get("availability_text", {}) or {}
        if any(flags.values()):
            continue
        markup = any(offer_availability(offer) for node in products_on(page)
                     for offer in offers_of(node))
        if not markup:
            silent.append(page)
    # `availability_text` is read through the prose vocabulary, so an
    # unsupported language produces silence here, not absence on the page.
    silent = [p for p in silent if p.get("language_supported") is not False]
    if not silent or len(silent) / len(products) < 0.5:
        return None
    return finding(
        "EG-AVAILABILITY-INVISIBLE",
        "Physical-goods product pages never state whether the item is in stock",
        cap_severity("high", len(products)), PILLAR,
        evidence=f"{len(silent)} of {len(products)} product page(s) selling physical goods "
                 "contain no stock wording in their text and no availability value in their "
                 "markup." + parts.note(),
        interpretation="With no stock statement in the text or the markup, the page states "
                       "nothing about whether the item can be bought now, so that question has "
                       "no fact on this page to be answered from. This audit does not measure "
                       "how any assistant or visitor responds to the silence.",
        items=page_items(silent, "no stock/availability statement in text or markup on {url}",
                         limit=5),
        action=action("Show an explicit stock state on every product page and in the Offer.",
                      priority="high", effort="low", impact="high",
                      mechanism="A stock statement in the text and a typed availability value "
                                "in the Offer provide explicit, machine-readable evidence of "
                                "whether the item can be bought now.",
                      steps=["Render 'In stock' / 'Out of stock' / 'Ships in N days' as text.",
                             "Emit the matching schema.org availability value.",
                             "For sizes, show which sizes are available rather than only "
                             "disabling them visually."],
                      verification="Every product URL shows a stock state in the raw HTML."),
        urls=[label(p) for p in silent],
        confidence=confidence_for(len(silent), len(products)),
        metrics={"scope": scope_for(len(silent), len(products)),
                 "affected": len(silent), "sampled": len(products),
                 "sample_unit": "sampled product page(s) selling physical goods",
                 "not_assessed": parts.not_assessed,
                 "kind_inferred_from_site": parts.inferred},
        tags=["availability"])


def rule_comparison_affordance(bundle: dict) -> Optional[Finding]:
    # Catalogue-shaped check: it describes filters, comparisons, specs or
    # buying affordances, none of which a non-commerce site owes anyone.
    if not commerce_guard(bundle):
        return None
    # Comparison presupposes a range of comparable items: two sellable goods,
    # applications or plans. A site with one product, or with services and
    # listings only, is not asked why it offers no comparison.
    if not semantics.is_comparison_applicable(bundle):
        return None
    pages = ev.pages(bundle)
    products = [p for p in ev.product_pages(bundle)
                if semantics.is_price_applicable(p, semantic_context(bundle))]
    if not sample_guard(products, 2):
        return None
    any_compare = any((p.get("mentions", {}) or {}).get("compare") for p in pages)
    spec_coverage = len([p for p in products if page_has_spec_block(p)])
    if any_compare or spec_coverage >= max(2, len(products) * 0.6):
        return None
    # "No comparison wording anywhere" is only observable in a language the
    # vocabulary covers. If every sampled page is in one it does not, the
    # audit saw nothing - which is not the same as the site offering nothing.
    if all(p.get("language_supported") is False for p in pages):
        return None
    return finding(
        "EG-COMPARISON-UNSUPPORTED",
        "Nothing on the site supports comparing one model against another",
        "medium", PILLAR,
        evidence=f"No comparison wording or comparison UI was found across {len(pages)} sampled "
                 f"page(s), and only {spec_coverage} of {len(products)} product page(s) publish "
                 "a comparable specification block.",
        items=[absent("no compare control, comparison table or 'X vs Y' content found in the "
                      "crawl", url=bundle["site"]["origin"]),
               measured(f"{spec_coverage} of {len(products)} product pages have a comparable "
                        "spec block", value=spec_coverage, url=bundle["site"]["origin"])],
        action=action("Publish comparison content and give the catalogue comparable attributes.",
                      priority="medium", effort="medium", impact="high",
                      mechanism="A comparison page states, on the site's own pages, how its "
                                "models differ; comparable attributes in the same structure on "
                                "every product page let those differences be read without "
                                "interpreting each page separately. Whether any visitor or "
                                "assistant was mid-comparison is not something this audit "
                                "measures.",
                      steps=["Publish '<model A> vs <model B>' pages for your own range, with a "
                             "real HTML table.",
                             "Standardise the attribute set across the category so rows line up.",
                             "Add a compare control on category pages that produces a shareable "
                             "URL.",
                             "State who each model is for - the differentiator buyers actually "
                             "use."],
                      verification="Ask an assistant to compare two products from this "
                                   "catalogue and check it can, and cites this site.",
                      verification_type="external_validation"),
        urls=[bundle["site"]["origin"]], confidence=0.75,
        metrics={"scope": "site", "spec_coverage": spec_coverage, "sampled": len(products),
                 "sample_unit": "sampled product page(s)"},
        tags=["comparison"])


def rule_cta_not_in_html(bundle: dict) -> Optional[Finding]:
    # Catalogue-shaped check: it describes filters, comparisons, specs or
    # buying affordances, none of which a non-commerce site owes anyone.
    if not commerce_guard(bundle):
        return None
    # An add-to-cart affordance is expected of goods sold through the site's
    # own cart. A subscription's "start trial", a service's "book now" and an
    # information page are not asked for one.
    parts = product_pages_where(bundle, semantics.is_purchase_cta_applicable)
    products = parts.pages
    if not sample_guard(products, 2):
        return None
    without = [p for p in products if not _states_purchase_action(p)]
    without = [p for p in without if p.get("language_supported") is not False]
    if not without or len(without) / len(products) < 0.6:
        return None
    return finding(
        "EG-CTA-NOT-IN-HTML",
        "No purchase action is present in the server-rendered product page",
        "medium", PILLAR,
        evidence=f"{len(without)} of {len(products)} product page(s) selling goods contain no "
                 "add-to-cart or buy wording in the response body." + parts.note(),
        interpretation="Where the buy affordance is absent from the fetched HTML, nothing in "
                       "the response states that the page is transactable; the affordance may "
                       "be assembled after load by script, which a fetch without JavaScript "
                       "does not receive. This audit observes the response, not how any "
                       "visitor's device rendered it.",
        items=page_items(without, "no add-to-cart/buy wording in the HTML of {url}", limit=5),
        action=action("Render the purchase affordance (and its state) server-side.",
                      priority="medium", effort="medium", impact="medium",
                      mechanism="A buy control in the server HTML is explicit evidence, in the "
                                "bytes a fetch receives, that the page is transactable and in "
                                "what state.",
                      steps=["Render the button and its disabled/out-of-stock state in the HTML.",
                             "Keep the cart interaction client-side, but not the affordance.",
                             "Confirm with `curl -s <url> | grep -i 'add to'`."],
                      verification="curl a product page and find the buy affordance text."),
        urls=[label(p) for p in without],
        confidence=confidence_for(len(without), len(products), base=0.8),
        metrics={"scope": "template", "affected": len(without), "sampled": len(products),
                 "sample_unit": "sampled product page(s) selling goods",
                 "not_assessed": parts.not_assessed,
                 "kind_inferred_from_site": parts.inferred},
        tags=["commerce", "rendering"])


def rule_orientation_dead_end(bundle: dict) -> Optional[Finding]:
    products = ev.product_pages(bundle)
    if not sample_guard(products, 2):
        return None
    dead_ends = []
    for page in products:
        internal = (page.get("links", {}) or {}).get("internal_count", 0)
        breadcrumb = (page.get("breadcrumbs", {}) or {}).get("present")
        if internal < 6 and not breadcrumb:
            dead_ends.append(page)
    if not dead_ends or len(dead_ends) / len(products) < 0.5:
        return None
    return finding(
        "EG-PRODUCT-DEAD-END",
        "Product pages are dead ends with no way onward",
        "medium", PILLAR,
        evidence=f"{len(dead_ends)} of {len(products)} product page(s) expose fewer than six "
                 "internal links and no breadcrumb trail, so a visitor who lands on the wrong "
                 "model has no path to the right one.",
        items=[measured(f"{(p.get('links') or {}).get('internal_count', 0)} internal links, no "
                        "breadcrumb trail", value=(p.get("links") or {}).get("internal_count", 0),
                        url=label(p)) for p in dead_ends[:5]],
        action=action("Give every product page a breadcrumb and onward links.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="A breadcrumb and onward links state, in the page itself, where "
                                "it sits and what is near it, so a page reached by a link that "
                                "was almost right offers a path to the right one - and a crawler "
                                "following links has the same paths. Whether any visitor takes "
                                "them is not something this audit measures.",
                      steps=["Add a breadcrumb trail as real links.",
                             "Add 'related models' and 'others in this category' link blocks.",
                             "Link to the size guide, the shipping policy and the returns page "
                             "from the product page.",
                             "Render all of it in the HTML."],
                      verification="Each product page exposes a breadcrumb and 6+ internal links "
                                   "in the raw HTML."),
        urls=[label(p) for p in dead_ends],
        confidence=confidence_for(len(dead_ends), len(products), base=0.8),
        metrics={"scope": scope_for(len(dead_ends), len(products)),
                 "affected": len(dead_ends), "sampled": len(products),
                 "sample_unit": "sampled product page(s)"},
        tags=["navigation", "continuity"])


def rule_deeplink_redirect(bundle: dict) -> Optional[Finding]:
    """A deep link that bounces to the home page is the bounce problem itself.

    Only that. A redirect is an event with several possible meanings, and this
    rule owns exactly one of them: a path that promised a resource and served a
    front door. A scheme upgrade, a www-to-apex normalisation, a market
    redirect and a route change all produce a redirect too, and each is a site
    doing something reasonable - so the shared classification decides, and this
    rule reads its answer rather than inferring one from the final URL.
    """
    verdicts = redirect_index(bundle)
    # Every requested URL: a collapsed deep link is typed `reference` (it is
    # the front door's document, not a page of its own) and is exactly the
    # evidence this rule exists to read.
    hijacked = [p for p in ev.pages(bundle, include_errors=True, include_aliases=True,
                                    include_utility=True)
                if verdicts.get(p.get("url") or "", {}).get("kind") == "homepage_collapse"]
    if not hijacked:
        return None
    first = verdicts[hijacked[0].get("url")]
    # A deep link sent to another domain's front door is still a collapse -
    # the link no longer resolves to its content - but it is the shape of a
    # domain migration whose old URLs were pointed at the new home, which is
    # a decision to review rather than a catch-all to remove.
    cross = [p for p in hijacked if verdicts[p.get("url")].get("cross_domain")]
    migration = bool(cross) and len(cross) == len(hijacked)
    return finding(
        "EG-DEEPLINK-REDIRECTED-HOME",
        "Deep links are redirected to another domain's home page" if migration else
        "Deep links are redirected to the home page",
        "medium" if migration else "high", PILLAR,
        evidence=f"{len(hijacked)} requested URL(s) ended at a front door after a redirect: "
                 f"{first['why']} (e.g. {label(hijacked[0])} -> "
                 f"{hijacked[0].get('final_url')})."
                 + (" Every one crossed to another domain, which is the shape of a domain "
                    "migration that sent old deep URLs to the new home page rather than to "
                    "their new addresses; whether that was intended is for the site owner to "
                    "say." if migration else ""),
        interpretation="A URL that resolves to the home page carries none of the specificity "
                       "the original link promised, so anything that cited the deep link now "
                       "points at a generic landing page. A crawler that requests arbitrary "
                       "paths under this host also receives 200 for all of them, which can "
                       "make retired URLs look live. This audit observed the redirects; it "
                       "does not measure how any particular index treats them.",
        items=[observed(f"{label(p)} redirected to {p.get('final_url')} "
                        f"({verdicts[p.get('url')]['hops']} hop(s))",
                        url=label(p), locator="redirect chain") for p in hijacked[:5]],
        action=action("Stop collapsing unknown or retired URLs onto the home page.",
                      priority="high", effort="low", impact="high",
                      mechanism="A home-page catch-all breaks the continuity between the "
                                "answer and the visit, and it means arbitrary URLs under the "
                                "host return 200 rather than 404, so retired addresses stay "
                                "indistinguishable from live ones.",
                      steps=["Redirect a retired product to its closest live replacement, not to "
                             "the home page.",
                             "If there is no replacement, return 404/410 with a helpful page.",
                             "Never use a catch-all rewrite for unmatched routes."],
                      verification="Each URL listed resolves to its own content or returns 404."),
        urls=[label(p) for p in hijacked], confidence=0.9,
        metrics={"scope": "site", "affected": len(hijacked), "cross_domain": len(cross)},
        tags=["continuity", "redirects"])


def rule_no_site_search(bundle: dict) -> Optional[Finding]:
    """No site search was observed - reported only where one would be expected.

    A search box is an affordance a large or catalogue-shaped site benefits
    from, not something every site owes. A six-page brochure site, a single
    department's information pages or a small blog is not asked why it has
    none; the applicability engine says when a site is big enough that its
    absence is worth a sentence, and the sentence is a `low` observation.
    """
    pages = ev.pages(bundle)
    if not sample_guard(pages, 3):
        return None
    if any((p.get("forms", {}) or {}).get("has_site_search") for p in pages):
        return None
    if any(find_nodes(jsonld_nodes(p), "SearchAction") for p in pages):
        return None
    expected = semantics.is_site_search_expected(bundle)
    if not expected:
        return None
    caveat = coverage_caveat(bundle, "search", "buscar", "recherche", "suche", "busca", "ricerca")
    return finding(
        "EG-NO-SITE-SEARCH",
        "No site search was observed on a site large enough to benefit from one",
        "low", PILLAR,
        evidence=f"No search input, search form or SearchAction markup was found on any of the "
                 f"{len(pages)} sampled page(s). A search was expected because "
                 f"{expected['reason']}." + caveat,
        interpretation="Without a search, a visitor who lands on a page that is almost the "
                       "right one has no on-site query to correct it with, and no search "
                       "result URL exists for anything to link into. Whether visitors need "
                       "that path on this site is not something this audit measures.",
        items=[absent("no <input type=search>, search form or SearchAction on any sampled page",
                      url=bundle["site"]["origin"])],
        action=action("Consider adding site search with linkable result URLs; declare it with "
                      "SearchAction once a search endpoint exists.",
                      priority="low", effort="medium", impact="medium",
                      mechanism="A search box gives a visitor an on-site way to correct a "
                                "near-miss landing, and a linkable result URL is a page that "
                                "can be pointed at directly. SearchAction markup describes an "
                                "endpoint that exists; it is only worth adding once one does.",
                      steps=["Add a search box in the header on every page.",
                             "Make results addressable at /search?q=... and server-rendered.",
                             "Once the endpoint exists, add WebSite + potentialAction "
                             "SearchAction with its urlTemplate.",
                             "Log the queries - they are the FAQ you should be publishing."],
                      example='{"@type":"WebSite","url":"https://example.com/","potentialAction":'
                              '{"@type":"SearchAction","target":'
                              '"https://example.com/search?q={search_term_string}",'
                              '"query-input":"required name=search_term_string"}}',
                      verification="https://<host>/search?q=<term> returns rendered results."),
        urls=[bundle["site"]["origin"]], confidence=0.85,
        metrics={"scope": "site", "search_expected_because": expected["reason"]},
        tags=["navigation"])


def rule_viewport(bundle: dict) -> Optional[Finding]:
    pages = ev.pages(bundle)
    if not sample_guard(pages, 3):
        return None
    without = [p for p in pages if not (p.get("viewport") or "").strip()]
    if len(without) < len(pages):
        return None
    return finding(
        "EG-NO-VIEWPORT", "Pages declare no mobile viewport", "low", PILLAR,
        evidence=f"None of the {len(pages)} sampled page(s) sets a viewport meta tag, so mobile "
                 "browsers fall back to a desktop-width layout.",
        items=page_items(without, "no viewport meta tag on {url}", limit=4),
        action=action('Add <meta name="viewport" content="width=device-width, initial-scale=1">.',
                      priority="low", effort="low", impact="medium",
                      mechanism="The viewport meta tag is the explicit statement that the page "
                                "is laid out for the width of the device showing it; without it "
                                "a mobile browser falls back to a desktop-width layout. What "
                                "share of visitors use a phone is not something this audit "
                                "measures.",
                      steps=["Add the viewport meta to the base template.",
                             "Verify the main content template at 375px width."],
                      verification="Every page returns a viewport meta tag."),
        urls=[label(p) for p in without[:8]], confidence=0.95,
        metrics={"scope": "site"}, tags=["mobile"])


RULES = (
    rule_lead_answer,
    rule_specs_missing,
    rule_listing_controls,
    rule_reviews_absent,
    rule_reviews_widget_only,
    rule_faq_missing,
    rule_policy_facts_invisible,
    rule_policy_not_structured,
    rule_availability_invisible,
    rule_comparison_affordance,
    rule_cta_not_in_html,
    rule_orientation_dead_end,
    rule_deeplink_redirect,
    rule_no_site_search,
    rule_viewport,
)


def analyze(bundle: dict) -> List[Finding]:
    # Absence is only meaningful when something was actually read. With no
    # readable page in the bundle every absence check is trivially true, so
    # the specialist reports nothing rather than a site's worth of defects
    # nobody observed.
    if not crawl_yielded_evidence(bundle):
        return []
    out: List[Finding] = []
    for rule in RULES:
        result = rule(bundle)
        if result is None:
            continue
        out.extend(result if isinstance(result, list) else [result])
    for item in out:
        item.source_skill = SKILL
        item.pillar = PILLAR
    return out


def main(argv: Optional[List[str]] = None) -> int:
    util.use_utf8_stdio()   # a report quotes the site's own text; write it as UTF-8
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    with open(args.bundle, "r", encoding="utf-8") as handle:
        bundle = json.load(handle)
    payload = json.dumps({"skill": SKILL, "pillar": PILLAR,
                          "findings": [f.to_dict() for f in analyze(bundle)]},
                         indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
