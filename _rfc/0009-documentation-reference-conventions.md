---
rfc: 0009
title: Reference decisions by topic and code by symbol, never by number or line
status: Proposed
created: 2026-09-03
decided:
supersedes:
superseded_by:
topic: doc-conventions
commits: []
tags: [process, documentation]
---

# RFC 0009 — Reference decisions by topic and code by symbol, never by number or line

## Context

Two kinds of reference in this repository rot on their own, and both were
observed rather than anticipated.

**Superseding one RFC invalidated references in ten places.** When RFC 0008
superseded RFC 0002, every document that said "see RFC 0002 for the
authentication scheme" became a pointer to a file stamped *no longer true —
history only*. Six were citations inside other RFCs. Four were outside `_rfc/`
entirely: `CLAUDE.md`, `README.md` twice, and `.env.example`. The `CLAUDE.md`
case is the serious one, because that file is loaded into every session in this
repository — it was instructing future sessions to read a retired decision in
order to learn current behaviour, which is precisely what RFC 0001 warns against.
All ten were repaired by hand, and nothing would have detected them if they had
been missed.

The diagnosis is narrower than the symptom. RFC 0001 already forbids hardcoding
an RFC's **path**, and that rule held — no path broke. What broke was **a number
used as a claim about current truth**. "See RFC 0002 for the auth scheme"
asserts currency, and currency is exactly what supersession revokes.

**Line numbers will rot as soon as there is code.** No implementation exists yet,
so this is pre-emptive, but the pattern already appeared during research: working
notes cited the OpenAPI specification as "line 1807 of the YAML" and "defined at
line 8815". The documents that were actually committed happen to cite
`operationId` and schema names instead — good practice that occurred by accident
rather than by rule. RFC 0008 makes the hazard concrete: that specification is
template-rendered, so a line number in one fetched copy need not describe any
other copy, and the digest can change without the API changing.

## Decision

Two rules, one for decisions and one for code.

### Rule 1 — cite decisions by topic where the citing document must stay current

Whether a reference should name an RFC number depends on whether the document
doing the citing is a living document or a frozen one.

**Frozen documents cite numbers, and are never updated afterwards.** An accepted
RFC's body is a dated snapshot. A citation of what was current when it was
written is *correct* as history, not stale, and the freeze rule already forbids
editing it. No future supersession creates work in an accepted RFC. The six
in-`_rfc/` citations repaired during RFC 0008's supersession only needed
repairing because those RFCs were still Proposed and had not yet frozen.

**Living documents cite a topic, never a number.** This covers `CLAUDE.md`,
`README.md`, `.env.example`, everything under `docs/`, and any future file whose
job is to describe how the project works *now*.

The mechanism is a `topic:` frontmatter field: a short kebab-case name for the
**subject** a decision is about, not for the decision itself. Successive RFCs on
the same subject share a topic — RFC 0002 and RFC 0008 are both `api-pin`. A
topic has at most one current RFC.

`_rfc/README.md` gains a **Current decisions by topic** table:

```
| Topic         | Current RFC | Status   | Path |
|---------------|-------------|----------|------|
| api-pin       | 0008        | Proposed | `_rfc/0008-...md` |
| doc-conventions | 0009      | Proposed | `_rfc/0009-...md` |
```

The table carries status, so a reader can see whether the current decision on a
topic has actually been accepted. Superseding then edits **one row** instead of
hunting through the repository.

A living document cites like this:

> The API surface this project targets is pinned by the `api-pin` topic — see
> `_rfc/README.md` — read it before writing any client code.

### Rule 2 — cite code by symbol and specifications by identifier

- **Code is cited as path plus symbol**, never a line:
  `src/superhumandoc_mcp/api/limits.py::TokenBucket.acquire`. A symbol survives
  every edit above it, and a rename is a deliberate act that shows up in review.
- **Line numbers never appear in committed documentation.** They remain fine in
  ephemeral contexts — a review comment, a chat message, a session transcript —
  because those are not maintained.
- **Where no symbol exists**, such as one branch of a conditional or a block of
  configuration, place a named anchor comment in the code and cite the anchor:

  ```python
  # ANCHOR: export-poll-loop
  ```

  Anchors are greppable, and they move with the code they mark.
- **Recording what was built uses commit SHAs**, not symbols. RFC 0001 already
  provides the `commits:` frontmatter field for this. The split: an RFC body
  describes intent and cites symbols; Implementation notes record history and
  cite SHAs.
- **External specifications are cited by `operationId`, schema name, or JSON
  path** — `operationId: listPageContent`, `PageContentExportStatus` — never by
  line number in a fetched copy.

### Adopting this

The convention requires four changes when it ships: add `topic:` to
`_rfc/TEMPLATE.md`; assign a topic to each live RFC; add the topic table to
`_rfc/README.md`; and repoint `CLAUDE.md`, `README.md` and `.env.example` from
`RFC 0008` to the `api-pin` topic. The `rfc` skill also needs the topic table
added to its index-regeneration procedure.

## Alternatives considered

### Keep citing numbers everywhere and repair by hand on each supersede

What the repository does today. It is not unworkable — the RFC 0008 supersession
was repaired in a single pass. Rejected because the failure is silent: nothing
detects a reference that should have been updated and was not, and the one
document where a missed reference does real damage, `CLAUDE.md`, is the one a
session reads before it knows anything else. The cost is also paid by whoever
supersedes, which is exactly when attention is on the new decision rather than on
auditing old references.

### Always cite the first RFC in a lineage and let the reader follow `superseded_by`

Numbers stay valid forever, and no document ever needs updating. Rejected because
it lands the reader on a document marked *no longer true — history only*, and
asks them to notice a frontmatter field and navigate onward before believing
anything. RFC 0001 is explicit that retired RFCs are read only to understand
history, never to learn current behaviour. This alternative makes them the front
door.

### Pointer files, one per topic — `_rfc/topics/api-pin.md`

A one-line file naming the current RFC, cited directly by living documents.
Functionally equivalent and arguably more discoverable, since a citation becomes
a real path. Rejected as heavier for the same benefit: it adds a file per topic
and a second place to look, where a table in the index a reader already opens
costs nothing extra.

### Symlinks from a stable name to the current RFC

Rejected on mechanics rather than principle — symlinks interact badly with `git
mv` transitions, behave inconsistently across platforms, and would obscure the
`git log --follow` history that RFC 0001 goes out of its way to preserve.

### Generate the topic table with a script

Rejected now for the reason RFC 0001 gave for the index it already maintains by
hand: below roughly ten RFCs the drift is cheap to correct, and a script is
weight to carry. Visible drift in either table is the signal to write one
generator for both — a bounded change, not a new RFC.

### For code: permalinks pinned to a commit SHA

A GitHub blob URL with a SHA never breaks. Rejected as the general rule because
it is precisely wrong for the common case: it points at code as it was, so a
reader following it to learn current behaviour is misled by a link that looks
authoritative. It remains the right tool for recording history, which is why
Implementation notes use SHAs.

### For code: keep line numbers and add a CI check that validates them

Machinery to defend a practice that has no advantage over symbols in the first
place. Rejected as solving a self-inflicted problem.

## Consequences

**Makes easy.** Superseding costs one table row instead of a repository-wide
audit. Living documents stop rotting silently. Refactoring stops invalidating
documentation, because a moved function keeps its name and an anchor moves with
its code. The distinction between "what we decided then" and "what is true now"
becomes visible in the citation style itself.

**Makes hard.** Every reference in a living document gains an indirection hop:
the reader learns the topic, then consults the index, then opens the RFC. There
is a second hand-maintained table to keep current. Topics must be chosen with
some care — one per subject, not one per decision — or the table grows a row per
RFC and stops being useful.

**Commits us to.** A `topic:` field on every future RFC, and `_rfc/TEMPLATE.md`
changing to match. Anchor comments that exist purely to be cited, which is a
small amount of code written for documentation's benefit.

**Honest about the tradeoff.** This machinery pays for itself only if
supersession is reasonably common. If this repository settles into a handful of
stable decisions that are rarely revised, the topic table is overhead and the
manual repair we performed once would have remained the cheaper path. That
judgement is recorded here deliberately, so a future session that finds the table
unused can supersede this RFC on the evidence rather than rediscovering the
argument from scratch.

**Deferred.** Nothing detects a living document that cites an RFC number in
violation of Rule 1, or committed documentation containing a line number in
violation of Rule 2. Both are greppable and could become a pre-commit check;
neither is worth building before the conventions have been lived with.

## Implementation notes

Left empty at Proposed.
