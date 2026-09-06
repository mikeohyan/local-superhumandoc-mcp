---
rfc: 0013
title: Write page content as HTML, and never send a read back as a write
status: Proposed
created: 2026-09-06
decided:
supersedes: 0005
superseded_by:
topic: tool-surface
commits: []
tags: [tools, fidelity, write-safety]
---

# RFC 0013 — Write page content as HTML, and never send a read back as a write

## Context

RFC 0005 chose markdown as the notation for every page-content write, and said
so with a condition attached. Its accepted-risk section reads: *"Whether
markdown export is round-trip stable is also unconfirmed — if it is not, even
element-scoped read-modify-write degrades content over repeated edits, and this
design would need revisiting. Both are settled by running
`docs/validation/2026-09-03-markdown-fidelity-tests.md`."*

That plan ran on 2026-09-06. Markdown export is not round-trip stable, and the
instability is not a rounding error. Test B5 recorded it as *"Not a fixed point
— the most consequential result of this run"*: a page containing a table, read
as markdown and written back unchanged, gains a row. The synthesised header is
demoted to data and a fresh generic header is invented above it, and this
happens **again on every cycle**. B7 states the shape of the damage plainly —
it *"accumulates with the number of edits rather than with their size."* A
one-character edit costs as much fidelity as a rewrite.

Three further findings from the same run bear on the notation itself. A
markdown pipe table does create a real native table, so the corruption is not a
failure to build the object — the object is right and its header is wrong. An
inline image *"degrades to a link"* rather than vanishing, which narrows RFC
0005's stated reason for rejecting image syntax without removing the reason. And
a table created this way is invisible to `listPageContent`, so `outline_page`
cannot produce an element ID for it, which means the one construct that
degrades worst is also the one construct element-scoped editing cannot reach.

A direct comparison settled the notation question on 2026-09-06. The same table
written as a markdown pipe table and as an HTML `<table>` produces objects
identical in kind — both `tableType: "table"`, `layout: "default"` — and
different in content. HTML preserves the header row as the table's column names
(`Column A`, `Column B`, two data rows). Markdown discards it, generates
`Column 1` and `Column 2`, and pushes the real header down into the data as a
third row. The API's page-content write takes `canvasContent: {format,
content}` and accepts both notations, so this was always a choice rather than a
constraint, and RFC 0005 made it on grounds that the evidence has now moved.

The deeper finding is that the notation is not the whole problem. Degradation
is a property of the **cycle**, not of any single write. One HTML write is
faithful. One markdown write builds a table with a wrong header. What compounds
without bound is reading content out of the document and writing it back in,
because export is lossy in a way that is not idempotent — each pass through it
adds damage the previous pass did not have. No choice of notation fixes a loop
that loses information on every turn; it only changes how fast.

## Decision

**Page content is written as HTML.** `canvasContent.format` is `html` for every
tool that writes page content. The evidence is narrow but decisive on the one
construct that matters: a table survives with its header, where markdown
corrupts it. Nothing else measured favours markdown except that a model
produces it more naturally, which is a cost paid once per call against a
corruption paid on every subsequent edit.

**A read is never a write source.** No tool accepts content that this server
produced. `read_page` returns a projection for a model to understand, and its
description says in terms that its output must not be sent back as content.
`outline_page` returns text for identification, not for round-tripping. Writes
carry content the caller composed. This is the rule that actually stops the
degradation B5 measured, and it is the rule RFC 0005 was missing rather than
the notation it chose: element-scoped editing is safe because it is scoped, not
because the content passing through it is faithful.

**Tabular content belongs to the row tools.** A model that wants to change data
in a table calls `update_row` or `upsert_rows`, which address cells directly and
do not pass through any notation at all. Writing a table as page content
remains possible — HTML makes it correct — but it is how a table is *created*,
never how one is *edited*.

**Image syntax is rejected in both notations.** RFC 0005 rejected markdown image
syntax on the grounds that the block would vanish from the next read. B3 found
it degrades to a link instead. A link is not what the caller asked for, and
silently substituting one for the other is the failure the rule exists to
prevent, so the rule stands with its reason corrected. `<img>` is rejected on
the same basis.

### The tool surface

Seventeen tools. Eleven are always on; six are registered only when
`SHDOC_ALLOW_DESTRUCTIVE` is set, and when it is unset they do not appear in
`list_tools` at all, so no per-call permission decision arises. MCP grants tool
permissions by name, and a single `edit_page` approved once — plausibly for a
harmless append — would thereafter also authorise whole-page replacement, so the
additive and destructive operations stay on separate permission surfaces.

Always on, reading:

- **`get_doc_overview`** — no parameters. Returns the page tree and the table
  list. At or below eight tables it also returns each table's column schema, so
  a model orients in one turn; above that threshold columns are omitted, the
  response says so, and the model is directed to `describe_table`. The threshold
  is bounded because the call costs `listPages` + `listTables` + one
  `listColumns` per table.
- **`describe_table`** — `table_id_or_name`. One table's column schema, from the
  same cache the row tools use, so calling it warms rather than duplicates.
- **`outline_page`** — `page_id_or_name`. The page's lines as an ordered list of
  `{element_id, style, level, text}`. Cheap, works with a read-only token, and
  is the only source of the stable element IDs that anchored editing requires.
  Its `text` is for identifying a line, not for editing and returning.
- **`read_page`** — `page_id_or_name`. The page as HTML. Expensive: it runs the
  asynchronous export flow, and it requires `contentType == "canvas"` — embed
  and sync pages cannot be exported and are refused with that reason. Rendered
  content is cached against the page's `updatedAt`. Its description states that
  it is a projection in which images, tables, buttons, controls, callouts and
  dividers may be missing or flattened, that it must not be treated as the
  document, and that it must not be sent back as write content.
- **`find_rows`** — `table_id_or_name`, optional filters, sort and limit. Pages
  internally up to the caller's cap and returns rows keyed by column name, each
  carrying its row ID. States that server-side filtering is one column and
  exact-value only, and that everything else is applied client-side after
  paging.
- **`get_row`** — `table_id_or_name`, `row_id`. One row, cells keyed by column
  name. The API returns them keyed by column ID, so the column schema is what
  resolves them.

Always on, writing:

- **`create_page`** — `name`, optional `subtitle`, `parent_page_id`, `content`.
- **`append_to_page`** — `page_id_or_name`, `content`, `position` (`append` |
  `prepend`). Additive only; it never removes existing content. RFC 0005 also
  listed an optional `element_id` here without saying what it did; it is
  removed rather than guessed at.
- **`replace_element`** — `page_id_or_name`, `element_id` (required), `content`.
  Replaces exactly one element. There is deliberately no way to spell "replace
  the whole page" with this tool.
- **`rename_page`** — `page_id_or_name`, `name`.
- **`upsert_rows`** — `table_id_or_name`, `rows`, optional `key_columns`.
- **`update_row`** — `table_id_or_name`, `row_id`, `cells`.

Gated behind the flag:

- **`delete_page`** — `page_id_or_name`.
- **`clear_page_content`** — `page_id_or_name`, optional `force`. Empties a page
  while leaving the page itself in place.
- **`delete_rows`** — `table_id_or_name`, `row_ids`.
- **`push_button`** — `table_id_or_name`, `row_id`, `column_id_or_name`.
  Destructive despite deleting nothing, because a button's underlying action
  *"can perform any action on the document, including writing to other tables
  and performing Pack actions"* — its blast radius cannot be declared in
  advance.
- **`overwrite_page`** — `page_id_or_name`, `content`, optional `force`.
- **`delete_element`** — `page_id_or_name`, `element_id`. RFC 0005 left this
  open rather than settling it in passing. It is settled here and gated: it is
  the targeted counterpart to `replace_element`, and a model that can replace one
  element but must call `overwrite_page` to remove one is being pushed toward the
  blunter tool, which is the opposite of what the gating is for.

Before any gated page operation, the guard lists the document's tables,
controls and formulas and filters them on `parent.id == pageId` — all three
schemas carry a `parent: PageReference`, which is what makes the check
possible. If the page owns any such object the tool refuses and names what it
found. A `force` parameter overrides the refusal. Note that this guard sees a
table that `outline_page` cannot, because it reads `listTables` rather than
`listPageContent`.

### Reporting

Write tools report **applied**, never *succeeded*, because `completed: true` is
what the API actually tells us. A poll that times out says the outcome is
unknown rather than asserting failure. Every write polls the mutation status
and surfaces any `warning` **verbatim**, since silent degradation is reported
there and nowhere else — and the field is absent rather than null when there is
none, so it is read as absent. Write tool descriptions state that an immediate
read-back may lag, because the snapshot lag is independent of mutation
application.

Rows are addressed by ID, never by name: the API accepts a name but affects
*"an arbitrary row"* on collision, for updates and deletes alike. Cell writes
send ISO 8601 dates only, and reject writes to calculated and button columns
before a request is made.

Retry after acceptance is permitted only for `GET`s and for upserts with
`key_columns` set, because there are no idempotency keys and replaying an
unkeyed upsert duplicates rows. A 429 carries no such restriction: it is
refused before the request executes, so nothing happened. The retry budget and
backoff belong to the `failure-policy` topic, not to this one — RFC 0005 sent
readers to `upstream-api` for them, which never had them.

## Alternatives considered

### Keep markdown and reject tables the way images are rejected

The narrowest change: leave the notation alone and refuse the one construct
that corrupts. It fails because tables are not the only casualty — B5 also
found blockquote continuations losing their `>` and horizontal rules losing the
blank lines around them — and because refusing tables in page content pushes a
model toward `overwrite_page`, the gated blunt instrument, to do something the
API supports natively. Rejecting a capability the platform has is a worse
answer than encoding it correctly.

### Keep markdown and forbid read-modify-write

This is half of what is decided above, without the notation change. It stops
the compounding, which is the severe failure, and leaves every single write
building tables with wrong headers. Since the evidence for HTML costs nothing
to act on and the API accepts both, taking only half of an available fix is
hard to justify.

### Choose the notation per call, letting the caller pass `format`

Superficially flexible and genuinely worse. The caller is a language model with
no way to know which constructs survive which notation, so the parameter
transfers a decision this RFC exists to make onto the party least equipped to
make it. It also doubles the surface every fidelity finding has to be checked
against, permanently.

### Detect tables in the content and switch notation automatically

Write HTML when the content contains a table and markdown otherwise. It needs a
markdown table parser to decide, which is the thing most likely to be wrong,
and it makes the notation — and therefore the fidelity — depend on content in a
way no caller can predict. A rule that behaves differently on inputs that look
alike is a rule nobody can reason about.

### Make `read_page` lossless instead

The most attractive option, and unavailable. The lossiness is in the vendor's
export, which this client does not control: the API offers markdown and HTML
projections of a canvas and nothing that round-trips. Fixing it would mean
reconstructing page content from `listPageContent`, which cannot see native
tables at all — so the reconstruction would be lossy in a different and less
predictable way.

### Supersede nothing, and record the format as a tuned constant

RFC 0005 pre-authorised exactly this: *"changing the format is a bounded change
to a constant rather than a supersede."* It is available for the notation alone
and insufficient for what the evidence found. The revisit trigger it wrote was
not about the constant — it said the *design* would need revisiting if
round-trip proved unstable, and the rule that a read is never a write source is
a new rule about the tool surface, not a new value for an old one.

## Consequences

**Makes easy.** A table written to a page keeps its header, which is the
difference between a table a person can read and one they have to repair. The
degradation that compounded per edit stops compounding, because the loop that
caused it no longer exists as a supported path. And the boundary between the
two ways of changing a table — content writes create, row tools edit — is
stated rather than left for a model to discover by damaging a document.

**Makes hard.** A model composing page content now writes HTML, which it does
less naturally than markdown and which is more verbose, so more of a call's
budget goes to the content itself. Anything that wants to edit existing prose
must now compose the replacement rather than reading it, adjusting it and
sending it back — which is a real ergonomic loss and the direct cost of not
having a lossless read. Rejecting `<img>` will read as arbitrary to a caller
who has just been told to write HTML.

**Commits us to.** HTML as the encoding for every page-content write, which is
expensive to reverse once documents contain content written that way. And to
the claim that no tool accepts server-produced content — a claim that has to be
maintained in every future tool's description, not just enforced once.

**Accepted risk.** `replace_element`'s element-scoping mechanism is still
unconfirmed: the only evidence that `contentUpdate` accepts an `elementId` is an
unrun probe, and the endpoint inventory does not list such a field. If it does
not exist, the tool cannot be built as specified and this RFC's central safe
primitive has no implementation — which would be a second revisit, on a
different question. The fidelity comparison behind the HTML decision is one
construct on one document; nothing has tested HTML round-trip stability, and
this RFC does not claim it is stable, only that it does not corrupt the
construct markdown corrupts. Writing content is the one thing this server does
that a person notices immediately, so a fidelity failure here is visible in a
way a throttling bug is not.

## Implementation notes
