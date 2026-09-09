# MCP tool surface — live validation plan

**Date:** 2026-09-08
**Target:** the 18 tools registered by `superhumandoc_mcp.server.build_server`, driven through an in-process `mcp.Client` against the live API
**Status:** RUN TWICE on 2026-09-08, against the same scratch doc. First run:
L0, L1, L2 and L3 all passed in full; L4 passed four of its five checks, with
L4b (`clear_page_content`) failing against the pass condition as originally
written. That run's findings prompted two fixes — `clear_page_content`'s tool
description and `create_page`/`upsert_rows` id reporting — recorded under
"What this run changed" below. Second run, after both fixes: 35 PASS, 0 FAIL,
1 SKIP of 36 checks. L4b now passes, against a pass condition corrected to
match the API's measured behaviour rather than a changed tool; three checks
were added to confirm the id-reporting fixes live. `push_button` was
deliberately not run in either run, per "Before you run this" above. The
Results section below carries the raw output of both runs, clearly labelled.
An empty slot there means untested — it does not mean the test ran clean.

## What this plan settles

Every tool this server registers, except `read_page`, has only ever been
exercised against mocks. `read_page` got a live pass on 2026-09-08 (recorded
in the `tool-surface` topic's Implementation notes), but the other seventeen
have not been called through anything resembling the boundary a real client
crosses. That gap already cost this project a shipped, unusable tool once:
`find_rows`'s registered wrapper in `superhumandoc_mcp.tools.reads` was
annotated `-> list[dict]` while the function it wraps returns
`{rows, complete, note}`. The SDK validates a tool's return value against its
declared annotation, so every real call failed that validation and the model
saw "Error executing tool find_rows" — while every unit test for `find_rows`
passed, because every one of them called the underlying function directly and
never went through tool registration at all. A green suite and a broken tool
coexisted for as long as nothing called through the boundary.

The fix for that class of defect is not a better unit test — it's a test that
cannot be fooled the same way, because it is not a unit test. This plan drives
every registered tool through an in-process `mcp.Client`, the same boundary a
real MCP host crosses, against the live API rather than a mock. It is the
first time all eighteen tools will have been called this way, and the first
time any of them (`read_page` excepted) will have been called against real
data at all.

## Before you run this

- Runs against the throwaway scratch doc `6vqpBu-VYd` ("MCP Validator"). Its
  id is pinned as a literal in the driver, not read from `$SHDOC_DOC_ID` — a
  driver that reads the id from the environment could be pointed at a real
  document by an unrelated config change and this plan is destructive. The
  driver asserts the resolved doc id equals `6vqpBu-VYd` at startup and aborts
  before making any other call if it does not.
- The token is never printed. Every recorded transcript redacts it as
  `<token>`.
- Destructive steps act only on a page this run creates and rows this run
  inserts. Nothing that already exists in the document is deleted, cleared,
  overwritten or renamed.
- `push_button` is deliberately not run. `test-table-02` (`grid-EETnwpzofr`)
  carries a button column whose action was never recorded by any earlier
  validation run, and the API specification's own warning for this operation
  is that a button can perform any action on the document — including writing
  to other tables and running Pack actions — with no way to predict which
  from the outside. A blast radius that cannot be stated in advance is not one
  this plan accepts for a scratch doc other validation runs also depend on.
  `push_button` stays mock-only; this is recorded as a known gap, not an
  oversight.
- Writes are paced by the client's own doc-content-write self-throttle, not
  by anything added for this plan. Row mutations were previously measured
  (see `docs/validation/2026-09-03-api-operational-probes.md`, P8) completing
  16-23 seconds after being sent, and this plan issues several. Expect the
  full run to take roughly 15 minutes, almost all of it spent waiting on
  mutations to land rather than on anything CPU-bound.
- Do not extend any retry or poll loop below to "get a cleaner signal." A
  loop that doesn't converge in the stated number of attempts is itself a
  result — record it as such rather than widening the loop until it passes.

## Document state read live on 2026-09-08

PAGES (10):

| Page id | Name | contentType | Parent |
|---|---|---|---|
| `canvas-4LiD-eeMTK` | test-page-01 | canvas | — |
| `canvas-fiFAJhhuKC` | test-page-02 | canvas | — |
| `canvas-3zcCCEtuyP` | test-subpage-02 | canvas | `canvas-fiFAJhhuKC` |
| `canvas-9hl0iPSWQb` | test-table-02 | **table** | `canvas-fiFAJhhuKC` |
| `canvas-VTK4j7fF0-` | test-table-01 | **table** | — |
| `canvas--WjjZil_19` | TORTURE-MD | canvas | — |
| `canvas-ceyUJcCKU8` | TORTURE-HTML | canvas | — |
| `canvas-JyBW6sOWuB` | TORTURE-GEN2 | canvas | — |
| `canvas-9p61hMYYmH` | b6-20260907T145220Z | canvas | — |
| `canvas-wzBw5Lq3v6` | b6-20260907T145220Z | canvas | — |

TABLES (5) and the page each reports as its parent:

| Table id | Name | Parent page id | Parent page name |
|---|---|---|---|
| `grid-PH5-RNMCB1` | test-table-01 | `canvas-VTK4j7fF0-` | test-table-01 |
| `grid-EETnwpzofr` | test-table-02 | `canvas-9hl0iPSWQb` | test-table-02 |
| `grid-D53nA4DcMR` | Table 1 | `canvas--WjjZil_19` | TORTURE-MD |
| `grid-vSs9GXsAi0` | Table 2 | `canvas-ceyUJcCKU8` | TORTURE-HTML |
| `grid-gmDtYP_rKK` | Table 3 | `canvas-JyBW6sOWuB` | TORTURE-GEN2 |

`listControls` returned 0 items and `listFormulas` returned 0 items against
this document. The pre-write guard (`superhumandoc_mcp.tools.guard.objects_owned_by_page`)
has three arms — tables, controls, formulas — and only the table arm can be
exercised here; the control and formula arms cannot be driven against real
data by this plan or any other run against this document, for lack of a
control or a formula to find.

Two pages share the name `b6-20260907T145220Z` (`canvas-9p61hMYYmH` and
`canvas-wzBw5Lq3v6`). Addressing a page by that name is therefore ambiguous —
whichever tool resolves it first wins, and which one that is is not specified
anywhere a caller can rely on. This plan avoids naming either of them by that
shared name and always uses their ids instead.

This inventory contradicts what `docs/validation/2026-09-03-cell-write-formats.md`
and `docs/validation/2026-09-03-api-operational-probes.md` recorded for this
same document: one page, two tables. The document has since gained the
TORTURE-* pages and the b6-* pages from later validation runs (markdown/HTML
fidelity testing and packaging/build probes respectively), so the shape
recorded in those two files describes an earlier state of the same scratch
doc, not a discrepancy to resolve.

## Inventory of the tests

| Test | What it settles | Destructive? |
|---|---|---|
| L0 | Does the destructive-tool gate actually change what `list_tools` reports? | No |
| L1 | Do all six read tools work through the MCP boundary against real data? | No |
| L2 | Does the pre-write guard refuse a page that really owns a table? | No — refusals only |
| L3 | Do the six always-on write tools work, and is `upsert_rows` really replay-safe? | **Yes — creates a page and rows** |
| L4 | Do the five testable gated tools work? | **Yes — deletes only what L3 made** |

---

# Test plan

## L0. Does the destructive-tool gate change what `list_tools` reports?

**Question.** `superhumandoc_mcp.server.build_server` registers the six gated
write tools only when `config.allow_destructive` is set, and never at request
time — the `tool-surface` topic (see `_rfc/README.md`) treats this as a
build-time registration decision, not a runtime refusal a present-but-disabled
tool would issue. This test settles whether the running server actually
behaves that way, rather than the code merely reading as though it should.

**Calls.** Build the server twice, once with `allow_destructive` unset and
once with it set, and call `list_tools` against each through `mcp.Client`.

**Pass condition.** With the flag off, `list_tools` reports exactly these 12
names: `append_to_page`, `create_page`, `describe_table`, `find_rows`,
`get_doc_overview`, `get_row`, `outline_page`, `read_page`, `rename_page`,
`replace_element`, `update_row`, `upsert_rows`. With it on, those 12 plus
`clear_page_content`, `delete_element`, `delete_page`, `delete_rows`,
`overwrite_page`, `push_button` — 18 in total. No name appears that isn't on
one of these two lists, and no name is missing from the list its flag setting
predicts. Note that a pass here confirms registration, not authorization: the
gate decides which tools *exist* for a given server instance, so there is no
"tool present but refuses" case to test separately.

## L1. Do all six read tools work through the MCP boundary against real data?

**Question.** Every read tool's unit tests call the underlying function
directly. This is the first time any of them (`read_page` aside) will be
called the way a real client calls them, against the document inventoried
above.

**Calls and pass conditions:**

- `get_doc_overview()`. This document has 5 tables, at or below the
  `OVERVIEW_INLINE_COLUMNS_MAX_TABLES` threshold documented in
  `docs/reference/api-operational-constants.md`, so every table dict in the
  result must carry a `columns` key, and the key `columns_omitted` must be
  **absent** from the result entirely — its presence would mean the inlining
  threshold was miscounted or misapplied.
- `outline_page(page_id_or_name="canvas--WjjZil_19")` (TORTURE-MD). Passes if
  it returns without error; its output is also the baseline L2 later compares
  against byte-for-byte.
- `describe_table(table_id_or_name="grid-PH5-RNMCB1")` (test-table-01).
- `find_rows(table_id_or_name="grid-PH5-RNMCB1")`. Must return a dict with
  exactly the keys `rows`, `complete`, `note` — no more, no fewer, which is
  exactly the shape whose annotation mismatch broke this tool the first time
  it shipped. `note` must be `None` when `complete` is `True`.
- `get_row(table_id_or_name="grid-PH5-RNMCB1", row_id=<a row id taken from
  the `find_rows` call above>)`. The pass condition is that the returned
  cells are keyed by **column name** (e.g. `Name`), not by column id — that
  is the one fact that proves this call actually resolved the live schema
  rather than echoing whatever key shape the row endpoint happened to hand
  back.
- `read_page(page_id_or_name="canvas--WjjZil_19")`, called twice in a row.
  The second call must be dramatically faster than the first — that gap is
  the only externally observable evidence that `PageCache` in
  `superhumandoc_mcp.tools.reads` actually served the second call from cache
  rather than re-exporting.
- `read_page(page_id_or_name="canvas-VTK4j7fF0-")` (test-table-01, a page
  whose `contentType` is `table`, not `canvas`). This call must be refused,
  naming the `contentType` found. `read_page` only ever accepts
  `contentType == "canvas"` positively rather than excluding known-bad
  values, so this is the first opportunity to exercise that refusal branch
  against a real `table`-typed page — it was previously believed untestable
  against this document, back when the document had no `table`-typed page at
  all.

## L2. Does the pre-write guard refuse a page that really owns a table?

**Question.** `superhumandoc_mcp.tools.guard.objects_owned_by_page` and the
`_refuse_if_page_owns_hidden_objects` check in `superhumandoc_mcp.tools.writes`
exist because `outline_page` is built on `listPageContent`, and a table,
control or formula chip written to a page never appears there — a page that
reads as empty to `outline_page` can still own objects a destructive write
would silently destroy. This test settles whether the guard actually stops
such a write on live data, using `canvas--WjjZil_19` (TORTURE-MD), which owns
`grid-D53nA4DcMR` per the inventory above.

**Calls.** Against `canvas--WjjZil_19`, with `force=False` (the default) in
every case: `delete_page`, `clear_page_content`, `overwrite_page`, and
`delete_element` (with any element id, since the guard must fire before the
element id is even considered).

**Pass condition.** Every one of the four calls fails, and each failure's
error names the table found — `grid-D53nA4DcMR` — exactly as
`_refuse_if_page_owns_hidden_objects` is written to report. After all four
refusals, `outline_page("canvas--WjjZil_19")` is called again and its result
compared byte-for-byte against L1's earlier call on the same page. Identical
output is what proves the four refused calls destroyed nothing.

**Not tested.** `force=True` against a page that genuinely owns objects is
not exercised anywhere in this plan. The v1 API this project targets cannot
create a table, so a table destroyed by a forced write on this scratch
document is not something a later run can recreate — the loss would be
permanent. `force` is only ever exercised (in L4) against a page this same
run creates and confirms owns nothing. Whether `force=True` correctly
bypasses the guard and completes the destructive write on a page that truly
owns something stays unproven after this plan runs, same as before it.

## L3. Do the six always-on write tools work, and is `upsert_rows` really replay-safe?

**Question.** `create_page`, `append_to_page`, `rename_page`,
`replace_element`, `update_row` and `upsert_rows` are the six always-on write
tools. None has been called through the MCP boundary against a live document.
`upsert_rows`'s own description claims it is replay-safe — calling it twice
with the same key columns and the same rows should not create duplicates —
and that claim has never been tested against the real API, only assumed from
reading the code.

**Calls, in order:**

1. `create_page(name="MCP-LIVE-<UTC timestamp>")`. The created page is the
   object every later step in L3 and all of L4 acts on.
2. `rename_page(page_id_or_name=<id from step 1>, name=<new name>)`.
3. `append_to_page(page_id_or_name=<id from step 1>, content=...)`, then
   a second call with `insertionMode` effectively prepending (per the
   `tool-surface` topic's read-write-cycle decision) — confirms both
   insertion directions work.
4. `replace_element(page_id_or_name=<id from step 1>, element_id=<an id
   from the page just written>, content=...)` — replaces exactly one
   element.
5. `upsert_rows(table_id_or_name="grid-PH5-RNMCB1", key_columns=["Name"],
   rows=[<two new rows>])`. Confirm two rows are added.
6. Run the **identical** call from step 5 again, same key columns, same row
   payload. This is the actual test of the replay-safety claim: read the
   table back afterward and confirm the row count did not increase versus
   after step 5. Growth here would mean `upsert_rows` matched on nothing and
   inserted a duplicate instead of updating in place.

**Two negatives that must be refused before anything is sent to the API**
(both are input-validation refusals from `superhumandoc_mcp.cells`, checked
against the cached schema before any request leaves the client):

- `update_row` naming the calculated column `Modified by` — must be refused
  as a calculated-column write, per `cells_for_write`'s check in
  `superhumandoc_mcp.cells`.
- `update_row` naming a column that does not exist on the target table —
  must be refused as an unresolvable column name, not sent to the API and
  misinterpreted there.

**Pass condition.** Every successful write above reports `outcome: "applied"`
in its `MutationOutcome`. Because the document's own read-after-write
snapshot lags behind its mutations (measured at 16-23 seconds in
`docs/validation/2026-09-03-api-operational-probes.md`, P8), every write is
confirmed by reading the affected page or table back afterward, retrying the
read on a short interval until the change is visible or a generous timeout is
reached — a single immediate read-back that finds nothing is not evidence the
write failed.

## L4. Do the five testable gated tools work?

**Question.** With `allow_destructive` on, `delete_element`,
`clear_page_content`, `overwrite_page`, `delete_rows` and `delete_page` have
never been called through the MCP boundary against real data. This test
settles whether they work, acting exclusively on the page L3 created and the
rows L3 inserted — never on anything pre-existing in the document.

**Calls, in order, all against the page and rows L3 created:**

1. `delete_element(page_id_or_name=<L3's page>, element_id=<one of the
   elements L3 wrote>, force=False)`. This page owns no table, control or
   formula, so the pre-write guard should pass it through without needing
   `force=True` at all — record whether it does.
2. `clear_page_content(page_id_or_name=<L3's page>, force=False)`, for the
   same reason.
3. `overwrite_page(page_id_or_name=<L3's page>, content=..., force=True)`.
   This is the one call in this plan that passes `force=True`, and it does so
   deliberately against a page already confirmed to own nothing — this is
   the safe way to exercise the `force` flag's code path at all, per the
   limit stated in L2.
4. `delete_rows(table_id_or_name="grid-PH5-RNMCB1", row_ids=<the two row ids
   L3 inserted>)`.
5. `delete_page(page_id_or_name=<L3's page>, force=False)`, as the final
   cleanup step — by this point the page owns nothing, so no `force` should
   be needed.

**Pass conditions.** Steps 1-3 and 5 each report a successful outcome.
`delete_rows` (step 4) must return per-row entries each carrying `index`,
`outcome` and `warning`, plus the batch-level `chunks` and `resume_from`
keys documented in `superhumandoc_mcp.tools.writes` — `resume_from` must be
`None`, since nothing here is large enough to be left unattempted partway
through a chunked batch. After step 5, a fresh `listPages`-backed read (or
equivalent) confirms the page L3 created no longer exists, and a fresh read
of `grid-PH5-RNMCB1` confirms it has exactly the row count it had before L3
ran.

**Not run.** `push_button` is not run in this test or anywhere in this plan.
See "Before you run this" above: `test-table-02`'s button column has an
action nobody has recorded, and the API specification's own warning states a
button's blast radius can extend to any part of the document, including
tables and Pack actions this test has no way to anticipate or undo. It
remains mock-only.

---

# Results

*An empty section below means the corresponding test has not been run — not
that it ran and produced no findings. Fill in `_Verdict:_` and `_Evidence:_`
under each heading only once that test has actually executed against the
live document; do not mark a slot done from reading the code that it should
pass.*

**Run date:** 2026-09-08
**Doc used:** `6vqpBu-VYd` ("MCP Validator"), matching the pin in "Before you
run this" above; the driver asserted this before making any other call.
**Driver totals:** 59 tool calls, 486.2s elapsed, 31 PASS / 1 FAIL / 1 SKIP of
33 checks.

```
==============================================================================
SUMMARY
==============================================================================
  ID     STATUS  DESCRIPTION
  ------ ------- ---------------------------------------------------
  L0a    PASS    flag off registers exactly the 12 always-on tools
  L0b    PASS    flag on registers exactly 18 tools (12 + 6 gated)
  L1a    PASS    get_doc_overview returns pages + tables + columns
  L1b    PASS    outline_page on TORTURE-MD
  L1c    PASS    describe_table on grid-PH5-RNMCB1
  L1d    PASS    find_rows shape is {rows, complete, note}
  L1e    PASS    get_row returns name-keyed cells
  L1f    PASS    read_page is cached on the second call
  L1g    PASS    read_page refuses a contentType=table page
  L2d    PASS    delete_element refuses on a page that owns a table
  L2c    PASS    overwrite_page refuses a page that owns a table
  L2b    PASS    clear_page_content refuses a page that owns a table
  L2a    PASS    delete_page refuses a page that owns a table
  L2e    PASS    TORTURE-MD is byte-for-byte unchanged
  L3a    PASS    create_page applies
  L3a2   PASS    resolve the created page's id
  L3b    PASS    rename_page applies and is visible
  L3c    PASS    append_to_page (append) applies
  L3d    PASS    append_to_page (prepend) applies
  L3e    PASS    prepend/append land in the right order
  L3f    PASS    replace_element rewrites one line
  L3g    PASS    upsert_rows reports one outcome per row
  L3g2   PASS    the upserted rows become visible
  L3h    PASS    a repeated keyed upsert updates, not duplicates
  L3i    PASS    update_row writes a typed cell
  L3j    PASS    update_row refuses a calculated column
  L3k    PASS    update_row refuses an unknown column
  L4a    PASS    delete_element on the created page
  L4b    FAIL    clear_page_content on the created page
  L4c    PASS    overwrite_page with force=True on the created page
  L4d    PASS    delete_rows removes the rows this run inserted
  L4e    PASS    delete_page on the created page
  L4f    SKIP    push_button

  PASS 31   FAIL 1   SKIP 1   (of 33 checks)

  Failures:
    L4b  clear_page_content on the created page
          applied, but outline still has 1 lines after 90s

  tool calls made: 59
  elapsed: 486.2s
```

## L0

_Verdict:_ PASS. Both halves of the gate were confirmed live for the first
time — this is the first time `list_tools` has actually been checked against
a running server for either setting of `allow_destructive`, rather than read
off `superhumandoc_mcp.server.build_server`.

_Evidence:_

```
[PASS] L0a  flag off registers exactly the 12 always-on tools
       12 tools
[PASS] L0b  flag on registers exactly 18 tools (12 + 6 gated)
       18 tools
```

With the flag off, `list_tools` reported exactly 12 tools. With it on, exactly
18. Neither count needed correcting against the plan's predicted name lists.

## L1

_Verdict:_ PASS, all seven checks.

_Evidence:_

```
[PASS] L1a  get_doc_overview returns pages + tables + columns
       10 pages, 5 tables
[PASS] L1b  outline_page on TORTURE-MD
       38 lines; first element cl-0Tj_qPM-_I
[PASS] L1c  describe_table on grid-PH5-RNMCB1
       columns: ['Name', 'number', 'date', 'Notes', 'checkbox', 'dropdown', 'Modified by', 'Modified on']
[PASS] L1d  find_rows shape is {rows, complete, note}
       5 rows, complete=True, first row_id=i-t9LSfemxfl
[PASS] L1e  get_row returns name-keyed cells
       cell keys: ['Modified by', 'Modified on', 'Name', 'Notes', 'checkbox', 'date', 'dropdown', 'number']
[PASS] L1f  read_page is cached on the second call
       first call 5.21s, second call 0.11s; 7726 chars of identical html
[PASS] L1g  read_page refuses a contentType=table page
       error: Error executing tool read_page: page 'canvas-VTK4j7fF0-' has contentType 'table', so it cannot be exported — only canvas pages can be read this way.
```

Three findings worth calling out specifically:

- `get_row` (L1e) returned cells keyed by column **name** —
  `['Modified by', 'Modified on', 'Name', 'Notes', 'checkbox', 'date',
  'dropdown', 'number']` — not by column id. That is the fact the plan named
  as the pass condition: it confirms live schema resolution rather than the
  call echoing back whatever key shape the row endpoint happened to hand
  back.
- `read_page`'s second call was served from cache, not re-exported:
  `first call 5.21s, second call 0.11s; 7726 chars of identical html`.
- `read_page` refused `canvas-VTK4j7fF0-` because its `contentType` is
  `table`: `Error executing tool read_page: page 'canvas-VTK4j7fF0-' has
  contentType 'table', so it cannot be exported — only canvas pages can be
  read this way.` The plan's own L1 text records this branch as "previously
  believed untestable against this document, back when the document had no
  `table`-typed page at all" — it is now confirmed against real data.

## L2

_Verdict:_ PASS, all five checks.

_Evidence:_

```
target page canvas--WjjZil_19, which owns table grid-D53nA4DcMR. Every call below is expected to REFUSE.
precheck: objects_owned_by_page('canvas--WjjZil_19') -> {'tables': ['grid-D53nA4DcMR'], 'controls': [], 'formulas': []}
precheck passed: the guard sees the table, so a refusal is the expected answer and the calls below are safe to make.
       full refusal text for delete_element:
         Error executing tool delete_element: Page 'canvas--WjjZil_19' owns objects this write cannot see and would destroy: tables grid-D53nA4DcMR. outline_page only sees canvas text — a table, control or formula chip written to a page never appears there, only in listTables/listControls/listFormulas, which is what this guard reads instead. Pass force=True to proceed anyway.
[PASS] L2d  delete_element refuses on a page that owns a table
       refused, and the message names the table
       full refusal text for overwrite_page:
         Error executing tool overwrite_page: Page 'canvas--WjjZil_19' owns objects this write cannot see and would destroy: tables grid-D53nA4DcMR. outline_page only sees canvas text — a table, control or formula chip written to a page never appears there, only in listTables/listControls/listFormulas, which is what this guard reads instead. Pass force=True to proceed anyway.
[PASS] L2c  overwrite_page refuses a page that owns a table
       refused, and the message names the table
       full refusal text for clear_page_content:
         Error executing tool clear_page_content: Page 'canvas--WjjZil_19' owns objects this write cannot see and would destroy: tables grid-D53nA4DcMR. outline_page only sees canvas text — a table, control or formula chip written to a page never appears there, only in listTables/listControls/listFormulas, which is what this guard reads instead. Pass force=True to proceed anyway.
[PASS] L2b  clear_page_content refuses a page that owns a table
       refused, and the message names the table
       full refusal text for delete_page:
         Error executing tool delete_page: Page 'canvas--WjjZil_19' owns objects this write cannot see and would destroy: tables grid-D53nA4DcMR. outline_page only sees canvas text — a table, control or formula chip written to a page never appears there, only in listTables/listControls/listFormulas, which is what this guard reads instead. Pass force=True to proceed anyway.
[PASS] L2a  delete_page refuses a page that owns a table
       refused, and the message names the table
[PASS] L2e  TORTURE-MD is byte-for-byte unchanged
       38 lines, identical to L1b
```

**A safety change was made to the driver before this phase ran, and it is
part of the evidence, not incidental to it.** Before issuing any of the four
"expected to refuse" calls, the driver calls
`superhumandoc_mcp.tools.guard.objects_owned_by_page` directly, read-only,
against `canvas--WjjZil_19`, and L2 runs only if that precheck reports the
table. A guard that merely assumed the table was still there — a "blind
guard" — would mean the four calls this phase makes are not refusal checks at
all: they are `delete_page`, `overwrite_page`, `clear_page_content` and
`delete_element` against a page that, absent the table, is a normal writable
page, and each would actually apply and destroy the page (and, for
`delete_page`, everything on it, including the table itself). The precheck
confirms the guard's premise before the run leans on it:

```
precheck: objects_owned_by_page('canvas--WjjZil_19') -> {'tables': ['grid-D53nA4DcMR'], 'controls': [], 'formulas': []}
precheck passed: the guard sees the table, so a refusal is the expected answer and the calls below are safe to make.
```

The four cases also run in a different order from the one the plan's Calls
section lists (`delete_page, clear_page_content, overwrite_page,
delete_element`): the driver reordered them least-destructive-first —
`delete_element`, then `overwrite_page`, then `clear_page_content`, then
`delete_page` — and the loop aborts on the first call that is not refused,
rather than running all four regardless. Each of the four refused, naming the
table:

- `delete_element`: `Error executing tool delete_element: Page
  'canvas--WjjZil_19' owns objects this write cannot see and would destroy:
  tables grid-D53nA4DcMR. outline_page only sees canvas text — a table,
  control or formula chip written to a page never appears there, only in
  listTables/listControls/listFormulas, which is what this guard reads
  instead. Pass force=True to proceed anyway.`
- `overwrite_page`: `Error executing tool overwrite_page: Page
  'canvas--WjjZil_19' owns objects this write cannot see and would destroy:
  tables grid-D53nA4DcMR. outline_page only sees canvas text — a table,
  control or formula chip written to a page never appears there, only in
  listTables/listControls/listFormulas, which is what this guard reads
  instead. Pass force=True to proceed anyway.`
- `clear_page_content`: `Error executing tool clear_page_content: Page
  'canvas--WjjZil_19' owns objects this write cannot see and would destroy:
  tables grid-D53nA4DcMR. outline_page only sees canvas text — a table,
  control or formula chip written to a page never appears there, only in
  listTables/listControls/listFormulas, which is what this guard reads
  instead. Pass force=True to proceed anyway.`
- `delete_page`: `Error executing tool delete_page: Page 'canvas--WjjZil_19'
  owns objects this write cannot see and would destroy: tables
  grid-D53nA4DcMR. outline_page only sees canvas text — a table, control or
  formula chip written to a page never appears there, only in
  listTables/listControls/listFormulas, which is what this guard reads
  instead. Pass force=True to proceed anyway.`

L2e is the check that closes the loop: after all four refusals,
`outline_page("canvas--WjjZil_19")` came back **byte-for-byte identical** to
L1b's earlier call on the same page — `38 lines, identical to L1b` — which is
what proves the four refused calls destroyed nothing.

**Still restated as untested, and why.** `force=True` against a page that
really owns objects remains UNTESTED by this run, same as before it — the v1
API this project targets cannot recreate a table, so a table destroyed by a
forced write against this scratch document could not be recreated by a later
run; the loss would be permanent. Separately, `listControls` and
`listFormulas` both returned empty against this document (see "Document
state read live on 2026-09-08" above), so this phase exercised only the
table arm of `objects_owned_by_page`'s three-arm guard. The control and
formula arms remain untested — not because this run skipped them, but
because this document has no control or formula for either arm to find.

## L3

_Verdict:_ PASS, all eleven checks (L3a through L3k; L3a2 and L3g2 below are
id-resolution sub-steps nested under L3a and L3g, not independent checks).

_Evidence:_

```
  page name  : MCP-LIVE-20260908T033141Z
  row names  : live-A-20260908T033141Z / live-B-20260908T033141Z
  [PASS] L3a  create_page applies
         {'outcome': 'applied', 'detail': 'applied', 'warning': None}

  --- resolving the new page id (create_page returns none) ---
         poll[new page appears] satisfied after 0.7s (1 attempts)
  [PASS] L3a2  resolve the created page's id
         id=canvas-UtzJCPcNBK after 1s / 1 polls. create_page itself returns no id — a caller must list the document to find it.
         poll[rename visible] satisfied after 4.0s (1 attempts)
  [PASS] L3b  rename_page applies and is visible
         name is now 'MCP-LIVE-20260908T033141Z-renamed' after 4s
  [PASS] L3c  append_to_page (append) applies
         {'outcome': 'applied', 'detail': 'applied', 'warning': None}
  [PASS] L3d  append_to_page (prepend) applies
         {'outcome': 'applied', 'detail': 'applied', 'warning': None}
         poll[page order] satisfied after 0.1s (1 attempts)
         outline observed: ['start', 'live', 'alpha', 'omega']
  [PASS] L3e  prepend/append land in the right order
         start < alpha < omega after 0s
         poll[replacement visible] satisfied after 0.2s (1 attempts)
         outline observed: ['start', 'live', 'replaced', 'omega']
  [PASS] L3f  replace_element rewrites one line
         'replaced' visible after 0s
  [PASS] L3g  upsert_rows reports one outcome per row
         {'rows': [{'index': 0, 'outcome': 'applied', 'warning': None}, {'index': 1, 'outcome': 'applied', 'warning': None}], 'chunks': 1, 'resume_from': None}

  --- resolving the inserted row ids ---
         poll[rows visible] satisfied after 0.2s (1 attempts)
  [PASS] L3g2  the upserted rows become visible
         A=i-cGRRVu0UL3 B=i-3fpYWvjilk after 0s; table now lists 14 rows
         second upsert: {'rows': [{'index': 0, 'outcome': 'applied', 'warning': None}, {'index': 1, 'outcome': 'applied', 'warning': None}], 'chunks': 1, 'resume_from': None}
         settling for 30s before re-reading
         rows named live-A-20260908T033141Z: 1
         rows named live-B-20260908T033141Z: 1
  [PASS] L3h  a repeated keyed upsert updates, not duplicates
         one of each; table lists 14 rows (was 14)
  [PASS] L3i  update_row writes a typed cell
         {'outcome': 'applied', 'detail': 'applied', 'warning': None}
         refusal text: Error executing tool update_row: Column 'Modified by' is a calculated column. Calculated columns are read-only and their values are discarded on write. Remove this column from the write.
  [PASS] L3j  update_row refuses a calculated column
         refused: Error executing tool update_row: Column 'Modified by' is a calculated column. Calculated columns are read-only and their values are discarded on write. Remove this column from the write.
         refusal text: Error executing tool update_row: Column 'NoSuchColumnXYZ' was not found in this table's schema. Cells are addressed by column name here — the name a row read comes back keyed by — not by column ID. Call describe_table to see this table's column names.
  [PASS] L3k  update_row refuses an unknown column
         refused: Error executing tool update_row: Column 'NoSuchColumnXYZ' was not found in this table's schema. Cells are addressed by column name here — the name a row read comes back keyed by — not by column ID. Call describe_table to see this table's column names.
```

Findings worth calling out specifically:

- **`create_page` does not return the id of the page it created** — its own
  `MutationOutcome` is just `{'outcome': 'applied', 'detail': 'applied',
  'warning': None}`. The driver had to poll `get_doc_overview` to find the
  new page by the name it had just asked for:
  `id=canvas-UtzJCPcNBK after 1s / 1 polls. create_page itself returns no
  id — a caller must list the document to find it.` This is an ergonomic
  gap, not a correctness bug: a model that creates a page cannot address
  that page for any follow-up action without a second lookup by name, and
  that lookup is ambiguous whenever two pages share a name — which this same
  document already demonstrates (`canvas-9p61hMYYmH` and `canvas-wzBw5Lq3v6`,
  both named `b6-20260907T145220Z`; see "Document state read live on
  2026-09-08" above).
- The repeated, identical, keyed `upsert_rows` call **updated rather than
  duplicated**: the table listed 14 rows after the first upsert and still
  14 rows after the second, with exactly `one of each` of the two row names
  found. This is the first live confirmation of the replay-safety claim
  `upsert_rows`'s own description makes — previously assumed only from
  reading the code.
- Both negatives refused before anything was sent to the API. The calculated
  column: `Error executing tool update_row: Column 'Modified by' is a
  calculated column. Calculated columns are read-only and their values are
  discarded on write. Remove this column from the write.` The unknown column
  name: `Error executing tool update_row: Column 'NoSuchColumnXYZ' was not
  found in this table's schema. Cells are addressed by column name here —
  the name a row read comes back keyed by — not by column ID. Call
  describe_table to see this table's column names.`

## L4

_Verdict:_ Four of five checks PASS; **L4b FAILED**. `push_button` (L4f) was
deliberately not run.

_Evidence:_

```
  owned page: canvas-UtzJCPcNBK
  owned rows: ['i-cGRRVu0UL3', 'i-3fpYWvjilk']
         poll[element gone] satisfied after 0.2s (1 attempts)
  [PASS] L4a  delete_element on the created page
         cl-0VFCIleGYc gone after 0s; 3 elements remain
         poll[page empty] not yet (0s elapsed), sleeping 5s
         poll[page empty] not yet (6s elapsed), sleeping 5s
         poll[page empty] not yet (11s elapsed), sleeping 5s
         poll[page empty] not yet (18s elapsed), sleeping 5s
         poll[page empty] not yet (23s elapsed), sleeping 5s
         poll[page empty] not yet (28s elapsed), sleeping 5s
         poll[page empty] not yet (33s elapsed), sleeping 5s
         poll[page empty] not yet (39s elapsed), sleeping 5s
         poll[page empty] not yet (44s elapsed), sleeping 5s
         poll[page empty] not yet (50s elapsed), sleeping 5s
         poll[page empty] not yet (55s elapsed), sleeping 5s
         poll[page empty] not yet (64s elapsed), sleeping 5s
         poll[page empty] not yet (69s elapsed), sleeping 5s
         poll[page empty] not yet (74s elapsed), sleeping 5s
         poll[page empty] not yet (79s elapsed), sleeping 5s
         poll[page empty] not yet (85s elapsed), sleeping 5s
         poll[page empty] gave up after 90.1s (17 attempts)
  [FAIL] L4b  clear_page_content on the created page
         applied, but outline still has 1 lines after 90s
         poll[overwrite visible] satisfied after 0.2s (1 attempts)
         outline observed: ['overwritten']
  [PASS] L4c  overwrite_page with force=True on the created page
         visible after 0s
         poll[rows gone] satisfied after 1.4s (1 attempts)
  [PASS] L4d  delete_rows removes the rows this run inserted
         {'rows': [{'index': 0, 'outcome': 'applied', 'warning': None}, {'index': 1, 'outcome': 'applied', 'warning': None}], 'chunks': 1, 'resume_from': None}; both names gone after 1s
         poll[page gone] satisfied after 1.0s (1 attempts)
  [PASS] L4e  delete_page on the created page
         gone after 1s; 10 pages remain
  [SKIP] L4f  push_button
         unknown button action, blast radius cannot be stated in advance
```

L4a, L4c, L4d and L4e each reported a successful outcome, and `delete_rows`
(L4d) returned the shape the plan's pass condition names — per-row `index`,
`outcome` and `warning`, plus batch-level `chunks` and `resume_from`, with
`resume_from: None` since nothing here was large enough to be chunked:

```
{'rows': [{'index': 0, 'outcome': 'applied', 'warning': None}, {'index': 1, 'outcome': 'applied', 'warning': None}], 'chunks': 1, 'resume_from': None}
```

After L4e, the cleanup audit confirmed the page L3 created and the rows L3
inserted were both gone:

```
==============================================================================
CLEANUP AUDIT — what this run left behind
==============================================================================
  page : gone  (canvas-UtzJCPcNBK)
  rows : gone  (no row named live-A-20260908T033141Z or live-B-20260908T033141Z in grid-PH5-RNMCB1)

  Clean: this run left nothing behind.
```

### L4b — the run's one real finding

`clear_page_content` reported `outcome: applied`, but the page still had one
line 90 seconds later — the driver polled for an empty outline 17 times over
90.1s and gave up:

```
         poll[page empty] not yet (0s elapsed), sleeping 5s
         ...
         poll[page empty] gave up after 90.1s (17 attempts)
  [FAIL] L4b  clear_page_content on the created page
         applied, but outline still has 1 lines after 90s
```

A follow-up probe isolated the question by creating its own throwaway page
with three elements, clearing it, and reading the raw content back rather
than trusting `outline_page`'s summarised view:

```
BEFORE clear: 3 elements
    {'id': 'cl-e1wZWp-VdR', 'type': 'line', 'itemContent': {'style': 'h1', 'format': 'plainText', 'content': 'one'}}
    {'id': 'cl-lLCCpLOk8S', 'type': 'line', 'itemContent': {'style': 'paragraph', 'format': 'plainText', 'content': 'two', 'lineLevel': 0}}
    {'id': 'cl-J6DVMo7kNE', 'type': 'line', 'itemContent': {'style': 'paragraph', 'format': 'plainText', 'content': 'three', 'lineLevel': 0}}
clear: {'outcome': 'applied', 'detail': 'applied', 'warning': None}
  t=5s -> 1 elements
AFTER clear: 1 elements
   RAW: {'id': 'cl-e1wZWp-VdR', 'type': 'line', 'itemContent': {'style': 'h1', 'format': 'plainText', 'content': ''}}
```

**This is not a defect in the client.** `deletePageContent` empties a canvas
but leaves exactly one line behind, and that survivor keeps the *first*
element's id (`cl-e1wZWp-VdR`) and its style (`h1`), with the content emptied
to the empty string. A cleared page is therefore not an empty page: it
retains one styled, empty line whose element id is still addressable.

Two consequences worth recording:

- `clear_page_content`'s own tool description (as registered by
  `superhumandoc_mcp.tools.writes.clear_page_content_tool`) claimed it
  deletes "every element of a page's canvas" — that overstated what the API
  does, and `superhumandoc_mcp.tools.writes._CLEAR_PAGE_CONTENT_DESCRIPTION`
  has since been corrected to say what this run measured: one line
  survives, keeping the first element's id and style with the content
  emptied.
- Content appended to a freshly cleared page follows a surviving `h1` line
  rather than starting clean — a caller that clears a page and then appends,
  expecting a blank canvas, gets its new content trailing an empty
  first-line heading it did not ask for.

The test's pass condition — an empty outline after clearing — was wrong, not
the tool.

## Second run — 2026-09-08

After the first run's findings prompted the two fixes below, the identical
plan was run a second time, same day, against the same scratch doc.

**Run date:** 2026-09-08 (same day as the first run, after both fixes below
had been made).
**Doc used:** `6vqpBu-VYd`, same scratch doc as the first run.
**Driver totals:** 45 tool calls, 416.9s elapsed, 35 PASS / 0 FAIL / 1 SKIP of
36 checks.

```
==============================================================================
SUMMARY
==============================================================================
  ID     STATUS  DESCRIPTION
  ------ ------- ---------------------------------------------------
  L0a    PASS    flag off registers exactly the 12 always-on tools
  L0b    PASS    flag on registers exactly 18 tools (12 + 6 gated)
  L1a    PASS    get_doc_overview returns pages + tables + columns
  L1b    PASS    outline_page on TORTURE-MD
  L1c    PASS    describe_table on grid-PH5-RNMCB1
  L1d    PASS    find_rows shape is {rows, complete, note}
  L1e    PASS    get_row returns name-keyed cells
  L1f    PASS    read_page is cached on the second call
  L1g    PASS    read_page refuses a contentType=table page
  L2d    PASS    delete_element refuses on a page that owns a table
  L2c    PASS    overwrite_page refuses a page that owns a table
  L2b    PASS    clear_page_content refuses a page that owns a table
  L2a    PASS    delete_page refuses a page that owns a table
  L2e    PASS    TORTURE-MD is byte-for-byte unchanged
  L3a    PASS    create_page applies
  L3a3   PASS    create_page returns the new page's id
  L3a2   PASS    resolve the created page's id
  L3a4   PASS    create_page's id is the page that was created
  L3b    PASS    rename_page applies and is visible
  L3c    PASS    append_to_page (append) applies
  L3d    PASS    append_to_page (prepend) applies
  L3e    PASS    prepend/append land in the right order
  L3f    PASS    replace_element rewrites one line
  L3g    PASS    upsert_rows reports one outcome per row
  L3g2   PASS    the upserted rows become visible
  L3h    PASS    a repeated keyed upsert updates, not duplicates
  L3g3   PASS    an unkeyed upsert reports the inserted row id
  L3i    PASS    update_row writes a typed cell
  L3j    PASS    update_row refuses a calculated column
  L3k    PASS    update_row refuses an unknown column
  L4a    PASS    delete_element on the created page
  L4b    PASS    clear_page_content leaves one empty line
  L4c    PASS    overwrite_page with force=True on the created page
  L4d    PASS    delete_rows removes the rows this run inserted
  L4e    PASS    delete_page on the created page
  L4f    SKIP    push_button

  PASS 35   FAIL 0   SKIP 1   (of 36 checks)

  tool calls made: 45
  elapsed: 416.9s
```

The created page this run acted on was `canvas-c3SJnaSjp0`. The cleanup audit
at the end of the run confirmed it left nothing behind:

```
==============================================================================
CLEANUP AUDIT — what this run left behind
==============================================================================
  page : gone  (canvas-c3SJnaSjp0)
  rows : gone  (no row named live-A-20260908T042745Z, live-B-20260908T042745Z or live-C-20260908T042745Z in grid-PH5-RNMCB1)

  Clean: this run left nothing behind.
```

`push_button` (L4f) is still the only SKIP, for the same unchanged reason
stated in "Before you run this" above: `test-table-02`'s button column has an
action nobody has recorded, and its blast radius cannot be stated in advance.

### Three checks were added, because the tools gained fields since the first run

- **L3a3** — asserts `create_page` returns a non-null `page_id` on an applied
  create, closing the ergonomic gap the first run found (see "What this run
  changed" below). Evidence:

  ```
  {'outcome': 'applied', 'detail': 'applied', 'warning': None, 'page_id': 'canvas-c3SJnaSjp0'}
  ```

- **L3a4** — asserts the id `create_page` reported names the *same* page a
  listing finds by the name that was given to `create_page`, not merely that
  some id came back. This matters on its own: a `page_id` that named the
  wrong page would be worse than no id at all, because every later call in
  the run would address the wrong page while still reporting success — the
  failure would surface somewhere else entirely, if it surfaced at all.
  Evidence: `reported canvas-c3SJnaSjp0, listing agrees`.

- **L3g3** — asserts an *unkeyed* `upsert_rows` call reports the inserted row
  id, and that the id reads back as the row just written. This needed its
  own check because L3g exercises `upsert_rows` with `key_columns` set, and
  in that keyed mode the API reports no row ids at all — so L3g can only ever
  prove `row_id` comes back `None`. The populated half of the id-reporting
  fix (the unkeyed path, where ids are actually returned) had no check
  proving it worked until L3g3. Evidence: `row_id=i-VSWJT3XDri and get_row
  under it returns the row just written`.

### One check's pass condition changed: L4b

The first run's L4b failed while waiting for `clear_page_content` to leave an
empty outline. That run's own follow-up probe (see L4b above) established
what the API actually does: it leaves exactly one line behind, keeping the
first element's id and style with the text emptied — not a genuinely empty
canvas. L4b's assertion now checks for that measured behaviour instead of an
empty outline, and passes:

```
one line, text empty, after 0s: [{'element_id': 'cl-JshtOje6-u', 'style': 'h1', 'level': None, 'text': ''}]
```

To be explicit about what changed and why: the original expectation was wrong
about the API, not about the tool, so the fix was to the test's pass
condition, not to `clear_page_content` itself. The new assertion is also
stricter than a bare "not empty" check would be — it pins exactly one line
with empty text, so it would still fail against a future change either to a
genuinely empty page or to a clear that leaves two lines behind.

### L3g's own assertion was also tightened

Independent of L3g3 above, the per-row key set L3g checks against was
tightened to exactly `{index, outcome, warning, row_id}`. On a *keyed*
upsert, `row_id` must now be present and `None` — not missing from the dict,
and not a fabricated id — matching the present-but-null convention the fix
established (see "What this run changed" below).

## What this run changed

- `clear_page_content`'s tool description overstated the API's behaviour
  ("delete every element of a page's canvas") and has since been corrected
  to record the measured one-line survivor (see L4b above; also recorded
  in `docs/reference/api-operational-constants.md`). **Confirmed live** by
  the second run's L4b, which now passes against the corrected pass
  condition — see "Second run — 2026-09-08" above.
- `create_page` returning no id for the page it just created was an
  ergonomic gap; it has since been **fixed**. A live probe against scratch
  doc `6vqpBu-VYd` showed the 202 body already carries the id alongside
  `requestId`:

  ```
  RAW createPage 202 body:
      'id': 'canvas-jBZGx4yN81'
      'requestId': 'mutate:7b735abf-3f15-4178-a4b7-e2bef4ef8e1d'
  ```

  `create_page` now returns a `page_id` key alongside `outcome`/`detail`/
  `warning`, taken straight from that `id`. The key is always present and
  `None` when the API did not report one — the same present-but-null
  convention the `warning` key already follows, so a caller never has to
  test for a missing key. Only `create_page` gained it: `rename_page` and
  `append_to_page` create nothing, so a page id in their reports would
  suggest something new exists where nothing did. The tool's description
  now also tells the model to prefer the id over the name when addressing
  the page afterward, because names are not unique in this document and
  addressing by a duplicated name reaches an arbitrary one of them (see L3
  findings above, and the two pages both named `b6-20260907T145220Z`).

  This needed no RFC: no RFC specifies the write tools' return shape —
  `{outcome, detail, warning}` is a code choice in
  `superhumandoc_mcp.tools.writes._report`, and the governing topics
  constrain only the outcome vocabulary (`applied`/`unknown`, never
  `failed`) and the `warning` field's verbatim pass-through, not which
  sibling fields may exist.

  The same probe also found that the id is not immediately readable: a
  `getPage` addressed to `canvas-jBZGx4yN81` roughly 20 seconds after the
  202, and before the mutation reported `completed: true`, refused with
  `HTTP 404 "Could not find a page with the specified ID or name."` Through
  the `create_page` tool this is not a problem a caller has to plan for,
  because the tool polls the mutation to completion before returning: the
  id is usable as soon as the outcome is `applied`. See
  `docs/reference/api-operational-constants.md` for the full measurement.

  `upsert_rows` had the analogous gap; it has since been **fixed**. Each
  entry in `upsert_rows`' returned `rows` list now carries `row_id` alongside
  `index`, `outcome` and `warning`. The id is mapped through the chunk's own
  index list, not by position in the whole batch, because the alignment is
  per request — past the first chunk those two disagree and the wrong one
  would file every id against another row. It is only mapped when the count
  of returned ids matches the count of rows in that chunk; if they ever
  disagree, the correspondence is precisely what is unknown, so nothing is
  guessed. `row_id` is always present and `None` when there is no id — the
  same present-but-null convention `warning` and `create_page`'s `page_id`
  follow.

  It is `None` on every row of a KEYED upsert, even genuinely new rows,
  because the API omits the field in that mode. This is the notable
  finding: `key_columns` buys replay safety and costs you the inserted IDs;
  omitting it returns the IDs and costs replay safety. The tool's
  description now states this trade-off and recommends preferring
  `key_columns` plus a follow-up `find_rows`, since a duplicated row is
  harder to undo than a lookup is to repeat.

  Live confirmation through the MCP boundary:

  ```
  A) unkeyed upsert: {'rows': [{'index': 0, 'outcome': 'applied', 'warning': None, 'row_id': 'i-eeJIT5_mco'}, {'index': 1, 'outcome': 'applied', 'warning': None, 'row_id': 'i-C2IM3hiL5c'}], 'chunks': 1, 'resume_from': None}
     get_row on the returned id succeeded immediately.
  B) keyed upsert:   {'rows': [{'index': 0, 'outcome': 'applied', 'warning': None, 'row_id': None}], 'chunks': 1, 'resume_from': None}
  ```

  This needed no RFC, for the same reason the `create_page` change did not:
  no RFC specifies the write tools' return shape. See
  `docs/reference/api-operational-constants.md` for the underlying
  measurement.

  Both id-reporting fixes are **confirmed live** by the second run: L3a3 and
  L3a4 exercise `create_page`'s new `page_id`, and L3g3 exercises the
  unkeyed-upsert half of `upsert_rows`'s new `row_id` (L3g's own keyed case
  can only ever show `row_id` as `None`). See "Second run — 2026-09-08"
  above for the evidence each check produced.
- Three things remain untested after this run, each for a stated reason
  rather than an oversight:
  - `push_button` — `test-table-02`'s button column has an action nobody has
    recorded, and its blast radius cannot be stated in advance (see "Before
    you run this" above).
  - `force=True` against a page that genuinely owns a table, control or
    formula — the v1 API this project targets cannot recreate a table, so
    the loss from a forced write on this scratch document would be
    permanent (see L2 above).
  - The control and formula arms of `objects_owned_by_page`'s three-arm
    guard — this document has zero controls and zero formulas for either
    arm to find (see L2 above and "Document state read live on 2026-09-08").

---

# Correction — 2026-09-09: the premise behind one "untested" item was wrong

The two runs above both record `force=True` against a page that genuinely owns
a table as untested, and both give the same reason: *"the v1 API this project
targets cannot recreate a table, so the loss would be permanent."*

**That reason is false.** A probe on 2026-09-09 created a page whose HTML
content contained a `<table>`, and a real table object appeared in
`listTables` within ten seconds, owned by that page. The full measurement is
in `docs/reference/api-operational-constants.md`, §3.3.

The claim was already contradicted by evidence inside this very document. The
"Document state read live on 2026-09-08" section lists `Table 1`, `Table 2`
and `Table 3`; those are owned by the `TORTURE-MD`, `TORTURE-HTML` and
`TORTURE-GEN2` pages, which the 2026-09-03 fidelity runs created through this
same API. Tables had been created by page-content writes three times before
anyone wrote down that it could not be done. The claim appears to have been
inferred from the absence of a `createTable` endpoint in the inventory, and
never checked against the document it was written about.

**What this changes.** The blocker was never the writing, it was the cleanup —
and the cleanup problem is real. v1.6.0 has no endpoint that deletes a table,
and deleting the owning page orphans the table rather than removing it (its
`parent` becomes `null`). So a run *can* now build its own page-owning-a-table
and force a destructive write over it; it just cannot tidy up afterwards
without someone opening the UI.

The two remaining gaps are unaffected by this correction. `push_button` still
has no button whose action is known, and the control and formula arms of
`objects_owned_by_page` still have nothing to find: `listControls` and
`listFormulas` both returned empty again on 2026-09-09.

**Litter left by the probe.** `grid-gL5OlKQPxM` ("Table 4") is an orphan in
`6vqpBu-VYd` with a null parent. Its page was deleted; the table could not be.
It is harmless — no test reads it — but only the UI can remove it.

---

# L5 and L6 — 2026-09-09: two of the three gaps closed

Run against `6vqpBu-VYd`, same rules as the runs above: the doc id is asserted
before any other call, the token is never printed, and no pre-existing object
is written to except where stated.

## L5. Does `push_button` work, and what does the button actually do?

**The blast radius was readable all along.** Every run above skipped
`push_button` because `test-table-02`'s button "has an action nobody has
recorded" and "a blast radius that cannot be stated in advance". It is
returned by `listColumns`, in the column's own `format`:

```
c-Lapt2e6qA9  name "button"  calculated: true
  format: {label: "Increment Count",
           action: "ModifyRows(thisRow, count, count+1)",
           type: "button", isArray: false}
```

The action writes one number cell on its own row. That is a blast radius of a
single cell, statable in advance by one read call that nobody made. The
caution was reasonable but the premise — that the action was unknowable —
was not checked.

**Result: PASS.** `push_button(grid-EETnwpzofr, i-_0US3LVT0m, c-Lapt2e6qA9)`
returned `{'outcome': 'applied', 'detail': 'applied', 'warning': None}`, and
`count` on that row moved `0 -> 1`, visible 8 seconds later. Exactly one
increment; no other cell changed. `push_button` is no longer mock-only.

## L6. Does `force=True` bypass the guard on a page that really owns a table?

Built its own fixture rather than touching anything pre-existing, which §3.3
of `docs/reference/api-operational-constants.md` establishes is possible.

1. `create_page` with a `<table>` in its HTML → `canvas-sZBc4nHK_N`,
   `outcome: applied`.
2. `objects_owned_by_page` → `{'tables': ['grid-UMvMvdBdNV'], 'controls': [],
   'formulas': []}`. The guard sees the table the page owns.
3. `overwrite_page(force=False)` → **refused**, as designed:

   > `ContentRefused: Page 'canvas-sZBc4nHK_N' owns objects this write cannot
   > see and would destroy: tables grid-UMvMvdBdNV. ... Pass force=True to
   > proceed anyway.`

4. `overwrite_page(force=True)` → `outcome: applied`. 8 seconds later the page
   held a single `line` element, `objects_owned_by_page` reported no tables,
   and `grid-UMvMvdBdNV` was gone from `listTables` altogether.

**Result: PASS.** The guard refuses without `force` and yields to it, and the
destruction it warns about is real rather than theoretical — the table is
destroyed, not orphaned. Fixture page deleted afterward; the doc is back to 10
pages.

## What remains

One gap, unchanged and still needing the web UI: **the control and formula
arms of `objects_owned_by_page`**. `listControls` and `listFormulas` are still
empty, so two of the guard's three arms have never matched a real object. No
API endpoint creates either, so this cannot be closed from code. Creating one
control and one named formula on a page that no test destroys would close it
permanently — the guard test only needs them to exist and be detected, never
to be consumed.

The orphan `grid-gL5OlKQPxM` ("Table 4") from the earlier probe is still
there and still removable only in the UI.
