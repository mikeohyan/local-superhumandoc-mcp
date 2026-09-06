# Superhuman Docs API — markdown write/export fidelity test plan

**Date:** 2026-09-03
**Target:** `https://docs.superhuman.com/apis/v1` (formerly Coda API v1; specs are byte-identical)
**Status:** B3, B4 and B5 ran on 2026-09-06 against a throwaway scratch doc —
see the Results section at the bottom. B1, B2 and B6 remain blocked: they
require the manual browser setup described under "Manual browser prep" below —
a scratch page containing a real table, button, formula control, callout,
divider, image, collapsible list and pull quote, duplicated twice in the UI to
produce SCRATCH-A/B/C — which does not yet exist.

## Before you run this

- Requires an **API token** (from `/account`) and a **throwaway scratch doc**.
- **NEVER run this against a doc anyone cares about.** Tests B1 and B2 are *deliberately destructive*: they issue whole-page `insertionMode: "replace"` writes against pages that contain real tables, buttons and controls, specifically to find out whether those native objects get destroyed. Assume everything on SCRATCH-A / SCRATCH-B / SCRATCH-C will be lost.
- Takes roughly **15 minutes**, dominated by export polling (~5-10 s per export, ~8 exports) plus a one-time manual page setup in the browser.
- Tests are ordered so the most dangerous unknown (destructive `replace`) is settled first.

## Why this plan exists

Coda staff, in the announcement thread for these exact page-content endpoints,
said plainly that a round trip through HTML or markdown can lose information and
that these endpoints are best used for import/export, not page editing — see the
full quote and source under "Round-trip fidelity — the constraint that shapes
the tool surface" in `docs/reference/api-operational-constants.md` §2.5.

That is the ceiling on every honest claim our `read_page` / `edit_page` tools can make. Beyond that statement, **no one — Coda, Superhuman, or any open-source implementation — has documented per-construct markdown fidelity.** No working implementation reviewed (orellazri/coda-mcp, TJC-LP/coda-mcp-server) contains any sanitizer, fidelity note, or destructive-write warning. This plan closes that gap empirically.

---

# Findings (desk research, pre-test)

Confidence markers: **[S]** confirmed by Coda/Superhuman staff or first-party docs · **[C]** inferred from working code / first-party tool design · **[?]** speculative, undocumented anywhere — must be tested.

## Primary sources

| Source | What it establishes |
|---|---|
| [Import Markdown into Docs (help center)](https://help.coda.io/hc/en-us/articles/39555724729869-Import-Markdown-into-Coda) | "Superhuman Docs supports the **basic syntax** markdown flavor and, as such, **does not support text colors, highlights, and other extended features**." Basic syntax (markdownguide.org) **excludes** tables, task lists, strikethrough, footnotes, fenced code, autolinks. |
| [Official Docs MCP tools & endpoints](https://coda.io/resources/mcp/tools-and-endpoints) | `content_read` takes `contentTypesToInclude` = **markdown, tables, formulas, controls, comments** — markdown is a *separate channel* from tables/formulas/controls. `content_modify` has **no whole-page replace**; only `insert_element`, `replace_element_text`, `replace_text`, `delete_element`, anchored by `elementId`. `markdownIncludeAnnotations` "adds `[[elementId]]` for editing". Verbatim: **"For tabular data, prefer `table_create` over Markdown tables."** |
| [Page attachments export thread](https://connect.superhuman.com/t/coda-api-v1-how-to-retrieve-page-level-attachments-not-just-table-files-when-exporting-to-markdown-html/57065) | Page-level attachments are omitted from the markdown export and present in the HTML export — staff-confirmed; see `docs/reference/api-operational-constants.md` §2.5. HTML export carries `<img src>` + `data-coda-blob-id`. |
| [Transform text with paragraph styles](https://help.coda.io/hc/en-us/articles/39555971852941-Transform-text-with-paragraph-styles) + [Format and style text](https://help.coda.io/hc/en-us/articles/39555789925389-Format-and-style-text) | Native canvas blocks: plain text, **H1/H2/H3 only**, bulleted/numbered/checklist/**collapsible** lists, block quotes, **pull quotes**, code blocks, **callouts**. Native inline: bold, italic, underline, strikethrough, inline code. |
| [markdown via API thread](https://connect.superhuman.com/t/markdown-via-api/46228) | Luis Curiel (Coda), Feb 2024: markdown format works for **pages**; confirmed Mar 2024 that markdown into **canvas columns in table rows** "is not possible at the moment". |
| [orellazri/coda-mcp](https://github.com/orellazri/coda-mcp) `src/helpers.ts`, `src/server.ts` | Reference TS implementation: export -> poll (5x5s) -> GET downloadLink. **Zero** sanitizing, validation, fidelity notes or warnings. Always `format:"markdown"`, never HTML. Its `coda_duplicate_page` does export-markdown -> create-page-from-markdown, i.e. it silently ships the lossy round trip as "duplicate". |
| [TJC-LP/coda-mcp-server](https://github.com/TJC-LP/coda-mcp-server) | Python prior art. Same: no fidelity documentation, no replace guard. |
| Local spec `coda-openapi.yaml` v1.6.0 | `Table`, `Control`, `Formula` **all carry `parent: PageReference`** -> a pre-write guard is implementable. `PageContentItem` has `id` (`cl-2ZUJuRhNuN`) matching the `elementId` example format, and `itemContent` is **optional** — non-line elements may surface as bare IDs. `GET /mutationStatus/{requestId}` is how you retrieve `MutationStatus.warning`. |

## Fidelity table — markdown constructs

| Markdown construct | Supported on write? | Preserved on export to markdown? | Round-trip stable? |
|---|---|---|---|
| `#`/`##`/`###` (h1-h3) | Yes — native `h1/h2/h3` **[S]** (PageLineStyle enum + help center "three heading sizes") | Yes — confirmed by B3, byte-identical text | Confirmed by B3: a setext H1 (`Setext H1` / `=========`) is written as ATX `# Setext H1` on export — no setext form survives. h1-h3 content itself round-trips unchanged |
| `####`-`######` (h4-h6) | **No native target exists** — canvas has exactly 3 levels **[S]**. Confirmed by B3: markdown h4-h6 write as plain paragraph text, heading text intact, no bold and no clamping to h3 (`T_content.json` shows `"style":"paragraph"`) | n/a — no heading style survives on export via either write path | **No.** Confirmed unstable, and the exact degradation depends on write format: plain paragraph via markdown (B3), but `### **bold**` (h3-level, bolded text) via HTML (B4) |
| `**bold**`, `*italic*` | Yes — native; first-party MCP lists "Inline formatting: bold, italic" **[S]** | Yes — confirmed by B3 | Confirmed stable by B3: `**bold**` and `*italic*` delimiters are preserved unchanged, no `_` substitution observed |
| `~~strikethrough~~` | Confirmed by B3: accepted and produces real struck text despite the basic-syntax-only documentation | Confirmed by B3: exports back as `~~strikethrough~~` | Confirmed stable by B3 |
| `` `inline code` `` | Confirmed by B3 | Confirmed by B3: exports unchanged | Confirmed stable by B3 |
| `[text](url)` links | Basic syntax; staff-confirmed markdown works for pages **[S]** | Yes — export "works fine for text, links" **[S]** | Confirmed by B3: inline links round-trip unchanged; a reference-style link (`[link][ref]`) normalizes to inline on export; an autolink (`<https://example.com>`) and a bare URL both come back rewritten as `[https://example.com](https://example.com)` |
| `![alt](url)` images | Confirmed by B3: accepted on markdown write | Corrected by B3 — **not omitted.** Comes back as `[alt text](url)`: the leading `!` is dropped and the title attribute is lost, so it silently degrades into a plain link rather than disappearing. (The earlier "omitted from export" note concerns page-level *attachments*, a different object from an inline image in `canvasContent` — see the corrected note below.) Confirmed by B4: the same image written as HTML `<img>` is instead dropped from the export entirely, with no link left behind | **No.** Confirmed unstable, and unstable in two different ways depending on write format |
| GFM tables (`\| a \| b \|`) | Corrected by B3 — a markdown pipe table **does** create a real native Coda table (`grid-D53nA4DcMR`), contrary to the "likely literal text" assumption | Confirmed by B3, with a defect: export **demotes the real header row to a data row** and synthesizes a generic `Column 1`/`Column 2` header above it. Confirmed by B4: writing the equivalent `<table>` as HTML instead keeps the true header row (`Column A`/`Column B`), with no synthesized header. Confirmed by B3: the table is invisible to the page-content read either way — no table/grid item appears among `T_content.json`'s items at all | **No.** Confirmed by B5: a second write-export cycle over the already-corrupted table adds another copy of the synthesized header as a further data row — each cycle grows the table |
| `---` / `***` horizontal rule | Confirmed by B3: none of `---`, `***`, `___` (each on its own blank-line-separated line) produced a divider or any other visible construct — no corresponding item appears in `T_content.json` | Confirmed by B3: **all three vanish entirely** from the markdown export. The setext-H2 trap (`---` directly after a text line, no intervening blank line) was not exercised — torture.md put a blank line before each rule — so that specific case is still **[?]** | **No** — and unstable across generations too: B5 shows the blank-line residue gen-1 left behind shrinks further at gen-2 |
| Fenced code ` ```lang ` | Confirmed by B3: `` ```python `` writes as a native code block | Confirmed by B3: exports back as a fence with the language tag intact. Confirmed by B4: writing the same code as HTML (`<pre class="python">`) **loses the language tag** — exports as a bare fence | Confirmed stable via markdown write (B3); confirmed to drop the tag via HTML write (B4) |
| `> blockquote` | Yes — native `blockQuote` **[S]** | Confirmed by B3 | Confirmed by B3: nested `> >` flattens to a single level (both lines come back as plain `>` quotes at the same level). Confirmed by B5 to decay further: on a second write-export cycle the flattened quote's continuation line loses its `>` marker entirely and becomes an unquoted paragraph line |
| Nested lists | Native (`lineLevel` "for indentable elements") **[S]** | Confirmed by B3 | Confirmed by B3: three nesting levels survive with 2-space-per-level indentation; all bullet markers (`*`, `+`, `-`) normalize to `-` |
| Ordered lists | Native `numberedList` **[S]** | Confirmed by B3 | Confirmed by B3: a list starting at `5.` is renumbered to `3.` (continuing the outer sequence), and lazy numbering (`1.` repeated) is renumbered to `4.` — sequential renumbering, not preserved as written |
| `- [ ]` task lists | Confirmed by B3: creates real native `checkboxList` items (`T_content.json`), despite the basic-syntax-only documentation | Confirmed by B3: exports back as literal `- [ ]` / `- [x]` | Confirmed stable via markdown write (B3). Confirmed by B4 to differ sharply via HTML write: `<input type="checkbox">` list items lose the checkbox entirely on export, leaving bare list items with no `[ ]`/`[x]` marker at all |
| Footnotes `[^1]` | Confirmed by B3: `[^1]` and its `[^1]: body` definition pass through as literal text, unrecognized | Confirmed by B3: literal text, unchanged | **No** — not a construct via markdown write. Confirmed by B4 to differ via HTML write: real footnote HTML (`<a href="#fn1">` / footnotes section) is not reconstructed as `[^1]` syntax on export — it comes back as a plain markdown link (`[#fn1](#fn1)`) |
| LaTeX / `$...$` math | Confirmed by B3: both inline `$E = mc^2$` and block `$$...$$` pass through as literal text | Confirmed by B3: literal text, unchanged (aside from incidental hard-break whitespace added around the block form) | **No** — not a construct |
| `@mentions` / page refs | Confirmed by B3: `@Someone` and `#Tag` both pass through as literal text, not created as real mentions/tags | Confirmed by B3: literal text, unchanged | **No** — not a construct |
| Raw HTML inside markdown | Confirmed by B3: a `<div class="raw-html"><b>...</b></div>` block written inside markdown content passes through as literal text, tags and all | Confirmed by B3: literal text, unchanged. Confirmed by B4 to differ when the *page itself* is written as HTML: the same div is not preserved as raw HTML on export — it flattens to `**raw html block**`, keeping only the `<b>` as markdown bold | **No** — behavior differs by write format |
| Text color / highlight | **Explicitly unsupported** in the markdown flavor **[S]**; first-party MCP uses proprietary tags **[S]** | Lost **[S]** | **No** |
| Underline | Native inline style, **no markdown syntax at all** **[S]** | Lost **[C]** | **No** |

## Coda-native content with no markdown equivalent (export direction)

| Native object | What markdown export does |
|---|---|
| Tables / views | Corrected by B3/B4 — a markdown or HTML pipe/`<table>` write **creates a real native Coda table** (confirmed grid objects `grid-D53nA4DcMR` and `grid-vSs9GXsAi0`), not a flattened/omitted rendering. It is invisible to the page-content read (no item for it appears among `T_content.json`'s items). Confirmed by B3: its header row is corrupted on a markdown round trip — demoted to a data row under a synthesized `Column 1`/`Column 2` header, and B5 confirms this worsens by one duplicate row per further write-export cycle. A table written via HTML instead keeps its true header row (B4) |
| Buttons, controls, formula chips | Separate `controls` / `formulas` content types **[S]**; separate `/docs/{docId}/controls` and `/formulas` endpoints **[S]** -> almost certainly flattened to a value or omitted **[C]**. Not exercised by B3/B4/B5 — torture.md/torture.html contained no button, control or formula chip; still **[?]** |
| Images / page attachments | Page-level *attachments* are omitted from markdown export, present in HTML export **[S]** — see `docs/reference/api-operational-constants.md` §2.5. That is a different object from an inline image written via `canvasContent`: confirmed by B3, an inline `![alt](url)` markdown image is **not** omitted on export — it degrades to a plain link (`!` and title dropped). Confirmed by B4: the same inline image written as HTML `<img>` **is** dropped entirely from the markdown export, with no trace |
| Callouts | Native block **[S]**, not in `PageLineStyle` **[S]** -> flattened in the cheap read; markdown export emission unknown **[?]** |
| Pull quotes, collapsible lists | In `PageLineStyle` (cheap read sees them) **[S]** but **no markdown syntax** -> downgraded on export **[C]**, unrecreatable from markdown **[S]** |
| Dividers | Not in `PageLineStyle` at all **[S]** |
| Embeds, subpage links | Embed is a page *type* set only at creation, "cannot be toggled after the fact" **[S]**; inline embeds have no markdown form -> likely a bare URL **[?]** |
| Comments | Separate content type **[S]** — never in markdown |

## `format: "html"` vs `format: "markdown"` on write

- HTML is the format Coda uses in its own examples (`<p><b>This</b> is rich text</p>` in both the spec and the announcement post) **[S]**, and `MutationStatus.warning`'s documented example is *"Initial page HTML was invalid."* **[S]** — the warning vocabulary is HTML-centric, suggesting HTML is the primary ingestion path.
- HTML is confirmed **richer on export** (images/attachments survive there, not in markdown) **[S]**. Symmetric richness on write is a reasonable but **unproven** inference **[C]**.
- **For tables specifically:** nobody has documented this. Working assumption until B4 is run: **neither format reliably creates a native Coda table; treat table creation as out of scope for `edit_page`.**
- Real-world signal: `chalbersma/sphinx-to-coda-action` pushes docs into Coda pages using **`format: "html"`** with image-URL rewriting to absolute S3 URLs **[C]** — the one production pipeline found chose HTML.

## Risk assessment — blunt

1. **Whole-page read-modify-write over markdown is not a supported editing model.** Coda says so directly. Their own MCP does not do it: it reads markdown *with `[[elementId]]` annotations* and edits via `replace_element_text` / `delete_element` scoped to those IDs, with atomic rollback across <=10 operations. The `tool-surface` topic subsequently adopted that shape — element-scoped, ID-anchored editing — for the same reason.
2. **`insertionMode: "replace"` with no `elementId` is a page-wide content wipe followed by a markdown-only rebuild.** Anything markdown cannot express — tables, buttons, controls, callouts, dividers, images, embeds, collapsible lists, pull quotes, colors — is by construction not in the payload. Whether the backend preserves native objects it can't see is **undocumented**. The spec describes replace-without-elementId as operating "on the entire page". **Rated: likely destructive, unconfirmed. Test B1 before shipping anything.**
3. **Failures are silent.** Writes return **202 + requestId**; malformed content surfaces only as `MutationStatus.warning` on a *separate* `GET /mutationStatus/{requestId}` call that no open-source implementation makes.
4. **Instability compounds.** If export normalizes (`*`->`-`, renumbered lists, reflowed indentation), every RMW cycle rewrites lines the agent never touched — spurious diffs, broken text anchors, decayed content.

**What the tool surface did with this.** The findings above were written before
any tool surface existed and originally read as recommendations. They have since
been decided by the `tool-surface` topic (see `_rfc/README.md`), so they are
recorded here as the evidence trail rather than as choices this file makes:

- The page-markdown read declares its own lossiness in its tool description —
  images, tables, buttons, controls, callouts and dividers may be missing or
  flattened, and it is not the document.
- Editing is element-scoped and anchored on IDs obtained from the synchronous
  page-content read; additive editing is a separate tool from replacement.
- Whole-page replacement is a separate, explicitly named destructive tool, gated
  behind an environment flag. Its `force` parameter is optional and exists to
  override the guard below when it refuses — it is not required on a page the
  guard passes.
- A pre-write guard lists the document's tables, controls and formulas filtered
  on `parent.id == pageId` — all three schemas carry `parent: PageReference` —
  and refuses, naming what it found.
- Every write polls `GET /mutationStatus/{requestId}` and surfaces `warning`
  verbatim.

---

# Test plan

## B0. Setup (2 min)

```bash
export TOKEN='<API token from /account>'
export DOC='<docId>'                 # from the URL .../d/_d<docId>
export API='https://docs.superhuman.com/apis/v1'
mkdir -p ~/shdoc-test && cd ~/shdoc-test

api() { curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$@"; }

md_export() {  # $1=pageId $2=outfile $3=format(markdown|html)
  local fmt=${3:-markdown}
  local rid=$(api -X POST "$API/docs/$DOC/pages/$1/export" -d "{\"outputFormat\":\"$fmt\"}" | jq -r .id)
  sleep 2
  for i in $(seq 1 25); do
    local j=$(api "$API/docs/$DOC/pages/$1/export/$rid")
    case "$(echo "$j" | jq -r .status)" in
      complete) curl -sS "$(echo "$j" | jq -r .downloadLink)" -o "$2"; echo "OK -> $2"; return 0;;
      failed)   echo "EXPORT FAILED: $j"; return 1;;
    esac
    sleep 2
  done
  echo "TIMEOUT"; return 1
}

mutwait() {  # $1=requestId  -- THIS is where degradation shows up
  for i in $(seq 1 20); do
    local j=$(api "$API/mutationStatus/$1")
    [ "$(echo "$j" | jq -r .completed)" = true ] && { echo "MUTATION: $j"; return 0; }
    sleep 2
  done
  echo "MUTATION still incomplete"
}

inventory() {  # $1=pageId -- native objects owned by this page
  echo "--- tables:";   api "$API/docs/$DOC/tables?limit=100"   | jq -r --arg p "$1" '.items[]|select(.parent.id==$p)|"\(.id)\t\(.name)"'
  echo "--- controls:"; api "$API/docs/$DOC/controls?limit=100" | jq -r --arg p "$1" '.items[]|select(.parent.id==$p)|"\(.id)\t\(.name)"'
  echo "--- formulas:"; api "$API/docs/$DOC/formulas?limit=100" | jq -r --arg p "$1" '.items[]|select(.parent.id==$p)|"\(.id)\t\(.name)"'
}
```

### Manual browser prep (required — v1 cannot create tables/buttons)

In a **scratch doc**, create a page named `SCRATCH-A` containing, in order:

1. an H1
2. a paragraph
3. a **real table** (2 columns x 2 rows)
4. a **button**
5. a **formula control**
6. a **callout**
7. a **divider**
8. an **image**
9. a **collapsible list**
10. a **pull quote**

Then **duplicate that page twice in the UI** -> `SCRATCH-B`, `SCRATCH-C`.
(Duplicate in the UI, not via the API — API duplicate already round-trips through markdown and would pre-destroy the objects under test.)

```bash
api "$API/docs/$DOC/pages?limit=100" | jq -r '.items[]|"\(.id)\t\(.name)"'
export A='canvas-...'; export B='canvas-...'; export C='canvas-...'
```

## B1. Does a blunt `replace` destroy native objects? (MOST DANGEROUS — run first, on SCRATCH-A)

```bash
inventory "$A" | tee A_before.txt
md_export "$A" A_before.md
api "$API/docs/$DOC/pages/$A/content?limit=200" > A_content_before.json

RID=$(api -X PUT "$API/docs/$DOC/pages/$A" \
  -d '{"contentUpdate":{"insertionMode":"replace","canvasContent":{"format":"markdown","content":"# Replaced\n\nplain paragraph"}}}' \
  | jq -r .requestId)
mutwait "$RID"

sleep 5
inventory "$A" | tee A_after.txt
diff A_before.txt A_after.txt && echo "NATIVE OBJECTS SURVIVED" || echo ">>> NATIVE OBJECTS DESTROYED <<<"
md_export "$A" A_after.md; cat A_after.md
```

**Verdict criteria:** any table/control/formula ID missing from `A_after.txt` => `replace` is destructive => ship the guard + a separate destructive tool. **Also open the page in the browser**: objects may survive in the API listing but be orphaned off-canvas — that counts as destruction too.

## B2. Does the exact read-modify-write flow destroy objects, and is it stable? (SCRATCH-B)

```bash
inventory "$B" > B_before.txt
md_export "$B" B_before.md

jq -Rs --arg m replace '{contentUpdate:{insertionMode:$m,canvasContent:{format:"markdown",content:.}}}' \
  B_before.md > B_payload.json
RID=$(api -X PUT "$API/docs/$DOC/pages/$B" --data-binary @B_payload.json | jq -r .requestId)
mutwait "$RID"

sleep 5
inventory "$B" > B_after.txt; diff B_before.txt B_after.txt
md_export "$B" B_after.md
diff -u B_before.md B_after.md   # empty => RMW is a fixed point; non-empty => unstable
```

**Verdict criteria:** this is precisely what `edit_page` would do. If it deletes the table, or the diff is non-empty, whole-page RMW is off the table.

## B3. Markdown torture write on a fresh page

````bash
cat > torture.md <<'EOF'
# H1 heading
## H2 heading
### H3 heading
#### H4 heading
##### H5 heading
###### H6 heading

Setext H1
=========

Plain paragraph with **bold**, *italic*, ***bold italic***, ~~strikethrough~~,
`inline code`, and an escaped \*asterisk\* plus an &amp; entity.

Hard break test: line one  
line two (two-space break), and line three\
after a backslash break.

Inline [link](https://example.com), reference [link][ref], autolink
<https://example.com>, and bare https://example.com

[ref]: https://example.com "Ref title"

![alt text](https://placehold.co/120x40.png "image title")

* star bullet one
* star bullet two
  * nested star level two
    * nested star level three
+ plus bullet
- dash bullet

1. ordered one
2. ordered two
   1. nested ordered
5. ordered starting at five
1. lazy numbering

- [ ] unchecked task
- [x] checked task

> blockquote level one
> > nested blockquote level two

```python
def hello(name: str) -> str:
    return f"hi {name}"  # fenced, language-tagged
```

    indented code block (four spaces)

| Column A | Column B |
| -------- | -------- |
| a1       | b1       |
| a2       | b2       |

Term
: definition list item

Footnote reference[^1].

[^1]: The footnote body.

Math inline $E = mc^2$ and block:

$$
\int_0^1 x^2 dx = \frac{1}{3}
$$

Mention test: @Someone and #Tag

<div class="raw-html"><b>raw html block</b></div>

Horizontal rules follow, each on its own separated line:

---

***

___

Final paragraph.
EOF

jq -Rs '{name:"TORTURE-MD",pageContent:{type:"canvas",canvasContent:{format:"markdown",content:.}}}' \
  torture.md > t_payload.json
RESP=$(api -X POST "$API/docs/$DOC/pages" --data-binary @t_payload.json); echo "$RESP"
export T=$(echo "$RESP" | jq -r .id)
mutwait "$(echo "$RESP" | jq -r .requestId)"     # <<< READ THE `warning` FIELD

sleep 5
md_export "$T" T_out.md
md_export "$T" T_out.html html
api "$API/docs/$DOC/pages/$T/content?limit=300" > T_content.json
jq -r '.items[]|"\(.id)\t\(.itemContent.style // "NO-ITEMCONTENT")\t\(.itemContent.lineLevel // "-")\t\((.itemContent.content // "")[0:60])"' T_content.json
````

**Compare exactly this, `torture.md` vs `T_out.md`:**

1. **h4-h6** — clamped to `###`? demoted to bold paragraph? left literal? (decides the heading policy in our tool description)
2. **Bullet markers** — did `*` and `+` become `-`? (decides whether RMW produces spurious diffs)
3. **Ordered lists** — was `5.` renumbered to `3.`? was lazy `1. 1. 1.` renumbered?
4. **Task lists** — real checkboxes (style `checkboxList` in `T_content.json`) or literal `- [ ]`?
5. **Strikethrough** — struck text, or literal `~~`?
6. **The table** — a native table (does it appear in `api $API/docs/$DOC/tables` with `parent.id == $T`?), a code-ish literal block, or flattened lines? Then: **does it come back at all in `T_out.md`?**
7. **The image** — present in `T_out.html` but absent from `T_out.md`? (predicted yes)
8. **HRs** — dividers created? do they survive export? note whether the first `---` after text became a setext H2 instead.
9. **Fenced code** — fence preserved, language tag preserved?
10. **Footnote / math / definition list / raw HTML / `@mention`** — literal, dropped, or mangled?
11. **`T_content.json`** — which `PageLineStyle` values appear; whether any item has an `id` but **no** `itemContent` (our cheap detector for native objects); whether the divider/callout/table appear at all.
12. **`MutationStatus.warning`** — did malformed constructs produce a warning, or total silence?

## B4. Is HTML a better write format? (especially tables)

```bash
# pandoc if available; otherwise hand-write a small HTML file with the same constructs
pandoc -f markdown -t html torture.md -o torture.html 2>/dev/null || echo "write torture.html by hand"

jq -Rs '{name:"TORTURE-HTML",pageContent:{type:"canvas",canvasContent:{format:"html",content:.}}}' \
  torture.html > th_payload.json
RESP=$(api -X POST "$API/docs/$DOC/pages" --data-binary @th_payload.json)
export TH=$(echo "$RESP" | jq -r .id); mutwait "$(echo "$RESP" | jq -r .requestId)"
sleep 5
md_export "$TH" TH_out.md
api "$API/docs/$DOC/tables?limit=100" | jq -r --arg p "$TH" '.items[]|select(.parent.id==$p)|.name'
diff -u T_out.md TH_out.md
```

**Verdict criteria:** does `<table>` produce a real Coda table where GFM `|` did not? Does HTML preserve h4-h6, strikethrough, or images any better? If HTML wins on tables, `edit_page` should convert to HTML on write.

## B5. Round-trip idempotence at generation 2

```bash
jq -Rs '{name:"TORTURE-GEN2",pageContent:{type:"canvas",canvasContent:{format:"markdown",content:.}}}' \
  T_out.md > g2.json
RESP=$(api -X POST "$API/docs/$DOC/pages" --data-binary @g2.json)
export G=$(echo "$RESP" | jq -r .id); mutwait "$(echo "$RESP" | jq -r .requestId)"
sleep 5
md_export "$G" G_out.md
diff -u T_out.md G_out.md && echo "STABLE FIXED POINT (gen2==gen1)" || echo ">>> NOT IDEMPOTENT: repeated edits drift <<<"
```

**Verdict criteria:** even if gen1 != input (normalization), a **stable fixed point at gen2** means anchored RMW is workable provided we normalize once. Non-idempotence means content decays with every edit — a hard blocker.

## B6. `elementId`-scoped replace — the safe editing primitive (SCRATCH-C)

```bash
api "$API/docs/$DOC/pages/$C/content?limit=200" | jq -r '.items[]|"\(.id)\t\(.itemContent.style)\t\((.itemContent.content//"")[0:50])"'
export EID='cl-XXXXXXXX'   # pick the paragraph line

inventory "$C" > C_before.txt
RID=$(api -X PUT "$API/docs/$DOC/pages/$C" \
  -d "{\"contentUpdate\":{\"insertionMode\":\"replace\",\"elementId\":\"$EID\",\"canvasContent\":{\"format\":\"markdown\",\"content\":\"REPLACED ONLY THIS LINE\"}}}" \
  | jq -r .requestId)
mutwait "$RID"; sleep 5
inventory "$C" > C_after.txt; diff C_before.txt C_after.txt && echo "SCOPED REPLACE IS NON-DESTRUCTIVE"
md_export "$C" C_after.md
```

**Verdict criteria:** only the targeted element changed, and the inventory is unchanged. Also re-list `/content` afterwards to check whether **element IDs are stable across writes** — if they churn, anchored editing must re-resolve IDs before every operation.

## B7. What each outcome means for the tool set

Each row below states what an outcome would bear on. None of them is decided
here — what the client does about any of it belongs to the `tool-surface` topic.

| Result | Status | What it bears on |
|---|---|---|
| B1 destroys the table | unrun | Whether a whole-page replace can exist at all without the tables/controls/formulas guard in front of it |
| B2 diff is non-empty | unrun | Whether whole-page read-modify-write is viable, or only `elementId`-anchored edits |
| B5 not idempotent | **confirmed 2026-09-06** | Same question, sharpened: the drift is not a one-time normalization that settles. A table gains a row per cycle, so the damage accumulates with the number of edits rather than with their size |
| B3 shows table/image loss on export | **refuted as stated, 2026-09-06** | The premise was wrong in both halves. A markdown pipe table is not lost — it becomes a real native table object. An inline image is not omitted — it degrades to a link. The real losses are narrower and stranger: the table's *header row* is demoted to data, and horizontal rules disappear entirely |
| B4 shows HTML wins | **partly confirmed 2026-09-06** | HTML wins on tables and only on tables — it alone preserves the header row. It loses the code-fence language tag, destroys task-list checkboxes, and drops images outright. Any format choice is a trade rather than a win |
| B6 IDs churn across writes | unrun | Whether an anchored write can reuse an element id it read earlier, or must re-resolve first |

**Total runtime** ~12-15 min, dominated by export polling (~5-10 s per export, 8 exports) and the one-time manual page setup.

---

# Results

> Paste actual output below once the plan is run. Record the date, the token's workspace/plan tier, and the doc used.

**Run date:** 2026-09-06 (B3, B4 and B5 only — B1, B2 and B6 remain blocked, see Status above)
**Run by:** Mike Yan
**Doc / workspace:** throwaway scratch doc, docId `6vqpBu-VYd` (from the `T_content.json` `href`); token workspace/plan tier not captured for this run

## B1 — blunt `replace` vs native objects

_Verdict:_
_Evidence:_

```
(paste A_before.txt / A_after.txt diff, mutationStatus JSON, A_after.md)
```

## B2 — read-modify-write round trip

_Verdict:_
_Evidence:_

```
(paste B_before.txt vs B_after.txt diff, and diff -u B_before.md B_after.md)
```

## B3 — markdown torture write/export

_Verdict per construct:_ recorded directly in the fidelity table above — every
row previously marked as an untested assumption is now either confirmed or
narrowed to the specific sub-case still untested.

_Evidence:_ Page `canvas--WjjZil_19` (name `TORTURE-MD`), created from
`torture.md`. Key excerpts from the diff between the write input (`torture.md`)
and the read-back export (`T_out.decompressed.md`):

```
-#### H4 heading
-##### H5 heading
-###### H6 heading
+H4 heading
+H5 heading
+H6 heading

-Setext H1
-=========
+# Setext H1

-an escaped \*asterisk\* plus an &amp; entity.
+an escaped *asterisk* plus an & entity.

-reference [link][ref], autolink
-<https://example.com>, and bare https://example.com
+reference [link](https://example.com), autolink
+[https://example.com](https://example.com), and bare [https://example.com](https://example.com)

-![alt text](https://placehold.co/120x40.png "image title")
+[alt text](https://placehold.co/120x40.png)

-* star bullet one
-* star bullet two
-+ plus bullet
+- star bullet one
+- star bullet two
+- plus bullet

-5. ordered starting at five
-1. lazy numbering
+3. ordered starting at five
+4. lazy numbering

-> blockquote level one
-> > nested blockquote level two
+> blockquote level one
+> nested blockquote level two

-    indented code block (four spaces)
+```
+indented code block (four spaces)
+```

-| Column A | Column B |
-| -------- | -------- |
+| Column 1 | Column 2 |
+| --- | --- |
+| Column A | Column B |

-Horizontal rules follow, each on its own separated line:
-
----
-
-***
-
-___
-
-Final paragraph.
+Horizontal rules follow, each on its own separated line:
+(six blank lines, no divider, no trace of --- / *** / ___)
+Final paragraph.
```

The backslash-escaped `\*asterisk\*` coming back as unescaped `*asterisk*` is
significant beyond the character diff: a further round trip through any
markdown parser would read that as italic text, not a literal asterisk.

Definition list, footnote reference/body, math (inline and block), the
`@mention`/`#Tag` line, and the raw `<div>` block all came back byte-identical
as literal text — the write did not recognize or alter them.

`T_content.json` (the cheap page-content read) confirms: the task-list lines
carry `"style":"checkboxList"` (a real native construct, not literal text); the
h4-h6 lines carry `"style":"paragraph"` (not `"h3"`, not bold); the two
blockquote lines are both `"style":"blockQuote"` with no level distinction; and
critically, **no item of any style corresponds to the table** the same write
created (`grid-D53nA4DcMR`, "Table 1") — the table is completely absent from
this listing, confirming it is invisible to the cheap read.

`MutationStatus.warning` was not captured in the artifacts for this run — no
mutation-status response was saved alongside the other B3 files — so whether
the constructs markdown does not understand (definition list, footnotes, math,
raw HTML, mentions) produced a warning or total silence remains unknown.

## B4 — HTML vs markdown write format

_Verdict:_ HTML wins on the one construct it was tested for a reason to win on
(the table's header row) and loses on several others; it is not a categorical
improvement over markdown as a write format.

_Input note:_ pandoc was not available in this environment
(`pandoc -f markdown -t html` had no binary to run), so `torture.html` was
**hand-authored** to mirror `torture.md`'s constructs one for one — it was not
produced by converting `torture.md` with pandoc. A reader comparing B3 and B4
should treat `torture.html` as an independently written approximation of the
same test cases, not a mechanical pandoc translation, and allow for that when
weighing any difference between the two runs.

_Evidence:_ Page `canvas-ceyUJcCKU8` (name `TORTURE-HTML`), created from
`torture.html`; exported to `H_out.md`. Notable differences from B3's
`T_out.decompressed.md`:

- **Table.** `<table><thead><tr><th>Column A</th>...` exports as
  `## Table 2` / `| Column A | Column B |` / `| --- | --- |` / data rows — the
  true header row is kept, unlike the markdown-written table's synthesized
  `Column 1`/`Column 2` header (B3). This is the one clear advantage found.
  Against it: a `## Table 2` heading is injected above the table that did not
  exist in the input.
- **Fenced code.** `<pre class="python">` exports as a bare ` ``` ` fence — the
  `python` language tag is lost (B3's markdown write kept it).
- **Task lists.** `<li><input type="checkbox" disabled>` / `checked` export as
  `-  unchecked task` / `-  checked task` — the checkbox state is destroyed,
  leaving bare list items with no `[ ]`/`[x]` marker at all.
- **Image.** `<img src="..." alt="alt text" title="image title" />` is
  **dropped entirely** from the export — no link, no alt text, nothing. This is
  a worse outcome than the markdown write's degrade-to-link behavior (B3).
- **h4-h6.** `<h4>`/`<h5>`/`<h6>` export as `### **H4 heading**` /
  `### **H5 heading**` / `### **H6 heading**` — an h3-level heading wrapping
  bolded text, rather than B3's plain-paragraph demotion.
- **Stray whitespace.** The export is littered with lines containing only a
  single space character — confirmed by byte inspection (`0x20 0x0a`, an
  ordinary ASCII space, not a non-breaking space) — 29 such lines in
  `H_out.md`, one apparently per HTML block-level element boundary.
- **Footnote / definition list.** The `<a href="#fn1">…</a>` /
  `<section class="footnotes">` markup is not reconstructed as `[^1]` syntax on
  export — it comes back as a plain markdown link (`[#fn1](#fn1)`). The
  `<dl><dt><dd>` definition list flattens to a single line
  (`  Term definition list item  `), losing the colon-definition form.
- **Raw HTML.** The hand-written `<div class="raw-html"><b>raw html
  block</b></div>` (here an ordinary content element, since the whole page is
  HTML) flattens to `**raw html block**` — the div is discarded but the `<b>`
  survives as markdown bold.

## B5 — round-trip idempotence (gen2)

_Verdict:_ **Not a fixed point — the most consequential result of this run.** A
second write-export cycle over gen-1's already-normalized markdown introduces
new, different changes rather than reproducing gen-1 exactly.

_Evidence:_ Page `canvas-JyBW6sOWuB` (name `TORTURE-GEN2`), created by feeding
B3's export (`T_out.decompressed.md`) back in as the write. Exported to
`G2_out.md`. The diff between gen-1 and gen-2 is confined to three places:

```
-> blockquote level one
-> nested blockquote level two
+> blockquote level one  
+nested blockquote level two
```
The flattened blockquote's continuation line loses its `>` marker entirely on
the second cycle — it is no longer quoted at all.

```
 | Column 1 | Column 2 |
 | --- | --- |
+| Column 1 | Column 2 |
 | Column A | Column B |
 | a1 | b1 |
 | a2 | b2 |
```
The synthesized header row is duplicated as a second data row. This is the
finding that compounds: each read-modify-write cycle over a page containing a
table adds another copy of the bad header — it does not stabilize after one
normalization pass, it keeps growing.

```
 Horizontal rules follow, each on its own separated line:
-
-
-
-
-
-
 Final paragraph.
```
The six blank lines gen-1 left behind where the three horizontal rules vanished
collapse to zero at gen-2 — further drift, not stabilization.

Everything else in the diff is empty: headings, lists, code fences, task-list
markers, links, and the literal-text constructs (footnote, math, mentions, raw
HTML) are unchanged between gen-1 and gen-2.

One transport-level fact surfaced while running this test: the export's
`downloadLink` serves the content with `Content-Encoding: gzip` and
`Content-Type: text/plain` — confirmed directly, since `T_out.md` and
`T_out.html` on disk are themselves gzip streams (`file` reports "gzip
compressed data"), not plain text, despite the `.md`/`.html` extension. A
client that does not decompress the download gets binary. This bit the first
run of this test: the raw gzip bytes were nearly re-posted as the gen-2 page
content before the mistake was caught.

## B6 — elementId-scoped replace

_Verdict:_
_Evidence:_

```
(paste content listing before/after, inventory diff, C_after.md)
```
