---
name: crawl-render-audit
description: Check whether a machine can reach a website's content at all. Reads a
  shared evidence bundle and reports robots.txt problems (including blanket or
  path-scoped blocks on assistant crawler tokens such as GPTBot, OAI-SearchBot,
  ClaudeBot, PerplexityBot and Google-Extended, and directives like Noindex: that
  silently do nothing), missing, broken or undeclared XML sitemaps, HTTP errors and
  redirect chains on URLs the site advertises, http-to-https and www/apex
  canonicalisation splits, soft 404s, noindex directives in meta tags and X-Robots-Tag
  headers, canonical tags that point away from a page's own content, pages delivered
  as an empty JavaScript shell, thin product HTML, catalogues unreachable from the
  home page, slow responses, and bot mitigation that refuses an ordinary non-browser
  agent before the origin serves a page. Use as the first stage of an AI-visibility
  audit, or when a site's content is reachable in a browser but not in a plain,
  non-JavaScript fetch.
license: Apache-2.0
compatibility: Requires Python 3.9+. Consumes an evidence bundle; performs no network I/O.
allowed-tools: Bash(python3:*) Read
metadata:
  role: specialist
  pillar: crawl_render
  dimension: discoverability
  marketplace: marketplace-ai-visibility-auditor
---

# Crawl & render audit

**Pillar:** `crawl_render` · **Dimension:** discoverability · Stage 1 of the
discovery funnel.

Three things have to succeed, in order, before a page can appear in an
assistant's answer: the crawler has to be **let in**, it has to be able to
**read** what is there, and it has to be able to **pick out the fact** being
asked for. This skill owns the first two. When it reports a `critical`, nothing
any other skill recommends can take effect until it is resolved.

## When to use

As the first specialist in the marketplace, or standalone when a site is
"perfectly fine in a browser" and absent from assistants and search.

## Input / output

Input: the shared evidence bundle (`schemas/evidence-bundle.schema.json`).
Output: `list[Finding]` in the `crawl_render` pillar.

```bash
python3 skills/crawl-render-audit/scripts/analyze.py --bundle bundle.json
```

Performs no network I/O. If a fact is not in the bundle, this skill does not
claim it.

## What it checks

| Rule | Severity | What it means |
|---|---|---|
| `CR-BOT-WALL` | critical/high | bot mitigation refused this audit before a page was served — `critical` when the home page itself was refused. Reported as an observation about the edge, never as a defect in the HTML |
| `CR-ROBOTS-UNREACHABLE` | critical | robots.txt 5xx/timeout → RFC 9309 requires compliant crawlers to assume complete disallow |
| `CR-AI-CRAWLERS-BLOCKED` | critical/high | assistant crawler tokens disallowed at `/` |
| `CR-AI-CRAWLERS-PATH-BLOCKED` | high | robots.txt disallows those tokens from content paths the site otherwise publishes to be found |
| `CR-NOINDEX-ON-IMPORTANT-PAGES` | critical/high/medium/low | `noindex` in meta or `X-Robots-Tag` on citable pages; carts, accounts, logins and internal search are excluded as conventionally non-indexed, and severity scales with how many discoverable pages are affected |
| `CR-JS-RENDERED-SHELL` | critical/high | client-render markers plus almost no text in the raw response |
| `CR-JS-CONTENT-GAP` | high | measured: a headless render yields ≥2× the content of a plain fetch |
| `CR-HOME-NO-INTERNAL-LINKS` | critical | no crawlable `<a href>` on the home page |
| `CR-COMMERCE-NOT-LINKED-FROM-HOME` | high | no product or category page reachable from the root |
| `CR-CANONICAL-CROSS-HOST` | low | a canonical names another host. May be intentional (syndication, migration, a consolidated brand domain); the other host is not fetched, so the target is not verified and the action is to review |
| `CR-CANONICAL-WRONG-TARGET` | high | on eligible content pages only (see below): canonical points to another host, or collapses a deep page onto the home page |
| `CR-NO-SITEMAP` | high/medium | none of the conventional locations this audit probes served a valid `urlset`/`sitemapindex`, and the site declares none. States what was probed and how each location answered; `high` and the "discovery falls back to internal linking" interpretation only when every probe answered and robots.txt was read without a `Sitemap:` line, `medium` when locations went unchecked or robots.txt could not be read. Never claims the site *has* no sitemap; suppressed when the site declares one (that is `CR-SITEMAP-BROKEN`'s fact) |
| `CR-HTTP-ERRORS` | high/medium | URLs from the site's own sitemap or links answer 404/410: the origin says the resource is not there |
| `CR-URLS-NOT-VERIFIED` | info | advertised URLs that did not deliver an answer to this audit (403, 429, 5xx, timeout, DNS). Recorded as not verified, never as broken |
| `CR-NO-HTTPS-UPGRADE` | high | the http origin serves content instead of redirecting. Suppressed when the probe was refused (401/403/407/408/429/451/5xx) or the origin never answered — a refusal is not evidence about canonicalisation |
| `CR-THIN-PRODUCT-HTML` | high/medium | product pages with <200 words of extractable text |
| `CR-CANONICAL-MISSING` | high/medium | ≥40% of sampled *eligible content pages* declare no canonical. Eligibility comes from page evidence, not URL shape: the classified type must be a content type (product, category, policy, faq, article, about, contact, support, program, promotional, home), the page must not carry `noindex`, and a URL that redirected onto another page's document is not assessed. Pages set aside are counted in the evidence with the reason |
| `CR-HOST-DUPLICATION` | medium | www and apex both serve, neither redirects |
| `CR-SOFT-404` | medium | unknown URLs return a success status |
| `CR-REDIRECT-CHAINS` | medium | advertised URLs resolve through 2+ hops |
| `CR-SITEMAP-BROKEN` | medium/low | a sitemap the site declares returned 404 or does not parse (`medium`); one this audit could not fetch - refused, errored, timed out - is reported as *unread*, at `low`, with the outcome named, not as broken |
| `CR-ROBOTS-SYNTAX` | medium/low | non-standard directives (`Noindex:`, `Host:`) that are silently ignored |
| `CR-SLOW-RESPONSES` | medium | median response >2.5s — answer-time fetchers time out |
| `CR-SITEMAP-UNDECLARED` | low | robots.txt was read and carries no `Sitemap:` directive - a fact about robots.txt, reported on its own whether a sitemap was found at a conventional path ("a working sitemap exists but robots.txt does not point at it") or not |
| `CR-ROBOTS-MISSING` | low | no robots.txt: crawling is allowed, but nothing is declared |

## How it avoids false positives

- The HTTPS rule stays silent when the audit target was itself an `http://` URL.
- The www/apex rule stays silent for IP literals and single-label hosts, and when
  the alternate host redirects to the primary.
- The soft-404 rule ignores 403/429/5xx responses to the probe, which mean
  "blocked" or "broken", not "soft 404".
- Rules that describe product pages stay silent when the crawl sampled none.
- Confidence scales with how many pages were sampled and how universal the
  defect is; a rule seen on 2 of 2 pages ships less confident than the same rule
  on 12 of 12.

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

- [references/checks.md](references/checks.md) — the reasoning behind each check, the AI crawler token catalogue, and how to fix the hard ones.
