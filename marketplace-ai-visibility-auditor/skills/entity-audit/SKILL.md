---
name: entity-audit
description: Check whether a website defines unambiguously who and what it is. Reads a
  shared evidence bundle and reports a thinly described Organization, a brand called
  different things across schema.org name, legalName, og:site_name, the title suffix,
  the footer copyright and Product.brand, products not connected to the brand,
  product brand strings that drift from the organisation, structured data
  with no stable @id, several URLs claiming to be the same product, duplicate page
  titles, products that declare no category or breadcrumb, size and colour variants
  that exist in the UI but not as addressable entities, official profiles linked but
  never declared as sameAs, no self-description, no address or contact point, and a
  store locator whose physical locations exist nowhere as LocalBusiness entities. Use
  as the fourth stage of an AI-visibility audit, or when assistants confuse a brand
  with a similarly named company, attribute the wrong products to it, invent store
  locations, or cannot answer variant questions.
license: Apache-2.0
compatibility: Requires Python 3.9+. Consumes an evidence bundle; performs no network I/O.
allowed-tools: Bash(python3:*) Read
metadata:
  role: specialist
  pillar: entity
  dimension: discoverability
  marketplace: marketplace-ai-visibility-auditor
---

# Entity audit

**Pillar:** `entity` · **Dimension:** discoverability · Stage 4.

A question about an organisation is a question about an **entity**, not about a
page. A fact extracted from a page has to be attached to something: this company,
this brand, this product, this variant. Where the site does not state that
identity — one name, one set of relationships to its products and categories —
the attachment has to be inferred from the page rather than read from it, and
nothing in the markup distinguishes this organisation from a similarly named
one. This audit measures what the site publishes about its own identity; it does
not observe any system resolving it.

Mistaken identity is the failure mode people notice: an answer that is internally
plausible but actually about a different organisation with the same name. It
happens when nothing in the data distinguishes one from the other.

## When to use

After `machine-readability-audit`, or standalone when assistants mix a brand up
with another, attribute the wrong products, or cannot answer a question about one
specific variant.

## Input / output

Input: the shared evidence bundle. Output: `list[Finding]` in the `entity`
pillar.

```bash
python3 skills/entity-audit/scripts/analyze.py --bundle bundle.json
```

Performs no network I/O.

## What it checks

| Rule | Severity | What it means |
|---|---|---|
| `EN-NAME-INCONSISTENT` | high | materially different *trading* names across the site's own metadata; legal entity names and copyright holders are recorded separately and never counted as conflicts |
| `EN-PRODUCT-BRAND-MISSING` | high/medium | `Product` nodes with no `brand`: the catalogue is a set of orphan pages |
| `EN-CATEGORY-UNDECLARED` | medium | no `category` and no `BreadcrumbList`, so no machine-readable category relationship is exposed |
| `EN-LOCATIONS-UNSTRUCTURED` | high | a store locator or locations section with no `LocalBusiness`, `Store`, `Place` or addressed `Organization` anywhere in the crawl — the shape that gets a branch invented |
| `EN-ORG-INCOMPLETE` | medium/low | `Organization` declared but missing properties a site *of this shape* is expected to carry. Which fields are required-when-applicable, recommended or optional follows the site kind and what it sells |
| `EN-PRODUCT-BRAND-DRIFT` | medium | product brand strings that do not match the declared organisation |
| `EN-NO-ENTITY-IDS` | medium | no `@id` anywhere, so per-page snippets never join into one graph |
| `EN-DUPLICATE-PRODUCT-NAMES` | medium | several URLs present themselves as the same product |
| `EN-DUPLICATE-TITLES` | medium | different pages share one `<title>` |
| `EN-VARIANTS-UNMODELLED` | medium | variant pickers in the UI, a single `Product` with a single `Offer` in the data |
| `EN-NO-SELF-DESCRIPTION` | medium | no meta description, `og:description` or `Organization.description` |
| `EN-SAMEAS-UNDECLARED` | medium | profiles linked in the footer but not asserted as `sameAs` |
| `EN-NO-CONTACT-GROUNDING` | low | no address or contact point on the organisation |

## How it avoids false positives

- **`@id` references are resolved first.** `{"@id": "/#organization"}` is looked
  up in the crawl's JSON-LD graph, so the *correct* pattern — declare the
  organisation once, reference it everywhere — is never mistaken for a brand
  named `/#organization`.
- **Names are folded, not string-compared.** Case, punctuation, accents and
  trademark symbols are normalised, and names that are prefixes or substrings of
  each other ("Acme" vs "Acme Supplies") are treated as one entity described at
  different lengths.
- **A nested `Brand` is not the site's identity.** A `Brand` node inside a
  `Product` is the manufacturer; only `Brand` on the home page counts as the
  site's own. Otherwise a genuine drift would mask itself.
- **Multi-brand retail is respected.** Brand drift is not reported when several
  distinct foreign brands appear — that is a marketplace selling other people's
  products, not naming drift.

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

- [references/checks.md](references/checks.md) — entity resolution, the canonical name checklist, variant modelling, and disambiguation signals.
