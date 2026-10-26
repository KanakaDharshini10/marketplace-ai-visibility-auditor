---
name: machine-readability-audit
description: Check whether a machine can parse a page's facts once it has reached it.
  Reads a shared evidence bundle and reports missing, invalid or context-less
  schema.org JSON-LD, product pages with no Product node, Offers without price,
  priceCurrency or availability, products with no sku/gtin/mpn identifier, catalogues
  with no comparable attributes, review and rating content that is visible but not
  marked up, missing BreadcrumbList, a home page that declares no Organization or
  WebSite, absent titles, meta descriptions, h1 structure or lang, images without alt
  text, microdata used where JSON-LD would survive a redesign, pages with no usable
  Open Graph summary, specification and price facts published only inside linked PDFs
  or office documents, and the decisive case where a buying fact such as price exists
  nowhere in the response as text. Use as the second stage of an AI-visibility audit,
  or when assistants misquote a product's price, stock or specifications, or ignore
  the page as a source.
license: Apache-2.0
compatibility: Requires Python 3.9+. Consumes an evidence bundle; performs no network I/O.
allowed-tools: Bash(python3:*) Read
metadata:
  role: specialist
  pillar: machine_readability
  dimension: discoverability
  marketplace: marketplace-ai-visibility-auditor
---

# Machine readability audit

**Pillar:** `machine_readability` · **Dimension:** discoverability · Stage 2 of
the discovery funnel.

The page is reachable. Can a program extract the specific fact somebody asked
for? A page that looks complete to a person is not always complete to a machine:
the more explicitly and unambiguously a fact is stated in plain, readable text
and typed markup, the more likely it is to be extracted correctly; the more it is
implied, styled, or locked inside something non-textual, the more likely it is
missed — or invented.

## When to use

After `crawl-render-audit`, or standalone when assistants describe a product
inaccurately, quote the wrong price, or decline to answer a question the page
plainly answers.

## Input / output

Input: the shared evidence bundle. Output: `list[Finding]` in the
`machine_readability` pillar.

```bash
python3 skills/machine-readability-audit/scripts/analyze.py --bundle bundle.json
```

Performs no network I/O.

## What it checks

| Rule | Severity | What it means |
|---|---|---|
| `MR-NO-STRUCTURED-DATA` | critical | no JSON-LD, microdata or RDFa anywhere in the sample |
| `MR-FACTS-NOT-IN-TEXT` | critical/high | no price in the text *and* none in markup, while images are present — the fact is pixels or script |
| `MR-PRODUCT-SCHEMA-MISSING` | critical/high | product pages with no `Product` node |
| `MR-JSONLD-INVALID` | high | a block fails to parse, so the whole block is discarded silently |
| `MR-OFFER-MISSING` | high | `Product` with no `offers` |
| `MR-OFFER-INCOMPLETE` | high/medium | `Offer` missing `price`, `priceCurrency` or `availability` |
| `MR-IDENTIFIERS-MISSING` | high/medium | no `sku`/`gtin`/`mpn`, so listings elsewhere cannot be matched to this product |
| `MR-ATTRIBUTES-THIN` | high/medium | fewer than two typed attributes and no spec block; reports separately how many attributes the page states in visible copy |
| `MR-SITE-SCHEMA-MISSING` | high/low | home page declares no `Organization` (and/or no `WebSite`) |
| `MR-JSONLD-CONTEXT` | medium | `@context` missing or not schema.org, so `@type` resolves to nothing |
| `MR-BREADCRUMB-MISSING` | medium | no `BreadcrumbList` and no breadcrumb nav on product/category pages |
| `MR-REVIEW-MARKUP-MISSING` | medium | reviews referenced in the text with no `AggregateRating`/`Review` |
| `MR-HEADING-STRUCTURE` | low | no top-level heading names the page's subject (the headings repeat the site name or a section label). Several `<h1>` elements, or a page led by an `<h2>`, are permitted by HTML and are not reported |
| `MR-TITLE-MISSING` | medium | empty or absent `<title>` |
| `MR-IMAGE-ALT-COVERAGE` | medium | >50% of images have no usable alt text |
| `MR-META-DESCRIPTION-MISSING` | low | most pages have no meta description |
| `MR-OPEN-GRAPH-INCOMPLETE` | high/medium | most quotable pages are missing `og:title`, `og:description` or `og:type` — the summary the page offers about itself without its body being parsed |
| `MR-FACTS-IN-OPAQUE-DOCS` | medium | three or more spec sheets, price lists or catalogues linked as PDFs/office documents with no HTML equivalent. The documents are counted, never opened |
| `MR-MICRODATA-ONLY` | low | inline microdata with no JSON-LD — valid, but entangled with the design |
| `MR-LANG-MISSING` | low | no `lang` attribute on any page |

## How it decides

- **Visible presence and structured presence are measured separately.** A page
  stating "cocoa butter content: 22%" in its copy has published the attribute;
  what it lacks is a `PropertyValue` an extractor can read without parsing a
  sentence. `MR-ATTRIBUTES-THIN` reports the *format*, names the attributes it
  found and in which form, and never claims the information is absent when it
  is merely unstructured.
- **Worked examples are built from the audited site.** Every JSON-LD snippet in
  a recommendation is assembled by `lib/aiva/examples.py` from names, prices,
  categories and attributes read back out of the crawl - falling back to
  `<Placeholder>` slots when nothing was observed. No example names a product,
  brand or attribute the auditor did not see.

- **Aggregate, then report once.** Each rule counts affected pages against
  sampled pages of the relevant type, quotes both numbers in its evidence, and
  emits one finding with per-page `evidence_items`.
- **Reference resolution.** `{"@id": "…"}` references are resolved against the
  whole crawl's JSON-LD graph before any judgement, so a well-built site that
  declares its brand once and references it everywhere is not mistaken for one
  with a different brand on every page.
- **Aggregate offers count.** `AggregateOffer` with `lowPrice`/`highPrice`
  satisfies the price check; a `ProductGroup` whose variants carry the offers is
  not reported as offer-less.
- **Thresholds, not absolutes.** Most rules need a ratio (e.g. ≥40% of pages)
  before firing, so one odd page in a healthy catalogue does not become a
  finding.

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

- [references/checks.md](references/checks.md) — what each schema.org field buys you, the minimum viable Product block, and the failure modes of structured data.
