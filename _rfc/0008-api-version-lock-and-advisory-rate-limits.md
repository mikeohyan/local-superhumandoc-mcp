---
rfc: 0008
title: Pin development to Superhuman Docs API v1.6.0 and treat published rate limits as advisory
status: Proposed
created: 2026-09-03
decided:
supersedes: 0002
superseded_by:
topic: upstream-api
commits: []
tags: [api, dependencies, superhuman-docs, rate-limiting]
---

# RFC 0008 — Pin development to Superhuman Docs API v1.6.0 and treat published rate limits as advisory

## Context

RFC 0002 pinned this project to Superhuman Docs API `info.version` 1.6.0 and, in
the same breath, recorded the published rate limits as settled fact: *"reads 100
requests / 6 seconds; writes 10 / 6 seconds; doc-content writes 5 / 10 seconds;
listing docs 4 / 6 seconds; analytics reads 100 / 6 seconds."* It further
declared itself the single place those values are stated, so that code and
configuration would reference them rather than redefine them.

The pin is sound. The rate-limit paragraph is not, and an accepted RFC's body may
not be rewritten — so the correction takes the form of a supersede.

**What was verified on 2026-09-03.** The specification is served in two
renderings from the same source, and they disagree:

- `https://coda.io/apis/v1/openapi.yaml` carries substituted numbers — the five
  figures RFC 0002 recorded.
- `https://coda.io/apis/v1/openapi.json` carries **unsubstituted template
  variables**: `{{READ_RATE_LIMIT}}`, `{{WRITE_RATE_LIMIT}}`,
  `{{WRITE_DOC_CONTENT_RATE_LIMIT}}`, `{{LIST_DOCS_RATE_LIMIT}}` and
  `{{ANALYTICS_RATE_LIMIT}}`.

The numbers are therefore a **render artifact of a template**, not a contract.
Whatever value is substituted at render time is what a reader sees, and the
templating exists precisely because the values are expected to be configurable
upstream rather than fixed.

**What is reported but not verified.** Research recorded in
`docs/reference/api-operational-constants.md` reports that the vendor's help
centre states **3 requests per 10 seconds** for doc-content writes, against the
YAML's 5, and that the buckets are keyed per user **and IP address** rather than
per user alone. Neither claim was independently confirmed. They are recorded here
as leads because they point the same direction — the published figure may be
more generous than the enforced one — not as findings.

**A second, independent limitation of the pin.** Some of this API's most
important behaviours are documented only in vendor forum posts and never appear
in the specification at all. The clearest case: writing a relation cell by
referencing a target row's ID is staff-confirmed and load-bearing for RFC 0005,
yet all nineteen `rowId` occurrences in the specification are read-side, part of
`RowsDelete`, or path parameters. A fingerprint over the specification cannot
detect a change to behaviour the specification never described.

## Decision

Everything RFC 0002 decided about the pin itself is carried forward unchanged:

- **Version:** Superhuman Docs API `info.version` **1.6.0**, `openapi: 3.0.0`.
- **Base URL:** `https://docs.superhuman.com/apis/v1`, from the specification's
  own `servers` block.
- **Canonical spec URL:** `https://coda.io/apis/v1/openapi.yaml`. The legacy
  `coda.io` host serves the machine-readable document; `docs.superhuman.com` is
  where it is documented and where requests go. One API, two hostnames.
- **Spec fingerprint:** SHA-256
  `d145ed596a33830548e1ceac6668df94c10b71491800d0855bc0711472d0224b`. Confirmed
  on 2026-09-03 to be identical across an initial fetch and an independent
  re-fetch later the same day.
- **Authentication:** HTTP bearer, `bearerFormat: UUID`, in the `Authorization`
  header, read from `.env` per RFC 0006 and never committed.

**Published rate limits are advisory, not contractual.** The figures rendered in
the YAML at pin time are recorded below as the best available published values,
explicitly not as a guarantee:

| Bucket | Published figure (YAML rendering, 2026-09-03) |
|---|---|
| Reading data | 100 requests / 6 seconds |
| Writing data (POST/PUT/PATCH) | 10 / 6 seconds |
| Writing doc content (POST/PUT/PATCH) | 5 / 10 seconds |
| Listing docs | 4 / 6 seconds |
| Reading analytics | 100 / 6 seconds |

Three rules follow, and they are the substance of this RFC:

1. **The client self-throttles to the most conservative published figure, not
   the most convenient.** For doc-content writes that means operating at **3 per
   10 seconds** rather than 5, pending confirmation of the help-centre figure.
   Being wrong in the conservative direction costs only latency; being wrong in
   the permissive direction costs 429s in the middle of a user's work.

2. **A 429 is an expected outcome, not an exceptional one.** The buckets are
   shared beyond this process — at minimum per user across all docs, and
   possibly per IP as well — so a second client, another session, or a shared
   egress address can exhaust a bucket this server's limiter believes has
   headroom. Local limiter headroom is never evidence that a request will
   succeed. Error messages surfaced to the model must say this, so a 429 does
   not read as a bug in the throttle.

3. **Neither a changed nor an unchanged fingerprint is conclusive.** A changed
   digest may mean nothing more than a re-render with different substitutions,
   so it triggers a comparison of `info.version` and the endpoints this project
   calls — not an assumption that the API moved. An unchanged digest is **not**
   evidence that behaviour is unchanged, because behaviour documented only in
   forum posts is invisible to it.

Drift is still checked the same way, with those caveats understood:

```bash
curl -s https://coda.io/apis/v1/openapi.yaml | sha256sum
```

Moving to a later API version means writing a new RFC with `supersedes: 0008`,
not editing this one.

## Alternatives considered

### Amend RFC 0002 in place

Edit the rate-limit paragraph and move on. Rejected because RFC 0001 freezes an
accepted body, and the rule is worth more than the convenience. There is also a
substantive reason beyond process: what RFC 0002 believed on the day it was
written is itself information. A future session that finds the enforced limit is
3 per 10 seconds benefits from seeing that the published figure once said 5.

### Keep RFC 0002 and record the correction only in `docs/`

Put the discrepancy in the reference file and leave the decision record alone.
Rejected because RFC 0002's body asserts the numbers as fact *and* claims to be
the single place they are stated. A `docs/` file contradicting a live RFC is
exactly the drift RFC 0003 forbids: evidence records what is true, only an RFC
makes it binding.

### Pin the JSON rendering instead of the YAML

Superficially attractive, since the JSON's unsubstituted placeholders are more
honest about the templating. Rejected because a document that renders
`{{READ_RATE_LIMIT}}` to a reader gives the client no starting value at all, and
the rest of the specification is identical. Better to pin the informative
rendering and document its nature.

### Drop rate limits from the RFC entirely

Say nothing, and let the client discover limits through 429s. Rejected because
the client needs a defensible starting number to throttle against, and
discovering limits by hitting them is precisely the behaviour the vendor's own
guidance warns against. Advisory is not the same as absent.

### Vendor a copy of the specification into the repository

Rejected for the same reason RFC 0002 rejected it, and the reasoning is
unchanged: the file is large, would dominate diff history, and nothing yet
generates code from it. It becomes worth revisiting if client generation is
introduced, which would be its own RFC. Note that vendoring would *not* solve the
problem this RFC addresses — a vendored copy freezes one render's substitutions
and makes them look more authoritative than they are.

## Consequences

**Makes easy.** The client's throttle is honest about what it knows. A 429 that
arrives despite available local headroom has a documented explanation rather than
looking like a defect, which saves a future session a debugging session chasing a
limiter bug that does not exist.

**Makes hard.** Doc-content writes run at 3 per 10 seconds rather than 5 — forty
percent slower on the tightest bucket in the API. Batch operations will feel it.

Page-markdown reads were originally counted in that cost, on the reasoning that
the export kickoff is a POST and so must draw on the doc-content-write bucket.
**Probe P6 refuted this on 2026-09-04.** Six export POSTs fired back-to-back,
under two seconds for the whole loop, all returned 202 — well over both published
figures for that bucket, with nothing throttled. Export traffic is also served by
a visibly separate backend pod class (`x-coda-server: api-doc`, against `api` for
`/whoami` and `/docs/{docId}/tables`), which is consistent with a separate bucket
without proving one. So reads of page markdown do not compete with doc-content
writes for the tightest bucket in the API, and a throttle that serialises them
against each other would be needlessly slow. The evidence is at
`docs/validation/2026-09-03-api-operational-probes.md`.

**Commits us to.** A drift check that is explicitly incomplete. This RFC records
that the fingerprint cannot see undocumented behaviour, which means the project
has no automated way to detect a change to relation-write semantics or any other
forum-documented behaviour. That gap is now known rather than assumed away, but
it is not closed.

**Watch for.** Probe P6 in `docs/validation/2026-09-03-api-operational-probes.md`
was run on 2026-09-04 and settled less than was hoped. It refuted the export
bucket assumption recorded above, but it never provoked a 429, so **whether a
real 429 carries `Retry-After` remains empirically unresolved** — as does the
3-versus-5 figure for doc-content writes. No 429 was seen anywhere in that
session, across every probe run.

That question stays open deliberately. P6 is bounded at exactly six requests
because these buckets are shared per user and possibly per IP, so exhausting one
degrades service for every other client behind the same identity or egress
address. Six was not enough to reach a 429 here. **The bound is not to be lifted
to chase the answer.** The honest way to close the question is a 429 encountered
in normal operation, not one manufactured.

If the enforced limit does turn out to be 5, the conservative operating value
should be revisited — a bounded change to a constant, not a supersede, because
this RFC decides the *rule* (throttle to the most conservative published figure)
rather than the number.

## Implementation notes

Left empty at Proposed.
