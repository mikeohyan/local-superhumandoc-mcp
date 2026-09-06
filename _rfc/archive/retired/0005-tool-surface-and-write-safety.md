---
rfc: 0005
title: Expose element-scoped editing tools and gate destructive operations behind a flag
status: Superseded
created: 2026-09-03
decided: 2026-09-04
supersedes:
superseded_by: 0013
topic: tool-surface
commits: []
tags: [architecture, mcp, tools, safety]
---

# RFC 0005 — Expose element-scoped editing tools and gate destructive operations behind a flag

## Context

RFC 0004 settles that this project builds its own local, document-scoped MCP
server. This RFC settles what that server exposes to a model, and what stops the
model from destroying the document it was pointed at.

The obvious design — mirror the API, offer `read_page` and `write_page`, let the
model read markdown, edit it, and write it back — is the one the vendor
explicitly warns against. Announcing the very page-content endpoints this server
wraps, Coda's Jonathan Goldman wrote:

> "HTML and markdown can't perfectly represent all of the features of a Coda doc,
> so a round trip in either format may lose some information. **These endpoints
> are best used for import or export scenarios, not page editing.**"
>
> — *More powerful page endpoints in the Coda API*, 2 Nov 2023

That statement is the ceiling on any honest claim this server can make about
editing, and it forces the shape of everything below.

**The vendor's own MCP server agrees with the warning.** Superhuman ships an MCP
server over the same document model, and it offers **no whole-page replace at
all**. Its content-modification surface is entirely element-scoped —
`insert_element`, `replace_element_text`, `replace_text`, `delete_element`, each
anchored by an element ID — and it reads markdown with `[[elementId]]`
annotations for precisely that purpose. It treats tables, formulas, controls and
comments as content channels *separate from* markdown, and instructs callers that
"for tabular data, prefer `table_create` over Markdown tables". The team that owns
the document model, building for the same consumer, declined to offer the obvious
design. That is the strongest available evidence that the obvious design is wrong.

**Markdown loses specific, documented things.** The markdown importer supports
the "basic syntax" flavour only and "does not support text colors, highlights,
and other extended features" — basic syntax excludes tables, task lists,
strikethrough, footnotes and fenced code. Page-level images are *omitted from
markdown export* while surviving HTML export, staff-confirmed. So a
markdown read-modify-write cycle silently drops content, and whether a whole-page
`replace` additionally destroys native objects the payload cannot express —
tables, buttons, controls, callouts, dividers — is undocumented by anyone. It is
rated likely but remains **unconfirmed**; the evidence and a runnable test plan
are at `docs/validation/2026-09-03-markdown-fidelity-tests.md`.

**Writes are asynchronous and structurally cannot report failure.** Every
mutating endpoint returns HTTP 202 with a `requestId`, and
`GET /mutationStatus/{requestId}` returns the entire status schema:
`{"completed": bool, "warning": string?}`. There is no failure state, no error
field, no status enum. The documentation says an edit "may fail if invalid", but a
failed mutation has no representation — most plausibly `completed` simply never
becomes true, which is itself unverified. A poll loop's timeout path and its
failure path are therefore indistinguishable, and "applied" is the strongest
claim any tool here can honestly make. Malformed content is accepted with a 202
and degraded silently; `warning` is the only signal that it happened.

**Read-after-write is a second, independent lag.** Reads are served from a
document snapshot that may be stale relative to the browser. `completed: true`
means the edit reached the document; it does not mean the next read sees it. The
only documented remedy is an `X-Coda-Doc-Version: latest` header that returns 400
rather than waiting — and that header appears only in prose, declared on zero
operations in the specification.

**Reading a page as markdown costs a write-budget slot.** There is no synchronous
markdown read. The sequence is a metadata GET, a `POST .../export`, a poll, and a
fetch of a short-lived pre-signed link. Because step two is a POST it is charged
against a write budget rather than a read one, and a read-only-restricted token
cannot read page content at all — a scope consequence of the POST, independent of
any rate limit.

This RFC originally placed that POST in the doc-content write bucket recorded in
RFC 0008 — the tightest in the API — and concluded that an uncached page read
rate-limits the server by *reading*. **Probe P6 refuted that on 2026-09-04.** Six
export POSTs fired back-to-back all returned 202, exceeding that bucket's
published capacity, and export is served by a visibly separate backend pod class.
RFC 0008 carries the correction; the evidence is at
`docs/validation/2026-09-03-api-operational-probes.md`.

What P6 does **not** establish is which budget export does draw on. A six-request
burst is within the general write bucket's published capacity of 10 per 6
seconds, so that bucket is not excluded — the finding narrows the question rather
than closing it. Page reads are therefore cheaper than this RFC first assumed and
do not contend with page edits for the tightest bucket in the API, but they are
not free, they still require write scope, and caching them remains worthwhile on
latency alone: the export flow is four sequential round trips with a poll in the
middle, whatever it costs in budget.

**Row querying is far weaker than it looks.** The `query` parameter on `listRows`
accepts a single column and an exact value, with no operators — no `contains`, no
comparison, no `AND`/`OR`. Coda staff confirmed as recently as March 2025 that this
is unchanged. A model that constructs multi-condition filters will have them
silently ignored unless the tool says otherwise.

**Cell writes are asymmetric.** Reading with `valueFormat=rich` returns
structured JSON-LD values carrying relation row IDs and person emails; writing
accepts scalars only, so the object just read cannot be sent back. Matching for
relation and people columns is **exact** — the vendor's own help centre gives the
counterexamples, that "Molly" will not map to "Molly Rose" and "Launch Site" will
not map to "Launch the Website". Date parsing runs in a "loose mode" whose
interpretation depends on the document's regional settings, so an ambiguous
numeric date resolves differently in different documents. Images and attachments
are written as a publicly-accessible URL, or an array of them, which the API then
ingests; bytes are never accepted. The full evidence is at
`docs/validation/2026-09-03-cell-write-formats.md`.

**One capability we rely on is absent from the specification entirely.** Writing
a relation cell by referencing the target row's ID is staff-confirmed behaviour,
but the pinned OpenAPI document does not describe it anywhere: all nineteen
`rowId` occurrences are read-side, part of `RowsDelete`, or path parameters. A
client generated from the specification cannot discover the capability at all —
which is exactly why `orellazri/coda-mcp`, built from the same document, does not
have it, and a concrete instance of the general argument RFC 0004 makes for
building our own.

**One operation has unbounded blast radius.** `pushButton` invokes a button whose
underlying action "can perform any action on the document, including writing to
other tables and performing Pack actions". Nothing in the API declares what a
given button does before it is pressed.

## Decision

The server exposes **seventeen tools: twelve registered always, five registered
only when `SHDOC_ALLOW_DESTRUCTIVE` is enabled.** The always-on editing
vocabulary is element-scoped, matching the shape the vendor's own server settled
on.

### Always-on read tools

- **`get_doc_overview`** — no parameters. Returns the page tree and the table
  list. When the document has eight or fewer tables it also returns each table's
  column schema, so a model orients in one turn; above that threshold columns are
  omitted, the response says so, and the model is directed to `describe_table`.
  The threshold is bounded deliberately: this call costs `listPages` +
  `listTables` + one `listColumns` per table, so unbounded it would spend a large
  fraction of the read budget on orientation alone.
- **`describe_table`** — `table_id_or_name`. Returns one table's column schema,
  from the same cache the row tools use, so calling it warms rather than
  duplicates.
- **`outline_page`** — `page_id_or_name`. Returns the page's lines as an ordered
  list of `{element_id, style, level, text}`. Cheap, works with a read-only
  token, and is the only source of the stable element IDs that anchored editing
  requires.
- **`read_page`** — `page_id_or_name`. Returns the page as markdown. Expensive:
  it runs the asynchronous export flow, and it requires `contentType == "canvas"`
  — embed and sync pages cannot be exported and are refused with that reason.
  Rendered markdown is cached against the page's `updatedAt`, which is
  load-bearing rather than an optimisation.
- **`find_rows`** — `table_id_or_name`, optional filters, sort and limit. Pages
  internally up to the caller's cap and returns rows keyed by column name, each
  carrying its row ID.
- **`get_row`** — `table_id_or_name`, `row_id`.

### Always-on write tools

- **`create_page`** — `name`, optional `subtitle`, `parent_page_id`, `content`.
- **`append_to_page`** — `page_id_or_name`, `content`, `position`
  (`append` | `prepend`), optional `element_id`. Additive only; it never removes
  existing content.
- **`replace_element`** — `page_id_or_name`, **`element_id` (required)**,
  `content`. Replaces exactly one element. There is deliberately no way to spell
  "replace the whole page" with this tool.
- **`rename_page`** — `page_id_or_name`, `name`.
- **`upsert_rows`** — `table_id_or_name`, `rows`, optional `key_columns`.
- **`update_row`** — `table_id_or_name`, `row_id`, `cells`.

**`content` is markdown.** The API's page-content write takes
`canvasContent: {format, content}` with `markdown` and `html` both legal, so the
format is a choice this RFC has to make rather than a given. Markdown is chosen
because these are element-scoped edits — a paragraph, a heading, a list item —
where HTML is noise the model must generate correctly for no gain, and because
markdown is what a model produces naturally.

The choice has one known cost, and the tools state it rather than absorbing it.
Markdown export omits page-level attachments while HTML export retains them
(staff-confirmed), so an image cannot survive a markdown write-then-read.
Accordingly the write tools **reject markdown image syntax with an explicit
error** instead of creating a block that will vanish from the next read. The one
production pipeline surveyed chose `html` for exactly this reason, which is the
right trade for a documentation importer pushing whole pages and the wrong one
for element-scoped editing.

This is the write format for the tools in this surface, not a claim about which
format is better in general. If the fidelity tests show markdown mangling
constructs beyond images, changing the format is a bounded change to a constant
rather than a supersede — the decision here is that the format is **explicit and
declared**, not left to whatever the caller happens to send.

### Gated tools

These five are registered only when `SHDOC_ALLOW_DESTRUCTIVE` is **enabled**,
which means an explicit affirmative value and not merely a variable that exists.
RFC 0006 specifies the parser: `SHDOC_ALLOW_DESTRUCTIVE=false` leaves them
unregistered, as does any value the parser does not recognise.

- **`delete_page`** — `page_id_or_name`.
- **`clear_page_content`** — `page_id_or_name`, optional `force`.
- **`delete_rows`** — `table_id_or_name`, `row_ids`.
- **`push_button`** — `table_id_or_name`, `row_id`, `column_id_or_name`.
- **`overwrite_page`** — `page_id_or_name`, `content`, optional `force`.
  Replaces the entire page. `content` is markdown, as for the always-on write
  tools.

`push_button` is classified destructive despite deleting nothing, because its
blast radius is unbounded and cannot be declared in advance. `overwrite_page` is
whole-page replacement, and is the operation the vendor's warning is about.

`clear_page_content` empties a page while leaving the page itself in place. It
has its own endpoint — `DELETE .../pages/{id}/content`, which the specification
describes as deleting either named elements or all content — so it is a
first-class operation rather than a whole-page `replace` carrying an empty
payload. That does not make it gentler: emptying a page destroys exactly what
`overwrite_page` destroys, so **it carries the same pre-write guard** and the
same `force` override. Naming it separately is worth the duplication: "clear
this page" is a thing a model will try to express, and without the tool it would
reach for `overwrite_page` with an empty string, which is the more dangerous
habit to teach.

That endpoint also deletes **specific elements by ID**, a narrower destructive
primitive than this surface currently exposes. Whether that deserves its own
gated tool — a targeted `delete_element` to sit beside `replace_element` — is
left open here rather than settled in passing; the surface ships without it.
The endpoint inventory is at `docs/reference/api-operational-constants.md`.

### Three safety mechanisms

**1. Gated tools are not registered, not merely restricted.** When the flag is
unset they do not appear in `list_tools`, so the model cannot see them and cannot
call them, and no per-call permission decision arises. This is stronger than
relying on the client's tool-permission prompts, which are granted once and then
persist for the session.

**2. Additive and destructive editing are separate tools, on purpose.** The API's
`contentUpdate` object carries an `insertionMode` of `append | prepend | replace`,
which invites a single `edit_page` tool with a mode parameter. We do not do that,
for a reason external to the API: **MCP tool permissions in Claude Code are
granted per tool name.** A single `edit_page` approved once — plausibly for a
harmless append — would thereafter also authorise whole-page replacement.
Splitting keeps the additive operation and the destructive one on separate
permission surfaces, so an "always allow" on the safe one confers nothing
dangerous.

**3. `overwrite_page` and `clear_page_content` carry a pre-write guard.** They
are the only tools with one, and they have it because they are the only two that
destroy content they did not read — every other write is additive or
element-scoped. The mechanism differs between them, a write in one case and a
delete in the other, but the blast radius is the same page either way, so the
same check applies. Before writing, the guard lists the document's tables, controls
and formulas and filters them on `parent.id == pageId` — all three schemas carry
a `parent: PageReference`,
which is what makes the check possible. If the page owns any such object the tool
**refuses** and names what it found. A `force` parameter overrides the refusal.
The flag governs whether the tool exists; the guard governs whether a particular
call is safe.

### Reporting rules

These apply to every tool and are not negotiable per-tool:

- Write tools report **applied**, never *succeeded*, because `completed: true` is
  what the API actually tells us. A poll that times out says the outcome is
  unknown rather than asserting failure.
- Every write polls `getMutationStatus` and surfaces any `warning` **verbatim**,
  since silent degradation is reported there and nowhere else.
- Write tool descriptions state that an immediate read-back may lag, because the
  snapshot lag is independent of mutation application.
- `read_page` declares its own lossiness in its description: markdown is a
  projection in which images, tables, buttons, controls, callouts and dividers may
  be missing or flattened, and it must not be treated as the document.
- `find_rows` states that server-side filtering is one column and exact-value
  only, and that everything else is applied client-side after paging.
- Rows are addressed by ID, never by name. The API accepts a name but affects "an
  arbitrary row" on collision, for updates and deletes alike.
- Cell writes send ISO 8601 dates only, and reject writes to calculated and button
  columns before a request is made.
- **A 429 and a timeout are different failures and are retried differently.** A
  429 is refused before the request executes, so replaying it is safe on every
  method, including an unkeyed upsert — nothing happened. A timeout or a
  connection drop *after* the request was accepted is the dangerous case: the
  mutation may be in flight, and there are no idempotency keys, so replaying an
  unkeyed upsert duplicates rows. Retry after acceptance is therefore permitted
  only for GETs and for upserts with `key_columns` set, while a 429 carries no
  such restriction. Conflating the two costs correctness in one direction and
  throughput in the other: treating every 429 as unsafe makes writes fail that
  never reached the server, and treating every timeout as safe silently
  duplicates data. The retry budget and backoff are RFC 0008's.

## Alternatives considered

### A single `edit_page` tool with a `mode` parameter

Mirrors the API's own `contentUpdate` shape exactly, and is the smaller surface:
one tool instead of three. An earlier draft of this design used it. Rejected
because Claude Code grants MCP tool permissions per tool name, so one tool
spanning append and whole-page replace lets an approval granted for the safe
operation silently authorise the destructive one. The API's shape is a poor guide
here because the API has no concept of a persisted per-tool permission.

### A thin one-to-one mirror of the API

One tool per endpoint, roughly twenty-five of them, mechanically complete and
trivially checkable against the specification. Rejected because it is built for an
HTTP client rather than an agent. The model would spend turns chaining calls, would
have to know that reading a page means starting an asynchronous export and polling
it, and would carry twenty-five near-identical descriptions in context.
Completeness of that kind costs quality.

### Expose everything and rely on the client's permission prompts

Maximum capability, no flag, no gating — let the host ask the user before each
call. Rejected because those approvals persist: a single "always allow" on a
delete tool removes the safety net permanently, and the user who granted it was
most likely approving one specific deletion. A tool that is never registered
cannot be approved by accident.

### Never expose deletes at all

Ship only reads and non-destructive writes; handle deletion by hand in the
browser. Genuinely safe, and briefly tempting. Rejected because it makes real
workflows impossible — clearing stale rows from a tracker is ordinary work, not an
exceptional act — and because a flag that is off by default already delivers most
of the safety without forcing the user out of the tool.

### A global read-only mode in addition to the destructive flag

A second switch stripping every write tool, so the same server could be pointed at
a production document for context and a scratch document for editing. Rejected as
redundant for now: an API token can itself be scoped to read-only, and the API
enforces that server-side, which is a stronger guarantee than a client-side flag.
Worth revisiting if operating the same token against two documents becomes common.

### One page-read tool with a `format` parameter

Route `plaintext` to the cheap synchronous endpoint and `markdown` to the export
flow, behind a single `read_page`. Fewer tools, and the cost difference could be
explained in the description. Rejected on two grounds: it merges an operation
usable with a read-only token and one requiring write scope into a single
permission surface, and it hides the element IDs — which only the cheap path
produces and which anchored editing depends on — behind a parameter the model must
know to set. Keeping `outline_page` distinct makes the IDs discoverable on the
tool that produces them.

### Whole-page replace with the guard but without the flag

Ship `overwrite_page` always-on, relying on the tables/controls/formulas guard
alone. Rejected because the guard only detects objects the API enumerates. Callouts,
dividers, inline images and embeds have no such listing and would be destroyed
without warning, so the guard cannot be the sole protection for an operation the
vendor says not to perform.

## Consequences

**Makes easy.** A model orients in one call and edits without reading an entire
page first. Anchored edits touch one element, so they neither depend on markdown
round-trip stability nor produce spurious diffs across untouched content. The
dangerous operation is absent by default, and when present it refuses the cases it
can detect. Honest reporting means a model is told when an outcome is unknown
instead of inferring success from a 202.

**Makes hard.** `find_rows` does most filtering client-side, so it pages the table
and will be slow — and expensive against the read budget — on large tables; a
filtered view in the document remains the faster answer for hot queries. Anchored
editing requires an `outline_page` call first to obtain element IDs, so a
single logical edit costs two round trips. Users who genuinely want whole-page
replacement must set an environment variable and then pass `force`, which is
friction by design but is still friction.

**Commits us to.** A tool surface that is deliberately narrower than the API, and
to defending that narrowness against the recurring, reasonable-sounding suggestion
to "just add a write_page". Reversing the element-scoped decision means
superseding this RFC. It also commits the implementation to polling
`getMutationStatus` on every write, which spends read budget on each mutation, and
to a per-endpoint mutation helper rather than a generic "if 202 then poll" rule —
some endpoints outside this surface return 202 with no `requestId` at all.

**Evidence weaker than the rest of the surface, in one place.** Relation writes by
row ID rest on staff statements rather than on the pinned specification, because
the specification does not describe them. RFC 0008's drift-detection fingerprint
therefore cannot catch a change to this behaviour: the document could stay
byte-identical while the parser's treatment of row IDs changed underneath us. This
is the one capability here supported on that footing, and confirming it is part of
what `docs/validation/2026-09-03-cell-write-formats.md` exists to do.

**Accepted risk, unresolved.** Whether whole-page `replace` actually destroys
native objects is rated likely and remains unconfirmed; the guard and the flag are
sized for the pessimistic case. Whether markdown export is round-trip stable is
also unconfirmed — if it is not, even element-scoped read-modify-write degrades
content over repeated edits, and this design would need revisiting. Both are
settled by running `docs/validation/2026-09-03-markdown-fidelity-tests.md`, which
requires a token and a throwaway document. The threshold of eight tables in
`get_doc_overview`, and the poll intervals and deadlines recorded in
`docs/reference/`, are judgements rather than measurements and are named constants
so they can be tuned once real documents are observed.

**A cost paid by the user, not just the code.** Reporting "applied" rather than
"succeeded", and saying an outcome is unknown on timeout, will sometimes read as
evasiveness. It is the accurate description of what the API returns, and the
alternative is a server that confidently reports success for writes that were
silently degraded.

## Implementation notes

Left empty at Proposed.
