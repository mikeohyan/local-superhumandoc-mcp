# RFC index

Design decisions for this repository, newest number last. The process is
specified by the `rfc-process` topic below; the operating manual is the `rfc`
skill in `.claude/skills/rfc/`.

**An RFC's number does not determine its path.** Use the Path column below, or
`ls _rfc/**/NNNN-*.md`.

## Current decisions by topic

**Cite this table, not a number.** Any document whose job is to describe how the
project works now — every file in this repository that is not an RFC body —
refers to a decision by its **topic**, so that superseding costs one row here
instead of a repository-wide repair. RFC bodies are the exception: they are
frozen records and cite numbers. The convention is specified by the
`doc-conventions` topic.

A topic names a *subject*, so successive decisions about it share one topic and
only the newest appears here. Status is carried because a topic's current
decision may not yet be accepted.

| Topic | Current RFC | Status | Path |
|---|---|---|---|
| `upstream-api` | 0008 | Implemented | `_rfc/archive/implemented/0008-api-version-lock-and-advisory-rate-limits.md` |
| `config-resolution` | 0006 | Implemented | `_rfc/archive/implemented/0006-credential-and-config-resolution.md` |
| `doc-conventions` | 0009 | Implemented | `_rfc/archive/implemented/0009-documentation-reference-conventions.md` |
| `evidence-location` | 0003 | Implemented | `_rfc/archive/implemented/0003-evidence-and-reference-material.md` |
| `failure-policy` | 0010 | Implemented | `_rfc/archive/implemented/0010-failure-classification-and-retry-policy.md` |
| `packaging` | 0007 | Implemented | `_rfc/archive/implemented/0007-packaging-and-distribution.md` |
| `rfc-process` | 0001 | Implemented | `_rfc/archive/implemented/0001-rfc-process.md` |
| `server-ownership` | 0004 | Accepted | `_rfc/0004-build-local-doc-scoped-server.md` |
| `tool-surface` | 0005 | Accepted | `_rfc/0005-tool-surface-and-write-safety.md` |

## In flight — `_rfc/`

Proposed and Accepted: decided or awaiting decision, not yet shipped.

| # | Title | Topic | Status | Decided | Path |
|---|---|---|---|---|---|
| 0004 | Build a local doc-scoped MCP server rather than adopting the official or community servers | `server-ownership` | Accepted | 2026-09-04 | `_rfc/0004-build-local-doc-scoped-server.md` |
| 0005 | Expose element-scoped editing tools and gate destructive operations behind a flag | `tool-surface` | Accepted | 2026-09-04 | `_rfc/0005-tool-surface-and-write-safety.md` |

## Implemented — `_rfc/archive/implemented/`

Shipped, **and still the current truth**. Read these to learn how the system
works today.

| # | Title | Topic | Status | Decided | Path |
|---|---|---|---|---|---|
| 0001 | Record design decisions as immutable RFCs in `_rfc/` | `rfc-process` | Implemented | 2026-09-03 | `_rfc/archive/implemented/0001-rfc-process.md` |
| 0003 | Keep empirical evidence and reference material in `docs/`, separate from decisions in `_rfc/` | `evidence-location` | Implemented | 2026-09-04 | `_rfc/archive/implemented/0003-evidence-and-reference-material.md` |
| 0006 | Resolve credentials and document scope from a project-local `.env` inside the server | `config-resolution` | Implemented | 2026-09-04 | `_rfc/archive/implemented/0006-credential-and-config-resolution.md` |
| 0007 | Package with hatchling and distribute via `uvx` from pinned git tags | `packaging` | Implemented | 2026-09-04 | `_rfc/archive/implemented/0007-packaging-and-distribution.md` |
| 0008 | Pin development to Superhuman Docs API v1.6.0 and treat published rate limits as advisory | `upstream-api` | Implemented | 2026-09-04 | `_rfc/archive/implemented/0008-api-version-lock-and-advisory-rate-limits.md` |
| 0009 | Reference decisions by topic and code by symbol, never by number or line | `doc-conventions` | Implemented | 2026-09-03 | `_rfc/archive/implemented/0009-documentation-reference-conventions.md` |
| 0010 | Classify transport failures by whether the request was transmitted, and bound every retry by one deadline | `failure-policy` | Implemented | 2026-09-04 | `_rfc/archive/implemented/0010-failure-classification-and-retry-policy.md` |

## Retired — `_rfc/archive/retired/`

Superseded or Rejected. No longer true — history only. A retired RFC keeps its
topic so the lineage stays joined; it is never the topic's current decision.

| # | Title | Topic | Status | Superseded by | Path |
|---|---|---|---|---|---|
| 0002 | Pin development to Superhuman Docs API v1.6.0 and track spec drift | `upstream-api` | Superseded | 0008 | `_rfc/archive/retired/0002-superhuman-docs-api-version-lock.md` |
