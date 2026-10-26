"""Helpers shared by the six specialist analyzers.

Two things live here that matter for the rubric:

* **False-positive guards.** :func:`sample_guard` refuses to let a rule fire
  when the crawl did not actually see enough of the relevant page type, and
  :func:`confidence_for` scales a finding's confidence by sample size, so a
  thin crawl produces cautious findings rather than confident wrong ones.
* **Consistent evidence construction.** Every rule builds its evidence items
  through the same helpers, so each one carries a URL and a locator.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import evidence as ev
from . import lexicon, util
from .config import PAGE_TYPE_HINTS
from .extract import (PRICE_RE, find_nodes, microdata_items, microdata_props,
                      microdata_types, node_types, product_subjects, prop, text_of)
from .findings import EvidenceItem, Finding, SuggestedAction, make_finding

# ---------------------------------------------------------------------------
# JSON-LD graph resolution
# ---------------------------------------------------------------------------


def entity_index(bundle: dict) -> Dict[str, dict]:
    """Map every declared ``@id`` in the crawl to its node.

    Well-built sites reference entities (``{"@id": "/#organization"}``) rather
    than repeating them. Without resolving those references an auditor would
    read the IRI as a name and report a false "inconsistent brand name".
    """
    index: Dict[str, dict] = {}
    for page in ev.pages(bundle):
        for node in page.get("jsonld_nodes", []) or []:
            node_id = prop(node, "@id")
            if isinstance(node_id, str) and node_id and node_id not in index and node_types(node):
                index[node_id] = node
    return index


def resolve_entity(value: Any, index: Dict[str, dict]) -> Any:
    if isinstance(value, dict):
        if prop(value, "name"):
            return value
        ref = prop(value, "@id")
        if isinstance(ref, str) and ref in index:
            return index[ref]
        return value
    if isinstance(value, str) and value in index:
        return index[value]
    return value


def entity_name(value: Any, index: Optional[Dict[str, dict]] = None) -> Optional[str]:
    """The human name of a referenced entity, or ``None`` if it cannot be resolved.

    Returning ``None`` rather than the raw IRI is deliberate: an unresolvable
    reference is missing evidence, not evidence of a wrong name.
    """
    resolved = resolve_entity(value, index or {})
    if isinstance(resolved, dict):
        name = text_of(prop(resolved, "name"))
        return name or None
    if isinstance(resolved, str):
        if resolved.startswith(("#", "/", "http://", "https://", "urn:")):
            return None
        return resolved.strip() or None
    if isinstance(resolved, list):
        for item in resolved:
            name = entity_name(item, index)
            if name:
                return name
    return None

# ---------------------------------------------------------------------------
# page helpers
# ---------------------------------------------------------------------------

def has_jsonld_type(page: dict, *types: str) -> bool:
    wanted = {t.lower() for t in types}
    return bool({t.lower() for t in page.get("jsonld_types", [])} & wanted)


def jsonld_nodes(page: dict) -> List[dict]:
    return page.get("jsonld_nodes", []) or []


def products_on(page: dict) -> List[dict]:
    return find_nodes(jsonld_nodes(page), "Product", "ProductGroup", "IndividualProduct")


def offers_of(node: dict) -> List[dict]:
    raw = prop(node, "offers")
    if raw is None:
        return []
    candidates = raw if isinstance(raw, list) else [raw]
    out: List[dict] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            types = {t.lower() for t in node_types(candidate)}
            if types & {"aggregateoffer"}:
                out.append(candidate)
                for inner in (prop(candidate, "offers") or []) if isinstance(
                        prop(candidate, "offers"), list) else []:
                    if isinstance(inner, dict):
                        out.append(inner)
            else:
                out.append(candidate)
    return out


def offer_price(offer: dict) -> Optional[str]:
    for key in ("price", "lowPrice", "highPrice"):
        value = text_of(prop(offer, key))
        if value:
            return value
    spec = prop(offer, "priceSpecification")
    if isinstance(spec, dict):
        return text_of(prop(spec, "price"))
    if isinstance(spec, list):
        for item in spec:
            value = text_of(prop(item, "price")) if isinstance(item, dict) else None
            if value:
                return value
    return None


def offer_currency(offer: dict) -> Optional[str]:
    value = text_of(prop(offer, "priceCurrency"))
    if value:
        return value
    spec = prop(offer, "priceSpecification")
    if isinstance(spec, dict):
        return text_of(prop(spec, "priceCurrency"))
    return None


def offer_availability(offer: dict) -> Optional[str]:
    value = text_of(prop(offer, "availability", "itemAvailability"))
    if not value:
        return None
    return value.rstrip("/").split("/")[-1].split("#")[-1]


# ---------------------------------------------------------------------------
# item identity: what a product page is *called*, and how we know
# ---------------------------------------------------------------------------
#
# Several consumers quote a product's name back to the reader - a generated
# question, a worked example in a recommendation, a duplicate-name finding.
# All of them used to read the first `<h1>` on any page classified `product`,
# which on a live site produced questions about "Add to bag", "Shop the
# range" and "Product details": headings that name a control, a promotion or
# a section of the template, not the thing the page sells.
#
# Identity therefore comes from *item-scoped* evidence only, in this order:
#
# 1. the name of the product entity the page's own markup declares
#    (JSON-LD subject node, microdata product item, an Open Graph product card);
# 2. failing that, a heading - but only one the page corroborates in a second,
#    independent channel: its `<title>` (with template segments removed), its
#    `og:title`, or its URL slug; and never one that is the label of one of the
#    page's own controls, a string the site repeats across pages, or a string
#    shaped like a promotion rather than a name.
#
# Every test below is about shape or provenance. None of it knows a brand, a
# framework, or a word a call to action is likely to use.

#: Strings that are not the name of a thing anyone sells. A generated question
#: quotes its subject back to the reader - "What is the price of {name}?" - so
#: a template token, a component id or a CSS class becomes a question about
#: nothing, cited to a real URL, which is worse than asking no question at all.
#: Each test below is about the *shape* of the string, not its vocabulary, so
#: none of it depends on knowing any particular site or framework.
_PLACEHOLDER_NAME_RE = re.compile(
    r"^\s*(?:"
    r"\{\{.*\}\}|\{.*\}|%[sd]|\$\{.*\}|<[^>]+>|"          # template tokens
    r"(?:data|aria)-[a-z-]+|"                              # DOM attribute names
    r"(?:lorem\s+ipsum|test|todo|tbd|xxx+|n/?a|null|none|undefined|"
    r"product\s*name|item\s*name|title|untitled|placeholder|default|sample)"
    r")\s*$", re.I)

#: A component or class name rather than prose: `ProductTile__price--sale`,
#: `pdp_hero_v2`, `data-testid`. Real product names contain a space or are a
#: short model code; these are long, unspaced and carry code punctuation.
_COMPONENT_NAME_RE = re.compile(r"(?:__|--|::)|^[a-z]+(?:[A-Z][a-z]+){2,}$"
                                r"|^[a-z0-9]+(?:[-_][a-z0-9]+){3,}$")

#: A string shaped like a promotion or a slogan rather than a name: it quotes
#: a percentage, or it ends the way an exhortation or a question does. A
#: product name is a noun phrase; it does not end in "!" and it does not
#: contain "20% off". A quoted *price* is the third shape, and it is read
#: with the extractor's own price grammar rather than a second one.
_PROMOTION_SHAPE_RE = re.compile(r"\d\s*%|%\s*\d|[!?…]\s*$")

#: Title segment separators, shared with the entity specialist's brand
#: reading so both split a title the same way.
TITLE_SEPARATORS = ("|", "–", "—", " - ", "::", "·", "»")

#: Declared page-level types that identify a product card.
_PRODUCT_CARD_TYPES = frozenset({"product", "product.item", "og:product"})

#: Microdata / JSON-LD product types, bare and lower-cased.
_PRODUCT_ITEM_TYPES = frozenset({"product", "productgroup", "individualproduct",
                                 "vehicle", "book", "softwareapplication"})

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def is_usable_entity_name(name: str) -> bool:
    """Is this string shaped like the name of something the site could sell?

    The audit generates questions from the site's own catalogue, which is what
    makes them fair - and what makes an unvalidated name dangerous. A question
    built on a template token or a component id reads exactly like a question
    built on a product, and the reader has no way to tell which they are
    looking at. Where identity cannot be established the question is not asked
    at all; a missing question is a gap, an invented one is a wrong answer.
    """
    name = util.collapse_ws(name or "")
    if len(name) < 2 or len(name) > 120:
        return False
    if _PLACEHOLDER_NAME_RE.match(name):
        return False
    if _COMPONENT_NAME_RE.search(name):
        return False
    if not re.search(r"[a-z]", name, re.I):        # digits or symbols alone
        return False
    # A name that is one long unspaced token of mixed case and punctuation is a
    # slug or an identifier, not a display name.
    if " " not in name and re.search(r"[_/\\|]", name):
        return False
    return True


def reads_as_a_promotion(name: str) -> bool:
    """Is this string shaped like a promotion, a slogan or a question?"""
    text = util.collapse_ws(name or "")
    return bool(_PROMOTION_SHAPE_RE.search(text) or PRICE_RE.search(text))


def title_segments(title: str) -> List[str]:
    """A title split at its separators, empty segments dropped."""
    parts = [util.collapse_ws(title or "")]
    for separator in TITLE_SEPARATORS:
        parts = [piece.strip() for part in parts for piece in part.split(separator)]
    return [p for p in parts if p]


def _fold(text: str) -> str:
    return util.collapse_ws(lexicon.fold(text or "")).strip().lower()


def _words(text: str) -> List[str]:
    return [w for w in _WORD_RE.findall(_fold(text)) if len(w) > 1 or w.isdigit()]


def site_declared_names(bundle: dict) -> set:
    """The names the site declares for *itself*, folded.

    Organization/Brand/Store names in markup and ``og:site_name``. A product
    cannot be called what the site is called: a page whose heading - or whose
    declared product name - is the brand has not said which product it is.
    """
    names = set()
    for page in ev.pages(bundle or {}):
        og = page.get("open_graph") or {}
        names.add(_fold(str(og.get("og:site_name") or "")))
        for node in jsonld_nodes(page):
            if set(t.lower() for t in node_types(node)) & {
                    "organization", "brand", "onlinestore", "store", "corporation"}:
                names.add(_fold(text_of(prop(node, "name")) or ""))
    names.discard("")
    return names


def site_template_strings(bundle: dict) -> set:
    """Strings this site repeats from page to page, folded.

    A heading or title segment that appears on two or more distinct crawled
    URLs is part of the template - the site name, a tagline, a section label
    - and cannot on its own be the identity of any one page. The site's
    declared names are included for the same reason.

    Repetition is evidence about *headings*, not about declarations: six
    variant pages that each declare ``Product.name = "VITTSKAR"`` have each
    stated an identity, and a heading they share is corroborated page by
    page through the title segment that differs. See :func:`item_identity`.
    """
    counts: Dict[str, set] = {}

    def saw(text: str, url: str) -> None:
        key = _fold(text)
        if key:
            counts.setdefault(key, set()).add(url)

    for page in ev.pages(bundle or {}):
        url = util.normalize_url(label(page)) or label(page)
        for heading in _heading_candidates(page):
            saw(heading, url)
        for segment in title_segments(str(page.get("title") or "")):
            saw(segment, url)
    repeated = {key for key, urls in counts.items() if len(urls) >= 2}
    return repeated | site_declared_names(bundle)


def identity_context(bundle: Optional[dict]) -> Dict[str, set]:
    """What :func:`item_identity` needs to know about the whole crawl, once."""
    if not bundle:
        return {"template": set(), "site_names": set()}
    return {"template": site_template_strings(bundle),
            "site_names": site_declared_names(bundle)}


def _corroborates(candidate: str, statement: str) -> bool:
    """Does an independent statement of the page's subject match this candidate?"""
    a, b = _fold(candidate), _fold(statement)
    if len(a) < 3 or len(b) < 3:
        return False
    return a == b or a in b or b in a


def _slug_corroborates(candidate: str, url: str) -> bool:
    """Do the heading's words appear in the URL's final path segment?"""
    path = (util.url_path(url) or "").rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    slug_words = set(_words(re.sub(r"[-_.+%]+", " ", slug)))
    heading_words = _words(candidate)
    if not heading_words or not slug_words:
        return False
    matched = sum(1 for w in heading_words if w in slug_words)
    return matched >= 1 and matched / len(heading_words) >= 0.6


def _heading_candidates(page: dict) -> List[str]:
    """The page's top-level headings: its `<h1>`s, or, on a page with none,
    the headings at the highest level it does use.

    A product page that names its product in an `<h2>` because the template
    spent the `<h1>` elsewhere has still named it, and the corroboration a
    heading needs to be accepted is the same whatever its level.
    """
    h1s = [util.collapse_ws(str(h or "")) for h in (page.get("h1_texts") or [])]
    if any(h1s):
        return [h for h in h1s if h][:5]
    headings = [h for h in (page.get("headings") or []) if isinstance(h, dict)]
    levels = [int(h.get("level") or 0) for h in headings if h.get("level")]
    if not levels:
        return []
    top = min(levels)
    return [util.collapse_ws(str(h.get("text") or "")) for h in headings
            if int(h.get("level") or 0) == top and h.get("text")][:5]


def _control_labels(page: dict) -> set:
    """Everything the page calls a control: buttons, link labels in the nav."""
    labels = {_fold(t) for t in (page.get("control_labels") or [])}
    for link in (page.get("links") or {}).get("internal") or []:
        if isinstance(link, dict):
            labels.add(_fold(str(link.get("text") or "")))
    labels.discard("")
    return labels


def item_identity(page: dict, bundle: Optional[dict] = None,
                  context: Optional[Dict[str, set]] = None) -> Optional[dict]:
    """The name of the item this page is about, with the evidence for it.

    Returns ``{"name", "source", "corroboration"}`` or ``None`` when nothing
    on the page establishes an identity a reader could hold it to. ``None``
    is the conservative answer, and callers must treat it as "ask nothing"
    rather than as "fall back to a heading" - the fallback is what this
    function already is.

    ``context`` is :func:`identity_context` of the crawl; pass it when calling
    for many pages so the site's template strings are computed once.
    """
    if not page or page.get("fetch_failed") or page.get("non_html"):
        return None
    if context is None:
        context = identity_context(bundle)
    template, site_names = context["template"], context["site_names"]
    url = page.get("final_url") or page.get("url") or ""

    def acceptable(name: str) -> bool:
        return (is_usable_entity_name(name) and not reads_as_a_promotion(name)
                and _fold(name) not in site_names)

    # 1. The entity the markup declares this page to be about. A declaration
    # is item-scoped by construction, so it is not subject to the repetition
    # test: six variant pages declaring the same product name have each
    # named their product.
    for node in product_subjects(page):
        name = text_of(prop(node, "name"))
        if name and acceptable(name):
            return {"name": util.collapse_ws(name), "source": "declared product entity",
                    "corroboration": "JSON-LD Product.name on the page's subject node"}
    for record in microdata_items(page):
        if set(microdata_types([record])) & _PRODUCT_ITEM_TYPES:
            names = microdata_props(record).get("name") or []
            if names and acceptable(names[0]):
                return {"name": util.collapse_ws(names[0]),
                        "source": "declared product item",
                        "corroboration": "microdata itemprop=name on a product item"}
    og = page.get("open_graph") or {}
    og_type = str(og.get("og:type") or "").strip().lower()
    og_title = util.collapse_ws(str(og.get("og:title") or ""))
    if og_type in _PRODUCT_CARD_TYPES and og_title:
        for segment in title_segments(og_title):
            if acceptable(segment) and _fold(segment) not in template:
                return {"name": segment, "source": "declared product card",
                        "corroboration": "og:type=product with og:title"}

    # 2. A heading the page corroborates elsewhere. Every heading is tried in
    # order, but only ever accepted on corroboration - the first <h1> of a
    # page with several is a guess, and a guess is not an identity. A heading
    # the site repeats on other pages needs a title segment unique to this
    # page to vouch for it; its URL slug cannot, because a section label and
    # the section's URL agree by construction.
    controls = _control_labels(page)
    statements = [s for s in title_segments(str(page.get("title") or ""))
                  if _fold(s) not in template]
    statements += [s for s in title_segments(og_title) if _fold(s) not in template]
    for candidate in _heading_candidates(page):
        if not acceptable(candidate) or _fold(candidate) in controls:
            continue
        for statement in statements:
            if _corroborates(candidate, statement):
                return {"name": candidate, "source": "corroborated heading",
                        "corroboration": f"<h1> matches the page title segment \"{statement}\""}
        if _fold(candidate) not in template and _slug_corroborates(candidate, url):
            return {"name": candidate, "source": "corroborated heading",
                    "corroboration": "<h1> matches the URL slug"}
    return None


def product_identifiers(node: dict) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for key in ("sku", "gtin", "gtin8", "gtin12", "gtin13", "gtin14", "mpn",
                "productID", "isbn", "identifier"):
        value = text_of(prop(node, key))
        if value:
            found[key] = value
    return found


def product_attributes(node: dict) -> Dict[str, Any]:
    found: Dict[str, Any] = {}
    for key in ("color", "size", "material", "pattern", "weight", "width",
                "height", "depth", "audience", "additionalProperty",
                "hasMeasurement", "itemCondition"):
        value = prop(node, key)
        if value not in (None, "", []):
            found[key] = value
    return found


def page_has_spec_block(page: dict) -> bool:
    if page.get("definition_spec_lists", 0):
        return True
    for table in page.get("tables", []) or []:
        if table.get("looks_like_spec_table"):
            return True
    for node in products_on(page):
        extra = prop(node, "additionalProperty")
        if extra:
            return True
        if len(product_attributes(node)) >= 2:
            return True
    return False


# ---------------------------------------------------------------------------
# visible vs structured attributes
# ---------------------------------------------------------------------------

def structured_attribute_presence(page: dict) -> Dict[str, Any]:
    """Attributes exposed in a *typed* form a machine can read without parsing prose.

    Only schema.org properties count here: first-class ones (``color``,
    ``material``, ``size``...) and ``additionalProperty`` ``PropertyValue``
    entries. These are the ones an assistant can compare across products
    without interpreting a sentence.
    """
    typed: Dict[str, Any] = {}
    named: List[str] = []
    for node in products_on(page):
        for key, value in product_attributes(node).items():
            if key == "additionalProperty":
                entries = value if isinstance(value, list) else [value]
                for entry in entries:
                    if isinstance(entry, dict):
                        name = text_of(prop(entry, "name"))
                        if name:
                            named.append(str(name))
                            typed.setdefault(str(name), text_of(prop(entry, "value")))
            else:
                typed.setdefault(key, value)
                named.append(key)
    # Software declares its attributes under different names: an operating
    # system, a version, a category, requirements. They are typed
    # properties in exactly the sense colour and material are, and a
    # software page that publishes them has published its specification.
    for node in find_nodes(jsonld_nodes(page), "SoftwareApplication", "WebApplication",
                           "MobileApplication", "VideoGame"):
        for key in _SOFTWARE_ATTRIBUTE_PROPS:
            value = prop(node, key)
            if value not in (None, "", []):
                typed.setdefault(key, value)
                named.append(key)
    return {"count": len(typed), "names": sorted(set(named))[:20], "typed": typed}


#: Typed properties that describe a software application, read by
#: :func:`structured_attribute_presence` beside the physical ones.
_SOFTWARE_ATTRIBUTE_PROPS = ("operatingSystem", "applicationCategory", "softwareVersion",
                             "memoryRequirements", "storageRequirements",
                             "processorRequirements", "softwareRequirements", "fileSize",
                             "permissions", "featureList", "applicationSubCategory")


def visible_attribute_presence(page: dict) -> Dict[str, Any]:
    """Attributes the page states in human-readable content, however formatted.

    Three sources, all directly observed: two-column specification tables,
    ``<dl>`` term/definition pairs, and ``Label: value`` lines in the visible
    copy. A page can be rich in all three and still expose nothing typed - that
    is precisely the case the audit must be able to describe, because "present
    but unstructured" and "absent" have different fixes and only one of them is
    true of most storefronts.
    """
    labels: List[str] = []
    sources: List[str] = []
    for table in page.get("tables", []) or []:
        if table.get("looks_like_spec_table"):
            sources.append("specification table")
            for pair in table.get("sample_pairs", []) or []:
                if pair and pair[0]:
                    labels.append(str(pair[0]).strip(" :"))
    terms = page.get("definition_terms", []) or []
    if terms:
        sources.append("definition list")
        labels.extend(str(t).strip(" :") for t in terms)
    pairs = page.get("visible_attribute_pairs", []) or []
    if pairs:
        sources.append("label/value lines in visible copy")
        labels.extend(str(p.get("label", "")).strip(" :") for p in pairs)
    clean = [lbl for lbl in labels if lbl]
    unique: List[str] = []
    seen = set()
    for lbl in clean:
        key = lbl.lower()
        if key not in seen:
            seen.add(key)
            unique.append(lbl)
    return {"count": len(unique), "names": unique[:20],
            "sources": sorted(set(sources)),
            "structured_format": bool(page.get("definition_spec_lists") or
                                      any(t.get("looks_like_spec_table")
                                          for t in (page.get("tables") or [])))}


def listing_controls(page: dict) -> Dict[str, Any]:
    """Filtering and sorting, reported as two independent affordances.

    They are not the same feature and they do not answer the same question.
    *Filtering* removes non-matching products, which is what a constrained
    request ("under 300", "unsweetened") needs. *Sorting* re-orders the same
    set, which helps a superlative request ("cheapest") and does nothing for a
    constraint. A listing can plainly offer one and not the other, so the
    auditor records both and never collapses them into a single "no filtering
    or sorting" claim that the page itself contradicts.
    """
    forms = page.get("forms", {}) or {}
    filters = int(forms.get("filter_controls") or 0)
    # Bundles written before the split carry only the boolean.
    sorts = forms.get("sort_controls")
    if sorts is None:
        sorts = 1 if forms.get("has_sort_control") else 0
    sorts = int(sorts or 0)
    return {"filter_controls": filters, "sort_controls": sorts,
            "has_filter_controls": bool(forms.get("has_filter_controls", filters > 0)),
            "has_sort_controls": bool(forms.get("has_sort_controls", sorts > 0)),
            # What was found, named. A reader can check these against the page.
            "filter_control_names": list(forms.get("filter_control_names") or []),
            "sort_control_names": list(forms.get("sort_control_names") or []),
            "sort_options": list(forms.get("sort_options") or [])}


def name_list(values: Sequence[str], limit: int = 4) -> str:
    """A readable, quoted list of observed names for use inside evidence."""
    picked = [str(v) for v in values if v][:limit]
    if not picked:
        return ""
    quoted = [f"'{v}'" for v in picked]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


def visible_prices(page: dict) -> List[dict]:
    return page.get("prices_in_text", []) or []


def label(page: dict) -> str:
    return page.get("url") or page.get("final_url") or "(unknown url)"


# ---------------------------------------------------------------------------
# site vocabulary — where examples come from
# ---------------------------------------------------------------------------

#: Neutral stand-ins used when the crawl observed nothing to name.
#:
#: A worked example is worth more than an abstract instruction, but only if it
#: is *about the audited site*. An example drawn from some other trade is worse
#: than no example at all: it reads as though the audit was run against a
#: different website, and a reader cannot tell which parts of the report were
#: measured and which were boilerplate. So every example is either derived from
#: this crawl or falls back to one of these placeholders, and no rule is
#: permitted to name a product, brand or attribute that the auditor did not see.
PLACEHOLDER = {
    "organization": "<Organization Name>",
    "product": "<Product Name>",
    "category": "<Category>",
    "attribute": "<Attribute>",
    "value": "<Value>",
    "unit": "<Unit>",
    "price": "<Price>",
    "currency": "<CUR>",
    "sku": "<SKU>",
    "variant": "<Variant>",
    "question": "<a question buyers actually ask>",
}

#: Attribute labels that describe the transaction rather than the product.
#: Excluded from *comparison* examples, where naming "Price" as the attribute
#: to structure would be unhelpful, but still counted as visible attributes.
_TRANSACTIONAL_LABELS = {
    "price", "prix", "precio", "preis", "prezzo", "preço",
    "quantity", "qty", "total", "subtotal", "sku", "availability",
    "shipping", "delivery", "returns", "return policy", "share", "tax",
}


def _first_text(values: Sequence[Any]) -> Optional[str]:
    for value in values:
        text = text_of(value)
        if isinstance(text, str) and text.strip():
            return util.truncate(util.collapse_ws(text), 60)
    return None


#: A page carrying this many external scripts, or an SPA hydration marker, is
#: one where referenced-but-absent content plausibly arrives after JavaScript.
#: Defined once and shared, because two rules in two different pillars split
#: the same population along exactly this line and must not both claim a page.
CLIENT_RENDER_SCRIPT_THRESHOLD = 5


def shows_client_rendering_signals(page: dict) -> bool:
    """Does this page look like it assembles content after the initial response?"""
    scripts = page.get("scripts", {}) or {}
    return bool(scripts.get("spa_markers")) or \
        int(scripts.get("external_count") or 0) >= CLIENT_RENDER_SCRIPT_THRESHOLD


def _usable_page(page: dict) -> bool:
    """A page whose content can be quoted: fetched, parsed, and not an error."""
    return bool(page) and not page.get("fetch_failed") and not page.get("non_html") \
        and int(page.get("status") or 0) < 400


def _is_populated_listing(page: dict, bundle: dict) -> bool:
    """Does this category page actually list products?

    A URL classified as a category by its path can still be an empty-state
    page - "no results", "nothing here yet", a cleared search - served with a
    200 and a perfectly ordinary ``<h1>``. Reading that heading as the site's
    category noun put a string like "Uh-Oh, Nothing To See Here!" into every
    generic example in the report.

    The generic discriminator is not the wording, which differs per site and
    per language, but whether the listing has members: it links to pages the
    crawl identified as products, or declares an ItemList/CollectionPage with
    entries. An empty state has neither, whatever its heading says.
    """
    if not _usable_page(page):
        return False
    for node in jsonld_nodes(page):
        if set(node_types(node)) & {"ItemList", "CollectionPage", "OfferCatalog"}:
            if prop(node, "itemListElement") or prop(node, "numberOfItems"):
                return True
    product_urls = {util.normalize_url(label(p)) or label(p)
                    for p in ev.product_pages(bundle)}
    if product_urls:
        for link in (page.get("links", {}) or {}).get("internal", []) or []:
            target = link.get("url") if isinstance(link, dict) else link
            if (util.normalize_url(target) or target) in product_urls:
                return True
    return False


def site_vocabulary(bundle: dict, pages: Optional[List[dict]] = None) -> Dict[str, Any]:
    """The audited site's own nouns: organisation, product, category, attributes.

    Every worked example in the report is built from this. Nothing here is
    invented - each value is read back out of a page the crawl actually
    fetched - so a recommendation names whichever attribute the audited
    catalogue itself publishes, and names a completely different one on the
    next site, without the rule set knowing anything
    about either trade.

    ``pages`` restricts the product pages the vocabulary is read from, so a
    recommendation about physical goods quotes a physical product's own
    attributes rather than a software page's.
    """
    org: Optional[str] = None
    product: Optional[str] = None
    category: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = None
    sku: Optional[str] = None
    index = entity_index(bundle)

    home = ev.home_page(bundle)
    if home:
        for node in jsonld_nodes(home):
            if set(node_types(node)) & {"Organization", "Brand", "OnlineStore",
                                        "Store", "LocalBusiness", "Corporation"}:
                org = org or entity_name(node, index)
        org = org or _first_text([(home.get("meta", {}) or {}).get("og:site_name")])

    products = list(pages) if pages is not None else ev.product_pages(bundle)
    context = identity_context(bundle)
    for page in products:
        for node in products_on(page):
            category = category or _first_text([prop(node, "category")])
            sku = sku or _first_text([prop(node, "sku"), prop(node, "mpn")])
            for offer in offers_of(node):
                price = price or _first_text([offer_price(offer)])
                currency = currency or _first_text([offer_currency(offer)])
        # A worked example quotes the product's name back to the reader, so it
        # is held to the same identity rule as a generated question: the name
        # the page declares, or a heading the page corroborates - never a
        # heading alone.
        if not product and _usable_page(page):
            identity = item_identity(page, bundle, context)
            product = identity["name"] if identity else None
    if not category:
        for page in ev.category_pages(bundle):
            if not _is_populated_listing(page, bundle):
                continue
            headings = page.get("headings", []) or []
            category = _first_text([h.get("text") for h in headings
                                    if h.get("level") == 1])
            if category:
                break

    # Attributes: what this catalogue actually talks about, typed first.
    structured: List[str] = []
    visible: List[str] = []
    for page in products:
        structured.extend(structured_attribute_presence(page)["names"])
        visible.extend(visible_attribute_presence(page)["names"])

    def _dedupe(names: Sequence[str], drop_transactional: bool) -> List[str]:
        out: List[str] = []
        seen = set()
        for name in names:
            clean = util.collapse_ws(str(name)).strip(" :")
            if not clean or len(clean) > 40:
                continue
            key = clean.lower()
            if key in seen:
                continue
            if drop_transactional and key in _TRANSACTIONAL_LABELS:
                continue
            seen.add(key)
            out.append(clean)
        return out

    return {
        "origin": (bundle.get("site") or {}).get("origin") or "",
        "organization": org,
        "product": product,
        "category": category,
        "price": price,
        "currency": currency,
        "sku": sku,
        "structured_attributes": _dedupe(structured, False)[:12],
        "visible_attributes": _dedupe(visible, False)[:12],
        "comparable_attributes": _dedupe(visible + structured, True)[:12],
    }


def named(vocab: Dict[str, Any], key: str) -> str:
    """A vocabulary value, or the neutral placeholder when nothing was observed."""
    value = vocab.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return PLACEHOLDER.get(key, f"<{key}>")


def example_attributes(vocab: Dict[str, Any], limit: int = 3) -> List[str]:
    """Attribute names observed on the audited site, else a neutral placeholder."""
    names = [n for n in vocab.get("comparable_attributes") or [] if n]
    if names:
        return names[:limit]
    return [PLACEHOLDER["attribute"]]


def attribute_phrase(vocab: Dict[str, Any], limit: int = 3) -> str:
    """A readable list of this site's own attribute names, for prose."""
    names = example_attributes(vocab, limit)
    quoted = [f"'{n}'" for n in names]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


# ---------------------------------------------------------------------------
# evidence helpers
# ---------------------------------------------------------------------------

def observed(observation: str, url: str = "", locator: str = "",
             value: Any = None) -> EvidenceItem:
    return EvidenceItem(observation=observation, url=url, locator=locator,
                        value=value, kind="observation")


def absent(observation: str, url: str = "", locator: str = "") -> EvidenceItem:
    return EvidenceItem(observation=observation, url=url, locator=locator, kind="absence")


def measured(observation: str, value: Any = None, url: str = "") -> EvidenceItem:
    return EvidenceItem(observation=observation, value=value, url=url, kind="measurement")


def quote(text: str, url: str = "", locator: str = "") -> EvidenceItem:
    return EvidenceItem(observation=f'observed text: "{util.truncate(text, 200)}"',
                        url=url, locator=locator, kind="quote")


def page_items(pages: Sequence[dict], template: str, *, limit: int = 5,
               kind: str = "absence") -> List[EvidenceItem]:
    """One evidence item per affected page (capped), each carrying its URL."""
    items: List[EvidenceItem] = []
    for page in pages[:limit]:
        items.append(EvidenceItem(observation=template.format(url=label(page)),
                                  url=label(page), kind=kind))
    if len(pages) > limit:
        items.append(measured(
            f"...and {len(pages) - limit} further page(s) with the same observation",
            value=len(pages)))
    return items


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# applicability gates
# ---------------------------------------------------------------------------

def readable_pages(bundle: dict) -> List[dict]:
    """Pages the crawl actually parsed: fetched, HTML, and not an error."""
    return [p for p in ev.pages(bundle)
            if not p.get("fetch_failed") and not p.get("non_html")
            and int(p.get("status") or 0) < 400]


def crawl_yielded_evidence(bundle: dict, minimum: int = 1) -> bool:
    """Did this crawl obtain enough to reason about the site at all?

    Absence rules are only sound when the thing said to be absent was looked
    for. When a crawl returns nothing - the host refused, DNS failed, robots
    disallowed everything, the budget expired on the first request - every
    absence check is trivially "true" and the report fills with defects
    belonging to a site nobody read. This gate is the single place that
    distinguishes *observed absence* from *no observation*.
    """
    return len(readable_pages(bundle)) >= minimum


#: schema.org types whose presence is direct evidence of a catalogue.
_COMMERCE_TYPES = {"product", "productgroup", "individualproduct", "offer",
                   "aggregateoffer", "offercatalog", "onlinestore"}

#: schema.org types that mark a page as editorial rather than catalogue.
#: Recorded so the report can *say* why the commerce rules stood down, instead
#: of the reader having to infer it from their absence.
_EDITORIAL_TYPES = {"article", "newsarticle", "blogposting", "techarticle",
                    "reportagenewsarticle", "opinionnewsarticle", "liveblogposting",
                    "scholarlyarticle", "podcastepisode", "videoobject",
                    "collectionpage", "profilepage"}


def _lists_products(page: dict) -> bool:
    """Does this listing page point at products, or at articles?

    A storefront's collection page links to product-shaped URLs and usually
    prints prices beside them. A blog or news archive at the same URL shape
    does neither. One cheap test separates the two.
    """
    if page.get("prices_in_text"):
        return True
    for link in (page.get("links", {}) or {}).get("internal", []) or []:
        path = util.url_path(link.get("url", "")).lower()
        for pattern in _PRODUCT_URL_HINTS:
            if pattern.search(path):
                return True
    return False


#: Reuses the classifier's own product-URL vocabulary so the two never drift.
_PRODUCT_URL_HINTS = tuple(
    re.compile(pattern, re.I)
    for label, patterns in PAGE_TYPE_HINTS if label == "product"
    for pattern in patterns)


def commerce_evidence(bundle: dict) -> Dict[str, Any]:
    """How much evidence is there that this site sells things?

    Most rules in this marketplace describe a catalogue: prices, stock,
    variants, filters, specification tables. Run against a documentation site,
    a B2B SaaS marketing site or a brochure site they report a shop that was
    never there - a critical finding for having no Offer markup is a false
    positive on a site with nothing to offer.

    Three independent signals, all directly observed:

    * pages the classifier typed as ``product`` or ``category``;
    * commerce schema.org types anywhere in the crawl;
    * a cart or checkout affordance in a form action.

    Any one of them is enough to treat the site as a catalogue. None of them
    means the commerce rules do not apply, and the report says so rather than
    reporting their absence as a defect.
    """
    pages = readable_pages(bundle)
    readable = {id(p) for p in pages}
    typed_products = [p for p in ev.product_pages(bundle) if id(p) in readable]
    typed_categories = [p for p in ev.category_pages(bundle) if id(p) in readable]
    schema_pages = [p for p in pages
                    if {t.lower() for t in (p.get("jsonld_types") or [])} & _COMMERCE_TYPES]
    cart_pages = [p for p in pages if (p.get("forms", {}) or {}).get("has_cart_action")]
    signals = []
    if typed_products:
        signals.append(f"{len(typed_products)} page(s) classified as product pages")
    if typed_categories:
        signals.append(f"{len(typed_categories)} page(s) classified as category pages")
    if schema_pages:
        signals.append(f"{len(schema_pages)} page(s) declaring commerce schema.org types")
    if cart_pages:
        signals.append(f"{len(cart_pages)} page(s) with a cart or checkout form action")

    # A category page's *URL shape* is not evidence of a catalogue.
    # `/category/<slug>/` is the default WordPress archive path, so a
    # newspaper, a blog and a university news section all classify as
    # "category" without selling anything. Left as a sufficient signal it made
    # the catalogue rules fire on editorial sites - telling a newspaper to add
    # filters to "the attributes these product pages already publish".
    #
    # What a *storefront's* category page does, and an archive does not, is
    # point at products and quote prices. That is the distinction used here, so
    # a shop whose crawl reached only its collection pages is still audited as
    # a shop.
    listing_pages = [p for p in typed_categories if _lists_products(p)]
    if listing_pages:
        signals.append(f"{len(listing_pages)} category page(s) listing product links or prices")
    decisive = bool(typed_products or schema_pages or cart_pages or listing_pages)
    editorial = [p for p in pages
                 if {t.lower() for t in (p.get("jsonld_types") or [])} & _EDITORIAL_TYPES]
    if not decisive and typed_categories:
        signals.append(
            "category-shaped URLs only, with no product link, price, commerce markup or "
            "cart affordance on any of them"
            + (f"; {len(editorial)} page(s) declare article/editorial types" if editorial else "")
            + " - treated as non-commerce")
    return {
        "is_commerce": decisive,
        "signals": signals,
        "product_pages": len(typed_products),
        "category_pages": len(typed_categories),
        "schema_pages": len(schema_pages),
        "cart_pages": len(cart_pages),
        "pages_examined": len(pages),
    }


def commerce_guard(bundle: dict) -> bool:
    """Should catalogue-specific rules run against this site at all?"""
    return commerce_evidence(bundle)["is_commerce"]


# ---------------------------------------------------------------------------
# semantic applicability - the fine-grained gate every commerce rule uses
# ---------------------------------------------------------------------------
#
# `commerce_guard` answers the coarse question - does this site sell anything?
# It cannot answer the one that decides whether a rule *applies to a page*: a
# site that sells software and services still has product pages, and none of
# them owes anyone a delivery estimate or a stock statement. Each rule that
# describes a commerce expectation asks `aiva.semantics` per page, through the
# helpers below, and says in its evidence which pages were set aside and why.

def semantic_context(bundle: dict) -> Dict[str, Any]:
    """The site's semantic shape (see :func:`aiva.semantics.site_context`)."""
    from . import semantics
    return semantics.site_context(bundle)


class Partition:
    """The product pages an expectation applies to, and an account of the rest.

    ``pages`` are the pages the predicate accepted; ``set_aside`` maps each
    reason for exclusion to a page count; ``inferred`` counts the accepted
    pages whose kind was not established on the page itself but inferred
    from what the site as a whole is seen to sell. Iterating a Partition
    yields ``(pages, set_aside)``, so ``pages, aside = ...`` still reads.
    """

    def __init__(self, pages: List[dict], set_aside: Dict[str, int], inferred: int = 0):
        self.pages = pages
        self.set_aside = set_aside
        self.inferred = inferred

    def __iter__(self):
        yield self.pages
        yield self.set_aside

    @property
    def not_assessed(self) -> int:
        return sum(self.set_aside.values())

    def note(self, unit: str = "product page(s)") -> str:
        """The evidence sentence(s): what was set aside, and what was inferred."""
        text = set_aside_note(self.set_aside, unit)
        if self.inferred:
            text += (f" For {self.inferred} of the assessed page(s) the kind of item is not "
                     f"established on the page itself and was inferred from what the site as "
                     f"a whole is seen to sell.")
        return text


def product_pages_where(bundle: dict, predicate) -> Partition:
    """Product pages the applicability ``predicate`` accepts, and why the rest were not.

    ``predicate`` is one of the ``is_*_applicable(page, context)`` functions
    in :mod:`aiva.semantics`. The returned :class:`Partition` names, per
    reason, the pages it excluded, so the finding can state "3 product
    page(s) were not assessed: software, to which a delivery statement does
    not apply" - and how many it accepted by inference from the site.
    """
    context = semantic_context(bundle)
    kept: List[dict] = []
    set_aside: Dict[str, int] = {}
    inferred = 0
    for page in ev.product_pages(bundle):
        verdict = predicate(page, context)
        if verdict:
            kept.append(page)
            if verdict.get("basis") == "inferred":
                inferred += 1
        else:
            reason = str(verdict.get("reason") or "not applicable")
            set_aside[reason] = set_aside.get(reason, 0) + 1
    return Partition(kept, set_aside, inferred)


def set_aside_note(set_aside: Dict[str, int], unit: str = "product page(s)") -> str:
    """A sentence for the evidence naming what was not assessed, or ``""``."""
    if not set_aside:
        return ""
    parts = [f"{count} ({reason})" for reason, count in sorted(set_aside.items(),
                                                              key=lambda kv: (-kv[1], kv[0]))]
    total = sum(set_aside.values())
    return (f" {total} further {unit} were not assessed because the expectation does not "
            f"apply to them: " + "; ".join(parts[:4]) + ".")


#: Listing kinds to which catalogue affordances (filtering, sorting) apply.
_CATALOGUE_LISTING_KINDS = frozenset({"ecommerce_listing", "software_catalog",
                                      "marketplace_listing"})


def catalogue_listing_pages(bundle: dict) -> Tuple[List[dict], Dict[str, int]]:
    """Category pages that list things a visitor filters and sorts among.

    An article index, a documentation section, a podcast list and a service
    directory are listings too, and none of them owes anyone a price sort. A
    listing whose kind could not be established is kept only when the site
    is one that sells goods - the coarse guard - and set aside otherwise.
    """
    from . import semantics
    context = semantic_context(bundle)
    kept: List[dict] = []
    set_aside: Dict[str, int] = {}
    # The coarse commerce evidence counts here as well: a listing that points
    # at product pages or quotes prices is a catalogue listing even when the
    # crawl read none of the products it lists.
    sells_goods = bool(context.get("sells_physical_goods") or context.get("sells_digital_goods")
                       or context.get("sells_software") or context.get("is_marketplace")
                       or commerce_evidence(bundle)["is_commerce"])
    for page in ev.category_pages(bundle):
        record = semantics.listing_record(page, bundle, context)
        kind = record.get("subtype") or "unknown"
        # A listing of unknown kind is a catalogue listing only when it shows
        # the shape of one - product links or prices on the listing itself -
        # and the site sells goods. A page typed as a listing that lists
        # nothing of the kind is set aside and named.
        lists_goods = _lists_products(page)
        if kind in _CATALOGUE_LISTING_KINDS or (kind == "unknown" and sells_goods
                                                and lists_goods):
            kept.append(page)
        else:
            if kind != "unknown":
                reason = f"a {kind.replace('_', ' ')}, not a catalogue"
            elif not lists_goods:
                reason = ("no product links or prices were observed on the listing, so what "
                          "it lists could not be established")
            else:
                reason = ("what the listing lists could not be established and the site "
                          "sells no goods")
            set_aside[reason] = set_aside.get(reason, 0) + 1
    return kept, set_aside


#: How many entries a listing must show before sort and filter controls are
#: an expectation of it. A page of five items is scanned, not sorted.
LISTING_CONTROLS_MIN_ENTRIES = 8


def listing_entry_count(page: dict) -> int:
    """How many catalogue entries the listing visibly shows.

    Counts distinct internal links outside the site's navigation and footer
    that look like entries (a product-shaped URL, a price in the anchor text,
    or a repeated link into one section), ItemList elements, and distinct
    prices in the text; returns the largest. A listing that paginates is
    reported as at least :data:`LISTING_CONTROLS_MIN_ENTRIES`, since the set
    demonstrably exceeds the page.
    """
    links = (page.get("links", {}) or {}).get("internal", []) or []
    # Pagination is read from every link: `rel="next"` belongs in a <nav>,
    # which is exactly where the chrome filter would have dropped it.
    paginates = any(str(l.get("rel") or "").lower() in ("next", "prev", "previous")
                    for l in links)
    body_links = [l for l in links if not l.get("in_nav") and not l.get("in_footer")]
    entries = set()
    for link in body_links:
        if str(link.get("rel") or "").lower() in ("next", "prev", "previous"):
            continue
        url = str(link.get("url") or "")
        path = util.url_path(url).lower()
        text = str(link.get("text") or "")
        if PRICE_RE.search(text) or any(pat.search(path) for pat in _PRODUCT_URL_HINTS):
            entries.add(url.split("#")[0])
    distinct_prices = set()
    for item in page.get("prices_in_text") or []:
        value = item.get("value", item.get("raw", "")) if isinstance(item, dict) else item
        if value not in (None, ""):
            distinct_prices.add(str(value))
    counts = [len(entries), len(distinct_prices)]
    for node in jsonld_nodes(page):
        if str(node.get("@type") or "").lower() == "itemlist":
            elements = node.get("itemListElement")
            if isinstance(elements, list):
                counts.append(len(elements))
            number = node.get("numberOfItems")
            try:
                counts.append(int(number))
            except (TypeError, ValueError):
                pass
    if paginates:
        counts.append(LISTING_CONTROLS_MIN_ENTRIES)
    return max(counts)


def listing_controls_expected(page: dict) -> Tuple[bool, str]:
    """Are sort/filter affordances an expectation of this listing?

    Only where the listing shows a set large enough to need them - at least
    :data:`LISTING_CONTROLS_MIN_ENTRIES` entries, or pagination onward.
    """
    count = listing_entry_count(page)
    if count >= LISTING_CONTROLS_MIN_ENTRIES:
        return True, f"the listing shows {count} entries"
    return False, (f"only {count} entr{'y' if count == 1 else 'ies'} were observed on the "
                   f"listing, too few for sort or filter controls to be expected")


# ---------------------------------------------------------------------------
# listing provenance - which items a listing is a listing *of*
# ---------------------------------------------------------------------------
#
# A listing page and the product pages elsewhere in the crawl are different
# entities. Until the link between them is carried explicitly, "the attributes
# these product pages already publish" means "some product page, anywhere on
# this host" - and a recommendation on a handset family page came back naming
# a locator tag's diameter and operating temperature. Nothing in the rule was
# wrong about those attributes; they were read off a page the listing has
# nothing to do with. These three helpers carry the link.

def listing_members(page: dict, bundle: dict) -> List[dict]:
    """The crawled product pages this listing itself links to.

    Membership is read from the listing's *own body*: navigation and footer
    links are the site's chrome, repeated on every page, and say nothing about
    what this listing lists. Pagination links are not entries either. What is
    left is resolved against the pages the crawl actually read, so a member is
    a page whose content the audit can point at - never a URL it guessed at.

    The same discipline :func:`aiva.semantics.listing_semantics` uses to decide
    *what* a listing lists, reused to say *which items* it represents.
    """
    by_url: Dict[str, dict] = {}
    for other in bundle.get("pages") or []:
        for key in (other.get("url"), other.get("final_url")):
            if key:
                by_url[str(key)] = other
                normalized = util.normalize_url(str(key))
                if normalized:
                    by_url.setdefault(normalized, other)
    members: List[dict] = []
    seen: set = set()
    for link in ((page.get("links") or {}).get("internal") or []):
        if link.get("in_nav") or link.get("in_footer"):
            continue
        if str(link.get("rel") or "").lower() in ("next", "prev", "previous"):
            continue
        href = str(link.get("url") or "")
        if not href:
            continue
        target = by_url.get(href) or by_url.get(util.normalize_url(href) or href)
        if not target and ("?" in href or "#" in href):
            bare = href.split("#")[0].split("?")[0]
            target = by_url.get(bare) or by_url.get(util.normalize_url(bare) or bare)
        if not target or target is page or target.get("fetch_failed"):
            continue
        if target.get("page_type") != "product":
            continue
        key = str(target.get("url") or href)
        if key in seen:
            continue
        seen.add(key)
        members.append(target)
    return members


def collection_provenance(page: dict, bundle: dict) -> Dict[str, Any]:
    """What this audit can establish about the set a listing represents.

    Filtering and sorting are affordances of a *set*, and the advice that goes
    with them names things about that set: filter on these attributes, order
    by this dimension. Both are claims about items, so both need the items.

    Four observations establish a set, in descending order of directness:

    * product pages the listing links to were read, so the items are known;
    * the page declares an ``ItemList``/``OfferCatalog`` of two or more entries;
    * the listing paginates, so the set demonstrably exceeds this page;
    * the listing already carries filter or sort controls of its own, which is
      the site treating it as a collection.

    Returns ``{"members", "basis", "established"}``. Where none of the four
    holds, the page shows entries the audit counted and a set it cannot
    delimit - which is a real and reportable observation about the page, and
    is *not* a licence to describe the items. So the caller keeps its finding
    and drops every claim that would have to be about them: no attribute is
    named, no ordering dimension is asserted, and the evidence says which of
    the two situations this is.

    The distinction deliberately does not try to tell a catalogue listing from
    a product-family or marketing landing page by shape. On the evidence a
    crawl has - links, prices, headings - the two are the same page, and a
    rule that guessed between them would be a heuristic about page design
    rather than a statement about what was observed.
    """
    members = listing_members(page, bundle)
    if len(members) >= 2:
        return {"members": members, "established": True,
                "basis": f"{len(members)} product page(s) the listing links to were read, "
                         f"so the items it represents are known"}

    declared = 0
    for node in jsonld_nodes(page):
        if str(node.get("@type") or "").lower() not in ("itemlist", "offercatalog"):
            continue
        elements = node.get("itemListElement")
        if isinstance(elements, list):
            declared = max(declared, len(elements))
        try:
            declared = max(declared, int(node.get("numberOfItems")))
        except (TypeError, ValueError):
            pass
    if declared >= 2:
        return {"members": members, "established": True,
                "basis": f"the page declares an ItemList of {declared} entries"}

    links = (page.get("links", {}) or {}).get("internal", []) or []
    if any(str(l.get("rel") or "").lower() in ("next", "prev", "previous") for l in links):
        return {"members": members, "established": True,
                "basis": "the listing paginates, so the set exceeds this page"}

    controls = listing_controls(page)
    if controls["has_filter_controls"] or controls["has_sort_controls"]:
        return {"members": members, "established": True,
                "basis": "the listing already exposes filter or sort controls of its own"}

    return {"members": members, "established": False,
            "basis": ""}


def orderable_dimensions(bundle: dict, pages: Sequence[dict]) -> List[str]:
    """The dimensions these listings' own items can actually be ordered on.

    "Add sorting by price and by rating" is a claim about the items: it says
    those two values exist across the set. On a listing whose items publish no
    rating it is advice to sort on a field nobody has, and on a family or
    marketing page - where the items were never read - it is advice about
    items the audit never saw. Each dimension here is named only where the
    value behind it was observed: a price on the listing or on one of its
    members, an AggregateRating on a member.
    """
    found: List[str] = []
    priced = any(page.get("prices_in_text") for page in pages)
    rated = False
    for page in pages:
        for member in listing_members(page, bundle):
            for node in products_on(member):
                if any(offer_price(offer) for offer in offers_of(node)):
                    priced = True
            if find_nodes(jsonld_nodes(member), "AggregateRating", "Rating"):
                rated = True
    if priced:
        found.append("price")
    if rated:
        found.append("rating")
    return found


def catalogue_vocabulary(bundle: dict, pages: Sequence[dict]) -> Dict[str, Any]:
    """The site's nouns, read only from the items ``pages`` are listings of.

    The provenance rule for any recommendation aimed at a listing: an
    attribute may be named only when it was observed on a page that listing
    actually represents. Where no member page was read, the vocabulary comes
    back empty and the caller says nothing about attributes rather than
    reaching for whichever product the crawl read last.
    """
    members: List[dict] = []
    seen: set = set()
    for page in pages:
        for member in listing_members(page, bundle):
            key = str(member.get("url") or id(member))
            if key in seen:
                continue
            seen.add(key)
            members.append(member)
    return site_vocabulary(bundle, pages=members)


# ---------------------------------------------------------------------------
# raw vs browser-rendered evidence
# ---------------------------------------------------------------------------
#
# The audit's evidence is the server response, and that does not change. What
# changes is what an *absence* in it is allowed to be called. "Not in the HTML
# a fetch receives" and "not on the page" are two observations, and a report
# that prints the second when it measured the first is wrong in a way the site
# owner can see: the rating is right there, it just arrives after hydration.
#
# When the optional render pass ran (see :mod:`aiva.render`) each rendered page
# carries a `rendered` fact bag built by the *same* extractor, so one predicate
# can be asked of both and the answer named in one vocabulary.

#: What this audit observed about one fact on one page. Six states, no more:
#: three about where it was seen, one for "nowhere", and two that distinguish
#: "we looked in the browser and it was not there" from "we did not look".
VISIBILITY_STATES = ("server_and_rendered", "server_visible", "rendered_only",
                     "structured_only", "not_observed", "render_unavailable")

#: How each state reads in a finding. Never a claim about any external system:
#: each sentence says where this audit saw the fact, and nothing else.
VISIBILITY_PHRASE = {
    "server_and_rendered": "present in the server HTML and in the browser-rendered page",
    "server_visible": "present in the server HTML",
    "rendered_only": ("present in the browser-rendered page but not observed in the "
                      "server HTML"),
    "structured_only": "present only as structured data",
    "not_observed": "not observed in the server HTML",
    "render_unavailable": ("not observed in the server HTML; the browser-rendered state "
                           "was not measured"),
}


def render_state(page: dict) -> str:
    """``rendered`` | ``not_rendered`` - was this page's DOM measured at all?"""
    rendered = page.get("rendered")
    if isinstance(rendered, dict) and rendered.get("ok"):
        return "rendered"
    return "not_rendered"


def rendered_facts(page: dict) -> Optional[dict]:
    """This page's rendered fact bag, or ``None`` when it was not rendered.

    The bag has the same keys as the raw page, so every reader in this module -
    ``listing_controls``, ``products_on``, ``structured_attribute_presence`` -
    works on it with no change and no knowledge that a browser was involved.
    """
    rendered = page.get("rendered")
    if isinstance(rendered, dict) and rendered.get("ok"):
        return rendered
    return None


def fact_visibility(page: dict, probe, *, structured=None) -> Dict[str, Any]:
    """Where one audited fact was observed on one page.

    ``probe`` is a predicate over a fact bag - the same callable is asked of
    the raw page and of the rendered one, which is the whole point: there is
    one definition of "this page states the price", not a raw one and a
    rendered one that can drift apart. ``structured`` is an optional second
    predicate for the typed form of the same fact.

    Returns ``{"state", "raw", "rendered", "structured", "phrase"}`` where
    ``raw`` and ``structured`` are ``present``/``absent`` and ``rendered`` is
    ``present``/``absent``/``unavailable``. ``state`` is one of
    :data:`VISIBILITY_STATES`.

    Nothing here says anything about how any external system reads a page.
    """
    raw = bool(probe(page))
    typed = bool(structured(page)) if structured is not None else False
    facts = rendered_facts(page)
    if facts is None:
        rendered = "unavailable"
    else:
        rendered = "present" if probe(facts) else "absent"

    if raw and rendered == "present":
        state = "server_and_rendered"
    elif raw:
        state = "server_visible"
    elif rendered == "present":
        state = "rendered_only"
    elif typed:
        state = "structured_only"
    elif rendered == "unavailable":
        state = "render_unavailable"
    else:
        state = "not_observed"
    return {
        "state": state,
        "raw": "present" if raw else "absent",
        "rendered": rendered,
        "structured": "present" if typed else "absent",
        "phrase": VISIBILITY_PHRASE[state],
    }


def _states_price(facts: dict) -> bool:
    if facts.get("prices_in_text"):
        return True
    return any(offer_price(offer) for node in products_on(facts)
               for offer in offers_of(node))


def _states_availability(facts: dict) -> bool:
    text = str(facts.get("text") or "")
    if any(lexicon.mentions(concept, text)
           for concept in ("in_stock", "out_of_stock", "preorder")):
        return True
    return any(offer_availability(offer) for node in products_on(facts)
               for offer in offers_of(node))


def _states_purchase_control(facts: dict) -> bool:
    if (facts.get("mentions", {}) or {}).get("add_to_cart"):
        return True
    return bool((facts.get("forms", {}) or {}).get("has_cart_action"))


def _states_rating(facts: dict) -> bool:
    if find_nodes(jsonld_nodes(facts), "AggregateRating", "Review", "Rating"):
        return True
    return bool((facts.get("mentions", {}) or {}).get("reviews"))


#: The facts a raw/rendered comparison is worth making about, each with the
#: predicate that decides it. One table, read by every specialist that reports
#: an absence, so "the page states a price" means the same thing in the crawl
#: rule, the engagement rule and the answerability matrix - and means the same
#: thing of a rendered DOM as of a server response, because the same callable
#: is asked of both.
AUDITED_FACTS = (
    ("price", "a price", _states_price),
    ("availability", "a stock statement", _states_availability),
    ("purchase_control", "a buy control", _states_purchase_control),
    ("rating", "a rating or review content", _states_rating),
    ("specifications", "a specification block", lambda f: page_has_spec_block(f)),
    ("typed_product", "typed Product markup", lambda f: bool(products_on(f))),
    ("filter_controls", "a filter control",
     lambda f: listing_controls(f)["has_filter_controls"]),
    ("sort_controls", "a sort control",
     lambda f: listing_controls(f)["has_sort_controls"]),
)


def rendered_fact_gaps(page: dict) -> List[Dict[str, str]]:
    """Facts present in this page's rendered DOM and absent from its server HTML.

    Empty when the page was not rendered, and empty when rendering changed
    nothing - both of which are the answer, not a missing measurement.
    """
    if rendered_facts(page) is None:
        return []
    gaps = []
    for key, label_text, probe in AUDITED_FACTS:
        verdict = fact_visibility(page, probe)
        if verdict["state"] == "rendered_only":
            gaps.append({"fact": key, "label": label_text, "state": verdict["state"]})
    return gaps


def rendered_only(pages: Sequence[dict], probe) -> List[dict]:
    """The pages where ``probe`` holds of the rendered DOM but not the raw HTML.

    The population a finding must describe differently: on these pages the fact
    is not missing, it is missing *from the server response*.
    """
    return [p for p in pages if fact_visibility(p, probe)["state"] == "rendered_only"]


def render_coverage(bundle: dict) -> Dict[str, Any]:
    """What the optional render pass did, for the report's coverage block."""
    render = bundle.get("render", {}) or {}
    rendered_pages = [p for p in (bundle.get("pages") or []) if render_state(p) == "rendered"]
    return {
        "attempted": bool(render.get("attempted")),
        "available": bool(render.get("available")),
        "render_mode": render.get("render_mode") or "static-fetch",
        "viewport": render.get("viewport"),
        "pages_selected": int(render.get("pages_selected") or 0),
        "pages_rendered": len(rendered_pages),
        "pages_failed": int(render.get("pages_failed") or 0),
        "budget": render.get("budget") or {},
        "budget_exhausted": bool(render.get("budget_exhausted")),
        "elapsed_s": render.get("elapsed_s"),
        "unavailable_reason": render.get("unavailable_reason") or render.get("error"),
    }


def rendered_note(bundle: dict) -> str:
    """One sentence for a finding's evidence: was the rendered state measured?

    An absence claim reads differently depending on whether the browser was
    looked at, so the finding says which it is rather than leaving the reader
    to check the coverage block.
    """
    coverage = render_coverage(bundle)
    if not coverage["attempted"]:
        return (" This is the server response only; the browser-rendered state was not "
                "measured in this run.")
    if not coverage["available"]:
        return (" A browser-rendered comparison was requested but could not run"
                + (f" ({coverage['unavailable_reason']})" if coverage["unavailable_reason"]
                   else "")
                + ", so this is the server response only.")
    return (f" The browser-rendered state was also measured on "
            f"{coverage['pages_rendered']} page(s).")


def coverage_caveat(bundle: dict, *keywords: str) -> str:
    """Why a site-wide *absence* claim may be an artefact of the crawl.

    An absence rule says "nothing on this site does X". That is a claim about
    the whole site made from a bounded sample, and two things routinely make it
    wrong: robots.txt disallowed exactly the paths that would have shown X, or
    the crawl stopped early and never reached them. Both are already recorded
    in the bundle and, until now, no rule read them - so a site whose
    robots.txt disallows ``/faq`` was told it answers no questions.

    Returns a sentence to append to the evidence, or ``""`` when the crawl
    covered enough to support the claim. Callers should also step the severity
    down when this is non-empty: a coverage gap is a reason to be less certain,
    not a reason to stay silent.
    """
    parts: List[str] = []
    blocked = bundle.get("blocked_by_robots", []) or []
    if keywords:
        relevant = [b for b in blocked
                    if any(k.lower() in str(b.get("url", "")).lower() for k in keywords)]
    else:
        relevant = list(blocked)
    if relevant:
        sample = ", ".join(sorted({str(b.get("url", "")) for b in relevant})[:3])
        parts.append(f"{len(relevant)} URL(s) that would have been checked were disallowed by "
                     f"robots.txt and never fetched ({sample})")
    notes = bundle.get("notes", []) or []
    if any("budget" in str(n).lower() for n in notes):
        parts.append("the crawl stopped on its time budget before the frontier was exhausted")
    stats = bundle.get("stats", {}) or {}
    config = bundle.get("config", {}) or {}
    seen = sum(len(r.get("entries", []) or []) for r in (bundle.get("sitemaps", []) or []))
    fetched = stats.get("html_pages_parsed", 0) or 0
    if seen and fetched and seen > fetched * 3:
        parts.append(f"the site's sitemaps advertise {seen} URLs and this audit sampled "
                     f"{fetched} of them (page cap {config.get('max_pages', '?')})")
    if not parts:
        return ""
    return (" This is what the sampled pages show, not a proof about every page: "
            + "; ".join(parts) + ".")


def step_down(severity: str, caveat: str) -> str:
    """One severity level lower when the coverage caveat is non-empty."""
    if not caveat:
        return severity
    index = _SEVERITY_ORDER.index(severity)
    return _SEVERITY_ORDER[max(0, index - 1)] if index > 0 else severity


# ---------------------------------------------------------------------------
# report, downgrade or suppress - one decision, in one place
# ---------------------------------------------------------------------------
#
# A finding needs two things to be true, and they fail independently:
#
#   the condition exists      - something was actually observed
#   the condition applies     - the expectation belongs to this page
#
# Detecting a pattern establishes only the first. A listing with no filter
# control is a real observation; whether that listing is a comparable set worth
# filtering is a separate question, and answering it with the detector's own
# certainty is how an auditor reports a marketing page for missing a price
# sort. Confidence must follow the weaker of the two, not the stronger.
#
# Three outcomes, and the rule for choosing between them:
#
#   REPORT     both are evidenced
#   DOWNGRADE  the observation is real, the interpretation is uncertain -
#              lower the severity, lower the confidence, say what could not be
#              assessed, and describe nothing that rests on the missing half
#   SUPPRESS   the finding would mislead: the condition itself is not
#              established, or the expectation does not apply at all
#
# Centralised here so a specialist asks rather than re-deciding, and so the
# three words mean one thing across the marketplace.

REPORT = "report"
DOWNGRADE = "downgrade"
SUPPRESS = "suppress"

#: A downgraded finding can never be rated above this, whatever its ratio.
#: An observation whose interpretation is uncertain is not a blocker.
UNCERTAIN_APPLICABILITY_CEILING = "low"

#: ...and its confidence is capped here, so a reader can see at a glance that
#: the number describes the *interpretation* rather than the detector.
UNCERTAIN_APPLICABILITY_CONFIDENCE = 0.4


class Verdict:
    """What to do with one finding, and the words for why.

    Iterating yields ``(action, severity, confidence)`` so a rule can unpack
    it, and ``note`` is the sentence the evidence must carry when the
    interpretation is uncertain.
    """

    def __init__(self, action: str, severity: str, confidence: float, note: str = ""):
        self.action = action
        self.severity = severity
        self.confidence = confidence
        self.note = note

    def __iter__(self):
        yield self.action
        yield self.severity
        yield self.confidence

    def __bool__(self) -> bool:
        """True when the finding may be emitted at all."""
        return self.action != SUPPRESS

    @property
    def reported(self) -> bool:
        return self.action == REPORT

    @property
    def downgraded(self) -> bool:
        return self.action == DOWNGRADE

    def __repr__(self) -> str:                              # pragma: no cover
        return f"Verdict({self.action}, {self.severity}, {self.confidence})"


def applicability_verdict(*, observed: bool, applies: bool, severity: str,
                          confidence: float, uncertain_note: str = "") -> Verdict:
    """Report, downgrade or suppress, from the two halves of a finding.

    ``observed`` is whether the condition was actually seen; ``applies`` is
    whether the expectation belongs to the page it was seen on. Both true is a
    finding. Not observed is nothing to report. Observed but not established as
    applicable is a real observation whose meaning is not settled: it is
    reported at a lowered severity and a lowered confidence, carrying
    ``uncertain_note`` so the reader is told which half is missing rather than
    being handed a confident-looking defect.
    """
    if not observed:
        return Verdict(SUPPRESS, severity, confidence,
                       "the condition itself was not observed")
    if applies:
        return Verdict(REPORT, severity, confidence)
    lowered = severity
    ceiling = _SEVERITY_ORDER.index(UNCERTAIN_APPLICABILITY_CEILING)
    if _SEVERITY_ORDER.index(lowered) > ceiling:
        lowered = UNCERTAIN_APPLICABILITY_CEILING
    return Verdict(DOWNGRADE, lowered,
                   min(confidence, UNCERTAIN_APPLICABILITY_CONFIDENCE),
                   uncertain_note)


def conditional_advice(verdict: Verdict, *, intended_as: str, assertive: Dict[str, Any],
                       conditional: Dict[str, Any]) -> Dict[str, Any]:
    """The action for a finding, made conditional when applicability is not established.

    The inconsistency this closes: a finding's *title* would become properly
    cautious - "sort controls could not be assessed against a known comparable
    set" - while its *recommendation* went on saying "add a sort control",
    which is an instruction that presumes the very thing the title says was not
    established. A reader acts on the recommendation, so the caution has to
    reach it.

    A downgraded finding may still describe what was observed. What it may not
    do is introduce a dimension, an attribute, an intent or a business
    requirement that was never observed. So on a downgrade the ``conditional``
    body is used, phrased against ``intended_as`` - "if this page is intended
    to function as *a comparable catalogue*..." - which puts the premise back
    in the reader's hands where the evidence left it.

    Returns the keyword arguments for :func:`action`; the caller passes them
    through unchanged.
    """
    body = dict(conditional if verdict.downgraded else assertive)
    if verdict.downgraded:
        body.setdefault("priority", "low")
        body["summary"] = body["summary"].format(intended_as=intended_as)
        body["mechanism"] = body["mechanism"].format(intended_as=intended_as)
        body["steps"] = [step.format(intended_as=intended_as) for step in body["steps"]]
    return body


def sample_guard(sample: Sequence[Any], minimum: int = 1) -> bool:
    """Never assert an absence from a sample we did not actually take."""
    return len(sample) >= minimum


def confidence_for(affected: int, sampled: int, *, base: float = 0.95) -> float:
    """Lower confidence when the sample is small; never above ``base``."""
    if sampled <= 0:
        return 0.4
    coverage = min(1.0, sampled / 8.0)          # 8+ pages == full confidence
    consistency = affected / float(sampled)      # how universal the defect is
    value = base * (0.55 + 0.45 * coverage) * (0.7 + 0.3 * consistency)
    return round(min(base, max(0.35, value)), 2)


def severity_from_ratio(ratio: float, *, critical: float = 1.0, high: float = 0.6,
                        medium: float = 0.25) -> str:
    if ratio >= critical:
        return "critical"
    if ratio >= high:
        return "high"
    if ratio >= medium:
        return "medium"
    return "low"


#: A sample this size or larger can support a claim about a *template*.
#: Below it, "3 of 3" is three pages, not a pattern, and calling it
#: template-wide overstates what one or two URLs can show.
MIN_TEMPLATE_SAMPLE = 3

#: Severity ceilings by sample size. A single observation cannot establish a
#: site-wide blocker however complete the ratio looks: 1-of-1 is 100% of a
#: sample of one. Rules with genuinely site-wide evidence (robots.txt, a host
#: probe, the home page) do not route through here and keep their severity.
_SEVERITY_CEILING = ((1, "medium"), (2, "high"))

_SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")


def scope_for(affected: int, sampled: int) -> str:
    """How widely the observation reaches, without overstating a thin sample."""
    if sampled and affected >= sampled and sampled >= MIN_TEMPLATE_SAMPLE:
        return "template"
    if affected > 1:
        return "section"
    return "page"


def cap_severity(severity: str, sampled: int) -> str:
    """Lower a severity the sample size cannot support.

    Ratio-derived severity treats 1-of-1 and 12-of-12 identically, so a rule
    that saw a single product page could report a `critical` template defect.
    Coverage already scales *confidence*; this scales the label a reader acts
    on first, so a thin crawl produces cautious findings rather than confident
    wrong ones.
    """
    for threshold, ceiling in _SEVERITY_CEILING:
        if sampled <= threshold:
            if _SEVERITY_ORDER.index(severity) > _SEVERITY_ORDER.index(ceiling):
                return ceiling
            return severity
    return severity


def severity_from_sample(ratio: float, sampled: int, *, critical: float = 1.0,
                         high: float = 0.6, medium: float = 0.25) -> str:
    """``severity_from_ratio`` with the sample-size ceiling applied."""
    return cap_severity(severity_from_ratio(ratio, critical=critical, high=high,
                                            medium=medium), sampled)


# ---------------------------------------------------------------------------
# finding shorthand
# ---------------------------------------------------------------------------

def finding(rule_id: str, title: str, severity: str, pillar: str, *,
            evidence: str, items: List[EvidenceItem], action: SuggestedAction,
            urls: Optional[List[str]] = None, confidence: float = 0.9,
            metrics: Optional[Dict[str, Any]] = None,
            tags: Optional[List[str]] = None,
            interpretation: str = "") -> Finding:
    return make_finding(rule_id, title, severity, pillar, evidence=evidence,
                        action=action, items=items, urls=urls or [],
                        confidence=confidence, metrics=metrics or {}, tags=tags or [],
                        interpretation=interpretation)


def action(summary: str, *, priority: str = "medium", mechanism: str = "",
           steps: Optional[List[str]] = None, effort: str = "medium",
           impact: str = "medium", verification: str = "",
           verification_type: str = "self_verifiable", example: str = "",
           owner: str = "", references: Optional[List[str]] = None) -> SuggestedAction:
    return SuggestedAction(summary=summary, priority=priority, mechanism=mechanism,
                           steps=steps or [], effort=effort, impact=impact,
                           verification=verification,
                           verification_type=verification_type,
                           example=example, owner=owner,
                           references=references or [])


# ---------------------------------------------------------------------------
# redirect semantics
# ---------------------------------------------------------------------------
#
# A redirect is an *event*, and several different site behaviours produce one.
# Reading only the final URL cannot tell them apart, so three rules each read
# it their own way and a single intentional hop was reported as a duplicate
# host, a broken deep link and a chain defect at once.
#
# What separates them is the relationship between the requested URL, every hop
# in the chain, and the destination - scheme, host, locale segment and the path
# that survives. That relationship is computed once here and every rule reads
# the same answer.

#: A locale or market segment: `/in/en/`, `/en-gb/`, `/de/`, `/global/en/`.
#: Two letters is the whole test, plus the handful of market words that behave
#: like one. Deliberately not a country list: a list is a maintenance burden
#: that fails on the first market it has not heard of.
_LOCALE_SEGMENT_RE = re.compile(
    r"^(?:[a-z]{2}(?:[-_][a-z]{2})?|global|int|intl|www)$", re.I)

#: Filenames that mean "this directory". A redirect from `/x/` to `/x/index.html`
#: changes the URL and not the resource.
_DEFAULT_DOCS = ("index.html", "index.htm", "index.php", "default.html",
                 "default.htm", "home.html")

REDIRECT_KINDS = ("none", "canonical_representation", "canonical_host", "locale",
                  "homepage_collapse", "unrelated")


def _path_segments(path: str) -> List[str]:
    return [seg for seg in (path or "").split("/") if seg]


def _slug(segment: str) -> str:
    """A path segment with its separators and extension normalised away."""
    segment = re.sub(r"\.(?:html?|php|aspx?|jsp)$", "", segment.lower())
    return re.sub(r"[^a-z0-9]+", "", segment)


def _strip_locale(segments: Sequence[str]) -> List[str]:
    """Drop leading market segments so two paths can be compared on merit."""
    out = list(segments)
    while out and _LOCALE_SEGMENT_RE.match(out[0]):
        out.pop(0)
    return out


def _canonical_segments(path: str) -> List[str]:
    segments = _path_segments(path)
    if segments and segments[-1].lower() in _DEFAULT_DOCS:
        segments.pop()
    return [seg.lower() for seg in segments]


def _is_site_root(path: str) -> bool:
    """`/`, `/in/en/`, `/global/en/` - a front door rather than a document."""
    return not _strip_locale(_canonical_segments(path))


def classify_redirect(page: dict, origin: str = "") -> Dict[str, Any]:
    """What kind of redirect is this, and what in the chain says so?

    Returns ``{"kind", "hops", "why", "requested", "final", "locale_changed",
    "host_changed", "scheme_upgraded", "path_preserved"}``. ``kind`` is one of
    :data:`REDIRECT_KINDS`, and every one of them is a *different* thing for a
    site to have done:

    ``canonical_host``
        http to https, or www to apex (or back), with the path intact. The
        site is normalising its address, which is the behaviour the
        canonicalisation rules ask for - reporting it as a defect punishes a
        site for doing the right thing.
    ``locale``
        a market segment was added, removed or changed and the rest of the
        path survived: `/products/x` to `/in/en/products/x`. The resource is
        the same one, in a market.
    ``canonical_representation``
        the destination is the same resource written differently - a trailing
        slash, a default document, a case fold, or the page's own declared
        canonical.
    ``homepage_collapse``
        a deep path ended at a root or a market root, so whatever the URL
        promised is not what it served. This is the only kind the deep-link
        rule fires on.
    ``unrelated``
        the destination shares no path with the request and is not a root.
        Reported as an observation, because a retirement redirect to a
        replacement is legitimate and looks exactly like this from outside.
    """
    redirects = page.get("redirects") or []
    requested = page.get("url") or ""
    final = page.get("final_url") or requested
    result = {
        "kind": "none", "hops": len(redirects), "why": "",
        "requested": requested, "final": final,
        "host_changed": False, "scheme_upgraded": False,
        "locale_changed": False, "path_preserved": False,
        "cross_domain": False, "host_relationship": "same host",
    }
    if not redirects or not final or final == requested:
        return result

    from urllib.parse import urlsplit
    a, b = urlsplit(requested), urlsplit(final)
    a_segments, b_segments = _canonical_segments(a.path), _canonical_segments(b.path)
    a_bare, b_bare = _strip_locale(a_segments), _strip_locale(b_segments)

    result["host_changed"] = a.netloc.lower() != b.netloc.lower()
    result["scheme_upgraded"] = a.scheme == "http" and b.scheme == "https"
    result["locale_changed"] = (a_segments[:1] != b_segments[:1]
                                and (bool(_strip_locale(a_segments[:1]) == [])
                                     or bool(_strip_locale(b_segments[:1]) == [])))
    result["path_preserved"] = a_bare == b_bare

    same_registrable = (util.registrable_host(requested) == util.registrable_host(final)
                        if requested and final else False)
    same_site = util.same_site(requested, final) if requested and final else False
    host_is_variant = same_registrable and result["host_changed"]
    result["cross_domain"] = bool(result["host_changed"] and not same_site)
    result["host_relationship"] = ("same host" if not result["host_changed"] else
                                   "same site" if same_site else "another domain")

    # 0. A section moved to its own host: `/blog/...` on the apex ending at
    #    `blog.<site>/...`. The last stripped segment of the request survives
    #    as a label of the destination host, so the resource is the same one
    #    at a new address - not a deep path collapsing onto a front door.
    if result["host_changed"] and same_site and a_bare and not result["cross_domain"]:
        final_labels = b.netloc.lower().split(":")[0].split(".")
        if _slug(a_bare[0]) in {_slug(lbl) for lbl in final_labels[:-2]} and \
                (b_bare == a_bare[1:] or (not b_bare and len(a_bare) == 1)):
            result["path_preserved"] = True
            result["kind"] = "canonical_representation"
            result["why"] = "the section moved to its own host"
            return result

    # 1. The resource survived. Whatever else changed is an address, not a page.
    if result["path_preserved"]:
        if result["scheme_upgraded"] or host_is_variant:
            parts = []
            if result["scheme_upgraded"]:
                parts.append("http to https")
            if host_is_variant:
                parts.append(f"{a.netloc} to {b.netloc}")
            result["kind"] = "canonical_host"
            result["why"] = "the same path, " + " and ".join(parts)
            return result
        if result["locale_changed"]:
            result["kind"] = "locale"
            result["why"] = "the same path, in a different market segment"
            return result
        result["kind"] = "canonical_representation"
        result["why"] = "the same resource, written differently"
        return result

    # 2. A deep request that ended at a front door. The one collapse case.
    #    Across domains it is still a collapse - the deep link no longer
    #    resolves to its content - but it may be a migration whose old deep
    #    URLs were sent to the new home, and the reason says so.
    if b_bare == [] and a_bare != []:
        result["kind"] = "homepage_collapse"
        result["why"] = ("a deep path ended at "
                         + ("a market root" if b_segments else "the site root")
                         + (" of another domain" if result["cross_domain"] else ""))
        return result

    # 3. Root to root: a market selector sending a visitor to their storefront.
    if a_bare == [] and b_bare == []:
        result["kind"] = "locale" if b_segments else "canonical_host"
        result["why"] = "one front door redirecting to another"
        return result

    # 4. The page's own canonical says the destination is the right address.
    canonical = (page.get("canonical") or "").strip()
    if canonical:
        canonical_segments = _strip_locale(_canonical_segments(urlsplit(canonical).path))
        if canonical_segments == b_bare:
            result["kind"] = "canonical_representation"
            result["why"] = "the destination is the page's declared canonical"
            return result

    # 5. The last meaningful segment survived: `/x/velocity-x9` to
    #    `/shop/x/velocity-x9` is a route change, not a different thing.
    #    Separators are normalised away, because `buy_phone` and `buy-phone`
    #    are the same slug written by two generations of the same router.
    if a_bare and b_bare and _slug(a_bare[-1]) == _slug(b_bare[-1]):
        result["kind"] = "canonical_representation"
        result["why"] = "the destination names the same resource on a different route"
        return result

    result["kind"] = "unrelated"
    result["why"] = "the destination shares no path with the request"
    return result


def redirect_index(bundle: dict) -> Dict[str, Dict[str, Any]]:
    """Every redirected page in the bundle, classified once, keyed by URL."""
    origin = (bundle.get("site", {}) or {}).get("origin") or ""
    index = {}
    # Every requested URL, including a redirect endpoint typed `reference`:
    # a redirect is transport evidence whatever document it ended on.
    for page in ev.pages(bundle, include_errors=True, include_aliases=True,
                         include_utility=True):
        verdict = classify_redirect(page, origin)
        if verdict["kind"] != "none":
            index[page.get("url") or ""] = verdict
    return index
