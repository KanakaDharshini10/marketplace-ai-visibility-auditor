# Machine readability: what each field buys you

## The minimum viable product page

The snippet below uses `<Placeholder>` values on purpose. A worked example
naming some other company's products would make this page easier to read and
the reports harder to trust — when the auditor emits a snippet it fills these
slots from the site it just crawled (see `lib/aiva/examples.py`), and falls
back to these same placeholders when it observed nothing to name.

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "@id": "https://example.com/<product-path>#product",
  "name": "<Product Name>",
  "description": "<one factual sentence, with the numbers that matter>",
  "image": "https://example.com/<image-path>",
  "sku": "<SKU>", "mpn": "<MPN>", "gtin13": "<13-digit GTIN>",
  "brand": { "@id": "https://example.com/#organization" },
  "category": "<Category>",
  "additionalProperty": [
    { "@type": "PropertyValue", "name": "<Attribute>", "value": "<value>",
      "unitText": "<unit, if the value has one>" },
    { "@type": "PropertyValue", "name": "<Attribute the product does NOT have>",
      "value": "No" }
  ],
  "aggregateRating": { "@type": "AggregateRating", "ratingValue": "4.5", "reviewCount": "128" },
  "offers": {
    "@type": "Offer",
    "price": "<price>", "priceCurrency": "<CUR>",
    "availability": "https://schema.org/InStock",
    "priceValidUntil": "2027-12-31",
    "url": "https://example.com/<product-path>",
    "hasMerchantReturnPolicy": { "@type": "MerchantReturnPolicy", "merchantReturnDays": 30 },
    "shippingDetails": { "@type": "OfferShippingDetails", "shippingRate":
      { "@type": "MonetaryAmount", "value": "0", "currency": "INR" } }
  }
}
</script>
```

Field by field, the question each one lets an assistant answer:

| Field | Question it answers |
|---|---|
| `name`, `description` | what is this? |
| `sku`, `gtin`, `mpn` | is the listing I found elsewhere the *same* product? |
| `brand` (by `@id`) | who makes it, and is that this site's company? |
| `category` | is it eligible for a question about that category? |
| `color`, `material`, `additionalProperty` | how does it compare on the attributes buyers weigh? |
| `aggregateRating` | is it any good? |
| `offers.price` + `priceCurrency` | how much, in what currency? |
| `offers.availability` | can I buy it right now? |
| `priceValidUntil` | is a cached price still trustworthy? |
| `hasMerchantReturnPolicy`, `shippingDetails` | when does it arrive, can I send it back? |

Omitting a field is not neutral. Silence reads as *unknown*, and an assistant
that cannot confirm a fact will usually decline to state it — which removes the
brand from that answer entirely.

## The four ways structured data fails

1. **Absent.** Nothing to extract; the page competes on prose alone.
2. **Invalid.** One unescaped quote in a product description invalidates the
   whole block. Nothing in the UI reveals it, and view-source looks fine. Always
   serialise with a JSON library, never string-concatenate a template, and
   `JSON.parse` every `ld+json` block in CI.
3. **Context-less.** Without `"@context": "https://schema.org"`, `"@type":
   "Product"` is an undefined term and the block carries no meaning.
4. **Contradicting the page.** Markup that disagrees with the visible text
   produces confident wrong answers, which is worse than no markup. That failure
   is owned by `freshness-corroboration`, but it is the reason both must be
   generated from a single server-side value.

## Facts that are not text

The decisive check in this pillar is `MR-FACTS-NOT-IN-TEXT`: no
currency-formatted price in the body text *and* no `Offer.price` in markup, on a
page carrying images. In practice the price is one of:

- baked into a promotional banner image;
- injected by a pricing script after load;
- rendered from a client-side template.

In all three cases the fact is absent from the text the page itself serves. The
same applies to specs delivered as a PDF or an image, and to key claims that live
only in a video. Rule of thumb: **if `curl -s <url> | grep` cannot find it, the
page does not state it in text, and nothing reading that text can quote it.**

## JSON-LD vs microdata

Both are valid. JSON-LD is preferred because it is one block that survives a
redesign; microdata is scattered through the DOM and degrades silently every time
a designer moves a `div`. `MR-MICRODATA-ONLY` is `low` severity for exactly that
reason — it is a durability warning, not a defect.

## Entity graph hygiene

Give reusable entities a stable `@id` on the canonical domain
(`https://example.com/#organization`) and reference them by `@id` elsewhere,
rather than repeating the name. Without it, each page re-declares an anonymous
"some organisation named X" and none of the evidence about the brand accumulates
on a single node. This auditor resolves `@id` references before comparing names,
so the good pattern is never mistaken for inconsistency.

## Semantic HTML still matters

- A top-level heading naming the entity the page is about, so the page states
  its own subject in the element conventionally reserved for it. A logo wrapped
  in an `h1` makes that statement about the brand rather than the product.
  (Several `<h1>` elements, or a page led by an `<h2>` that names the subject,
  are permitted by HTML and are not reported — see `MR-HEADING-STRUCTURE`.)
- `<table>` for specifications: two columns of name/value pairs are the highest
  density, most quotable content a commerce page can carry.
- `alt` text is the only textual representation of a photo, and often the only
  place colourway and use-case words enter the text index at all.
- `lang` states the page's language explicitly, so a short, name-heavy page
  does not have to have its language guessed from its body text.

## Open Graph: the summary a page offers without being parsed

`MR-OPEN-GRAPH-INCOMPLETE` reports pages missing `og:title`, `og:description`
or `og:type`. It is scoped to page types a site would want quoted — home,
product, category, article, FAQ — so a paginated archive never drags the ratio
down, and it needs a majority of the sample before it speaks.

- Several retrieval and preview pipelines read the head first and some read
  nothing else; an absent OG block means they assemble a summary from
  navigation text, or from nothing.
- `og:image` is deliberately **not** required. It carries no fact, and
  demanding it would turn a text-first site into a defect.
- `og:site_name` is not required either, but where it exists the entity rules
  compare it against every other name the site uses — a contradiction there is
  `EN-NAME-INCONSISTENT`, not this rule.
- Keep the OG values identical to the visible title and summary. A page whose
  OG description contradicts its body is a freshness defect wearing a metadata
  costume.

## Facts published only as documents

`MR-FACTS-IN-OPAQUE-DOCS` fires when three or more fact-bearing documents —
spec sheets, price lists, catalogues, manuals, warranty terms, size guides —
are linked from the crawled pages, matched on both the URL extension
(`.pdf`, `.doc(x)`, `.xls(x)`, `.ppt(x)`) and the link text.

The threshold is three because one brochure is a brochure and a pattern of them
is where the facts live. An annual report is not matched: the hint list is
about buying and product facts, not corporate publishing.

**This rule never opens the documents.** The crawler excludes binary assets
from the frontier by design — that is correct politeness and correct budgeting
— so the evidence item is anchored to the *page that links the document* and
says `(document not fetched)`. A finding that cited the PDF as its own evidence
URL would claim an observation nobody made, and the report builder rejects
exactly that class of claim.

The fix is not "stop publishing PDFs". It is: render the same table as HTML
under a stable URL, keep the document linked from it, and mirror the values
into `additionalProperty` so the fact is typed as well as visible.
