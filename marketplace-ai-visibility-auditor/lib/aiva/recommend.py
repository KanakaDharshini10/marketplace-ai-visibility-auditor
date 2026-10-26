"""Proactive recommendations - improvements that are *not* defects.

The brief asks for suggestions that "go beyond the detected problems". These
are the moves that strengthen how an organisation is found, cited and
experienced even when nothing is technically broken. Anything that *is* a
defect belongs in a specialist skill as a finding; this module deliberately
only emits opportunities.

Every recommendation is an entry in a **library** with applicability
metadata - which kinds of site it applies to, which page kinds it concerns,
what must have been observed before it is offered, and why - and is emitted
only when the site's semantic shape (:mod:`aiva.semantics`) satisfies those
conditions. A comparison-page recommendation is a recommendation for a site
that sells a range; offered to a government department, a documentation site
or a broadcaster it is advice about a business they are not in, and it was
being offered to all of them. Each emitted recommendation carries the
conditions it was gated on, so the reader can see why it appears.

Wording constraints, enforced by the compliance suite: a recommendation says
what a change *provides* (explicit machine-readable evidence, a stated fact,
a page that can be linked to) and may say what it *may* improve; it never
asserts how any assistant, retrieval system or crawler behaves, because this
audit measures none of them.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from . import evidence as ev
from . import examples, semantics
from .analysis import (PLACEHOLDER, attribute_phrase, commerce_guard, example_attributes,
                       named, readable_pages, site_vocabulary)
from .extract import find_nodes, prop

Opportunity = Dict[str, Any]

#: What a proactive recommendation rests on. Rendered in the report, because
#: "we noticed this about your site" and "this is good practice generally" are
#: different claims and only one of them needs evidence.
GROUNDING = ("evidence_backed", "site_personalised", "generic")

#: Site kinds grouped by what they publish, for the applicability tables.
SELLING_KINDS = frozenset({"ecommerce", "marketplace", "travel_hospitality", "software",
                           "services", "mixed"})
#: Every kind that is an organisation - which is every kind. Kept as an
#: explicit set rather than "any" so that a new site kind has to be considered
#: here rather than inheriting organisation advice by accident.
ORGANISATION_KINDS = frozenset({"ecommerce", "marketplace", "travel_hospitality", "software",
                                "services", "corporate", "government", "education",
                                "publisher", "documentation", "developer_platform",
                                "knowledge_reference", "nonprofit", "community", "mixed",
                                "unknown"})

#: The recommendation library: applicability metadata for every entry, in one
#: place, so the conditions can be read and tested without running a
#: generator. ``site_kinds`` names the kinds of site the entry is for
#: (``"any"`` means every kind); ``page_contexts`` the kinds of page it
#: concerns; ``evidence_requirement`` what must have been observed.
LIBRARY: Dict[str, Dict[str, Any]] = {
    "OPP-BRAND-FACTS": {
        "title": "Publish a single machine-readable fact page about the organisation and keep "
                 "every surface pointed at it",
        "site_kinds": "any", "page_contexts": ("home", "about"),
        "evidence_requirement": "an organisation identity is declared or named on the site, "
                                "and no page already carries a well-described Organization node",
        "grounding": "generic", "priority": "medium", "effort": "medium", "impact": "medium",
        "dimension": "discoverability",
    },
    "OPP-EXPLICIT-ABSENCE": {
        "title": "Publish the negative facts, not only the positive ones",
        "site_kinds": frozenset({"ecommerce", "marketplace", "mixed"}),
        "page_contexts": ("product",),
        "evidence_requirement": "physical goods sold with published attributes",
        "grounding": "site_personalised", "priority": "medium", "effort": "medium",
        "impact": "high", "dimension": "discoverability",
    },
    "OPP-INTENT-COVERAGE": {
        "title": "Publish the other framings of the question, not just the item page",
        "site_kinds": SELLING_KINDS, "page_contexts": ("product", "faq", "article"),
        "evidence_requirement": "items sold online, and no FAQ-shaped or explanatory page "
                                "or hreflang alternates among the pages read",
        "grounding": "site_personalised", "priority": "medium", "effort": "medium",
        "impact": "high", "dimension": "discoverability",
    },
    "OPP-ANSWER-PAGES": {
        "title": "Publish comparison and 'which one for what' pages for the range you sell",
        "site_kinds": SELLING_KINDS, "page_contexts": ("product", "category"),
        "evidence_requirement": "two or more comparable sellable items were read",
        "grounding": "generic", "priority": "medium", "effort": "medium", "impact": "high",
        "dimension": "discoverability",
    },
    "OPP-REFERRAL-CONTINUITY": {
        "title": "Make every deep link land on the specific page it names",
        "site_kinds": "any", "page_contexts": ("product", "article", "faq", "support", "policy"),
        "evidence_requirement": "two or more deep content pages were read",
        "grounding": "generic", "priority": "medium", "effort": "medium", "impact": "medium",
        "dimension": "engagement",
    },
    "OPP-PRODUCT-GROUP": {
        "title": "Model size/colour variants as ProductGroup + hasVariant instead of one flat Product",
        "site_kinds": frozenset({"ecommerce", "marketplace", "mixed"}),
        "page_contexts": ("product",),
        "evidence_requirement": "variant pickers on physical-goods product pages and no "
                                "ProductGroup markup",
        "grounding": "evidence_backed", "priority": "high", "effort": "medium", "impact": "high",
        "dimension": "discoverability",
    },
    "OPP-MONITORING": {
        "title": "Stand up a recurring answer-monitoring set instead of auditing once",
        "site_kinds": "any", "page_contexts": ("home",),
        "evidence_requirement": "none - a standing practice for any site",
        "grounding": "generic", "priority": "medium", "effort": "low",
        "impact": "medium", "dimension": "discoverability",
    },
    "OPP-KNOWLEDGE-ANCHOR": {
        "title": "Link the organisation to an independent knowledge-base entry where one "
                 "exists or is warranted",
        "site_kinds": ORGANISATION_KINDS, "page_contexts": ("home", "about"),
        "evidence_requirement": "an organisation is declared, and no sameAs or link to a "
                                "knowledge-base entry about it was found",
        "grounding": "evidence_backed", "priority": "low", "effort": "high", "impact": "medium",
        "dimension": "discoverability",
    },
    "OPP-POLICY-AS-DATA": {
        "title": "State shipping, returns and warranty as structured data, not just prose",
        "site_kinds": frozenset({"ecommerce", "marketplace", "mixed"}),
        "page_contexts": ("product", "policy"),
        "evidence_requirement": "physical goods sold on the site and no MerchantReturnPolicy "
                                "or OfferShippingDetails markup",
        "grounding": "evidence_backed", "priority": "medium", "effort": "low", "impact": "medium",
        "dimension": "engagement",
    },
    "OPP-PRODUCT-FEED": {
        "title": "Expose a public, versioned product data feed at a stable URL",
        "site_kinds": frozenset({"ecommerce", "marketplace", "mixed"}),
        "page_contexts": ("product",),
        "evidence_requirement": "physical or digital goods sold with priced offers",
        "grounding": "evidence_backed", "priority": "medium", "effort": "medium",
        "impact": "medium", "dimension": "discoverability",
    },
    "OPP-AI-DISCOVERY-SURFACE": {
        "title": "Publish an agent-facing index (/llms.txt or /agents.md) of the pages you "
                 "want quoted",
        "site_kinds": "any", "page_contexts": ("home",),
        "evidence_requirement": "a content page was read, and every probed index location "
                                "conclusively answered not-found or empty",
        "grounding": "evidence_backed", "priority": "medium", "effort": "low", "impact": "medium",
        "dimension": "discoverability",
    },
    "OPP-THIRD-PARTY-SYNC": {
        "title": "Run a correction pass over the third-party copies of your facts",
        "site_kinds": ORGANISATION_KINDS, "page_contexts": ("home", "about"),
        "evidence_requirement": "the site declares off-site profiles or is an organisation "
                                "whose facts are repeated elsewhere",
        "grounding": "generic", "priority": "low", "effort": "high", "impact": "medium",
        "dimension": "discoverability",
    },
}


def _opp(oid: str, *, mechanism: str, why_now: str, steps: List[str],
         applies_because: str, conditions: List[str], verification: str = "",
         verification_type: str = "self_verifiable", example: str = "",
         site_kind: str = "unknown", title: Optional[str] = None,
         priority: Optional[str] = None) -> Opportunity:
    """One proactive recommendation, built from its library entry.

    ``verification_type`` says how the verification step can be checked, and
    it matters most here: several of these are verified by asking an assistant
    or by segmenting analytics, neither of which this auditor can observe.
    Labelling them keeps a reader from reading "confirm it returns the exact
    number of days" as something the audit already confirmed.

    ``applies_because`` and ``conditions`` are the applicability record: what
    about *this* site satisfied the library entry's requirements.
    """
    spec = LIBRARY[oid]
    if spec["grounding"] not in GROUNDING:
        raise ValueError(f"{oid}: unknown grounding {spec['grounding']!r}")
    kinds = spec["site_kinds"]
    return {
        "id": oid,
        "type": "proactive",
        "grounding": spec["grounding"],
        "title": title or spec["title"],
        "dimension": spec["dimension"],
        "mechanism": mechanism,
        "why_now": why_now,
        "steps": steps,
        "effort": spec["effort"],
        "impact": spec["impact"],
        "priority": priority or spec["priority"],
        "verification": verification,
        "verification_type": verification_type,
        "example": example,
        "applicability": {
            "site_kind": site_kind,
            "applies_because": applies_because,
            "conditions": conditions,
            "evidence_requirement": spec["evidence_requirement"],
            "site_kinds": "any" if kinds == "any" else sorted(kinds),
            "page_contexts": list(spec["page_contexts"]),
        },
    }


def _site_kind_allowed(oid: str, ctx: dict) -> bool:
    kinds = LIBRARY[oid]["site_kinds"]
    if kinds == "any":
        return True
    kind = ctx.get("site_kind") or "unknown"
    if kind in kinds:
        return True
    if kind == "mixed":
        return any(component in kinds for component in ctx.get("components") or [])
    return False


def _organisation_declared(bundle: dict, ctx: dict) -> bool:
    return bool(ctx.get("organization_names")) or bool(ctx.get("organization_types"))


# ---------------------------------------------------------------------------
# individual generators
# ---------------------------------------------------------------------------

def _ai_discovery_surface(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """Recommend an agent-facing index only when the site publishes none.

    Two conventions are in circulation - ``/llms.txt`` and ``/agents.md`` - and
    a site that already ships either one has solved this. Recommending a second
    file to a site that already has one would be noise.
    """
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    well_known = bundle.get("well_known", {}) or {}
    surfaces = dict(well_known.get("ai_surfaces", {}) or {})
    # A bundle produced before ai_surfaces existed still carries llms_txt.
    if "llms_txt" not in surfaces and well_known.get("llms_txt"):
        surfaces["llms_txt"] = well_known["llms_txt"]
    if any(surface.get("present") for surface in surfaces.values()):
        return None

    # Recommending "publish an agent index" is a claim that the site has none,
    # so it needs positive evidence of absence for every surface probed - a
    # real 404/410, or a 200 that served an empty file. A refusal (401/403/429),
    # a server or gateway error (5xx), a timeout, or a probe that never ran are
    # all inconclusive: the file may well be served to a browser. Reading any of
    # them as "absent" draws a claim about the site from a fact about the path
    # between this auditor and the origin.
    def _conclusively_absent(surface: dict) -> bool:
        if not surface.get("checked"):
            return False
        status = surface.get("status")
        if status in (404, 410):
            return True
        return status == 200 and not surface.get("present")

    if not surfaces or not all(_conclusively_absent(s) for s in surfaces.values()):
        return None
    if not readable_pages(bundle):
        return None
    host = ev.site_host(bundle)
    probed = ", ".join(surface.get("url", "") for surface in surfaces.values()) or \
        f"https://{host}/llms.txt"
    kind = ctx.get("site_kind") or "unknown"
    what = {
        "ecommerce": "the brand fact page, the top product pages, the category hubs, "
                     "shipping, returns, warranty and FAQ",
        "marketplace": "the fact page about the platform, the category hubs, the policy pages "
                       "for buyers and sellers, and the FAQ",
        "software": "the product overview, pricing, documentation entry points, release notes "
                    "and the support/FAQ pages",
        "services": "the service pages, the pricing or quote page, the service area, the "
                    "contact page and the FAQ",
        "documentation": "the getting-started page, the reference sections, the FAQ and the "
                         "release notes",
        "publisher": "the about page, the section fronts, the editorial standards and "
                     "corrections pages",
        "government": "the services the department provides, the guidance pages, the contact "
                      "page and the pages explaining who the department is",
        "education": "the about page, admissions, the course index and the contact page",
        "community": "the about page, the getting-started guide, the rules and the FAQ",
    }.get(kind, "the pages that state the facts you most want quoted: who you are, what you "
                "do, and where the answers to common questions live")
    return _opp(
        "OPP-AI-DISCOVERY-SURFACE",
        site_kind=kind,
        applies_because=(f"{ctx.get('content_pages')} content pages were read, and every probed "
                         f"index location answered not-found or empty"),
        conditions=["no /llms.txt or /agents.md served",
                    "every probe conclusive (404/410 or an empty 200)",
                    "at least one content page read"],
        mechanism=(
            "An agent-facing index is a plain-text, machine-readable map naming which URLs "
            "carry the canonical answer to the questions the site is asked. It provides "
            "explicit evidence of where the facts are, on one fetch; how any given agent "
            "uses it, or whether it reads it at all, is not something this audit measures."
        ),
        why_now=f"Neither convention was served during this audit (probed: {probed}).",
        steps=[
            "Create /llms.txt with an H1 of the organisation's name and a one-line description.",
            f"List, as markdown links with a short gloss each: {what}.",
            "Keep every linked page server-rendered and under the same canonical host.",
            "Link it from robots.txt with a comment and list it in your sitemap so it is "
            "discoverable without guessing the path.",
            "If you prefer the /agents.md convention, publish that instead - one is enough, "
            "and both should say the same thing if you ship both.",
        ],
        verification="curl -s https://%s/llms.txt | head -40 returns the index, and each "
                     "linked URL returns 200 with the fact visible in the raw HTML." % host,
        example=examples.llms_txt(site_vocabulary(bundle), ctx),
    )


def _brand_fact_endpoint(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """A single authoritative fact page about the organisation.

    Scoped to organisations, and suppressed when the site already carries a
    well-described Organization node: telling such a site to publish what it
    has published is noise.
    """
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    if not _organisation_declared(bundle, ctx):
        return None
    for page in readable_pages(bundle):
        for node in find_nodes(page.get("jsonld_nodes") or [], "Organization", "Corporation",
                               "GovernmentOrganization", "NewsMediaOrganization",
                               "EducationalOrganization", "NGO", "OnlineStore"):
            fields = [k for k in ("name", "description", "url", "address", "foundingDate",
                                  "sameAs", "contactPoint", "legalName", "logo")
                      if prop(node, k) not in (None, "", [])]
            if len(fields) >= 5:
                return None
    host = ev.site_host(bundle)
    kind = ctx.get("site_kind") or "unknown"
    facts = {
        "ecommerce": "legal entity name, trading name, founded, HQ location, official "
                     "profiles, and the current product line with model names",
        "marketplace": "legal entity name, trading name, founded, HQ location, what the "
                       "platform is for, and official profiles",
        "software": "legal entity name, product name(s), current version, founded, HQ "
                    "location, licence, and official profiles",
        "services": "legal entity name, trading name, services offered, service area, "
                    "founded, address, and official profiles",
        "government": "the official name of the body, its remit, its parent department or "
                      "ministry, the services it provides, and how to contact it",
        "education": "the official name, what it teaches, its location, its accreditation, "
                     "and how to contact it",
        "publisher": "the masthead's official name, its owner, its editorial standards, "
                     "founded, and official profiles",
        "documentation": "the project's official name, who maintains it, its licence, its "
                         "current version, and where the source and the community live",
        "community": "the community's official name, who runs it, its purpose, and where "
                     "its official channels are",
    }.get(kind, "official name, what the organisation does, founded, location, and official "
                "profiles")
    return _opp(
        "OPP-BRAND-FACTS",
        site_kind=kind,
        applies_because=f"an organisation is named on the site ({kind}) and no page carries an "
                        f"Organization node describing it in five or more properties",
        conditions=["an organisation identity is declared or named",
                    "no well-described Organization node (5+ properties) on any page read"],
        mechanism=(
            "One URL that states the organisation's facts in plain text and mirrors them in "
            "Organization JSON-LD provides a single explicit, machine-readable statement of "
            "record - the page every other surface, and every correction elsewhere, can be "
            "pointed at. Whether any system prefers it to older copies is not something this "
            "audit measures."
        ),
        why_now="A single canonical fact page makes later corrections cheap: every third-party "
                "copy can be pointed at one authoritative statement.",
        steps=[
            f"Create one server-rendered page (for example /about or /organisation) stating: "
            f"{facts}.",
            "Mirror the same facts in an Organization node on that page, with sameAs to every "
            "official profile.",
            "Add 'last reviewed' with a visible date and dateModified in the markup.",
            "Reference the page from the footer of every page and from /llms.txt.",
        ],
        verification=f"Fetch the fact page with curl and confirm each fact appears in the HTML "
                     f"and in the Organization JSON-LD; ask an assistant what {host} is and "
                     f"compare its answer with the page.",
        verification_type="external_validation",
    )


def _knowledge_anchor(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """A knowledge-base entry *about the organisation*, where one is warranted.

    A link to an encyclopaedia article about some other subject is not an
    anchor for the entity, so only entity-matching knowledge links, and
    anything declared as sameAs, count as already having one.
    """
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    if not _organisation_declared(bundle, ctx):
        return None
    anchors = bundle.get("declared_anchors", []) or []
    for anchor in anchors:
        if anchor.get("link_kind") == "knowledge_reference" and (
                anchor.get("entity_match") or anchor.get("declared_as_sameas")
                or anchor.get("in_site_chrome")):
            return None
        if "link_kind" not in anchor and anchor.get("is_knowledge_host"):
            return None
    kind = ctx.get("site_kind") or "unknown"
    return _opp(
        "OPP-KNOWLEDGE-ANCHOR",
        site_kind=kind,
        applies_because="an organisation is declared and no sameAs or entity-matching link to a "
                        "public knowledge base or registry was found",
        conditions=["an organisation identity is declared",
                    "no knowledge-base entry about the organisation is linked or declared"],
        mechanism=(
            "A knowledge-base or registry entry is an independent, machine-readable "
            "description of the organisation, and a sameAs pointing at it is the explicit "
            "statement that the two are the same entity. That provides evidence a similarly "
            "named organisation cannot be confused with; whether any system uses it is not "
            "something this audit measures."
        ),
        why_now="No outbound link to a knowledge-base entry about the organisation, and no "
                "sameAs, was found in the crawled pages.",
        steps=[
            "Check whether a registry or knowledge-base entry already exists (a company "
            "register, a research or organisation identifier, an encyclopaedia article), and "
            "declare it in Organization.sameAs.",
            "Where none exists and the organisation meets the relevant notability and "
            "conflict-of-interest rules, follow each knowledge base's own process - never "
            "author an entry covertly.",
            "Use one exact official name string on the site and in every entry.",
        ],
        verification="Organization.sameAs lists at least one knowledge-base or registry entry "
                     "that names this organisation.",
        verification_type="external_validation",
    )


def _product_feed(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    priced = [p for p in ev.product_pages(bundle)
              if semantics.is_price_applicable(p, ctx)
              and semantics.product_record(p, ctx).get("subtype")
              in ("physical", "digital", "marketplace_listing")]
    if len(priced) < 2:
        return None
    return _opp(
        "OPP-PRODUCT-FEED",
        site_kind=ctx.get("site_kind") or "unknown",
        applies_because=f"{len(priced)} product page(s) selling physical or digital goods with a "
                        f"price were read",
        conditions=["two or more product pages selling goods with a price"],
        mechanism=(
            "Page-by-page crawling samples a catalogue; a feed states it. A single crawlable "
            "feed provides every item's price, availability and identifier in one "
            "machine-readable document, so a change is visible in one fetch instead of a "
            "re-crawl of every page. Which consumers read feeds is not measured here."
        ),
        why_now="Product pages exist, so the catalogue data already exists in a database - "
                "publishing it costs one endpoint.",
        steps=[
            "Publish /feeds/products.json (and optionally a merchant-centre style feed) with "
            "sku, gtin, mpn, name, brand, category, price, currency, availability, "
            "canonical URL, image, and lastModified per item.",
            "Serve it uncompressed under 10MB per file, paginate with a next link if larger.",
            "Reference the feed from robots.txt as a comment and from /llms.txt.",
            "Regenerate on every price or stock change, never on a nightly-only cadence.",
        ],
        verification="Diff the feed against three live product pages; price, availability and "
                     "title must match exactly.",
    )


def _variant_modelling(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    products = [p for p in ev.product_pages(bundle)
                if semantics.is_physical_specs_applicable(p, ctx)]
    if not products:
        return None
    has_group = any("productgroup" in {t.lower() for t in p.get("jsonld_types", [])}
                    for p in products)
    has_variant_ui = any(p.get("variants", {}).get("variant_selects", 0) or
                         p.get("variants", {}).get("variant_swatches", 0)
                         for p in products)
    if has_group or not has_variant_ui:
        return None
    return _opp(
        "OPP-PRODUCT-GROUP",
        site_kind=ctx.get("site_kind") or "unknown",
        applies_because="variant pickers were observed on physical-goods product pages and no "
                        "ProductGroup markup was found",
        conditions=["physical goods", "variant selects or swatches in the HTML",
                    "no ProductGroup node"],
        mechanism=(
            "When each variant is an unlabelled option inside one Product, no typed fact "
            "states one variant's price or stock. ProductGroup/hasVariant with variesBy "
            "makes each variant an explicit, machine-readable entity with its own offer, "
            "sku and availability."
        ),
        why_now="Variant pickers were detected on product pages but no ProductGroup markup "
                "was found.",
        steps=[
            "Emit ProductGroup with productGroupID and variesBy naming the properties that "
            "actually vary across this range.",
            "Emit one Product per variant under hasVariant with its own sku, gtin, the "
            "varying properties and its own Offer (price + availability).",
            "Give each variant a stable, crawlable URL (?variant=... that server-renders).",
        ],
        verification="Fetch a product page with curl and confirm each in-stock size appears as "
                     "its own hasVariant node with an availability value.",
        example=examples.variant_group_jsonld(site_vocabulary(bundle)),
    )


def _answer_pages(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """Comparison pages, for a site that sells a range a visitor would compare.

    Not for a documentation site, a publisher, a public body or a school:
    none of them sells a range, and "publish 'best X for Y' pages" is advice
    about a business they are not in.
    """
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    comparable = semantics.is_comparison_applicable(bundle, ctx)
    if not comparable:
        return None
    kind = ctx.get("site_kind") or "unknown"
    vocab = site_vocabulary(bundle)
    subject = named(vocab, "product")
    shape = {
        "software": "plan-comparison and 'which edition do I need' pages",
        "services": "'which service do I need' and 'what does it cost for my case' pages",
        "marketplace": "category comparison and 'how to choose' guides",
    }.get(kind, "comparison and 'best <item> for <use>' pages")
    return _opp(
        "OPP-ANSWER-PAGES",
        site_kind=kind,
        applies_because=f"{comparable['reason']}, on a {kind} site",
        conditions=["two or more comparable sellable items were read"],
        mechanism=(
            "A page whose heading is the question and whose body is a comparison table "
            "states the answer to a constrained question explicitly, in one place, where a "
            "listing states only the range. That provides a page that can be quoted and "
            "linked to for that question; whether any system retrieves it is not something "
            "this audit measures."
        ),
        why_now=f"The site sells a range ({comparable['reason']}) and comparison-shaped content "
                f"is the direct way to state how its items differ.",
        steps=[
            "List the 10-20 questions your buyers actually ask, from support tickets, "
            "on-site search logs and marketplace Q&A. This audit generates its questions "
            "from your content, not from anyone's behaviour, so your own sources are the "
            "ones that know.",
            f"Publish {shape}, each at its own URL with the question as the heading and a "
            f"direct answer in the first paragraph (e.g. about {subject}).",
            "Include an HTML <table> comparing the items on the attributes the question "
            "cares about, with units, and link each row to its own page.",
            "Mark the page up with FAQPage or ItemList as appropriate and keep it updated.",
        ],
        verification="Re-ask the same questions in a browsing-enabled assistant, monthly, "
                     "and record whether the page is cited.",
        verification_type="external_validation",
    )


def _referral_continuity(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """Deep links that land on the page they name - generic to any site with
    deep content, framed in that site's own page kinds."""
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    deep = [p for p in readable_pages(bundle)
            if p.get("page_type") in ("product", "article", "faq", "support", "policy")]
    if len(deep) < 2:
        return None
    kind = ctx.get("site_kind") or "unknown"
    unit = {"ecommerce": "product page", "marketplace": "listing", "software": "product or "
            "documentation page", "documentation": "documentation section",
            "developer_platform": "repository or API reference page",
            "publisher": "article", "government": "guidance page",
            "travel_hospitality": "property or booking page",
            "knowledge_reference": "entry", "community": "thread",
            "nonprofit": "programme or appeal page",
            "education": "course or guidance page"}.get(kind, "content page")
    # The decisive fact is whatever this kind of page exists to state.
    decisive = {"ecommerce": "the price and whether it is available",
                "marketplace": "the price, the seller and the condition",
                "software": "what it does, what it costs and which platforms it runs on",
                "documentation": "the step, the command or the configuration value",
                "developer_platform": "what the project does and how to install or call it",
                "publisher": "the claim the headline makes, and when it was published",
                "government": "who is eligible and what to do next",
                "travel_hospitality": "where it is, what it includes and what it costs",
                "knowledge_reference": "the definition or the value",
                "community": "the accepted answer",
                "education": "what the course covers and who it is for",
                "nonprofit": "what the programme does and how to take part",
                }.get(kind, "the fact the page exists to state")
    return _opp(
        "OPP-REFERRAL-CONTINUITY",
        site_kind=kind,
        applies_because=f"{len(deep)} deep content pages were read on a {kind} site",
        conditions=["two or more deep content pages read"],
        mechanism=(
            "A visitor who arrives by a link was pointed at something specific. A deep link "
            "that resolves to the exact page, with the decisive fact stated early in the "
            "server-rendered HTML, provides that fact at the point of arrival instead of "
            "leaving it to be searched for. How often visitors arrive this way, and what they "
            "do next, is not something this audit measures."
        ),
        why_now="Every quotable fact on the site is a potential landing page, and a landing "
                "page that answers the question it was linked for needs nothing else.",
        steps=[
            f"Deep-link from every quotable fact to the exact {unit}, never the home page, "
            f"and never collapse retired URLs onto the front door.",
            f"Keep what the page exists to state - {decisive} - in the first screen of "
            f"server-rendered markup, before long-form copy.",
            "Where a documented intent parameter is read (for example ?intent=...), "
            "server-render the matching one-line context strip; use first-party storage only.",
            "Give each section a breadcrumb and onward links so a near-miss landing has a "
            "path to the right page.",
        ],
        verification="Segment analytics by referrer and compare bounce rate and "
                     "time-to-first-interaction against organic search.",
        verification_type="requires_external_data",
    )


def _monitoring(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """Standing recommendation: whether an organisation watches what is said
    about it leaves no trace in its HTML, so this is never suppressed."""
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    host = ev.site_host(bundle)
    kind = ctx.get("site_kind") or "unknown"
    vocab = site_vocabulary(bundle)
    probe = examples.monitoring_probe(vocab, ctx)
    question_set = {
        "ecommerce": "10 category questions, 10 brand-fact questions (return window, delivery "
                     "time, who you are), and 10 product questions",
        "software": "10 'how do I' questions, 10 product-fact questions (pricing, requirements, "
                    "who makes it), and 10 comparison questions",
        "documentation": "20 'how do I' questions taken from the documentation's own headings, "
                         "and 10 questions about what the project is",
        "government": "20 'how do I' and 'am I eligible' questions about the services the "
                      "body provides, and 10 about what the body is",
        "publisher": "20 questions about subjects the site covers, and 10 about who "
                     "publishes it",
    }.get(kind, "20 questions about what the organisation does, and 10 about who it is")
    return _opp(
        "OPP-MONITORING",
        site_kind=kind,
        applies_because="a standing practice for any site; this audit is a point-in-time "
                        "snapshot",
        conditions=["none: a standing practice for any site that wants to know how its "
                    "published facts are being read"],
        mechanism=(
            "A fixed question set turned into a weekly measurement converts 'are we visible?' "
            "from an opinion into a series of observations that can be compared over time; "
            "this audit makes one such observation, of the site alone."
        ),
        why_now="This audit is a point-in-time snapshot; the gaps it detects recur silently.",
        steps=[
            f"Freeze ~30 questions in your own nouns: {question_set}, for example "
            f"{probe!r}.",
            "Run them weekly across at least three assistants with browsing enabled.",
            "Record three numbers per question: organisation mentioned (y/n), correct fact "
            "(y/n), own domain cited (y/n).",
            "Re-run this audit on the same cadence and track the pillar scores and the "
            "finding count alongside.",
        ],
        verification=f"A dated spreadsheet or dashboard showing mention-rate, fact-accuracy "
                     f"and citation-rate for {host} over time.",
        verification_type="requires_external_data",
    )


def _third_party_correction(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """Standing recommendation for an organisation whose facts are repeated
    off-site; what those copies say is off-site by definition, so it is
    never gated on the crawl beyond the organisation being one."""
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    if not _organisation_declared(bundle, ctx):
        return None
    kind = ctx.get("site_kind") or "unknown"
    anchors = bundle.get("declared_anchors", []) or []
    profiles = [a for a in anchors if a.get("link_kind") == "official_profile"
                or a.get("declared_as_sameas")]
    where = {
        "ecommerce": "retailer listings, marketplaces, comparison sites, review aggregators "
                     "and directories",
        "software": "app stores, package registries, review platforms, directories and "
                    "third-party documentation",
        "services": "directories, review platforms, maps listings and trade registers",
        "publisher": "media directories, aggregators and encyclopaedia entries",
        "government": "directories, encyclopaedia entries and third-party guidance that "
                      "restates your services",
        "education": "course directories, rankings sites and encyclopaedia entries",
    }.get(kind, "directories, review platforms, encyclopaedia entries and press archives")
    return _opp(
        "OPP-THIRD-PARTY-SYNC",
        site_kind=kind,
        applies_because=(f"an organisation is declared on a {kind} site"
                         + (f", with {len(profiles)} off-site profile(s) linked" if profiles
                            else "")),
        conditions=["an organisation identity is declared"],
        mechanism=(
            "Facts about an organisation are repeated on sites it does not control, and a "
            "correction made only on its own site leaves every older copy stating the old "
            "fact. Correcting the copies provides the same fact in every place it is stated; "
            "how any system weighs agreement between sources is not something this audit "
            "measures."
        ),
        why_now="Updating the site is necessary but not sufficient: copies of its facts live "
                "off-site, and this audit can only see what the site itself declares.",
        steps=[
            f"Inventory where your facts are repeated: {where}.",
            "For each, submit the correction through that source's own supported channel "
            "- a listing or profile claim, a partner or seller portal where one exists, an "
            "editorial correction request - never by scraping or editing anything you do "
            "not own.",
            "Publish a dated changelog page for renames, rebrands and discontinuations so "
            "third parties have something citable to point at.",
            "Re-check the highest-traffic ten sources quarterly.",
        ],
        verification="Count of third-party sources stating the current fact, tracked "
                     "quarterly.",
        verification_type="requires_external_data",
    )


def _policy_facts(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    pages = ev.pages(bundle)
    if not pages:
        return None
    # Shipping and returns markup is a physical-goods concern. A software
    # catalogue, a service and a news organisation have no delivery to
    # describe, and telling them otherwise is advice about a business they
    # are not in.
    if not commerce_guard(bundle):
        return None
    physical = [p for p in ev.product_pages(bundle) if semantics.is_shipping_applicable(p, ctx)]
    if not physical:
        return None
    has_policy_schema = any(
        find_nodes(p.get("jsonld_nodes", []) or [], "MerchantReturnPolicy",
                   "OfferShippingDetails")
        for p in pages)
    if has_policy_schema:
        return None
    return _opp(
        "OPP-POLICY-AS-DATA",
        site_kind=ctx.get("site_kind") or "unknown",
        applies_because=f"{len(physical)} product page(s) sell physical goods and no "
                        f"MerchantReturnPolicy or OfferShippingDetails markup was found",
        conditions=["physical goods sold on the site",
                    "no MerchantReturnPolicy / OfferShippingDetails node on any page read"],
        mechanism=(
            "'Can I return this?' and 'when does it arrive?' are questions about physical "
            "goods. MerchantReturnPolicy and OfferShippingDetails state the window, the cost "
            "and the destination as typed values, which provides the same facts in a form "
            "that does not depend on parsing the policy page's prose."
        ),
        why_now="No MerchantReturnPolicy or OfferShippingDetails markup was found on any "
                "crawled page.",
        steps=[
            "Add hasMerchantReturnPolicy to every Offer with merchantReturnDays, "
            "returnPolicyCategory, returnMethod and returnFees.",
            "Add shippingDetails with deliveryTime (handling + transit) and shippingRate "
            "per shippingDestination.",
            "Keep the visible policy page in agreement with the markup, word for word on "
            "the numbers.",
        ],
        verification="Ask an assistant what this organisation's return window is and confirm "
                     "it returns the exact number of days stated on the policy page.",
        verification_type="external_validation",
    )


def _explicit_absence(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """Say what a physical product is *not*, so nothing is left to be filled in.

    Gated on physical goods with published attributes: a page with no
    attributes to negate has nothing to publish here, and a download or a
    service has no 'waterproof' to be silent about.
    """
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    if not commerce_guard(bundle):
        return None
    physical = [p for p in ev.product_pages(bundle)
                if semantics.is_physical_specs_applicable(p, ctx)]
    if not physical:
        return None
    # The worked example quotes the physical pages' own attributes: a
    # software page's 'applicationCategory' is not something a boot lacks.
    vocab = site_vocabulary(bundle, pages=physical)
    attributes = [a for a in example_attributes(vocab, limit=3) if a != PLACEHOLDER["attribute"]]
    if not attributes:
        return None
    subject = named(vocab, "product")
    return _opp(
        "OPP-EXPLICIT-ABSENCE",
        site_kind=ctx.get("site_kind") or "unknown",
        applies_because=f"{len(physical)} product page(s) sell physical goods and publish "
                        f"attributes ({attribute_phrase(vocab, limit=3)})",
        conditions=["physical goods sold on the site", "attributes observed on product pages"],
        mechanism=(
            "A page that never mentions a feature gives a reader no stated fact about it "
            "either way, so a question about that feature has nothing on this page to be "
            "answered from. An explicit negative ('no wireless charging', 'not waterproof') "
            "replaces the gap with a stated fact that can be quoted. Whether any given "
            "assistant fills such gaps, and how, is not something this audit measures."
        ),
        why_now=f"This site publishes {attribute_phrase(vocab, limit=3)} for its catalogue, "
                f"so the attributes a buyer would ask about are addressable - and the ones that are "
                f"absent are the ones with no stated fact to quote.",
        steps=[
            f"List the attributes a buyer would ask about for {subject} - the audit generated "
            f"an attribute question for it from the site's own markup, and cannot see what "
            f"anyone actually asked - including "
            f"the ones you do not offer (waterproofing, warranty extensions, sizes, "
            f"compatibility, certifications, materials).",
            "State each one either way in the page text: 'Not waterproof - water-resistant "
            "to IPX4' beats omitting the line, because an omission states nothing.",
            "Mirror the same values into Product.additionalProperty as PropertyValue "
            "pairs, negatives included, so the fact is typed and not only prose.",
            "Where a product genuinely varies, say so explicitly and link the variant that "
            "does have the attribute, rather than leaving the range ambiguous.",
            "Add the recurring 'does it...' questions to an FAQPage on the product "
            "template, answered in one sentence each.",
        ],
        verification="Ask an assistant a direct question about an attribute you do NOT "
                     "offer and confirm the answer says so, citing your page, rather than "
                     "describing a feature you never claimed.",
        verification_type="external_validation",
        example=('"materialFeature": "Not waterproof", '
                 '"additionalProperty": [{"@type": "PropertyValue", '
                 '"name": "Waterproof", "value": "No"}]'),
    )


def _intent_coverage(bundle: dict, ctx: Optional[dict] = None) -> Optional[Opportunity]:
    """The other framings of a buying question, for a site that sells.

    A documentation site, a publisher and a public body already publish the
    explanatory framings - that is what they are - and are not told to.
    """
    ctx = ctx if ctx is not None else semantics.site_context(bundle)
    pages = ev.pages(bundle)
    if not pages:
        return None
    readable = [p for p in pages if not p.get("fetch_failed") and not p.get("non_html")]
    if len(readable) < 3 or not ctx.get("sells_online"):
        return None

    # Only recommend what the site is missing: a site already publishing
    # comparison and use-case pages is doing this, and does not need telling.
    intent_types = {"faq", "article", "compare"}
    covered = {p.get("page_type") for p in readable} & intent_types
    localized = any((p.get("hreflang_alternates") or []) for p in readable)
    if covered and localized:
        return None

    vocab = site_vocabulary(bundle)
    subject = named(vocab, "product")
    missing = []
    if "faq" not in covered:
        missing.append("no FAQ-shaped page")
    if "article" not in covered:
        missing.append("no explanatory or use-case content")
    if not localized:
        missing.append("no hreflang alternates declared")
    return _opp(
        "OPP-INTENT-COVERAGE",
        site_kind=ctx.get("site_kind") or "unknown",
        applies_because=f"the site sells online and, among {len(readable)} pages read, "
                        + ", ".join(missing),
        conditions=["items sold online", "three or more pages read"] + missing,
        mechanism=(
            "The same underlying question reaches a site in many shapes - by use case, by "
            "budget, by comparison, by constraint, in another language. A page per framing "
            "provides an explicit answer for each shape; a catalogue that exists only as item "
            "pages states an answer for one of them. Which framing any given question takes, "
            "and what any assistant does with it, is not something this audit measures."
        ),
        why_now=f"Crawled {len(readable)} page(s): " + ", ".join(missing) + ".",
        steps=[
            f"Write one page per recurring buying question about {subject}: 'best for X', "
            f"'X vs Y', 'which size/model do I need', 'is this suitable for Z'. Answer in "
            f"the first paragraph, then justify.",
            "Give each a stable URL and link it from the relevant item and category "
            "pages, so it is reachable rather than merely published.",
            "Cover the budget and constraint framings explicitly - price bands, "
            "compatibility, use conditions - in the words customers use, not internal ones.",
            "Where you trade in more than one market, declare hreflang alternates and "
            "localize prices, availability and policy terms rather than translating copy.",
            "Keep every one of these server-rendered: they exist to be fetched.",
        ],
        verification="Ask an assistant three differently-framed versions of the same "
                     "buying question and confirm the site is cited for more than one.",
        verification_type="external_validation",
    )


GENERATORS: List[Callable[..., Optional[Opportunity]]] = [
    _brand_fact_endpoint,
    _explicit_absence,
    _intent_coverage,
    _answer_pages,
    _referral_continuity,
    _variant_modelling,
    _monitoring,
    _knowledge_anchor,
    _policy_facts,
    _product_feed,
    _ai_discovery_surface,
    _third_party_correction,
]

#: Generator -> library id, so the site-kind gate is applied uniformly
#: before any generator runs.
_GENERATOR_IDS = {
    _brand_fact_endpoint: "OPP-BRAND-FACTS",
    _explicit_absence: "OPP-EXPLICIT-ABSENCE",
    _intent_coverage: "OPP-INTENT-COVERAGE",
    _answer_pages: "OPP-ANSWER-PAGES",
    _referral_continuity: "OPP-REFERRAL-CONTINUITY",
    _variant_modelling: "OPP-PRODUCT-GROUP",
    _monitoring: "OPP-MONITORING",
    _knowledge_anchor: "OPP-KNOWLEDGE-ANCHOR",
    _policy_facts: "OPP-POLICY-AS-DATA",
    _product_feed: "OPP-PRODUCT-FEED",
    _ai_discovery_surface: "OPP-AI-DISCOVERY-SURFACE",
    _third_party_correction: "OPP-THIRD-PARTY-SYNC",
}


#: An opportunity is suppressed when a specialist skill already reported the
#: same ground as a defect - proactive advice must never duplicate a finding.
SUPERSEDED_BY = {
    "OPP-PRODUCT-GROUP": {"EN-VARIANTS-UNMODELLED"},
    "OPP-POLICY-AS-DATA": {"EG-POLICY-NOT-STRUCTURED"},
    "OPP-KNOWLEDGE-ANCHOR": {"FC-NO-CORROBORATION-ANCHORS"},
    # Telling a site to publish negative attributes while a finding already
    # reports it publishes no attributes at all is advice about the wrong step.
    "OPP-EXPLICIT-ABSENCE": {"MR-ATTRIBUTES-THIN", "EG-SPECS-MISSING"},
    # The FAQ half of intent coverage is already a defect when this fires.
    "OPP-INTENT-COVERAGE": {"EG-FAQ-MISSING"},
    # The fact page is the Organization node's job when that node is missing.
    "OPP-BRAND-FACTS": {"MR-SITE-SCHEMA-MISSING", "EN-ORG-INCOMPLETE"},
}


def applicability_of(oid: str, bundle: dict) -> Dict[str, Any]:
    """Whether the library entry ``oid`` applies to this site, and why.

    The site-kind gate only; a generator may still decline on evidence.
    Exposed so the conditions can be tested without building a report.
    """
    ctx = semantics.site_context(bundle)
    allowed = _site_kind_allowed(oid, ctx)
    kinds = LIBRARY[oid]["site_kinds"]
    return {
        "id": oid,
        "site_kind": ctx.get("site_kind"),
        "site_kind_allowed": allowed,
        "reason": ("applies to every kind of site" if kinds == "any" else
                   f"a {ctx.get('site_kind')} site is "
                   + ("one of" if allowed else "not one of")
                   + f" the kinds this recommendation is for ({', '.join(sorted(kinds))})"),
        "evidence_requirement": LIBRARY[oid]["evidence_requirement"],
    }


def build_opportunities(bundle: dict, findings: Optional[List] = None) -> List[Opportunity]:
    """Applicability-gated proactive recommendations, highest value first.

    Three gates, in order: the library entry's site kinds (a comparison-page
    recommendation is never offered to a documentation site); the
    generator's own evidence requirement; and the specialist findings, which
    suppress any opportunity that already appears as a defect.

    A run that read no page keeps only the `generic` ones. The other two
    classes both say, in their wording, that something about *this* site was
    looked at, and a crawl refused at the front door looked at nothing.
    """
    covered = {getattr(f, "rule_id", "") for f in (findings or [])}
    read_content = bool(readable_pages(bundle))
    ctx = semantics.site_context(bundle) if read_content else {"site_kind": "unknown"}
    out: List[Opportunity] = []
    for generator in GENERATORS:
        oid = _GENERATOR_IDS[generator]
        if read_content and not _site_kind_allowed(oid, ctx):
            continue
        try:
            opportunity = generator(bundle, ctx)
        except Exception:  # noqa: BLE001 - a bad generator must not kill a report
            opportunity = None
        if not opportunity:
            continue
        if opportunity["id"] in covered:
            continue
        if SUPERSEDED_BY.get(opportunity["id"], set()) & covered:
            continue
        if not read_content and opportunity["grounding"] != "generic":
            continue
        out.append(opportunity)
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(key=lambda o: (rank.get(o["priority"], 3),
                            {"high": 0, "medium": 1, "low": 2}.get(o["impact"], 1)))
    return out
