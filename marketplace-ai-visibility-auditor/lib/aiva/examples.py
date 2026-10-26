"""Worked examples, built from the audited site rather than from a template.

A recommendation is easier to act on when it comes with a snippet the team can
paste. The hazard is that a snippet written once, by hand, describes whatever
website its author had in mind - and then appears in every report the tool ever
produces. A reader auditing a grocer who is shown a running-shoe example
learns two things: what to do, and that the audit was not really about their
site. The second one is louder, and it discredits the measured findings
alongside the invented ones.

So examples are assembled here, from :func:`aiva.analysis.site_vocabulary`,
which reads names, categories, prices and attributes back out of pages the
crawl actually fetched. When the crawl saw nothing to name, the value falls
back to a neutral placeholder (``<Product Name>``, ``<Attribute>``) which is
obviously a blank to fill in rather than a claim about the site.

Every function here is pure and takes the vocabulary dict; nothing reaches the
network, and nothing invents an attribute the site does not use.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .analysis import PLACEHOLDER, example_attributes, named

__all__ = [
    "product_jsonld", "additional_property", "organization_jsonld",
    "breadcrumb_jsonld", "variant_group_jsonld", "spec_table",
    "answer_page_title", "llms_txt", "monitoring_probe",
]


def _example_id(vocab: Dict[str, Any], suffix: str) -> str:
    origin = vocab.get("origin") or "https://example.com"
    return f"{origin.rstrip('/')}/{suffix}"


def _attribute_rows(vocab: Dict[str, Any], limit: int = 2) -> List[Dict[str, str]]:
    return [{"@type": "PropertyValue", "name": name, "value": "<value>"}
            for name in example_attributes(vocab, limit)]


def product_jsonld(vocab: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """A complete Product node named after a product the crawl actually saw.

    ``context`` is the site's semantic shape (:func:`aiva.semantics.site_context`).
    The physical-goods fields - a GTIN, a stock value - are only shown when
    the site is seen to sell physical goods; a software or subscription
    catalogue is shown the fields that describe what it sells.
    """
    context = context or {}
    physical = bool(context.get("sells_physical_goods")) or not context
    software = bool(context.get("sells_software") or context.get("sells_subscriptions"))
    node: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication" if (software and not physical) else "Product",
        "@id": _example_id(vocab, "<product-path>#product"),
        "name": named(vocab, "product"),
        "sku": named(vocab, "sku"),
    }
    if physical:
        node["gtin13"] = "<13-digit GTIN>"
    node.update({
        "brand": {"@type": "Brand", "name": named(vocab, "organization")},
        "category": named(vocab, "category"),
    })
    if software and not physical:
        node.update({"operatingSystem": "<OS list>", "applicationCategory": "<category>",
                     "softwareVersion": "<version>"})
    else:
        node["additionalProperty"] = _attribute_rows(vocab, 2)
    node["aggregateRating"] = {"@type": "AggregateRating",
                               "ratingValue": "<value>", "reviewCount": "<count>"}
    offer: Dict[str, Any] = {
        "@type": "Offer",
        "price": named(vocab, "price"),
        "priceCurrency": named(vocab, "currency"),
    }
    if physical:
        offer["availability"] = "https://schema.org/InStock"
    offer["priceValidUntil"] = "<YYYY-MM-DD>"
    offer["url"] = _example_id(vocab, "<product-path>")
    node["offers"] = offer
    body = json.dumps(node, indent=2, ensure_ascii=False)
    return f'<script type="application/ld+json">\n{body}\n</script>'


def additional_property(vocab: Dict[str, Any]) -> str:
    """Just the additionalProperty array, naming this site's own attributes."""
    rows = [{"@type": "PropertyValue", "name": name,
             "value": "<value>", "unitText": "<unit, if the value has one>"}
            for name in example_attributes(vocab, 2)]
    return '"additionalProperty": ' + json.dumps(rows, ensure_ascii=False)


def organization_jsonld(vocab: Dict[str, Any], *, full: bool = True) -> str:
    node: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": _example_id(vocab, "#organization"),
        "name": named(vocab, "organization"),
        "url": (vocab.get("origin") or "https://example.com").rstrip("/") + "/",
        "logo": _example_id(vocab, "<logo-path>"),
    }
    if full:
        node.update({
            "legalName": "<Registered Legal Name>",
            "foundingDate": "<YYYY>",
            "description": "<one sentence describing what this organization sells>",
            "address": {"@type": "PostalAddress",
                        "addressLocality": "<City>", "addressCountry": "<CC>"},
        })
    node["sameAs"] = ["<canonical profile URL>", "<knowledge base entry URL>"]
    return json.dumps(node, indent=2, ensure_ascii=False)


def breadcrumb_jsonld(vocab: Dict[str, Any]) -> str:
    node = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1,
             "name": named(vocab, "category"),
             "item": _example_id(vocab, "<category-path>")},
            {"@type": "ListItem", "position": 2,
             "name": named(vocab, "product"),
             "item": _example_id(vocab, "<product-path>")},
        ],
    }
    return json.dumps(node, ensure_ascii=False)


def variant_group_jsonld(vocab: Dict[str, Any]) -> str:
    varies = example_attributes(vocab, 1)[0]
    node = {
        "@type": "ProductGroup",
        "productGroupID": named(vocab, "sku"),
        "name": named(vocab, "product"),
        "variesBy": [varies],
        "hasVariant": [
            {"@type": "Product",
             "sku": f"{named(vocab, 'sku')}-<variant-suffix>",
             varies: PLACEHOLDER["value"],
             "offers": {"@type": "Offer",
                        "price": named(vocab, "price"),
                        "priceCurrency": named(vocab, "currency"),
                        "availability": "https://schema.org/InStock"}},
        ],
    }
    return json.dumps(node, indent=2, ensure_ascii=False)


def spec_table(vocab: Dict[str, Any], limit: int = 3) -> str:
    rows = "\n".join(
        f'  <tr><th scope="row">{name}</th><td>&lt;value&gt;</td></tr>'
        for name in example_attributes(vocab, limit))
    return f"<table>\n{rows}\n</table>"


def answer_page_title(vocab: Dict[str, Any]) -> str:
    """A question-shaped page title using this site's own category noun."""
    category = named(vocab, "category")
    attribute = example_attributes(vocab, 1)[0]
    if category == PLACEHOLDER["category"] and attribute == PLACEHOLDER["attribute"]:
        return "How do I choose the right <Category>? — a question buyers actually ask"
    return f"How do I choose the right {category} for a given {attribute}?"


def llms_txt(vocab: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """An agent-facing index shaped like the site it is for.

    A shop's index lists products and policies; a documentation site's lists
    its sections; a public body's lists its services. The sections follow
    the site's semantic shape so the example never describes a catalogue the
    site does not have.
    """
    context = context or {}
    origin = (vocab.get("origin") or "https://example.com").rstrip("/")
    kind = context.get("site_kind") or "unknown"
    head = f"# {named(vocab, 'organization')}\n"
    if context.get("sells_physical_goods") or kind in ("ecommerce", "marketplace"):
        stock = ", in stock" if context.get("sells_physical_goods") else ""
        return (head + "> <one sentence describing what this organisation sells>\n\n"
                f"## Products\n"
                f"- [{named(vocab, 'product')}]({origin}/<product-path>): "
                f"{named(vocab, 'category')}, {named(vocab, 'currency')} "
                f"{named(vocab, 'price')}{stock}\n\n"
                f"## Policies\n"
                f"- [Returns]({origin}/<returns-path>): <return window>\n"
                f"- [Delivery]({origin}/<delivery-path>): <destinations and cost>\n")
    if kind == "software" or context.get("sells_software") or context.get("sells_subscriptions"):
        return (head + "> <one sentence describing what this software does>\n\n"
                f"## Product\n"
                f"- [{named(vocab, 'product')}]({origin}/<product-path>): <what it is, "
                f"current version, platforms>\n"
                f"- [Pricing]({origin}/<pricing-path>): <plans and prices>\n\n"
                f"## Documentation\n"
                f"- [Getting started]({origin}/<docs-path>): <one-line gloss>\n"
                f"- [Release notes]({origin}/<changelog-path>): <one-line gloss>\n")
    if kind == "documentation":
        return (head + "> <one sentence describing what this project is>\n\n"
                f"## Documentation\n"
                f"- [Getting started]({origin}/<docs-path>): <one-line gloss>\n"
                f"- [Reference]({origin}/<reference-path>): <one-line gloss>\n"
                f"- [FAQ]({origin}/<faq-path>): <one-line gloss>\n")
    if kind == "government":
        return (head + "> <one sentence describing what this body does>\n\n"
                f"## Services\n"
                f"- [<service name>]({origin}/<service-path>): <who it is for, how to apply>\n\n"
                f"## About\n"
                f"- [Contact]({origin}/<contact-path>): <how to reach the body>\n")
    if kind == "travel_hospitality":
        return (head + "> <one sentence describing what this place or operator offers>\n\n"
                f"## Places\n"
                f"- [<property name>]({origin}/<property-path>): <where it is, what it "
                f"includes, what it costs>\n\n"
                f"## Booking\n"
                f"- [Availability and booking]({origin}/<booking-path>): <how to book, "
                f"minimum stay>\n"
                f"- [Cancellation]({origin}/<cancellation-path>): <the terms>\n")
    if kind == "developer_platform":
        return (head + "> <one sentence describing what this project or platform is>\n\n"
                f"## Projects\n"
                f"- [<repository name>]({origin}/<repo-path>): <what it does, language, "
                f"licence>\n\n"
                f"## Reference\n"
                f"- [API reference]({origin}/<api-path>): <one-line gloss>\n"
                f"- [Getting started]({origin}/<docs-path>): <one-line gloss>\n")
    if kind == "knowledge_reference":
        return (head + "> <one sentence describing what this reference covers>\n\n"
                f"## Reference\n"
                f"- [<entry name>]({origin}/<entry-path>): <the definition or value it "
                f"states>\n"
                f"- [<dataset name>]({origin}/<dataset-path>): <what it covers, licence>\n\n"
                f"## About\n"
                f"- [Sources]({origin}/<sources-path>): <where the statements come from>\n")
    if kind in ("publisher", "education", "community", "nonprofit"):
        section = {"publisher": "Sections", "education": "Courses",
                   "community": "Guides", "nonprofit": "Programmes"}[kind]
        return (head + "> <one sentence describing what this organisation does>\n\n"
                f"## {section}\n"
                f"- [<name>]({origin}/<path>): <one-line gloss>\n\n"
                f"## About\n"
                f"- [About]({origin}/<about-path>): <who runs this and what it is for>\n")
    return (head + "> <one sentence describing what this organisation does>\n\n"
            f"## Key pages\n"
            f"- [<page name>]({origin}/<path>): <the fact this page states>\n\n"
            f"## About\n"
            f"- [About]({origin}/<about-path>): <who this is and what it does>\n")


def monitoring_probe(vocab: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """A question to ask an assistant, phrased in this site's own nouns and
    shaped like the site: a buying question for a shop, a 'how do I' for a
    documentation site, an eligibility question for a public body."""
    context = context or {}
    kind = context.get("site_kind") or "unknown"
    product = named(vocab, "product")
    organization = named(vocab, "organization")
    if context.get("sells_physical_goods") or kind in ("ecommerce", "marketplace"):
        return f"is {product} available, and what does it cost?"
    if kind == "software" or context.get("sells_software"):
        return f"what does {product} cost, and which platforms does it run on?"
    if kind == "documentation":
        return f"how do I get started with {organization}?"
    if kind == "developer_platform":
        return f"what does {product} do, and how do I install it?"
    if kind == "government":
        return f"what services does {organization} provide, and how do I apply?"
    if kind == "travel_hospitality":
        return f"where is {product}, what does it include, and what does it cost?"
    if kind == "knowledge_reference":
        return f"what does {organization} say about <one term it defines>?"
    return f"what is {organization}, and what does it do?"
