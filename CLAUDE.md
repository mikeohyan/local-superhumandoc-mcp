# CLAUDE.md

## Project

A locally run MCP server, written in Python and managed with `uv`, that exposes
a specific Superhuman Docs document to Claude and Claude Code. Credentials come
from a per-project `.env` and are never committed.

The API surface this project targets is pinned in RFC 0008 — read it before
writing any client code, and do not re-derive the version, base URL, or auth
scheme from the web.

## Design decisions live in `_rfc/`

Read `_rfc/README.md` before starting design work. It indexes every decision and
gives each RFC's path. Decisions that are still true are split across `_rfc/`
(decided, not yet shipped) and `_rfc/archive/implemented/` (shipped) — check
both. `_rfc/archive/retired/` is history only.

Use the `rfc` skill (`.claude/skills/rfc/`) for anything that touches an RFC:
allocating a number, writing one, or moving one between statuses. The full
process is specified in RFC 0001.

Rules that apply to every session:

- **Superpowers writes its specs to `_rfc/`, not `docs/superpowers/specs/`.**
  This overrides the default path in the `superpowers:brainstorming` skill,
  which honors a project preference for spec location. Implementation plans from
  `superpowers:writing-plans` go to `_rfc/plans/NNNN-plan.md`.
- **Architectural work gets an RFC.** Use the classification
  `superpowers:brainstorming` already made: architectural → RFC; bounded → no
  RFC unless it reverses an existing decision; spike → no RFC. Decisions with no
  code count, such as pinning a dependency or setting a convention.
- **An accepted RFC's body is frozen.** Never rewrite Context, Decision,
  Alternatives considered, or Consequences after acceptance — supersede the RFC
  instead. Frontmatter (`status`, `decided`, `superseded_by`, `commits`) stays
  living, and the shipping session fills in Implementation notes.
- **Move RFC files with `git mv`, never plain `mv`.** Every transition edits
  frontmatter in the same commit as the move, which is exactly where git's
  rename inference fails. This applies to any tracked file in this repository,
  not only RFCs.
