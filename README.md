# local-superhumandoc-mcp

A locally run MCP server that exposes a specific Superhuman Docs document to
Claude and Claude Code. Written in Python, managed with `uv`, and intended to be
set up per project folder: each project points the server at its own document
and supplies its own credentials through a local `.env`.

**Status: no implementation yet.** The repository currently holds the decision
record and project conventions. The API surface has been pinned, but no client
code has been written.

## Setup

```bash
cp .env.example .env    # then fill in your token and document ID
```

`.env` is gitignored and must never be committed. The API token is a bearer
token in UUID form; see RFC 0002 for the authentication scheme, the pinned API
version, and the documented rate limits.

Further setup steps will be added here once the server exists.

## Design decisions

Every architectural decision in this repository is recorded as an RFC under
[`_rfc/`](_rfc/README.md). Start with that index — it lists each decision, its
status, and its path.

Decisions that are still true are split across two directories: `_rfc/` holds
what has been decided but not yet shipped, and `_rfc/archive/implemented/` holds
what has shipped and remains current. `_rfc/archive/retired/` is history only.

Worth reading first:

- **RFC 0001** — the RFC process itself: numbering, the frozen-body rule, and
  how a decision is superseded rather than rewritten.
- **RFC 0002** — the pinned Superhuman Docs API version, base URL, auth scheme,
  rate limits, and how to detect upstream drift.

## Working in this repository with Claude Code

`CLAUDE.md` carries the rules that apply to every session, and
`.claude/skills/rfc/` is the operating manual for the RFC process. The short
version: architectural decisions get an RFC before the code, an accepted RFC's
body is never rewritten, and tracked files are moved with `git mv`.
