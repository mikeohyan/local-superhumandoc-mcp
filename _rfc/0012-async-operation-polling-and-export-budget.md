---
rfc: 0012
title: Poll asynchronous operations on one bounded loop, and give export its own budget
status: Accepted
created: 2026-09-06
decided: 2026-09-06
supersedes:
superseded_by:
topic: async-operations
commits: []
tags: [export, polling, concurrency]
---

# RFC 0012 — Poll asynchronous operations on one bounded loop, and give export its own budget

## Context

Two things on this API finish after the response that started them has already
returned. Every mutating endpoint answers `202` with a `requestId`, and the write
is observed by polling `GET /mutationStatus/{requestId}`. Page export is longer:
a `POST` returns `202` with an id, a status `GET` eventually yields a
`downloadLink` or an `error`, and the content is then fetched from a signed URL
on a different host.

Three decisions touch this territory and none of them owns it.

RFC 0008 sets four rate-limit buckets, but which one an export `POST` draws on
was never established. Probe P6 fired six export requests inside two seconds and
got six `202`s with no `429`, which rules out both published doc-content rates
and shows export served by a visibly distinct backend pod class — but a
six-request burst also fits inside the general write bucket, so P6 narrows the
question without answering it.

RFC 0010 classifies transport failures and bounds every retry by one deadline.
Its table places `404` under "answered with a refusal — never replay". Its
Context, though, already says the opposite thing about this specific case: *"A
404 on a status poll is routinely not an absence at all, because status IDs are
'not immediately replicated to all of our servers'."* And its Implementation
notes hand the loops away explicitly — *"the export and mutation poll loops are
tool-layer, so their subordination to the tool-call deadline is decided here but
exercised there."* So the reconciliation exists inside that frozen body; what is
missing is a decision about the loop rather than the request.

RFC 0005 delegates "the poll intervals and deadlines recorded in `docs/`". Read
at face value that reaches an interval between polls and an absolute ceiling, and
stops short of two things it plainly did not consider: the delay before the
*first* poll, and the window inside which a `404` is tolerated. RFC 0011 scoped
itself away from anything but `find_rows` paging.

The result is a gap with a shape. Nine operating constants have no owner —
`EXPORT_BUCKET`, `EXPORT_CONCURRENCY_PER_PAGE`, `EXPORT_CONCURRENCY_GLOBAL`,
`EXPORT_MAX_PAGES_PER_CALL`, `EXPORT_MAX_LINK_REFRESH`, and the four poll-loop
windows `MUTATION_INITIAL_SLEEP_S`, `MUTATION_404_GRACE_S`,
`EXPORT_INITIAL_SLEEP_S` and `EXPORT_404_GRACE_S`. Until recently
`docs/reference/api-operational-constants.md` also carried twelve numbered rules
telling the client how to drive the export state machine, with no topic cited for
any of them; one of those rules described a capped recursive multi-page export,
a capability RFC 0005's decided surface does not contain. Those rules have been
stripped back to facts, which is what makes this decision necessary rather than
merely tidy: the behaviour they described is no longer written down anywhere.

Two of the unowned windows are not pacing. `MUTATION_404_GRACE_S` and
`EXPORT_404_GRACE_S` decide how long a `404` reads as replication lag before
being treated as terminal, and that is a correctness question. Set too short, a
write that actually succeeded is reported as failed or unknown. Set too long, a
dead request is reported slowly. Nothing has decided which way that error should
fall.

What evidence exists is thin and mostly negative. Across probes P4, P5 and P8 no
status poll has ever returned a `404` — the replication race the grace windows
exist for has not once reproduced. What P4 and P8 did measure is completion
latency: a row insert reported complete after roughly 20 seconds, a delete after
roughly 10, with every intermediate poll returning `{"completed": false}` and no
`warning` key present at all. P5b measured the download link expiring between
300 and 330 seconds while the file behind it lives for days. And a 2026-09-06 run
found the download served `Content-Encoding: gzip` with `Content-Type:
text/plain`, so an undecompressed body is a third possible shape alongside real
content and the XML a dead link returns.

## Decision

**1. A poll is not a retry, and the two are governed separately.** RFC 0010
classifies what happened to a request that failed. A poll loop asks a different
question — has this finished? — and each poll is a fresh idempotent `GET` whose
own transport failures that RFC still classifies. What this RFC decides is the
loop around them: when it starts, how often it asks, when it stops, and what it
concludes. Re-reading a status endpoint is never a replay of the operation being
watched, so nothing here weakens RFC 0010's replay rules.

**2. Both asynchronous operations are polled on one shape.** Wait
`INITIAL_SLEEP`, then poll at `POLL_INTERVAL`, backing off by `POLL_BACKOFF` to
`POLL_MAX_INTERVAL`, until a terminal answer, the operation's own deadline, or
the tool-call deadline — whichever comes first. Mutation and export differ in
their constants and in what counts as terminal, not in their structure. One shape
is chosen so that a change of pacing policy is made once.

**3. A status `404` is "not yet" inside the grace window and terminal outside
it.** Both status endpoints address a resource whose creating request already
returned `202`, so the resource is known to have been accepted. A `404` therefore
means either that it has not replicated to the pod serving this read, or that it
never existed — and nothing in the response distinguishes them. Elapsed time
since the `202` is the only discriminator available, so it is the one used. This
is the tool-layer exercise of the case RFC 0010's Context already identified.

**4. The grace windows bound patience, not a measured lag.** No `404` has ever
been observed from either status endpoint. The windows are therefore not
calibrated against anything; they are a decision about how long to keep asking
for a resource that may never appear. They are set generously, because the error
they guard against is misreporting a write that succeeded, and that error is
worse than answering slowly.

**5. Exhausting a deadline is reported as unknown, never as failure.** A mutation
that has not completed by `MUTATION_DEADLINE_S` has not failed — the API offers
no failure state for a mutation at all, only `completed` and an optional
`warning`. The honest answer is that the write was accepted and its outcome is
unconfirmed, which is RFC 0010's *transmitted, outcome unknown* reported through
a tool rather than a transport.

**6. Concurrent exports of one page are serialised; exports overall are
capped.** The export blob key is `DOC_EXPORT_RENDERING/{pageId}/{docId}` — keyed
by page and document, not by request id — so two in-flight exports of one page
contend for a single object. Serialising per `(docId, pageId)` is a correctness
requirement rather than politeness. A separate global cap,
`EXPORT_CONCURRENCY_GLOBAL`, bounds how much export traffic the client generates
at once, since concurrency limits are entirely undocumented upstream.

**7. An export `POST` is charged to the write bucket until something measures
otherwise.** P6 excluded the doc-content rates without identifying what does
apply. `BUCKET_WRITE` is the most conservative reading that survives the
evidence. The status `GET` is charged to the read bucket. This is deliberately a
placeholder with an owner, replacing a placeholder with none.

**8. The download is a separate hop and does not follow the API's rules.** The
signed URL is on a different host, carries no bearer token, and sits outside
every rate bucket. It is fetched with decompression enabled, because the body is
served `Content-Encoding: gzip`. It is never cached: the link expires in about
five minutes while the file behind it lives for days, so a stored link is the
most likely cause of a later inexplicable failure, and the spec sanctions
re-minting — *"Call this method again to get a fresh link."* A body is checked
before being returned, because a dead link answers with S3-style XML under a
`200` or a `403` rather than with an error the transport would notice; a failed
check re-mints up to `EXPORT_MAX_LINK_REFRESH` times.

**9. Bulk and recursive export are out of scope.** RFC 0005's surface exports one
page. The capped-recursion rule that used to live in `docs/` described a tool
that does not exist, and reinstating it here would be deciding a tool surface
from the wrong end. If a bulk read is ever wanted it is a `tool-surface` question
first and a budget question second. `EXPORT_MAX_PAGES_PER_CALL` is accordingly
**retired rather than owned** — it is deleted from the constants file, not
adopted.

**10. The operating values live in `docs/reference/api-operational-constants.md`
and may be tuned against observation without superseding this RFC.** What is
decided here is that each window exists, which failure it guards against, and
which way its error falls. The numbers themselves rest on very little and are
expected to move.

| Constant | Value | Basis |
|---|---|---|
| `MUTATION_INITIAL_SLEEP_S` | `3.0` | Staff prescribe a short delay; the magnitude is unsourced |
| `MUTATION_POLL_INTERVAL_S` | `2.0` | Status reads are the cheapest bucket |
| `MUTATION_404_GRACE_S` | `15.0` | Never observed; bounds patience |
| `MUTATION_DEADLINE_S` | `60.0` | Measured completions were 10-20 s; margin for the "few minutes" staff describe |
| `EXPORT_INITIAL_SLEEP_S` | `2.0` | Staff: *"Simply wait a second and retry"*; magnitude unsourced |
| `EXPORT_POLL_INTERVAL_S` | `2.0` | Matches the two best-behaved surveyed clients |
| `EXPORT_POLL_BACKOFF` | ×1.5 to `15.0` | Follows `ofloveandhate/codaio` |
| `EXPORT_404_GRACE_S` | `20.0` | Never observed; bounds patience |
| `EXPORT_DEADLINE_S` | `90.0` | No source quantifies export duration |
| `EXPORT_BUCKET` | `BUCKET_WRITE` | Conservative reading of what P6 left standing |
| `EXPORT_CONCURRENCY_PER_PAGE` | `1` | Forced by the blob key |
| `EXPORT_CONCURRENCY_GLOBAL` | `3` | Undocumented upstream; a judgement |
| `EXPORT_MAX_LINK_REFRESH` | `2` | A judgement |

## Alternatives considered

### Fold this into `failure-policy`

The 404 question sits closest to RFC 0010, which already names the case in its
Context. Rejected on two grounds. That body is frozen, so reaching it means a
supersede of a shipped decision in order to add something it deliberately
deferred — its Implementation notes hand the poll loops away in terms. And the
subjects genuinely differ: RFC 0010 answers "what happened to this request?",
while a poll loop answers "has this operation finished?". Merging them would put
export concurrency and blob-key collisions inside a transport-classification
decision, where nobody would look for them.

### Fold this into `tool-surface`

RFC 0005 already gestures at the poll constants, and export exists only to serve
`read_page`. Rejected because that body is frozen too, and because it decides
*which tools exist and what they refuse* — a different question from how much
concurrent work the client permits itself. Putting a global export concurrency
cap in the tool-surface decision would also mean any change to pacing reopens the
tool list.

### Extend `upstream-api` to cover the export bucket

The bucket question is a rate-limit question, and RFC 0008 owns rate limits.
Rejected because only one of the nine unowned constants is a bucket. Splitting
this decision so that `EXPORT_BUCKET` lives with the rate limits and the eight
others live elsewhere would put the two halves of one subject in two places, and
the bucket is unresolved precisely because export behaves unlike the endpoints
RFC 0008 measured.

### Scope this to export alone, leaving the mutation windows unowned

Tempting, since export is the larger and messier half. Rejected because the four
unowned windows split two-and-two across the loops, and both loops have the same
shape and the same replication-lag problem. An export-only decision would leave
`MUTATION_404_GRACE_S` — a correctness-bearing number — orphaned for no reason
other than which endpoint it names.

### Treat a status `404` as terminal immediately

This is the strict reading of RFC 0010's classification table, and it has the
virtue of needing no new number. Rejected because staff state directly that
status ids are not immediately replicated, so the strict reading converts a
routine timing artefact into a reported failure — and the failure it reports is
the worst possible one, telling a model that a write which actually succeeded did
not.

### Cache the download link for the life of the exported file

The file lives for days and the export is expensive, so caching the link looks
like an obvious saving. Rejected because the link expires in about five minutes,
measured. A cached link fails long after the code that stored it ran, and it
fails by returning XML under a `200`, which is the hardest possible shape to
diagnose.

### Let each tool own its own poll loop

Simplest to write, and each tool knows its own timing best. Rejected because the
two loops would drift apart on windows that encode a correctness decision, and
because the 404 question would then be answered once per tool rather than once.

### Adopt the capped recursive export the constants file described

`EXPORT_MAX_PAGES_PER_CALL` already had a value, so adopting it is nearly free.
Rejected because it decides a tool that does not exist. RFC 0005's surface reads
one page; a recursive read is a new tool with its own refusal semantics and its
own truncation reporting, and inventing it inside a budget RFC would be deciding
the tool surface sideways.

## Consequences

**Makes easy.** Both asynchronous operations behave the same way, so a reader who
understands one understands the other, and a change of pacing policy is made once
rather than twice. The nine unowned constants acquire an owner and a stated
purpose, which means the next session can tune them without wondering whether it
is allowed to. The export subsystem stops being the one part of the client whose
behaviour is described nowhere. And the 404 question gets a single answer that
says which way its error falls, rather than two tools guessing separately.

**Makes hard.** Serialising per page makes a bulk read of one page's siblings no
faster than serial, and the global cap means a model asking for several pages at
once waits. Reporting a deadline exhaustion as unknown rather than failure is
honest but unsatisfying: the model is told the write may or may not have landed,
and has no way to find out other than reading the document back. And the grace
windows add latency to the one case they exist for — a genuinely absent resource
is now reported slowly rather than immediately.

**Commits us to.** A poll-loop shape shared by both operations, which is
expensive to unpick if the two turn out to need different structures rather than
different numbers. A conservative export bucket that will over-throttle if export
really does have its own generous limit — P6 hints it might. And the position
that a status 404 is ambiguous, which would need revisiting if the API ever grew
a way to distinguish "not replicated" from "never existed".

**Accepted risk.** The two grace windows are the weakest numbers in this
document. They guard a failure mode that has never once been observed across
three probe campaigns, which means they could be badly wrong in either direction
and nothing in the evidence would show it. A window that is too short will
misreport successful writes under exactly the conditions least likely to appear
in testing — a loaded upstream, an unlucky pod. This is accepted because the
alternative is not a better number but no decision at all, and because the
failure is at least biased in the safe direction: too long merely wastes time.

The export bucket carries a similar risk in the other direction. If export draws
on a limit more generous than `BUCKET_WRITE`, the client will be slower than it
needs to be, and nothing will signal that — under-using a budget is invisible.
Only a measurement will settle it, and P6 established that measuring it means
provoking a 429, which this project does not do.

## Implementation notes

Left empty at Proposed.
