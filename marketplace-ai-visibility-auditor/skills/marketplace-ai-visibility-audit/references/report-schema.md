# The audit report

Machine-checkable definition: `schemas/audit-report.schema.json`. The report is
validated against it on every run, and the result is recorded in
`diagnostics.schema_validation`.

## The required floor

The brief's minimum shape, always present:

```json
{
  "site": "example.com",
  "audited_at": "2026-09-20T14:32:00Z",
  "summary": { "total_findings": 6, "critical": 1, "high": 2, "medium": 3 },
  "findings": [
    {
      "id": "F-001",
      "title": "No JSON-LD structured data on product pages",
      "severity": "high",
      "evidence": "Crawled 12 product pages; 0/12 contain schema.org markup.",
      "suggested_action": { "summary": "Add Product/Offer JSON-LD to every product page.",
                            "priority": "high" }
    }
  ]
}
```

## What the default (`full`) report adds

| Field | Why it is there |
|---|---|
| `summary.overall_score`, `readiness_band` | one number a non-expert can track over time |
| `summary.discoverability_score` / `engagement_score` | proves both halves of the problem are covered |
| `summary.by_pillar`, `by_dimension`, `headline` | where the damage is concentrated, in one line |
| `findings[].evidence_items[]` | the individual observations behind the evidence string, each with its URL and locator |
| `findings[].rule_id`, `pillar`, `dimension`, `source_skill` | which specialist found it and under which concern |
| `findings[].confidence` | 0–1; lowered when the sample was small or the signal is heuristic |
| `findings[].metrics` | the counts the evidence string quotes, machine-readable |
| `findings[].affected_urls` | up to 25 URLs, plus `affected_url_count` |
| `suggested_action.mechanism` | *what the change provides* — the explicit, machine-readable statement it adds — never a claim about how any assistant behaves |
| `suggested_action.steps`, `example`, `verification`, `effort`, `impact` | enough for a developer to act without a follow-up meeting |
| `scores.pillars` | per-pillar score, weight and finding counts |
| `prioritized_actions` | the ranked do-this-next list, top 15 |
| `proactive_recommendations` | improvements where no defect was found. Each carries an `applicability` record: the site kind, what about this site satisfied the entry's conditions, the conditions themselves, the evidence the entry requires, and the site kinds and page contexts it is for |
| `coverage` | what was crawled, what was skipped and why, plus which agent-facing discovery surfaces (`llms.txt`, `agents.md`) the site publishes |
| `coverage.site_kind`, `site_kind_confidence` | the shape the site was read as, and how confidently |
| `coverage.product_subtypes`, `listing_subtypes` | how many pages of each kind of item and each kind of listing were read |
| `coverage.expectations_not_applied` | per expectation (shipping, returns, stock, physical specifications, reviews, price, identifiers, purchase CTA): how many product pages it was applied to, out of how many, and the reason for each page it was not |
| `evidence_manifest` | every URL fetched, its type, status and why it was fetched |
| `diagnostics` | specialist runs, rejected findings, `fetches_avoided`, schema validation, the semantic summary, and the evidence accounting below |
| `diagnostics.evidence_reuse` | `shared_evidence_reuse_ratio` = `1 − R / (N × R)` for `N` specialists that completed over a bundle of `R` network requests — what the shared bundle saved by being collected once. `transport_cache_hit_ratio` is the separate fetch-layer measure (cache reuses + duplicate URLs collapsed). Both are defined in the block itself |
| `diagnostics.duplicate_evidence_entries_removed` | repeated evidence items and URLs removed deterministically at serialisation, reported rather than hidden |
| `diagnostics.semantics` | the site kind and its evidence, the question classes asked, and the expectation accounting |

Extra fields are explicitly allowed by the brief ("a floor, not a ceiling").

## Projections

`--schema` selects a projection of the same report:

- **`full`** (default) — everything above.
- **`handout`** — exactly the brief's fields and nothing else. `evidence` is the
  string; `suggested_action` is `{summary, priority}`.
- **`flat`** — the flattest variant: `evidence` becomes the list of observation
  strings and `suggested_action` becomes a single string.

All three are produced from one internal report, so they can never disagree.

## Severity vs priority

`severity` describes the defect. `suggested_action.priority` describes what to
do first, and also accounts for how much of the site is affected and how
expensive the fix is. They are deliberately different fields; see
[severity-and-priority.md](severity-and-priority.md).

## Invariants the validator enforces

Beyond the JSON Schema:

- finding ids are unique and sequential in priority order;
- `summary.total_findings` equals `len(findings)`;
- `summary.critical/high/medium` equal the actual counts;
- every finding has at least one evidence item;
- every evidence item has an observation, and a URL unless it is a measurement.

## `summary.coverage_state`

`content` | `transport_only` — the class of claim the report is entitled to
make, in one machine-readable field.

`transport_only` means no page was parsed: everything in the report comes from
the transport layer (robots.txt, status codes, host probes), and no rule that
needs page content ran. The headline says so in words and names the barrier —
bot mitigation, a robots disallow, a transport failure, or a crawl that found
no parseable HTML — in that order of precedence, because a wall explains
everything downstream of it including a robots.txt that could not be read.

Read it before the score. The readiness band is already capped at `weak`
without majority coverage (see `severity-and-priority.md`), but a score is a
number and numbers get quoted: `coverage_state` is the field that says whether
this one describes a site or a doorway.
