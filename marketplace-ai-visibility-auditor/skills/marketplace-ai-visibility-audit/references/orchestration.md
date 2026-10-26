# Composition contract

## The shape

```
                        run_audit.py  (entrypoint skill)
                                |
                     1. collect once  ──────────────►  evidence bundle (frozen JSON)
                                |                              │
                     2. read marketplace.json                  │ read-only
                                |                              ▼
    ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼          ▼          ▼          │
 crawl-    machine-   freshness-  entity-   engagement- answer-       │
 render-   readability corrobo-    audit      audit     ability-      │
 audit      -audit     ration                            audit        │
    └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
                                |
                  3. merge → score → prioritise → recommend
                                |
                                ▼
                        one audit report
```

## The contract

Every non-entrypoint skill exposes exactly one function in the script its
manifest entry names:

```python
def analyze(bundle: dict) -> list[aiva.findings.Finding]: ...
```

Rules of the contract:

1. **Input is the frozen bundle.** Specialists receive a plain dict that
   validates against `schemas/evidence-bundle.schema.json`.
2. **No network.** A specialist may not import `urllib`, `http.client`,
   `socket`, `requests`, `aiva.httpclient` or `aiva.discover`. This is asserted
   in `tests/test_safety.py` against each module's import graph, not by grepping
   prose.
3. **No mutation.** The bundle is shared; a specialist that mutated it would
   corrupt the ones that run after it. Also asserted in the test suite.
4. **One finding per rule.** Aggregate across pages and put the per-page detail
   in `evidence_items` and `affected_urls`; do not emit the same rule once per
   URL. The report builder merges duplicates, but relying on that hides the
   aggregate numbers the evidence string should quote.
5. **Every finding cites an observation.** At least one `EvidenceItem`, each
   carrying the URL it was seen on (a `measurement` item may omit the URL).
   Evidence-less findings are rejected, not silently emitted.
6. **Own exactly one pillar.** The orchestrator stamps `source_skill`; the
   specialist stamps `pillar`. One pillar per skill keeps the score attributable.
   Six specialists, six pillars: five audit the *mechanisms* a machine reader draws on
   (reachability, readability, freshness, entity clarity, on-page continuity)
   and `answerability-audit` audits the *outcome* - whether the evidence those
   five describe can answer a question the site's own content raises.

## Why the entrypoint fetches and the specialists do not

Three properties fall out of this split, and none of them depends on anybody
remembering a rule:

- **Shared evidence is reused by construction.** A specialist has no way to
  fetch, so it cannot re-download a page another specialist already read. The
  test suite asserts `requests == unique_urls_fetched` after a full run, and
  `diagnostics.evidence_reuse.shared_evidence_reuse_ratio` states what that
  saved: `1 − R / (N × R)` for `N` specialists over a bundle of `R` requests
  — 0.833 for six. (The fetch-layer measure, cache hits and duplicate URLs
  collapsed, is reported separately as `transport_cache_hit_ratio`; an earlier
  release published it under the reuse ratio's name, where it read near zero
  and said nothing about sharing.)
- **Findings cannot be invented.** If a fact is not in the bundle, no rule can
  cite it, and a rule that cites nothing is rejected before it reaches the
  report.
- **The audit is reproducible.** Save the bundle and every specialist can be
  re-run offline, deterministically, without touching the site again — which is
  also how you debug one rule without re-crawling.

## Adding or removing a specialist

Add the folder with a spec-compliant `SKILL.md` and a `scripts/analyze.py`, then
add one entry to `marketplace.json`:

```json
{ "id": "my-new-audit", "path": "skills/my-new-audit", "role": "specialist",
  "pillar": "machine_readability", "script": "scripts/analyze.py" }
```

No orchestrator code changes: `aiva.orchestrator.load_specialists()` resolves
the list from the manifest. If the new concern is genuinely a sixth pillar, add
it to `aiva.findings.PILLARS`, `PILLAR_DIMENSION` and
`aiva.scoring.PILLAR_WEIGHTS` (weights must be re-balanced to keep summing to
1.0) and to the `pillar` enum in `schemas/audit-report.schema.json`.

## Failure isolation

`run_specialists` wraps each call. A specialist that raises does not stop the
others - and is never presented as one that found nothing. Its run record
carries `status: "failed"`, `findings: null` (a count is recorded only for a
specialist that finished), `pillar`, the error and a short traceback in
`diagnostics.skill_runs`; the pillar it would have measured scores `None` with
`band: "unmeasured"` and an `unmeasured_reason`; `summary.specialist_coverage`
is `partial` rather than `complete`; `coverage.specialists` lists what
completed, what failed and which pillars are therefore unmeasured; and the
headline and `score_basis` say so in prose. `coverage_state` is untouched -
whether any page was *read* is a separate fact from whether every specialist
*finished*, and a content crawl with one failed specialist is a content report
with one pillar missing, not a transport-only one. The progress line reads
`entity-audit: FAILED before producing findings (...)`, never `0 finding(s)`.
A partial report with an honest diagnostic beats no report.
