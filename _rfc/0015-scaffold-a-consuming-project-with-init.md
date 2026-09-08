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
never deletes existing configuration — this RFC follows `terraform init`, not
`uv init`, on that point: a directory where everything already exists is the
steady state a re-run is supposed to reach, not a refusal condition.

## Decision

The console script grows one subcommand. **`superhumandoc-mcp init` scaffolds
the current directory into a working consuming project**, offline, touching no
network and handling no credentials. It writes three things:

1. **`.env`**, copied from the packaged template, with `SHDOC_API_KEY` and
   `SHDOC_DOC_ID` present and empty, and created with mode `600`. That mode is a
   POSIX guarantee, not a portable one: `os.chmod(0o600)` on Windows does not
   carry POSIX permission semantics, it only clears the read-only attribute, so
   the confidentiality this buys is real on POSIX and effectively absent on
   Windows rather than degraded-but-present.
2. **`.mcp.json`**, carrying exactly the stanza RFC 0006 fixes — `type: stdio`,
   `command: uvx`, and `args` naming the pinned source and the script — with no
   `env` block and no secret.
3. **A `.env` line appended to `.gitignore`**, creating the file if absent and
   doing nothing if the line is already there.

**The command never overwrites a byte it did not write.** That principle now
governs each artifact independently rather than gating the run as a whole.
`.env` and `.mcp.json` are each create-only, and each is checked and written on
its own: if `.env` already exists, `init` leaves it untouched and reports why,
and it makes the same check for `.mcp.json` separately, in either order. A
project that already carries a `.mcp.json` — because it registers some other
MCP server, an ordinary case — no longer blocks its `.env` from being
scaffolded, and a project with an `.env` left over from an earlier partial run
still gets its `.mcp.json` written. Collision on one artifact says nothing about
the others. That per-artifact independence is also what makes `init` safe to
re-run on a directory that is only partly scaffolded: a second run writes
whatever is still missing and leaves what already exists untouched, rather than
refusing outright the way a whole-run guard would.

There is no promise that a run produces every artifact or leaves the directory
exactly as it found it — pre-checking existence never delivered that anyway,
since a permissions error or a full disk between two independent writes has no
rollback, and this RFC does not claim otherwise. What `init` guarantees instead
is that it reports, per artifact, what it wrote and what it skipped and why —
`wrote .env`, `skipped .mcp.json: already exists` — so the report, not an
atomicity guarantee, is what makes a partial run recoverable: the user can see
exactly which artifact still needs attention rather than re-running blind. That
report is printed to stdout, one line per artifact. This looks like it breaks a
rule this codebase otherwise enforces everywhere — `__main__.py` sends even its
startup diagnostics to stderr, with a comment that stdout is reserved for the
MCP transport — but that rule protects the serving path, and `init` is not on
it: it runs to completion and exits before any transport exists, so there is no
protocol stream on stdout to corrupt, and the report is not a diagnostic beside
one but the entire output a person reading a terminal is here for. A future
change should not fold this into stderr on the strength of the general rule;
the rule and this command are answering different questions.

Skipping every artifact because each one was already correct is success, not
failure. `init` exits `0` whenever every artifact either was written this run
or was already present, with the report saying so plainly — three
`skipped: already exists` lines rather than three `wrote` lines when there was
nothing left to do — echoing `terraform init`'s re-run guarantee from the
Context above rather than contradicting it: finding nothing to do is the
expected steady state of a directory `init` has already finished, not an error
condition. `SystemExit(2)`, the same code `__main__.py` already uses for
configuration failure, is reserved for genuine failure instead: an artifact
that could not be written because of a permissions or I/O error. That failure
prints to stderr, distinct from the stdout report above.

`.gitignore` gets different treatment, but by policy rather than by exception —
appending a line destroys nothing an existing `.gitignore` holds, so there is
nothing here for the "never overwrites" principle to protect against. `.env`
and `.mcp.json` refuse when present; `.gitignore` is appended to. A line counts
as already present only on an exact match against a stripped line of the file;
a project that ignores `.env` through a broader pattern such as `.env*`, or
through a global ignore file, gets a redundant but harmless extra line rather
than a silently skipped append. `init` writes `.gitignore` even when the current
directory is not a git repository: the ignore rule is what keeps `.env` safe on
the day the directory becomes one, and no scaffolding tool surveyed gates any
file on `.git` existing.

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

Errors — the genuine-failure case above, not the per-artifact report — follow
the precedent already in `__main__.py` rather than RFC 0007's `ToolError`
convention, which cannot apply: `ToolError` carries a message to a model inside
a running MCP session, and `init` finishes before any session exists. A failure
prints to stderr and `init` exits with `SystemExit(2)`, the same code
`__main__.py` already raises for configuration failure, rather than inventing a
second convention for what is, at bottom, the same kind of failure.

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

### Merge the stanza into an existing `.mcp.json`

When `.mcp.json` already exists — typically because the project registers some
other MCP server — `init` could parse it, add its own key under `mcpServers`,
and write the merged result, instead of skipping the file and reporting why.
This would close the one gap the per-artifact rule still leaves: a user with a
pre-existing `.mcp.json` adds this server's stanza by hand. Rejected for this
RFC because merging trades a read-only, zero-risk skip for a read-modify-write
on a file `init` did not create — exactly the class of risk "never overwrites a
byte it did not write" exists to avoid. JSON carries no comments, so a merged
write cannot mark its own addition the way `.env.example`'s prose marks the
lines it owns, and round-tripping through `json.load`/`json.dump` is not
guaranteed to reproduce another tool's formatting or key order byte-for-byte,
which turns "merge" into "rewrite" for the parts `init` did not add. The
pressure this alternative relieves is also smaller than it looks: the
per-artifact rule above already lets `.env` scaffold independently of
`.mcp.json`, so the merge case
left over is "the user still types one JSON stanza by hand," not "the server
still cannot be configured." A future RFC can take up merge semantics
deliberately if that manual step turns out to matter in practice.

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
documentation.** Every word in it will be copied verbatim into user projects
that never see this repository. That raised the cost of the staleness present
in both files when this RFC was drafted: `.env.example`'s `SHDOC_ALLOW_DESTRUCTIVE`
comment claimed the flag "gates nothing, because the server registers no tools
at all", which had stopped being true once RFC 0013 shipped eighteen tools, and
the README carried three separate variants of the same "registers no tools yet"
claim. Both were prerequisites of shipping this RFC rather than cleanup that
could follow it, since `init` would otherwise have propagated the error to
every new project — and both have since been corrected on this branch, ahead of
implementation, rather than deferred. The point that endures past the
correction is the forward-looking one: shipping `init` permanently raises the
cost of any future staleness in `.env.example`, because from that point on
every word in it ships verbatim into a project with no way to notice it has
drifted.

**The console script now has two jobs, and the boundary must stay sharp.** Every
future subcommand faces the question of whether it belongs here or in the tool
surface RFC 0013 governs. The line this RFC sets: `init` is offline, runs before
any MCP session, handles no credentials, and is invoked by a human. Anything a
model invokes is a tool, not a subcommand.

**Cutting `v0.1.0` becomes load-bearing, and the obligation does not end there.**
Today the repository has no tags and `init` cannot emit a resolvable pin.
Cutting the tag fixes only the bootstrap case: `init` derives `@vX.Y.Z` from
`importlib.metadata.version("superhumandoc-mcp")`, which is correct only while
the installed version and an existing tag of that name actually agree. Every
release from here on carries a standing obligation to keep those two facts in
lockstep — bump `pyproject.toml` and cut the matching tag together, not in
either order with a gap between — because a maintainer who bumps the version
first and tags later leaves a window in which `init`, run against that
intermediate state, emits a pin naming a tag that does not exist yet. Beyond
that, a version that ships a broken `init` mints broken projects until the next
tag.

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
