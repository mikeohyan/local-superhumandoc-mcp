---
rfc: 0003
title: Keep empirical evidence and reference material in docs/, separate from decisions in _rfc/
status: Proposed
created: 2026-09-03
decided:
supersedes:
superseded_by:
commits: []
tags: [process, documentation]
---

# RFC 0003 — Keep empirical evidence and reference material in `docs/`, separate from decisions in `_rfc/`

## Context

RFC 0001 gave decisions a home and a rule: an RFC's body freezes at Accepted, and
a spike's finding "becomes evidence inside the RFC it informs". That rule is
sound for a finding that fits in a paragraph. The design work for the MCP server
produced two kinds of material it does not fit.

The first is a **runnable test plan**. Several questions about the Superhuman
Docs API cannot be answered from its specification, its documentation, or its
vendor's forum, because nobody has ever written the answer down — whether a
whole-page markdown `replace` destroys native doc objects, whether markdown
export is round-trip stable, what happens when a value outside a select column's
option list is written. Each is settled by running commands against a scratch
document. The resulting artifact is a few hundred lines of shell, is explicitly
destructive, and carries an empty Results section for the operator to paste
output into. It is an instrument, and it is written to be *used and updated*.

The second is a **body of API behaviour findings**: roughly eighty verified
statements about rate-limit buckets, asynchronous mutation semantics, cell value
formats, error shapes and pagination. These constrain several independent
decisions at once — the tool surface, the retry policy, the configuration model.

Neither is a decision, so neither is an RFC. Neither is an implementation plan,
so `_rfc/plans/` is wrong: plans are deleted when their RFC reaches Implemented,
and this material stays true long afterwards — it is most valuable to the session
that arrives a year later asking why the client throttles the way it does.

Inlining them into RFC bodies fails on both counts. Findings that inform four
RFCs would be copied into four frozen bodies and would immediately disagree with
each other. A test plan pasted into a frozen body could never have its results
recorded.

## Decision

`_rfc/` holds decisions. `docs/` holds the durable reference and evidence that
decisions rest on.

```
docs/
  reference/     distilled findings an implementer consults while writing code
  validation/    runnable test plans, with a Results section filled in as they are run
```

Files under `docs/` are **mutable and unversioned**. They carry no RFC
frontmatter, no status, and no number. They are corrected in place as facts are
learned, which is the entire point of separating them from bodies that freeze.

RFCs cite `docs/` files **by path**, never by copying their contents. A citation
is a pointer to where the evidence lives, not a snapshot of it; the RFC records
what was decided and why, and the `docs/` file records what is true.

The boundary is directional and worth stating plainly: **nothing in `docs/` is
authoritative for a decision.** A `docs/` file may say the API's rate limit for
doc-content writes is five requests per ten seconds; only an RFC may say the
client therefore self-throttles. When a `docs/` file starts asserting a choice
rather than a fact, that choice belongs in an RFC.

This extends RFC 0001 rather than contradicting it. RFC 0001 placed decisions in
`_rfc/`; it never claimed every artifact belongs there.

## Alternatives considered

### `_rfc/evidence/NNNN-*.md`, numbered to match the RFC it supports

Keeps a single tree to search and makes the coupling between a decision and its
evidence explicit in the filename. Rejected on two grounds. RFC 0001 already
considered and rejected per-RFC directories as premature at this repository's
size, and this drifts toward the same shape. More substantially, the numbering
asserts a one-to-one relationship that does not exist: the API behaviour findings
inform four separate decisions, so any number chosen for them would be wrong
three times.

### Inline everything into the RFCs that cite it

The literal reading of RFC 0001, and it requires no new convention. Rejected
because it fails on exactly the material that motivated this RFC. Findings
spanning several decisions get duplicated into several frozen bodies and drift
apart. A test plan with a Results section cannot live in a body that may not be
edited — the operator would have nowhere to record what happened.

### Put evidence in `_rfc/plans/`

The directory already exists and already holds mutable working documents.
Rejected because plans are `git rm`'d when their RFC reaches Implemented, on the
reasoning that a plan's job ends when the work ships. Evidence is the opposite:
its value is highest after the work ships, when someone is asking why the code
behaves as it does.

### Keep Superpowers' default `docs/superpowers/specs/` for this material

Requires no decision at all. Rejected because `CLAUDE.md` already redirects that
path to `_rfc/`, and reviving it would give the repository two competing
conventions for where design material lives — the precise confusion RFC 0001
exists to prevent.

## Consequences

**Makes easy.** Evidence can be corrected the moment a fact is learned, without
superseding anything. A test plan can accumulate results across several sessions.
RFC bodies stay short and stay about decisions, because the supporting detail
lives somewhere it can be pointed at. Findings that inform several decisions are
stated once.

**Makes hard.** There are now two trees to search, and a session that reads only
`_rfc/` will miss material it needs. This is mitigated by RFCs citing `docs/`
paths at the point of use, and by `CLAUDE.md` naming both locations — but the
mitigation depends on citations actually being written.

**Commits us to.** A discipline that is easy to erode: keeping assertions of
choice out of `docs/` and keeping snapshots of fact out of RFC bodies. The
failure mode to watch for is a `docs/` reference file that quietly grows a
rationale section and becomes a shadow RFC.

**Deferred.** No index for `docs/`, and no rule about pruning evidence that has
been fully superseded by a later finding. Both are cheap to add if the directory
grows past the point where `ls` is a sufficient index; neither is worth carrying
now.

## Implementation notes

Left empty at Proposed.
