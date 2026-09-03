# Superhuman Docs API — operational probe plan

**Date:** 2026-09-03
**Target:** `https://docs.superhuman.com/apis/v1` (formerly Coda API v1; specs are byte-identical)
**Status:** NOT YET RUN — see the empty Results section at the bottom.

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
express. The current recommendation is not to ship sync tokens in v1. **Run this
only if that recommendation is being reconsidered.**

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

**Run date:**
**Doc used (size / row count / page count):**
**Token owner / workspace:**

## P1 — Authenticated rate-limit headers

_(not yet run)_

## P2 — `X-Coda-Doc-Version` value handling

_(not yet run)_

## P3 — Staleness 400: fires? message text? control case?

_(not yet run)_

## P4 — `getMutationStatus` 404 window

_(not yet run)_

## P5a — Export replication window and status value

_(not yet run)_

## P5b — `downloadLink` lifetime

_(not yet run)_

## P5c — Subpages and `contentType` precondition

_(not yet run)_

## P6 — Export bucket, and 429 headers

_(not yet run)_

## P7 — Row-size inflation factor

_(not yet run)_

## P8 — Sync-token deletion reporting *(only if reconsidering sync tokens)*

_(not yet run)_

## P9 — Synchronous page-content read

_(not yet run)_

## Constants to update in `docs/reference/api-operational-constants.md`

_(list each constant whose marker changes from [CHOSEN — no evidence, tune later]
to an evidenced value, with its new value and the probe that established it)_
