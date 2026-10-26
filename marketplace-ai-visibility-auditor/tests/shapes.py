"""Generic site shapes, one per semantic site type, for regression tests.

Every fixture here is invented. None of them is modelled on, named after, or
keyed to any real site: each is the *shape* a class of site has - what it
declares about itself, what it sells or publishes, and what its pages are
about. A rule that reads these correctly reads any site of the same shape
correctly, which is the point: the auditor must never contain a rule that
knows a domain name.

The shapes, and what each one exists to prove:

``shop``                 physical goods - commerce checks must still work
``subscription_saas``    software sold by the month - plans, not parcels
``software_vendor``      software sold once and downloaded
``documentation``        technical documentation - no commerce at all
``publisher``            articles - freshness and authorship, not stock
``public_body``          guidance and services - eligibility, not returns
``knowledge_reference``  definitions and datasets - nothing is for sale
``developer_platform``   repositories and APIs - a repo list is not a catalogue
``travel``               stays and bookings - amenities, not delivery
``community``            forum and Q&A content
``mixed``                two of the above on one host
"""

from __future__ import annotations

from helpers import ORIGIN, bundle, html_doc, jsonld, page

LONG = " ".join(["This page explains the subject in enough detail to be read."] * 25)

ORG_LD = ('{"@context":"https://schema.org","@type":"Organization","name":"Kestrel Ltd",'
          '"url":"%s/","description":"An invented organisation used by the tests."}' % ORIGIN)
GOV_LD = ('{"@context":"https://schema.org","@type":"GovernmentOrganization",'
          '"name":"Water Regulator","url":"%s/"}' % ORIGIN)
NEWS_ORG_LD = ('{"@context":"https://schema.org","@type":"NewsMediaOrganization",'
               '"name":"The Kestrel Times","url":"%s/"}' % ORIGIN)
NGO_LD = ('{"@context":"https://schema.org","@type":"NGO","name":"Riverbank Trust",'
          '"url":"%s/"}' % ORIGIN)


def _page(path: str, title: str, ld: str = "", body: str = "", **kw) -> dict:
    return page(ORIGIN + path, html_doc(
        title=title, canonical=ORIGIN + path, head=jsonld(ld) if ld else "",
        body=body or f"<main><h1>{title}</h1><p>{LONG}</p></main>", **kw))


def home(ld: str = ORG_LD, name: str = "Kestrel Ltd") -> dict:
    return _page("/", name, ld, f"<h1>{name}</h1><p>{LONG}</p>")


# ---------------------------------------------------------------------------
# individual pages, by what they are about
# ---------------------------------------------------------------------------

def physical_product(path: str = "/products/trail-boot", name: str = "Trail Boot",
                     price: str = "120") -> dict:
    ld = ('{"@context":"https://schema.org","@type":"Product","name":"%s","sku":"%s",'
          '"color":"Brown","material":"Leather",'
          '"weight":{"@type":"QuantitativeValue","value":"1.1","unitCode":"KGM"},'
          '"offers":{"@type":"Offer","price":"%s","priceCurrency":"GBP",'
          '"availability":"https://schema.org/InStock"}}' % (name, name[:3].upper(), price))
    return _page(path, name, ld,
                 f"<main><h1>{name}</h1><p>£{price}. In stock.</p>"
                 f"<form action='/cart'><select name='size'><option>8</option>"
                 f"<option>9</option></select><button>Add to cart</button></form>"
                 f"<p>{LONG}</p></main>")


def instrument_product(path: str = "/products/locator-tag", name: str = "Locator Tag",
                       price: str = "35") -> dict:
    """A physical product whose attributes belong to nothing else on the site.

    "Diameter", "Height" and "Operating ambient temperature" are the shape of
    attribute a small hardware accessory publishes and a boot or a handset
    never does, which is what makes this page useful: if one of these names
    turns up in a recommendation aimed at another page, the recommendation
    read it off a page it has no relationship with.
    """
    ld = ('{"@context":"https://schema.org","@type":"Product","name":"%s","sku":"LT-1",'
          '"additionalProperty":['
          '{"@type":"PropertyValue","name":"Diameter","value":"31.9 mm"},'
          '{"@type":"PropertyValue","name":"Height","value":"8.0 mm"},'
          '{"@type":"PropertyValue","name":"Operating ambient temperature",'
          '"value":"-20 to 60 C"}],'
          '"offers":{"@type":"Offer","price":"%s","priceCurrency":"GBP",'
          '"availability":"https://schema.org/InStock"}}' % (name, price))
    return _page(path, name, ld,
                 f"<main><h1>{name}</h1><p>£{price}. In stock.</p>"
                 f"<table><tr><th>Diameter</th><td>31.9 mm</td></tr>"
                 f"<tr><th>Height</th><td>8.0 mm</td></tr>"
                 f"<tr><th>Operating ambient temperature</th><td>-20 to 60 C</td></tr>"
                 f"</table><p>{LONG}</p></main>")


def subscription_plan(path: str = "/plans/team", name: str = "Team plan") -> dict:
    ld = ('{"@context":"https://schema.org","@type":"Product","name":"%s",'
          '"description":"Team plan for the hosted service.",'
          '"offers":{"@type":"Offer","priceCurrency":"USD",'
          '"priceSpecification":{"@type":"UnitPriceSpecification","price":"12",'
          '"priceCurrency":"USD","billingDuration":1,"billingIncrement":1,'
          '"referenceQuantity":{"@type":"QuantitativeValue","value":1,'
          '"unitCode":"MON"}}}}' % name)
    return _page(path, name, ld,
                 f"<main><h1>{name}</h1><p>$12 per user per month, billed annually. "
                 f"Free trial, cancel anytime.</p><p>{LONG}</p></main>")


def software_download(path: str = "/products/studio", name: str = "Kestrel Studio",
                      price: str = "49") -> dict:
    ld = ('{"@context":"https://schema.org","@type":"SoftwareApplication","name":"%s",'
          '"operatingSystem":"Windows, macOS","applicationCategory":"DeveloperApplication",'
          '"softwareVersion":"4.2","offers":{"@type":"Offer","price":"%s",'
          '"priceCurrency":"USD"}}' % (name, price))
    return _page(path, name, ld,
                 f"<main><h1>{name}</h1><p>${price} licence. Download the installer for "
                 f"Windows or macOS. System requirements: 8 GB RAM.</p><p>{LONG}</p></main>")


def doc_article(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"TechArticle","headline":"%s",'
          '"dateModified":"2026-05-01"}' % title)
    return _page(path, title, ld)


def news_article(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"NewsArticle","headline":"%s",'
          '"datePublished":"2026-05-01","dateModified":"2026-05-02",'
          '"author":{"@type":"Person","name":"A Reporter"}}' % title)
    return _page(path, title, ld)


def audio_episode(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"PodcastEpisode","name":"%s",'
          '"datePublished":"2026-05-01",'
          '"partOfSeries":{"@type":"PodcastSeries","name":"River Notes"}}' % title)
    return _page(path, title, ld)


def guidance_page(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"GovernmentService","name":"%s",'
          '"serviceType":"Licensing","provider":{"@id":"%s/#organization"}}' % (title, ORIGIN))
    return _page(path, title, ld)


def reference_entry(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"DefinedTerm","name":"%s",'
          '"inDefinedTermSet":"%s/glossary","description":"An invented definition."}'
          % (title, ORIGIN))
    return _page(path, title, ld)


def dataset_entry(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"Dataset","name":"%s",'
          '"description":"An invented dataset.","license":"%s/licence"}' % (title, ORIGIN))
    return _page(path, title, ld)


def repository_page(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"SoftwareSourceCode","name":"%s",'
          '"codeRepository":"%s%s","programmingLanguage":"Python"}' % (title, ORIGIN, path))
    return _page(path, title, ld)


def api_reference(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"WebAPI","name":"%s",'
          '"documentation":"%s%s"}' % (title, ORIGIN, path))
    return _page(path, title, ld)


def lodging(path: str = "/stays/river-cottage", name: str = "River Cottage") -> dict:
    ld = ('{"@context":"https://schema.org","@type":"Accommodation","name":"%s",'
          '"numberOfRooms":2,"amenityFeature":['
          '{"@type":"LocationFeatureSpecification","name":"Wi-Fi","value":true},'
          '{"@type":"LocationFeatureSpecification","name":"Parking","value":true}],'
          '"address":{"@type":"PostalAddress","addressLocality":"Bristol"}}' % name)
    return _page(path, name, ld,
                 f"<main><h1>{name}</h1><p>Two bedrooms, sleeps four. From £95 per night, "
                 f"two-night minimum. Free cancellation up to 48 hours before arrival."
                 f"</p><p>{LONG}</p></main>")


def service_page(path: str = "/services/boiler-servicing",
                 name: str = "Boiler servicing") -> dict:
    """A service that is sold and delivered by a person, not shipped."""
    ld = ('{"@context":"https://schema.org","@type":"Service","name":"%s",'
          '"serviceType":"Maintenance","areaServed":"Bristol",'
          '"provider":{"@id":"%s/#organization"}}' % (name, ORIGIN))
    return _page(path, name, ld,
                 f"<main><h1>{name}</h1><p>An annual service carried out at your address. "
                 f"Book a visit and we will confirm a time.</p><p>{LONG}</p></main>")


def search_endpoint(path: str = "/search?q=boots") -> dict:
    """A results page, not a document the site publishes to be cited."""
    return page(ORIGIN + path, html_doc(
        title="Search results", description="Search this site.",
        body="<main><h1>Search results</h1><form role='search'>"
             "<input name='q' value='boots'></form>"
             "<p>3 results for &quot;boots&quot;.</p></main>"))


def facet_permutation(path: str = "/collections/boots?colour=black&size=9",
                      canonical_path: str = "/collections/boots") -> dict:
    """One address of a faceted listing, declaring the canonical it belongs to.

    A site that excludes these from its index is doing the ordinary thing, and
    an auditor that reports them is manufacturing work.
    """
    return page(ORIGIN + path, html_doc(
        title="Boots - black, size 9", canonical=ORIGIN + canonical_path,
        head='<meta name="robots" content="noindex,follow">',
        body="<main><h1>Boots</h1><ul><li><a href='/products/trail-boot'>Trail Boot</a>"
             "</li></ul></main>"))


def ambiguous_listing(path: str = "/browse/", title: str = "Browse") -> dict:
    """A page that reads as a listing and whose item set cannot be delimited.

    Repeated links and prices, nothing the crawl can resolve into members: the
    shape that must be reported honestly rather than advised confidently.
    """
    entries = "".join(f'<li><a href="/go/item-{n}">Item {n}</a> <span>&#163;{n}9</span></li>'
                      for n in range(1, 10))
    return _page(path, title, "",
                 f"<main><h1>{title}</h1><p>{LONG}</p><ul>{entries}</ul></main>")


def comparison_page(path: str = "/compare/boots", title: str = "Compare boots") -> dict:
    """A comparison table. A set, but not a catalogue to be filtered."""
    return _page(path, title, "",
                 f"<main><h1>{title}</h1><table>"
                 f"<tr><th></th><th>Trail Boot</th><th>Summit Boot</th></tr>"
                 f"<tr><th>Material</th><td>Leather</td><td>Leather</td></tr>"
                 f"<tr><th>Weight</th><td>1.1 kg</td><td>1.4 kg</td></tr>"
                 f"</table><p>{LONG}</p></main>")


def localized(path: str, name: str, lang: str, price: str) -> dict:
    """The same organisation, in another language, at another address."""
    ld = ('{"@context":"https://schema.org","@type":"Organization","name":"%s",'
          '"url":"%s%s"}' % (name, ORIGIN, path))
    return page(ORIGIN + path, html_doc(
        title=name, canonical=ORIGIN + path, lang=lang, head=jsonld(ld),
        description="Une organisation inventee.",
        body=f"<main><h1>{name}</h1><p>{price}</p><p>{LONG}</p></main>"))


def forum_thread(path: str, title: str) -> dict:
    ld = ('{"@context":"https://schema.org","@type":"DiscussionForumPosting",'
          '"headline":"%s","datePublished":"2026-05-01"}' % title)
    return _page(path, title, ld)


def listing(path: str, title: str, entries, ld_type: str = "CollectionPage") -> dict:
    ld = ('{"@context":"https://schema.org","@type":"%s","name":"%s"}' % (ld_type, title))
    items = "".join(f"<li><a href='{href}'>{label}</a></li>" for href, label in entries)
    return _page(path, title, ld, f"<main><h1>{title}</h1><ul>{items}</ul></main>")


def catalogue_listing(path: str, title: str, entries, paginates: bool = True) -> dict:
    """A real catalogue listing: many entries, prices beside them, and a next page.

    The positive control for every applicability test below. It differs from
    :func:`product_family` in exactly the ways that make a set a set: the
    entries are a range of comparable items and the set continues onto a
    further page.
    """
    items = "".join(f"<li><a href='{href}'>{name}</a> <span>£{price}</span></li>"
                    for href, name, price in entries)
    nav = (f"<a rel='next' href='{path}?page=2'>Next</a>") if paginates else ""
    return _page(path, title, "",
                 f"<main><h1>{title}</h1><ul>{items}</ul>{nav}</main>")


def product_family(path: str = "/handset/", name: str = "Handset",
                   models: int = 9) -> dict:
    """A product-family landing page: model links and prices, and no set.

    The shape that made the auditor ask a marketing page for a price sort. It
    carries everything a link-and-price count reads as a catalogue - several
    model names, several prices, product-shaped hrefs - and none of what makes
    a page a *collection*: no ItemList, no pagination, no catalogue controls,
    and the pages it points at are not part of the crawl. Deliberately built
    from an invented product line; nothing here is modelled on a real site.
    """
    entries = "".join(
        f"<li><a href='/shop/buy-{name.lower()}/model-{n}'>{name} Model {n}</a> "
        f"<span>£{600 + n * 100}</span></li>" for n in range(1, models + 1))
    return _page(path, name, "",
                 f"<main><h1>{name}</h1><p>The {name} family. {LONG}</p>"
                 f"<ul>{entries}</ul></main>")


def marketing_page(path: str = "/why-kestrel", title: str = "Why Kestrel") -> dict:
    """A promotional page: claims, a price mention, and nothing to filter."""
    return _page(path, title, "",
                 f"<main><h1>{title}</h1><p>Built to last. From £120. {LONG}</p>"
                 f"<a href='/collections/boots'>See the range</a></main>")


# ---------------------------------------------------------------------------
# whole sites
# ---------------------------------------------------------------------------

def shop() -> dict:
    return bundle([home(), physical_product(),
                   physical_product("/products/summit-boot", "Summit Boot", "210"),
                   listing("/collections/boots", "Boots",
                           [("/products/trail-boot", "Trail Boot £120"),
                            ("/products/summit-boot", "Summit Boot £210")])])


def family_landing_site() -> dict:
    """The cross-page leak, in its smallest generic form.

    One product-family landing page whose models were never crawled, and one
    unrelated accessory whose attributes *were* read. The two pages share a
    host and nothing else. Any attribute of the accessory appearing in advice
    aimed at the family page is the defect this fixture exists to catch.
    """
    return bundle([
        home(),
        product_family(),
        listing("/collections/accessories", "Accessories",
                [("/products/locator-tag", "Locator Tag £35")]),
        instrument_product(),
    ])


def two_catalogue_site() -> dict:
    """Two genuine catalogues on one host, with disjoint item sets.

    Advice aimed at either one must quote that one's own items. Boots publish
    colour, material and weight; the accessory publishes diameter and height;
    neither set may appear in the other's recommendation.
    """
    return bundle([
        home(),
        physical_product(),
        physical_product("/products/summit-boot", "Summit Boot", "210"),
        instrument_product(),
        instrument_product("/products/locator-clip", "Locator Clip", "25"),
        catalogue_listing("/collections/boots", "Boots",
                          [("/products/trail-boot", "Trail Boot", "120"),
                           ("/products/summit-boot", "Summit Boot", "210")]),
        catalogue_listing("/collections/accessories", "Accessories",
                          [("/products/locator-tag", "Locator Tag", "35"),
                           ("/products/locator-clip", "Locator Clip", "25")]),
    ])


def golden_site() -> dict:
    """One host carrying every shape this auditor has to tell apart.

    The fixture the 1.11.1 false-positive work is judged against. Its value is
    as much in what must *not* be reported as in what must:

    ============================  =========================================
    element                       what it exists to prove
    ============================  =========================================
    physical product              stock, shipping, returns and specs apply
    software product              they do not apply to a download
    subscription plan             nor to a plan
    service page                  nor to a visit
    article                       no commerce expectation at all
    documentation page            nor here
    public-sector guidance        nor here
    genuine ecommerce listing     filter/sort assessed against known members
    ambiguous listing             reported honestly, advised of nothing
    product-family landing page   not a catalogue
    comparison page               a set, but not one to filter
    localized pages               another language, not a rival trading name
    rendered-only facts           absent from the response, not from the page
    unrelated outbound links      documentation and knowledge links are not
                                  official profiles
    search endpoint               not a content page, not a canonical rival
    facet permutation             noindex here is ordinary, not a defect
    ============================  =========================================

    Everything is invented. No element is modelled on, named after or keyed to
    any real site.
    """
    boots = catalogue_listing("/collections/boots", "Boots",
                              [("/products/trail-boot", "Trail Boot", "120"),
                               ("/products/summit-boot", "Summit Boot", "210")])
    pages = [
        home(),
        # --- things that are sold, one of each kind ------------------------
        physical_product(),
        physical_product("/products/summit-boot", "Summit Boot", "210"),
        software_download(),
        subscription_plan(),
        service_page(),
        # --- things that are published --------------------------------------
        news_article("/news/river-report", "River report published"),
        doc_article("/docs/install", "Installing"),
        guidance_page("/guidance/licensing", "Apply for a licence"),
        # --- listings, genuine and not ---------------------------------------
        boots,
        ambiguous_listing(),
        product_family(),
        comparison_page(),
        # --- addresses that are not documents --------------------------------
        search_endpoint(),
        facet_permutation(),
        # --- the same organisation, elsewhere --------------------------------
        localized("/fr/", "Kestrel SARL", "fr", "120 EUR"),
    ]
    data = bundle(pages)
    # One rendered-only fact, attached the way a successful render attaches it:
    # the software page states its price only after hydration.
    rendered_software = software_download()
    rendered_software = dict(rendered_software)
    for page_dict in data["pages"]:
        if page_dict["url"].endswith("/products/studio"):
            page_dict["rendered"] = dict(rendered_software, ok=True)
    return data


def subscription_saas() -> dict:
    return bundle([home(), subscription_plan(),
                   subscription_plan("/plans/business", "Business plan"),
                   doc_article("/docs/start", "Getting started")])


def software_vendor() -> dict:
    return bundle([home(), software_download(),
                   software_download("/products/studio-pro", "Kestrel Studio Pro", "99")])


def documentation() -> dict:
    return bundle([home(), doc_article("/docs/install", "Installing"),
                   doc_article("/docs/configure", "Configuration"),
                   doc_article("/docs/upgrade", "Upgrading"),
                   listing("/docs/", "Documentation",
                           [("/docs/install", "Installing"),
                            ("/docs/configure", "Configuration"),
                            ("/docs/upgrade", "Upgrading")])])


def publisher() -> dict:
    return bundle([home(NEWS_ORG_LD, "The Kestrel Times"),
                   news_article("/news/river-levels", "River levels rise"),
                   news_article("/news/council-plan", "Council approves plan"),
                   news_article("/news/festival", "Festival returns"),
                   listing("/news/", "News",
                           [("/news/river-levels", "River levels rise"),
                            ("/news/council-plan", "Council approves plan"),
                            ("/news/festival", "Festival returns")])])


def audio_publisher() -> dict:
    return bundle([home(NEWS_ORG_LD, "The Kestrel Times"),
                   audio_episode("/audio/one", "River Notes: episode one"),
                   audio_episode("/audio/two", "River Notes: episode two"),
                   audio_episode("/audio/three", "River Notes: episode three"),
                   listing("/audio/", "River Notes",
                           [("/audio/one", "Episode one"), ("/audio/two", "Episode two"),
                            ("/audio/three", "Episode three")])])


def public_body() -> dict:
    return bundle([home(GOV_LD, "Water Regulator"),
                   guidance_page("/apply", "Apply for an abstraction licence"),
                   guidance_page("/renew", "Renew a licence"),
                   _page("/guidance/eligibility", "Who can apply")])


def knowledge_reference() -> dict:
    return bundle([home(), reference_entry("/glossary/aquifer", "Aquifer"),
                   reference_entry("/glossary/catchment", "Catchment"),
                   dataset_entry("/data/river-levels", "River levels, 1990-2026"),
                   listing("/glossary/", "Glossary",
                           [("/glossary/aquifer", "Aquifer"),
                            ("/glossary/catchment", "Catchment")])])


def developer_platform() -> dict:
    return bundle([home(), repository_page("/repos/kestrel-core", "kestrel-core"),
                   repository_page("/repos/kestrel-cli", "kestrel-cli"),
                   api_reference("/api/v2", "Kestrel API v2"),
                   listing("/repos/", "Repositories",
                           [("/repos/kestrel-core", "kestrel-core"),
                            ("/repos/kestrel-cli", "kestrel-cli")])])


def travel() -> dict:
    return bundle([home(), lodging(),
                   lodging("/stays/hill-barn", "Hill Barn"),
                   listing("/stays/", "Places to stay",
                           [("/stays/river-cottage", "River Cottage"),
                            ("/stays/hill-barn", "Hill Barn")])])


def community() -> dict:
    return bundle([home(), forum_thread("/t/one", "How do I calibrate the gauge?"),
                   forum_thread("/t/two", "Reading the catchment data"),
                   forum_thread("/t/three", "Winter maintenance")])


def nonprofit() -> dict:
    return bundle([home(NGO_LD, "Riverbank Trust"),
                   _page("/about", "About the trust"),
                   _page("/volunteer", "Volunteering"),
                   news_article("/news/appeal", "Spring appeal")])


def mixed() -> dict:
    return bundle([home(), physical_product(), software_download(),
                   doc_article("/docs/install", "Installing"),
                   doc_article("/docs/configure", "Configuration")])


#: Sites that sell nothing physical. Every one of these must be free of
#: delivery, stock, returns and catalogue advice.
NON_COMMERCE = (
    ("documentation", documentation),
    ("publisher", publisher),
    ("audio_publisher", audio_publisher),
    ("public_body", public_body),
    ("knowledge_reference", knowledge_reference),
    ("developer_platform", developer_platform),
    ("community", community),
    ("nonprofit", nonprofit),
)

#: Sites that sell something, but not a parcel.
NON_PHYSICAL_SELLERS = (
    ("subscription_saas", subscription_saas),
    ("software_vendor", software_vendor),
    ("travel", travel),
)

ALL_SHAPES = (("shop", shop),) + NON_PHYSICAL_SELLERS + NON_COMMERCE + (("mixed", mixed),)
