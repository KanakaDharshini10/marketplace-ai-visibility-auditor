---
name: freshness-corroboration
description: Check whether a website's machine-readable facts are current, internally
  consistent and supported by more than one source. Reads a shared evidence bundle and
  reports pages with no machine-readable date, sitemaps with missing, uniform or
  future lastmod values, stale content and stale footer copyright years, structured
  data whose price contradicts the price shown on the page, availability markup that
  contradicts the stock message, the same product priced differently on a listing and
  on its own page, expired priceValidUntil, reviews that are undated or years old, a
  brand whose facts exist in exactly one place on the web, and declared sameAs anchors
  that do not resolve. Use as the third stage of an AI-visibility audit, or when
  assistants repeat outdated prices, discontinued products, an old logo or a retired
  tagline despite the website having been updated.
license: Apache-2.0
compatibility: Requires Python 3.9+. Consumes an evidence bundle; performs no network I/O.
allowed-tools: Bash(python3:*) Read
metadata:
  role: specialist
  pillar: freshness_corroboration
  dimension: discoverability
  marketplace: marketplace-ai-visibility-auditor
---

# Freshness & corroboration audit

**Pillar:** `freshness_corroboration` · **Dimension:** discoverability · Stage 3.

A page can be crawlable and perfectly marked up and still state a fact that is
out of date, contradicted elsewhere on the same site, or unsupported by any
other source the site itself points to. Three distinct gaps are measured here:
the site disagrees with itself, nothing on the page says which version is
current, or the site declares no independent source that repeats the fact.
Whether any consumer of that evidence prefers corroborated or recent facts is
not something this audit measures.

This is the pillar behind the classic complaint: *"we updated the site, and the
assistants still quote the 2019 price."* Updating your own page does not remove
the old version from the wider web — it just adds one more source to a vote you
are currently losing.

## When to use

After `machine-readability-audit`, or standalone when assistants state facts
about the brand that used to be true.

## Input / output

Input: the shared evidence bundle. Output: `list[Finding]` in the
`freshness_corroboration` pillar.

```bash
python3 skills/freshness-corroboration/scripts/analyze.py --bundle bundle.json
```

Performs no network I/O: the off-site anchor checks were made once during
collection and are read from the bundle.

## What it checks

| Rule | Severity | What it means |
|---|---|---|
| `FC-PRICE-CONFLICT` | high | `Offer.price` appears nowhere in the page's visible text |
| `FC-AVAILABILITY-CONFLICT` | high | markup says in stock while the page says sold out (or the reverse) |
| `FC-CROSS-PAGE-PRICE-CONFLICT` | high | the listing and the product page state different prices for the same product |
| `FC-NO-CORROBORATION-ANCHORS` | high | no `sameAs`, `rel=me` or knowledge-host link anywhere: every fact is single-source |
| `FC-NO-DATE-SIGNALS` | medium/high | no `dateModified`, `<time datetime>` or `Last-Modified` on most pages *where a date is expected or useful* - a home page, a contact page and a listing carry no dated fact and are set aside; reports separately whether a last-updated date is stated in visible copy |
| `FC-STALE-CONTENT` | high/medium | dated pages older than the staleness threshold (default 365 days) |
| `FC-SITEMAP-NO-LASTMOD` | medium | ≥50% of sitemap entries have no `lastmod` |
| `FC-SITEMAP-LASTMOD-UNIFORM` | medium | every entry shares one date — the field tracks the build, not the content |
| `FC-SITEMAP-LASTMOD-FUTURE` | medium | dates in the future invalidate the field as a signal |
| `FC-PRICE-VALID-UNTIL-EXPIRED` | medium | the offer states its own price is no longer guaranteed |
| `FC-REVIEWS-UNDATED` | medium | `Review` nodes with no `datePublished` |
| `FC-REVIEWS-STALE` | medium | newest marked-up review older than the threshold (default 540 days) |
| `FC-BROKEN-CORROBORATION-ANCHOR` | medium/low | a declared `sameAs`/profile URL answers 404/410 (medium). A refusal, rate limit, timeout or server error is reported as "could not be verified" (low), and never as a "dead profile" |
| `FC-STALE-COPYRIGHT` | medium/low | footer copyright year is years behind |

## How it decides

- **A visible date is a real signal, and is reported as one.** A page printing
  "This data was last updated on 2026-09-01" has published its currency; it has
  simply not exposed it through a mechanism with a declared meaning. The rule
  measures `visible_freshness_signal` and `machine_readable_freshness_signal`
  separately, drops to `medium` when the visible date exists, quotes it in the
  evidence, and recommends *keeping* it while adding the typed form - rather
  than telling a site owner to publish a date they are already publishing.

- **Conflicts are only reported when both sides were observed.** A price
  conflict needs a markup price *and* at least one currency-formatted price in
  the text; if the page shows several prices (list and sale), a markup price
  matching any of them is not a conflict.
- **Availability conflicts require an unambiguous contradiction.** A page
  containing both "in stock" and "out of stock" wording is not reported, because
  the auditor cannot tell which applies to the variant being described.
- **A `Last-Modified` header counts as a date signal**, so a site with honest
  server dates is not told it has none.
- **Corroboration is checked, never searched.** The audit verifies that the
  anchors *the site itself declares* resolve. It does not query a search engine
  and does not crawl third parties, so it can prove a declared anchor is broken
  but cannot enumerate who else describes the brand — the remedy for that is the
  monitoring loop in the report's proactive recommendations.

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

- [references/checks.md](references/checks.md) — the freshness signal hierarchy, why self-contradiction is worse than silence, and how to run a third-party correction pass.
