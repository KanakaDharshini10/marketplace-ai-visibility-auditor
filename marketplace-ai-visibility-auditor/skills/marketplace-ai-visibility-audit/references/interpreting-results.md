# Reading the report

## In order

1. **`summary.headline`** — one sentence on whether the site is blocked,
   unreadable, or merely improvable.
2. **`summary.discoverability_score` vs `engagement_score`** — which half of the
   problem you have. A site can be perfectly readable and still bounce every
   visitor an assistant sends, and the fixes are owned by different people.
3. **`prioritized_actions`** — the ranked list. Rank 1 is what to do on Monday.
4. **`scores.pillars`** — the weakest pillar tells you which team to talk to:
   crawl/render is infrastructure, machine readability is templates, entity is
   marketing plus templates, freshness is pipelines, engagement is product/UX.
5. **Individual findings** — for each, read `evidence` first. If you disagree
   with a finding, the `evidence_items` name the URL and the locator, so the
   disagreement is checkable in one `curl`.

## The mental model behind the pillars

A brand appears in an assistant's answer only if a chain of steps all succeed:

```
crawler admitted → page readable → fact extractable → entity resolved
   → fact corroborated and current → retrieved for this question
   → landing page continues the answer
   → the question actually gets an answer
```

The first five pillars are that chain, and `answerability` is the last step:
whether the evidence those five produce can in fact answer something a buyer
would ask. This is why ordering matters more than counting - a `critical` in
`crawl_render` invalidates every downstream improvement, which is why gating
pillars get a ranking bonus. Fix left to right, and read
`answerability` as the outcome the rest exists to serve.

## What a high score does and does not mean

A score of 100 means *nothing this audit can observe is wrong*. It does not mean
the brand will be cited. Two large factors are outside any static audit:

- **Off-site corroboration.** The audit can verify that the anchors a site
  declares resolve. It cannot see how the wider web describes the brand, whether
  third parties repeat an old price, or whether a knowledge base has the entity.
  That is why `OPP-THIRD-PARTY-SYNC` and `OPP-MONITORING` are recommended even
  on a perfect site.
- **Competition and demand.** Being quotable does not make you the best answer to
  a question nobody asks you about, or a better answer than a competitor with the
  same markup and ten years of citations.

Treat the score as a *readiness* measure — necessary conditions, not sufficient
ones — and the monitoring loop as the outcome measure.

## Sampling and false negatives

The audit reads a bounded, type-balanced sample: the home page, up to a dozen
product pages, a handful of category, policy, FAQ, about and contact pages,
drawn from the sitemap and the site's own internal links. Consequences worth
knowing:

- You can point the audit at any URL. The site root is always fetched and
  audited as the home page; the URL you supplied is fetched first and seeds
  discovery, but is classified for what it is. So auditing a category URL still
  gets you the site-wide identity checks, and `coverage.pages_by_type` will
  show both a `home` page and your entry page.
- A defect on a template the sample missed will not be reported. Re-run with a
  higher `--max-pages` on a large catalogue.
- `coverage.pages_by_type` tells you what was actually seen. If `product` is 0,
  every product rule was suppressed rather than guessed — check whether the
  catalogue is reachable at all (that is usually itself the finding).
- Findings scale their confidence with the sample; a rule that fired on 2 of 2
  pages is less certain than the same rule on 12 of 12, and the ranking reflects
  it.
- The handful of checks that read prose cover English, Spanish, French, German,
  Portuguese, Italian and Dutch. On a page in another language they stay silent
  rather than guessing, so an audit of, say, a Japanese storefront is complete
  on structure and light on the four prose-dependent engagement checks.

## Re-running

The audit is designed to be run repeatedly:

- keep `audit-report.json` per run and diff `summary.overall_score`,
  `summary.total_findings` and the set of `rule_id`s;
- a rule disappearing is the acceptance test for a fix — each
  `suggested_action.verification` describes the check to run first, and this
  audit is the second check;
- pair it with the answer-monitoring set (`OPP-MONITORING`): this audit measures
  the causes, the monitoring set measures the effect.

## When a finding looks wrong

1. Read its `evidence_items` and re-fetch the URL with `curl -s <url>` — not in a
   browser. The browser runs JavaScript and this auditor does not, and that
   difference is the source of most surprise: the finding is about the bytes the
   origin served, not about the page you see.
2. Check `confidence` and `metrics`. A heuristic rule at 0.75 is telling you to
   look, not asserting a fact.
3. If the expectation itself does not apply to the page — a download asked
   when it will arrive, a plan asked whether it is in stock — read
   `coverage.site_kind` and `coverage.expectations_not_applied` first. They
   say which kind each page was read as and which expectations were applied to
   it; the evidence sentence of each finding names the pages it set aside and
   why. A page read as the wrong kind is a semantics bug, not a rule bug, and
   `tests/test_semantics.py` shows how to reproduce it from the page's markup.
4. If it is still wrong, it is a rule bug: the rule id points at exactly one
   function in one specialist skill, and `tests/test_rules.py` shows how to
   reproduce it against a synthetic bundle.

## Report, downgrade or suppress

A finding needs two things to be true, and they fail independently:

* **the condition exists** — something was actually observed;
* **the condition applies** — the expectation belongs to this page.

Detecting a pattern establishes only the first. A listing with no filter
control is a real observation; whether that listing is a comparable set worth
filtering is a separate question, and answering it with the detector's own
certainty is how a marketing page ends up being told to add a price sort.

`analysis.applicability_verdict` makes the decision once, for every specialist:

| both halves | outcome |
|---|---|
| observed **and** applicable | **reported** at its own severity and confidence |
| observed, applicability not established | **downgraded** — severity capped at `low`, confidence capped at 0.4, retitled to say what could not be assessed, and stripped of every claim that rests on the missing half |
| condition not established | **suppressed** — the finding would mislead |

A downgraded finding is not a softened one. It keeps the observation, which is
real, and withdraws the interpretation, which is not: on a listing whose item
set could not be delimited, no attribute is named and no ordering dimension is
asserted. `metrics.applicability` carries the word, so a consumer can filter on
it.

## Advice about items requires the items

An attribute or an ordering dimension is a claim about a listing's members, so
it is named only where the chain exists:

```
listing → members the crawl read → the attribute or value observed on them
```

Where it does not, the advice says which of the two situations it is — the
member pages were not read, or they were read and publish nothing to order on —
rather than reaching for whichever product the crawl happened to see. A price
printed on the listing page itself is not enough: it may belong to items that
page does not represent.

## Browser-rendered evidence

Where the optional `--render` pass ran, an absence is qualified rather than
asserted. "Not in the HTML a fetch receives" and "not on the page" are two
observations, and `coverage.rendered_evidence` says which of them this run
measured. A fact seen in the rendered DOM and not in the response is reported
as absent from the *response* — never removed, because the rendering gap is
itself the finding.

## A downgraded finding's advice is conditional

A downgraded finding keeps its observation and withdraws its interpretation, and
that has to reach the **recommendation**, not only the title. A reader acts on
the recommendation, so a cautious headline above an assertive instruction is
worse than either alone.

    a DOWNGRADE finding's recommendation may describe what was observed, and
    may not introduce a dimension, an attribute, an intent or a business
    requirement that was not

So a listing whose item set could not be delimited is told:

> Because the comparable item set could not be established, no specific filter
> attribute can be recommended. If this page is intended to function as a
> catalogue of comparable items, make its members readable — then expose filters
> only for attributes shared by those members.

rather than "add filtering on the attributes this catalogue publishes". The
observation — no filter control in the server response — is unchanged.

## Two measurements, one remediation

Two rules can measure genuinely different properties of one page and still be
answered by one change. `CR-JS-RENDERED-SHELL` reads the server response alone
and reports *delivery architecture*; `CR-JS-CONTENT-GAP` needs a browser and
reports *magnitude*. Either can fire without the other, so neither is a
duplicate — but the score must not be charged twice for one piece of work.

A rule declares the relationship in its own metrics (`corroborates`), the report
links the two only when both are present and they share an affected URL, and the
corroborating finding's penalty is dropped. Both keep their severity, their
evidence and their place in the report; `metrics.scoring_role` says which one
was not charged, and `metrics.corroborated_by` points the other way.

## The site shapes a sample contained

`coverage.site_kind` is one value because an expectation is either applied or
not. `coverage.observed_contexts` lists the shapes the sampled evidence
supported, ranked, so a low-confidence primary is read beside its alternatives
rather than alone. Nothing consults it; it is there to be read.
