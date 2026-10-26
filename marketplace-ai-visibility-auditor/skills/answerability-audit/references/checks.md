# Answerability: the reasoning

## Why a sixth pillar

The five mechanism pillars form a chain of *necessary conditions*:

```
crawler admitted → page readable → fact extractable → entity resolved
   → fact corroborated and current → landing page continues the answer
```

Each link is measurable and each is worth fixing. But the chain is a proxy.
The thing anyone actually wants to know is whether the site can be used to
answer a question, and a proxy can be satisfied in full while the outcome
fails.

Two concrete ways that happens:

- **Complete markup, missing field.** A `Product` node with `name`, `image`,
  `description`, `sku`, `brand` and `offers.price` passes every structured-data
  check and cannot answer "can I buy it?", because `availability` is absent.
  No mechanism rule fires on a *complete-looking* Offer.
- **No markup, plain answer.** A site with no JSON-LD at all may state "Free
  returns within 30 days" in a heading. The mechanism pillars report it as
  unreadable; a reader — or a retrieval system reading text — answers the
  question immediately.

Answerability measures the outcome directly, from the same evidence. It is the
smallest weight in the score (0.15) precisely because it is *derived* from what
the other pillars measure: weighting it heavily would count the same evidence
twice.

## The generation rule

> A question is generated only when its subject was observed.

This is the difference between simulating a buyer and inventing one. A stock
question list — "does it ship to India?", "is it waterproof?" — produces a
matrix that looks impressive and means nothing: every site fails questions
about products it does not sell, and the failures say more about the list than
the site.

So generation is gated twice:

1. **Subject existence.** Product questions require a fetched page carrying a
   product name. Category questions require a classified category page with a
   heading *and* at least two sampled products, because "the cheapest" is
   meaningless over one item. Comparison requires two products.
2. **Applicability.** Return-window, shipping and payment questions are asked
   of the site as a whole, and only when commerce evidence exists — a product
   page, a category page, commerce schema.org types, or a cart form action. A
   documentation site has no return window, and reporting that it fails to
   state one is a defect of the auditor.

When a kind is skipped, the matrix `notes` record why. Silence is explained
rather than left to look like a pass.

## The three verdicts

| Verdict | Requires | What it tells the owner |
|---|---|---|
| `answerable` | a typed value in markup | nothing to do |
| `partial` | the fact in visible text only | the content exists; publish it as a typed field |
| `not_answerable` | neither | the fact is missing from every page fetched |

`partial` is the most useful state in the matrix. It separates two problems
that look identical in a mechanism audit — "you have not written this down" and
"you have written it down where only a human can read it" — and they have
completely different costs and fixes.

## What a verdict does *not* claim

The matrix reports what the **crawled evidence** supports. It does not claim:

- that any particular assistant would fail — no assistant was queried;
- that the fact is absent from the *site* — only from the pages sampled;
- that answering the question would produce a citation.

Every row names the URL it examined and the source it read (`Offer.price in
JSON-LD`, `visible page text`, `all crawled pages`), so a reader can check the
verdict against the page in one fetch.

## Limits worth stating

- **Sampling.** Questions are generated over at most five product subjects.
  A fact present on an unsampled product is not seen. `sampling` on each
  finding states the basis, and severity is capped by sample size.
- **Prose detection is language-bounded.** The `partial` verdict for stock and
  policy facts uses the shared multilingual vocabulary
  (`lib/aiva/lexicon.py`). On a page in a language it does not cover, the
  availability question returns `partial` with an explicit note that a prose
  statement could not be confirmed either way — not `not_answerable`, which
  would penalise the site for the auditor's vocabulary.
- **No semantic matching.** Two products are compared on attribute *names*
  matching exactly. A site using "Weight" on one page and "Net weight" on
  another is reported as having no shared axis — which is, in fact, the
  finding: inconsistent attribute naming is what stops values lining up.
- **A high answerability score is not a citation guarantee.** It means the
  evidence supports the questions this site's content raises. Competition,
  demand and off-site corroboration are outside any static audit.

## What may be quoted as evidence

A `partial` verdict says the fact is on the page but not in a typed field, and
it must show the reader the sentence that carries it. Two failures are possible
here, and both were live:

**Quoting the top of the page.** The snippet helper was called with no search
term, so it returned `text[:160]` — which on any modern site is the skip-link
and the primary navigation. A privacy statement was cited as a retailer's
return window, quoted as *"Skip to main content Stories Jobs Newsroom Our
business … Privacy and Cookie statement"*. Nothing in that sentence is about
returns, and the retailer's actual return-policy page had been crawled.

`quote_concept` makes that impossible:

- It locates the concept with `lexicon.find`, which returns the match's span in
  the **original** text — the fold used for matching is length-preserving, so
  the quotation keeps its real words and diacritics.
- It searches `main_text` before the whole document, so the page's own prose
  outranks a navigation label, and the verdict names which region it read.
- It opens the quotation at the sentence the phrase sits in, rather than a
  fixed distance before it, so the quote reads as a statement.
- **It returns nothing when the concept is absent.** No quotation means no
  `partial`: the question is `not_answerable`, which is the honest verdict.

Source pages are then ranked, not merely filtered: a page whose URL or title
says it is *about* the concept (`/customer-service/return-policy/`) outranks
one that merely contains the word. Ordering by page type alone could not
separate them — a privacy statement and a return policy are both policy pages,
so the winner was decided by URL sort order.

**Resolving a question against the wrong concept.** `payment_options` was
matched against the `add_to_cart` vocabulary, so any page carrying a cart button
"answered" what payment methods are accepted. That is a category error, not a
weak match, and no amount of better quoting would have fixed it. The lexicon now
carries a `payment` concept in its own right, with anti-phrases so a privacy
page describing how payment *data* is processed does not qualify as a statement
of accepted methods.

The general rule: a question is resolved against its own concept or it is not
resolved at all. A near-miss reported confidently costs more than an honest
`not_answerable`.
