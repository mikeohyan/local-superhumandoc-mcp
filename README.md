# local-superhumandoc-mcp

A locally run MCP server that exposes a specific Superhuman Docs document to
Claude and Claude Code. Written in Python, managed with `uv`, and intended to be
set up per project folder: each project points the server at its own document
and supplies its own credentials through a local `.env`.

**Status: the server is built, and its tool surface is complete.** Credential
and config resolution, the HTTP client with its throttling, retry and
failure-classification policy, the server factory, and the tool surface —
decided by the `tool-surface` and `request-sizing` topics — are all
implemented and tested. A client that connects finds twelve always-on tools:
`outline_page`, `describe_table`, `get_doc_overview`, `get_row`, `find_rows`,
`read_page`, `create_page`, `append_to_page`, `rename_page`,
`replace_element`, `update_row`, `upsert_rows`. Six more — `delete_page`,
`clear_page_content`, `overwrite_page`, `delete_element`, `delete_rows`,
`push_button` — register only when `SHDOC_ALLOW_DESTRUCTIVE` is enabled.

## Requirements

[`uv`](https://docs.astral.sh/uv/) is the only thing you need installed. It
fetches its own Python — this project needs 3.11 or newer — and handles
everything else. Nothing below assumes a checkout of this repository or any
credentials beyond your own Superhuman Docs API token.

## Installing in a project

Run this once in the project directory:

```bash
uvx --from git+https://github.com/mikeohyan/local-superhumandoc-mcp@v0.2.0 \
  superhumandoc-mcp init
```

It writes three files and reports on each: a `.mcp.json` registering this
server, a `.env` skeleton at mode `600` waiting for your token and document ID,
and a `.env` line in `.gitignore`. Fill in the two values, then launch `claude`
from that directory.

**`init` never overwrites anything, and each file is decided on its own.** A
file that is missing gets created. A `.env` that already exists — because the
project holds other credentials, or because an earlier run stopped halfway —
keeps every byte it has and gains only the `SHDOC_` keys it was missing,
appended at the end with their explanatory comments. An existing `.mcp.json` is
left exactly as it is, because adding a key to a JSON document means rewriting
all of it; `init` prints the stanza to paste under `mcpServers` instead. So it
is safe to re-run: a directory that is already set up reports three skips and
exits 0.

The registration `init` writes:

```json
{
  "mcpServers": {
    "superhumandoc": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/mikeohyan/local-superhumandoc-mcp@v0.2.0",
        "superhumandoc-mcp"
      ]
    }
  }
}
```

It carries no secret and no `env` block — the server resolves credentials
itself, which is what the `config-resolution` topic decides. The pin names a
tagged release rather than a branch, as the `packaging` topic requires, and
`init` writes the version that scaffolded the project, so a project stays on
the exact server it was set up with until someone changes that line. The shape
of the command and its collision rules are set by the `project-setup` topic.

The `.env` beside it holds `SHDOC_API_KEY` and `SHDOC_DOC_ID`, plus the
optional keys documented in [`.env.example`](.env.example) — which `init`
copies in full, so the file it leaves in your project is the list to read
rather than this paragraph.

Scope the API token to that single document when you create it: the server is
bound to one document anyway, and a workspace-wide token would give every
project's server access to every other project's documents. Give it write
access rather than read-only — reading a page as markdown begins with a `POST`
to start an export, so a read-restricted token fails with a 403 that appears to
contradict its own name.

### Launch `claude` from the project root

The server resolves its own `.env`, and its primary path is
`$CLAUDE_PROJECT_DIR/.env`. **That variable holds the directory `claude` was
launched from — not a project root found by walking up.** Project `.mcp.json`
discovery *does* walk up, so starting a session in a subdirectory registers the
server correctly and then hands it the wrong directory. The `.env` is never
found, and the first symptom is a confusing authentication error several tool
calls later.

Nothing in the client prevents this, and the obvious workarounds were each tested
and each fail — see `docs/reference/mcp-client-environment.md` for what was tried
and what it did. The convention is the mechanism.

If a project cannot guarantee its launch directory, pass an **absolute** path
instead, through `--env-file` or `SHDOC_ENV_FILE`, and put it in a local,
gitignored registration rather than the committed `.mcp.json` — where the path
would otherwise be identical for every clone and every machine.

The server logs the `.env` path it resolved to stderr at startup. That line is
how you confirm which file was actually loaded.

## Working on the server itself

Everything above is about *using* the server. To change it:

```bash
git clone https://github.com/mikeohyan/local-superhumandoc-mcp
cd local-superhumandoc-mcp
cp .env.example .env                      # then fill in your token and document ID
uv sync                                   # including the dev group
uv run pytest                             # the test suite
uv run superhumandoc-mcp --env-file "$PWD/.env"
```

`.env` is gitignored and must never be committed. The API token is a bearer
token in UUID form; see the `upstream-api` topic in
[`_rfc/README.md`](_rfc/README.md) for the authentication scheme, the pinned API
version, and why the published rate limits are treated as advisory.

The last command serves MCP over stdio, so it will sit waiting on a client
rather than printing and exiting. The startup line described above is how you
check it resolved the `.env` you meant.

Changes arrive by fork and pull request; nobody but the owner can push here.
`main` refuses force-pushes and deletion, and a published `v*` tag can never be
moved or deleted — those tags are pins inside other people's `.mcp.json` files,
so moving one would silently change what their server runs. The immutability
rule itself belongs to the `packaging` topic; the repository now enforces it
rather than relying on discipline.

## Design decisions

Every architectural decision in this repository is recorded as an RFC under
[`_rfc/`](_rfc/README.md). Start with that index — it lists each decision, its
status, and its path.

Decisions that are still true live in more than one directory, and the index
explains which. Worth reading first:

- **`rfc-process`** — the RFC process itself: numbering, the frozen-body rule,
  and how a decision is superseded rather than rewritten.
- **`upstream-api`** — the pinned Superhuman Docs API version, base URL, auth
  scheme, how to detect upstream drift, and why the published rate limits are
  advisory rather than contractual.
- **`doc-conventions`** — why the two entries above are named by topic rather
  than by RFC number, and how to cite code without line numbers.

Those are topics, not filenames. The index resolves each to its current RFC.

## Evidence and reference material

Decisions in `_rfc/` rest on evidence kept separately, in
[`docs/`](docs/): `docs/reference/` holds distilled findings, and
`docs/validation/` holds runnable test plans with their results. Files there
are mutable and unversioned, and nothing in `docs/` is authoritative for a
decision — only an RFC can turn a finding into a choice. See the
`evidence-location` topic.

## Working in this repository with Claude Code

`CLAUDE.md` carries the rules that apply to every session, and
`.claude/skills/rfc/` is the operating manual for the RFC process. The short
version: architectural decisions get an RFC before the code, an accepted RFC's
body is never rewritten, and tracked files are moved with `git mv`.
