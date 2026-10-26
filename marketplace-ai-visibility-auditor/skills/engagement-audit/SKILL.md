---
name: engagement-audit
description: Check whether visitors an AI assistant sends to a website actually land on
  the answer they were promised. Reads a shared evidence bundle and reports product
  pages whose first screen states no price or availability, missing specification
  blocks, category pages with no filtering or sorting, absent reviews or reviews
  rendered only by a client-side widget, no FAQ content anywhere, shipping, returns
  and stock information missing from product pages, policy terms in prose with no
  MerchantReturnPolicy or OfferShippingDetails markup, no comparison support across a
  range, purchase actions that exist only after hydration, product pages that are dead
  ends with no breadcrumb or onward links, deep links redirected to the home page, no
  site search, and no mobile viewport. Use as the engagement half of an AI-visibility
  audit, or when AI-referred traffic arrives and bounces.
license: Apache-2.0
compatibility: Requires Python 3.9+. Consumes an evidence bundle; performs no network I/O.
allowed-tools: Bash(python3:*) Read
metadata:
  role: specialist
  pillar: engagement
  dimension: engagement
  marketplace: marketplace-ai-visibility-auditor
---

# Engagement & comparison-readiness audit

**Pillar:** `engagement` · **Dimension:** engagement · The on-site half of the
problem.

Discoverability gets the brand into the answer. This decides whether the click
that follows is worth anything. The recurring failure is a **continuity**
failure: the assistant answered something specific — a model, a price, a size, a
return window — and the landing page makes the visitor start the search again.

Everything here is checked against what a plain fetch can see, because that is
the evidence a non-JavaScript reader of the page has. A fact that is not in the
HTML is not stated by the page to such a reader, so the page cannot confirm it
for a visitor who arrives expecting it. What any particular assistant read
before linking to the page is not something this audit observes.

## When to use

Alongside the discoverability specialists in a full audit, or standalone when
analytics show assistant-referred traffic arriving and bouncing.

## Input / output

Input: the shared evidence bundle. Output: `list[Finding]` in the `engagement`
pillar.

```bash
python3 skills/engagement-audit/scripts/analyze.py --bundle bundle.json
```

Performs no network I/O.

## What it checks

| Rule | Severity | What it means |
|---|---|---|
| `EG-LEAD-ANSWER-WEAK` | high/medium | the first ~1,200 characters of a product page, in document order, carry no price and/or no availability |
| `EG-SPECS-MISSING` | high/medium | attributes are published, but not inside a spec table, `<dl>` or typed attribute block |
| `EG-FILTER-CONTROLS-ABSENT` | high/medium | category pages with no filter, facet or refine control in the HTML |
| `EG-SORT-CONTROLS-ABSENT` | medium/low | category pages with no sort or order control in the HTML |
| `EG-REVIEWS-ABSENT` | medium | no review or rating content on the product pages reviews apply to (goods and software; a service page is not asked) |
| `EG-REVIEWS-CLIENT-RENDERED` | high | reviews referenced, many external scripts, no review text in the response |
| `EG-AVAILABILITY-INVISIBLE` | high | no stock statement in text or markup |
| `EG-SHIPPING-INVISIBLE` | high/medium | no delivery information on the product pages delivery applies to (physical goods, or a page that states delivery terms itself) |
| `EG-RETURNS-INVISIBLE` | high/medium | no return information on the product pages returns apply to (physical goods, or a page that states return terms itself) |
| `EG-DEEPLINK-REDIRECTED-HOME` | high | deep links collapse onto the home page |
| `EG-FAQ-MISSING` | medium | no FAQ page, no `FAQPage` markup, no question-shaped headings |
| `EG-POLICY-NOT-STRUCTURED` | medium | policy terms in prose only, with no `MerchantReturnPolicy`/`OfferShippingDetails`, on pages those terms apply to |
| `EG-COMPARISON-UNSUPPORTED` | medium | nothing supports comparing one model with another |
| `EG-CTA-NOT-IN-HTML` | medium | no purchase affordance in the server-rendered page |
| `EG-PRODUCT-DEAD-END` | medium | <6 internal links and no breadcrumb |
| `EG-NO-SITE-SEARCH` | low | no search input, form or `SearchAction` anywhere, on a site *observed* to be larger than a visitor can browse (many advertised URLs, a paginated listing, or a crawl that spent its page budget) |
| `EG-NO-VIEWPORT` | low | no mobile viewport, and most assistant referrals are on a phone |

## How it decides

- Every rule requires that the crawl actually sampled the relevant page type;
  none infers an absence from a sample it did not take.
- Most rules need a majority (typically ≥50–60% of sampled pages of that type)
  before firing, so one thin page in a healthy catalogue is not a finding.
- `EG-REVIEWS-CLIENT-RENDERED` is a heuristic (review wording + heavy external
  scripting + no review text) and ships at reduced confidence, because it infers
  a cause rather than observing one.
- **Language is not assumed.** The few checks that read prose (delivery,
  returns, stock, a way to buy) look for typed markup first - `OfferShippingDetails`
  and `MerchantReturnPolicy` state the same facts language-neutrally - then match
  a multilingual vocabulary (`lib/aiva/lexicon.py`), and finally stay *silent*
  when the page's declared language is one the vocabulary does not cover. A
  Spanish storefront saying "Envío gratis. Devoluciones en 30 días. En stock."
  states all three facts, and reporting them as missing would be a false
  positive caused by the auditor's own assumptions.
- Findings distinguish *invisible to a fetch* from *absent*: both hurt, but the
  fixes are different, and the evidence string says which was observed.
- **Filtering and sorting are two affordances, not one.** They answer different
  questions - a constraint needs non-matching products removed, a superlative
  needs the set re-ordered - so each has its own rule, its own evidence and its
  own severity. A listing offering nine sort options and no filters gets one
  finding naming the filtering, and its evidence says the sorting is there.
- **Unstructured is not absent.** `EG-SPECS-MISSING` reports the *shape* of the
  presentation. Where a page states attributes in visible copy, the evidence
  counts them and says so; the finding is that they are not in a standardized
  structure, never that the information is missing.
- **No claim the audit cannot make.** Without a headless render at a known
  viewport there is no way to observe what is above the fold, what a carousel
  does, or whether anyone bounced. `EG-LEAD-ANSWER-WEAK` therefore measures
  *document order* in the fetched bytes, records `render_mode` and `viewport`
  in its metrics, and says in the evidence which of the two it measured.

## Why this skill shares the marketplace library

This skill imports `lib/aiva` from the marketplace root rather than vendoring
its own copy, and that is the architecture rather than an oversight. The brief
requires evidence to be gathered **once** and reused: a specialist carrying its
own extraction code would either re-fetch pages (breaking the fetch-once
guarantee) or re-derive facts from raw HTML and drift from the definitions the
other specialists reason with. Composition here is *one crawl, one frozen
bundle, many analyzers* - the entrypoint resolves every specialist from
`marketplace.json` and hands each the same JSON document.

The skill is standalone in the sense that matters for the contract: it exposes
`analyze(bundle) -> list[Finding]`, runs from the command line against a saved
bundle, and performs no network I/O. See
`skills/marketplace-ai-visibility-audit/references/orchestration.md`.

## Reference

- [references/checks.md](references/checks.md) — the continuity model, what belongs on the first screen, comparison readiness, and how to measure the effect.
