---
name: answerability-audit
description: Check whether a website's own evidence can answer the high-value questions
  a visitor would bring to it. Generates questions from the site's own content and from
  what the site is observed to be - price, stock, specifications, delivery and returns for
  a catalogue that sells goods; installation, compatibility and versions for documentation;
  eligibility, process and deadlines for a public body; plans and limits for subscription
  software - never from a stock list, and only where the crawl observed the subject and
  the concept applies. Resolves each question against the shared evidence bundle and
  records answerable, partial or not_answerable with a citing URL, the snippet found and
  what to publish; a prose verdict quotes the sentence containing the matched phrase,
  taken from the page's content region rather than its navigation. Use as the outcome
  check of an AI-visibility audit, after the mechanism checks, or when a site passes
  every structured-data test and still cannot be quoted.
license: Apache-2.0
compatibility: Requires Python 3.9+. Consumes an evidence bundle; performs no network I/O.
allowed-tools: Bash(python3:*) Read
metadata:
  role: specialist
  pillar: answerability
  dimension: answerability
  marketplace: marketplace-ai-visibility-auditor
---

# Answerability audit

**Pillar:** `answerability` · **Dimension:** answerability · The outcome check.

Every other specialist here audits a *mechanism*: is the crawler admitted, is
the markup typed, is the entity resolvable, is the fact current, does the
landing page continue the answer. Those are necessary conditions. None of them
asks the question that decides whether any of it mattered — **can the evidence
this site publishes actually answer something a buyer would ask?**

A site can pass every structured-data test and still fail here: perfect
`Product` markup with no `Offer.availability` answers "what is it?" and not "can
I buy it?". And the reverse happens too — a site with no JSON-LD at all may
state its return window plainly enough to be quoted. Mechanisms predict
answerability; they do not establish it.

## How questions are generated

**From the site, never from a list.** A question is only generated when its
subject was observed in the crawl:

| Question | Generated when |
|---|---|
| What is the price of *P*? | a product page whose identity is established by item-scoped evidence was fetched: the product entity its markup declares, or a heading the page's own title, `og:title` or URL slug corroborates. A heading that is one of the page's control labels, a string the site repeats on other pages, or one shaped like a promotion is not an identity; such pages are set aside and the matrix notes them |
| Is *P* in stock? | as above |
| What are the specifications of *P*? | as above |
| What is the cheapest item in *C*? | a category page with a heading **and** ≥2 products |
| What is the difference between *P* and *Q*? | ≥2 products were sampled |
| What is the return window? | the site shows commerce evidence |
| Where does it ship to, and what does delivery cost? | as above |
| What payment methods are accepted? | as above |

Each product-scoped row records `subject_identity` - how the subject's name was
established - so a reader can check that *P* is a product and not a heading
the page happened to carry.

If the crawl saw no product, no product question exists. If the site is a
documentation or brochure site — no product pages, no commerce markup, no cart
affordance — the commerce questions are not generated at all, and the matrix
records why. A question about something that was never observed can be neither
answered nor fairly reported as unanswerable.

## How each question is resolved

Three verdicts, and the middle one carries most of the signal:

- **`answerable`** — the fact is present as a typed value (`Offer.price`,
  `Offer.availability`, `MerchantReturnPolicy`, typed attributes). The row
  cites the URL and the value.
- **`partial`** — the fact is on the page, but only as prose. A reader can find
  it; a machine has to parse a sentence, and that parse differs by phrasing and
  by language. The row quotes the snippet and names the typed field missing.
- **`not_answerable`** — no evidence in markup or text on any page fetched. The
  row states what was looked for and where.

Every row carries `citing_url`, `evidence`, `evidence_source`, `missing` and
`suggested_action`. The full matrix is emitted in the report under
`answerability`; findings aggregate it.

## What it reports

| Rule | Severity | What it means |
|---|---|---|
| `AN-UNANSWERABLE-*` | high/medium | questions of one kind the fetched evidence cannot answer, one rule id per kind |
| `AN-ANSWERS-PROSE-ONLY` | high/medium | facts are published but only as prose, with no typed value behind them |

## How it decides

- **Nothing is asked that was not observed.** Question generation is gated on
  the subject existing in the bundle, and the commerce questions additionally
  on commerce evidence. The matrix `notes` say which kinds were skipped.
- **Nothing is answered from outside the crawl.** A verdict is derived only
  from pages in the shared bundle. There is no model, no API and no lookup.
- **Severity follows the sample.** A single product with no price is a page
  problem; the rules require a pattern before reporting one, and severity is
  capped by sample size through the shared `cap_severity` helper.
- **Deterministic.** The same bundle always yields the same questions, in the
  same order, with the same verdicts — so two runs are comparable and a fix
  can be verified by re-running.

## Input / output

Input: the shared evidence bundle. Output: `list[Finding]` in the
`answerability` pillar, plus the matrix.

```bash
python3 skills/answerability-audit/scripts/analyze.py --bundle bundle.json
python3 skills/answerability-audit/scripts/analyze.py --bundle bundle.json --matrix
```

Performs no network I/O.

## Why this skill shares the marketplace library

Like the other specialists, this skill imports `lib/aiva` from the
marketplace root rather than vendoring its own copy. That is the architecture,
not an oversight: the brief requires that evidence be gathered **once** and
reused, and a specialist that carried its own extraction code would either
re-derive facts from raw HTML (duplicating work the entrypoint already did) or
drift from the shared definitions the other skills reason with. Composition
here is *one crawl, one frozen bundle, many analyzers* — see
`skills/marketplace-ai-visibility-audit/references/orchestration.md`.

## Reference

- [references/checks.md](references/checks.md) — the question catalogue, how each verdict is derived, and the limits of the method.
