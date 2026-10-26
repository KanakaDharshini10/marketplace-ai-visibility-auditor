#!/usr/bin/env python3
"""entity-audit - does the site say unambiguously *who* and *what* it is?

Stage four. A question about an organisation is a question about an
*entity*, and a fact extracted from a page has to be attached to something:
this company, this brand, this product, this variant. Where the site does not
state that identity - one name, one set of relationships to its products and
categories - the attachment has to be inferred from the page. This audit
measures what the site publishes about its own identity; it does not observe
any system resolving it.

Consumes the shared evidence bundle. Performs no network I/O.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
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

from urllib.parse import urlsplit               # noqa: E402

from aiva import evidence as ev                      # noqa: E402
from aiva import lexicon                             # noqa: E402
from aiva import semantics                           # noqa: E402
from aiva import util                                # noqa: E402
from aiva.analysis import (crawl_yielded_evidence, absent, action, confidence_for, entity_index,   # noqa: E402
                           coverage_caveat, step_down,
                           entity_name, example_attributes, finding, item_identity,
                           jsonld_nodes, label, named, observed, offers_of, page_items,
                           products_on, sample_guard, scope_for,
                           severity_from_ratio, severity_from_sample,
                           identity_context, site_vocabulary, semantic_context)
from aiva import examples                            # noqa: E402
from aiva.extract import (find_nodes, microdata_items, microdata_props,   # noqa: E402
                          microdata_types, node_types, prop, text_of)
from aiva.findings import Finding                    # noqa: E402

SKILL = "entity-audit"
PILLAR = "entity"

#: Types that identify *the site's own* organisation.
ORG_TYPES = ("Organization", "Corporation", "OnlineStore", "LocalBusiness",
             "Store", "OnlineBusiness")

#: Tokens that appear in a <title> suffix but are not the brand name.
#:
#: This list has to be multilingual or it produces its own worst finding. A
#: Spanish site titled "Bodegas Ejemplo S.L. | Inicio" has no English "home" to
#: strip, so the word-count tiebreak downstream picks the *shorter* half and
#: hands back "Inicio" as the trading name - which then reads as a second brand
#: and fires EN-NAME-INCONSISTENT at `high` against a site whose identity data
#: is complete and correct. Same for Accueil, Início, Startseite, Startpagina.
_TITLE_NOISE_WORDS = (
    # English
    "home", "homepage", "shop", "store", "official site", "official website",
    "official store", "official online store", "buy online", "online store",
    "online shop", "welcome", "welcome to", "the official site",
    # geography that qualifies a brand rather than naming it
    "india", "usa", "us", "uk", "eu", "canada", "australia", "deutschland",
    "espana", "france", "italia", "nederland", "brasil", "mexico",
    # Spanish / Portuguese
    "inicio", "portada", "tienda", "tienda online", "bienvenido", "bienvenidos",
    "pagina principal", "loja", "loja online", "bem vindo", "pagina inicial",
    # French
    "accueil", "boutique", "boutique en ligne", "page d accueil", "bienvenue",
    # German / Dutch
    "startseite", "start", "shop online", "willkommen", "onlineshop",
    "startpagina", "winkel", "welkom", "webshop",
    # Italian
    "pagina iniziale", "negozio", "benvenuto", "benvenuti",
    # Nordic / Polish / Turkish
    "hem", "hjem", "forside", "butikk", "butik", "nettbutikk", "valkommen",
    "strona glowna", "sklep", "sklep internetowy", "witamy",
    "anasayfa", "ana sayfa", "magaza", "resmi site",
)

TITLE_NOISE = re.compile(
    "|".join(re.escape(lexicon.fold(w)).replace(r"\ ", r"[\s\-]+")
             for w in sorted(_TITLE_NOISE_WORDS, key=len, reverse=True)), re.I)


def _is_title_noise(text: str) -> bool:
    """Is this title half a generic label rather than the brand's name?

    Folded before matching so "Inicio", "Início" and "INICIO" are one word, and
    "Anasayfa" is not defeated by its own orthography.
    """
    folded = lexicon.fold(text or "").strip(" -|\u2013\u2014\u00b7:")
    return bool(folded) and bool(TITLE_NOISE.fullmatch(folded))


def organization_nodes(bundle: dict) -> List[dict]:
    """The site's own identity nodes.

    A bare ``Brand`` node is only treated as the site's identity when it is
    declared on the home page: a Brand nested inside a Product is the
    *manufacturer* of that product, and counting it as the site's own name
    would mask exactly the drift this skill exists to detect.
    """
    out: List[dict] = []
    for page in ev.pages(bundle):
        out.extend(find_nodes(jsonld_nodes(page), *ORG_TYPES))
    home = ev.home_page(bundle)
    if home:
        for node in find_nodes(jsonld_nodes(home), "Brand"):
            if node not in out:
                out.append(node)
    return out


def _title_brand(page: dict) -> Optional[str]:
    """The brand segment of a home-page title, or ``None`` if it is ambiguous.

    Titles put the brand at either end: "Organic Coffee Roasters | Acme" and
    "Acme | Organic Coffee Roasters" are both ordinary. Taking the last
    segment unconditionally read the tagline of a brand-first title as a
    second brand name, and reported the site as calling itself two things.

    A segment is only accepted when the other end corroborates it - it matches
    a name the site declares elsewhere - or when one end is clearly not a
    brand. Where neither test settles it, this returns ``None``: a missed
    signal, rather than an invented conflict.
    """
    title = util.collapse_ws(page.get("title") or "")
    if not title:
        return None
    for separator in ("|", "–", "—", " - ", "::", "·"):
        if separator not in title:
            continue
        parts = [p.strip() for p in title.split(separator) if p.strip()]
        if len(parts) < 2:
            return None
        head, tail = parts[0], parts[-1]
        declared = {util.normalize_name(n) for n in _declared_names(page) if n}
        # Corroboration: whichever end the site already calls itself.
        for candidate in (tail, head):
            if util.normalize_name(candidate) in declared:
                return candidate
        # Otherwise prefer the shorter end - a brand is normally shorter than
        # the descriptive half - but only when the difference is decisive.
        if _is_title_noise(tail):
            return head if not _is_title_noise(head) else None
        if _is_title_noise(head):
            return tail
        head_words, tail_words = len(head.split()), len(tail.split())
        if tail_words + 1 < head_words:
            return tail
        if head_words + 1 < tail_words:
            return head
        return None
    return None


def _declared_names(page: dict) -> List[str]:
    """Names this page states about itself outside the title."""
    out: List[str] = []
    og = (page.get("open_graph", {}) or {}).get("og:site_name")
    if og:
        out.append(og)
    for node in find_nodes(jsonld_nodes(page), *ORG_TYPES, "Brand"):
        for key in ("name", "legalName"):
            value = text_of(prop(node, key))
            if value:
                out.append(value)
    return out


#: The reservation-of-rights phrase that follows a company name in a copyright
#: line, in the languages the rest of the auditor reads. Only this phrase is
#: stripped - a corporate suffix is deliberately *kept*, because it is the
#: signal that classifies the remainder as a legal name rather than a trading
#: one. Stripping it would turn "AB DNAM LLC" into "DNAM" and lose both the
#: name and the classification.
_RIGHTS_BOILERPLATE = re.compile(
    r"(?i)\b(all\s+rights?\s+reserved|todos\s+los\s+derechos\s+reservados|"
    r"tous\s+droits\s+r[ée]serv[ée]s|alle\s+rechte\s+vorbehalten|"
    r"todos\s+os\s+direitos\s+reservados|tutti\s+i\s+diritti\s+riservati|"
    r"alle\s+rechten\s+voorbehouden)\b\.?")

#: Suffixes that mark a string as a *legal* entity name rather than a trading
#: one. Presence of any of these is what makes "Example Holdings LLC" a
#: legal-role sighting; it is not a list of brands and never matches a name.
#: Written to tolerate the punctuation having already been stripped, so both
#: "Example S.L." and "Example S L" are recognised as the same legal form.
_LEGAL_SUFFIX = re.compile(
    r"(?i)(?:^|[\s,.])(inc|l\.?\s?l\.?\s?c|ltd|limited|gmbh|"
    r"s\.?\s?a\.?\s?r\.?\s?l|b\.?\s?v|pty|pvt|plc|corp|corporation|company|"
    r"holdings|group|s\.?\s?a|s\.?\s?l|s\.?\s?p\.?\s?a|oy|ab|a\/s|as|nv|kg|ag|"
    r"kft|sp\.?\s?z\.?\s?o\.?\s?o)\.?\s*$")


def looks_like_legal_entity(raw: str) -> bool:
    """Does this string carry a corporate-form suffix?

    Used to *describe* a name, never to reclassify one. The distinction
    matters: plenty of trading names end in a word that also appears in a
    company register - a shop whose name ends in "Spa", "Company" or "Group"
    is not thereby a registered form - and treating those as legal entities
    would quietly exclude them from conflict detection, silencing a real
    finding to avoid a false one. The role of a name comes from *where it was
    declared*, which is unambiguous, rather than from how it ends, which is
    not.
    """
    return bool(_LEGAL_SUFFIX.search(util.collapse_ws(raw or "")))


def _copyright_holders(text: str) -> List[str]:
    """Entity names stated in copyright lines, with the boilerplate removed.

    The previous pattern anchored on the © symbol and captured whatever
    followed it, which on a line reading "Example Ltd © 2026. All Rights
    Reserved" is the reservation of rights and not a name at all. This reads
    the whole line, drops years, symbols and rights boilerplate, and keeps
    what is left only if it still looks like a name.
    """
    out: List[str] = []
    for match in re.finditer(r"(?i)(©|\(c\)|copyright)", text or ""):
        line_start = (text.rfind("\n", 0, match.start()) + 1)
        line_end = text.find("\n", match.end())
        line_end = len(text) if line_end < 0 else line_end
        before = text[line_start:match.start()]
        after = text[match.end():line_end]
        # The holder sits immediately either side of the mark. Taking the whole
        # line instead swallows whatever footer text happens to precede it -
        # "Privacy Terms © 2026 Example Ltd" is not a company called
        # "Privacy Terms Example Ltd".
        candidate = _clean_holder(after) or _clean_holder(before, from_end=True)
        if candidate:
            out.append(candidate)
    return util.dedupe(out)[:4]


def _clean_holder(fragment: str, *, from_end: bool = False) -> Optional[str]:
    """Strip years, symbols and rights boilerplate; keep what reads as a name."""
    cleaned = re.sub(r"\b(19|20)\d{2}(\s*[-–—]\s*(19|20)?\d{2})?\b", " ", fragment or "")
    cleaned = _RIGHTS_BOILERPLATE.sub(" ", cleaned)
    cleaned = re.sub(r"[^\w&'’\- ]+", " ", cleaned, flags=re.UNICODE)
    words = util.collapse_ws(cleaned).split()
    if not words:
        return None
    # Adjacent to the mark: the last few words before it, the first few after.
    words = words[-4:] if from_end else words[:4]
    candidate = " ".join(words)
    if not (2 <= len(candidate) <= 60):
        return None
    # A holder is a name, so at least one word is capitalised or an initialism.
    # "Copyright and licensing" leaves "and licensing", which is prose.
    if not any(w[:1].isupper() or w.isupper() for w in words):
        return None
    return candidate


#: Role precedence, strongest first. A string seen in several roles is
#: reported under the strongest one: a trading name that is also used as a
#: handle is still a trading name.
_ROLE_RANK = {"brand": 0, "legal": 1, "copyright": 2, "social": 3}

#: Path segments that name a *section* of a profile rather than the profile.
#: Generic across platforms: these are the words platforms use for routing,
#: not identities, so the identity is the first segment that is not one.
_PROFILE_SECTIONS = frozenset((
    "company", "c", "user", "users", "profile", "in", "pages", "page",
    "channel", "organization", "organizations", "org", "people", "groups",
    "showcase", "wiki", "about", "posts", "post", "videos", "video",
    "featured", "status", "photos", "reviews", "jobs", "careers", "life",
    "feed", "home", "index", "p", "s", "e", "watch", "shorts", "reel",
))

#: A segment that could be an identity: starts alphanumeric, no spaces.
_HANDLE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{1,39}$")

#: Endings that mark a segment as a script or document, not a name.
_NOT_A_NAME_SUFFIX = (".php", ".html", ".htm", ".aspx", ".jsp", ".cgi")


def _handle_from_path(path: str) -> Optional[str]:
    """The identity segment of a profile URL, or ``None``.

    Reads the *first* segment that is not a platform routing word, so
    ``/company/acme-supplies/about`` yields ``acme-supplies`` rather than
    ``about``. An earlier version anchored on the end of the path and read
    whatever was last, which produced handles like "posts", "videos" and
    "1234567890" - none of which is a name anybody claims.
    """
    for segment in (path or "").split("/"):
        if not segment or segment.lower() in _PROFILE_SECTIONS:
            continue
        if segment.isdigit() or segment.lower().endswith(_NOT_A_NAME_SUFFIX):
            continue
        if _HANDLE_SEGMENT_RE.match(segment):
            return segment
    return None


#: A profile handle sitting at the end of a social or knowledge-base URL.
#: Generic by construction: it reads whatever the last meaningful path segment
#: is, on any host, rather than knowing anything about particular platforms.
def profile_handles(bundle: dict) -> List[Tuple[str, str]]:
    """Names the site claims for itself on other platforms, as ``(handle, url)``.

    A handle is an identity the site asserts, but it lives under a platform's
    naming rules, not the brand's: it cannot contain spaces, is often
    lowercased, and is frequently suffixed to avoid a collision with someone
    else. Treating one as a rival spelling of the trading name would report
    every site with a social presence as inconsistent, so these are collected
    under their own role and never compared against the brand.
    """
    out: List[Tuple[str, str]] = []
    seen = set()
    for page in ev.pages(bundle):
        for url in ((page.get("links", {}) or {}).get("sameas_like") or [])[:40]:
            handle = _handle_from_path(urlsplit(url).path or "")
            if not handle:
                continue
            key = util.normalize_name(handle)
            if not key or len(key) < 2 or key in seen:
                continue
            seen.add(key)
            out.append((handle, url))
    return out[:12]


def primary_sighting(entry: dict) -> Tuple[str, str]:
    """The (where, raw) to show for a name, taken from its winning role."""
    sightings = entry.get("sightings") or {}
    for role in sorted(sightings, key=lambda r: _ROLE_RANK.get(r, 99)):
        if sightings[role]:
            return sightings[role][0]
    return ("", "")


def brand_name_candidates(bundle: dict) -> Dict[str, dict]:
    """Names the site states for itself, each tagged with the *role* it was seen in.

    A site is entitled to more than one name. The consumer-facing trading
    name, the registered legal entity behind it, and the rights holder in the
    footer are three different things, and a well-run business routinely has a
    different string for each. Pooling them and reporting the spread as an
    inconsistency turns correct practice into a high-severity finding - and
    the fix the rule recommends ("put the legal entity name in legalName") is
    exactly what such a site already did.

    So each sighting carries one of four roles:

    ``brand``
        the consumer-facing trading name (Organization/Brand ``name``,
        ``og:site_name``, the ``<title>`` suffix, ``Product.brand.name``).
    ``legal``
        the registered entity (``legalName``, and any string carrying a
        corporate-form suffix wherever it appears).
    ``copyright``
        the rights holder named in a footer copyright line.
    ``social``
        a handle the site claims on another platform, which lives under that
        platform's naming rules rather than the brand's.

    Only ``brand``-role names are compared against each other. The other three
    are recorded as evidence of what the site declares, and never conflict
    with the trading name.
    """
    seen: Dict[str, dict] = {}
    home = ev.home_page(bundle)


    def record(raw: Optional[str], where: str, role: str = "brand") -> None:
        if not raw:
            return
        raw = util.collapse_ws(str(raw))
        if not raw or len(raw) > 80:
            return
        key = util.normalize_name(raw)
        if not key or len(key) < 2:
            return
        # Role comes from the declaration site, not from the shape of the
        # string. `legalName` is a legal name because schema.org says so; a
        # footer copyright is a rights holder because that is what a copyright
        # line states. Nothing is demoted out of `brand` on a guess.
        entry = seen.setdefault(key, {"role": role, "sightings": {}})
        entry["sightings"].setdefault(role, []).append((where, raw))
        # One string can legitimately appear in several roles. The strongest
        # one wins, so a name that is also a handle is still a trading name -
        # and the sighting shown is the one from the winning role.
        if _ROLE_RANK[role] < _ROLE_RANK[entry["role"]]:
            entry["role"] = role

    for node in organization_nodes(bundle):
        record(text_of(prop(node, "name")), "schema.org Organization/Brand name")
        record(text_of(prop(node, "legalName")), "schema.org legalName", role="legal")
    if home:
        record((home.get("open_graph", {}) or {}).get("og:site_name"), "og:site_name")
        record(_title_brand(home), "home page <title> suffix")
        for holder in _copyright_holders(home.get("text", "")):
            record(holder, "footer copyright line", role="copyright")
    for handle, url in profile_handles(bundle):
        record(handle, f"profile handle at {url}", role="social")
    index = entity_index(bundle)
    for page in ev.product_pages(bundle):
        for node in products_on(page):
            record(entity_name(prop(node, "brand"), index), "Product.brand")
    return seen


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def rule_org_incomplete(bundle: dict) -> Optional[Finding]:
    """The Organization node, measured against what a site of this shape needs.

    A postal address is required of a site with a physical presence, a
    government body, a school or a shop shipping goods, and optional for a
    documentation site or a publisher. A founding date and a logo are
    optional everywhere. The finding lists what is missing *by expectation*,
    and a node missing only optional properties is not reported at all.
    """
    nodes = organization_nodes(bundle)
    if not nodes:
        return None  # absence is reported by machine-readability-audit
    merged: Dict[str, object] = {}
    for node in nodes:
        for key in ("name", "legalName", "description", "logo", "url", "address",
                    "sameAs", "foundingDate", "contactPoint", "telephone", "email",
                    "identifier", "vatID", "taxID", "brand", "@id"):
            if key not in merged:
                value = prop(node, key)
                if value not in (None, "", []):
                    merged[key] = value
    context = dict(semantic_context(bundle))
    anchors = bundle.get("declared_anchors") or []
    context["official_profiles_linked"] = any(a.get("link_kind") == "official_profile"
                                              for a in anchors)
    if "contactPoint" not in merged and ("telephone" in merged or "email" in merged):
        merged["contactPoint"] = merged.get("telephone") or merged.get("email")
    expectations = {}
    for key in ("description", "address", "contactPoint", "sameAs", "@id", "logo",
                "foundingDate"):
        expectations[key] = semantics.organization_field_expectation(key, context)
    required = [k for k, e in expectations.items()
                if e == "required_when_applicable" and k not in merged]
    recommended = [k for k, e in expectations.items() if e == "recommended" and k not in merged]
    optional = [k for k, e in expectations.items() if e == "optional" and k not in merged]
    if not required and not recommended:
        return None
    severity = "medium" if required else "low"
    site_kind = context.get("site_kind") or "unknown"

    def _why(key: str) -> str:
        # Name the observation that made the property expected, not the
        # list of observations that could have.
        if key == "address":
            if context.get("physical_presence"):
                return "the site declares a physical presence"
            if context.get("sells_physical_goods"):
                return "the site sells physical goods"
            return f"a {site_kind} site is expected to state where it is"
        if key == "contactPoint":
            if context.get("sells_online"):
                return "the site sells online"
            if context.get("transactions"):
                return "the site takes transactions"
            return f"a {site_kind} site is expected to state how to reach it"
        if key == "sameAs":
            return "official profiles are linked from the site"
        if key == "@id":
            return "product pages need a node to reference"
        return "it describes any organisation"

    described = ", ".join(f"{k} ({_why(k)})" for k in required + recommended)
    return finding(
        "EN-ORG-INCOMPLETE",
        "The Organization entity is declared but omits properties a site of this shape "
        "is expected to carry",
        severity, PILLAR,
        evidence=f"The site's Organization/Brand node declares "
                 f"{', '.join(sorted(k for k in merged if k != '@id')) or 'almost nothing'} but "
                 f"omits {described}."
                 + (f" Also absent, but optional for any site and not counted: "
                    f"{', '.join(optional)}." if optional else "")
                 + f" Expectations follow the site's shape ({site_kind}).",
        interpretation="Each of these properties is an explicit, machine-readable statement "
                       "that tells this organisation apart from others with a similar name. "
                       "Which ones a site owes depends on what kind of organisation it is; "
                       "this audit does not measure how any system resolves the entity.",
        items=[absent(f"Organization node has no `{key}` property "
                      f"({expectations[key].replace('_', ' ')})",
                      url=label(ev.home_page(bundle) or {}), locator="JSON-LD Organization")
               for key in required + recommended],
        action=action("Fill out the Organization entity with the properties that apply to it.",
                      priority=severity, effort="low", impact="medium",
                      mechanism="Entity resolution works by matching attributes. A node with "
                                "only a name matches every company sharing that name; a node "
                                "with a description, contact details and, where it has one, an "
                                "address provides explicit machine-readable evidence to match "
                                "on.",
                      steps=["Add description (one factual sentence, no marketing)."]
                            + (["Add a PostalAddress for the organisation's location."]
                               if "address" in required else [])
                            + (["Add a ContactPoint (or telephone/email)."]
                               if "contactPoint" in required + recommended else [])
                            + (["Add sameAs for every official profile the site links to."]
                               if "sameAs" in required + recommended else [])
                            + ["Add legalName when it differs from the trading name.",
                               "Give the node a stable @id such as https://example.com/#organization "
                               "and reference it from every page that names the organisation."],
                      example=examples.organization_jsonld(site_vocabulary(bundle)),
                      verification="Structured-data test shows an Organization carrying the "
                                   "properties listed as expected."),
        urls=[label(ev.home_page(bundle) or {})], confidence=0.9,
        metrics={"scope": "site", "missing_required": required,
                 "missing_recommended": recommended, "missing_optional": optional,
                 "site_kind": site_kind}, tags=["entity"])


#: Relationships under which a name is *not* a rival spelling of the site's
#: own trading name: a department, a subsidiary, a public body, a product's
#: brand, a partner, a localized rendering, a knowledge link, a mention.
_NOT_A_RIVAL_NAME = frozenset({
    "department", "subsidiary", "agency", "tribunal", "brand", "product", "partner",
    "customer", "acquired_company", "localization", "language_variant", "knowledge",
    "navigation", "official_profile", "unrelated",
})


def _related_names(bundle: dict) -> Dict[str, Tuple[str, str]]:
    """normalised name -> (relationship, why) for every entity the crawl names."""
    out: Dict[str, Tuple[str, str]] = {}
    for record in semantics.entity_relationships(bundle):
        key = util.normalize_name(record["name"])
        if not key:
            continue
        # First sighting wins, except that a stated relationship replaces
        # "unknown" and the site's own identity replaces anything.
        if key not in out or record["relationship"] == "primary_entity" \
                or out[key][0] == "unknown":
            out[key] = (record["relationship"], record["why"])
    return out


def rule_name_inconsistency(bundle: dict) -> Optional[Finding]:
    candidates = brand_name_candidates(bundle)
    # Only trading names compete with each other. A legal entity name and a
    # copyright holder are different facts about the same business, not rival
    # spellings of one name.
    brands = {key: entry for key, entry in candidates.items()
              if entry["role"] == "brand"}
    # And only names that are *the site's own*. The entity-relationship
    # classifier says which names belong to a department, a subsidiary, a
    # product's brand, a partner, or are the same name rendered in another
    # language or script - none of which is the site calling itself two
    # things, and every one of which was once reported as exactly that.
    related = _related_names(bundle)
    excluded: List[Tuple[str, str, str]] = []
    for key in list(brands):
        relationship, why = related.get(key, ("unknown", ""))
        if relationship in _NOT_A_RIVAL_NAME:
            excluded.append((primary_sighting(brands[key])[1], relationship, why))
            del brands[key]
    if len(brands) < 2:
        return None
    # Fold names that are prefixes/substrings of each other: "acme" and
    # "acme supplies" are the same entity described at different lengths, which
    # is normal. Case and punctuation are already folded by normalize_name, so
    # a name and the same name in different capitalisation arrive here as one
    # key. Only genuinely different strings are reported.
    keys = sorted(brands, key=len)
    distinct: List[str] = []
    for key in keys:
        if not any(key in other or other in key for other in distinct):
            distinct.append(key)
    if len(distinct) < 2:
        return None
    items = []
    for key in distinct[:5]:
        where, raw = primary_sighting(brands[key])
        items.append(observed(f'brand name "{raw}" declared in {where}',
                              url=label(ev.home_page(bundle) or {}), locator=where))
    # Everything the site declares under another role is context, not conflict.
    other_roles = [(entry["role"], primary_sighting(entry)[1])
                   for entry in candidates.values() if entry["role"] != "brand"]
    aside = ""
    if other_roles:
        shown = "; ".join(f'"{name}" ({role})' for role, name in other_roles[:3])
        aside = (f" ({len(other_roles)} further name(s) are declared in a non-trading role "
                 f"and are not counted as conflicting: {shown}.)")
    if excluded:
        shown = "; ".join(f'"{name}" ({relationship.replace("_", " ")})'
                          for name, relationship, _ in excluded[:3])
        aside += (f" ({len(excluded)} further name(s) belong to a related entity or are a "
                  f"localized rendering, and are not counted as conflicting: {shown}.)")
    return finding(
        "EN-NAME-INCONSISTENT",
        "The brand is called different things in different places on its own site",
        "high", PILLAR,
        evidence=f"{len(distinct)} materially different trading names are declared across the "
                 f"site's own metadata: " +
                 "; ".join(f'"{primary_sighting(brands[k])[1]}" '
                           f'({primary_sighting(brands[k])[0]})'
                           for k in distinct[:4]) + "." + aside,
        interpretation="Every distinct spelling of a name is a candidate for a separate "
                       "entity. Where the site itself uses several for the same organisation, "
                       "nothing in its markup states that they are one, so a reader has to "
                       "infer it. Names that belong to a department, a subsidiary, a product "
                       "brand or a localized version of the site are classified as such and "
                       "are not counted here.",
        items=items,
        action=action("Pick one canonical brand string and use it byte-identically everywhere.",
                      priority="high", effort="low", impact="high",
                      mechanism="One exact string in Organization.name, og:site_name, the title "
                                "suffix and Product.brand is an explicit statement that every "
                                "mention is the same entity; several strings leave that to "
                                "be inferred.",
                      steps=["Choose the exact trading name, including capitalisation and any "
                             "suffix.",
                             "Use it in Organization.name, og:site_name, the <title> suffix, the "
                             "footer copyright and Product.brand.name.",
                             "Put the legal entity name in legalName, not in name.",
                             "Roll the same string out to every off-site profile."],
                      verification="Grep the rendered home page for the brand string; every "
                                   "occurrence should be identical."),
        urls=[label(ev.home_page(bundle) or {})], confidence=0.8,
        metrics={"scope": "site", "distinct_names": len(distinct),
                 "excluded_related_names": [
                     {"name": name, "relationship": relationship}
                     for name, relationship, _ in excluded[:8]]},
        tags=["entity", "naming"])


def rule_product_brand_missing(bundle: dict) -> Optional[Finding]:
    products = [p for p in ev.product_pages(bundle) if products_on(p)]
    if not sample_guard(products, 1):
        return None
    without = []
    for page in products:
        if not any(prop(node, "brand") for node in products_on(page)):
            without.append(page)
    if not without:
        return None
    ratio = len(without) / len(products)
    return finding(
        "EN-PRODUCT-BRAND-MISSING",
        "Products are not connected to the brand entity",
        severity_from_sample(ratio, len(products), critical=1.01, high=0.6, medium=0.25), PILLAR,
        evidence=f"{len(without)} of {len(products)} product page(s) declare a Product node with "
                 "no `brand` property, so nothing in the markup states that these products "
                 "belong to this company.",
        items=page_items(without, "Product node on {url} has no brand property", limit=5),
        action=action("Reference the Organization/Brand entity from every Product.",
                      priority="high", effort="low", impact="high",
                      mechanism="Product.brand is the explicit, machine-readable statement "
                                "that a product belongs to this organisation. Without it, "
                                "nothing in the markup connects the product pages to the "
                                "entity, and the relationship has to be inferred from the "
                                "domain.",
                      steps=['Add "brand": {"@type": "Brand", "name": "<exact brand name>"} to '
                             "every Product.",
                             "Better: give the Organization an @id and use "
                             '"brand": {"@id": "https://example.com/#organization"} so both '
                             "resolve to one node.",
                             "Use the identical brand string used in Organization.name."],
                      verification="Every Product node in a crawl of your sitemap has a brand."),
        urls=[label(p) for p in without],
        confidence=confidence_for(len(without), len(products)),
        metrics={"scope": scope_for(len(without), len(products)),
                 "affected": len(without), "sampled": len(products),
                 "sample_unit": "sampled product page(s)"},
        tags=["entity", "relationships"])


def rule_product_brand_mismatch(bundle: dict) -> Optional[Finding]:
    products = [p for p in ev.product_pages(bundle) if products_on(p)]
    orgs = organization_nodes(bundle)
    if not products or not orgs:
        return None
    site_names = {util.normalize_name(text_of(prop(node, "name")) or "") for node in orgs}
    site_names |= {util.normalize_name(text_of(prop(node, "legalName")) or "") for node in orgs}
    site_names.discard("")
    if not site_names:
        return None
    index = entity_index(bundle)
    mismatched: List[Tuple[dict, str]] = []
    for page in products:
        for node in products_on(page):
            # An unresolvable reference is missing evidence, not a mismatch.
            raw = entity_name(prop(node, "brand"), index)
            if not raw:
                continue
            key = util.normalize_name(raw)
            if not key:
                continue
            if any(key in name or name in key for name in site_names):
                continue
            mismatched.append((page, raw))
    if not mismatched:
        return None
    # A genuine multi-brand retailer or marketplace legitimately sells other
    # brands, and a page that names a manufacturer or a third-party seller
    # has said so. Only report when a *single* foreign brand dominates and
    # nothing declares the relationship, which is what naming drift looks like.
    counts = Counter(util.normalize_name(name) for _, name in mismatched)
    if len(counts) > 3:
        return None
    declared_relationship = [
        page for page, _ in mismatched
        if any(prop(node, "manufacturer") or any(prop(o, "seller", "offeredBy")
                                                   for o in offers_of(node))
               for node in products_on(page))]
    if len(declared_relationship) == len(mismatched):
        return None
    return finding(
        "EN-PRODUCT-BRAND-DRIFT",
        "Product brand names do not match the site's own declared brand",
        "low", PILLAR,
        evidence=f"{len(mismatched)} product node(s) declare a brand "
                 f"({', '.join(sorted({n for _, n in mismatched})[:3])}) that does not match the "
                 f"site's Organization name ({', '.join(sorted(site_names))}), and no "
                 "manufacturer or seller relationship is declared to explain the difference. "
                 "Either the products are another entity's brand sold here, or the site's "
                 "own name has drifted; the markup does not say which.",
        items=[observed(f'Product.brand = "{raw}" while the site Organization is named '
                        f'"{sorted(site_names)[0]}"', url=label(page), locator="JSON-LD Product")
               for page, raw in mismatched[:5]],
        action=action("State the relationship explicitly: align the strings if it is the same "
                      "entity, or declare manufacturer/seller if it is not.",
                      priority="low", effort="low", impact="low",
                      mechanism="Product.brand and Organization.name that differ, with no "
                                "declared manufacturer or seller, leave the relationship "
                                "between the products and the site to be inferred; declaring "
                                "it either way makes it explicit.",
                      steps=["If it is the same company, use one exact string everywhere.",
                             "If you genuinely retail other brands, keep Product.brand as the "
                             "manufacturer and add seller/Organization for yourself.",
                             "Give each brand its own @id so both entities resolve cleanly."],
                      verification="Every Product.brand value matches either your Organization "
                                   "name or a deliberately-modelled partner brand."),
        urls=[label(p) for p, _ in mismatched], confidence=0.7,
        metrics={"scope": "template", "affected": len(mismatched),
                 "with_declared_relationship": len(declared_relationship)},
        tags=["entity", "naming"])


def rule_missing_entity_ids(bundle: dict) -> Optional[Finding]:
    pages = [p for p in ev.pages(bundle) if p.get("jsonld_blocks")]
    if not sample_guard(pages, 2):
        return None
    # An @id is worth having where nodes on different pages name the same
    # entity - an Organization referenced from product pages, an author on
    # every article. A site whose markup is one node per page has nothing to
    # reference, and is not asked for one.
    context = semantic_context(bundle)
    if semantics.organization_field_expectation("@id", context) == "optional" \
            and len(organization_nodes(bundle)) < 2:
        return None
    with_ids = 0
    total_nodes = 0
    for page in pages:
        for node in jsonld_nodes(page):
            if not node_types(node):
                continue
            total_nodes += 1
            if prop(node, "@id"):
                with_ids += 1
    if total_nodes == 0 or with_ids > 0:
        return None
    return finding(
        "EN-NO-ENTITY-IDS",
        "No structured-data node declares a stable @id",
        "low", PILLAR,
        evidence=f"None of the {total_nodes} typed JSON-LD node(s) across {len(pages)} sampled "
                 "page(s) declares an @id, so no node in the markup references any other node.",
        interpretation="Without shared identifiers each page declares an anonymous entity of its "
                       "own. Nothing in the data states that the organisation on the home page "
                       "and the brand on a product page are the same thing, so evidence about "
                       "the brand does not accumulate on one node.",
        items=[absent("no @id on any typed JSON-LD node", url=label(page), locator="JSON-LD")
               for page in pages[:4]],
        action=action("Give every reusable entity a stable @id and reference it by @id elsewhere.",
                      priority="low", effort="low", impact="medium",
                      mechanism="@id is the explicit statement that two nodes on two pages are "
                                "one entity. Without it, each page re-declares an anonymous "
                                "'some organisation named X' and the identity has to be "
                                "inferred from the name.",
                      steps=["Use fragment URIs on the canonical domain: "
                             "https://example.com/#organization, "
                             "https://example.com/products/x#product.",
                             "Declare the full node once (home page) and reference "
                             '{"@id": "..."} from everywhere else.',
                             "Keep @id values stable across redesigns - they are identifiers, "
                             "not URLs to render."],
                      verification="Product pages reference the organisation by @id rather than "
                                   "repeating its name."),
        urls=[label(p) for p in pages[:6]], confidence=0.85,
        metrics={"scope": "site", "typed_nodes": total_nodes},
        tags=["entity", "graph"])


def rule_duplicate_product_names(bundle: dict) -> Optional[Finding]:
    products = ev.product_pages(bundle)
    if not sample_guard(products, 3):
        return None
    names: Dict[str, List[dict]] = defaultdict(list)
    context = identity_context(bundle)
    for page in products:
        # The declared name first; otherwise the identity the page corroborates
        # (see `analysis.item_identity`). A bare heading is not used: two pages
        # whose only heading is the same template label ("Product details") are
        # not two products with one name, and were reported as exactly that.
        candidates = [text_of(prop(node, "name")) for node in products_on(page)]
        candidates = [c for c in candidates if c]
        if not candidates:
            identity = item_identity(page, bundle, context)
            candidates = [identity["name"]] if identity else []
        if not candidates:
            continue
        names[util.normalize_name(candidates[0])].append(page)
    duplicates = {name: group for name, group in names.items() if name and len(group) > 1}
    if not duplicates:
        return None
    return finding(
        "EN-DUPLICATE-PRODUCT-NAMES",
        "Several distinct URLs present themselves as the same product",
        "medium", PILLAR,
        evidence=f"{len(duplicates)} product name(s) are used by more than one URL "
                 f"(e.g. \"{list(duplicates)[0]}\" appears on "
                 f"{len(list(duplicates.values())[0])} pages). A consumer cannot tell whether "
                 "these are variants, duplicates or different products.",
        items=[observed(f'product name "{name}" also used by {len(group)} URL(s)',
                        url=label(group[0]),
                        locator="; ".join(label(p) for p in group[1:3]))
               for name, group in list(duplicates.items())[:4]],
        action=action("Disambiguate variants explicitly instead of duplicating the product name.",
                      priority="medium", effort="medium", impact="medium",
                      mechanism="Identically-named pages state nothing that tells them apart, "
                                "so a question about one particular variant has no name to be "
                                "matched to the URL that describes it. A distinct name, or a "
                                "ProductGroup with named variants, makes the difference "
                                "explicit.",
                      steps=["Model variants as a ProductGroup with hasVariant rather than as "
                             "separate identically-named products.",
                             "If separate URLs are required, make each name unique by appending "
                             "the attribute that varies (e.g. '"
                             + named(site_vocabulary(bundle), "product")
                             + " - " + example_attributes(site_vocabulary(bundle), 1)[0]
                             + " <value>') and set canonical to the group page.",
                             "Give each variant its own sku and its own Offer."],
                      verification="No two indexable product URLs share an identical Product.name."),
        urls=[label(page) for group in duplicates.values() for page in group],
        confidence=0.8,
        metrics={"scope": "section", "duplicate_names": len(duplicates)},
        tags=["entity", "variants"])


def rule_duplicate_titles(bundle: dict) -> Optional[Finding]:
    pages = [p for p in ev.pages(bundle) if (p.get("title") or "").strip()]
    if not sample_guard(pages, 4):
        return None
    counts = Counter(util.collapse_ws(p["title"]).lower() for p in pages)
    duplicates = {title: count for title, count in counts.items() if count > 1}
    if not duplicates:
        return None
    affected = sum(duplicates.values())
    if affected / len(pages) < 0.3:
        return None
    return finding(
        "EN-DUPLICATE-TITLES",
        "Different pages share the same title",
        "medium", PILLAR,
        evidence=f"{affected} of {len(pages)} sampled page(s) share only {len(duplicates)} "
                 f"distinct title(s) (most common: \"{max(duplicates, key=duplicates.get)}\" on "
                 f"{max(duplicates.values())} pages).",
        items=[observed(f'title "{title}" is used by {count} different URLs',
                        url=label(pages[0]), locator="<title>")
               for title, count in list(duplicates.items())[:4]],
        action=action("Give every page a title that names its own subject.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="The title is the page's own short label. When many URLs "
                                "share one, nothing in the title tells them apart, so the "
                                "pages cannot be told apart by name without reading each.",
                      steps=["Template each page's title from what that page is about plus a "
                             "differentiator.",
                             "Template section titles from the section name.",
                             "Never ship the site name alone as a title."],
                      verification="Every URL in the sitemap has a unique <title>."),
        urls=[label(p) for p in pages[:10]], confidence=0.9,
        metrics={"scope": "template", "duplicate_groups": len(duplicates)},
        tags=["entity", "metadata"])


def rule_category_undeclared(bundle: dict) -> Optional[Finding]:
    products = [p for p in ev.product_pages(bundle) if products_on(p)]
    if not sample_guard(products, 2):
        return None
    undeclared = []
    for page in products:
        has_category = any(text_of(prop(node, "category")) for node in products_on(page))
        has_breadcrumb = bool(find_nodes(jsonld_nodes(page), "BreadcrumbList"))
        if not has_category and not has_breadcrumb:
            undeclared.append(page)
    if not undeclared or len(undeclared) / len(products) < 0.5:
        return None
    ratio = len(undeclared) / len(products)
    return finding(
        "EN-CATEGORY-UNDECLARED",
        "Product pages expose no machine-readable category relationship",
        # `category` and BreadcrumbList are optional metadata: their absence
        # is never more than a medium finding on its own.
        semantics.cap_optional(
            severity_from_sample(ratio, len(products), critical=1.01, high=0.85, medium=0.5)),
        PILLAR,
        evidence=f"{len(undeclared)} of {len(products)} product page(s) expose no "
                 "machine-readable category relationship through `Product.category` or "
                 "`BreadcrumbList` in the sampled markup.",
        interpretation="Category membership is one of the relationships an answer about a "
                       "group of products can be assembled from. Where it is not stated "
                       "in the markup it has to be inferred from the URL, the navigation or the "
                       "copy, which is slower and less reliable than reading a declared value. "
                       "This can make category membership harder for automated systems to "
                       "resolve; it does not establish that any particular system failed to.",
        items=page_items(undeclared,
                         "no `category` property and no BreadcrumbList markup on {url}",
                         limit=5),
        action=action("Declare a consistent category for every product.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="A declared category states the product's membership directly, "
                                "so a system assembling an answer about that category does not "
                                "have to infer the relationship from the URL or the surrounding "
                                "copy.",
                      steps=["Add category to Product using this site's own taxonomy path "
                             "(the path shown in its breadcrumbs, e.g. '"
                             + named(site_vocabulary(bundle), "category") + "').",
                             "Add BreadcrumbList markup mirroring the same path.",
                             "Use the same category strings on the category page's own markup.",
                             "Keep the taxonomy shallow and stable - renaming categories resets "
                             "the association."],
                      verification="Every Product node has a category value that matches a real "
                                   "category page."),
        urls=[label(p) for p in undeclared],
        confidence=confidence_for(len(undeclared), len(products)),
        metrics={"scope": scope_for(len(undeclared), len(products)),
                 "affected": len(undeclared), "sampled": len(products),
                 "sample_unit": "sampled product page(s)"},
        tags=["entity", "taxonomy"])


def rule_self_description(bundle: dict) -> Optional[Finding]:
    home = ev.home_page(bundle)
    if not home or home.get("fetch_failed"):
        return None
    description = (home.get("meta_description") or "").strip()
    org_description = ""
    for node in organization_nodes(bundle):
        org_description = text_of(prop(node, "description")) or org_description
    og_description = (home.get("open_graph", {}) or {}).get("og:description", "")
    if description or org_description or og_description:
        return None
    return finding(
        "EN-NO-SELF-DESCRIPTION",
        "The site never states in one place what it is",
        "medium", PILLAR,
        evidence=f"The home page ({label(home)}) has no meta description, no og:description and "
                 "no Organization.description. There is no single sentence a machine can quote "
                 "to say what this organisation is or does.",
        items=[absent("no meta description on the home page", url=label(home)),
               absent("no og:description on the home page", url=label(home)),
               absent("no Organization.description in the structured data", url=label(home),
                      locator="JSON-LD")],
        action=action("Write one factual sentence describing the business and publish it in all "
                      "three places.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="A one-sentence description is an explicit statement of what "
                                "the organisation is. 'An organisation called X' matches many "
                                "entities; 'X, a <what it does> in <where>, founded <when>' "
                                "matches one - and it is the sentence a reader of the markup "
                                "can quote when introducing you.",
                      steps=["Write 15-25 words: what you do, for whom, where.",
                             "Put it in Organization.description, meta description and "
                             "og:description, identically.",
                             "Repeat the same sentence on your off-site profiles so the "
                             "description corroborates."],
                      verification="Ask an assistant what this organization is and check the "
                                   "answer matches the sentence you published.",
                      verification_type="external_validation"),
        urls=[label(home)], confidence=0.9,
        metrics={"scope": "site"}, tags=["entity", "disambiguation"])


def rule_sameas_undeclared(bundle: dict) -> Optional[Finding]:
    anchors = bundle.get("declared_anchors", [])
    if not anchors:
        return None  # freshness-corroboration reports the total absence
    nodes = organization_nodes(bundle)
    if not nodes:
        return None
    declared_sameas = any(prop(node, "sameAs") for node in nodes)
    if declared_sameas:
        return None
    # Only an *account* the site links to - a profile on a social or listing
    # platform, or anything marked rel=me - is a claim of identity the site
    # could declare as sameAs. A documentation host, an app-store listing, a
    # knowledge-base article about some subject and a platform video are
    # links, not profiles, and are set aside here and named.
    candidates = [a for a in anchors
                  if "outbound profile/knowledge link" in a.get("sources", [])
                  or "rel=me link" in a.get("sources", [])]
    profile_links = [a for a in candidates
                     if a.get("link_kind") in (None, "official_profile")
                     or "rel=me link" in a.get("sources", [])]
    other_links = [a for a in candidates if a not in profile_links]
    if not profile_links:
        return None
    kinds = Counter(str(a.get("link_kind")).replace("_", " ") for a in other_links)
    aside = ""
    if other_links:
        aside = (f" {len(other_links)} further outbound link(s) to other platforms are not "
                 f"profiles and are not counted: "
                 + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) + ".")
    return finding(
        "EN-SAMEAS-UNDECLARED",
        "Official profiles are linked in the page but not declared as sameAs",
        "medium", PILLAR,
        evidence=f"{len(profile_links)} outbound link(s) to an account on another platform were "
                 f"found (e.g. {profile_links[0]['url']}) but the Organization node declares no "
                 "sameAs, so the identity link is left for a consumer to infer from a footer "
                 "icon. This audit did not verify that those accounts belong to the "
                 "organisation." + aside,
        items=[observed(f"profile link present in page markup: {a['url']}",
                        url=a.get("declared_on", [""])[0] if a.get("declared_on") else "",
                        locator=", ".join(a.get("sources", []))) for a in profile_links[:5]],
        action=action("List every official profile in Organization.sameAs.",
                      priority="medium", effort="low", impact="medium",
                      mechanism="A footer icon is a link; sameAs is an explicit, "
                                "machine-readable assertion that the account is this "
                                "organisation, which is what lets facts stated there be "
                                "matched to facts stated here.",
                      steps=['Add "sameAs": ["<profile 1>", "<profile 2>", ...] to the '
                             "Organization node.",
                             "Include only accounts you actually control.",
                             "Make sure each profile links back to the canonical domain."],
                      verification="Structured-data test shows sameAs containing every official "
                                   "profile."),
        urls=[a["url"] for a in profile_links], confidence=0.85,
        metrics={"scope": "site", "profiles": len(profile_links),
                 "other_platform_links_not_counted": len(other_links)},
        tags=["entity", "corroboration"])


def rule_variants_unmodelled(bundle: dict) -> Optional[Finding]:
    products = ev.product_pages(bundle)
    if not sample_guard(products, 1):
        return None
    unmodelled = []
    for page in products:
        variants = page.get("variants", {}) or {}
        has_ui = (variants.get("variant_selects", 0) or 0) + (variants.get("variant_swatches", 0) or 0)
        if not has_ui:
            continue
        nodes = products_on(page)
        has_group = any("productgroup" in {t.lower() for t in node_types(n)} for n in nodes)
        has_variant_offers = any(prop(n, "hasVariant") for n in nodes)
        multi_offers = sum(len(offers_of(n)) for n in nodes) > 1
        if not (has_group or has_variant_offers or multi_offers):
            unmodelled.append(page)
    if not unmodelled:
        return None
    return finding(
        "EN-VARIANTS-UNMODELLED",
        "Size and colour variants exist in the UI but not as addressable entities",
        "medium", PILLAR,
        evidence=f"{len(unmodelled)} of {len(products)} product page(s) render variant pickers "
                 "(size/colour selects or swatches) while their structured data declares a "
                 "single Product with a single Offer. Per-variant availability and price are "
                 "therefore unanswerable.",
        items=[observed(f"{(p.get('variants') or {}).get('variant_selects', 0)} variant select(s) "
                        f"and {(p.get('variants') or {}).get('variant_swatches', 0)} swatch(es) "
                        "in the HTML, but no ProductGroup/hasVariant in the markup",
                        url=label(p), locator="page HTML vs JSON-LD") for p in unmodelled[:5]],
        action=action("Model variants as ProductGroup + hasVariant with per-variant offers.",
                      priority="medium", effort="medium", impact="high",
                      mechanism="A question about one specific variant can only be answered if "
                                "that variant is a thing with its own availability. A single "
                                "Product node covering the whole range leaves every "
                                "variant-level question unanswerable from the markup.",
                      steps=["Emit ProductGroup with productGroupID and variesBy.",
                             "Emit one Product per variant under hasVariant, each with its own "
                             "sku, the properties that vary, and its own Offer including "
                             "availability.",
                             "Give each variant a crawlable, server-rendered URL.",
                             "Keep the variant list in the server HTML, not fetched on selection."],
                      example=examples.variant_group_jsonld(site_vocabulary(bundle)),
                      verification="curl a product URL and confirm each size appears with its "
                                   "own availability value."),
        urls=[label(p) for p in unmodelled],
        confidence=confidence_for(len(unmodelled), len(products), base=0.85),
        metrics={"scope": scope_for(len(unmodelled), len(products)),
                 "affected": len(unmodelled), "sampled": len(products),
                 "sample_unit": "sampled product page(s)"},
        tags=["entity", "variants"])


def rule_contact_grounding(bundle: dict) -> Optional[Finding]:
    nodes = organization_nodes(bundle)
    if not nodes:
        return None
    grounded = any(prop(node, "address") or prop(node, "contactPoint") or
                   prop(node, "telephone") or prop(node, "email") for node in nodes)
    if grounded:
        return None
    # Contact grounding is expected of a site that transacts, offers services,
    # is a public body or has a physical presence. A documentation site or a
    # publisher is not asked for it, and the expectation is stated.
    context = semantic_context(bundle)
    if semantics.organization_field_expectation("contactPoint", context) == "optional" \
            and semantics.organization_field_expectation("address", context) == "optional":
        return None
    pages = ev.pages(bundle)
    has_contact_page = any(p.get("page_type") == "contact" for p in pages)
    return finding(
        "EN-NO-CONTACT-GROUNDING",
        "The organisation declares no address or contact point",
        "low", PILLAR,
        evidence="The Organization node declares no address, contactPoint, telephone or email"
                 + (", though a contact page exists on the site." if has_contact_page
                    else ", and no contact page was found in the crawl.")
                 + f" Contact grounding is expected of a {context.get('site_kind')} site"
                 + (" with a physical presence." if context.get("physical_presence") else "."),
        items=[absent("no address/contactPoint/telephone/email on the Organization node",
                      url=label(ev.home_page(bundle) or {}), locator="JSON-LD Organization")],
        action=action("Add a postal address and a contact point to the Organization entity.",
                      priority="low", effort="low", impact="medium",
                      mechanism="An address and a contact point are explicit, machine-readable "
                                "attributes that tell this organisation apart from others with "
                                "a similar name, and that a registry entry can be matched on.",
                      steps=["Add a PostalAddress with locality, region and country.",
                             "Add a ContactPoint with contactType 'customer service'.",
                             "For physical locations, publish LocalBusiness/Store markup per "
                             "location so each is a typed entity."],
                      verification="Structured-data test shows an address on the Organization."),
        urls=[label(ev.home_page(bundle) or {})], confidence=0.85,
        metrics={"scope": "site"}, tags=["entity", "disambiguation"])


#: Words in a page's *own* URL, title or heading that say it is about places
#: to visit. On their own they establish nothing - a conference has a venue, a
#: jobs page lists the cities it hires in, a user-group directory maps chapters,
#: and all of them are "locations" - so this vocabulary only says which pages
#: to look at; what the page then carries decides.
_LOCATION_PATH_RE = re.compile(
    r"/(stores?|store-locator|store-finder|locations?|branch(es)?|showrooms?|"
    r"find-?a-?(store|dealer|stockist)|stockists?|dealers?|where-to-buy|"
    r"filialen|tiendas|magasins|negozi|lojas)(/|\.|$)", re.I)
_LOCATION_TEXT_HINTS = (
    "store locator", "find a store", "find a dealer", "our stores", "store finder",
    "where to buy", "stockists", "showroom", "our locations", "visit us",
    "branches", "outlets", "tiendas", "nuestras tiendas", "magasins", "filialen",
    "punti vendita", "lojas",
)

#: schema.org types that model a place a customer can go to.
_PLACE_TYPES = ("LocalBusiness", "Store", "ClothingStore", "ShoeStore",
                "SportingGoodsStore", "HardwareStore", "GroceryStore",
                "DepartmentStore", "AutomotiveBusiness", "Restaurant",
                "Place", "Organization+address")


#: The place vocabulary as bare lower-case names, so JSON-LD ``@type`` and
#: microdata ``itemtype`` - which the extractor spells the same way - are
#: compared with one test rather than two.
_PLACE_TYPE_NAMES = frozenset(t.lower() for t in _PLACE_TYPES if "+" not in t)
_ORG_TYPE_NAMES = frozenset({"organization", "corporation", "onlinestore"})

#: What a page about *visitable* places carries and a page about other kinds
#: of location does not: telephone numbers and opening hours. A store locator
#: lists a phone and hours per branch; a conference venue page has a date and
#: a hall; a jobs page has titles and an apply button; a geographic article has
#: prose. None of this is a vocabulary of place names or a URL rule - it is
#: the shape of the information a person needs to turn up somewhere.
_PHONE_RE = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().\-]{6,18}\d(?![\w/])")
_TIME_RANGE_RE = re.compile(
    r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|h|uhr)?\s*[-–—]\s*\d{1,2}(?:[:.]\d{2})?"
    r"\s*(?:am|pm|h|uhr)?\b", re.I)
_HOURS_WORDS = (
    "opening hours", "opening times", "open hours", "store hours", "hours:",
    "horaires", "öffnungszeiten", "offnungszeiten", "orari", "horario",
    "openingstijden", "godziny otwarcia", "åbningstider", "öppettider",
)
#: Opening hours stated in prose rather than as a numeric range ("open
#: weekdays until six"). Each names the act of opening or closing a place.
_HOURS_PROSE = (
    "open weekdays", "open daily", "open every day", "open seven days", "open mon",
    "opens at", "closes at", "open from", "open until", "closed on", "closed sunday",
    "ouvert du", "geöffnet", "geoffnet", "aperto dal", "abierto de", "aberto de",
)
#: A street address: a building number followed by a street name and a
#: street-type word. The street-type words are the vocabulary of addresses in
#: several languages, not of any site, and a number alone never matches.
_STREET_ADDRESS_RE = re.compile(
    r"\b\d{1,5}[a-zA-Z]?[,\s]+(?:[A-Z][\w'\-]+[,\s]+){0,3}"
    r"(?:Street|St\.?|Road|Rd\.?|Row|Avenue|Ave\.?|Lane|Ln\.?|Drive|Dr\.?|Way|Place|"
    r"Pl\.?|Square|Sq\.?|Centre|Center|Mall|Boulevard|Blvd\.?|Parade|Terrace|Crescent|"
    r"Close|Court|Ct\.?|Highway|Hwy\.?|Broadway|Gate|Hill|Park|Quay|Wharf|"
    r"Straße|Strasse|Str\.?|Platz|Weg|Allee|Gasse|Rue|Via|Viale|Piazza|Corso|Calle|"
    r"Avenida|Plaza|Carrer|Rua|Praça|Marg|Nagar|Sarani|Chowk)\b")
_DAY_WORDS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon-", "mon–", "mon ", "tue ", "wed ", "thu ", "fri ", "sat ", "sun ",
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
    "segunda", "terça", "quarta", "quinta", "sexta", "sábado",
)

#: Declared document types whose "location" is something else: an event's
#: venue, a job's city. A page declaring one of these is about that thing.
_NOT_A_PLACE_PAGE_TYPES = ("event", "jobposting")


def _declares_place_entity(bundle: dict) -> bool:
    """Does anything in the crawl model a visitable location as an entity?

    A bare ``Organization`` with a ``PostalAddress`` counts: one head office
    that a machine can read is a different situation from a chain of shops
    described only in prose, and the rule should only speak to the latter.

    Both structured-data channels are read, through the same test. Microdata
    arrives as a *list* of item records (see ``extract.microdata_items``); an
    earlier version read it as a mapping and raised on the first page that
    carried any, which took the whole entity pillar down with it.
    """
    for page in ev.pages(bundle):
        for node in jsonld_nodes(page):
            types = {t.lower() for t in node_types(node)}
            if types & _PLACE_TYPE_NAMES:
                return True
            if types & _ORG_TYPE_NAMES and prop(node, "address"):
                return True
        for record in microdata_items(page):
            types = set(microdata_types([record]))
            if types & _PLACE_TYPE_NAMES or "postaladdress" in types:
                return True
            if types & _ORG_TYPE_NAMES and microdata_props(record).get("address"):
                return True
    return False


def _presents_itself_as_locations(page: dict) -> bool:
    """Does the page's own URL, title or heading say it is about places?"""
    path = urlsplit(page.get("final_url") or page.get("url") or "").path or ""
    if _LOCATION_PATH_RE.search(path):
        return True
    own = " ".join([str(page.get("title") or "")] + list(page.get("h1_texts") or [])).lower()
    return any(hint in own for hint in _LOCATION_TEXT_HINTS)


def _about_something_else(page: dict) -> bool:
    """An event, a job, an article: a location there is not a place to shop."""
    if page.get("page_type") in ("article", "faq", "policy", "search", "account"):
        return True
    declared = {str(t).lower() for t in (page.get("jsonld_types") or [])}
    return any(d.endswith(_NOT_A_PLACE_PAGE_TYPES) for d in declared)


def physical_location_signals(page: dict) -> Dict[str, object]:
    """The shape of visitable places in a page's text: phones, hours.

    Returns ``{"phones": int, "hours": bool, "established": bool}``. A page
    has established that it presents visitable places when it lists a phone
    number together with opening hours, or several phone numbers - one per
    branch. A single address with no hours, or a list of city names, has not.
    """
    text = str(page.get("text") or "")
    phones = set()
    for match in _PHONE_RE.finditer(text):
        token = match.group(0)
        digits = re.sub(r"\D", "", token)
        # Nine digits or more, so a year range ("2020 - 2024"), a price, an
        # order number or a product code never reads as a telephone; and never
        # a run of digits joined only by dots, which is an IP address or a
        # version string.
        if len(digits) >= 9 and not re.fullmatch(r"\d{4}\s*[-–—]\s*\d{4}", token.strip()) \
                and not re.fullmatch(r"[\d.]+", token.strip()):
            phones.add(re.sub(r"\s+", " ", token.strip()))
    lowered = text.lower()
    hours = (bool(_TIME_RANGE_RE.search(text)) and (
        any(word in lowered for word in _HOURS_WORDS)
        or any(day in lowered for day in _DAY_WORDS))) or \
        any(phrase in lowered for phrase in _HOURS_PROSE)
    addresses = {re.sub(r"\s+", " ", m.group(0).strip(" ,"))
                 for m in _STREET_ADDRESS_RE.finditer(text)}
    # Established when the page carries what a person needs to turn up
    # somewhere: several street addresses, or one with a phone number or
    # opening hours, or a phone number with hours, or several phone numbers.
    established = (len(addresses) >= 2
                   or (len(addresses) >= 1 and (len(phones) >= 1 or hours))
                   or (len(phones) >= 1 and hours)
                   or len(phones) >= 3)
    return {"phones": len(phones), "addresses": len(addresses), "hours": hours,
            "established": established}


def rule_locations_unstructured(bundle: dict) -> Optional[Finding]:
    """The site presents visitable places, and names none of them to a machine.

    What is required, and why. A *fetched* page has to present itself as
    being about places (its own URL, title or heading) *and* carry the shape
    of visitable places - street addresses, a telephone number with opening
    hours, or several telephone numbers - and must not be an event, a job
    listing or an article,
    whose "locations" are a venue, a hiring city or a subject. A link labelled
    "Locations" whose target the crawl never read establishes nothing and is
    reported as not assessed rather than as a store; an earlier version fired
    on that link alone, and told a documentation site with a conference venue
    and a jobs page that its shops were invisible.

    The absence half is unchanged: no LocalBusiness, Store or Place node, and
    no Organization carrying a PostalAddress, anywhere in the crawl.
    """
    pages = [p for p in ev.pages(bundle)
             if not p.get("fetch_failed") and not p.get("non_html")]
    if not sample_guard(pages, 2):
        return None
    if _declares_place_entity(bundle):
        return None

    established: List[Tuple[dict, Dict[str, object]]] = []
    unassessed_links: List[str] = []
    seen_links = set()
    # Every address the crawl read. A locator link whose target is among them
    # was assessed - as a store, or as something else - and is not "unread".
    fetched = set()
    for page in ev.pages(bundle, include_errors=True, include_aliases=True,
                         include_utility=True):
        for key in (page.get("url"), page.get("final_url")):
            if key:
                fetched.add(util.normalize_url(str(key)) or str(key))
    for page in pages:
        if _presents_itself_as_locations(page) and not _about_something_else(page):
            signals = physical_location_signals(page)
            if signals["established"]:
                established.append((page, signals))
                continue
        # Links to pages that *sound* like locators, whose targets this crawl
        # did not read as location pages. Recorded so the reader knows they
        # were seen, and never counted as evidence of a store.
        for link in ((page.get("links", {}) or {}).get("internal", []) or []):
            url = str(link.get("url", ""))
            text = str(link.get("text", "")).strip()
            if url in seen_links or (util.normalize_url(url) or url) in fetched:
                continue
            if _LOCATION_PATH_RE.search(urlsplit(url).path or "") or \
                    any(hint in text.lower() for hint in _LOCATION_TEXT_HINTS):
                seen_links.add(url)
                unassessed_links.append(f"'{text[:40]}' -> {url}")
    if not established:
        return None

    total_phones = sum(int(sig["phones"]) for _, sig in established)
    total_places = sum(max(int(sig.get("addresses") or 0), int(sig["phones"])) for _, sig in established)
    caveat = coverage_caveat(bundle, "store", "location", "branch")
    severity = step_down("high" if total_places >= 3 else "medium", caveat)
    first_page, first = established[0]
    parts = []
    if first.get("addresses"):
        parts.append(f"{first['addresses']} street address(es)")
    if first.get("phones"):
        parts.append(f"{first['phones']} telephone number(s)")
    if first.get("hours"):
        parts.append("opening hours")
    shape = ", ".join(parts) or "location details"
    aside = ""
    if unassessed_links:
        aside = (f" {len(unassessed_links)} further link(s) that sound like a locator "
                 f"(e.g. {unassessed_links[0]}) point at pages this crawl did not read as "
                 f"location pages, and are not counted.")
    return finding(
        "EN-LOCATIONS-UNSTRUCTURED",
        "The site presents visitable locations that exist nowhere as machine-readable entities",
        severity, PILLAR,
        evidence=(f"{len(established)} sampled page(s) present physical locations in prose - "
                  f"{label(first_page)} lists {shape} under a locations heading - but no "
                  f"LocalBusiness, Store or Place node, and no Organization carrying a "
                  f"PostalAddress, appears anywhere in the crawled structured data."
                  + aside + caveat),
        interpretation=("A question such as 'where can I buy this near me?' is resolved from "
                        "typed location entities where they exist. With none published, the "
                        "locations this site describes are available to a machine only as "
                        "prose, which makes them less directly addressable. This audit does "
                        "not measure how any assistant answers such a question."),
        items=[observed(", ".join(x for x in [
                            f"{sig['addresses']} street address(es)" if sig.get("addresses") else "",
                            f"{sig['phones']} telephone number(s)" if sig.get("phones") else "",
                            "opening hours" if sig.get("hours") else ""] if x)
                        + " in prose on a locations page",
                        url=label(page), locator="page text")
               for page, sig in established[:5]]
        + [absent("no LocalBusiness / Store / Place node, and no Organization with a "
                  "PostalAddress, in any crawled page",
                  url=bundle.get("site", {}).get("home_url", ""), locator="structured data")],
        action=action(
            "Publish each location as a LocalBusiness (or the Organization's PostalAddress, "
            "for a single site) with address, hours and phone.",
            priority=severity, effort="medium", impact="high",
            mechanism="A typed location entity states the address, hours and phone in a form "
                      "a machine reads without parsing prose; it is the explicit, "
                      "machine-readable version of what the page already says.",
            steps=["Give every location its own crawlable URL under the locator, "
                   "server-rendered rather than assembled by a map widget.",
                   "On each, emit LocalBusiness (or the specific subtype) JSON-LD with name, "
                   "address (PostalAddress with streetAddress, addressLocality, postalCode, "
                   "addressCountry), telephone, openingHoursSpecification, geo and a stable @id.",
                   "For a single site, an Organization node with a PostalAddress and telephone "
                   "on the home or contact page is enough.",
                   "Link each location back to the brand with parentOrganization, and list "
                   "them all from the locator page as a plain HTML list, not only on a map."],
            verification="Fetching a location URL with JavaScript disabled shows the address "
                         "and hours in the HTML, and its JSON-LD validates as LocalBusiness."),
        urls=[label(page) for page, _ in established],
        confidence=0.85 if total_places >= 3 else 0.7,
        metrics={"scope": "site", "affected": len(established), "sampled": len(pages),
                 "telephone_numbers_observed": total_phones,
                 "street_addresses_observed": sum(int(sig.get("addresses") or 0)
                                                  for _, sig in established),
                 "unassessed_location_links": len(unassessed_links)},
        tags=["entity", "local"])


RULES = (
    rule_locations_unstructured,
    rule_org_incomplete,
    rule_name_inconsistency,
    rule_product_brand_missing,
    rule_product_brand_mismatch,
    rule_missing_entity_ids,
    rule_duplicate_product_names,
    rule_duplicate_titles,
    rule_category_undeclared,
    rule_self_description,
    rule_sameas_undeclared,
    rule_variants_unmodelled,
    rule_contact_grounding,
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
