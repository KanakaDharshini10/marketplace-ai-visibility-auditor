# Safety, scope and how each guardrail is enforced

Every claim below is enforced in code and asserted in `tests/test_safety.py`.
Prose promises are not a control; these are.

## Read-only

| Guardrail | Enforcement | Test |
|---|---|---|
| Only GET and HEAD exist | `HttpClient.SAFE_METHODS`; any other method raises `ValueError` before a socket opens | `test_unsafe_methods_are_refused` |
| No credentials | no cookie jar, no auth handler, no `Authorization`/`Cookie` header anywhere in the client — checked against the parsed AST, not the text | `test_no_credentials_are_ever_sent` |
| Honest identity | `User-Agent` names the auditor and links its purpose; it never impersonates a browser or another crawler | `test_user_agent_is_honest` |
| The target is unchanged | the fixture tree is hashed before and after a full audit | `test_auditing_does_not_modify_the_target` |

## robots.txt

- Parsed with a purpose-built parser (RFC 9309 group selection, longest-match
  with allow-wins ties, `*` and `$`), so the audit can quote *which rule on which
  line* decided an outcome.
- Obeyed for the audited site. A path we are disallowed from is not fetched; it
  is recorded in `blocked_by_robots` with the deciding rule and reported in
  `coverage`.
- Obeyed on the URL that **actually served the bytes**, not only on the URL that
  was requested. Checking only the request left an open door: a permitted URL
  that redirects into a disallowed path would have handed us content robots.txt
  refused, and the same report would then have listed that URL as blocked while
  quoting its body. The redirect target is re-authorised and, when it lands on
  another host, checked against *that* host's robots.txt — fetched on demand,
  because "we hold no policy for that host" has to mean *go and read it*, never
  *assume yes*. Such a block is recorded with a `reached_via` field naming the
  URL that led there. Every **intermediate** redirect hop is vetted too, not
  only the final URL: a hop to a private, loopback or link-local address is
  refused mid-chain (a hop that bounced back to a public URL would otherwise
  have opened a socket to the internal host unseen), and a redirect to a
  non-web scheme (`file:`, `ftp:`) is refused before urllib's default opener
  can reach its file or FTP handler. A redirect that never resolves within the
  six-hop limit is recorded as a transport failure, never as the 3xx status of
  its last hop.
- Product tokens are matched by **prefix**, per RFC 9309 §2.2.1 — not by
  substring. `User-agent: bot` names one crawler; reading it as every crawler
  whose name contains those letters manufactured a `critical` finding about a
  site doing nothing wrong. Records repeating one user-agent are merged, so a
  second group's rules are never silently dropped, and the politest declared
  `Crawl-delay` among them wins.
- Obeyed for off-site anchors too: before checking that a declared `sameAs` URL
  resolves, that host's own robots.txt is fetched and consulted.
- `Crawl-delay` is honoured when it is stricter than our default, capped at 5s so
  a hostile value cannot exhaust the time budget.
- An unreachable robots.txt is treated as a **complete disallow**, per RFC 9309
  §2.3.1.4, and reported as `CR-ROBOTS-UNREACHABLE` (critical). The audit still
  returns a valid report explaining why it stopped. This applies only when the
  origin answered. A request that never arrived — a proxy refusal, DNS or TLS
  failure, a bot wall rejecting the auditor's user-agent — is *this audit's*
  problem, not the site's, and is reported as `CR-ROBOTS-NOT-REACHED` (info):
  nothing about the site was measured, so nothing about the site is claimed.
- `respect_robots=False` is rejected by `AuditConfig.validate()`, so the flag
  cannot be turned off even from code.

## Rate and resource limits

| Limit | Default | Cap |
|---|---|---|
| delay between requests to a host | 0.4s | must be ≥ 0.1s |
| HTML documents fetched | 40 | 200 |
| bytes per response | 3 MB | truncated, and the truncation is recorded |
| per-request timeout | 12s | |
| wall-clock budget | 240s | 600s |
| off-site anchor checks | 12 | private, loopback and link-local addresses refused |

Requests are strictly sequential — there is no concurrency anywhere in the
package, so the audit cannot become a load test.

## What is deliberately out of scope

- **Authenticated areas.** Never entered, never probed.
- **Anything that writes.** No forms submitted, no carts, no accounts, no
  comments, no "test purchases".
- **Vulnerability testing.** This is not a security scanner. It does not probe
  for misconfigurations, enumerate paths, or attempt any bypass.
- **Third-party sites.** The only off-site requests are HEAD/GET checks that the
  anchors *the audited site itself declares* resolve, robots-gated and capped.
  The auditor never crawls a competitor, never queries a search engine, and never
  scrapes an assistant. Because those anchors come from the audited site's own
  markup, they are site-controlled input: any that resolve to a private, loopback
  or link-local address — cloud instance metadata being the case that matters —
  are refused before a request is made. The one exception is the host the
  operator named: auditing your own staging box, or the bundled fixture server on
  loopback, stays possible.
- **Live assistant testing.** The report tells you how to run that monitoring
  loop yourself (`OPP-MONITORING`); the skill does not do it, because doing so
  reliably needs credentials and per-provider terms.
- **Ranking or recommending products.** This is an auditor, not a shopping
  agent. It never ranks a merchant's products or advises a consumer.

## Evidence discipline

- A finding with no `evidence_items` is rejected by the report builder and
  listed in `diagnostics.rejected_findings` with the reason.
- Every evidence item carries the URL it was observed on (a `measurement` may
  omit it) and, where it applies, a locator such as "robots.txt line 14" or
  "JSON-LD block 0".
- The `evidence_manifest` lists every URL fetched, its status and why it was
  fetched, so a reader can re-derive any claim.
- Where the crawl could not sample a page type, the rules that would need it do
  not fire. Absence of evidence is never reported as evidence of absence.

## Fixtures

The three bundled fixture sites under `tests/fixtures/` are fictional. They are
served from a local loopback server, never deployed, and exist so that the audit
can be demonstrated and regression-tested without touching anyone's website.

## User-Agent: honest by default, overridable, never spoofed

The auditor identifies itself and links to the marketplace, so a site owner
reading their logs can tell what fetched them. That is the default and it does
not change.

`--user-agent` exists because an operator auditing *their own* site may need to
pass an allowlist they control at their edge. It is not a bypass:
`AuditConfig._user_agent_errors` rejects any value containing a browser token
(`Mozilla`, `Chrome`, `Safari`, `Firefox`, `WebKit`, …) or a named crawler
(`GPTBot`, `OAI-SearchBot`, `ClaudeBot`, `PerplexityBot`, `Googlebot`,
`Google-Extended`, `Bingbot`, `Applebot`, `CCBot`, …), and validation runs
before a socket opens.

Two reasons, and the second matters more than the first. Impersonating a
browser evades a control the site deliberately configured. Impersonating a
named crawler forges another party's identity — and it would also make every
crawlability finding a measurement of a lie, since the report's whole claim is
"this is what an ordinary compliant agent sees".

## What a refusal means, and what it does not

When bot mitigation refuses this audit, the run enters `coverage_state:
transport_only`: the headline says no page could be read and names the barrier,
and no rule that needs page content fires. `CR-BOT-WALL` reports the refusal
itself, and it is careful about the boundary between the two claims it makes:

- **Observed** — an honest, robots-respecting agent with an unknown User-Agent
  was refused, with the statuses and any vendor fingerprints recorded.
- **Inferred** — that a wall scoring agent reputation refuses assistant
  crawlers on the same basis. This is a *risk*, not a measurement. Only the
  site owner's edge logs can settle it, which is why the fix's first step is to
  read them rather than to change a setting.

## Off-site scope, stated plainly

The audit fetches the site under audit and the anchors that site itself
declares. It queries no search engine, no knowledge graph and no third-party
API — not because corroboration does not matter (it is the root cause this
package takes most seriously) but because a read-only crawl of one site cannot
observe it, and inventing a dependency, a rate limit and a failure mode to
half-observe it would trade a self-contained package for a worse one.

Everything genuinely off-site is therefore emitted as a prioritized
recommendation with a mechanism and a verification step —
`OPP-THIRD-PARTY-SYNC`, `OPP-KNOWLEDGE-ANCHOR`, `OPP-BRAND-FACTS`,
`OPP-MONITORING` — rather than as a finding the report cannot evidence.
