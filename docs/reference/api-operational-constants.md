# Superhuman Docs API — operational constants and behaviour findings

**Date:** 2026-09-03
**Target:** `https://docs.superhuman.com/apis/v1` (formerly Coda API v1; specs are byte-identical)
**Spec read:** OpenAPI `v1.6.0`, `info.title: "Superhuman Docs API"`

This file records **what is true** about the API's operational behaviour: rate-limit
buckets, retry semantics, size ceilings, the export state machine, and the failure
modes that are not in the specification. Per the `evidence-location` topic (see
`_rfc/README.md`), nothing here is authoritative for a decision. Only an RFC may
say the client therefore throttles, chunks, or polls a particular way.

Two kinds of number appear below and they are not interchangeable. Some are
**operating values an RFC has decided**; this file records them and the evidence
behind them, and the decision itself lives in the RFC named by the marker. The
rest are **starting values with a justification and no owner** — a reader may
adopt one, but adopting it is a decision that belongs in an RFC, not a fact this
file establishes.

Corrections belong in place. This file is mutable.

## How to read the confidence markers

| Marker | Meaning |
|---|---|
| **[STAFF]** | Stated by a Coda/Superhuman employee, quoted verbatim below with a URL |
| **[SPEC-VERIFIED]** | Read directly out of the v1.6.0 OpenAPI document, or measured against the live API |
| **[INFERRED-FROM-CLIENTS]** | Observed in the source of a working production client; not documented anywhere |
| **[CHOSEN — no evidence, tune later]** | A judgement call. No source supports the specific number. Expected to move once the probes in `docs/validation/2026-09-03-api-operational-probes.md` are run |
| **[DECIDED]** | An operating value set by an RFC, named in the justification column. Recorded here with its evidence; changing it means amending that RFC, not editing this file |

The distinction matters most in the constants table. Several numbers there look
equally authoritative and are not: `EXPORT_LINK_TTL_S` is staff-quantified,
`EXPORT_INITIAL_SLEEP_S` is staff-motivated but arbitrary in magnitude, and
`MAX_ROWS_PER_UPSERT` has no published basis at all.

---

# 1. Operational constants

## 1.1 Rate limiting

The published limits, and a caution that outranks them:

| Class | Published limit | Notes |
|---|---|---|
| Reading data | 100 per 6 s | |
| Writing data (POST/PUT/PATCH) | 10 per 6 s | |
| **Writing doc content** (POST/PUT/PATCH) | **3 or 5 per 10 s — sources disagree** | See below |
| Listing docs | 4 per 6 s | |
| Reading analytics | 100 per 6 s | |

**Two live official sources disagree, as of 2026-09-03** [SPEC-VERIFIED]:

- The rendered developer docs at `https://docs.superhuman.com/developers/apis/v1`
  say **5 requests per 10 seconds**.
- The help centre *Overview: Doc limits*
  ([coda.io](https://help.coda.io/hc/en-us/articles/39555760015757-Overview-Doc-limits),
  [superhuman.com](https://help.superhuman.com/hc/en-us/articles/46210176318477), updated
  2026-08-28) says **3 requests per 10 seconds**.

The numbers are **injected at render time**: the raw specification served at
`https://docs.superhuman.com/apis/v1/openapi.json` contains unsubstituted template
placeholders — `{{READ_RATE_LIMIT}}`, `{{WRITE_DOC_CONTENT_RATE_LIMIT}}`, and so on.
Any numbers appearing in a locally saved `coda-openapi.yaml` are a rendering
snapshot, not a contract.

They have demonstrably moved before. Eric Koleda (Coda), 2024-03-25,
<https://connect.superhuman.com/t/x/47493/4>:

> "Last week we had to implement a tighter rate limit on doc content changes to
> deal with some abuse vectors that were compromising our infrastructure. As per
> that last screenshot, there is a **new 3/10 second rate limit on doc content
> changes (rows, etc)**. Are you able to batch your row changes into fewer
> `upsertRows` calls?"

And staff advise against encoding them at all — Eric Koleda, 2023-09-08,
<https://connect.superhuman.com/t/x/42678/3>:

> "it's possible via experimentation to determine the approximate current rate
> limits, but I would still advise you **don't rely on those numbers as they are
> subject to change**. Instead detect rate limit errors (429 response code) and
> when they occur wait for a bit and then try again."

### Client-side bucket values

These are **decided by the `upstream-api` topic** (see `_rfc/README.md`), not
chosen here. Each sits below the lowest published candidate for its class, so
the client is correct whichever figure is live, and below rather than at it
because the buckets are shared per user and possibly per IP. The justification
column records why each number is defensible; the rule that produces them is the
RFC's.

| Constant | Value | Marker | Justification |
|---|---|---|---|
| `BUCKET_READ` | 50 per 6 s | [DECIDED] | 50% of the published 100/6 s; set by the `upstream-api` topic |
| `BUCKET_WRITE` | 5 per 6 s | [DECIDED] | 50% of the published 10/6 s; set by the `upstream-api` topic |
| `BUCKET_DOC_CONTENT_WRITE` | 2 per 10 s | [DECIDED] | Below both the 3/10 s and 5/10 s candidates; set by the `upstream-api` topic |
| `BUCKET_LIST_DOCS` | 2 per 6 s | [DECIDED] | 50% of the published 4/6 s; set by the `upstream-api` topic |
| `RATE_LIMIT_KEY` | `sha256(token)` | [SPEC-VERIFIED] | Server-side buckets are keyed per **user/IP**, not per token — see §2.2. One limiter instance per credential is the closest a single process can get |

### 429 retry parameters

The retry policy itself — that a 429 is retried at all, on a bounded budget,
under a hard deadline, with jitter, and surfaced rather than waited out when the
budget is spent — is **decided by the `upstream-api` topic**. The values below
are that policy's parameters.

| Constant | Value | Marker | Justification |
|---|---|---|---|
| `RETRY_AFTER_TRUSTED` | `False` | [SPEC-VERIFIED] | No `Retry-After` or `X-RateLimit-*` header exists — see §2.2. Parse opportunistically, never require. **Probe P6, 2026-09-04**: a live attempt to provoke a real 429 (the ethically-bounded maximum of 6 rapid export POSTs) did not succeed — all six returned 202. Whether a genuine 429 carries `Retry-After` remains empirically unanswered; this entry's basis is unchanged and uncontradicted |
| `RETRY_AFTER_CLAMP_S` | `(1.0, 60.0)` | [DECIDED] | Bounds an untrusted value if one ever appears; set by the `upstream-api` topic |
| `BACKOFF_BASE_S` | `2.0` | [DECIDED] | Staff suggest 30/60/120 s, which is intolerable inside a synchronous tool call. See note below; set by the `upstream-api` topic |
| `BACKOFF_FACTOR` | `3.0` | [DECIDED] | Yields 2 s, 6 s, 18 s, 54 s; set by the `upstream-api` topic |
| `BACKOFF_MAX_S` | `60.0` | [DECIDED] | Matches the Onyx connector's `max_delay`; set by the `upstream-api` topic |
| `BACKOFF_JITTER` | equal jitter — `delay/2 + uniform(0, delay/2)` | [INFERRED-FROM-CLIENTS] | Every surveyed client that backs off applies jitter; buckets are shared, so unjittered clients synchronise |
| `MAX_429_RETRIES_READ` | `3` | [DECIDED] | ≈26 s of waiting; set by the `upstream-api` topic |
| `MAX_429_RETRIES_WRITE` | `4` | [DECIDED] | ≈80 s of waiting; set by the `upstream-api` topic |
| `STICKY_429_THRESHOLD` | `3` consecutive 429s, `STICKY_429_WINDOW_S` `120.0` with zero successes | [STAFF] | Sticky account-level 429s exist that backoff cannot clear — see §2.2 |
| `TOOL_CALL_DEADLINE_S` | `90.0` | [DECIDED] | Hard ceiling regardless of retries remaining. An MCP tool call has a human waiting on it; set by the `upstream-api` topic |

On the backoff base: staff's own recommendation is materially slower —
Eric Koleda, <https://connect.superhuman.com/t/x/42678/3>: *"One popular strategy
for this is exponential backoff, whereby you double the time you wait each time it
fails (30 seconds, then a minute, then two minutes, etc)."* That is right for a
batch job and wrong for an interactive tool. The client-side limiter is what
should make deep backoff rare; the backoff is a safety net, not the primary
strategy. **Staff's actual first answer to 429 is to batch**, not to wait.

**429 is replay-safe on every method, including POST/PUT/DELETE** [INFERRED-FROM-CLIENTS] —
the request was refused before execution. The `flywheel_connectors` Rust client
encodes this explicitly, treating 429 as retryable even for non-idempotent verbs.

## 1.2 Batch and size caps

| Constant | Value | Marker | Justification |
|---|---|---|---|
| `MAX_REQUEST_BYTES` | `1_500_000` (1.5 MB) | [STAFF] on the ceiling, [CHOSEN] on the margin | Published cap is **2 MB**; 25% headroom for encoding overhead |
| `ROW_INFLATION_FACTOR` | `2.2` | [CHOSEN — no evidence, tune later] | Single data point: a 44 KB `Content-Length` request was rejected as "87 KB". Ratio ≈2.0; 2.2 adds margin. Must be re-measured — see probe P7 |
| `MAX_ROW_JSON_BYTES` | `38_000` (38 KB) | [CHOSEN — no evidence, tune later] | 38 KB × 2.2 ≈ 84 KB internal, under the published 85 KB row ceiling |
| `MAX_ROWS_PER_UPSERT` | `100` soft, `250` hard | [CHOSEN — no evidence, tune later] | **No published limit exists.** A user reports "several hundred rows" in one call working in production. The byte cap binds first for fat rows |
| `MAX_ROW_IDS_PER_DELETE` | `500` | [CHOSEN — no evidence, tune later] | Row IDs are ~12 bytes; the byte cap never binds. Larger batches consume fewer doc-content-write tokens |
| `MAX_PAGE_CONTENT_BYTES` | `700_000` (700 KB) | [CHOSEN — no evidence, tune later] | 700 KB × 2.2 ≈ 1.5 MB internal. No published page-content limit exists |
| `LIST_PAGE_SIZE` | `200` requested | [INFERRED-FROM-CLIENTS] | `codaio` self-caps GET `limit` at 200. The real max is deliberately undocumented and **silently clamped** |
| `PAGE_CONTENT_LIST_LIMIT` | `500` | [SPEC-VERIFIED] | `listPageContent` uses a distinct `pageContentLimit` param with `maximum: 500`, `default: 50` |

Chunk on **both** axes — accumulate rows until either the count cap or
`MAX_REQUEST_BYTES` is reached, measured on the actual serialised JSON. 100 rows ×
38 KB would be 3.8 MB, so the byte cap governs fat rows and the count cap governs
skinny ones.

Reject an oversized single row **before** sending it. The server's error does not
identify which row in the batch was at fault.

## 1.3 Asynchronous mutation polling

| Constant | Value | Marker | Justification |
|---|---|---|---|
| `MUTATION_INITIAL_SLEEP_S` | `3.0` | [STAFF] on the need, [CHOSEN] on the magnitude | "add a short sleep, **maybe a few seconds**, before the first time you call that endpoint" — see §2.1 |
| `MUTATION_POLL_INTERVAL_S` | `2.0` | [CHOSEN — no evidence, tune later] | Status reads are the cheapest bucket |
| `MUTATION_404_GRACE_S` | `15.0` | [CHOSEN — no evidence, tune later] | A 404 before this is replication lag, not a missing mutation. **Probe P4, 2026-09-04**: two independent write→poll sequences on a near-empty scratch doc never produced a 404, including at t=0 immediately after the write — the endpoint consistently returned 200 with `completed:false` instead. `completed` flipped to `true` between t=16s and t=18s. The 404-replication race did not reproduce on this doc; the observed bottleneck was completion latency (~18s), not a 404 window |
| `MUTATION_DEADLINE_S` | `60.0` | [CHOSEN — no evidence, tune later] | Then return "queued, not confirmed" — never an error. Staff describe the underlying delay as "30 seconds to a few minutes" and architectural |

The endpoint is at the **root**: `GET /mutationStatus/{requestId}`, *not*
`/docs/{docId}/mutationStatus/{requestId}` [SPEC-VERIFIED]. At least one public
client uses the wrong path. Status information is *"not guaranteed to be available
for more than one day after the mutation was completed"* [SPEC-VERIFIED].

## 1.4 Export

| Constant | Value | Marker | Justification |
|---|---|---|---|
| `EXPORT_BUCKET` | `BUCKET_WRITE` | [CHOSEN — no evidence, tune later] | **Not** the doc-content bucket. Genuinely undocumented; two independent client authors assume the tightest bucket, and **probe P6, 2026-09-04 refuted that**: six export POSTs in under 2 seconds all returned 202 with zero 429s, inconsistent with 3/10 s or 5/10 s, and served by a distinct `api-doc` backend pod class. A six-request burst is still within the general write bucket's published 10/6 s, so that bucket is not excluded — P6 narrows the question rather than answering it. `BUCKET_WRITE` is the conservative reading of what survives. See §2.5 |
| `EXPORT_INITIAL_SLEEP_S` | `2.0` | [STAFF] on the need, [CHOSEN] on the magnitude | Staff: *"Simply wait a second and retry"* — see §2.5 |
| `EXPORT_POLL_INTERVAL_S` | `2.0` | [INFERRED-FROM-CLIENTS] | Status GET is read-bucket; at 2 s this uses ~1.5% of it. Matches the two best-behaved clients |
| `EXPORT_POLL_BACKOFF` | ×1.5, capped at `EXPORT_POLL_MAX_INTERVAL_S = 15.0` | [INFERRED-FROM-CLIENTS] | `ofloveandhate/codaio` uses 1 s × 1.5 → 15 s |
| `EXPORT_DEADLINE_S` | `90.0` | [CHOSEN — no evidence, tune later] | No source quantifies export duration. `codaio` allows 300 s; 90 s fits a synchronous tool call |
| `EXPORT_404_GRACE_S` | `20.0` | [CHOSEN — no evidence, tune later] | A 404 within this window is replication lag. Calibrate with probe P5 |
| `EXPORT_LINK_TTL_S` | `300` (5 min) | **[STAFF], confirmed [SPEC-VERIFIED] 2026-09-04** | *"the downloadLink returned by the API expires after only a few minutes"*; the sibling Admin API endpoint publishes exactly 5 minutes. **Directly observed by probe P5b**: link served content at t=300s, failed by t=330s; the signed URL's own `X-Amz-Expires=300` query parameter corroborates this independent of staff prose — see §2.5 |
| `EXPORT_FILE_TTL` | ~a few days | [STAFF] | *"the exported file remains live for a few days"* — the file outlives the link, which is why re-polling mints a fresh URL |
| `EXPORT_MAX_LINK_REFRESH` | `2` | [CHOSEN — no evidence, tune later] | Re-GET the status endpoint to mint a fresh link |
| `EXPORT_CONCURRENCY_PER_PAGE` | `1` | [INFERRED-FROM-CLIENTS] | The blob key is `DOC_EXPORT_RENDERING/{pageId}/{docId}` — keyed by page and doc, **not** by request ID, so concurrent exports of one page collide on one object |
| `EXPORT_CONCURRENCY_GLOBAL` | `3` | [CHOSEN — no evidence, tune later] | Concurrency limits are entirely undocumented. `professor-eggs/coda-md-export` throttles to avoid "45+ concurrent exports at once" |
| `EXPORT_MAX_PAGES_PER_CALL` | `50` | [CHOSEN — no evidence, tune later] | Export is single-page; recursion is ours. Bounded by `EXPORT_CONCURRENCY_GLOBAL` and the export deadline rather than by the doc-content rate, which P6 showed export does not draw on — surface truncation rather than blocking |

---

# 2. Findings on the five unknowns

## 2.1 `X-Coda-Doc-Version: latest`

**Declared on zero operations** [SPEC-VERIFIED] — there are no `in: header`
parameters anywhere in v1.6.0. It is a cross-cutting header the framework reads,
not a per-operation parameter.

**Scope is the whole doc, not the requested resource** [STAFF]. Asked directly
whether it fails on any pending update anywhere versus only the requested row's
dependency graph — Eric Koleda, 2022-10-17,
<https://connect.superhuman.com/t/x/34463/7>:

> **Nick_HE:** "if you supply that header, it will return an error if there is a
> pending update anywhere in the doc"
>
> **Eric_Koleda:** "That's correct. It is looking at **any pending updates to the
> doc, from any source**."

And on what it actually buys, same post:

> "this new feature **doesn't get you new content any faster, it just fails rather
> than return the old content**."

**Accepted values:** only `latest` appears in the spec, the rendered docs, the help
centre, every staff post, and all public code referencing it. Any other value is
untested — see probe P2.

**The 400 cannot be distinguished by shape** [SPEC-VERIFIED]. There are two 400
schemas: `BadRequestError` (bare `{statusCode, statusMessage, message}`) and
`BadRequestWithValidationErrors` (adds `codaDetail.validationErrors`). The latter is
referenced by 49 operations — **all of them Packs, Pack-logs, or agent-logs
endpoints**. Not one docs, rows, pages, tables, or columns operation uses it. On
every endpoint this project touches, a staleness 400 and a malformed-request 400 are
byte-identical.

**Corrected by live observation, 2026-09-04 (probes P2/P3).** `listPageContent`
(`GET /docs/{docId}/pages/{pageId}/content`) *does* return a
`codaType`/`codaDetail.issues`-bearing 400 for a real schema violation (tested:
`contentFormat=bogusFormat`) — the shape claim above does not hold for at least
this docs-domain operation. Separately, and more consequentially:
`X-Coda-Doc-Version` was found to reject **any value other than the literal string
`latest`** with `400 {"message":"Doc is not yet up to date."}` — reproduced
deterministically across multiple endpoints and before any write had been made in
the session, i.e. with no plausible pending mutation. This is plausibly the *same*
underlying mechanism as genuine staleness (the header may compare against an
actual current-version stamp, with `latest` special-cased to always pass, so an
arbitrary string simply never matches) rather than a separate validation path —
it is not necessarily evidence that the message text is fake. But it does mean an
observed `"Doc is not yet up to date."` 400 during real usage, where the header is
always sent as `latest`, has not been *confirmed* to require an actual pending
mutation, only demonstrated to require `header value != "latest"`. Genuine
staleness immediately after a real write was not observed in this session (10
reads post-write all returned 200 — see the probe plan's Results for P3).

The only implementation found that attempts the distinction substring-matches an
undocumented message, hedging across four guesses — `jimbaxley/coda-to-framer-node`,
`lib/coda-client.js`:

```js
message.includes("pending mutation") || message.includes("pending mutations")
  || message.includes("not yet up to date")
  || (message.includes("latest") && message.includes("mutation"))
```

No one has ever posted the actual message text. **A shape-free discriminator exists
and does not depend on wording:** on a 400 from a request carrying the header,
re-issue the byte-identical request *without* it. Success means staleness; a second
400 means the request was malformed. This costs one extra read only on the failure
path.

**Staff argue both sides.** Recommending the retry loop —
<https://connect.superhuman.com/t/x/54041/2>:

> "Add the header `X-Coda-Doc-Version: latest` to your requests, which will cause
> them to fail if there is a pending mutation. **Keep retrying until the request
> succeeds.**"

Then, two posts later, <https://connect.superhuman.com/t/x/54041/4>:

> "The problem with the `X-Coda-Doc-Version: latest` header is that it will fail
> the request if there is **any** pending mutation in the doc. For a busy doc with
> lots of users working on it at the same time **the API requests may continue to
> fail for a long time**. The **getMutationStatus approach works better** when you
> really only care about a specific mutation being completed."

**It may not fire at all.** One user reported it never returning 400 after large
row deletions — unanswered by staff, thread closed:
<https://connect.superhuman.com/t/x/49750/1> (2024-07-02).

**Why the staleness exists** [STAFF], <https://connect.superhuman.com/t/x/54041/2>:

> "Docs are composed of two things: a snapshot and a list of operations… The API
> backend can't replay operations, so it's just looking at the latest snapshot. New
> doc snapshots are taken on a regular basis, which for small docs can be **within
> 30 seconds or so**, but for larger more complex docs it may be **every few
> minutes**."

**For read-your-writes after our own mutation, use `getMutationStatus`, not this
header** [STAFF]. The mutation-status endpoint has its own replication race —
Eric Koleda, <https://connect.superhuman.com/t/x/54041/8>:

> "There is unfortunately a known issue with the `getMutationStatus` endpoint
> returning a 404, and this happens because of a **replication delay in our
> backend**. The solution is to add a **short sleep, maybe a few seconds**, before
> the first time you call that endpoint."

## 2.2 429, `Retry-After`, and bucket ownership

**No `Retry-After`. No `X-RateLimit-*`.** [SPEC-VERIFIED]

- The spec contains 127 `429` references, every one a `$ref` to
  `TooManyRequestsError`, which declares `content` only — **no `headers` object**.
  `components.headers` is empty. Zero occurrences of `Retry-After` or `X-RateLimit`
  anywhere in the document.
- The rendered developer docs page (2.6 MB) contains zero case-insensitive matches
  for `retry-after`.
- Forum-wide full-text search for `Retry-After` returns **zero posts**.
- Live measurement against `GET /apis/v1/whoami` (15 sequential unauthenticated
  requests). The complete response header set is: `content-type`, `content-length`,
  `date`, `x-coda-pod`, `vary`, `set-cookie` ×2, `etag`, `x-coda-server`, `x-cache`,
  `via`, `x-amz-cf-pop`, `alt-svc`, `x-amz-cf-id`, `strict-transport-security`.
  **No rate-limit headers of any kind.** A real 429 was not provoked; the limiter
  sits behind authentication and hammering it would be abusive. Probe P6 settles it.

**429 body** [SPEC-VERIFIED, plus a real user paste at
<https://connect.superhuman.com/t/x/47493/7>]:

```json
{"statusCode": 429, "statusMessage": "Too Many Requests", "message": "Too Many Requests"}
```

`additionalProperties: false` on the schema means there is no undocumented body
field carrying a retry delay either.

**Buckets are keyed per user *and IP*, not per token.** The spec says "per-user";
the help centre FAQ is more specific, and this is the single most consequential line
for a multi-client MCP server —
<https://help.coda.io/hc/en-us/articles/39555941038349> and its Superhuman mirror
<https://help.superhuman.com/hc/en-us/articles/46210310809613> (updated 2026-08-17):

> **"Are API limits per workspace, user, or token?** Limits are attached to a
> **user/IP**."

Consequences: two tokens for one user share one bucket; two docs share one bucket;
two MCP client processes on one account contend; and users behind one egress IP may
contend with each other. A per-process limiter cannot see any of this, so **429s
will occur that the limiter did not predict**. Surface that in the error text rather
than pretending the limiter is authoritative.

Spec prose, verbatim: *"Limits apply per-user across all endpoints that share the
same limit and across all docs."* [SPEC-VERIFIED]

**Sticky 429s exist and backoff does not clear them** [STAFF]. In
<https://connect.superhuman.com/t/x/47493>, a user disabled all API traffic for 30
minutes, then made **one** write to a **fresh** doc and still received a 429,
repeatedly; reads were unaffected. Eric Koleda: *"1 request per 10 seconds should be
under the limit, so I'm not sure why you are still getting 429 errors."* It required
an engineer to touch the account (`/47493/10`: *"the engineering fix has
successfully stopped the 429 errors"*). Detect this state and fail fast with a
distinct message rather than exhausting the deadline in a loop.

**No tier escape hatch** [STAFF], <https://connect.superhuman.com/t/x/54749/2>
(2025-03-25): *"Unfortunately we don't offer different tiers of rate limits
currently, although I think it's worth considering."*

**Most public clients have no 429 handling at all** [INFERRED-FROM-CLIENTS]:
`codaio`, `coda-js`, the n8n Coda node, and `orellazri/coda-mcp` (zero matches for
`429` or `retry` in the entire repository). Of those that do, **none treats
`Retry-After` as guaranteed** — every one hardcodes a fallback (Onyx: 30 s;
`flywheel_connectors`: `unwrap_or(30_000)` ms; TJC-LP: `headers.get("Retry-After", "60")`).

**Staff's first answer to 429 is to batch**, <https://connect.superhuman.com/t/x/47493/4>:
*"Are you able to batch your row changes into fewer `upsertRows` calls?"* and
`/47493/12`: *"you can use the `upsertRows` endpoint to update multiple rows at once."*

## 2.3 Batch and size limits

**The 85 KB / 2 MB figures are official, not folklore** [STAFF/help centre]. Same
FAQ as above:

> **"Are there API size limits on requests?** The limit for requests is **2 MB**,
> but there is also a limit of **85 KB** for any given row."

**The 85 KB is measured in Coda's internal representation, not wire bytes.** Real
error bodies:

```json
{"statusCode":400,"statusMessage":"Bad Request",
 "message":"Row edit of size 87 KB exceeds maximum size of 85 KB."}
```

— sent for a request whose `Content-Length` was **44 KB**
(<https://connect.superhuman.com/t/x/44481/1>). A second report shows *"Row edit of
size 89 KB exceeds maximum size of 85 KB"* (<https://connect.superhuman.com/t/x/17819/1>).
Community explanation, **not staff**: 85 KB is the row's size in the doc file,
covering all non-formula columns plus overhead, with rich text stored as JSON and
likely UTF-16 accounting. The claim that formula columns are excluded is
unconfirmed by anyone at Coda.

**An oversized body returns 400, not 413** [real error paste]: *"I got a 400 error:
'request entity too large'"* (<https://connect.superhuman.com/t/x/10826/1>). A
forum search for `413` returns zero posts. Treat a 400 matching
`entity too large` or `exceeds maximum size` as **non-retryable** and re-chunk.

**No maximum rows per upsert has ever been published.** [SPEC-VERIFIED] The entire
spec contains **zero** `maxItems`, and no `maxLength` on any docs-domain schema —
`RowsUpsert.rows`, `RowsDelete.rowIds`, and `PageContent.content` are all
unconstrained. Forum searches for batch-size guidance return nothing. The only
data point is a user describing *"a single write request … which updates several
hundred rows"* working in production (<https://connect.superhuman.com/t/x/47493/5>).
The binding constraint is the 2 MB body, not a row count.

**Page size is silently clamped** [SPEC-VERIFIED], spec prose verbatim:

> "**The maximum page size may change at any time, and may be different for
> different endpoints.** Please do not rely on it… If you pass a `limit` parameter
> that is larger than our maximum allowed limit, we will only return as many results
> as our maximum limit. You should look for the presence of the `nextPageToken` on
> the response to see if there are more results available, rather than relying on a
> result set that matches your provided limit."

So continuation must key off `nextPageToken`, never off a short result set.

**Docs over 125 MB lose API access entirely** [help centre]:

> "On all plan types, docs larger than 125 MB may not be able to access the
> Superhuman Docs API… **developer APIs will not be supported past this limit.**…
> This doc is over 125 MB. Developer API calls or use as a new Cross-doc sync source
> doc are not supported at this size."

The 125 MB excludes file attachments. Separately, HTML exports cannot exceed
125 MB (does not apply to PDF or plain text), and all docs are subject to a 325 MB
formula-calculation limit above which calculations are disabled. Doc size is not
readable through the API — if a doc produces persistent 4xx/timeouts across
multiple endpoints, surface this message so the user can check the Statistics panel.

## 2.4 Sync tokens — recommendation: **do not ship in v1**

**`syncToken` is the least-exercised surface in the API.** [SPEC-VERIFIED plus
exhaustive negative search]

- Forum full-text search for `syncToken` → **zero posts**. For `nextSyncToken` →
  **one post**, and it is incidental: a user pasted the sample response while asking
  about *pagination* (<https://connect.superhuman.com/t/x/34616/3>). A Coda staff
  member replied twice in that thread about `nextPageToken` and never addressed
  `nextSyncToken`, though it was in the pasted payload.
- The `syncToken` / `nextSyncToken` description text is **byte-identical between a
  2022-03 archived spec and today's v1.6.0** — unchanged in four years.
- No hand-written consumer exists in any public repository. `codaio` passes it
  through with a copied docstring and no semantics. `orellazri/coda-mcp` does not
  expose it.
- The help centre has no article on it. No staff member has ever posted about it.

**Deleted rows: structurally cannot be reported.** [SPEC-VERIFIED] `RowList.items`
is `Row[]`; `Row` is `additionalProperties: false` with
`required: [id, type, href, name, index, browserLink, createdAt, updatedAt, values]`.
There is no `deleted`/`tombstone` field, and a deleted row could not supply
`values`, `index`, or `browserLink`. **Assume deletions are invisible to a delta
and require a reconciling full read.**

**Expiry and invalidation: no error string exists to quote.** [SPEC-VERIFIED on the
shape] `listRows` declares 400/401/403/404/429 and notably **no 410**, in contrast
to the export endpoints which do. A rejected token most likely surfaces as a generic
400 with no discriminator — the same undiagnosable shape as §2.1.

**Combining with other parameters: the filter is baked into the token.**
[SPEC-VERIFIED for `pageToken`, inferred for `syncToken`] Spec prose, verbatim:

> "You only need to pass the `pageToken` to get the next page of results, you don't
> need to pass any of the parameters from your original request, as they are all
> implied by the `pageToken`. **Any other parameters provided alongside a
> `pageToken` will be ignored.**"

Coda's own `packs-sdk` enforces this first-party, dropping every parameter —
`syncToken` included — when `pageToken` is present
(`helpers/external-api/coda.ts`):

```ts
const {pageToken, ...rest} = allParams;
const codaUrl = withQueryParams(
  `/apis/v1/docs/${docId}/tables/${tableIdOrName}/rows`,
  pageToken ? {pageToken} : rest,
);
```

`nextSyncToken`'s own description mirrors the wording — *"results that match the
parameters specified when the sync token was created"* — so filters are almost
certainly baked in at creation time. **The "will be ignored" sentence is written
about `pageToken` only; no source extends it to `syncToken`.**

**Calculated columns: unknown, and the closest documented analogue does not work.**
The `sortBy` parameter carries this warning verbatim: *"'UpdatedAt' sort ordering is
the order of rows based upon when they were last updated. **This does not include
updates to calculated values.**"* Nothing extends or contradicts that for
`syncToken`. Related staff observation on non-obvious change stamping —
Eric Koleda, <https://connect.superhuman.com/t/x/50562/2>: *"one tricky bit is that
I think table content updates will cause the document to be updated, but not any
individual page."*

**Staff have never endorsed it, and recommend `updatedAt` polling instead.** When
asked the exact adjacent question — how to incrementally re-export changed pages —
Eric Koleda, 2024-08-19, <https://connect.superhuman.com/t/x/50562/2>:

> "Although you can't filter on updated date, both the Document and Page resource
> contain an `updatedAt` field you can use to determine if it has been updated
> recently. So your approach could be: For each doc: If updated after last sync: For
> each page in the doc: If updated after last sync: Export page content"

And earlier, Oleg Vaskevich (Coda), 2019-10-31,
<https://connect.superhuman.com/t/x/11765/4>:

> "you can either build a tool yourself that periodically looks for changes to a
> table (**fetch all the rows and look where the modified date is greater than the
> last fetch date**), or use Zapier"

**Recommended v1 posture.** Do not expose `sync_token` on any tool. If
`nextSyncToken` appears in a response, ignore it for control flow and do not surface
it to the model as a usable handle. Offer the staff-recommended alternative instead:
`listRows` with `query` for filtering, `updatedAt` for coarse change detection with
the calculated-value caveat stated **in the tool description**, and client-side
content hashing where exactness matters.

The reasons, in order of weight: you cannot tell a caller whether a delta is
complete, because deletion reporting is structurally impossible; you cannot detect
token invalidation, because the 400 is undiagnosable; the calculated-column
semantics are unknown and the nearest documented analogue explicitly fails; and with
zero users and zero staff posts in the forum's entire history, there is no chance of
discovering you are wrong before your users do. An MCP tool that silently returns an
incomplete delta to a language model is worse than one that does not offer the
feature.

If it is ever added: pass the token opaquely, send it as the only query parameter,
treat any non-2xx on a token'd request as "invalid → full resync" without retrying,
and label every result `deletions_included: false`.

## 2.5 Export mechanics

**`downloadLink` lifetime is quantified** [STAFF]. Jonathan Goldman (Coda,
`user_title: "Superhumans"`), the endpoint's launch announcement, 2023-11-02,
<https://connect.superhuman.com/t/44103/1>:

> "While the **exported file remains live for a few days**, the **downloadLink
> returned by the API expires after only a few minutes**. To get a fresh URL to your
> export simply make another request to retrieve the export status."

Corroborated by Coda's **Admin API** spec, which quantifies the sibling doc-export
endpoint exactly — `getExportRequestStatusV2`: *"Download links are valid for
**5 minutes** and a new download link is returned on each call to this API once the
export has completed."* Same wording pattern for the `downloadLink` field, same
team. That is the best available quantification, though it is literally about
`/apis/admin/v1/`, not the page export.

**Polling instructions, verbatim** [STAFF], same launch post:

> "Make a GET request to the href URL to check the status of the export. **Continue
> to poll this endpoint until the status is "complete".** A completed export will
> include a `downloadLink` field which is the URL of a temporary file that contains
> the exported content."

**The 404 race is staff-documented twice.** Same launch post:

> "If you begin a new export and then immediately check it's status you might get a
> **404 Not Found** error response. This is because our backend hasn't caught up
> just yet. **Simply wait a second and retry.**"

And Eric Koleda, 2024-06-26, <https://connect.superhuman.com/t/49372/3>:

> "There is a known issue with page content exports, where the **export IDs aren't
> immediately replicated to all of our servers**, resulting in a 404 error if you
> request the status right after the export has started. Unfortunately the best
> solution at the moment is to introduce a **small delay and/or add a retry with
> some backoff**."

The mechanism is observable: consecutive requests to `/apis/v1/whoami` are served by
different pods (`x-coda-pod: api-5c99ccdd94-bb8l8`, `…-vqlxf`, `…-skcvf`), so there
is no request affinity to hide replication lag [SPEC-VERIFIED by live probe].

**The rate-limit bucket is genuinely undocumented.** No staff statement, no user
429 report on the export endpoint. Two competing inferences: *against* the
doc-content bucket, staff describe it as "doc content **changes**" and an export
mutates nothing; *for* it, the call is a POST under `/docs/{docId}/pages/…`
returning 202, and rendering is expensive. Two independent client authors assume the
tightest bucket.

**Probe P6, 2026-09-04, live measurement: six export POSTs fired in under 2 seconds
all returned 202. Zero 429s.** This is inconsistent with the export POST sharing
the doc-content-write bucket at either published rate (3/10s or 5/10s) — either
figure would have produced a 429 by the fourth or fifth request in that window.
Whether export uses the general-write bucket, an export-specific bucket, or no
enforced bucket at all could not be determined from six requests (the plan
deliberately bounds this probe there), but it is measurably more permissive than
doc-content-write. **Incidental corroborating detail:** the export POST's response
headers show `x-coda-server: api-doc` and pod names prefixed `api-doc-...`,
distinct from `x-coda-server: api` / `api-...` seen on every other endpoint probed
in the same session (`/whoami`, `/docs/{docId}/tables`, `/docs/{docId}/pages/...`)
— export traffic is served by a visibly separate backend pod class, consistent
with (though not proof of) a separate rate-limit bucket. A real 429 was not
provoked, so the `Retry-After` question (see §1.1 `RETRY_AFTER_TRUSTED`) remains
unanswered.

**Concurrency limits are undocumented.** Zero forum hits, nothing in either spec.
That is absence of documentation, not evidence that no limit exists.

**Subpages are not included** [SPEC-VERIFIED]. `BeginPageContentExportRequest` is
`additionalProperties: false` with exactly one property, `outputFormat` (required).
There is no include-children flag. Coda **does** use an explicit `includeSubpages`
flag where it means it — the sync-page creation payload has one — so its absence
here is a design signal, not an oversight. The `Page` schema has `children` as a
**required** field: the tree is meant to be walked client-side. Community
confirmation, <https://connect.superhuman.com/t/x/12539/5>: *"This is however page
at a time, so you would have to couple this with listing/enumerating the
pages/subpages of a document and export each one."*

**Sync pages cannot be exported.** They return 400 saying only canvas pages can be
exported (<https://connect.superhuman.com/t/55845/1>); Eric Koleda called it *"a
really reasonable request"* and filed it, still open. [SPEC-VERIFIED] `PageType` is
`[canvas, embed, syncPage]`.

**Markdown export drops page-level attachments; HTML keeps them** [STAFF] —
Eric Koleda, 2025-08-25, <https://connect.superhuman.com/t/57065/2>: *"we don't have
a dedicated API endpoint for getting page-level file attachments. While they are
**omitted in the markdown export**, you can get the URLs from the **HTML export**."*

**A dead download URL returns XML, not JSON.** Observed shape
(<https://connect.superhuman.com/t/44960/1>; that specific instance was a Coda bug
fixed within days, but the error *shape* is real):

```xml
<Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message>
  <Key>DOC_EXPORT_RENDERING/pageId/DocID</Key>
```

Note the key is `DOC_EXPORT_RENDERING/{pageId}/{docId}` — keyed by page and doc, not
by request ID.

**Directly observed, 2026-09-04 (probe P5b): the link is valid through t=300s and
expired by t=330s after mint, confirming `EXPORT_LINK_TTL_S = 300`.** The expired
link returned **`HTTP 403` with `<Code>AccessDenied</Code>`** — a different status
code and S3 error code than the `NoSuchKey`-on-200 shape above, but the same
failure family (an `<?xml`-prefixed body). Both shapes must be treated as
fatal-for-this-link; do not assume the failure is always disguised behind a 200.

**The download host is not the API host** [SPEC-VERIFIED by live probe].
`https://docs.superhuman.com/blobs/DOC_EXPORT_RENDERING/…` is served by the web app,
not the API pod: it returns none of `x-coda-server: api` / `x-coda-pod` that every
`/apis/v1/*` response carries. **Downloading does not consume the API rate-limit
budget**, and it needs no `Authorization` header — `orellazri/coda-mcp` fetches it
with a bare `axios.get` and it works.

### A synchronous alternative that avoids the export machinery entirely

`GET /docs/{docId}/pages/{pageIdOrName}/content` — `operationId: listPageContent`
[SPEC-VERIFIED]:

- Returns `PageContentList`: content elements, one per line, each with a stable
  element `id`. **Correction, [SPEC-VERIFIED] by live probe P9, 2026-09-04:**
  `style`, `format`, `content`, and `lineLevel` are not top-level fields on each
  item — they are nested one level down under `item.itemContent`. Observed shape:
  `{"id": "cl-...", "type": "line", "itemContent": {"style": "paragraph",
  "format": "plainText", "content": "...", "lineLevel": 0}}`.
- `limit` uses the distinct `pageContentLimit` parameter — `maximum: 500`,
  `default: 50`.
- `contentFormat` is an enum with exactly one legal member: **`plainText`**.
- It is a **GET → read bucket (100/6 s)**. No 202, no polling, no download link, no
  404 replication race, no XML failure mode. Declares `410 Gone`.

Markdown and HTML remain export-only. Where plain text suffices — previews, search,
"what is on this page" — this is dramatically cheaper and cannot fail in any of the
ways §3 guards against.

### Round-trip fidelity — the constraint that shapes the tool surface

Staff, in the same launch post for these endpoints,
<https://connect.superhuman.com/t/44103/1>:

> "Be aware **HTML and markdown can't perfectly represent all of the features of a
> Coda doc, so a round trip in either format may lose some information. These
> endpoints are best used for import or export scenarios, not page editing.**"

The natural MCP shape — read page, let the model edit, write it back — is exactly
the round trip staff warn against. Per-construct fidelity is measured separately in
`docs/validation/2026-09-03-markdown-fidelity-tests.md`.

---

# 3. The export state machine

This is the subtlest part of the client. State it as rules, not as a status-string
comparison.

## 3.1 Gate on `downloadLink` / `error`, never on `status`

**`PageContentExportStatus` is a dangling enum.** [SPEC-VERIFIED] It is defined:

```yaml
PageContentExportStatus:
  type: string
  enum: [inProgress, failed, complete]
```

and **nothing `$ref`s it**. Both `BeginPageContentExportResponse.status` and
`PageContentExportStatusResponse.status` are bare `type: string` with a
`description` and an `example`. The enum therefore constrains nothing on the wire
and nothing in generated clients — `orellazri/coda-mcp`'s generated `types.gen.ts`
carries both the enum *and* `status: string`.

The examples are demonstrably unreliable in both directions: `example: complete`
appears on the **begin** response, for a request that has just started. And the
spec's own three code samples for the status endpoint all print **`completed`**,
contradicting the enum's `complete`.

Staff prose says `complete` (§2.5), and every surveyed third-party client compares
against `"complete"` without anyone filing a bug — if the wire value were
`completed`, Pipedream's `do…while (exportStatus !== "complete")` would loop
forever and would have been reported. So `complete` is very probably correct.

**Confirmed by live observation, 2026-09-04 (probe P5a).** The begin-response
`status` was `"inProgress"`, not the spec example's `"complete"` — the example is
wrong, as predicted above. The completed-response `status` was `"complete"`, not
`"completed"` — the code samples are wrong, also as predicted above.

**But do not depend on it.** The field is typed as an unconstrained string by the
API's own schema, so reading it is guessing. Gate on **presence of `downloadLink`**
for success and **presence of `error`** for failure. This is immune to the whole
ambiguity and costs nothing. Read `status` only for logging, and if you must branch
on it, accept `complete` **and** `completed`.

## 3.2 Rules

1. **Precondition:** only export pages whose `contentType == "canvas"`. `syncPage`
   returns 400; `embed` is untested. Skip the rest with an explicit reason rather
   than a generic error.
2. **Choose the format for the payload:** `markdown` drops page-level attachments;
   `html` retains them. If the caller needs attachments, `html` is the only option.
3. **POST** `/docs/{docId}/pages/{pageIdOrName}/export` → expect **202** with `id`
   and `href`. Charge it to `EXPORT_BUCKET`.
4. **Sleep `EXPORT_INITIAL_SLEEP_S` (2 s) before the first status GET.** Staff
   prescribe a delay; skipping it guarantees the 404 race.
5. **Poll** the status GET at `EXPORT_POLL_INTERVAL_S` (2 s), backing off ×1.5 to a
   15 s ceiling, until `EXPORT_DEADLINE_S` (90 s). Status GETs are read-bucket.
6. **404 within `EXPORT_404_GRACE_S` (20 s) is *not* an error** — it means the
   export ID has not replicated to the pod serving this request. Keep polling. After
   the grace window, a 404 becomes terminal.
7. **410 Gone is distinct from 404.** The status endpoint declares
   `410 — "The resource has been deleted."` [SPEC-VERIFIED], which `listRows` does
   not. Read 410 as *the export request has aged out*, consistent with the file
   living "a few days". Restart from the POST once; do not treat it as retryable
   polling.
8. **Success** = `downloadLink` present. **Failure** = `error` present; surface it
   verbatim and stop.
9. **Never cache `downloadLink`.** It expires in ~5 minutes while the underlying
   file lives for days, so a cached link is the single most likely cause of a
   mysterious later failure. Download immediately; if the download must be deferred
   or retried, re-GET the status endpoint to mint a fresh URL —
   the spec explicitly sanctions this: *"Call this method again to get a fresh link."*
10. **Validate the downloaded body before returning it.** A dead link yields S3-style
    XML, and a naive client hands that to the model as page content:

    ```python
    def looks_like_s3_error(body: bytes) -> bool:
        head = body[:512].lstrip()
        return head.startswith(b"<?xml") or b"<Code>NoSuchKey</Code>" in head
    ```

    On a non-200, or on a 200 that trips this check, re-GET status for a fresh link
    up to `EXPORT_MAX_LINK_REFRESH` (2) times.
11. **Serialise per `(docId, pageId)`.** The blob key omits the request ID, so two
    in-flight exports of one page race on one object.
12. **Recurse over subpages ourselves** via `listPages` / `Page.children`, capped at
    `EXPORT_MAX_PAGES_PER_CALL` (50), reporting truncation. At 2 requests per 10 s
    for the POST alone, 50 pages is ≥250 s — prefer a "list pages, then export
    these N" flow over one tool call that blocks for minutes.

---

# 4. Client survey

All read in source. Note that the two most widely used MCP implementations are among
the weakest here.

| Client | Poll interval | Cap / timeout | Gates on |
|---|---|---|---|
| `ofloveandhate/codaio` | 1 s, ×1.5 backoff, max 15 s | 300 s | **`downloadLink` / `error`** — the correct approach |
| `professor-eggs/coda-md-export` | 2 s, after a 3 s pre-poll delay | 60 tries (~2 min) | `'complete'` / `'failed'` |
| `IP-Copilot/integration-examples` | 2 s | 10 tries (~20 s) | `!= "complete"`; **handles 404 correctly** |
| `Auniik/coda-ai` | 3 s, sleeps before first poll | 30 tries | `'complete'` / `'failed'` |
| `PipedreamHQ/pipedream` | 3 s | **none** | `!== "complete"` |
| `orellazri/coda-mcp` | 5 s, sleeps 5 s before first poll | 5 tries (~25 s) | `=== "complete"` |

**Two bugs not to copy:**

1. **`PipedreamHQ/pipedream` — the infinite loop.** Its `do…while (exportStatus !== "complete")`
   has no iteration cap and never checks for `"failed"`. A failed export hangs the
   integration permanently.
2. **`orellazri/coda-mcp` — treats 404 as fatal.** Its status call uses
   `throwOnError: true` inside a `try` that rethrows, so the staff-documented
   replication 404 aborts the whole operation instead of being retried. It also
   throws on its final loop iteration rather than polling it, wasting the last
   attempt, and its 5 s pre-poll sleep adds latency without benefit.

For 429 handling specifically: `codaio`, `coda-js`, the n8n Coda node and
`orellazri/coda-mcp` have **none at all**. See §2.2 for those that do.

---

# 5. `listRows` under load — 504, not 429

`listRows` is the endpoint that fails first on large docs, and it fails with a
**gateway timeout**, not a rate-limit error. Eric Koleda (Coda), 2025-02-20,
<https://connect.superhuman.com/t/54136/3>, responding to repeated 504s:

> "If this is a very large doc then it sounds likely that it's hitting some
> **infrastructure limit in our API** that's causing requests to fail. Have you
> looked into reducing the size or complexity of the doc?"

**Response:** treat a 504 from `listRows` as **"reduce `limit` and retry"**, not as
a transient blip to back off on. Halve the requested page size (e.g. 200 → 100 → 50
→ 25) and retry, up to a floor of 25, before surfacing the failure. Backing off in
time does not help — the request is too expensive at that page size and will time
out again. Include the doc-size hypothesis in the error text so the user can check
the Statistics panel against the 125 MB API ceiling (§2.3).

There is precedent for API-wide degradation unrelated to any client behaviour: a
multi-day timeout incident in March 2026 (<https://connect.superhuman.com/t/60264>)
that staff traced to API server memory having been "accidentally reduced". A client
that retries forever on 5xx will burn a user's whole session during such an
incident; the `TOOL_CALL_DEADLINE_S` ceiling exists partly for this.

---

# 6. Endpoint inventory — what v1.6.0 does and does not contain

Read directly out of the served OpenAPI document on 2026-09-04 [SPEC-VERIFIED].
`https://coda.io/apis/v1/openapi.json`, `info.version: 1.6.0`, 92 paths.
YAML-rendering digest at the same moment:
`d145ed596a33830548e1ceac6668df94c10b71491800d0855bc0711472d0224b`.

**Absent from the surface.** These were checked because a design decision turns
on them, and each is an absence in the specification rather than an inference:

- **No comment endpoint of any kind.** No path contains the substring
  `comment`.
- **No table creation.** Every `/tables` path is GET-only except the row
  collections. The complete set of `create*` operations in the whole document is
  `createDoc`, `createPage`, `createFolder`, and four Packs operations
  (`createPack`, `createPackInvitation`, `createPackRelease`,
  `createPackReview`). Nothing creates a table, and nothing creates a column.
- **No transaction or rollback.** The only paths matching `batch` belong to Packs
  ingestion and are unrelated. The write model is the asynchronous one —
  `/mutationStatus/{requestId}` — which has no concept of grouping writes or
  undoing them.

The vendor's own MCP server offers all three (`table_create`, comments as a
content channel, atomic multi-operation editing with rollback). They are
capabilities of that server, not of this REST surface, so a client built on v1
cannot reach them by trying harder.

**Present, and easy to miss.** `DELETE /docs/{docId}/pages/{pageIdOrName}/content`
— `deletePageContent`, *"Delete content from a page. You can delete specific
elements by providing their IDs, or delete all content from the page."* Clearing
a page is therefore a first-class operation with its own endpoint, **not** a
whole-page `replace` carrying an empty payload. The same endpoint also deletes
named elements by ID, which is a narrower destructive primitive than a
whole-page write.

The page write surface in full: `POST /docs/{docId}/pages` (create),
`PUT /docs/{docId}/pages/{pageIdOrName}` (`updatePage`, which carries
`contentUpdate`), `DELETE` on the page itself, `DELETE .../content` as above,
`GET .../content` (`listPageContent`, synchronous), and
`POST .../export` + `GET .../export/{requestId}` for the asynchronous markdown
or HTML read.

# 7. Primary sources

| Source | Establishes |
|---|---|
| Local `coda-openapi.yaml` v1.6.0 / live `openapi.json` | Header absence on 429, dangling export enum, 400 schema split, no `maxItems` anywhere, `listPageContent`, `PageType`, 410 on export endpoints, rate-limit template placeholders |
| [Does Superhuman Docs have an API? (help centre)](https://help.superhuman.com/hc/en-us/articles/46210310809613) | 2 MB request cap, 85 KB row cap, **"Limits are attached to a user/IP"** |
| [Overview: Doc limits (help centre)](https://help.superhuman.com/hc/en-us/articles/46210176318477) | 125 MB API ceiling, 325 MB formula ceiling, rate-limit table (3/10 s variant) |
| [More powerful page endpoints in the Coda API](https://connect.superhuman.com/t/44103/1) — J. Goldman (Coda) | `downloadLink` "a few minutes" / file "a few days"; "poll until complete"; the 404 race; the round-trip fidelity warning |
| [C# to Superhuman Docs API timing issue?](https://connect.superhuman.com/t/54041) — E. Koleda | Snapshot architecture; `X-Coda-Doc-Version` retry advice **and** its footgun; `getMutationStatus` 404 sleep |
| [How much of the delay…](https://connect.superhuman.com/t/34463/7) — E. Koleda | `X-Coda-Doc-Version` is doc-wide, from any source; "doesn't get you new content any faster" |
| [Problem with coda API too many request…](https://connect.superhuman.com/t/47493) — E. Koleda | 3/10 s tightening; batching advice; real 429 body; sticky account-level 429s |
| [API rate limitations](https://connect.superhuman.com/t/42678/3) — E. Koleda | "don't rely on those numbers"; 30/60/120 s backoff suggestion |
| [Enable ChatGPT to Read/Write in Coda](https://connect.superhuman.com/t/49372/3) — E. Koleda | Export ID replication 404, "small delay and/or retry with backoff" |
| [PUT update row, size limit of 85Kb](https://connect.superhuman.com/t/x/44481/1) | Exact row-size 400 body; 44 KB wire → "87 KB" internal |
| [Cannot export page. Code "NoSuchKey"](https://connect.superhuman.com/t/44960/1) | XML failure shape of a dead download link |
| [Page-level attachments thread](https://connect.superhuman.com/t/57065/2) — E. Koleda | Markdown export omits attachments; HTML retains them |
| [Allow exporting Sync pages via API](https://connect.superhuman.com/t/55845/1) | Sync pages 400 on export |
| [listRows 504s](https://connect.superhuman.com/t/54136/3) — E. Koleda | Large-doc infrastructure limit |
| [Incremental re-export approach](https://connect.superhuman.com/t/50562/2) — E. Koleda | Staff-recommended `updatedAt` polling in place of sync tokens |
| `coda/packs-sdk` `helpers/external-api/coda.ts` | First-party: `pageToken` drops all other params |

Open questions are enumerated with runnable commands in
`docs/validation/2026-09-03-api-operational-probes.md`.
