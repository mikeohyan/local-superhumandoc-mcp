# RFC index

Design decisions for this repository, newest number last. The process is
specified in RFC 0001; the operating manual is the `rfc` skill in
`.claude/skills/rfc/`.

**An RFC's number does not determine its path.** Use the Path column below, or
`ls _rfc/**/NNNN-*.md`.

## In flight — `_rfc/`

Proposed and Accepted: decided or awaiting decision, not yet shipped.

| # | Title | Status | Decided | Path |
|---|---|---|---|---|
| 0003 | Keep empirical evidence and reference material in `docs/`, separate from decisions in `_rfc/` | Proposed | — | `_rfc/0003-evidence-and-reference-material.md` |
| 0008 | Pin development to Superhuman Docs API v1.6.0 and treat published rate limits as advisory | Proposed | — | `_rfc/0008-api-version-lock-and-advisory-rate-limits.md` |

## Implemented — `_rfc/archive/implemented/`

Shipped, **and still the current truth**. Read these to learn how the system
works today.

| # | Title | Status | Decided | Path |
|---|---|---|---|---|
| 0001 | Record design decisions as immutable RFCs in `_rfc/` | Implemented | 2026-09-03 | `_rfc/archive/implemented/0001-rfc-process.md` |

## Retired — `_rfc/archive/retired/`

Superseded or Rejected. No longer true — history only.

| # | Title | Status | Superseded by | Path |
|---|---|---|---|---|
| 0002 | Pin development to Superhuman Docs API v1.6.0 and track spec drift | Superseded | 0008 | `_rfc/archive/retired/0002-superhuman-docs-api-version-lock.md` |
