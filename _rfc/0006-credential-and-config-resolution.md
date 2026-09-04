---
rfc: 0006
title: Resolve credentials and document scope from a project-local .env inside the server
status: Proposed
created: 2026-09-03
decided:
supersedes:
superseded_by:
topic: config-resolution
commits: []
tags: [architecture, configuration, security]
---

# RFC 0006 — Resolve credentials and document scope from a project-local `.env` inside the server

## Context

This server is installed per project folder. Each project points it at its own
Superhuman Docs document and supplies its own API token through a local `.env`
that is never committed. The authentication scheme itself — HTTP bearer, UUID
token format — is fixed by RFC 0008 and is not restated here. What is unsettled
is the mechanism: how a process started by an MCP client finds the right `.env`
for the project it is serving.

The obvious answer, "read `.env` from the current directory", does not survive
contact with how stdio servers are launched.

**A stdio MCP server does not control its own working directory. The client sets
it.** Claude Code gives a spawned stdio server the directory `claude` was
launched from, uniformly across project, local and user registration scopes. The
client's documentation is easily read as saying the working directory is
`~/.claude` for a user-scoped server; that table describes a different helper
process, and direct observation shows no scope-dependent variation for the stdio
server itself. The hazard is real but differently shaped: the working directory
is the *launch* directory, so a user who runs `claude` from a subdirectory of
their project gets that subdirectory. Anything resting on `Path.cwd()` therefore
works until someone changes directory before launching, at which point it
silently loads the wrong file or none at all. A `find_dotenv()`-style walk
upward survives that case but introduces its own, since it keeps climbing past
the project root and can load an unrelated `.env` from a parent directory or
from home. The observations are recorded at
`docs/reference/mcp-client-environment.md`.

The second constraint rules out the mechanism the client appears to offer.
Claude Code supports `${VAR}` and `${VAR:-default}` expansion inside `.mcp.json`
for `command`, `args`, and `env`. It cannot carry the token:

- Expansion draws from the **shell environment and `settings.json`**, never from
  a `.env` file. `.mcp.json` has no `envFile` support; there are open feature
  requests for precisely this (claude-code#28942, claude-code#48873).
- It is reported broken in the Claude Desktop application, where the server
  receives the literal string `${VAR}` rather than a value (claude-code#40372).
- `claude mcp add` is reported to expand placeholders eagerly and write the
  **resolved values** into `.mcp.json` (claude-code#18692). Since `.mcp.json` is
  a committed file, that turns a convenience into a leaked credential.

Writing the token directly into `.mcp.json`'s `env` block has the same fatal
property for the same reason.

So the client can neither be trusted to supply the working directory nor used to
carry the secret. The server has to find its own configuration.

## Decision

The server loads its own `.env` at startup, resolving the file from four
candidates in order:

1. an explicit `--env-file <path>` command-line argument
2. `$SHDOC_ENV_FILE`
3. `$CLAUDE_PROJECT_DIR/.env`
4. `./.env`, relative to whatever working directory the client happened to set

**A candidate that was asked for explicitly is not allowed to fall through.**
Candidates 1 and 2 name a path directly, so if that path does not exist the
server **fails at startup and says which path was missing**. It does not quietly
try the next candidate. The alternative is the worst failure this design can
produce: a typo in `--env-file` silently resolving to some other project's
`.env`, binding the server to the wrong document with a token that works. An
explicit path is a statement about intent, and the only safe response to an
intent that cannot be honoured is to stop. Candidates 3 and 4 are inferred
rather than stated, so a miss there is ordinary and falls through as normal.

Candidate 3 carries normal operation when `claude` is launched from the project
root, which is the common case. Claude Code sets `CLAUDE_PROJECT_DIR` in the
spawned server's environment, and it is the same value hooks receive. Because it
is provided by the client rather than inferred, it stays correct across
registration scopes — but it does **not** stay correct across launch
directories. It carries the directory `claude` was started in, not a project
root found by walking up. `.mcp.json` discovery *does* walk up, so a session
started from a subdirectory registers this server correctly and then hands it
the wrong directory. Candidate 4 fails identically and for the same reason: both
resolve against the launch directory.

Candidates 1 and 2 are therefore load-bearing more often than "escape hatch"
suggests. They are the only candidates independent of the launch directory, and
only when given an absolute path. They cover clients that set no such variable,
a `.env` outside the project, and any project that cannot guarantee where
`claude` is started. An absolute path belongs in a local, gitignored
registration rather than in the committed project `.mcp.json`, where it would be
identical for every clone and every machine. Candidate 4 remains last because it
is the one that can be wrong without being empty.

Two mechanisms that look like they would close the gap do not.
`${CLAUDE_PROJECT_DIR}` is not expanded inside `.mcp.json`'s `args`, which
receives the literal string; and a `SessionStart` hook can neither be relied on
to run before the server spawns nor influence the environment it receives. Both
were tested; see `docs/reference/mcp-client-environment.md`.

**Only `SHDOC_`-prefixed keys are read out of the file, and the file is not
exported into the process environment.** A project `.env` is a project's file,
not this server's: it routinely holds database passwords, cloud credentials and
third-party keys that have nothing to do with Superhuman Docs. Loading it
wholesale into `os.environ` would put every one of them inside a process that
talks to the network, for no benefit — the server needs five variables and knows
all of their names. Reading only its own prefix keeps the blast radius of a
compromised or over-curious dependency to the credential this server was always
going to hold.

Within that prefix, values are resolved with real environment variables winning
over file contents — the equivalent of `override=False`, and the intuitive
precedence, since it lets a project override a single value through
`.mcp.json`'s `env` block without editing its file.

**`SHDOC_ALLOW_DESTRUCTIVE` is the exception: disagreement resolves to the
restrictive value.** If the environment enables the destructive tools and the
`.env` does not, they stay unregistered. Ordinary precedence is a convenience
rule, and applying it to this flag would let a `SHDOC_ALLOW_DESTRUCTIVE=1`
exported into a shell months ago and long forgotten silently arm whole-page
overwrite in every project launched from that shell — including projects whose
own `.env` explicitly disables it. A user who wants the tools in a project can
say so in that project. The startup line names the source of each resolved
value, file or environment, so an override is visible rather than inferred.

**The server logs the resolved `.env` path to stderr at startup.** This is not a
diagnostic nicety. Every failure mode above is silent: the wrong file loads, or
no file loads, and the first symptom is a confusing authentication error several
tool calls later. One line of output turns a mystery into an observation.

### Environment variables

Every variable carries the `SHDOC_` prefix.

| Variable | Required | Meaning |
| --- | --- | --- |
| `SHDOC_API_KEY` | yes | Superhuman Docs API token, sent as `Authorization: Bearer <token>` per RFC 0008. |
| `SHDOC_DOC_ID` | yes | The single document this server instance is bound to. Every tool operates within it. |
| `SHDOC_ALLOW_DESTRUCTIVE` | no | Registers the destructive tools, but only on an explicit affirmative value — see the parser below. Default off. What it gates, and why gating happens at registration rather than at call time, is specified in RFC 0005. |
| `SHDOC_ENV_FILE` | no | Explicit path to the `.env` file; candidate 2 above. |
| `SHDOC_LOG_LEVEL` | no | Verbosity of stderr diagnostics. |

**`SHDOC_ALLOW_DESTRUCTIVE` is parsed as an explicit affirmative, not as a set
variable and not as Python truthiness.** The value is stripped of surrounding
whitespace and lowercased; the tools are registered if and only if the result is
one of `1`, `true`, `yes`, `on`. Every other value leaves them unregistered —
unset, empty, `0`, `false`, `no`, `off`, and **any unrecognised string**.

The distinction is load-bearing rather than pedantic, and this RFC states it
because two plausible readings disagree exactly where it is most dangerous.
"Set" would register whole-page overwrite and `push_button` for
`SHDOC_ALLOW_DESTRUCTIVE=false`, which is the opposite of what anyone writing
that line intends. Python truthiness on the raw string does the same, since any
non-empty string is truthy. Both readings turn an attempt to disable the
destructive surface into the act of enabling it.

Unrecognised values fail closed for the same reason. A typo must not arm a
destructive tool, and there is nothing to gain by guessing what a value like
`maybe` was meant to say. The server logs the parsed result at startup beside the
resolved `.env` path, so a user who expected the tools and does not see them has
one line to read rather than a missing-tool mystery.

These names supersede the provisional `SUPERHUMAN_API_TOKEN` and
`SUPERHUMAN_DOC_ID` placeholders currently in `.env.example`, which that file
already marks as awaiting the RFC that specifies the client. Updating
`.env.example` and the README is part of shipping this RFC.

Configuration is read **once, at build time, before the server begins serving**.
Tool registration is therefore static for the life of the process: the set of
tools a client sees is fixed when the process starts and cannot change in
response to a later environment change. Changing a flag means restarting the
server.

### The resulting client configuration

Because the server finds its own credentials, the `.mcp.json` stanza contains no
secrets and needs no expansion:

```json
{
  "mcpServers": {
    "superhumandoc": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "<pinned source>", "superhumandoc-mcp"]
    }
  }
}
```

`command` and `args` belong to RFC 0007, and `<pinned source>` is deliberately
not spelled out here: a concrete repository URL and version tag written into
this RFC would freeze, in a configuration decision, a distribution detail that
is another RFC's to change. The README carries the form a user copies.

What **this** RFC fixes is the shape of the rest: there is no `env` block and no
`${VAR}` anywhere in the stanza. Both are absent by design rather than by
omission, and the Alternatives below explain why neither can carry the token.

### Token scope

Tokens are minted at `https://docs.superhuman.com/account` and cannot be viewed
or modified after creation. The API supports restricting a token to a single
document (`/docs/${DOC_ID}`) or even a single table.

**Projects use a document-scoped token.** The server is bound to one document by
`SHDOC_DOC_ID`; scoping the credential the same way costs nothing and means a
leaked or misused token cannot reach the rest of the workspace. A workspace-wide
token grants every project's server access to every other project's documents,
which is a strictly worse position for no benefit.

Two properties of token restrictions must be stated because both produce
confusing failures:

- Restrictions are set in the provider's UI at creation time. There is no API to
  create or introspect them, and `whoami` does not report scope. A server cannot
  discover at runtime what its token may do — only by making a call and reading a
  403.
- Operation restrictions map `GET` to read access and `POST`, `PUT`, `DELETE` to
  write access. **Reading a page's content as markdown requires a `POST`** to
  begin an export. A token restricted to read access therefore cannot read page
  content, and fails with a 403 that appears to contradict its own name. The
  error layer translates this case explicitly rather than passing the raw status
  through.

## Alternatives considered

### Bare `load_dotenv()` or `find_dotenv()`, walking up from the working directory

The idiomatic Python approach and a single line of code. Rejected because it
inherits the client's working directory, which is exactly the value that is not
under our control. Bare `load_dotenv()` reads `./.env` against the launch
directory, making it candidate 4 with no fallbacks: it fails whenever `claude`
is started from a subdirectory, silently and with no signal that anything
changed. `find_dotenv()` survives that case by walking up, and buys a worse one
— the walk does not stop at the project root, so it can reach an unrelated
`.env` in a parent directory or in the user's home and load a token scoped to
the wrong document.

This RFC first rejected the approach on a different ground: that it would
resolve to `~/.claude/.env` for a user-scoped registration, making correctness
depend on an invisible registration choice made in another tool. **Direct
observation refuted that.** The working directory is the launch directory
uniformly across project, local and user scopes, and the `~/.claude` value the
client's documentation shows describes a different helper process, not the
spawned stdio server. The rejection stands, but on launch-directory grounds
rather than scope-dependence — the failure is triggered by where a user happens
to be standing, not by how the server was registered. Recorded at
`docs/reference/mcp-client-environment.md`.

### Environment variables written inline into `.mcp.json`'s `env` block

Works today, requires nothing of the server, and is what most MCP server
documentation shows. Rejected for the API token because `.mcp.json` is a
committed file and the token is a secret; this is a credential leak with extra
steps. It remains perfectly reasonable for non-secret values, and the
`override=False` precedence above is chosen so that a project *can* set
`SHDOC_DOC_ID` there if it prefers.

### `${VAR}` expansion in `.mcp.json`

The mechanism the client appears to offer for exactly this problem, and the one
a future session is most likely to propose. Rejected on three independent
grounds, any one of which would be sufficient: it expands from the shell
environment and `settings.json` rather than from a `.env`, so it does not solve
the problem we actually have; it is reported broken in Claude Desktop, where the
literal `${VAR}` string reaches the server; and `claude mcp add` is reported to
resolve placeholders and write real values into the committed file. Depending on
it would make the project's security posture a function of which client the user
happens to launch.

### Require `--env-file` always, with no fallbacks

Fully explicit, trivially debuggable, no inference anywhere. Rejected because it
pushes a mandatory path into every `.mcp.json` in every project, which is both
noise and a second place for the project's layout to be wrong. It also breaks
the plain `uvx` invocation for anyone trying the server from a shell. Keeping it
as candidate 1 preserves the explicit path for the projects that need it —
which, per the Decision above, is more of them than "escape hatch" suggests —
without making every project carry it.

## Consequences

**Makes easy.** A project's credentials live in one gitignored file next to the
code that uses them, and the client configuration that references the server
contains nothing sensitive — so `.mcp.json` can be committed and shared without
thought. Moving a project between machines means copying one file. The same
server binary serves many projects, each bound to its own document, with no
global state.

**Makes hard.** Anything that wants to change configuration must restart the
server, because registration is static. Diagnosing a bad `.env` requires reading
stderr, which some clients bury.

Three choices here trade convenience for safety, and each will occasionally
annoy someone who knew what they were doing. A stale `--env-file` or
`SHDOC_ENV_FILE` now stops the server at startup rather than falling back to a
working default, so a path that rots breaks a session outright instead of
degrading quietly — which is the point, but it is still a session that stopped.
Reading only the `SHDOC_` prefix means a project cannot route any other value to
this server through its `.env`, and would have to use the `env` block for that.
And because `SHDOC_ALLOW_DESTRUCTIVE` resolves to the restrictive value on
disagreement, a user who deliberately exports it to enable the destructive tools
will find it ignored in any project whose `.env` sets it off, with only the
startup line to explain why. That is the intended answer — the project's own
file should win when the two disagree about arming a destructive surface — but
it inverts the precedence every other variable follows, and it will surprise
someone.

**Commits us to.** A dependency on `CLAUDE_PROJECT_DIR` for the path that
matters. That variable is documented on the Claude Code MCP documentation page
but is **absent from the environment-variables reference page**. It has since
been confirmed by direct observation to be set for spawned stdio servers under
every registration scope, so the dependency itself is sound. It was confirmed
just as directly to be the launch directory rather than the project root, and no
way to pin it was found: `--add-dir` does not affect it, a shell-preset value is
overwritten, and no setting or CLI command assigns it. The startup log line is
therefore not a first-install check that can later be retired — it is the
standing signal for a failure that recurs whenever a session is started from a
subdirectory.

Under other MCP clients — Claude Desktop, Cursor, an editor extension — neither
`CLAUDE_PROJECT_DIR` nor a useful working directory can be assumed. Those clients
fall through to candidate 4 and will frequently find nothing, which is why
`--env-file` and `SHDOC_ENV_FILE` exist and why the startup log names the file
actually loaded. Supporting a client that offers no way to locate the project
would mean requiring an explicit path there.

**Accepted risk.** The `.env` sits in the project directory as plaintext, at
whatever permissions the filesystem gives it. This is the ordinary posture for
local development credentials and matches what the repository already documents,
but it is a real exposure: any process running as the user can read the token,
and the token is only as narrow as its scope. That is the concrete reason the
document-scoped token above is a requirement rather than a suggestion.

## Implementation notes

Left empty at Proposed.
