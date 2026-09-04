---
rfc: 0011
title: Split oversized batches rather than refusing them, and answer a size refusal by asking for less
status: Proposed
created: 2026-09-04
decided:
supersedes:
superseded_by:
topic: request-sizing
commits: []
tags: [architecture, http-client, limits, tool-surface]
---

# RFC 0011 — Split oversized batches rather than refusing them, and answer a size refusal by asking for less

## Context

RFC 0005 specifies `upsert_rows`, `delete_rows` and four page-content writes
without saying how much a caller may hand them. RFC 0010 classified every
failure by whether the request was transmitted, and put a 400 and a 504 together
in its *Answered with a refusal* class marked **never replay** — deliberately,
because sending the identical request again is the one response that cannot
help. It then said where the rest belongs, in its Implementation notes:

> "**Not built here, by scope rather than omission:** … the 504 page-size ladder
> belongs to the wave that owns paging, and the transport only surfaces the 504"

Nothing owns that wave yet. The gap is visible in
`docs/reference/api-operational-constants.md`: eight constants sit in its §1.2,
six marked `[CHOSEN — no evidence, tune later]`, and five passages across the
file instruct an implementer rather than inform one — *"Chunk on both axes"*,
*"Reject an oversized single row before sending it"*, *"Treat a 400 matching
`entity too large` or `exceeds maximum size` as non-retryable and re-chunk"*,
*"continuation must key off `nextPageToken`"*, and a four-step page-size ladder
for 504s. Those are decisions about what the client does, which RFC 0003 places
in an RFC and not in `docs/`.

**Two ceilings are published, and both are real.** From the vendor's API FAQ
[STAFF]:

> **"Are there API size limits on requests?** The limit for requests is **2 MB**,
> but there is also a limit of **85 KB** for any given row."

**The 85 KB is not wire bytes, and this client cannot compute the number it does
measure.** A real error body, sent for a request whose `Content-Length` was
44 KB:

```json
{"statusCode":400,"statusMessage":"Bad Request",
 "message":"Row edit of size 87 KB exceeds maximum size of 85 KB."}
```

The ratio is roughly two, from a single forum-reported data point in which the
44 KB figure is the reporter's rather than a measurement of ours. A second report
shows the same shape at 89 KB but carries no wire figure, so it cannot
corroborate a ratio. The community explanation — that the ceiling counts the
row's size in the stored document, rich text held as JSON and probably tallied
in UTF-16 — is confirmed by nobody at Coda. Probe P7 exists to calibrate this and
has never run, because it needs a table with a writable column and the scratch
document has none. So the client is asked to stay under a limit expressed in
units it cannot see.

**That error body names a size and not a row.** It is the only size refusal ever
observed, and reading it is the whole of what is known: there is no field
identifying which row of a batch was at fault, and no vendor statement about
whether one exists.

**The refusal is a 400, not a 413** [real error paste]: *"I got a 400 error:
'request entity too large'"*. A forum search for `413` returns nothing. A size
failure is therefore indistinguishable by status code from any other malformed
request, and only the message text separates them.

**Nothing in the specification bounds a batch** [SPEC-VERIFIED]. The whole
document contains zero `maxItems`, and `RowsUpsert.rows`, `RowsDelete.rowIds`
and `PageContent.content` carry no length constraint at all. The only datum in
either direction is a user describing *"a single write request … which updates
several hundred rows"* working in production. A third-party client asserts a
"500 rows per request" limit; `docs/validation/2026-09-03-cell-write-formats.md`
records that no vendor source supports it, which is why that client is on the
do-not-cite list.

**A split write cannot be undone** [SPEC-VERIFIED]. The API has no transaction,
no rollback and no way to group writes: the only paths matching `batch` belong to
Packs ingestion, and `/mutationStatus/{requestId}` has no concept of undoing
anything. RFC 0005 established that the status schema is
`{"completed": bool, "warning": string?}` with no failure state at all. So a
batch that stops halfway leaves the document permanently half-written, and the
API will never say that anything failed.

**Time runs out before bytes do.** RFC 0010 rule 6 gives one deadline per tool
call and makes it the sole authority; RFC 0008 sets it at 90 seconds. RFC 0005
requires every write to poll `getMutationStatus`. Probe P4 watched a single
page-content mutation on a near-empty scratch document flip to `completed`
between t=16 s and t=18 s — a floor, measured on the cheapest document that
exists. Four chunks of that shape exhaust the tool call. Whatever the byte caps
say, the practical ceiling on a batch is the deadline.

**Reads have the same problem from the other side, plus one of their own.** The
specification forbids relying on page size:

> "**The maximum page size may change at any time, and may be different for
> different endpoints.** Please do not rely on it… If you pass a `limit`
> parameter that is larger than our maximum allowed limit, we will only return as
> many results as our maximum limit. You should look for the presence of the
> `nextPageToken` on the response to see if there are more results available,
> rather than relying on a result set that matches your provided limit."

And a page size, once chosen, cannot be changed part-way through a listing
[SPEC-VERIFIED], spec prose again:

> "You only need to pass the `pageToken` to get the next page of results… **Any
> other parameters provided alongside a `pageToken` will be ignored.**"

Coda's own `packs-sdk` enforces exactly that first-party, destructuring
`pageToken` out and dropping every other parameter. A continuation therefore
carries the original `limit` whether the client wants it or not.

That matters because `listRows` is the endpoint that fails first on large
documents, with a gateway timeout rather than a rate-limit error. Eric Koleda
(Coda), 2025-02-20, answering repeated 504s:

> "If this is a very large doc then it sounds likely that it's hitting some
> **infrastructure limit in our API** that's causing requests to fail. Have you
> looked into reducing the size or complexity of the doc?"

That is why RFC 0010 refuses to replay a 504. Waiting does not make an
over-expensive request cheaper; it times out again at the same page size.

**One apparent contradiction to settle.** RFC 0008 rule 3 has the client tell the
model that *"batching is the effective remedy"* when the rate-limit budget is
exhausted, and its Consequences call batching *"the intended answer rather than a
workaround"*. That is about request *count* against a replenishing budget — send
fifty rows in one call, not fifty calls. This RFC is about a single request being
too large to serve at all. They agree on the target and approach it from
opposite sides: use the largest request that stays under the ceiling. Nothing
here loosens RFC 0008's advice, and nothing there licenses an unbounded body.

## Decision

**When the API refuses a request for being too large, the remedy is a smaller
request, never a later one.** RFC 0010 decided how such a refusal is classified
and deferred the rest to this wave. Ten rules follow.

1. **A tool splits an oversized batch; it does not refuse one.** `upsert_rows`
   and `delete_rows` accept what the caller passes and divide it into chunks,
   each sent as its own request and polled as its own mutation. The alternative
   — erroring with "too many rows, try fewer" — pushes an API mechanic onto the
   model, which RFC 0004 says this server exists to absorb, and which RFC 0004
   already applies to pagination for the same reason.

2. **Page-content writes are refused above the cap, never split.** Rule 1
   applies to rows and row IDs, which are a set: the order chunks are sent in
   does not change what the table ends up holding. Page content is a sequence
   with a replace semantic, and neither property survives splitting. Two
   `replace` calls leave the page holding only the second half; two ordered
   `append` calls leave the page holding half a document if the second fails,
   and half a markdown document is not merely incomplete but malformed — an
   unclosed fence, a severed table. So `create_page`, `append_to_page`,
   `replace_element` and `overwrite_page` reject a body above
   `MAX_PAGE_CONTENT_BYTES` before sending it, and say what the limit is and
   how far over the body went.

3. **Two axes bound a chunk, and the byte axis is measured on the serialised
   request.** Rows accumulate until either the count cap or the byte cap would
   be exceeded, whichever comes first, with the byte figure taken from the JSON
   that will actually be sent rather than estimated from the caller's objects.
   The count cap governs many small rows; the byte cap governs few large ones.

4. **The pre-send estimate is advisory; the API's refusal is authoritative.**
   Because the 85 KB ceiling is measured in a representation this client cannot
   compute, the estimate exists to make the common case cheap, not to be
   correct. A **size refusal** — a 400 whose message matches `exceeds maximum
   size` or `entity too large` — is answered by halving the chunk and sending
   each half, recursively, until either the halves are accepted or a chunk of a
   single row is refused. A single row cannot be split further, so the recursion
   terminates, and the row named in the report is identified by being alone in
   the request that was refused rather than by anything the API says — which is
   the only way available, since the observed error names a size and not a row.

5. **Re-chunking is not a replay, and RFC 0010's replay budget is untouched.**
   Rule 4 there permits at most one replay *per request*; a halved chunk is a
   different request with different content and carries its own budget like any
   other. What bounds the recursion is the single-row floor together with the
   deadline — not the replay counter, which never sees it.

6. **A split write reports every chunk's outcome and never a single verdict.**
   Each chunk ends *applied*, *unknown*, or *not attempted*, in RFC 0010's
   sense, and the tool returns all three sets. There is no rollback to offer, so
   the only honest thing a partly-applied batch can do is say exactly how far it
   got. Reporting one aggregate result is wrong even when every chunk succeeded,
   because the caller then cannot distinguish that from the case where it did
   not.

7. **Chunking stops when the deadline cannot afford the next chunk**, not when a
   count is reached; the remaining rows are reported as *not attempted*. This is
   the guard RFC 0010 already puts on its replay delay and its throttle wait: a
   call that has run out of time never starts work it cannot finish.

8. **Reads request a page size and never trust the count returned.**
   `nextPageToken` is the sole continuation authority; a short page is not
   evidence of the end, and a full page is not evidence of more. This restates a
   published constraint rather than choosing anything, and it is written down
   because the natural implementation gets it wrong.

9. **A 504 from a listing restarts that listing at half the page size, down to a
   floor.** Restarting is not a preference: a `pageToken` ignores every parameter
   sent beside it, so a smaller `limit` cannot take effect part-way through.
   Each attempt is a fresh request rather than a replay, the ladder is bounded
   below by a floor and above by the deadline, and work already delivered to the
   caller from the abandoned pass is discarded rather than merged, because the
   two passes page the table differently. On reaching the floor the tool
   surfaces the failure and includes the document-size hypothesis — the vendor's
   125 MB API ceiling, which is not readable through the API — so the user can
   check the Statistics panel rather than reading the failure as a bug in this
   client.

10. **The operating values live in `docs/reference/api-operational-constants.md`
   and may be tuned against observation without superseding this RFC.** What is
   decided here is that each cap exists, which axis it bounds, and that it sits
   below the published ceiling rather than at it — the same delegation RFC 0008
   rule 1 makes for the rate-limit buckets and RFC 0010 rule 7 for its sticky-429
   threshold, for the same reason: the rule is the decision, the number is a
   calibration. The values at the time of writing:

   | Constant | Value | Bounds |
   |---|---|---|
   | `MAX_REQUEST_BYTES` | 1.5 MB | Serialised request body, against the published 2 MB |
   | `MAX_ROW_JSON_BYTES` | 38 KB | One row, against the published 85 KB internal |
   | `ROW_INFLATION_FACTOR` | 2.2 | Wire bytes to internal bytes; estimate only |
   | `MAX_ROWS_PER_UPSERT` | 100 | Rows per chunk |
   | `MAX_ROW_IDS_PER_DELETE` | 500 | Row IDs per chunk |
   | `MAX_PAGE_CONTENT_BYTES` | 700 KB | One page-content write |
   | `LIST_PAGE_SIZE` | 200 | Requested page size, never trusted |
   | `PAGE_CONTENT_LIST_LIMIT` | 500 | The spec's own maximum, not a choice |
   | `LIST_PAGE_SIZE_FLOOR` | 25 | Rule 9's ladder floor |

   Two notes on that table. `MAX_ROWS_PER_UPSERT` was previously recorded as
   "100 soft, 250 hard"; rule 1 removes the need for two numbers, because a
   batch above the cap is split rather than refused and there is nothing for a
   hard limit to refuse. And `MAX_ROW_IDS_PER_DELETE` shares a value with the
   fabricated third-party "500 rows per request" limit by coincidence — it is a
   chunk size chosen against the byte budget, not that claim adopted.

   `ROW_INFLATION_FACTOR` is the weakest entry and the one rule 4 is built to
   tolerate: its error costs a wasted round trip, never a wrong answer.

**Not decided here.** The 125 MB document ceiling, above which the API stops
serving a document at all, is a property of the document rather than of a
request. Rule 9 surfaces it as a hypothesis; nothing here tries to detect or
manage it.

## Alternatives considered

### Refuse an oversized batch instead of splitting it

Return an error naming the cap and let the model retry with fewer rows. It is
the smallest implementation, it makes partial application impossible inside one
tool call, and every call stays a single API request with a single outcome —
which genuinely simplifies the reporting rules.

Rejected because it moves a mechanic onto the model that the server exists to
absorb, and because it does not actually avoid partial application: a model told
"too many rows" will loop and send four calls itself, producing the same
half-written document with none of the reporting rule 6 provides. The failure
mode is identical and the honesty is worse.

### Bound chunks by bytes alone

The byte ceiling is the only request limit the vendor publishes, no row-count
limit exists anywhere in the specification, and the one third-party client that
claims otherwise was found to have invented it. Dropping the count cap would
remove an unowned constant rather than re-home it.

Rejected because the byte cap is computed from an estimate rule 4 already
concedes may be wrong, and because a thousand skinny rows is a problem the byte
cap does not see: it is one mutation, one blast radius, and one all-or-nothing
outcome. The count cap bounds the damage of a single chunk, which is a different
concern from bounding the request.

### Trust the estimate and pre-check only

Compute the estimated internal size, refuse anything above it before sending,
and never react to a 400. This is what the constants file's current wording
implies, and it keeps all behaviour local and testable without the network.

Rejected because a guessed factor is wrong in both directions and only one
direction is visible. Too high and it refuses rows the API would have taken,
with no way for the user to learn the limit was ours; too low and the 400
arrives anyway, unhandled. The API's message states the actual size and the
actual ceiling, which is strictly better information than the estimate.

### Halve once on a size refusal rather than recursively

Split the refused chunk in two, send both, and give up if either is refused
again. Bounded at one extra round trip, and simple to reason about.

Rejected because it does not terminate on the case that matters. A single row
above 85 KB stays whole in whichever half contains it, so one halving reports a
failure without ever identifying the row — and the caller is left with the
information the API already gave them. Recursion costs at most a logarithmic
number of round trips, is bounded by the deadline anyway under rule 7, and ends
holding the offending row.

### Retry a 504 in time rather than shrinking the request

Treat the gateway timeout as transient and back off, which is what a generic
HTTP client does by default.

Rejected on the vendor's own account of the failure: it is an infrastructure
limit reached by an expensive request, so the identical request at the identical
page size reaches it again. RFC 0010 already encodes this by classifying 504 as
answered-never-replay. Backing off would spend the tool call's whole deadline
arriving at the same failure. No evidence was found either way about what other
clients do here — `docs/` surveys six clients on export polling and none on 504
handling — so this rests on the staff statement rather than on prior art.

### Fold this into RFC 0008, or supersede RFC 0005

Rate limiting and request sizing are both "how much the client asks for at
once", and RFC 0008 already delegates tunables to `docs/` in the shape rule 10
uses. Alternatively, since the caps exist to serve `upsert_rows` and
`delete_rows`, the tool-surface RFC could own them.

Rejected on both counts, and the reasoning matters because both bodies are
frozen. RFC 0008's subject is *how often*, against a shared budget that
replenishes; a 429 refuses a perfectly well-formed request and waiting fixes it.
This RFC's subject is one request being too large to serve at all, which no
amount of waiting fixes — the two remedies are opposites, which is exactly why
RFC 0010 had to classify them into different buckets. And superseding RFC 0005
would retire a body whose element-scoped tool surface is entirely sound in order
to append a section about bytes. A new topic is the cheaper and more honest
structure.

### One chunk per tool call, with the model looping

Accept only what fits in one request, apply it, and return a continuation marker
the model passes back for the next slice. Bounded, transparent, one outcome per
call.

Rejected because it multiplies tool calls by the number of chunks, spends a
model turn on each, and makes the caller responsible for noticing it stopped
early — the same failure the refuse option has, dressed as a feature. Rule 6
delivers the same information in one call.

## Consequences

**Makes easy.** A caller hands a tool four hundred rows and gets a truthful
account of what happened to all four hundred. The client stops depending on a
guessed unit conversion for correctness: rule 4 demotes `ROW_INFLATION_FACTOR`
from a load-bearing constant to a latency optimisation, which is the right weight
for a number derived from one forum post. A 504 and a 429 stop being handled
alike, which they never should have been. And the behavioural assertions
currently sitting in `docs/` acquire an owner, so that file goes back to
recording only what is true of the API.

**Makes hard.** Every batching write tool now has three outcome sets to report
rather than one result, and its description must explain them — more surface for
a model to misread than a single success value. Chunking makes a partly-applied
document a routine outcome instead of an exceptional one, with no rollback to
offer. Rule 4's recursion turns one refused chunk into up to a logarithmic
number of extra requests, each spending a write-budget token against RFC 0008's
tightest bucket, so a pathological batch is slow in exactly the situation where
the user is already waiting. Rule 9 is worse: a 504 late in a large listing
discards everything paged so far, because the token cannot carry a new page
size, so the cost of shrinking grows with how far the listing got.

**Commits us to.** Measuring serialised bytes at the point of sending rather
than estimating from inputs, so the chunker cannot be a pure function of the
caller's rows. And carrying a message-text match — `exceeds maximum size`,
`entity too large` — as the discriminator for a size refusal, because the API
answers 400 for everything and does not use 413. That match is the most fragile
thing in this RFC: the vendor can reword an error without changing the
specification digest RFC 0008 fingerprints, and nothing would catch it. A missed
match degrades to an ordinary 400 surfaced to the caller — tolerable rather than
dangerous, but it will look like a bug.

**Accepted risk, unresolved.** Six of the nine values in rule 10's table have no
empirical support, and the one the design leans on least,
`ROW_INFLATION_FACTOR`, is the only one with even a single observation behind
it. Probe P7 would calibrate it and is blocked on a scratch table that does not
exist; no probe in the existing plan targets the row-count, delete-count or
page-content caps at all, so those would need new ones. Rule 4 is a real
mitigation, but it means the first oversized batch a user sends costs extra
round trips to discover a limit that could have been measured. Rule 9's ladder
is untested in a different way: no 504 has ever been observed from this client,
and both the halving and the floor are reasoning from a staff answer to somebody
else's problem.

## Implementation notes

Left empty at Proposed.
