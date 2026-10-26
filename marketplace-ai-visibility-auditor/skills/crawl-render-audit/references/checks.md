# Crawl & render: the reasoning behind each check

## Why assistant crawler tokens are a separate concern from SEO

Classic SEO tooling reports on Googlebot and Bingbot. Vendors publish a
separate and growing set of product tokens for their AI crawlers, and a
`Disallow: /` copy-pasted from a "block AI scrapers" blog post covers those
tokens while remaining invisible in every SEO dashboard the marketing team
looks at. What a robots.txt directive *says* is measurable; what any operator
does with the pages it covers is not, so the table below states what each
group of tokens is published for, not what blocking it will cause.

Three categories matter, and conflating them is the usual mistake:

| Category | Tokens | What their operators publish them for |
|---|---|---|
| Index / training crawlers | `GPTBot`, `CCBot`, `Google-Extended`, `Applebot-Extended`, `anthropic-ai`, `Bytespider`, `Amazonbot`, `meta-externalagent`, `cohere-ai`, `Diffbot` | collecting pages into a corpus |
| Search-index crawlers behind answers | `OAI-SearchBot`, `Bingbot`, `PerplexityBot`, `YouBot` | building the search index an answer surface draws on |
| Answer-time user fetchers | `ChatGPT-User`, `Claude-User`, `Perplexity-User` | fetching a page *at the moment a person asks about it by name* |

The third category is the one nobody means to block: a directive that covers it
also covers the fetch made on behalf of a person who named the site.

**Recommended shape** — scope by path, not by agent:

```
User-agent: *
Disallow: /cart
Disallow: /checkout
Disallow: /account
Disallow: /*?sort=

Sitemap: https://example.com/sitemap.xml
```

If training must be excluded but citations kept, block `GPTBot` and `CCBot`
specifically and leave the search and user-fetch tokens allowed.

## robots.txt directives that do nothing

- `Noindex:` — unsupported since 2019. Pages the author believes are hidden are
  being indexed. Use a `noindex` meta tag or `X-Robots-Tag` header *and keep the
  page crawlable*, or the directive can never be read.
- `Host:` — a Yandex-only hint; use canonical tags and redirects.
- `Request-rate:`, `Visit-time:` — ignored by major crawlers; use `Crawl-delay:`.
- A rule that appears before any `User-agent:` line belongs to no group and is
  discarded silently.

## Rendering: what is in the response body

This audit fetches a page the way any plain HTTP client does: one GET, no
JavaScript execution. That is the representation it measures, and the only one
it can speak for. So the question it asks is never "does the page work?" but
"what is in the response body?" - a property of the site, checkable with
`curl`, whatever any other client may or may not execute.

Two signals are used:

1. **Static (always available).** Client-render markers (`<div id="root">`,
   `__NEXT_DATA__`, `window.__NUXT__`, `data-reactroot`, `ng-version`,
   `__APOLLO_STATE__`, `data-sveltekit`) together with fewer than 120 words of
   text in the raw response.
2. **Measured (`--render`, needs Playwright).** Word count after hydration
   divided by word count in the raw response. A ratio ≥2.0 is reported with the
   exact numbers.

The fix is rarely "migrate to SSR". It is: get **the facts** into the server
response — name, price, availability, key specs, breadcrumbs and the JSON-LD
block — and leave the interactive extras client-side. Verify with
`curl -s <url> | grep`, never with a browser.

## Canonicalisation

Four distinct failures, often confused:

| Symptom | Effect |
|---|---|
| no canonical | every URL variant (tracking params, sort orders) competes as its own document |
| canonical → home page | the page's own content is discarded in favour of the home page — the fastest way to make a catalogue invisible |
| canonical → other host | signals are handed to a domain you may not control |
| www and apex both serve 200 | links, citations and entity association split across two identities |

## Discovery

A crawler reaches pages two ways: sitemap and links. Both fail quietly.

- A sitemap that lists URLs which 404, redirect, or are disallowed in robots.txt
  teaches crawlers that the site's own metadata is unreliable, and they lean
  harder on heuristics that reach fewer deep pages.
- Navigation built from `<button onclick>` or a client-side router has no `href`
  for a crawler to follow. `CR-HOME-NO-INTERNAL-LINKS` and
  `CR-COMMERCE-NOT-LINKED-FROM-HOME` catch the two common shapes.
- A soft 404 (unknown URL → 200) is worse than it looks in an AI context: it
  makes a *hallucinated* URL appear to resolve, so a wrong link gets repeated as
  if verified.

## Speed

A fetch made while someone waits for an answer works to a short timeout, and a
response slower than that timeout delivers nothing to whatever made the
request. This audit measures the site's own response times, not any consumer's
timeout: the check reports the median across the sample plus the slowest URLs,
so the target is unambiguous.

## Sampling

The bundle carries a type-balanced sample, not the whole site. Every ratio-based
rule therefore reports `affected / sampled` in its evidence string and its
`metrics`, and lowers its confidence when `sampled` is small. If
`coverage.pages_by_type` shows zero product pages, the product rules did not
fire — that absence is itself worth investigating, and is usually explained by
another finding in this pillar.

## Refusals, and why they are not defects

A `403`, `429`, `451` or `503` on the path between this auditor and the origin
is an observation about that path. It is *not* evidence about the site's
configuration, and reading it as such is how an audit produces its worst
output: a confident `high` finding about a site that behaves correctly.

Two mechanisms enforce the distinction:

- **`_probe_is_conclusive`** disqualifies the host-canonicalisation probes when
  the status is a refusal (401/403/407/408/429/451/5xx) or when the same host's
  `robots.txt` never reached the origin. Before this, an origin behind a proxy
  answering `403` produced *"the http:// origin does not redirect to https://"*
  at `high` — while `CR-ROBOTS-NOT-REACHED` reported the same event honestly as
  `info`. One event, two contradictory verdicts.
- **`CR-BOT-WALL`** reports the pattern itself. It fires when the home page is
  refused, or when refusals are at least half of all requests — two independent
  routes, so an unrecognised vendor is still caught by the status pattern
  alone. Vendor fingerprints (Cloudflare, Incapsula, DataDome, Akamai, Sucuri,
  in markup and in headers) only raise confidence.

The finding is careful about what it claims. **Observed:** an honest,
robots-respecting agent with an unknown User-Agent was refused. **Inferred:**
that a wall scoring agent reputation refuses assistant crawlers on the same
basis — a risk only the site owner's edge logs can settle, which is why the
fix's first step is to go and read them rather than to change a setting.

`--user-agent` exists for the operator of the site being audited, who may need
to pass their own allowlist. Config validation rejects any value matching a
browser or a named crawler (`Mozilla`, `Chrome`, `GPTBot`, `Googlebot`, …)
before a socket opens: spoofing would evade a control the site deliberately
configured, and would make every crawlability finding a measurement of a lie.

When a wall is detected the report's `summary.coverage_state` becomes
`transport_only` and the headline says no page could be read — so the reader is
never handed a verdict about content nobody fetched.
