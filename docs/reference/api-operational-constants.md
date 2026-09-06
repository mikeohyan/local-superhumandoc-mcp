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
| **[DECIDED]** | An operating value a decision owns, with the owning **topic** named in the justification column. Recorded here with its evidence |
| **[DECIDED — no evidence]** | Owned as above, but nothing measured or published supports the number itself |
| **[DECIDED — thin evidence]** | Owned as above, with a single observation behind it and margin added on top |

**Owned does not mean frozen here, and it does not mean well-founded.** Whether a
`[DECIDED]` value can be retuned by editing this file depends on the decision that
owns it. Four topics say in terms that their numbers may move against observation
without a new RFC — `upstream-api`, `request-sizing`, `failure-policy` and
`async-operations` — because what those decisions fix is the rule and not the
calibration. The `tool-surface` topic also owns a value here, but with weaker
language: it says its constants are "named constants so they can be tuned once
real documents are observed", which states the intent without granting the
licence outright. Where a
decision does *not* say either, the value changes only by superseding it — an
accepted RFC body is never amended in place. Either way the edit belongs to whoever
owns the topic, and the justification column is where to look before touching a
number.

The distinction matters most in the constants table. Several numbers there look
equally authoritative and are not: `EXPORT_LINK_TTL_S` is staff-quantified,
`EXPORT_INITIAL_SLEEP_S` is staff-motivated but arbitrary in magnitude, and
`LIST_PAGE_SIZE_FLOOR` is owned by a topic while resting on nothing measured at
all. Ownership settles who may change a value, never whether it is right.

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
| `RETRY_AFTER_TRUSTED` | `False` | [SPEC-VERIFIED] | No `Retry-After` or `X-RateLimit-*` header exists — see §2.2, so there is no signal to depend on; the `upstream-api` topic's retry rule is what says to parse one opportunistically if it ever appears and never require it. **Probe P6, 2026-09-04**: a live attempt to provoke a real 429 (the ethically-bounded maximum of 6 rapid export POSTs) did not succeed — all six returned 202. Whether a genuine 429 carries `Retry-After` remains empirically unanswered; this entry's basis is unchanged and uncontradicted |
| `RETRY_AFTER_CLAMP_S` | `(1.0, 60.0)` | [DECIDED] | Bounds an untrusted value if one ever appears; set by the `upstream-api` topic |
| `BACKOFF_BASE_S` | `2.0` | [DECIDED] | Staff suggest 30/60/120 s, which is intolerable inside a synchronous tool call. See note below; set by the `upstream-api` topic |
| `BACKOFF_FACTOR` | `3.0` | [DECIDED] | Yields 2 s, 6 s, 18 s, 54 s; set by the `upstream-api` topic |
| `BACKOFF_MAX_S` | `60.0` | [DECIDED] | Matches the Onyx connector's `max_delay`; set by the `upstream-api` topic |
| `BACKOFF_JITTER` | equal jitter — `delay/2 + uniform(0, delay/2)` | [DECIDED] | Equal jitter is named in the `upstream-api` topic's own retry rule, so the algorithm is decided rather than inferred; the survey is its evidence. Every surveyed client that backs off applies jitter; buckets are shared, so unjittered clients synchronise |
| `MAX_429_RETRIES_READ` | `3` | [DECIDED] | ≈26 s of waiting; set by the `upstream-api` topic |
| `MAX_429_RETRIES_WRITE` | `4` | [DECIDED] | ≈80 s of waiting; set by the `upstream-api` topic |
| `STICKY_429_THRESHOLD` | `3` consecutive 429s, `STICKY_429_WINDOW_S` `120.0` with zero successes | [DECIDED — thin evidence] | Sticky account-level 429s exist that backoff cannot clear — see §2.2. The threshold and window are set by the `failure-policy` topic, which supplied the trigger the `upstream-api` topic required and left unnumbered. Adopted from a staff report rather than measured, and tunable without superseding |
| `TOOL_CALL_DEADLINE_S` | `90.0` | [DECIDED] | Hard ceiling regardless of retries remaining. An MCP tool call has a human waiting on it. Constructed by the `failure-policy` topic, whose one-deadline-per-tool-call rule builds it and makes it the only authority, and which reserves a ten-second tail from it. This row previously named the `upstream-api` topic as its owner; that topic reuses the phrase "hard ceiling regardless of retries remaining" but states neither the constant's name nor the value 90, and defers the deadline itself |

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
| `MAX_REQUEST_BYTES` | `1_500_000` (1.5 MB) | [DECIDED] | Published cap is **2 MB**, staff-stated; the 25% headroom for encoding overhead is set by the `request-sizing` topic |
| `ROW_INFLATION_FACTOR` | `2.2` | [DECIDED] | Owned by the `request-sizing` topic and, unusually for this table, **measured**: nine samples on 2026-09-05. Internal size ≈ the value's UTF-8 byte length with each newline counted **twice**, accurate to ~1% across every shape tested. The ratio is therefore bounded above by **2.0** — the all-newline limit — and 2.2 is a safe ceiling that is roughly double what any realistic row needs. See §2.3 |
| `MAX_ROW_JSON_BYTES` | `38_000` (38 KB) | [DECIDED] | 38 KB × 2.2 ≈ 84 KB internal, under the published 85 KB row ceiling; set by the `request-sizing` topic. Two facts now sit against that derivation, both from §2.3 and neither settled here. The multiplier 2.2 is above the ratio's provable maximum of 2.0, so the derivation reserves headroom for a case that cannot occur. And the internal size is directly computable from the value — `utf8_len` plus one extra byte per newline, accurate to ~1% over nine samples — so a client need not multiply wire bytes by anything to know it. Which quantity this cap is denominated in, and whether a computed internal size replaces the estimate, is an open decision for the owning topic |
| `MAX_ROWS_PER_UPSERT` | `100` | [DECIDED] | **No published limit exists.** A user reports "several hundred rows" in one call working in production. One number, not the former soft/hard pair: the `request-sizing` topic splits an over-cap batch rather than refusing it, so there is nothing for a hard limit to refuse |
| `MAX_ROW_IDS_PER_DELETE` | `500` | [DECIDED] | Row IDs are ~12 bytes, so the byte cap never binds; larger batches consume fewer doc-content-write tokens. Set by the `request-sizing` topic. The matching value in a third-party client is a coincidence, not a source — see the do-not-cite note in the cell-write findings |
| `MAX_PAGE_CONTENT_BYTES` | `700_000` (700 KB) | [DECIDED] | 700 KB × 2.2 ≈ 1.5 MB internal. No published page-content limit exists. Set by the `request-sizing` topic, which refuses an over-cap page body rather than splitting it |
| `LIST_PAGE_SIZE` | `200` requested | [DECIDED] | Named in the `request-sizing` topic's own table of operating values, as the page size to request and never to trust; `codaio` self-caps GET `limit` at 200, which is its evidence. The real max is deliberately undocumented and **silently clamped**, so the number requested is never the number to trust — see §2.3 |
| `LIST_PAGE_SIZE_FLOOR` | `25` | [DECIDED — no evidence] | The floor of the page-size ladder the `request-sizing` topic runs on a 504. No 504 has ever been observed from this client, so both the ladder and its floor are reasoning from a staff answer to another user's problem |
| `CHUNK_COST_ESTIMATE_S` | `30.0` | [DECIDED — thin evidence] | What the `request-sizing` topic charges against the tool-call deadline before starting another chunk. This row previously cited "a sample of one"; §1.3 now carries four observations, and they are two-sided. Inserts: ~20 s (probe P8, 2026-09-06) and a ~21.9–23.0 s figure whose source is not locatable. Deletes: ~10 s (P8) and a ~12 s figure from the same unlocatable run. Deletes therefore run at roughly half an insert's cost, and one constant covers both, so a delete-only batch is charged as though it were an insert. Whether the two operations get separate estimates is an open question for the owning topic |
| `OVERVIEW_INLINE_COLUMNS_MAX_TABLES` | `8` | [DECIDED] | Recorded 2026-09-06. At or below eight tables, a document overview also returns every table's column schema; above it, columns are omitted and the caller is directed to fetch one table's schema on its own. The number is stated in the `tool-surface` topic's own body, which calls it a judgement rather than a measurement and a named constant to be tuned once real documents are observed — but it had no row here, so the one value that topic owns in this file was the one value not written down. It bounds cost: the call is one page list, one table list, and one column list per table, so leaving it unbounded spends a large share of the read budget on orientation. Note the weaker licence recorded in the legend: the `tool-surface` topic states the intent to tune without granting it outright |
| `PAGE_CONTENT_LIST_LIMIT` | `500` | [SPEC-VERIFIED] | `listPageContent` uses a distinct `pageContentLimit` param with `maximum: 500`, `default: 50` |

The two byte caps do not measure the same thing, which is the fact that makes them
easy to misuse. `MAX_REQUEST_BYTES` is about the request, so it is a count of the
bytes actually put on the wire. `MAX_ROW_JSON_BYTES` is about the row, and §2.3
shows the server counts a row as its values' UTF-8 length with newlines charged
twice — a quantity that can be six times smaller than the same row's escaped JSON.
100 rows at 38 KB would be 3.8 MB, so on either measure the byte axis binds for
large rows and the count axis for small ones. What a client does with these — split
or refuse, and which measure applies where — is set by the `request-sizing` topic.

**A batch refusal does not identify the offending row** [measured 2026-09-04]. An
`upsertRows` carrying three rows, the middle one oversized, was refused with a
message identical in form to the single-row case: it gives a size and nothing else.
This entry previously asserted the same thing without a citation; it now has one.

## 1.3 Asynchronous mutation polling

**Row writes are slower to complete than page-content writes** [probe P8,
2026-09-06]. Polling at 2-second intervals, a single-row insert reported
`completed: true` at about 20 seconds and a single-row delete at about 10 seconds.
This is the sourced measurement, and it is the one to reason from.

An earlier pair of figures dated 2026-09-04 — a single-row `upsertRows` carrying a
fifteen-character value completing between t=21.9 s and t=23.0 s, and a six-row
`deleteRows` at about twelve seconds — is **recorded here without a locatable
source** [flagged 2026-09-06]. No probe in `docs/validation/` contains those
timings, that row shape, or that batch size: P4 is a page-content append rather
than a row write, and P7 measured row size without recording completion times.
The figures agree with P8 in shape and magnitude and so are kept, but anything
load-bearing should cite P8 instead. Probe P4's 16–18 s figure was a
page-content append, so the row path is the slower of the two, not a proxy for it
— any budget reasoning that assumed otherwise is optimistic.
Note also that the status body was `{"completed":false}` with **no `warning` key at
all**, where P4 recorded `{"completed": false, "warning": null}`; a client must
treat the field as absent rather than null. Every intermediate poll in the
2026-09-06 run confirmed the same thing — no `warning` key on any
`{"completed":false}` response — so the field's absence, as distinct from null, is
now observed across two independent runs rather than one.


| Constant | Value | Marker | Justification |
|---|---|---|---|
| `MUTATION_INITIAL_SLEEP_S` | `3.0` | [DECIDED — no evidence] | Staff confirm the *need* for a first-poll delay — "add a short sleep, **maybe a few seconds**, before the first time you call that endpoint" (see §2.1) — but nothing sources the specific 3.0 s. Owned by the `async-operations` topic, which fixes that the delay exists and leaves the number tunable |
| `MUTATION_POLL_INTERVAL_S` | `2.0` | [DECIDED — no evidence] | Status reads are the cheapest bucket. Owned by the `async-operations` topic |
| `MUTATION_POLL_BACKOFF` | ×1.5, capped at `MUTATION_POLL_MAX_INTERVAL_S = 15.0` | [DECIDED — no evidence] | Added 2026-09-06. The `async-operations` topic states that the two poll loops share one shape and differ in their numbers, but only the export half of that shape had been written down: the mutation half named an interval and no schedule for it to follow, so the loop could not be built from the tables alone. Mirrored from the export row, which is the same topic's own expression of the shared shape. Nothing measured supports ×1.5 or 15.0 on the mutation path specifically |
| `MUTATION_404_GRACE_S` | `30.0` | [DECIDED — no evidence] | A 404 before this is replication lag, not a missing mutation. Raised from `15.0` on 2026-09-06: row writes are not observed to complete until ~20–23 s (see the note opening this section), so a 15 s window declared a 404 terminal *before the write it was watching was ever expected to finish*, which falls the opposite way from the owning topic's own instruction that these windows be set generously because the error they guard against is misreporting a write that succeeded. 30 s clears the observed completion time and stays well inside `MUTATION_DEADLINE_S`. **Probe P4, 2026-09-04**: two independent write→poll sequences on a near-empty scratch doc never produced a 404, including at t=0 immediately after the write — the endpoint consistently returned 200 with `completed:false` instead. `completed` flipped to `true` between t=16s and t=18s. The 404-replication race did not reproduce on this doc; the observed bottleneck was completion latency (~18s), not a 404 window. Owned by the `async-operations` topic, which sets which way this window's error falls — see the note after §1.4 |
| `MUTATION_DEADLINE_S` | `60.0` | [DECIDED — no evidence] | Then return "queued, not confirmed" — never an error, since the API offers no failure state for a mutation. Staff describe the underlying delay as "30 seconds to a few minutes" and architectural. Owned by the `async-operations` topic |

The endpoint is at the **root**: `GET /mutationStatus/{requestId}`, *not*
`/docs/{docId}/mutationStatus/{requestId}` [SPEC-VERIFIED]. At least one public
client uses the wrong path. Status information is *"not guaranteed to be available
for more than one day after the mutation was completed"* [SPEC-VERIFIED].

## 1.4 Export

| Constant | Value | Marker | Justification |
|---|---|---|---|
| `EXPORT_BUCKET` | `BUCKET_WRITE` | [DECIDED — thin evidence] | **Not** the doc-content bucket. Genuinely undocumented; two independent client authors assume the tightest bucket, and **probe P6, 2026-09-04 refuted that**: six export POSTs in under 2 seconds all returned 202 with zero 429s, inconsistent with 3/10 s or 5/10 s, and served by a distinct `api-doc` backend pod class. A six-request burst is still within the general write bucket's published 10/6 s, so that bucket is not excluded — P6 narrows the question rather than answering it. Owned by the `async-operations` topic, which adopts `BUCKET_WRITE` as the conservative reading of what survives. See §2.5 |
| `EXPORT_INITIAL_SLEEP_S` | `2.0` | [DECIDED — no evidence] | Staff confirm the *need* — *"Simply wait a second and retry"* (see §2.5) — but nothing sources the specific 2.0 s. Owned by the `async-operations` topic, on the same footing as its mutation counterpart |
| `EXPORT_POLL_INTERVAL_S` | `2.0` | [DECIDED — no evidence] | Owned by the `async-operations` topic. Status GET is read-bucket; at 2 s this uses ~1.5% of it. Matches the two best-behaved clients |
| `EXPORT_POLL_BACKOFF` | ×1.5, capped at `EXPORT_POLL_MAX_INTERVAL_S = 15.0` | [DECIDED — no evidence] | The schedule the poll interval follows; owned by the `async-operations` topic, which decides the loop shape rather than only its interval. `ofloveandhate/codaio` uses 1 s × 1.5 → 15 s |
| `EXPORT_DEADLINE_S` | `90.0` | [DECIDED — no evidence] | Owned by the `async-operations` topic. No source quantifies export duration. `codaio` allows 300 s; 90 s fits a synchronous tool call. **Inert as written** [noted 2026-09-06]: it equals `TOOL_CALL_DEADLINE_S` while the `failure-policy` topic makes that the only authority and reserves a ten-second tail from it, leaving an eighty-second working budget. A subordinate ceiling equal to the outer total can never be the one that fires — the outer deadline always cuts the loop first. Whether it is retired or given a value below the working budget is an open question for its owning topic; this row records only that at 90.0 it has no effect |
| `EXPORT_404_GRACE_S` | `20.0` | [DECIDED — no evidence] | A 404 within this window is replication lag. Probe P5 was to calibrate it and never produced a 404. Owned by the `async-operations` topic — see the note after §1.4 on why this window carries more weight than its marker suggests |
| `EXPORT_LINK_TTL_S` | `300` (5 min) | **[STAFF], confirmed [SPEC-VERIFIED] 2026-09-04** | *"the downloadLink returned by the API expires after only a few minutes"*; the sibling Admin API endpoint publishes exactly 5 minutes. **Directly observed by probe P5b**: link served content at t=300s, failed by t=330s; the signed URL's own `X-Amz-Expires=300` query parameter corroborates this independent of staff prose — see §2.5 |
| `EXPORT_FILE_TTL` | ~a few days | [STAFF] | *"the exported file remains live for a few days"* — the file outlives the link, which is why re-polling mints a fresh URL |
| `EXPORT_MAX_LINK_REFRESH` | `2` | [DECIDED — no evidence] | How many times a fresh link is minted after a download fails its check. Owned by the `async-operations` topic |
| `EXPORT_CONCURRENCY_PER_PAGE` | `1` | [DECIDED] | The blob key is `DOC_EXPORT_RENDERING/{pageId}/{docId}` — keyed by page and doc, **not** by request ID, so concurrent exports of one page collide on one object. Owned by the `async-operations` topic, which treats serialising per page as a correctness requirement rather than pacing |
| `EXPORT_CONCURRENCY_GLOBAL` | `3` | [DECIDED — no evidence] | Concurrency limits are entirely undocumented. `professor-eggs/coda-md-export` throttles to avoid "45+ concurrent exports at once". Owned by the `async-operations` topic |

### What the poll-loop windows are for

Both tables above describe one loop shape, and the `async-operations` topic owns
all of it: wait, poll on a backing-off interval, stop on a terminal answer or a
deadline. The mutation and export loops differ in their numbers, not their
structure.

The two grace windows are the ones worth flagging. They are not pacing: they
decide how long a 404 from a status endpoint is read as replication lag before
being treated as terminal, which is a correctness question. Set too short, a
write that actually succeeded is reported as failed or unknown; set too long, a
genuinely dead request is reported slowly. The `async-operations` topic decides
that the error falls the second way, on the grounds that answering slowly is the
cheaper mistake — but the numbers themselves rest on nothing. No 404 has ever
been returned by either status endpoint across probes P4, P5 and P8, so these
windows bound patience rather than track a measured lag, and they could be wrong
in either direction without any evidence here showing it.

One overlap is worth recording rather than smoothing over. The `tool-surface`
topic's Consequences also gesture at "the poll intervals and deadlines recorded
in `docs/reference/`" as tunable constants. The `async-operations` topic is the
later and far more specific claim — it takes the whole loop as its subject, where
the earlier remark was a passing aside in a decision about which tools exist — so
the poll-loop constants are attributed to it here. Nothing is reversed by that;
the two decisions do not disagree about any value.

The 404 case reads at first like a conflict with the `failure-policy` topic,
whose classification table places a 404 under "answered with a refusal — never
replay", where a status poll plainly does keep asking. It is not a conflict. That
topic's own Context already singles this case out, saying a 404 on a status poll
is routinely not an absence at all because status ids are not immediately
replicated across servers, and its implementation notes hand the poll loops to
the tool layer in terms. So the table governs the individual poll request, which
is an idempotent read rather than a replay of the operation being watched, and
the loop around it is deliberately left to whichever decision claims it. What
remains genuinely undecided is only the window's length.

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

**The 400's shape varies by endpoint in both directions, and the spec does not
predict it** [SPEC-VERIFIED, corrected by live observation 2026-09-04, sharpened
2026-09-06]. The spec declares two 400
schemas: `BadRequestError` (bare `{statusCode, statusMessage, message}`) and
`BadRequestWithValidationErrors` (adds `codaDetail.validationErrors`). The latter is
referenced by 49 operations — **all of them Packs, Pack-logs, or agent-logs
endpoints**; not one docs, rows, pages, tables, or columns operation declares it.

That reading of the spec once supported a blanket claim here that a staleness 400
and a malformed-request 400 are byte-identical on every endpoint this project
touches. **Probe P3 refuted it.** `listPageContent`
(`GET /docs/{docId}/pages/{pageId}/content`) returns a
`codaType`/`codaDetail.issues`-bearing 400 for a real schema violation (tested:
`contentFormat=bogusFormat`), despite declaring no such schema — a discriminator
present where the spec promises none. **Probe P3's control, run 2026-09-06 against
`listRows` with the documented-unsatisfiable combination
`sortBy=natural&visibleOnly=false`, went the other way**: it returned a **bare**
`{statusCode, statusMessage, message}` 400 with **no** discriminator, byte-identical
with and without the `X-Coda-Doc-Version: latest` header. An invalid sync token on
the same endpoint likewise came back bare (`"Invalid pageToken."`). So the
discriminator's presence is not something the spec's declared schema settles either
way: it can appear where none is promised (`listPageContent`), and it can also stay
absent exactly where none is promised (`listRows`) — neither presence nor absence
can be predicted from the spec at all, only measured per operation. The `listRows`
message text was, however, long and specific — *"Natural sorting is only available
for visible rows..."* — which is a weaker and different kind of signal than a
structured field: distinctive prose can help a human reading logs, but it is not
something a client can safely match on the way it would a `codaType`.

Separately, and more consequentially:
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
will occur that the limiter did not predict**. This is why the `upstream-api` topic
requires that error text surfaced to the model say so, rather than presenting the
limiter as authoritative.

Spec prose, verbatim: *"Limits apply per-user across all endpoints that share the
same limit and across all docs."* [SPEC-VERIFIED]

**Sticky 429s exist and backoff does not clear them** [STAFF]. In
<https://connect.superhuman.com/t/x/47493>, a user disabled all API traffic for 30
minutes, then made **one** write to a **fresh** doc and still received a 429,
repeatedly; reads were unaffected. Eric Koleda: *"1 request per 10 seconds should be
under the limit, so I'm not sure why you are still getting 429 errors."* It required
an engineer to touch the account (`/47493/10`: *"the engineering fix has
successfully stopped the 429 errors"*). No amount of client-side waiting resolved
it. The `failure-policy` topic is what requires detecting this state and failing
fast with a distinct message rather than exhausting the deadline in a loop; the
threshold and window it sets for that are in §1.1.

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

**An oversized body returns 400, not 413** — **directly observed 2026-09-04**,
upgrading this from a forum report to a first-party measurement. A 2,500,102-byte
`PUT /docs/{docId}/pages/{pageId}` carrying a `contentUpdate` in `append` mode was
answered in 0.25 s with HTTP 400 and this body, complete and verbatim:

```json
{"statusCode":400,"statusMessage":"Bad Request","message":"request entity too large"}
```

Response headers carried `x-coda-server: api-doc`, and `curl` reported the full
2.5 MB as uploaded, so the refusal comes from the application after the body is
transmitted rather than from the CDN edge. The message text matches the 2023 forum
paste (<https://connect.superhuman.com/t/x/10826/1>) word for word. A forum search
for `413` still returns zero posts.

**The size refusal carries no structured discriminator** [observed 2026-09-04].
The body is the bare `{statusCode, statusMessage, message}` shape with **no
`codaType` and no `codaDetail`** — unlike the schema-validation 400 that probe P3
recorded on `listPageContent`, which carries `codaType:
"RequestSchemaValidationFailed"` and `codaDetail.issues`. So the two 400 shapes are
distinguishable from each other, but a size refusal is separable from a plain
`BadRequestError` **only by its message text**. Nothing structured exists to match
on. This was tested because a client that must react to a size refusal needs a
discriminator, and a field would have been far more durable than a substring.

**What the 85 KB actually counts** [measured 2026-09-05, nine samples]. The
counter is not the request's wire bytes and not a mystery. Every sample fits
`internal ≈ utf8_len(value) + newline_count`, i.e. the value's UTF-8 length with
each newline charged twice, reported in units of 1024 bytes:

| Value | UTF-8 bytes | Newlines | Predicted | Reported |
|---|---|---|---|---|
| 133,000 × `y` | 133,000 | 0 | 129.9 KB | **130 KB** |
| 120,000 chars, newline every 10th | 120,000 | 12,000 | 128.9 KB | **129 KB** |
| 120,000 chars, newline every 2nd | 120,000 | 60,000 | 175.8 KB | **176 KB** |
| 100,000 × `中` | 300,000 | 0 | 293.0 KB | **294 KB** |
| 75,000 × emoji | 300,000 | 0 | 293.0 KB | **294 KB** |
| 84,160 × `y` + 4,000 trailing newlines | 88,160 | 4,000 | 90.0 KB | **91 KB** |

Three consequences follow, and all three matter to a client.

**The maximum ratio is 2.0, at all-newline content.** Nothing can exceed it, which
retires the question of how conservative `ROW_INFLATION_FACTOR` needs to be. It
also explains the 2023 forum report exactly — a 44 KB body counted as 87 KB is
newline-dense content sitting at that limit, which is what a markdown list or a
pasted document looks like.

**Non-ASCII is counted by decoded UTF-8 bytes, not by the escaped wire form.** The
CJK and emoji rows above were 600,065 and 900,065 bytes on the wire, because
`json.dumps` escapes non-ASCII to `\uXXXX`; both were counted as 294 KB. A client
that measures the serialised request therefore **overestimates by up to 6×** for
non-Latin text and will split or refuse rows the API would have taken.

**Spreading a value across columns costs nothing extra.** 66 KB in each of two
columns was counted as 129 KB, the same as 132 KB in one.

The trailing-newline sample is the one that missed, by 1 KB (1.1%): its newlines
were one contiguous block rather than interspersed, so a run of empty paragraphs
may cost slightly more than two bytes each. Treat the formula as an estimate good
to about a percent, not an exact reproduction of Coda's accounting.

**The row ceiling's refusal shape** [observed 2026-09-04, probe P7]. Provoked
against a real table row, complete and verbatim:

```json
{"statusCode":400,"statusMessage":"Bad Request","message":"Row edit of size 131 KB exceeds maximum size of 85 KB."}
```

Same bare shape, no `codaType`, no `codaDetail`. So **both** message patterns a
client would match on — `entity too large` for the request ceiling and
`exceeds maximum size` for the row ceiling — are now first-party observations, and
neither carries anything structured to key off instead.

**A batch refusal does not say which row was at fault** [observed 2026-09-04]. An
`upsertRows` carrying three rows, the middle one oversized, was refused with a
message byte-identical in form to the single-row case: it names the offending row's
*size* and nothing else — no index, no position, no identifier. This settles the
question the §1.2 note asserted without a citation, and it settles it the same way:
a client that must locate the bad row in a batch has to subdivide and resend,
because the API will not tell it.

The size figure is a partial handle — a caller that knows its own rows' sizes can
sometimes match `131 KB` back to one of them — but only when the sizes are distinct
and only under a known inflation ratio, which the entry above shows is not known for
rich text. It is not a substitute for subdividing.

**A refused request applies nothing** [observed 2026-09-04]. In the same three-row
test the two valid rows did **not** land: a read-back after the mutation window
showed neither present. So an `upsertRows` call is all-or-nothing when it is
rejected at validation time, which is the case a chunking client depends on. This
says nothing about a failure *after* a 202, which the API has no way to report at
all.

**`upsertRows` returns the ids it assigned** [SPEC-adjacent, observed 2026-09-04].
The 202 body is `{"requestId": ..., "addedRowIds": [...]}`, so a newly inserted row
is not anonymous — the caller gets its id back immediately, in request order, before
the mutation completes.

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

So a short page is not evidence that a listing has ended, and a full page is not
evidence that it has not: `nextPageToken` is the only signal separating them. How a
client is required to use it is set by the `request-sizing` topic.

**Docs over 125 MB lose API access entirely** [help centre]:

> "On all plan types, docs larger than 125 MB may not be able to access the
> Superhuman Docs API… **developer APIs will not be supported past this limit.**…
> This doc is over 125 MB. Developer API calls or use as a new Cross-doc sync source
> doc are not supported at this size."

The 125 MB excludes file attachments. Separately, HTML exports cannot exceed
125 MB (does not apply to PDF or plain text), and all docs are subject to a 325 MB
formula-calculation limit above which calculations are disabled. Doc size is not
readable through the API; the document's own Statistics panel is where a user can
see it. Persistent 4xx or timeouts across multiple endpoints are the symptom this
would produce. When a client raises that as a hypothesis is set by the
`request-sizing` topic.

## 2.4 Sync tokens — the least-exercised surface in the API

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

**Deleted rows: structurally cannot be reported, and this is now also directly
observed.** [SPEC-VERIFIED, confirmed by live observation 2026-09-06] `RowList.items`
is `Row[]`; `Row` is `additionalProperties: false` with
`required: [id, type, href, name, index, browserLink, createdAt, updatedAt, values]`.
There is no `deleted`/`tombstone` field, and a deleted row could not supply
`values`, `index`, or `browserLink`. **A deleted row therefore cannot appear in a
sync delta at all — the schema has no field that could represent one.** **Probe
P8, 2026-09-06**, confirmed this live rather than by schema-reasoning alone: a row
was inserted, a sync token minted, the row deleted, and the delta read 60 seconds
later returned `count: 0` with an empty `ids` array — no mention of the deleted row
anywhere in the response. What a client should do about that is the open decision
recorded at the end of this section.

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

**No RFC decides sync tokens.** The facts above point clearly at leaving them
alone in a first version, and this file previously stated that as a recommended
posture — which is a choice, and choices do not belong here. It is recorded
instead as an **open decision with no owner**: nothing in `_rfc/` currently says
whether `sync_token` is exposed on any tool, whether `nextSyncToken` is ignored
for control flow, or whether the alternatives staff suggest (`listRows` with
`query`, `updatedAt` for coarse change detection, client-side content hashing)
are adopted in its place. The tool surface as decided contains no sync-token
tool, so the question is currently moot in practice and would become live again
only if one were proposed.

The reasons, in order of weight: you cannot tell a caller whether a delta is
complete, because deletion reporting is structurally impossible; you cannot detect
token invalidation, because the 400 is undiagnosable; the calculated-column
semantics are unknown and the nearest documented analogue explicitly fails; and with
zero users and zero staff posts in the forum's entire history, there is no chance of
discovering you are wrong before your users do. An MCP tool that silently returns an
incomplete delta to a language model is worse than one that does not offer the
feature.

Should it ever be proposed, these are the constraints the facts above impose,
and the shape of the decision an RFC would have to make: the token is opaque, so
nothing can be inferred from its contents; filters appear to be baked in at
creation time, so sending it alongside other query parameters has undefined
meaning; a non-2xx on a tokened request is undiagnosable, so the only sound
reading is that the token is invalid and a full resync is needed; and deletions
are structurally unreportable, so no result derived from one can claim to be a
complete delta. Those are consequences of the evidence, not a chosen design.

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

**A successful download is gzip-encoded, not plain text** [SPEC-VERIFIED by live
probe, 2026-09-06]. The response behind a live `downloadLink` carried
`Content-Encoding: gzip` and `Content-Type: text/plain`, with `Content-Length`
reporting the **compressed** size — 761 bytes for a 1,424-byte markdown export. A
client that saves the response body without decompressing it gets gzip bytes, not
the exported text. This was observed directly: a first run wrote the raw bytes to
a file and `file(1)` identified it as "gzip compressed data". A gzip body is
therefore a third possible shape behind the link, alongside the valid content it
appears to be and the XML error document above — which of the three a given
response is stays unresolved until it is decompressed.

**What separates the three on the wire** [assembled 2026-09-06 from the shapes
above; no new probe]. The status code does not: the `NoSuchKey` document was
reported under a `200` and the `AccessDenied` document was measured under a `403`,
so a `200` alone distinguishes nothing. The decisive bytes are the body's own
prefix. Gzip content begins `1f 8b`; both error documents begin `<?xml` and carry
a `<Code>` element naming which failure it is. Note that these two facts are not
visible at the same time through an ordinary HTTP client: `httpx2` selects a
decoder from `Content-Encoding` automatically for `.content`, `.text` and
`.json()`, so by the time a body is read the gzip framing is gone and what remains
is either the exported markdown or the XML error document. Only `iter_raw` /
`aiter_raw` yield the undecoded bytes. What a client should check, and at which of
those two layers, is a decision this file does not make.

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

Export is the most intricate behaviour on this surface. It is owned by the
`async-operations` topic, which decides the poll loop, the concurrency limits and
the download rules. This section records what the endpoints do and what has been
observed of them; it does not restate that decision, and it does not say what the
client does. See the note at the end of §3.2 for the one thing still open.

## 3.1 `downloadLink` and `error` are the only guaranteed signals; `status` is not

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

**The observation does not make the field dependable.** It is typed as an
unconstrained string by the API's own schema, both of its spec examples are wrong,
and the spec's code samples disagree with its own enum — so a single confirmed
observation says what one run returned, not what the contract permits. The
structurally guaranteed signals are different: `downloadLink` is present exactly
when the export has produced a file, and `error` is present exactly when it has
failed. Those two are unambiguous where `status` is not, and they cost nothing to
read. Note also that `complete` and `completed` both appear across the spec's own
material, so any code that does compare the string faces both.

## 3.2 What the endpoints do

Facts, in the order a caller meets them.

1. **Only canvas pages export.** `syncPage` returns 400; `embed` is untested. The
   page's `contentType` is readable in advance, so the refusal is predictable
   rather than something that must be discovered by trying.
2. **The two formats carry different content.** `markdown` drops page-level
   attachments; `html` retains them [STAFF, §2.5]. Nothing else distinguishes them
   for this purpose, so attachments are the only axis on which the choice matters.
3. **`POST /docs/{docId}/pages/{pageIdOrName}/export` returns 202** with `id` and
   `href`. Which rate-limit bucket it draws on is **not established** — probe P6
   ruled out the doc-content rates without identifying what does apply (§1.4,
   §2.5).
4. **An immediate first status GET races replication.** Staff prescribe a delay
   before it — *"Simply wait a second and retry"* [STAFF, §2.5]. The magnitude is
   unsourced.
5. **Status GETs are read-bucket**, the cheapest of the four.
6. **A 404 from the status endpoint is ambiguous.** Early, it means the export ID
   has not replicated to the pod serving the request. Later, it is
   indistinguishable from a request that never existed. Nothing in the response
   separates the two cases; only elapsed time does, and no measurement establishes
   where the boundary falls — probe P5 was to calibrate this and has not.
7. **410 Gone is a distinct, declared outcome.** The status endpoint declares
   `410 — "The resource has been deleted."` [SPEC-VERIFIED], which `listRows` does
   not. It is consistent with the export request having aged out, the exported file
   living only "a few days" [STAFF]. Unlike a 404 it is unambiguous: the resource
   existed and is gone, so no amount of further polling will produce it.
8. **`error`, when present, carries the API's own failure text.** There is no
   structured failure code alongside it.
9. **`downloadLink` expires in ~5 minutes; the file behind it lives for days**
   (§1.4, both measured). A link is therefore stale long before its content is, and
   the spec sanctions re-minting: *"Call this method again to get a fresh link."*
10. **A dead link returns S3-style XML with a 200 or a 403**, not an empty
    response — probe P5b observed `403` with `<Code>AccessDenied</Code>`, where the
    previously documented shape was `200` with `<Code>NoSuchKey</Code>`. Both are
    `<?xml`-prefixed, which is the one property common to every observed form.
    This matters because such a body is a plausible-looking string that is not page
    content. A live link is a third shape again, not a second: the body is
    gzip-compressed bytes served with `Content-Type: text/plain` (§2.5), which is
    neither the XML above nor readable text until it is decompressed.
11. **Concurrent exports of one page collide.** The blob key is
    `DOC_EXPORT_RENDERING/{pageId}/{docId}` — keyed by page and doc, **not** by
    request ID — so two in-flight exports of the same page contend for one object.
12. **Export is single-page.** There is no recursive or bulk export endpoint;
    `listPages` and `Page.children` are the only way to enumerate subpages. At the
    POST rates in play, walking 50 pages is a multi-minute operation.

### What is decided, and the one thing that is not

Every item above is a fact about the API. The `async-operations` topic turns them
into behaviour: it charges the export POST to a bucket, serialises exports per
page and caps them overall, sets the first-poll delay and the 404 tolerance,
requires the downloaded body to be checked before it is returned, and bounds how
many times a link is re-minted. The values are in §1.4 and may be tuned there.

Two of those deserve a pointer back to the evidence. The per-page serialisation
follows from item 11 rather than from judgement — the blob key omits the request
id, so it is a correctness constraint. And the export bucket in item 3 is still
unmeasured: `BUCKET_WRITE` is adopted as the conservative reading of what P6 left
standing, not as a finding, and settling it properly would mean provoking a 429,
which this project does not do.

The one genuinely open question is item 12. Nothing decides whether a tool walks
subpages at all, because no such tool exists — the `tool-surface` topic's decided
surface reads one page. A capped recursion was once described in this file as
settled behaviour and was not; the cap has since been retired rather than
adopted, on the grounds that inventing the tool from a budget decision would be
deciding the surface from the wrong end. If a bulk read is ever wanted, it is a
`tool-surface` question first.

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

**What follows from that.** Staff attribute the failure to the request's cost at
the page size asked for, not to a transient condition, so waiting does not change
the outcome — the same request at the same `limit` times out again. A smaller
`limit` is the only lever the caller has, and a `pageToken` cannot carry one,
because the API ignores every parameter sent beside it (§2.4). A smaller page size
can therefore only take effect by starting the listing over.

Those are the facts. The behaviour they imply — that a 504 restarts the listing at
a halved page size down to `LIST_PAGE_SIZE_FLOOR`, which pass's rows survive, and
that the failure surfaced at the floor carries the 125 MB doc-size hypothesis
(§2.3) — is set by the `request-sizing` topic.

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

**The single-row read exists** [SPEC-VERIFIED by live probe, 2026-09-06].
`GET /docs/{docId}/tables/{tableIdOrName}/rows/{rowIdOrName}` returned `200`
with the row against the scratch document. This is worth recording because the
path had never appeared in any excerpt here: it was inferred by symmetry with
the `PUT` on the same path, and an inference is not a fact until something
checks it.

The response body carries `id`, `type`, `href`, `name`, `index`, `createdAt`,
`updatedAt`, `browserLink`, and `values`. **`values` is keyed by column ID, not
by column name** — the observed keys look like `c-euWseAF6J-`. A caller that
wants cells keyed by a name a human or a model would recognise has to resolve
those IDs against the table's column schema itself; the row endpoint does not
do it. Note that `name` on the row is the row's own display name, which is not
a cell value and is not a column.

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

The vendor's own MCP server offers table creation and comments as a content
channel [SPEC-VERIFIED against that server's published tool list at
<https://coda.io/resources/mcp/tools-and-endpoints>, which names `table_create`
and lists `comments` among `content_read`'s content types; the same page is
quoted in `docs/validation/2026-09-03-markdown-fidelity-tests.md`]. It has
additionally been described here as offering atomic multi-operation editing with
rollback — **[unattributed]**, since that page documents `content_modify`'s
element-anchored operations without saying anything about atomicity, and no other
source has been recorded for it. Either way these are capabilities of that server
rather than of this REST surface, so a client built on v1 cannot reach them by
trying harder.

**Present, and easy to miss.** `DELETE /docs/{docId}/pages/{pageIdOrName}/content`
— `deletePageContent`, *"Delete content from a page. You can delete specific
elements by providing their IDs, or delete all content from the page."* Clearing
a page is therefore a first-class operation with its own endpoint, **not** a
whole-page `replace` carrying an empty payload. The same endpoint also deletes
named elements by ID, which is a narrower destructive primitive than a
whole-page write.

**What `whoami` reveals about a token** [SPEC-VERIFIED and live-confirmed,
2026-09-04]. `GET /whoami` returns a `User` whose properties are `href`,
`loginId`, `name`, `pictureLink`, `scoped`, `tokenName`, `type`, `workspace`.
Two matter for configuration:

- `scoped` — boolean, *"True if the token used to make this request has
  restricted/scoped access to the API."*
- `tokenName` — the name given to the token at creation.

Confirmed live on 2026-09-04 with this project's own document-scoped token:
`scoped: true`, `tokenName: "MCP Validator"`. The boolean says only *that* the
token is restricted — nothing reports which document or which operations, and
there is no endpoint anywhere in the surface for creating or reading token
restrictions (no path matches `token`, `apikey`, `credential` or `scope`). So
the extent of a restriction is discoverable only by making a call and reading a
403.

**Content format enums** [SPEC-VERIFIED, 2026-09-04]. Three distinct enums, and
conflating them is easy:

- `PageContentFormat` — `["html", "markdown"]`, *"Supported content types for
  page (canvas) content."* This is the **write** side: the format field on the
  content a page is created or updated with. Both members are legal on write.
- `PageContentOutputFormat` — `["html", "markdown"]`, the formats an **export**
  may be requested in.
- `PageContentItemContentFormat` — `["plainText"]`, one member only. This is the
  **synchronous** `listPageContent` read, which is why markdown cannot be read
  back without the asynchronous export.

**202 responses that carry no `requestId`** [SPEC-VERIFIED, 2026-09-04]. Fourteen
operations answer 202. Eleven return a schema carrying `requestId` and are
therefore pollable through `/mutationStatus/{requestId}`: `createPage`,
`updatePage`, `deletePage`, `deletePageContent`, `upsertRows`, `deleteRows`,
`updateRow`, `deleteRow`, `pushButton`, `publishDoc`, `triggerWebhookAutomation`.

Three do **not**: `addCustomDocDomain`, `deleteDoc`, and — the one that matters
here — `beginPageContentExport`. The export's 202 returns an id polled on its own
path; the specification names that path parameter `requestId`, while the response
body field carrying the value is `id` and is also reachable as `href`. It is not
a mutation id and `/mutationStatus/` will not accept it. A blanket "if 202 then
poll `getMutationStatus`" rule therefore breaks on the export kickoff, which is
the most-used write in a read path.

Note that `deleteDoc` mutates and yet carries no `requestId`, so the general
statement that *every* mutating endpoint returns one is too broad. It holds for
every endpoint the tool surface actually calls, which is what the design depends
on, but not for the API as a whole.

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
