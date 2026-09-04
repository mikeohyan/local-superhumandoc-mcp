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

_(not yet run)_

## B2 — documented `pyproject.toml` builds a correct wheel

_(not yet run)_

## B3 — distribution/script name mismatch, exact error text

_(not yet run)_

## B4 — `uvx` from a pinned git tag

_(not yet run)_

## B5 — cold-cache vs warm-cache network dependency

_(not yet run)_

## B6 — dependency resolution, and absence of classic `httpx`

_(not yet run)_

## B7 — `requires-python` lower bound

_(not yet run)_

## B8 — stdio end-to-end through the console script

_(not yet run)_

## Claims to correct in the `packaging` topic

_(list each claim that the probes refuted or refined, with the probe that did
it. The RFC is still Proposed, so its body may be amended rather than
superseded — but that is a decision for an RFC-owning session, not for this
file.)_
