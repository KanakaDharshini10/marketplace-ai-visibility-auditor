# AI visibility & recommendation-readiness audit — 127.0.0.1:34559

*Audited 2026-09-07T14:11:47Z by marketplace-ai-visibility-auditor v1.11.2 (read-only).*

**127.0.0.1:34559 is reachable, but 12 high-severity gap(s) weaken how readily its facts can be quoted from the pages sampled.**

| Overall | Discoverability | Engagement | Findings |
|---|---|---|---|
| 10.5/100 (critical) | 8.4/100 | 0.0/100 | 35 (0C / 12H / 21M) |

## Pillar scores

| Pillar | Score | Findings |
|---|---|---|
| Crawl & render reachability | 0.0/100 | 6 |
| Machine readability & structured data | 0.0/100 | 8 |
| Freshness & corroboration | 34.3/100 | 3 |
| Entity clarity & disambiguation | 7.8/100 | 6 |
| Engagement & comparison readiness | 0.0/100 | 7 |
| Answerability of buyer questions | 32.1/100 | 5 |

## Answerability

Questions generated from this site's own content: **14** · answerable 4 · partial 3 · not answerable 7 · score 39.3

| Question | Verdict | Evidence | Cited URL |
|---|---|---|---|
| What is the price of Northvale Press? | `not_answerable` | no currency-formatted price found in the fetched HTML and no Offer.price in structured data | http://127.0.0.1:34559/products/image-price.html |
| Is Northvale Press in stock? | `not_answerable` | no Offer.availability in markup and no stock statement detected in the fetched text | http://127.0.0.1:34559/products/image-price.html |
| What are the specifications of Northvale Press? | `not_answerable` | no specification table, definition list, label/value lines or typed attributes found in the server response | http://127.0.0.1:34559/products/image-price.html |
| What is the price of Northvale Kettle? | `answerable` | Offer.price = 4499 INR | http://127.0.0.1:34559/products/northvale-kettle-blue.html |
| Is Northvale Kettle in stock? | `answerable` | Offer.availability = InStock | http://127.0.0.1:34559/products/northvale-kettle-blue.html |
| What are the specifications of Northvale Kettle? | `not_answerable` | no specification table, definition list, label/value lines or typed attributes found in the server response | http://127.0.0.1:34559/products/northvale-kettle-blue.html |
| What is the price of Northvale Kettle? | `answerable` | Offer.price = 4499 | http://127.0.0.1:34559/products/northvale-kettle.html |
| Is Northvale Kettle in stock? | `partial` | stock state stated in prose (in stock), on the phrase "in stock": "thvale Kettle Northvale Kettle ₹4,499 — in stock. The Northvale Kettle is a cushioned daily trainer with a breathable mesh upper and a durable rubber outsole. It suits neutral runners logging thirty t" | http://127.0.0.1:34559/products/northvale-kettle.html |
| What are the specifications of Northvale Kettle? | `not_answerable` | no specification table, definition list, label/value lines or typed attributes found in the server response | http://127.0.0.1:34559/products/northvale-kettle.html |
| What is the cheapest item in All products? | `answerable` | 2 sampled product(s) expose a typed price; the lowest observed is 4499 on http://127.0.0.1:34559/products/northvale-kettle-blue.html | http://127.0.0.1:34559/collections/all.html |
| What is the difference between Northvale Press and Northvale Kettle? | `not_answerable` | the two sampled products share no attribute name in typed markup or in visible content, so there is no common axis to compare on | http://127.0.0.1:34559/products/image-price.html |
| What is the return window? | `partial` | stated in prose, on the phrase "returns": "Shipping and returns Free shipping over ₹2,000. Delivery in 3–6 business days. Returns accepted within 30 days of delivery on unused items." | http://127.0.0.1:34559/pages/shipping.html |
| Where does this site ship to, and what does delivery cost? | `partial` | stated in prose, on the phrase "Shipping": "Shipping and returns Free shipping over ₹2,000. Delivery in 3–6 business days. Returns accepted within 30 days of delivery on unused items." | http://127.0.0.1:34559/pages/shipping.html |
| What payment methods are accepted? | `not_answerable` | no statement of this policy was detected in any page the crawl fetched, in markup or in text | http://127.0.0.1:34559/ |

> 1 page(s) classified as products were not asked product questions because no item-scoped evidence establishes what they are called - no declared product name, and no heading the page's title or URL corroborates: http://127.0.0.1:34559/products/northvale-grinder.html (no heading)

## Findings

### !  F-001 — Deep links are redirected to the home page

*HIGH · Engagement & comparison readiness · engagement · confidence HIGH (0.9) · site-wide observation*

**Observed.** 1 requested URL(s) ended at a front door after a redirect: a deep path ended at the site root (e.g. http://127.0.0.1:34559/products/legacy-model.html -> http://127.0.0.1:34559/).

**What it may mean.** A URL that resolves to the home page carries none of the specificity the original link promised, so anything that cited the deep link now points at a generic landing page. A crawler that requests arbitrary paths under this host also receives 200 for all of them, which can make retired URLs look live. This audit observed the redirects; it does not measure how any particular index treats them.

- http://127.0.0.1:34559/products/legacy-model.html redirected to http://127.0.0.1:34559/ (2 hop(s)) (redirect chain) — `http://127.0.0.1:34559/products/legacy-model.html`

**Fix (high priority, low effort).** Stop collapsing unknown or retired URLs onto the home page.

*Why it works:* A home-page catch-all breaks the continuity between the answer and the visit, and it means arbitrary URLs under the host return 200 rather than 404, so retired addresses stay indistinguishable from live ones.

1. Redirect a retired product to its closest live replacement, not to the home page.
1. If there is no replacement, return 404/410 with a helpful page.
1. Never use a catch-all rewrite for unmatched routes.

*Verify:* Each URL listed resolves to its own content or returns 404.

### !  F-002 — The brand is called different things in different places on its own site

*HIGH · Entity clarity & disambiguation · discoverability · confidence MEDIUM (0.8) · site-wide observation*

**Observed.** 2 materially different trading names are declared across the site's own metadata: "Northvale" (schema.org Organization/Brand name); "Kitchenware Direct" (og:site_name). (1 further name(s) are declared in a non-trading role and are not counted as conflicting: "northvale.example" (social).)

**What it may mean.** Every distinct spelling of a name is a candidate for a separate entity. Where the site itself uses several for the same organisation, nothing in its markup states that they are one, so a reader has to infer it. Names that belong to a department, a subsidiary, a product brand or a localized version of the site are classified as such and are not counted here.

- brand name "Northvale" declared in schema.org Organization/Brand name (schema.org Organization/Brand name) — `http://127.0.0.1:34559/`
- brand name "Kitchenware Direct" declared in og:site_name (og:site_name) — `http://127.0.0.1:34559/`

**Fix (high priority, low effort).** Pick one canonical brand string and use it byte-identically everywhere.

*Why it works:* One exact string in Organization.name, og:site_name, the title suffix and Product.brand is an explicit statement that every mention is the same entity; several strings leave that to be inferred.

1. Choose the exact trading name, including capitalisation and any suffix.
1. Use it in Organization.name, og:site_name, the <title> suffix, the footer copyright and Product.brand.name.
1. Put the legal entity name in legalName, not in name.
1. Roll the same string out to every off-site profile.

*Verify:* Grep the rendered home page for the brand string; every occurrence should be identical.

### !  F-003 — The same product is priced differently on the listing and on its own page

*HIGH · Freshness & corroboration · discoverability · confidence HIGH (0.9) · site-wide observation*

**Observed.** 1 product(s) carry different Offer.price values on a listing page and on the product page itself (e.g. 3999 on http://127.0.0.1:34559/collections/all.html vs 4499 on http://127.0.0.1:34559/products/northvale-kettle.html).

**What it may mean.** Two prices for one product is an internal contradiction: nothing in the markup says which is current, so a reader of either page has no basis to pick. One source removes the disagreement.

- listing price 3999 vs product-page price 4499 (compared against http://127.0.0.1:34559/products/northvale-kettle.html) — `http://127.0.0.1:34559/collections/all.html`

**Fix (high priority, medium effort).** Serve one price per product from a single source, on every surface.

*Why it works:* Two prices for one product is an internal contradiction: nothing in the markup says which is current, so a reader of either page has no basis to pick. One source removes the disagreement.

1. Render listing tiles and product pages from the same pricing service call, not from a denormalised copy.
1. Invalidate listing caches when a product price changes.
1. Add a nightly consistency job that diffs listing vs detail prices.

*Verify:* A crawl of every category page reports zero price mismatches against the linked product pages.

### !  F-004 — Canonical tags collapse content pages onto the home page

*HIGH · Crawl & render reachability · discoverability · confidence HIGH (0.95) · 1/6 sampled content page(s)*

**Observed.** 1 of 6 sampled content page(s) (product) declare the home page as their canonical URL, a statement that the home page is the preferred address for content it does not carry. 2 further sampled page(s) were not assessed: 1 a navigation/reference address of http://127.0.0.1:34559/, not a document of its own; 1 carries a noindex directive, so it is not competing for a canonical URL.

**What it may mean.** A canonical names the URL the site prefers for this content. When a page with content of its own names the home page, the markup states that this page's content is a duplicate of the front door, which it is not. How any index acts on that statement is not something this audit measures.

- canonical on http://127.0.0.1:34559/products/northvale-kettle.html -> http://127.0.0.1:34559/ (collapses a deep page onto the home page) (link rel=canonical) — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (high priority, low effort).** Make each page canonical to itself unless it is a genuine duplicate.

*Why it works:* Product detail pages whose canonical is the home page state that their content is the home page's; a self-referencing canonical states, explicitly, that each page is its own preferred address.

1. Remove hardcoded canonicals from shared templates.
1. Generate the canonical from the page's own route, not from a site-wide constant.

*Verify:* For each URL listed, the canonical equals the URL itself.

### !  F-005 — Reviews appear to be loaded by a client-side widget, so the proof is invisible to a fetch

*HIGH · Engagement & comparison readiness · engagement · confidence MEDIUM (0.75) · 1 sampled page(s)*

**Observed.** 1 product page(s) reference reviews in their text and load many external scripts, but no review text or rating value is present in the server response - the pattern of a rating assembled after load by a client-side widget, in a form a fetch that does not run scripts cannot read.

**What it may mean.** Third-party review widgets inject their content after load, so the rating exists in the rendered page and not in the server response; rendering it server-side puts the same value in the bytes a fetch receives.

- 6 external scripts, review wording present, no Review/AggregateRating node in the HTML (raw HTML response) — `http://127.0.0.1:34559/products/northvale-grinder.html`

**Fix (high priority, medium effort).** Render at least the aggregate rating and a few reviews server-side.

*Why it works:* Third-party review widgets inject their content after load, so the rating exists in the rendered page and not in the server response; rendering it server-side puts the same value in the bytes a fetch receives.

1. Ask the review vendor for their SEO/server-rendered snippet or API.
1. Fetch the aggregate at build/render time and emit it in the HTML plus AggregateRating markup.
1. Render the newest 3-5 review bodies server-side; keep pagination client-side.
1. Never mark up a rating the page does not actually display.

*Verify:* curl -s <product url> | grep -i 'ratingValue' returns a value.

### !  F-006 — Product attributes are not presented in a standardized specification structure

*HIGH · Engagement & comparison readiness · engagement · confidence MEDIUM (0.74) · 4/4 sampled physical-goods product page(s)*

**Observed.** 4 of 4 physical-goods product page(s) contain no two-column specification table, no <dl> definition list and no typed attribute set. No attribute label/value pairs were detected in their visible copy either. For 1 of the assessed page(s) the kind of item is not established on the page itself and was inferred from what the site as a whole is seen to sell.

**What it may mean.** A standardized structure is what makes attributes line up across products: the same rows, in the same order, with units. Attributes stated as running copy have to be located and parsed per page before any two products can be set side by side, and the parse is the step that goes wrong. This is about the shape of the presentation, not about whether the information exists.

- no specification table, <dl> or typed attribute block on http://127.0.0.1:34559/products/image-price.html; 0 attribute label/value pair(s) detected in visible copy (product page body) — `http://127.0.0.1:34559/products/image-price.html`
- no specification table, <dl> or typed attribute block on http://127.0.0.1:34559/products/northvale-grinder.html; 0 attribute label/value pair(s) detected in visible copy (product page body) — `http://127.0.0.1:34559/products/northvale-grinder.html`
- no specification table, <dl> or typed attribute block on http://127.0.0.1:34559/products/northvale-kettle-blue.html; 0 attribute label/value pair(s) detected in visible copy (product page body) — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`
- no specification table, <dl> or typed attribute block on http://127.0.0.1:34559/products/northvale-kettle.html; 0 attribute label/value pair(s) detected in visible copy (product page body) — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (high priority, medium effort).** Move the attributes already published into a specification structure.

*Why it works:* A two-column structure with one row per attribute makes the same attribute addressable at the same place on every product page, so values can be compared across the range without interpreting a sentence differently on each page.

1. Use a real <table> or <dl> with one row per attribute, including units - starting with the attributes these pages already publish: '<Attribute>'.
1. Keep the same attribute set, in the same order, across the category so rows line up between products.
1. State the negative values too, not only the positive ones - an explicitly absent property cannot be inferred as present.
1. Mirror the same values in additionalProperty markup so the visible table and the typed data agree.

*Verify:* curl -s <product-url> shows a <table> or <dl> whose rows are the attribute names.

### ·  F-007 — A declared sitemap is missing or does not parse

*MEDIUM · Crawl & render reachability · discoverability · confidence HIGH (0.95) · site-wide observation*

**Observed.** 1 sitemap(s) that the site itself declares did not yield a valid sitemap: http://127.0.0.1:34559/sitemap-products.xml -> HTTP 404

**What it may mean.** A declared sitemap is the site's own statement of which URLs exist; one that does not parse, or is not there, states nothing, so the URLs it was meant to list are discoverable only by following links.

- declared sitemap http://127.0.0.1:34559/sitemap-products.xml: HTTP 404 (robots.txt Sitemap directive) — `http://127.0.0.1:34559/sitemap-products.xml`

**Fix (medium priority, low effort).** Fix or remove the broken sitemap references.

*Why it works:* A declared sitemap is the site's own statement of which URLs exist; one that does not parse, or is not there, states nothing, so the URLs it was meant to list are discoverable only by following links.

1. Remove Sitemap: lines pointing at URLs that 404.
1. Validate the XML (a stray & or an unescaped < will break the whole file).
1. If a sitemap index lists children, make sure every child resolves.
1. If the sitemap is served but refuses unknown user-agents, allow crawlers to read it - a sitemap only a browser can fetch helps no crawler.

*Verify:* Every URL in every Sitemap: directive returns 200 and valid XML.

### !  F-008 — Products carry no stable identifier, so listings elsewhere cannot be matched to them

*HIGH · Machine readability & structured data · discoverability · confidence MEDIUM (0.63) · 2/2 sampled physical-goods product page(s)*

**Observed.** 2 of 2 physical-goods product page(s) declare no sku, gtin, mpn or productID in their markup. For 1 of the assessed page(s) the kind of item is not established on the page itself and was inferred from what the site as a whole is seen to sell.

**What it may mean.** A shared identifier is how the same product is recognised as the same product across sources. Without one, a listing of this product elsewhere and this page have no field in common to match on, so agreement between them cannot be established even when they agree.

- no sku/gtin/mpn/productID in the Product markup on http://127.0.0.1:34559/products/northvale-kettle-blue.html — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`
- no sku/gtin/mpn/productID in the Product markup on http://127.0.0.1:34559/products/northvale-kettle.html — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (high priority, low effort).** Publish a stable sku plus a global identifier (GTIN or MPN) on every product.

*Why it works:* Corroboration works by matching entities across sources. Without a shared identifier there is no field on which your page and a retailer's listing are the same product, so the two never reinforce each other and neither becomes the trusted answer.

1. Emit sku (your internal code) on every Product.
1. Emit gtin13/gtin12/gtin8 where a barcode exists, mpn otherwise.
1. Use the same identifier in your merchant feeds and marketplace listings so they resolve to one entity.
1. Keep the identifier stable across price changes and re-designs.

*Optional external validation — outside this audit's measured behaviour:* Search a GTIN from your catalogue; your own page and your retail partners' listings should both surface. (A result obtained this way is one observation, and may vary by model, phrasing, date and configuration. It is not part of the score and is not evidence this audit collected.)

### !  F-009 — A buyer asking about a product's specifications finds no answer in the fetched evidence

*HIGH · Answerability of buyer questions · answerability · confidence MEDIUM (0.68) · 3/3 generated question(s)*

**Observed.** 3 of 3 generated question(s) of this kind could not be answered from the crawled pages. Example: "What are the specifications of Northvale Press?" - no specification table, definition list, label/value lines or typed attributes found in the server response.

**What it may mean.** The question was generated from this site's own content, so it is a question the catalogue invites. An assistant assembling an answer has the same pages this audit read; where the fact is not in them, the answer has to come from somewhere else or not at all. This measures the evidence, not any particular assistant's behaviour.

- "What are the specifications of Northvale Press?" - no specification table, definition list, label/value lines or typed attributes found in the server response (product page) — `http://127.0.0.1:34559/products/image-price.html`
- "What are the specifications of Northvale Kettle?" - no specification table, definition list, label/value lines or typed attributes found in the server response (product page) — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`
- "What are the specifications of Northvale Kettle?" - no specification table, definition list, label/value lines or typed attributes found in the server response (product page) — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (high priority, medium effort).** Publish the product's attributes as a specification block and mirror them in additionalProperty.

*Why it works:* A question is answerable when the fact is present in the response and identifiable without guessing. Publishing it once, in a typed field, makes every phrasing of the question resolvable from the same value.

1. Publish the product's attributes as a specification block and mirror them in additionalProperty.

*Verify:* Re-run this audit; the question moves out of not_answerable in the answerability matrix.

### !  F-010 — Product pages carry very little extractable text

*HIGH · Crawl & render reachability · discoverability · confidence MEDIUM (0.68) · 3/4 sampled product page(s)*

**Observed.** 3 of 4 product page(s) contain fewer than 200 words of text in the response body (median 116 words).

**What it may mean.** A page carrying a title, a price and a few bullet points states very little that a question could be matched against, so a fuller description of the same product elsewhere would state more. Whether any system prefers the fuller page is not something this audit measures.

- 101 words of body text — `http://127.0.0.1:34559/products/image-price.html`
- 116 words of body text — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`
- 162 words of body text — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (high priority, medium effort).** Give each product page enough plain-text substance to answer a question.

*Why it works:* Plain-text substance is what a question can be matched against; a page with a title, a price and three bullet points states almost nothing to match.

1. Add a 100-200 word description that states what the product is, who it is for and what makes it different - in plain sentences.
1. Publish the full specification as text (not an image or a PDF).
1. Include the questions buyers actually ask, with answers.
1. Keep the text in the server response, not in a tab loaded on click.

*Verify:* curl -s <url> | wc -w exceeds ~400 for a product page.

### ·  F-011 — Sitemap entries omit <lastmod>, so the sitemap says nothing about what changed

*MEDIUM · Freshness & corroboration · discoverability · confidence HIGH (0.95) · site-wide observation*

**Observed.** 9 of 9 sitemap URL(s) have no <lastmod> value.

**What it may mean.** lastmod is the sitemap's own statement of what changed and when. Without it the sitemap gives a reader no basis to tell a page that changed this morning from one untouched for two years.

- 9 of 9 entries without <lastmod> — `http://127.0.0.1:34559/sitemap.xml`

**Fix (medium priority, low effort).** Emit a truthful <lastmod> for every sitemap URL.

*Why it works:* lastmod is the sitemap's own statement of what changed and when. Without it the sitemap gives a reader no basis to tell a page that changed this morning from one untouched for two years.

1. Set lastmod from the content's real modification timestamp.
1. Use W3C datetime format with a timezone.
1. Update it whenever a stated fact on the page changes, not only on copy edits.

*Verify:* Change one page, regenerate the sitemap, and confirm only that URL's lastmod moved.

### ·  F-012 — Pages the site itself advertises are not there

*MEDIUM · Crawl & render reachability · discoverability · confidence HIGH (0.98) · over 9 sampled page(s)*

**Observed.** 1 of 9 fetched URL(s) answered HTTP 404. Each of these URLs is listed in the site's own sitemap or linked from one of its pages, so the site is pointing at a page that its origin says does not exist.

**What it may mean.** A URL the site advertises and then answers with 404 or 410 is a statement the site contradicts itself on; each one is a request spent on a page that did not serve.

- HTTP 404 at http://127.0.0.1:34559/products/ghost-product.html (why fetched: listed in http://127.0.0.1:34559/sitemap.xml) — `http://127.0.0.1:34559/products/ghost-product.html`

**Fix (medium priority, medium effort).** Repair or remove the missing URLs from sitemaps and internal links.

*Why it works:* A URL the site advertises and then answers with 404 or 410 is a statement the site contradicts itself on; each one is a request spent on a page that did not serve.

1. Either restore the page or 301 it to the closest live equivalent.
1. Regenerate the sitemap so it no longer lists missing URLs.
1. Add a build-time check that every sitemap URL returns 200.

*Verify:* Re-crawl: zero 404/410 among sitemap-listed and internally linked URLs.

### ·  F-013 — The Organization entity is declared but omits properties a site of this shape is expected to carry

*MEDIUM · Entity clarity & disambiguation · discoverability · confidence HIGH (0.9) · site-wide observation*

**Observed.** The site's Organization/Brand node declares name, url but omits address (the site sells physical goods), description (it describes any organisation), contactPoint (the site sells online), sameAs (official profiles are linked from the site). Also absent, but optional for any site and not counted: logo, foundingDate. Expectations follow the site's shape (ecommerce).

**What it may mean.** Each of these properties is an explicit, machine-readable statement that tells this organisation apart from others with a similar name. Which ones a site owes depends on what kind of organisation it is; this audit does not measure how any system resolves the entity.

- Organization node has no `address` property (required when applicable) (JSON-LD Organization) — `http://127.0.0.1:34559/`
- Organization node has no `description` property (recommended) (JSON-LD Organization) — `http://127.0.0.1:34559/`
- Organization node has no `contactPoint` property (recommended) (JSON-LD Organization) — `http://127.0.0.1:34559/`
- Organization node has no `sameAs` property (recommended) (JSON-LD Organization) — `http://127.0.0.1:34559/`

**Fix (medium priority, low effort).** Fill out the Organization entity with the properties that apply to it.

*Why it works:* Entity resolution works by matching attributes. A node with only a name matches every company sharing that name; a node with a description, contact details and, where it has one, an address provides explicit machine-readable evidence to match on.

1. Add description (one factual sentence, no marketing).
1. Add a PostalAddress for the organisation's location.
1. Add a ContactPoint (or telephone/email).
1. Add sameAs for every official profile the site links to.
1. Add legalName when it differs from the trading name.
1. Give the node a stable @id such as https://example.com/#organization and reference it from every page that names the organisation.

*Verify:* Structured-data test shows an Organization carrying the properties listed as expected.

### ·  F-014 — JSON-LD blocks do not declare the schema.org context

*MEDIUM · Machine readability & structured data · discoverability · confidence HIGH (0.9) · template-wide observation*

**Observed.** 1 parseable JSON-LD block(s) have a missing or non-schema.org @context, so their @type values resolve to nothing and consumers ignore them.

**What it may mean.** Without the context, `"@type": "Product"` is an undefined term rather than schema.org's Product, so the block carries no meaning to a consumer.

- block #0 has @context=missing (ld+json #0) — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`

**Fix (medium priority, low effort).** Set "@context": "https://schema.org" on every JSON-LD block.

*Why it works:* Without the context, `"@type": "Product"` is an undefined term rather than schema.org's Product, so the block carries no meaning to a consumer.

1. Use the https:// form of the context URL.
1. If you use @graph, put @context once at the top level.

*Verify:* Every ld+json block contains schema.org in its @context.

### !  F-015 — Product pages expose no typed schema.org attributes

*HIGH · Machine readability & structured data · discoverability · confidence MEDIUM (0.63) · 2/2 sampled physical-goods product page(s)*

**Observed.** 2 of 2 physical-goods product page(s) declare fewer than two typed schema.org attributes (color, size, material, additionalProperty...) and no specification table in the HTML. No attribute label/value pairs were detected in their visible content either. For 1 of the assessed page(s) the kind of item is not established on the page itself and was inferred from what the site as a whole is seen to sell.

**What it may mean.** A typed attribute is addressable: it has a name, a value and often a unit, in a fixed place, identical in shape on every product. The same fact written into a sentence has to be found and parsed first, and the parse differs per page and per language. A comparison across products can be assembled from the addressable form without interpreting each page; whether any system does so is not something this audit measures.

- 0 typed schema.org attribute(s) and no specification table on http://127.0.0.1:34559/products/northvale-kettle-blue.html; 0 attribute label/value pair(s) present in visible content (Product JSON-LD and page body) — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`
- 0 typed schema.org attribute(s) and no specification table on http://127.0.0.1:34559/products/northvale-kettle.html; 0 attribute label/value pair(s) present in visible content (Product JSON-LD and page body) — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (high priority, medium effort).** Publish the attributes this catalogue already states as typed properties.

*Why it works:* A PropertyValue with a name, a value and a unit is comparable across products without interpretation. The same fact in prose has to be located and parsed first, and that step is where it is dropped.

1. Add an additionalProperty PropertyValue entry for each attribute these pages already publish: '<Attribute>'.
1. Use the first-class properties where schema.org has one: color, size, material, weight, width, height.
1. Keep the typed value and the visible value identical - the markup must describe what the page displays.
1. State the negative facts as well as the positive ones; an attribute that is absent from the markup is not readable as 'no', only as 'unknown'.

*Verify:* The Product JSON-LD on a product page contains an additionalProperty entry for each attribute the page displays, with matching values.

### !  F-016 — Product pages carry no Product structured data

*HIGH · Machine readability & structured data · discoverability · confidence MEDIUM (0.63) · 2/4 sampled product page(s)*

**Observed.** 2 of 4 identified product page(s) contain no schema.org Product node in JSON-LD or microdata, so name, price, availability and identifiers are not machine-addressable on those pages.

**What it may mean.** A Product node (or the schema.org type for what the page sells) is the explicit, typed statement of what the page is about; without it the same facts are available only as prose to be interpreted.

- no Product node in the structured data on http://127.0.0.1:34559/products/image-price.html — `http://127.0.0.1:34559/products/image-price.html`
- no Product node in the structured data on http://127.0.0.1:34559/products/northvale-grinder.html — `http://127.0.0.1:34559/products/northvale-grinder.html`

**Fix (high priority, medium effort).** Emit a complete Product + Offer JSON-LD block on every product page.

*Why it works:* A Product node (or the schema.org type for what the page sells) is the explicit, typed statement of what the page is about; without it the same facts are available only as prose to be interpreted.

1. Generate the block from the same data the page renders, in the same request, so the two can never drift.
1. Required minimum: name, image, description, sku, brand, offers {price, priceCurrency, availability, url}.
1. Add category and additionalProperty for the specs.
1. Keep it in the server-rendered HTML, not injected by a tag manager.

*Verify:* curl -s <product url> | python -c "import sys,re,json; print('Product' in sys.stdin.read())"

### ·  F-017 — Official profiles are linked in the page but not declared as sameAs

*MEDIUM · Entity clarity & disambiguation · discoverability · confidence HIGH (0.85) · site-wide observation*

**Observed.** 2 outbound link(s) to an account on another platform were found (e.g. https://www.instagram.com/northvale.example) but the Organization node declares no sameAs, so the identity link is left for a consumer to infer from a footer icon. This audit did not verify that those accounts belong to the organisation.

**What it may mean.** A footer icon is a link; sameAs is an explicit, machine-readable assertion that the account is this organisation, which is what lets facts stated there be matched to facts stated here.

- profile link present in page markup: https://www.instagram.com/northvale.example (outbound profile/knowledge link) — `http://127.0.0.1:34559/`
- profile link present in page markup: https://www.linkedin.com/company/northvale-example (outbound profile/knowledge link) — `http://127.0.0.1:34559/`

**Fix (medium priority, low effort).** List every official profile in Organization.sameAs.

*Why it works:* A footer icon is a link; sameAs is an explicit, machine-readable assertion that the account is this organisation, which is what lets facts stated there be matched to facts stated here.

1. Add "sameAs": ["<profile 1>", "<profile 2>", ...] to the Organization node.
1. Include only accounts you actually control.
1. Make sure each profile links back to the canonical domain.

*Verify:* Structured-data test shows sameAs containing every official profile.

### ·  F-018 — Shipping and return terms are prose only, not typed data

*MEDIUM · Engagement & comparison readiness · engagement · confidence HIGH (0.9) · 3 sampled page(s)*

**Observed.** 3 product page(s) to which delivery or return terms apply (physical goods, or pages that state such terms themselves) mention shipping and/or returns in prose, but none declares MerchantReturnPolicy or OfferShippingDetails, so the actual numbers (days, cost, destinations) are not addressable. 1 further product page(s) were not assessed because the expectation does not apply to them: 1 (the page describes the item without selling it).

**What it may mean.** Prose has to be interpreted; typed fields are read. merchantReturnDays is a number that can be read and quoted directly; 'hassle-free returns' is not.

- shipping/returns mentioned in text but no MerchantReturnPolicy or OfferShippingDetails markup (JSON-LD Offer) — `http://127.0.0.1:34559/products/image-price.html`
- shipping/returns mentioned in text but no MerchantReturnPolicy or OfferShippingDetails markup (JSON-LD Offer) — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`
- shipping/returns mentioned in text but no MerchantReturnPolicy or OfferShippingDetails markup (JSON-LD Offer) — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (medium priority, low effort).** Add MerchantReturnPolicy and OfferShippingDetails to the Offer.

*Why it works:* Prose has to be interpreted; typed fields are read. merchantReturnDays is a number that can be read and quoted directly; 'hassle-free returns' is not.

1. Add hasMerchantReturnPolicy with merchantReturnDays, returnPolicyCategory, returnFees and returnMethod.
1. Add shippingDetails with shippingRate and deliveryTime (handlingTime + transitTime) per shippingDestination.
1. Keep the numbers identical to the policy page.

*Optional external validation — outside this audit's measured behaviour:* Ask an assistant what this organization's return window is and check it returns the exact number of days stated on the policy page. (A result obtained this way is one observation, and may vary by model, phrasing, date and configuration. It is not part of the score and is not evidence this audit collected.)

### ·  F-019 — Reviews are marked up but carry no publication date

*MEDIUM · Freshness & corroboration · discoverability · confidence HIGH (0.9) · 1 sampled page(s)*

**Observed.** 1 page(s) publish Review structured data with no datePublished value on any Review node.

**What it may mean.** An undated review states a judgement without stating when it was made, so nothing on the page says whether the opinions are recent. How any reader weighs that is not something this audit measures.

- Review nodes have no datePublished (JSON-LD Review) — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (medium priority, low effort).** Emit datePublished on every Review node.

*Why it works:* A datePublished on each Review is the explicit, machine-readable statement of when the opinion was given; without it nothing on the page supports 'well reviewed recently'.

1. Populate datePublished from the review's submission timestamp.
1. Show the date visibly next to each review as well.

*Verify:* Every Review node in the rendered HTML has a datePublished.

### ·  F-020 — Pages ship without a usable Open Graph summary

*MEDIUM · Machine readability & structured data · discoverability · confidence MEDIUM (0.75) · 6/6 sampled page(s)*

**Observed.** 6 of 6 sampled page(s) are missing at least one of og:title, og:description, og:type, and 6 carry none of them. Open Graph is optional metadata; this is a gap in the explicit summary a page offers, not a blocker.

**What it may mean.** Open Graph states a title, a one-line summary and a type in a fixed place with a declared meaning. Where it is absent, any summary of the page has to be assembled from its body. Which consumers make use of the Open Graph block, and when, is not something this audit measures.

- incomplete Open Graph on http://127.0.0.1:34559/ — `http://127.0.0.1:34559/`
- incomplete Open Graph on http://127.0.0.1:34559/collections/all.html — `http://127.0.0.1:34559/collections/all.html`
- incomplete Open Graph on http://127.0.0.1:34559/products/image-price.html — `http://127.0.0.1:34559/products/image-price.html`
- incomplete Open Graph on http://127.0.0.1:34559/products/northvale-grinder.html — `http://127.0.0.1:34559/products/northvale-grinder.html`
- incomplete Open Graph on http://127.0.0.1:34559/products/northvale-kettle-blue.html — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`
- ...and 1 further page(s) with the same observation

**Fix (medium priority, low effort).** Emit og:title, og:description and og:type on every page a machine might quote.

*Why it works:* Open Graph is a page's own one-line summary in a fixed, unambiguous place: explicit, machine-readable evidence of what the page is about that does not depend on parsing the body.

1. Set og:title from the page title, og:description from the same sentence as the meta description, and og:type ('website', 'article', 'product').
1. Add og:url as the canonical absolute URL so shares resolve to one address.
1. Keep the OG values identical to the visible title and summary - a contradiction between them is a freshness defect of its own.

*Verify:* curl -s <url> | grep 'og:' shows title, description and type on every sampled page.

### ·  F-021 — No page states an answer in the form of the question it answers

*MEDIUM · Engagement & comparison readiness · engagement · confidence HIGH (0.85) · over 7 sampled page(s)*

**Observed.** Across 7 sampled page(s) there is no FAQ page, no FAQPage/Question markup, and no question-shaped headings. On the evidence of what this site publishes, the questions its readers arrive with are about price, availability, specifications, delivery and returns (the site sells physical goods).

**What it may mean.** A question-shaped heading with its answer immediately below states one fact in the form the question takes, in one place, where the same fact spread through prose has to be assembled. Which questions are worth publishing follows what this site is; whether any system matches on that shape is not something this audit measures.

- no FAQ page found among the crawled pages — `http://127.0.0.1:34559`
- no FAQPage/QAPage/Question structured data on any sampled page (JSON-LD) — `http://127.0.0.1:34559`
- no question-shaped headings or <details>/<summary> Q&A blocks (page headings) — `http://127.0.0.1:34559`
- question intents derived from this site's own evidence: price, availability, specifications, delivery and returns (the site sells physical goods) (site semantics) — `http://127.0.0.1:34559`

**Fix (medium priority, medium effort).** Publish the questions your readers actually arrive with, each answered directly beneath it, on the page that owns the answer.

*Why it works:* A heading that is the question, with the answer in the next sentence, states that answer explicitly and in one place. Where no page does that, the answer has to be assembled from prose that was written for a different purpose.

1. Start from the subjects this site publishes: price, availability, specifications, delivery and returns.
1. Take the real wording from your own sources - support tickets, on-site search logs, the questions people send you. This audit derives intents from your content, not from anyone's behaviour.
1. Answer each in 2-3 sentences immediately under the question heading; no preamble.
1. Keep each question on the page that owns the answer, and general ones on a single FAQ page.
1. Add FAQPage markup, and keep the marked-up text identical to what is displayed.

*Verify:* Fetch the page with curl and confirm each question appears as a heading with its answer in the following element, and that FAQPage markup quotes the same text.

### !  F-022 — Offer markup is missing fields a buying question is answered from

*HIGH · Machine readability & structured data · discoverability · confidence LOW (0.53) · 1/2 sampled product page(s) offered for sale*

**Observed.** Offers on 1 of 2 product page(s) offered for sale omit priceCurrency, availability. Those fields are where 'how much', 'in what currency' and 'can I buy it now' are stated as typed values. Availability was expected only of the pages selling physical goods. For 1 of the assessed page(s) the kind of item is not established on the page itself and was inferred from what the site as a whole is seen to sell.

**What it may mean.** A partial Offer looks valid to a validator, so the field that is missing is the one nobody notices; each field is the typed statement of one fact a buyer asks about.

- Offer on this page has no priceCurrency (JSON-LD Offer) — `http://127.0.0.1:34559/products/northvale-kettle.html`
- Offer on this page has no availability (JSON-LD Offer) — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (high priority, low effort).** Complete every Offer: price, priceCurrency, availability and url.

*Why it works:* A partial Offer looks valid to a validator, so the field that is missing is the one nobody notices; each field is the typed statement of one fact a buyer asks about.

1. Emit availability on every offer, including out-of-stock states (https://schema.org/OutOfStock) - an absent value states nothing, not 'available'.
1. Emit priceCurrency even for a single-currency store.
1. Add priceValidUntil so a cached price has an expiry.
1. For price ranges use AggregateOffer with lowPrice/highPrice.

*Verify:* Structured-data testing tool reports no missing recommended fields on Offer.

### ·  F-023 — Nothing on the site supports comparing one model against another

*MEDIUM · Engagement & comparison readiness · engagement · confidence MEDIUM (0.75) · over 4 sampled product page(s)*

**Observed.** No comparison wording or comparison UI was found across 7 sampled page(s), and only 0 of 4 product page(s) publish a comparable specification block.

**What it may mean.** A comparison page states, on the site's own pages, how its models differ; comparable attributes in the same structure on every product page let those differences be read without interpreting each page separately. Whether any visitor or assistant was mid-comparison is not something this audit measures.

- no compare control, comparison table or 'X vs Y' content found in the crawl — `http://127.0.0.1:34559`
- 0 of 4 product pages have a comparable spec block — `http://127.0.0.1:34559`

**Fix (medium priority, medium effort).** Publish comparison content and give the catalogue comparable attributes.

*Why it works:* A comparison page states, on the site's own pages, how its models differ; comparable attributes in the same structure on every product page let those differences be read without interpreting each page separately. Whether any visitor or assistant was mid-comparison is not something this audit measures.

1. Publish '<model A> vs <model B>' pages for your own range, with a real HTML table.
1. Standardise the attribute set across the category so rows line up.
1. Add a compare control on category pages that produces a shareable URL.
1. State who each model is for - the differentiator buyers actually use.

*Optional external validation — outside this audit's measured behaviour:* Ask an assistant to compare two products from this catalogue and check it can, and cites this site. (A result obtained this way is one observation, and may vary by model, phrasing, date and configuration. It is not part of the score and is not evidence this audit collected.)

### ·  F-024 — Content pages a site would usually want indexed carry a noindex directive

*MEDIUM · Crawl & render reachability · discoverability · confidence HIGH (0.98) · 1/7 sampled page(s)*

**Observed.** 1 of 7 sampled page(s) outside carts, accounts and internal search carry a noindex directive, including 1 content page(s) of a kind a site usually publishes to be found (product). Whether the exclusion is intentional is not something this audit can tell from the directive.

**What it may mean.** A noindex directive asks indexes not to keep the page, so an index that honours it does not hold the page, while a person visiting directly reads it as normal. This audit observes the directive, not the intent behind it: the exclusion may be deliberate, and the point of the finding is that the decision should be a conscious one for pages the business wants cited.

- noindex directive `noindex, follow` on a product page (meta robots / X-Robots-Tag) — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`

**Fix (high priority, low effort).** Review whether this exclusion is intentional on each of these pages.

*Why it works:* A page a directive asks indexes not to keep cannot be retrieved from one that honours it. Where the exclusion is deliberate that is the correct outcome; where it is inherited from a template or a CDN-wide header it removes pages the business wants cited, with no visible symptom.

1. Confirm for each listed page whether the exclusion is intended.
1. Where it is not, make the robots meta value explicit per page type in the template rather than inherited.
1. Check the X-Robots-Tag response header as well - it overrides the meta tag and is easy to set globally by mistake at the CDN.
1. Keep noindex where it belongs: carts, accounts, internal search results and thin filter permutations.

*Verify:* For each page you decided should be indexable, curl -sI <url> returns no noindex X-Robots-Tag and the HTML contains no noindex meta.

### ·  F-025 — Answers exist on the page but only as prose, not as typed values

*MEDIUM · Answerability of buyer questions · answerability · confidence MEDIUM (0.73) · 3/14 generated question(s)*

**Observed.** 3 of 14 generated question(s) were answerable only from visible text, with no typed value behind them (product_availability, return_window, shipping_destinations).

**What it may mean.** A fact stated in a sentence is available to a reader and recoverable by a machine only after parsing that sentence, which differs by phrasing and by language. The same fact in a typed field is read directly. This is the gap between a page a person can use and evidence a system can quote.

- "Is Northvale Kettle in stock?" - stock state stated in prose (in stock), on the phrase "in stock": "thvale Kettle Northvale Kettle ₹4,499 — in stock. The Northvale Kettle is a cushioned daily trainer with a breathable mesh upper and a durable rubber outsole. It suits neutral runners logging thirty t" (visible main content) — `http://127.0.0.1:34559/products/northvale-kettle.html`
- "What is the return window?" - stated in prose, on the phrase "returns": "Shipping and returns Free shipping over ₹2,000. Delivery in 3–6 business days. Returns accepted within 30 days of delivery on unused items." (visible main content) — `http://127.0.0.1:34559/pages/shipping.html`
- "Where does this site ship to, and what does delivery cost?" - stated in prose, on the phrase "Shipping": "Shipping and returns Free shipping over ₹2,000. Delivery in 3–6 business days. Returns accepted within 30 days of delivery on unused items." (visible main content) — `http://127.0.0.1:34559/pages/shipping.html`

**Fix (medium priority, low effort).** Mirror the facts already published into typed structured data.

*Why it works:* The content already exists; publishing it as a typed value removes the parsing step between the page and an answer.

1. Add MerchantReturnPolicy with merchantReturnDays to the Offer, matching the number stated on the policy page.
1. Add Offer.availability (schema.org InStock / OutOfStock) to the product's Offer.
1. Add OfferShippingDetails to the Offer, naming the destinations served and the rate, so delivery can be answered without reading the policy page.

*Verify:* Re-run this audit; these questions move from partial to answerable in the answerability matrix.

### ·  F-026 — Several distinct URLs present themselves as the same product

*MEDIUM · Entity clarity & disambiguation · discoverability · confidence MEDIUM (0.8) · observed across a section of the site*

**Observed.** 1 product name(s) are used by more than one URL (e.g. "northvale kettle" appears on 2 pages). A consumer cannot tell whether these are variants, duplicates or different products.

**What it may mean.** Identically-named pages state nothing that tells them apart, so a question about one particular variant has no name to be matched to the URL that describes it. A distinct name, or a ProductGroup with named variants, makes the difference explicit.

- product name "northvale kettle" also used by 2 URL(s) (http://127.0.0.1:34559/products/northvale-kettle.html) — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`

**Fix (medium priority, medium effort).** Disambiguate variants explicitly instead of duplicating the product name.

*Why it works:* Identically-named pages state nothing that tells them apart, so a question about one particular variant has no name to be matched to the URL that describes it. A distinct name, or a ProductGroup with named variants, makes the difference explicit.

1. Model variants as a ProductGroup with hasVariant rather than as separate identically-named products.
1. If separate URLs are required, make each name unique by appending the attribute that varies (e.g. 'Northvale Press - <Attribute> <value>') and set canonical to the group page.
1. Give each variant its own sku and its own Offer.

*Verify:* No two indexable product URLs share an identical Product.name.

### ·  F-027 — Product pages expose no machine-readable category relationship

*MEDIUM · Entity clarity & disambiguation · discoverability · confidence MEDIUM (0.63) · 2/2 sampled product page(s)*

**Observed.** 2 of 2 product page(s) expose no machine-readable category relationship through `Product.category` or `BreadcrumbList` in the sampled markup.

**What it may mean.** Category membership is one of the relationships an answer about a group of products can be assembled from. Where it is not stated in the markup it has to be inferred from the URL, the navigation or the copy, which is slower and less reliable than reading a declared value. This can make category membership harder for automated systems to resolve; it does not establish that any particular system failed to.

- no `category` property and no BreadcrumbList markup on http://127.0.0.1:34559/products/northvale-kettle-blue.html — `http://127.0.0.1:34559/products/northvale-kettle-blue.html`
- no `category` property and no BreadcrumbList markup on http://127.0.0.1:34559/products/northvale-kettle.html — `http://127.0.0.1:34559/products/northvale-kettle.html`

**Fix (medium priority, low effort).** Declare a consistent category for every product.

*Why it works:* A declared category states the product's membership directly, so a system assembling an answer about that category does not have to infer the relationship from the URL or the surrounding copy.

1. Add category to Product using this site's own taxonomy path (the path shown in its breadcrumbs, e.g. 'All products').
1. Add BreadcrumbList markup mirroring the same path.
1. Use the same category strings on the category page's own markup.
1. Keep the taxonomy shallow and stable - renaming categories resets the association.

*Verify:* Every Product node has a category value that matches a real category page.

### ·  F-028 — A buyer asking about which payment methods are accepted finds no answer in the fetched evidence

*MEDIUM · Answerability of buyer questions · answerability · confidence LOW (0.58) · 1/1 generated question(s)*

**Observed.** 1 of 1 generated question(s) of this kind could not be answered from the crawled pages. Example: "What payment methods are accepted?" - no statement of this policy was detected in any page the crawl fetched, in markup or in text.

**What it may mean.** The question was generated from this site's own content, so it is a question the catalogue invites. An assistant assembling an answer has the same pages this audit read; where the fact is not in them, the answer has to come from somewhere else or not at all. This measures the evidence, not any particular assistant's behaviour.

- "What payment methods are accepted?" - no statement of this policy was detected in any page the crawl fetched, in markup or in text (all crawled pages) — `http://127.0.0.1:34559/`

**Fix (medium priority, medium effort).** State accepted payment methods in the page text and as acceptedPaymentMethod on the Offer.

*Why it works:* A question is answerable when the fact is present in the response and identifiable without guessing. Publishing it once, in a typed field, makes every phrasing of the question resolvable from the same value.

1. State accepted payment methods in the page text and as acceptedPaymentMethod on the Offer.

*Verify:* Re-run this audit; the question moves out of not_answerable in the answerability matrix.

### ·  F-029 — Price and availability are not in the opening block of the product HTML

*MEDIUM · Engagement & comparison readiness · engagement · confidence LOW (0.56) · 2/4 sampled product page(s) offered for sale*

**Observed.** On 2 of 4 product page(s) offered for sale, the first ~1,200 characters of readable content in the fetched HTML contain no price and/or no availability statement. Measured on the server-rendered HTML in document order; no headless render was performed, so this finding makes no claim about what is visible without scrolling. A stock statement was expected only of the pages selling physical goods. For 1 of the assessed page(s) the kind of item is not established on the page itself and was inferred from what the site as a whole is seen to sell.

**What it may mean.** A reader that takes the document in order meets the opening block first, and one that works from a bounded window may not reach facts placed further down, or may not associate them with this product. This is an observation about document order; how any particular fetcher windows a page, and the effect on any individual visit, are not things this audit measures.

- opening block contains no price and no an availability statement (first ~1200 characters of block text, document order) — `http://127.0.0.1:34559/products/image-price.html`
- opening block contains no price (first ~1200 characters of block text, document order) — `http://127.0.0.1:34559/products/northvale-grinder.html`

**Fix (high priority, low effort).** Order the product template so price and availability come first.

*Why it works:* A reader that takes a bounded window of the document gets the facts that appear early. Putting the name and the decisive facts at the top of the markup puts them inside any such window regardless of how the page is laid out visually.

1. Emit the name, the price, the stock position, the delivery estimate and the return window early in the product template's markup, before long-form marketing copy.
1. Server-render those facts so they are in the HTML a fetcher receives, not added afterwards by script.
1. Keep the visible layout free to differ - this is about the order of the markup, not the order on screen.

*Verify:* curl -s <product-url> | head -c 4000 contains price and availability.

### ·  F-030 — A buyer asking about whether a product is in stock finds no answer in the fetched evidence

*MEDIUM · Answerability of buyer questions · answerability · confidence LOW (0.55) · 1/3 generated question(s)*

**Observed.** 1 of 3 generated question(s) of this kind could not be answered from the crawled pages. Example: "Is Northvale Press in stock?" - no Offer.availability in markup and no stock statement detected in the fetched text.

**What it may mean.** The question was generated from this site's own content, so it is a question the catalogue invites. An assistant assembling an answer has the same pages this audit read; where the fact is not in them, the answer has to come from somewhere else or not at all. This measures the evidence, not any particular assistant's behaviour.

- "Is Northvale Press in stock?" - no Offer.availability in markup and no stock statement detected in the fetched text (product page) — `http://127.0.0.1:34559/products/image-price.html`

**Fix (medium priority, medium effort).** State stock status on the page and in Offer.availability.

*Why it works:* A question is answerable when the fact is present in the response and identifiable without guessing. Publishing it once, in a typed field, makes every phrasing of the question resolvable from the same value.

1. State stock status on the page and in Offer.availability.

*Verify:* Re-run this audit; the question moves out of not_answerable in the answerability matrix.

### ·  F-031 — A buyer asking about the price of a product finds no answer in the fetched evidence

*MEDIUM · Answerability of buyer questions · answerability · confidence LOW (0.55) · 1/3 generated question(s)*

**Observed.** 1 of 3 generated question(s) of this kind could not be answered from the crawled pages. Example: "What is the price of Northvale Press?" - no currency-formatted price found in the fetched HTML and no Offer.price in structured data.

**What it may mean.** The question was generated from this site's own content, so it is a question the catalogue invites. An assistant assembling an answer has the same pages this audit read; where the fact is not in them, the answer has to come from somewhere else or not at all. This measures the evidence, not any particular assistant's behaviour.

- "What is the price of Northvale Press?" - no currency-formatted price found in the fetched HTML and no Offer.price in structured data (product page) — `http://127.0.0.1:34559/products/image-price.html`

**Fix (medium priority, medium effort).** State the price in the server-rendered HTML and mirror it in Offer.price / priceCurrency.

*Why it works:* A question is answerable when the fact is present in the response and identifiable without guessing. Publishing it once, in a typed field, makes every phrasing of the question resolvable from the same value.

1. State the price in the server-rendered HTML and mirror it in Offer.price / priceCurrency.

*Verify:* Re-run this audit; the question moves out of not_answerable in the answerability matrix.

###    F-032 — The organisation declares no address or contact point

*LOW · Entity clarity & disambiguation · discoverability · confidence HIGH (0.85) · site-wide observation*

**Observed.** The Organization node declares no address, contactPoint, telephone or email, and no contact page was found in the crawl. Contact grounding is expected of a ecommerce site.

**What it may mean.** An address and a contact point are explicit, machine-readable attributes that tell this organisation apart from others with a similar name, and that a registry entry can be matched on.

- no address/contactPoint/telephone/email on the Organization node (JSON-LD Organization) — `http://127.0.0.1:34559/`

**Fix (low priority, low effort).** Add a postal address and a contact point to the Organization entity.

*Why it works:* An address and a contact point are explicit, machine-readable attributes that tell this organisation apart from others with a similar name, and that a registry entry can be matched on.

1. Add a PostalAddress with locality, region and country.
1. Add a ContactPoint with contactType 'customer service'.
1. For physical locations, publish LocalBusiness/Store markup per location so each is a typed entity.

*Verify:* Structured-data test shows an address on the Organization.

### ·  F-033 — Core buying facts do not exist as text anywhere in the response

*MEDIUM · Machine readability & structured data · discoverability · confidence LOW (0.51) · 1/4 sampled product page(s)*

**Observed.** 1 of 4 product page(s) contain no currency-formatted price in the visible text and no price in structured data, while carrying 3 image(s).

**What it may mean.** Three things produce this observation - the price is inside an image, it is injected after load by script, or the page does not state it - and the audit cannot tell them apart from a single fetch. What is common to all three is that the number is not in the bytes a text extractor receives, so a system reading the response has no price to quote from this page.

- no currency-formatted price in text and no Offer.price in markup; 3 images on the page, 0 without alt text (page text + JSON-LD) — `http://127.0.0.1:34559/products/image-price.html`

**Fix (critical priority, medium effort).** Put every buying-decision fact in the HTML as text, and mirror it in markup.

*Why it works:* A fact that lives only inside an image carries no text for a reader that does not run OCR, so a page that looks complete to a person can carry no readable version of that fact in text at all.

1. Render the price, the currency and the key facts a buyer asks about as selectable text.
1. Never place price, offers or specifications inside a banner image.
1. Give every informative image a descriptive alt attribute as a backstop.
1. Mirror the same values in Product/Offer JSON-LD.

*Verify:* curl -s <product url> | grep -F '<your price>' finds the price in the raw HTML.

### ·  F-034 — Page content is delivered through an empty client-rendering shell

*MEDIUM · Crawl & render reachability · discoverability · confidence LOW (0.57) · 1/6 sampled content page(s)*

**Observed.** 1 of 6 sampled page(s) contain client-rendering markers and fewer than 120 words of text in the raw HTML (e.g. http://127.0.0.1:34559/products/northvale-grinder.html: 6 words, markers: empty React mount point in the raw HTML). A fetch that does not execute JavaScript receives only this raw response.

**What it may mean.** This is a statement about how the page is *delivered*, not about how much is missing from it: the response contains an unfilled mount point and almost no text, and the content is assembled afterwards by script. A fetch that does not execute JavaScript receives the pre-hydration HTML, so any fact that only exists after hydration is not in the bytes it receives.

- 6 words of text in raw HTML; client-render markers: empty React mount point in the raw HTML (raw HTML response) — `http://127.0.0.1:34559/products/northvale-grinder.html`

**Fix (critical priority, high effort).** Server-render (or pre-render) the facts that must be quotable.

*Why it works:* This is a statement about how the page is *delivered*, not about how much is missing from it: the response contains an unfilled mount point and almost no text, and the content is assembled afterwards by script. A fetch that does not execute JavaScript receives the pre-hydration HTML, so any fact that only exists after hydration is not in the bytes it receives.

1. Move the page's name, its key facts, breadcrumbs and the JSON-LD block into the server-rendered HTML.
1. If a full SSR migration is out of scope, add a pre-render/static snapshot layer for the content routes - that is where the citable facts live.
1. Verify with `curl -s <url> | grep -i '<price>'` rather than with a browser: the browser will always look fine.
1. Keep interactive extras (recommendations, live chat) client-side; only the facts need to be in the HTML.

*Verify:* curl -s <product url> | grep -c 'application/ld+json' returns >= 1 and the price string appears in the raw HTML.

###    F-035 — The home page declares no WebSite node

*INFO · Machine readability & structured data · discoverability · confidence HIGH (0.95) · site-wide observation*

**Observed.** The home page (http://127.0.0.1:34559/) has no WebSite node in its JSON-LD (types found: Organization). WebSite is optional metadata; this is an observation, not a defect.

**What it may mean.** The home page does not expose Organization/Brand or WebSite identity through the structured-data structures checked by this rule. That reduces the amount of explicit machine-readable identity information available to automated systems, which then have to infer the operator from page copy and the domain. This audit observes the absence of the markup; it does not test, and does not claim, that any system failed to identify the brand.

- no WebSite node in the home page structured data (JSON-LD) — `http://127.0.0.1:34559/`

**Fix (low priority, low effort).** Optionally declare WebSite JSON-LD on the home page.

*Why it works:* An Organization node is a typed statement of who the site belongs to, and WebSite ties the domain to that entity. Publishing them adds explicit machine-readable identity information for entity resolution to work from, in place of inferring the operator from page copy and the domain name.

1. Add Organization with name, url, description, address, contactPoint; legalName, logo and foundingDate are optional.
1. Add WebSite with url, name and a potentialAction SearchAction pointing at your site-search URL template.
1. Use one @id (e.g. https://example.com/#organization) and reference it from every page that names the organisation, so the whole site resolves to one entity.

*Verify:* curl -s https://<host>/ | grep -c '"Organization"' >= 1.

## Proactive recommendations (no defect detected)

Each one says what it rests on. *Evidence-backed* was gated on something this crawl observed; *site-personalised* is standard practice written in this site's own nouns; *generic* is standard practice that would read the same for any site, and is not a deficiency found here.

### OPP-ANSWER-PAGES — Publish comparison and 'which one for what' pages for the range you sell

*generic best practice · medium priority · medium effort · discoverability*

*Applies because:* two or more sellable items of the same kind (physical: 3), on a ecommerce site (site shape: ecommerce).

*Why now:* The site sells a range (two or more sellable items of the same kind (physical: 3)) and comparison-shaped content is the direct way to state how its items differ.

*Why it works:* A page whose heading is the question and whose body is a comparison table states the answer to a constrained question explicitly, in one place, where a listing states only the range. That provides a page that can be quoted and linked to for that question; whether any system retrieves it is not something this audit measures.

1. List the 10-20 questions your buyers actually ask, from support tickets, on-site search logs and marketplace Q&A. This audit generates its questions from your content, not from anyone's behaviour, so your own sources are the ones that know.
1. Publish comparison and 'best <item> for <use>' pages, each at its own URL with the question as the heading and a direct answer in the first paragraph (e.g. about Northvale Press).
1. Include an HTML <table> comparing the items on the attributes the question cares about, with units, and link each row to its own page.
1. Mark the page up with FAQPage or ItemList as appropriate and keep it updated.

*Optional external validation — outside this audit's measured behaviour:* Re-ask the same questions in a browsing-enabled assistant, monthly, and record whether the page is cited. (A result obtained this way is one observation, and may vary by model, phrasing, date and configuration. It is not part of the score and is not evidence this audit collected.)

### OPP-REFERRAL-CONTINUITY — Make every deep link land on the specific page it names

*generic best practice · medium priority · medium effort · engagement*

*Applies because:* 5 deep content pages were read on a ecommerce site (site shape: ecommerce).

*Why now:* Every quotable fact on the site is a potential landing page, and a landing page that answers the question it was linked for needs nothing else.

*Why it works:* A visitor who arrives by a link was pointed at something specific. A deep link that resolves to the exact page, with the decisive fact stated early in the server-rendered HTML, provides that fact at the point of arrival instead of leaving it to be searched for. How often visitors arrive this way, and what they do next, is not something this audit measures.

1. Deep-link from every quotable fact to the exact product page, never the home page, and never collapse retired URLs onto the front door.
1. Keep what the page exists to state - the price and whether it is available - in the first screen of server-rendered markup, before long-form copy.
1. Where a documented intent parameter is read (for example ?intent=...), server-render the matching one-line context strip; use first-party storage only.
1. Give each section a breadcrumb and onward links so a near-miss landing has a path to the right page.

*Verify against your own data — not observed by this audit:* Segment analytics by referrer and compare bounce rate and time-to-first-interaction against organic search.

### OPP-MONITORING — Stand up a recurring answer-monitoring set instead of auditing once

*generic best practice · medium priority · low effort · discoverability*

*Applies because:* a standing practice for any site; this audit is a point-in-time snapshot (site shape: ecommerce).

*Why now:* This audit is a point-in-time snapshot; the gaps it detects recur silently.

*Why it works:* A fixed question set turned into a weekly measurement converts 'are we visible?' from an opinion into a series of observations that can be compared over time; this audit makes one such observation, of the site alone.

1. Freeze ~30 questions in your own nouns: 10 category questions, 10 brand-fact questions (return window, delivery time, who you are), and 10 product questions, for example 'is Northvale Press available, and what does it cost?'.
1. Run them weekly across at least three assistants with browsing enabled.
1. Record three numbers per question: organisation mentioned (y/n), correct fact (y/n), own domain cited (y/n).
1. Re-run this audit on the same cadence and track the pillar scores and the finding count alongside.

*Verify against your own data — not observed by this audit:* A dated spreadsheet or dashboard showing mention-rate, fact-accuracy and citation-rate for 127.0.0.1:34559 over time.

### OPP-PRODUCT-FEED — Expose a public, versioned product data feed at a stable URL

*evidence-backed · medium priority · medium effort · discoverability*

*Applies because:* 3 product page(s) selling physical or digital goods with a price were read (site shape: ecommerce).

*Why now:* Product pages exist, so the catalogue data already exists in a database - publishing it costs one endpoint.

*Why it works:* Page-by-page crawling samples a catalogue; a feed states it. A single crawlable feed provides every item's price, availability and identifier in one machine-readable document, so a change is visible in one fetch instead of a re-crawl of every page. Which consumers read feeds is not measured here.

1. Publish /feeds/products.json (and optionally a merchant-centre style feed) with sku, gtin, mpn, name, brand, category, price, currency, availability, canonical URL, image, and lastModified per item.
1. Serve it uncompressed under 10MB per file, paginate with a next link if larger.
1. Reference the feed from robots.txt as a comment and from /llms.txt.
1. Regenerate on every price or stock change, never on a nightly-only cadence.

*Verify:* Diff the feed against three live product pages; price, availability and title must match exactly.

### OPP-AI-DISCOVERY-SURFACE — Publish an agent-facing index (/llms.txt or /agents.md) of the pages you want quoted

*evidence-backed · medium priority · low effort · discoverability*

*Applies because:* 7 content pages were read, and every probed index location answered not-found or empty (site shape: ecommerce).

*Why now:* Neither convention was served during this audit (probed: http://127.0.0.1:34559/llms.txt, http://127.0.0.1:34559/agents.md).

*Why it works:* An agent-facing index is a plain-text, machine-readable map naming which URLs carry the canonical answer to the questions the site is asked. It provides explicit evidence of where the facts are, on one fetch; how any given agent uses it, or whether it reads it at all, is not something this audit measures.

1. Create /llms.txt with an H1 of the organisation's name and a one-line description.
1. List, as markdown links with a short gloss each: the brand fact page, the top product pages, the category hubs, shipping, returns, warranty and FAQ.
1. Keep every linked page server-rendered and under the same canonical host.
1. Link it from robots.txt with a comment and list it in your sitemap so it is discoverable without guessing the path.
1. If you prefer the /agents.md convention, publish that instead - one is enough, and both should say the same thing if you ship both.

*Verify:* curl -s https://127.0.0.1:34559/llms.txt | head -40 returns the index, and each linked URL returns 200 with the fact visible in the raw HTML.

### OPP-KNOWLEDGE-ANCHOR — Link the organisation to an independent knowledge-base entry where one exists or is warranted

*evidence-backed · low priority · high effort · discoverability*

*Applies because:* an organisation is declared and no sameAs or entity-matching link to a public knowledge base or registry was found (site shape: ecommerce).

*Why now:* No outbound link to a knowledge-base entry about the organisation, and no sameAs, was found in the crawled pages.

*Why it works:* A knowledge-base or registry entry is an independent, machine-readable description of the organisation, and a sameAs pointing at it is the explicit statement that the two are the same entity. That provides evidence a similarly named organisation cannot be confused with; whether any system uses it is not something this audit measures.

1. Check whether a registry or knowledge-base entry already exists (a company register, a research or organisation identifier, an encyclopaedia article), and declare it in Organization.sameAs.
1. Where none exists and the organisation meets the relevant notability and conflict-of-interest rules, follow each knowledge base's own process - never author an entry covertly.
1. Use one exact official name string on the site and in every entry.

*Optional external validation — outside this audit's measured behaviour:* Organization.sameAs lists at least one knowledge-base or registry entry that names this organisation. (A result obtained this way is one observation, and may vary by model, phrasing, date and configuration. It is not part of the score and is not evidence this audit collected.)

### OPP-THIRD-PARTY-SYNC — Run a correction pass over the third-party copies of your facts

*generic best practice · low priority · high effort · discoverability*

*Applies because:* an organisation is declared on a ecommerce site, with 2 off-site profile(s) linked (site shape: ecommerce).

*Why now:* Updating the site is necessary but not sufficient: copies of its facts live off-site, and this audit can only see what the site itself declares.

*Why it works:* Facts about an organisation are repeated on sites it does not control, and a correction made only on its own site leaves every older copy stating the old fact. Correcting the copies provides the same fact in every place it is stated; how any system weighs agreement between sources is not something this audit measures.

1. Inventory where your facts are repeated: retailer listings, marketplaces, comparison sites, review aggregators and directories.
1. For each, submit the correction through that source's own supported channel - a listing or profile claim, a partner or seller portal where one exists, an editorial correction request - never by scraping or editing anything you do not own.
1. Publish a dated changelog page for renames, rebrands and discontinuations so third parties have something citable to point at.
1. Re-check the highest-traffic ten sources quarterly.

*Verify against your own data — not observed by this audit:* Count of third-party sources stating the current fact, tracked quarterly.

## Coverage

*Score basis: content and transport evidence from 7 parsed content page(s) (1 further fetched page(s) - search, account or navigation/reference endpoints - carry no content claim), sampled from 9 URL(s) the site advertises (page cap 40).*

- Pages fetched: 9 (home: 1, category: 1, policy: 1, error: 1, product: 4, reference: 1)
- Content pages every ratio is computed over: 7; set aside as non-content endpoints: reference: 1
- Sitemaps parsed: 1; URLs seen in sitemaps: 9
- Requests: 19 in 1.81s (answered 0.02s, refused or error status 0.01s, throttle 1.72s)
- robots.txt present: True; URLs skipped for robots: 0
- Browser-rendered evidence: not measured in this run (run with --render to compare the server response against the browser-rendered state)
- Specialists completed: 6 of 6
- Evidence reuse: 6 specialist(s) read one shared bundle of 19 request(s) (shared-evidence reuse ratio 0.833; 95 request(s) avoided; transport cache hit ratio 0.321)
- Site shape read as: ecommerce (high confidence); product kinds: informational: 1, physical: 3; listing kinds: ecommerce_listing: 1
- Expectation 'shipping' applied to 3 of 4 product page(s); not applied to: 1 (the page describes the item without selling it)
- Expectation 'returns' applied to 3 of 4 product page(s); not applied to: 1 (the page describes the item without selling it)
- Expectation 'stock' applied to 3 of 4 product page(s); not applied to: 1 (the page describes the item without selling it)
- Expectation 'purchase_cta' applied to 3 of 4 product page(s); not applied to: 1 (the page does not offer the item for sale)
- Duplicate evidence entries removed: 1
