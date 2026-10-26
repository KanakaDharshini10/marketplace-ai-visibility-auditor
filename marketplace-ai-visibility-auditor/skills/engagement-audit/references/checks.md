# Engagement & comparison readiness: the reasoning

## The continuity model

A visitor from an assistant is not a cold visitor. They have already been told
something specific and have chosen to act on it. The visit is the *continuation*
of an information journey, and it breaks at one of four points:

1. **The link does not go where the answer was.** A deep link redirected to the
   home page (or a "shop all" page) forces the visitor to redo the search the
   assistant just did for them. This is the single most destructive pattern, and
   it also teaches crawlers that arbitrary URLs resolve.
2. **The page does not restate the answer.** The visitor was told a price, a
   size, a delivery window. If the first screen opens with a hero carousel and a
   newsletter modal, they have to hunt for the fact they already have.
3. **The page cannot support the next question.** "Is it better than the other
   one?" "Does it come in my size?" "What if it doesn't fit?" — no specs, no
   comparison, no returns line, no answer.
4. **The page is a dead end.** Assistant referrals are precise but not always
   right. A near-miss with no breadcrumb and no related links becomes a bounce
   instead of a browse.

## What belongs on the first screen of a product page

In this order, server-rendered, before any marketing copy:

- product name (matching what the assistant called it)
- price and currency
- availability, per variant where variants exist
- two or three defining specifications
- delivery expectation
- return window

`EG-LEAD-ANSWER-WEAK` checks the first ~1,200 characters of readable content for
a price and an availability statement — a deliberately low bar that a
well-ordered template clears without effort.

## Preserving intent

A referral can carry intent in the URL and the referrer. Whether a site does
anything with it is a choice, and it is one this audit cannot make for you.
Two cheap moves:

- **Deep-link every quotable fact** to the exact product or answer page, never
  the home page. This is mostly a matter of making those pages exist, be
  crawlable, and be the obvious canonical URL for the fact.
- **Read a documented intent parameter** (`?intent=price|sizes|returns`) and
  server-render a one-line context strip at the top that answers it directly.
  Keep it a progressive enhancement — the page must be complete without it — and
  persist the intent for the session using first-party storage only.

Neither requires knowing which assistant sent the visitor.

## Comparison readiness

A visitor who arrives having been shown options is mid-comparison, and a site
that publishes no comparable attributes states nothing they can decide from —
so the comparison has to be finished somewhere else, on a third-party page the
brand does not control. Three layers, cheapest first:

1. **A specification table on every product page.** Two columns, units included,
   the same attribute set across the category so rows line up. Include the
   negatives ("Waterproof: No") — explicit negatives are what stop an assistant
   inventing a feature you do not have.
2. **Filtering and sorting on category pages**, on the attributes buyers actually
   use, with each filter combination addressable at a crawlable URL so an
   assistant can deep-link straight into the filtered view.
3. **"A vs B" pages for your own range**, with the comparison in a real HTML
   table and a one-line recommendation at the top. These are among the most
   quotable pages a commerce site can publish.

## Policy facts are buying facts

"When does it arrive?" and "can I send it back?" are pre-purchase blockers, not
footer material. Put the numbers on the product page near the buy button, link
to the full policy for detail, and mirror the numbers in
`MerchantReturnPolicy` and `OfferShippingDetails` on the `Offer`. Prose has to be
interpreted; `merchantReturnDays: 30` is a typed number that can be read and
quoted without parsing a sentence.

## Reviews

Two distinct failures with different fixes:

- **Absent.** Nothing on the page answers "is it any good?", so that question
  has no stated fact here to be answered from, and whatever answers it is
  published somewhere the brand does not control — usually a marketplace listing.
- **Client-rendered.** The rating is drawn by JavaScript, so a plain fetch of
  the page contains no rating at all: social proof the brand already paid to
  collect is absent from the evidence the page itself serves. Ask the review
  vendor for their server-rendered/SEO output or fetch the aggregate at render
  time; emit `aggregateRating` plus the newest few `Review` bodies in the HTML and
  keep pagination client-side. Never mark up a rating the page does not display.

## FAQs

A page whose headings *are* the questions, with the answer in the next two
sentences, states each answer in the form the question takes, in one place. That
is the most directly quotable shape content can have; whether any particular
system matches a reader's question against it is not something this audit
measures. Which questions are worth publishing follows what the site is - the
audit derives the topic families from the site's own evidence (see
`EG-FAQ-MISSING`), and your own sources, such as support tickets and on-site
search logs, are what know the real wording. Put subject-specific questions on
the page that owns the answer and general ones on a single FAQ page; mark them
up with `FAQPage` and keep the marked-up text identical to what is displayed.

## Reading prose without assuming English

Most of this auditor reads structure, which is language-neutral. Four checks
have to read words: delivery, returns, stock state and a way to buy. Those run
a three-step ladder, strongest evidence first:

1. **Typed markup.** `OfferShippingDetails` and `MerchantReturnPolicy` state
   the terms in a form no language affects; a cart-targeting `<form action>`
   is a purchase affordance whatever the button says. If the markup is there,
   the fact is stated.
2. **A multilingual vocabulary** (`lib/aiva/lexicon.py`) covering English,
   Spanish, French, German, Portuguese, Italian and Dutch, matched on
   diacritic-folded text with word boundaries so "Envío" and "envio" both hit.
3. **Silence.** If the page declares a language the vocabulary does not cover,
   the prose-only checks do not fire. A recorded false negative is better than
   a confident false positive - especially one that fires *because* the site is
   not in English.

Two related portability fixes live in the same area:

- **Question headings** are detected by the trailing `?`, not by a list of
  English interrogatives, so "¿Cómo devuelvo un artículo?" counts as an FAQ.
- **Money is parsed for both grouping conventions.** `EUR 5.499` is five and a
  half thousand euros, not five and a half. Reading it the English way makes
  every European storefront appear to contradict its own `Offer.price`, which
  is a `high`-severity finding raised entirely by the auditor's locale
  assumption. See `aiva.extract.parse_amount`.

The limit is honest: only Latin-script languages the vocabulary actually
covers. Japanese, Chinese, Arabic, Hindi and others are reported as unreadable
prose rather than silently mis-audited, and the structured checks - which are
the majority of the audit - still run in full.

## Measuring the effect

On-site changes need on-site measurement:

- segment analytics by assistant referrer (or by your intent parameter) and
  compare bounce rate, time-to-first-interaction and scroll depth against organic
  search;
- measure time-to-find for the fact the visitor arrived for;
- track add-to-cart rate on deep-linked product pages before and after;
- pair this with the answer-monitoring set from the report's proactive
  recommendations, so you can tell an engagement problem apart from a
  discoverability one rather than guessing.
