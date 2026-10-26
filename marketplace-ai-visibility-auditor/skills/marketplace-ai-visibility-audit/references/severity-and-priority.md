# Severity, confidence, scoring and priority

## Severity — how broken is this?

| Severity | Meaning | Typical example |
|---|---|---|
| `critical` | The audited evidence does not let the content be reached, read or attributed at all. Everything else is moot until it is fixed. | assistant crawlers disallowed at `/`; product pages `noindex`; price exists nowhere as text |
| `high` | The content is reachable but a fact the page exists to state is missing, wrong or unquotable. | no Product markup; markup price disagrees with the page; no returns information on a PDP |
| `medium` | A real gap that costs citations or engagement without blocking them. | no breadcrumbs; no filters on category pages; stale copyright |
| `low` | Hygiene. Cheap to fix, small individually, and cumulative. | no `lang` attribute; missing meta descriptions; no viewport |
| `info` | Observation only, no action implied. |  |

Rules that scale with prevalence use `severity_from_ratio`: a defect on every
sampled page of a type is a template defect and outranks the same defect on one
page.

## Confidence — how sure are we?

`confidence` (0–1) scales a finding's effect on the score and its rank. It falls
when:

- the crawl saw few pages of the relevant type (`confidence_for` caps out at
  eight sampled pages);
- the defect is present on only some of them;
- the signal is heuristic rather than a direct observation — a client-rendered
  review widget is inferred from "reviews mentioned + many external scripts + no
  review text", so it ships at 0.75, while a `Disallow: /` for GPTBot is a
  direct reading of the file and ships at 0.99.

Rules that would need evidence the crawl does not have stay silent. There is no
"probably" severity.

## Pillar scores

Each pillar starts at 100 and loses `severity_weight × confidence × 0.6` per
finding, floored at 0.

```
critical 100 · high 60 · medium 30 · low 12 · info 0
```

The overall score is the weighted mean:

| Pillar | Weight | Why |
|---|---|---|
| crawl_render | 0.204 | if a machine cannot reach it, nothing downstream matters |
| machine_readability | 0.204 | and if it cannot parse it, nothing downstream matters |
| entity | 0.136 | the right facts attached to the wrong entity are worse than none |
| freshness_corroboration | 0.136 | wrong-but-confident answers come from here |
| engagement | 0.170 | the on-site half of the problem, weighted like a first-class concern |
| answerability | 0.150 | can the evidence answer a question anyone would ask? |

The five mechanism pillars hold the ratios they have always had
(24 : 24 : 16 : 16 : 20), scaled by 0.85 to make room for the outcome pillar.
`answerability` is deliberately the smallest weight: it is the check a reader
cares about most, but it is *derived* from the same evidence the other five
measure, so a large share would count that evidence twice.

Bands: `strong` ≥85, `workable` ≥70, `weak` ≥50, `poor` ≥30, else `critical`.

**Coverage gates the band, not the arithmetic.** A pillar with no evidence
behind it scores `null` and is excluded from the weighted mean, which is
renormalised across the pillars that were measured. The score is always
reported exactly as computed - but a *band* is a claim about the whole site,
so when less than half the model's weight was measured the band is capped at
`weak`. A crawl that read nothing therefore cannot be labelled `strong` on the
strength of a healthy robots.txt alone.

The score is a communication device. The findings and their evidence are the
product; do not tune a site to the number.

## Priority — what to do first

```
priority_score = severity_weight × confidence × scope × effort × gating_bonus
```

- **scope**: site 1.0 · template 0.9 · section 0.75 · page 0.55
- **effort**: low 1.2 · medium 1.0 · high 0.8
- **gating bonus**: crawl_render ×1.15, machine_readability ×1.08 — a page that
  is not served to a plain fetch, or whose facts are not in its markup, cannot
  be improved by any fix further down the funnel, so unblocking comes first.

Buckets: ≥70 critical · ≥40 high · ≥18 medium · else low.

The specialist's own priority is a **floor**: ranking can promote a cheap
site-wide fix, never quietly demote one its author considered urgent.

This is why a one-line `robots.txt` change outranks a rendering migration even
when both are "high": same severity, but one is site-wide and takes ten minutes.
