# CLAUDE.md

## Project

A locally run MCP server, written in Python and managed with `uv`, that exposes
a specific Superhuman Docs document to Claude and Claude Code. Credentials come
from a per-project `.env` and are never committed.

The API surface this project targets is pinned by the `upstream-api` topic. Look
it up in `_rfc/README.md` and read the RFC it names before writing any client
code, and do not re-derive the version, base URL, or auth scheme from the web.

## Design decisions live in `_rfc/`

Read `_rfc/README.md` before starting design work. It indexes every decision and
gives each RFC's path. Decisions that are still true are split across `_rfc/`
(decided, not yet shipped) and `_rfc/archive/implemented/` (shipped) — check
both. `_rfc/archive/retired/` is history only.

Use the `rfc` skill (`.claude/skills/rfc/`) for anything that touches an RFC:
allocating a number, writing one, or moving one between statuses. The full
process is specified by the `rfc-process` topic.

## Evidence and reference material live in `docs/`

`docs/reference/` holds distilled findings — API behaviour, constants, formats —
that an implementer consults while writing code. `docs/validation/` holds
runnable test plans, with a Results section filled in as they are run. Read
`docs/` when a decision already made in `_rfc/` needs the evidence behind it, or
when writing client code that depends on undocumented API behaviour. This split
is decided by the `evidence-location` topic.

Files under `docs/` are mutable, unversioned, and corrected in place as facts
are learned — the opposite of a frozen RFC body. The boundary is directional:
**nothing in `docs/` is authoritative for a decision.** A `docs/` file may
record that the API's rate limit is five requests per ten seconds; only an RFC
may say the client therefore self-throttles. When a `docs/` file starts
asserting a choice rather than a fact, that choice belongs in an RFC.

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
- **Cite decisions by topic, never by number, in any living document.** This
  file, both `README.md` files, `.env.example`, `.gitignore`, everything under
  `.claude/skills/` and everything under `docs/` describe how the project works
  *now*, so they name a topic and let `_rfc/README.md` resolve it. An RFC number
  in one of them rots the moment that RFC is superseded. RFC bodies are the
  exception — they are frozen records, and a number in one is correct as
  history. Code is cited the same way: path plus symbol, never a line number.
  See the `doc-conventions` topic.
- **Move RFC files with `git mv`, never plain `mv`.** Every transition edits
  frontmatter in the same commit as the move, which is exactly where git's
  rename inference fails. This applies to any tracked file in this repository,
  not only RFCs.
