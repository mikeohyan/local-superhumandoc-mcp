# Cell write formats for the Superhuman Docs API (Coda v1)

Evidence document. Last updated 2026-09-03. Updatable — extend it as tests are run
and as vendor behaviour changes. Cite it from an RFC; do not paste it into one.

**Status:** the desk research in the sections below is complete and sourced. Of
the test plan, **T7, T7b, T12, and the checkbox and canvas halves of T11 ran live
on 2026-09-06**, against the throwaway scratch doc `6vqpBu-VYd`, along with a new
reaction-column test the plan did not originally include. Results are recorded
below. **T1-T6, T8, T9, T10, and the duration and currency halves of T11 remain
unrun and blocked** — no relation, image, non-calculated person, duration, or
currency column exists in that doc. An empty Results section for a given test
means untested, never tested-and-clean. The scratch doc's real column inventory,
read live on 2026-09-05, is recorded at the head of the test plan and says which
tests are blocked and why.

## What this document settles

Reading rows with `valueFormat=rich` returns JSON-LD objects (`StructuredValue` for
relation cells, `Person`, `MonetaryAmount`, `ImageObject`). Writing is asymmetric:
`CellEdit.value` is typed `Value` = `ScalarValue` (string | number | boolean) or arrays
of scalars. **The rich types are read-only. You cannot send back what you read.** The
OpenAPI spec (v1.6.0) never documents what string the server-side parser accepts to
populate a relation, person, or select cell.

This document records what the vendor has actually stated about those write formats,
gathered from Coda/Superhuman staff posts, vendor help-centre articles, and the source
of working client libraries — and marks precisely what remains unverified.

**Completing it requires an API token and a throwaway scratch doc.** The Confirmed
section below is complete and needs nothing further. The Test plan section resolves the
six items in Still unknown, and takes roughly **10 minutes** to run once the scratch doc
is built (the scratch doc itself takes about 3 minutes to build in the UI). Paste output
into the Results section as tests are run.

Base URL: `https://docs.superhuman.com/apis/v1`. Coda and Superhuman Docs are
byte-identical; `coda.io/developers` 307s to `docs.superhuman.com`, and
`community.coda.io` 301s to `connect.superhuman.com`. Old URLs still resolve.

---

## Confirmed

Confidence markers:

- **[staff]** — stated by a Coda/Superhuman employee on the record, or in a
  vendor-authored help-centre article.
- **[code]** — read from the source of a working implementation.
- **[inferred]** — follows from the spec plus a staff statement, but nobody has said it.
- **[unknown]** — no source anywhere. Listed in Still unknown.

### The governing principle

Eric Koleda (Coda staff), asked directly how to insert date/currency/user objects —
<https://connect.superhuman.com/t/coda-api-insert-update-rows-with-different-object-types/31532/2>:

> That's correct, setting values can only be done via plain text. However Coda
> intelligently parses those plain text value based on the column type. It works the same
> way as when you type a value into the cell directly using your keyboard. For a date for
> example, you can see which date formats are interpreted correctly in the doc, and then
> use those same formats in your API request.

There is no per-type write encoding. There is one parser, and it is the one the UI uses.
Jason Tamulonis (Coda staff) on how it is built —
<https://connect.superhuman.com/t/launched-more-international-date-and-time-options/52411/46>:

> The general pattern we try to follow for all value-type conversions is to handle them in
> a central piece of code shared between UX, formulas, API, and automations. Hence, we get
> consistent behavior across all of them. Most conversions also have two modes depending on
> the usage: strict and loose. [...] Loose mode often has a preferential order that can
> depend on various factors like column settings, the document's regional settings, and,
> eventually, a user's regional settings.

### Load-bearing vendor statement #1 — exact match for people and relation columns

Vendor-authored help-centre article, "Connect Superhuman Docs with other apps using
Zapier". The HTML is behind a Cloudflare challenge; the Zendesk JSON API serves it
(`https://help.superhuman.com/api/v2/help_center/en-us/articles/46210081347597.json`,
verified HTTP 200 on 2026-09-03). Verbatim:

> **How do I write to people or relation columns?**
> If you write to a people column or a relation column, we will auto-convert raw text
> values based on an exact match (eg, "Molly" won't map to "Molly Rose" or "Launch Site"
> won't map to "Launch the Website")

<https://help.superhuman.com/hc/en-us/articles/46210081347597-Connect-Superhuman-Docs-with-other-apps-using-Zapier>

This rules out prefix and fuzzy matching explicitly, with worked counterexamples.

### Load-bearing vendor statement #2 — images and files are written as public URLs

Eric Koleda (Coda staff, `staff=true admin=true`), 2024-03-14, in "Upload images to table
from API". Verbatim:

> You can use the API to upload images and files to a Coda table, but only if they are
> already hosted on a publicly-accessible URL. If you pass that URL (or array of URLs) as
> the cell value in the API, Coda will ingest the images/files into the table.

<https://connect.superhuman.com/t/upload-images-to-table-from-api/29585/4>

Same thread, post 6, 2025-05-12:

> You may need to ensure that the correct Content-Type header is returned by the URL, so
> that Coda ingests it correctly.

<https://connect.superhuman.com/t/upload-images-to-table-from-api/29585/6>

### Per column type

#### relation / lookup (`ColumnFormatType: lookup`)

**Send the target row's ID as a bare string, `"i-XxXxXxX"`.** For a multi-value column
(`format.isArray == true`), send a JSON array of row IDs. Fallback: the target row's
display-column text, exact match. **[staff]**

Eric Koleda, 2023-12-15, giving the canonical payload —
<https://connect.superhuman.com/t/inserting-relation-through-the-api/42955/15>:

> Good news! The engineer working on this has now also added support for setting multiple
> relations via ID using the API:
>
> ```
> PUT https://coda.io/apis/v1/docs/{DOC_ID}/tables/{TABLE_ID}/rows/{ROW_ID}
> { "row": { "cells": [ { "column": "{COLUMN_ID}",
>     "value": [ "{TARGET_ROW_ID_1}", "{TARGET_ROW_ID_2}" ] } ] } }
> ```

Restated a year later — <https://connect.superhuman.com/t/api-how-to-query-for-a-relation/52025/4>:

> The upsertRows endpoint allows you to change the value of a cell in a Relation column.
> You can either pass the display value of the target row, but a more accurate method is to
> pass the row ID.

Feature timeline, all from the same staff member in thread 42955: 2023-09-20 "Unfortunately
not. At the moment the only option is to use the display value of the target row, which I
understand is quite error prone" (#2); 2023-12-01 "this week we released support for
passing row IDs in this upsertRows endpoint" (#11); 2023-12-15 arrays (#15). A user in
that thread pins the release at **API 1.4.5**. Our spec is 1.6.0, so both are in.

The display-name path, and the multi-value forms, from Oleg Vaskevich (Coda API engineer)
— <https://connect.superhuman.com/t/how-to-pass-a-lookup-value-via-api-or-copy-paste-or-anything/6743/2>:

> For Lookup from table columns, specify the text-only name of your lookup value's display
> column, and when inserted it will get matched to the row [...] Also for both types of
> columns in multi-select mode, you can pass in an array or comma-separated list to insert
> multiple values.

Still working in 2024, per Eric Koleda in the same thread (#6): "sending the display name
of the row works correctly in my doc [...] We also recently added support for sending the
row ID of the target row, as a more accurate way to set the value."

Also: "lookup columns are always strings in the API" — Oleg,
<https://connect.superhuman.com/t/updating-a-lookup-column-through-api/6250/4>. Send
numeric-looking display values as JSON strings, never as JSON numbers.

**On no match:** the API returns 202, the mutation completes, and the literal string is
written into the cell, which then renders Coda's red in-cell error *"X is not a valid row
reference"*. No row is created in the target table and no HTTP error is raised.
**[staff-adjacent; three independent user reports, no staff contradiction]** — see
<https://connect.superhuman.com/t/updating-a-lookup-column-through-api/6250/1>,
<https://connect.superhuman.com/t/creating-new-select-options-with-zapier/33262/4>, and
most clearly <https://connect.superhuman.com/t/create-new-rows-in-relation-columns-automatically/51076/1>:

> if I was manually adding the data in Coda [...] you just type what you need in and when
> you hit enter on that it will create a requisite row. But if you paste data into a row
> (or use something like Make to copy data into a Coda table [...]) Coda will not go ahead
> and create a requisite row in the related tables automatically. Instead you just see the
> text without a "bubble" around it, meaning its not actually relating to a row in that
> table.

Note this contradicts the staff "works the same way as when you type" framing. Nobody at
Coda has reconciled the two. **Consequence: a name-based relation write can silently
corrupt a cell and the HTTP response will not tell you. Read back and verify.**

#### person (`ColumnFormatType: person`)

**Send the email address.** The full display name is also accepted. Exact match. The
person must already be in the doc. Multi-value: array (preferred) or comma-separated
string. **[staff]**

Christopher Eck (Coda staff) —
<https://connect.superhuman.com/t/coda-api-writing-values-of-type-people/1886/2>: "put the
user's full name in the cell for the API…basically the text you see in that column for
existing people." Oleg, same thread #5, asked about duplicate names: "you can also use the
email address of each person in lieu of their name."

Oleg's fuller statement (thread 6743 #2, quoted above): "For People columns, you can use
either the full name of the person or their email address. Note that the person already
needs to be in the doc (i.e., show up directly in the People dropdown, not under 'Show
more' if you have a G Suite account)."

Email is the correct default: it is the only stable identifier and it is the documented
fix for duplicate names.

Reading the email back requires `valueFormat=rich` — Christopher Eck,
<https://connect.superhuman.com/t/user-email-is-not-displayed-in-api-for-people-type-column/46034/2>.

#### select (`ColumnFormatType: select`)

**Send the option's `name` as a plain string.** Multi-value: array or comma-separated
string. **[inferred]** — the spec gives `SelectOption` only a `name`, and the multi-value
rule is stated for lookup and person by analogy. No staff statement about select columns
specifically exists.

What happens on a value not in the option list is **[unknown]** — see Still unknown #1.

Note the spec caveat on `SelectColumnFormat.options`: "Only returned for select lists that
used a fixed set of options. Returns the first 5000 options." The UI toggle "Allow adding
of new options" exists on the column but is **not** exposed in the API's `format` object.

#### image / imageReference / attachments

**Send a publicly-accessible URL string, or an array of URL strings.** Coda fetches and
ingests the file. Bytes are never accepted. Ensure the URL serves a correct `Content-Type`
or previews break. **[staff]** — see load-bearing statement #2 above.

The spec has three distinct format types here (`image`, `imageReference`, `attachments`)
and the Packs SDK distinguishes hotlinking (`ImageReference`) from ingesting
(`ImageAttachment`), so ingest-vs-hotlink behaviour probably differs between them. Which
does which over the REST API is untested — probe in T10.

#### canvas (`ColumnFormatType: canvas`)

**Plain text only.** Markdown and HTML are not interpreted. **[staff]** — Eric Koleda,
2026-04-16, <https://connect.superhuman.com/t/formatting-canvas-columns-via-api/60338/2>:
"Unfortunately there aren't any solutions for this at the moment, but I'll pass along the
desire to the product team." The community workaround is to write plain markdown text and
then push a button running a Pack that converts it in-doc.

#### button (`ColumnFormatType: button`)

**Not written through `cells` at all.** Use `POST /docs/{docId}/tables/{tableIdOrName}/rows/{rowIdOrName}/buttons/{columnIdOrName}`
(`operationId: pushButton`). **[staff/spec]** Note the spec's authorization warning: the
underlying button can perform any action on the doc, including writing to other tables and
running Pack actions.

#### formula / calculated columns

**Not writable.** **[staff/vendor]** — the Zapier help article: "Since formulas apply to
the entire column, we do not allow you to edit them on a per-row basis." This also
prevents using a formula-backed column as an upsert `keyColumn`.

#### date / dateTime / time

**Send ISO 8601** (`2026-09-03`, `2026-09-03T18:30:45`). Unix timestamps are also
converted. **[staff/vendor + inferred]** — the Zapier help article: "we will automatically
convert Unix time stamps to date-time and date column formats. Note that we render these
times in Pacific time."

ISO 8601 is a hard rule here, not a preference — see Contradictions and traps.

#### checkbox

**Send a JSON boolean `true` / `false`.** **[inferred]** — the spec permits booleans in
`ScalarValue`; `coda-js` documents `{ Completed: true }`; Activepieces maps checkbox
columns to a boolean form field. **No staff statement exists.** Settled by T11.

#### duration

**[unknown].** No staff post, no vendor doc, no third-party integration documents it. The
only hint is Coda's Packs SDK (`schema.ts`, `ValueHintType.Duration`), a *different*
ingestion path: "The value should be provided as a string like `"3 days"` or
`"40 minutes 30 seconds"`." Plausible that they share a parser given Tamulonis's "central
piece of code", but nobody has said so. Settled by T11.

#### currency / number / percent / slider / scale

**Send a bare JSON number.** **[inferred]** — no staff statement. Do not send a formatted
string like `"$12.34"`; the spec uses that only as a `ScalarValue` example. Settled by T11.

### Structural facts from the spec that make a real implementation possible

- `ReferenceColumnFormat` — the schema for **both** `lookup` and `person` — has a
  **required** `table: TableReference`, and `TableReference.href` contains the target doc
  ID and table ID. So `listColumns` tells you exactly which table a relation points at.
- `Table.displayColumn` names the column used for display-value matching.
- `listRows` supports `?query=<columnIdOrName>:<jsonValue>`. Together with the two facts
  above this gives a complete client-side name-to-rowId resolver.
- You **cannot** query a table *by* a relation's row ID. Eric Koleda,
  <https://connect.superhuman.com/t/api-how-to-query-for-a-relation/52025/2>: "At the
  moment you can only query on the plain text value of cell [...] For now the best you can
  do is fetch the full contents of the table and do the filtering in your code."
- Writes are asynchronous: HTTP 202 plus a `requestId`. Poll `GET /mutationStatus/{requestId}`
  until `completed == true`.
- Reads come from a possibly-stale snapshot unless you send the header
  `X-Coda-Doc-Version: latest`.
- **Row-ID writes are entirely absent from the OpenAPI spec v1.6.0.** All 19 occurrences of
  `rowId` in the spec are read-side (`RowValue`, `PushButtonResult`, the JSON-LD prose
  example), `rowIds` in `RowsDelete`, or the `rowIdOrName` path parameter. Zero on the
  write path. Generated clients cannot know about this feature.

### Prior art

- **`leongrdic/coda-mapper`** (TypeScript) is the only library found that serialises
  relations correctly. `src/CodaMapper.ts`, `encodeValue()`: a related row object collapses
  to `column.id` (the `i-` row ID); arrays recurse into arrays of row IDs. It also ships a
  `getMutationStatus` wait helper. **[code]** Its author is the same forum user who
  requested row-ID support and first announced it shipped — which explains why no other
  library does this.
- **`orellazri/coda-mcp`** (TypeScript, the most-used Coda MCP server) does **nothing**.
  `src/server.ts` takes a JSON string from the model and `JSON.parse`s it straight into the
  request body; it never inspects `format.type`, never resolves names, never passes
  `disableParsing`. It is generated from this same spec, which is why it cannot know about
  row IDs. Not prior art to copy. **[code]**
- n8n, Pipedream, Make.com: no per-type coercion at all (Pipedream types every column as
  `string`, so a checkbox column receives the string `"true"`).
- Activepieces is the only integration that branches on column type: `select`/`lookup` to a
  text field labelled "Provide options as comma separated values" when `isArray`,
  `checkbox` to boolean, `duration` to number — and `person` is **absent from its switch
  entirely**, falling through to `default: break;` and being silently dropped.

### `disableParsing`

The entire official documentation is one sentence, identical on `upsertRows` and
`updateRow`: *"If true, the API will not attempt to parse the data in any way."* No
default is declared.

What it is for, from Coda staff — Jonathan Goldman,
<https://connect.superhuman.com/t/column-type-changing-via-api/25259/4>: "This should
disable any type inference on previously-unfilled columns." Adam Ginzberg,
<https://connect.superhuman.com/t/update-bug-fix-for-column-format-changes-via-adding-rows-in-the-api/25615>,
distinguishing two behaviours: users "may have suppressed it manually using the
disableParsing URL parameter (which is related but designed for a slightly different use
case)".

What it breaks — <https://connect.superhuman.com/t/api-upsert-lookup-field/24045>, a user
whose lookup column would not link:

> I will answer the question myself like this it can help others. I change the option
> disableparsing to false and now it is working perfectly

What it does **not** affect: markdown/rich-text handling
(<https://connect.superhuman.com/t/markdown-in-table-text-column-with-the-api/23141/4> —
"it made no difference if I used the disableParsing parameter").

What follows from that: `disableParsing=true` suppresses the parsing that
relation, person, select and date columns depend on, so a payload touching one of
those and carrying the flag cannot resolve as intended. Its one clearly safe use
is preserving literal text such as `"00123"`. Whether it also blocks *row-ID*
resolution is untested — T5. **No RFC decides whether the client ever sends this
flag**, so that remains open.

---

## Contradictions and traps

### 1. The stale help-centre FAQ says the API cannot accept images

Coda's help-centre FAQ "Does Superhuman Docs have an API?" still says:

> How do I send an image to the API? Right now our API doesn't accept image files. Instead,
> the closest we can come is passing an Image URL to an Image URL column.

<https://help.superhuman.com/hc/en-us/articles/46210310809613-Does-Superhuman-Docs-have-an-API>

This contradicts Eric Koleda's 2024-03-14 and 2025-05-12 posts in thread 29585, which say
Coda will **ingest** a file from a public URL into an image or file column, not merely
hotlink it into an "Image URL" column.

**We follow the staff posts.** They are more recent (2024/2025 vs an undated FAQ entry),
more specific (they name the ingest behaviour, the array-of-URLs form, and the
`Content-Type` requirement), and they come from the developer-relations owner of the API
answering the exact question in a thread where users then confirmed the behaviour working.
The FAQ is a general-audience summary that was not updated. **T10 verifies this against the
live API; if T10 shows hotlink-only behaviour, revise this section rather than the FAQ.**

### 2. Date parsing depends on the document's locale — ISO 8601 only

Tamulonis's "loose mode" statement (quoted in Confirmed) says value conversion "can depend
on various factors like column settings, the document's regional settings, and, eventually,
a user's regional settings." Combined with Koleda's "use the formats the doc interprets",
this means **`03/04/2026` can resolve to 3 April or 4 March depending on the doc it is
written to.** A server writing on behalf of many users' docs cannot know the locale.

The `tool-surface` topic decided accordingly that cell writes send ISO 8601 only
(`YYYY-MM-DD`, `YYYY-MM-DDTHH:MM:SS`) and reject ambiguous input before a request
is made; see `_rfc/README.md`. Unix timestamps are also
unambiguous and documented, but note the vendor's caveat that Coda renders them in Pacific
time. T12 demonstrates the hazard concretely.

### 3. Do not cite `vish288/mcp-coda`

This repository ships a per-column-type mapping table that appears to be LLM-generated and
is wrong in at least two places:

- It claims the API **rejects writes to lookup columns**. Coda staff explicitly contradict
  this in threads 42955, 6743 and 52025 — lookup columns are writable by display value and,
  since API 1.4.5, by row ID.
- It asserts a **"500 rows per request" limit** on upsert. The spec places no `maxItems` on
  `RowsUpsert.rows`, and no vendor source states such a limit.

It is a 2-star repository with no evident testing against the live API. Anything it says
that is not independently corroborated should be treated as fabricated. The same caution
applies to the other thin generated MCP wrappers surveyed (`craigbryan/coda-mcp`,
`TJC-LP/coda-mcp-server`): they do no per-type handling, so they neither confirm nor refute
anything.

### 4. Column metadata is not fully trustworthy

Eric Koleda,
<https://connect.superhuman.com/t/bug-text-type-lookup-is-returned-in-columns-api-call-as-being-isarray-false-yet-its-values-appear-as-an-array-in-the-rows-call/47241/2>:

> we don't completely prevent a user from entering content into that column that doesn't
> match the type [...] The /columns endpoint will report it as type number but the /rows
> endpoint will return the text value. [...] Dealing with the messiness of tables is
> challenging when working with the API.

`format.type` and `format.isArray` are heuristics, not contracts — a formula-driven text
column can return relation objects, and `isArray` is known to misreport on attachment
columns. **No RFC decides how a client should respond to that**, so whether
column metadata is treated as advisory or as a hard precondition is an open
question rather than something this file settles.

### 5. Other silent-failure traps

- The relation column may point at a **different table than you assume**; the symptom is a
  correct-looking row ID stored as literal text
  (<https://connect.superhuman.com/t/inserting-relation-through-the-api/42955/14>).
- If the target table's **display column is a formula**, name matching may not resolve
  (<https://connect.superhuman.com/t/updating-a-lookup-column-through-api/6250/7>, never
  answered by staff).
- Comma-separated multi-values are ambiguous when a display value **contains a comma**.
  Prefer JSON arrays everywhere. T4d demonstrates.

---

## Test plan

Approximately 10 minutes once the scratch doc exists. Tests are ordered so the
highest-value uncertainty resolves first. Everything is copy-pasteable.

### What the scratch doc actually has today

Read live from the "MCP Validator" doc on 2026-09-05, so the blocked/runnable
split below rests on this rather than on memory. Two tables exist, and neither is
the `Targets`/`Writes` pair this plan specifies:

| Table | Column | Type | Calculated |
|---|---|---|---|
| `test-table-01` | `Name` | text | no |
| `test-table-01` | `number` | number | no |
| `test-table-01` | `date` | date | no |
| `test-table-01` | `Notes` | canvas | no |
| `test-table-01` | `checkbox` | checkbox | no |
| `test-table-01` | `dropdown` | select | no |
| `test-table-01` | `Modified by` | person | **yes** |
| `test-table-01` | `Modified on` | dateTime | **yes** |
| `test-table-02` | `Name` | text | no |
| `test-table-02` | `reaction` | reaction | no |
| `test-table-02` | `button` | button | **yes** |
| `test-table-02` | `Notes` | canvas | no |
| `test-table-02` | `count` | number | no |

Writable select, date, checkbox, canvas and reaction columns therefore exist. The
tests needing them — T7, T7b, T12, the checkbox and canvas halves of T11, and a
reaction write, which this plan has no test for — are runnable today against these
tables, with the column ids substituted for the ones the preamble names.

Still genuinely blocked, because no such column exists: anything needing a
**relation** column (T1-T6, T8, T9 as scripted), a **non-calculated person**
column (the only person column here is `Modified by`, which is calculated and so
not writable), an **image** column (T10), or **duration** and **currency** columns
(the other halves of T11).

### Scratch doc structure the plan assumes (build in the UI first, ~3 min)

Create one throwaway doc with two tables.

**Table A — `Targets`** (the relation target). One column `Name` (Text), set as the
display column. Rows:

| Name |
| --- |
| `Alpha` |
| `Bravo` |
| `Dup` |
| `Dup` |
| `123` |
| `Smith, John` |

**Table B — `Writes`**:

| Column | Type | Setting |
| --- | --- | --- |
| `Title` | Text | display column |
| `Rel` | Relation to `Targets` | single |
| `RelMulti` | Relation to `Targets` | Allow multiple selections **ON** |
| `Who` | Person | single |
| `WhoMulti` | Person | multiple ON |
| `Sel` | Select list | fixed options `Red`, `Green`, `Blue`; "Allow adding of new options" **OFF** |
| `SelMulti` | Select list | same options, multiple ON |
| `Img` | Image | |
| `Cnv` | Canvas | |
| `Chk` | Checkbox | |
| `Dur` | Duration | |
| `Cur` | Currency | |
| `Dt` | Date | |

Add exactly one row to `Writes` with `Title` = `probe`.

### Preamble (paste once)

```bash
export TOK='YOUR_API_TOKEN'
export DOC='YOUR_DOC_ID'                       # e.g. AbCDeFGH
export API='https://docs.superhuman.com/apis/v1'

api() { curl -s -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
             -H "X-Coda-Doc-Version: latest" "$@"; }

# discover table ids
api "$API/docs/$DOC/tables?limit=50" | jq -r '.items[] | "\(.id)\t\(.name)"'
export TS='grid-XXXX_TARGETS'
export TW='grid-YYYY_WRITES'

# discover column ids, types, isArray, and relation target tables
api "$API/docs/$DOC/tables/$TW/columns?limit=50" \
  | jq -r '.items[] | "\(.id)\t\(.name)\t\(.format.type)\tisArray=\(.format.isArray)\ttable=\(.format.table.name // "-")"'

export C_REL='c-...'   C_RELM='c-...'  C_WHO='c-...'  C_WHOM='c-...'
export C_SEL='c-...'   C_SELM='c-...'  C_IMG='c-...'  C_CNV='c-...'
export C_CHK='c-...'   C_DUR='c-...'   C_CUR='c-...'  C_DT='c-...'

# the probe row and the target row ids
export R=$(api "$API/docs/$DOC/tables/$TW/rows?query=Title:%22probe%22" | jq -r '.items[0].id')
api "$API/docs/$DOC/tables/$TS/rows?limit=50" | jq -r '.items[] | "\(.id)\t\(.name)"'
export A='i-AAAA'      # Alpha
export B='i-BBBB'      # Bravo
export SJ='i-SSSS'     # Smith, John

# helpers
wait_mut() { for i in $(seq 1 20); do
    [ "$(api "$API/mutationStatus/$1" | jq -r .completed)" = "true" ] && { echo "  mutation applied"; return; }
    sleep 1; done; echo "  TIMEOUT"; }

put() {  # put <columnId> <json-value> [querystring]
  rid=$(api -X PUT "$API/docs/$DOC/tables/$TW/rows/$R?$3" \
        -d "{\"row\":{\"cells\":[{\"column\":\"$1\",\"value\":$2}]}}" | jq -r .requestId)
  echo "  requestId=$rid"; wait_mut "$rid"; }

show() {  # show <columnId>
  api "$API/docs/$DOC/tables/$TW/rows/$R?valueFormat=rich" | jq ".values[\"$1\"]"; }
```

### The decision rule used by every test

Read back with `valueFormat=rich`.

- **PASS** — the cell is an **object**: `{"@type":"StructuredValue","additionalType":"row","rowId":"i-…","name":"…"}`
  for a relation, `{"@type":"Person","name":…,"email":…}` for a person,
  `{"@type":"ImageObject","url":…}` for an image. The value resolved.
- **FAIL** — the cell is a **bare string** equal to the literal text sent. That is the
  "not a valid row reference" state: HTTP returned 202, the mutation reports completed, and
  the cell is broken. This is the failure that is invisible without reading back.

---

#### T1 — Relation, single, by row ID *(highest value: decides the whole write strategy)*

```bash
put "$C_REL" "\"$A\"" ; show "$C_REL"
```

- Object with `"rowId":"i-AAAA"`, `"name":"Alpha"` → row-ID writes work. Build on this.
- Bare string `"i-AAAA"` → row IDs are not honoured on this deployment despite spec 1.6.0.
  This refutes the staff claim for Superhuman Docs and changes everything downstream: fall
  back to display names plus mandatory read-back verification.

#### T2 — Relation, multi, array of row IDs (PUT)

```bash
put "$C_RELM" "[\"$A\",\"$B\"]" ; show "$C_RELM"
```

- Array of two `StructuredValue` objects → the Dec-2023 multi-relation feature works; the
  server's write API can take `list[str]` of row IDs.
- One object, or a bare string → arrays unsupported on PUT; try the 2019 comma form:

```bash
put "$C_RELM" '"Alpha,Bravo"' ; show "$C_RELM"
```

#### T2b — Relation, multi, array of row IDs on POST / upsertRows

Eric Koleda's array announcement covers `PUT` only. **No staff has confirmed the array form
on `POST /rows`**, and the one user who reported arrays failing was testing upsert before
the fix. This is a real gap.

```bash
rid=$(api -X POST "$API/docs/$DOC/tables/$TW/rows" -d "{\"rows\":[{\"cells\":[
  {\"column\":\"Title\",\"value\":\"probe-post\"},
  {\"column\":\"$C_RELM\",\"value\":[\"$A\",\"$B\"]}]}]}" | jq -r .requestId)
wait_mut "$rid"
api "$API/docs/$DOC/tables/$TW/rows?query=Title:%22probe-post%22&valueFormat=rich" \
  | jq ".items[0].values[\"$C_RELM\"]"
```

- Both PUT and POST return arrays of objects → one code path, no special-casing.
- PUT works but POST does not → `upsert_rows` needs a documented fallback (insert scalars,
  then a follow-up PUT for multi-relations). This asymmetry is invisible from the spec,
  since both endpoints share the `RowEdit` schema.

#### T3 — Relation, no match *(silent corruption, error, or auto-create?)*

```bash
before=$(api "$API/docs/$DOC/tables/$TS/rows?limit=100" | jq '.items|length')
put "$C_REL" '"Zizzle-NoSuchRow"' ; show "$C_REL"
after=$(api "$API/docs/$DOC/tables/$TS/rows?limit=100" | jq '.items|length')
echo "Targets rows: $before -> $after"

# and an ID-shaped value that does not exist
put "$C_REL" '"i-ZZZZZZZZZZ"' ; show "$C_REL"
```

- Bare string, count unchanged → confirms silent in-cell corruption with no error and no
  row created. If confirmed, this would argue for pre-resolving every relation value and
  refusing to write on no match — a decision for the `tool-surface` topic, not settled here.
- HTTP 4xx from the PUT (re-run with `-i`) → the API validates; lean on it.
- Count increased by 1 → Coda auto-creates the target row, refuting the whole body of user
  reports. Surprising, and worth knowing.

#### T4 — Relation by display name; duplicates; numeric; comma-in-name

```bash
put "$C_REL" '"Bravo"' ; show "$C_REL"      # a — expect object, rowId == $B
put "$C_REL" '"Dup"'   ; show "$C_REL"      # b — two rows named Dup
put "$C_REL" '"123"'   ; show "$C_REL"      # c — numeric-looking, as a JSON string
put "$C_REL" 123       ; show "$C_REL"      # c2 — same, as a JSON number
put "$C_RELM" '"Smith, John"' ; show "$C_RELM"   # d — display value contains a comma
put "$C_RELM" '["Smith, John"]' ; show "$C_RELM" # d2 — same via array
```

- (b) object → the server silently picks one; **record which `rowId`** (lowest index?
  newest?). Your resolver should error on more than one match regardless.
- (b) bare string → ambiguity is rejected. Cleaner, still needs client handling.
- (c) PASS but (c2) FAIL → the 2019 numeric-coercion bug is alive; always send relation
  values as JSON strings.
- (d) resolving to **two broken references** while (d2) resolves to one good one → decisive
  argument for arrays-only in the server's API surface. If (d) yields one correct reference,
  the parser is smarter than documented — note it, still prefer arrays.

#### T5 — `disableParsing`

```bash
put "$C_REL" '"Alpha"' 'disableParsing=true' ; show "$C_REL"   # name + parsing off
put "$C_REL" "\"$A\""  'disableParsing=true' ; show "$C_REL"   # row ID + parsing off
```

- Name FAILs, ID PASSes → parsing governs *name* resolution only; ID resolution is a
  separate path, and `disableParsing=true` is safe alongside ID writes.
- Both FAIL → the flag disables relation resolution entirely. If confirmed, this would argue
  for never sending it on a payload touching a relation column — a decision for the
  `tool-surface` topic, not settled here. (This is what thread 24045 predicts.)
- Both PASS → the flag does not touch relations at all.

Sanity-check the documented use on a text column while here: writing `"00123"` with
`disableParsing=true` should read back `"00123"`, not `123`.

#### T6 — Person

```bash
put "$C_WHO"  '"you@example.com"'        ; show "$C_WHO"   # a — email
put "$C_WHO"  '"Your Full Name"'         ; show "$C_WHO"   # b — display name
put "$C_WHO"  "\"$A\""                   ; show "$C_WHO"   # c — a row ID (speculative)
put "$C_WHO"  '"nobody@nowhere.invalid"' ; show "$C_WHO"   # d — not in doc
put "$C_WHOM" '["you@example.com","teammate@example.com"]' ; show "$C_WHOM"   # e
```

- (a) `{"@type":"Person","name":…,"email":…}` confirms staff; make email the canonical
  person input.
- (c) PASS → an undocumented row-ID path exists for person columns (`person` shares
  `ReferenceColumnFormat` with `lookup`). Nobody has reported this; pure upside.
- (d) is Still unknown #4 — record the exact failure mode.
- (e) failing → retry `'"a@x.com,b@x.com"'`.

#### T7 — Select list, "Allow adding of new options" **OFF**

```bash
put "$C_SEL"  '"Green"'        ; show "$C_SEL"    # a — listed option
put "$C_SEL"  '"Chartreuse"'   ; show "$C_SEL"    # b — UNLISTED
api "$API/docs/$DOC/tables/$TW/columns/$C_SEL" | jq '.format.options'
put "$C_SELM" '["Red","Blue"]' ; show "$C_SELM"   # c — array
put "$C_SELM" '"Red,Blue"'     ; show "$C_SELM"   # d — comma string
```

#### T7b — Select list, "Allow adding of new options" **ON**

Flip the toggle on `Sel` in the UI, then repeat the unlisted-value write:

```bash
put "$C_SEL" '"Chartreuse2"' ; show "$C_SEL"
api "$API/docs/$DOC/tables/$TW/columns/$C_SEL" | jq '.format.options'
```

Interpretation across T7/T7b:

- Behaviour differs between OFF and ON → the toggle would govern API writes, exactly as the
  "parses as if typed" principle predicts. That's a problem: the toggle is not exposed
  in the API's `format` object, so the behaviour would be undetectable from the API — if
  confirmed, this would be an argument for validating against `format.options` defensively
  in every case, a decision for the `tool-surface` topic, not settled here.
- Behaviour identical in both states → the toggle is UI-only. Record which behaviour it is
  (option created / stored as off-list text / rejected).
- Value appears in `format.options` after the write → the API mutates column schema. An LLM
  typo would permanently alter the doc; validation becomes mandatory, not optional.

#### T8 — URL forms for relations *(cheap; expected to refute)*

```bash
BL=$(api "$API/docs/$DOC/tables/$TS/rows/$A" | jq -r .browserLink)
HR=$(api "$API/docs/$DOC/tables/$TS/rows/$A" | jq -r .href)
put "$C_REL" "\"$BL\"" ; show "$C_REL"
put "$C_REL" "\"$HR\"" ; show "$C_REL"
```

Either passing is a free extra input format (users paste links from the UI). Both failing
closes the question permanently. No source anywhere reports anyone trying this.

#### T9 — Clearing a cell

```bash
put "$C_REL"  '""'   ; show "$C_REL"
put "$C_RELM" '[]'   ; show "$C_RELM"
put "$C_REL"  'null' ; show "$C_REL"   # NB: `Value` excludes null — may 400
```

Establishes the documented "clear" semantic for `update_row`.

#### T10 — Image ingest vs hotlink

```bash
IMG='https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png'
put "$C_IMG" "\"$IMG\"" ; show "$C_IMG"
put "$C_IMG" "[\"$IMG\"]" ; show "$C_IMG"     # array form, per Koleda
```

- `{"@type":"ImageObject","url":…}` where the returned `url` is a **codahosted / superhuman
  domain** → Coda ingested the file, confirming the staff post and refuting the stale FAQ.
- Returned `url` still points at `upload.wikimedia.org` → hotlink only, which would mean the
  FAQ is right for this column type. If so, repeat against `attachments` and
  `imageReference` columns before concluding.

#### T11 — Canvas, checkbox, duration, currency

```bash
put "$C_CNV" '"# Heading\n\n**bold** text"' ; show "$C_CNV"   # expect literal characters
put "$C_CHK" 'true'        ; show "$C_CHK"
put "$C_CHK" '"true"'      ; show "$C_CHK"   # does the string coerce?
put "$C_DUR" '"3 hours"'   ; show "$C_DUR"   # Packs-SDK-style string
put "$C_DUR" '10800'       ; show "$C_DUR"   # seconds as a number
put "$C_CUR" '12.34'       ; show "$C_CUR"   # bare number
put "$C_CUR" '"$12.34"'    ; show "$C_CUR"   # formatted string
```

Nothing authoritative exists for checkbox, duration or currency. Whatever these return is
the only evidence there is — record it carefully.

#### T12 — Date: ISO 8601 vs `MM/DD/YYYY`

```bash
put "$C_DT" '"2026-03-04"'  ; show "$C_DT"   # a — ISO 8601, unambiguous
put "$C_DT" '"03/04/2026"'  ; show "$C_DT"   # b — ambiguous under locale
put "$C_DT" '"04/03/2026"'  ; show "$C_DT"   # c — the transposition
put "$C_DT" '1772582400'    ; show "$C_DT"   # d — Unix timestamp
```

- (a) always yields 2026-03-04. (b) and (c) yielding *different* dates from each other
  demonstrates the locale hazard concretely; whichever way this doc's regional settings
  resolve them, another user's doc may differ. **This test exists to justify the ISO-8601-only
  rule, not to find a workaround.**
- (d) confirms the vendor's Unix-timestamp claim; note the Pacific-time rendering caveat.

### Cleanup

Delete the scratch doc. Note that T7b may have permanently added a select option and T3 may
have added a `Targets` row if auto-create turns out to be real.

---

## Still unknown

In priority order. Each entry names the test that settles it.

1. **Select-list behaviour for a value not in the option list.** Answered by T7/T7b on
   2026-09-06: an unlisted value is accepted and stored in the cell with no error, and
   `format.options` is unchanged afterward — the unlisted value is not added as an option.
   What is still open is whether the "Allow adding of new options" toggle changes this at
   all, since the toggle is not exposed in the API's `format` object and the run could not
   tell which state the scratch doc's `dropdown` column was in — see the T7/T7b results.
2. **Duplicate display names in a relation target — which row wins.** Cited by users as the
   reason row IDs were needed; never answered by staff. → **T4b.**
3. **Whether `disableParsing=true` blocks row-ID resolution as well as name resolution.**
   One user datapoint covers names only; no staff statement exists on either. → **T5.**
4. **The failure mode when a person is not in the doc or workspace.** Oleg's 2019 "already
   needs to be in the doc" is the only constraint anyone has stated, and he does not say
   whether it errors, no-ops, or stores plain text. → **T6d.**
5. **Array-of-row-IDs on `POST` / `upsertRows`,** as opposed to `PUT` / `updateRow` where
   staff confirmed it. → **T2b.**
6. **Checkbox, duration and currency write formats.** Checkbox is answered by T11 on
   2026-09-06: both the JSON boolean `true` and the JSON string `"true"` read back as
   boolean `true`. Duration and currency remain fully unknown — zero staff posts, zero
   StackOverflow answers, zero vendor docs, only cross-path hints from the Packs SDK — and
   remain blocked: no duration or currency column exists in the scratch doc. → **T11.**

Lower priority, also unresolved: whether a browser link or API `href` is accepted for a
relation (**T8**); whether person columns accept a row ID (**T6c**); ingest-vs-hotlink
across the three image/file column types (**T10**); the documented default of
`disableParsing`; and whether `time` and `packObject` columns are writable at all
(untested, no sources). `reaction` writability is now answered — see the Results section:
the column is writable, accepts a bare emoji string or a JSON array of emoji, replaces
rather than accumulates on a second array write, clears on an empty array, and does not
validate its contents as emoji (plain non-emoji text was accepted and stored).

---

## Results

Paste raw output under each slot. Record the date and the API version header if present.

Run on: `2026-09-06` — token scope: not captured by the run output — scratch doc: `6vqpBu-VYd`

Run tag `cellwrite-20260906T033523Z`. Probe rows were created and left in place rather
than cleaned up: `i-t9LSfemxfl` (`Name=cellwrite-20260906T033523Z-t1`) in `test-table-01`
(`grid-PH5-RNMCB1`), and `i-_0US3LVT0m` (`Name=cellwrite-20260906T033523Z-t2`) in
`test-table-02` (`grid-EETnwpzofr`). All writes in this run completed (HTTP 202, then
`mutationStatus` polled to `completed: true`) before the read-back that follows it.

### T1 — relation, single, by row ID

Blocked — needs a relation column. None exists in either table of this scratch doc.

### T2 — relation, multi, array of row IDs (PUT)

Blocked — needs a relation column.

### T2b — relation, multi, array of row IDs (POST / upsertRows)

Blocked — needs a relation column.

### T3 — relation, no match (name-shaped and ID-shaped)

Blocked — needs a relation column.

### T4 — relation by display name: (a) simple (b) duplicate (c/c2) numeric (d/d2) comma-in-name

Blocked — needs a relation column.

### T5 — disableParsing, name and row ID

Blocked — needs a relation column.

### T6 — person: (a) email (b) name (c) row ID (d) not in doc (e) multi

Blocked — the only person column in this scratch doc, `Modified by`, is calculated and so
not writable. Needs a non-calculated person column.

### T7 — select list, "Allow adding of new options" OFF

Column under test: `dropdown` (`c-nACxS-2d_4`) in `test-table-01`, existing options
Small/Medium/Large/X-Large.

```
--- Reading dropdown column format BEFORE any writes ---
{
  "type": "select",
  "options": [
    {"name": "Small", "foregroundColor": "#8B6C1D", "backgroundColor": "#FDF3D8"},
    {"name": "Medium", "foregroundColor": "#A12B86", "backgroundColor": "#F8E7F3"},
    {"name": "Large", "foregroundColor": "#187B34", "backgroundColor": "#E2F8E8"},
    {"name": "X-Large", "foregroundColor": "#0F58BD", "backgroundColor": "#DDEDFD"}
  ]
}

--- T7/T7b (a) -- writing an already-listed option value: Small ---
  requestId=mutate:f9c42c89-1784-4234-a6c3-0f48d7dbef7c
  mutation mutate:f9c42c89-1784-4234-a6c3-0f48d7dbef7c completed
  readback (valueFormat=rich) for column c-nACxS-2d_4:
"```Small```"
```

Writing the listed value `Small` stored it. Note the readback itself: the rich-format
value for this string-typed column comes back wrapped in a markdown code fence
(`` ```Small``` ``) rather than as a bare JSON string — unlike the date and checkbox
readbacks below (T12, T11), which return unwrapped native JSON types. That wrapping is
part of what the API returned, not something added in this write-up.

### T7b — select list, "Allow adding of new options" ON

This scratch doc's `dropdown` column was not toggled between OFF and ON for this run —
the toggle is not exposed in the API's `format` object, so the script had no way to set or
detect it, and (a) and (b) below were both run against whatever state the toggle is
currently in. This run therefore cannot distinguish a T7 (OFF) result from a T7b (ON)
result; it records the behaviour of one unknown toggle state only.

```
--- T7/T7b (b) -- writing a value NOT present in format.options: ZZ-Unlisted-cellwrite-20260906T033523Z ---
  requestId=mutate:53640170-1362-451c-99f5-2a3b4f245e15
  mutation mutate:53640170-1362-451c-99f5-2a3b4f245e15 completed
  readback (valueFormat=rich) for column c-nACxS-2d_4:
"```ZZ-Unlisted-cellwrite-20260906T033523Z```"

--- T7/T7b (c) -- re-reading format.options AFTER both writes, to see whether the schema mutated ---
[
  {"name": "Small", "foregroundColor": "#8B6C1D", "backgroundColor": "#FDF3D8"},
  {"name": "Medium", "foregroundColor": "#A12B86", "backgroundColor": "#F8E7F3"},
  {"name": "Large", "foregroundColor": "#187B34", "backgroundColor": "#E2F8E8"},
  {"name": "X-Large", "foregroundColor": "#0F58BD", "backgroundColor": "#DDEDFD"}
]
  format.options UNCHANGED -- the unlisted write did not add a new option to the schema.
```

The plainly unlisted value `ZZ-Unlisted-cellwrite-20260906T033523Z` was accepted and
stored in the cell with no HTTP error, and `format.options` read back unchanged afterward
— the unlisted value was not added as an option. A select cell can hold a value that is
not one of its own options. Whether the toggle changes this outcome is still open; if it
does, that state would be undetectable from the API's `format` object, which would argue
for validating a select write against `format.options` defensively regardless of the
toggle — a decision for the `tool-surface` topic, not settled here.

### T8 — relation via browserLink and href

Blocked — needs a relation column.

### T9 — clearing a cell

Blocked — needs a relation column.

### T10 — image: ingest vs hotlink, single and array

Blocked — no image column exists in this scratch doc.

### T11 — canvas, checkbox, duration, currency

Duration and currency are blocked — no such columns exist in this scratch doc. Canvas and
checkbox ran, against `Notes`/canvas (`c-orqRPHUjBy`) and `checkbox` (`c-iuWNGg-fcV`) in
`test-table-01`.

```
--- T11 checkbox (a) -- writing JSON boolean true ---
  requestId=mutate:7d71cc1f-4da2-4b7e-ac18-26e9b3e93a89
  mutation mutate:7d71cc1f-4da2-4b7e-ac18-26e9b3e93a89 completed
  readback (valueFormat=rich) for column c-iuWNGg-fcV:
true

--- T11 checkbox (b) -- writing the JSON STRING "true" (does it coerce to boolean true, or fail/store literally?) ---
  requestId=mutate:1c7c5dcc-9abd-44aa-ad10-fde35a84eabe
  mutation mutate:1c7c5dcc-9abd-44aa-ad10-fde35a84eabe completed
  readback (valueFormat=rich) for column c-iuWNGg-fcV:
true

--- T11 canvas -- writing markdown-looking text; expect literal characters, not rendered formatting ---
  requestId=mutate:5c1b4a2b-9286-4037-a8a4-32fd4989e4b7
  mutation mutate:5c1b4a2b-9286-4037-a8a4-32fd4989e4b7 completed
  readback (valueFormat=rich) for column c-orqRPHUjBy:
"```# Heading\n\n**bold** text```"
```

Both the JSON boolean `true` and the JSON string `"true"` read back as boolean `true` —
the string coerces. The markdown-looking canvas text was stored literally: the read-back
carries the `#` and `**` characters as plain text rather than rendering them, wrapped (as
in T7 above) in a markdown code fence in the rich-format value.

### T12 — date: ISO 8601 vs MM/DD/YYYY vs Unix timestamp

Column under test: `date` (`c-fsVFh3y1p9`) in `test-table-01`.

```
--- T12 (a) -- ISO 8601, unambiguous: 2026-03-04 ---
  requestId=mutate:daded53b-bde9-418c-9c54-52dbbf349164
  mutation mutate:daded53b-bde9-418c-9c54-52dbbf349164 completed
  readback (valueFormat=rich) for column c-fsVFh3y1p9:
"2026-03-04T00:00:00.000-05:00"

--- T12 (b) -- ambiguous under locale: 03/04/2026 ---
  requestId=mutate:1ed198d1-d093-4f2a-9861-19e21dc6a207
  mutation mutate:1ed198d1-d093-4f2a-9861-19e21dc6a207 completed
  readback (valueFormat=rich) for column c-fsVFh3y1p9:
"2026-03-04T00:00:00.000-05:00"

--- T12 (c) -- the transposition: 04/03/2026 ---
  requestId=mutate:5f1f1dce-98bc-4713-9b49-572d229c2591
  mutation mutate:5f1f1dce-98bc-4713-9b49-572d229c2591 completed
  readback (valueFormat=rich) for column c-fsVFh3y1p9:
"2026-04-03T00:00:00.000-04:00"

--- T12 (d) -- Unix timestamp: 1772582400 ---
  requestId=mutate:21b8d07d-bded-46c3-ae10-de76b26a5c5a
  mutation mutate:21b8d07d-bded-46c3-ae10-de76b26a5c5a completed
  readback (valueFormat=rich) for column c-fsVFh3y1p9:
1772582400
```

(a) ISO `2026-03-04` read back as `2026-03-04T00:00:00.000-05:00`. (b), the slash form
`03/04/2026`, read back identically — parsed as 4 March, i.e. MM/DD. (c), the
transposition `04/03/2026`, read back as `2026-04-03T00:00:00.000-04:00` — 3 April. So a
day-first date is silently reinterpreted as month-first; both (b) and (c) were accepted
with no error, and each resolved to a different calendar date than the other despite
differing only in which two numbers come first. This is the locale hazard the ISO-8601-only
rule (`tool-surface` topic) exists to avoid; the differing UTC offsets between (c) and the
other rows (-04:00 vs -05:00) are ordinary daylight-saving for early March versus April,
not a finding. (d), the Unix timestamp `1772582400`, was **not** parsed as a date at all —
it read back as the bare number `1772582400`, contradicting the vendor's stated
Unix-timestamp-conversion behaviour for at least this column/deployment.

### Reaction column — writability (test added for this run; not in the original plan)

The plan had no test for the `reaction` column type — it appears in "Still unknown" only as
one of three column types (`time`, `reaction`, `packObject`) with zero sources on
writability at all. The scratch doc's `test-table-02` has a writable-looking `reaction`
column (`c-UnvrVRuVfv`), so this run added a probe for it.

```
--- Reaction (a) -- bare JSON string, single emoji: "\xf0\x9f\x91\x8d" ---
  requestId=mutate:479254f3-716d-4503-8a74-e58cdac93a2d
  mutation mutate:479254f3-716d-4503-8a74-e58cdac93a2d completed
  readback (valueFormat=rich) for column c-UnvrVRuVfv:
"```👍```"

--- Reaction (b) -- JSON array containing one emoji ---
  requestId=mutate:5e50fc96-ef22-4206-9f46-b7375e45c79c
  mutation mutate:5e50fc96-ef22-4206-9f46-b7375e45c79c completed
  readback (valueFormat=rich) for column c-UnvrVRuVfv:
[
  "```👍```"
]

--- Reaction (c) -- JSON array with two distinct emoji (does it accumulate, replace, or reject?) ---
  requestId=mutate:c499acfb-3675-4d74-9fb2-82ba6b32c0dc
  mutation mutate:c499acfb-3675-4d74-9fb2-82ba6b32c0dc completed
  readback (valueFormat=rich) for column c-UnvrVRuVfv:
[
  "```👍```",
  "```🎉```"
]

--- Reaction (d) -- plain non-emoji text: does it reject, coerce, or store literally? ---
  requestId=mutate:913de8e1-0b36-4866-990e-9f1bbfc4ba5f
  mutation mutate:913de8e1-0b36-4866-990e-9f1bbfc4ba5f completed
  readback (valueFormat=rich) for column c-UnvrVRuVfv:
"```nice```"

--- Reaction (e) -- clearing with an empty array ---
  requestId=mutate:b181fb8c-5d61-432a-ab94-27ad404f6199
  mutation mutate:b181fb8c-5d61-432a-ab94-27ad404f6199 completed
  readback (valueFormat=rich) for column c-UnvrVRuVfv:
[]
```

The column is writable. (a) a bare emoji string stored. (b) a one-element array stored.
(c) a two-element array of distinct emoji stored both — a second array write **replaces**
the cell's contents rather than accumulating onto the first write's emoji. (d) plain
non-emoji text, `nice`, was accepted and stored — the column does not validate its
contents as emoji. (e) an empty array cleared the cell. Every stored string value came
back wrapped in the same markdown code fence noted under T7 and T11.

### Conclusions drawn / document updates made

```
T7/T7b, T12, and the checkbox/canvas halves of T11 ran live on 2026-09-06 against
scratch doc 6vqpBu-VYd (run tag cellwrite-20260906T033523Z); a reaction-column test
was added since the plan had none. T1-T6, T8, T9, T10, and the duration/currency
halves of T11 remain blocked for lack of a relation, image, non-calculated person,
duration, or currency column in this doc.

Updated in this file as a result:
- Status line at the top of the document.
- "Still unknown" item 1 (select unlisted-value behaviour): answered -- accepted,
  stored, schema unchanged; the toggle's effect remains open since the API cannot
  report or set it.
- "Still unknown" item 6 (checkbox/duration/currency): checkbox answered (string
  "true" coerces to boolean true); duration and currency remain fully unknown and
  blocked.
- "Still unknown" closing paragraph: reaction writability answered.

Not updated: the "Confirmed" section's per-column-type entries for select, date,
checkbox, canvas, and reaction still read as they did before this run. Folding
these results into Confirmed (with confidence markers) and into "Contradictions
and traps" (the Unix-timestamp non-conversion contradicts the vendor's stated
behaviour) is left as follow-up, since this pass was scoped to the Results
section only.
```
