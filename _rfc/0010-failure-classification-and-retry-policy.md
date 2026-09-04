---
rfc: 0010
title: Classify transport failures by whether the request was transmitted, and bound every retry by one deadline
status: Proposed
created: 2026-09-04
decided:
supersedes:
superseded_by:
topic: failure-policy
commits: []
tags: [architecture, http-client, reliability, error-handling]
---

# RFC 0010 — Classify transport failures by whether the request was transmitted, and bound every retry by one deadline

## Context

RFC 0005 ends its rule on retry safety with a sentence that hands the numbers
somewhere else: *"The retry budget and backoff are RFC 0008's."* RFC 0008's rule
3 does not have them. That rule opens *"A 429 is retried, on a bounded budget,
under a hard deadline"*, and its reasoning is explicitly about refusal: *"Because
a 429 is refused before execution, replaying it is safe on every method."*
Nothing in RFC 0008 mentions a timeout, a dropped connection, or a 5xx. So the
one case RFC 0005 actually cares about — a request that was accepted and then
lost, where an unkeyed upsert would duplicate rows on replay — is deferred to a
decision that was never made. Both bodies are frozen, so neither can be amended
to close it.

Three smaller holes sit beside that one. RFC 0008 requires detecting
*"consecutive 429s [that] indicate an account-level limit that backoff cannot
clear"*, but the
only numbers for that trigger are marked `[STAFF]` in
`docs/reference/api-operational-constants.md`, not `[DECIDED]` — a named
requirement with no decided threshold, on a table where eleven neighbouring
retry constants are marked as owned by the `upstream-api` topic. No per-request
HTTP timeout is decided anywhere; `TOOL_CALL_DEADLINE_S` bounds a whole tool
call, not a socket read, and an implementer cannot construct a client without
inventing one. And RFC 0006 shipped with a documented hole pointing here: its
startup line omits the token name and `scoped` flag because those come from
`GET /whoami`, which needs a client that did not exist when it shipped.

What makes this hard is that the failures are not one kind of thing. The
evidence separates them. A 429 is refused before execution and replaying it is
safe on any method. A read timeout leaves the client unable to tell whether the
mutation ran. A 504 from `listRows` is neither: staff attribute it to *"some
infrastructure limit"*, and the recorded response is *"reduce `limit` and
retry"*, with the explicit warning that *"backing off in time does not help —
the request is too expensive at that page size and will time out again"*. A 404
on a status poll is routinely not an absence at all, because status IDs are
*"not immediately replicated to all of our servers"*. And a client that treats
all of these as one retryable blur has a documented way to fail badly: a
multi-day API degradation in March 2026, about which the evidence file warns
that *"a client that retries forever on 5xx will burn a user's whole session"*.

## Decision

Failures are classified by **whether the request was transmitted**, not by what
came back, and every retry in a tool call is bounded by that call's single
deadline.

1. **Four classes, decided by what the server did.**

   | Class | Members | Replay |
   |---|---|---|
   | Refused before execution | 429; connect-phase failure (`ConnectTimeout`, `ConnectError`) | 429: any method. Connect-phase: SAFE only |
   | Transmitted, outcome unknown | `ReadTimeout`, mid-response drop (`RemoteProtocolError`, `ReadError`), 500, 502, 503 | SAFE only |
   | Answered with a refusal | 404, 504, every other 4xx, and any 3xx | Never |
   | Auth | 401, 403 | Never |

   A 2xx whose body cannot be parsed is `ResponseUnusable`. It sits orthogonal
   to the axis above — transmitted *and* answered, failing on content — and is
   named because the table would otherwise imply a 2xx always succeeds. On the
   export kickoff it is unrecoverable: that 202 is one of three that carry no
   `requestId`, so there is nothing to poll.

   A 3xx is surfaced, never followed. The base URL is pinned by RFC 0008; a
   redirect away from it means the pin is wrong, and following it quietly would
   defeat the pin.

2. **A connect-phase failure does not override an UNSAFE declaration.** It is
   believed replay-safe, and the honest reason it is not treated as such is that
   nothing in this repository establishes when `httpx2` raises these exceptions
   relative to bytes reaching the socket. A pooled connection the peer closed
   silently could in principle surface this way after a partial write, and
   replaying `push_button` or `overwrite_page` on a belief is the duplication
   RFC 0005's allowlist exists to prevent. What the class earns is wording, not
   a replay: an UNSAFE call failing at connect reports that the request most
   likely never reached the server, rather than claiming its outcome is unknown.
   A probe could settle this and promote the class; until one does, the
   conservative rule stands.

3. **Replay safety is declared by the caller and never inferred.** `SAFE` is
   GETs and upserts carrying `key_columns` — RFC 0005's allowlist exactly,
   neither widened nor narrowed. `UNSAFE` is the default, so a call site that
   forgets gets the conservative answer and arming the dangerous direction
   requires someone to type it.

4. **At most one replay per request, never per tool call.** `read_page` issues a
   metadata GET, an export POST, many poll GETs and a download; one transient
   blip on the first must not strip tolerance from the twenty that follow. What
   bounds the total is the deadline, not the count. The replay waits on RFC
   0008's existing equal-jitter formula at a one-second base, giving 0.5–1.0 s.
   There is no second jitter scheme.

5. **Per-request timeouts are 5 s connect and 30 s read**, constructed as
   `httpx2.Timeout(30.0, connect=5.0)`. The read value follows from arithmetic
   against decided numbers rather than from any property of the upstream
   gateway, whose own threshold is nowhere recorded: `(5+30) + 1 + (5+30)` is
   66 s, inside the 80 s that rule 6 leaves, so one replay fits; a second would
   need 97 s and does not. Whether the client's timeout or a gateway 504 fires
   first does not matter, because both land in classes that are never replayed
   on an UNSAFE call.

6. **One deadline per tool call, and it is the only authority.** A `Deadline` is
   constructed once per invocation at `TOOL_CALL_DEADLINE_S` and threaded into
   every request. `EXPORT_DEADLINE_S` and `MUTATION_DEADLINE_S` become
   subordinate ceilings that may consume what remains and never extend it; each
   was sized assuming it had the whole budget, and two 90-second budgets drawn
   on one clock is one budget with a bug. Subordination must not change what a
   user is told: a mutation poll cut short by the outer deadline still reports
   *"queued, not confirmed"*, never an error, exactly as it does at its own.
   Ten seconds are reserved for the terminal fetch of an already-earned result,
   which carries its own single retry independent of the API-host budget —
   justified not by convenience but by fact, since the download host is not the
   API host, needs no `Authorization` header, and does not consume the
   rate-limit budget, so the machinery protecting a bucket and an auth scheme
   does not apply to it.

7. **A sticky 429 is three consecutive with no intervening success inside 120
   seconds.** This supplies the trigger RFC 0008 required and left unnumbered.
   It is adopted from a staff report rather than measured, and like RFC 0008's
   buckets it may be tuned against observation without superseding this RFC.
   Composition is explicit: a 429 does not reset the replay budget, and neither
   budget may outlive the deadline.

8. **The client raises typed exceptions; the tool boundary translates them into
   `ToolError`.** Only `ToolError` text reaches the model verbatim — anything
   else is redacted to a generic string, discarding the upstream message. The
   unknown-outcome message keeps the word *unknown*, which RFC 0005 requires,
   and adds that the write may already have been applied. That addition is this
   RFC's decision rather than RFC 0005's requirement, and it exists because
   "unknown" alone invites a user to retry by hand and duplicate rows.

9. **`whoami` runs at startup under `httpx2.Timeout(10.0, connect=5.0)` and is
   never retried.** The ceiling lives in the read timeout because a call with no
   replays has no retry checkpoint for a deadline to act at. A 401 exits
   non-zero: the token is not valid and every tool would fail. A 403 starts the
   server with scope unknown, because RFC 0006 treats a 403 as what a token
   teaches per call — the server *"learns what the token may actually do only by
   making a call and reading a 403"* — not as a verdict on the token. A timeout,
   5xx or 429 also starts the server, with the line saying scope is unknown.
   Never retrying matters beyond politeness: a supervisor restarting a
   crash-looping server would otherwise amplify one configuration mistake into
   repeated calls against a shared bucket, toward a sticky 429 that backoff
   cannot clear.

## Alternatives considered

### Supersede RFC 0008 and inherit the `upstream-api` topic

The obvious reading of the topic rule is that this belongs to `upstream-api`,
and superseding is how a topic changes hands — RFC 0002 and RFC 0008 already
share that topic across a supersession, so "the topic is taken" rules nothing
out. It was rejected because RFC 0008 bundles two unrelated decisions: the
version, base URL and fingerprint pin, and the rate-limit stance. A
failure-policy RFC has no business re-deciding the pin, and superseding would
force it to either restate that content or leave `upstream-api`'s current truth
incomplete. The cost of the new topic is real and is accepted: describing the
client's failure behaviour now requires citing two topics, which is the
fragmentation RFC 0009 warned against.

### Explicit retry decisions at each call site

Every tool would state its own retry behaviour, with nothing hidden and each
call readable in isolation. Rejected because it puts the policy in seventeen
places, which is precisely what RFC 0005 was avoiding when it deferred the
budget to a single owner. The first tool written slightly differently becomes a
correctness bug that no reviewer would notice, and the failure mode is silent
data duplication rather than an error.

### Retry middleware inside the `httpx2` transport

Retries become invisible and call sites look like ordinary requests. Rejected on
a structural flaw rather than a preference: a transport sees a method and a URL,
not whether an upsert carried `key_columns`. That is exactly the distinction RFC
0005 requires, so a transport-level implementation must either replay unkeyed
upserts and duplicate rows, or refuse to replay any write and lose the safe
cases. Neither is acceptable, and no configuration recovers the information.

### Treat a connect-phase failure as replay-safe on any method

This is what the class name suggests and it would restore transient-failure
protection to writes. Rejected for lack of evidence: no probe, staff citation or
library documentation in this repository establishes when `httpx2` raises
`ConnectError` relative to transmission. The 429 case is safe because RFC 0008
cites precedent for it; this one would rest on an assumption, and the failure
mode is duplicated destructive writes.

### Widen RFC 0005's allowlist to cover the export POST

`read_page`'s export kickoff is a POST, so it is UNSAFE by RFC 0005's letter and
gets no replay on the most-used read path. Rejected because that allowlist is
frozen and widening it means superseding an RFC that decides far more than retry
policy. The reissue is not obviously harmless in any case — the evidence notes
that two in-flight exports of one page race on one object.

## Consequences

The seventeen tools get one place to read the policy and one place to change it,
and the classification is testable without a live API, because `httpx2`'s
`MockTransport` can raise real timeout and connection-error types.

`read_page` has no transient-failure protection. It is the most-used read path,
its kickoff is a POST, and honouring RFC 0005's frozen allowlist means a single
blip fails the call. This is the clearest cost of the decision and the most
likely thing a future RFC will revisit.

The `whoami` call makes startup depend on the network for the first time. A
configuration error still exits before any request, and tests run against
`MockTransport`, but a server that used to start offline now makes one call
before it serves.

Rule 2 leaves a known question open rather than answering it, and marks it as
the kind of question a probe settles. That is deliberate, and it means the
conservative behaviour ships first and is relaxed only on evidence.

Two topics now describe one subsystem's failure behaviour. Anyone writing a
living document about the client must cite both `upstream-api` and
`failure-policy`, and anyone changing one must check the other.

## Implementation notes

Left empty at Proposed.
