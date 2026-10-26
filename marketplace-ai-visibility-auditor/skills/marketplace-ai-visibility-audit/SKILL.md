---
name: marketplace-ai-visibility-audit
description: Audit a marketplace, storefront or brand website for AI visibility and
  recommendation readiness, and emit one evidence-backed report. Reports where the site
  does not publish the evidence a machine reader needs to find, read, trust and attribute
  it (blocked crawlers, JavaScript-only content, missing or invalid schema.org data, facts
  locked in images, stale or contradictory prices, single-source claims, ambiguous
  entities) and where a referred visitor lands on a page that does not continue the answer
  (no specifications, no comparison attributes, no filters, no reviews, no answers in
  question form, hidden delivery, returns and stock, deep links that land on the home
  page). Emits findings with severity and observable evidence plus prioritized,
  mechanism-explained fixes and proactive improvements. Use when
  asked to audit or improve a site's visibility in ChatGPT, Claude, Gemini or
  Perplexity, its AI discoverability or structured data, or why AI-referred traffic
  bounces. Read-only: never modifies the audited site.
license: Apache-2.0
compatibility: Requires Python 3.9+ and outbound HTTPS to the audited site. No
  third-party packages. Playwright is optional and only used by --render.
allowed-tools: Bash(python3:*) Read Write
metadata:
  role: entrypoint
  marketplace: marketplace-ai-visibility-auditor
  version: "1.11.2"
---

# Marketplace AI Visibility & Recommendation-Readiness Audit

The entrypoint of the `marketplace-ai-visibility-auditor` marketplace. It receives
the audit request, collects the evidence **once**, composes the six specialist
skills over that shared evidence, and emits **one** report.

## When to use

- "Why doesn't ChatGPT / Claude / Gemini / Perplexity mention us?"
- "Is our storefront machine-readable? Are our product pages quotable?"
- "Assistants quote our old price / old tagline / a product we discontinued."
- "AI traffic lands on our site and bounces."
- Before or after a replatform, a rebrand, or a structured-data project.

Not for: writing content, changing a site, ranking products, or answering
shopping questions. This skill diagnoses and recommends. It never edits a site.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `site` | yes | A URL or bare domain. Any depth is fine: `example.com`, `https://shop.example/`, or `https://shop.example/collections/x?utm_source=…` — the root is always audited as the home page and the URL you pass becomes the entry point |
| `--max-pages` | no | Fetched HTML documents, default 40, hard cap 200 |
| `--time-budget` | no | Seconds, default 240 (the brief's budget is 5 minutes) |
| `--schema` | no | `full` (default), `handout` (the brief's exact floor), `flat` |
| `--render` | no | Also collect **browser-rendered evidence** for a bounded subset of pages, so an absence can be reported as "not in the server response" rather than "not on the page". Optional: needs Playwright, skipped gracefully without it, and every navigation goes through the same robots.txt and private-address gate as the fetcher |
| `--render-pages` | no | How many pages the render pass may open, default 3. Only meaningful with `--render` |
| `--user-agent` | no | override the auditor's User-Agent — for an operator auditing their own site. Values that impersonate a browser or a named crawler are rejected before a socket opens |
| `--offline weak\|mixed\|strong\|locales\|semantic\|rendered` | no | Audit a bundled fixture site over a local server, no external network |

## Safety and scope (non-negotiable)

1. **Read-only.** Only GET and HEAD exist in the HTTP client; any other method
   raises. No skill can alter the audited site.
2. **robots.txt is obeyed** for the audited site and for any off-site anchor the
   site itself declares — and re-checked on the URL that actually served the
   bytes, so a redirect cannot carry the crawl into a disallowed path. A
   redirect onto another host is authorised against *that* host's robots.txt.
   A robots.txt the origin answers but cannot serve is treated as a full
   disallow (RFC 9309) and reported as a critical finding; a request that never
   reached the origin is reported as a coverage limit of this audit, not as a
   defect of the site.
3. **No authentication, no credentials, no cookies, no bypass of any control.**
   Transactional URLs are excluded by path *and* query, so a cart-mutating GET
   is never queued.
4. **Rate limited and bounded**: one request at a time, a minimum delay per host
   (raised to any `Crawl-delay` the site declares), a page cap, a byte cap and a
   wall-clock budget.
5. **Off-site requests are vetted.** The audited site controls the anchors this
   tool verifies, so any that resolve to a private, loopback or link-local
   address are refused rather than fetched.
6. **Every finding must cite an observation**, and the observation must
   support the claim. Findings without evidence are rejected by the report
   builder and listed in `diagnostics.rejected_findings` — as is a finding
   whose `metrics.sample_unit` names a page type its cited URLs are not, and a
   quotation offered as prose evidence that does not contain the fact it is
   offered for.
7. **Nothing is inferred that was not seen.** Where the crawl could not reach a
   page type, the affected rules stay silent rather than guessing; where robots
   or the budget hid the pages that would have settled an absence claim, the
   finding names that and drops a severity level.
8. **Deterministic.** Two runs of the same site produce byte-identical output
   apart from the timestamps.
9. **No third-party services.** Nothing outside the audited site and the anchors
   it declares is ever fetched — no search API, no knowledge-graph lookup. Web-wide
   corroboration is the root cause this audit takes most seriously and the one a
   read-only crawl of a single site cannot observe, so it is emitted as prioritized
   recommendations (`OPP-THIRD-PARTY-SYNC`, `OPP-KNOWLEDGE-ANCHOR`,
   `OPP-BRAND-FACTS`, `OPP-MONITORING`) rather than as findings the report cannot
   evidence. The manifest stays self-contained and the runtime keeps no external
   dependency.
10. **A refusal is not a defect.** A 403, 429 or challenge page is recorded as an
   observation about the path between this auditor and the origin. It is reported
   as `CR-BOT-WALL`, never as a fault in the site's HTML, and it forces the report
   into its `transport_only` state. One barrier is one finding: a refused
   `/robots.txt` is not evidence that no robots.txt exists (only a 404 is), and a
   refused URL is not a broken URL the site advertised — reporting the same
   obstacle under three headings scored one site three times for it. And what was
   observed is that *this* agent was refused: the audit does not send an assistant
   crawler's User-Agent, so how GPTBot or ClaudeBot are treated is stated as the
   open question it is, and the recommendation begins by reading the edge logs
   rather than by changing a configuration.

## Conservative under uncertainty

The auditor is built to be conservative when it is unsure, because on an
unseen site a confident wrong finding costs more than a missed one.

0. **Page type is not enough, so it is never the last word.** A walking boot,
   a software licence, a monthly plan, a boiler service and a manufacturer's
   information page are all product pages; only the first is delivered in a
   box, kept in stock or sent back. `lib/aiva/semantics.py` decides, from
   declared types, typed properties, the offer's shape and the page's own
   words - never from words in a URL - what kind of thing each page is about
   (`physical`, `digital`, `software`, `subscription`, `service`,
   `marketplace_listing`, `informational`, `ambiguous`), what each listing is
   a listing *of*, and what shape the site is. Every commerce rule and every
   generated question then asks one shared applicability function
   (`is_shipping_applicable`, `is_stock_applicable`, `is_returns_applicable`,
   `is_physical_specs_applicable`, `is_reviews_applicable`, …), each of which
   returns a decision with its reason, its basis (`declared`, `observed`,
   `inferred`, `unknown`) and its confidence.

   Nothing is silently skipped: a finding names the pages it set aside and
   why ("2 further product page(s) were not assessed because the expectation
   does not apply to them: 1 (a return policy does not apply to a software
   item) …"), and `coverage.expectations_not_applied` prints the same
   accounting for the whole run. Where a page's own kind is not established
   and every item the site is seen to sell is of one kind, the expectation is
   applied by inference, at lower confidence, and the finding says so.

   The same layer decides how a name relates to the site's own (a department,
   a subsidiary, a product's brand, a former trading name and the site's own
   name in another script are never rival spellings), what kind of thing an
   outbound link is (only an account on a platform is an identity claim a
   site could declare as `sameAs`), and whether the origin answered at all: a
   404 or 410 is the resource saying it is not there, while a 403, a 429, a
   5xx, a timeout, a robots disallow or a spent budget is reported as *could
   not be verified* and never as a broken URL.

1. **Page-type classification is a question about cardinality, and it
   requires multiple independent signals.** The question is not "does this
   page look commercial?" - on a storefront every page does - but "is this
   page about *one* purchasable thing, several, or neither?" Three separate
   readings answer it:

   - a **declared listing type** (`CollectionPage`, `SearchResultsPage`,
     `OfferCatalog`) is a statement about the document and settles it;
   - **plurality** - two or more distinct product entities, a grid of prices,
     sort or filter controls a single item would not need, pagination, priced
     sibling links - means the page presents a set, unless the markup names
     one entity and the page's own heading repeats that name;
   - **singularity** needs an **anchor** that fixes *which* item the page is
     about (one declared product entity, an item-shaped URL, a buy control
     inside the content region) *and* at least two signal families in total.

   So no page becomes an individual product from an isolated signal: not a
   price, not one `h1`, not product vocabulary, not `/shop/` or `/buy/` in the
   URL, not product links, and not a bare `Product` token in the markup. Two
   observations of the same thing cannot masquerade as two signals, and two
   corroborators with no anchor - a price and a specification table, which a
   comparison page, a shipping policy and a promotions hub all have - are not
   enough either. A variant family declared correctly (a `ProductGroup` and
   its sizes) is one subject, not three, so good markup is not punished.

   **Being a listing is earned the same way.** `category` is a specific type
   too, and it carries obligations of its own - a listing is asked why it has
   no filtering, no sorting, no comparison support. So a page is not promoted
   to `category` merely because it shows several prices. Where a singular
   anchor and a plural signal are both present, only *item-scoped* evidence
   settles it - a specification block, a buy control in the content, variant
   options, a declared single entity - because a page presenting a set does
   not publish the dimensions of one of them. A heading, a price and a URL are
   page-scoped and fit either reading, so they do not. Unsettled, the page is
   `other`: audited as neither, asked neither why its Product schema is
   missing nor why it has no sort control.

   **The decision is recorded.** Every page carries `page_type_evidence`, and
   the report prints `why_type` beside each URL in its `evidence_manifest`, so
   a classification can be read and disputed rather than reverse-engineered.
   **Only content documents are samples.** A search results page (recognised
   from the page's own search box pre-filled with the URL's query, its own
   search parameter in the query, or a declared `SearchResultsPage`), a
   navigation/reference address that serves a document the crawl already
   holds (a redirect, a declared canonical, an identical copy - typed
   `reference`), and an account/auth endpoint are read and listed, but no
   content rule samples them: a search page is asked neither why it declares
   no Product markup nor why it has no filters, and the home page reached by a
   tracking suffix is not a content page whose canonical points elsewhere.
   A grid of purchase controls is plurality, not the anchor one control gives.
2. **Explicit non-product signals take precedence.** Category, listing,
   promotional, program, support, contact, policy, FAQ, about, article, search
   and planner/configurator (`tool`) pages are classified as what they are
   before any commerce heuristic runs, and none of them can be sampled as a
   product.
3. **Downstream specialists consume the shared classification.** `page_type` is
   decided once, by the collector, and frozen into the evidence bundle.
   `ev.product_pages` is the single funnel every product-specific rule goes
   through, and `ev.category_pages` is its twin for the listing-only rules -
   filtering, sorting, comparison support - which are questions only a set can
   answer. A rule that decides for itself what a listing is is a second
   opinion, and a second opinion is how a product detail page came to be asked
   why it published no filter controls. Both funnels state their exclusion as
   well as their filter, and the test suite asserts that no rule selects
   either type by a literal.
4. **Composed evidence, not keyword matches.** Where a question's answer is a
   construction rather than a word, the quotation must carry every vocabulary
   the answer is made of and none that marks a different subject - so "paid
   through a Credit/Debit card" in a refund anecdote, or "a payment method" in
   a privacy notice, cannot answer what the site accepts at checkout. The
   composed vocabularies are asserted to be disjoint, or a conjunction would
   collapse back into a single keyword.
5. **A product's identity comes from item-scoped evidence, or not at all.**
   Anything that quotes a product's name back to the reader - a generated
   question, a worked example, a duplicate-name finding - takes it from the
   product entity the page declares (JSON-LD subject node, microdata product
   item, Open Graph product card), or from a heading the page corroborates in
   a second channel: a `<title>` segment unique to that page, its `og:title`,
   or its URL slug. A heading that is the label of one of the page's own
   controls, a string the site repeats across pages, or one shaped like a
   promotion (a price, a percentage, an exhortation) is never an identity.
   Where none is established, no product question is asked, and the matrix
   says which pages were set aside and why. Every test is about shape or
   provenance - none knows a brand, a framework or a phrase a call to action
   tends to use.
6. **Absence is stated about what was probed.** "No sitemap was found at the
   conventional locations this audit probes" is an observation; "the site has
   no sitemap" is not, and the report never says it. The internal-linking
   consequence is drawn only when both discovery mechanisms a crawler has
   unaided - the robots.txt `Sitemap:` directive and the conventional paths -
   were checked and both came back empty; a location that timed out or was
   refused is reported as unchecked, not absent. The missing directive is a
   separate fact about robots.txt and is reported as one. Canonical findings
   are made only about eligible content pages, chosen from page evidence
   (classified type, robots directives, whether the fetched document is the
   page's own) rather than URL shape, with the pages set aside counted.
7. **Negative regression cases.** Every fix above ships with tests that fail on
   the build before it, and the suite is weighted towards assertions that a
   rule stays *silent* - the failure mode that matters on a site nobody
   designed the auditor for.

The goal is not to maximise the number of product pages detected. It is to
maximise trustworthy findings and minimise false positives under uncertainty.

## Procedure

1. **Validate the request.** Normalise the URL, build the `AuditConfig`, refuse a
   configuration that would be impolite (see `AuditConfig.validate`).
2. **Collect the shared evidence, once.** In this order: `robots.txt` →
   host canonicalisation probes → agent-facing discovery surfaces
   (`/llms.txt`, `/agents.md`) → sitemaps (declared and
   well-known) → **the site root** → the supplied URL when it is deeper than
   the root → a type-balanced sample of product, category, policy, FAQ, about
   and contact pages → a soft-404 probe → verification that the off-site
   anchors the site declares actually resolve. Every URL is fetched at most
   once and frozen into an evidence bundle
   (`schemas/evidence-bundle.schema.json`).

   *One market per audit.* When the URL you supply carries a locale
   (`/in/en/`, `/de/de/`), that market becomes the audit's scope: the frontier
   keeps to the same locale and the same host, admitting market-neutral
   segments (`/global/...`) and paths with no locale at all, and sitemap
   entries are filtered the same way. Without it a market selector leads the
   crawl into three other countries and every ratio becomes an average across
   catalogues, prices and policies that have nothing to do with each other.
   `coverage.locale_scope` reports the scope; sites that do not partition by
   locale are unaffected.

   *Home page vs entry point.* Site-wide identity checks (Organization and
   WebSite markup, navigation reachability, self-description) are only
   meaningful against the real front door, so the home page is always the
   origin root. A deeper URL you pass in is the **entry point**: it is crawled
   first and seeds the frontier, but it is classified on its merits — a
   `/collections/…` URL is a category page, not a home page. Cart, checkout and
   account paths, and binary assets, are excluded from the frontier entirely:
   they can never be a citable source and only burn budget.
3. **Compose the specialists.** Read `marketplace.json`, resolve each
   non-entrypoint skill's `scripts/analyze.py`, and call `analyze(bundle)`.
   Specialists get the bundle, never a network client. A specialist that raises
   is isolated and recorded - as *failed*, never as "0 findings": its pillar is
   reported unmeasured, `summary.specialist_coverage` becomes `partial`, and
   `coverage.specialists` names the skill, its pillar and the error. The rest
   still run and keep their findings.
4. **Merge.** De-duplicate by rule id, reject evidence-less findings, score the
   six pillars, rank by priority (severity × confidence × scope × effort, with
   a bonus for gating pillars), assign `F-001…` in priority order.
5. **Add proactive recommendations** that are gated on evidence and suppressed
   when a specialist already reported the same ground as a defect.
6. **Emit one report** and validate it against
   `schemas/audit-report.schema.json` before returning it.

## How to run

```bash
# full audit of a live site
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py https://example.com \
    --out ./audit --format both

# self-contained demo, no external network
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline weak --format markdown

# exactly the report shape the brief specifies
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py https://example.com --schema handout

# split phases (inspect the raw evidence, or debug one specialist)
python3 skills/marketplace-ai-visibility-audit/scripts/collect_evidence.py https://example.com \
    --out bundle.json --validate
python3 skills/crawl-render-audit/scripts/analyze.py --bundle bundle.json
python3 skills/marketplace-ai-visibility-audit/scripts/compose_report.py --bundle bundle.json

# self-check the package against the Agent Skills spec
python3 skills/marketplace-ai-visibility-audit/scripts/validate_marketplace.py
```

## Output

One JSON report. Required floor: `site`, `audited_at`, a counts-by-severity
`summary`, and per finding `id`, `title`, `severity`, `evidence`,
`suggested_action`. On top of that floor the report adds structured
`evidence_items`, pillar and dimension scores, a ranked `prioritized_actions`
plan, `proactive_recommendations`, crawl `coverage`, an `evidence_manifest` and
`diagnostics`. See [references/report-schema.md](references/report-schema.md).

`summary.coverage_state` says what class of claim the report is entitled to
make: `content` when at least one page was parsed, `transport_only` when none
was. In the `transport_only` state the headline names the barrier — a bot wall,
a robots disallow, a transport failure or an empty crawl — and says plainly that
no claim is made about the site's content, engagement or readiness.

Read the report top-down: `summary.headline` → `prioritized_actions` →
individual findings. See
[references/interpreting-results.md](references/interpreting-results.md).

## References

- [references/orchestration.md](references/orchestration.md) — the composition contract and how to add a specialist
- [references/report-schema.md](references/report-schema.md) — the report shape and the three projections
- [references/severity-and-priority.md](references/severity-and-priority.md) — how severity, confidence, scoring and ranking are decided
- [references/safety-and-scope.md](references/safety-and-scope.md) — the guardrails and how they are enforced and tested
- [references/interpreting-results.md](references/interpreting-results.md) — reading the report, and what it deliberately cannot tell you
