# Freshness & corroboration: the reasoning

## Why "we updated the site" is not enough

A brand's facts live in many places: its own pages, retailer listings,
marketplaces, directories, comparison sites, review aggregators, app stores,
press archives, old blog posts. When a fact changes, only one of those places
updates. Everything else keeps stating the old version.

Retrieval systems weigh agreement across independent sources and use recency to
break ties. So after a rebrand or a price change the web contains a vote, and the
official site is one voice against many. Two consequences:

1. **The site must be unambiguously the freshest source.** That means explicit,
   machine-readable dates — not "we know it's current".
2. **The correction has to reach the other sources.** No on-site change can do
   this. It is a distribution task, and it is why the report recommends a
   third-party correction pass and a dated changelog page even when the site
   itself is perfect.

## The freshness signal hierarchy

From strongest to weakest, and all four should agree:

| Signal | Where | Notes |
|---|---|---|
| `dateModified` in JSON-LD | page markup | the clearest statement; set it from the real content change, not the deploy |
| `<time datetime="…">` plus visible "Last updated" | page body | humans and machines read the same thing |
| `Last-Modified` header | HTTP response | must be truthful; a CDN that always returns "now" destroys the signal |
| `<lastmod>` in the sitemap | sitemap | drives re-crawl priority |

Three anti-patterns the audit detects because each one makes the field worthless:

- **Missing** — the page states no date at all, so nothing on it distinguishes
  it from an older version of the same content.
- **Uniform** — every URL stamped with the sitemap build time, so the field
  states the build, not the content, including on the pages where a real date
  would have been available.
- **Future-dated** — a date the page cannot yet have been modified on, which
  contradicts the rest of the page's own evidence.

A related trap: bumping `dateModified` on every deploy without a content change.
It makes the field state the deploy rather than the content, and it destroys
your own ability to tell what actually changed.

## Self-contradiction is worse than silence

If the machine-readable price and the visible price disagree, an assistant may
quote a price the customer will not be charged. That is worse than no markup: it
produces confident wrong answers, generates support load, and erodes trust in the
source. The same applies to availability, which is the fact most likely to be
stale and the one customers act on immediately — a stale `InStock` sends a buyer
from a recommendation straight to an out-of-stock page.

The single fix for the whole class: **render the markup and the visible value
from one server-side variable in one request**, and invalidate the page cache on
price and stock transitions. A cached JSON-LD block that outlives the price it
describes is the usual root cause.

Cross-page conflicts (listing tile vs product page) have the same shape one level
up: a denormalised copy of the price in the listing index that is not invalidated
with the product. A nightly job diffing listing prices against detail prices
catches it cheaply.

## Reviews

Recency is part of what makes social proof credible, and an undated review is
discounted. Two distinct failures:

- **Undated** — `Review` nodes with no `datePublished`. Usually a template
  omission.
- **Stale** — the newest marked-up review is old. Usually *not* because reviews
  stopped: they are being collected and rendered by a client-side widget, so only
  the old server-rendered ones are visible to a fetcher. Check that before
  concluding the review programme has died.

## Corroboration anchors

`sameAs` is not a link, it is an assertion of identity: *that account is this
company*. It is what lets facts stated on an official profile corroborate facts
stated on the site. Three states the audit distinguishes:

- **None declared** — every fact about the brand exists in one place. Fragile,
  and the reason a single stale third-party copy can outvote the truth.
- **Declared but broken** — worse than none: an identity link that cannot be
  verified weakens entity resolution rather than strengthening it. Add a
  link-check for `sameAs` values to the release pipeline.
- **Declared and resolving** — the baseline. Make sure each profile links back to
  the canonical domain and repeats the same name, description and logo verbatim.

## Running a correction pass

1. Inventory where your facts are repeated (retailers, marketplaces, directories,
   comparison sites, review aggregators, app stores, press archives).
2. Correct each through its own supported channel — a merchant portal, a listing
   claim, an editorial correction request. Never by scraping or editing anything
   you do not own.
3. Publish a dated changelog page for renames, rebrands and discontinuations, so
   third parties have something citable to point at.
4. Re-check the highest-traffic ten sources quarterly, and track "share of
   sources stating the current fact" as the metric.

## Thresholds

`stale_page_days` (365), `very_stale_page_days` (730) and `stale_review_days`
(540) are configurable in `AuditConfig`. Sensible ranges differ by sector: a
policy page that has not changed in two years may be entirely correct, while a
price page that has not changed in two months may already be wrong. Treat a
staleness finding as a prompt to review, not as proof of error.
