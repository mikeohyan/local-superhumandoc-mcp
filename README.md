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
token in UUID form; see the `upstream-api` topic in
[`_rfc/README.md`](_rfc/README.md) for the authentication scheme, the pinned API
version, and why the published rate limits are treated as advisory.

That covers working on the server in this repository. Installing it into a
project that *uses* it is below.

## Installing in a project

**Not yet available** — there is no implementation, so nothing here runs
today. This records the shape decided by the `config-resolution` and
`packaging` topics, and the one operational requirement that is easy to get
wrong.

A consuming project commits a `.mcp.json` carrying no secrets:

```json
{
  "mcpServers": {
    "superhumandoc": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/USER/REPO@v0.1.0",
        "superhumandoc-mcp"
      ]
    }
  }
}
```

Beside it sits a gitignored `.env` holding `SHDOC_API_KEY` and `SHDOC_DOC_ID`.
Scope the API token to that single document when you create it: the server is
bound to one document anyway, and a workspace-wide token would give every
project's server access to every other project's documents. Give it write
access rather than read-only — reading a page as markdown begins with a `POST`
to start an export, so a read-restricted token fails with a 403 that appears to
contradict its own name.

(`.env.example` in this repository still carries provisional `SUPERHUMAN_*`
names; the `config-resolution` topic renames them when it ships.)

### Launch `claude` from the project root

The server resolves its own `.env`, and its primary path is
`$CLAUDE_PROJECT_DIR/.env`. **That variable holds the directory `claude` was
launched from — not a project root found by walking up.** Project `.mcp.json`
discovery *does* walk up, so starting a session in a subdirectory registers the
server correctly and then hands it the wrong directory. The `.env` is never
found, and the first symptom is a confusing authentication error several tool
calls later.

Nothing in the client prevents this. `--add-dir` does not affect the variable,
a value preset in your shell is overwritten, `${CLAUDE_PROJECT_DIR}` is passed
through literally inside `.mcp.json`'s `args`, and a `SessionStart` hook cannot
reach the spawned server's environment. The convention is the mechanism.

If a project cannot guarantee its launch directory, pass an **absolute** path
instead, through `--env-file` or `SHDOC_ENV_FILE`, and put it in a local,
gitignored registration rather than the committed `.mcp.json` — where the path
would otherwise be identical for every clone and every machine.

The server logs the `.env` path it resolved to stderr at startup. That line is
how you confirm which file was actually loaded.

## Design decisions

Every architectural decision in this repository is recorded as an RFC under
[`_rfc/`](_rfc/README.md). Start with that index — it lists each decision, its
status, and its path.

Decisions that are still true are split across two directories: `_rfc/` holds
what has been decided but not yet shipped, and `_rfc/archive/implemented/` holds
what has shipped and remains current. `_rfc/archive/retired/` is history only.

Worth reading first:

- **`rfc-process`** — the RFC process itself: numbering, the frozen-body rule,
  and how a decision is superseded rather than rewritten.
- **`upstream-api`** — the pinned Superhuman Docs API version, base URL, auth
  scheme, how to detect upstream drift, and why the published rate limits are
  advisory rather than contractual.
- **`doc-conventions`** — why the two entries above are named by topic rather
  than by RFC number, and how to cite code without line numbers.

Those are topics, not filenames. The index resolves each to its current RFC.

## Working in this repository with Claude Code

`CLAUDE.md` carries the rules that apply to every session, and
`.claude/skills/rfc/` is the operating manual for the RFC process. The short
version: architectural decisions get an RFC before the code, an accepted RFC's
body is never rewritten, and tracked files are moved with `git mv`.
