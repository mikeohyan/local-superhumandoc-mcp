---
rfc: 0015
title: Scaffold a consuming project with an `init` subcommand
status: Proposed
created: 2026-09-08
decided:
supersedes:
superseded_by:
topic: project-setup
commits: []
tags: [architecture, cli, onboarding, packaging, configuration]
---

# RFC 0015 — Scaffold a consuming project with an `init` subcommand

## Context

RFC 0007 distributes this server as `uvx --from git+<url>@<tag> superhumandoc-mcp`,
specifically so a consuming project never clones this repository. RFC 0006 puts
credential resolution inside the server, reading a project-local `.env` the
project owns. Each decision is sound on its own. Together they leave a hole:
**the only good `.env` template lives in a repository the consumer deliberately
does not have.**

`.env.example` at this repository's root is that template — a commented file
that explains the `SHDOC_` prefix rule, why `SHDOC_ENV_FILE` is absent from it,
and how `SHDOC_ALLOW_DESTRUCTIVE` fails closed. None of it ships. The wheel
built from this project contains `superhumandoc_mcp/*.py` and `dist-info` and
nothing else, because `[tool.hatch.build.targets.wheel] packages` names only the
package directory. Unzipping the built wheel confirms it. So the setup path the
README documents — copy `.env.example`, fill in two values — asks a user to go
fetch a file by hand from a URL nobody has told them, out of a repository the
distribution model exists to avoid cloning.

What actually fills the gap today is the server's own error messages, and they
are better than the documentation. An empty directory produces `No .env found.
Looked for --env-file, $SHDOC_ENV_FILE, $CLAUDE_PROJECT_DIR/.env and ./.env.`,
and a file with blank values produces `SHDOC_API_KEY, SHDOC_DOC_ID not set.
Resolved .env: <path>`. Both name the next action. But they are diagnostics for a
server that is already misconfigured and already running under a client. They are
not a path from an empty directory to a working one, and reaching the first of
them requires having written a `.mcp.json` correctly first.

**The MCP client cannot close this gap, and waiting for it to is not a plan.**
`claude mcp add --scope project` does write a `.mcp.json`, and `.mcp.json`
supports `${VAR}` expansion in `command`, `args`, and `env`, which is how a
committed registration normally stays secret-free. But there is no `envFile` key
that would let a committed `.mcp.json` point at a gitignored `.env`. That is an
open feature request, anthropics/claude-code#28942, filed 2026-02-26 and still
carrying no maintainer response. So the client can do the `.mcp.json` half and
not the `.env` half — and under RFC 0006 the `.env` half is the half that
matters, because resolution was deliberately placed inside the server rather than
in the client's `env` block.

A survey of prior art found no precedent to copy. The official
`modelcontextprotocol/servers` repository documents setup as README prose plus
copy-paste JSON, with no server shipping an `init` subcommand. The automation
that exists sits in two other categories: tools that scaffold a *new server's
source code* (`automcp init`), and cross-server installers that configure other
people's servers into a client (`mcpm`, `install-mcp`). Neither is a server
bootstrapping its own consumer. This is a negative finding from a reasonably
thorough search rather than proof of absence, and it is a reason to be careful
about the shape rather than a reason not to build it.

The scaffolding conventions themselves are settled, though, and worth borrowing.
`uv init` refuses outright when a `pyproject.toml` already exists rather than
prompting or overwriting. `terraform init` is documented as safe to re-run and
never deletes existing configuration. Across the tools surveyed, no tool treats
"the file already existed, so I did nothing" as a success.

## Decision

The console script grows one subcommand. **`superhumandoc-mcp init` scaffolds
the current directory into a working consuming project**, offline, touching no
network and handling no credentials. It writes three things:

1. **`.env`**, copied from the packaged template, with `SHDOC_API_KEY` and
   `SHDOC_DOC_ID` present and empty, and created with mode `600`.
2. **`.mcp.json`**, carrying exactly the stanza RFC 0006 fixes — `type: stdio`,
   `command: uvx`, and `args` naming the pinned source and the script — with no
   `env` block and no secret.
3. **A `.env` line appended to `.gitignore`**, creating the file if absent and
   doing nothing if the line is already there.

**The command never overwrites a byte it did not write.** This single rule
decides every collision. `.env` and `.mcp.json` are create-only: if either
already exists, `init` writes *nothing at all*, names the file that stopped it,
and exits non-zero. The check happens before the first write, so a run either
produces both files or leaves the directory exactly as it found it — there is no
partial state in which a user has a fresh `.mcp.json` pointing at credentials
that were never written. `.gitignore` is the exception that proves the rule:
appending a line destroys nothing, so `init` appends idempotently rather than
refusing, and it never rewrites the file's existing content.

There is no `--force`. Regenerating means deleting the file first, which is an
act the user performs deliberately on a file that may hold a live token. A flag
that overwrites credentials is a flag that eventually overwrites credentials by
accident, and the recovery cost is asymmetric: the user must go re-issue a token.
This is the one place this RFC departs from the `uv init` convention it otherwise
follows, and it departs in the more conservative direction.

**The `.env` template has exactly one copy on disk.** The root `.env.example`
stays the canonical file that contributors edit, and hatchling's `force-include`
re-exposes it inside the wheel:

```toml
[tool.hatch.build.targets.wheel.force-include]
".env.example" = "superhumandoc_mcp/templates/env.example"
```

`init` reads it back with
`importlib.resources.files("superhumandoc_mcp").joinpath("templates/env.example")`.
Because there is one file rather than a copy under `src/`, the packaged template
cannot drift from the canonical one and no test is needed to hold them together.
The alternative — a second physical copy — was built and measured too, and is
rejected below.

**`init` writes a real pinned tag, derived from its own version.** RFC 0007
requires a tag pin rather than a branch, and forbids moving a published tag, so
version `X.Y.Z` and tag `vX.Y.Z` identify the same code permanently. `init` reads
`importlib.metadata.version("superhumandoc-mcp")` and writes `@vX.Y.Z`, which
means a scaffolded project pins the exact server that scaffolded it. **This makes
cutting `v0.1.0` a prerequisite of shipping this RFC**, not a follow-up: RFC
0007's implementation notes left that tag outstanding, and until it exists `init`
would emit a registration that resolves to nothing.

`init` operates on the current working directory and takes no path argument. A
process launched by `uvx` inherits the invoking shell's working directory, which
was verified directly rather than assumed, and which is already the property RFC
0006 relies on for resolution candidate 4. Adding a `--path` flag would let a
user write credentials into a directory they are not standing in — the same class
of confusion that made RFC 0006 refuse to fall back to a second `.env`.

Argument parsing uses `argparse` subparsers registered **without**
`required=True`, so the bare, subcommand-free invocation that every `.mcp.json`
emits keeps parsing exactly as it does today and keeps reaching the server path.
Unrecognized arguments continue to fail closed with a non-zero exit rather than
being reinterpreted.

Errors follow the precedent already in `__main__.py` rather than RFC 0007's
`ToolError` convention, which cannot apply: `ToolError` carries a message to a
model inside a running MCP session, and `init` finishes before any session
exists. It prints to stderr and exits non-zero, as configuration failures already
do.

## Alternatives considered

### Inline the template in the README instead

The cheap fix: paste the full `.env` body into the README's install section so it
is copy-paste with no fetch, and change nothing in the code. It genuinely solves
most of the pain and costs nothing to ship. Rejected as the *whole* answer
because it creates a second copy of the template that drifts from `.env.example`
— the exact failure this RFC's force-include arrangement is designed to prevent —
and because it still leaves the user hand-assembling three files. It is,
however, worth doing immediately as an interim step, and it remains correct after
`init` ships, since a reader deciding whether to adopt the server should be able
to see what it will write.

### Prompt interactively for the token and document ID

Ask for the two values and write a complete, working `.env`, saving the user an
editing step. Rejected because it requires a TTY, which makes the command
unusable from a script or a nested agent session, and because it puts a live
credential through terminal input and shell history for no real gain — the user
must open an editor to review the file anyway. A non-interactive skeleton
composes with automation; a prompt does not.

### Provide `--force` to regenerate

The convention `uv init` follows, and the obvious escape hatch when the packaged
template gains a new key. Rejected because the file it would overwrite is the one
holding a live API token, and the blast radius is asymmetric: a mistaken
overwrite costs a token re-issue, while its absence costs one `rm`. If a future
version needs to migrate an existing `.env`, that is a different command with
different semantics — one that reads and merges rather than truncates — and it
should be designed as such rather than smuggled in behind a flag.

### Ship the template as a copied file under `src/`

Put `env.example` under `src/superhumandoc_mcp/templates/` as ordinary package
data and let `packages` pick it up, requiring no build configuration. This was
built and verified to work. Rejected because it puts two copies of the same
content in the repository, which drift, and the only defense is a test asserting
byte equality. `force-include` reaches the same wheel layout with one file and no
test.

### Ship the template as hatchling `shared-data`

Also built and measured. Rejected on evidence rather than taste: `shared-data`
installs to `sys.prefix` rather than into the package, so the file landed outside
the package directory and was unreachable from
`importlib.resources.files("superhumandoc_mcp")`. Under `uvx` that prefix is an
ephemeral cache directory, unrelated to anything the user can see.

### Wait for `.mcp.json` to support `envFile`

If anthropics/claude-code#28942 ships, a committed `.mcp.json` could name a
gitignored `.env` directly and part of this problem dissolves. Rejected as a
plan because the issue has sat since February 2026 with no maintainer response,
and because it would close the registration half rather than the template half —
a user would still need to obtain a correctly-commented `.env` from somewhere.
Should it ship, it changes what `init` writes into `.mcp.json`, not whether
`init` should exist.

### Build a separate installer tool

The `mcpm` model: a standalone CLI that configures many MCP servers into many
clients. Rejected as wildly disproportionate. This is one server bound to one
document; a second distributable package with its own release cadence, to write
two files, is not a trade this project should make.

## Consequences

**A new project becomes three steps: run `init`, paste two values, launch
`claude` from that directory.** The launch-directory constraint that RFC 0006
documents does not go away — `CLAUDE_PROJECT_DIR` is still the directory `claude`
started in, and starting in a subdirectory still resolves the wrong `.env` — but
`init` at least guarantees the file exists at the root where a correct launch
will find it. The startup line remains the way to confirm which file loaded, and
`init` does not replace it.

**`.env.example` stops being an internal convenience and becomes shipped user
documentation.** Every word in it will be copied verbatim into user projects that
never see this repository. That raises the cost of the staleness already present
there: its `SHDOC_ALLOW_DESTRUCTIVE` comment still claims the flag "gates
nothing, because the server registers no tools at all", which stopped being true
when RFC 0013 shipped eighteen tools. Correcting that file is a prerequisite of
shipping this RFC, not a cleanup that can follow it, because `init` would
otherwise propagate the error to every new project. The same is true of the
README's three separate "registers no tools yet" claims, which currently tell a
prospective user the server is not worth installing.

**The console script now has two jobs, and the boundary must stay sharp.** Every
future subcommand faces the question of whether it belongs here or in the tool
surface RFC 0013 governs. The line this RFC sets: `init` is offline, runs before
any MCP session, handles no credentials, and is invoked by a human. Anything a
model invokes is a tool, not a subcommand.

**Cutting `v0.1.0` becomes load-bearing.** Today the repository has no tags and
`init` cannot emit a resolvable pin. Beyond that, every release now has a second
obligation: a scaffolded project pins the version that scaffolded it, so a
version that ships a broken `init` mints broken projects until the next tag.

**Committing to writing `.mcp.json` couples this project to a client format it
does not own.** The stanza is currently stable and shared across MCP clients, but
if it changes, projects scaffolded by older versions carry the old shape, and
they carry it in a committed file rather than a regenerable one. The mitigation
is only that `init` writes the minimal documented form and no optional keys.

**Writing `.gitignore` touches a file this project does not own.** Appending one
line is close to the smallest possible intrusion, and it is idempotent, but a
project with an unusual ignore setup — a global ignore file, or an existing
negation for `.env` — could end up with a redundant or contradictory line. The
alternative was leaving the secret-leak footgun armed, which is worse.

**A `.env` at mode `600` is a deliberate choice this project makes, not an
industry default it inherits.** The survey could not confirm from primary sources
that `gh` or `aws configure` chmod their credential files rather than leaving them
at the umask. The reasoning stands on its own — the file holds a bearer token —
but the RFC should not be read as citing precedent it does not have.

## Implementation notes

Left empty at Proposed.
