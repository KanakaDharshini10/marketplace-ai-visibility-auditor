# Changelog

All notable changes to `marketplace-ai-visibility-auditor`.
The README carries the current design; this file carries how it got there.

**1.11.2** — Recommendation precision. A patch, not a change of direction:
no architecture, no scoring weight, no security control and no semantic model
was touched, and all five fixtures return identical verdicts.

**A cautious title was carrying an assertive recommendation.** 1.11.1 made a
finding's title follow its applicability — a listing whose item set could not be
delimited was retitled "sort controls could not be assessed against a known
comparable set", lowered to `low`/0.4 and stripped of named attributes and
dimensions — but its recommendation still read "Add a sort control to category
listings", an instruction that presumes exactly what the title says was not
established. A reader acts on the recommendation, so that is where the caution
has to arrive. `analysis.conditional_advice` is now the one place that enforces
it: on a downgrade the assertive action body is swapped for a conditional one
phrased against what the page would have to be intended as. The filter and sort
findings now say *"Because the comparable item set could not be established, no
specific filter attribute can be recommended"* and *"If this page is intended to
function as a catalogue of comparable items, make its members readable … then
expose ordering controls only for values actually published by its members"*.
Their priority drops to `low` with the rest of the verdict. The general rule: a
DOWNGRADE finding's recommendation may describe what was observed, and may not
introduce a dimension, attribute, intent or business requirement that was not.

**Two rendering findings read as one defect.** `CR-JS-RENDERED-SHELL` and
`CR-JS-CONTENT-GAP` fired together on the same page with near-identical titles.
They are *not* duplicates — one reads the server response alone and reports the
delivery architecture (an unfilled mount point, under 120 words); the other
needs a browser and reports magnitude (rendered words against response words) —
and each can fire without the other. So neither was deleted. They are retitled
to say which is which ("Page content is delivered through an empty
client-rendering shell" / "Browser rendering reveals substantially more content
than the server response"), each declares what it measures and what it measured
*from*, and the gap finding points the reader at the shell finding.

What was wrong was the scoring: one site owner performs one piece of work to
answer both, so charging the pillar twice said the page was twice as bad as it
is. `report.link_corroborating` is a centralized relationship — a rule declares
`metrics["corroborates"]`, the link is made only when the named rule is also
present *and* the two share an affected URL, and the corroborating finding's
penalty is dropped while it keeps its severity, its evidence and its place in
the report. Two findings about different pages are still two findings.

**One host is often several things.** The report's coverage block now lists the
site shapes the sample supports beside the one that was chosen —
`observed_contexts` — so a low-confidence "publisher" no longer hides that
commerce, support and corporate content were observed too. This is purely
additive: it reads scores `semantics.site_context` already computes, no
expectation or gate consults it, and `site_kind` is unchanged. `semantics.py`
was not opened.

`tests/test_recommendation_precision.py` (26 tests) covers the brief's seven
recommendation cases, the corroboration mechanism including the cases where it
must *not* link, the two rendering findings end to end on a bundle carrying both
conditions, and the 1.11.0 rendered-evidence contract unchanged.

**1.11.1** — False-positive reduction and applicability refinement. No
architecture changed, no module was replaced and no score was optimised. The
release is one principle, applied in four places:

> an auditor reports a semantic defect only when **both** the observed
> condition and its applicability are supported by evidence

Absence of evidence is not evidence of absence, and detecting a pattern
establishes only the first half.

**A trial offer was being read as a product's price.** `TRY` is the ISO code
for the Turkish lira and the price pattern was case-insensitive, so "Try 7 days
free" matched as a price of 7 - and on a page whose only price-shaped string
was that offer, the audit reported the product's price as `try 7`. The same
collision exists for `PEN` (a pen), `COP` (a cop) and `RON` (a name).
Alphabetic currency codes now match in their canonical case only: `TRY 7` is
still a price and `try 7` is a sentence. Price records also carry a
`confidence` - `high` for a currency symbol, which no word spells, `medium` for
an alphabetic code, which could also be a model designator - and the
answerability matrix states an uncertain reading as uncertain instead of
asserting a number recovered from an ambiguous token.

That one fix removed two further findings on the reproduction fixture, both
correctly: with no false price, the page's own subtype resolves to
`informational` ("no price, offer or purchase control: the page describes the
item without offering it for sale"), so `MR-OFFER-MISSING` and
`AN-UNANSWERABLE-PAYMENT-OPTIONS` no longer apply to it. They were resting on
the false price, and the existing semantic subtype model stood them down
without a single new suppression rule.

**Report, downgrade or suppress is now one decision.**
`analysis.applicability_verdict` is the single place that weighs the two
halves: both evidenced is REPORT, an unestablished condition is SUPPRESS, and a
real observation whose interpretation is uncertain is DOWNGRADE - severity
capped at `low`, confidence capped at 0.4, the evidence saying which half is
missing, and every claim that rests on the missing half withdrawn. Confidence
now follows applicability rather than the detector: a filter control is
*certainly* absent from a page whose item set is *not* established, and the
number a reader sees describes the weaker of the two.

**A listing whose item set cannot be delimited is no longer advised.** Both
control findings still fire - the missing affordance was observed either way,
and a shop whose crawl reached only its listings must not be silenced - but on
an undelimited set they are retitled "Filter/Sort controls could not be
assessed against a known comparable set", lowered to `low`/0.4, and name no
attribute and no ordering dimension. The ordering dimension in particular was
tightened: until 1.11.1 prices printed on the listing page itself were accepted
as evidence for "sort by price", which is a claim about items the page may not
represent. The chain is now listing -> members -> observed value, or nothing is
named.

**Two noindex exclusions were missing.** A `tool` endpoint (a configurator, a
planner) was reported for carrying `noindex` because the utility list here had
drifted from the one the canonical rule uses; both now read one shared tuple.
And a faceted listing's permutations - `?colour=black&size=9` - were counted as
pages losing their index place. They are recognised now by the site's *own*
statement rather than by guessing parameter names: a URL with a query string
whose declared canonical is a different URL is the page saying the document
worth indexing is elsewhere.

**One ratio did not name its population.** `MR-BREADCRUMB-MISSING` reported
"8 of 8" with no statement of what the 8 were. It now names the composition,
and does so without claiming every cited URL is a product page.

Audited and found already correct, so left alone: outbound-link and `sameAs`
classification (only `rel=me`, a known profile host with a handle, or an
organisation root reaches `official_profile`; locale variants are
`localization`, never a rival trading name), canonical eligibility, the
contextual `Organization` property expectations, the Open Graph wording, and
the semantic H1 assessment. The browser-rendered evidence of 1.11.0 is
untouched: a rendered-only fact is still reported as absent from the *response*
rather than from the page, and a raw-HTML finding is never deleted because
Playwright saw the content.

`tests/test_false_positives.py` (58 tests) and `shapes.golden_site()` - one
host carrying a physical product, a download, a plan, a service, an article,
documentation, public-sector guidance, a genuine catalogue, an ambiguous
listing, a product-family page, a comparison page, a localized page, a
rendered-only fact, a search endpoint and a facet permutation - assert what
must be reported *and* what must not. All five existing fixtures return
identical findings, severities, scores and answerability scores.

**1.11.0** — Optional browser-rendered evidence. The audit's evidence is still
the server response, and every default is unchanged: without `--render` this
release behaves exactly as 1.10.2, stdlib-only, with no browser anywhere near
it. What is new is that an *absence* can now be qualified. "Not in the HTML a
fetch receives" and "not on the page" are two observations, and reporting the
second when only the first was measured is wrong in a way a site owner can see:
the rating is there, it arrives after hydration.

**One extractor, two states.** With `--render`, a bounded subset of pages is
opened in headless Chromium and the resulting DOM is put through
`aiva.extract.extract_page` — the same extractor the raw fetch uses — so each
rendered page carries a fact bag of the same shape as its raw one. No rule
downstream learns anything about browsers: `analysis.fact_visibility(page,
probe)` asks one predicate of both and returns one of six states —
`server_and_rendered`, `server_visible`, `rendered_only`, `structured_only`,
`not_observed`, `render_unavailable`. `render_unavailable` is deliberately not
`not_observed`: "we looked in the browser and it was not there" is a different
fact from "we did not look", and the report says which it is.

**Rendering is not a second crawler.** Every navigation target goes through
`EvidenceStore.allowed` — the same robots.txt and private-address gate the
fetcher obeys — a request-level route guard applies that rule to every
subresource and client-side navigation the page attempts, and the URL the
browser actually landed on is re-checked afterwards, so a redirect out of
bounds discards the render instead of reporting it. It is navigate, wait, read:
no click, no form submission, no typing, no stored state, and the auditor's own
honest User-Agent.

**Bounded and deterministic.** At most `--render-pages` pages (default 3),
15 s per page, 60 s for the whole pass; images, media and fonts are aborted;
rendered text is capped at 20 000 characters and no screenshot or raw HTML is
stored. Selection is by documented priority — pages already showing
client-rendering signals, then products, then listings, then home — then URL,
so it never depends on crawl timing or dict ordering. Three consecutive runs of
the bundled fixture select the same four pages and emit the same findings.

**What it corrects.** `CR-RENDER-FACT-GAP` names *which* audited facts the
response omits and the rendered DOM carries (the existing `CR-JS-CONTENT-GAP`
measures only the size of the difference). A listing whose facets mount after
hydration is no longer told it "exposes no filter control": it gets
`EG-CONTROLS-RENDERED-ONLY` instead, which says the control is in the browser
state and not in the response. Answerability keeps its existing semantics — the
question is about the document the site returns — but a `not_answerable` verdict
now says when the value was seen in the rendered state, and the matrix notes
which selling facts the response is missing. Every absence finding says whether
the browser was looked at.

**It does not flatter a site.** On the bundled `site_rendered` fixture the score
with rendering is *lower* than without, because the rendered pass adds a real
finding rather than removing one. No scoring, severity or schema changed.

`tests/test_rendered_evidence.py` (47 tests) covers the comparison states, the
unavailable/failed/timeout/refused paths, deterministic bounded selection, the
robots, private-address, redirect and read-only guarantees, and a real headless
render of the new `site_rendered` fixture end to end through the CLI. Nothing
is skipped: where Playwright is absent, the same tests assert the unavailable
contract instead.

**1.10.2** — Evidence provenance for listing advice. A live audit recommended
that a handset family page add filters on *Diameter*, *Height* and *Operating
ambient temperature* — three attributes read off a locator-tag product page
elsewhere in the same crawl. Nothing was wrong with the observation; it was an
observation about a different entity. Two rules were describing items they had
never connected to the page they were advising.

**Attributes now come from the listing's own items.** `analysis.listing_members`
resolves a listing's body links — chrome and pagination excluded — against the
pages the crawl actually read, and `analysis.catalogue_vocabulary` reads the
worked example's attribute names from those members and nothing else. Where no
member page was read the vocabulary is empty and the step names no attribute at
all, saying which of the two situations it is: the products were not read, or
they were read and publish nothing to filter on. `EG-SPECS-MISSING` and
`MR-ATTRIBUTES-THIN` had the same gap in a milder form — both say "the
attributes these pages already publish" while reading the whole crawl — and both
now read the pages the finding is actually about.

**Order dimensions are evidenced too.** "Add sorting by price and by rating" is
a claim that both values exist across the set. `analysis.orderable_dimensions`
names a dimension only where the value behind it was observed — a price on the
listing or on a member, an AggregateRating on a member — and where neither was,
the step says to publish a value to order on instead of asserting two.

**A listing states what set it represents.** `analysis.collection_provenance`
records which of four observations delimits the set: members read, a declared
`ItemList`, pagination, or catalogue controls already present. Both control
findings carry it in their evidence and metrics. Where none holds, the finding
still reports the missing affordance — that absence was observed — and says
plainly that the set could not be delimited, so it describes no item. It
deliberately does not try to tell a catalogue listing from a product-family or
marketing landing page by shape: on the evidence a crawl has, the two are the
same page, and guessing between them would be a heuristic about page design
rather than a statement about what was observed.

**A comparison question stays inside one listing.** Pairing by product kind put
a boot and a cable accessory in one question — both physical goods, nothing else
connecting them — and then recorded "they share no attribute" as an
answerability gap for a comparison the site never invites. Membership of one
listing is now preferred, kind remains the fallback, and the row says which of
the two it is.

`tests/test_provenance.py` (33 tests) holds all of it, including the reported
failure reproduced on an invented fixture. All five fixtures return identical
findings, severities, scores and answerability scores.

**1.10.1** — Windows portability. A Windows run of this release reported four
failures, all from platform assumptions that Linux happens to make true. No
rule, score, schema, threshold or piece of audit logic changed; the report a
run produces is byte-identical once the timestamp, the loopback port and the
soft-404 probe nonce are normalised, and all five fixtures return the same
findings at the same severities.

**Three CLI entry points died printing a valid report.** The weak fixture
prices its goods in rupees, and cp1252 - the code page a default Windows
console gives a Python process - has no code point for U+20B9, so
`run_audit.py`, `compose_report.py` and the answerability specialist raised
`UnicodeEncodeError` mid-write and exited non-zero. One helper,
`aiva.util.use_utf8_stdio()`, now reconfigures stdout and stderr to UTF-8, and
every one of the ten CLI entry points calls it as the first statement of
`main()`. It reconfigures the existing stream rather than wrapping it, so the
descriptor, the buffering and any redirection are untouched; it leaves the
error handler strict, because the point is to write the characters rather than
to substitute them; and where stdout is already UTF-8 it does nothing at all.
`TextIOWrapper.reconfigure` is stdlib from 3.7, so the floor stays 3.9.

**The claim scanner spelled paths two ways.** `str(PurePath)` uses the platform
separator, so a scanned file was `docs\WALKTHROUGH.md` on Windows and
`docs/WALKTHROUGH.md` everywhere else, and a scope assertion that named the
POSIX spelling failed. One boundary helper, `_relative()`, now renders every
scanned path with `as_posix()`, and both the offender messages and the scope
assertions go through it. Nothing left the scan: the scope is unchanged, no
exemption was added, and `docs/WALKTHROUGH.md` is still read for unsupported
claims.

**Both failures are now reproduced on every platform.**
`tests/test_portability.py` (20 tests) runs the CLI entry points in a child
process whose stdout is forced to cp1252 with `PYTHONIOENCODING` - exactly the
condition a Windows console creates - and asserts each exits zero, that the
rupee sign survives round-trip as UTF-8 bytes, and that decoding those bytes as
cp1252 does *not* reproduce it. It also asserts the helper has exactly one home
and ten callers, that it is a no-op on an already-UTF-8 stream and on a
`StringIO` a test installed, and that it survives a detached stream. The path
half feeds a genuine `PureWindowsPath` root and path through the boundary
helper and requires POSIX output. The end-to-end tests now decode their child's
output as UTF-8 explicitly rather than trusting the runner's locale.

**1.10.1** — precision pass over what the package *says*. Delivered in two
parts: the semantic and documentation pass below, then a final claim sweep that
replaced the phrase list's blind spot with a pattern rule.

**The claim scan reads prose, not source, and matches a shape rather than a
list.** The phrase list is exact and grows one entry at a time; it cannot catch
a claim nobody has written yet. A second rule now matches *an external subject
followed by an indicative behaviour verb* - "assistants will", "retrieval
matches", "extractors weight", "AI cannot see" - which is the shape every
unsupported claim takes. Three exemptions keep it from rejecting the project's
own subject matter, each with its own regression test: a phrase inside quotes
or backticks is being named; a sentence carrying a disclaimer ("not something
this audit measures") is doing the right thing; and a hypothetical or
conditional clause asserts nothing. Capability and definition verbs (`can`,
`is`, `has`) are deliberately outside the rule, because "a machine can read
plain text" and "machine-readable" are statements about evidence.

Scanning Python needed one correction to be meaningful: a rule's mechanism
sentence lives inside a string literal, and the literal's own quotes were
exempting every sentence in every specialist. The scan now extracts docstrings,
string literals and comments with their delimiters stripped, so the prose is
scanned as prose. Thirteen further statements failed once it could see them and
were rewritten - among them "robots.txt is the first file a retrieval crawler
fetches" and "a directive a crawler does not understand is silently skipped",
both now attributed to RFC 9309, which is a citable standard rather than an
observation of anyone's crawler; "most retrieval fetches are a plain HTTP GET",
now a statement about the fetch *this audit* makes; "retrieval matches a user's
question against text"; "the summary a fetcher takes"; and "blocking an
answer-time fetcher is what most directly keeps a brand out of answers".

An external-validation step now carries its own caveat in the rendered report:
a result obtained by asking an assistant is one observation, may vary by model,
phrasing, date and configuration, is not part of the score, and is not evidence
this audit collected.

`tests/test_claim_scanner.py` drives the detector from both directions - 18
sentences that must be rejected, and four classes that must not: measured
evidence, qualified inference, educational or hypothetical explanation, and
labelled optional external validation. A repository-wide scan reports **0**
unsupported claims across 60 shipped files, with every allowed match attributed
to one of the three documented exemptions.

**1.10.1** — precision pass over what the package *says*. 1.10.0 made the
findings semantic; this release makes the shipped prose and the last
site-shaped recommendations match. No architecture changed: the crawler, the
evidence bundle, the six specialists, the schemas and every transport guard are
byte-identical to 1.10.0, and the four bundled fixture sites score exactly what
they scored before. 1073 tests (1037 before).

**The claim scan now reads every shipped document, not only the rule code.**
`test_compliance` scanned `analyze.py` and eight library modules; a reference
document that says an assistant *will* do something is the same unmeasured
claim read by the same person, so the scan now covers every `SKILL.md`, every
`references/*.md`, the README, the changelog, the walkthrough, the example
report and the whole of `lib/aiva`. It also matches on word boundaries (a
"dead sitemap entry" is not a "dead site") and treats a phrase inside
quotation marks or backticks as *named* rather than asserted — which is how a
changelog can record the wording it removed, and which makes "quote it if you
name it" the enforced convention. Forty-one passages failed the extended scan
on first run and were rewritten: "retrieval systems answer questions about
entities" became a statement about what a page declares about its own
identity; "machines treat a fact as more trustworthy when many places say the
same thing" became the three gaps the rule actually measures; "extractors
weight it heavily", "an assistant cannot quote it", "the summary a fetcher
gets", "assistants use a different set of crawlers", "crawlers learn to ignore
the field" and the rest each became a statement about the page's own evidence.
Twenty-four new phrasings joined the banned list.

**Optional external validation is labelled as optional and external.** The
report data already separated `self_verifiable` from `external_validation` and
`requires_external_data`; the rendered Markdown introduced all three with the
same "*Verify:*", so a step that asks an assistant a question read like
something the audit had checked. Each type now has its own label — "*Optional
external validation — outside this audit's measured behaviour:*" — and
proactive recommendations render their verification step at all, which they
previously did not.

**`EG-FAQ-MISSING` asks about the questions this site's readers actually
bring.** It told every site to "mine support tickets, on-site search and
marketplace Q&A" and to "put product-specific questions on the product page".
A new `high_value_question_intents(ctx)` derives the topic families from the
same site context every other rule reads — delivery and returns for a site
that sells goods; installation, configuration and versions for documentation;
eligibility, process and deadlines for a public body; plans and limits for a
subscription; amenities, location and cancellation for a stay; definitions and
sources for a reference work — and the finding names the families it derived
and the evidence for each. Where the audit can characterise nothing about a
site, it now asks for no questions at all rather than guessing. Its
verification step is `curl`-checkable instead of "ask an assistant".

**Four site kinds whose expectations genuinely differ.** `travel_hospitality`
(a stay is not a parcel: amenities, location, availability, cancellation and
booking constraints apply, delivery and returns do not), `developer_platform`
(a list of repositories is not a catalogue), `knowledge_reference` (definitions
and datasets, which sell nothing) and `nonprofit`. Each is scored from declared
types only, in the same table as every existing kind, with the same evidence
sentences. Three names an operator might expect were deliberately *not* added,
because the concept is already here under an older spelling: `software` covers
both a software vendor and SaaS (`sells_subscriptions` distinguishes them),
`government` is the public-body kind, and `services` is the service-business
kind. An audio index is recognised as `audio_listing` through the existing
listing vocabulary, and a listing whose entries are episodes, definitions,
datasets or repositories is no longer classified from its links as `unknown`.

**Three remaining ecommerce assumptions in shipped text.** A home page with no
crawlable links said "the rest of the catalogue is unreachable"; the
third-party correction step named a "merchant portal"; and the referral
recommendation asked every site to keep "the answer, the price, the step"
above the fold — now the decisive fact *for that kind of page*: the step or
the command for documentation, who is eligible and what to do next for a
public body, where it is and what it includes for a stay.

**A regression module per semantic site type.** `tests/shapes.py` builds
eleven invented sites — a shop, a subscription service, a software vendor, a
documentation set, a publisher, an audio publisher, a public body, a
knowledge reference, a developer platform, a booking site, a forum and a
nonprofit — and `tests/test_site_type_semantics.py` asserts, over the
*rendered text of every finding and every recommendation*, that no parcel
vocabulary reaches a site that sells none, that commerce checks and commerce
advice still fire where goods are sold, that a repository index and a glossary
are not catalogues, that a not-applicable question is never a finding, and
that every recommendation still makes sense with the domain removed. The same
property is asserted as a compliance rule so a new rule cannot reintroduce the
leak unnoticed. None of these fixtures is named after or keyed to any real
site: each is a shape.

**1.10.0** — semantic applicability. Page type is not enough: a walking boot,
a software licence, a monthly plan, a boiler service and a manufacturer's
information page are all *product pages*, and only the first is delivered in a
box, kept in stock or sent back. Audited against a generic mixed site, the
previous release asked a download when it would arrive, told a documentation
site to model size variants, reported a Japanese rendering of the site's own
name as a competing brand, called a rate-limited URL a broken one, and scored
that site 23.6/100 "critical" on thirty-five findings, most of which were
expectations that did not apply. This release adds one semantic layer, asks it
everywhere, and makes every rule say what it set aside and why. 1033 tests
(833 before). No rule was deleted, no schema field removed, no CLI flag
changed; the security posture is unchanged.

**`lib/aiva/semantics.py`, the one place a page's kind is decided.** Product
subtype (`physical`, `digital`, `software`, `subscription`, `service`,
`marketplace_listing`, `informational`, `ambiguous`) from declared types, typed
properties, the offer's shape and the page's own words — never from words in a
URL, which is asserted directly: the same page at `/products/…`, `/downloads/…`
and `/plans/…` reaches the same verdict. Listing subtype (`ecommerce_listing`,
`content_listing`, `documentation_section`, `article_index`, `audio_listing`,
`service_listing`, `software_catalog`, `marketplace_listing`, `unknown`) from
`ItemList` entry types and from what the crawl read at the other end of the
listing's *body* links — the site's navigation is the same on every page and
now says nothing about what a listing lists. Site kind (`ecommerce`,
`marketplace`, `software`, `services`, `documentation`, `publisher`,
`government`, `education`, `community`, `corporate`, `mixed`, `unknown`) with
its evidence printed in `coverage.site_kind_evidence`.

**An applicability engine, not scattered conditionals.**
`is_shipping_applicable`, `is_returns_applicable`, `is_stock_applicable`,
`is_physical_specs_applicable`, `is_reviews_applicable`, `is_price_applicable`,
`is_identifier_applicable`, `is_purchase_cta_applicable`,
`is_comparison_applicable`, `is_site_search_expected`, `is_breadcrumb_applicable`
— each returns a decision, a reason, a basis (`declared`, `observed`,
`inferred`, `unknown`) and a confidence, and every commerce rule and every
generated question asks these rather than deciding for itself. Where a page's
own kind is not established and every item the site is seen to sell is of one
kind, the expectation applies *by inference*, at lower confidence, and the
finding says so (`metrics.kind_inferred_from_site`). Nothing is silently
skipped: a finding names the pages it set aside and why, and
`coverage.expectations_not_applied` prints the same accounting for the run.

**Entity relationships.** `primary_entity`, `organization`, `brand`, `product`,
`subsidiary`, `department`, `agency`, `tribunal`, `acquired_company`,
`partner`, `customer`, `official_profile`, `localization`, `language_variant`,
`knowledge`, `navigation`, `unrelated`, `unknown` — read from
`parentOrganization`, `subOrganization`, `department`, `Product.brand`,
`manufacturer`, `Offer.seller`, `Article.publisher`/`about`, the page's
declared language and script, and phrases in the page's own text ("formerly
known as", "now part of", "acquired"). `EN-NAME-INCONSISTENT` excludes every
related name, so a department, a product's brand, a former trading name and
the site's own name in another script are no longer rival spellings; the rule
still fires on two genuinely unrelated trading names.

**Links are classified before they are counted.** `classify_outbound_link`
returns `official_profile`, `review_listing`, `knowledge_reference`,
`documentation`, `product_listing`, `code_repository`, `language_variant`,
`navigation`, `share_intent` or `unknown`. `EN-SAMEAS-UNDECLARED` counts only
profiles and `rel=me`, says how many other platform links it did not count,
and no longer claims the site's Wikipedia topic link or its documentation host
is an undeclared social account. It also states that the audit did not verify
that the accounts belong to the organisation.

**Transport uncertainty, everywhere, in one vocabulary.**
`transport_verdict(status, error)` returns `verified`, `not_found` or
`unverified`. `CR-HTTP-ERRORS` now reports only 404/410 — an origin saying the
resource is not there — and the new `CR-URLS-NOT-VERIFIED` (`info`,
confidence 0.5) reports refusals, throttles, server errors, timeouts and DNS
failures as *could not be verified*. `FC-BROKEN-CORROBORATION-ANCHOR` splits
the same way: `medium` for a profile that 404s, `low` for one a platform
declined to show an automated client, and never "dead". A declared sitemap
that is served but does not parse says "HTTP 200 but sitemap XML parsing
failed"; one that was refused says "could not be verified".

**Canonical, redirect, noindex, heading and freshness semantics.** A canonical
naming another host is `CR-CANONICAL-CROSS-HOST` at `low` — syndication, a
migration or a consolidated brand domain look identical from outside, and the
other host is not fetched — while `CR-CANONICAL-WRONG-TARGET` keeps `high` for
a deep page collapsing onto the home page. A section that moved to its own
host (`/blog/x` → `blog.example.com/x`) is a canonical representation, not a
homepage collapse. `CR-NOINDEX-ON-IMPORTANT-PAGES` no longer calls pages
"commercially important" and asks the reader to review whether the exclusion
is intentional. `MR-HEADING-STRUCTURE` reports only that no top-level heading
names the page's subject, at `low`: several `<h1>` elements and a page led by
an `<h2>` are permitted by HTML. `FC-NO-DATE-SIGNALS` is measured over pages
where a date is expected or useful — a home page, a contact page and a listing
carry no dated fact — and titles itself "Machine-readable freshness metadata is
absent".

**Contextual expectations for organisations, Open Graph and search.**
`organization_field_expectation` grades each `Organization` property as
required-when-applicable, recommended or optional *for this kind of site*, and
the evidence names the observation that made it required ("the site sells
physical goods"). Open Graph is stated as optional metadata and capped at
`medium`. `EG-NO-SITE-SEARCH` is `low` and fires only where the site is
*observed* to be larger than a visitor can browse — many advertised URLs, a
paginated listing, or a crawl that spent its page budget — and `SearchAction`
is recommended only where a search endpoint exists. Sort and filter controls
are asked of a listing that shows a set large enough to need them.

**Answerability follows what the site sells.** Question classes come from the
site's shape and the item's kind: a documentation site, a publisher and a
public body are asked no buying question and report `unmeasured`; a software
catalogue is asked about price and specifications but never about stock,
delivery or returns; only a page selling physical goods is asked whether the
item is in stock. A comparison is asked within one kind — a boot and a licence
are not alternatives. "The cheapest item in X" is answered from the products
observed to be *in* X, and is not asked when that set cannot be delimited.
Questions that do not apply are listed in `answerability.not_asked` and are
not counted as gaps.

**Proactive recommendations carry applicability metadata.** Every entry in
`recommend.LIBRARY` declares its site kinds, page contexts and evidence
requirement; every emitted recommendation carries an `applicability` record
saying what about this site satisfied them, rendered as *"Applies because: …"*.
A documentation site is no longer told to model size variants or publish a
product feed; the worked examples (`/llms.txt`, the Product node, the
monitoring probe) are shaped by the site kind, and the physical-goods
recommendation quotes a physical page's own attributes rather than a software
page's.

**Two numbers were wrong and are now defined.** `evidence_reuse_ratio` read
~0.01 on real sites because it measured fetch-layer cache hits, not shared
evidence. It is now `1 − R / (N × R)` for `N` specialists over a bundle of `R`
requests (0.833 for six specialists), with the old measure kept under its own
name, `transport_cache_hit_ratio`, and both defined in the report. Repeated
evidence items and URLs are removed deterministically at serialisation — never
by editing the `Finding` a specialist returned, so building a report twice
from the same objects yields the same report — and the count removed is
reported rather than hidden.

**Severity respects applicability and uncertainty.** The absence of optional
metadata is capped at `medium` (`semantics.cap_optional`); a universal absence
observed on one page is capped by sample size; an unverified transport outcome
is `info` with confidence 0.5. No optional-absence rule can reach `high`,
which is asserted over every fixture shape.

**A twenty-five-element fixture and 200 new tests.**
`tests/fixtures/site_semantic` carries, on one host: a physical product, a
software product, a subscription, a service, a documentation section, a
publisher section, an ecommerce listing, a content listing, a department with a
parent organisation, localized organisation names in Latin and CJK script,
official profiles beside knowledge, documentation and ambiguous external links,
a cross-domain canonical, a redirect chain, a 403, a 429, a timeout, a
noindexed public page, a noindexed private page, a visible date with no machine
date, a partial `Organization` node, a page with two `<h1>` elements, a page
with none, and no site search. `tests/test_semantic_fixture.py` audits it end
to end and asserts every element; `test_semantics`, `test_contextual_findings`,
`test_entity_relationships` and `test_recommendation_applicability` hold the
units. On the previous release the same fixture scored 23.6 "critical" with 35
findings; it now scores 66.3 with 19, and the difference is entirely
expectations that did not apply. The deliberately broken fixtures still score
4.5 and 10.5 ("critical"), and `site_strong` still produces zero findings.

**Not done, on purpose.** No rule keys off a domain, a brand or a URL string;
the classifier was fixed instead, every time. No new network dependency, no
model, no service: the semantic layer is stdlib Python 3.9 and runs on the
evidence already collected. SSRF protection, private-address rejection,
redirect validation, scheme validation, DNS safety, decompression limits, page
and request limits, robots compliance, user-agent safeguards and redirect-loop
handling are untouched, and their tests still pass unchanged.

**1.9.1** — page eligibility and evidence boundaries, from two live runs: a
large marketplace and a documentation site. No new rules, no verdict changed
on any bundled fixture; three classes of page were being sampled by rules
that were not about them, one rule was reading a link as a shop, and a
handful of sentences still described outcomes in systems the audit never
queries. Every fix is a property over a shape - none matches a URL string or
a site - and each ships with the negative that reproduces it and the positive
control that proves the legitimate finding survives. 832 tests.

**A search results page was cited by product-only and listing-only findings.**
Read as a listing (a grid of prices) it was asked why it had no filters and no
breadcrumb; read as a product - a quick-add button on every result counted as
*the* purchase affordance in the content - it was asked why it declared no
Product markup. Two generic causes. `cart_action_in_main` was a boolean, so
one buy control and thirty looked identical; it is now a count, and five or
more purchase controls in the content region are plurality (one per item),
never an anchor. And a search results page had no way to be recognised
except by a URL word. It is now settled from what the page says about the URL
it was fetched at: its own search box pre-filled with the query, or the query
carrying a parameter under the page's own search-form name
(`extract.search_results_evidence`) - or a declared `SearchResultsPage`, which
had been filed as a `category` and now is `search`.

**Two navigation addresses that serve the home page were reported as content
pages whose canonical points elsewhere.** A tracking suffix on the logo link
returns the home document at a second URL with a canonical pointing at the
root; classified from its content it read as a listing, entered the canonical
population, and its *correct* canonical was reported as
`CR-CANONICAL-WRONG-TARGET` at high. `discover.resolve_aliases` now runs
after the crawl and types as `reference` any fetched page that is another
fetched page's document - via a redirect onto it, a declared canonical to it
(with title and headings agreeing), or an identical copy (same title,
headings, length and internal links; two pages of one paginated listing share
the first three and not the fourth, and stay distinct). The reason is printed
beside the URL in the manifest. The home page is never an alias.

**Only content documents are samples now.** `evidence.pages()` - the
population every content rule reads - leaves out `reference` pages and the
`search`, `account` and `tool` endpoints unless asked for them by type or with
`include_aliases` / `include_utility`; the redirect rules, the noindex aside,
canonical set-aside accounting, response timing and the report's page-type
gate opt in, because for them every requested URL is the evidence. A collapsed
deep link is still `EG-DEEPLINK-REDIRECTED-HOME`; it is simply no longer also
a second home page. `account` is decided from evidence too: a password field
in a content region that holds little else. `coverage.content_pages` and
`coverage.non_content_pages_by_type` state the split, and a run whose only
parsed pages were such endpoints says so in its headline rather than scoring
content pillars over nothing.

**A link labelled "Locations" was a shop.** `EN-LOCATIONS-UNSTRUCTURED` fired
on the link alone, and told a documentation site with a conference venue, a
jobs page and a user-group directory that its shops were invisible - while
asserting that "the model still answers ... it produces a plausible address ...
indistinguishable from a real one". The rule now needs a *fetched* page
that presents itself as being about places *and* carries the shape of
visitable places - several street addresses, or one with a telephone number
or opening hours, or a telephone number with hours, or several telephone
numbers - and not a declared `Event` or `JobPosting`, an article or a policy. A locator link whose target the crawl did not read is reported as
not counted. Seven fixture shapes hold the line: a retail locator and a single
branch are reported; an event venue, a jobs page, a geographic article, a
service-area page and an unread link are not.

**An old copyright year was an abandonment cue.** It is a weak signal and is
now reported as one, weighed against every other date the site carries: `info`
and "contradicted" when fresher signals exist elsewhere, `low` and
"uncorroborated" when there are none, `low`/`medium` and "consistent" when the
maintenance dates reported separately are old too - worded as a possibility to
check, never as a "dead site" or a lost contest with competitors.

**And the last few sentences that outran the evidence.** A soft 404 no longer
means a "hallucinated URL gets repeated as if verified"; a missing review no
longer sends "both the visitor and the assistant ... to a competitor ... that
then gets cited instead of you"; hydrated content is "absent from the response
such a fetch reads", not "invisible to retrieval" ; a missing negative attribute
is a fact "a reader may fill", not one "a model will supply"; JSON-LD is no
longer "what most extractors read first"; a missing `lastmod` means "the
sitemap says nothing about what changed", not that "crawlers cannot tell". The
compliance guard bans each phrasing so the sweep is a rule. No production file
names a real website any more, in code or in comment.

**1.9.0** — a reliability and safety hardening pass. No new rules and no
change to any verdict on the bundled fixtures; the same findings, with the
transport layer more honest, one real SSRF hole closed, and the last few
sentences that claimed more than the crawl measured brought back to what it
observed. `tests/test_round3_hardening.py` holds one regression per fix,
every one failing on 1.8.9 and passing here; 785 tests, green on 3.9 and 3.11.

**A declared off-site anchor at a private address was fetched.** The crawl's
private-host guard (`EvidenceStore.private_refused`) refuses a `sameAs`,
`rel=me` or knowledge-graph link that resolves to loopback, RFC 1918 space or
a cloud metadata endpoint - but only on the paths that route through the store.
`verify_anchors` fetched the anchor through the *raw* client
(`store.client.head_or_get`), which holds no such guard, so a page declaring
`"sameAs": "http://169.254.169.254/…"` sent a real request to it on exactly the
kind of runner where that answers. Anchor verification now goes through
`store.fetch`, which applies the private-address guard, the anchor host's own
robots.txt, the per-hop redirect guard and the budget cap, and records the
response once. The robots pre-check no longer reads a refused fetch as
"allow everything" either. A regression asserts no private host is ever
requested, and its twin asserts a public anchor still is.

**A redirect could still steer a fetch somewhere the audit never chose.** The
final-URL re-authorisation caught a redirect that *ended* on a private host,
but not an intermediate hop that bounced back to a public URL, and not a
redirect to a non-web scheme - urllib's default opener also installs FTP and
file handlers, so an `http → ftp://internal:22/` or `file://` redirect opened a
socket the audit never intended. The redirect handler now refuses a non-web
scheme and calls the store's private-host guard on every hop, so an
intermediate private hop is refused mid-chain. And a redirect that never
resolves - past the six-hop limit - now raises a transport error rather than an
`HTTPError` carrying the last 3xx status, which the client had recorded as an
answered 3xx page: an infinite redirect loop is a transport failure, not the
site answering.

**A bot wall was manufactured from a site's own outbound links.**
`assess_access` computed its refusal share over *every* response the store held,
and by the time it ran that included the off-site anchor responses and their
robots.txt. A brand that answered every one of its own pages cleanly but
declared a dozen `sameAs` links to a host that 403s them was reported as sitting
behind a bot wall, tipping the whole report into its transport-only state.
Refusal share is now computed over the audited registrable host only. A real
wall on the origin is still detected, and a genuine lone 403 on an advertised
URL is still reported.

**A gzipped sitemap was reported as malformed.** A `.xml.gz` sitemap served the
usual way - `Content-Type: application/gzip`, no `Content-Encoding` header - was
decoded as text and then re-encoded and gunzipped, which cannot recover the
original bytes, so a valid sitemap read as unparseable. The HTTP client now
gunzips any body whose bytes begin with the gzip magic number regardless of the
header, from the raw bytes, before charset handling. Decompression - here and
for any gzip/deflate response - is bounded to 30 MB of output, so a crafted body
that expands without limit is truncated rather than exhausting memory, a
decompression-bomb class the wire byte cap did not cover.

**`<meta name="robots" content="none">` was honoured by one rule and hidden from
another.** `none` is a valid noindex+nofollow directive; the canonical-eligibility
check read it correctly, but `CR-NOINDEX-ON-IMPORTANT-PAGES` compared the
comma-split tokens without stripping them, so `none` never matched and the
finding was silently dropped for that directive form. Both now read the
directives through one helper, so they can never disagree about whether a page
is noindexed again.

**`CR-SOFT-404` called a refusal a success.** The soft-404 rule bailed on a hand
list of statuses (`0, 403, 429, 5xx`) that omitted 401, 407, 408 and 451, so a
probe answered with a 451 was reported as "returns a success status instead of
404". It now fires only on an actual success (2xx) or a redirect that dumps the
probe on the home page.

**A run's page budget was spent on fetches that read nothing.** `max_pages`
counted every attempt, including a timeout and a circuit-breaker skip, both of
which return no document - so a black-holed host quietly shrank the sample and
the site read as thin. The budget now counts documents actually served.

**And three sentences claimed more than the crawl saw.**
`CR-AI-CRAWLERS-BLOCKED` said a blanket robots block meant the site "can never
be the source of an answer" for the blocked agents - an absolute, unmeasured
outcome about answer surfaces the audit never queries - and lumped training
crawlers in with answer-time fetchers. The evidence now states only the
observation and separates the two crawler classes (an answer-time fetcher's
block most directly affects a cited answer; an indexing or training crawler's
governs the corpus), with the consequence conditional in `interpretation`. The
report headline no longer reads "assistants cannot reliably reach, read or attribute
its content" - an inference about assistants the audit never queried -
but describes the conditions a crawler must clear, which is what it measured;
the compliance guard that bans indicative claims about external systems now
covers the plural form that slipped through. The recommendation to publish an
agent index (`/llms.txt`) no longer fires on a 5xx or a timed-out probe, only on
a conclusive 404/410 or an empty 200, for the same reason a refused `/robots.txt`
does not prove the file absent. `EG-REVIEWS-CLIENT-RENDERED` no longer asserts
what "a visitor sees", which the static audit did not render. The report count
validator now reconciles every severity bucket, not only the three the brief
names.

**1.8.9** — generic reliability regressions from the latest live run. No
new rules; four failure modes closed at the layer that produced them, each
with a regression test that fails on 1.8.8.

**A specialist crashed on the first page carrying microdata, and the run
reported `entity-audit: 0 finding(s) [FAILED: AttributeError: 'list' object
has no attribute 'get']`.** Two bugs, in two layers. The producer
(`extract.extract_page`) writes `microdata` as a *list* of item records -
`{"itemtype", "types", "props"}`, one per `itemscope` - and the entity
specialist's place-entity check read it as a mapping. The classifier had
already been fixed for the same misreading in an earlier version, privately;
the contract is now stated once, in `extract.microdata_items()`,
`microdata_types()` and `microdata_props()`, which accept the list, tolerate a
single record passed bare, yield nothing for foreign shapes, and are the only
way either consumer reads the field. The entity rule compares microdata types
against the same place vocabulary it uses for JSON-LD (the old substring test
matched `OnlineStore` as a physical store) and reads an Organization item's
`address` prop the way it reads the JSON-LD property. The data is read, not
stepped around: a product item still leaves `EN-LOCATIONS-UNSTRUCTURED`
firing, a `LocalBusiness` or `PostalAddress` item still satisfies it. A
shape-matrix test runs all six specialists over every shape schema.org
permits - every property value a list, `@graph`-wrapped, top-level lists -
and asserts none fails and the report validates.

The second bug is the sentence. A specialist that raised was recorded with
`findings: 0`, the number a specialist reports when it audited the site and
found nothing wrong. Run records now carry `status` (`ok` | `failed`),
`pillar` (from the manifest), and `findings` only when the specialist
finished - `null` otherwise. The report treats the failed pillar exactly as
it treats one no page was read for: `score: null`, `band: "unmeasured"`, an
`unmeasured_reason` naming the specialist and the error, excluded from the
weighted mean rather than assumed sound. `summary.specialist_coverage` reads
`complete`, `partial` or `unrecorded`; `coverage.specialists` lists what
completed, what failed and which pillars are therefore unmeasured; the
headline and `score_basis` say so in prose, the markdown's pillar table and
coverage section show it, and the progress line reads `FAILED before
producing findings`, never `0 finding(s)`. `coverage_state` is untouched:
whether any page was read and whether every specialist finished are two
facts, and a content crawl with one failed specialist is a content report
with one pillar missing. The findings of every specialist that finished are
kept unchanged. Both fields are declared in the report schema.

**Questions were generated about "Add to bag", "Shop the range" and "Product
details".** The answerability engine, the worked-example vocabulary and the
duplicate-product-name rule all read the first `<h1>` of any page classified
`product` as the product's name. Identity now comes from item-scoped evidence
only, in `analysis.item_identity()`: the product entity the page declares
(the JSON-LD *subject* node - not the first product-typed node in document
order, which on a detail page with a related-items rail is a different
product - a microdata product item, or an Open Graph product card), and
failing that a heading the page corroborates in a second channel: a `<title>`
segment unique to that page, its `og:title`, or its URL slug. A heading that
is one of the page's own control labels (the extractor now records
`control_labels`: buttons, submit inputs, button-role elements, summaries)
or navigation link texts, a string the site repeats across pages, the site's
own declared name, or a string shaped like a promotion - a price by the
extractor's own price grammar, a percentage, a terminal `!` or `?` - is never
an identity. Repetition is a fact about headings, not declarations: six
variant pages each declaring `Product.name` have each named their product,
and a repeated heading is rescued by a title segment unique to its page but
not by its slug (a section label and the section's URL agree by
construction). Where nothing establishes an identity, no product question is
asked; the matrix notes which product pages were set aside and why, and every
product-scoped row records `subject_identity`. Every test is about shape or
provenance; none knows a brand, a framework or a phrase a call to action
tends to use. A page with no `<h1>` offers the headings at the highest level
it does use, under the same corroboration - a product named in an `<h2>`
because the template spent the `<h1>` elsewhere has still named it. On every
bundled fixture the subjects resolved are the same as before; on the
reconstructed appliance storefront, whose product pages name the product in
an `<h2>` the title repeats, five products that 1.8.8 skipped are now asked
about.

**"No usable XML sitemap was found, so page discovery depends entirely on
internal linking" was printed over five probed locations.** A finite probe
list cannot establish that a site has no sitemap, and the finding never says
so now. Each probed location is classified by what it observed - `valid`,
`not_found` (404/410), `malformed` (a document that is not a sitemap), or
`unchecked` (refused, errored, timed out, not attempted) - and the evidence
lists every location with its answer. `CR-NO-SITEMAP` is suppressed when the
site declares a sitemap anywhere (that sitemap's state is
`CR-SITEMAP-BROKEN`'s fact) and when no location answered at all; it is
`high`, and draws the internal-linking consequence, only when every
conventional location answered and robots.txt was read without a `Sitemap:`
line - both mechanisms a crawler has unaided, both empty; otherwise it is
`medium`, titled "at the conventional locations that answered", and says what
could not be settled. `metrics.discoverability_established` records which.
`CR-SITEMAP-BROKEN` names the outcome per declared sitemap and, when every
one was merely unreadable by this audit, says *unread* at `low` rather than
broken at `medium`. `CR-SITEMAP-UNDECLARED` is the fact about robots.txt on
its own: reported whenever robots.txt was read and carries no directive,
whether or not a sitemap was found at a conventional path, with wording for
each case, and never when robots.txt is absent or could not be read.

**Canonical findings counted a navigation endpoint and an unclassified page.**
`CR-CANONICAL-MISSING` and `CR-CANONICAL-WRONG-TARGET` now sample only pages
whose canonical is a statement they can make, decided by
`canonical_eligibility()` from page evidence and never from URL shape: the
classified type must be a content type (product, category, policy, faq,
article, about, contact, support, program, promotional, home) - a search or
tool endpoint and an `other`/unclassified page are not - the page must not
carry `noindex`, and a URL that redirected onto another page's document
(homepage collapse, unrelated destination) is not assessed, while an
address-normalising redirect still is. The pages set aside are counted in the
evidence with the reason, the ratio is computed over eligible pages only, and
`sample_unit` says so.

Four new suites (`test_specialist_reliability`, `test_product_identity`,
`test_sitemap_semantics`, `test_canonical_eligibility`), 764 tests, green on
3.9 and 3.11. Live sites remain unreachable from the build sandbox; the four
regressions were reproduced from the live report's own trace and from
reconstructions, and the fixes verified against those and every bundled
fixture.

**1.8.8** — a general evidence-discipline pass. No new findings; the same
findings, correctly scoped. Six changes, each closing a way a claim could
outrun the observation behind it.

**A redirect means several different things, and one classifier now decides
which.** `classify_redirect()` reads the requested URL, every hop and the
destination together and returns one of: `canonical_host` (http to https, www
to apex, path intact), `locale` (a market segment added or changed),
`canonical_representation` (a trailing slash, a default document, a case fold,
a route change, or the page's own declared canonical), `homepage_collapse` (a
deep path that ended at a root or market root), or `unrelated`. Every rule that
reads a redirect now reads that answer. `EG-DEEPLINK-REDIRECTED-HOME` fires on
the collapse and nothing else — a scheme upgrade and a market redirect are
sites doing the right thing — and `CR-REDIRECT-CHAINS` characterises what its
hops are instead of only counting them, saying so when the destination is
already canonical and only the hop count is in question. A chain that collapses
is reported once, as the collapse: two headings for one redirect meant two
severities and a pillar scored twice.

**A zero-page run now explains where its time went.** One took 15 seconds and
another several minutes, and every other field in the two reports was
identical. `HttpClient` records seconds by outcome — answered, refused,
transport failure, retry backoff, politeness throttle — and stops requesting a
host after three *consecutive* transport failures, which bounds a black-holed
origin at three timeouts rather than one per queued URL. No timeout was
reduced; instead no single request may outlive the audit's declared budget,
because the budget guard runs before a fetch and a request begun with seconds
left could spend the full timeout twice over. `coverage.transport` carries the
breakdown and the report prints it.

**Claims about external systems are scoped to what was measured.** Twenty-two
phrasings across six specialists asserted how an assistant, a fetcher, an index
or a retrieval system behaves — "assistants never read", "the index cannot tell them
apart", "loses to competitors", "silently dropped from the answer". The
audit sends its own User-Agent to one origin and reads what comes back; it
queries no retrieval system and asks no model anything. The factual half of
each claim is unchanged and the mechanism is still named; what changed is the
mood. A compliance test now fails the build on the banned phrasings, so this is
a rule rather than a sweep.

**Proactive recommendations declare what they rest on.** Every one is now
`evidence_backed` (gated on something the crawl observed), `site_personalised`
(standard practice in this site's own nouns) or `generic` (standard practice,
identical anywhere), the class is printed beside each, and a run that read no
page keeps only the generic ones — a transport-only report used to carry seven
improvements as though it had inspected a site nobody had seen. A refused
`/llms.txt` probe no longer recommends publishing one, for the same reason a
refused `/robots.txt` no longer proves absence.

**A generated question needs a validated entity.** The subject is quoted back
to the reader, so "What is the price of {{product.title}}?" cited to a live URL
is worse than no question: it is "indistinguishable from a real one". Template
tokens, DOM attribute names, component and class names, slugs, placeholders and
strings with no letters are refused, and where no identity can be established
the question is not asked. The wording changed too: the audit generates
questions from a catalogue, not from behaviour, so "the attributes buyers most
often ask about X" became a statement about what the audit did, with the
reader's own support tickets named as the source that actually knows.

**And the score says what it is a score of.** `summary.score_basis` names the
evidence behind the number — how many pages were parsed, out of how many the
site advertises, under what page cap — and in a transport-only run says plainly
that it reflects audit reachability and makes no assessment of content quality.

Verified against the 1.8.7 build: **13 of 19 redirect tests, 16 of 59
answerability tests, 6 of 28 transport tests and 15 of 43 compliance tests fail
on it.** The new page-type negatives (component fragments, template-token
headings, regional duplicates) pass on 1.8.7 as well — the cardinality work in
1.8.5 and 1.8.6 already covered those shapes, and they are kept as coverage
rather than claimed as a regression. 679 tests, green on Python 3.9 through
3.13.

**1.8.7** — five live audits, five defects, all of the same kind: a claim wider
than the observation behind it.

**A hub hint became a prefix.** `/buy[-_]` was unanchored, so it matched
`/shop/buy-ipad/ipad-air` as well as `/shop/buy-ipad`. A live audit of a large
storefront came back with **no product pages at all** in 39 fetched pages — and
the machine-readability pillar then scored 100/100 over a population of zero,
which is the worst possible failure: silence that reads as a pass. The hint is
now anchored at the hub, exactly as `/products/` was anchored against
`/products/velocity-x9` in 1.8.5.

**`category` was doing two jobs.** Buying landing pages, gift-card hubs and
model choosers were filed as listings to keep them out of *product* sampling,
which put them into *listing* sampling instead — and a listing is asked why it
has no filtering, no sorting and no comparison support. They are `promotional`
now: non-product and non-listing, in neither funnel. The storefront section
words (`/shop`, `/store`, `/tienda`) move to `WEAK_CATEGORY_PATH_HINTS`, read
as a pre-fetch prediction and never as a verdict — `/shop` is a catalogue index
on most sites and a product on one, and the content settles it.

**A policy quote had to contain a policy.** On a site whose *subject matter* is
commerce, returns and delivery vocabulary matches on every page. Three
questions were reported as answered in prose by sentences stating nothing: a
return window evidenced by "It includes a money-back guarantee. UPS Next Day
Air Saver… UPS 2nd Day Air" — which passed the numeric test on the "2" in a
courier's product name; shipping destinations evidenced by a feature blurb,
because the page's URL contained "shipping" and that *waived* the test; and a
product's stock state evidenced by advice about when inventory runs low. So:
the quantity test needs a quantity in a unit the policy is measured in (or an
explicit no-charge term), the page being about the topic no longer waives
anything, and a new `hypothetical` vocabulary vetoes suppositional framing for
returns, shipping and stock. A third outcome joins the two: the topic is
discussed and no terms are stated, which is both truer and more useful than
"no statement was detected".

**One barrier stopped being three findings.** A storefront behind bot
mitigation refused every request, and the report said so correctly — then said
"pages the site itself advertises return HTTP errors", citing the home page the
wall had refused and which no sitemap listed, then "no robots.txt is published",
from a 403. `CR-HTTP-ERRORS` now reports only URLs the site actually advertises
(in a sitemap it served, or linked from a page it served) and never a refusal
already attributed to a wall; `CR-ROBOTS-MISSING` fires on 404, the status for
a file that is not there, and not on 401/403/429/451. The transport-only report
for such a site is one finding instead of three, and its crawl pillar is scored
once for one obstacle.

**And the inference is labelled.** `CR-BOT-WALL` observed that *this* agent was
refused. It did not send GPTBot's User-Agent — impersonating a named crawler is
refused before a socket opens — so how assistant crawlers are treated is
genuinely unknown to it. The evidence sentence now states only the refusal, the
inference moves to `interpretation` and says plainly that the audit has no
evidence either way, the mechanism is conditional rather than assertive, and
the first step of the fix is reading the edge logs: if the assistant crawlers
are being served, the rest of the recommendation does not apply.

`tests/test_transport_only.py` holds the five distinctions the report has to
keep — observed versus inferred, refusal versus absence, conditional
recommendations, one barrier one finding, and no content claim from a run that
read no content — each paired with the positive case that proves the
suppression is narrow: a sitemap URL that 404s, a linked URL that 404s and a
lone 403 with no wall are all still reported. Verified against the 1.8.6 build:
**13 of 22 transport tests, 6 of 36 page-type tests and 8 of 51 answerability
tests fail on it**. 636 tests, green on Python 3.9 through 3.13.

**1.8.6** — a product detail page was asked why it published no filter controls
and no sort controls, and a finding said the catalogue could not be reached in
a report listing the pages it had reached.

**Being a listing was not earned.** 1.8.5 made *product* a type a page has to
earn and left *category* a type a page could fall into: any weak plurality
signal — several prices, a few priced sibling links — decided it, with nothing
required to say the page presented a set rather than one item. A detail page
with a related-items rail matched, and it was then handed to the listing rules,
which asked it questions only a catalogue can answer. Plurality is now decisive
only when nothing anchors the page to a single item. Where both readings have
support the conflict is settled by **item-scoped** evidence — a specification
block, a buy control in the content region, variant options, a declared single
entity — because a page presenting a set does not publish the dimensions of one
of them or a control that puts one of them in a basket. A heading, a price and
a URL are page-scoped, fit either reading, and settle nothing. Unsettled, the
page is `other`: audited as neither, and asked neither why its Product schema is
missing nor why it has no sort control. `page_type_evidence.conflict` and the
report's `why_type` say which of these happened.

**The listing side had no funnel.** Product sampling went through
`ev.product_pages` and stated its exclusion; listing sampling was a string
literal in each rule that wanted one, which is how a rule and the classifier
could disagree about a URL. `ev.category_pages` is now the twin, with
`LISTING_PAGE_TYPES` / `NON_LISTING_PAGE_TYPES` stated the same way, and every
listing-only rule — filtering, sorting, comparison, breadcrumbs, cross-page
price, category answerability, the vocabulary derivation and the commerce
signal — goes through it. A compliance test fails the build if any rule selects
listings by a literal again, and the remaining multi-type samples read named
constants rather than inline strings.

**A missing link is not an unreachable catalogue.**
`CR-COMMERCE-NOT-LINKED-FROM-HOME` said "a crawler that starts at the root
cannot reach the catalogue by following links" whenever the home page had no
direct catalogue link — in reports that went on to list catalogue pages reached
through the sitemap. The rule now reads the crawl's own record: which catalogue
pages were reached, and whether the sitemap or a link on another page found
them. With the catalogue reached it reports reduced *directness* of discovery
at `medium`; with nothing reached by any path it keeps the serious reading at
`high`, still scoped to what this audit could see, because a bot wall, a budget
limit and a genuinely unreachable catalogue look alike from here. The channels
are recorded in `metrics.discovery_channels`.

A side effect worth naming: the shell fallback (an item URL and no content is
still a product page, because emptiness is the defect the crawl rules report)
treated any short page as empty. A four-item listing with a heading and five
prices is short but not silent, so a page is now a shell only when it is short
*and* produced no content signal at all.

Verified against the 1.8.5 build: **12 of the 22 new provenance tests fail on
it**, including a product detail page appearing in "2 of 2 category page(s)
expose no filter…". `tests/test_page_type_provenance.py` covers the five shapes
the classifier separates — genuine detail page, listing, multi-product
collection, promotional page quoting prices, ambiguous landing page — on five
unrelated synthetic domains, and asserts behaviour: the same bytes stamped
`category` in one bundle and `product` in another are audited differently, and
no finding in any of the six specialists describes a URL as a type the bundle
does not. 593 tests, green on Python 3.9 through 3.13.

**1.8.5** — page-type classification rewritten around cardinality. Four
consecutive live reports produced a product-page false positive, and each of
the first three fixes removed one *shape* — a loyalty programme, a promotions
hub, a planner landing page, five storefront utility routes — without changing
the rule underneath. That rule was "a price somewhere plus one more commerce
affordance". On a storefront the cart control is in the header of every page,
so it reduced to "mentions a price", which is true of nearly every page of a
shop.

**The question was wrong, not the word lists.** "Does this page look
commercial?" cannot separate a product from a catalogue, a promotions hub or a
membership page, because on a storefront all of them are. `product_evidence()`
asks about *cardinality* instead — one purchasable thing, several, or neither —
and answers it in three readings:

- a **declared listing type** (`CollectionPage`, `SearchResultsPage`,
  `OfferCatalog`) is a statement about the document and settles it;
- **plurality**: two or more distinct product entities, more than four distinct
  prices, sort controls, filter controls beyond the page's own options,
  pagination, five or more priced sibling links — overridable only when the
  markup names one entity and the page's own heading repeats that name;
- **singularity**: an **anchor** that fixes which item the page is about (one
  declared product entity, an item-shaped URL, a buy control inside the content
  region) *and* at least two signal families in total.

Nothing decides alone: not a price, not one `h1`, not product vocabulary, not
`/shop/` or `/buy/` in the URL, not product links, not a bare `Product` token.
Nor do two corroborators with no anchor — a price and a specification table
describe a comparison page, a shipping policy and a promotions hub as well as
they describe a product. Where the evidence does not settle it the page is
`other`, which no product rule can sample.

**Detection got better, not just quieter.** Counting product-typed JSON-LD
nodes had made the *best*-marked-up pages the most likely to be misread: a
`ProductGroup` with two sizes is three `Product` nodes and looked like three
products. Variants under `hasVariant`/`isVariantOf`, related items, spare parts
and names that qualify a parent ("Velocity X9, UK 8") now collapse into one
subject. A page's own size picker is no longer counted as a catalogue filter.
A related-items rail with prices no longer turns a detail page into a listing.
And a JavaScript-rendered product page — an item URL and a body of six script
tags — is still a product page, because emptiness is the defect the crawl rules
exist to report, not evidence against the site's own routing.

**The decision is now inspectable.** `classify_page_verbose()` returns the
anchors, the corroboration and the plurality it read; every page carries
`page_type_evidence`; and the report prints `why_type` beside each URL in
`evidence_manifest.pages`. Three rounds of this work began with someone reading
a report and having to reverse-engineer why a page had been called a product.

Verified against the 1.8.4 build: **13 of the 26 new page-type tests fail on
it**, including a priced service page classified as an individual product and
five product-specific rules firing on a bundle with no product page in it.
`tests/test_page_types.py` covers the taxonomy on fourteen unrelated synthetic
domains — individual product, multi-product shopping page, category, curated
collection, promotional landing page with prices, ambiguous product-like page,
storefront buying route, small category at a plain URL, comparison page, priced
service page — plus the shapes detection must survive. The Apple routes remain
as one fixture among them, not as a rule. Three property tests in
`TestConservativeUnderUncertainty` assert the principle over the *signals*, so
a signal added later cannot quietly become sufficient on its own. 569 tests,
green on Python 3.9 through 3.13.

**1.8.4** — an Apple audit classified five storefront utility routes as
individual products, and published a sampling coverage of 1.05.

**A URL shape decided a page type on its own.** `/us/shop/goto/account`,
`/buy_accessories`, `/buy_iphone`, `/giftcards` and `/payment_plan` all matched
one pattern in the *product* hint tuple: `/shop/[^/]+/[^/]+$`. That is a guess
about layout, and it fits a sign-in route as well as it fits a product. Three
changes. The pattern moves to `WEAK_PRODUCT_PATH_HINTS`, where a match is a
candidate rather than a verdict and yields `product` only if the markup declares
one or the content shows an individual item - the same bar an unrecognisable URL
has to clear. `NON_PRODUCT_PATH_HINTS` settles commerce *functions* before any
product heuristic runs: buying landing pages, gift-card hubs, financing and
payment-plan pages, trade-in programmes. And `NON_CITABLE_PATH_RE` is anchored
at any segment boundary rather than at the root, so account, cart, bag and
checkout routes are excluded from the frontier wherever they sit - `^/` meant
the exclusion silently stopped working on every locale- or shop-prefixed site,
which is why an account page was in the sample at all. Localized cart words
(`warenkorb`, `panier`, `carrito`, `koszyk`, …) join the same rule.

Detection is preserved where it was real: explicit product URLs, declared
`Product` markup, and `/shop/x/y` pages whose content shows an individual item
all still classify as products.

**A ratio that cannot exist.** `EN-LOCATIONS-UNSTRUCTURED` appended a signal for
a page that *links to* a store locator and another for a page that *is* one, so
a page could contribute twice - 40 observations over a population of 38 pages,
coverage 1.05, and a schema violation in the emitted report. The rule now counts
one entry per page. The invariant is enforced rather than clamped: any finding
whose `metrics.affected` exceeds `metrics.sampled` is refused by
`Finding.problems()` and listed in `diagnostics.rejected_findings`, because
rounding 1.05 down to 1.0 would publish a plausible number over a population
nobody measured. A suite-wide test asserts no finding on any bundled fixture
reports a coverage above 1.

Verified against the 1.8.3 build: **59 subtest failures across the 16 new
tests**, including all five Apple routes and the coverage invariant. 537 tests.

**1.8.3** — the third live report in a row produced a product-page false
positive, and that is the finding: two previous rounds each removed one *shape*
(`/ikea-family/`, `/offers/`) without changing the rule underneath, so the next
shape (`/planners/`) walked straight through it. The rule was "a price
somewhere plus a cart control somewhere", and on a storefront the cart control
is in the header of every page - which reduces it to "mentions a price".

**Evidence of an individual item, not of a shop.** The content-signal branch
now requires four things, each a claim about *this* page: two independent
affordances; singularity (at most four distinct prices, one `h1`); a price
inside the content region; and a heading that does not announce the page as a
hub, a tool or an activity. The purchase affordance only counts when it is
outside `nav`, `header` and `footer` - `forms.has_cart_action_in_main` is new,
and it is the signal that separates a product page from every other page of the
same site. A `tool` page type covers planners, configurators, designers and
builders generally. Detection is preserved where it was real: explicit product
URLs, declared `Product` markup and opaque-URL product pages with a cart
control in their own content all still classify as products, which
`TestVerdictDoesNotDependOnUrlVocabulary` continues to guard.

**An instrument is not an acceptance statement.** With an instrument required,
the payment question moved from a privacy notice to an FAQ, citing "I purchased
an article at the store and paid through a Credit/Debit card. It was returned
for a refund" - a refund anecdote. Requiring one more keyword was never going to
fix this, so the rule is now compositional: a quotation must carry *every*
vocabulary the answer is made of (`payment_acceptance` **and**
`payment_instrument`) and none of the vocabulary that marks a different subject
(`payment_off_context`: refunds, chargebacks, transaction history, bookings,
data collection, past-tense narration). Acceptance language is present-tense
statements of what the site takes - "we accept", "you can pay with", "payment
options" - so "paid by" and "paid through" do not qualify.

**The conjunction is enforced, not assumed.** `we accept` had been in both the
instrument and the acceptance vocabularies, so one observation satisfied a rule
that needed two - a two-signal requirement that was still a keyword match, with
no change to the logic reading it. The vocabularies are now disjoint in all
twelve languages, and a compliance test fails if any overlap returns.

**The principle, as assertions.**
`test_compliance.TestConservativeUnderUncertainty` asserts that no specialist
re-derives the page type of a fetched page, that every page type the hint
tables can emit is refused by the product funnel, that composed vocabularies
stay disjoint, and that every composed concept declares a veto. 521 tests.

**1.8.2** — a second live report showed 1.8.1 had not closed the semantic half
of the provenance problem. The citations were now *typed* correctly; what they
were citing was still wrong.

**Non-product pages audited as products.** `/in/en/ikea-family/` and
`/in/en/offers/` matched no URL hint, fell through to the content-signal
branch, and satisfied it: a price somewhere on the page plus a cart control. On
a country site both are true of almost every page - the cart lives in the
site-wide header and a promotional strip carries a price - so six
product-specific rules ran against a loyalty programme and a promotions
listing. Three changes, none of them an IKEA exception. `promotional` and
`program` join the specific hint table. A path segment prefixed with the site's
own registrable name (`/ikea-family/`, `/tesco-clubcard/`,
`/nike-membership/`) is a programme, consulted only when nothing specific
matched so `/ikea-products/` is unaffected. And the content-signal branch now
requires *singularity* as well as affordances: at most four distinct prices, a
single `h1`, and a price inside the content region rather than inherited from a
header. `ev.product_pages` became the single funnel every product rule goes
through, stated as an exclusion as well as a filter so the invariant is
checkable.

**A support section read as a document type.** `/global/en/support/contact-ikea-submit-complaint/`
was classified `faq` because `/support` sat in the FAQ hint tuple, which is one
generic keyword deciding a page type on its own. Hub words - `support`, `help`,
`customer-service` - move to a generic tier consulted only when nothing
specific matched, and `contact` gains complaint and feedback vocabulary. A
complaint form is now `contact`, a real FAQ under `/support/` is still `faq`, a
bare `/support/` hub is `support`, and a return policy under
`/customer-service/` is still `policy`.

**A keyword match presented as an answer.** "What payment methods are accepted?"
cited a privacy statement, quoting a sentence about collecting a payment method
when booking a tour at the IKEA Museum. The phrase matched; nothing in the
sentence was an answer, and no amount of anti-phrase patching fixes that class
of error. Two independent guards now apply. A new `payment_instrument`
vocabulary holds the things a payment answer consists of - card schemes, wallets,
UPI, cash on delivery, acceptance statements - and the quotation must contain
one, so a topic hit is no longer sufficient. Separately, documents whose
identity says they are about something else (privacy, cookies, careers, press,
museum, investor relations) are excluded from answering commercial questions
regardless of what they contain.

Verified by copying the new tests onto the 1.8.1 build: **14 of 17 fail there**,
including the payment row citing the privacy statement verbatim. 23 new tests,
500 under `unittest discover`.

**1.8.1** — an evidence-provenance pass, prompted by reviewing a live audit of
a multi-market retailer. Nothing here changes a conclusion; all three defects
were wrong *citations*, which is worse, because a reader who checks the cited
page finds nothing there and stops trusting the whole report.

**A quotation that did not contain the fact.** "What is the return window?" was
answered `partial - stated in prose` and the quotation offered was
`"Skip to main content Stories Jobs Newsroom Our business ... Privacy and Cookie
statement"` - the first 160 characters of a privacy page, because `_snippet`
was called with no needle and fell through to `text[:width]`. The site's actual
return-policy page had been crawled and was not cited. `quote_concept` replaces
that: it locates the concept with `lexicon.find`, a new span-returning matcher
whose fold is length-preserving so the original words and diacritics survive,
opens the quotation at the sentence the phrase sits in, and returns **nothing**
when the concept is absent - so a question can no longer be reported as answered
in prose that does not contain the answer. Pages are ranked by whether their URL
or title says they are *about* the concept, which is what separates a return
policy from a privacy statement that merely links to one; the content region is
searched before the whole document, so a navigation label never outranks the
page's own text.

**A question resolved against the wrong concept.** "What payment methods are
accepted?" was matched against `add_to_cart`, so any page with a cart button
"answered" it. That is a category error rather than a weak match. The lexicon
gains a real `payment` concept across its twelve languages, with anti-phrases so
a privacy page describing how payment data is processed does not qualify.

**A citation that was not the page type claimed.** `MR-PRODUCT-SCHEMA-MISSING`
reported "1 of 16 identified product page(s)" and cited a country front door,
which the content-signal branch had classified `product` because it carries
prices, a cart control and variant swatches. `classify_page` now settles locale
roots first - `/in/en/`, `/ae/ar/`, `/global/en/`, `/en-gb/` are home pages, and
nothing is shadowed because a locale root has no path left after the locale. On
top of that, `build_report` refuses any finding whose `metrics.sample_unit`
names a page type that its cited URLs are not, and lists it in
`diagnostics.rejected_findings`. The claim is read only from the sample unit,
never from prose: "though a contact page exists" is an aside, not a claim about
a sampled population, and treating it as one produced false rejections against
rules that were correct.

**A scope that was not a site.** The crawl was entered at `/in/en/`, followed
the market selector into Estonia, the Emirates, Canada and Morocco, and then
aggregated "33 of 38 sampled pages" across all of them - different catalogues,
different prices, different policies, one ratio describing no site that exists.
Fifteen of the sixteen product pages behind two entity findings were Estonian.
When the entry URL carries a locale, the frontier now keeps to it: same market,
same host, plus market-neutral segments (`/global/...`) and paths with no locale
at all (`robots.txt`, sitemaps). Sitemap entries are filtered at collection, so
lastmod statistics describe the audited market too, and `coverage.locale_scope`
and `coverage.out_of_locale_candidates` state the scope rather than leaving a
reader to infer it from the URLs. Replayed against that audit's own manifest, 23
of its 38 crawled pages fall outside the market it was pointed at.

**Also:** `main_text` is kept in the fact bag rather than only its word count -
a quotation offered as evidence should come from the content region, and only
that region can distinguish it from the chrome. New fixture `site_locales`
reproduces all three shapes; `tests/test_ikea_regression.py` adds 34 tests, each
failing before the fix it names. Suite 443 -> 477.

**Found by reading the fixed report's own evidence.** "You can return any item
within 365 days *of delivery*" was being quoted as the site's answer to "where
does this ship to, and what does it cost?" - a shipping word inside a returns
sentence. Those collocations are now anti-phrases, and the two policy questions
whose answer is a quantity (`return_window`, `shipping_destinations`) require
either a page that presents itself as being about the concept or a number in
the quoted sentence. A sentence with neither points at the answer instead of
being it, and `not_answerable` is the honest verdict.

**1.8.0** — the refusal pass. Three of the four things fixed here were found by
pointing the auditor at a live origin behind a proxy rather than at a fixture,
which is the one thing the bundled sites cannot simulate: a site that never
answers.

**A 403 was read as a canonicalisation defect.** `rule_https_upgrade` returned a
finding for any non-zero status on the `http://` probe and never asked whether
that status was the site answering or something refusing. An origin behind a
proxy answering `403` produced *"The http:// origin does not redirect to
https:// … with status 403"* at `high`, about a site that redirects correctly.
The probe is now disqualified by a refusal status (401/403/407/408/429/451/5xx)
and by a transport failure on the same host's `robots.txt` — which had already
been reported honestly as `info` by `CR-ROBOTS-NOT-REACHED`, so one event was
producing two contradictory verdicts.

**The headline described content nobody read.** The same run printed
*"example.com is reachable but 1 high-severity gap(s) stop assistants quoting
its facts"* over `pages_fetched: 0`. The band cap added in 1.5.1 guarded the
label and not this sentence, which is the line most readers act on. A run with
no parsed page now says so, names why in the site's own terms — a wall, a
robots disallow, a transport failure, or an empty crawl — and states that it
makes no claim about content. `summary.coverage_state` (`content` /
`transport_only`) carries the same fact for machines.

**Bot walls were invisible.** The auditor sends an honest, unknown User-Agent,
and a growing share of sites answer unknown agents with a challenge. That
produced the worst report the tool can produce: nothing fetched, two transport
findings, and a score. `assess_access` now records the refusal pattern and
`CR-BOT-WALL` reports it — `critical` when the front door itself is refused —
separating what was observed (this audit was refused) from the risk that
follows (a wall scoring agent reputation refuses assistant crawlers on the same
basis), because only the site owner's edge logs can settle the second.
`--user-agent` allows an operator to pass their own allowlist; strings that
impersonate a browser or a named crawler are rejected by config validation
before a socket opens.

**Three rules and two recommendations from the Round-2 trace.**
`MR-OPEN-GRAPH-INCOMPLETE` — Open Graph was read for the entity rules and never
audited, though it is the only structured summary a page offers about itself
without its body being parsed.
`MR-FACTS-IN-OPAQUE-DOCS` — the crawler excludes `.pdf` from the frontier by
design, so a site whose spec sheets and price lists exist only as PDFs produced
no finding at all and read as clean; the documents are counted from the links
the site publishes, never opened, and the evidence item is anchored to the page
that was fetched. `EN-LOCATIONS-UNSTRUCTURED` — a store locator with no
`LocalBusiness`, `Store` or `PostalAddress` anywhere in the crawl, which is the
shape that gets a branch invented. `OPP-EXPLICIT-ABSENCE` recommends publishing
the negative attributes that stop a model completing a gap from what comparable
products usually have; `OPP-INTENT-COVERAGE` covers the other framings of the
same question, including locale.

**A generator that raised produced silence.** `build_opportunities` catches
every exception so one bad generator cannot cost a reader their report — and a
`NameError` in a new recommendation therefore removed it from every report with
nothing logged. `TestGeneratorsNeverSilentlyDie` calls each generator directly,
where nothing is caught. 37 new tests, 443 in total, still under a minute.

**Also:** the changelog moved here, out of a README the brief asks to keep
short.

**1.7.0** — a correctness pass aimed squarely at the failure the rubric is
built to punish: a confident wrong finding on a site nobody here designed for.
The previous release fixed *coverage* (the crawl not reaching enough pages);
this one fixes *judgement* (the rules over-reading what the crawl did reach).
Seven rules produced evidence strings the page in front of the reader refutes,
three of them at `critical`, which is the severity that writes the report
headline.

**Two robots.txt bugs, one of them a compliance hole.** Permission was checked
on the URL about to be requested and never re-checked on the URL that actually
served the bytes, so a permitted URL that redirected into a disallowed path
handed us content robots.txt had refused — and the same report would list that
URL as blocked while quoting its body. The final URL is now re-authorised, and a
redirect onto another host is checked against *that host's* robots.txt, fetched
on demand. Separately, product-token matching accepted a substring, so a
robots.txt saying `User-agent: bot / Disallow: /` was read as blocking ten of
the nineteen assistant crawlers this tool tracks — a fabricated `critical` about
a site doing nothing wrong. Matching is now the prefix test RFC 9309 §2.2.1
specifies. Records repeating one user-agent are merged rather than the first
winning and the rest being silently dropped, and an empty `Allow:` no longer
builds a zero-length pattern that could be cited as a deciding rule.

**Three rules that fired on healthy sites.** `__NEXT_DATA__` is emitted by every
Next.js page, server-rendered ones included; combined with a flat 120-word
floor applied to policy and contact pages, a fully server-rendered site was
reported as an empty JavaScript shell at `critical`, with an SSR migration as
the prescribed fix. Mount points are now confirmed empty against the parsed DOM,
hydration payloads are recorded separately and are never sufficient alone, and
the word floor applies only to page types whose volume means something.
`MR-FACTS-NOT-IN-TEXT` read "no price + an image" as a price locked inside a
banner, handing every quote-on-request catalogue — industrial, medical,
wholesale, made-to-order — a fabricated top-priority `critical`; it now
recognises the invitation to request a quote, and reports the genuinely
inconsistent case (a site that prices its catalogue but not these pages)
instead. `FC-STALE-CONTENT` called a correctly dated 2019 news story stale, from
`datePublished` alone and with no ratio gate, so one old page escalated a whole
site; it now reads maintenance dates, skips archival page types, and needs a
share of the sample behind it.

**`commerce_guard` was written, documented and never called.** Worse, a
category-shaped URL alone counted as evidence of a catalogue — and
`/category/<slug>/` is the default WordPress archive path, so newspapers, blogs
and university news sections were audited as shops and told to add filters to
"the attributes these product pages already publish". A listing page now counts
only when it points at products or quotes prices, which keeps storefronts whose
crawl reached only collection pages, and the five catalogue-shaped engagement
rules consult the guard.

**Non-English sites.** Three engagement rules skipped the `language_supported`
guard their siblings applied, so a Polish storefront printing stock, ratings and
a comparison link was told it had none of them. The title-noise list was
English-only, so a localized "Home" — `Inicio`, `Accueil`, `Startseite` —
survived as a candidate brand and was reported as a second trading name at
`high`. Search-form detection matched only the English string `search`, though
the page classifier already knew `/recherche` and `/buscar`. Name folding
stripped every non-ASCII character, collapsing three distinct Chinese products
to `"pro"` and Cyrillic or Greek names to the empty string, which switched the
entity rules off without the report saying so. All four are fixed, five
languages were added to the vocabulary, and phrases that contain a concept's
words without meaning it — "return to top", "content delivery network",
"energy rating" — no longer match.

**Prices.** `₹1,20,000` parsed as **1.2**, because the grouped branch required
three-digit runs and the Indian lakh grouping fell through to the plain branch;
that produced an `FC-PRICE-CONFLICT` reading "markup says 120000, page shows
1.2" on a page whose text and JSON-LD agreed exactly. Groups may now be two or
three digits, and `₱`, `Rp` and `RM` are recognised.

**Evidence honesty.** `blocked_by_robots` and the crawl-truncation note were
recorded and read by no rule, so a site whose robots.txt disallows `/faq` was
told it "answers no questions in question form". Absence rules now name what the
crawl could not see and step their severity down when coverage is incomplete. A
transport failure on the auditor's own side — a proxy, DNS, TLS or bot-wall
refusal — is reported as an audit-coverage limitation rather than as the site's
`critical` defect. Off-site anchors, which the audited site controls, are
refused when they resolve to a private, loopback or link-local address. Cart
URLs such as `?add-to-cart=` are kept out of the frontier, where one document
under three query strings had been counted as three product pages. The soft-404
probe is seeded from the origin rather than the clock, so two runs of one site
now produce byte-identical output apart from the timestamps. The full Apache-2.0
text ships with the package the seven skills declare it under.

Twenty-nine new tests — twenty-six of them in `tests/test_generalization.py` —
each one failing before the fix it names. Their assertions are mostly negative,
which is the gap they close: the rest of the suite proves the rules fire on
broken sites and says almost nothing about whether they stay quiet on sites
that are merely unfamiliar. Suite total 377 → 406, still under a minute.

**1.6.0** — the audit's verdict was partly a property of the site's **URL
scheme**, and that is the one defect that decides whether this works on a site
nobody designed it for. The crawl budget was handed out against
`classify_page(url)` — a guess made *before* anything was fetched — with a
quota per predicted type, and whatever a quota did not spend was discarded. A
store writing `/shop/blue-mug` rather than `/products/blue-mug` matched no
product hint, so its entire catalogue was filed under `other` (quota 4) while
the twelve product slots went unused: **5 pages fetched against a budget of
40**. Every ratio in the report — "8 of 12 product pages have no price" — was
then computed over almost nothing, and the sample-size guards added in 1.5.0
correctly declined to generalise from three pages, so the report came back
nearly empty and *read as clean*. Measured on one storefront written twice: 28.3
"critical" under familiar URLs, **57.1 "weak"** under unfamiliar ones. The
quotas now govern only the first round; the remainder is handed back out
round-robin, so one large bucket — a blog, a paginated archive — cannot crowd
out the catalogue the first round was starving. The same site now scores 28.3
under either spelling, and a new end-to-end test builds it both ways and fails
the build if the two verdicts diverge.

Page type is also read from more of what a page declares about itself:
schema.org **microdata**, **Open Graph `og:type`** and Twitter product cards
join JSON-LD, consulted only after the URL says nothing, so a site with
recognisable URLs classifies exactly as before. A fourth content signal
(`availability_text`) was tried and reverted — it reads from the same prose as
the price, and it reclassified a comparison page as a product page.

`/wp-admin`, `/wp-login.php`, `/administrator`, `/my-account`, `/auth` and
`/password` join the never-crawled list; `admin` alone never covered the
platforms an unseen site is most likely to be built on. And the brief's
non-negotiables are now a test class rather than a paragraph:
`TestBriefConstraints` asserts read-only behaviour, the absence of any
authentication surface, no form submission, no conversational or ranking
surface, evidence reuse, whole-report determinism, evidence on every finding,
steps and a verification on every recommendation, and a page budget that is
actually reachable. 26 new tests, 377 in total.

**1.5.1** — two ways the auditor could still claim more than it observed, and
two recommendations that spoke past the site in front of them. A crawl that
read **zero pages** scored 93.2 on the strength of a healthy `robots.txt`
alone and was labelled **"strong — machines can find, read, attribute and act
on this site"**, about a site it never read: renormalising the weighted mean
over the one measured pillar kept the arithmetic honest but left the *band*
free. The score is now reported exactly as computed, and the band alone is
capped at `weak` when less than half the model's weight had evidence behind
it — a ceiling, never a floor, so the ordinary all-pages-error run keeps the
band its score already earned. `answerability` scored **100.0 off an empty
question matrix**: a documentation or brochure site that raises no buyer
question was being credited with 0.15 of unearned weight, worth 4.4 points of
overall score. Zero questions evaluated is now `unmeasured`, not perfect. The
published weight table still listed the pre-answerability five-pillar weights;
it now matches `PILLAR_WEIGHTS`, and the "five pillars / five specialists"
counts left in the prose are six. `MR-NO-STRUCTURED-DATA` told every site to
add "Product + Offer", including sites with no catalogue — the finding is
unchanged, the recommendation now follows the observed site type — and
`FC-NO-CORROBORATION-ANCHORS`, whose evidence reads "no sameAs on any crawled
page", now respects the same `crawl_yielded_evidence()` gate as the other
absence rules while the broken-anchor observation beside it stays ungated. 16
new tests, 351 in total.

**1.5.0** — a robustness pass plus a sixth specialist. Correctness first:
`$1200` was read as **120** by the price regex (a grouped alternative matching
a prefix), which fabricated `FC-PRICE-CONFLICT` findings against sites whose
markup was correct — the pattern now handles prefix and postfix currency in
sixteen tested formats and refuses partial digit runs. `word_count()` matched
Latin characters only, so Cyrillic, Japanese, Arabic and Devanagari pages
counted as **zero words** and fired every thin-content rule; counting is now
Unicode-aware with character-volume handling for unsegmented scripts. A crawl
that fetched nothing produced a report full of absence findings — a
bundle-level `crawl_yielded_evidence()` gate now suppresses them. `home_page()`
silently substituted `pages[0]` when the root fetch failed, so findings about
"the home page" named a product page; it now returns `None`. Commerce rules
fired on documentation and B2B sites; `commerce_evidence()` gates them on
observed product pages, commerce markup or a cart affordance. Severity is
capped by sample size, page classification uses declared types as well as URL
shape, brand-first titles are no longer read as two brands, `alt=""` is treated
as the correct decorative marking it is, and the handout/flat summaries now
reconcile (`critical + high + medium + low + info = total`).

Then the new skill: **`answerability-audit`**, a sixth pillar that asks whether
the crawled evidence can answer the questions a buyer would ask — generated
from the site's own catalogue, never a stock list, resolved to
`answerable`/`partial`/`not_answerable` with a citing URL and the snippet
found. The report carries the full answerability matrix. 40 new tests, 335 in
total.

**1.4.3** — a final correctness pass. `MR-SITE-SCHEMA-MISSING` claimed a
missing Organization node was "the root cause" of a brand being unrecognised
or confused with another company; it now reports the absence and says
explicitly that the audit does not test, and does not claim, that any system
failed to identify the brand. A collection page served 200 with a heading like
"Uh-Oh, Nothing To See Here!" had that string adopted as the site's category
noun and printed into every generic example — the vocabulary now takes a
heading only from a listing with actual members (product links the crawl
found, or an ItemList with entries), falling back to `<Category>`. The two
review findings are kept as the independent dimensions they are, but
`MR-REVIEW-MARKUP-MISSING` did not test the visibility its own title claimed,
so a client-rendered page was reported by both it and
`EG-REVIEWS-CLIENT-RENDERED` and the same absence was scored against two
pillars; the populations are now disjoint and cross-referenced. And a crawl
that fetched zero pages scored **72.4 / "workable"**, because four pillars sat
at a default 100 having never been measured — an unmeasured pillar now scores
`null` and is excluded from the weighted mean (weights renormalised, not
changed), so that same run reports 6.4 over 1 of 5 pillars. 12 new tests, 293
in total.

**1.4.2** — a quality pass, then an adversarial review of that pass which
found nine defects in it. Findings now carry a `confidence_level`
(high/medium/low, a fixed threshold over the numeric confidence) and a
`sampling` block stating what was measured over — `3/12 sampled product
page(s)`, `site-wide observation`, `template-wide observation` — so a small
sample can no longer read as a universal fact. Filter and sort findings name
the facets and sort options they actually observed rather than returning a
boolean. Entity names carry one of four roles (trading / legal / copyright /
social), and role now comes from *where a name was declared* rather than how
it ends: the previous suffix heuristic was silently reclassifying trading
names like "…Spa", "…Company" and "…Group" as legal entities and excluding
them from conflict detection, which suppressed genuine findings. Profile
handles are read as identities rather than URL tails (`/company/acme/about`
gives `acme`, not `about`), copyright holders no longer absorb the footer text
preceding the © mark, and filter query tokens are matched against query
parameters instead of as substrings of the path — a product at
`/products/refined-coconut-oil` was being counted, and named, as a refinement
facet. Two more observations that asserted an incapacity ("a machine cannot
read it", "any assistant that cites those URLs") moved to `interpretation`,
with a guard that fails the build if the pattern returns. 19 new tests, 281 in
total.

**1.4.1** — a second review pass, against a storefront whose registered
company differs from its trading name. Three findings claimed more than the
evidence supported, all generically. `EN-NAME-INCONSISTENT` pooled the trading
name, `legalName` and the footer copyright holder into one set and reported
the spread as a defect — so a site that had done exactly what the rule
recommends was told to fix it; names now carry a *role*, only trading names
compete, and the copyright parser no longer reads "All Rights Reserved" as a
company. `EN-CATEGORY-UNDECLARED` claimed products were "structurally
ineligible" for category answers, which an absence in markup does not
establish; it now reports what is missing and what that can make harder.
`CR-NOINDEX-ON-IMPORTANT-PAGES` diagnosed intent ("usually left over from a
staging config") and went straight to `critical`; it now asks the owner to
confirm, excludes carts, accounts, logins and internal search as conventionally
non-indexed, and scales severity with how many discoverable pages are affected
and whether the sample supports calling it template-wide. Nothing was tuned to
raise a score, no site-specific handling was added, and a genericity scan of
all 34 production files finds zero website-specific terms — 16 new tests, 262
in total.

**1.4.0** — a manual review of a live audit found five ways the report claimed
more than it had measured, and one way it described the wrong website
entirely. Filtering and sorting were reported as a single affordance, so a
listing with nine sort options was told it had none: they are now two rules
with separate evidence (`EG-FILTER-CONTROLS-ABSENT`, `EG-SORT-CONTROLS-ABSENT`)
and a four-case regression suite. Attributes stated in visible copy were
reported as absent rather than unstructured; `MR-ATTRIBUTES-THIN` and
`EG-SPECS-MISSING` now measure visible and typed presence separately and say
what was found in which form. A page printing its own last-updated date was
called undated; `FC-NO-DATE-SIGNALS` now quotes the visible date and
recommends marking it up rather than adding it. `EG-LEAD-ANSWER-WEAK` claimed
carousels, modals and bounces that no static fetch can observe, and now
measures document order and records `render_mode` and `viewport`. Worked
examples were hardcoded to a footwear brand from an unrelated case study;
they are now assembled by `lib/aiva/examples.py` from the audited site's own
names and attributes, with neutral placeholders as the fallback, and a
regression test fails the build if a report mentions a website it did not
crawl. Findings now carry `observation` and `interpretation` as separate
fields, actions carry `verification_type`, and the model *rejects* a finding
whose evidence line asserts a consequence the audit did not measure — 33 new
tests, 246 in total.

**1.3.0** — a review pass found the audit was penalising sites for not being
English, which is the exact failure the "generalization" criterion is about:

- the prose-reading checks now try typed markup first (`OfferShippingDetails`,
  `MerchantReturnPolicy`, a cart-targeting form), then a multilingual
  vocabulary (`lib/aiva/lexicon.py`: en, es, fr, de, pt, it, nl), and stay
  silent on languages they cannot read rather than reporting an absence;
- money is parsed under both grouping conventions — `EUR 5.499` is 5499, not
  5.499. The English-only reading raised a `high`-severity
  `FC-PRICE-CONFLICT` on every storefront that groups thousands with a dot;
- question headings are detected by the trailing `?` rather than by English
  interrogatives, and URL page-type hints cover the common Romance/Germanic
  spellings (`/productos/`, `/produits/`, `/kategorien/`,
  `/preguntas-frecuentes`, `/devoluciones`…);
- regression test: a well-built Spanish storefront must produce **zero**
  engagement findings. Before this change it produced four.

**1.2.0** — from the second live run of the same storefront:

- the audit now probes both agent-facing discovery conventions (`/llms.txt` and
  `/agents.md`), records what it finds in `coverage.ai_discovery_surfaces`, and
  only recommends publishing one when the site has neither
  (`OPP-LLMS-TXT` → `OPP-AI-DISCOVERY-SURFACE`);
- `evidence_reuse_ratio` now counts every fetch the shared evidence layer
  avoided — cache hits *plus* duplicate candidate URLs collapsed between the
  navigation and the sitemap — instead of cache hits alone, which read as 0.0
  on a site that simply had no repeats;
- the http→https probe uses a short timeout, so a host that silently drops
  plain HTTP costs a few seconds of the budget rather than the full allowance.

**1.1.0** — five fixes found by the first audit of a real, unseen storefront:

- the site root is now always fetched and audited as the home page, and a
  deeper URL passed in is kept as the *entry point* (previously a
  `/collections/…` URL was relabelled as the home page, which pointed the
  site-wide identity checks at the wrong document);
- non-HTML and error responses now carry a `page_type` and a `fetch_reason`
  instead of appearing as `unknown`/`null` in coverage;
- social **share** endpoints (`sharer.php`, `/intent/`, `pin/create`, …) are no
  longer counted as official profile links — they share a host with real
  profiles but assert nothing about identity;
- cart, checkout and account paths and binary assets are excluded from the
  frontier, so crawl budget goes to citable pages;
- discovery now counts the duplicate candidate URLs it collapses
  (`duplicate_urls_collapsed`), which is the number that actually evidences the
  fetch-once guarantee on a site whose navigation and sitemap overlap.

**1.0.0** — initial submission.

