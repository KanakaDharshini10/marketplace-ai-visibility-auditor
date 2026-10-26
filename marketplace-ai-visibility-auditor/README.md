# Marketplace AI Visibility & Recommendation-Readiness Auditor

An Agent Skill Marketplace that audits any marketplace, storefront or brand
website for **AI visibility** (can assistants find, read, trust and correctly
attribute it?) and **recommendation readiness** (does a visitor an assistant
sends actually land on the answer?), and emits **one** evidence-backed report
with prioritized fixes.

Seven skills: one entrypoint plus six specialists. Python 3.9+, **no
third-party dependencies**, read-only, robots-respecting, well inside the
brief's five-minute budget.

---

## Run it

```bash
cd marketplace-ai-visibility-auditor

python3 skills/marketplace-ai-visibility-audit/scripts/validate_marketplace.py
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline weak --format markdown
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline strong   # must find nothing
python3 tests/run_tests.py
```

Against a real site:

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py https://example.com \
    --out ./audit --format both
```

Nothing to install. On Windows use `py -3` in place of `python3`; the CLI
writes UTF-8 whatever the console code page is, so a report that quotes a
rupee sign or a Japanese product name prints and redirects cleanly there too.
[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) is the guided tour, in the order
worth reading it.

---

## The model: visibility is a funnel, not a score

A brand appears in an assistant's answer only if a chain of steps all succeed:

```
crawler admitted → page readable → fact extractable → entity resolved
    → fact corroborated and current → retrieved for this question
    → landing page continues the answer
    → the question actually gets an answer
```

Each specialist owns one link in that chain, which is where the decomposition
comes from — not from splitting a checklist six ways. The first five audit the
*mechanisms*; `answerability` audits the outcome those mechanisms exist to
serve, because a site can satisfy every mechanism and still answer nothing.

## The skills

| Skill | Pillar | Half | What it owns |
|---|---|---|---|
| **`marketplace-ai-visibility-audit`** *(entrypoint)* | — | both | Receives the request, collects all evidence once, composes the specialists from the manifest, scores, ranks, and emits the single report. |
| `crawl-render-audit` | `crawl_render` | discoverability | Can a machine reach the content? robots.txt including **assistant crawler tokens** (GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot, Google-Extended…), **bot walls and edge refusals**, sitemaps, HTTP status and redirects, canonicalisation, indexability, soft 404s, JavaScript-only pages, discovery paths, speed. |
| `machine-readability-audit` | `machine_readability` | discoverability | Once reached, can it be parsed? JSON-LD validity and coverage, Product/Offer/Brand completeness, price, availability, identifiers, attributes, ratings, breadcrumbs, semantic HTML, **Open Graph**, and facts that exist only as pixels **or only inside a PDF**. |
| `freshness-corroboration` | `freshness_corroboration` | discoverability | Is it current, self-consistent and supported by more than one source? Date signals, sitemap `lastmod` honesty, markup-vs-page price and stock conflicts, cross-page price conflicts, review recency, declared off-site anchors. |
| `entity-audit` | `entity` | discoverability | Who is this? Organization and Brand identity, name consistency across every surface, product→brand and product→category edges, stable `@id`s, variant modelling, duplicate identities, **physical locations as readable entities**. |
| `engagement-audit` | `engagement` | **engagement** | Does the visitor land on the answer? First-screen price and availability, specifications, comparison support, filters, reviews, FAQs, shipping/returns/stock visibility, deep-link continuity, orientation. |
| `answerability-audit` | `answerability` | outcome | Can the crawled evidence answer the questions a buyer would ask? Questions are generated from the site's own catalogue, never a stock list, and each is resolved against the shared evidence with a citing URL and the snippet found. |

Detail lives in each skill's `SKILL.md` and its `references/checks.md`
(progressive disclosure: the rule catalogue and the reasoning are one level
down).

## How the entrypoint composes them

Every specialist exposes exactly one function:

```python
def analyze(bundle: dict) -> list[Finding]: ...
```

The entrypoint reads `marketplace.json`, resolves each non-entrypoint skill's
declared script, and calls it with the one shared evidence bundle. Adding or
removing a specialist is a manifest edit — no orchestrator code changes.

Three properties fall out of the split, and none relies on discipline:

- **Shared evidence is reused by construction.** Specialists have no network
  capability (asserted against their import graph in the test suite), so they
  cannot re-fetch what another specialist already read.
- **Findings cannot be invented.** A finding with no evidence item is
  *rejected* by the report builder and listed in
  `diagnostics.rejected_findings` — as is one whose evidence sentence states a
  consequence the crawl did not measure.
- **A failing specialist is isolated, and never disguised.** Its error is
  recorded in `diagnostics.skill_runs` with `status: "failed"` and
  `findings: null`, its pillar is scored `unmeasured` rather than clean,
  `summary.specialist_coverage` reads `partial`, and the other five still run
  with their findings intact.

## The report

The brief's required floor is always present exactly as specified: `site`,
`audited_at`, a counts-by-severity `summary`, and per finding `id`, `title`,
`severity`, `evidence`, `suggested_action`. On top of it: structured
`evidence_items` (URL + locator per observation), `confidence`, pillar and
dimension scores, a ranked `prioritized_actions` plan,
`proactive_recommendations`, the answerability matrix, crawl `coverage`, an
`evidence_manifest` of every URL fetched and why, and `diagnostics`.

Three projections of the same report, so they can never disagree:
`--schema full` (default) · `handout` (the brief's fields only) · `flat`.
Validated against `schemas/audit-report.schema.json` on every run.

Every suggested action carries a **mechanism**, concrete **steps**, an
**example** where markup is involved, and a **verification** step — so a
non-expert can act and then check.

`summary.coverage_state` says what class of claim the report is entitled to
make: `content` when pages were parsed, `transport_only` when they were not.
A run that read nothing says so in its headline instead of scoring the
fragments it did get.

Two rules govern what may be cited, both enforced in the report builder rather
than left to each rule's discipline:

- **A quotation must contain the fact.** Answerability quotes are anchored to
  the phrase they matched, taken from the page's content region in preference
  to its chrome, and opened at the sentence the phrase sits in. Where the
  concept cannot be located there is no quotation and the question is not
  reported as answered in prose.
- **A citation must be the page type the finding claims.** A finding whose
  `metrics.sample_unit` names a page type may only cite URLs the crawl
  classified as that type; anything else is rejected into
  `diagnostics.rejected_findings`.

**One market per audit.** Point the audit at `https://example.com/in/en/` and
it stays in that market: the frontier keeps to the same locale and host, plus
market-neutral paths (`/global/...`) and paths with no locale at all, and
sitemap entries are filtered the same way. `coverage.locale_scope` and
`coverage.out_of_locale_candidates` state the scope, so a ratio is never a
silent average across countries with different catalogues, prices and
policies.

## Page type is not enough

Knowing a page is a *product page* does not say what it is a page about. A
walking boot, a software licence, a monthly plan, a boiler service and a
manufacturer's information page are all product pages, and only the first is
delivered in a box, kept in stock or sent back. A rule set that reads the page
type alone asks a download when it will arrive, tells a documentation site to
publish a product feed, and reports a Japanese rendering of the site's own
name as a competing brand.

`lib/aiva/semantics.py` is the one place those questions are answered, from
evidence and never from words in a URL:

- **What kind of thing is this page about?** `physical`, `digital`,
  `software`, `subscription`, `service`, `marketplace_listing`,
  `informational` or `ambiguous`, each with its confidence and the evidence
  that decided it: declared types, typed properties (`gtin`/`weight` versus
  `operatingSystem` versus a `UnitPriceSpecification` billed monthly), the
  offer's shape, and the page's own words. It also records whether the page
  *sells* the item or only describes it.
- **What is this listing a listing of?** `ecommerce_listing`,
  `content_listing`, `documentation_section`, `article_index`,
  `audio_listing`, `service_listing`, `software_catalog`,
  `marketplace_listing` or `unknown`, read from the `ItemList` entry types and
  from what the crawl found at the other end of the listing's own links —
  never from the site's navigation, which is the same on every page.
- **What shape is this site?** `ecommerce`, `marketplace`,
  `travel_hospitality`, `software`, `services`, `documentation`,
  `developer_platform`, `publisher`, `government`, `education`, `community`,
  `knowledge_reference`, `nonprofit`, `corporate`, `mixed` or `unknown`, with
  the evidence printed in `coverage.site_kind_evidence`. `software` covers both
  a software vendor and SaaS (`sells_subscriptions` tells them apart),
  `government` is the public-body kind and `services` the service-business
  kind; an audio publisher is a `publisher` whose listings are
  `audio_listing`.
- **Does this expectation apply to this page?** One function per expectation —
  `is_shipping_applicable`, `is_returns_applicable`, `is_stock_applicable`,
  `is_physical_specs_applicable`, `is_reviews_applicable`, `is_price_applicable`,
  `is_identifier_applicable`, `is_purchase_cta_applicable`,
  `is_comparison_applicable`, `is_site_search_expected` — each returning a
  decision *and its reason and basis* (`declared`, `observed`, `inferred`,
  `unknown`). Every commerce rule and every generated question asks these, so a
  page is decided once, the same way, everywhere.

The same context decides **which questions this site's readers arrive with**.
`high_value_question_intents` returns the topic families the evidence supports —
delivery and returns for a site that sells goods, installation and versions for
documentation, eligibility and deadlines for a public body, plans and limits for
a subscription, amenities and cancellation for a stay, definitions and sources
for a reference work — and `EG-FAQ-MISSING` names the families it derived and
the evidence for each. A site the audit can characterise in no way at all is
asked for no questions rather than guessed at.

Nothing is silently skipped. A finding names what it set aside and why — "2
further product page(s) were not assessed because the expectation does not
apply to them: 1 (a return policy does not apply to a software item); 1 (a
return policy does not apply to a subscription item)" — and
`coverage.expectations_not_applied` prints the same accounting for the whole
run. Where a page's own kind is not established and every item the site is
seen to sell is of one kind, the expectation is applied *by inference*, at
lower confidence, and the finding says that too.

The same layer answers three more questions that used to be guessed:

- **How does this name relate to the site's own?** `primary_entity`, `brand`,
  `subsidiary`, `department`, `agency`, `tribunal`, `partner`,
  `acquired_company`, `official_profile`, `localization`, `language_variant`,
  `knowledge`, `unrelated` … so a department, a product's brand, a former
  trading name and the site's own name in another script are never counted as
  rival spellings of the trading name.
- **What kind of link is this?** An account on a platform, a knowledge-base
  entry, a documentation host, a listing on someone else's store, a repository,
  a locale variant, a share intent. Only the first is an identity claim a site
  could declare as `sameAs`; the rest are links, and the finding says how many
  it did not count.
- **Did the origin answer?** `verified`, `not_found` or `unverified`. A 404 or
  410 is the origin saying the resource is not there. A 403, a 429, a 5xx, a
  timeout, a robots disallow or a spent budget is the path failing, and is
  reported as "could not be verified" — `CR-URLS-NOT-VERIFIED`, at `info` — never
  as a broken URL or a "dead profile".

Proactive recommendations carry the same metadata. Every entry in
`lib/aiva/recommend.py`'s library declares the site kinds it is for, the page
contexts it concerns and the evidence it requires; every emitted
recommendation carries an `applicability` record saying what about *this* site
satisfied them, printed in the Markdown as *"Applies because: …"*. A
documentation site is never told to model size variants, and a publisher is
never told to publish a product feed.

## Conservative under uncertainty

Page-type classification requires **multiple independent signals**; downstream
specialists consume the shared classification rather than guessing; and
composed evidence rules stop keyword-only matches becoming findings.

The product question is one of **cardinality** — is this page about one
purchasable thing, several, or neither? — because on a storefront every page
looks commercial and no vocabulary can separate them. A declared listing type
(`CollectionPage`, `OfferCatalog`) settles it. Otherwise plurality is read
first: two or more distinct product entities, a grid of prices, sort or filter
controls a single item would not need, pagination, priced sibling links. What
is left has to earn `product` twice over — an **anchor** that says *which* item
the page is about (one declared entity, an item-shaped URL, a buy control in
the content region) plus at least two signal families in total. So no isolated
signal decides: not a price, not one `h1`, not product vocabulary, not
`/shop/` or `/buy/` in the URL, not product links, not a bare `Product` token.
Neither do two corroborators with no anchor — a price and a specification
table describe a comparison page and a shipping policy as well as a product.
A correctly declared variant family (a `ProductGroup` and its sizes) is one
subject, not three, so good markup is not punished, and a related-items rail
does not turn a detail page into a catalogue. Where the evidence does not
settle it, the page is `other`, which no product rule can sample.

Being a **listing** is earned the same way, because `category` carries
obligations of its own — a listing is asked why it has no filtering, no
sorting, no comparison support. A page is not promoted to `category` merely
because it shows several prices. Where a singular anchor and a plural signal
are both present, only *item-scoped* evidence settles it — a specification
block, a buy control in the content, variant options, a declared single
entity — because a page presenting a set does not publish the dimensions of
one of them. A heading, a price and a URL are page-scoped and fit either
reading, so they do not. Unsettled, the page is `other` and is audited as
neither.

**Not every fetched page is a content document, and only content documents
are samples.** Three kinds are read, typed and listed in the manifest but kept
out of every content population: a **search results page**, recognised from
what the page says about the URL it was fetched at (its own search box
pre-filled with the query, or the query carrying its own search parameter, or
a declared `SearchResultsPage`) rather than from any URL word; a
**navigation/reference address** (`reference`) — a second URL that serves a
document the crawl already holds, via a redirect, a declared canonical, or an
identical copy — so a tracking suffix on the home page's logo link is neither a
second home page in every ratio nor a "content page whose canonical points
elsewhere"; and an **account/auth endpoint**, whose content is a sign-in form.
A grid of purchase controls, one per tile, is read as the plurality it is, not
as the single purchase affordance that anchors a product page.
`coverage.content_pages` and `coverage.non_content_pages_by_type` print both
numbers, and the redirect rules still read redirect endpoints as the transport
evidence they are.

Non-product types (category, promotional, program, support, contact, policy,
FAQ, about, article, search, `tool`) are settled before any commerce heuristic
runs. `ev.product_pages` and `ev.category_pages` are the only two ways a rule
can reach a product or a listing, so a rule cannot disagree with the
classifier about a URL. Every page carries `page_type_evidence` and the report
prints `why_type` beside each URL in `evidence_manifest.pages`, so a
classification can be read and disputed rather than reverse-engineered.

**A refusal is not a defect, and one barrier is one finding.** When bot
mitigation turns the audit away, that is reported once, as `CR-BOT-WALL`, and
the report enters its `transport_only` state: no content pillar is scored, and
the pillars that could not be measured read `None` rather than zero. A refused
`/robots.txt` is not evidence that none exists — only a 404 is — and a refused
URL is not a broken URL the site advertised. What was observed is that *this*
agent was refused; the audit never sends an assistant crawler's User-Agent, so
how GPTBot or ClaudeBot are treated is stated as an open question in
`interpretation`, and the recommendation begins by reading the edge logs.

**A finding claims only what was observed.** "The home page does not link
directly to any product or category page" and "the catalogue is unreachable"
are different claims, and the run that reports the first has usually just
disproved the second by reaching the catalogue through the sitemap. The
stronger reading, and the higher severity, are reserved for a crawl in which
no discovery path found a catalogue page at all — and even then the finding
says what it could see rather than asserting an outage.
`tests/test_compliance.py::TestConservativeUnderUncertainty` asserts the
principle as a property over the signals, and `tests/test_page_types.py`
covers the taxonomy on fourteen unrelated synthetic domains.

## What it deliberately does not do

- **It never fetches a third-party service.** Corroboration across the wider
  web is the root cause the audit takes most seriously, and it is also the one
  thing a read-only crawl of a single site cannot observe. Rather than query
  search or knowledge-graph APIs — a dependency, a rate limit and a failure
  mode the brief's self-contained requirement does not want — the package
  verifies the anchors the site itself declares, and everything genuinely
  off-site is emitted as a prioritized recommendation
  (`OPP-THIRD-PARTY-SYNC`, `OPP-KNOWLEDGE-ANCHOR`, `OPP-BRAND-FACTS`,
  `OPP-MONITORING`) rather than as a finding it cannot evidence.
- **It never modifies anything.** No writes, no authentication, no forms.
- **It is not a chatbot or a ranking engine.** It diagnoses and recommends.
- **It does not audit email.** Round 2's appendix also covers summarizers
  dropping the substance of a message. That failure has the same root cause
  this package audits everywhere else — a fact that is not readable text is not
  a fact a machine can use — but an email is not reachable from a URL, so it is
  out of scope for a marketplace whose entrypoint takes a website. The rule
  that transfers is `MR-FACTS-IN-OPAQUE-DOCS`: put the substance in text, near
  the top, and do not carry it in an image.

## Guardrails

| Guarantee | How it is enforced |
|---|---|
| Read-only | `HttpClient.SAFE_METHODS == ("GET", "HEAD")`; any other method raises before a socket opens |
| No credentials | no cookie jar, no auth handler, no `Authorization`/`Cookie` header — checked against the parsed AST |
| No impersonation | `--user-agent` is allowed for an operator auditing their own site; strings matching a browser or a named crawler are rejected by config validation |
| robots.txt honoured | purpose-built RFC 9309 parser; disallowed URLs are never fetched; re-authorised on the URL that served the bytes; an unreachable robots.txt is treated as a full disallow; `respect_robots=False` is rejected |
| No SSRF | every fetched URL, **every declared off-site anchor** and **every redirect hop** is refused if it resolves to a private, loopback or link-local address the operator did not name; redirects to non-web schemes (`file:`, `ftp:`) are refused before the opener's other handlers see them |
| Off-site politeness | the only external requests verify anchors the site itself declares, through the guarded evidence store (private-address guard + that host's robots.txt), capped at 12 |
| Rate limited | sequential requests, ≥0.1s enforced delay (raised to any declared `Crawl-delay`), 40-page default cap (documents actually served, not attempts), 3 MB response cap, output-bounded decompression, 240s budget |
| Target unchanged | the fixture tree is hashed before and after a full audit in the test suite |

See
[`skills/marketplace-ai-visibility-audit/references/safety-and-scope.md`](skills/marketplace-ai-visibility-audit/references/safety-and-scope.md).

## Tests

```bash
python3 tests/run_tests.py          # everything, ~45s
python3 tests/run_tests.py -v
```

1276 tests, stdlib `unittest`, no test dependencies. Library primitives; every
rule against synthetic bundles including negative cases; the semantic layer and
the applicability engine as units; report assembly, scoring, ranking,
projections and schema validation; five end-to-end fixture audits over real
HTTP; the guardrails; and Agent Skills spec compliance of every skill folder.

Four are worth naming, because they guard the properties that decide whether
this works on a site nobody designed it for:

- `test_e2e.TestVerdictDoesNotDependOnUrlVocabulary` builds the same broken
  storefront at `/products/…` and at `/shop/…` and fails if the two audits
  reach different verdicts.
- `test_compliance.TestBriefConstraints` turns each of the brief's
  non-negotiables into an assertion.
- `test_hardening.TestHttpsUpgradeIgnoresRefusals` fails if a refusal is ever
  read as a defect of the site.
- `test_hardening.TestGeneratorsNeverSilentlyDie` calls every recommendation
  generator where exceptions are not caught, because the report builder
  deliberately swallows them.
- `test_ikea_regression` holds the evidence-provenance rules: a quotation that
  does not contain the fact, a citation that is not the page type claimed, and
  a crawl that wanders out of the market it was pointed at.
- `test_semantics` and `test_contextual_findings` hold the applicability
  engine: what each kind of page is asked, what it is not asked, and the
  sentence each finding uses to say which pages it set aside.
- `test_semantic_fixture` audits one mixed site end to end and asserts every
  one of its twenty-five elements — a boot, a licence, a plan, a service, a
  documentation section, a news section, two localized names, a department, a
  403, a 429, a timeout, a cross-domain canonical, a redirect chain, a public
  and a private `noindex` — against the report the pipeline actually produces.
- `test_entity_relationships` and `test_recommendation_applicability` hold the
  two contracts most likely to leak an assumption: which names belong to the
  site, and which advice belongs to which kind of site.
- `test_site_type_semantics` builds eleven invented sites — a shop, a
  subscription service, a software vendor, a documentation set, a publisher, an
  audio publisher, a public body, a knowledge reference, a developer platform,
  a booking site, a forum and a nonprofit — and asserts over the *rendered text
  of every finding and every recommendation* that no delivery, stock, returns
  or catalogue vocabulary reaches a site that sells none, while the same checks
  still fire where goods are sold.
- `test_round3_hardening` holds the 1.9.0 reliability and safety regressions:
  a declared anchor at a private address is never fetched, a redirect to a
  non-web scheme or a private hop is refused, a bot wall is not manufactured
  from a site's outbound links, gzipped sitemaps decode, decompression is
  bounded, and the last few sentences that outran the crawl were brought back
  to what it measured — each failing on 1.8.9.

Five bundled fixture sites (fictional, served on loopback, never deployed):

| Fixture | Purpose |
|---|---|
| `site_weak` | deliberately broken — detection breadth |
| `site_strong` | well-built — **must produce zero findings** (false-positive control) |
| `site_mixed` | realistic middling site — JS-only route, noindex page, dead sitemap entry, redirect chain to home, listing/PDP price conflict, duplicate identities |
| `site_locales` | a multi-market retailer — a locale root that looks product-shaped, a privacy page whose only mention of returns is in its nav, and two other countries advertised in the shared sitemap |
| `site_semantic` | one host carrying a boot, a software licence, a monthly plan, a service, a documentation section, a news section, an ecommerce listing, a department, two localized organisation names, official profiles beside knowledge and documentation links, a cross-domain canonical, a redirect chain, a 403, a 429, a timeout, a public `noindex` and a private one |

Every defect in a fixture is annotated in its HTML with the rule it triggers.

## Layout

```
marketplace-ai-visibility-auditor/
├── marketplace.json          manifest: seven skills, exactly one entrypoint
├── README.md  CHANGELOG.md  LICENSE
├── docs/WALKTHROUGH.md
├── examples/                 a pre-generated report (JSON + Markdown)
├── schemas/                  audit-report + evidence-bundle JSON Schemas
├── lib/aiva/                 shared runtime: fetcher, robots, DOM, extraction,
│                             evidence store, semantics (product/listing/site
│                             kind + applicability engine), findings, scoring,
│                             ranking, recommendations, report
├── skills/
│   ├── marketplace-ai-visibility-audit/   ← ENTRYPOINT
│   │   ├── SKILL.md
│   │   ├── scripts/  run_audit.py · collect_evidence.py · compose_report.py
│   │   │             validate_marketplace.py
│   │   └── references/  orchestration · report-schema · severity-and-priority
│   │                    safety-and-scope · interpreting-results
│   ├── crawl-render-audit/           SKILL.md · scripts/analyze.py · references/
│   ├── machine-readability-audit/    SKILL.md · scripts/analyze.py · references/
│   ├── freshness-corroboration/      SKILL.md · scripts/analyze.py · references/
│   ├── entity-audit/                 SKILL.md · scripts/analyze.py · references/
│   ├── engagement-audit/             SKILL.md · scripts/analyze.py · references/
│   └── answerability-audit/          SKILL.md · scripts/analyze.py · references/
└── tests/                    fixtures + unit, rule, report, e2e, safety,
                              compliance, generalization, hardening suites
```

Each skill folder is independently valid against the agentskills.io spec. They
share `lib/aiva` rather than vendoring six copies of an HTTP client and a DOM
parser; every `SKILL.md` says so under "Why this skill shares the marketplace
library", and `validate_marketplace.py` checks each folder on its own terms.

## Design notes

- **Stdlib only.** A judge runs one command with no install step. Playwright is
  optional and used only by `--render`, which adds *browser-rendered evidence*:
  a bounded subset of pages is opened in headless Chromium and put through the
  same extractor as the raw fetch, so an absence can be reported as "not in the
  server response" rather than "not on the page". Without it the audit is
  complete and behaves exactly as it did before the option existed.
- **Patterns, not fitted examples.** Every rule is written against a mechanism,
  reports `affected / sampled` counts, and lowers its confidence on thin
  samples. No rule keys off a specific platform, theme or site.
- **An expectation must be applicable before it can be unmet.** Whether a page
  owes a delivery statement, a stock value, a manufacturer identifier or a
  return policy is decided by one shared engine from what the page is about,
  and a finding always names the pages it did not assess and why. The absence
  of optional metadata is never reported above `medium`.
- **Absence of evidence is not evidence of absence.** A finding needs two
  things, and they fail independently: the condition was observed, and the
  expectation applies to the page it was observed on. Detecting a pattern
  establishes only the first. `analysis.applicability_verdict` weighs both in
  one place and returns **report** (both evidenced), **downgrade** (a real
  observation whose interpretation is not established — severity capped at
  `low`, confidence at 0.4, the evidence saying which half is missing, and
  every claim resting on the missing half withdrawn) or **suppress** (the
  finding would mislead). Confidence follows the weaker half, never the
  detector: a filter control can be certainly absent from a page whose item set
  is not established, and the number a reader sees says so.
- **Advice about items requires the items.** An attribute or an ordering
  dimension is named only where the chain listing → members → observed value
  exists. A listing whose set cannot be delimited is still reported for the
  affordance it lacks, and told nothing about what to filter or sort on.
- **A cautious finding carries cautious advice.** A downgraded finding's
  *recommendation* is conditional too, not just its title: it may describe what
  was observed and may not introduce a dimension, attribute, intent or business
  requirement that was not. `analysis.conditional_advice` enforces this in one
  place, so the caution cannot reach the headline and stop there.
- **Two measurements of one condition cost the score once.** Where two rules
  measure genuinely different properties of a page — its delivery architecture
  and the size of what it withholds — both stay in the report with their own
  evidence, and `report.link_corroborating` drops the second penalty, because
  the site owner does one piece of work to answer both. Findings about
  different pages are never collapsed.
- **False positives are treated as failures.** `site_strong` producing a single
  finding fails the build. Rules stay silent when the crawl did not sample the
  relevant page type, and heuristic rules ship at reduced confidence and say so.
- **Refusals are not defects.** A 403, a 429 or a challenge page is an
  observation about the path between this auditor and the origin. It is
  reported as exactly that, never as a fault in the site's HTML.
- **Severity ≠ priority.** Severity describes the defect; priority also
  accounts for scope, effort and whether the pillar gates everything
  downstream — which is why a one-line `robots.txt` fix outranks a rendering
  migration.

Version history is in [CHANGELOG.md](CHANGELOG.md).

## License

Apache-2.0. See [LICENSE](LICENSE). The bundled fixture sites are fictional and
are served only from a local loopback server.
