#!/usr/bin/env python3
"""machine-readability-audit - once reached, can a machine parse the facts?

Stage two of the discovery funnel. A page a crawler can fetch is still useless
if the price is an image, the JSON-LD does not parse, or the Offer has no
availability: the fact exists for a human and not for a machine.

Which facts a page owes depends on what kind of thing it is about. An Offer
with a stock value is expected of goods sold on the page, a GTIN of a physical
item, typed physical attributes of something with dimensions - and none of
those of a software download, a subscription plan, a service or a
manufacturer's information page. Every such expectation is asked of the
shared semantic layer (:mod:`aiva.semantics`) per page, and each finding
names the pages it set aside and why.

Consumes the shared evidence bundle. Performs no network I/O.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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

from aiva import evidence as ev                       # noqa: E402
from aiva import lexicon                              # noqa: E402
from aiva import util                                 # noqa: E402
from aiva.analysis import (cap_severity, coverage_caveat, step_down, crawl_yielded_evidence, commerce_evidence, absent, action, confidence_for, finding, label,    # noqa: E402
                           measured, observed, offer_availability, offer_currency,
                           offer_price, offers_of, page_has_spec_block,
                           page_items, product_attributes, product_identifiers,
                           products_on, sample_guard, scope_for,
                           severity_from_ratio, severity_from_sample, visible_prices, jsonld_nodes,
                           attribute_phrase, example_attributes, site_vocabulary,
                           structured_attribute_presence, visible_attribute_presence,
                           shows_client_rendering_signals, product_pages_where,
                           semantic_context, site_template_strings)
from aiva import semantics                            # noqa: E402
from aiva.extract import find_nodes, node_types, product_subjects, prop, text_of   # noqa: E402
from aiva import examples                             # noqa: E402
from aiva.findings import Finding                     # noqa: E402

SKILL = "machine-readability-audit"
PILLAR = "machine_readability"



# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def rule_no_structured_data(bundle: dict) -> Optional[Finding]:
    pages = ev.pages(bundle)
    if not sample_guard(pages, 2):
        return None
    with_jsonld = [p for p in pages if p.get("jsonld_blocks")]
    with_microdata = [p for p in pages if p.get("microdata")]
    if with_jsonld or with_microdata:
        return None
    # The *finding* applies to any site: no structured data anywhere is a real
    # gap wherever it occurs. The *recommendation* must not be. Telling a
    # documentation or brochure site to add "Product + Offer on every product
    # page" describes a catalogue it does not have, so the steps and the
    # worked example follow the site type the crawl actually observed.
    commerce = commerce_evidence(bundle)
    vocab = site_vocabulary(bundle)
    context = semantic_context(bundle)
    website_step = ("Home page: Organization, plus WebSite with a SearchAction pointing at "
                    "the site's own search endpoint." if context.get("has_site_search")
                    else "Home page: Organization (WebSite is optional; add a SearchAction "
                         "only once a search endpoint exists).")
    if commerce["is_commerce"]:
        physical = bool(context.get("sells_physical_goods"))
        summary = ("Add schema.org JSON-LD, starting with Organization on the home page "
                   "and Product + Offer on every product page.")
        steps = ["Add one JSON-LD block per page in the server-rendered <head>.",
                 website_step,
                 "Product pages: Product with brand, category, offers (price, priceCurrency"
                 + (", availability" if physical else "") + ")"
                 + (", sku/gtin" if physical else "") + ", aggregateRating when you have one.",
                 "Category pages: ItemList or CollectionPage listing the products."]
        if physical:
            steps.append("Policy pages: keep the numbers in text and reference them from "
                         "hasMerchantReturnPolicy / shippingDetails on the Offer.")
        steps.append("Validate every template once with a structured-data testing tool.")
        example = examples.product_jsonld(vocab, context)
        verification = ("curl -s <product url> | grep -c 'application/ld+json' returns >= 1 "
                        "and the JSON parses.")
    else:
        summary = ("Add schema.org JSON-LD, starting with Organization on the home page "
                   "and a page-level type on every content template.")
        steps = ["Add one JSON-LD block per page in the server-rendered <head>.",
                 website_step,
                 "Choose the schema.org type that matches each template - Article or "
                 "TechArticle for documentation and posts, FAQPage for question pages, "
                 "AboutPage, ContactPage, WebPage otherwise.",
                 "Reference the same Organization by @id from every page so the whole "
                 "site resolves to one entity.",
                 "Validate every template once with a structured-data testing tool."]
        example = examples.organization_jsonld(vocab, full=False)
        verification = ("curl -s <any page url> | grep -c 'application/ld+json' returns >= 1 "
                        "and the JSON parses.")

    return finding(
        "MR-NO-STRUCTURED-DATA",
        "The site publishes no structured data at all",
        # "No structured data anywhere" is a claim about the whole site, and a
        # two-page sample cannot support it at `critical`. The ceiling scales
        # the label with the evidence behind it.
        step_down(cap_severity("critical", len(pages)), coverage_caveat(bundle)), PILLAR,
        evidence=f"0 of {len(pages)} sampled pages contain JSON-LD, microdata or RDFa."
                 + coverage_caveat(bundle)
                 + (f" Commerce evidence was observed ({'; '.join(commerce['signals'])}), "
                    "so the recommendation covers Product and Offer markup."
                    if commerce["is_commerce"] else
                    " No product page, category page, commerce markup or cart affordance "
                    "was observed, so the recommendation covers site and page identity "
                    "rather than catalogue markup."),
        interpretation="Structured data is the one channel where a fact is stated with a "
                       "declared type rather than inferred from surrounding prose. Without it "
                       "every fact the site states has to be recovered by interpreting "
                       "sentences, and that recovery step is where a value gets misread or "
                       "the page gets passed over for one that states the same fact "
                       "unambiguously.",
        items=page_items(pages, "no JSON-LD, microdata or RDFa found on {url}", limit=5),
        action=action(
            summary,
            priority="critical", effort="medium", impact="high",
            mechanism="Structured data is the only channel where a fact is stated unambiguously "
                      "rather than inferred. A typed value is read directly; the same fact in a "
                      "sentence has to be parsed out first, and that parse differs by phrasing "
                      "and by language.",
            steps=steps,
            example=example,
            verification=verification),
        urls=[label(p) for p in pages[:10]], confidence=0.97,
        metrics={"scope": "site", "sampled": len(pages),
                 "site_type": "commerce" if commerce["is_commerce"] else "non-commerce",
                 "commerce_signals": commerce["signals"]},
        tags=["structured-data", "blocking"])


def _declares_its_item(page: dict) -> bool:
    """Does the page declare the thing it is about, in any product-kind type?

    ``Product`` is one spelling. A software page declares
    ``SoftwareApplication``, a service page ``Service``, a book ``Book`` -
    each is the schema.org type for what that page sells, and asking such a
    page why it has no ``Product`` node would be a category error.
    """
    if products_on(page) or product_subjects(page):
        return True
    if find_nodes(jsonld_nodes(page), "Service", "Book", "SoftwareApplication",
                  "WebApplication", "MobileApplication", "Vehicle", "Course", "Event"):
        return True
    return any(kind in (item.get("itemtype") or "").lower()
               for item in page.get("microdata", []) or []
               for kind in ("product", "softwareapplication", "service", "book"))


def rule_product_schema_missing(bundle: dict) -> Optional[Finding]:
    products = ev.product_pages(bundle)
    if not sample_guard(products, 1):
        return None
    missing = [p for p in products if not _declares_its_item(p)]
    if not missing:
        return None
    context = semantic_context(bundle)
    sold = [p for p in missing if semantics.is_price_applicable(p, context)]
    physical = bool(context.get("sells_physical_goods"))
    ratio = len(missing) / len(products)
    kind_word = ("Product" if physical or not (context.get("sells_software")
                                                or context.get("offers_services"))
                 else "product-kind (Product, SoftwareApplication, Service)")
    facts = "name, price" + (", availability" if physical else "") + \
        (" and identifiers" if physical else " and category")
    return finding(
        "MR-PRODUCT-SCHEMA-MISSING",
        "Product pages carry no Product structured data",
        severity_from_sample(ratio, len(products), critical=0.95, high=0.5, medium=0.2), PILLAR,
        evidence=f"{len(missing)} of {len(products)} identified product page(s) contain no "
                 f"schema.org {kind_word} node in JSON-LD or microdata, so {facts} are not "
                 f"machine-addressable on those pages."
                 + (f" {len(missing) - len(sold)} of them describe the item without offering "
                    f"it for sale, so an Offer is not expected of those."
                    if len(sold) < len(missing) else ""),
        items=page_items(missing, "no Product node in the structured data on {url}", limit=6),
        action=action("Emit a complete Product + Offer JSON-LD block on every product page."
                      if sold else
                      "Emit a Product JSON-LD block on every product page.",
                      priority="critical" if ratio > 0.8 else "high",
                      effort="medium", impact="high",
                      mechanism="A Product node (or the schema.org type for what the page sells) "
                                "is the explicit, typed statement of what the page is about; "
                                "without it the same facts are available only as prose to be "
                                "interpreted.",
                      steps=["Generate the block from the same data the page renders, in the "
                             "same request, so the two can never drift.",
                             "Required minimum: name, image, description, sku, brand"
                             + (", offers {price, priceCurrency"
                                + (", availability" if physical else "") + ", url}"
                                if sold else "") + ".",
                             "Add category" + (" and additionalProperty for the specs."
                                               if physical else "."),
                             "Keep it in the server-rendered HTML, not injected by a tag manager."],
                      example=examples.product_jsonld(site_vocabulary(bundle), context),
                      verification="curl -s <product url> | python -c \"import sys,re,json; "
                                   "print('Product' in sys.stdin.read())\""),
        urls=[label(p) for p in missing],
        confidence=confidence_for(len(missing), len(products)),
        metrics={"scope": scope_for(len(missing), len(products)),
                 "affected": len(missing), "sampled": len(products),
                 "sample_unit": "sampled product page(s)"},
        tags=["structured-data", "product"])


def rule_invalid_jsonld(bundle: dict) -> Optional[Finding]:
    pages = ev.pages(bundle)
    broken: List[Tuple[dict, dict]] = []
    for page in pages:
        for block in page.get("jsonld_blocks", []) or []:
            if not block.get("parse_ok"):
                broken.append((page, block))
    if not broken:
        return None
    return finding(
        "MR-JSONLD-INVALID",
        "Structured-data blocks fail to parse and are discarded silently",
        "high", PILLAR,
        evidence=f"{len(broken)} JSON-LD block(s) across {len({label(p) for p, _ in broken})} "
                 f"page(s) are not valid JSON (e.g. {broken[0][1].get('error')}). A parser "
                 "discards the entire block, so the page behaves as if it had no markup at all.",
        items=[observed(f"JSON-LD block #{block.get('index')} failed: {block.get('error')}",
                        url=label(page), locator=f"script[type=application/ld+json] "
                                                 f"#{block.get('index')}")
               for page, block in broken[:6]],
        action=action("Fix the JSON syntax and validate structured data in CI.",
                      priority="high", effort="low", impact="high",
                      mechanism="Structured data fails closed: one unescaped quote in a product "
                                "description invalidates the whole block, and nothing in the UI "
                                "reveals it. The markup looks present in view-source and is worth "
                                "nothing.",
                      steps=["JSON-escape all interpolated values - serialise with a real JSON "
                             "library instead of string-concatenating a template.",
                             "Never emit trailing commas, comments or unquoted keys.",
                             "Add a build step that JSON.parse()s every ld+json block in the "
                             "rendered output and fails the build on error."],
                      verification="Extract every ld+json block from a rendered page and json.loads "
                                   "each one without error."),
        urls=util.dedupe([label(p) for p, _ in broken]), confidence=0.99,
        metrics={"scope": "template", "blocks": len(broken)},
        tags=["structured-data", "validity"])


def rule_jsonld_context(bundle: dict) -> Optional[Finding]:
    pages = ev.pages(bundle)
    bad: List[Tuple[dict, dict]] = []
    for page in pages:
        for block in page.get("jsonld_blocks", []) or []:
            if not block.get("parse_ok"):
                continue
            context = (block.get("context") or "").lower()
            if "schema.org" not in context:
                bad.append((page, block))
    if not bad:
        return None
    return finding(
        "MR-JSONLD-CONTEXT",
        "JSON-LD blocks do not declare the schema.org context",
        "medium", PILLAR,
        evidence=f"{len(bad)} parseable JSON-LD block(s) have a missing or non-schema.org "
                 "@context, so their @type values resolve to nothing and consumers ignore them.",
        items=[observed(f"block #{block.get('index')} has @context="
                        f"{block.get('context') or 'missing'}",
                        url=label(page), locator=f"ld+json #{block.get('index')}")
               for page, block in bad[:5]],
        action=action('Set "@context": "https://schema.org" on every JSON-LD block.',
                      priority="medium", effort="low", impact="medium",
                      mechanism="Without the context, `\"@type\": \"Product\"` is an undefined "
                                "term rather than schema.org's Product, so the block carries no "
                                "meaning to a consumer.",
                      steps=['Use the https:// form of the context URL.',
                             "If you use @graph, put @context once at the top level."],
                      verification="Every ld+json block contains schema.org in its @context."),
        urls=util.dedupe([label(p) for p, _ in bad]), confidence=0.9,
        metrics={"scope": "template", "blocks": len(bad)}, tags=["structured-data"])


def _offer_gaps(products: List[dict], context: dict) -> Dict[str, List[Tuple[dict, dict]]]:
    """Offer fields missing on pages that owe them.

    A page that describes an item without selling it owes no Offer at all. A
    stock value is asked only of goods stock applies to. A price is not asked
    of a page that says, in so many words, that pricing is on request.
    """
    gaps: Dict[str, List[Tuple[dict, dict]]] = {
        "no_offer": [], "no_price": [], "no_currency": [], "no_availability": []}
    for page in products:
        wants_stock = bool(semantics.is_stock_applicable(page, context))
        quotes = _quotes_on_request(page)
        for node in products_on(page):
            if "productgroup" in {t.lower() for t in node_types(node)} and prop(node, "hasVariant"):
                continue  # variants carry the offers
            offers = offers_of(node)
            if not offers:
                gaps["no_offer"].append((page, node))
                continue
            for offer in offers:
                if not offer_price(offer) and not quotes:
                    gaps["no_price"].append((page, offer))
                if not offer_currency(offer) and (offer_price(offer) or not quotes):
                    gaps["no_currency"].append((page, offer))
                if wants_stock and not offer_availability(offer):
                    gaps["no_availability"].append((page, offer))
    return gaps


def rule_offer_completeness(bundle: dict) -> List[Finding]:
    # An Offer is owed by a page that offers the item for sale. A page that
    # describes an item without selling it - a manufacturer's catalogue, a
    # spec page that points at retailers - is set aside and named.
    parts = product_pages_where(bundle, semantics.is_price_applicable)
    products = [p for p in parts.pages if products_on(p)]
    if not sample_guard(products, 1):
        return []
    context = semantic_context(bundle)
    gaps = _offer_gaps(products, context)
    out: List[Finding] = []
    total = len(products)
    physical = any(semantics.is_stock_applicable(p, context) for p in products)
    fields = "price, priceCurrency" + (", availability" if physical else "") + " and url"

    if gaps["no_offer"]:
        affected = util.dedupe([label(p) for p, _ in gaps["no_offer"]])
        out.append(finding(
            "MR-OFFER-MISSING",
            "Product markup declares no Offer, so the price is not machine-readable",
            "high", PILLAR,
            evidence=f"{len(affected)} of {total} product page(s) offered for sale have a "
                     "Product node with no `offers` property. The page may show a price to a "
                     "human, but there is no typed price a machine can quote." + parts.note(),
            items=[absent(f"Product node '{util.truncate(text_of(prop(n, 'name')) or '?', 60)}' "
                          f"has no offers property", url=label(p), locator="JSON-LD Product")
                   for p, n in gaps["no_offer"][:5]],
            action=action(f"Attach an Offer with {fields}.",
                          priority="high", effort="low", impact="high",
                          mechanism="An Offer is where the price is stated as a typed value with "
                                    "a declared meaning; without it the same number exists only "
                                    "as prose to be interpreted.",
                          steps=["Add offers to every Product node.",
                                 "price as a plain number string, no currency symbol or "
                                 "thousands separator.",
                                 "priceCurrency as an ISO-4217 code (INR, USD)."]
                                + (["availability as a schema.org URL "
                                    "(https://schema.org/InStock)."] if physical else []),
                          example=examples.product_jsonld(site_vocabulary(bundle), context),
                          verification="Every Product node in the rendered HTML has an offers "
                                       f"object with {fields}."),
            urls=affected, confidence=confidence_for(len(affected), total),
            metrics={"scope": scope_for(len(affected), total), "affected": len(affected),
                     "sampled": total, "sample_unit": "sampled product page(s) offered for sale",
                     "not_assessed": parts.not_assessed},
            tags=["structured-data", "offer"]))

    detail_gaps = [(key, gaps[key]) for key in ("no_price", "no_currency", "no_availability")
                   if gaps[key]]
    if detail_gaps:
        names = {"no_price": "price", "no_currency": "priceCurrency",
                 "no_availability": "availability"}
        missing_fields = [names[key] for key, _ in detail_gaps]
        pairs = [pair for _, group in detail_gaps for pair in group]
        affected = util.dedupe([label(p) for p, _ in pairs])
        out.append(finding(
            "MR-OFFER-INCOMPLETE",
            "Offer markup is missing fields a buying question is answered from",
            "high" if "availability" in missing_fields or "price" in missing_fields else "medium",
            PILLAR,
            evidence=f"Offers on {len(affected)} of {total} product page(s) offered for sale "
                     f"omit {', '.join(missing_fields)}. Those fields are where 'how much', "
                     "'in what currency'" + (" and 'can I buy it now'" if "availability" in
                                             missing_fields else "")
                     + " are stated as typed values."
                     + (" Availability was expected only of the pages selling physical goods."
                        if "availability" in missing_fields else "") + parts.note(),
            items=[absent(f"Offer on this page has no {names[key]}", url=label(pair[0]),
                          locator="JSON-LD Offer")
                   for key, group in detail_gaps for pair in group[:2]][:6],
            action=action(f"Complete every Offer: {fields}.",
                          priority="high", effort="low", impact="high",
                          mechanism="A partial Offer looks valid to a validator, so the field "
                                    "that is missing is the one nobody notices; each field is "
                                    "the typed statement of one fact a buyer asks about.",
                          steps=(["Emit availability on every offer, including out-of-stock "
                                  "states (https://schema.org/OutOfStock) - an absent value "
                                  "states nothing, not 'available'."] if physical else [])
                                + ["Emit priceCurrency even for a single-currency store.",
                                   "Add priceValidUntil so a cached price has an expiry.",
                                   "For price ranges use AggregateOffer with lowPrice/highPrice."],
                          verification="Structured-data testing tool reports no missing "
                                       "recommended fields on Offer."),
            urls=affected, confidence=confidence_for(len(affected), total),
            metrics={"scope": scope_for(len(affected), total), "missing_fields": missing_fields,
                     "affected": len(affected), "sampled": total,
                     "sample_unit": "sampled product page(s) offered for sale",
                     "not_assessed": parts.not_assessed},
            tags=["structured-data", "offer"]))
    return out


def rule_identifiers(bundle: dict) -> Optional[Finding]:
    # A GTIN or MPN is a physical-goods identifier. A download, a plan, a
    # service and an information page are set aside and named.
    parts = product_pages_where(bundle, semantics.is_identifier_applicable)
    products = [p for p in parts.pages if products_on(p)]
    if not sample_guard(products, 2):
        return None
    without = []
    for page in products:
        found = {}
        for node in products_on(page):
            found.update(product_identifiers(node))
        if not found:
            without.append(page)
    if not without:
        return None
    ratio = len(without) / len(products)
    if ratio < 0.3:
        return None
    return finding(
        "MR-IDENTIFIERS-MISSING",
        "Products carry no stable identifier, so listings elsewhere cannot be matched to them",
        severity_from_sample(ratio, len(products), critical=1.01, high=0.7, medium=0.3), PILLAR,
        evidence=f"{len(without)} of {len(products)} physical-goods product page(s) declare no "
                 "sku, gtin, mpn or productID in their markup." + parts.note(),
        interpretation="A shared identifier is how the same product is recognised as the same "
                       "product across sources. Without one, a listing of this product elsewhere "
                       "and this page have no field in common to match on, so agreement between "
                       "them cannot be established even when they agree.",
        items=page_items(without, "no sku/gtin/mpn/productID in the Product markup on {url}",
                         limit=5),
        action=action("Publish a stable sku plus a global identifier (GTIN or MPN) on every product.",
                      priority="high", effort="low", impact="high",
                      mechanism="Corroboration works by matching entities across sources. Without "
                                "a shared identifier there is no field on which your page and "
                                "a retailer's listing are the same product, so the two never "
                                "reinforce each other and neither becomes the trusted answer.",
                      steps=["Emit sku (your internal code) on every Product.",
                             "Emit gtin13/gtin12/gtin8 where a barcode exists, mpn otherwise.",
                             "Use the same identifier in your merchant feeds and marketplace "
                             "listings so they resolve to one entity.",
                             "Keep the identifier stable across price changes and re-designs."],
                      verification="Search a GTIN from your catalogue; your own page and your "
                                   "retail partners' listings should both surface.",
                      verification_type="external_validation"),
        urls=[label(p) for p in without],
        confidence=confidence_for(len(without), len(products)),
        metrics={"scope": scope_for(len(without), len(products)),
                 "affected": len(without), "sampled": len(products),
                 "sample_unit": "sampled physical-goods product page(s)",
                 "not_assessed": parts.not_assessed,
                 "kind_inferred_from_site": parts.inferred},
        tags=["identifiers", "corroboration"])


def rule_attributes_thin(bundle: dict) -> Optional[Finding]:
    """Typed attributes, measured separately from attributes stated in copy.

    The distinction is the whole point of the rule. A page stating an
    attribute in its visible copy ("Fat content: 22%") has published it; what
    it has not done is expose it as a ``PropertyValue`` that can be read without
    parsing a sentence. Reporting that page as having "almost no attributes"
    is false, and a site owner reading it can see with their own eyes that it
    is false, which costs the whole report its credibility. So the finding
    reports *format*, and says what was found and in which form.
    """
    # Typed physical attributes are an expectation of physical goods. A
    # software product's typed attributes are operatingSystem and
    # applicationCategory, not colour and material, and asking it for the
    # latter is a category error; it and every other kind are set aside.
    parts = product_pages_where(bundle, semantics.is_physical_specs_applicable)
    products = [p for p in parts.pages if products_on(p)]
    if not sample_guard(products, 2):
        return None
    thin = []
    for page in products:
        structured = structured_attribute_presence(page)
        if structured["count"] < 2 and not page_has_spec_block(page):
            thin.append((page, structured, visible_attribute_presence(page)))
    if not thin or len(thin) / len(products) < 0.4:
        return None
    ratio = len(thin) / len(products)
    # "the attributes these pages already publish" has to mean these pages: the
    # physical-goods pages this finding is about, not whichever product page the
    # crawl read first.
    vocab = site_vocabulary(bundle, pages=products)

    with_visible = [(p, s, v) for p, s, v in thin if v["count"]]
    if with_visible:
        sample_names = []
        for _, _, vis in with_visible:
            sample_names.extend(vis["names"])
        shown = ", ".join(f"'{n}'" for n in dict.fromkeys(sample_names))
        formats = sorted({src for _, _, v in with_visible for src in v["sources"]})
        contrast = (f" {len(with_visible)} of those page(s) do state attributes in visible "
                    f"content ({'; '.join(formats)}), including {shown}, with no corresponding "
                    f"Product.additionalProperty or typed schema.org property.")
        title = ("Product attributes are published in visible content but not as typed "
                 "schema.org properties")
    else:
        contrast = (" No attribute label/value pairs were detected in their visible content "
                    "either.")
        title = "Product pages expose no typed schema.org attributes"

    return finding(
        "MR-ATTRIBUTES-THIN",
        title,
        severity_from_sample(ratio, len(products), critical=1.01, high=0.75, medium=0.4), PILLAR,
        evidence=f"{len(thin)} of {len(products)} physical-goods product page(s) declare fewer "
                 f"than two typed schema.org attributes (color, size, material, "
                 f"additionalProperty...) and no specification table in the HTML.{contrast}"
                 + parts.note(),
        interpretation="A typed attribute is addressable: it has a name, a value and often a "
                       "unit, in a fixed place, identical in shape on every product. The same "
                       "fact written into a sentence has to be found and parsed first, and the "
                       "parse differs per page and per language. A comparison across "
                       "products can be assembled from the addressable form without "
                       "interpreting each page; whether any system does so is not something "
                       "this audit measures.",
        items=[observed(
            "{} typed schema.org attribute(s) and no specification table on {}; "
            "{} attribute label/value pair(s) present in visible content{}".format(
                structured["count"], label(page), visible["count"],
                " (" + ", ".join(visible["names"][:4]) + ")" if visible["names"] else ""),
            url=label(page), locator="Product JSON-LD and page body")
            for page, structured, visible in thin[:5]],
        action=action("Publish the attributes this catalogue already states as typed properties.",
                      priority="high", effort="medium", impact="high",
                      mechanism="A PropertyValue with a name, a value and a unit is comparable "
                                "across products without interpretation. The same fact in prose "
                                "has to be located and parsed first, and that step is where it "
                                "is dropped.",
                      steps=[f"Add an additionalProperty PropertyValue entry for each attribute "
                             f"these pages already publish: {attribute_phrase(vocab, 4)}.",
                             "Use the first-class properties where schema.org has one: color, "
                             "size, material, weight, width, height.",
                             "Keep the typed value and the visible value identical - the "
                             "markup must describe what the page displays.",
                             "State the negative facts as well as the positive ones; an "
                             "attribute that is absent from the markup is not readable as "
                             "'no', only as 'unknown'."],
                      example=examples.additional_property(vocab),
                      verification="The Product JSON-LD on a product page contains an "
                                   "additionalProperty entry for each attribute the page "
                                   "displays, with matching values.",
                      verification_type="self_verifiable"),
        urls=[label(p) for p, _, _ in thin],
        confidence=confidence_for(len(thin), len(products)),
        metrics={"scope": scope_for(len(thin), len(products)),
                 "affected": len(thin), "sampled": len(products),
                 "structured_attribute_presence": [s["count"] for _, s, _ in thin][:10],
                 "visible_attribute_presence": [v["count"] for _, _, v in thin][:10],
                 "observed_visible_attributes": example_attributes(vocab, 6),
                 "sample_unit": "sampled physical-goods product page(s)",
                 "not_assessed": parts.not_assessed,
                 "kind_inferred_from_site": parts.inferred},
        tags=["attributes", "comparison", "structure"])


def rule_ratings_and_reviews(bundle: dict) -> Optional[Finding]:
    products = ev.product_pages(bundle)
    if not sample_guard(products, 1):
        return None
    visible_reviews = [p for p in products if p.get("mentions", {}).get("reviews")]
    if not visible_reviews:
        return None
    untyped = [p for p in visible_reviews
               if not find_nodes(jsonld_nodes(p), "AggregateRating", "Review", "Rating")]
    # Pages whose review content plausibly arrives after JavaScript are a
    # different problem with a different owner, and engagement-audit reports
    # them as EG-REVIEWS-CLIENT-RENDERED. Splitting the population here keeps
    # this rule's title true - it really is about content the fetch *can* see -
    # and stops one observation being reported, and scored, twice.
    deferred = [p for p in untyped if shows_client_rendering_signals(p)]
    unmarked = [p for p in untyped if p not in deferred]
    if not unmarked:
        return None
    return finding(
        "MR-REVIEW-MARKUP-MISSING",
        "Review and rating content is visible but not marked up",
        "medium", PILLAR,
        evidence=f"{len(unmarked)} of {len(visible_reviews)} product page(s) reference reviews "
                 "or ratings in the fetched text but carry no AggregateRating, Review or Rating "
                 "node in their markup."
                 + (f" A further {len(deferred)} page(s) also lack the markup but show "
                    "client-rendering signals, and are reported separately as "
                    "EG-REVIEWS-CLIENT-RENDERED rather than counted here."
                    if deferred else ""),
        interpretation="The rating exists on the page as text a reader can see, but not as a "
                       "typed value with a declared meaning. A reader of the response can "
                       "recover the score and the count only by parsing prose, since there is "
                       "no ratingValue or reviewCount to read directly.",
        items=[observed("page text references reviews/ratings but no AggregateRating or Review "
                        "node exists in the markup", url=label(p), locator="JSON-LD")
               for p in unmarked[:5]],
        action=action("Mark up aggregate ratings and individual reviews with schema.org types.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="'Is it any good?' is answered from ratings. A star widget "
                                "rendered by a review platform's JavaScript is absent from the "
                                "response a fetch without JavaScript receives; AggregateRating "
                                "in the server HTML is a typed number any reader of the "
                                "response can quote.",
                      steps=["Emit aggregateRating {ratingValue, reviewCount, bestRating} on the "
                             "Product node.",
                             "Emit a handful of Review nodes with author, datePublished and "
                             "reviewBody in the server-rendered HTML.",
                             "If reviews come from a third-party widget, ask the vendor for the "
                             "server-side/SEO rendering option, or render the aggregate yourself "
                             "from their API at build time.",
                             "Only mark up ratings that are genuinely displayed on the page."],
                      verification="curl -s <product url> | grep -c aggregateRating returns >= 1."),
        urls=[label(p) for p in unmarked],
        confidence=confidence_for(len(unmarked), len(visible_reviews), base=0.85),
        metrics={"scope": scope_for(len(unmarked), len(visible_reviews)),
                 "affected": len(unmarked), "sampled": len(visible_reviews),
                 "sample_unit": "sampled product page(s) referencing reviews",
                 "excluded_as_client_rendered": len(deferred),
                 "related_rule": "EG-REVIEWS-CLIENT-RENDERED"},
        tags=["reviews", "structured-data"])


def rule_breadcrumb_markup(bundle: dict) -> Optional[Finding]:
    products = ev.product_pages(bundle)
    categories = ev.category_pages(bundle)
    pages = products + categories
    if not sample_guard(pages, 2):
        return None
    # Name the population exactly as it was assembled. "product/category
    # page(s)" on a bundle holding only listings claims a product page was
    # sampled, which is the ratio describing a set that was never read.
    unit = " and ".join(part for part in (
        f"{len(products)} product page(s)" if products else "",
        f"{len(categories)} listing page(s)" if categories else "") if part)
    without = [p for p in pages if not find_nodes(jsonld_nodes(p), "BreadcrumbList")
               and not p.get("breadcrumbs", {}).get("present")]
    if not without or len(without) / len(pages) < 0.5:
        return None
    return finding(
        "MR-BREADCRUMB-MISSING",
        "Pages do not declare where they sit in the site's hierarchy",
        "medium", PILLAR,
        evidence=f"{len(without)} of {len(pages)} sampled page(s) ({unit}) have neither "
                 "BreadcrumbList markup nor a breadcrumb navigation element, so the page's "
                 "position in the section hierarchy is undeclared.",
        items=page_items(without, "no BreadcrumbList markup and no breadcrumb nav on {url}",
                         limit=5),
        action=action("Add BreadcrumbList JSON-LD plus a visible breadcrumb trail.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="A breadcrumb states explicitly which section a page belongs "
                                "to, so the relationship does not have to be inferred from the "
                                "URL or the navigation.",
                      steps=["Emit BreadcrumbList with ListItem position/name/item for each level.",
                             "Render the same trail visibly as <a href> links.",
                             "Keep the naming identical to your category page titles."],
                      example=examples.breadcrumb_jsonld(site_vocabulary(bundle)),
                      verification="Structured-data test shows a BreadcrumbList on product pages."),
        urls=[label(p) for p in without],
        confidence=confidence_for(len(without), len(pages)),
        # Every ratio in this report names the population it was computed over,
        # so "8 of 8" is never read as "every page on the site". This rule was
        # the one place the unit was left implicit.
        metrics={"scope": scope_for(len(without), len(pages)),
                 "affected": len(without), "sampled": len(pages),
                 # The unit names no single page type, because the population
                 # is two of them: naming either one would claim every cited
                 # URL is that type. The composition goes beside it, and in the
                 # evidence sentence, where it can be read without being
                 # mistaken for a claim about each URL.
                 "sample_unit": "sampled page(s) where a breadcrumb applies",
                 "population": unit},
        tags=["structured-data", "taxonomy"])


def rule_site_level_schema(bundle: dict) -> Optional[Finding]:
    home = ev.home_page(bundle)
    if not home or home.get("fetch_failed"):
        return None
    nodes = jsonld_nodes(home)
    has_org = bool(find_nodes(nodes, "Organization", "Corporation", "OnlineStore",
                              "LocalBusiness", "Store", "Brand"))
    has_website = bool(find_nodes(nodes, "WebSite"))
    if has_org and has_website:
        return None
    # An Organization node is the site's typed statement of who it is; its
    # absence is a real gap on any site, and a `medium` one - it is metadata,
    # and metadata that is absent is not a blocker. WebSite is optional: it
    # matters where a SearchAction has an endpoint to describe, and is
    # reported alone only as an `info` note.
    context = semantic_context(bundle)
    missing = []
    if not has_org:
        missing.append("Organization/Brand")
    if not has_website:
        missing.append("WebSite")
    org_fields = [f for f in ("name", "url", "description", "address", "contactPoint", "sameAs")
                  if semantics.organization_field_expectation(f, context)
                  in ("required_when_applicable", "recommended")]
    website_step = ("Add WebSite with url, name and a potentialAction SearchAction pointing "
                    "at your site-search URL template."
                    if context.get("has_site_search") else
                    "WebSite is optional; add it (with a SearchAction) once the site has a "
                    "search endpoint to describe.")
    return finding(
        "MR-SITE-SCHEMA-MISSING",
        "The home page does not declare the site's own identity in structured data"
        if not has_org else "The home page declares no WebSite node",
        "medium" if not has_org else "info", PILLAR,
        evidence=f"The home page ({label(home)}) has no {' and no '.join(missing)} node in its "
                 f"JSON-LD (types found: {', '.join(home.get('jsonld_types', [])) or 'none'})."
                 + ("" if not has_org else
                    " WebSite is optional metadata; this is an observation, not a defect."),
        interpretation="The home page does not expose Organization/Brand or WebSite identity "
                       "through the structured-data structures checked by this rule. That "
                       "reduces the amount of explicit machine-readable identity information "
                       "available to automated systems, which then have to infer the operator "
                       "from page copy and the domain. This audit observes the absence of the "
                       "markup; it does not test, and does not claim, that any system failed "
                       "to identify the brand.",
        items=[absent(f"no {name} node in the home page structured data",
                      url=label(home), locator="JSON-LD") for name in missing],
        action=action("Declare Organization JSON-LD on the home page." if not has_org else
                      "Optionally declare WebSite JSON-LD on the home page.",
                      priority="medium" if not has_org else "low", effort="low",
                      impact="medium" if not has_org else "low",
                      mechanism="An Organization node is a typed statement of who the site "
                                "belongs to, and WebSite ties the domain to that entity. "
                                "Publishing them adds explicit machine-readable identity "
                                "information for entity resolution to work from, in place of "
                                "inferring the operator from page copy and the domain name.",
                      steps=[f"Add Organization with {', '.join(org_fields)}"
                             + ("; legalName, logo and foundingDate are optional." if org_fields
                                else "."),
                             website_step,
                             "Use one @id (e.g. https://example.com/#organization) and reference "
                             "it from every page that names the organisation, so the whole site "
                             "resolves to one entity."],
                      example=examples.organization_jsonld(site_vocabulary(bundle), full=False),
                      verification="curl -s https://<host>/ | grep -c '\"Organization\"' >= 1."),
        urls=[label(home)], confidence=0.95,
        metrics={"scope": "site", "missing": missing,
                 "recommended_organization_fields": org_fields},
        tags=["structured-data", "entity"])


def rule_metadata_hygiene(bundle: dict) -> List[Finding]:
    pages = [p for p in ev.pages(bundle) if not p.get("fetch_failed")]
    if not sample_guard(pages, 3):
        return []
    out: List[Finding] = []

    no_title = [p for p in pages if not (p.get("title") or "").strip()]
    no_description = [p for p in pages if not (p.get("meta_description") or "").strip()]
    if no_title:
        out.append(finding(
            "MR-TITLE-MISSING", "Pages ship without a <title>", "medium", PILLAR,
            evidence=f"{len(no_title)} of {len(pages)} sampled page(s) have an empty or absent "
                     "<title> element - the page's own short label, and the one every reader "
                     "of the document looks for first.",
            items=page_items(no_title, "empty or missing <title> on {url}", limit=5),
            action=action("Give every page a unique, descriptive <title>.",
                          priority="medium", effort="low", impact="medium",
                          mechanism="The title is the page's own name in the one place every "
                                    "reader of the document looks for it; an untitled page "
                                    "offers nothing to label it by.",
                          steps=["Pattern: '<what this page is about> | <Site name>'.",
                                 "Keep it under ~60 visible characters and never duplicate it."],
                          verification="Every sampled URL returns a non-empty <title>."),
            urls=[label(p) for p in no_title],
            confidence=confidence_for(len(no_title), len(pages)),
            metrics={"scope": scope_for(len(no_title), len(pages)), "affected": len(no_title)},
            tags=["metadata"]))

    if no_description and len(no_description) / len(pages) >= 0.5:
        out.append(finding(
            "MR-META-DESCRIPTION-MISSING",
            "Most pages have no meta description", "low", PILLAR,
            evidence=f"{len(no_description)} of {len(pages)} sampled page(s) have no meta "
                     "description, so the page offers no summary of its own in the place a "
                     "summary is conventionally read from.",
            items=page_items(no_description, "no meta description on {url}", limit=5),
            action=action("Write a one-sentence meta description per template.",
                          priority="low", effort="low", impact="low",
                          mechanism="It is the page's own summary, in a fixed place with a "
                                    "declared meaning. Without it, any summary has to be "
                                    "assembled from the body, which may begin with navigation.",
                          steps=["Generate it from the page's own first sentence rather than "
                                 "leaving it blank.",
                                 "State the concrete fact the page exists for, not marketing "
                                 "copy."],
                          verification="Every sampled URL returns a meta description of 100-160 "
                                       "characters."),
            urls=[label(p) for p in no_description],
            confidence=confidence_for(len(no_description), len(pages), base=0.8),
            metrics={"scope": scope_for(len(no_description), len(pages))},
            tags=["metadata"]))

    # Neither "more than one <h1>" nor "no <h1>" is a defect by itself: HTML
    # sectioning permits an <h1> per article, and a template that spent its
    # <h1> on the logo may still name the page in an <h2>. What is reported
    # is the page whose top-level headings name nothing - a site name, a
    # section label, or no heading at all - and only as a `low` observation.
    template = site_template_strings(bundle)
    assessed = [(p, semantics.heading_assessment(p, template)) for p in pages]
    unnamed = [(p, verdict) for p, verdict in assessed if not verdict["identifies_subject"]]
    multi_h1 = sum(1 for p, v in assessed if v["h1_count"] > 1 and v["identifies_subject"])
    no_h1 = sum(1 for p, v in assessed if v["h1_count"] == 0 and v["identifies_subject"])
    if len(unnamed) >= max(2, len(pages) * 0.4):
        permitted = ""
        if multi_h1 or no_h1:
            permitted = (f" A further {multi_h1} page(s) carry more than one <h1> and "
                         f"{no_h1} carry none, but a top-level heading on each names the page; "
                         f"those are not counted.")
        out.append(finding(
            "MR-HEADING-STRUCTURE",
            "Top-level headings do not name the subject of the page",
            "low", PILLAR,
            evidence=f"On {len(unnamed)} of {len(pages)} sampled page(s) no top-level heading "
                     f"names what the page is about - the headings repeat the site name or a "
                     f"section label, or there is no heading at all.{permitted}",
            interpretation="A heading that names the page's subject is one explicit statement "
                           "of what the page is about; where none does, that has to be inferred "
                           "from the title, the URL or the body. Multiple <h1> elements and a "
                           "page led by an <h2> are permitted by HTML and are not what this "
                           "reports.",
            items=[observed(f"{verdict['why']} ({verdict['h1_count']} <h1> element(s))",
                            url=label(p), locator="headings")
                   for p, verdict in unnamed[:5]],
            action=action("Make the first top-level heading on each page name its subject.",
                          priority="low", effort="low", impact="low",
                          mechanism="A top-level heading that matches the page title states the "
                                    "subject in the document body as well as in the head, so "
                                    "the two agree on what the page is about.",
                          steps=["Give each content page a heading that names its subject "
                                 "(the item, the article, the section).",
                                 "Do not wrap the site logo in the only <h1>.",
                                 "Keep h2/h3 in order without skipping levels."],
                          verification="Each sampled URL has a top-level heading that matches "
                                       "its <title>."),
            urls=[label(p) for p, _ in unnamed],
            confidence=confidence_for(len(unnamed), len(pages)),
            metrics={"scope": "template", "affected": len(unnamed), "sampled": len(pages),
                     "permitted_multiple_h1": multi_h1, "permitted_no_h1": no_h1},
            tags=["semantic-html"]))
    return out


def _quotes_on_request(page: dict) -> bool:
    """Does this page say, in so many words, that pricing is on request?"""
    if page.get("language_supported") is False:
        # In a language the vocabulary does not cover we cannot read the
        # invitation, so we must not claim the price was hidden either.
        return True
    text = " ".join(filter(None, [page.get("text", ""),
                                  " ".join(page.get("h1_texts", []) or [])]))
    return lexicon.mentions("quote_request", text)


def rule_facts_locked_in_images(bundle: dict) -> Optional[Finding]:
    # The premise here is that the price is *not* in the text, so the usual
    # sale evidence cannot be demanded. What can be read is the opposite: a
    # page that points at retailers, or a service that is quoted rather than
    # priced, is not hiding a price and is set aside.
    parts = product_pages_where(bundle, semantics.is_hidden_price_check_applicable)
    products = parts.pages
    if not sample_guard(products, 1):
        return None

    # A catalogue where *no* page anywhere publishes a price, and pages invite
    # a quote instead, is a quote-on-request business - industrial, medical,
    # wholesale, made-to-order, regulated. Its pricing is a commercial decision,
    # not a fact locked inside an image, and calling it the site's top-priority
    # blocker is a confident wrong answer. The rule looks for the *inconsistent*
    # case instead: a site that prices its catalogue but not these pages.
    priced_anywhere = any(
        visible_prices(p) or any(offer_price(o) for node in products_on(p)
                                 for o in offers_of(node))
        for p in products)

    locked = []
    quote_based = 0
    for page in products:
        has_text_price = bool(visible_prices(page))
        has_markup_price = any(offer_price(offer) for node in products_on(page)
                               for offer in offers_of(node))
        image_count = (page.get("images", {}) or {}).get("total", 0)
        if has_text_price or has_markup_price or image_count < 1:
            continue
        if _quotes_on_request(page):
            quote_based += 1
            continue
        locked.append(page)
    if not locked:
        return None
    if not priced_anywhere and quote_based:
        # Mixed evidence pointing the same way: nothing is priced and the site
        # says why. Stay silent rather than guess against the site's own words.
        return None
    return finding(
        "MR-FACTS-NOT-IN-TEXT",
        "Core buying facts do not exist as text anywhere in the response",
        severity_from_sample(len(locked) / len(products), len(products),
                             critical=1.0, high=0.5, medium=0.0), PILLAR,
        evidence=f"{len(locked)} of {len(products)} product page(s) contain "
                 "no currency-formatted price in the visible text and no price in structured "
                 "data, while carrying "
                 f"{sum((p.get('images', {}) or {}).get('total', 0) for p in locked)} image(s)."
                 + parts.note(),
        interpretation="Three things produce this observation - the price is inside an image, "
                       "it is injected after load by script, or the page does not state it - "
                       "and the audit cannot tell them apart from a single fetch. What is "
                       "common to all three is that the number is not in the bytes a text "
                       "extractor receives, so a system reading the response has no price to "
                       "quote from this page.",
        items=[observed(f"no currency-formatted price in text and no Offer.price in markup; "
                        f"{(p.get('images', {}) or {}).get('total', 0)} images on the page, "
                        f"{(p.get('images', {}) or {}).get('missing_alt', 0)} without alt text",
                        url=label(p), locator="page text + JSON-LD") for p in locked[:5]],
        action=action("Put every buying-decision fact in the HTML as text, and mirror it in markup.",
                      priority="critical", effort="medium", impact="high",
                      mechanism="A fact that lives only inside an image carries no text for a "
                                "reader that does not run OCR, so a page that looks complete to a "
                                "person can carry no readable version of that fact in text at all.",
                      steps=["Render the price, the currency and the key facts a buyer asks "
                             "about as selectable text.",
                             "Never place price, offers or specifications inside a banner image.",
                             "Give every informative image a descriptive alt attribute as a "
                             "backstop.",
                             "Mirror the same values in Product/Offer JSON-LD."],
                      verification="curl -s <product url> | grep -F '<your price>' finds the "
                                   "price in the raw HTML."),
        urls=[label(p) for p in locked],
        confidence=confidence_for(len(locked), len(products), base=0.85),
        metrics={"scope": scope_for(len(locked), len(products)),
                 "affected": len(locked), "sampled": len(products),
                 "sample_unit": "sampled product page(s)",
                 "not_assessed": parts.not_assessed},
        tags=["non-text", "blocking"])


def rule_image_alt_coverage(bundle: dict) -> Optional[Finding]:
    pages = [p for p in ev.pages(bundle) if (p.get("images", {}) or {}).get("total", 0) >= 4]
    if not sample_guard(pages, 2):
        return None
    total = sum(p["images"]["total"] for p in pages)
    # `alt=""` is the correct, specified way to mark a decorative image: it
    # tells a screen reader to skip it. Counting it as a missing attribute
    # penalises sites that did the accessible thing, so only images with *no*
    # alt attribute at all are counted as defects. Empty ones are reported
    # alongside as context.
    missing = sum(p["images"]["missing_alt"] for p in pages)
    decorative = sum(p["images"]["empty_alt"] for p in pages)
    if total == 0 or missing / total < 0.5:
        return None
    return finding(
        "MR-IMAGE-ALT-COVERAGE",
        "Most images carry no alt attribute, so their content enters no text index",
        "medium", PILLAR,
        evidence=f"{missing} of {total} images across {len(pages)} sampled page(s) "
                 f"({util.pct(missing, total)}%) have no alt attribute at all."
                 + (f" A further {decorative} carry an explicit empty alt, which is the "
                    "correct marking for a decorative image and is not counted here."
                    if decorative else ""),
        items=[measured(f"{p['images']['missing_alt']} of "
                        f"{p['images']['total']} images with no alt attribute",
                        value=p["images"]["total"], url=label(p)) for p in pages[:5]],
        action=action("Write descriptive alt text for every informative image.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="Alt text is the only textual representation an image has, so "
                                "it is the only form in which whatever the image shows is "
                                "available to a reader of the text.",
                      steps=["Describe what the image shows, naming the thing pictured.",
                             "Leave alt=\"\" only for genuinely decorative images.",
                             "Never put the price in an image; if you do, repeat it in alt text "
                             "and in the body copy."],
                      verification="Alt coverage above 90% on the sampled templates."),
        urls=[label(p) for p in pages], confidence=0.85,
        metrics={"scope": "template", "images": total, "missing": missing},
        tags=["accessibility", "non-text"])


def rule_lang_declaration(bundle: dict) -> Optional[Finding]:
    pages = [p for p in ev.pages(bundle) if not p.get("fetch_failed")]
    if not sample_guard(pages, 2):
        return None
    without = [p for p in pages if not (p.get("lang") or "").strip()]
    if len(without) < len(pages):
        return None
    return finding(
        "MR-LANG-MISSING", "No page declares its content language", "low", PILLAR,
        evidence=f"None of the {len(pages)} sampled pages set a lang attribute on <html>.",
        items=page_items(without, "no lang attribute on <html> for {url}", limit=4),
        action=action('Set <html lang="…"> on every page.',
                      priority="low", effort="low", impact="low",
                      mechanism="The lang attribute is the explicit, machine-readable statement "
                                "of the page's language; without it the language has to be "
                                "guessed from the text, which is least reliable on short pages "
                                "made of names and numbers.",
                      steps=["Emit the BCP-47 tag for the page's actual language (en, en-IN, hi).",
                             "If you serve multiple languages, add hreflang alternates too."],
                      verification="Every page's <html> element has a lang attribute."),
        urls=[label(p) for p in without[:10]], confidence=0.9,
        metrics={"scope": "site"}, tags=["metadata"])


def rule_microdata_only(bundle: dict) -> Optional[Finding]:
    pages = ev.pages(bundle)
    micro_only = [p for p in pages if p.get("microdata") and not p.get("jsonld_blocks")]
    if not micro_only or len(micro_only) < max(2, len(pages) * 0.5):
        return None
    return finding(
        "MR-MICRODATA-ONLY",
        "Structured data is expressed only as inline microdata", "low", PILLAR,
        evidence=f"{len(micro_only)} of {len(pages)} sampled page(s) carry microdata attributes "
                 "but no JSON-LD block. Microdata is valid, but it is entangled with the "
                 "presentation markup and breaks whenever the template is redesigned.",
        items=[observed(f"{len(p.get('microdata', []))} microdata item(s), 0 JSON-LD blocks",
                        url=label(p), locator="itemscope attributes") for p in micro_only[:5]],
        action=action("Add JSON-LD alongside (or instead of) the inline microdata.",
                      priority="low", effort="low", impact="low",
                      mechanism="JSON-LD is a single block, read as one unit, that survives a "
                                "redesign of the template. Microdata scattered through the DOM "
                                "can break every time a designer moves a div, with no error to notice.",
                      steps=["Generate JSON-LD from the same data source that fills the template.",
                             "Keep the values byte-identical to the visible text.",
                             "Remove the microdata once JSON-LD is verified, or keep both in sync."],
                      verification="Structured-data test shows the same entity from the JSON-LD "
                                   "block."),
        urls=[label(p) for p in micro_only], confidence=0.85,
        metrics={"scope": "template", "affected": len(micro_only)},
        tags=["structured-data"])


#: The four Open Graph properties a fetcher can actually do something with.
#: `og:image` is deliberately excluded from the required set - it carries no
#: fact, and demanding it would turn a text-first site into a defect.
_OG_REQUIRED = ("og:title", "og:description", "og:type")


def rule_open_graph_coverage(bundle: dict) -> Optional[Finding]:
    """Open Graph is a page's own summary, in a fixed place with a declared meaning.

    The extractor has always consumed `og:site_name` and `og:description` for
    the entity rules, so a site could ship no OG at all and hear nothing about
    it. This reports the absence - as optional metadata, never as a blocker,
    and without any claim about which consumers read the block or when.

    Scoped to pages that carry a fact worth summarising - a page type the site
    would want quoted - so a paginated archive never drags the ratio down.
    """
    context = semantic_context(bundle)
    pages = [p for p in ev.pages(bundle)
             if semantics.open_graph_expectation(p, context) == "recommended"
             and not p.get("fetch_failed") and not p.get("non_html")]
    if not sample_guard(pages, 3):
        return None

    def missing_for(page: dict) -> List[str]:
        og = page.get("open_graph", {}) or {}
        return [key for key in _OG_REQUIRED if not str(og.get(key, "")).strip()]

    incomplete = [(p, missing_for(p)) for p in pages]
    incomplete = [(p, gaps) for p, gaps in incomplete if gaps]
    if not incomplete or len(incomplete) / len(pages) < 0.5:
        return None

    bare = [p for p, gaps in incomplete if len(gaps) == len(_OG_REQUIRED)]
    caveat = coverage_caveat(bundle)
    # Open Graph is optional metadata: its absence is a gap worth naming and
    # never a blocker, so the severity is capped at the optional ceiling.
    severity = semantics.cap_optional(step_down(
        severity_from_ratio(len(incomplete) / len(pages), critical=1.01, high=0.9, medium=0.5),
        caveat))
    og_types = ["'website'", "'article'"]
    if context.get("sells_online"):
        og_types.append("'product'")
    return finding(
        "MR-OPEN-GRAPH-INCOMPLETE",
        "Pages ship without a usable Open Graph summary",
        severity, PILLAR,
        evidence=(f"{len(incomplete)} of {len(pages)} sampled page(s) are missing at least one "
                  f"of {', '.join(_OG_REQUIRED)}"
                  + (f", and {len(bare)} carry none of them" if bare else "")
                  + ". Open Graph is optional metadata; this is a gap in the explicit "
                    "summary a page offers, not a blocker." + caveat),
        interpretation="Open Graph states a title, a one-line summary and a type in a fixed "
                       "place with a declared meaning. Where it is absent, any summary of the "
                       "page has to be assembled from its body. Which consumers make use of "
                       "the Open Graph block, and when, is not something this audit measures.",
        items=page_items([p for p, _ in incomplete],
                         "incomplete Open Graph on {url}", limit=5),
        action=action(
            "Emit og:title, og:description and og:type on every page a machine might quote.",
            priority="medium", effort="low", impact="medium",
            mechanism="Open Graph is a page's own one-line summary in a fixed, unambiguous "
                      "place: explicit, machine-readable evidence of what the page is about "
                      "that does not depend on parsing the body.",
            steps=["Set og:title from the page title, og:description from the same sentence "
                   f"as the meta description, and og:type ({', '.join(og_types)}).",
                   "Add og:url as the canonical absolute URL so shares resolve to one address.",
                   "Keep the OG values identical to the visible title and summary - a "
                   "contradiction between them is a freshness defect of its own."],
            verification="curl -s <url> | grep 'og:' shows title, description and type on "
                         "every sampled page."),
        urls=[label(p) for p, _ in incomplete],
        confidence=confidence_for(len(incomplete), len(pages), base=0.85),
        metrics={"scope": scope_for(len(incomplete), len(pages)),
                 "affected": len(incomplete), "sampled": len(pages)},
        tags=["metadata", "open-graph"])


#: Document types that carry facts but are not text a retrieval pipeline reads
#: in the ordinary course. PDFs dominate; the others appear on B2B and
#: industrial sites, where spec sheets and price lists are routinely the only
#: place a number is published.
_OPAQUE_DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")

#: Link text that says the document behind it carries a buying or brand fact.
#: Deliberately narrow: a link labelled "annual report" is not a product fact,
#: and reporting it would be noise.
_FACT_BEARING_HINTS = (
    "spec", "specification", "datasheet", "data sheet", "tech sheet",
    "price list", "pricelist", "catalog", "catalogue", "brochure",
    "manual", "user guide", "instruction", "warranty", "product sheet",
    "size guide", "size chart", "fact sheet", "press release", "press kit",
)


def rule_facts_locked_in_documents(bundle: dict) -> Optional[Finding]:
    """A fact published only as a PDF requires a consumer that fetches and parses PDFs.

    The crawler deliberately excludes binary documents from the frontier, which
    is correct behaviour and also a blind spot: a site whose spec sheets, price
    lists and press kit exist only as PDFs produced no finding at all, and read
    as clean. This does not parse the documents - it counts them, from the link
    the site itself published, and reports the pattern.
    """
    pages = [p for p in ev.pages(bundle)
             if not p.get("fetch_failed") and not p.get("non_html")]
    if not sample_guard(pages, 2):
        return None

    hits: List[Tuple[dict, dict]] = []
    for page in pages:
        links = page.get("links", {}) or {}
        for link in (links.get("internal", []) or []) + (links.get("external", []) or []):
            url = str(link.get("url", ""))
            path = util.url_path(url).lower()
            if not path.endswith(_OPAQUE_DOC_EXT):
                continue
            label_text = f"{link.get('text', '')} {path}".lower()
            if any(hint in label_text for hint in _FACT_BEARING_HINTS):
                hits.append((page, link))

    # One brochure is a brochure. A pattern of them is where the facts live.
    unique_docs = {str(link.get("url")) for _, link in hits}
    if len(unique_docs) < 3:
        return None

    host_pages = sorted({label(page) for page, _ in hits})
    return finding(
        "MR-FACTS-IN-OPAQUE-DOCS",
        "Product and brand facts are published as downloadable documents rather than as page text",
        "medium", PILLAR,
        evidence=(f"{len(unique_docs)} fact-bearing document(s) - spec sheets, price lists, "
                  f"catalogues, manuals - are linked from {len(host_pages)} sampled page(s), "
                  f"e.g. {', '.join(sorted(unique_docs)[:3])}. A number that exists only "
                  f"inside a downloadable document is not in the HTML a fetch of the page "
                  f"receives, and this audit did not open the documents either."),
        # The evidence item is anchored to the page that *was* fetched, and the
        # document it points at is named in the observation. Citing the PDF as
        # the item URL would claim an observation of a document this audit
        # never opened - the crawler excludes them by design.
        items=[observed(f"links to {str(link.get('url'))} as "
                        f"'{(link.get('text') or '').strip()[:60]}' (document not fetched)",
                        url=label(page), locator="document link")
               for page, link in hits[:5]],
        action=action(
            "Publish the same facts as HTML alongside the document, and link the document from it.",
            priority="medium", effort="medium", impact="high",
            mechanism="A fact published as HTML text is in the response a fetch of the page "
                      "receives; a fact inside a linked document requires a second fetch and a "
                      "document parser, and the parse is lossy. Publishing the same values as "
                      "page text and typed markup makes them available without either step. "
                      "Whether any given fetcher opens documents is not measured here.",
            steps=["For each spec sheet or price list, render its table as an HTML page under "
                   "a stable URL, and keep the PDF as a download link on that page.",
                   "Mirror the same values into structured data (Product additionalProperty, "
                   "or PropertyValue pairs) so the fact is typed as well as visible.",
                   "Where the document is the canonical artefact (a warranty, a manual), "
                   "publish an HTML summary of the terms buyers actually ask about."],
            verification="Each specification value is present in the HTML response body, not "
                         "only in the linked document."),
        urls=host_pages[:10],
        confidence=0.8,
        metrics={"scope": "site", "affected": len(unique_docs), "sampled": len(pages)},
        tags=["extractability", "non-text-facts"])


RULES = (
    rule_no_structured_data,
    rule_product_schema_missing,
    rule_invalid_jsonld,
    rule_jsonld_context,
    rule_offer_completeness,
    rule_identifiers,
    rule_attributes_thin,
    rule_ratings_and_reviews,
    rule_breadcrumb_markup,
    rule_site_level_schema,
    rule_metadata_hygiene,
    rule_facts_locked_in_images,
    rule_image_alt_coverage,
    rule_lang_declaration,
    rule_microdata_only,
    rule_open_graph_coverage,
    rule_facts_locked_in_documents,
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
