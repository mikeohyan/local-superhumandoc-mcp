---
rfc: 0011
title: Split oversized batches rather than refusing them, and answer a size refusal by asking for less
status: Superseded
created: 2026-09-04
decided: 2026-09-05
supersedes:
superseded_by: 0014
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
five marked `[CHOSEN — no evidence, tune later]` and a sixth chosen on its
margin, and five passages in its size and paging sections instruct an
implementer rather than inform one — *"Chunk on both axes"*,
*"Reject an oversized single row before sending it"*, *"Treat a 400 matching
`entity too large` or `exceeds maximum size` as non-retryable and re-chunk"*,
*"continuation must key off `nextPageToken`"*, and a four-step page-size ladder
for 504s. Rule 9 below adopts a sixth, the instruction to surface the
document-size hypothesis. Those are decisions about what the client does, which
RFC 0003 places in an RFC and not in `docs/`.

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
in UTF-16 — is close, but it is no longer the best available account. Probe P7 ran
across nine samples and the counter turns out to be computable: internal size is
the value's UTF-8 byte length with **each newline charged twice**, matching every
sample to about one percent. Two things follow. The ratio is bounded above by
**2.0**, reached only by all-newline content — which explains the 2023 report
exactly, since 44 KB counted as 87 KB is newline-dense text sitting at that limit.
And non-ASCII is counted by decoded UTF-8 bytes rather than by the escaped wire
form, so a client measuring the serialised request overestimates a CJK row by up
to six times. The limit is therefore expressed in units the client *can* compute,
provided it measures the right thing.

**The refusal names a size and not a row, and this was tested rather than
assumed.** An `upsertRows` carrying three rows, the middle one oversized, was
refused with a message identical in form to the single-row case — it gives the
offending row's size and nothing else: no index, no position, no identifier. A
client that must find the bad row in a batch therefore has to subdivide and
resend, because the API will not say. The size is a partial handle, since a caller
knowing its own rows can sometimes match the figure back to one of them, but only
when the sizes differ and only under a ratio the paragraph above shows is unknown
for the content that matters.

**The refusal is a 400, not a 413, and it carries nothing structured to match
on.** A 2.5 MB write was answered `{"statusCode":400,"statusMessage":"Bad
Request","message":"request entity too large"}` — observed directly rather
than quoted from a report, and the bare `BadRequestError` shape with no
`codaType` and no `codaDetail`, where a schema-validation 400 on the same API
carries both. A size failure is therefore separable from any other malformed
request by its message text and by nothing else. That is not a shortcut this
RFC is taking; it is the only handle the API offers.

**Nothing in the specification bounds a batch** [SPEC-VERIFIED]. The whole
document contains zero `maxItems`, and `RowsUpsert.rows`, `RowsDelete.rowIds`
and `PageContent.content` carry no length constraint at all. The only datum in
either direction is a user describing *"a single write request … which updates
several hundred rows"* working in production. A third-party client asserts a
"500 rows per request" limit; `docs/validation/2026-09-03-cell-write-formats.md`
records that no vendor source supports it; it is one of two claims that put that
client on the do-not-cite list, the other being one staff contradict outright.

**A split write cannot be undone** [SPEC-VERIFIED]. The API has no transaction,
no rollback and no way to group writes: the only paths matching `batch` belong to
Packs ingestion, and `/mutationStatus/{requestId}` has no concept of undoing
anything. RFC 0005 established that the status schema is
`{"completed": bool, "warning": string?}` with no failure state at all. So a
batch that stops halfway leaves the document permanently half-written, and the
API will never say that anything failed.

**Time runs out before bytes do.** RFC 0010 rule 6 gives one deadline per tool
call and makes it the sole authority; the operating value is ninety seconds,
recorded in `docs/reference/api-operational-constants.md` and attributed there
to the `upstream-api` topic. RFC 0005 requires every write to poll
`getMutationStatus`. Probe P4 watched a mutation on a near-empty scratch
document flip to `completed` between t=16 s and t=18 s, and a later probe timed
the operation these rules actually govern: a single-row insert carrying a
fifteen-character value reported `completed` only between t=21.9 s and t=23.0 s,
with a six-row delete taking about twelve. **The row path is the slower one**, so
roughly three chunks of that shape exhaust the tool call rather than four. Whatever the byte caps say, the practical ceiling on a batch is the
deadline.

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

2. **Page-content writes are refused above the cap, never split.** The callers of
   `upsert_rows` and `delete_rows` have already partitioned their input: rule 6
   can report by position because the positions are the caller's own, and a row
   ID handed to `delete_rows` is a stronger handle still. The caller of
   `append_to_page` passes one string, so the client would have to invent the
   partition and then report progress against boundaries the caller never chose
   and cannot address — RFC 0005's write tools have no vocabulary for "resume
   from the third block". Markdown *could* be split at block boundaries; the
   claim is not that it is indivisible, but that a report about an invented
   partition is not something a caller can act on. Separately, `overwrite_page`
   and `replace_element` carry a replace semantic, where two calls leave only
   the second one's content, so for them splitting is not merely unreportable
   but wrong. So
   `create_page`, `append_to_page`, `replace_element` and `overwrite_page`
   reject a body above `MAX_PAGE_CONTENT_BYTES` before sending it, and say both
   the limit and how far over the body went. `replace_element` shares that cap
   despite being scoped to a single element, because it shares the endpoint; the
   cap will simply never bind on a paragraph.

3. **Two axes bound a chunk, and each is measured against the thing it
   protects.** Rows accumulate until either the count cap or a byte cap would be
   exceeded, whichever comes first. The two byte caps measure differently, and
   conflating them is the mistake this rule exists to prevent.
   `MAX_REQUEST_BYTES` guards the request, so it is measured on the serialised
   body actually being sent. `MAX_ROW_JSON_BYTES` guards the row, and the API
   counts a row as its values' UTF-8 length with newlines charged twice — not as
   wire bytes — so it is measured that way. A client that measured a row's
   escaped JSON instead would refuse non-Latin rows six times smaller than the
   API accepts. The count cap governs many small rows; the byte caps govern few
   large ones.
   A row whose own serialised size, multiplied by `ROW_INFLATION_FACTOR`,
   already exceeds `MAX_ROW_JSON_BYTES` is placed in a chunk by itself, so that
   a refusal names that row and costs only that row rather than the batch around
   it. An empty `rows` or `row_ids` list is an empty report and sends nothing.

4. **The pre-send estimate is advisory; the API's refusal is authoritative.**
   Because the 85 KB ceiling is measured in a representation this client cannot
   compute, the estimate exists to make the common case cheap, not to be
   correct. A **size refusal** — a 400 whose message matches `exceeds maximum
   size` or `entity too large` — is answered by halving the chunk and sending
   each half, recursively, until either the halves are accepted or a chunk of a
   single row is refused. Halves go sequentially, in the order the caller's rows
   arrived, so that what is reported unattempted at the deadline is a suffix of
   the caller's own input rather than an arbitrary subset. A single row cannot
   be split further, so the recursion terminates; that row is identified by
   having been alone in the refused request, which is the only way available,
   since a batch refusal was observed to name a size and not a row. Its refusal
   ends that branch and nothing else: the remaining chunks are still attempted.
   `update_row` is the degenerate case of all this, a chunk of one row with no
   halving to do, and it reports a size refusal the same way. Note what rule 3
   leaves for this rule to do: any row the estimate flags is already alone in
   its chunk, so a chunk that reaches the halving contains no row the estimate
   thought was too big. The case this handles is the estimate being wrong,
   which is the case it was written for.

5. **Re-chunking is not a replay, and RFC 0010's replay budget is untouched.**
   Rule 4 there permits at most one replay *per request*; a halved chunk is a
   different request with different content and carries its own budget like any
   other. What bounds the recursion is the single-row floor together with the
   deadline — not the replay counter, which never sees it.

6. **A split write reports every row's outcome and never a single verdict.**
   A rejected chunk applies nothing — tested, with two valid rows sent beside
   an oversized one and neither landing — so the unit a chunk reports on is the
   whole chunk, and per-row reporting is bookkeeping over chunk results rather
   than a claim the API supports row-level partial success.
   Four outcomes, not three: *applied* in RFC 0005's sense, *unknown* in RFC
   0010's, *refused* for a row the API answered with a size refusal, and *not
   attempted* — a state this RFC adds, for rows the deadline was reached before
   reaching. *Refused* is deliberately not folded into *unknown*. RFC 0010's
   class table already separates a definite server answer from a transmitted
   request whose fate is open; this rule carries that same distinction down to
   the row, because a report that calls a definite refusal unknown throws away
   the one thing the caller could have acted on. Outcomes are
   reported per row and keyed by the row's position in the caller's input,
   because a new row in an unkeyed upsert has no identifier of its own until the
   API assigns one. It does assign one promptly: `upsertRows` returns
   `addedRowIds` in the 202, in request order, so an *applied* row can be
   reported with its real id alongside its position, and `delete_rows` has the
   id from the start. Position is what makes the four sets addressable when
   there is no id yet, not a substitute for one where there is.
   There is no rollback to offer, so the only honest thing a partly-applied
   batch can do is say exactly how far it got. Reporting one aggregate result is
   wrong even when every chunk succeeded, because the caller then cannot
   distinguish that from the case where it did not.

7. **A chunk is started only while the deadline can afford one, and the
   estimate is explicit.** A mutation's completion time is not knowable in
   advance, so "afford" cannot mean a prediction: the client checks the
   remaining budget against `CHUNK_COST_ESTIMATE_S`, an operating value under
   rule 10, using the same `Deadline.can_afford` that RFC 0010 already applies
   to its replay delay and its throttle wait. Rows in chunks never started are
   reported *not attempted*. A chunk that is started and whose poll then reaches
   the deadline reports *unknown*, per RFC 0010. This check cannot pre-empt the
   throttle's own refusal and does not try to: the wait a full bucket imposes
   depends on bucket state the tool layer cannot see, so a chunk can pass this
   check and still be refused a slot. The throttle raises rather than reporting,
   so the tool catches that refusal and folds the rows it covers into *not
   attempted* rather than letting it escape — losing the whole account of a
   batch because its last chunk could not get a slot is the failure rule 6
   exists to prevent.

8. **Reads request a page size and never trust the count returned.**
   `nextPageToken` is the sole continuation authority; a short page is not
   evidence of the end, and a full page is not evidence of more. This restates a
   published constraint rather than choosing anything, and it is written down
   because the natural implementation gets it wrong.

9. **A 504 from `find_rows` restarts that listing at half the page size, down
   to a floor.** Restarting is not a preference: a `pageToken` ignores every
   parameter sent beside it, so a smaller `limit` cannot take effect part-way
   through. Each attempt is a fresh request rather than a replay. Halving is of
   the size the failing attempt used, rounded down, never below
   `LIST_PAGE_SIZE_FLOOR`; the floor size is itself attempted once, and only if
   that attempt also fails does the tool surface the failure. Rows from a pass a
   504 ended are discarded rather than merged into the next, because nothing
   establishes that two passes enumerate a table in the same order. Rows from
   the final pass — the one the deadline rather than a 504 cut short — are kept
   and reported: no response distrusted them, and discarding them would make
   "say how far it got" mean nothing after three attempts. When
   the **deadline** rather than the floor ends the ladder, the tool says so and
   says how far it got, rather than returning a short result that would read as
   the whole table — RFC 0005 has `find_rows` page "up to the caller's cap", and
   silently returning less than that cap without saying so would narrow the
   promise rather than keep it. On surfacing, the failure includes the
   document-size hypothesis — the vendor says the API is not supported for
   documents past 125 MB, and document size is not readable through the API — so
   the user can check the Statistics panel rather than reading the failure as a
   bug in this client.

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
   | `CHUNK_COST_ESTIMATE_S` | — | Rule 7's affordability check |

   Three notes on that table. `MAX_ROWS_PER_UPSERT` is currently recorded as
   "100 soft, 250 hard"; rule 1 removes the need for two numbers, because a
   batch above the cap is split rather than refused and there is nothing left
   for a hard limit to refuse. `MAX_ROW_IDS_PER_DELETE` shares a value with the
   unsourced third-party "500 rows per request" claim by coincidence — it is a
   chunk size set against the byte budget, not that claim adopted. And the last
   two rows are named here for the first time: `LIST_PAGE_SIZE_FLOOR` exists in
   `docs/` only as unmarked prose inside the very instruction passage this RFC
   objects to, and `CHUNK_COST_ESTIMATE_S` does not exist there at all. Both
   need a row and a confidence marker in that file before any code reads them,
   and neither has evidence behind it today.

   `ROW_INFLATION_FACTOR` is no longer a guess. Probe P7 measured the quantity it
   stands for and found it computable and bounded above by 2.0, so 2.2 is a
   ceiling rather than an estimate — roughly double what any realistic row needs.
   Rule 4 still tolerates it being wrong, which now costs a wasted round trip in
   a case that should be rare rather than routine.

**Not decided here.** Two things. The 125 MB document ceiling, past which the
vendor says the API is not supported, is a property of the document rather than
of a request; rule 9 surfaces it as a hypothesis and nothing here tries to
detect or manage it. And rule 9 is scoped to `find_rows` because that is the
endpoint the 504 evidence is about. `get_doc_overview` and `describe_table` also
page — `listPages`, `listTables`, `listColumns` — and could presumably 504 on a
large enough document, but nothing has been observed there, their natural page
sizes are not the row page size, and inventing a ladder for them from one
endpoint's evidence is the kind of extrapolation this RFC is trying to stop.

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
claims otherwise has no vendor source for it. Dropping the count cap would
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

Rejected because it does not *identify* on the case that matters. It terminates
fine — that is its pitch — but a single row above 85 KB stays whole in whichever
half contains it, so one halving reports a failure without ever naming the row,
and the caller is left holding exactly the information the API already gave
them. Recursion costs at most a logarithmic
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
for a number derived from one forum post. A 504 acquires a remedy of its own — ask for less — where
RFC 0010 could only classify it and decline to replay it. And the behavioural assertions
currently sitting in `docs/` acquire an owner, so that file goes back to
recording only what is true of the API.

**Makes hard.** Every batching write tool now reports four outcomes per row
rather than one result for the call, and its description must explain them —
more surface for a model to misread than a single success value. Chunking makes a partly-applied
document a routine outcome instead of an exceptional one, with no rollback to
offer. Rule 3's isolation is what keeps rule 4 cheap, and the cost
lands somewhere other than the recursion. A batch where many rows are
individually oversized never reaches the halving at all: each such row is already
alone in its chunk, so it costs one round trip, not a binary-tree search. Rule 4's
recursion is reserved for the case the estimate got wrong, which is rarer and
genuinely logarithmic in the chunk. What binds either case is arithmetic rather
than a rule, and the two paths are bound by different arithmetic. A chunk that is
*applied* costs a write plus a poll to completion, measured at twenty-three
seconds for a trivial row, so about three of those fit in the eighty seconds the
deadline leaves after its reserved tail. A chunk *refused* for size costs one round trip
and no poll at all, so what limits those is admission to the doc-content bucket at
two per ten seconds — about sixteen in the same budget. Rule 7 needs no special
case for this because it tests the time actually remaining rather than a running
tally: a fast refusal returns almost all of the budget, and the next check passes
again on its own. The honest description of a pathological batch is that it spends
its whole deadline discovering oversized rows one at a time and reports most of
itself *not attempted* — slow and truthful rather than fast and wrong. Rule 9 is worse: a 504 late in a large listing
discards everything paged so far, because the token cannot carry a new page
size, so the cost of shrinking grows with how far the listing got.

**Commits us to.** Measuring serialised bytes at the point of sending rather
than estimating from inputs, so the chunker cannot be a pure function of the
caller's rows. And carrying a message-text match — `exceeds maximum size`,
`entity too large` — as the discriminator for a size refusal, because the API
answers 400 for everything, was observed doing so for an oversized body, and has
never been seen to use 413. Reading that
message at all is a change to the shipped client: `UpstreamRefused` accepts a
`detail` argument but stores neither it nor the status as a value, and the
request chokepoint never passes one, so today a caller cannot see why a 400 came
back. `AuthFailure` already sets the precedent of keeping a status where callers
must branch on it. The match is also the most fragile thing in this RFC: the
vendor can reword an error without changing the specification digest RFC 0008
fingerprints, and nothing would catch it. A missed
match degrades to an ordinary 400 surfaced to the caller — tolerable rather than
dangerous, but it will look like a bug.

**Accepted risk, unresolved.** Six of the ten values in rule 10's table have
no empirical support: four of the five marked `[CHOSEN — no evidence]` in `docs/`,
plus `LIST_PAGE_SIZE_FLOOR` and `CHUNK_COST_ESTIMATE_S`, which this RFC names for the
first time — though `ROW_INFLATION_FACTOR` has left that list entirely, since P7
measured the quantity behind it across nine samples and bounded it at 2.0. No
probe
in the existing plan targets the row-count, delete-count or page-content caps at
all, so those would need new ones. Rule 4 is a real mitigation, but it means the
first oversized batch a user sends costs extra round trips to discover a limit
that could have been measured. Rule 9's ladder
is untested in a different way: no 504 has ever been observed from this client,
and both the halving and the floor are reasoning from a staff answer to somebody
else's problem.

## Implementation notes

Left empty at Proposed.
