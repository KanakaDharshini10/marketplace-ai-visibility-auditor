"""Turn one fetched document into a flat, JSON-serialisable bag of *facts*.

Everything a specialist skill is allowed to reason about lives here. Because
the output is plain JSON, the whole evidence bundle can be dumped to disk and
re-inspected by a human - which is what makes "never invent evidence"
verifiable rather than aspirational.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote_plus

from . import lexicon, util
from .htmldom import Document, parse_html

# ---------------------------------------------------------------------------
# regexes
# ---------------------------------------------------------------------------

CURRENCY_SYMBOLS = "₹$€£¥₩₽₺₴₦₪₫฿₱₡₲₵₸₮₭₾₼؋"

#: Alphabetic currency codes and common abbreviations, written *without* a
#: trailing ``\b``: "Rs." ends in a full stop, and a word boundary after a
#: non-word character requires a word character next, so `Rs. 499` never
#: matched at all.
CURRENCY_CODES = (
    "INR", "USD", "EUR", "GBP", "AUD", "CAD", "NZD", "JPY", "CNY", "SGD",
    "HKD", "AED", "SAR", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF",
    "RON", "TRY", "ZAR", "BRL", "MXN", "ARS", "CLP", "COP", "PEN", "ILS",
    "THB", "MYR", "IDR", "PHP", "VND", "KRW", "TWD", "RUB", "UAH", "NGN",
    "KES", "EGP", "PKR", "BDT", "LKR", "Rs", "kr", "zł", "Kč", "лв", "R\\$",
    # Locale spellings that appear far more often than the ISO code on the
    # sites that use them. Without these, an Indonesian, Malaysian or
    # Philippine storefront reads as publishing no price at all - which then
    # cascades into "the price is locked inside an image".
    "Rp", "RM", "S\\$", "HK\\$", "NT\\$", "A\\$", "C\\$", "NZ\\$", "R\\$",
)

_CODE_ALT = "|".join(sorted(CURRENCY_CODES, key=len, reverse=True))

#: The amount itself.
#:
#: Two alternatives, longest-form first, and the grouped one now *requires* at
#: least one group separator (``+`` not ``*``). With ``*`` the grouped branch
#: matched the first three digits of ``1200`` and succeeded, so the plain
#: branch was never tried and ``$1200`` was read as 120 - an error that turned
#: a correct page into a high-severity ``FC-PRICE-CONFLICT`` against its own
#: JSON-LD. The trailing ``(?!\d)`` stops any partial match of a longer run.
#:
#: Groups are ``\d{2,3}``, not ``\d{3}``, because the Indian numbering system
#: groups in lakhs and crores: ``\u20b91,20,000`` is one hundred and twenty
#: thousand. Requiring three-digit groups made that fall through to the plain
#: branch, which matched ``1,20`` and read the price as **1.2** - producing a
#: fabricated ``FC-PRICE-CONFLICT`` ("markup says 120000, page shows 1.2") on
#: a page whose text and JSON-LD agreed exactly. The final group is still
#: anchored at three digits, which is true in both systems.
_AMOUNT = (r"(?:\d{1,3}(?:[.,\s\u00a0\u202f]\d{2,3})*[.,\s\u00a0\u202f]\d{3}(?:[.,]\d{1,2})?"
           r"|\d+(?:[.,]\d{1,2})?)(?!\d)")

#: Prefix form (``$1,299.50``, ``CHF 89.00``, ``Rs. 499``) and postfix form
#: (``19,99 €``, ``1 299 kr``). Both are ordinary on real storefronts; only the
#: prefix form was recognised before, so every postfix-currency locale had its
#: visible prices read as absent.
#: An alphabetic currency code is matched in its own case, never folded.
#:
#: The pattern is case-insensitive overall, because a *symbol* has no case and
#: the surrounding alternation is easier to read that way. Applied to the code
#: alternation, though, case-insensitivity turns ordinary English words into
#: currencies: ``TRY`` is the Turkish lira, so "Try 7 days free" was read as a
#: price of 7, and a product page whose only "price" was that trial offer
#: reported it as the item's price. ``PEN`` (Peruvian sol) does the same to "a
#: pen 5 pack", ``COP`` (Colombian peso) to "the cop 20 summit", ``RON``
#: (Romanian leu) to a person's name.
#:
#: `(?-i:...)` scopes the flag off for exactly this group - stdlib since 3.6 -
#: so `TRY 7` is still a price and `try 7` is a sentence. Codes are listed in
#: their canonical spelling (`INR`, `Rs`, `kr`, `Rp`), which is how a site that
#: means the currency writes it.
_CODE_GROUP = r"(?-i:" + _CODE_ALT + r")"

PRICE_RE = re.compile(
    r"(?:(?P<sym>[" + CURRENCY_SYMBOLS + r"])|(?P<code>" + _CODE_GROUP + r"\.?))"
    r"\s*(?P<amount>" + _AMOUNT + r")"
    r"|"
    r"(?<![\w.,])(?P<amount_post>" + _AMOUNT + r")\s*"
    r"(?:(?P<sym_post>[" + CURRENCY_SYMBOLS + r"])|(?P<code_post>" + _CODE_GROUP + r")(?![\w]))"
    # A symbol with a number after it belongs to that number, not to the one
    # before it. Product names routinely end in digits ("Vento 300", "Model
    # 3"), so on "Cafetera Vento 300 EUR5.499" the postfix branch would
    # otherwise read "300 EUR" and report a price conflict against the site's
    # own correct Offer.price.
    r"(?!\s*\d)",
    re.I,
)

#: A price written with a currency *symbol* is unambiguous: no word is spelled
#: `₹` or `€`. A price written with an alphabetic *code* is a token that could
#: also be a model designator or an abbreviation ("Model RM 55"), so it is
#: reported as a price of lower confidence, and a caller that must state an
#: exact value says the value is uncertain instead of asserting it.
PRICE_CONFIDENCE = {"symbol": "high", "code": "medium"}


def price_match_kind(match) -> str:
    """``symbol`` or ``code`` - which branch of :data:`PRICE_RE` matched."""
    if match.group("sym") or match.group("sym_post"):
        return "symbol"
    return "code"


def price_confidence(match) -> str:
    """``high`` for a symbol-marked price, ``medium`` for a code-marked one."""
    return PRICE_CONFIDENCE[price_match_kind(match)]


def price_match_parts(match) -> Tuple[str, str]:
    """``(currency, amount)`` from either the prefix or the postfix branch."""
    amount = match.group("amount") or match.group("amount_post") or ""
    currency = (match.group("sym") or match.group("code")
                or match.group("sym_post") or match.group("code_post") or "")
    return currency.strip().rstrip("."), amount


#: Stock states. The first three come from the multilingual lexicon; "limited"
#: is a numeric pattern that reads the same in every Latin-script language.
AVAILABILITY_CONCEPTS = ("in_stock", "out_of_stock", "preorder")
LIMITED_STOCK_RE = re.compile(
    r"\bonly \d+ left\b|\blow stock\b|\blimited stock\b|\bsolo \d+|\bnur noch \d+",
    re.I)

WARRANTY_RE = re.compile(
    r"\bwarrant(y|ies)\b|\bguarantee\b|\bgarantia\b|\bgarantie\b|\bgaranzia\b", re.I)

#: A heading that ends in a question mark is a question in every language that
#: uses one - far more portable than a list of English interrogatives.
#: A heading ending in a question mark, ASCII or full-width (CJK keyboards
#: emit U+FF1F), or the Arabic/Greek question marks.
QUESTION_RE = re.compile(r"^\s*\S.{10,}[?\uff1f\u061f\u037e]\s*$", re.S)
COPYRIGHT_YEAR_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–—]\s*)?((?:19|20)\d{2})", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

#: Framework mount points. Their *presence* proves nothing - every
#: server-rendered React, Vue, Nuxt or Angular page has one too, filled with
#: content. Only an **empty** mount point is evidence that the raw response
#: carries no content, so each of these is confirmed against the parsed DOM
#: before it is recorded. See :func:`_empty_mount_points`.
SPA_ROOT_IDS = (
    ("root", "React"),
    ("app", "Vue/Nuxt"),
    ("__next", "Next.js"),
    ("__nuxt", "Nuxt"),
    ("q-app", "Quasar"),
    ("svelte", "Svelte"),
)

#: Attributes that mark a client-rendered root in place, rather than by id.
SPA_ROOT_ATTRS = (
    ("data-reactroot", "React"),
    ("ng-version", "Angular"),
)

#: Hydration payloads. These are emitted by *fully server-rendered* pages as
#: well - ``__NEXT_DATA__`` appears on every Next.js page ever served - so they
#: are recorded separately and are never on their own evidence that a page is a
#: shell. Treating them as sufficient is what makes an SSR site look blank.
HYDRATION_MARKERS = (
    ("__NEXT_DATA__", "Next.js hydration payload"),
    ("window.__NUXT__", "Nuxt hydration payload"),
    ("window.__INITIAL_STATE__", "client-side state hydration payload"),
    ("window.__APOLLO_STATE__", "Apollo cache hydration payload"),
    ("data-sveltekit", "SvelteKit hydration payload"),
)

#: Words of text inside a mount point below which it counts as empty. A shell
#: is not always literally `<div id="root"></div>`; it may hold a spinner, a
#: "Loading…" string or a noscript nudge.
_EMPTY_MOUNT_WORDS = 12

#: Hosts where a brand's official presence lives. The list must not be
#: Western-only: a site whose profiles are on Weibo, VK, Naver or Line would
#: otherwise yield no anchors at all and collect a `high` "no corroboration
#: anchors" finding stating something untrue about a brand that is in fact
#: corroborated in several places.
SOCIAL_HOSTS = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "pinterest.com", "tiktok.com", "threads.net", "wikipedia.org",
    "wikidata.org", "crunchbase.com", "g.page", "goo.gl/maps", "maps.google",
    "trustpilot.com", "glassdoor.com", "github.com", "reddit.com",
    # East and South-East Asia
    "weibo.com", "weibo.cn", "xiaohongshu.com", "douyin.com", "bilibili.com",
    "zhihu.com", "line.me", "naver.com", "blog.naver.com", "kakao.com",
    "kakaocorp.com", "band.us", "qq.com", "wechat.com", "zalo.me",
    # Russia, CIS, Middle East, Latin America, Europe
    "vk.com", "ok.ru", "telegram.me", "t.me", "rutube.ru", "yandex.ru",
    "mercadolibre.com", "vimeo.com", "xing.com", "mastodon.social",
    "bsky.app", "medium.com", "behance.net", "dribbble.com",
    # review and knowledge surfaces
    "yelp.com", "tripadvisor.com", "g2.com", "capterra.com", "trustedshops.com",
    "opencorporates.com", "bloomberg.com", "companieshouse.gov.uk",
)

KNOWLEDGE_HOSTS = ("wikipedia.org", "wikidata.org", "crunchbase.com",
                   "opencorporates.com", "bloomberg.com", "linkedin.com")

#: Social *share* endpoints. They live on the same hosts as real profiles but
#: assert nothing about identity - a "share on Facebook" button is not an
#: official account, and citing one as a profile link is a false positive.
SHARE_INTENT_RE = re.compile(
    r"sharer\.php|/sharer/|/share(r)?[/?]|/shareArticle|/intent/|/dialog/|"
    r"pinterest\.[a-z.]+/pin/create|reddit\.com/submit|t\.me/share|"
    r"wa\.me/\?|api\.whatsapp\.com/send|/share-offsite|[?&]u=http|[?&]url=http",
    re.I)


# ---------------------------------------------------------------------------
# JSON-LD helpers (shared by several specialist skills)
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def node_types(node: Any) -> List[str]:
    if not isinstance(node, dict):
        return []
    out = []
    for value in _as_list(node.get("@type")):
        if isinstance(value, str):
            out.append(value.split("/")[-1].split("#")[-1])
    return out


# ---------------------------------------------------------------------------
# microdata (the boundary contract, stated once)
# ---------------------------------------------------------------------------
#
# ``facts["microdata"]`` is a *list* of item records, one per ``itemscope``
# element, each shaped ``{"itemtype": str | None, "types": [str], "props":
# {name: [str]}}``. It is never a mapping. Two consumers have now read it as one
# - the classifier (fixed in 1.8.x) and the entity specialist, whose
# ``micro.get("types")`` raised ``'list' object has no attribute 'get'`` on the
# first page that carried any microdata at all, and the orchestrator reported
# the whole pillar as a failed specialist. The accessors below are the only
# sanctioned way to read the field: they accept the list, tolerate a single
# record passed bare, and yield nothing for anything else, so a consumer never
# has to know the shape and never has to guess at it.

#: The keys that make a mapping an item record rather than something else.
_MICRODATA_RECORD_KEYS = frozenset({"itemtype", "types", "props"})


def microdata_items(facts: Any) -> List[dict]:
    """Every microdata item record on a page, whatever the field's shape.

    Reads ``facts["microdata"]`` when given a page fact-bag, or the raw field
    value itself. A single record passed bare is one item; anything that is
    not a record is skipped rather than raised on. The data is *read*, not
    filtered: every record the extractor produced comes back.
    """
    raw = facts
    if isinstance(facts, dict):
        if "microdata" in facts:
            raw = facts.get("microdata")
        elif not _MICRODATA_RECORD_KEYS & set(facts):
            return []                       # a fact-bag with no microdata field
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [record for record in raw
            if isinstance(record, dict) and _MICRODATA_RECORD_KEYS & set(record)]


def microdata_types(facts: Any) -> List[str]:
    """Bare, lower-cased type names every microdata item on a page declares.

    ``https://schema.org/LocalBusiness`` and a pre-split ``LocalBusiness`` both
    arrive as ``localbusiness``, the same spelling ``node_types`` gives JSON-LD,
    so a rule can compare the two vocabularies without a second code path.
    """
    out: List[str] = []
    for record in microdata_items(facts):
        for value in list(_as_list(record.get("types"))) + [record.get("itemtype")]:
            if isinstance(value, str) and value.strip():
                out.append(value.strip().rstrip("/").rsplit("/", 1)[-1]
                           .rsplit("#", 1)[-1].lower())
    return out


def microdata_props(record: Any) -> Dict[str, List[str]]:
    """The ``itemprop`` values of one item record, name -> values, never raising."""
    if not isinstance(record, dict):
        return {}
    props = record.get("props")
    if not isinstance(props, dict):
        return {}
    return {str(name): [str(v) for v in _as_list(values)] for name, values in props.items()}


def flatten_jsonld(data: Any, _depth: int = 0) -> List[dict]:
    """Yield every dict node in a JSON-LD payload, @graph included."""
    out: List[dict] = []
    if _depth > 12:
        return out
    if isinstance(data, list):
        for item in data:
            out.extend(flatten_jsonld(item, _depth + 1))
    elif isinstance(data, dict):
        out.append(data)
        for key, value in data.items():
            if key in ("@context",):
                continue
            if isinstance(value, (dict, list)):
                out.extend(flatten_jsonld(value, _depth + 1))
    return out


def find_nodes(nodes: Iterable[dict], *types: str) -> List[dict]:
    wanted = {t.lower() for t in types}
    return [n for n in nodes if any(t.lower() in wanted for t in node_types(n))]


def prop(node: dict, *names: str) -> Any:
    """First present property among ``names`` (schema.org is inconsistent)."""
    if not isinstance(node, dict):
        return None
    lowered = {k.lower(): v for k, v in node.items()}
    for name in names:
        if name in node:
            return node[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def text_of(value: Any) -> Optional[str]:
    """Coerce a schema.org value into a plain string when it has one."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "@value", "value", "url", "@id"):
            if key in value:
                return text_of(value[key])
        return None
    if isinstance(value, list):
        for item in value:
            got = text_of(item)
            if got:
                return got
    return None


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------

def _meta_maps(doc: Document) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    named: Dict[str, str] = {}
    prop_meta: Dict[str, str] = {}
    http_equiv: Dict[str, str] = {}
    for meta in doc.find_all("meta"):
        content = (meta.get("content") or "").strip()
        if meta.has_attr("name"):
            named.setdefault(meta.get("name").strip().lower(), content)
        if meta.has_attr("property"):
            prop_meta.setdefault(meta.get("property").strip().lower(), content)
        if meta.has_attr("http-equiv"):
            http_equiv.setdefault(meta.get("http-equiv").strip().lower(), content)
    return named, prop_meta, http_equiv


def _extract_jsonld(doc: Document) -> List[dict]:
    blocks: List[dict] = []
    for index, script in enumerate(doc.find_all("script")):
        script_type = (script.get("type") or "").strip().lower()
        if script_type != "application/ld+json":
            continue
        raw = script.raw_text.strip()
        entry: Dict[str, Any] = {"index": index, "bytes": len(raw), "parse_ok": False,
                                 "error": None, "types": [], "data": None}
        if not raw:
            entry["error"] = "empty <script type=application/ld+json> block"
            blocks.append(entry)
            continue
        cleaned = raw
        # Tolerate the two most common authoring mistakes so that we report
        # "invalid JSON-LD" only when it is genuinely unparseable.
        if cleaned.startswith("//<![CDATA["):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("]]>", 1)[0]
        cleaned = cleaned.replace("<!--", "").replace("-->", "").strip()
        try:
            data = json.loads(cleaned)
            entry["parse_ok"] = True
            entry["data"] = data
            entry["types"] = sorted({t for node in flatten_jsonld(data) for t in node_types(node)})
            context = None
            if isinstance(data, dict):
                context = data.get("@context")
            elif isinstance(data, list) and data and isinstance(data[0], dict):
                context = data[0].get("@context")
            entry["context"] = text_of(context)
        except (json.JSONDecodeError, ValueError) as exc:
            entry["error"] = f"invalid JSON: {exc}"
        blocks.append(entry)
    return blocks


def _extract_microdata(doc: Document) -> List[dict]:
    items: List[dict] = []
    for node in doc.find_all(attrs={"itemscope": None}):
        itemtype = node.get("itemtype")
        props: Dict[str, List[str]] = {}
        for child in node.walk():
            if child.is_text or not child.has_attr("itemprop"):
                continue
            name = child.get("itemprop").strip()
            value = (child.get("content") or child.get("href") or child.get("src")
                     or child.get("datetime") or child.get_text(" "))
            props.setdefault(name, []).append(util.truncate(value, 120))
        items.append({
            "itemtype": itemtype,
            "types": [itemtype.rstrip("/").split("/")[-1]] if itemtype else [],
            "props": props,
        })
    return items


def _extract_links(doc: Document, base_url: str) -> Dict[str, Any]:
    internal: List[dict] = []
    external: List[dict] = []
    nofollow = 0
    seen_internal = set()
    for anchor in doc.find_all("a"):
        href = anchor.get("href")
        if not href:
            continue
        normalized = util.normalize_url(href, base_url)
        if not normalized:
            continue
        rel = (anchor.get("rel") or "").lower()
        if "nofollow" in rel:
            nofollow += 1
        record = {
            "url": normalized,
            "text": util.truncate(anchor.get_text(" "), 90),
            "rel": rel,
            "in_nav": anchor.has_ancestor({"nav", "header"}),
            "in_footer": anchor.has_ancestor({"footer"}),
        }
        if util.same_site(normalized, base_url):
            if normalized in seen_internal:
                continue
            seen_internal.add(normalized)
            internal.append(record)
        else:
            external.append(record)
    return {"internal": internal, "external": external, "nofollow_count": nofollow}


def _extract_headings(doc: Document) -> List[dict]:
    out = []
    for node in doc.find_all({"h1", "h2", "h3", "h4", "h5", "h6"}):
        out.append({"level": int(node.tag[1]),
                    "text": util.truncate(node.get_text(" "), 160)})
    return out


#: How many control labels to keep per page. Enough for every button and
#: link-as-button a product or listing page carries; a cap, not a sample.
_MAX_CONTROL_LABELS = 80


def _extract_control_labels(doc: Document) -> List[str]:
    """The visible text of every clickable control on the page.

    Buttons, submit inputs, elements playing the button role, and disclosure
    summaries. Recorded so a downstream reader can tell a heading that names
    a thing from a heading that repeats a call to action: "Add to bag" is a
    control label wherever it appears, and a page whose only heading matches
    one of its own controls has not named its subject. The list is what the
    page itself says its controls are called - no vocabulary is involved.
    """
    labels: List[str] = []
    seen = set()

    def keep(text: str) -> None:
        clean = util.collapse_ws(text or "")
        key = clean.lower()
        if clean and key not in seen and len(labels) < _MAX_CONTROL_LABELS:
            seen.add(key)
            labels.append(util.truncate(clean, 80))

    for node in doc.find_all({"button", "summary"}):
        keep(node.get_text(" ") or node.get("aria-label") or node.get("value") or "")
    for node in doc.find_all("input"):
        if (node.get("type") or "").strip().lower() in ("submit", "button", "reset", "image"):
            keep(node.get("value") or node.get("aria-label") or node.get("alt") or "")
    for node in doc.find_all(attrs={"role": None}):
        if (node.get("role") or "").strip().lower() in ("button", "menuitem", "tab"):
            keep(node.get_text(" ") or node.get("aria-label") or "")
    return labels


def _extract_tables(doc: Document) -> List[dict]:
    tables = []
    for table in doc.find_all("table"):
        rows = table.find_all("tr")
        two_col_rows = 0
        pairs: List[Tuple[str, str]] = []
        for row in rows:
            cells = row.find_all({"td", "th"})
            if len(cells) == 2:
                two_col_rows += 1
                if len(pairs) < 8:
                    pairs.append((util.truncate(cells[0].get_text(" "), 60),
                                  util.truncate(cells[1].get_text(" "), 60)))
        tables.append({
            "rows": len(rows),
            "two_column_rows": two_col_rows,
            "looks_like_spec_table": len(rows) >= 3 and two_col_rows >= max(2, len(rows) - 1),
            "sample_pairs": pairs,
            "has_caption": table.find("caption") is not None,
        })
    return tables


def _extract_definition_specs(doc: Document) -> int:
    """`<dl><dt>Material</dt><dd>Mesh</dd></dl>` is a spec list too."""
    count = 0
    for dl in doc.find_all("dl"):
        dts = len(dl.find_all("dt"))
        dds = len(dl.find_all("dd"))
        if dts >= 2 and dds >= 2:
            count += 1
    return count


def _extract_definition_terms(doc: Document) -> List[str]:
    """The `<dt>` labels themselves, so a recommendation can name real attributes."""
    terms: List[str] = []
    for dl in doc.find_all("dl"):
        for dt_node in dl.find_all("dt"):
            text = util.collapse_ws(dt_node.get_text(" ")).strip(" : ")
            if 2 <= len(text) <= 40:
                terms.append(util.truncate(text, 40))
    return terms[:20]


#: A `Label: value` line in visible copy. Deliberately shape-based rather than
#: keyword-based: it detects that the page *states an attribute*, in any
#: language, without the auditor holding an opinion about which attributes a
#: given trade ought to publish.
VISIBLE_ATTRIBUTE_PAIR_RE = re.compile(
    r"(?m)^[ \t]*(?P<label>[^\n:;=|]{2,40}?)[ \t]*[:：][ \t]*(?P<value>[^\n]{1,80}?)[ \t]*$")

#: Labels that are page furniture rather than product attributes.
_NON_ATTRIBUTE_LABELS = re.compile(
    r"(?i)\b(https?|www|tel|email|e-mail|copyright|menu|search|share|follow|"
    r"subscribe|newsletter|cart|login|sign in|sign up|home|note|warning|error|"
    r"tip|example|see also)\b")


def _extract_visible_attribute_pairs(block_text: str) -> List[Dict[str, str]]:
    """`Label: value` pairs stated in the page's own visible copy.

    This exists so the audit can tell *unstructured* apart from *absent*. A
    page that states an attribute in prose ("Fat content: 22%") has published
    it; what it has not done is expose it in a form a machine can read without
    parsing English. Those are different findings with different
    fixes, and conflating them produces a report that tells a site owner
    information is missing while they are looking straight at it.
    """
    pairs: List[Dict[str, str]] = []
    seen = set()
    for match in VISIBLE_ATTRIBUTE_PAIR_RE.finditer(block_text or ""):
        label = util.collapse_ws(match.group("label")).strip()
        value = util.collapse_ws(match.group("value")).strip()
        if not label or not value:
            continue
        # A label is a short noun phrase, not a sentence.
        if len(label.split()) > 4 or label.endswith((".", "!", "?")):
            continue
        if _NON_ATTRIBUTE_LABELS.search(label):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"label": util.truncate(label, 40),
                      "value": util.truncate(value, 60)})
        if len(pairs) >= 20:
            break
    return pairs


def _extract_images(doc: Document) -> Dict[str, Any]:
    total = 0
    missing_alt = 0
    empty_alt = 0
    lazy_only = 0
    samples: List[dict] = []
    for img in doc.find_all("img"):
        total += 1
        if not img.has_attr("alt"):
            missing_alt += 1
            if len(samples) < 6:
                samples.append({"src": util.truncate(img.get("src") or img.get("data-src"), 120),
                                "issue": "no alt attribute"})
        elif not (img.get("alt") or "").strip():
            empty_alt += 1
        if not img.get("src") and (img.get("data-src") or img.get("data-lazy-src")):
            lazy_only += 1
    return {"total": total, "missing_alt": missing_alt, "empty_alt": empty_alt,
            "lazy_src_only": lazy_only, "samples": samples}


def _extract_scripts(doc: Document, html: str) -> Dict[str, Any]:
    external = 0
    inline_bytes = 0
    for script in doc.find_all("script"):
        script_type = (script.get("type") or "").strip().lower()
        if script.get("src"):
            external += 1
        elif script_type in ("", "text/javascript", "module", "application/javascript"):
            inline_bytes += len(script.raw_text)
    return {"external_count": external, "inline_bytes": inline_bytes,
            "spa_markers": _empty_mount_points(doc),
            "hydration_markers": [reason for token, reason in HYDRATION_MARKERS
                                  if token in html]}


def _empty_mount_points(doc: Document) -> List[str]:
    """Framework mount points that are actually empty in the raw response.

    This is the whole difference between "this site uses React" and "this page
    arrives blank". Only the second is a finding, and only the second is
    recorded here.
    """
    found: List[str] = []
    seen = set()

    def consider(node, label: str) -> None:
        if label in seen:
            return
        text = util.collapse_ws(node.get_text())
        if util.word_count(text) < _EMPTY_MOUNT_WORDS:
            seen.add(label)
            found.append(f"empty {label} mount point in the raw HTML")

    for node in doc.find_all("div"):
        node_id = (node.get("id") or "").strip().lower()
        if not node_id:
            continue
        for candidate, label in SPA_ROOT_IDS:
            if node_id == candidate:
                consider(node, label)
    for attr, label in SPA_ROOT_ATTRS:
        node = doc.find(None, {attr: True})
        if node is not None:
            consider(node, label)
    return found


#: Control names that narrow a result set (a *filter*).
FILTER_NAME_TOKENS = ("filter", "facet", "refine", "brand", "price", "category",
                      "size", "color", "colour", "rating", "material", "flavour",
                      "flavor", "type", "collection", "availability")

#: Control names that re-order a result set without removing anything (a *sort*).
#: Kept strictly separate from the filter tokens: sorting and filtering are
#: different affordances that answer different questions, and conflating them
#: produces a finding that contradicts what is on the page.
SORT_NAME_TOKENS = ("sort", "sort_by", "sortby", "orderby", "order_by",
                    "sort-by", "ordenar", "trier", "sortieren", "ordinare")

#: Query *parameter names* a listing uses to express an active sort. Matched
#: against the query string only - never against the path, where "sort" and
#: "order" appear inside ordinary product slugs.
SORT_QUERY_TOKENS = ("sort_by", "sort", "orderby", "order_by", "sortby",
                     "sort-by", "order")

#: Query parameter names that express an active filter. Same rule: a product
#: called "Refined Coconut Oil" lives at /products/refined-coconut-oil, and
#: matching "refine" as a substring of the path turned that link into a
#: reported filter control.
FILTER_QUERY_TOKENS = ("filter", "facet", "facets", "refine", "refinement",
                       "constraint", "pf", "tags", "tag", "pf_rd")


#: Search-endpoint spellings. The page-type classifier already localises this
#: concept; the form detector did not, so an ordinary French or German header
#: search box read as "the site offers no search a visitor can use".
SEARCH_ACTION_TOKENS = (
    "search", "buscar", "busca", "busqueda", "recherche", "rechercher", "suche",
    "suchen", "ricerca", "cerca", "zoeken", "szukaj", "wyszukiwarka", "sok",
    "soek", "sog", "arama", "ara", "procurar", "pesquisa", "pesquisar",
)

#: Query-parameter names a search form submits under.
SEARCH_QUERY_TOKENS = ("q", "s", "query", "keyword", "keywords", "search",
                       "search_query", "term", "wd", "kw")


def _looks_like_search(action: str) -> bool:
    if not action:
        return False
    lowered = action.lower()
    if any(token in lowered for token in SEARCH_ACTION_TOKENS):
        return True
    return bool(_query_parameter_names(lowered) & set(SEARCH_QUERY_TOKENS))


def _query_parameter_names(url: str) -> set:
    """Lower-cased parameter names in a URL's query string, prefixes included.

    Shopify-style faceting uses dotted names (``filter.p.price``), so the
    leading component is kept as well as the whole name - that is what makes
    ``filter.v.option`` match ``filter`` without matching a path segment.
    """
    query = url.split("?", 1)[1] if "?" in url else ""
    names = set()
    for pair in query.split("&"):
        name = pair.split("=", 1)[0].strip().lower()
        if not name:
            continue
        names.add(name)
        names.add(name.split(".", 1)[0])
        names.add(name.split("[", 1)[0])
    return names


def _control_label(node, fallback: str = "") -> str:
    """A human name for a control, from whatever the markup actually provides."""
    for attr in ("aria-label", "data-label", "title", "name", "id"):
        value = util.collapse_ws(node.get(attr) or "")
        if value:
            return util.truncate(value, 40)
    return util.truncate(fallback, 40)


def _extract_forms(doc: Document) -> Dict[str, Any]:
    has_search = False
    filter_controls = 0
    sort_controls = 0
    newsletter = False
    cart_action = False
    cart_action_in_main = False
    # How many purchase controls sit in the content region, not only whether
    # one does. One is what fixes *which* item a page is about; a grid of them
    # - one per tile on a listing or a search results page - is the opposite
    # statement, and a boolean could not tell the two apart.
    cart_actions_in_main = 0
    # A sign-in or registration form in the content region: the mark of an
    # account/auth endpoint, which is never a content document.
    password_form_in_main = False
    # What the page's own search form is called and what it is holding. A
    # search results page pre-fills its search box with the query it ran, and
    # submits under a parameter name of its own choosing; both are the page's
    # own statement that a URL carrying that query is one of its searches.
    search_param_names: List[str] = []
    search_prefill_values: List[str] = []
    # The names of what was actually found, not just how many. A finding that
    # says "no filter controls; the page does expose sort controls" is worth
    # more when it can list the sort options it saw, because the reader can
    # check the claim against the page in front of them.
    filter_names: List[str] = []
    sort_names: List[str] = []
    sort_options: List[str] = []

    def note_search_field(field) -> None:
        field_type = (field.get("type") or "text").strip().lower()
        if field_type not in ("text", "search", ""):
            return
        field_name = (field.get("name") or "").strip().lower()
        if field_name and field_name not in search_param_names and \
                len(search_param_names) < 12:
            search_param_names.append(field_name)
        value = util.collapse_ws(field.get("value") or "").lower()
        if value and value not in search_prefill_values and len(search_prefill_values) < 12:
            search_prefill_values.append(util.truncate(value, 80))

    for form in doc.find_all("form"):
        action = (form.get("action") or "").lower()
        is_search_form = False
        if _looks_like_search(action) or form.find("input", {"type": "search"}):
            is_search_form = True
        elif (form.get("role") or "").lower() == "search":
            is_search_form = True
        else:
            # `<form action="/"><input name="q">` is a search box in any
            # language; the parameter name is the language-neutral signal.
            for field in form.find_all("input"):
                field_name = (field.get("name") or "").strip().lower()
                field_type = (field.get("type") or "text").strip().lower()
                if field_type in ("text", "search", "") and \
                        field_name in SEARCH_QUERY_TOKENS:
                    is_search_form = True
                    break
        if is_search_form:
            has_search = True
            for field in form.find_all("input"):
                note_search_field(field)
        if "newsletter" in action or "subscribe" in action:
            newsletter = True
        in_content = not form.has_ancestor({"nav", "header", "footer"})
        # A form posting to the cart is a purchase affordance in any language.
        if any(token in action for token in ("/cart", "/checkout", "cart/add",
                                             "/panier", "/warenkorb", "/carrito",
                                             "/carrinho", "/carrello")):
            cart_action = True
            # *Where* it sits decides what it proves. Every page of a
            # storefront carries the header's cart control, so its presence
            # says the site sells things, not that this page is one of them.
            # Only a purchase affordance inside the content region is evidence
            # about the page it is on.
            if in_content:
                cart_action_in_main = True
                cart_actions_in_main += 1
        if in_content and form.find("input", {"type": "password"}) is not None:
            password_form_in_main = True
    for node in doc.find_all("input", {"type": "search"}):
        has_search = True
        note_search_field(node)
    for node in doc.find_all("input"):
        input_type = (node.get("type") or "").lower()
        name = (node.get("name") or node.get("id") or "").lower()
        if input_type in ("checkbox", "radio"):
            if any(token in name for token in SORT_NAME_TOKENS):
                sort_controls += 1
                sort_names.append(_control_label(node))
            elif any(token in name for token in FILTER_NAME_TOKENS):
                filter_controls += 1
                filter_names.append(_control_label(node))
        if input_type == "search":
            has_search = True
        if "email" in input_type or "newsletter" in name or "subscribe" in name:
            newsletter = True
    for select in doc.find_all("select"):
        name = (select.get("name") or select.get("id") or "").lower()
        # Sort is tested first and wins: a control named "sort_by" also
        # contains "by", and several storefronts name their sort select
        # "SortBy" inside a form whose action carries filter parameters.
        if any(token in name for token in SORT_NAME_TOKENS):
            sort_controls += 1
            sort_names.append(_control_label(select))
            for option in select.find_all("option"):
                text = util.collapse_ws(option.get_text(" "))
                if text and text not in sort_options:
                    sort_options.append(util.truncate(text, 40))
        elif any(token in name for token in FILTER_NAME_TOKENS):
            filter_controls += 1
            filter_names.append(_control_label(select))
    # Both affordances are frequently built from links or custom elements
    # rather than form controls, so the attribute hooks are checked too.
    for node in doc.find_all(attrs={"data-filter": None}):
        filter_controls += 1
        filter_names.append(_control_label(node, node.get("data-filter") or ""))
    for attr in ("data-sort", "data-sort-by"):
        for node in doc.find_all(attrs={attr: None}):
            sort_controls += 1
            sort_names.append(_control_label(node, node.get(attr) or ""))
    # A listing that links to its own sorted/filtered variants exposes the
    # affordance even with no <select> at all.
    for node in doc.find_all("a"):
        href = (node.get("href") or "").lower()
        if not href:
            continue
        text = util.collapse_ws(node.get_text(" "))
        params = _query_parameter_names(href)
        if params & set(SORT_QUERY_TOKENS):
            sort_controls += 1
            if text and text not in sort_options:
                sort_options.append(util.truncate(text, 40))
        if params & set(FILTER_QUERY_TOKENS):
            filter_controls += 1
            if text:
                filter_names.append(util.truncate(text, 40))

    def _unique(values: List[str], limit: int = 12) -> List[str]:
        out: List[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out[:limit]

    return {"has_site_search": has_search,
            "filter_controls": filter_controls,
            "sort_controls": sort_controls,
            "has_filter_controls": filter_controls > 0,
            "has_sort_controls": sort_controls > 0,
            "filter_control_names": _unique(filter_names),
            "sort_control_names": _unique(sort_names),
            "sort_options": _unique(sort_options),
            # Retained for backwards compatibility with bundles written by
            # earlier versions; new code reads has_sort_controls.
            "has_sort_control": sort_controls > 0,
            "has_newsletter": newsletter,
            "has_cart_action": cart_action,
            "has_cart_action_in_main": cart_action_in_main,
            "cart_actions_in_main": cart_actions_in_main,
            "has_password_form_in_main": password_form_in_main,
            "search_param_names": search_param_names,
            "search_prefill_values": search_prefill_values}


def _extract_variant_controls(doc: Document) -> Dict[str, Any]:
    selects = 0
    swatches = 0
    for select in doc.find_all("select"):
        name = (select.get("name") or select.get("id") or "").lower()
        if any(token in name for token in ("size", "colour", "color", "variant",
                                           "option", "style", "width")):
            selects += 1
    for node in doc.find_all(attrs={"data-variant": None}):
        swatches += 1
    for node in doc.find_all(attrs={"class": "swatch"}):
        swatches += 1
    return {"variant_selects": selects, "variant_swatches": swatches}


#: A last-updated date stated in visible copy, in any of the languages the
#: lexicon covers. This is a *human-readable* freshness signal: real, checkable
#: and often the only one a site publishes. It is not machine-readable - no
#: `dateModified`, no `<time datetime>`, no `Last-Modified` - and the audit
#: reports the two separately rather than declaring a visibly dated page
#: undated, which is a claim the page itself refutes.
VISIBLE_UPDATED_RE = re.compile(
    r"(?i)\b(?P<phrase>last\s+updated|updated\s+on|last\s+modified|last\s+revised|"
    r"published\s+on|reviewed\s+on|effective\s+(?:date|from)|"
    r"[uú]ltima\s+actualizaci[oó]n|actualizado\s+el|mis[e]?\s+[aà]\s+jour|"
    r"zuletzt\s+aktualisiert|[uú]ltima\s+atualiza[cç][aã]o|"
    r"ultimo\s+aggiornamento|laatst\s+bijgewerkt)\b"
    r"[^\n.]{0,40}?(?P<date>\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
    r"|\d{1,2}\s+[A-Za-zÀ-ɏ]{3,12},?\s+\d{4}"
    r"|[A-Za-zÀ-ɏ]{3,12}\s+\d{1,2},?\s+\d{4})")


def _extract_visible_updated(text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for match in VISIBLE_UPDATED_RE.finditer(text or ""):
        out.append({"phrase": util.collapse_ws(match.group("phrase")),
                    "date": util.collapse_ws(match.group("date")),
                    "text": util.truncate(util.collapse_ws(match.group(0)), 120)})
        if len(out) >= 5:
            break
    return out


def _extract_dates(doc: Document, text: str) -> Dict[str, Any]:
    time_nodes = []
    for node in doc.find_all("time"):
        time_nodes.append({"datetime": node.get("datetime"),
                           "text": util.truncate(node.get_text(" "), 60)})
    copyright_years = [int(m.group(1)) for m in COPYRIGHT_YEAR_RE.finditer(text)]
    return {"time_elements": time_nodes,
            "visible_updated": _extract_visible_updated(text),
            "copyright_years": sorted(set(copyright_years)),
            "years_mentioned": sorted({int(m.group(0)) for m in YEAR_RE.finditer(text)})[-8:]}


def parse_amount(raw: str) -> Optional[float]:
    """Parse a money amount under either grouping convention.

    ``1,234.56`` (en), ``1.234,56`` (es/de/it/pt/nl) and ``1 234,56`` (fr) are
    the same number. Assuming the English one turns "EUR 5.499" into 5.499 and
    makes every European storefront look like it contradicts its own structured
    data - a high-severity false positive that fires because of the locale.
    """
    cleaned = re.sub(r"[\s\u00a0\u202f\u2009]", "", raw or "")
    if not cleaned:
        return None
    last_dot, last_comma = cleaned.rfind("."), cleaned.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        # Both present: the rightmost one is the decimal separator.
        decimal_sep, group_sep = (".", ",") if last_dot > last_comma else (",", ".")
        cleaned = cleaned.replace(group_sep, "").replace(decimal_sep, ".")
    elif last_dot >= 0 or last_comma >= 0:
        sep = "." if last_dot >= 0 else ","
        parts = cleaned.split(sep)
        tail = parts[-1]
        # One separator with exactly three trailing digits is grouping:
        # "5.499" is five thousand four hundred and ninety-nine, not 5.499.
        if len(parts) > 2 or (len(tail) == 3 and tail.isdigit()):
            cleaned = cleaned.replace(sep, "")
        else:
            cleaned = cleaned.replace(sep, ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_prices(text: str) -> List[dict]:
    out = []
    for match in PRICE_RE.finditer(text):
        currency, amount = price_match_parts(match)
        value = parse_amount(amount)
        if value is None:
            continue
        out.append({"raw": util.collapse_ws(match.group(0)), "value": value,
                    "currency": currency.upper(),
                    # Which branch matched, so a caller that must state an
                    # exact value can say how sure the reading is instead of
                    # asserting a number it inferred from an ambiguous token.
                    "marker": price_match_kind(match),
                    "confidence": price_confidence(match)})
        if len(out) >= 40:
            break
    return out


def _extract_breadcrumbs(doc: Document) -> Dict[str, Any]:
    found = False
    depth = 0
    for nav in doc.find_all("nav"):
        label = (nav.get("aria-label") or "").lower()
        if "breadcrumb" in label or "breadcrumb" in (nav.get("class") or "").lower():
            found = True
            depth = max(depth, len(nav.find_all("a")))
    for node in doc.find_all(attrs={"class": "breadcrumb"}):
        found = True
        depth = max(depth, len(node.find_all("a")))
    for node in doc.find_all(attrs={"itemtype": None}):
        if "BreadcrumbList" in (node.get("itemtype") or ""):
            found = True
    return {"present": found, "link_depth": depth}


def _detail_faq_blocks(doc: Document) -> int:
    return len([d for d in doc.find_all("details") if d.find("summary")])


def extract_page(response, html: Optional[str] = None) -> Dict[str, Any]:
    """Build the fact bag for one HTML response."""
    html = response.body if html is None else html
    doc = parse_html(html)
    base = response.final_url or response.requested_url

    named_meta, prop_meta, http_equiv = _meta_maps(doc)
    html_node = doc.find("html")
    body = doc.body

    text = util.collapse_ws(body.get_text(" "))
    block_text = body.get_block_text()
    main_node = doc.find("main") or doc.find("article") or body
    main_text = util.collapse_ws(main_node.get_text(" "))

    canonical_node = None
    alternates: List[dict] = []
    feeds: List[dict] = []
    for link in doc.find_all("link"):
        rel = (link.get("rel") or "").lower()
        href = link.get("href")
        if "canonical" in rel and href and canonical_node is None:
            canonical_node = util.normalize_url(href, base)
        if "alternate" in rel and href:
            link_type = (link.get("type") or "").lower()
            if "rss" in link_type or "atom" in link_type:
                feeds.append({"url": util.normalize_url(href, base), "type": link_type})
            elif link.has_attr("hreflang"):
                alternates.append({"hreflang": link.get("hreflang"),
                                   "url": util.normalize_url(href, base)})

    jsonld = _extract_jsonld(doc)
    jsonld_nodes = [n for block in jsonld if block["parse_ok"]
                    for n in flatten_jsonld(block["data"])]
    jsonld_types = sorted({t for node in jsonld_nodes for t in node_types(node)})

    links = _extract_links(doc, base)
    scripts = _extract_scripts(doc, html)
    noscript_nodes = doc.find_all("noscript")
    noscript_text = util.collapse_ws(" ".join(n.get_text(" ", skip_non_content=False)
                                              for n in noscript_nodes))

    availability_hits = {key: lexicon.mentions(key, text) for key in AVAILABILITY_CONCEPTS}
    availability_hits["limited"] = bool(LIMITED_STOCK_RE.search(text))

    headings = _extract_headings(doc)
    h1s = [h["text"] for h in headings if h["level"] == 1]
    title_node = doc.find("title")

    external_links = links["external"]
    sameas_like = [link["url"] for link in external_links
                   if any(host in link["url"] for host in SOCIAL_HOSTS)
                   and not SHARE_INTENT_RE.search(link["url"])]

    facts: Dict[str, Any] = {
        # ---- transport ---------------------------------------------------
        "url": util.normalize_url(response.requested_url) or response.requested_url,
        "final_url": base,
        "status": response.status,
        "content_type": response.content_type,
        "bytes": response.body_bytes,
        "elapsed_ms": response.elapsed_ms,
        "redirects": [{"status": s, "location": loc} for s, loc in response.redirects],
        "headers": {k: v for k, v in response.headers.items() if k in (
            "x-robots-tag", "last-modified", "etag", "cache-control", "expires",
            "content-language", "link", "vary", "age", "server", "date",
            "content-security-policy", "strict-transport-security")},
        # ---- document ----------------------------------------------------
        "lang": (html_node.get("lang") if html_node else "") or named_meta.get("language", ""),
        "doctype": doc.doctype,
        "parse_errors": doc.parse_errors,
        # <title> lives inside <head>, which get_text() skips as non-content,
        # so it has to be read with skip_non_content disabled.
        "title": util.truncate(
            (title_node.get_text(" ", skip_non_content=False) if title_node else ""), 300),
        "meta_description": named_meta.get("description", ""),
        "meta_robots": named_meta.get("robots", ""),
        "meta_googlebot": named_meta.get("googlebot", ""),
        "meta_charset": http_equiv.get("content-type", ""),
        "viewport": named_meta.get("viewport", ""),
        "canonical": canonical_node,
        "hreflang_alternates": alternates,
        "feeds": feeds,
        "open_graph": {k: v for k, v in prop_meta.items() if k.startswith("og:")},
        "twitter_card": {k: v for k, v in named_meta.items() if k.startswith("twitter:")},
        # ---- structure ---------------------------------------------------
        "headings": headings,
        "h1_count": len(h1s),
        "h1_texts": h1s[:5],
        # What the page's own controls are called, so a heading that merely
        # repeats one of them is never mistaken for the name of a thing.
        "control_labels": _extract_control_labels(doc),
        "heading_levels": [h["level"] for h in headings],
        "semantic_landmarks": {
            "main": doc.find("main") is not None,
            "nav": doc.find("nav") is not None,
            "header": doc.find("header") is not None,
            "footer": doc.find("footer") is not None,
            "article": doc.find("article") is not None,
            "section": doc.find("section") is not None,
        },
        "breadcrumbs": _extract_breadcrumbs(doc),
        # ---- structured data ---------------------------------------------
        "jsonld_blocks": [{k: v for k, v in b.items() if k != "data"} for b in jsonld],
        "jsonld_nodes": jsonld_nodes,
        "jsonld_types": jsonld_types,
        "jsonld_invalid_count": len([b for b in jsonld if not b["parse_ok"]]),
        "microdata": _extract_microdata(doc),
        "rdfa_typeof_count": len(doc.find_all(attrs={"typeof": None})),
        # ---- content -----------------------------------------------------
        "text": text[:40000],
        # The <main>/<article> region, kept as text rather than only as a word
        # count. A quotation offered as evidence should come from the page's
        # content, not from the skip-link and the navigation that precede it in
        # document order - and only the content region can distinguish them.
        "main_text": main_text[:20000],
        "text_word_count": util.word_count(text),
        "main_text_word_count": util.word_count(main_text),
        "block_text_excerpt": util.truncate(block_text, 1200),
        "html_bytes": len(html),
        "text_to_html_ratio": round(len(text) / max(1, len(html)), 4),
        "tables": _extract_tables(doc),
        "definition_spec_lists": _extract_definition_specs(doc),
        "definition_terms": _extract_definition_terms(doc),
        "visible_attribute_pairs": _extract_visible_attribute_pairs(block_text),
        "images": _extract_images(doc),
        "links": {
            "internal_count": len(links["internal"]),
            "external_count": len(external_links),
            "nofollow_count": links["nofollow_count"],
            "internal": links["internal"][:400],
            "external": external_links[:120],
            "sameas_like": util.dedupe(sameas_like)[:40],
        },
        # ---- rendering ---------------------------------------------------
        "scripts": scripts,
        "noscript_present": bool(noscript_nodes),
        "noscript_text": util.truncate(noscript_text, 400),
        # ---- commerce signals --------------------------------------------
        "prices_in_text": _extract_prices(text),
        "availability_text": availability_hits,
        "forms": _extract_forms(doc),
        "variants": _extract_variant_controls(doc),
        "dates": _extract_dates(doc, text),
        "mentions": {
            "shipping": lexicon.mentions("shipping", text),
            "returns": lexicon.mentions("returns", text),
            "warranty": bool(WARRANTY_RE.search(text)),
            "reviews": lexicon.mentions("reviews", text),
            "faq": lexicon.mentions("faq", text),
            "compare": lexicon.mentions("compare", text),
            "add_to_cart": lexicon.mentions("add_to_cart", text),
            "payment": lexicon.mentions("payment", text),
        },
        "language_supported": lexicon.language_supported(
            (html_node.get("lang") if html_node else "") or named_meta.get("language", "")),
        "question_headings": [h["text"] for h in headings if QUESTION_RE.match(h["text"] or "")][:12],
        "details_faq_blocks": _detail_faq_blocks(doc),
        "html_excerpt": html[:4000],
    }
    return facts


#: Declared page-level types that identify a catalogue entry, lower-cased and
#: bare of any vocabulary prefix. ``product.item`` is the Open Graph spelling.
_PRODUCT_TYPES = frozenset({"product", "productgroup", "individualproduct",
                            "vehicle", "product.item", "product.group"})

#: ...and the ones that identify a listing of them.
_CATEGORY_TYPES = frozenset({"collectionpage", "itemlist", "offercatalog"})

#: A declared search results document. It is a set of things, like a listing,
#: but it is not a catalogue page the site publishes: it owes no filters, no
#: sort controls, no breadcrumb and no Product markup, so it is its own type
#: rather than a `category`, which carries all of those obligations.
_SEARCH_PAGE_TYPES = frozenset({"searchresultspage"})


def _declared_types(facts: dict) -> set:
    """Page-level types the document declares outside JSON-LD.

    schema.org microdata (``itemtype``), Open Graph ``og:type`` and the
    Twitter card type. All three are statements the page makes about itself,
    so they carry the same authority as a JSON-LD ``@type`` - they are simply
    the channels a site that predates, or ignores, JSON-LD tends to use.
    """
    declared = set(microdata_types(facts))
    for value in ((facts.get("open_graph") or {}).get("og:type"),
                  (facts.get("twitter_card") or {}).get("twitter:card")):
        if isinstance(value, str) and value.strip():
            declared.add(value.strip().lower())
    declared.discard("")
    return declared


#: Paths that are nothing but a locale: a country segment, optionally followed
#: by a language segment, and then the end of the path. `global` and `www` are
#: included because large multi-market sites use them as the market-neutral
#: equivalent. Anything with a path after the locale (`/in/en/kitchen/`) is not
#: matched, so this can only ever reclassify a front door.
_LOCALE_ROOT_RE = re.compile(
    r"^/(?:[a-z]{2}|global|int|intl)"          # country / market segment
    r"(?:[-_][a-z]{2})?"                       # or an en-gb / en_GB spelling
    r"(?:/[a-z]{2}(?:[-_][a-z]{2})?)?"         # optional language segment
    r"/?$", re.I)


#: Page types that are emphatically *not* an individual product detail page.
#: Product-specific rules and the answerability engine both read this, so a
#: page classified as any of them can never be sampled as a product.
NON_PRODUCT_PAGE_TYPES = frozenset({
    "home", "category", "promotional", "program", "support", "contact",
    "policy", "faq", "about", "article", "search", "tool", "error", "non_html",
    "reference", "account",
})

#: Page types that are not content documents of their own and so never enter
#: a content population: a search endpoint, a navigation/reference address
#: that serves another page's document (an alias), and an account/auth
#: endpoint. Every funnel that samples "content" reads this set.
NON_CONTENT_PAGE_TYPES = frozenset({
    "search", "reference", "account", "tool", "error", "non_html",
})

#: Page types that present a *set* of products: a catalogue index, a category,
#: a collection. The listing-only rules - filtering, sorting, comparison
#: support - are about affordances only a set needs, so this is the type set
#: they are allowed to sample.
LISTING_PAGE_TYPES = frozenset({"category"})

#: And its complement, stated rather than implied, for the same reason
#: `NON_PRODUCT_PAGE_TYPES` is: an invariant nobody can read off a positive
#: filter is an invariant nobody checks. A product page asked why it has no
#: sort control is the listing-side twin of a promotions hub audited as a
#: product, and it reached the report the same way - through a rule that
#: decided for itself what a listing was.
NON_LISTING_PAGE_TYPES = frozenset({
    "product", "home", "promotional", "program", "support", "contact",
    "policy", "faq", "about", "article", "search", "tool", "error",
    "non_html", "other", "reference", "account",
})


def _brand_token(url: str) -> str:
    """The registrable name of the site, e.g. `acme` for www.acme.com."""
    host = util.registrable_host(url) or ""
    return host.split(".")[0].lower() if host else ""


#: Words that, in a page's own title or H1, say it is a place to *do*
#: something rather than an item to buy: a planner, a configurator, a hub, a
#: guide. Used only to veto the content-signal branch - an explicit product URL
#: or a declared Product type still wins, so a product genuinely called "Design
#: Guide Chair" is unaffected.
_NOT_AN_ITEM_HEADING = (
    "planner", "planners", "planning", "configurator", "configure",
    "design tool", "designer", "builder", "build your", "customiser",
    "customizer", "calculator", "quiz", "finder", "wizard", "explore",
    "inspiration", "ideas", "how to", "guide", "services", "workshop",
    "book an appointment", "appointment", "showroom", "browse", "shop all",
    "all products", "our range", "collections", "offers", "deals",
    "membership", "rewards", "newsletter", "careers",
)


def _heading_says_not_an_item(url: str, facts: dict) -> bool:
    """Does the page's own title or H1 say it is not an individual item?"""
    haystack = lexicon.fold(" ".join([
        str(facts.get("title") or ""),
        " ".join(facts.get("h1_texts") or []),
    ]))
    return any(word in haystack for word in _NOT_AN_ITEM_HEADING)


#: Document types whose whole meaning is "this *page* is about several
#: things". A page declaring one of them is a listing however many product
#: names, prices or specifications it also carries: they are statements about
#: the document, not data structures that happen to appear inside it.
_COLLECTION_PAGE_TYPES = {"collectionpage", "offercatalog", "productcollection"}

#: `ItemList` is different in kind: it is a container, and a product detail
#: page legitimately carries one for its related items, its images or its
#: reviews. It is read as evidence of plurality, but as the overridable kind.
_COLLECTION_CONTAINER_TYPES = {"itemlist"}

#: schema.org properties whose values are *subordinate* products: a size of
#: this shoe, a similar shoe, a spare part for it. Products found there are
#: not other subjects of the page, so counting them is how a correctly marked
#: up variant family - one ProductGroup and its two sizes - came to look like
#: three products and disqualified its own detail page.
_SUBORDINATE_PRODUCT_PROPS = frozenset({
    "hasvariant", "isvariantof", "issimilarto", "isrelatedto",
    "isaccessoryorsparepartfor", "isconsumablefor", "ispartof", "haspart",
    "model", "itemoffered", "additionalproperty", "aboutproduct",
})

#: Properties that describe a declared product entity rather than merely
#: naming it. Two of them make a declaration a description - the difference
#: between `{"@type":"Product","name":"A"}`, which any template can emit
#: anywhere, and a page stating what the thing is.
_ENTITY_DETAIL_PROPS = frozenset({
    "sku", "gtin", "gtin8", "gtin12", "gtin13", "gtin14", "mpn", "productid",
    "brand", "offers", "aggregaterating", "review", "image", "description",
    "color", "colour", "material", "size", "additionalproperty", "category",
    "weight", "depth", "width", "height", "model", "manufacturer", "audience",
})

#: URL markers that name an *item*, as opposed to a section. Each must be
#: followed by a slug, because `/products/` is a listing and
#: `/products/velocity-x9` is one shoe - the same pattern matched both, so a
#: catalogue index classified as an individual product.
_ITEM_URL_RE = re.compile(
    r"/(?:products?|p|item|dp|pd|sku|productos?|produits?|produkte?|produtos?|"
    r"prodott[oi])/[^/]+(?:/|$)|-p-\d+|/product-detail", re.I)

#: How many distinct prices a page may show and still be about one thing. A
#: product page shows a price, sometimes a was-price and a member price; a
#: grid shows one per tile.
_MAX_PRICES_FOR_ONE_ITEM = 4

#: Sibling links in the content region above which the page is presenting a
#: set. Counted only when the link text itself carries a price: a product page
#: links to related items too - often a dozen of them - so the bare count of
#: item-shaped links says nothing, and reading it as plurality turned a Spanish
#: product page with a related-items rail into a category page.
_SIBLING_LINKS_FOR_A_SET = 5

#: Below this, a page has no content to classify from: a render shell, an
#: empty template, a page whose body is a mount point and six script tags.
_SHELL_WORD_COUNT = 25

#: Evidence about *one item* rather than about the page. A heading, a price and
#: a URL are page-scoped: a catalogue index has all three. A specification
#: block, a buy control in the content region, variant options and a declared
#: single entity are item-scoped - a page presenting a set does not publish the
#: dimensions of one of them, or a control that puts one of them in a basket.
#: Only item-scoped evidence can settle a page that reads as both.
_ITEM_SCOPED_FAMILIES = ("identity:", "purchase:", "specification:",
                         "variants:", "offer:", "entity:")


def _distinct_prices(values) -> set:
    out = set()
    for item in values or []:
        if isinstance(item, dict):
            out.add(str(item.get("value", item.get("raw", ""))))
        else:
            out.add(str(item))
    return {v for v in out if v}


def _declared_type_names(facts: dict) -> set:
    """Every type this page declares about itself, in any vocabulary.

    `microdata` is a list of item records, not a mapping - reading it as one
    raised inside the classifier, which the orchestrator then reported as a
    failed specialist rather than as a bug here. It is read through
    :func:`microdata_types`, the one accessor that knows the field's shape.
    """
    names = {str(t).lower() for t in (facts.get("jsonld_types") or [])}
    names.update(microdata_types(facts))
    og_type = str(((facts.get("open_graph") or {}).get("og:type") or "")).lower()
    if og_type:
        names.add(og_type)
    twitter = str(((facts.get("twitter_card") or {}).get("twitter:card") or "")).lower()
    if twitter:
        names.add(twitter)
    return names


def _content_links(facts: dict) -> list:
    """Internal links outside the navigation and the footer."""
    links = (facts.get("links") or {}).get("internal") or []
    return [l for l in links if not l.get("in_nav") and not l.get("in_footer")]


_PRODUCT_NODE_TYPES = {"product", "productgroup", "individualproduct",
                       "vehicle", "book", "softwareapplication"}

#: Separators after which a variant name qualifies the product it varies:
#: "Velocity X9, UK 8", "Velocity X9 - Slate blue", "Velocity X9 (2026)".
_VARIANT_SUFFIX_RE = re.compile(r"^\s*[,\-–—(\[/|:]")


def _is_product_node(node: dict) -> bool:
    return bool({str(t).lower() for t in _node_types_of(node)} & _PRODUCT_NODE_TYPES)


def _node_identity(node: dict) -> str:
    """A stable-enough key for one JSON-LD node: its @id, else its name."""
    for key in ("@id", "id"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return "@" + value.strip().lower()
    name = node.get("name")
    if isinstance(name, str) and name.strip():
        return util.collapse_ws(name).lower()
    return ""


def _subordinate_product_ids(facts: dict) -> set:
    """Identities of product nodes reached through a subordinate property.

    `jsonld_nodes` is flattened, so a ProductGroup's two sizes arrive as two
    more Product nodes beside their parent. Reading the parents' properties is
    what tells a variant apart from a second subject.
    """
    subordinate = set()
    for node in facts.get("jsonld_nodes") or []:
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if str(key).lower().lstrip("@") not in _SUBORDINATE_PRODUCT_PROPS:
                continue
            for child in (value if isinstance(value, list) else [value]):
                if isinstance(child, dict):
                    identity = _node_identity(child)
                    if identity:
                        subordinate.add(identity)
    return subordinate


def _product_subjects(facts: dict) -> List[dict]:
    """The distinct product entities this page is *about*.

    Not the count of product-typed nodes: a page marked up properly carries
    more of those than it has subjects. Variants declared under `hasVariant`,
    related items under `isRelatedTo` and spare parts under
    `isAccessoryOrSparePartFor` all describe the same subject, and a variant
    whose name qualifies its parent's ("Velocity X9, UK 8") is that parent.
    """
    subordinate = _subordinate_product_ids(facts)
    subjects: List[dict] = []
    seen_names: List[str] = []
    for node in facts.get("jsonld_nodes") or []:
        if not isinstance(node, dict) or not _is_product_node(node):
            continue
        identity = _node_identity(node)
        if identity and identity in subordinate:
            continue
        raw_name = node.get("name")
        name = util.collapse_ws(raw_name).lower() if isinstance(raw_name, str) else ""
        if name:
            merged = False
            for index, kept in enumerate(seen_names):
                if not kept:
                    continue
                short, long = sorted((kept, name), key=len)
                if long == short or (long.startswith(short)
                                     and _VARIANT_SUFFIX_RE.match(long[len(short):])):
                    # Same subject, described twice (a ProductGroup and its
                    # detail node) or once per variant. Keep the richer node.
                    if len(node) > len(subjects[index]):
                        subjects[index] = node
                        seen_names[index] = short
                    merged = True
                    break
            if merged:
                continue
        subjects.append(node)
        seen_names.append(name)
    return subjects


def product_subjects(facts: dict) -> List[dict]:
    """Public name for :func:`_product_subjects`: the entities a page is *about*.

    Consumers that need a product's identity must read it from a subject node
    rather than from the first product-typed node in document order - on a
    detail page with a related-items rail, that first node is frequently a
    *different* product.
    """
    return _product_subjects(facts or {})


def _entity_is_described(node: dict) -> bool:
    """Does the declaration describe the thing, or only name it?"""
    present = {str(k).lower() for k in node.keys()}
    return len(present & _ENTITY_DETAIL_PROPS) >= 2


def _node_types_of(node: dict) -> list:
    value = node.get("@type") or node.get("type") or []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _offer_with_a_price(node: dict) -> bool:
    """An Offer carrying a price, on the entity this page is about."""
    offers = node.get("offers")
    for offer in (offers if isinstance(offers, list) else [offers]):
        if isinstance(offer, dict) and (offer.get("price")
                                        or offer.get("lowPrice")
                                        or offer.get("priceSpecification")):
            return True
    return False


def _names_the_page(node: dict, facts: dict) -> bool:
    """Does the declared entity's name match what the page calls itself?

    The strongest statement of singular identity available without a network:
    the markup names one entity and the visible heading names the same one.
    A listing's markup never does this - its heading names the section.
    """
    name = node.get("name")
    if not isinstance(name, str) or not name.strip():
        return False
    name = util.collapse_ws(name).lower()
    if len(name) < 3:
        return False
    for heading in [util.collapse_ws(h).lower() for h in (facts.get("h1_texts") or [])] \
            + [util.collapse_ws(str(facts.get("title") or "")).lower()]:
        if heading and (name in heading or heading in name):
            return True
    return False


def _listing_controls(facts: dict) -> str:
    """Sort and filter affordances that a *set* needs and one item does not.

    A product page's size picker is counted as a filter control by the
    extractor - the engagement rules want it counted that way - so the same
    `<select name="size">` arrives here as both a variant control and a
    filter. Netting the two off is what stops a shoe with two sizes reading as
    a filtered catalogue.
    """
    forms = facts.get("forms") or {}
    variants = facts.get("variants") or {}
    sort = forms.get("sort_controls")
    if sort is None:
        sort = 1 if forms.get("has_sort_controls") or forms.get("has_sort_control") else 0
    filters = forms.get("filter_controls")
    if filters is None:
        filters = 1 if forms.get("has_filter_controls") else 0
    explained = int(variants.get("variant_selects") or 0)
    if sort:
        return "sort controls"
    if filters > explained:
        return "filter controls beyond the page's own options"
    return ""


def _content_is_a_shell(facts: dict, verdict: Optional[dict] = None) -> bool:
    """Is there any content here to classify from at all?

    A JavaScript-rendered product page ships a mount point and six script
    tags. It has no price, no heading and no markup - not because it is not a
    product page but because it is empty, which is the defect the crawl and
    render rules exist to report. Reading its emptiness as "not a product"
    would silence the finding that matters most on such a site.

    "Empty" has to mean empty, though. A word count alone made a short page a
    shell, and a short page is not a silent one: a four-item listing with a
    heading and five prices said plenty, and fell back to its URL anyway. So a
    page is a shell only when it is short *and* produced no content signal -
    the URL excepted, since the URL is what the fallback defers to.
    """
    words = facts.get("main_text_word_count")
    if words is None:
        words = facts.get("text_word_count")
    if words is None or int(words) >= _SHELL_WORD_COUNT:
        return False
    if verdict is None:
        return True
    said_something = [s for s in verdict.get("singular") or []
                      if not s.startswith("url:")] + list(verdict.get("plural") or [])
    return not said_something


def product_evidence(url: str, facts: Optional[dict]) -> Dict[str, Any]:
    """Is this page about **one** purchasable thing, or several, or neither?

    This is the whole product decision, in one place, and it is written around
    cardinality rather than vocabulary. Every false positive this auditor has
    produced came from a signal that says "commerce happens here" - a price, a
    cart control, the word shop or buy in a URL, product-shaped markup - being
    read as "this page is one product". Those signals are all true of a
    catalogue index, a promotions hub, a gift-card page and a membership
    programme.

    Three questions are asked separately.

    * **Does the page declare itself a listing?** `CollectionPage`,
      `SearchResultsPage`, `OfferCatalog`. That is a statement about the
      document and nothing overrides it.
    * **Does the page present a set?** Two or more product *subjects*, a grid
      of prices, sort or filter controls a single item would not need,
      pagination, priced sibling links. Each is strong evidence and none is a
      declaration, so a page that names one entity and shows its heading -
      a detail page with a related-items rail - is allowed to override them.
    * **Is the page about one item?** *Anchors* fix the identity of that item:
      one declared product subject, an item-shaped URL, a purchase affordance
      inside the content. *Corroborators* are consistent with an item but
      common elsewhere: a price, a specification block, a heading, variant
      controls, a breadcrumb, a priced offer. At least one anchor and at least
      two families in total are required, so no isolated signal - not a price,
      not an `h1`, not `/shop/` in the URL, not a bare `Product` token -
      decides on its own, and two observations of the same thing cannot
      masquerade as two signals.

    Returns ``{"verdict", "anchors", "singular", "plural"}`` where verdict is
    ``individual`` | ``plural`` | ``uncertain``. Uncertain is *not* a product:
    when the evidence does not settle it, the conservative answer is the one
    that does not invent a product page.
    """
    facts = facts or {}
    declared = _declared_type_names(facts)
    prices = _distinct_prices(facts.get("prices_in_text"))
    forms = facts.get("forms") or {}
    variants = facts.get("variants") or {}
    subjects = _product_subjects(facts)
    only = subjects[0] if len(subjects) == 1 else None
    content_links = _content_links(facts)

    declares_listing: List[str] = []
    if declared & _COLLECTION_PAGE_TYPES:
        declares_listing.append("declares a collection document type")

    plural: List[str] = list(declares_listing)
    if len(subjects) >= 2:
        plural.append(f"{len(subjects)} distinct product entities in markup")
    if declared & _COLLECTION_CONTAINER_TYPES:
        plural.append("carries an ItemList")
    if len(prices) > _MAX_PRICES_FOR_ONE_ITEM:
        plural.append(f"{len(prices)} distinct prices")
    controls = _listing_controls(facts)
    if controls:
        plural.append(controls)
    if any(str(l.get("rel", "")).lower() in ("next", "prev", "previous")
           for l in ((facts.get("links") or {}).get("internal") or [])):
        plural.append("pagination links")
    priced_siblings = [l for l in content_links
                       if PRICE_RE.search(str(l.get("text") or ""))]
    if len(priced_siblings) >= _SIBLING_LINKS_FOR_A_SET:
        plural.append(f"{len(priced_siblings)} priced sibling links in the content")
    # A purchase control in the content region fixes which item the page is
    # about - when there is one. A grid of them, one per tile, is a listing or
    # a search results page saying the opposite, and a boolean read both as an
    # anchor: that is how a search results page with a quick-add button on
    # every result became an individual product.
    cart_controls = forms.get("cart_actions_in_main")
    if cart_controls is None:                        # bundle predates the count
        cart_controls = 1 if forms.get("has_cart_action_in_main") else 0
    cart_controls = int(cart_controls or 0)
    if cart_controls >= _SIBLING_LINKS_FOR_A_SET:
        plural.append(f"{cart_controls} purchase controls in the content region, "
                      "one per item")

    # An anchor fixes *which* item the page is about. Without one, product-like
    # information is just information: a promotions hub, a membership page and
    # a comparison table all carry prices and attributes.
    anchors: List[str] = []
    if only is not None:
        anchors.append("identity: one product entity declared")
    elif not subjects and declared & _PRODUCT_TYPES:
        # Declared in microdata, Open Graph or a Twitter product card rather
        # than JSON-LD. A site that does not write Shopify-style URLs is no
        # more likely to write Shopify-style JSON-LD.
        anchors.append("identity: a declared product type")
    if _ITEM_URL_RE.search(util.url_path(url) or ""):
        anchors.append("url: an item slug rather than a section")
    if 1 <= cart_controls < _SIBLING_LINKS_FOR_A_SET:
        anchors.append("purchase: a cart affordance in the content region")

    corroborating: List[str] = []
    if only is not None and _offer_with_a_price(only):
        corroborating.append("offer: a priced Offer on that entity")
    if only is not None and _entity_is_described(only):
        corroborating.append("entity: the declaration describes the thing")
    if (facts.get("h1_count") or 0) == 1 and not _heading_says_not_an_item(url, facts):
        corroborating.append("heading: one heading, naming a thing")
    if prices and len(prices) <= 3 and _price_in_main_content(facts):
        corroborating.append("price: a small price set in the content region")
    if (facts.get("definition_spec_lists") or 0) or (facts.get("tables") or []) \
            or (facts.get("visible_attribute_pairs") or []):
        corroborating.append("specification: an attribute block")
    if variants.get("variant_selects") or variants.get("variant_swatches"):
        corroborating.append("variants: per-item option controls")
    if (facts.get("breadcrumbs") or {}).get("link_depth", 0) >= 2:
        corroborating.append("breadcrumb: a trail ending at this page")
    if "has_cart_action_in_main" not in forms and forms.get("has_cart_action"):
        # A bundle written before the position of the cart control was
        # recorded. Read, because dropping it would silently reclassify old
        # bundles, but only ever as corroboration: on a storefront the header's
        # cart control is on every page, which is what made every page look
        # like a product in the first place.
        corroborating.append("purchase: a cart affordance somewhere on the page")

    singular = anchors + corroborating
    names_the_page = only is not None and _names_the_page(only, facts)
    is_individual = (bool(anchors) and len(singular) >= 2
                     and not _heading_says_not_an_item(url, facts))

    # `category` is a specific type too, and it carries obligations of its own:
    # a listing is asked why it has no filters, no sorting and no comparison
    # support. So being a listing has to be earned on the same terms as being a
    # product - a page is not promoted to either type merely because it shows
    # some of that type's signals.
    conflict = ""
    if declares_listing:
        # A statement about the document, in the document's own markup.
        verdict = "plural"
    elif plural and names_the_page:
        # The markup names one entity and the page's own heading repeats that
        # name. One thing said twice outranks the weaker plurality signals -
        # this is a detail page with a related-items rail.
        verdict = "individual" if is_individual else "uncertain"
    elif plural and anchors:
        # Both readings have support: something fixes the identity of a single
        # item *and* something says the page presents a set. A product detail
        # page whose related-items rail carries six prices looks like this, and
        # so does a catalogue index with one featured product.
        #
        # What separates them is *scope*. A heading, a price and a URL belong
        # to the page and fit either reading. A specification block, a buy
        # control in the content, variant options and a declared single entity
        # belong to one item: a page presenting a set does not carry the
        # dimensions of one of them, or a control that adds one of them to a
        # basket. So item-scoped evidence resolves the conflict, and
        # page-scoped evidence does not.
        item_scoped = [s for s in singular if s.startswith(_ITEM_SCOPED_FAMILIES)]
        if item_scoped and is_individual:
            verdict = "individual"
        else:
            # Nothing settles it, so neither type is assigned - and the page is
            # asked neither why its Product schema is missing nor why it has no
            # sort controls.
            conflict = ("both a singular anchor and a plural signal, and no "
                        "item-scoped evidence to settle it; neither type is "
                        "assigned")
            verdict = "uncertain"
    elif plural:
        verdict = "plural"
    elif is_individual:
        verdict = "individual"
    else:
        verdict = "uncertain"
    return {"verdict": verdict, "anchors": anchors, "singular": singular,
            "plural": plural, "conflict": conflict}


def _price_in_main_content(facts: dict) -> bool:
    """A price inside <main>, not one inherited from a header or a footer.

    A promotional strip in a site-wide header ("Free delivery over 2,000")
    put a price on every page of the site. Reading prices from the content
    region instead is what stops that being counted as evidence that the page
    is selling something.
    """
    main_text = facts.get("main_text")
    if main_text is None:                       # bundle predates the field
        return bool(facts.get("prices_in_text"))
    return bool(PRICE_RE.search(main_text))


def _an(word: str) -> str:
    return ("an " if word[:1] in "aeiou" else "a ") + word


def _query_pairs(url: str) -> List[Tuple[str, str]]:
    """``(name, value)`` pairs of a URL's query string, decoded and lower-cased."""
    query = url.split("?", 1)[1] if "?" in url else ""
    query = query.split("#", 1)[0]
    pairs: List[Tuple[str, str]] = []
    for raw in query.split("&"):
        if not raw:
            continue
        name, _, value = raw.partition("=")
        name = unquote_plus(name).strip().lower()
        value = util.collapse_ws(unquote_plus(value)).lower()
        if name:
            pairs.append((name, value))
    return pairs


def search_results_evidence(url: str, facts: Optional[dict]) -> str:
    """Why this URL is one of the page's *own* searches, or ``""``.

    Two statements the page makes about itself, matched against the URL it
    was fetched at, and neither involves a vocabulary or a URL shape:

    * the URL carries a query parameter under the same name the page's own
      search form submits (``?q=`` with ``<input name="q">``);
    * the page's search box is pre-filled with a value the URL's query
      carries - what a results page does with the query it just ran, and
      what no other page does with an arbitrary parameter.

    A search results page is a set of things, like a listing, but it is not a
    catalogue page the site publishes. Read as a listing it was asked why it
    had no filters and no breadcrumb; read as a product - a quick-add button
    on every result being a "purchase affordance in the content" - it was
    asked why it declared no Product markup. It is neither.
    """
    forms = (facts or {}).get("forms") or {}
    if not forms.get("has_site_search"):
        return ""
    pairs = _query_pairs(url)
    if not pairs:
        return ""
    names = {name for name, _ in pairs}
    params = {str(n).strip().lower() for n in (forms.get("search_param_names") or []) if n}
    if names & params:
        return "the URL carries the page's own search parameter"
    prefill = {str(v).strip().lower() for v in (forms.get("search_prefill_values") or []) if v}
    for _, value in pairs:
        if len(value) >= 2 and re.search(r"[^\W\d_]", value) and value in prefill:
            return "the page's search box is pre-filled with the URL's query value"
    return ""


#: Above this many words in the content region, a page that carries a
#: password field is a page *with* a login widget, not a login page.
_AUTH_FORM_WORD_CEILING = 200


def _content_is_an_auth_form(facts: dict) -> bool:
    forms = facts.get("forms") or {}
    if not forms.get("has_password_form_in_main"):
        return False
    if _product_subjects(facts):
        return False
    words = facts.get("main_text_word_count")
    if words is None:
        words = facts.get("text_word_count") or 0
    return int(words or 0) < _AUTH_FORM_WORD_CEILING


def _folded_title(facts: dict) -> str:
    return util.collapse_ws(lexicon.fold(str(facts.get("title") or ""))).strip().lower()


def _folded_headings(facts: dict) -> List[str]:
    return [util.collapse_ws(lexicon.fold(str(h or ""))).strip().lower()
            for h in (facts.get("h1_texts") or [])]


def _internal_link_set(facts: dict) -> set:
    return {str(l.get("url")) for l in ((facts.get("links") or {}).get("internal") or [])
            if isinstance(l, dict) and l.get("url")}


def same_document(a: dict, b: dict, *, declared: bool) -> bool:
    """Are these two fact-bags the same document fetched at two addresses?

    ``declared`` means one of them names the other as its canonical URL, or
    redirected onto it: the site has stated the relationship, so agreement
    on title and headings (and a similar length) is enough to confirm it.
    Without a declaration the bar is higher - the same title, the same
    headings, a similar length *and* nearly the same set of internal links -
    because two pages of one paginated listing share a title and a heading
    and are not the same document, and their product links are what tells
    them apart.
    """
    title_a, title_b = _folded_title(a), _folded_title(b)
    if not title_a or title_a != title_b:
        return False
    if _folded_headings(a) != _folded_headings(b):
        return False
    words_a = int(a.get("text_word_count") or 0)
    words_b = int(b.get("text_word_count") or 0)
    tolerance = 0.2 if declared else 0.15
    if abs(words_a - words_b) > max(40, tolerance * max(words_a, words_b)):
        return False
    if declared:
        return True
    links_a, links_b = _internal_link_set(a), _internal_link_set(b)
    if len(links_a) < 5 or len(links_b) < 5:
        return False
    return len(links_a & links_b) / len(links_a | links_b) >= 0.9


def classify_page(url: str, facts: Optional[dict] = None) -> str:
    """Best-effort page-type classification: URL shape first, then markup."""
    return classify_page_verbose(url, facts)["page_type"]


def classify_page_verbose(url: str, facts: Optional[dict] = None) -> Dict[str, Any]:
    """The classification and the reasons for it.

    A classifier that returns a bare label cannot be argued with, and every
    round of this auditor's page-type work began with someone reading a report
    and asking why a page was called a product. The answer is recorded here,
    travels in the evidence bundle and is printed beside each URL in the
    report's manifest, so a wrong classification can be read rather than
    reverse-engineered.

    Returns ``{"page_type", "decided_by", "anchors", "corroborating",
    "plural"}``; the three lists are empty unless the content branch ran.
    """
    from .config import (GENERIC_PAGE_TYPE_HINTS, NON_PRODUCT_PATH_HINTS,
                         PAGE_TYPE_HINTS, WEAK_CATEGORY_PATH_HINTS)

    def decided(page_type: str, why: str, verdict: Optional[dict] = None) -> Dict[str, Any]:
        verdict = verdict or {}
        return {"page_type": page_type, "decided_by": why,
                "anchors": list(verdict.get("anchors") or []),
                "corroborating": [s for s in (verdict.get("singular") or [])
                                  if s not in (verdict.get("anchors") or [])],
                "plural": list(verdict.get("plural") or [])}

    path = util.url_path(url).lower()
    query = url.split("?", 1)[1].lower() if "?" in url else ""
    probe = path + ("?" + query if query else "")

    if path in ("", "/") and not query:
        return decided("home", "the site root")

    # A locale root is a home page. `/in/en/`, `/ae/ar/`, `/ca/fr/`, `/global/en/`
    # are the front doors of a market, and they carry exactly what a front door
    # carries: prices, a cart control and variant swatches in promotional
    # modules. The content-signal branch below reads those affordances and
    # concluded "product", which is how a country home page came to be counted
    # among "16 identified product pages" and then cited as the product page
    # with no Product schema. Deciding this first costs nothing: a locale root
    # has no path left after the locale, so nothing else can be shadowed.
    if _LOCALE_ROOT_RE.match(path) and not query:
        return decided("home", "a locale root: the front door of one market")

    url_type = None
    url_reason = ""
    # Commerce *functions* are settled before any product heuristic. A buying
    # landing page, a gift-card hub or a payment-plan page carries prices, buy
    # vocabulary and a cart control, so every downstream signal reads it as a
    # product unless the negative signal takes precedence here.
    for page_type, patterns in NON_PRODUCT_PATH_HINTS:
        if any(re.search(pattern, probe) for pattern in patterns):
            url_type = page_type
            url_reason = f"the URL names {_an(page_type)} function"
            break

    if url_type is None:
        for page_type, patterns in PAGE_TYPE_HINTS:
            for pattern in patterns:
                if re.search(pattern, probe):
                    url_type = page_type
                    url_reason = f"the URL path is {_an(page_type)} route"
                    break
            if url_type:
                break

    # Deliberately *not* consulted: a URL shape that merely resembles a product
    # route. `/shop/x/y` fits `/us/shop/goto/account`, `/shop/help/returns` and
    # `/shop/goto/payment_plan` as well as it fits a real product, so it says
    # nothing on its own and the content branch below decides those pages.
    # Five storefront utility routes were classified as individual products by
    # that pattern alone (`config.WEAK_PRODUCT_PATH_HINTS` records the shape).

    # A brand-prefixed path segment - `/<brand>-family/`, `/<brand>-clubcard/`,
    # `/<brand>-membership/` - names a programme the brand runs, not a document
    # type. Consulted only when nothing specific matched, so `/<brand>-products/`
    # is still a product URL.
    if url_type is None:
        brand = _brand_token(url)
        if brand and len(brand) > 2:
            for segment in [seg for seg in path.split("/") if seg]:
                if segment.startswith(brand + "-") and len(segment) > len(brand) + 1:
                    url_type = "program"
                    url_reason = "a path segment names a programme the brand runs"
                    break

    # Generic hub words last, and only when nothing specific matched.
    if url_type is None:
        for page_type, patterns in GENERIC_PAGE_TYPE_HINTS:
            if any(re.search(pattern, probe) for pattern in patterns):
                url_type = page_type
                url_reason = f"a generic {page_type} word in the URL"
                break

    types = {t.lower() for t in (facts or {}).get("jsonld_types", [])}

    # A *page-level* declared type is a stronger signal than a URL segment.
    # `/p/` matches a product hint, but a documentation or blog URL containing
    # it - `/docs/p/getting-started` - is not a product, and the page says so
    # by declaring Article or TechArticle. These types describe the document
    # itself, so they override the URL guess.
    if types & {"faqpage", "qapage"}:
        return decided("faq", "the page declares itself an FAQPage")
    if types & {"blogposting", "newsarticle", "article", "techarticle",
                "howto", "scholarlyarticle", "report"}:
        return decided("article", "the page declares itself an article")
    # A search results page is settled before any listing or product reading,
    # from the page's own declaration or from what it says about the URL it
    # was fetched at (see `search_results_evidence`). It is a set of things,
    # but not a catalogue page: no listing obligation and no product rule
    # applies to it.
    if types & _SEARCH_PAGE_TYPES:
        return decided("search", "the page declares itself a SearchResultsPage")
    search_reason = search_results_evidence(url, facts) if facts else ""
    if search_reason:
        return decided("search", search_reason)
    # An account/auth endpoint: the page's content *is* a sign-in or
    # registration form. Two things establish that - a password field in the
    # content region and little else there - so a rich page that merely embeds
    # a login widget (a B2B product page gating its trade price) is not
    # relabelled on the strength of one input.
    if facts and _content_is_an_auth_form(facts):
        return decided("account", "a sign-in or registration form is the page's content")
    # Only the *page* types are decisive here. `ItemList` is a container, and a
    # product detail page legitimately carries one for its related items, its
    # images or its reviews - so it is weighed with the other evidence below
    # rather than ending the question, where it would have made a page's own
    # good markup the reason it stopped being a product page.
    if types & _COLLECTION_PAGE_TYPES:
        return decided("category", "the page declares a collection type")

    # An explicit non-product URL type wins outright. A listing whose ItemList
    # contains products is still a listing, and a support hub that quotes a
    # price is still a support hub.
    if url_type and url_type != "product":
        return decided(url_type, url_reason)

    # From here the only question left is "is this one product?", and it is
    # answered from evidence rather than from the URL. `product_evidence`
    # needs an anchor and two independent families, and is vetoed by any sign
    # that the page presents a set; an item-shaped URL is one anchor, never the
    # answer. With no facts - the frontier's pre-fetch prediction - the URL
    # prior is all there is, and it is documented as a prediction there.
    # A storefront section word - `/shop`, `/store` - is a prediction, never a
    # verdict. It is answered here only when there is nothing to read.
    weak_category = url_type is None and any(
        re.search(pattern, probe) for pattern in WEAK_CATEGORY_PATH_HINTS)

    if facts:
        verdict = product_evidence(url, facts)
        if verdict["verdict"] == "individual":
            return decided("product", "content evidence", verdict)
        if verdict["verdict"] == "plural":
            return decided("category", "the page presents a set", verdict)
        # Nothing settled it. One case is not uncertainty at all: a page with
        # an item URL and no content has nothing to weigh, and the site's own
        # routing is the only statement anyone has made about it. Calling that
        # "not a product" would hide exactly the sites this audit exists for -
        # a JavaScript-rendered catalogue whose HTML is a mount point.
        if url_type == "product" and _content_is_a_shell(facts, verdict):
            return decided("product", "an item URL and no content to weigh "
                                      "against it", verdict)
        return decided("other", verdict.get("conflict")
                       or "no signal identified an individual item", verdict)
    if url_type:
        return decided(url_type, url_reason + " (predicted before fetching)")
    if weak_category:
        return decided("category", "a storefront section word in the URL "
                                   "(predicted before fetching)")

    # Markup second, for sites with opaque URLs (/item.php?id=42).
    #
    # JSON-LD is not the only place a page declares its own type, and a site
    # that does not write Shopify-style URLs is no more likely to write
    # Shopify-style JSON-LD. schema.org microdata, Open Graph `og:type` and
    # Twitter product cards are declarations too, made by the page about
    # itself, and reading them is recall rather than guesswork. They are
    # consulted only after the URL failed to say anything, so a site with
    # recognisable URLs is classified exactly as it was before.
    if facts:
        declared = set(types) | _declared_types(facts)
        if declared & _PRODUCT_TYPES:
            return decided("product", "a declared product type")
        if declared & _SEARCH_PAGE_TYPES:
            return decided("search", "a declared search results type")
        if declared & _CATEGORY_TYPES:
            return decided("category", "a declared category type")

    return decided("other", "nothing in the URL or the markup says what this is")

