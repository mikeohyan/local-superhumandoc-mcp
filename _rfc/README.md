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
| `async-operations` | 0012 | Accepted | `_rfc/0012-async-operation-polling-and-export-budget.md` |
| `upstream-api` | 0008 | Implemented | `_rfc/archive/implemented/0008-api-version-lock-and-advisory-rate-limits.md` |
| `config-resolution` | 0006 | Implemented | `_rfc/archive/implemented/0006-credential-and-config-resolution.md` |
| `doc-conventions` | 0009 | Implemented | `_rfc/archive/implemented/0009-documentation-reference-conventions.md` |
| `evidence-location` | 0003 | Implemented | `_rfc/archive/implemented/0003-evidence-and-reference-material.md` |
| `failure-policy` | 0010 | Implemented | `_rfc/archive/implemented/0010-failure-classification-and-retry-policy.md` |
| `packaging` | 0007 | Implemented | `_rfc/archive/implemented/0007-packaging-and-distribution.md` |
| `request-sizing` | 0014 | Proposed | `_rfc/0014-measure-the-row-instead-of-estimating-it.md` |
| `rfc-process` | 0001 | Implemented | `_rfc/archive/implemented/0001-rfc-process.md` |
| `server-ownership` | 0004 | Implemented | `_rfc/archive/implemented/0004-build-local-doc-scoped-server.md` |
| `tool-surface` | 0013 | Proposed | `_rfc/0013-html-content-and-the-read-write-cycle.md` |

**Two topics currently resolve to a Proposed RFC.** `tool-surface` and
`request-sizing` each name a supersede that has not been accepted yet, so the
decision they point at is proposed rather than settled — which is why this table
carries Status. The RFCs they replace are retired below and are history, not
fallbacks: shipped code written against them is described by their replacements,
which carry those parts forward deliberately.

## In flight — `_rfc/`

Proposed and Accepted: decided or awaiting decision, not yet shipped.

| # | Title | Topic | Status | Decided | Path |
|---|---|---|---|---|---|
| 0012 | Poll asynchronous operations on one bounded loop, and give export its own budget | `async-operations` | Accepted | 2026-09-06 | `_rfc/0012-async-operation-polling-and-export-budget.md` |
| 0013 | Write page content as HTML, and never send a read back as a write | `tool-surface` | Proposed | | `_rfc/0013-html-content-and-the-read-write-cycle.md` |
| 0014 | Measure a row in the units the API counts, and report what a deadline left undone | `request-sizing` | Proposed | | `_rfc/0014-measure-the-row-instead-of-estimating-it.md` |

## Implemented — `_rfc/archive/implemented/`

Shipped, **and still the current truth**. Read these to learn how the system
works today.

| # | Title | Topic | Status | Decided | Path |
|---|---|---|---|---|---|
| 0001 | Record design decisions as immutable RFCs in `_rfc/` | `rfc-process` | Implemented | 2026-09-03 | `_rfc/archive/implemented/0001-rfc-process.md` |
| 0003 | Keep empirical evidence and reference material in `docs/`, separate from decisions in `_rfc/` | `evidence-location` | Implemented | 2026-09-04 | `_rfc/archive/implemented/0003-evidence-and-reference-material.md` |
| 0004 | Build a local doc-scoped MCP server rather than adopting the official or community servers | `server-ownership` | Implemented | 2026-09-04 | `_rfc/archive/implemented/0004-build-local-doc-scoped-server.md` |
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
| 0005 | Expose element-scoped editing tools and gate destructive operations behind a flag | `tool-surface` | Superseded | 0013 | `_rfc/archive/retired/0005-tool-surface-and-write-safety.md` |
| 0011 | Split oversized batches rather than refusing them, and answer a size refusal by asking for less | `request-sizing` | Superseded | 0014 | `_rfc/archive/retired/0011-request-sizing-and-batch-splitting.md` |
