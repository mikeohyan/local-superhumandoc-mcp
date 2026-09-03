---
name: rfc
description: Use when recording an architectural decision, asking what was decided about something or why the project works a certain way, reversing or superseding an earlier decision, or moving an RFC between statuses - owns the numbering, template, immutability rule, and git mv transitions for _rfc/
---

# RFC process

Design decisions in this repository are recorded as numbered RFCs under `_rfc/`.
The process itself is specified in RFC 0001
(`_rfc/archive/implemented/0001-rfc-process.md`). This skill is the operating
manual: what to run, in what order.

## Before anything else

Read `_rfc/README.md`. It is the index — every RFC's number, title, topic,
status, and **path**, plus a **Current decisions by topic** table that names the
one live RFC per subject. An RFC's number does not determine where it lives, so
never construct a path from a number. To locate one directly:

```bash
ls _rfc/NNNN-*.md _rfc/archive/*/NNNN-*.md 2>/dev/null
```

Currently-true decisions are split across two places, and both matter — the
third directory below is history only:

- `_rfc/*.md` — Proposed and Accepted: decided or awaiting decision, not yet
  shipped.
- `_rfc/archive/implemented/*.md` — shipped, **and still the current truth**.
  A session learning how the system works today reads these.
- `_rfc/archive/retired/*.md` — Superseded and Rejected. No longer true. Read
  these only to understand history, never to learn current behaviour.

## The one rule that is easy to get wrong

**Once an RFC is Accepted, its body is frozen. Its frontmatter is not.**

- Never edit Context, Decision, Alternatives considered, or Consequences after
  acceptance. If the decision was wrong, supersede it.
- Always update `status`, `decided`, `superseded_by`, and `commits` as the RFC
  moves through its lifecycle — that is what they are for.
- Implementation notes is the single body exception: the session that ships the
  work fills it in, because it records what happened.

## Does this need an RFC?

Use the classification the `superpowers:brainstorming` skill already produced —
do not make a second, separate judgment:

- **Architectural** → write an RFC.
- **Bounded** → no RFC, *unless* it reverses an existing decision. Then it is a
  supersede and needs one.
- **Spike** → no RFC. The finding becomes evidence inside the RFC it informs.

Decisions with no code count: pinning an external API version, choosing a
dependency manager, setting a repository convention.

## Allocating a number

```bash
ls _rfc/[0-9]*.md _rfc/archive/*/[0-9]*.md 2>/dev/null \
  | grep -oE '[0-9]{4}' | sort -n | tail -1
```

Add one; pad to four digits. Numbers are permanent and never reused, including
for Rejected RFCs.

## Writing a new RFC

Copy `_rfc/TEMPLATE.md` to `_rfc/NNNN-slug.md` and fill it in. The template is
the single source of truth for the frontmatter fields and section headings — do
not reproduce its structure from memory, read it.

The slug is short, lowercase, hyphenated, and describes the decision rather than
the component: `0007-mcp-auth-model`, not `0007-auth`.

`topic:` is the opposite: it names the **subject**, not the decision, because
living documents cite it in place of a number and successive decisions on the
same subject must share it. Before inventing one, read the topic table in
`_rfc/README.md` — if this RFC revises a subject already listed there, reuse that
topic rather than creating a near-duplicate.

Write the rejected options into Alternatives considered while the reasoning is
still in context. `superpowers:brainstorming` required 2-3 approaches with
trade-offs; those approaches are the section's content. Recovering them later is
impossible — the transcript is gone.

Commit the RFC at Proposed, before implementation begins.

## Transitions

Every relocation uses `git mv`. Never a plain `mv`, and never write-then-delete.
A plain move registers as an untracked add plus a deletion, and git's rename
inference degrades exactly when frontmatter is edited in the same commit — which
every transition below does. `git mv` keeps `git log --follow` and `git blame`
intact across an RFC's whole life.

### Proposed → Accepted

The owner approves at the `superpowers:brainstorming` spec-review gate. Set
`status: Accepted` and `decided: YYYY-MM-DD`. The file does not move. Update the
index — the status appears in two tables, the in-flight one and the topic one.

### Accepted → Implemented

Only after `superpowers:verification-before-completion` actually passes.

```bash
git mv _rfc/NNNN-slug.md _rfc/archive/implemented/
git rm _rfc/plans/NNNN-plan.md      # if a plan exists
```

Then set `status: Implemented`, list the shipping commit SHAs in `commits`, and
fill in Implementation notes — including anything that diverged from the
Decision and why. Update the index.

The plan is deleted because its only job, letting a later session resume
half-finished work, is over. Git history keeps it.

### Proposed → Rejected

```bash
git mv _rfc/NNNN-slug.md _rfc/archive/retired/
```

Set `status: Rejected`. The body still freezes — a rejected proposal is a record
that the option was considered. Update the index.

### Accepted or Implemented → Superseded

Write the new RFC first, with `supersedes: NNNN` in its frontmatter. Then, on
the old one:

Locate the old RFC with the lookup above, then move it by its actual path:

```bash
git mv _rfc/NNNN-old-slug.md _rfc/archive/retired/                     # if in flight
git mv _rfc/archive/implemented/NNNN-old-slug.md _rfc/archive/retired/  # if shipped
```

Set `status: Superseded` and `superseded_by: MMMM`. Keep its `topic` unchanged:
the retired RFC and its replacement share a subject, and that shared value is
what makes the lineage traceable. Do not edit its body, and do not delete it —
the superseded reasoning is the point.

Then update the index, and note that a supersede is the one transition that
**rewrites a topic row rather than adding one**: the topic's row in *Current
decisions by topic* must now name MMMM, not NNNN. Getting this wrong is the
failure the topic table exists to prevent, because every living document in the
repository resolves through that row.

## Implementation plans

`superpowers:writing-plans` writes to `_rfc/plans/NNNN-plan.md`, matching the
RFC's number. Plans are mutable working documents: tick the checkboxes, edit
freely. They are deleted when the RFC reaches Implemented.

A plan is the one living document that may cite RFC numbers directly. It is
named after a single RFC and deleted with it, so the number is its identity
rather than a claim about current truth that could go stale.

## Keeping the index current

`_rfc/README.md` is regenerated by hand as part of every transition above — it
is not generated by a script, by deliberate choice recorded in RFC 0001. It carries one table per location (in flight, implemented, retired), each
row giving number, title, topic, status, decided date, and path — plus the
**Current decisions by topic** table, which lists one row per subject naming that
subject's single current RFC.

The two kinds of table fail differently. A wrong row in a location table is
cosmetic; a wrong row in the topic table silently misdirects every living
document that cites that topic. Regenerate both, and check that each topic
resolves to exactly one non-retired RFC.

Regenerating it means re-reading the frontmatter of every RFC, not editing one
row from memory:

```bash
grep -H -E '^(rfc|title|status|decided|superseded_by|topic):' \
  _rfc/[0-9]*.md _rfc/archive/*/[0-9]*.md 2>/dev/null
```

Two invariants to check after regenerating:

```bash
# Every RFC has a topic (silence is success).
grep -L '^topic:' _rfc/[0-9]*.md _rfc/archive/*/[0-9]*.md

# No living document cites an RFC by number. Only RFC bodies are frozen, so
# only they are excluded; nothing under docs/ is exempt. Silence is success.
# The (\./)? is load-bearing: GNU grep -r prefixes every path with ./ and the
# filter is a silent no-op without it.
# _rfc/plans/ is excluded for the same reason as the index: a plan is named
# after the one RFC it implements and dies with it.
grep -rn --exclude-dir=.git -E 'RFC[- ]?[0-9]{4}' . \
  | grep -vE '^(\./)?_rfc/([0-9]|archive/|plans/)'

# No living document cites an RFC by path either — the `rfc-process` topic
# forbids it, since a path changes when the RFC is archived.
grep -rn --exclude-dir=.git -E '_rfc/(archive/[a-z]+/)?[0-9]{4}-' . \
  | grep -vE '^(\./)?_rfc/(README|[0-9]|archive/)'

# No RFC still carries the template's placeholder topic.
grep -n 'kebab-case-subject' _rfc/[0-9]*.md _rfc/archive/*/[0-9]*.md
```

The `[0-9]*` glob is deliberate: a plain `*.md` also matches `TEMPLATE.md`,
whose placeholder frontmatter (`rfc: NNNN`, `status: Proposed`) would otherwise
be copied into the index as a phantom row.

If the index has visibly drifted from the files more than once, that is the
signal to write a generator script — a bounded change, not a new RFC.
