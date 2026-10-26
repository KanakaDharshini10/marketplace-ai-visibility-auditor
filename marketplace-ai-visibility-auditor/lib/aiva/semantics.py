"""Semantic applicability: *what kind of thing* a page is about, and which
expectations therefore apply to it.

Page type is not enough. The classifier says a page is a ``product``; it does
not say whether the product is a pair of shoes, a desktop application, a
monthly plan, a plumbing service, a listing somebody else is selling, or a
manufacturer's information page with no way to buy. Every commerce expectation
- stock, shipping, returns, physical specifications, reviews, GTINs - is a
statement about *one* of those kinds, and applied to the others it is a
confident wrong finding: a documentation site told its downloads have no
delivery estimate, a government department asked for a return policy.

This module is the one place those distinctions are made:

* :func:`product_semantics` - the kind of item a product page is about
  (``physical``, ``digital``, ``software``, ``subscription``, ``service``,
  ``marketplace_listing``, ``informational``, ``ambiguous``), with the
  evidence and a confidence.
* :func:`listing_semantics` - what a category/listing page is a listing *of*.
* :func:`site_context` - the shape of the whole site, from the pages read.
* the applicability functions (:func:`is_shipping_applicable` and friends) -
  every rule that describes a commerce expectation asks here, so the decision
  is made once, in one testable place, instead of in a dozen ``if`` branches.
* :func:`classify_outbound_link` and :func:`entity_relationships` - which
  outbound links are official profiles rather than knowledge references or
  product listings, and how each named organisation relates to the site's own.
* :func:`transport_verdict` - the difference between "not found" and "could
  not be verified", stated once.

Every decision is evidence-based and deterministic: declared schema.org types
and properties first, then the page's own text, never the words in a URL and
never the name of any site. Where the evidence does not settle a question the
answer is ``ambiguous``/``unknown`` and every consumer treats that as "do not
assert", because an expectation nobody established is not a defect.

Nothing here reaches the network. The functions are pure over the evidence
bundle; the results are recorded in the bundle (``page["semantics"]`` and
``bundle["semantics"]``) so the report can show the reader how each decision
was reached.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from . import lexicon, util
from .extract import (KNOWLEDGE_HOSTS, LISTING_PAGE_TYPES, SHARE_INTENT_RE, find_nodes,
                      microdata_props, microdata_types, node_types, product_subjects, prop,
                      text_of)

__all__ = [
    "PRODUCT_SUBTYPES", "LISTING_SUBTYPES", "SITE_KINDS", "CONFIDENCE_LEVELS",
    "product_semantics", "listing_semantics", "page_semantics", "site_context",
    "annotate_bundle", "Applicability", "is_shipping_applicable",
    "is_returns_applicable", "is_stock_applicable", "is_physical_specs_applicable",
    "is_reviews_applicable", "is_price_applicable", "is_identifier_applicable",
    "is_purchase_cta_applicable", "is_comparison_applicable",
    "is_hidden_price_check_applicable",
    "is_site_search_expected", "is_breadcrumb_applicable", "freshness_expectation",
    "high_value_question_intents",
    "organization_field_expectation", "open_graph_expectation", "heading_assessment",
    "answerability_question_classes", "applicability_summary",
    "classify_outbound_link", "entity_relationships", "transport_verdict",
    "LINK_KINDS", "ENTITY_RELATIONSHIPS", "OPTIONAL_METADATA_CEILING",
    "page_record", "product_record", "listing_record", "site_organization_names",
    "cap_optional", "endpoint_kind",
]

PRODUCT_SUBTYPES = ("physical", "digital", "software", "subscription", "service",
                    "marketplace_listing", "informational", "ambiguous")

LISTING_SUBTYPES = ("ecommerce_listing", "content_listing", "documentation_section",
                    "article_index", "audio_listing", "service_listing",
                    "software_catalog", "marketplace_listing", "unknown")

#: What kind of thing the site as a whole is. One vocabulary, extended in
#: 1.10.1 with four kinds whose *expectations* differ from anything already
#: here rather than as new names for the same behaviour:
#:
#: * ``travel_hospitality`` - a stay or a booking is not a parcel, so delivery,
#:   stock and returns do not apply while amenities, location, cancellation and
#:   booking constraints do;
#: * ``developer_platform`` - repositories, APIs and code, where a collection
#:   of repositories is not a catalogue of goods;
#: * ``knowledge_reference`` - definitions, datasets and reference entries,
#:   which sell nothing at all;
#: * ``nonprofit`` - an organisation whose declared type is an NGO.
#:
#: Three of the names an operator might expect are already here under an older
#: spelling and were deliberately not renamed: ``software`` covers both a
#: software vendor and SaaS (``sells_subscriptions`` distinguishes them),
#: ``government`` is the public-body kind, and ``services`` is the
#: service-business kind. ``media_audio`` is carried by the ``audio_listing``
#: listing subtype on a ``publisher`` site.
SITE_KINDS = ("ecommerce", "marketplace", "travel_hospitality", "software", "services",
              "documentation", "developer_platform", "publisher", "government",
              "education", "community", "knowledge_reference", "nonprofit", "corporate",
              "mixed", "unknown")

CONFIDENCE_LEVELS = ("high", "medium", "low")

#: A finding that reports the *absence of optional metadata* can never be
#: rated above this. Missing Open Graph, a thin Organization node, an
#: undated home page, no site search: each is a gap worth naming and none is
#: a blocker, and rating it ``high`` said more than the evidence does.
OPTIONAL_METADATA_CEILING = "medium"

_SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")


def cap_optional(severity: str) -> str:
    """``severity``, lowered to :data:`OPTIONAL_METADATA_CEILING` if above it."""
    if severity not in _SEVERITY_ORDER:
        return severity
    if _SEVERITY_ORDER.index(severity) > _SEVERITY_ORDER.index(OPTIONAL_METADATA_CEILING):
        return OPTIONAL_METADATA_CEILING
    return severity


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _lower_types(node: Any) -> set:
    return {str(t).lower() for t in node_types(node)}


def _declared_types(page: dict) -> set:
    names = {str(t).lower() for t in (page.get("jsonld_types") or [])}
    names.update(microdata_types(page))
    og_type = str(((page.get("open_graph") or {}).get("og:type") or "")).lower()
    if og_type:
        names.add(og_type)
    return names


def _folded(text: Any) -> str:
    return util.collapse_ws(lexicon.fold(str(text or ""))).lower()


def _main_text(page: dict) -> str:
    text = page.get("main_text")
    if text is None:
        text = page.get("text") or ""
    return str(text)


def _phrases_present(text: str, phrases: Sequence[str], cap: int) -> List[str]:
    """Which of ``phrases`` occur in ``text`` as whole words, at most ``cap``."""
    found: List[str] = []
    for phrase in phrases:
        if len(found) >= cap:
            break
        pattern = r"(?<![\w])" + re.escape(lexicon.fold(phrase)).replace(r"\ ", r"[\s\-]+") \
            + r"(?![\w])"
        if re.search(pattern, text):
            found.append(phrase)
    return found


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _offers(node: dict) -> List[dict]:
    out: List[dict] = []
    for candidate in _as_list(prop(node, "offers")):
        if isinstance(candidate, dict):
            out.append(candidate)
            for inner in _as_list(prop(candidate, "offers")):
                if isinstance(inner, dict):
                    out.append(inner)
    return out


def _has_price(offer: dict) -> bool:
    for key in ("price", "lowPrice", "highPrice"):
        if text_of(prop(offer, key)):
            return True
    spec = prop(offer, "priceSpecification")
    for item in _as_list(spec):
        if isinstance(item, dict) and text_of(prop(item, "price")):
            return True
    return False


def _entity_name(value: Any) -> str:
    if isinstance(value, dict):
        return util.collapse_ws(str(text_of(prop(value, "name")) or ""))
    if isinstance(value, str) and not value.startswith(("#", "/", "http://", "https://")):
        return util.collapse_ws(value)
    if isinstance(value, list):
        for item in value:
            name = _entity_name(item)
            if name:
                return name
    return ""


def _names_match(a: str, b: str) -> bool:
    fa, fb = util.normalize_name(a), util.normalize_name(b)
    if not fa or not fb:
        return False
    return fa == fb or fa in fb or fb in fa


def _page_lang(page: dict) -> str:
    """The page's declared language: ``<html lang>``, else ``og:locale``, else
    the hreflang alternate that names this page's own URL."""
    lang = lexicon.normalize_language(page.get("lang"))
    if lang:
        return lang
    locale = str((page.get("open_graph") or {}).get("og:locale") or "")
    lang = lexicon.normalize_language(locale)
    if lang:
        return lang
    own = {page.get("url"), page.get("final_url")}
    for alternate in page.get("hreflang_alternates") or []:
        if isinstance(alternate, dict) and alternate.get("url") in own:
            code = lexicon.normalize_language(alternate.get("hreflang"))
            if code and code != "x":
                return code
    return ""


_SCRIPT_RANGES = (
    ("latin", re.compile(r"[A-Za-zÀ-ɏ]")),
    ("cyrillic", re.compile(r"[Ѐ-ӿ]")),
    ("greek", re.compile(r"[Ͱ-Ͽ]")),
    ("arabic", re.compile(r"[؀-ۿ]")),
    ("hebrew", re.compile(r"[֐-׿]")),
    ("devanagari", re.compile(r"[ऀ-ॿ]")),
    ("cjk", re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")),
    ("thai", re.compile(r"[฀-๿]")),
)


def _script_of(text: str) -> str:
    """The dominant writing system of a name, or ``""`` for none."""
    counts = {name: len(pattern.findall(text or "")) for name, pattern in _SCRIPT_RANGES}
    best = max(counts.items(), key=lambda kv: kv[1]) if counts else ("", 0)
    return best[0] if best[1] else ""


# ---------------------------------------------------------------------------
# product semantics
# ---------------------------------------------------------------------------

#: Declared types that settle the kind of item, by facet. Each is a statement
#: the page's own markup makes about what the thing *is*.
_SOFTWARE_TYPES = frozenset({"softwareapplication", "webapplication", "mobileapplication",
                             "videogame", "softwaresourcecode", "webapi"})
_DIGITAL_TYPES = frozenset({"digitaldocument", "mediaobject", "audiobook", "dataset",
                            "ebook", "musicrecording", "musicalbum", "course",
                            "videoobject", "audioobject", "imageobject"})
_SERVICE_TYPES = frozenset({"service", "financialproduct", "loanorcredit", "bankaccount",
                            "investmentordeposit", "paymentcard", "medicalprocedure",
                            "broadcastservice", "cableorsatelliteservice", "foodservice",
                            "governmentservice", "taxiservice", "webapiservice",
                            "professionalservice", "legalservice"})
_ACCOMMODATION_TYPES = frozenset({"accommodation", "lodgingbusiness", "apartment",
                                  "house", "room", "hotel", "hotelroom", "suite",
                                  "campingpitch", "touristattraction", "event"})
_PHYSICAL_DIMENSION_PROPS = ("weight", "width", "height", "depth", "size", "color",
                             "colour", "material", "pattern")
_PHYSICAL_IDENTIFIER_PROPS = ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "mpn", "isbn")
_SOFTWARE_PROPS = ("operatingsystem", "applicationcategory", "softwareversion",
                   "downloadurl", "installurl", "softwarerequirements",
                   "memoryrequirements", "storagerequirements", "releasenotes",
                   "filesize", "processorrequirements", "applicationsubcategory")
_SERVICE_PROPS = ("servicetype", "areaserved", "hoursavailable", "serviceoutput",
                  "provider", "termsofservice")
_SUBSCRIPTION_UNITS = frozenset({"mon", "ann", "day", "wee", "month", "year", "week",
                                 "p1m", "p1y", "p1w"})

#: Text corroboration, by facet. Vocabulary of *kinds of thing*, not of any
#: site: the words a page about software, a subscription or a service uses
#: about itself. Text only ever corroborates; a declared type decides.
_TEXT_SOFTWARE = ("system requirements", "release notes", "changelog", "download",
                  "install", "installer", "operating system", "macos", "windows 10",
                  "windows 11", "linux", "android", "ios", "app store", "google play",
                  "license key", "licence key", "open source", "source code",
                  "command line", "sdk", "plugin")
_TEXT_DIGITAL = ("instant download", "digital download", "downloadable", "ebook",
                 "e-book", "audiobook", "streaming", "stream now", "digital edition",
                 "pdf download", "digital copy", "online course", "digital product")
_TEXT_SUBSCRIPTION = ("per month", "/month", "/mo", "a month", "per year",
                      "/year", "/yr", "billed annually", "billed monthly",
                      "free trial", "start your free trial", "cancel anytime",
                      "pricing plans", "per user", "per seat", "subscription")
_TEXT_SERVICE = ("book an appointment", "book now", "get a quote", "request a quote",
                 "free quote", "consultation", "call-out", "callout", "hire us",
                 "our services", "service area", "areas we serve", "per hour",
                 "hourly rate", "estimate", "site visit")
_TEXT_MARKETPLACE = ("sold by", "seller", "sellers", "hosted by", "host:", "listed by",
                     "ships from", "dispatched by", "third-party seller", "vendor",
                     "other sellers", "buy from", "superhost", "guests", "check-in",
                     "check-out", "nightly", "per night")
_TEXT_INFORMATIONAL = ("where to buy", "find a retailer", "find a dealer", "find a stockist",
                       "stockists", "authorised dealer", "authorized dealer",
                       "available at retailers", "available from retailers",
                       "buy from a retailer", "contact sales", "request a demo")
_TEXT_PHYSICAL = ("dimensions", "weight", "material", "materials", "size guide",
                  "size chart", "colour", "color", "fabric", "washing instructions",
                  "assembly", "ships in", "delivery", "shipping", "in stock",
                  "out of stock", "add to cart", "add to basket", "add to bag")


def _subject_nodes(page: dict) -> List[dict]:
    subjects = product_subjects(page)
    if subjects:
        return subjects
    return find_nodes(page.get("jsonld_nodes") or [], "Product", "ProductGroup",
                      "IndividualProduct", "SoftwareApplication", "Service", "Book",
                      "Vehicle", "WebApplication", "MobileApplication")


def site_organization_names(pages: Iterable[dict]) -> List[str]:
    """Every name the site declares for an organisation or brand of its own."""
    return _site_org_names(pages)


def _site_org_names(pages: Iterable[dict]) -> List[str]:
    names: List[str] = []
    for page in pages:
        og = (page.get("open_graph") or {}).get("og:site_name")
        if og:
            names.append(util.collapse_ws(str(og)))
        for node in find_nodes(page.get("jsonld_nodes") or [], "Organization", "Corporation",
                               "OnlineStore", "Store", "LocalBusiness", "Brand",
                               "GovernmentOrganization", "NewsMediaOrganization",
                               "EducationalOrganization", "NGO"):
            name = text_of(prop(node, "name"))
            if name:
                names.append(util.collapse_ws(name))
    return util.dedupe(names)


def product_semantics(page: dict, site_names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The kind of item this product page is about, with its evidence.

    Returns ``{"subtype", "confidence", "evidence", "facets", "sells",
    "sell_evidence", "described_as"}``. ``subtype`` is one of
    :data:`PRODUCT_SUBTYPES`; ``facets`` is the score each kind accumulated,
    so a reader can see *how close* the decision was; ``sells`` says whether
    the page offers the thing for purchase at all, and when it does not the
    subtype is ``informational`` with ``described_as`` recording which kind
    of thing the page describes.

    Declared types and typed properties carry the decision; visible text only
    corroborates. Nothing here reads the URL, and no site is named anywhere.
    """
    page = page or {}
    facets: Dict[str, int] = {"physical": 0, "digital": 0, "software": 0,
                              "subscription": 0, "service": 0, "marketplace_listing": 0}
    evidence: List[str] = []
    site_names = list(site_names or [])

    def add(facet: str, weight: int, why: str) -> None:
        facets[facet] += weight
        evidence.append(f"{facet}: {why}")

    declared = _declared_types(page)
    subjects = _subject_nodes(page)
    nodes = page.get("jsonld_nodes") or []

    # 1. What the markup declares the thing to be.
    if declared & _SOFTWARE_TYPES:
        add("software", 4, "declares a software application type")
    if declared & _DIGITAL_TYPES:
        add("digital", 3, "declares a digital media/document type")
    if declared & _SERVICE_TYPES:
        add("service", 4, "declares a Service type")
    if declared & _ACCOMMODATION_TYPES and (declared & {"product", "offer"} or _offers_anywhere(nodes)):
        # A stay or a ticket is a service the page sells; it becomes a
        # *listing* only when someone other than the site is the seller,
        # which the seller/provider evidence below establishes.
        add("service", 3, "declares an accommodation/event type with an offer")

    # 2. Typed properties on the subject and its offers.
    sellers: List[str] = []
    for node in subjects:
        keys = {str(k).lower() for k in node.keys()}
        types = _lower_types(node)
        if types & _SOFTWARE_TYPES:
            add("software", 3, "the subject entity is software")
        if types & _SERVICE_TYPES:
            add("service", 3, "the subject entity is a Service")
        dims = [k for k in _PHYSICAL_DIMENSION_PROPS if k in keys]
        if dims:
            add("physical", min(3, len(dims)), f"typed physical attributes ({', '.join(dims[:3])})")
        ids = [k for k in _PHYSICAL_IDENTIFIER_PROPS if k in keys]
        if ids:
            add("physical", 1, f"manufacturer identifier ({ids[0]})")
        soft = [k for k in _SOFTWARE_PROPS if k in keys]
        if soft:
            add("software", min(3, len(soft)), f"software properties ({', '.join(soft[:3])})")
        serv = [k for k in _SERVICE_PROPS if k in keys]
        if serv and not (types & {"product", "productgroup"}):
            add("service", min(2, len(serv)), f"service properties ({', '.join(serv[:2])})")
        if "itemcondition" in keys:
            add("physical", 1, "itemCondition declared")
        if "hasvariant" in keys or "variesby" in keys:
            add("physical", 1, "a variant family is declared")
        book_format = _folded(text_of(prop(node, "bookFormat")))
        if book_format:
            if "ebook" in book_format or "audiobook" in book_format:
                add("digital", 3, f"bookFormat {book_format}")
            elif book_format:
                add("physical", 2, f"bookFormat {book_format}")
        for offer in _offers(node):
            okeys = {str(k).lower() for k in offer.keys()}
            if "shippingdetails" in okeys:
                add("physical", 3, "Offer.shippingDetails declared")
            if "hasmerchantreturnpolicy" in okeys:
                add("physical", 1, "a merchant return policy is declared")
            if "availability" in okeys or "inventorylevel" in okeys:
                add("physical", 1, "Offer.availability declared")
            if "deliverymethod" in okeys or "availabledeliverymethod" in okeys:
                method = _folded(text_of(prop(offer, "deliveryMethod", "availableDeliveryMethod")))
                if "download" in method:
                    add("digital", 3, "delivery method is direct download")
                else:
                    add("physical", 2, "a physical delivery method is declared")
            for spec in _as_list(prop(offer, "priceSpecification")):
                if not isinstance(spec, dict):
                    continue
                skeys = {str(k).lower() for k in spec.keys()}
                if skeys & {"billingduration", "billingincrement", "billingperiod"}:
                    add("subscription", 3, "a billing period is declared on the price")
                quantity = prop(spec, "referenceQuantity")
                unit = _folded(text_of(prop(quantity, "unitCode"))) if isinstance(quantity, dict) else ""
                if unit in _SUBSCRIPTION_UNITS:
                    add("subscription", 3, f"the price is per {unit}")
            category = _folded(text_of(prop(offer, "category")))
            if "subscription" in category:
                add("subscription", 2, "Offer.category names a subscription")
            seller_node = prop(offer, "seller", "offeredBy")
            seller = _entity_name(seller_node)
            if seller:
                sellers.append(seller)
                if isinstance(seller_node, dict) and "person" in _lower_types(seller_node):
                    add("marketplace_listing", 1, "the seller is an individual (Person)")
        provider = _entity_name(prop(node, "provider"))
        if provider and site_names and not any(_names_match(provider, s) for s in site_names):
            add("marketplace_listing", 1, f"provided by a third party ({provider[:40]})")

    foreign_sellers = [s for s in sellers
                       if site_names and not any(_names_match(s, n) for n in site_names)]
    if foreign_sellers:
        add("marketplace_listing", 3, f"offered by a seller other than the site "
                                      f"({util.dedupe(foreign_sellers)[0][:40]})")
    if len(set(util.normalize_name(s) for s in sellers)) >= 2:
        add("marketplace_listing", 3, f"{len(set(sellers))} distinct sellers in the offers")
    if find_nodes(nodes, "OfferShippingDetails", "ShippingDeliveryTime"):
        add("physical", 3, "OfferShippingDetails node present")
    if find_nodes(nodes, "MerchantReturnPolicy"):
        add("physical", 1, "MerchantReturnPolicy node present")

    # 3. Text corroboration - the page's own words about what it offers.
    text = lexicon.fold(_main_text(page)[:20000])
    for facet, phrases, cap in (("software", _TEXT_SOFTWARE, 2), ("digital", _TEXT_DIGITAL, 2),
                                ("subscription", _TEXT_SUBSCRIPTION, 3),
                                ("service", _TEXT_SERVICE, 2),
                                ("marketplace_listing", _TEXT_MARKETPLACE, 2),
                                ("physical", _TEXT_PHYSICAL, 2)):
        found = _phrases_present(text, phrases, cap)
        if found:
            add(facet, len(found), "page text mentions " + ", ".join(f"'{f}'" for f in found))
    if lexicon.mentions("shipping", text):
        add("physical", 1, "delivery/shipping wording on the page")
    availability = page.get("availability_text") or {}
    if any(availability.get(k) for k in ("in_stock", "out_of_stock", "preorder", "limited")):
        add("physical", 1, "a stock statement in the page text")
    variants = page.get("variants") or {}
    if variants.get("variant_swatches") or variants.get("variant_selects"):
        add("physical", 1, "size/colour option controls")

    # 4. Does the page sell the thing at all?
    sell_evidence: List[str] = []
    forms = page.get("forms") or {}
    if any(_has_price(o) for n in subjects for o in _offers(n)):
        sell_evidence.append("a priced Offer in the markup")
    if forms.get("cart_actions_in_main") or forms.get("has_cart_action_in_main"):
        sell_evidence.append("a purchase control in the content region")
    elif forms.get("has_cart_action"):
        sell_evidence.append("a cart form on the page")
    from .extract import PRICE_RE
    if PRICE_RE.search(_main_text(page)[:20000]):
        sell_evidence.append("a currency-formatted price in the content")
    if (page.get("mentions") or {}).get("add_to_cart"):
        sell_evidence.append("add-to-cart wording")
    if facets["subscription"] >= 3 and PRICE_RE.search(page.get("text") or ""):
        sell_evidence.append("plan pricing")
    informational_hits = _phrases_present(text, _TEXT_INFORMATIONAL, 2)
    sells = bool(sell_evidence)
    # A cart is a goods affordance: services are booked, software is
    # downloaded, plans are subscribed to, listings name their seller. A page
    # that puts its item in a basket and shows no sign of any of those is
    # read as goods - weakly, so that one more physical signal (a stock line,
    # a size, a delivery sentence) is needed before the kind is asserted.
    has_cart = bool(forms.get("cart_actions_in_main") or forms.get("has_cart_action_in_main")
                    or forms.get("has_cart_action"))
    if has_cart and not any(facets[k] for k in ("digital", "software", "subscription",
                                                 "service", "marketplace_listing")):
        add("physical", 1, "a cart control and no sign of a download, plan, service or "
                           "third-party seller")

    described = max(facets.items(), key=lambda kv: (kv[1], -list(facets).index(kv[0])))
    ordered = sorted(facets.values(), reverse=True)
    top, second = ordered[0], (ordered[1] if len(ordered) > 1 else 0)
    if top == 0:
        described_as, confidence = "ambiguous", "low"
    elif top >= 4 and top >= second + 2:
        described_as, confidence = described[0], "high"
    elif top >= 2 and top > second:
        described_as, confidence = described[0], "medium"
    else:
        described_as, confidence = "ambiguous", "low"

    if not sells:
        subtype = "informational"
        if informational_hits:
            evidence.append("informational: page text mentions "
                            + ", ".join(f"'{f}'" for f in informational_hits))
            info_confidence = "high" if described_as != "ambiguous" else "medium"
        else:
            info_confidence = "medium" if described_as != "ambiguous" else "low"
        return {"subtype": subtype, "confidence": info_confidence, "evidence": evidence,
                "facets": facets, "sells": False, "sell_evidence": [],
                "described_as": described_as,
                "points_elsewhere": bool(informational_hits),
                "decided_by": "no price, offer or purchase control: the page describes "
                              "the item without offering it for sale"}
    return {"subtype": described_as, "confidence": confidence, "evidence": evidence,
            "facets": facets, "sells": True, "sell_evidence": sell_evidence,
            "described_as": described_as, "points_elsewhere": False,
            "decided_by": (f"{described_as} scored {top} against {second} for the next kind"
                           if described_as != "ambiguous" else
                           "no kind of item is established by the markup or the text")}


def _offers_anywhere(nodes: Iterable[dict]) -> bool:
    return bool(find_nodes(nodes, "Offer", "AggregateOffer"))


# ---------------------------------------------------------------------------
# listing semantics
# ---------------------------------------------------------------------------

_ARTICLE_TYPES = frozenset({"article", "newsarticle", "blogposting", "reportagenewsarticle",
                            "opinionnewsarticle", "liveblogposting", "scholarlyarticle",
                            "report", "howto"})
_DOC_TYPES = frozenset({"techarticle", "apireference", "howto"})
_AUDIO_TYPES = frozenset({"podcastepisode", "podcastseries", "audioobject",
                          "musicrecording", "musicalbum", "episode", "radioepisode",
                          "radioseries"})


def _item_element_types(page: dict) -> List[str]:
    """Types of the entries a listing page's ItemList/CollectionPage names."""
    out: List[str] = []
    for node in page.get("jsonld_nodes") or []:
        if not (_lower_types(node) & {"itemlist", "collectionpage", "offercatalog"}):
            continue
        for element in _as_list(prop(node, "itemListElement", "hasPart", "mainEntity")):
            if not isinstance(element, dict):
                continue
            item = prop(element, "item")
            for candidate in ([item] if isinstance(item, dict) else [element]):
                out.extend(_lower_types(candidate))
    return out


def listing_semantics(page: dict, bundle: Optional[dict] = None) -> Dict[str, Any]:
    """What a category/listing page is a listing *of*.

    Reads the declared entry types of the page's ItemList, the types the
    crawl assigned to the pages it links to (and their product semantics),
    and price density. Returns ``{"subtype", "confidence", "evidence"}`` with
    ``subtype`` in :data:`LISTING_SUBTYPES`; ``unknown`` when nothing settles
    it, which every consumer treats as "assert nothing".
    """
    page = page or {}
    scores: Dict[str, int] = {k: 0 for k in LISTING_SUBTYPES if k != "unknown"}
    evidence: List[str] = []

    def add(kind: str, weight: int, why: str) -> None:
        scores[kind] += weight
        evidence.append(f"{kind}: {why}")

    entry_types = set(_item_element_types(page))
    if entry_types & {"product", "productgroup", "individualproduct"}:
        add("ecommerce_listing", 3, "ItemList entries are Products")
    if entry_types & _SOFTWARE_TYPES:
        add("software_catalog", 3, "ItemList entries are software applications")
    if entry_types & _SERVICE_TYPES:
        add("service_listing", 3, "ItemList entries are Services")
    if entry_types & _AUDIO_TYPES:
        add("audio_listing", 3, "ItemList entries are audio episodes/recordings")
    if entry_types & _DOC_TYPES:
        add("documentation_section", 3, "ItemList entries are technical articles")
    elif entry_types & _ARTICLE_TYPES:
        add("article_index", 3, "ItemList entries are articles")
    if entry_types & _ACCOMMODATION_TYPES:
        add("marketplace_listing", 3, "ItemList entries are accommodation/event listings")

    declared = _declared_types(page)
    if declared & {"blog"}:
        add("article_index", 2, "the page declares itself a Blog")
    if declared & {"podcastseries", "radioseries"}:
        add("audio_listing", 2, "the page declares a podcast/radio series")

    # What the crawl read at the other end of the listing's links.
    if bundle:
        by_url: Dict[str, dict] = {}
        for other in bundle.get("pages") or []:
            for key in (other.get("url"), other.get("final_url")):
                if key:
                    by_url[key] = other
        linked_kinds: Dict[str, int] = {}
        counted: set = set()
        for link in ((page.get("links") or {}).get("internal") or []):
            # A listing is what its *entries* link to. Links in the site's
            # navigation or footer are the site's chrome, repeated on every
            # page, and say nothing about this listing.
            if link.get("in_nav") or link.get("in_footer"):
                continue
            href = str(link.get("url") or "")
            target = by_url.get(href)
            if not target and ("?" in href or "#" in href):
                target = by_url.get(href.split("#")[0].split("?")[0])
            if not target or target is page or target.get("fetch_failed"):
                continue
            entry_key = target.get("url") or href
            if entry_key in counted:
                continue
            counted.add(entry_key)
            ptype = target.get("page_type")
            if ptype == "product":
                sem = target.get("semantics") or {}
                record = sem.get("product") if isinstance(sem, dict) else None
                if not record:
                    record = product_semantics(target)
                sub = record.get("subtype")
                described = record.get("described_as")
                key = sub if sub not in ("informational", "ambiguous") else (described or sub)
                linked_kinds[key or "ambiguous"] = linked_kinds.get(key or "ambiguous", 0) + 1
            elif ptype == "article":
                types = _declared_types(target)
                key = "documentation" if types & _DOC_TYPES else "article"
                linked_kinds[key] = linked_kinds.get(key, 0) + 1
            else:
                # An episode, a definition, a dataset or a repository is not a
                # product and not an article, and a page listing them is not a
                # catalogue. Read from the entry's own declared type only.
                types = _declared_types(target)
                if types & _AUDIO_TYPES:
                    linked_kinds["audio"] = linked_kinds.get("audio", 0) + 1
                elif types & _DOC_TYPES:
                    linked_kinds["documentation"] = linked_kinds.get("documentation", 0) + 1
                elif types & _REFERENCE_TYPES or types & _DEVELOPER_TYPES:
                    linked_kinds["reference"] = linked_kinds.get("reference", 0) + 1
        for kind, count in sorted(linked_kinds.items()):
            if count < 1:
                continue
            # One classified entry is a real observation about the listing's
            # own body (chrome links are excluded above); three settle it.
            weight = min(3, count + 1)
            if kind in ("physical", "digital"):
                add("ecommerce_listing", weight, f"links to {count} {kind}-goods product page(s)")
            elif kind == "software":
                add("software_catalog", weight, f"links to {count} software product page(s)")
            elif kind == "subscription":
                add("software_catalog", weight, f"links to {count} subscription/plan page(s)")
            elif kind == "service":
                add("service_listing", weight, f"links to {count} service page(s)")
            elif kind == "marketplace_listing":
                add("marketplace_listing", weight, f"links to {count} third-party listing(s)")
            elif kind == "documentation":
                add("documentation_section", weight, f"links to {count} technical article(s)")
            elif kind == "article":
                add("article_index", weight, f"links to {count} article page(s)")
            elif kind == "audio":
                add("audio_listing", weight, f"links to {count} audio episode(s)")
            elif kind == "reference":
                add("content_listing", weight,
                    f"links to {count} reference or source-code page(s)")
    prices = page.get("prices_in_text") or []
    if len(prices) >= 3 and not (scores["article_index"] or scores["documentation_section"]):
        add("ecommerce_listing", 1, f"{len(prices)} prices in the page text")

    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], LISTING_SUBTYPES.index(kv[0])))
    top_kind, top = ordered[0]
    second = ordered[1][1] if len(ordered) > 1 else 0
    if top == 0 or top == second:
        return {"subtype": "unknown", "confidence": "low", "evidence": evidence,
                "decided_by": "nothing establishes what the listing is a listing of"}
    confidence = "high" if top >= 3 and top >= second + 2 else ("medium" if top >= 2 else "low")
    if confidence == "low":
        return {"subtype": "unknown", "confidence": "low", "evidence": evidence,
                "decided_by": f"only weak evidence for {top_kind}"}
    return {"subtype": top_kind, "confidence": confidence, "evidence": evidence,
            "decided_by": f"{top_kind} scored {top} against {second}"}


# ---------------------------------------------------------------------------
# per-page record and bundle annotation
# ---------------------------------------------------------------------------

SEMANTICS_VERSION = 1

_ENDPOINT_KINDS = {
    "search": "utility", "account": "utility", "tool": "utility",
    "reference": "alias", "error": "error", "non_html": "non_html",
}
_ENDPOINT_KINDS.update({kind: "listing" for kind in LISTING_PAGE_TYPES})


def endpoint_kind(page: dict) -> str:
    """``content`` | ``listing`` | ``utility`` | ``alias`` | ``error`` | ``non_html``."""
    if page.get("fetch_failed"):
        return "error"
    if page.get("non_html"):
        return "non_html"
    return _ENDPOINT_KINDS.get(str(page.get("page_type") or ""), "content")


def page_semantics(page: dict, bundle: Optional[dict] = None,
                   site_names: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The semantic record for one page; cached on the page under ``semantics``."""
    cached = page.get("semantics")
    if isinstance(cached, dict) and cached.get("version") == SEMANTICS_VERSION:
        return cached
    record: Dict[str, Any] = {"version": SEMANTICS_VERSION,
                              "endpoint": endpoint_kind(page)}
    if page.get("fetch_failed") or page.get("non_html"):
        page["semantics"] = record
        return record
    page_type = str(page.get("page_type") or "")
    if page_type == "product" or _subject_nodes(page):
        record["product"] = product_semantics(page, site_names)
    if page_type in LISTING_PAGE_TYPES:
        record["listing"] = listing_semantics(page, bundle)
    record["lang"] = _page_lang(page)
    page["semantics"] = record
    return record


def annotate_bundle(bundle: dict) -> dict:
    """Record page and site semantics in the bundle, once, and return the site context.

    Called by the collector after classification and by :func:`site_context`
    for bundles that predate it (test fixtures, older bundle files). Pure over
    the bundle's pages, so a re-run gives the same answer.
    """
    pages = [p for p in bundle.get("pages") or [] if isinstance(p, dict)]
    names = _site_org_names(p for p in pages if not p.get("fetch_failed"))
    # Product pages first, so a listing can read the subtype of what it links to.
    for page in pages:
        if page.get("page_type") == "product" or (
                not page.get("fetch_failed") and _subject_nodes(page)):
            page_semantics(page, bundle, names)
    for page in pages:
        page_semantics(page, bundle, names)
    context = _build_site_context(bundle, pages, names)
    bundle["semantics"] = context
    return context


#: Bundles that arrived without semantics (test fixtures, bundle files
#: written by an earlier version) are annotated on a *shadow* - a shallow
#: copy of the bundle and of each page - so a specialist never writes into
#: the shared evidence it was handed. The shadow is kept here, keyed by the
#: bundle's identity and fingerprinted by its page objects, so the work is
#: done once per bundle rather than once per rule.
_LAZY_CACHE: Dict[int, Tuple[tuple, Dict[str, Any]]] = {}
_LAZY_CACHE_LIMIT = 16


def _fingerprint(bundle: dict) -> tuple:
    pages = bundle.get("pages") or []
    return (len(pages), tuple(id(p) for p in pages),
            tuple(str(p.get("url")) for p in pages if isinstance(p, dict)))


def _shadow_context(bundle: dict) -> Dict[str, Any]:
    key = id(bundle)
    print_ = _fingerprint(bundle)
    cached = _LAZY_CACHE.get(key)
    if cached and cached[0] == print_:
        return cached[1]
    shadow = dict(bundle)
    shadow["pages"] = [dict(p) if isinstance(p, dict) else p for p in bundle.get("pages") or []]
    context = annotate_bundle(shadow)
    # The per-page records live on the shadow pages; keep them reachable by
    # URL for consumers holding the original page dicts.
    context["_page_records"] = {
        str(p.get("url")): p.get("semantics") for p in shadow["pages"]
        if isinstance(p, dict) and p.get("semantics")}
    if len(_LAZY_CACHE) >= _LAZY_CACHE_LIMIT:
        _LAZY_CACHE.pop(next(iter(_LAZY_CACHE)))
    _LAZY_CACHE[key] = (print_, context)
    return context


def site_context(bundle: dict) -> Dict[str, Any]:
    """The site's semantic shape.

    Read from the bundle when the collector recorded it there; otherwise
    computed on a shadow copy (see :data:`_LAZY_CACHE`) so the bundle a
    specialist was handed is never mutated.
    """
    cached = bundle.get("semantics")
    if isinstance(cached, dict) and cached.get("version") == SEMANTICS_VERSION:
        return cached
    return _shadow_context(bundle)


def page_record(page: dict, ctx: Optional[dict] = None) -> Dict[str, Any]:
    """The semantic record for a page: from the page itself when annotated,
    else from the shadow the context was built on, else computed."""
    record = page.get("semantics")
    if isinstance(record, dict) and record.get("version") == SEMANTICS_VERSION:
        return record
    shadow = (ctx or {}).get("_page_records") or {}
    found = shadow.get(str(page.get("url")))
    if isinstance(found, dict):
        return found
    names = (ctx or {}).get("organization_names") or []
    record = {"version": SEMANTICS_VERSION, "endpoint": endpoint_kind(page),
              "lang": _page_lang(page)}
    if not (page.get("fetch_failed") or page.get("non_html")):
        if str(page.get("page_type") or "") == "product" or _subject_nodes(page):
            record["product"] = product_semantics(page, names)
        if str(page.get("page_type") or "") in LISTING_PAGE_TYPES:
            record["listing"] = listing_semantics(page)
    return record


def product_record(page: dict, ctx: Optional[dict] = None) -> Dict[str, Any]:
    """The product-kind record for a page (see :func:`product_semantics`)."""
    record = page_record(page, ctx).get("product")
    if record:
        return record
    return product_semantics(page, (ctx or {}).get("organization_names") or [])


def listing_record(page: dict, bundle: Optional[dict] = None,
                   ctx: Optional[dict] = None) -> Dict[str, Any]:
    """The listing-kind record for a page (see :func:`listing_semantics`)."""
    record = page_record(page, ctx).get("listing")
    if record:
        return record
    return listing_semantics(page, bundle)


# ---------------------------------------------------------------------------
# site context
# ---------------------------------------------------------------------------

_GOV_ORG_TYPES = frozenset({"governmentorganization", "governmentoffice",
                            "governmentservice", "governmentbenefitstype"})
_PUBLISHER_ORG_TYPES = frozenset({"newsmediaorganization"})
_EDU_ORG_TYPES = frozenset({"educationalorganization", "collegeoruniversity", "school",
                            "highschool", "elementaryschool", "middleschool", "preschool"})
_COMMUNITY_TYPES = frozenset({"discussionforumposting", "qapage", "socialmediaposting"})
#: Declared types that make a page about a stay, a trip or a visit rather than
#: about a parcel. `_ACCOMMODATION_TYPES` already collects the listing shapes;
#: these are the *organisation* and *booking* shapes beside them.
_TRAVEL_TYPES = frozenset({"lodgingbusiness", "hotel", "motel", "hostel", "resort",
                           "bedandbreakfast", "campground", "vacationrental",
                           "touristattraction", "touristdestination", "travelagency",
                           "lodgingreservation", "flightreservation", "trainreservation",
                           "busreservation", "rentalcarreservation", "reservation",
                           "trip", "touristtrip", "accommodation"})
#: Source code, APIs and the things a developer platform publishes.
_DEVELOPER_TYPES = frozenset({"softwaresourcecode", "webapi", "apireference",
                              "softwarelibrary", "computerlanguage"})
#: Reference works: definitions, datasets, scholarship. None of them is for sale.
_REFERENCE_TYPES = frozenset({"definedterm", "definedtermset", "dataset", "datacatalog",
                              "scholarlyarticle", "thesis", "archivecomponent",
                              "collection", "citation"})
#: Audio publishing, which is a publisher that ships no parcels.
_AUDIO_PUBLISHING_TYPES = frozenset({"podcastseries", "podcastepisode", "radioseries",
                                     "radioepisode", "audioobject"})

#: Public-suffix facts about who may register a host. Not a list of sites:
#: a registry rule about a kind of organisation, used only to corroborate a
#: declared type, never to decide on its own.
_GOV_HOST_SUFFIXES = (".gov", ".gov.uk", ".gov.au", ".gov.in", ".gov.sg", ".gov.br",
                      ".gouv.fr", ".gc.ca", ".mil", ".go.jp", ".gov.ie", ".govt.nz",
                      ".gob.es", ".gob.mx", ".gov.za", ".go.kr", ".gov.it", ".gv.at",
                      ".admin.ch", ".gov.pl", ".gov.nl", ".bund.de")
_EDU_HOST_SUFFIXES = (".edu", ".ac.uk", ".edu.au", ".ac.in", ".ac.jp", ".edu.sg",
                      ".ac.nz", ".edu.br", ".ac.za", ".edu.mx", ".ac.kr", ".edu.cn")


def _host_suffix_matches(host: str, suffixes: Sequence[str]) -> bool:
    host = (host or "").lower()
    return any(host == s.lstrip(".") or host.endswith(s) for s in suffixes)


def _physical_presence(pages: Iterable[dict]) -> Tuple[bool, str]:
    for page in pages:
        for node in page.get("jsonld_nodes") or []:
            types = _lower_types(node)
            if types & {"localbusiness", "store", "place", "postaladdress"} and (
                    types & {"postaladdress"} or prop(node, "address")):
                return True, "a LocalBusiness/Place with an address is declared"
            if types & {"organization", "corporation", "onlinestore",
                        "governmentorganization", "educationalorganization"} \
                    and prop(node, "address"):
                return True, "the Organization declares a postal address"
        for record in _as_list(page.get("microdata")):
            if isinstance(record, dict) and microdata_props(record).get("address"):
                return True, "microdata declares an address"
    return False, ""


def _build_site_context(bundle: dict, pages: List[dict], names: List[str]) -> Dict[str, Any]:
    readable = [p for p in pages if not p.get("fetch_failed") and not p.get("non_html")]
    content = [p for p in readable if endpoint_kind(p) in ("content", "listing")]
    home = None
    home_url = (bundle.get("site") or {}).get("home_url")
    for page in readable:
        if home_url and page.get("url") == home_url or page.get("page_type") == "home":
            home = page
            break
    host = (bundle.get("site") or {}).get("host") or ""

    org_types: set = set()
    for page in readable:
        for node in page.get("jsonld_nodes") or []:
            types = _lower_types(node)
            if types & ({"organization", "corporation", "onlinestore", "store",
                         "localbusiness", "brand", "ngo"} | _GOV_ORG_TYPES
                        | _PUBLISHER_ORG_TYPES | _EDU_ORG_TYPES):
                org_types |= types

    product_pages = [p for p in readable if p.get("page_type") == "product"]
    subtypes: Dict[str, int] = {}
    described: Dict[str, int] = {}
    sells_online = False
    sell_evidence: List[str] = []
    for page in product_pages:
        sem = (page.get("semantics") or {}).get("product") or product_semantics(page, names)
        # (pages here are the annotated ones - the bundle's own or the shadow's)
        subtypes[sem["subtype"]] = subtypes.get(sem["subtype"], 0) + 1
        if sem.get("sells"):
            sells_online = True
            kind = sem["subtype"]
            described[kind] = described.get(kind, 0) + 1
            for why in sem.get("sell_evidence") or []:
                if why not in sell_evidence:
                    sell_evidence.append(why)
        elif sem.get("described_as") not in (None, "ambiguous"):
            described.setdefault(sem["described_as"] + " (described, not sold)", 0)
            described[sem["described_as"] + " (described, not sold)"] += 1
    listing_kinds: Dict[str, int] = {}
    for page in readable:
        if str(page.get("page_type") or "") in LISTING_PAGE_TYPES:
            sem = (page.get("semantics") or {}).get("listing") or listing_semantics(page, bundle)
            listing_kinds[sem["subtype"]] = listing_kinds.get(sem["subtype"], 0) + 1

    transactions = any((p.get("forms") or {}).get("has_cart_action") for p in readable) \
        or any((p.get("forms") or {}).get("has_checkout_action") for p in readable)
    article_pages = [p for p in content if p.get("page_type") == "article"]
    doc_pages = [p for p in article_pages if _declared_types(p) & _DOC_TYPES]
    news_pages = [p for p in article_pages if _declared_types(p) & (_ARTICLE_TYPES - {"howto"})]
    community_pages = [p for p in content if _declared_types(p) & _COMMUNITY_TYPES]
    travel_pages = [p for p in content
                    if _declared_types(p) & (_TRAVEL_TYPES | _ACCOMMODATION_TYPES)]
    developer_pages = [p for p in content if _declared_types(p) & _DEVELOPER_TYPES
                       or any(prop(node, "codeRepository")
                              for node in (p.get("jsonld_nodes") or []))]
    reference_pages = [p for p in content if _declared_types(p) & _REFERENCE_TYPES]
    audio_pages = [p for p in content if _declared_types(p) & _AUDIO_PUBLISHING_TYPES]
    has_search = any((p.get("forms") or {}).get("has_site_search") for p in readable) or \
        any(find_nodes(p.get("jsonld_nodes") or [], "SearchAction") for p in readable)
    physical, physical_why = _physical_presence(readable)
    langs = sorted({_page_lang(p) for p in readable if _page_lang(p)})
    primary_lang = _page_lang(home) if home else (langs[0] if len(langs) == 1 else "")

    physical_sold = subtypes.get("physical", 0)
    software_sold = subtypes.get("software", 0) + subtypes.get("subscription", 0)
    service_pages = subtypes.get("service", 0)
    marketplace = subtypes.get("marketplace_listing", 0)

    scores: Dict[str, int] = {k: 0 for k in SITE_KINDS if k not in ("mixed", "unknown")}
    why: List[str] = []

    def add(kind: str, weight: int, reason: str) -> None:
        scores[kind] += weight
        why.append(f"{kind}: {reason}")

    if org_types & _GOV_ORG_TYPES:
        add("government", 3, "a GovernmentOrganization/GovernmentService is declared")
    if org_types & _PUBLISHER_ORG_TYPES:
        add("publisher", 3, "a NewsMediaOrganization is declared")
    if org_types & _EDU_ORG_TYPES:
        add("education", 3, "an EducationalOrganization is declared")
    if _host_suffix_matches(host, _GOV_HOST_SUFFIXES):
        add("government", 1, "the host is under a government registry suffix")
    if _host_suffix_matches(host, _EDU_HOST_SUFFIXES):
        add("education", 1, "the host is under an academic registry suffix")
    if physical_sold:
        add("ecommerce", 3 if physical_sold >= 2 else 2,
            f"{physical_sold} page(s) sell physical goods")
    if subtypes.get("digital", 0):
        add("ecommerce", 2, f"{subtypes['digital']} page(s) sell digital goods")
    if software_sold:
        add("software", 3 if software_sold >= 2 else 2,
            f"{software_sold} page(s) sell software or subscriptions")
    elif described.get("software (described, not sold)"):
        add("software", 2, "software is described without being sold on the page")
    if service_pages:
        add("services", 3 if service_pages >= 2 else 2, f"{service_pages} service page(s)")
    if marketplace:
        add("marketplace", 3 if marketplace >= 2 else 2,
            f"{marketplace} third-party listing(s)")
    if listing_kinds.get("ecommerce_listing"):
        add("ecommerce", 1, "an ecommerce listing page")
    if listing_kinds.get("software_catalog"):
        add("software", 1, "a software catalogue listing")
    if listing_kinds.get("service_listing"):
        add("services", 1, "a service listing page")
    if listing_kinds.get("marketplace_listing"):
        add("marketplace", 1, "a marketplace listing page")
    if listing_kinds.get("documentation_section"):
        add("documentation", 1, "a documentation section listing")
    if listing_kinds.get("article_index") or listing_kinds.get("audio_listing"):
        add("publisher", 1, "an article/audio index listing")
    if content and doc_pages and len(doc_pages) >= max(1, len(content) * 0.3):
        add("documentation", 3, f"{len(doc_pages)} of {len(content)} content page(s) are technical articles")
    elif doc_pages:
        add("documentation", 1, f"{len(doc_pages)} technical article page(s)")
    if content and news_pages and len(news_pages) >= max(2, len(content) * 0.4):
        add("publisher", 3, f"{len(news_pages)} of {len(content)} content page(s) are articles")
    elif news_pages:
        add("publisher", 1, f"{len(news_pages)} article page(s)")
    if community_pages:
        add("community", 3 if len(community_pages) >= 2 else 1,
            f"{len(community_pages)} forum/Q&A page(s)")
    # A stay, a trip or a visit. Scored from declared types only: a page that
    # merely mentions travel is not a booking, and the ecommerce expectations
    # this displaces are too consequential to infer from prose.
    if travel_pages:
        add("travel_hospitality", 3 if len(travel_pages) >= 2 else 2,
            f"{len(travel_pages)} page(s) declare accommodation, a trip or a booking")
    if org_types & _TRAVEL_TYPES:
        add("travel_hospitality", 2, "a lodging or travel business is declared")
    if developer_pages:
        add("developer_platform", 3 if len(developer_pages) >= 2 else 1,
            f"{len(developer_pages)} page(s) declare source code, an API or a repository")
    if reference_pages:
        add("knowledge_reference", 3 if len(reference_pages) >= 2 else 1,
            f"{len(reference_pages)} page(s) declare a definition, a dataset or a "
            f"reference work")
    if audio_pages or listing_kinds.get("audio_listing"):
        add("publisher", 1, "audio episodes or an audio index are declared")
    if "ngo" in org_types:
        add("nonprofit", 2, "an NGO is declared")
    if org_types and not any(scores.values()):
        add("corporate", 1, "an organisation is declared and nothing else settles the kind")

    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], SITE_KINDS.index(kv[0])))
    top_kind, top = ordered[0]
    second_kind, second = ordered[1] if len(ordered) > 1 else ("", 0)
    if top == 0:
        site_kind, confidence = "unknown", "low"
    elif second >= 2 and top - second <= 1:
        site_kind, confidence = "mixed", "medium"
    elif top >= 3 and top >= second + 2:
        site_kind, confidence = top_kind, "high"
    elif top >= 2:
        site_kind, confidence = top_kind, "medium"
    else:
        site_kind, confidence = top_kind, "low"

    sitemap_urls = sum(len(s.get("entries") or []) or int(s.get("url_count") or 0)
                       for s in (bundle.get("sitemaps") or []))
    paginated = sum(1 for p in pages if _paginates(p))
    max_pages = int(((bundle.get("config") or {}).get("max_pages")) or 0)
    budget_capped = bool(max_pages) and len(pages) >= max_pages
    search_expected, search_why = _search_expectation(len(content), listing_kinds,
                                                      sitemap_urls, site_kind,
                                                      paginated_listings=paginated,
                                                      budget_capped=budget_capped)
    return {
        "version": SEMANTICS_VERSION,
        "site_kind": site_kind,
        "site_kind_confidence": confidence,
        "site_kind_evidence": why,
        "site_kind_scores": scores,
        "components": [k for k, v in ordered if v >= 2] if site_kind == "mixed" else [],
        "organization_types": sorted(org_types),
        "organization_names": names[:8],
        "product_pages": len(product_pages),
        "product_subtypes": subtypes,
        "goods_sold": described,
        "dominant_product_subtype": (max(subtypes.items(), key=lambda kv: (kv[1], kv[0]))[0]
                                     if subtypes else None),
        "listing_subtypes": listing_kinds,
        "sells_online": sells_online,
        "sell_evidence": sell_evidence[:6],
        "sells_physical_goods": physical_sold > 0,
        "sells_digital_goods": subtypes.get("digital", 0) > 0,
        "sells_software": software_sold > 0,
        "sells_subscriptions": subtypes.get("subscription", 0) > 0,
        "offers_services": service_pages > 0,
        "is_marketplace": marketplace > 0,
        "informational_catalogue": subtypes.get("informational", 0) > 0 and not sells_online,
        "transactions": bool(transactions),
        "physical_presence": physical,
        "physical_presence_evidence": physical_why,
        "has_site_search": bool(has_search),
        "search_expected": search_expected,
        "search_expected_reason": search_why,
        "content_pages": len(content),
        "article_pages": len(article_pages),
        "documentation_pages": len(doc_pages),
        "primary_language": primary_lang,
        "languages": langs,
        "sitemap_urls_seen": sitemap_urls,
    }


def _paginates(page: dict) -> bool:
    """Does the page link onward to a next page of the same listing?"""
    for link in ((page.get("links") or {}).get("internal") or []):
        if str(link.get("rel") or "").lower() in ("next", "prev", "previous"):
            return True
    return False


#: How many advertised URLs make a site large enough that a visitor would
#: reasonably look for a search box rather than browse.
_SEARCH_WORTHY_URLS = 100
#: How many content pages a budget-capped crawl must have read before the
#: cap itself is evidence of a large site.
_SEARCH_WORTHY_CAPPED_PAGES = 30


def _search_expectation(content_pages: int, listing_kinds: Dict[str, int],
                        sitemap_urls: int, site_kind: str, *,
                        paginated_listings: int = 0,
                        budget_capped: bool = False) -> Tuple[bool, str]:
    """Is a site search something this site can be expected to offer?

    Not automatic. A search box is an expectation only where the site is
    observed to be larger than a visitor can browse: a sitemap advertising
    many URLs, listings that paginate, or a crawl that spent its whole page
    budget on content. A handful of listing pages, or the site's *kind*,
    does not make a search box owed - a twenty-page shop or a small
    documentation set is browsed, not searched.
    """
    if sitemap_urls >= _SEARCH_WORTHY_URLS:
        return True, f"the sitemaps advertise {sitemap_urls} URLs"
    if paginated_listings:
        return True, (f"{paginated_listings} listing page(s) paginate, so the catalogue "
                      f"exceeds what one page shows")
    if budget_capped and content_pages >= _SEARCH_WORTHY_CAPPED_PAGES:
        return True, (f"the crawl spent its page budget after reading {content_pages} "
                      f"content pages, so the site is larger than what was read")
    listings = sum(listing_kinds.values()) if listing_kinds else 0
    return False, (f"{content_pages} content page(s), {listings} listing page(s) and "
                   f"{sitemap_urls} sitemap URL(s) were read; nothing observed shows the site "
                   f"is larger than a visitor can browse, so no search box is owed")


# ---------------------------------------------------------------------------
# applicability engine
# ---------------------------------------------------------------------------

class Applicability(dict):
    """``{"applies", "reason", "basis", "confidence"}`` - a decision and why.

    ``basis`` is ``declared`` (markup says so), ``observed`` (the page's own
    text or controls say so), ``inferred`` (from the site's shape) or
    ``unknown`` (nothing settled it, so the expectation is not asserted).
    """

    def __init__(self, applies: bool, reason: str, basis: str = "observed",
                 confidence: str = "medium"):
        super().__init__(applies=bool(applies), reason=reason, basis=basis,
                         confidence=confidence)

    @property
    def applies(self) -> bool:
        return bool(self["applies"])

    def __bool__(self) -> bool:  # `if is_shipping_applicable(...)` reads naturally
        return self.applies


def _product_record(page: dict, ctx: Optional[dict]) -> Dict[str, Any]:
    return product_record(page, ctx)


def _not_applicable(subtype: str, what: str, confidence: str = "medium") -> Applicability:
    if subtype == "ambiguous":
        return Applicability(False, f"the kind of item could not be established, so the "
                                    f"expectation of {what} is not asserted", "unknown", "low")
    return Applicability(False, f"{what} does not apply to a {subtype.replace('_', ' ')} "
                                f"item", "declared" if confidence == "high" else "inferred",
                         confidence)


def _site_kind_of_goods(ctx: Optional[dict]) -> str:
    """The one kind of item a site is seen to sell, or ``""`` when it sells
    several kinds (or none): the only situation in which an ambiguous page
    may inherit the site's kind."""
    if not ctx:
        return ""
    kinds = [k for k, flag in (("physical", ctx.get("sells_physical_goods")),
                               ("digital", ctx.get("sells_digital_goods")),
                               ("software", ctx.get("sells_software")),
                               ("subscription", ctx.get("sells_subscriptions")),
                               ("service", ctx.get("offers_services")),
                               ("marketplace_listing", ctx.get("is_marketplace"))) if flag]
    return kinds[0] if len(kinds) == 1 else ""


def _silent_but_on_a_selling_site(record: Dict[str, Any], ctx: Optional[dict]) -> bool:
    """A product page with no price, offer or cart, on a site that sells
    online, and with nothing on it saying the item is sold elsewhere.

    Such a page is not an information page in the sense a manufacturer's
    catalogue is: on a shop, a product page with no price is a product page
    whose price is missing, which is exactly what the audit exists to find.
    """
    return (record["subtype"] == "informational" and not record.get("points_elsewhere")
            and bool((ctx or {}).get("sells_online")))


def _inherit(record: Dict[str, Any], ctx: Optional[dict], wanted: Sequence[str],
             what: str) -> Optional[Applicability]:
    """A page whose kind the page itself does not establish is read as the
    kind the site sells - stated as an inference, at low confidence.

    Two shapes qualify: an ambiguous page that sells, on a site that sells
    one kind of thing; and a silent page (no price, no cart) on a site that
    sells online, whose own markup describes a kind or whose site sells one
    kind. A page that points at retailers elsewhere never qualifies.
    """
    subtype = record["subtype"]
    facets = record.get("facets") or {}
    if subtype == "ambiguous" and record.get("sells"):
        kind = _site_kind_of_goods(ctx)
        if not kind or kind not in wanted:
            return None
        if any(v > 0 for k, v in facets.items() if k != kind):
            return None
        return Applicability(True, f"the kind of item is not established on the page itself; "
                                   f"every item this site is seen to sell is "
                                   f"{kind.replace('_', ' ')}, so {what} is asked of it by "
                                   f"inference", "inferred", "low")
    if _silent_but_on_a_selling_site(record, ctx):
        described = record.get("described_as") or "ambiguous"
        kind = described if described != "ambiguous" else _site_kind_of_goods(ctx)
        if not kind or kind not in wanted:
            return None
        if described == "ambiguous" and any(v > 0 for k, v in facets.items() if k != kind):
            return None
        return Applicability(True, f"the page states no price and offers no purchase control, "
                                   f"but the site sells online and nothing on the page says the "
                                   f"item is sold elsewhere; it is read as a "
                                   f"{kind.replace('_', ' ')} item whose facts are missing, so "
                                   f"{what} is asked of it by inference", "inferred", "low")


def _mentions(page: dict, concept: str) -> bool:
    return bool((page.get("mentions") or {}).get(concept))


def is_shipping_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Does this page owe anyone a delivery statement?"""
    record = _product_record(page, ctx)
    subtype, confidence = record["subtype"], record["confidence"]
    if _mentions(page, "shipping"):
        return Applicability(True, "the page itself discusses delivery", "observed", "high")
    if subtype == "physical" and confidence in ("high", "medium"):
        return Applicability(True, "the page sells a physical item", "declared", confidence)
    if subtype == "marketplace_listing" and record["facets"].get("physical", 0) >= 2:
        return Applicability(True, "a third-party listing of a physical item", "declared",
                             "medium")
    if subtype == "informational":
        return Applicability(False, "the page describes the item without selling it",
                             "observed", record["confidence"])
    inherited = _inherit(record, ctx, ("physical",), "a delivery statement")
    if inherited:
        return inherited
    return _not_applicable(subtype, "a delivery statement", confidence)


def is_returns_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Does this page owe anyone a return-policy statement?"""
    record = _product_record(page, ctx)
    subtype, confidence = record["subtype"], record["confidence"]
    if _mentions(page, "returns"):
        return Applicability(True, "the page itself discusses returns", "observed", "high")
    if subtype == "physical" and confidence in ("high", "medium"):
        return Applicability(True, "the page sells a physical item", "declared", confidence)
    if subtype == "marketplace_listing" and record["facets"].get("physical", 0) >= 2:
        return Applicability(True, "a third-party listing of a physical item", "declared",
                             "medium")
    if subtype == "informational":
        return Applicability(False, "the page describes the item without selling it",
                             "observed", record["confidence"])
    inherited = _inherit(record, ctx, ("physical",), "a return policy")
    if inherited:
        return inherited
    return _not_applicable(subtype, "a return policy", confidence)


def is_stock_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Is stock/inventory a concept that applies to this page's item?"""
    record = _product_record(page, ctx)
    subtype, confidence = record["subtype"], record["confidence"]
    flags = page.get("availability_text") or {}
    if any(flags.get(k) for k in ("in_stock", "out_of_stock", "preorder", "limited")):
        return Applicability(True, "the page itself states a stock position", "observed", "high")
    if subtype == "physical" and confidence in ("high", "medium"):
        return Applicability(True, "the page sells a physical item", "declared", confidence)
    if subtype == "marketplace_listing" and record["facets"].get("physical", 0) >= 2:
        return Applicability(True, "a third-party listing of a physical item", "declared",
                             "medium")
    if subtype == "informational":
        return Applicability(False, "the page describes the item without selling it",
                             "observed", record["confidence"])
    inherited = _inherit(record, ctx, ("physical",), "a stock statement")
    if inherited:
        return inherited
    return _not_applicable(subtype, "a stock statement", confidence)


def is_physical_specs_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Are physical specifications (dimensions, material, weight...) expected?"""
    record = _product_record(page, ctx)
    subtype, confidence = record["subtype"], record["confidence"]
    kind = record.get("described_as") if subtype == "informational" else subtype
    if kind == "physical" and confidence in ("high", "medium"):
        return Applicability(True, "the page is about a physical item", "declared", confidence)
    if kind == "marketplace_listing" and record["facets"].get("physical", 0) >= 2:
        return Applicability(True, "a listing of a physical item", "declared", "medium")
    inherited = _inherit(record, ctx, ("physical",), "a physical specification block")
    if inherited:
        return inherited
    return _not_applicable(kind or "ambiguous", "a physical specification block", confidence)


def is_reviews_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Is review/rating content something this page would carry if it existed?"""
    record = _product_record(page, ctx)
    subtype, confidence = record["subtype"], record["confidence"]
    if _mentions(page, "reviews"):
        return Applicability(True, "the page itself refers to reviews", "observed", "high")
    if subtype in ("physical", "software", "subscription", "marketplace_listing", "digital") \
            and confidence in ("high", "medium") and record.get("sells"):
        return Applicability(True, f"a {subtype.replace('_', ' ')} item sold on the page",
                             "declared", confidence)
    if subtype == "informational":
        return Applicability(False, "the page describes the item without selling it",
                             "observed", record["confidence"])
    inherited = _inherit(record, ctx, ("physical", "software", "subscription", "digital",
                                       "marketplace_listing"), "review content")
    if inherited:
        return inherited
    return _not_applicable(subtype, "review content", confidence)


def is_price_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Is a stated price expected on this page?"""
    record = _product_record(page, ctx)
    if record.get("sells"):
        return Applicability(True, "the page offers the item for sale ("
                             + "; ".join(record.get("sell_evidence") or [])[:120] + ")",
                             "observed", "high")
    if _silent_but_on_a_selling_site(record, ctx):
        return Applicability(True, "the page states no price and offers no purchase control, "
                                   "but the site sells online and nothing on the page says the "
                                   "item is sold elsewhere, so a price is expected of it by "
                                   "inference", "inferred", "low")
    if record["subtype"] == "informational":
        return Applicability(False, "the page describes the item without selling it",
                             "observed", record["confidence"])
    return Applicability(False, "no offer, price or purchase control on the page",
                         "unknown", "low")


def is_hidden_price_check_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """May a page with images and *no* price text be asked where its price is?

    The premise of that check is that the price is absent from the text, so
    the usual sale evidence cannot be demanded. What can be read is the
    opposite: a page that says where to buy the item elsewhere, a service
    that is quoted rather than priced, or a page of a kind that is not sold
    at all, is not hiding a price and is set aside.
    """
    record = _product_record(page, ctx)
    subtype = record["subtype"]
    text = lexicon.fold(_main_text(page)[:20000])
    if _phrases_present(text, _TEXT_INFORMATIONAL, 1):
        return Applicability(False, "the page points at retailers or sales contacts rather "
                                    "than selling the item itself", "observed", "medium")
    if subtype == "service":
        return Applicability(False, "a service, which is often quoted rather than priced",
                             "declared", record["confidence"])
    if record.get("sells") or subtype in ("physical", "digital", "software", "subscription",
                                          "marketplace_listing", "ambiguous", "informational"):
        return Applicability(True, "a product page with no statement that the item is sold "
                                   "elsewhere", "observed", "medium")
    return _not_applicable(subtype, "a stated price", record["confidence"])


def is_identifier_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Are manufacturer identifiers (GTIN/MPN) expected on this page's item?"""
    record = _product_record(page, ctx)
    subtype, confidence = record["subtype"], record["confidence"]
    if subtype == "physical" and confidence in ("high", "medium"):
        return Applicability(True, "a physical item, which carries a GTIN or MPN",
                             "declared", confidence)
    if subtype == "marketplace_listing" and record["facets"].get("physical", 0) >= 2:
        return Applicability(True, "a listing of a physical item", "declared", "medium")
    inherited = _inherit(record, ctx, ("physical",), "a manufacturer identifier")
    if inherited:
        return inherited
    return _not_applicable(subtype, "a manufacturer identifier", confidence)


def is_purchase_cta_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Is an add-to-cart / buy affordance expected in this page's HTML?"""
    record = _product_record(page, ctx)
    subtype = record["subtype"]
    if not record.get("sells"):
        inherited = _inherit(record, ctx, ("physical", "digital"), "an add-to-cart affordance")
        if inherited and (ctx or {}).get("transactions"):
            return inherited
        return Applicability(False, "the page does not offer the item for sale", "observed",
                             record["confidence"])
    if subtype in ("physical", "digital") and (ctx or {}).get("transactions"):
        return Applicability(True, "goods sold through an on-site cart", "observed", "high")
    if subtype in ("physical", "digital") and record["confidence"] in ("high", "medium"):
        return Applicability(True, f"{subtype} goods offered for sale", "declared",
                             record["confidence"])
    inherited = _inherit(record, ctx, ("physical", "digital"), "an add-to-cart affordance")
    if inherited:
        return inherited
    return _not_applicable(subtype, "an add-to-cart affordance", record["confidence"])


def is_comparison_applicable(bundle: dict, ctx: Optional[dict] = None) -> Applicability:
    """Does this site publish a range a visitor would compare within?"""
    ctx = ctx or site_context(bundle)
    # Items are comparable within a kind: two boots, two plans, two
    # applications. A boot and a licence are not a comparison anyone makes.
    comparable = {k: v for k, v in (ctx.get("product_subtypes") or {}).items()
                  if k in ("physical", "software", "subscription", "digital") and v >= 2}
    if comparable:
        return Applicability(True, "two or more sellable items of the same kind "
                             f"({', '.join(f'{k}: {v}' for k, v in sorted(comparable.items()))})",
                             "declared", "medium")
    return Applicability(False, "fewer than two sellable items of any one kind were read",
                         "observed", "medium")


def is_site_search_expected(bundle: dict, ctx: Optional[dict] = None) -> Applicability:
    ctx = ctx or site_context(bundle)
    return Applicability(bool(ctx.get("search_expected")), ctx.get("search_expected_reason", ""),
                         "inferred", "medium")


def is_breadcrumb_applicable(page: dict, ctx: Optional[dict] = None) -> Applicability:
    """Does this page sit in a hierarchy a breadcrumb would state?"""
    page_type = str(page.get("page_type") or "")
    if page_type == "product" or page_type in LISTING_PAGE_TYPES:
        return Applicability(True, f"a {page_type} page sits inside a section", "inferred",
                             "medium")
    if page_type == "article" and (page.get("breadcrumbs") or {}).get("present"):
        return Applicability(True, "the page renders a breadcrumb trail", "observed", "high")
    return Applicability(False, f"a {page_type or 'unclassified'} page has no established "
                                f"hierarchy", "inferred", "low")


#: Where a machine-readable date is *expected*, merely useful, or beside the
#: point. A home page, a contact page and a search endpoint do not carry a
#: dated fact; an article, an FAQ and a support document do.
_FRESHNESS_EXPECTED = frozenset({"article", "faq", "support"})
_FRESHNESS_OPTIONAL = frozenset({"policy", "product", "about", "other", "program",
                                 "promotional"}) | LISTING_PAGE_TYPES


def freshness_expectation(page: dict) -> str:
    """``expected`` | ``optional`` | ``not_applicable`` for a machine-readable date."""
    if (page.get("dates") or {}).get("visible_updated"):
        return "expected"           # the page states a date; the typed form is the gap
    page_type = str(page.get("page_type") or "other")
    if page_type in _FRESHNESS_EXPECTED:
        return "expected"
    if page_type in _FRESHNESS_OPTIONAL:
        return "optional"
    return "not_applicable"


#: Organization properties, and what each one is for a given kind of site.
#: ``required_when_applicable`` means the site's shape calls for it;
#: ``recommended`` means it helps any organisation; ``optional`` means its
#: absence is never a finding on its own.
def organization_field_expectation(field: str, ctx: dict) -> str:
    field = field.lower()
    kind = ctx.get("site_kind") or "unknown"
    if field in ("name", "url"):
        return "required_when_applicable"
    if field == "description":
        return "recommended"
    if field == "address":
        # A stay is somewhere: a lodging or travel site that does not state
        # where it is has omitted the fact its readers ask about first.
        if ctx.get("physical_presence") or ctx.get("sells_physical_goods") \
                or kind in ("government", "services", "education", "travel_hospitality"):
            return "required_when_applicable"
        return "optional"
    if field in ("contactpoint", "telephone", "email"):
        if ctx.get("transactions") or ctx.get("sells_online") \
                or kind in ("government", "services", "ecommerce", "marketplace",
                            "travel_hospitality", "nonprofit"):
            return "recommended"
        return "optional"
    if field == "sameas":
        return "recommended" if ctx.get("official_profiles_linked") else "optional"
    if field == "@id":
        return "recommended" if (ctx.get("product_pages") or 0) > 0 else "optional"
    if field in ("logo", "foundingdate", "legalname", "founder", "numberofemployees",
                 "vatid", "taxid", "duns", "leicode", "iso6523code"):
        return "optional"
    return "optional"


def open_graph_expectation(page: dict, ctx: Optional[dict] = None) -> str:
    """``recommended`` on pages a machine might summarise; ``optional`` elsewhere."""
    page_type = str(page.get("page_type") or "")
    if page_type in ("home", "product", "article", "faq", "about") \
            or page_type in LISTING_PAGE_TYPES:
        return "recommended"
    return "optional"


def heading_assessment(page: dict, template: Optional[set] = None) -> Dict[str, Any]:
    """Does the heading structure name the page's subject?

    Neither "more than one ``<h1>``" nor "no ``<h1>``" is a defect by itself:
    HTML sectioning permits an ``<h1>`` per article, and a template that spent
    its ``<h1>`` on the logo may still name the page in an ``<h2>``. What
    matters is whether *some* top-level heading names what the page is about
    - it corroborates the title, and it is not a string the whole site
    repeats. Returns ``{"identifies_subject", "why", "h1_count",
    "top_level_headings"}``.
    """
    from .analysis import _corroborates, _fold, _heading_candidates, title_segments
    template = template or set()
    h1_count = int(page.get("h1_count") or 0)
    candidates = _heading_candidates(page)
    title = str(page.get("title") or "")
    statements = [s for s in title_segments(title) if _fold(s) not in template]
    og_title = str((page.get("open_graph") or {}).get("og:title") or "")
    statements += [s for s in title_segments(og_title) if _fold(s) not in template]
    named = [c for c in candidates if c and _fold(c) not in template]
    if not candidates:
        return {"identifies_subject": False, "h1_count": h1_count, "top_level_headings": [],
                "why": "no heading of any level in the page"}
    # On the home page the site is the subject, so a heading that is the
    # site's name is exactly the right heading.
    if str(page.get("page_type") or "") == "home":
        return {"identifies_subject": True, "h1_count": h1_count,
                "top_level_headings": candidates[:3],
                "why": "the home page's heading names the site, which is its subject"}
    # A heading that matches an entity the page declares - a Product name, an
    # Article headline - names the subject whatever the rest of the site
    # repeats: a declaration is item-scoped by construction.
    declared: List[str] = []
    for node in page.get("jsonld_nodes") or []:
        for key in ("name", "headline"):
            value = text_of(prop(node, key))
            if value and (_lower_types(node) & ({"product", "productgroup", "individualproduct",
                                                 "softwareapplication", "service", "book",
                                                 "webpage", "faqpage", "aboutpage",
                                                 "contactpage", "collectionpage", "event",
                                                 "course", "recipe", "jobposting"}
                                                | _ARTICLE_TYPES | _DOC_TYPES)):
                declared.append(util.collapse_ws(value))
    matched = [c for c in candidates if any(_corroborates(c, d) for d in declared)]
    if matched:
        return {"identifies_subject": True, "h1_count": h1_count,
                "top_level_headings": candidates[:3],
                "why": f"heading \"{matched[0][:60]}\" matches the entity the page declares"}
    # A title segment unique to this page vouches for a heading, even one the
    # site repeats elsewhere.
    corroborated = [c for c in candidates if any(_corroborates(c, s) for s in statements)]
    if corroborated:
        return {"identifies_subject": True, "h1_count": h1_count,
                "top_level_headings": candidates[:3],
                "why": (f"heading \"{corroborated[0][:60]}\" matches the page title"
                        + (f"; {h1_count} <h1> elements are present, which HTML "
                           f"sectioning permits" if h1_count > 1 else "")
                        + ("; the page has no <h1> but its top-level heading names it"
                           if h1_count == 0 else ""))}
    if named and not statements:
        # Nothing to corroborate against: a page without a title. The heading
        # is the only statement of the subject, so it counts.
        return {"identifies_subject": True, "h1_count": h1_count,
                "top_level_headings": candidates[:3],
                "why": "a heading names the page and there is no title to check it against"}
    if named:
        return {"identifies_subject": False, "h1_count": h1_count,
                "top_level_headings": candidates[:3],
                "why": (f"no top-level heading matches the page title "
                        f"(headings: {'; '.join(c[:40] for c in candidates[:2])}; "
                        f"title: {title[:60]})")}
    return {"identifies_subject": False, "h1_count": h1_count,
            "top_level_headings": candidates[:3],
            "why": "every top-level heading is a string the site repeats on other pages "
                   "(a site name or a section label), so none names this page"}


#: Question classes by the kind of site, for the answerability matrix. A
#: class listed here is only *eligible*; the per-page applicability functions
#: still decide for each subject.
_QUESTION_CLASSES = {
    "ecommerce": {"product_price", "product_availability", "product_specifications",
                  "category_cheapest", "product_comparison", "return_window",
                  "shipping_destinations", "payment_options"},
    "marketplace": {"product_price", "product_availability", "product_specifications",
                    "category_cheapest", "product_comparison", "return_window",
                    "shipping_destinations", "payment_options"},
    "software": {"product_price", "product_specifications", "product_comparison",
                 "payment_options"},
    "services": {"product_price", "payment_options"},
    # A stay is priced and paid for, and it can be compared - but it is not
    # shipped, not stocked and not returned, so the parcel questions are absent.
    "travel_hospitality": {"product_price", "product_availability", "product_comparison",
                           "payment_options"},
    "mixed": {"product_price", "product_availability", "product_specifications",
              "category_cheapest", "product_comparison", "return_window",
              "shipping_destinations", "payment_options"},
}

#: The topic families a site of a given shape can be expected to answer
#: questions about, and the wording each family is described with. This is the
#: editorial companion to :data:`_QUESTION_CLASSES`: that table says which
#: questions the audit can *resolve* against typed evidence, this one says which
#: questions the site's readers arrive with. Both are derived from the same
#: site context in :func:`high_value_question_intents`, so they cannot disagree
#: about what a site is.
_INTENT_FAMILIES = {
    "physical_goods": ("price, availability, specifications, delivery and returns",
                       "the site sells physical goods"),
    "digital_goods": ("price, format, licence terms and how the file is delivered",
                      "the site sells digital goods"),
    "software": ("installation, system requirements, compatibility, versions and "
                 "licence terms", "the site sells or documents software"),
    "subscription": ("plan prices, what each plan includes, limits, integrations and "
                     "how plans differ", "the site sells a subscription"),
    "services": ("what the service includes, where it is offered, lead times, "
                 "what it costs and how to book it", "the site offers services"),
    "marketplace": ("who the seller is, the condition of the item, and how "
                    "fulfilment and disputes work", "the site lists third-party sellers"),
    "travel": ("amenities, location, availability for a date, cancellation terms and "
               "booking constraints", "the site publishes accommodation, trips or bookings"),
    "documentation": ("installation, configuration, API usage, compatibility and which "
                      "version a page describes", "the site publishes technical documentation"),
    "developer": ("what the project does, how to install and call it, which versions are "
                  "supported, and how to contribute",
                  "the site publishes source code, APIs or repositories"),
    "publishing": ("who wrote a piece, when it was published and last updated, what it "
                   "is about, and what it is sourced from",
                   "the site publishes articles"),
    "public_service": ("who is eligible, how to apply, what documents are required, what "
                       "the deadlines are, and which guidance is current",
                       "the site is a public body"),
    "education": ("what a course covers, who it is for, what it costs and how to enrol",
                  "the site is an educational organisation"),
    "reference": ("what an entity is, how terms are defined, how entities relate, and "
                  "what each statement is sourced from",
                  "the site publishes definitions, datasets or reference works"),
    "community": ("how to take part, what the rules are, and where an existing answer "
                  "lives", "the site publishes forum or Q&A content"),
    "organisation": ("what the organisation does, how to contact it, and where it "
                     "operates", "an organisation is declared"),
}


def high_value_question_intents(ctx: dict) -> List[Dict[str, str]]:
    """The topic families this site's own evidence says its readers ask about.

    Returned in a fixed order as ``{"intent", "topics", "why"}``. Every entry
    is earned by something observed - goods sold, software documented, articles
    published, a public body declared - so a documentation site is never told
    to publish delivery answers and a shop is never told to publish API usage.
    An organisation with nothing else established still has the last family:
    what it does, how to reach it, where it operates.
    """
    kind = ctx.get("site_kind") or "unknown"
    components = set(ctx.get("components") or ())
    kinds = {kind} | components
    picked: List[str] = []

    def take(name: str, when: bool) -> None:
        if when and name not in picked:
            picked.append(name)

    take("physical_goods", bool(ctx.get("sells_physical_goods")))
    take("digital_goods", bool(ctx.get("sells_digital_goods")))
    take("subscription", bool(ctx.get("sells_subscriptions")))
    take("software", bool(ctx.get("sells_software")) or "documentation" in kinds
         or "software" in kinds)
    take("services", bool(ctx.get("offers_services")) or "services" in kinds)
    take("marketplace", bool(ctx.get("is_marketplace")) or "marketplace" in kinds)
    take("travel", "travel_hospitality" in kinds)
    take("documentation", "documentation" in kinds)
    take("developer", "developer_platform" in kinds)
    take("publishing", "publisher" in kinds)
    take("public_service", "government" in kinds)
    take("education", "education" in kinds)
    take("reference", "knowledge_reference" in kinds)
    take("community", "community" in kinds)
    if not picked and (ctx.get("organization_names") or ctx.get("organization_types")
                       or kind not in ("unknown",)):
        take("organisation", True)
    return [{"intent": name, "topics": _INTENT_FAMILIES[name][0],
             "why": _INTENT_FAMILIES[name][1]} for name in picked]


def answerability_question_classes(ctx: dict) -> set:
    """Which question kinds a site of this shape can be asked at all.

    A documentation site, a publisher, a government department: none of them
    sells anything, so "what is the return window?" is not a question about
    them and its absence is not a gap. When a site of another shape still
    carries sellable items, the classes follow what is actually sold.
    """
    kind = ctx.get("site_kind") or "unknown"
    classes = set(_QUESTION_CLASSES.get(kind, set()))
    sells = bool(ctx.get("sells_online") or ctx.get("transactions"))
    if sells:
        # Anything sold online has a price and takes payment, whatever it is.
        classes |= {"product_price", "payment_options", "product_comparison"}
    if ctx.get("sells_physical_goods") or (ctx.get("is_marketplace") and sells):
        classes |= _QUESTION_CLASSES["ecommerce"]
    if ctx.get("sells_software") or ctx.get("sells_subscriptions"):
        classes |= _QUESTION_CLASSES["software"]
    if ctx.get("sells_digital_goods"):
        classes |= {"product_price", "product_specifications", "product_comparison",
                    "payment_options"}
    if ctx.get("offers_services") and sells:
        classes |= {"product_price", "payment_options"}
    if not ctx.get("sells_physical_goods") and not (ctx.get("is_marketplace") and sells):
        classes -= {"product_availability", "return_window", "shipping_destinations"}
    if not sells:
        classes.discard("payment_options")
    return classes


def applicability_summary(bundle: dict) -> Dict[str, Any]:
    """What the report says about which expectations were and were not applied."""
    ctx = site_context(bundle)
    from . import evidence as ev
    products = ev.product_pages(bundle)
    decisions: List[dict] = []
    for name, fn in (("shipping", is_shipping_applicable), ("returns", is_returns_applicable),
                     ("stock", is_stock_applicable),
                     ("physical_specifications", is_physical_specs_applicable),
                     ("reviews", is_reviews_applicable), ("price", is_price_applicable),
                     ("identifiers", is_identifier_applicable),
                     ("purchase_cta", is_purchase_cta_applicable)):
        applied = [p for p in products if fn(p, ctx)]
        reasons: Dict[str, int] = {}
        for page in products:
            verdict = fn(page, ctx)
            if not verdict:
                reasons[verdict["reason"]] = reasons.get(verdict["reason"], 0) + 1
        decisions.append({"expectation": name, "product_pages": len(products),
                          "applied_to": len(applied),
                          "not_applied": [{"reason": r, "pages": n}
                                          for r, n in sorted(reasons.items())]})
    return {
        "site_kind": ctx.get("site_kind"),
        "site_kind_confidence": ctx.get("site_kind_confidence"),
        "site_kind_evidence": ctx.get("site_kind_evidence"),
        "product_subtypes": ctx.get("product_subtypes"),
        "listing_subtypes": ctx.get("listing_subtypes"),
        "question_classes": sorted(answerability_question_classes(ctx)),
        "site_search_expected": is_site_search_expected(bundle, ctx),
        "comparison_expected": is_comparison_applicable(bundle, ctx),
        "expectations": decisions,
    }


# ---------------------------------------------------------------------------
# outbound links: profile, knowledge, product listing, or navigation?
# ---------------------------------------------------------------------------

LINK_KINDS = ("official_profile", "review_listing", "knowledge_reference", "documentation",
              "product_listing", "code_repository", "language_variant", "navigation",
              "share_intent", "unknown")

#: Platforms whose URLs name an *account* the linking site claims: a profile
#: the organisation controls. The handle in the path is the identity claim.
_PROFILE_HOSTS = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "pinterest.com", "tiktok.com", "threads.net", "weibo.com",
    "weibo.cn", "xiaohongshu.com", "douyin.com", "bilibili.com", "zhihu.com",
    "line.me", "naver.com", "kakao.com", "band.us", "vk.com", "ok.ru",
    "telegram.me", "t.me", "rutube.ru", "vimeo.com", "xing.com", "mastodon.social",
    "bsky.app", "medium.com", "behance.net", "dribbble.com", "flickr.com",
    "snapchat.com", "twitch.tv", "soundcloud.com", "spotify.com", "reddit.com",
    "g.page", "goo.gl/maps", "maps.google", "maps.app.goo.gl",
)
_REVIEW_HOSTS = ("trustpilot.com", "g2.com", "capterra.com", "yelp.com", "tripadvisor.com",
                 "glassdoor.com", "trustedshops.com", "reviews.io", "feefo.com",
                 "sitejabber.com", "producthunt.com")
#: Public knowledge bases and registries. ``KNOWLEDGE_HOSTS`` in the extractor
#: still lists a professional-network host for the anchor probe's ordering;
#: here a company page on such a network is an *account* the organisation
#: controls, so it is classified as a profile and not as a knowledge entry.
_KNOWLEDGE_HOSTS = tuple(h for h in KNOWLEDGE_HOSTS if "linkedin" not in h) + (
    "dbpedia.org", "britannica.com", "isni.org", "viaf.org", "d-nb.info",
    "companieshouse.gov.uk", "sec.gov", "grid.ac", "ror.org")
#: Paths on a profile platform that name a *content item* rather than an
#: account: a video, a post, a track, a thread. Linking one asserts nothing
#: about identity.
_PLATFORM_CONTENT_RE = re.compile(
    r"/(?:watch|shorts|embed|playlist|comments|track|album|episode|show|status|posts?|"
    r"reels?|videos?|photo|photos|pin|events?|jobs|hashtag|search|intent|share|"
    r"story|stories|live|clip|clips)(?:/|$|\?)", re.I)
_PRODUCT_LISTING_HOSTS = ("apps.apple.com", "itunes.apple.com", "play.google.com",
                          "chrome.google.com", "chromewebstore.google.com",
                          "addons.mozilla.org", "marketplace.visualstudio.com",
                          "store.steampowered.com", "amazon.", "etsy.com/shop",
                          "ebay.", "flipkart.com", "pypi.org", "npmjs.com",
                          "rubygems.org", "crates.io", "hub.docker.com", "marketplace.")
_CODE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "sr.ht")
_DOC_HOSTS = ("readthedocs.io", "readthedocs.org", "gitbook.io", "docs.", "developer.",
              "developers.", "api.", "help.", "support.", "learn.", "wiki.")
_LOCALE_HOST_RE = re.compile(r"^(?:[a-z]{2}(?:-[a-z]{2})?)\.", re.I)
_LOCALE_PATH_RE = re.compile(r"^/(?:[a-z]{2}(?:[-_][a-z]{2})?)(?:/|$)", re.I)


def _host_in(host: str, hosts: Sequence[str]) -> bool:
    host = host.lower()
    for candidate in hosts:
        if "/" in candidate:
            continue
        if candidate.endswith("."):
            if host.startswith(candidate) or ("." + candidate) in host:
                return True
        elif host == candidate or host.endswith("." + candidate):
            return True
    return False


def _handle_segment(path: str) -> str:
    from urllib.parse import unquote
    for segment in unquote(path or "").split("/"):
        segment = segment.strip()
        if not segment or segment.lower() in ("company", "in", "user", "channel", "c",
                                              "profile", "pages", "page", "people", "u",
                                              "org", "orgs", "users", "showcase", "school",
                                              "review", "reviews", "biz", "sellers",
                                              "products", "vendor"):
            continue
        if re.match(r"^@?[A-Za-z0-9][A-Za-z0-9._\-]{1,60}$", segment):
            return segment.lstrip("@")
        return ""
    return ""


def classify_outbound_link(url: str, *, site_origin: str = "", text: str = "",
                           rel: str = "", entity_names: Sequence[str] = ()) -> Dict[str, Any]:
    """What kind of relationship an outbound link asserts, if any.

    Returns ``{"kind", "why", "entity_match", "handle"}`` with ``kind`` in
    :data:`LINK_KINDS`. Only ``official_profile`` (and any ``rel=me`` link)
    is a claim of identity the site could declare as ``sameAs``; a knowledge
    reference, a documentation link, a product listing on someone else's
    store and a language variant of the site itself are all links, and none
    of them is a profile the site controls.

    Host tables here name *platforms* - the places where an account, a
    listing or an encyclopaedia entry lives - never any audited site.
    """
    parts = urlsplit(url or "")
    host = (parts.netloc or "").lower().split("@")[-1].split(":")[0]
    path = parts.path or "/"
    full = (host + path).lower()
    record = {"kind": "unknown", "why": "", "entity_match": False, "handle": ""}
    if not host:
        return record
    if "me" in (rel or "").lower().split():
        record.update(kind="official_profile", why="declared rel=me",
                      handle=_handle_segment(path))
        return record
    if SHARE_INTENT_RE.search(url or ""):
        record.update(kind="share_intent", why="a share/intent endpoint, not a profile")
        return record
    if site_origin and util.same_site(url, site_origin):
        site_host = urlsplit(site_origin).netloc.lower()
        if host != site_host and _LOCALE_HOST_RE.match(host) or _LOCALE_PATH_RE.match(path):
            record.update(kind="language_variant",
                          why="the same site under a locale host or path")
        else:
            record.update(kind="navigation", why="a link within the site itself")
        return record
    if _host_in(host, _KNOWLEDGE_HOSTS) or any(h in full for h in ("wikipedia.org/wiki/",
                                                                     "wikidata.org/wiki/")):
        slug = path.rsplit("/", 1)[-1].replace("_", " ")
        record.update(kind="knowledge_reference",
                      why="an entry in a public knowledge base or registry",
                      entity_match=any(_names_match(slug, n) for n in entity_names))
        return record
    if any(marker in full for marker in _PRODUCT_LISTING_HOSTS):
        record.update(kind="product_listing",
                      why="a listing on a store, app store or package registry")
        return record
    if _host_in(host, _CODE_HOSTS):
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2:
            record.update(kind="code_repository", why="a source-code repository",
                          handle=segments[0])
        else:
            record.update(kind="official_profile", why="an organisation/user profile on a "
                                                      "code-hosting platform",
                          handle=segments[0] if segments else "")
        return record
    if _host_in(host, _REVIEW_HOSTS):
        record.update(kind="review_listing", why="a listing on a review platform",
                      handle=_handle_segment(path))
        return record
    if _host_in(host, _PROFILE_HOSTS) or any(h in full for h in ("g.page/", "goo.gl/maps",
                                                                  "maps.google", "maps.app.goo.gl")):
        if _PLATFORM_CONTENT_RE.search(path) and not ("maps" in full or "g.page" in full):
            record.update(kind="unknown", why="a content item on a platform, not an account")
            return record
        handle = _handle_segment(path)
        if handle or "maps" in full or "g.page" in full:
            record.update(kind="official_profile", why="an account on a social or listing "
                                                      "platform", handle=handle)
        else:
            record.update(kind="navigation", why="a platform's front page, not an account")
        return record
    if any(host.startswith(h) for h in _DOC_HOSTS if h.endswith(".")) or \
            _host_in(host, tuple(h for h in _DOC_HOSTS if not h.endswith("."))):
        record.update(kind="documentation", why="a documentation or developer host")
        return record
    return record


# ---------------------------------------------------------------------------
# entity relationships
# ---------------------------------------------------------------------------

ENTITY_RELATIONSHIPS = (
    "primary_entity", "organization", "brand", "product", "subsidiary", "department",
    "agency", "tribunal", "acquired_company", "partner", "customer", "official_profile",
    "localization", "language_variant", "knowledge", "navigation", "unrelated", "unknown",
)

_ORG_NODE_TYPES = frozenset({"organization", "corporation", "onlinestore", "store",
                             "localbusiness", "brand", "ngo", "governmentorganization",
                             "newsmediaorganization", "educationalorganization",
                             "collegeoruniversity", "governmentoffice", "sportsorganization",
                             "medicalorganization", "airline", "consortium", "fundingagency",
                             "libarysystem", "librarysystem", "performinggroup",
                             "project", "researchorganization", "workersunion"})

_GOV_WORDS = {
    "department": ("department", "ministry", "ministere", "ministerio", "ministerium",
                   "directorate", "bureau", "office of", "secretariat"),
    "agency": ("agency", "authority", "commission", "council", "board", "service",
               "executive", "regulator", "inspectorate", "administration", "agentur"),
    "tribunal": ("tribunal", "court", "ombudsman", "appeals", "adjudicator"),
}
#: Phrases in page text that name a former identity of the organisation or
#: the organisation that owns it. The name is read from the words that follow
#: the phrase (a capitalised run), never from the site's own name nearby.
_FORMER_NAME_PHRASES = ("formerly known as", "previously known as", "formerly trading as",
                        "rebranded from", "formerly")
_OWNER_PHRASES = ("acquired by", "now part of", "a subsidiary of", "a division of",
                  "a wholly owned subsidiary of", "owned by", "part of the", "a member of the")
_ACQUISITION_PHRASES = ("acquired", "acquisition of", "merged with")
_ACQUIRED_PHRASES = _FORMER_NAME_PHRASES + _OWNER_PHRASES + _ACQUISITION_PHRASES
_NAME_CONNECTORS = ("of", "and", "&", "the", "de", "la", "du", "for")
_NAME_RUN_RE = (r"((?:[A-Z][\w&'\-]*)(?:\s+(?:of|and|&|the|de|la|du|for|[A-Z][\w&'\-]*)){0,5})")


def _names_after(text: str, phrase: str) -> List[str]:
    """Capitalised runs that follow ``phrase`` in ``text`` (raw case kept).

    A run stops at the first lower-case word or sentence mark, and trailing
    connectors ("and", "of") are trimmed, so "formerly known as Falcon
    Supplies and is now..." yields "Falcon Supplies".
    """
    pattern = re.compile(re.escape(phrase) + r"[\s:,]+" + _NAME_RUN_RE)
    out: List[str] = []
    for match in pattern.finditer(text or ""):
        tokens = util.collapse_ws(match.group(1)).split(" ")
        while tokens and tokens[-1].lower() in _NAME_CONNECTORS:
            tokens.pop()
        name = " ".join(tokens).strip(" .,;:")
        # A run that is only a stop-word or a sentence opener is not a name.
        if name and name.lower() not in ("the", "a", "an", "in", "on", "it", "we", "our") \
                and len(name) >= 3:
            out.append(name)
    return out


def _primary_identity(bundle: dict, home: Optional[dict]) -> Tuple[List[str], set, str]:
    """The site's own names, its Organization @ids, and its origin host."""
    names: List[str] = []
    ids: set = set()
    origin = (bundle.get("site") or {}).get("origin") or ""
    pages = [home] if home else []
    pages += [p for p in bundle.get("pages") or [] if p is not home
              and not p.get("fetch_failed")]
    for page in pages:
        og = (page.get("open_graph") or {}).get("og:site_name")
        if og and page is home:
            names.append(util.collapse_ws(str(og)))
        for node in page.get("jsonld_nodes") or []:
            if not (_lower_types(node) & _ORG_NODE_TYPES):
                continue
            node_url = text_of(prop(node, "url")) or ""
            node_id = prop(node, "@id")
            is_own = (page is home and not prop(node, "parentOrganization")) or \
                (origin and node_url and util.same_site(str(node_url), origin)
                 and util.url_path(str(node_url)) in ("", "/"))
            if is_own:
                name = text_of(prop(node, "name"))
                if name:
                    names.append(util.collapse_ws(name))
                if isinstance(node_id, str) and node_id:
                    ids.add(node_id)
    return util.dedupe(names), ids, origin


def _relationship_label(node: dict, name: str, primary_names: Sequence[str],
                        primary_ids: set, page: dict, home: Optional[dict],
                        primary_lang: str) -> Tuple[str, str]:
    """(relationship, why) for one organisation-like node or name."""
    types = _lower_types(node) if isinstance(node, dict) else set()
    folded_name = _folded(name)
    parent = prop(node, "parentOrganization") if isinstance(node, dict) else None
    parent_name = _entity_name(parent)
    parent_id = prop(parent, "@id") if isinstance(parent, dict) else (
        parent if isinstance(parent, str) else None)
    parent_is_primary = bool(parent) and (
        (parent_id and parent_id in primary_ids)
        or any(_names_match(parent_name, p) for p in primary_names))

    if any(_names_match(name, p) for p in primary_names):
        page_lang = _page_lang(page)
        if page is not home and primary_lang and page_lang and page_lang != primary_lang \
                and not any(util.normalize_name(name) == util.normalize_name(p)
                            for p in primary_names):
            return "localization", f"the site's own name as rendered on a {page_lang} page"
        return "primary_entity", "the site's own organisation"
    # A different script or language for what the same page calls itself.
    primary_scripts = {_script_of(p) for p in primary_names}
    if primary_names and _script_of(name) and _script_of(name) not in primary_scripts:
        return "localization", (f"written in {_script_of(name)} script where the site's "
                                f"own name is not")
    page_lang = _page_lang(page)
    if page is not home and primary_lang and page_lang and page_lang != primary_lang:
        return "language_variant", f"declared on a {page_lang} page of a {primary_lang} site"
    if parent_is_primary or (isinstance(node, dict) and prop(node, "parentOrganization")):
        whose = ("the site's organisation" if parent_is_primary else "a parent organisation")
        if any(w in folded_name for w in _GOV_WORDS["tribunal"]):
            return "tribunal", f"a tribunal/court body declaring {whose} as its parent"
        if any(w in folded_name for w in _GOV_WORDS["department"]):
            return "department", f"a department/ministry declaring {whose} as its parent"
        if types & _GOV_ORG_TYPES:
            return "agency", f"a public body declaring {whose} as its parent"
        return "subsidiary", f"declares {whose} as its parent"
    if isinstance(node, dict) and (prop(node, "subOrganization") or prop(node, "department")):
        return "organization", "an organisation that declares sub-organisations of its own"
    if types & {"brand"}:
        return "brand", "declared as a Brand"
    return "unknown", "declared organisation with no stated relationship"


def _text_stated_relationships(pages: Sequence[dict]) -> List[Tuple[str, str, str, str]]:
    """``(name, relationship, why, url)`` for every name the pages' own text
    gives as a former identity, an owner, or an organisation absorbed."""
    out: List[Tuple[str, str, str, str]] = []
    for page in pages:
        url = page.get("url") or ""
        raw_text = str(page.get("text") or "")[:20000]
        lowered = raw_text.lower()
        for phrase in _ACQUIRED_PHRASES:
            if phrase not in lowered:
                continue
            for name in _names_after(raw_text, phrase) + _names_after(
                    raw_text, phrase[:1].upper() + phrase[1:]):
                if phrase in _FORMER_NAME_PHRASES:
                    out.append((name, "acquired_company",
                                f"named after \"{phrase}\" in the page text: a former name of "
                                f"the organisation", url))
                elif phrase in _OWNER_PHRASES:
                    out.append((name, "organization",
                                f"named after \"{phrase}\" in the page text: the organisation's "
                                f"parent or owner", url))
                else:
                    out.append((name, "acquired_company",
                                f"named after \"{phrase}\" in the page text: an organisation "
                                f"this one absorbed", url))
    return out


def entity_relationships(bundle: dict) -> List[Dict[str, Any]]:
    """Every named organisation-like entity in the crawl, and how it relates
    to the site's own.

    Each record is ``{"name", "relationship", "why", "url", "source"}`` with
    ``relationship`` in :data:`ENTITY_RELATIONSHIPS`. The name-consistency
    rule reads this so that a department, a subsidiary, a product brand, a
    localized rendering of the site's own name or a knowledge-base link is
    never counted as a *rival spelling* of the trading name.
    """
    from . import evidence as ev
    home = ev.home_page(bundle)
    primary_names, primary_ids, origin = _primary_identity(bundle, home)
    primary_lang = _page_lang(home) if home else ""
    out: List[Dict[str, Any]] = []
    seen: set = set()

    def record(name: str, relationship: str, why: str, url: str, source: str) -> None:
        key = (util.normalize_name(name), relationship)
        if not name or key in seen:
            return
        seen.add(key)
        out.append({"name": util.collapse_ws(name), "relationship": relationship,
                    "why": why, "url": url, "source": source})

    # What the pages' own text says first: a name the site declares with
    # its own URL but describes as "formerly known as" is a former name, not
    # a second identity. The home page's own declared name is never demoted.
    stated = _text_stated_relationships(ev.pages(bundle))
    former = {util.normalize_name(n) for n, rel, _, _ in stated if rel == "acquired_company"}
    home_names = set()
    if home:
        for node in home.get("jsonld_nodes") or []:
            if _lower_types(node) & _ORG_NODE_TYPES and not prop(node, "parentOrganization"):
                home_names.add(util.normalize_name(text_of(prop(node, "name")) or ""))
    for name in primary_names:
        key = util.normalize_name(name)
        if key in former and key not in home_names:
            why = [w for n, rel, w, _ in stated if util.normalize_name(n) == key][0]
            record(name, "acquired_company", why, (home or {}).get("url") or origin, "page text")
            continue
        record(name, "primary_entity", "the site's own organisation",
               (home or {}).get("url") or origin, "home page identity")
    primary_names = [n for n in primary_names
                     if util.normalize_name(n) not in former
                     or util.normalize_name(n) in home_names]

    for page in ev.pages(bundle):
        url = page.get("url") or ""
        nodes = page.get("jsonld_nodes") or []
        for node in nodes:
            types = _lower_types(node)
            if types & _ORG_NODE_TYPES:
                name = text_of(prop(node, "name"))
                if not name:
                    continue
                relationship, why = _relationship_label(node, name, primary_names, primary_ids,
                                                        page, home, primary_lang)
                record(name, relationship, why, url, "schema.org " + "/".join(sorted(types))[:40])
                for sub in _as_list(prop(node, "subOrganization")):
                    sub_name = _entity_name(sub)
                    if sub_name:
                        record(sub_name, "subsidiary", "listed as a subOrganization", url,
                               "schema.org subOrganization")
                for dep in _as_list(prop(node, "department")):
                    dep_name = _entity_name(dep)
                    if dep_name:
                        record(dep_name, "department", "listed as a department", url,
                               "schema.org department")
            if types & {"product", "productgroup", "individualproduct", "softwareapplication"}:
                brand = _entity_name(prop(node, "brand"))
                if brand:
                    if any(_names_match(brand, p) for p in primary_names):
                        record(brand, "primary_entity", "Product.brand names the site's own "
                                                        "organisation", url, "Product.brand")
                    else:
                        record(brand, "brand", "the brand of a product on the page", url,
                               "Product.brand")
                maker = _entity_name(prop(node, "manufacturer"))
                if maker and not any(_names_match(maker, p) for p in primary_names):
                    record(maker, "partner", "the manufacturer of a product on the page", url,
                           "Product.manufacturer")
                for offer in _offers(node):
                    seller = _entity_name(prop(offer, "seller", "offeredBy"))
                    if seller and not any(_names_match(seller, p) for p in primary_names):
                        record(seller, "partner", "a third-party seller in an Offer", url,
                               "Offer.seller")
            if types & (_ARTICLE_TYPES | _DOC_TYPES):
                publisher = _entity_name(prop(node, "publisher"))
                if publisher and not any(_names_match(publisher, p) for p in primary_names):
                    record(publisher, "partner", "the publisher of an article on the page",
                           url, "Article.publisher")
                for about in _as_list(prop(node, "about", "mentions")):
                    about_name = _entity_name(about)
                    if about_name and isinstance(about, dict) and \
                            (_lower_types(about) & _ORG_NODE_TYPES) and \
                            not any(_names_match(about_name, p) for p in primary_names):
                        record(about_name, "unrelated", "an organisation the article is about",
                               url, "Article.about")
    # Names the pages' own text gives as a former identity, an owner, or an
    # organisation this one absorbed. The name is the capitalised run after
    # the phrase; the site's own current name is never the one recorded.
    for name, relationship, why, url in stated:
        if any(_names_match(name, p) for p in primary_names):
            continue
        record(name, relationship, why, url, "page text")

    # Outbound links: profiles, knowledge references, navigation.
    entity_names = primary_names
    for page in ev.pages(bundle):
        url = page.get("url") or ""
        links = page.get("links") or {}
        for link in (links.get("external") or [])[:120]:
            verdict = classify_outbound_link(str(link.get("url") or ""), site_origin=origin,
                                             text=str(link.get("text") or ""),
                                             rel=str(link.get("rel") or ""),
                                             entity_names=entity_names)
            kind = verdict["kind"]
            if kind == "official_profile":
                record(verdict["handle"] or str(link.get("url")), "official_profile",
                       verdict["why"], str(link.get("url")), "outbound link")
            elif kind == "knowledge_reference":
                record(str(link.get("url")), "knowledge",
                       verdict["why"] + (" about the site's own entity" if verdict["entity_match"]
                                         else " about another subject"),
                       str(link.get("url")), "outbound link")
            elif kind == "language_variant":
                record(str(link.get("url")), "language_variant", verdict["why"],
                       str(link.get("url")), "outbound link")
    # A nested node (a Product's manufacturer, an Article's subject) is also
    # met as a bare organisation with no stated relationship. Where a name
    # has a stated relationship, the "unknown" record for it is redundant.
    specific = {util.normalize_name(r["name"]) for r in out if r["relationship"] != "unknown"}
    return [r for r in out
            if r["relationship"] != "unknown" or util.normalize_name(r["name"]) not in specific]


# ---------------------------------------------------------------------------
# transport: not found versus not verified
# ---------------------------------------------------------------------------

#: Statuses that mean the request was refused or throttled rather than
#: answered for the resource itself.
_UNVERIFIED_STATUSES = frozenset({401, 403, 405, 406, 407, 408, 409, 418, 421, 425, 429,
                                  451, 500, 501, 502, 503, 504, 505, 507, 508, 509, 510,
                                  511, 520, 521, 522, 523, 524, 525, 526, 527, 530, 999})


def transport_verdict(status: Optional[int], error: Optional[str] = None,
                      *, checked: bool = True) -> Dict[str, str]:
    """``{"verdict", "reason"}``: ``verified`` | ``not_found`` | ``unverified``.

    The distinction every transport-facing rule needs, stated once. A 404 or
    410 is the origin saying the resource is not there. A refusal (401, 403,
    429), a server or gateway error, a timeout, a robots.txt disallow, a
    spent budget or a probe that never ran say nothing about the resource:
    the path between this auditor and the origin did not deliver an answer,
    and reading that as absence turns a transport fact into a content claim.
    """
    if not checked:
        return {"verdict": "unverified", "reason": "not attempted (robots.txt, address "
                                                   "guard, or budget)"}
    if error:
        text = str(error).lower()
        if "timed out" in text or "timeout" in text:
            return {"verdict": "unverified", "reason": "the request timed out"}
        if "robots" in text:
            return {"verdict": "unverified", "reason": "disallowed by robots.txt"}
        if "name or service not known" in text or "nodename nor servname" in text \
                or "getaddrinfo" in text or "no such host" in text or "dns" in text:
            return {"verdict": "unverified", "reason": "DNS lookup failed"}
        return {"verdict": "unverified", "reason": f"transport error: {str(error)[:80]}"}
    code = int(status or 0)
    if code in (404, 410):
        return {"verdict": "not_found", "reason": f"HTTP {code}"}
    if code == 0:
        return {"verdict": "unverified", "reason": "no response"}
    if code in _UNVERIFIED_STATUSES or code >= 500:
        why = "refused or rate-limited" if code < 500 else "server or gateway error"
        return {"verdict": "unverified", "reason": f"HTTP {code} ({why})"}
    if 200 <= code < 400:
        return {"verdict": "verified", "reason": f"HTTP {code}"}
    return {"verdict": "unverified", "reason": f"HTTP {code}"}
