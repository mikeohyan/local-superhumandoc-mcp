# Packaging and distribution — build validation plan

**Date:** 2026-09-04
**Target:** the build and distribution claims made by the `packaging` topic (see `_rfc/README.md`)
**Status:** NOT YET RUN — see the empty Results section at the bottom.

## What this plan settles

The `packaging` topic's SDK claims were verified against a real installed
`mcp==2.1.1` and are recorded in `docs/reference/mcp-sdk-v2-api-surface.md`. Its
*build and distribution* claims were not: no `pyproject.toml` was ever created,
so every assertion about hatchling, wheel contents, console-script naming and
`uvx` is reasoned rather than executed.

This plan executes them. Each probe below quotes the claim it tests, so a
failure is unambiguous.

## Before you run this

- Requires `uv` and network access to PyPI. No Superhuman Docs token, and no
  API calls — nothing here touches the vendor's API or any rate-limit bucket.
- Everything happens in a scratch directory. **Nothing in this plan writes to
  the repository's own `pyproject.toml`** — creating that is the `packaging`
  topic's shipping work, not this plan's.
- The git remote used in B4/B5 is a local `file://` clone. That is deliberate
  and its limits are stated in B4.
- Takes roughly 10 minutes, dominated by cold-cache dependency resolution.

## Setup

```bash
mkdir -p ~/pkg-spike && cd ~/pkg-spike
uv --version
python3 --version
```

The scratch package under test, unless a probe says otherwise:

```
sdmcp/
  pyproject.toml
  src/superhumandoc_mcp/
    __init__.py
    __main__.py          # def main(): starts an MCPServer over stdio
```

---

# Test plan

## B1. Does a `src/` layout without the `packages` line build an empty wheel?

**Claim:** "The `[tool.hatch.build.targets.wheel] packages` line is required with
a `src/` layout — without it hatchling cannot locate the package and builds an
empty wheel."

Build with the line omitted. Record whether the build **succeeds silently**, and
list the wheel's contents:

```bash
uv build --wheel
unzip -l dist/*.whl
```

The interesting outcome is not "does it fail" but *how* it fails. A hard error
is a materially different (and better) failure than a silently empty wheel, and
the claim asserts the latter. Record which it is, verbatim.

## B2. Does the documented `pyproject.toml` build a correct wheel?

Restore the `packages = ["src/superhumandoc_mcp"]` line and rebuild. Confirm the
wheel contains `superhumandoc_mcp/__init__.py` and `__main__.py`, and that its
metadata carries `Requires-Dist` entries for `mcp` and `httpx2`.

## B3. Does a name mismatch produce the documented error?

**Claim:** the distribution name and console-script name must be identical,
because "the final argument to `uvx` is the **script** name, and a mismatch
produces `An executable named X is not provided by package Y`."

Rename the console script to something different from the distribution name,
install, and invoke `uvx` with the distribution name. Capture the **exact**
error text and compare it to the claim word for word.

## B4. Does `uvx` run the package from a pinned git tag?

Initialise a git repository over the scratch package, commit, tag `v0.1.0`, and
run it through a local `file://` remote:

```bash
uvx --from "git+file://$PWD/sdmcp@v0.1.0" superhumandoc-mcp --help
```

**Stated limit:** a local `file://` remote does not generalise to GitHub over
HTTPS. This probe establishes that the *invocation form* works and that the
script resolves — not uv's caching behaviour against a real remote, which the
`packaging` topic already records as unverified and handles with a
never-move-a-tag rule that is correct either way. Do not attempt to settle the
moved-tag question here; it would require pushing and moving a tag on a real
remote.

## B5. Is the first run's network dependency as described?

**Claim:** "First run needs network beyond the git clone: uv fetches the build
backend and the runtime dependencies from PyPI. Later runs are served from the
uv cache."

Run B4's command with a cold cache and time it, then again warm. If uv offers a
supported offline or no-network mode, use it to demonstrate the second run needs
no network; if it does not, say so rather than inferring from timing alone.

## B6. Does the dependency set resolve as specified?

Confirm `mcp>=2.1.1,<3`, `httpx2>=2.5.0` and `python-dotenv>=1.0` resolve
together. Record the exact resolved versions. Then confirm **classic `httpx` is
absent** from the resolved environment — the `packaging` topic states it is not
a dependency of this project.

## B7. Does `requires-python = ">=3.11"` hold?

Record the interpreter the environment resolves to. If a 3.10 interpreter is
available, confirm uv refuses it; if not, record that the lower bound was not
exercised rather than assuming it works.

## B8. Does the built server actually serve over stdio?

Every test of the tool layer in the `packaging` topic is in-process via
`mcp.Client(server)`. That is not the transport a client uses. Start the
installed console script as a real subprocess, connect an MCP client over
stdio, and call `list_tools`. This is the one probe that exercises the console
script, the entry point, `run()`'s transport arguments and the wheel together.

Record whether transport parameters are passed to `run()` rather than the
constructor, as the `packaging` topic states.

---

# Results

## B1 — `src/` layout without the `packages` line

**Result: contradicts the claim.** The claim is that omitting
`[tool.hatch.build.targets.wheel] packages` yields "a silently empty wheel."
That is not what happened. With the `packages` line omitted entirely from an
otherwise-documented `pyproject.toml` (`src/superhumandoc_mcp/{__init__.py,
__main__.py}`), `uv build --wheel` (which resolved hatchling 1.32.0 as the
build backend) succeeded and produced a wheel containing the actual package
files — not an empty one, and not a build error. Verbatim:

```
$ uv build --wheel
Building wheel...
Successfully built dist/superhumandoc_mcp-0.1.0-py3-none-any.whl
```

```
$ unzip -l dist/superhumandoc_mcp-0.1.0-py3-none-any.whl
Archive:  dist/superhumandoc_mcp-0.1.0-py3-none-any.whl
  Length      Date    Time    Name
---------  ---------- -----   ----
        0  2020-02-02 00:00   superhumandoc_mcp/__init__.py
      135  2020-02-02 00:00   superhumandoc_mcp/__main__.py
      236  2020-02-02 00:00   superhumandoc_mcp-0.1.0.dist-info/METADATA
       87  2020-02-02 00:00   superhumandoc_mcp-0.1.0.dist-info/WHEEL
       70  2020-02-02 00:00   superhumandoc_mcp-0.1.0.dist-info/entry_points.txt
      508  2020-02-02 00:00   superhumandoc_mcp-0.1.0.dist-info/RECORD
---------                     -------
     1036                     6 files
```

Reproduced on a clean rebuild (`rm -rf dist build`, rebuild) with byte-identical
wheel contents, so this is not a one-off. Evidently hatchling 1.32.0
auto-discovers the `src/<normalized-project-name>` directory
(`superhumandoc-mcp` → `superhumandoc_mcp`) when no explicit `packages` list is
given, and packages it correctly. Neither of the two failure modes the claim
considers (silent empty wheel, or a hard error) occurred; the actual outcome is
a third one — a correct build with the line absent.

## B2 — documented `pyproject.toml` builds a correct wheel

Restored `[tool.hatch.build.targets.wheel] packages = ["src/superhumandoc_mcp"]`
and rebuilt from a clean `dist/` (`rm -rf dist build`, rebuild). The wheel's
contents were identical to B1's — `superhumandoc_mcp/__init__.py` and
`superhumandoc_mcp/__main__.py` both present — and its metadata carries the
claimed `Requires-Dist` entries, verbatim from `unzip -p
dist/superhumandoc_mcp-0.1.0-py3-none-any.whl
superhumandoc_mcp-0.1.0.dist-info/METADATA`:

```
Metadata-Version: 2.5
Name: superhumandoc-mcp
Version: 0.1.0
Summary: MCP server for a single Superhuman Docs document.
Requires-Python: >=3.11
Requires-Dist: httpx2>=2.5.0
Requires-Dist: mcp<3,>=2.1.1
Requires-Dist: python-dotenv>=1.0
```

Confirmed: the documented `pyproject.toml`, with the `packages` line present,
builds a correct wheel carrying `Requires-Dist` entries for `mcp` and
`httpx2`. Given B1, this establishes only that the documented form works — not
that it is the only form that works.

## B3 — distribution/script name mismatch, exact error text

Built a second scratch copy with `[project.scripts]` changed to
`sdmcp-run = "superhumandoc_mcp.__main__:main"` (distribution name left as
`superhumandoc-mcp`), then ran `uvx` against the distribution name (the now-
mismatched script name):

```
$ uvx --from /tmp/.../pkg-spike/mismatch superhumandoc-mcp
```

Exact output, character for character:

```
   Building superhumandoc-mcp @ file:///tmp/claude-1002/-home-mike-code-mike-local-superhumandoc-mcp/df6e3a93-5218-4bc7-b426-59cde866fc6e/scratchpad/pkg-spike/mismatch
      Built superhumandoc-mcp @ file:///tmp/claude-1002/-home-mike-code-mike-local-superhumandoc-mcp/df6e3a93-5218-4bc7-b426-59cde866fc6e/scratchpad/pkg-spike/mismatch
Installed 30 packages in 5ms
An executable named `superhumandoc-mcp` is not provided by package `superhumandoc-mcp`.
The following executables are available:
- sdmcp-run

Use `uvx --from superhumandoc-mcp sdmcp-run` instead.
```

Confirmed, word for word against the claim's shape: "An executable named `X`
is not provided by package `Y`" — here X and Y are both `superhumandoc-mcp`
since the *distribution* name is what was passed to `uvx` and also names the
package; the mismatch is between that name and the actual script name
(`sdmcp-run`). uv additionally lists the available executables and suggests
the corrected invocation, which the claim does not mention but does not
contradict either.

## B4 — `uvx` from a pinned git tag

**Confirmed.** Scratch package built outside the repository (`~/pkg-spike/sdmcp`,
matching the `pyproject.toml` in the `packaging` topic's Decision section
verbatim, plus a minimal `src/superhumandoc_mcp/__main__.py` exposing `main()`
that builds an `MCPServer` with one tool and calls `server.run("stdio")`),
committed to a fresh local git repo, tagged `v0.1.0`:

```
$ git -C ~/pkg-spike/sdmcp log --oneline
1759d1c scratch package for packaging spike
$ git -C ~/pkg-spike/sdmcp tag
v0.1.0
```

Ran the documented invocation form against a `file://` remote pointing at that
repo, exactly as the `packaging` topic's Distribution section shows (substituting
the local remote for `git+https://github.com/USER/REPO`):

```
$ uvx --from "git+file:///home/mike/pkg-spike/sdmcp@v0.1.0" superhumandoc-mcp --help </dev/null
   Updating file:///home/mike/pkg-spike/sdmcp (v0.1.0)
    Updated file:///home/mike/pkg-spike/sdmcp (1759d1c5ad7f599a15ff2ed27a484a2b3aebe285)
   Building superhumandoc-mcp @ git+file:///home/mike/pkg-spike/sdmcp@1759d1c5ad7f599a15ff2ed27a484a2b3aebe285
      Built superhumandoc-mcp @ git+file:///home/mike/pkg-spike/sdmcp@1759d1c5ad7f599a15ff2ed27a484a2b3aebe285
Installed 30 packages in 4ms
EXIT: 0
```

The invocation form works: `uvx` resolves the tag to a commit, builds the
package from the git checkout, installs it and its dependency closure (30
packages), and finds and runs the `superhumandoc-mcp` console script — the
exact script name declared in `[project.scripts]`. The process exited 0
quickly because `main()` calls `server.run("stdio")` with stdin closed
(`</dev/null`), so the server reads EOF immediately and stops; `--help` is not
implemented by this minimal spike server and was ignored, which is expected
and unrelated to the claim under test.

**Per the stated limit, this only establishes that the invocation form works
and the script resolves against a pinned tag.** No attempt was made to move
the tag or to test against a real HTTPS remote — that remains unverified, as
the `packaging` topic's Consequences section already states, and the
never-move-a-tag rule is untouched by this probe.

Full end-to-end serving of this same console script over a *real stdio
subprocess* (not just a fast-exiting smoke invocation) is exercised in B8
below, which drives it with an actual MCP client and confirms `list_tools`
and `call_tool` both work.

## B5 — cold-cache vs warm-cache network dependency

**Confirmed, with the definitive test rather than timing alone.** `uv` (0.11.6)
has a supported offline mode, `--offline` (env `UV_OFFLINE`; uv's own help
text: "Disable network access"), so that was used instead of relying on
timing as the primary evidence.

**Cold cache, offline — fails, as predicted.** After `uv cache clean` (removed
the entire `~/.cache/uv`, 6.2GiB):

```
$ uvx --offline --from "git+file:///home/mike/pkg-spike/sdmcp@v0.1.0" superhumandoc-mcp --help </dev/null
   Updating file:///home/mike/pkg-spike/sdmcp (v0.1.0)
    Updated file:///home/mike/pkg-spike/sdmcp (1759d1c5ad7f599a15ff2ed27a484a2b3aebe285)
  × No solution found when resolving tool dependencies:
  ╰─▶ Because mcp was not found in the cache and superhumandoc-mcp==0.1.0
      depends on mcp>=2.1.1,<3, we can conclude that superhumandoc-mcp==0.1.0
      cannot be used.
      ...
      hint: Packages were unavailable because the network was disabled. When
      the network is disabled, registry packages may only be read from the
      cache.
EXIT: 1
```

Note the local `file://` git clone step itself (`Updating`/`Updated`) still
succeeds under `--offline` — it's a local filesystem read, not a network
fetch, so it's outside what the claim means by "network." The failure is
specifically in resolving `mcp` and its dependency closure from PyPI, exactly
where the claim says the network dependency lives.

**Cold cache, online — succeeds, and visibly fetches from PyPI.** Cache
cleared again, then run without `--offline`:

```
$ uvx --from "git+file:///home/mike/pkg-spike/sdmcp@v0.1.0" superhumandoc-mcp --help </dev/null
   Updating file:///home/mike/pkg-spike/sdmcp (v0.1.0)
    Updated file:///home/mike/pkg-spike/sdmcp (1759d1c5ad7f599a15ff2ed27a484a2b3aebe285)
   Building superhumandoc-mcp @ git+file:///home/mike/pkg-spike/sdmcp@1759d1c5ad7f599a15ff2ed27a484a2b3aebe285
Downloading cryptography (4.5MiB)
Downloading pydantic-core (2.0MiB)
 Downloaded pydantic-core
 Downloaded cryptography
      Built superhumandoc-mcp @ git+file:///home/mike/pkg-spike/sdmcp@1759d1c5ad7f599a15ff2ed27a484a2b3aebe285
Installed 30 packages in 5ms
EXIT: 0
```
Elapsed: ~1.23s (`date +%s.%N` before/after).

The build backend (hatchling) is fetched too, just without its own progress
line — confirmed by finding `hatchling-1.32.0` populated in
`~/.cache/uv/archive-v0/.../hatchling` and `~/.cache/uv/wheels-v6/pypi/hatchling`
after this run, on a cache that had just been fully cleared. So "uv fetches
the build backend and the runtime dependencies from PyPI" holds for both
halves of the claim; only the runtime-dependency fetches (`cryptography`,
`pydantic-core`) were large enough to print a `Downloading` line.

**Warm cache — succeeds under `--offline`.** Immediately re-running the same
command with the now-populated cache and `--offline` added:

```
$ uvx --offline --from "git+file:///home/mike/pkg-spike/sdmcp@v0.1.0" superhumandoc-mcp --help </dev/null
   Updating file:///home/mike/pkg-spike/sdmcp (v0.1.0)
    Updated file:///home/mike/pkg-spike/sdmcp (1759d1c5ad7f599a15ff2ed27a484a2b3aebe285)
EXIT: 0
```

This is the definitive result: a warm run completes successfully with network
access disabled outright, not merely fast. (A plain warm, non-offline timing
run was also taken for reference — ~0.43s vs ~1.23s cold — but per the plan's
instruction that timing alone is weak evidence, the `--offline` success above,
not the timing gap, is what this result rests on.)

**Verdict: confirmed.** First run needs network to fetch the build backend and
runtime dependencies from PyPI (demonstrated by an offline cold run failing
with an explicit "network was disabled" hint); a subsequent run against a warm
cache needs no network at all (demonstrated by an offline warm run succeeding
outright, not inferred from being merely faster).

## B6 — dependency resolution, and absence of classic `httpx`

`uv lock` against the documented dependency set (`mcp>=2.1.1,<3`,
`httpx2>=2.5.0`, `python-dotenv>=1.0`) resolved successfully: "Resolved 32
packages in 16ms". Exact resolved versions, read from the generated
`uv.lock`:

- `mcp` 2.1.1
- `httpx2` 2.12.0
- `python-dotenv` 1.2.3

`grep '^name = "httpx' uv.lock` returns exactly two matches — `httpx2` and
`httpx2-jsfetch` — and zero matches for a package named exactly `httpx`.
Classic `httpx` is confirmed absent from the resolved dependency set, matching
the claim.

## B7 — `requires-python` lower bound

The environment's default interpreter resolution (`uv venv` / `uv lock`, no
explicit `--python`) picked **CPython 3.13.13**, a uv-managed interpreter at
`~/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13` — not
the system Python, which is 3.11.2 at `/usr/bin/python3.11`. Both satisfy
`>=3.11`; uv's default selection preferred the newest compatible interpreter
it knew about over the system one.

A 3.10 interpreter was not installed locally, but `uv python list` showed one
available for uv to fetch (`cpython-3.10.20-linux-x86_64-gnu ... <download
available>`), so the lower bound was exercised rather than left untested.
Forcing it:

```
$ uv run --python 3.10 python -c "print('hello')"
Downloading cpython-3.10.20-linux-x86_64-gnu (download) (28.4MiB)
 Downloaded cpython-3.10.20-linux-x86_64-gnu (download)
Using CPython 3.10.20
error: The requested interpreter resolved to Python 3.10.20, which is incompatible with the project's Python requirement: `>=3.11` (from `project.requires-python`)
```

Confirmed: `requires-python = ">=3.11"` is enforced by uv — a 3.10 interpreter
is downloaded (since it was requested explicitly) but then refused with a
clear, specific error rather than silently accepted.

## B8 — stdio end-to-end through the console script

**Confirmed: the console script does serve MCP over a real stdio subprocess,
and `run()` is invoked with the transport as its argument, not on the
constructor.**

`docs/reference/mcp-sdk-v2-api-surface.md` only covers the in-process
`mcp.Client(server)` path. The stdio *client* transport used here is not
recorded anywhere in this repository before this probe, so it was located by
inspecting the installed `mcp==2.1.1` package directly
(`inspect.signature`, in a disposable `uv init` throwaway project):

- `mcp.client.stdio.StdioServerParameters(*, command: str, args: list[str] = [], env=None, cwd=None, ...)`
- `mcp.client.stdio.stdio_client(server: StdioServerParameters, errlog=...) -> AsyncGenerator[(read_stream, write_stream)]`
- `mcp.client.session.ClientSession(read_stream, write_stream, ...)` (also
  exported as top-level `mcp.ClientSession`), with `initialize()`,
  `list_tools()`, `call_tool(name, arguments)`.

Scratch server (`~/pkg-spike/sdmcp/src/superhumandoc_mcp/__main__.py`):

```python
from mcp.server import MCPServer


def build_server() -> MCPServer:
    server = MCPServer("spike-server")

    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b

    return server


def main() -> None:
    server = build_server()
    server.run("stdio")
```

`main()` calls `server.run("stdio")` — the transport is passed as `run()`'s
argument, exactly as `MCPServer.run`'s confirmed signature in
`docs/reference/mcp-sdk-v2-api-surface.md`
(`(self, transport: Literal['stdio', 'sse', 'streamable-http'] = 'stdio', **kwargs)`)
requires; there is no transport parameter on `MCPServer.__init__` for it to
have gone on instead.

Client script, run from a separate throwaway project with `mcp` installed,
driving the **actual console script** through the **actual `uvx` invocation
form** (a local path rather than a tag, since this probe's target is the
serving mechanism, not tag resolution — that is B4's target) as a real child
process, over real stdio pipes, with no in-process shortcut:

```python
import asyncio
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession

async def main() -> None:
    params = StdioServerParameters(
        command="uvx",
        args=["--from", "/home/mike/pkg-spike/sdmcp", "superhumandoc-mcp"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            print("INITIALIZED:", init_result.server_info)
            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            result = await session.call_tool("add", {"a": 4, "b": 5})
            print("IS_ERROR:", result.is_error)
            print("CONTENT:", result.content)
            print("STRUCTURED:", result.structured_content)

asyncio.run(main())
```

Output (stdout/stderr captured separately; stderr was empty):

```
INITIALIZED: name='spike-server' title=None version='' description=None website_url=None icons=None
TOOLS: ['add']
IS_ERROR: False
CONTENT: [TextContent(type='text', text='9', annotations=None, meta=None)]
STRUCTURED: {'result': 9}
```
Exit code 0. No stray subprocess remained afterward (`pgrep -fa superhumandoc-mcp` / `pgrep -fa "uvx.*sdmcp"` both empty).

**This is a real subprocess, not the in-process client**: `uvx` was invoked as
`command="uvx"` via `StdioServerParameters`, which `stdio_client` spawns as a
genuine child process (`mcp.client.stdio` uses `anyio`'s process/`Process`
machinery, not an in-memory transport — contrast with
`mcp/client/_memory.py`'s `InMemoryTransport`, which is what backs
`mcp.Client(server)` per `docs/reference/mcp-sdk-v2-api-surface.md` §6). `uvx`
itself then re-resolves and runs the installed `superhumandoc-mcp` console
script from the built wheel as a grandchild process communicating over its
own stdio, which is what `ClientSession` actually spoke MCP JSON-RPC to.
`initialize()`, `list_tools()`, and `call_tool()` all completed correctly
against it: the server's declared name reached the client via `initialize()`,
the one registered tool was listed, and calling it returned the correct
result via both `content` (`"9"` as text) and `structured_content`
(`{'result': 9}`), with `is_error=False` for a successful call — mirroring the
success-path assertions already made in-process in
`docs/reference/mcp-sdk-v2-api-surface.md` §6, but now over the real
transport a client actually uses.

**Verdict: confirmed on both counts asked by the plan.** The built,
`uvx`-invoked console script does serve MCP over a genuine stdio subprocess,
and transport selection happens at `server.run("stdio")` — a `run()`-time
argument — never on `MCPServer()`'s constructor.

## Claims to correct in the `packaging` topic

_(list each claim that the probes refuted or refined, with the probe that did
it. The RFC is still Proposed, so its body may be amended rather than
superseded — but that is a decision for an RFC-owning session, not for this
file.)_

- **B1 refutes the packaging topic's claim that omitting
  `[tool.hatch.build.targets.wheel] packages` under a `src/` layout "builds an
  empty wheel."** Observed instead: with hatchling 1.32.0 (the version `uv
  build` resolved), omitting that line built a complete, correct wheel — the
  build backend auto-discovered `src/superhumandoc_mcp` from the normalized
  project name and packaged it without error or omission. Neither predicted
  failure mode (silent empty wheel, or a hard build error) occurred.
