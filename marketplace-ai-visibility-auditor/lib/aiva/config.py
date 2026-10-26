"""Audit configuration - every knob that bounds runtime, politeness and scope.

Defaults are tuned so a *typical* marketplace site completes well inside the
5-minute budget stated in the Round 3 brief while remaining polite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class AuditConfig:
    # --- target -----------------------------------------------------------
    site: str = ""

    # --- politeness (never relax these without the site owner's consent) ---
    respect_robots: bool = True
    request_delay_s: float = 0.4          # min gap between requests to a host
    timeout_s: float = 12.0
    max_retries: int = 1
    max_bytes_per_response: int = 3_000_000
    user_agent: Optional[str] = None       # defaults to version.USER_AGENT

    # --- crawl budget -----------------------------------------------------
    max_pages: int = 40                    # hard cap on fetched HTML documents
    max_sitemap_urls: int = 2000           # URLs read out of sitemaps
    max_sitemaps: int = 12
    max_depth: int = 2                     # link-following depth from home
    total_time_budget_s: float = 240.0     # < 5 min brief requirement

    # how many of each classified page type to sample
    sample_targets: Dict[str, int] = field(default_factory=lambda: {
        "product": 12,
        "category": 5,
        "policy": 4,
        "about": 1,
        "contact": 1,
        "faq": 2,
        "search": 1,
        "article": 2,
        "promotional": 2,
        "program": 1,
        "tool": 1,
        "support": 2,
        "other": 4,
    })

    # --- off-site corroboration ------------------------------------------
    # Verifies that entity anchors the *site itself declares* (schema.org
    # sameAs, rel=me, Wikidata/Wikipedia links) actually resolve. This is
    # read-only, robots-respecting and never a search engine query.
    check_external: bool = True
    max_external_checks: int = 12

    # --- rendering --------------------------------------------------------
    # Optional headless comparison. Off unless Playwright is installed AND
    # --render is passed; static JS-dependency heuristics always run.
    use_headless_render: bool = False
    render_page_limit: int = 3
    #: Ceilings on the optional render pass. A browser is the slowest thing
    #: this audit can do, so it gets a per-page timeout *and* a whole-run
    #: budget: whichever runs out first stops the pass, the pages already
    #: rendered stay, and the bundle records that the budget was reached. The
    #: raw crawl has its own budget and is never affected by these.
    render_timeout_s: float = 15.0
    render_budget_s: float = 60.0
    #: Viewport used when (and only when) headless rendering runs. Recorded in
    #: the bundle so any claim about what a viewport shows names the viewport
    #: it was measured in; without rendering the audit makes no such claim.
    render_viewport_width: int = 1280
    render_viewport_height: int = 800

    # --- freshness thresholds (days) -------------------------------------
    stale_page_days: int = 365
    very_stale_page_days: int = 730
    stale_review_days: int = 540

    # --- offline / fixture mode ------------------------------------------
    offline_root: Optional[str] = None     # serve from a local directory
    #: Only ``--offline`` sets this. It exists so the bundled fixture sites can
    #: be served from loopback while every real audit keeps the private-address
    #: guard that stops a site's own markup from steering us at internal hosts.
    allow_private_hosts: bool = False

    # --- output -----------------------------------------------------------
    schema_variant: str = "full"           # full | handout | flat
    verbose: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    # Guardrail: a config that would be impolite or destructive is rejected
    # before a single request goes out.
    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.site:
            errors.append("config.site is required")
        if not self.respect_robots:
            errors.append(
                "respect_robots=False is not permitted: the marketplace is "
                "recommend-only and must honour robots.txt"
            )
        if self.request_delay_s < 0.1:
            errors.append("request_delay_s must be >= 0.1s (rate-abuse guard)")
        if self.max_pages > 200:
            errors.append("max_pages must be <= 200 (rate-abuse guard)")
        if self.total_time_budget_s > 600:
            errors.append("total_time_budget_s must be <= 600s")
        if self.schema_variant not in ("full", "handout", "flat"):
            errors.append("schema_variant must be one of full|handout|flat")
        errors.extend(self._user_agent_errors())
        return errors

    #: A custom User-Agent is legitimate - an operator auditing their own site
    #: may need one their edge allowlists. Impersonation is not: claiming to be
    #: a browser evades bot mitigation the site deliberately configured, and
    #: claiming to be GPTBot or Googlebot forges another party's identity and
    #: would make every crawlability finding a measurement of a lie. Both are
    #: refused before a socket opens.
    IMPERSONATION_TOKENS = (
        "mozilla", "chrome", "safari", "firefox", "edge/", "webkit", "opera",
        "gptbot", "oai-searchbot", "chatgpt-user", "claudebot", "claude-web",
        "perplexitybot", "googlebot", "google-extended", "bingbot", "applebot",
        "duckduckbot", "yandexbot", "baiduspider", "ccbot", "facebookexternalhit",
    )

    def _user_agent_errors(self) -> List[str]:
        agent = (self.user_agent or "").strip()
        if not agent:
            return []
        if len(agent) < 8:
            return ["user_agent must be at least 8 characters and identify the operator"]
        lowered = agent.lower()
        hits = [token for token in self.IMPERSONATION_TOKENS if token in lowered]
        if hits:
            return [f"user_agent must not impersonate a browser or a known crawler "
                    f"(matched: {', '.join(hits)}). Identify this auditor honestly; "
                    f"spoofing evades controls the site chose to configure."]
        return []


#: Paths that exist to run a transaction or a session, not to be cited: carts,
#: checkouts, accounts, logins, wishlists, admin. Excluding them from the
#: frontier keeps the crawl polite; rules also read this to tell a page that is
#: *meant* to be excluded from one that was excluded by mistake.
#: Paths that are never fetched: transactional surfaces that would act on a
#: shop, and authentication or administration surfaces the auditor has no
#: business touching. The brief's read-only constraint is enforced at the
#: method level too (GET/HEAD only, no credentials, no form submission); this
#: is the frontier-level half, so such a URL is never even queued.
#:
#: The platform-specific spellings matter as much as the generic ones: an
#: unseen site is as likely to be WordPress or WooCommerce as bespoke, and
#: `/wp-admin` is not covered by `admin`. Every alternative is anchored and
#: closed by `(/|$)`, so `/my-account-guide` and `/authors/jane` stay crawlable.
#: Anchored at any segment boundary, not only at the root. `^/` meant that on
#: every locale-prefixed or shop-prefixed site the exclusion silently stopped
#: working: `/us/shop/goto/account` and `/de/warenkorb` were crawled, counted
#: in the page sample, and - because they carry prices and buy vocabulary -
#: audited as individual products.
NON_CITABLE_PATH_RE = re.compile(
    r"(?:^|/)(cart|bag|basket|checkout|account|my-account|customer|login|logout|"
    r"signin|sign-in|register|signup|sign-up|orders?|order-status|"
    r"customer_authentication|wishlist|favou?rites|admin|"
    r"warenkorb|panier|carrito|carrinho|carrello|winkelwagen|koszyk|varukorg|"
    r"handlekurv|indkurv|sepet|kassa|kasse|caisse|mein-konto|mi-cuenta|"
    r"mon-compte|minha-conta|il-mio-account|"
    r"apps|wp-admin|wp-login\.php|administrator|auth|password)(?:/|$)", re.I)

#: Query parameters that make a GET act on a shop rather than describe it.
#: WooCommerce writes its add-to-cart and cart-removal links as ordinary GETs
#: on an otherwise citable product URL, so a path-only filter lets them through.
#: Two costs follow. The smaller one is politeness - the auditor sends no
#: cookies, so nothing actually mutates, but these are exactly the URLs the
#: brief names. The larger one is arithmetic: one document fetched three times
#: under three query strings is recorded as three product pages, and every
#: "N of M product pages" ratio in the report is computed from that count.
#: Deliberately narrow: every alternative below names a transaction, so a
#: legitimate page is never dropped. A broad catch-all such as ``action=``
#: would exclude ordinary pages and turn a false positive into a silent miss,
#: which is the worse trade for an auditor.
MUTATING_QUERY_RE = re.compile(
    r"(^|&)(add[-_]to[-_]cart|remove[-_]item|removed?[-_]from[-_]cart|"
    r"add[-_]to[-_]wishlist|remove[-_]from[-_]wishlist|update[-_]cart|"
    r"empty[-_]cart|undo[-_]item|add[-_]to[-_]compare|customer[-_]logout|"
    r"wc[-_]ajax|_wpnonce)=", re.I)

#: Page-type classification hints. Ordered - first match wins.
#:
#: URL shape is the most reliable signal, but it is also the most
#: English-shaped one, so the common Romance/Germanic spellings are included
#: alongside. A URL in a language not listed here still classifies correctly
#: via its schema.org types (see extract.classify_page), which is why the
#: markup fallback exists.

#: Commerce pages that are emphatically not an individual product: buying
#: landing pages for a family, gift-card hubs, financing and payment-plan
#: information, trade-in programmes. They carry prices, "buy" vocabulary and a
#: cart control, so every commerce heuristic downstream reads them as products
#: unless they are settled first. Consulted before PAGE_TYPE_HINTS.
NON_PRODUCT_PATH_HINTS = [
    # Buying landing pages and gift-card hubs. Anchored at the end of the path,
    # because the hint is about the *hub*: `/shop/buy-ipad` is a chooser and
    # `/shop/buy-ipad/ipad-air` is one item inside it. Unanchored, this pattern
    # swallowed everything underneath a buying route, and a live audit of a
    # storefront came back with no product pages at all - its machine-readable
    # product rules then scored full marks on a population of zero.
    #
    # They are `promotional`, not `category`. Both are non-product, but a
    # listing owes filtering, sorting and comparison support, and a gift-card
    # page or a model chooser owes none of those - being asked for them is the
    # listing-side twin of a promotions hub audited as a product.
    ("promotional", (
        r"/buy[-_][a-z0-9]+/?$", r"/buy[-_][a-z0-9]+[?#]",
        r"/gift[-_]?cards?/?$", r"/e?gift[-_]?cards?/?$",
        r"/tarjetas?[-_]regalo/?$", r"/cartes?[-_]cadeaux?/?$",
        r"/geschenkkarten?/?$",
    )),
    ("category", (
        r"/shop[-_]all", r"/all[-_]models",
    )),
    ("policy", (
        r"/payment[-_]?plans?", r"/financing", r"/finance[-_]options",
        r"/instal?lments?", r"/monthly[-_]payments?", r"/credit[-_]terms",
        r"/leasing", r"/trade[-_]?in", r"/pay[-_]monthly",
    )),
]

#: Storefront *section* words: `/shop`, `/store`, `/tienda`, `/boutique`. Each
#: usually names a catalogue index and sometimes does not - `/shop` is the
#: name of a product on one well-known site, `/store` is a store locator on
#: another. Read as a verdict they made a feature page a listing and asked it
#: why it published no filters, so they are consulted only as a *prediction*
#: before anything is fetched, where a wrong guess costs a sampling slot and
#: nothing else. Once the page is in hand its content decides.
WEAK_CATEGORY_PATH_HINTS = (
    r"/shop/?$", r"/store/?$", r"/tienda/?$", r"/boutique/?$", r"/loja/?$",
    r"/negozio/?$", r"/winkel/?$",
)

#: Product URL shapes that are a *guess about layout* rather than a statement
#: about content. `/shop/<something>/<something>` describes as many storefront
#: utility routes as it does product pages - `/us/shop/goto/account`,
#: `/shop/help/returns`, `/shop/goto/payment_plan`.
#:
#: Kept as the record of a shape that must never classify anything: the
#: classifier does not consult it at all, so a page whose URL looks like this
#: is decided by `extract.product_evidence` on the same terms as a page whose
#: URL says nothing. Five storefront utility routes were audited as individual
#: products when this pattern sat in `PAGE_TYPE_HINTS`.
WEAK_PRODUCT_PATH_HINTS = (r"/shop/[^/]+/[^/]+$",)

PAGE_TYPE_HINTS = [
    ("product", (
        r"/products?/[^/]+", r"/p/[^/]+", r"/item/[^/]+", r"/dp/[^/]+",
        r"/pd/[^/]+", r"/sku/[^/]+",
        r"-p-\d+", r"/product-detail",
        r"/productos?/[^/]+", r"/produits?/[^/]+", r"/produkte?/[^/]+",
        r"/produtos?/[^/]+", r"/prodott[oi]/[^/]+",
    )),
    ("category", (
        r"/collections?/", r"/category/", r"/categories/", r"/c/",
        r"/catalog", r"/browse", r"/all-products",
        r"/coleccion(es)?/", r"/categorias?/", r"/categorie/", r"/kategorien?/",
        r"/colecoes/",
    )),
    ("search", (r"/search", r"/buscar", r"/recherche", r"/suche", r"/busca",
                r"/ricerca", r"[?&]q=", r"[?&]query=", r"[?&]s=")),
    # Promotional pages. An offers page carries many prices and a cart control,
    # which is exactly the combination the content-signal branch used to read
    # as "product". It is not a product - and it is not a catalogue index
    # either, so the listing rules do not run on it: a seasonal promotion owes
    # nobody a facet navigation.
    ("promotional", (
        r"/offers?/", r"/deals?/", r"/sale/", r"/promotions?/", r"/promo/",
        r"/campaign", r"/clearance", r"/discounts?/", r"/ofertas?/",
        r"/soldes/", r"/angebote/", r"/promocoes/", r"/saldi/",
    )),
    # Loyalty and membership programmes. Not a catalogue entry, not a policy,
    # and not something product rules have anything to say about.
    # Planners, configurators and builders. A page you *use*, not an item you
    # buy - and they carry prices and a cart control like everything else on a
    # storefront, which is why the content-signal branch could not tell them
    # apart from a product on its own.
    ("tool", (
        r"/planners?/", r"/planning/", r"/configurator", r"/configure/",
        r"/design-tool", r"/designer/", r"/builder/", r"/build-your",
        r"/customi[sz]er", r"/calculator", r"/room-planner", r"/wizard/",
        r"/planificador", r"/planificateur", r"/planer/", r"/pianificatore",
    )),
    ("program", (
        r"/loyalty", r"/membership", r"/members?/", r"/rewards?/", r"/club/",
        r"/programme?s?/", r"/fidelidad", r"/fidelite", r"/treueprogramm",
    )),
    ("contact", (
        r"/contact", r"/stores?/?$", r"/store-locator", r"/find-a-store",
        r"/contacto", r"/contato", r"/kontakt", r"/contatti",
        r"/complaint", r"/complaints", r"/feedback", r"/get-in-touch",
        r"/write-to-us", r"/reclamacion", r"/reclamacao", r"/reclamation",
        r"/beschwerde", r"/reclamo",
    )),
    # `/help` and `/support` are deliberately absent: they name a *section*,
    # not a document. `/global/en/support/contact-<brand>-submit-complaint/` was
    # read as an FAQ because it sits under `/support/`, which is how a complaint
    # form came to be reported as an FAQ page a site would want indexed, while
    # carrying noindex. Generic hub words live in GENERIC_PAGE_TYPE_HINTS below
    # and only apply when nothing more specific matched.
    ("faq", (
        r"/faqs?", r"/questions", r"/q-and-a", r"/knowledge-?base",
        r"/preguntas[-_]?frecuentes", r"/questions[-_]?frequentes",
        r"/foire[-_]aux[-_]questions", r"/haufige[-_]?fragen",
        r"/perguntas[-_]?frequentes", r"/domande[-_]?frequenti",
        r"/veelgestelde[-_]?vragen", r"/ayuda", r"/aide", r"/hilfe",
    )),
    ("policy", (
        r"/shipping", r"/delivery", r"/returns?", r"/refunds?", r"/exchange",
        r"/warrant", r"/privacy", r"/terms", r"/policy", r"/policies",
        r"/envios?", r"/livraison", r"/versand", r"/frete", r"/spedizioni",
        r"/verzending", r"/devoluciones?", r"/retours?", r"/ruckgabe",
        r"/devolucoes?", r"/resi", r"/privacidad", r"/confidentialite",
        r"/datenschutz", r"/impressum", r"/terminos", r"/condicoes",
        r"/condizioni", r"/voorwaarden",
    )),
    ("about", (
        r"/about", r"/our-story", r"/company", r"/brand", r"/who-we-are",
        r"/sobre[-_]?nosotros", r"/quienes[-_]?somos", r"/a[-_]propos",
        r"/uber[-_]?uns", r"/chi[-_]?siamo", r"/over[-_]?ons", r"/sobre",
    )),

    ("article", (r"/blog", r"/news", r"/journal", r"/press", r"/articles?/",
                 r"/guides?/", r"/noticias", r"/actualites", r"/nieuws")),
]

#: Crawler product tokens their operators publish for AI crawling and
#: answer-time fetching. A robots.txt rule covering these is invisible to
#: classic SEO tooling, which reports on Googlebot and Bingbot; what any
#: operator does with the pages a rule covers is not measured here.
AI_CRAWLER_AGENTS = {
    "GPTBot": "OpenAI - trains/serves ChatGPT retrieval corpus",
    "OAI-SearchBot": "OpenAI - powers ChatGPT Search result citations",
    "ChatGPT-User": "OpenAI - live fetch when a user's question needs the page",
    "ClaudeBot": "Anthropic - Claude web index",
    "Claude-Web": "Anthropic - legacy Claude crawler token",
    "Claude-User": "Anthropic - live fetch on behalf of a Claude user",
    "anthropic-ai": "Anthropic - legacy token still honoured by many sites",
    "PerplexityBot": "Perplexity - index used for cited answers",
    "Perplexity-User": "Perplexity - live fetch for a user question",
    "Google-Extended": "Google - gates Gemini grounding / AI Overviews use",
    "Applebot-Extended": "Apple - gates Apple Intelligence use",
    "Bingbot": "Microsoft - index behind Copilot answers",
    "CCBot": "Common Crawl - upstream corpus for many assistants",
    "Amazonbot": "Amazon - Alexa/Rufus answer surfaces",
    "meta-externalagent": "Meta AI - answer surfaces",
    "Bytespider": "ByteDance - Doubao/TikTok answer surfaces",
    "cohere-ai": "Cohere - retrieval corpus",
    "Diffbot": "Diffbot - knowledge graph feeding several assistants",
    "YouBot": "You.com - cited answers",
}

#: Bots whose loss is *not* an AI-visibility defect (ads/SEO tooling only), so
#: we never raise a finding for these being blocked.
NON_AI_AGENTS = {
    "AhrefsBot", "SemrushBot", "MJ12bot", "DotBot", "BLEXBot", "PetalBot",
    "SeekportBot", "DataForSeoBot", "Screaming Frog SEO Spider",
}


#: Hub words that name a *section* of a site rather than a kind of document.
#: They are consulted only when no specific hint matched, so a page under
#: `/support/` that is plainly a contact form, a return policy or an FAQ is
#: classified by what it is, and only a genuine landing hub is left as
#: `support`. Keeping them out of the specific table is what stops one generic
#: keyword deciding a page type on its own.
GENERIC_PAGE_TYPE_HINTS = [
    ("support", (
        r"/support", r"/help", r"/customer-service", r"/customer-care",
        r"/servicio-al-cliente", r"/service-client", r"/kundenservice",
        r"/hilfe", r"/ayuda", r"/aide", r"/assistenza", r"/klantenservice",
    )),
]
