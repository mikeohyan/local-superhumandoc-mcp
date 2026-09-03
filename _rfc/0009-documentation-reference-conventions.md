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

**Superseding one RFC staled every reference to it at once.** When RFC 0008
superseded RFC 0002, every document that said "see RFC 0002 for the
authentication scheme" became a pointer to a file stamped *no longer true —
history only*. Five such citations sat outside `_rfc/`, in four files:
`CLAUDE.md`, `README.md` twice, `.env.example` and `.gitignore`. The index
carried two more rows. The `CLAUDE.md` case is the serious one, because that file
is loaded into every session in this repository — it was instructing future
sessions to read a retired decision in order to learn current behaviour, which is
precisely what RFC 0001 warns against.

All were repaired by hand in the superseding commit, and nothing would have
detected them if they had been missed. Note what was *correctly* left alone: RFC
0001's Implementation notes cite RFC 0002, and that citation is still right,
because it records what was true when the work shipped.

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
editing it. No future supersession creates work in an accepted RFC's body. A
Proposed RFC is treated as already frozen for this purpose: its body is about to
freeze unchanged, so it cites numbers and is never repointed.

**Living documents cite a topic, never a number.** A living document is any file
whose job is to describe how the project works *now* — in practice, everything in
the repository that is not an RFC body. The set is deliberately not enumerated
here, because an enumeration inside a document that freezes is the very failure
this RFC exists to prevent; *Adopting this* gives a command that recovers it.

Two living documents still contain numbers, both because they are bound to a
number by construction rather than citing one as a claim about current truth.
`_rfc/README.md` is the index: resolving topics to numbers is its job. And
`_rfc/plans/NNNN-plan.md` is named after the single RFC it implements and is
deleted when that RFC ships, so it is scoped to one number and cannot outlive
it.

The mechanism is a `topic:` frontmatter field: a short kebab-case name for the
**subject** a decision is about, not for the decision itself. Successive RFCs on
the same subject share a topic — RFC 0002 and RFC 0008 are both `upstream-api`. A
topic has at most one current RFC.

`topic:` is frontmatter, so it is living in RFC 0001's sense: it may be added to
an RFC that has already frozen, and corrected later, without touching the body.
RFC 0001's list of living fields — `status`, `decided`, `superseded_by`,
`commits` — predates this field and is extended by it, not contradicted.

`_rfc/README.md` gains a **Current decisions by topic** table:

```
| Topic             | Current RFC | Status   | Path              |
|-------------------|-------------|----------|-------------------|
| `upstream-api`    | 0008        | Proposed | `_rfc/0008-...md` |
| `doc-conventions` | 0009        | Proposed | `_rfc/0009-...md` |
```

The table carries status, so a reader can see whether the current decision on a
topic has actually been accepted. Superseding then edits **one row** instead of
hunting through the repository.

Three rules keep the table honest at its edges. A retired RFC keeps its topic, so
a lineage stays joined, but never appears in this table — the table lists only
non-retired RFCs. A topic whose only RFC is Rejected has no row, because a
rejected proposal is not a current decision. And a topic whose current RFC is
retired with nothing replacing it loses its row in the same commit that retires
the RFC, together with every living-document citation of it — a dangling topic is
worse than a stale number, because a stale number at least lands the reader on a
readable file marked *history only*, while a dangling topic resolves to nothing.

A living document cites like this:

> The API surface this project targets is pinned by the `upstream-api` topic — see
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

Four structural changes: add `topic:` to `_rfc/TEMPLATE.md`; give **every** RFC
a topic, retired ones included, so a lineage stays joined after its current
member is superseded; add the topic table to `_rfc/README.md`; and extend the
`rfc` skill's index-regeneration procedure to cover that table.

The fifth change is the repoint of existing citations, and it is deliberately
**not** written here as a list of files — an enumeration inside a document that
freezes is correct on the day it is written and silently wrong once a file is
added. The rule is the durable form and the audit is a command:

```bash
# Number-shaped citations.
grep -rn --exclude-dir=.git -E 'RFC[- ]?[0-9]{4}' .

# Path-shaped citations. RFC 0001 already forbids these; nothing enforced it.
grep -rn --exclude-dir=.git -E '_rfc/(archive/[a-z]+/)?[0-9]{4}-' .
```

Every hit is classified rather than repaired reflexively: a number in an RFC
body — Proposed or accepted — is correct as history and is left alone; a number
anywhere else is repointed to a topic. Nothing under `docs/` is exempt. RFC 0003
makes those files mutable and corrected in place, so they are living documents in
full, and a carve-out for the dated files under `docs/validation/` would quietly
reverse that decision without superseding it.

Two blind spots are worth stating, because the commands above look more complete
than they are. Neither finds a citation written as prose — "the RFC that
specifies the client" is a pointer that rots exactly as fast as a number and is
invisible to both. And neither inspects `_rfc/README.md`, whose rows carry bare
numbers by construction. Repointing therefore ends with a read of the living
documents, not with a clean grep.

Adopting this before accepting a batch of Proposed RFCs costs nothing, because
their bodies are still mutable and their frontmatter has not yet been through a
freeze. Adopting it afterwards means adding a field to records that have just
frozen — permitted, since frontmatter stays living, but a worse moment.

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

### Pointer files, one per topic — `_rfc/topics/upstream-api.md`

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

It also concentrates the failure. Under the old regime a stale reference
misdirected one document; one wrong row in the topic table now misdirects every
living document citing that topic, simultaneously. The old failure also degraded
gracefully, landing a reader on a file marked *history only*, where a topic with
no row resolves to nothing at all. The table is small and the invariant is
checkable, which is the trade being made, but the blast radius genuinely grew.

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
