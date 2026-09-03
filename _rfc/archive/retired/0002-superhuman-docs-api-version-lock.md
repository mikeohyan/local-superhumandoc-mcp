---
rfc: 0002
title: Pin development to Superhuman Docs API v1.6.0 and track spec drift
status: Superseded
created: 2026-09-03
decided: 2026-09-03
supersedes:
superseded_by: 0008
topic: upstream-api
commits: []
tags: [api, dependencies, superhuman-docs]
---

# RFC 0002 — Pin development to Superhuman Docs API v1.6.0 and track spec drift

## Context

This project wraps the Superhuman Docs API in a locally run MCP server. The API
is versioned as `v1` in its URL path, but that path segment is not the version
that matters: the OpenAPI document behind it carries its own `info.version`,
which moves as endpoints and fields are added. Building against "v1" therefore
says nothing useful about what was actually available when the code was written.

The provider's stated deprecation policy is a three-month notice before older
APIs and functionality are removed, announced in the Developers Central section
of their community and documented at `https://docs.superhuman.com/api-updates`.
Three months is enough warning only if someone is watching. Nothing in a local
MCP server watches on its own.

There is a second, subtler hazard. The product was rebranded from Coda, and the
old and new hostnames both serve the same specification. A future session that
finds `coda.io` in one file and `docs.superhuman.com` in another may reasonably
conclude they are two different services.

Facts below were verified on 2026-09-03 by fetching the raw specification, not
by reading rendered documentation.

## Decision

Development targets **Superhuman Docs API `info.version` 1.6.0**, `openapi:
3.0.0`, retrieved 2026-09-03.

- **Base URL:** `https://docs.superhuman.com/apis/v1`, taken from the `servers`
  block of the specification itself.
- **Canonical spec URL:** `https://coda.io/apis/v1/openapi.yaml`. The legacy
  `coda.io` host is where the machine-readable document is served; the
  `docs.superhuman.com` host is where it is documented and where requests go.
  These are one API under two hostnames, not two APIs.
- **Spec fingerprint at pin time:** SHA-256
  `d145ed596a33830548e1ceac6668df94c10b71491800d0855bc0711472d0224b`.
- **Authentication:** HTTP bearer, `bearerFormat: UUID`, sent in the
  `Authorization` header. The token is read from `.env` and never committed.

The version, base URL, and fingerprint are recorded in this RFC, and this RFC is
the single place they are stated. Code and configuration reference the values;
they do not redefine them.

Drift is detected by comparing the live specification against the pinned
fingerprint:

```bash
curl -s https://coda.io/apis/v1/openapi.yaml | sha256sum
```

A changed digest means the specification moved. That is not by itself a problem
— the digest changes on any edit, including prose. The response is to compare
`info.version` and the endpoints this project actually calls, and then either
record that the pin still holds or supersede this RFC with a new pinned version.
Because an accepted RFC's body is frozen, moving to 1.7.0 means writing RFC
NNNN with `supersedes: 0002`, not editing this file.

Known rate limits at the pinned version, which the client is expected to respect
rather than discover through failures: reads 100 requests / 6 seconds; writes
10 / 6 seconds; doc-content writes 5 / 10 seconds; listing docs 4 / 6 seconds;
analytics reads 100 / 6 seconds.

## Alternatives considered

### Track the latest specification continuously

Re-fetch the spec on each build and always target current. Rejected because it
makes the project's behaviour depend on an external document that can change
between two runs of the same commit, which turns an upstream edit into an
unreproducible local failure. A pin plus a deliberate upgrade keeps the change
visible in git.

### Pin only the URL path segment `v1`

The cheapest option, and the one the API's own URL structure invites. Rejected
because `v1` has been stable across the entire Coda-to-Superhuman rebrand and
will not move when fields are added or removed. It records nothing.

### Vendor a copy of `openapi.yaml` into the repository

Guarantees reproducibility and allows generating a typed client offline.
Rejected for now as premature: the file is large, would dominate the repository's
diff history, and nothing yet generates code from it. A fingerprint gives the
drift detection without the weight. Vendoring becomes worth revisiting if and
when client generation is introduced — that would be its own RFC.

### Watch the changelog instead of the specification

Subscribe to `https://docs.superhuman.com/api-updates` and react to
announcements. Rejected as the primary mechanism because it depends on a human
reading announcements on a schedule. It remains the right place to look *after*
a fingerprint change has already signalled that something moved.

## Consequences

**Makes easy.** A single command answers "has upstream moved?". Any future
session can learn exactly what surface the code was written against without
inferring it from the code. The rebrand confusion is resolved in writing, once.

**Makes hard.** Adopting a newly released endpoint requires superseding this
RFC rather than simply calling it. Nothing runs the drift check automatically,
so it is only as reliable as the habit of running it.

**Commits us to.** Bearer-token authentication from `.env`, the
`docs.superhuman.com/apis/v1` base URL, and a client that treats the documented
rate limits as design constraints rather than as errors to retry blindly.

**Noted, not decided here.** The specification advertises an official Superhuman
Docs MCP server. Whether that changes the case for building a local one is a
separate question and, if pursued, a separate RFC.

## Implementation notes

Not yet implemented — no client code exists at the time of writing.
