# Entity clarity: the reasoning

## How entity resolution goes wrong

A retrieval system builds a node for "the thing this page is about" and merges
nodes it believes are the same thing. Merging is driven by matching attributes:
name, domain, location, founding date, identifiers, relationships. Two failure
directions:

- **Under-merged.** Every spelling of the name becomes its own candidate entity,
  so the corroboration each accumulates is split and none reaches the confidence
  threshold to be treated as a known brand. The site is "not recognised".
- **Over-merged.** Two different organisations sharing a name are treated as one,
  and facts leak between them. The answer is fluent, plausible and about the
  wrong company.

Both are fixed the same way: one canonical identity, described with enough
distinguishing attributes that only one real-world entity matches.

## The canonical name checklist

Pick one exact string — capitalisation, spacing and suffix included — and use it
byte-identically in all of:

- `Organization.name` (with the registered entity in `legalName` if different)
- `og:site_name`
- the `<title>` suffix
- the footer copyright line
- `Product.brand.name`, or better a `{"@id": …}` reference to the organisation
- every off-site profile, directory listing and marketplace storefront

The auditor folds case, punctuation, accents and trademark symbols before
comparing, and treats a short name and the same name with a trade word appended
("Acme" and "Acme Supplies") as one entity described at different lengths. What it flags is a *materially different* string — the kind that
appears when marketing renames the brand and the footer template is never
updated.

## Give entities stable identifiers

```json
{ "@type": "Organization", "@id": "https://example.com/#organization",
  "name": "Kestrel Athletics", "legalName": "Kestrel Athletics Private Limited",
  "foundingDate": "2016",
  "description": "Indian performance running-shoe brand.",
  "logo": "https://example.com/logo.png",
  "address": { "@type": "PostalAddress", "addressLocality": "Bengaluru",
               "addressCountry": "IN" },
  "sameAs": ["https://www.linkedin.com/company/…", "https://www.wikidata.org/wiki/…"] }
```

and everywhere else:

```json
"brand": { "@id": "https://example.com/#organization" }
```

`@id` values are identifiers, not URLs to render: keep them stable across
redesigns. Without them, each page re-declares an anonymous "some organisation
named X" and no evidence accumulates on a single node.

## Disambiguation attributes, in rough order of value

1. `sameAs` to profiles you control, each linking back to the canonical domain.
2. `legalName` plus `foundingDate` — a pair that almost never collides.
3. A `PostalAddress` — location is a strong discriminator and grounds the entity
   against local and registry data.
4. A one-sentence `description` that says what you make, for whom, where. "A
   company called X" fits many organisations; "an Indian performance running-shoe
   brand founded in 2016" fits one, and it is the sentence the site itself offers
   to anything summarising the organisation.
5. Product identifiers (`gtin`, `mpn`) that match your merchant feeds, so
   retailer listings resolve to the same products.

## Products, categories and variants

- **Brand edge.** `Product.brand` is what makes a question about the brand return
  its products, and a question about a product attribute return the brand.
  Without it the catalogue is a set of orphan pages that share a domain.
- **Category edge.** "Best `<category>` under `<price>`" is answered by resolving
  the category and then ranking its members. A product attached to no category is
  structurally ineligible. Declare `category` *and* `BreadcrumbList`, keep the
  strings identical to your category page titles, and keep the taxonomy shallow
  and stable — renaming a category resets its association.
- **Variants.** A question about one specific variant is only answerable if
  that variant is a thing with its own availability:

```json
{ "@type": "ProductGroup", "productGroupID": "<GROUP-SKU>",
  "variesBy": ["<the property that varies>"],
  "hasVariant": [
    { "@type": "Product", "sku": "<GROUP-SKU>-<variant-suffix>",
      "<varying property>": "<value>",
      "offers": { "@type": "Offer", "price": "<price>", "priceCurrency": "<CUR>",
                  "availability": "https://schema.org/InStock" } }
  ] }
```

Give each variant a stable, server-rendered URL. The common anti-pattern —
separate identically named product pages per variant — creates competing
entities for the same product; if you must have separate URLs, make the names
unique and canonicalise them to the group page.

## Duplicate titles

The `<title>` is the shortest label a page publishes about itself. When many
URLs share one title, the page's own markup states nothing that distinguishes
them, so anything holding those pages by name holds one label for all of them.
Template it from the entity: product name plus a differentiator, category name
for a category page. Never ship the site name alone.

## What this skill cannot see

Entity confusion is mostly an off-site phenomenon: how the wider web describes
the brand determines whether it merges with a namesake. This skill audits the
signals the site itself controls, which are the necessary conditions. Verify the
outcome by asking assistants disambiguating questions ("who is X?", "where is X
based?", "what does X make?") and tracking the share of answers with correct
attribution and zero facts belonging to another entity.

## Physical locations as entities

`EN-LOCATIONS-UNSTRUCTURED` fires when the site points customers at places they
can visit — a store locator link, a `/stores` or `/locations` path, "find a
dealer", "where to buy" — and nothing anywhere in the crawl models a place:
no `LocalBusiness`, no `Store` subtype, no `Place`, and no `Organization`
carrying a `PostalAddress`.

Why this one and not a general "add more markup" rule: "where can I buy this
near me?" is a high-intent question whose answer is a specific address, and an
address is exactly the kind of fact that is cheap to state and expensive to get
wrong. Where the site publishes no readable location entity, nothing in its
markup states the address, so any address offered for it came from somewhere
else. This audit measures whether the site states it; it does not measure what
any system produces when the site does not.

Deliberate exemptions, because each is a site doing nothing wrong:

- **One head office with an address is enough.** A single `Organization` with a
  `PostalAddress` is a readable location. The rule speaks to chains described
  only in prose.
- **No locator, no finding.** An online-only brand is never asked to invent
  premises it does not have. The site's own locator link is the evidence that
  locations exist.
- **Microdata counts.** A site expressing `LocalBusiness` in microdata rather
  than JSON-LD has published the entity; the format is a separate concern
  (`MR-MICRODATA-ONLY`).

The fix is per-location URLs that are server-rendered rather than assembled by
a map widget, each with `LocalBusiness` JSON-LD carrying `address`,
`telephone`, `openingHoursSpecification`, `geo` and a stable `@id`, linked back
to the brand with `parentOrganization` — plus the in-store policy terms as text
on those pages, so policy questions resolve there too.
