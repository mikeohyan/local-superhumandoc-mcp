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

_(not yet run)_

## B5 — cold-cache vs warm-cache network dependency

_(not yet run)_

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

_(not yet run)_

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
