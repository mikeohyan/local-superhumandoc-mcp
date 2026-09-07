---
rfc: 0014
title: Measure a row in the units the API counts, and report what a deadline left undone
status: Implemented
created: 2026-09-06
decided: 2026-09-06
supersedes: 0011
superseded_by:
topic: request-sizing
commits: [6d031b8, a22d6e6, bb29885, 1f157af, 285ca88]
tags: [sizing, batching, deadlines]
---

# RFC 0014 — Measure a row in the units the API counts, and report what a deadline left undone

## Context

RFC 0011 was written and decided on 2026-09-05. Probe P7 and the nine-sample
measurement recorded in `docs/reference/api-operational-constants.md` §2.3 landed
the same day, and the RFC absorbed them unevenly: its Not-decided section says
*"`ROW_INFLATION_FACTOR` is no longer a guess. Probe P7 measured the quantity it
stands for and found it computable and bounded above by 2.0"*, while rule 4's
premise still reads *"the 85 KB ceiling is measured in a representation this
client cannot compute."* Both sentences are in one frozen body, and they
contradict each other.

The contradiction has a consequence one level down. Rule 3 says the row cap is
measured the way the API counts a row — *"its values' UTF-8 length with newlines
charged twice — not as wire bytes"* — and warns that *"conflating them is the
mistake this rule exists to prevent."* Four lines later its own isolation test
is a row *"whose own serialised size, multiplied by `ROW_INFLATION_FACTOR`,
already exceeds `MAX_ROW_JSON_BYTES`"*, which is the wire measure multiplied by
an estimate. The constants file settles which unit the cap is in and confirms
the mismatch: *"38 KB × 2.2 ≈ 84 KB internal"* makes 38 KB a wire budget, so one
rule denominates one constant two ways.

The multiplier is worse than merely unnecessary. §2.3's nine samples fit
`internal ≈ utf8_len(value) + newline_count` to about 1%, and establish that the
ratio *"is therefore bounded above by 2.0 — the all-newline limit"*, with
"Nothing can exceed it." `ROW_INFLATION_FACTOR` is 2.2. It reserves headroom for
a case that cannot occur, and the cap derived from it refuses rows at roughly
half the size the API accepts. For a row of ordinary ASCII the true ratio is
about 1.01, so the cap binds around eighty-two thousand wire bytes of content
that a client measuring correctly would send in one request.

A second, unrelated problem surfaced in the readiness audit before implementation
began. Rule 4 promises that halving *"ends holding the offending row"*, and its
Alternatives defend recursion on the grounds that it *"costs at most a
logarithmic number of round trips, is bounded by the deadline anyway under rule
7."* The arithmetic does not support the promise. The working budget is eighty
seconds. A row upsert reports `completed` at about twenty seconds, measured by
probe P8 on 2026-09-06. Isolating one mis-measured row out of
`MAX_ROWS_PER_UPSERT` of a hundred takes seven halvings, and while the *refused*
halves are cheap, the *accepted* halves are ordinary applied chunks that must
each be polled to completion — roughly a hundred and forty seconds against
eighty. Rule 7's affordability check means the deadline is never breached; the
call simply stops after about three chunks and reports the rest as not
attempted. So the mechanism is safe and the promise is false: recursion reaches
a single row only for batches of about eight or fewer.

RFC 0011's Consequences price applied chunks and refusals but never price the
accepted halves the recursion itself generates, which is where the estimate went
missing.

## Decision

**A row is measured in the units the API counts, computed rather than
estimated.** The size of a row is the sum over its values of the value's UTF-8
byte length plus one additional byte for each newline it contains — §2.3's
formula, which fits nine samples across Latin text, CJK, emoji and
newline-dense content to about 1%. Nothing is multiplied by anything.

**`ROW_INFLATION_FACTOR` is retired.** It estimated a quantity that is now
computed directly, and its value exceeded the ratio's provable maximum, so it
could only ever have been wrong in the conservative direction. Retiring it
resolves rule 3's two-unit contradiction by removing the second unit.

**The row cap is `MAX_ROW_INTERNAL_BYTES`, denominated in those same internal
units**, set below the published 85 KB ceiling with a margin for the formula's
~1% error rather than for a guessed conversion. A row whose computed size alone
exceeds the cap is placed in a chunk by itself, so that a refusal names that row
and costs only that row rather than the batch around it.

**The pre-send measurement is accurate, and the API's refusal is still
authoritative.** These are no longer in tension. A size refusal — a 400 whose
message matches `exceeds maximum size` or `entity too large` — is still answered
by halving and resending, because a measurement fitting to 1% is not a
measurement fitting always, and because the 1.5 MB request cap is a separate
axis measured in wire bytes that this formula says nothing about. What changes
is the expected frequency: halving becomes the response to a genuine surprise
rather than a routine consequence of not knowing the units.

**A batch that the deadline cuts short reports exactly which rows were not
attempted, and makes no promise about isolating the offending one.** RFC 0011's
"ends holding the offending row" is withdrawn as a guarantee. What is guaranteed
is that every row is accounted for under one of four outcomes — *applied*,
*unknown*, *refused*, *not attempted* — and that the rows reported not attempted
are a suffix of the caller's own input, so a second call resumes rather than
guesses. Halves go sequentially, in the order the caller's rows arrived, which
is what makes the suffix property hold. This costs nothing that was working: the
affordability check already stopped the recursion at the same place, and only the
sentence describing the result was wrong.

The remaining rules carry forward from RFC 0011 unchanged in substance:

1. A tool splits an oversized batch; it does not refuse one.
2. Page-content writes are refused above their cap, never split, because a page
   body has no natural split point that preserves meaning.
3. Two axes bound a chunk. `MAX_REQUEST_BYTES` guards the request and is
   measured on the serialised body actually sent; the row cap guards the row and
   is measured as above. The count cap governs many small rows, the byte caps
   few large ones. An empty `rows` or `row_ids` list is an empty report and
   sends nothing.
4. Re-chunking is not a replay. A halved chunk is a different request with
   different content and carries its own budget; what bounds the recursion is
   the single-row floor together with the deadline, not the replay counter,
   which never sees it.
5. A split write reports every row's outcome and never a single verdict.
6. A chunk is started only while the deadline can afford one. The local
   throttle's admission refusal is caught and the rows it covers fold into *not
   attempted*, because losing the whole account of a batch because its last
   chunk could not get a slot is the failure the four outcomes exist to prevent.
   That refusal now has its own exception type, so catching it no longer means
   also catching a deadline that has simply expired.
7. Reads request a page size and never trust the count returned, because the API
   silently clamps it.
8. A 504 from `find_rows` restarts that listing at half the page size, down to a
   floor which is itself attempted once. Rows from a pass a 504 ended are
   discarded rather than merged, since nothing establishes that two passes
   enumerate a table in the same order. Rows from the pass the *deadline* cut
   short are kept and reported, and the tool says how far it got. The failure
   carries the document-size hypothesis, since the vendor says the API is not
   supported past 125 MB and document size is not readable through the API.
9. The operating values live in `docs/reference/api-operational-constants.md`
   and may be retuned against observation without superseding this RFC. What is
   decided here is the rule; the calibration is not.

## Alternatives considered

### Keep the multiplier and fix only the unit

Decide that the cap is denominated in wire bytes, leave `ROW_INFLATION_FACTOR`
in place, and make rule 3 self-consistent that way. It is the smaller edit and
it preserves a constant that is provably above its own maximum, which means the
cap stays roughly twice as conservative as it needs to be for no benefit. Fixing
a contradiction by keeping the wrong half is not a fix.

### Raise the cap to the published ceiling exactly

If the size is computed to 1%, 85 KB could be the cap. It is not, because the
formula missed by 1.1% on one of nine samples and the failure mode is a refused
request rather than a slightly smaller batch. A margin that costs a percent of
throughput and removes a class of avoidable round trips is worth paying.

### Allow concurrent mutations so the recursion can finish in one call

The readiness audit identified this as the escape hatch: admission to the
doc-content bucket at two per ten seconds would allow roughly sixteen writes in
eighty seconds, and the recursion would close comfortably. It is rejected here
because concurrency across mutations is not this topic's to decide — the
`async-operations` topic owns how much concurrent work the client permits itself
— and because it would buy a guarantee that is not worth its risk: overlapping
unkeyed writes against an API with no idempotency keys, to isolate a row whose
size this RFC now measures correctly anyway.

### Reduce `MAX_ROWS_PER_UPSERT` to eight so the promise becomes true

Arithmetically sufficient and practically absurd. It would cap every batch at
the size that makes a rare recovery path complete, penalising the common case —
a hundred rows that all fit — to preserve a sentence. Withdrawing the sentence
is cheaper than shrinking the tool.

### Compute the size from the serialised JSON and calibrate a new factor

A factor fitted to the escaped-JSON representation would at least be measured.
It fails on non-Latin content for the reason rule 3 already gave: escaping
inflates CJK and emoji several-fold against an internal count that does not, so
the factor would have to be fitted per script. The formula in §2.3 has no such
dependence — it fit CJK and emoji as well as ASCII — which is precisely why it
is worth using directly.

## Consequences

**Makes easy.** A batch of ordinary rows is roughly twice the size it was, for
no additional risk, because the cap now reflects what the API accepts rather
than what a doubled guess allowed. Non-Latin content stops being refused at a
fraction of its permitted size. And a caller whose batch ran out of time is told
exactly which rows to send next, which is the thing they actually need.

**Makes hard.** The size computation is now load-bearing rather than advisory,
so an error in it surfaces as a refused request rather than an extra round trip.
The formula is fitted to nine samples on one API version and nothing monitors
whether it still holds. Callers who read RFC 0011's promise that halving ends
holding the offending row will find this RFC declining to make it.

**Commits us to.** Computing a row's size the way one vendor's storage layer
counts it, which is an implementation detail of theirs that no specification
publishes and which can change without notice. The retired multiplier was
wrong but insensitive to that risk; a fitted formula is precise and brittle in
exactly the way precise things are.

**Accepted risk.** No 504 has ever been observed from this client, so the page-
size ladder ships tested against a mock alone, and calibrating it properly would
mean provoking gateway timeouts against a production document, which this
project does not do. The four outcomes are more surface for a model to misread
than a single result, and the *not attempted* state in particular has no
analogue in most APIs a model will have seen.

## Implementation notes

Shipped 2026-09-07 across five commits, in `sizing.py`, `outcomes.py`,
`chunking.py` and the two row-write tools in `tools/writes.py`.

**The measurement went in unchanged.** `row_internal_bytes` is
`utf8_len(value) + newline_count` summed over a row's values, and
`MAX_ROW_INTERNAL_BYTES` is 84,000 internal bytes. `ROW_INFLATION_FACTOR` is
gone from the constants file rather than merely unused.

**The second axis needed a correction the decision did not anticipate.**
`request_wire_bytes` was first written as `json.dumps(payload,
ensure_ascii=False)` with a docstring claiming non-ASCII inflates to `\uXXXX`
escapes — a claim that contradicts the very argument it was passing. It now
serialises exactly as `httpx2._content.encode_json` does, compact separators
included, because a measure that disagrees with the encoder is guessing at the
number the cap is expressed in. Default separators charge two bytes per field
that are never sent, which on a batch of many small cells is a real over-count.

**The suffix guarantee holds, and one defect nearly cost it.** `BatchReport`
initially left unmarked rows out of its outcome map, so `resume_from` answered
`None` while `as_dict` reported those same rows as not attempted — a caller
trusting `resume_from` would have dropped them. Reachable exactly when a
chunker returns early, which is the case resuming exists for. Every row now
starts `NOT_ATTEMPTED`, and a test marks fewer rows than it opens.

**The halving trigger shipped too broad and was narrowed.** `send_chunks`
halved on any `UpstreamRefused`. This RFC is specific — a size refusal is a 400
whose message says `exceeds maximum size` or `entity too large`, that text
being the only discriminator, since the body carries no `codaType` and no
`codaDetail`. Halving a 403 or a bad table name would have asked the same
question up to seven more times per batch. The test fake had raised an invented
paraphrase, close enough to read right and wrong enough not to exercise the
branch; it now raises the recorded message verbatim.

**`CHUNK_COST_ESTIMATE_S` as an admission gate rather than a bound is pinned by
a test**, because the obvious reading of an estimate is that it bounds the cost.
A chunk admitted on a thirty-second estimate may poll for sixty.

**Not carried out here:** `delete_rows` chunks row IDs against
`MAX_ROW_IDS_PER_DELETE`, which lives beside that tool rather than in
`sizing.py`, on the same reasoning that keeps `MAX_ROWS_PER_UPSERT` beside
`upsert_rows` — both are properties of one operation, not of the shared
measurement.
