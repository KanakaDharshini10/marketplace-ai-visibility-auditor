# Judge walkthrough

Everything below runs on a bare Python 3.9+ install. No `pip install`, no
network access needed, nothing to configure.

> **Windows / PowerShell:** `python3` is usually not on PATH. Use `py -3` (or
> `python`) in place of `python3` in every command below.

Confirm which build you are running before anything else — every report also
carries it in `generator.version`:

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --version
```

## 1. Is it a valid Agent Skill Marketplace? (5 seconds)

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/validate_marketplace.py
```

Checks every skill folder against the agentskills.io `SKILL.md` specification
(name grammar and 64-char limit, name matching the directory *and* the manifest
id, description ≤1024 chars, `compatibility` ≤500, `metadata` string values,
resolvable relative links, lean bodies) and the manifest convention (exactly one
entrypoint, every declared path and script present, no undeclared skill folder on
disk, self-contained with no external resolution). Expected: `0 error(s)`,
`0 warning(s)`.

## 2. Detection breadth — the deliberately broken fixture (2 seconds)

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline weak --format markdown
```

41 findings, score in the mid teens. Skim the top five: each states what was
observed, on which URL, and what to change and why. The fixture's HTML is
annotated with `<!-- DEFECT: RULE-ID -->` comments, so detection can be checked
against intent line by line — see `tests/fixtures/site_weak/`.

## 3. False positives — the well-built fixture (2 seconds)

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline strong
```

**Zero findings, 100/100.** This is the control that matters most: a rule set
that fires on everything is not a detector. The test suite fails the build if
this fixture produces a single finding. The report is still useful — it carries
six proactive recommendations, because "nothing is broken" is not the same as
"nothing left to do".

## 4. A realistic middling site (2 seconds)

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline mixed --format markdown
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline semantic --format markdown
```

The interesting failure modes, all detected together: a client-rendered product
route, a `noindex` on a live product page, a sitemap entry that 404s, a redirect
chain that lands on the home page, a listing price that contradicts the product
page, an organisation with a name that differs from its `og:site_name`, and two
URLs claiming to be the same product.

A pre-generated copy of this run is in
[`examples/sample-report.json`](../examples/sample-report.json) and
[`examples/sample-report.md`](../examples/sample-report.md).

`--offline semantic` is the other one worth running. It is one host carrying a
boot, a software licence, a monthly plan, a service, a documentation section, a
news section, a department, two localized organisation names, a cross-domain
canonical, a redirect chain, a 403, a 429 and a timeout — and the report is
worth reading for what it *does not* say: no delivery question for the licence,
no stock question for the plan, no brand conflict between the three renderings
of the organisation's name, and the refused URLs recorded as "could not be
verified" rather than as broken links. The coverage block prints every
expectation it did not apply and why.

## 5. The report shape

```bash
# the brief's exact minimum shape, nothing else
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline weak --schema handout --quiet | head -30
```

The default (`full`) report is a superset of that floor. Every run validates
itself against `schemas/audit-report.schema.json` and records the result in
`diagnostics.schema_validation`.

## 6. Composition — is the decomposition real?

```bash
# phase 1: one collection pass, written to disk and schema-validated
python3 skills/marketplace-ai-visibility-audit/scripts/collect_evidence.py \
    --offline mixed --out /tmp/bundle.json --validate

# phase 2: each specialist, standalone, over the same frozen evidence
python3 skills/crawl-render-audit/scripts/analyze.py          --bundle /tmp/bundle.json | head -40
python3 skills/machine-readability-audit/scripts/analyze.py   --bundle /tmp/bundle.json | head -40
python3 skills/freshness-corroboration/scripts/analyze.py     --bundle /tmp/bundle.json | head -40
python3 skills/entity-audit/scripts/analyze.py                --bundle /tmp/bundle.json | head -40
python3 skills/engagement-audit/scripts/analyze.py            --bundle /tmp/bundle.json | head -40
python3 skills/answerability-audit/scripts/analyze.py         --bundle /tmp/bundle.json | head -40

# phase 3: the entrypoint composing them into one report
python3 skills/marketplace-ai-visibility-audit/scripts/compose_report.py --bundle /tmp/bundle.json | head -40
```

The entrypoint resolves the specialist list **from `marketplace.json`** — adding
or removing a specialist needs no orchestrator code change. Specialists receive
the frozen bundle and have no network capability at all, which is what makes
"reuse shared evidence" and "never invent evidence" structural rather than
aspirational.

## 7. Tests

```bash
python3 tests/run_tests.py
```

1276 tests, stdlib `unittest`, ~125 seconds, no test dependencies. Worth knowing
what they cover:

| Suite | What it asserts |
|---|---|
| `test_core` | URL/date normalisation, the robots parser (group selection, longest-match, wildcards, unreachable handling), the HTML mini-DOM against malformed input, extraction, the JSON Schema subset validator, the frontmatter reader |
| `test_rules` | Every rule against a purpose-built synthetic bundle, **including negative cases** (a healthy bundle must produce no findings), plus cross-cutting invariants: every finding is self-valid, cites evidence with a source URL, and carries a mechanism, steps and a verification step |
| `test_report` | Report assembly, evidence-less findings being rejected, duplicate rule merging, summary/finding consistency, scoring, ranking, all three projections, round-tripping |
| `test_e2e` | Three fixture audits over real HTTP; the fetch-once guarantee observed directly; page and time budgets; and the four CLI scripts a judge would run |
| `test_safety` | Only GET/HEAD reachable, no credentials (checked against the parsed AST), the target directory unchanged after an audit, robots compliance including a site that disallows everything, specialists having no network imports and not mutating the bundle, and a failing specialist not taking down the report |
| `test_compliance` | The agentskills.io spec for every skill, the manifest convention, the schemas staying inside the validator's supported subset, no third-party imports, submission size, no model weights — and `TestBriefConstraints`, which turns each of the brief's non-negotiables into an assertion (see §12) |
| `test_answerability` | The answerability engine (question generation is evidence-gated and deterministic, every verdict cites a URL and a snippet) plus the Priority-1 correctness regressions: sixteen currency formats, Unicode word counting, the zero-page gate, the home-page substitution, commerce applicability, sample-size severity ceilings |
| `test_generalization` | The negative half: rules that must stay *quiet* on sites they were not designed for — server-rendered Next.js, quote-on-request catalogues, non-English storefronts, WordPress archives, lakh-grouped prices, correctly-dated archival content |
| `test_hardening` | Refusals are not defects (a 403/429/5xx probe can never produce a canonicalisation finding), the headline may not describe content nobody read, bot-wall detection and its negative cases, User-Agent impersonation refused, and every recommendation generator called where exceptions are *not* caught |
| `test_ikea_regression` | Evidence provenance, from a live multi-market audit: a quotation must contain the fact it evidences, a citation must be the page type the finding claims, and an audit entered at one market must not aggregate three others into its ratios |
| `test_cocoacraft_regression` | A faithful reconstruction of a real storefront that broke earlier versions: sorting without filtering, a visible last-updated date with no machine-readable one, attributes stated in prose and not in markup. Asserts the auditor reports what it observed — and fails the build if a report about one site mentions another |
| `test_redirect_semantics` | The seven things a redirect can mean — canonical host, market, route change, homepage collapse, unrelated destination, canonical representation — classified once from the requested URL, the hops and the destination, so one redirect event produces one finding rather than three |
| `test_transport_only` | What a report may say when it was refused before it read anything: an observed refusal is not an inference about assistant crawlers, HTTP 403 on /robots.txt is not proof the file is absent, one barrier is one finding rather than one per rule that trips over it, recommendations resting on an inference are conditional, and a run that read no page makes no claim about content and scores the pillars it could not measure as `None` |
| `test_page_type_provenance` | One classification, consumed by everything downstream: a product detail page never entering the filter or sort checks, the listing rules following the canonical `page_type` rather than the page's content, ambiguity resolving to neither type, and a missing home-page link not being reported as an unreachable catalogue when the sitemap found it |
| `test_page_types` | The product/listing/other taxonomy on fourteen unrelated synthetic domains: an individual product page, a multi-product shopping page, a category, a curated collection, a promotional landing page quoting prices, a genuinely ambiguous page, a storefront buying route, a comparison page, a priced service page — plus the shapes detection has to survive (markup-only, markup-free, a related-items rail, a declared variant family) and one test per isolated signal that must never decide alone |
| `test_specialist_reliability` | The data-shape contract at the bundle boundary, exercised through the real extractor: `microdata` is a list of item records and the entity specialist reads it as one; every specialist survives every shape schema.org permits (list-valued properties, `@graph`, top-level lists) and the report still validates; and a specialist that raises is recorded as `failed` with `findings: null`, its pillar scores `unmeasured`, the other five keep their findings, `specialist_coverage` reads `partial`, and the progress line never prints `0 finding(s)` for it |
| `test_product_identity` | Product identity from item-scoped evidence only: a declared entity, a microdata item, an Open Graph product card, or a heading the page's title or URL slug corroborates - and, one negative fixture each, never a heading that is one of the page's own control labels, a navigation link, a section label, a component name, a string the template repeats, the site's own name, or a promotion; genuine names, variant families sharing a declared name, and duplicate-name detection on declared names all still work |
| `test_sitemap_semantics` | Sitemap evidence bounded by what was probed: every conventional location 404 (established, with the internal-linking consequence and the missing directive as a separate finding), one valid sitemap, one declared in robots.txt, a malformed declared one (broken, not absent), transport failures (unchecked, never absent; a declared sitemap that timed out is *unread*), and a sitemap at a path nobody probed - the finding never claims the site has none |
| `test_semantics` | The semantic layer as units: a page's kind from its markup and its words (and never from its URL - the same page at `/products/`, `/downloads/` and `/plans/` reaches the same verdict), what a listing is a listing of, the shape of a site, every `is_*_applicable` decision with its reason and basis, heading assessment, outbound-link classification, entity relationships, the transport verdict, and the guarantee that computing any of it never edits the bundle it was handed |
| `test_contextual_findings` | The sixteen areas where a finding now follows the kind of thing a page is about: commerce expectations gated per page, typed policy markup, transport uncertainty, sitemap wording, cross-host canonicals, redirect semantics, page-type-aware freshness, contextual `Organization` fields, optional Open Graph, noindex wording, heading semantics, evidence-based site search, answerability gating, severity ceilings, endpoint classification, and the coverage block that reports what was *not* applied |
| `test_entity_relationships` | Which names belong to the site: a department, a subsidiary, an agency, a tribunal, a product's brand, a manufacturer, a third-party seller, a former trading name, and the same name in another language or script - none of them a rival spelling. Plus link classification (a profile, a knowledge entry, a documentation host, a store listing, a repository, a locale variant, a share intent) and the difference between a profile that 404s and one a platform declined to show |
| `test_recommendation_applicability` | Advice belongs to a kind of site: a documentation site, a publisher and a public body are never offered variant markup, a product feed, typed return policies or comparison pages; the worked examples follow the site's shape; and every emitted recommendation states what about this site satisfied its conditions |
| `test_portability` | The two platform assumptions that broke a Windows run: CLI entry points printing a report a legacy console cannot encode (reproduced anywhere by forcing the child's stdout to cp1252), and the claim scanner spelling paths with the platform separator |
| `test_provenance` | Advice about a page evidenced on that page or on its own items: a listing's members resolved from its body links, attributes and order dimensions read only from those members, the reported cross-page leak reproduced on an invented fixture, the four observations that delimit a set, negative proof for a product-family page, a marketing page and every non-commerce shape, and a comparison question that stays inside one listing |
| `test_rendered_evidence` | Optional browser-rendered evidence: the four raw/rendered comparison states and the difference between "rendered absent" and "not measured"; that nothing is fabricated when Playwright is missing, the browser fails, a page times out or a redirect lands out of bounds; deterministic bounded selection; the robots, private-address, read-only and no-network guarantees; and a real headless render of the `site_rendered` fixture end to end through the CLI |
| `test_false_positives` | Precision: the centralised report/downgrade/suppress decision; price extraction, including the currency codes that spell English words (`TRY`, `PEN`, `COP`); a listing whose item set cannot be delimited being downgraded rather than advised; commerce expectations following the product subtype; answerability generating no question whose subject the site does not support; endpoints, facet permutations and outbound links not being mistaken for content, defects and profiles; and one golden fixture asserting both what must be reported and what must not |
| `test_recommendation_precision` | A downgraded finding's *recommendation* is conditional too: the seven applicability cases (a known catalogue may name what its members publish; an undelimited one names nothing and says so), the invariant that no downgraded finding carries an imperative about the half that was missing, and the corroboration mechanism - two rules measuring different properties of one page stay separately visible while the score is charged once, and findings about different pages are never linked |
| `test_claim_scanner` | The claim scanner from both directions: eighteen unsupported external-AI claims that must be rejected, and four classes that must not be — measured evidence, qualified inference, educational or hypothetical explanation, and labelled optional external validation — plus proof that the scan reaches every shipped Markdown and reference file |
| `test_site_type_semantics` | One invented site per semantic type — shop, subscription service, software vendor, documentation, publisher, audio publisher, public body, knowledge reference, developer platform, booking site, forum, nonprofit — asserting over the rendered text of every finding and recommendation that commerce vocabulary never reaches a site that sells none, that commerce checks still fire where goods are sold, that a repository index and a glossary are not catalogues, and that a not-applicable question is never a finding |
| `test_semantic_fixture` | One mixed site audited end to end, with all twenty-five of its elements asserted against the report the pipeline actually produced |
| `test_canonical_eligibility` | Canonical findings made about content pages chosen by page evidence: a search endpoint, an ambiguous page, a noindexed page and a URL that redirected onto the home page are set aside and counted; a product, a category, a policy page and an address-normalising redirect are assessed; ineligible pages can neither create nor inflate the ratio |

## 8. The answerability matrix — the part nobody else has

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/collect_evidence.py --offline mixed --out /tmp/b.json
python3 skills/answerability-audit/scripts/analyze.py --bundle /tmp/b.json --matrix
```

Every other check in this marketplace audits a *mechanism*. This one audits the
*outcome*: it generates questions from the site's own catalogue — "What is the
price of X?", "Is X in stock?", "What is the cheapest item in C?" — resolves
each against the frozen bundle, and returns `answerable` / `partial` /
`not_answerable` with the URL it read and the snippet it found.

Two properties make it defensible: questions are only generated when the crawl
observed their subject (no product, no product question; a documentation site
is asked no commerce questions at all, and the matrix says why), and every
verdict cites its source. `partial` is the interesting state — the fact is on
the page but only as prose, which is exactly the gap between a page a person
can use and evidence a system can quote.

## 9. Does it claim more than it measured?

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py --offline mixed --quiet \
  | python3 -c "import sys,json; f=json.load(sys.stdin)['findings'][0]; \
    print(f['observation'],'\n---\n',f['interpretation'],'\n---\n',f['suggested_action']['summary'])"
```

Every finding is emitted as three separate fields — `observation` (what was
measured), `interpretation` (what it may mean) and `suggested_action` (what to
do) — and the model **rejects** a finding whose `observation` asserts a
consequence a static audit cannot see. A rule claiming a visitor bounced, or
that something was above the fold without a headless render, does not get
downgraded: it never reaches the report, and appears in
`diagnostics.rejected_findings` instead. `suggested_action.verification_type`
separates a step you can re-run with `curl` from one that needs a third party
(`external_validation`) or analytics you have and the audit does not
(`requires_external_data`).

Worked examples are assembled per-run from the crawled site's own names,
categories and attributes (`lib/aiva/examples.py`), falling back to
`<Placeholder>` slots when nothing was observed. No rule hardcodes a product,
brand or attribute, and `test_cocoacraft_regression` fails the build if a
report mentions a website the auditor did not crawl.

## 10. Where to read the thinking

The rubric is about the reasoning encoded in the skills, so the design lives in
the `references/` directories rather than in code comments:

| File | Why it is worth a minute |
|---|---|
| `skills/marketplace-ai-visibility-audit/references/orchestration.md` | the composition contract and its three structural guarantees |
| `skills/marketplace-ai-visibility-audit/references/severity-and-priority.md` | why severity and priority are different fields, and how confidence is derived |
| `skills/crawl-render-audit/references/checks.md` | the AI-crawler token catalogue — and why blocking `ChatGPT-User`/`Claude-User` is the mistake nobody means to make |
| `skills/machine-readability-audit/references/checks.md` | what each schema.org field lets an assistant answer, and the four ways structured data fails |
| `skills/freshness-corroboration/references/checks.md` | why updating your own site does not remove the old fact from the web |
| `skills/entity-audit/references/checks.md` | entity resolution, under- vs over-merging, and variant modelling |
| `skills/engagement-audit/references/checks.md` | the continuity model behind the bounce |
| `skills/marketplace-ai-visibility-audit/references/interpreting-results.md` | what a 100/100 does *not* mean |

## 11. Auditing a real site

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py https://<site> \
    --out ./audit --format both
```

Read-only and polite by construction: GET/HEAD only, robots.txt obeyed (including
`Crawl-delay`), sequential requests with a minimum gap, a 40-page cap, a 3 MB
response cap and a 240-second budget. It cannot log in, cannot submit anything,
and cannot change the site. Add `--render` to collect browser-rendered evidence
alongside the raw fetch, if Playwright happens to be installed; the audit is
complete without it, and the report says which of the two it measured.

Rendering obeys the same rules as the fetcher rather than a copy of them: every
navigation target passes `EvidenceStore.allowed` (robots.txt for this auditor's
own token, plus the private-address rule), a route guard holds the browser's own
subresource requests to it, and a redirect that lands out of bounds discards the
render. It is navigate, wait, read — never a click, a form or a stored session.
It is bounded too: `--render-pages` (default 3) pages, 15 s each, 60 s in total,
with images, media and fonts aborted, so a rendered run of the bundled fixture
adds about 3 seconds. Selection is deterministic: pages already showing
client-rendering signals first, then products, then listings, then home, then by
URL.

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py \
    --offline rendered --render --render-pages 4
```

The `site_rendered` fixture is built for exactly this: its price, stock, rating,
specification table and catalogue controls all arrive after hydration. Without
`--render` the audit reports them absent — correctly, of the response. With it,
`CR-RENDER-FACT-GAP` names which facts the response omits and
`EG-CONTROLS-RENDERED-ONLY` replaces "this listing exposes no filter control"
with the truth: the control is in the browser state and not in the response.
The score with rendering is *lower* than without, because the pass adds a
finding rather than removing one.

## 12. The brief's constraints, one assertion each

Every non-negotiable in the problem statement is a test, not a claim in a
README. `tests/test_compliance.py::TestBriefConstraints` is written as this
checklist so it can be read straight down.

| Constraint | Asserted by | How |
|---|---|---|
| Read-only auditing only | `test_safety.TestReadOnly` | the HTTP client exposes only GET/HEAD; unsafe methods raise |
| No authentication or security bypass | `TestBriefConstraints.test_no_authentication_or_transactional_surface_is_ever_requested` | login, account, cart, checkout, `wp-admin`, `wp-login.php` and friends can never enter the frontier |
| No modification of the target | `test_safety.test_auditing_does_not_modify_the_target` · `TestBriefConstraints.test_no_code_submits_a_form_or_writes_to_the_target` | fixture directory hash unchanged after an audit; no `.post/.put/.patch/.delete` call exists in the package |
| No credentials sent | `test_safety.test_no_credentials_are_ever_sent` | checked against the parsed AST, not by grep |
| robots.txt respected | `test_safety.TestRobotsCompliance` | a site that disallows everything is not crawled; `Crawl-delay` is honoured; compliance cannot be switched off in config |
| No chatbot, no recommendation engine | `TestBriefConstraints.test_the_package_ships_no_conversational_or_ranking_surface` | nothing reads stdin or calls `input()`; the only ranking orders *findings* by remediation priority |
| Exactly one entrypoint skill | `test_compliance.test_exactly_one_entrypoint` | over `marketplace.json` |
| Specialists are internal | `test_compliance.test_one_specialist_per_pillar` · `test_no_undeclared_skill_folder` | six specialists, one per pillar, none marked entrypoint |
| Evidence gathered once and reused | `test_e2e.test_no_url_is_fetched_twice` · `test_specialists_share_one_bundle` · `TestBriefConstraints.test_specialists_receive_a_bundle_and_cannot_fetch` | requests equal unique URLs; every specialist is `analyze(bundle)` and imports no network module |
| Never invent evidence | `test_rules.test_no_evidence_string_asserts_an_unmeasured_consequence` · `TestBriefConstraints.test_no_finding_can_be_emitted_without_evidence` | every rule's prose is scanned for unmeasured-consequence phrasing; the schema requires ≥1 evidence item |
| Recommendations are actionable | `TestBriefConstraints.test_every_recommendation_states_steps_and_a_way_to_check_it` | every action carries a summary, steps, an effort estimate and a verification |
| Deterministic | `TestBriefConstraints.test_the_same_bundle_always_produces_the_same_report` | two runs over one bundle serialise identically |
| Offline-compatible, no LLM / API / dependency | `test_compliance.test_no_third_party_runtime_dependency` · `test_no_model_weights_or_binaries` | stdlib-only import graph (Playwright optional and guarded); no weights ship |
| Inside the 5-minute budget | `test_e2e.TestRuntimeBudget` · `TestBriefConstraints.test_the_configured_budget_cannot_exceed_the_brief` | measured elapsed time, and a config that exceeds 300 s fails validation |
| The budget is actually spendable | `TestBriefConstraints.test_the_crawl_budget_is_actually_spendable` · `test_core.TestFrontierSampling` | the sampler reaches `max_pages` whatever the site's URL vocabulary |
| Report schema floor | `test_compliance.test_report_schema_requires_the_brief_floor` | the shipped schema requires exactly the brief's fields |
| A refusal is never reported as a site defect | `test_hardening.TestHttpsUpgradeIgnoresRefusals` · `TestHeadlineHonesty` | a 401/403/407/408/429/451/5xx probe, or a transport failure on robots.txt, disqualifies the canonicalisation rules; a run with no parsed page reports `coverage_state: transport_only` and says so in the headline |
| No third-party service is ever queried | `test_compliance.test_no_third_party_runtime_dependency` · `test_safety` | only the audited site and the anchors it declares are fetched; off-site corroboration ships as recommendations, not findings |
| No impersonation | `test_hardening.TestUserAgentOverride` | `--user-agent` values matching a browser or a named crawler are rejected by config validation before a socket opens |
| Agent Skills spec | `test_compliance.TestSkillFiles` | name, description, licence, compatibility, metadata and `allowed-tools` limits for all seven skills |

## 13. Does the verdict depend on the site's URL scheme?

No — and there is a test that fails if it starts to.

```bash
python3 tests/run_tests.py e2e -v 2>&1 | grep VerdictDoesNot -A 8
```

`test_e2e.TestVerdictDoesNotDependOnUrlVocabulary` builds the *same* broken
storefront twice — once at `/products/…` and `/collections/…`, once at
`/shop/…` and `/range/…` — audits both, and asserts they spend the same crawl
budget, recognise the same catalogue and reach the same band.

This was a real defect. The crawl budget was handed out against
`classify_page(url)`, a guess made *before* anything was fetched, with a quota
per predicted type. A store that did not use Shopify-style URLs had its whole
catalogue filed under `other` (quota 4), so the audit fetched **5 pages of a
40-page budget**; every ratio in the report was then computed over almost
nothing, and the sample-size guards correctly declined to generalise from it —
so the identical broken site scored **57.1 "weak"** instead of **28.3
"critical"** purely because of how it spelled its URLs. The quotas now govern
only the first round; the remainder is handed back out round-robin, and page
type is re-read from the markup once the page is in hand.
