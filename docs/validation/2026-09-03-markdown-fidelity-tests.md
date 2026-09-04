# Superhuman Docs API — markdown write/export fidelity test plan

**Date:** 2026-09-03
**Target:** `https://docs.superhuman.com/apis/v1` (formerly Coda API v1; specs are byte-identical)
**Status:** NOT YET RUN — see the empty Results section at the bottom.

## Before you run this

- Requires an **API token** (from `/account`) and a **throwaway scratch doc**.
- **NEVER run this against a doc anyone cares about.** Tests B1 and B2 are *deliberately destructive*: they issue whole-page `insertionMode: "replace"` writes against pages that contain real tables, buttons and controls, specifically to find out whether those native objects get destroyed. Assume everything on SCRATCH-A / SCRATCH-B / SCRATCH-C will be lost.
- Takes roughly **15 minutes**, dominated by export polling (~5-10 s per export, ~8 exports) plus a one-time manual page setup in the browser.
- Tests are ordered so the most dangerous unknown (destructive `replace`) is settled first.

## Why this plan exists

Coda staff, in the announcement thread for these exact page-content endpoints:

> "HTML and markdown can't perfectly represent all of the features of a Coda doc, so a round trip in either format may lose some information. **These endpoints are best used for import or export scenarios, not page editing.**"
>
> — Jonathan Goldman (Coda), *More powerful page endpoints in the Coda API*, 2 Nov 2023
> https://connect.superhuman.com/t/more-powerful-page-endpoints-in-the-coda-api/44103

That is the ceiling on every honest claim our `read_page` / `edit_page` tools can make. Beyond that statement, **no one — Coda, Superhuman, or any open-source implementation — has documented per-construct markdown fidelity.** No working implementation reviewed (orellazri/coda-mcp, TJC-LP/coda-mcp-server) contains any sanitizer, fidelity note, or destructive-write warning. This plan closes that gap empirically.

---

# Findings (desk research, pre-test)

Confidence markers: **[S]** confirmed by Coda/Superhuman staff or first-party docs · **[C]** inferred from working code / first-party tool design · **[?]** speculative, undocumented anywhere — must be tested.

## Primary sources

| Source | What it establishes |
|---|---|
| [Import Markdown into Docs (help center)](https://help.coda.io/hc/en-us/articles/39555724729869-Import-Markdown-into-Coda) | "Superhuman Docs supports the **basic syntax** markdown flavor and, as such, **does not support text colors, highlights, and other extended features**." Basic syntax (markdownguide.org) **excludes** tables, task lists, strikethrough, footnotes, fenced code, autolinks. |
| [Official Docs MCP tools & endpoints](https://coda.io/resources/mcp/tools-and-endpoints) | `content_read` takes `contentTypesToInclude` = **markdown, tables, formulas, controls, comments** — markdown is a *separate channel* from tables/formulas/controls. `content_modify` has **no whole-page replace**; only `insert_element`, `replace_element_text`, `replace_text`, `delete_element`, anchored by `elementId`. `markdownIncludeAnnotations` "adds `[[elementId]]` for editing". Verbatim: **"For tabular data, prefer `table_create` over Markdown tables."** |
| [Page attachments export thread](https://connect.superhuman.com/t/coda-api-v1-how-to-retrieve-page-level-attachments-not-just-table-files-when-exporting-to-markdown-html/57065) | Eric Koleda (Coda): "While they are **omitted in the markdown export**, you can get the URLs from the HTML export." HTML export carries `<img src>` + `data-coda-blob-id`. |
| [Transform text with paragraph styles](https://help.coda.io/hc/en-us/articles/39555971852941-Transform-text-with-paragraph-styles) + [Format and style text](https://help.coda.io/hc/en-us/articles/39555789925389-Format-and-style-text) | Native canvas blocks: plain text, **H1/H2/H3 only**, bulleted/numbered/checklist/**collapsible** lists, block quotes, **pull quotes**, code blocks, **callouts**. Native inline: bold, italic, underline, strikethrough, inline code. |
| [markdown via API thread](https://connect.superhuman.com/t/markdown-via-api/46228) | Luis Curiel (Coda), Feb 2024: markdown format works for **pages**; confirmed Mar 2024 that markdown into **canvas columns in table rows** "is not possible at the moment". |
| [orellazri/coda-mcp](https://github.com/orellazri/coda-mcp) `src/helpers.ts`, `src/server.ts` | Reference TS implementation: export -> poll (5x5s) -> GET downloadLink. **Zero** sanitizing, validation, fidelity notes or warnings. Always `format:"markdown"`, never HTML. Its `coda_duplicate_page` does export-markdown -> create-page-from-markdown, i.e. it silently ships the lossy round trip as "duplicate". |
| [TJC-LP/coda-mcp-server](https://github.com/TJC-LP/coda-mcp-server) | Python prior art. Same: no fidelity documentation, no replace guard. |
| Local spec `coda-openapi.yaml` v1.6.0 | `Table`, `Control`, `Formula` **all carry `parent: PageReference`** -> a pre-write guard is implementable. `PageContentItem` has `id` (`cl-2ZUJuRhNuN`) matching the `elementId` example format, and `itemContent` is **optional** — non-line elements may surface as bare IDs. `GET /mutationStatus/{requestId}` is how you retrieve `MutationStatus.warning`. |

## Fidelity table — markdown constructs

| Markdown construct | Supported on write? | Preserved on export to markdown? | Round-trip stable? |
|---|---|---|---|
| `#`/`##`/`###` (h1-h3) | Yes — native `h1/h2/h3` **[S]** (PageLineStyle enum + help center "three heading sizes") | Yes **[C]** | Likely, but ATX-vs-setext and trailing-`#` normalization untested **[?]** |
| `####`-`######` (h4-h6) | **No native target exists** — canvas has exactly 3 levels **[S]**. Must degrade: clamp->h3, bold paragraph, or literal `####` text. Which one is **undocumented** **[?]** | n/a | **No.** Guaranteed unstable **[S]** on the cause, **[?]** on the exact output |
| `**bold**`, `*italic*` | Yes — native; first-party MCP lists "Inline formatting: bold, italic" **[S]** | Yes **[C]** | Delimiter normalization (`*` vs `_`) untested **[?]** |
| `~~strikethrough~~` | **Conflict.** Strikethrough is native in the canvas (Ctrl+Shift+K) **[S]**, but `~~` is *extended* syntax and the importer is documented basic-syntax-only **[S]**. Likely literal `~~text~~` **[?]** | If it lands as struck text, export emission unknown **[?]** | Unknown **[?]** |
| `` `inline code` `` | Basic syntax + native inline code **[S]** -> very likely yes **[C]** | Likely **[C]** | Likely **[?]** |
| `[text](url)` links | Basic syntax; staff-confirmed markdown works for pages **[S]** | Yes — export "works fine for text, links" **[S]** | Reference-style links almost certainly normalized to inline **[?]** |
| `![alt](url)` images | Probably creates an image block **[?]** — first-party MCP treats `image` as its own `blockType` needing `content_image_upload`, implying markdown image syntax is not the sanctioned path **[C]** | **NO — omitted from markdown export** (staff-confirmed for page-level attachments; HTML export keeps them) **[S]** | **No. Write-then-read loses the image.** Clearest confirmed asymmetry **[S]** |
| GFM tables (`\| a \| b \|`) | Extended syntax, not in the supported flavor **[S]**; first-party guidance is "prefer `table_create` over Markdown tables" **[S]**. Likely literal text or flattened paragraphs, **not** a Coda table **[C]** | Native Coda tables in markdown export: **undocumented by anyone** **[?]** — but `content_read` separates `markdown` from `tables`, implying markdown alone does not carry table data **[C]** | **Assume no** **[C]** |
| `---` / `***` horizontal rule | Divider is a native block (MCP `blockType: divider`) **[S]**, so `---` probably makes one **[?]**. Trap: `---` after a text line is a **setext H2** in CommonMark | Divider is **absent from PageLineStyle** -> the cheap read cannot see it **[S]**; markdown export emission unknown **[?]** | Unknown **[?]** |
| Fenced code ` ```lang ` | Code block is native with a 100+ language enum **[S]**; fences are technically extended syntax **[S]** -> conflict, likely works but language tag may drop **[?]** | Likely as a fence **[?]** | Language attribute preservation untested **[?]** |
| `> blockquote` | Yes — native `blockQuote` **[S]** | Yes **[C]** | Nested `> >` probably flattened to one level + `lineLevel` **[?]** |
| Nested lists | Native (`lineLevel` "for indentable elements") **[S]** | Yes **[C]** | Indent width (2 vs 4 spaces) and marker normalization (`*`/`+` -> `-`) untested — **likeliest silent normalization** **[?]** |
| Ordered lists | Native `numberedList` **[S]** | Yes **[C]** | Start-number (`3.`) and lazy numbering almost certainly renumbered **[?]** |
| `- [ ]` task lists | Native `checkboxList` exists **[S]**, but `- [ ]` is extended syntax **[S]** -> conflict, must test **[?]** | Unknown **[?]** | Unknown **[?]** |
| Footnotes `[^1]` | Extended syntax, **no native equivalent** -> literal text or dropped **[C]** | n/a | **No** |
| LaTeX / `$...$` math | No native math block (packs only) **[S]** by absence from the block list -> literal text **[C]** | n/a | **No** |
| `@mentions` / page refs | No markdown syntax; native mentions exist. Writing `@Name` yields literal text **[C]** | Existing mentions probably flatten to text or a link **[?]** | **No** |
| Raw HTML inside markdown | Undocumented **[?]** | — | — |
| Text color / highlight | **Explicitly unsupported** in the markdown flavor **[S]**; first-party MCP uses proprietary tags **[S]** | Lost **[S]** | **No** |
| Underline | Native inline style, **no markdown syntax at all** **[S]** | Lost **[C]** | **No** |

## Coda-native content with no markdown equivalent (export direction)

| Native object | What markdown export does |
|---|---|
| Tables / views | Undocumented. `content_read` exposes `tables` separately from `markdown` **[S]** -> infer markdown does not faithfully carry them **[C]**. Rendered / flattened / omitted is **the biggest untested unknown** **[?]** |
| Buttons, controls, formula chips | Separate `controls` / `formulas` content types **[S]**; separate `/docs/{docId}/controls` and `/formulas` endpoints **[S]** -> almost certainly flattened to a value or omitted **[C]** |
| Images / page attachments | **Omitted from markdown export** — staff-confirmed **[S]**. Present in HTML export **[S]** |
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

1. **Whole-page read-modify-write over markdown is not a supported editing model.** Coda says so directly. Their own MCP does not do it: it reads markdown *with `[[elementId]]` annotations* and edits via `replace_element_text` / `delete_element` scoped to those IDs, with atomic rollback across <=10 operations. That is the design our anchored editing should copy.
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
  behind an environment flag and additionally requiring an explicit force
  parameter.
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

| Result | Action |
|---|---|
| B1 destroys the table | `replace` without `elementId` becomes an opt-in `overwrite_page` with the tables/controls/formulas guard; `edit_page` never uses it |
| B2 diff is non-empty | Do not offer whole-page RMW at all; anchored `elementId` edits only |
| B5 not idempotent | Same, plus warn the model that repeated edits degrade the page |
| B3 shows table/image loss on export | `read_page` description must state markdown omits tables and images, and should offer an `include_tables` path via `/docs/{docId}/tables` |
| B4 shows HTML wins | Accept markdown from the model, convert to HTML before writing |
| B6 IDs churn across writes | Re-fetch `/content` immediately before each anchored write |

**Total runtime** ~12-15 min, dominated by export polling (~5-10 s per export, 8 exports) and the one-time manual page setup.

---

# Results

> Paste actual output below once the plan is run. Record the date, the token's workspace/plan tier, and the doc used.

**Run date:** _not yet run_
**Run by:**
**Doc / workspace:**

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

_Verdict per construct (fill in the fidelity table above with confirmed values):_
_Evidence:_

```
(paste mutationStatus warning, T_out.md, the T_content.json style listing)
```

## B4 — HTML vs markdown write format

_Verdict:_
_Evidence:_

```
(paste diff -u T_out.md TH_out.md, and whether a native table appeared)
```

## B5 — round-trip idempotence (gen2)

_Verdict:_
_Evidence:_

```
(paste diff -u T_out.md G_out.md)
```

## B6 — elementId-scoped replace

_Verdict:_
_Evidence:_

```
(paste content listing before/after, inventory diff, C_after.md)
```
