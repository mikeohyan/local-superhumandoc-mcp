# Claude Code as an MCP client — what a spawned stdio server actually sees

This file records what is **true** about the environment and working directory
Claude Code gives a stdio MCP server it spawns, and about `python-dotenv`'s
`override` behaviour. It exists to settle the assumption flagged in the
`config-resolution` topic (see `_rfc/README.md`): that assumption rested on
manually setting `CLAUDE_PROJECT_DIR` rather than on observing Claude Code set
it. Nothing here is authoritative for a design decision — only an RFC may say
the server therefore resolves its `.env` a particular way. Corrections belong
in place; this file is mutable.

**Tested against:** Claude Code CLI `2.1.259`.
**Date:** 2026-09-03.

## How to read the confidence markers

Reusing the scheme from `docs/reference/api-operational-constants.md`:

| Marker | Meaning |
|---|---|
| **[OBSERVED]** | Reproduced directly in this environment: a probe process, spawned by this exact Claude Code binary as a real stdio MCP server, dumped its own `os.environ` and `os.getcwd()` to a file this session then read. |
| **[DOCUMENTED]** | Read from Claude Code's own hosted documentation (`code.claude.com/docs`), not independently reproduced here. |
| **[CAVEAT]** | A limitation of the observation method itself — read before trusting the finding it's attached to. |

## Method

A minimal script, `probe_server.py` (not a real MCP server — just enough
newline-delimited JSON-RPC to answer `initialize` / `notifications/initialized`
/ `tools/list` / `tools/call` without hanging the client), wrote its own
`os.environ` and `os.getcwd()` to an absolute path the instant it started, then
served one no-op tool. It was registered under all three scopes in turn and
spawned by running `claude -p "<call the tool>" --allowedTools "mcp__<name>__noop"`
from various working directories, then the dumped file was read back. Project
scope also used `--mcp-config .mcp.json --strict-mcp-config` for an isolated
first check. User- and local-scope registrations were removed immediately after
each observation (`claude mcp remove --scope <scope>`); nothing was left in
global config.

**[CAVEAT]** This session is itself a nested Claude Code agent working in a git
worktree, not a bare top-level CLI session. `CLAUDE_CONFIG_DIR` was set to a
non-default profile directory (`/home/mike/.claude-profiles/alt`) throughout,
and several `CLAUDE_CODE_*`/`CLAUDE_*` variables in the dumps below
(`CLAUDE_CODE_BRIDGE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_SOCKET`,
`CLAUDE_CODE_MESSAGING_TOKEN`, `CLAUDE_EFFORT`, `CLAUDE_PID`,
`CLAUDE_CODE_ENTRYPOINT=sdk-cli`, `AI_AGENT`) are artifacts of that outer
harness, not general-purpose Claude Code behaviour — don't treat their
presence or values as something every install of Claude Code provides. The
core findings below (`CLAUDE_PROJECT_DIR`, `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`,
`CLAUDE_CONFIG_DIR`, and the working-directory behaviour) are not specific to
nesting and are the ones worth relying on.

## 1. Is `CLAUDE_PROJECT_DIR` set for a spawned stdio server?

**Yes.** [OBSERVED] It was present, non-empty, in every one of six spawns
across all three registration scopes (project via `.mcp.json`, local, user)
and three different invocation directories.

## 2. What value does it carry?

**The directory Claude Code was started in for that session — not a fixed
"project root" in the git-repository sense, and not always the directory
containing the `.mcp.json` that declared the server.** [OBSERVED]

Across the six spawns, `CLAUDE_PROJECT_DIR` was byte-identical to
`os.getcwd()` as seen by the spawned server, and byte-identical to the
directory the host `claude` process was invoked from:

| Invocation cwd | Registration scope | Spawned server's `cwd` | Spawned server's `CLAUDE_PROJECT_DIR` |
|---|---|---|---|
| worktree root | project (`--mcp-config .mcp.json --strict-mcp-config`) | worktree root | worktree root |
| worktree root | local (`claude mcp add --scope local`) | worktree root | worktree root |
| worktree root | user (`claude mcp add --scope user`) | worktree root | worktree root |
| `/tmp` (no git repo present at all) | user | `/tmp` | `/tmp` |
| worktree root `/_rfc` subdirectory | user | `/_rfc` subdirectory | `/_rfc` subdirectory |
| worktree root `/_rfc` subdirectory | project (ambient `.mcp.json`, auto-discovered from the subdirectory) | `/_rfc` subdirectory | `/_rfc` subdirectory |

The `/tmp` case is the clearest evidence: there is no git repository, no
`.mcp.json`, and no project marker of any kind at `/tmp`, yet `CLAUDE_PROJECT_DIR`
was still set, to `/tmp` itself. The `_rfc`-subdirectory case shows the same
thing inside a real project: even though `.mcp.json` physically lives at the
worktree root, and Claude Code auto-discovered it from the subdirectory
(project-scope tool calls worked), the value delivered to the server was the
subdirectory, not the file's own directory. This matches Claude Code's own
description of the variable as "the session's primary working directory" that
"doesn't change when you add or remove working directories mid-session"
[DOCUMENTED] — it is fixed at session start to wherever `claude` was launched
from, independent of registration scope and independent of where the
declaring config file lives.

**[CAVEAT]** All spawns above were headless (`claude -p`) with a session
lifetime of one prompt. This says nothing about what happens if a long-running
interactive session changes its working directory mid-session (e.g. via `/cd`)
after the MCP server is already running — the documentation states
`CLAUDE_PROJECT_DIR` "doesn't change" in that case [DOCUMENTED], but that was
not independently observed here.

## 3. What working directory does the spawned server get?

**The same value as `CLAUDE_PROJECT_DIR` — the invocation directory — for all
three registration scopes, as observed here.** [OBSERVED] See the table above;
`cwd` and `CLAUDE_PROJECT_DIR` matched in every one of the six spawns,
including the user-scope ones, which never resolved to `~/.claude` or to
`CLAUDE_CONFIG_DIR`.

This appears to contradict a claim in the `config-resolution` topic that a
user-scoped server's working directory is the configuration directory
(`~/.claude`, or `CLAUDE_CONFIG_DIR`). Investigating the current Claude Code
MCP documentation resolves the discrepancy rather than confirming a
contradiction: the only place the documentation states a scope-dependent
working directory is a table titled **"Where the helper runs,"** which is
explicitly scoped to the `headersHelper` command — a separate, optional helper
process used to refresh HTTP headers/auth tokens — not to the stdio server's
own `command`/`args` process. [DOCUMENTED] Quoting the surrounding text
verbatim:

> "Claude Code picks the `headersHelper` command's working directory from the
> configuration that declares the server... Each row below gives the
> directory that a relative path in your `headersHelper` command resolves
> against."

That table does say user scope, managed MCP, and claude.ai connectors resolve
`headersHelper` against `~/.claude` (or `CLAUDE_CONFIG_DIR`), as of Claude Code
`2.1.238`+ — [DOCUMENTED], not tested here, since the probe server has no
`headersHelper`. But nowhere does current documentation state a working
directory for the actual stdio server process itself, and nothing there is
scope-dependent for it. The observation in the table above — that the actual
server process's cwd is the session's primary working directory regardless of
scope — is not documented anywhere and fills a real gap; it should be trusted
over the `config-resolution` topic's assumption, which appears to have
conflated the `headersHelper` table with the server process itself.

## 4. Other variables in the spawned server's environment

Full dump from one project-scope spawn (identical shape across scopes, modulo
the caveats in §1 above). Highlights, all [OBSERVED]:

| Variable | Value observed | Notes |
|---|---|---|
| `CLAUDECODE` | `1` | [DOCUMENTED] elsewhere as set in every subprocess Claude Code spawns; confirmed present here too |
| `CLAUDE_CODE_SESSION_ID` | a UUID, fresh per invocation | |
| `CLAUDE_CONFIG_DIR` | `/home/mike/.claude-profiles/alt` in this environment | Only set because this environment overrides it; absent by default, in which case a server that wants the config directory should default to `~/.claude` itself |
| `HOME` | the invoking user's real home directory, unmodified | Ordinary shape, nothing MCP-specific |
| `PATH` | inherited from the invoking shell, ~1300 chars, includes `~/.local/bin`, nvm's Node bin dir, VS Code / Cursor server helper paths | Not sanitised or minimised — the server sees the same `PATH` the launching shell had |
| `USER`, `SHELL`, `LANG`, `TERM` | ordinary shell-inherited values | |

**`CLAUDE_PROJECT_DIR` is absent from Claude Code's environment-variables
reference page** (`code.claude.com/docs/en/env-vars`) [DOCUMENTED] — confirmed
by fetching that page directly and searching it; it lists dozens of other
`CLAUDE_*`/`CLAUDE_CODE_*` variables but not this one. It is, however,
documented on the MCP page itself [DOCUMENTED]:

> "Claude Code sets `CLAUDE_PROJECT_DIR` in the spawned server's environment to
> the project root, so your server can resolve project-relative paths without
> depending on the working directory. This is the same directory hooks
> receive in their `CLAUDE_PROJECT_DIR` variable."

That description's use of "project root" should be read in light of §2 above:
in practice it means "the directory the session started in," which is only
the git/project root if that is where the user happened to launch `claude`.

## 5. `python-dotenv`'s `load_dotenv(path, override=False)`

**Behaves exactly as assumed: a real environment variable set before the call
wins over the same key in the file; a key present only in the file is still
loaded.** [OBSERVED]

Tested with `python-dotenv` `1.2.3` in a scratch virtualenv:

```python
import os
from dotenv import load_dotenv

os.environ["SHDOC_API_KEY"] = "from_real_env"  # simulates a value a client injected via .mcp.json's env block

# .env on disk contains:
#   SHDOC_API_KEY=from_file_value
#   SHDOC_DOC_ID=from_file_doc_id

load_dotenv(".env", override=False)

os.environ["SHDOC_API_KEY"]  # -> "from_real_env"   (real env var won)
os.environ["SHDOC_DOC_ID"]   # -> "from_file_doc_id" (only source was the file)
```

Output observed: `SHDOC_API_KEY` stayed `from_real_env`; `SHDOC_DOC_ID`, present
only in the file, was loaded as `from_file_doc_id`.

## Summary

| Question | Verdict | Basis |
|---|---|---|
| Is `CLAUDE_PROJECT_DIR` set for a spawned stdio server? | Yes, in every scope tested | [OBSERVED] |
| What value does it carry? | The directory Claude Code was launched from for that session (the "primary working directory"), not necessarily a git/project root and not necessarily the directory holding the declaring config file | [OBSERVED] |
| Working directory by scope | Same value as `CLAUDE_PROJECT_DIR` for the server process itself, uniformly across project/local/user scope, as tested here — the scope-dependent table in Claude Code's docs governs a separate `headersHelper` process, not the server's own `command` | [OBSERVED] for the server process; [DOCUMENTED] for the `headersHelper` distinction |
| Other useful variables | `CLAUDECODE=1`, a fresh `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CONFIG_DIR` (only if the launching environment set it), an inherited, unsanitised `PATH`/`HOME`/shell environment | [OBSERVED] |
| `load_dotenv(path, override=False)` precedence | Real env vars win; file-only keys still load | [OBSERVED] |

---

# Addendum — can a consumer project pin `CLAUDE_PROJECT_DIR` reliably?

**Tested against:** Claude Code CLI `2.1.259` (same binary as above).
**Date:** 2026-09-04.

§2 above established that `CLAUDE_PROJECT_DIR` is the directory Claude Code was
launched from, not a git root and not necessarily the directory holding the
declaring `.mcp.json`. That creates an operational hazard: a user who launches
`claude` from a subdirectory of their project gets the wrong `.env` path, or
none, with the first symptom being a confusing auth error several tool calls
later. This addendum tests every mechanism that could plausibly pin the value
independently of the launch directory, using the same probe-server method as
above (a minimal stdio server that dumps its own `os.environ`/`os.getcwd()`).
Same confidence markers as the rest of this file.

## A1. Is there a way to pin the project root independently of the launch directory?

**No usable mechanism was found, checked four ways.**

- **`--add-dir`:** does not affect `CLAUDE_PROJECT_DIR`. [OBSERVED] Launched
  from `/tmp` with `--add-dir <worktree-path>`, the spawned server still
  received `CLAUDE_PROJECT_DIR=/tmp` and `cwd=/tmp` — identical to a run with
  no `--add-dir` at all. `--add-dir` only grants file-tool access to the extra
  directory; it does not relabel the project root.
- **Presetting `CLAUDE_PROJECT_DIR` in the shell before launching `claude`:**
  overwritten, not respected. [OBSERVED] With
  `CLAUDE_PROJECT_DIR=/tmp/PRESET_VALUE_SHOULD_NOT_APPEAR claude -p ...` run
  from the worktree root, the spawned server received
  `CLAUDE_PROJECT_DIR=<worktree root>` — Claude Code recomputed the value from
  the launch directory and discarded the preset one entirely. This closes off
  the most obvious workaround cleanly: a project cannot tell its users "just
  export `CLAUDE_PROJECT_DIR` yourself."
- **`settings.json` (any scope) and the settings precedence/schema
  documentation:** no key was found. [DOCUMENTED — absence] Fetched
  `code.claude.com/docs/en/settings` and searched the full text for
  `projectDir`, `project_dir`, `rootDir`, and `workingDir` — zero matches. The
  only project-root-adjacent variable documented anywhere is
  `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR`, which controls whether the Bash
  tool snaps back to the project directory after a command — it doesn't
  influence what that directory *is*.
- **A `claude config` command:** does not exist in this CLI version.
  [OBSERVED] `claude --help`'s `Commands:` list is `agents, attach, auth,
  auto-mode, doctor, gateway, import, install, logs, mcp, plugin, project,
  respawn, rm, setup-token, stop, ultrareview, update` — no `config`. The
  `claude project` command exists but its only subcommand is `purge` (delete
  local state for a project); nothing sets or pins a root.

**Verdict: there is no supported way to make `CLAUDE_PROJECT_DIR` independent
of the directory `claude` was launched from.** The value is fixed for the
session at launch and nothing this project's setup instructions can tell a
user to configure will change that.

## A2. Does `.mcp.json` discovery walk up from the launch directory, and does `CLAUDE_PROJECT_DIR` walk up with it?

**Discovery walks up. `CLAUDE_PROJECT_DIR` does not. This is the crux
disagreement, and it is real.** [OBSERVED]

A project `.mcp.json` was placed at the worktree root. `claude mcp list`, run
from `_rfc/archive/implemented/` — two directories below the root — showed the
server as registered (pending approval), confirming discovery walks up rather
than looking only in the exact launch directory. A headless spawn
(`claude -p ... --allowedTools "mcp__env-probe2__noop"`, no `--mcp-config`,
relying purely on ambient discovery) from that same subdirectory then
successfully connected to and called the server — discovery isn't just
listing it, the server actually starts. Its dump showed:

```
cwd:                /home/mike/.../worktree/_rfc/archive/implemented
CLAUDE_PROJECT_DIR:  /home/mike/.../worktree/_rfc/archive/implemented
```

Both point at the **launch subdirectory**, not the worktree root two levels up
where `.mcp.json` actually lives. So the exact failure the operational hazard
describes is confirmed directly: a server can be found and started from a
subdirectory of the project, while simultaneously receiving a
`CLAUDE_PROJECT_DIR` that does not point at the project's `.env`. `./.env`
(candidate 4) would also miss in this scenario, since it resolves against the
same launch-directory `cwd`. There is no candidate in the `config-resolution`
topic's four-candidate list that resolves correctly here except an explicit
`--env-file` or `$SHDOC_ENV_FILE`.

## A3. Does `${CLAUDE_PROJECT_DIR}` expand inside `.mcp.json`'s `args`?

**No — it is passed through as the literal, unexpanded string.** [OBSERVED]

`.mcp.json` was configured with:

```json
"args": ["<probe.py>", "<dump-path>", "--env-file", "${CLAUDE_PROJECT_DIR}/.env"]
```

Tested twice — once spawned via `--mcp-config .mcp.json --strict-mcp-config`,
once via plain ambient discovery of the same file (the way a shipped project
would actually use it, with no CLI flags) — and in both cases the probe
server's dumped `argv` contained the four-element literal
`['<probe.py>', '<dump-path>', '--env-file', '${CLAUDE_PROJECT_DIR}/.env']`.
The placeholder was never substituted; the server would receive the literal
string `${CLAUDE_PROJECT_DIR}/.env` as its `--env-file` argument, which as a
path does not exist. A setup instruction of the form
`"args": ["--env-file", "${CLAUDE_PROJECT_DIR}/.env"]` therefore passes a
literal rather than a resolved path, and would
fail exactly the way the `config-resolution` topic's existing findings predict
for `${VAR}` expansion of other variables: this failure mode is specific
neither to Claude Desktop nor to secrets, it reproduces on the plain Claude
Code CLI for a value the client itself injects.

## A4. Does a `SessionStart` hook run early enough, and can it influence the spawned server's environment?

**A hook cannot influence the environment a spawned MCP server receives —
observed directly, not just inferred from OS process semantics — and hook
timing relative to MCP spawn is not a reliable "before" either.** [OBSERVED],
corroborated by [DOCUMENTED]

A `SessionStart` hook was configured (via a temporary
`.claude/settings.local.json`, removed afterward) to write a
high-resolution timestamp to a file and then `export MARKER_ENV=set_by_hook`
in its own shell. The probe MCP server's dump was checked for that variable:

```
hook fired_at (epoch):        1788469922.651169878
MCP server dumped_at (epoch): 1788469922.5626595      (~88ms earlier)
MARKER_ENV in server's environ: None
```

Two findings follow:

- **`export` inside a hook's shell process never reaches the MCP server's
  environment.** [OBSERVED] The hook and the MCP server are separate child
  processes of Claude Code; a shell `export` only affects that shell process
  and its own children, and is discarded when the hook process exits — this
  matches ordinary POSIX process semantics, and it was confirmed directly
  rather than assumed. There is also no documented JSON-output field a
  `SessionStart` hook can return that would inject or override an environment
  variable for a downstream MCP server — its available output fields are
  `hookSpecificOutput`, `systemMessage`, `terminalSequence`, and
  `additionalContext` [DOCUMENTED], none of which touch a spawned process's
  environment.
- **The MCP server's own startup was not strictly after the hook completed** —
  in this run it was about 88ms *before* the hook finished writing its file.
  [OBSERVED] This matches Claude Code's own documentation: "`SessionStart` and
  `Setup` typically fire before servers finish connecting, so hooks on those
  events should expect the 'not connected' error on first run" [DOCUMENTED] —
  i.e. the two are not sequenced the way "validate, then spawn" would need.

**Verdict: this option is closed.** Even setting aside the ordering problem, a
hook has no channel to influence the environment the MCP server actually
receives, so a `SessionStart` hook cannot be used to detect or correct a wrong
`CLAUDE_PROJECT_DIR` before the server reads its `.env`.

## Addendum summary

| Question | Verdict | Basis |
|---|---|---|
| Can `CLAUDE_PROJECT_DIR` be pinned independently of the launch directory? | No — not via `--add-dir`, a shell preset, `settings.json`, or any CLI command in this version | [OBSERVED] (`--add-dir`, shell preset) + [DOCUMENTED — absence] (`settings.json`, env-vars, CLI commands) |
| Does `.mcp.json` discovery walk up, and does `CLAUDE_PROJECT_DIR` walk up with it? | Discovery walks up; `CLAUDE_PROJECT_DIR` stays pinned to the launch directory — they disagree, exactly as feared | [OBSERVED] |
| Does `${CLAUDE_PROJECT_DIR}` expand in `.mcp.json`'s `args`? | No — passed through as a literal string, both via `--mcp-config` and plain ambient discovery | [OBSERVED] |
| Can a `SessionStart` hook fire early enough / influence the server's environment? | No — timing is not reliably "before," and there is no channel from a hook to a sibling process's environment | [OBSERVED] + [DOCUMENTED] |

## Which resolution candidates survive a subdirectory launch

Nothing tested here makes `CLAUDE_PROJECT_DIR` resolve to anything other than
the directory `claude` was launched from. Against the four-candidate `.env`
resolution order set by the `config-resolution` topic (see `_rfc/README.md`),
that sorts the candidates as follows.

**Candidates 1 (`--env-file <path>`) and 2 (`$SHDOC_ENV_FILE`)** are the only
two independent of the launch directory, and only when given an **absolute**
path. A literal absolute path needs no `${VAR}` expansion, so it is unaffected
by A3. Placed in the committed project-scope `.mcp.json`, such a path is
identical for every clone and machine; a local, gitignored location — a local-
or user-scope registration, or `.claude/settings.local.json` — keeps it
per-machine.

**Candidate 3 (`$CLAUDE_PROJECT_DIR/.env`)** resolves correctly only when
`claude` is launched from the directory holding the `.env`. A2 shows that
`.mcp.json` discovery walks up to the project root while `CLAUDE_PROJECT_DIR`
does not, so a subdirectory launch registers the server and then hands it the
wrong directory.

**Candidate 4 (`./.env`)** fails in the same scenario for the same reason:
both resolve against the launch `cwd`.

Two mechanisms that might be expected to close the gap do not.
`${CLAUDE_PROJECT_DIR}` is not expanded inside `.mcp.json`'s `args` (A3), and a
`SessionStart` hook can neither be relied on to run before MCP spawn nor
influence a sibling process's environment (A4).

Every failure mode above is silent until an authentication error several tool
calls later. The startup stderr line naming the resolved `.env` path, already
decided by the `config-resolution` topic, is what makes a violation observable.

Whether any of this changes the candidate order, or the framing of candidate 3
as the one that carries normal operation, is a decision for an RFC. This file
records what was observed and nothing more.
