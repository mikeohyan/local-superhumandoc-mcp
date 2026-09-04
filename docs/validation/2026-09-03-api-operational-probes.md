# Superhuman Docs API — operational probe plan

**Date:** 2026-09-03
**Target:** `https://docs.superhuman.com/apis/v1` (formerly Coda API v1; specs are byte-identical)
**Status:** RUN on 2026-09-04. P1, P2, P3, P4, P5 (a/b/c), P6, and P9 were executed
(P3/P4 adapted to a canvas-page content write in place of a table-row write, since
the scratch doc had no table at the time — see Results). P7 RAN on 2026-09-04 once
the doc gained tables; P8 is still NOT RUN, though it is no longer blocked — the
table with a writable column it needs now exists. See the
Results section for raw output and findings, several of which contradict the
plan's or the constants file's assumptions.

## What this plan settles

Nine questions about the API's operational behaviour that cannot be answered from
the specification, the documentation, or the vendor's forum, because nobody has
written the answers down. Each is settled by running commands against a scratch
document with a real token.

The findings these probes calibrate are recorded in
`docs/reference/api-operational-constants.md`. Several constants there are marked
*[CHOSEN — no evidence, tune later]*; this plan is how they stop being guesses.

| Probe | Question | Destructive? | Unattended? |
|---|---|---|---|
| P1 | Do authenticated responses carry any rate-limit headers? | No | No |
| P2 | Does `X-Coda-Doc-Version` accept values other than `latest`? | No | No |
| P3 | Does the staleness 400 ever fire, and what does it say? | **Yes — writes a row** | No |
| P4 | How long does `getMutationStatus` 404 after a write? | No (reuses P3's write) | No |
| P5 | Export: 404 window, status string, download-link lifetime | **Yes — starts exports** | Partly |
| P6 | Which rate-limit bucket does the export POST use, and does a real 429 carry `Retry-After`? | **Yes — starts 6 exports** | No |
| P7 | What is the real wire-bytes-to-internal-bytes inflation for a row? | **Yes — writes rows** | No |
| P8 | Do sync-token deltas report deletions? | **Yes — deletes a row** | No |
| P9 | Does the synchronous page-content read cover our needs? | No | No |

**Total attention required: roughly 8 minutes.** One probe (P5b, the download-link
lifetime watch) runs for ~4 minutes in a background terminal and needs no attention
while it does.

## Before you run this

- Requires an **API token** (from `/account`) and a **throwaway scratch doc**.
- **Never run this against a doc anyone cares about.** P3, P5, P6, P7 and P8 all
  write to or delete from the target table.
- `jq` and `python3` must be on `PATH`.
- **Rate-limit budget.** Only P6 deliberately exhausts a bucket, and it is bounded
  at six requests — enough to answer the question, small enough not to be abusive.
  Everything else is a handful of requests well inside normal usage. **Do not
  extend any loop in this plan** to "get a cleaner signal"; the buckets are shared
  per user/IP and hammering them affects other clients on the same account.
- If P6 produces 429s, **wait 60 seconds before running P7**, which also writes.

## Setup

```bash
export CODA_TOKEN="<paste API token from /account>"
export BASE="https://docs.superhuman.com/apis/v1"
export H="Authorization: Bearer $CODA_TOKEN"

export DOC="<docId, e.g. AbCDeFGH>"            # a SCRATCH doc you own
export PAGE="<pageIdOrName, e.g. canvas-tuVwxYz>"   # must be a canvas page
export TABLE="<tableIdOrName, e.g. grid-pqRst-U>"
export COL="<a writable text columnId or name in $TABLE>"
```

Confirm the setup is live before going further:

```bash
curl -s -H "$H" "$BASE/whoami" | jq '{name, loginId, workspace: .workspace.name}'
curl -s -H "$H" "$BASE/docs/$DOC/tables/$TABLE" | jq '{id, name, rowCount}'
```

Both must return data. If either 401s, the token is wrong or restricted; if either
404s, the ID is wrong.

---

## P1 — Do authenticated responses carry rate-limit headers?

**Question.** The spec declares no response headers anywhere, and unauthenticated
`401`s carry none. Does a *successful authenticated* response expose
`Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, or anything similar?

**Cost.** 1 request. Non-destructive. ~5 seconds.

```bash
curl -s -D - -o /dev/null -H "$H" "$BASE/whoami"
```

**What the outcomes mean.**

- **No `retry-after` / `x-ratelimit-*` in the output** → confirms the client has no
  server-side feedback channel and must self-throttle. This is the expected result.
- **Any such header present** → a significant find. Record the exact names and
  values; the client should prefer them over its own limiter, and
  `RETRY_AFTER_TRUSTED` in the constants file flips to `True`.

Also note the `x-coda-pod` value. Running this twice usually yields two different
pods, which is the replication lag that P4 and P5 measure.

---

## P2 — Does `X-Coda-Doc-Version` accept values other than `latest`?

**Question.** Only `latest` is documented. Is any other value rejected, or silently
ignored? A rejection would also give a second, distinguishable 400 shape.

**Cost.** 3 requests, read bucket. Non-destructive. ~20 seconds.

```bash
# 2a. Quiet doc, header present -> expect 200
curl -s -o /dev/null -w "quiet+header:  %{http_code}\n" \
  -H "$H" -H "X-Coda-Doc-Version: latest" "$BASE/docs/$DOC/tables"

# 2b. Bogus value -> validated, or ignored?
curl -s -w "\nbogus-value:   %{http_code}\n" \
  -H "$H" -H "X-Coda-Doc-Version: 12345" "$BASE/docs/$DOC/tables"

# 2c. Empty value
curl -s -o /dev/null -w "empty-value:   %{http_code}\n" \
  -H "$H" -H "X-Coda-Doc-Version: " "$BASE/docs/$DOC/tables"
```

**What the outcomes mean.**

- **All 200** → the header is parsed leniently and only `latest` is meaningful.
  Send `latest` or nothing.
- **2b/2c return 400** → values are validated. Record the message text: it is a
  malformed-request 400 on a docs endpoint, which is exactly the class P3 needs to
  distinguish from a staleness 400.

---

## P3 — Does the staleness 400 ever fire, and what does it say?

**⚠️ DESTRUCTIVE — inserts a row into `$TABLE`.**

**Question.** Two things at once. First, does `X-Coda-Doc-Version: latest` ever
actually return 400? One user reported it always returning 200 even after large row
deletions, and no staff member answered. Second, if it does fire, what is the exact
`message`? No one has ever posted it, and there is no machine-readable error code —
a staleness 400 and a malformed-request 400 are byte-identical in shape on every
docs endpoint.

**Cost.** 1 doc-content write + up to 10 reads. ~60 seconds.

```bash
# Fire a write, then immediately read with the header, repeatedly.
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"rows":[{"cells":[{"column":"'"$COL"'","value":"probe-'"$(date +%s)"'"}]}]}' \
  "$BASE/docs/$DOC/tables/$TABLE/rows" | tee /tmp/mut.json | jq .

for i in $(seq 1 10); do
  code=$(curl -s -o /tmp/dv.json -w "%{http_code}" \
    -H "$H" -H "X-Coda-Doc-Version: latest" \
    "$BASE/docs/$DOC/tables/$TABLE/rows?limit=1")
  echo "attempt $i -> $code"
  [ "$code" = "400" ] && { echo "=== STALE-400 BODY ==="; cat /tmp/dv.json; break; }
  sleep 2
done
```

**Control — verify the shape-free discriminator.** The client's planned way to tell
the two 400s apart is to re-issue the identical request *without* the header: if it
then succeeds the 400 was staleness, and if it 400s again the request was malformed.
This confirms the negative case. The spec states that `sortBy=natural` with
`visibleOnly=false` is an unsatisfiable combination and must 400.

```bash
echo "--- malformed, WITH header ---"
curl -s -H "$H" -H "X-Coda-Doc-Version: latest" \
  "$BASE/docs/$DOC/tables/$TABLE/rows?sortBy=natural&visibleOnly=false" | jq .
echo "--- malformed, WITHOUT header ---"
curl -s -H "$H" \
  "$BASE/docs/$DOC/tables/$TABLE/rows?sortBy=natural&visibleOnly=false" | jq .
```

**What the outcomes mean.**

- **All ten attempts return 200** → the header is effectively inert on this account
  and workload. Drop the `require_fresh` option from the tool surface entirely
  rather than shipping a knob that does nothing.
- **A 400 appears** → record the `message` verbatim. It validates (but must never
  become a *dependency* of) the re-probe discriminator.
- **Both control requests 400** → the discriminator's negative case holds, which is
  what makes it safe to rely on.
- **The control's with-header and without-header responses differ** → investigate;
  the discriminator's assumption is broken.

Keep `/tmp/mut.json` — P4 uses its `requestId`.

---

## P4 — How long does `getMutationStatus` 404 after a write?

**Question.** Staff acknowledge that mutation IDs are not immediately replicated
across backends, so the status endpoint 404s if called too soon, and prescribe "a
short sleep, maybe a few seconds". How long is the window actually? This calibrates
`MUTATION_404_GRACE_S` (currently a guess of 15 s).

**Cost.** 12 reads. Non-destructive (reuses P3's write). ~30 seconds.

Note the endpoint is at the **root**, not under `/docs/{docId}/`.

```bash
REQ=$(jq -r .requestId /tmp/mut.json)
echo "requestId=$REQ"
for i in $(seq 1 12); do
  printf "t=%2ss -> " $((i*2))
  curl -s -o /tmp/ms.json -w "%{http_code} " -H "$H" "$BASE/mutationStatus/$REQ"
  jq -c '{completed, warning}' /tmp/ms.json 2>/dev/null || echo
  sleep 2
done
```

**What the outcomes mean.**

- **404s for the first N seconds, then 200** → set `MUTATION_404_GRACE_S` to
  roughly 2× the observed N.
- **200 immediately** → the race did not reproduce on this doc. Keep a conservative
  grace window anyway; it is size- and load-dependent, and staff describe it as a
  known issue rather than a fixed one.
- **`completed: false` persisting past the loop** → normal. The write is queued;
  staff describe end-to-end delays of "30 seconds to a few minutes" on larger docs.
  It confirms the deadline must return "queued, not confirmed" rather than an error.

---

## P5 — Export: 404 window, status string, and download-link lifetime

**⚠️ DESTRUCTIVE in the sense that it starts export jobs** (it does not modify the
doc, but it consumes whatever bucket P6 identifies).

**Question.** Three things: how long the export status endpoint 404s before the
request ID replicates; whether the wire value is `complete` or `completed` (the spec
contradicts itself — the enum says `complete`, its own three code samples print
`completed`, and the enum is dangling so neither is enforced); and how long
`downloadLink` stays valid. Staff say "only a few minutes"; the sibling Admin API
endpoint publishes exactly 5 minutes.

**Cost.** 1 export POST + ~15 status reads, then a background watch. ~5 minutes
wall-clock, ~1 minute of attention.

### P5a — replication window and status value

```bash
RID=$(curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"outputFormat":"markdown"}' \
  "$BASE/docs/$DOC/pages/$PAGE/export" | tee /tmp/beg.json | jq -r .id)
echo "requestId=$RID"; jq . /tmp/beg.json

for i in $(seq 1 15); do
  printf "t=%2ss -> " $((i*2))
  curl -s -o /tmp/ex.json -w "%{http_code} " -H "$H" \
    "$BASE/docs/$DOC/pages/$PAGE/export/$RID"
  jq -r '"status=\(.status // "-") link=\(if .downloadLink then "yes" else "no" end) err=\(.error // "-")"' \
    /tmp/ex.json 2>/dev/null || echo "(non-JSON)"
  sleep 2
done
```

**What the outcomes mean.**

- **404s for the first N seconds** → calibrates `EXPORT_404_GRACE_S` (currently a
  guess of 20 s). Set it to roughly 2× N. This is the failure `orellazri/coda-mcp`
  treats as fatal.
- **The `status` value when `downloadLink` first appears** → settles `complete` vs
  `completed` for this account. Record it verbatim. Note the client is designed to
  gate on `downloadLink` presence regardless, precisely because the spec leaves this
  field unconstrained.
- **`status` on the initial POST response** (`/tmp/beg.json`) → the spec's example
  claims `complete` for a request that has just started. Confirm what it really is.

### P5b — download-link lifetime *(runs unattended)*

Start this in a **second terminal** and leave it. It needs no attention.

```bash
LINK=$(jq -r .downloadLink /tmp/ex.json); echo "$LINK"
for i in $(seq 1 12); do
  printf "t=%3ss -> " $((i*30))
  curl -s -o /tmp/dl.bin -w "http=%{http_code} bytes=%{size_download} " "$LINK"
  head -c 60 /tmp/dl.bin | tr -d '\n'; echo
  sleep 30
done
```

**What the outcomes mean.**

- **Content for ~5 minutes, then failure** → confirms `EXPORT_LINK_TTL_S = 300`.
- **The body flips to `<?xml … NoSuchKey …` while the HTTP status still looks
  benign** → this is the critical failure mode. It confirms the client must inspect
  the body, not just the status code, before returning content to the model.
- **Still serving content past 10 minutes** → the link outlives staff's "a few
  minutes". Record it, but keep the never-cache rule: the cost of re-polling is one
  cheap read, and the cost of a stale link is returning an XML error as page content.

### P5c — subpages and the canvas precondition

```bash
curl -s -H "$H" "$BASE/docs/$DOC/pages?limit=50" \
  | jq -r '.items[] | "\(.id)\t\(.contentType)\t\(.name)\tparent=\(.parent.id // "-")"'
```

**What the outcomes mean.** Diff the exported markdown from P5a against the subpage
names listed here. **Expected: no subpage content appears** — the export request
schema has exactly one property (`outputFormat`) and no include-children flag. Any
non-`canvas` `contentType` is a page that will 400 on export; `syncPage` is
staff-confirmed to do so.

---

## P6 — Export's rate-limit bucket, and whether a real 429 carries `Retry-After`

**⚠️ DESTRUCTIVE in that it starts six export jobs, and it deliberately consumes a
rate-limit bucket.**

**Question.** Which bucket does the export POST fall into? It is a POST under a
page-content path returning 202, which suggests the strictest doc-content-write
bucket (3 or 5 per 10 s), but an export mutates nothing, which argues against.
Nobody has documented it. And this is the only safe way to observe a real 429 and
answer the question P1 cannot: **does a genuine 429 carry `Retry-After` or any
`X-RateLimit-*` header?**

**Cost.** 6 POSTs in a burst. ~30 seconds. This is the one probe that intentionally
spends budget.

```bash
for i in $(seq 1 6); do
  printf "export POST %s -> " $i
  curl -s -o /tmp/e.json -D /tmp/e.hdr -w "%{http_code}\n" \
    -X POST -H "$H" -H "Content-Type: application/json" \
    -d '{"outputFormat":"markdown"}' \
    "$BASE/docs/$DOC/pages/$PAGE/export"
done
echo "=== headers of last response ==="; cat /tmp/e.hdr
echo "=== body of last response ===";    cat /tmp/e.json
echo "=== any rate-limit headers? ===";  grep -i "ratelimit\|retry-after" /tmp/e.hdr || echo "NONE"
```

**Do not extend this loop.** Six requests answers the question. More is abuse.

**What the outcomes mean.**

- **429s begin around request 4–6** → the export POST is in the doc-content-write
  bucket. Keep `EXPORT_BUCKET = BUCKET_DOC_CONTENT_WRITE`, and the count at which
  they start tells you whether the live limit is 3/10 s or 5/10 s — settling the
  contradiction between the developer docs and the help centre.
- **All six succeed** → the export POST is in the general-write or read bucket.
  `EXPORT_BUCKET` can be relaxed, which materially improves multi-page export
  throughput.
- **`Retry-After` or `X-RateLimit-*` present in `/tmp/e.hdr`** → the most valuable
  single result in this plan. Record exact names, values and format; the client
  should honour them and `RETRY_AFTER_TRUSTED` flips to `True`.
- **No such headers, body is
  `{"statusCode":429,"statusMessage":"Too Many Requests","message":"Too Many Requests"}`**
  → confirms the desk research. The client must self-throttle blind.

**If you saw 429s, wait 60 seconds before P7.**

---

## P7 — Row-size inflation factor

**⚠️ DESTRUCTIVE — inserts up to four rows, some deliberately oversized.**

**Question.** The published per-row ceiling is 85 KB, but it is measured in Coda's
internal representation, not wire bytes. The only public data point is a request with
`Content-Length: 44 KB` rejected as "87 KB" — an inflation ratio near 2.0, from a
single 2023 report. What is it really, for our content shapes? This calibrates
`ROW_INFLATION_FACTOR` (currently a guess of 2.2) and therefore
`MAX_ROW_JSON_BYTES`.

**Cost.** 4 doc-content writes, spaced. ~60 seconds.

```bash
for KB in 30 40 50 60; do
  PAYLOAD=$(python3 -c "print('x'*($KB*1024))")
  printf "%2sKB wire -> " $KB
  curl -s -X POST -H "$H" -H "Content-Type: application/json" \
    -d "{\"rows\":[{\"cells\":[{\"column\":\"$COL\",\"value\":\"$PAYLOAD\"}]}]}" \
    "$BASE/docs/$DOC/tables/$TABLE/rows" \
    | jq -r '.message // "OK (accepted)"'
  sleep 4   # stay inside the doc-content-write bucket
done
```

**What the outcomes mean.**

- **The KB value at which the error first appears**, together with the "size N KB"
  figure in the message, gives the real ratio: `N / KB`. Set
  `ROW_INFLATION_FACTOR` to that ratio plus margin, and
  `MAX_ROW_JSON_BYTES = 85000 / factor`.
- **All four accepted** → plain ASCII inflates far less than 2×. **Repeat with rich
  markdown** (headings, links, bold, nested lists) before relaxing the cap — the
  community explanation attributes the inflation to formatted text being stored as
  JSON structures, so ASCII is the best case and not the one to size for.
- **429 instead of 400** → the `sleep 4` was not enough; increase it and rerun.

---

## P8 — Do sync-token deltas report deletions?

**⚠️ DESTRUCTIVE — requires deleting a row.**

**Question.** `syncToken` is the least-exercised surface in the API: zero forum
posts, zero staff statements, zero public consumers, and description text unchanged
since 2022. The `Row` schema has no tombstone field and is
`additionalProperties: false`, so deletions appear structurally impossible to
express. No RFC decides whether sync tokens ship, and the tool surface as decided
contains no sync-token tool. **Run this only if one is proposed.**

**Cost.** 3 reads + 1 delete + a 60 s wait. ~2 minutes.

```bash
# 1. Mint a sync token.
TOK=$(curl -s -H "$H" "$BASE/docs/$DOC/tables/$TABLE/rows?limit=5" \
  | tee /tmp/s0.json | jq -r .nextSyncToken)
echo "syncToken=${TOK:0:24}..."

# 2. Immediate replay against a quiet table -> how many rows come back?
curl -s -H "$H" "$BASE/docs/$DOC/tables/$TABLE/rows?syncToken=$TOK" \
  | jq '{count:(.items|length), hasNextSync:(.nextSyncToken!=null)}'

# 3. Delete a row (use one of the probe rows written by P3 or P7).
ROWID=$(jq -r '.items[0].id' /tmp/s0.json)
curl -s -X DELETE -H "$H" "$BASE/docs/$DOC/tables/$TABLE/rows/$ROWID" | jq .
echo "deleted $ROWID; waiting 60s for the snapshot to catch up"; sleep 60

# 4. Does the delta mention it?
curl -s -H "$H" "$BASE/docs/$DOC/tables/$TABLE/rows?syncToken=$TOK" \
  | jq '{count:(.items|length), ids:[.items[].id]}'

# 5. Is an invalid token distinguishable from any other 400?
curl -s -H "$H" "$BASE/docs/$DOC/tables/$TABLE/rows?syncToken=NOT_A_TOKEN" | jq .
```

**What the outcomes mean.**

- **Step 4 does not mention the deleted row** → confirms the structural reading.
  A delta cannot be used as a mirror; deletions need an out-of-band reconciling full
  read. This is the expected result and it upholds the do-not-ship recommendation.
- **Step 4 somehow represents the deletion** → a genuine discovery. Record the exact
  JSON shape; it contradicts the `Row` schema and changes the recommendation.
- **Step 5 returns a distinctive message** → stale tokens are detectable, removing
  one of the four objections. Record it verbatim.
- **Step 5 returns a bare
  `{"statusCode":400,"statusMessage":"Bad Request","message":"Bad Request"}`** →
  token invalidation is undiagnosable, and any non-2xx on a token'd request must
  trigger a full resync.

---

## P9 — Is the synchronous page-content read sufficient?

**Question.** `GET /docs/{docId}/pages/{pageIdOrName}/content` (`listPageContent`)
returns page content **synchronously** — a plain GET on the read bucket, with no
202, no polling, no download link, and none of the export failure modes. Its
`contentFormat` has exactly one legal value, `plainText`, and its `limit` maxes at
500. If plain text is adequate for common reads, it removes the dependency on the
export machinery for those paths entirely.

**Cost.** 1–2 reads. Non-destructive. ~30 seconds.

```bash
curl -s -H "$H" "$BASE/docs/$DOC/pages/$PAGE/content?limit=500" \
  | jq '{n:(.items|length), hasNext:(.nextPageToken!=null), sample:(.items[0])}'

# Full text, for comparison against the markdown export from P5a:
curl -s -H "$H" "$BASE/docs/$DOC/pages/$PAGE/content?limit=500" \
  | jq -r '.items[] | "\(.style // "-")\t\(.lineLevel // 0)\t\(.itemContent // "")"' \
  | head -40
```

**What the outcomes mean.**

- **Element `id`s are present and stable, `style` and `lineLevel` are populated** →
  the structural information needed for targeted edits is available without an
  export. Route a `format: "plaintext"` read here.
- **`itemContent` is absent on some items** → non-line elements (tables, controls)
  surface as bare IDs. Note which; it bounds what a plain-text read can honestly
  claim to have returned.
- **Compare the text against P5a's markdown export** → quantifies what plain text
  loses. If the gap is only inline formatting, plaintext is the right default for
  previews and search, with markdown reserved for editing flows.

---

# Results

*Fill in as each probe is run. Record raw output, not summaries — a later session
will want the exact bytes. Note the date and the doc used, since several behaviours
are doc-size dependent.*

**Run date:** 2026-09-04 (the plan above is dated 2026-09-03; execution was the next day)
**Doc used:** `6vqpBu-VYd` ("MCP Validator"), one page `canvas-4LiD-eeMTK` (`contentType: canvas`, "Untitled page"), **zero tables** (`GET /docs/6vqpBu-VYd/tables` → `{"items":[]}`, confirmed live before running anything). The page started empty; P3/P4/P5/P6 wrote probe content to it, so it ends this run non-empty by design.
**Token owner / workspace:** Michael Yan, workspace "Prosperzero" (from `GET /whoami`).

**Adaptation note (applies to P3, P4, P7, P8):** the plan's Setup section assumes a `$TABLE`/`$COL` pair. None exists in this scratch doc — confirmed above. P7 was genuinely NOT RUN at that time and has since been run against a real table (see its section); P8 remains NOT RUN. P3 and P4 need *some* doc-content write to test staleness/mutation-status against, and the task scope named them as runnable with "only a canvas page," so they were adapted to use the one write operation a canvas page supports: `PUT /docs/{docId}/pages/{pageId}` with `contentUpdate: {insertionMode: "append", canvasContent: {format: "markdown", content: "..."}}` (`PageUpdate`/`PageContentUpdate` schemas, confirmed against a fresh fetch of `https://coda.io/apis/v1/openapi.yaml` this session). This is a doc-content-mutating request that returns a `requestId` via `DocumentMutateResponse`, exactly like a row write would, so `getMutationStatus` polling in P4 still applies unmodified. Every place below that deviates from the plan's literal commands is called out inline.

## P1 — Authenticated rate-limit headers

Ran as written: two back-to-back `GET /whoami` with full response headers.

```
$ curl -s -D - -o /dev/null -H "Authorization: Bearer <token>" "$BASE/whoami"
HTTP/2 200
content-type: application/json; charset=utf-8
content-length: 582
date: Fri, 04 Sep 2026 00:57:04 GMT
x-coda-pod: api-d76f7b4cc-rhqsv
vary: Origin, Accept-Encoding
surrogate-control: no-store
cache-control: no-store, no-cache, must-revalidate, proxy-revalidate
expires: 0
etag: W/"246-GktliZD5wAvw1ZpwhwE9zIZAeOc"
x-coda-server: api
x-cache: Miss from cloudfront
via: 1.1 e1398ce0772469b7a60133c0332b9d06.cloudfront.net (CloudFront)
x-amz-cf-pop: YTO53-P1
alt-svc: h3=":443"; ma=86400
x-amz-cf-id: zoDgb1UMoLesiHczTraUWEWQN56R4cTu38sUP-a1ihAt-ix1kxN6hQ==
strict-transport-security: max-age=63072000; includeSubDomains; preload

$ curl -s -D - -o /dev/null -H "Authorization: Bearer <token>" "$BASE/whoami"
HTTP/2 200
...
x-coda-pod: api-d76f7b4cc-t4dtb
...
```

**Result: no `Retry-After` or `X-RateLimit-*` header on a successful authenticated response.** Confirms the expected outcome — the client has no server-side feedback channel on 2xx responses and must self-throttle. `x-coda-pod` differed between the two consecutive requests (`rhqsv` vs `t4dtb`), confirming no request affinity across the pod fleet, consistent with the replication-lag mechanism P4/P5 measure.

## P2 — `X-Coda-Doc-Version` value handling

Ran 2a/2b/2c as written, then added confirmation re-runs (same class of request, no bucket abuse) because the result was unexpected and worth reproducing before trusting it.

```
$ curl -s -o /dev/null -w "quiet+header:  %{http_code}\n" -H "$H" -H "X-Coda-Doc-Version: latest" "$BASE/docs/$DOC/tables"
quiet+header:  200

$ curl -s -w "\nbogus-value:   %{http_code}\n" -H "$H" -H "X-Coda-Doc-Version: 12345" "$BASE/docs/$DOC/tables"
{"statusCode":400,"statusMessage":"Bad Request","message":"Doc is not yet up to date."}
bogus-value:   400

$ curl -s -o /dev/null -w "empty-value:   %{http_code}\n" -H "$H" -H "X-Coda-Doc-Version: " "$BASE/docs/$DOC/tables"
empty-value:   200
```

Reproduced the bogus-value case three more times across ~2 minutes, on two different endpoints, before and after P3's write:

```
header=latest  (tables, before write)  -> 200
header=12345   (tables, before write)  -> 400 {"statusCode":400,"statusMessage":"Bad Request","message":"Doc is not yet up to date."}
header=<none>  (tables, before write)  -> 200
header=12345   (page GET, after write) -> 400 {"statusCode":400,"statusMessage":"Bad Request","message":"Doc is not yet up to date."}
header=latest  (tables, after write)   -> 200
header=12345   (tables, after write)   -> 400 {"statusCode":400,"statusMessage":"Bad Request","message":"Doc is not yet up to date."}
```

**Result — deviates from every outcome the plan anticipated.** The header is not parsed leniently (2b/2c would then all be 200) and it is not schema-validated as a malformed request either (that shape is different — see P3 below). Instead: **any value other than the literal string `latest` (empty and omitted both count as "no header," and pass) deterministically produces a 400 with `message: "Doc is not yet up to date."`, regardless of whether a real pending mutation exists.** We reproduced this before any write had ever been made in the session, i.e. with no plausible staleness condition. This strongly suggests the header is checked for exact equality against `"latest"` and anything else takes the "not current" branch unconditionally, rather than being validated as an opaque token or ignored. **Consequence for P3's discriminator:** the message text `"Doc is not yet up to date."` cannot be trusted as evidence of genuine staleness — it is also what an arbitrary invalid value produces. See P3.

## P3 — Staleness 400: fires? message text? control case?

**Write (adapted — no table exists; see Adaptation note above):**

```
$ curl -s -X PUT -H "$H" -H "Content-Type: application/json" \
  -d '{"contentUpdate":{"insertionMode":"append","canvasContent":{"format":"markdown","content":"probe-1757033824"}}}' \
  "$BASE/docs/$DOC/pages/$PAGE"
202
{"id":"canvas-4LiD-eeMTK","requestId":"mutate:d2149ec0-e6b1-4ffb-afc4-e118484259ed"}
```

**Staleness read loop** (adapted target: `GET /docs/{docId}/pages/{pageId}` with `X-Coda-Doc-Version: latest`, since there is no rows endpoint to poll; 10 attempts, 1s apart, immediately after the write above):

```
attempt 1 -> 200
attempt 2 -> 200
attempt 3 -> 200
attempt 4 -> 200
attempt 5 -> 200
attempt 6 -> 200
attempt 7 -> 200
attempt 8 -> 200
attempt 9 -> 200
attempt 10 -> 200
```

All ten returned 200. **No staleness 400 fired as a consequence of our own write, on this scratch doc, within the ~10 s window tested.** This matches the plan's "all ten attempts return 200 → the header is effectively inert on this account and workload" outcome — with the caveat from P2 that we cannot conclude the header is inert in general, only that it never fired due to an actual pending mutation in this session.

**Control case — NOT RUN as specified.** The plan's control (`sortBy=natural&visibleOnly=false` against `$TABLE/rows`) requires a table; none exists. **Blocked part: the specific documented-unsatisfiable-combination request, which only exists on the rows/listRows endpoint.**

**Adapted control performed instead**, using a genuinely invalid enum value against a real docs-domain endpoint (`listPageContent`'s `contentFormat`, whose spec declares exactly one legal value, `plainText`):

```
$ curl -s -H "$H" -H "X-Coda-Doc-Version: latest" "$BASE/docs/$DOC/pages/$PAGE/content?contentFormat=bogusFormat"
{"statusCode":400,"statusMessage":"Bad Request","message":"Bad Request","codaType":"RequestSchemaValidationFailed","codaDetail":{"issues":[{"code":"invalid_union","errors":[[{"code":"invalid_value","values":["plainText"],"path":["contentFormat"],"message":"Invalid input: expected \"plainText\""}],[{"expected":"string","code":"invalid_type","path":["pageToken"],"message":"Invalid input: expected string, received undefined"},{"code":"unrecognized_keys","keys":["contentFormat"],"path":[],"message":"Unrecognized key: \"contentFormat\""}]],"path":[],"message":"Invalid input"}]}}
code=400

$ curl -s -H "$H" "$BASE/docs/$DOC/pages/$PAGE/content?contentFormat=bogusFormat"
(byte-identical body to the above)
code=400
```

**Result: the two 400 shapes ARE distinguishable, contrary to the constants file's §2.1 claim that they are "byte-identical in shape on every docs endpoint."** A real schema-validation 400 on `listPageContent` carries `codaType: "RequestSchemaValidationFailed"` and `codaDetail.issues`; the header-triggered 400 from P2 (`"message":"Doc is not yet up to date."`) carries neither. With-header and without-header requests produced byte-identical malformed-request bodies, confirming request validation runs independent of the freshness header (the negative control holds). **This also refutes the constants file's claim that no docs/rows/pages/tables/columns operation uses the `BadRequestWithValidationErrors` shape** — `listPageContent` demonstrably does, live, 2026-09-04.

**Net verdict for P3:** the genuine staleness 400 was never observed as a consequence of an actual pending mutation. The 400 that *is* reliably produced by the header comes from any non-`latest` value, and its message ("Doc is not yet up to date.") should not be assumed to be the real staleness message without testing on a larger/busier doc where a genuine pending-mutation condition can be created.

## P4 — `getMutationStatus` 404 window

**First attempt was contaminated:** P4 originally reused P3's write, but the P2/P3 investigation above consumed roughly 90+ seconds before the first `mutationStatus` poll, so every poll (t=2s..12s of *that* loop, really ~92-102s post-write) returned `{"completed":true,"warning":null}` immediately — this does not measure the replication window and is recorded only for completeness:

```
requestId=mutate:d2149ec0-e6b1-4ffb-afc4-e118484259ed
t= 2s -> 200 {"completed":true,"warning":null}   (× 6, all identical)
```

**Re-ran cleanly** with a fresh write and an immediate (t=0) first poll:

```
$ curl -s -X PUT ... (fresh append)
202 {"id":"canvas-4LiD-eeMTK","requestId":"mutate:05cbce66-bb2d-4f0d-8efa-ec469672bcc3"}

$ curl -s "$BASE/mutationStatus/mutate:05cbce66-..."   # t=0, immediately after the 202
200 {"completed":false}

t= 2s -> 200 {"completed":false,"warning":null}
t= 4s -> 200 {"completed":false,"warning":null}
t= 6s -> 200 {"completed":false,"warning":null}
t= 8s -> 200 {"completed":false,"warning":null}
t=10s -> 200 {"completed":false,"warning":null}
t=12s -> 200 {"completed":false,"warning":null}
t=14s -> 200 {"completed":false,"warning":null}
t=16s -> 200 {"completed":false,"warning":null}
t=18s -> 200 {"completed":true,"warning":null}
t=20s -> 200 {"completed":true,"warning":null}
t=22s -> 200 {"completed":true,"warning":null}
t=24s -> 200 {"completed":true,"warning":null}
```

**Result: no 404 was observed in either run, at any point, including t=0 immediately after the write.** The endpoint consistently returned 200 with `completed:false` until the mutation actually landed. Real completion time on this near-empty scratch doc was between 16 s and 18 s after the write — **slower than staff's "maybe a few seconds" framing for the 404 race (which didn't reproduce at all) but well inside `MUTATION_DEADLINE_S` (60 s).** This is a genuinely different failure mode than what the plan anticipated: the risk isn't a spurious 404 immediately after writing, it's that `completed` legitimately stays `false` for ~18 s even on a trivial doc.

## P5a — Export replication window and status value

Ran as written.

```
$ curl -s -X POST -H "$H" -H "Content-Type: application/json" -d '{"outputFormat":"markdown"}' "$BASE/docs/$DOC/pages/$PAGE/export"
202
{"id":"96672a79-d8d3-49a9-93f2-d84992610460","status":"inProgress","href":"https://docs.superhuman.com/apis/v1/docs/6vqpBu-VYd/pages/canvas-4LiD-eeMTK/export/96672a79-d8d3-49a9-93f2-d84992610460"}

t= 2s -> 200 status=complete link=yes err=-
t= 4s -> 200 status=complete link=yes err=-
t= 6s -> 200 status=complete link=yes err=-
t= 8s -> 200 status=complete link=yes err=-
t=10s -> 200 status=complete link=yes err=-
t=12s -> 200 status=complete link=yes err=-
t=14s -> 200 status=complete link=yes err=-
t=16s -> 200 status=complete link=yes err=-
```

**Results:**
- **Begin-response `status` was `"inProgress"`, not `"complete"`** — confirms the constants file's skepticism that the spec's own `example: complete` on the begin response is wrong.
- **No 404 at any point**, including the very first poll at t=2s — the export was already `complete` with a `downloadLink` by then. `EXPORT_INITIAL_SLEEP_S = 2.0` was sufficient in this case; we cannot say whether it would be on a larger doc.
- **Completed `status` value was `"complete"`**, matching the enum and staff prose, not `"completed"` as the spec's own contradictory code samples print. Confirms existing guidance to accept `complete` and treat `status` as advisory only.

## P5b — `downloadLink` lifetime

Started the unattended 12×30s watch immediately after P5a produced a `downloadLink`, running in the background while P5c/P6/P9 were executed. **Independent corroboration found immediately, without waiting:** the signed S3 URL itself carries `X-Amz-Date=20260904T010143Z` and `X-Amz-Expires=300` as literal query parameters — i.e. the server itself asserts a 300-second validity window at mint time, which corroborates `EXPORT_LINK_TTL_S = 300` [STAFF] independently of staff prose.

_(Background watch result appended below once the task completes — see note at end of this section.)_

**Watch result (background task completed):**

```
t= 30s -> http=200 bytes=57  (gzip content, decompresses to the 3 probe lines)
t= 60s -> http=200 bytes=57
t= 90s -> http=200 bytes=57
t=120s -> http=200 bytes=57
t=150s -> http=200 bytes=57
t=180s -> http=200 bytes=57
t=210s -> http=200 bytes=57
t=240s -> http=200 bytes=57
t=270s -> http=200 bytes=57
t=300s -> http=200 bytes=57
t=330s -> http=403 bytes=367 <?xml version="1.0" encoding="UTF-8"?><Error><Code>AccessDenied</Code><Message>...
t=360s -> http=403 bytes=387 <?xml version="1.0" encoding="UTF-8"?><Error><Code>AccessDenied</Code><Message>...
```

**Result: still valid at t=300s, expired by t=330s.** This lands squarely on the `X-Amz-Expires=300` value asserted by the URL itself — **`EXPORT_LINK_TTL_S = 300` is confirmed by direct observation**, not just staff prose. **One correction to the constants file's documented failure shape:** the expired-link response here was **HTTP 403 with `<Code>AccessDenied</Code>`**, not the HTTP-200-with-`<Code>NoSuchKey</Code>` shape the constants file documents (from a 2023 Coda-bug report). Both are XML in the response body starting with `<?xml`, so the existing `looks_like_s3_error()` body-sniffing guard (checking for `<?xml` / matching on body content, not on status code) still catches this case — but a naive client that only checked `status != 200` would actually have caught *this* instance (403 is unambiguous), while the `NoSuchKey`-on-200 case documented previously would not be. Both failure shapes should be treated as fatal-for-this-link and trigger a re-GET of the status endpoint.

## P5c — Subpages and `contentType` precondition

```
$ curl -s -H "$H" "$BASE/docs/$DOC/pages?limit=50" | jq -r '.items[] | "\(.id)\t\(.contentType)\t\(.name)\tparent=\(.parent.id // "-")"'
canvas-4LiD-eeMTK	canvas	Untitled page	parent=-
```

Single page, `contentType: canvas`, no parent, no children — matches the target-state description exactly. **No subpages and no non-`canvas` page exist in this doc, so the "no subpage content appears" and "non-canvas pages 400 on export" claims could not be tested here** — that requires a doc structure this scratch doc does not have. Recorded as a target-state limitation, not a probe failure. The exported markdown from P5a contained exactly the three probe lines written by P3/P4/P6's writes and nothing else, consistent with "no subpage content."

## P6 — Export bucket, and 429 headers

Ran exactly as written — 6 requests, no more.

```
export POST 1 -> 202  {"id":"57c1ecb0-...","status":"inProgress",...}
export POST 2 -> 202  {"id":"fbbbdd6b-...","status":"inProgress",...}
export POST 3 -> 202  {"id":"3d06cf55-...","status":"inProgress",...}
export POST 4 -> 202  {"id":"b5051ac6-...","status":"inProgress",...}
export POST 5 -> 202  {"id":"aa924e58-...","status":"inProgress",...}
export POST 6 -> 202  {"id":"df71aaf7-...","status":"inProgress",...}

=== headers of last response ===
HTTP/2 202
content-type: application/json; charset=utf-8
content-length: 196
date: Fri, 04 Sep 2026 01:04:46 GMT
x-coda-pod: api-doc-7b76d879df-pdd7b
x-coda-server: api-doc
... (no ratelimit/retry-after headers)

=== any rate-limit headers? ===
NONE
```

**Result: all six requests, fired back-to-back (sub-2-second wall time for the whole loop), returned 202. Zero 429s. No `Retry-After` or `X-RateLimit-*` headers appeared (none were expected to, since no 429 occurred).**

This directly contradicts the assumption held by the `upstream-api` topic (see `_rfc/README.md`) and the constants file that export shares the tight doc-content-write bucket (3 or 5 per 10 s): six requests in under two seconds is well over both published figures for that bucket, and none were throttled. **The `Retry-After` question remains empirically UNRESOLVED** — a real 429 was never provoked anywhere in this entire session (P1 through P9), and the plan's ethical bound (exactly 6 requests, not extended) was insufficient to reach one here. Per the rules, no further requests were sent to try to force a 429.

**Incidental finding:** the export POST's response headers show `x-coda-server: api-doc` and pod names prefixed `api-doc-...`, distinct from `x-coda-server: api` / `api-...` seen on `/whoami` and `/docs/{docId}/tables` in P1/P2. Export traffic is served by a visibly separate backend pod class. This is consistent with (though does not prove) export using a rate-limit bucket separate from the doc-content-write bucket used by table/page mutations.

No 429 occurred, so the 60-second wait rule was not triggered.

## P7 — Row-size inflation factor

**RUN 2026-09-04.** The scratch doc has since gained two tables; P7 ran against
`grid-PH5-RNMCB1` (`test-table-01`), text column `c-euWseAF6J-`, ASCII payloads,
one row per request, spaced six seconds.

| Wire bytes | Result | Reported internal size |
|---|---|---|
| 30,788 | 202 accepted | — |
| 41,028 | 202 accepted | — |
| 51,268 | 202 accepted | — |
| 61,508 | 202 accepted | — |
| 81,988 | 202 accepted | — |
| 102,468 | 400 refused | "101 KB" |
| 133,188 | 400 refused | "131 KB" |

**The ratio for plain ASCII is ≈1.01, not 2.2.** Internal size tracks wire size
almost exactly, plus about a kilobyte of overhead, and the ceiling bites between
82 KB and 102 KB of wire — consistent with the published 85 KB applied to something
very close to the bytes sent. The plan anticipated this outcome and said what it
means: *"All four accepted → plain ASCII inflates far less than 2×. Repeat with
rich markdown before relaxing the cap."* That repeat has **not** been done, so the
operating value stays at 2.2. What P7 establishes is the floor, and that the 2.0
ratio in the 2023 forum report cannot have come from plain text.

Deviation from the plan as written: it piped responses through
`jq -r '.message // "OK (accepted)"'`, which discards the rest of the body. Since
the question of whether a size refusal carries a structured discriminator was live,
full bodies were kept instead. They do not — see §2.3 of the constants file.

Cleanup: all six rows written by P7 and by the timing probe were deleted, the
delete mutation was polled to `completed`, and a read-back confirmed the table
returned to its original eleven rows.

## P8 — Sync-token deletion reporting

**NOT RUN, but no longer blocked.** It was originally skipped because the scratch doc had no table; the doc has since gained two, and a six-row `deleteRows` against `grid-PH5-RNMCB1` was executed successfully on 2026-09-04 during P7's cleanup, so the delete this probe needs is demonstrably available. It remains unrun because sync tokens were out of scope for that session, not because anything blocks it.

## P9 — Synchronous page-content read

Ran as written.

```
$ curl -s -H "$H" "$BASE/docs/$DOC/pages/$PAGE/content?limit=500" | jq '{n:(.items|length), hasNext:(.nextPageToken!=null), sample:(.items[0])}'
{
  "n": 4,
  "hasNext": false,
  "sample": {
    "id": "cl-_LhGBxzGdr",
    "type": "line",
    "itemContent": {
      "style": "paragraph",
      "format": "plainText",
      "content": "",
      "lineLevel": 0
    }
  }
}
```

Running the plan's own second jq expression (`.style // "-"`, `.lineLevel // 0`, `.itemContent // ""`) against the same response:

```
-	0	{"style":"paragraph","format":"plainText","content":"","lineLevel":0}
-	0	{"style":"paragraph","format":"plainText","content":"probe-1788469474","lineLevel":0}
-	0	{"style":"paragraph","format":"plainText","content":"probe-1757033824","lineLevel":0}
-	0	{"style":"paragraph","format":"plainText","content":"probe-p4-clean","lineLevel":0}
```

**Result — schema shape differs from what the plan (and the constants file) assumed.** `style` and `lineLevel` are not top-level fields on each item; they are nested one level down inside `itemContent`, alongside `format` and `content`. The plan's own jq expression, written against the assumed flat shape, prints `-`, `0`, and the raw nested object instead of real text for every row — reproduced verbatim above as the actual (not summarized) output. The correct paths are `.itemContent.style`, `.itemContent.lineLevel`, `.itemContent.content`.

Element `id`s are present and look stable (`cl-` prefixed, one per line). All 4 lines were returned in one page (`hasNext: false`, `limit=500` well above the 4 actual lines). Plain text content for the 3 non-empty lines matched the P5a markdown export exactly, byte-for-byte — but all three lines were plain ASCII probe strings with no formatting, so this run cannot speak to how much formatting-fidelity plaintext loses versus markdown; that needs richer content, which is out of scope for this scratch doc.

## Constants to update in `docs/reference/api-operational-constants.md`

Each item below is a factual addition (what was observed, dated 2026-09-04) — none
of them changes a recommended `Value` in the constants table. Where evidence
conflicts with an existing `[CHOSEN — no evidence, tune later]` recommendation,
the conflict is stated as fact; the number itself is left for an RFC-owning
session to revisit, per the evidence-file convention.

1. **`EXPORT_BUCKET`** (§1.4 table + §2.5 prose) — established by P6. Add: six
   export POSTs fired in under 2 seconds all returned 202, zero 429s — inconsistent
   with `EXPORT_BUCKET = BUCKET_DOC_CONTENT_WRITE` at either published doc-content
   rate (3/10s or 5/10s). Also add the `x-coda-server: api-doc` / `api-doc-*` pod
   detail from the same probe — export traffic is served by a visibly distinct
   backend pod class from `api`/`api-*`, which served every other endpoint touched
   in this session.
2. **`RETRY_AFTER_TRUSTED`** (§1.1 + §2.2) — established by P6 (negative result).
   Add: a live attempt to provoke a real 429 (P6, the ethically-bounded maximum of
   6 requests) did not succeed — all six requests returned 202. Whether a genuine
   429 carries `Retry-After` remains empirically unanswered; the existing
   spec-reading-based evidence for `False` is unchanged and uncontradicted.
3. **`MUTATION_404_GRACE_S` / `MUTATION_INITIAL_SLEEP_S` / `MUTATION_DEADLINE_S`**
   (§1.3 + §2.1) — established by P4. Add: two independent write→poll sequences on
   this scratch doc never produced a 404 from `getMutationStatus`, including at
   t=0 immediately after the write. `completed` legitimately stayed `false` until
   16-18 seconds after the write. The known 404-replication race did not reproduce
   on this doc; the real bottleneck observed was completion latency, not a 404
   window.
4. **`EXPORT_LINK_TTL_S`** (§1.4 + §2.5) — established by P5a/P5b. Add: directly
   observed download-link validity — HTTP 200 through t=300s, HTTP 403 by t=330s.
   Corroborates 300s independent of staff prose. Also correct the documented
   failure shape: the expired-link response observed here was **403 with
   `<Code>AccessDenied</Code>`**, not the previously-documented 200-with-
   `<Code>NoSuchKey</Code>` shape — both are `<?xml`-prefixed bodies, so the
   existing body-sniffing guard still catches both, but note the shape is not
   fixed to one specific S3 error code or status.
5. **Export status wire values** (§3.1) — established by P5a. Add: begin-response
   `status` observed as `"inProgress"` (not the spec example's `"complete"`);
   completed-response `status` observed as `"complete"` (not `"completed"`).
6. **`listPageContent` response shape** (§2.5, "A synchronous alternative..."
   section) — established by P9. Correct the description: `style`, `format`,
   `content`, and `lineLevel` are **not** top-level fields on each content item —
   they are nested one level down under `item.itemContent`. The current prose
   ("each with a stable element `id`, a `style`... and a `lineLevel`") reads as
   flat and should say so nests under `itemContent`.
7. **§2.1, "The 400 cannot be distinguished by shape"** — established by P2/P3.
   Add two findings: (a) live evidence that `listPageContent` **does** return the
   `BadRequestWithValidationErrors`-shaped 400 (`codaType`, `codaDetail.issues`)
   for a real schema violation, contradicting the claim that no docs/rows/pages/
   tables/columns operation uses that shape; (b) `X-Coda-Doc-Version` was found to
   reject *any* non-`latest`, non-empty value with `400 {"message":"Doc is not yet
   up to date."}`, deterministically and reproducibly, even with no plausible
   pending mutation — meaning that exact message text cannot be assumed to be the
   genuine staleness message; it is also what an invalid header value produces.
