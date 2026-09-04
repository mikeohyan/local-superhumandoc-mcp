---
rfc: 0007
title: Package with hatchling and distribute via uvx from pinned git tags
status: Accepted
created: 2026-09-03
decided: 2026-09-04
supersedes:
superseded_by:
topic: packaging
commits: []
tags: [architecture, packaging, dependencies, python]
---

# RFC 0007 — Package with hatchling and distribute via `uvx` from pinned git tags

## Context

The single fact that shapes this decision is that **the official Python MCP SDK
went 2.x, and the entry point everyone knows no longer exists.**

`mcp` 2.0.0 shipped 2026-07-28; the current release is 2.1.1, 2026-08-25.
`mcp.server.fastmcp` is gone. The SDK ships a deliberate stub in its place that
raises `ModuleNotFoundError` with a message naming the renamed class and pointing
at the v2 migration guide — a stub that exists precisely because the maintainers
expected people to arrive with v1 code. Every tutorial, blog post, and
half-remembered snippet built on `from mcp.server.fastmcp import FastMCP` targets
v1 and will fail immediately against a current install.

The naming history is genuinely confusing and worth recording once, because a
future session will otherwise reconstruct it wrongly. FastMCP began as a
third-party project; its high-level API was contributed into the official SDK and
lived there as `mcp.server.fastmcp`; in `mcp` 2.x that class was renamed to
`MCPServer`. Meanwhile the original third-party `fastmcp` package continued
independently under PrefectHQ and is now at 4.x. So "FastMCP" today names two
different things — a class that was renamed inside the official SDK, and a
separate package with its own release line. Searching for it finds both,
undifferentiated.

There is a second dependency surprise. `mcp` 2.x depends on **`httpx2`**,
pydantic's next-generation HTTP client, not on classic `httpx`. A project that
adds `httpx` for its own REST calls therefore ends up carrying two HTTP stacks
without noticing.

The distribution problem is separate and comes from how this server is meant to
be used. It is not a service; it is a local process that several unrelated
project folders each run against their own document. Each project needs to pin
its own version, upgrade on its own schedule, and do so without a build step or a
vendored copy. RFC 0002, now superseded by RFC 0008, established the precedent
for this repository: an
external dependency gets pinned to an exact version, that version is recorded in
one place, and moving it is a deliberate act rather than a side effect. This RFC
applies the same discipline to the SDK and to the server's own releases.

Facts about package versions and `uvx` behaviour below were verified on
2026-09-03 against PyPI metadata, the SDK's own error message, and uv's
documentation — not from recollection, which for this particular subject is
actively unreliable.

## Decision

The server is a Python package built with **hatchling**, depending on the
**official `mcp>=2.1.1,<3`** SDK, and distributed by running **`uvx` against a
pinned git tag**. It is never installed globally and never vendored into a
project.

**SDK.** The server is built on the official SDK, imported as
`from mcp.server import MCPServer`. Transport parameters live on `run()`, not on
the constructor — another v2 change. The choice over the third-party `fastmcp`
4.x rests on four things: the official SDK is the reference implementation and
tracks the protocol specification directly; its decorator ergonomics are
identical, so nothing is given up for a server of this shape; it is one
dependency rather than a package plus its own ecosystem; and it ships a
first-class in-process test client, which is what makes the test strategy below
possible. `fastmcp` is the better choice for server composition and proxying,
pluggable auth providers, or its own deployment tooling. A stdio server scoped to
one document needs none of those.

**HTTP client.** Superhuman Docs calls go through `httpx2.AsyncClient`, which
arrives transitively with `mcp` 2.x. Because the code imports it directly rather
than relying on it as an implementation detail of the SDK, `httpx2` is also
declared explicitly in `dependencies`. Classic `httpx` is not a dependency of
this project.

**Build.** Hatchling with a `src/` layout. The distribution name and the
console-script name are both `superhumandoc-mcp`, and keeping them identical is
load-bearing rather than tidy: the final argument to `uvx` is the **script**
name, and a mismatch produces `An executable named X is not provided by package
Y`. The `[tool.hatch.build.targets.wheel] packages` line is stated explicitly
but is not, on current hatchling, required: with the line omitted, hatchling
1.32.0 auto-discovers `src/superhumandoc_mcp` from the normalized distribution
name and builds a correct wheel. It is kept because the auto-discovery holds
only while the package directory matches that normalized name, and because an
explicit line costs nothing and survives a rename that would otherwise fail
silently. Every claim in this section was executed rather than reasoned; the
raw output is at `docs/validation/2026-09-04-packaging-build-validation.md`.

```toml
[project]
name = "superhumandoc-mcp"
version = "0.1.0"
description = "MCP server for a single Superhuman Docs document."
requires-python = ">=3.11"
dependencies = [
    "mcp>=2.1.1,<3",
    "httpx2>=2.5.0",
    "python-dotenv>=1.0",
]

[project.scripts]
superhumandoc-mcp = "superhumandoc_mcp.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/superhumandoc_mcp"]
```

**Distribution.** A project runs the server as:

```
uvx --from git+https://github.com/USER/REPO@v0.1.0 superhumandoc-mcp
```

**Pin tags, never branches.** uv caches on the fully-resolved commit hash, so a
branch pin does not pick up new commits without `--refresh`. A branch pin is
therefore quietly stale rather than loudly wrong, which is the worse of the two
failure modes.

**Never move a published tag.** Cut a new one. The tag *is* the version record,
and the reason a project can state which server it runs.

First run needs network beyond the git clone: uv fetches the build backend and
the runtime dependencies from PyPI. Later runs are served from the uv cache. For
a private repository, authentication goes through a Git credential helper or SSH
rather than a token embedded in the URL, because the `.mcp.json` that carries the
command is committed.

**Errors.** Anticipated failures — an API 4xx, a missing page, a token without
the needed scope — are raised as `ToolError`, whose message reaches the model.
Any other exception is redacted by the SDK to `Error executing tool X` with a
server-side traceback. So API errors are wrapped and genuine bugs are left
unwrapped, which gives the model actionable text in the first case and reveals
nothing in the second. `ToolError` is importable only as `from
mcp.server.mcpserver.exceptions import ToolError` — it is not re-exported from
`mcp.server.mcpserver`, from `mcp.server`, or from the top-level `mcp`, and each
of the shorter spellings raises `ImportError`.

**Testing.** The tool layer is tested in-process with `mcp.Client(server)`, which
connects directly to an `MCPServer` instance with no subprocess; v1's
`create_connected_server_and_client_session` was removed in v2 and is not an
option. Tool failures are asserted on the returned `CallToolResult` — its
`is_error` and `content` — never on an exception propagating out of
`call_tool()`. `Client` does accept `raise_exceptions=True`, but the flag does
not re-raise exceptions raised by tool bodies: `Tool.run` converts every one of
them into a `CallToolResult` before the request reaches the dispatcher where the
flag is consulted, so it is indistinguishable from the default client for the
scenario a test suite actually exercises. A test that needs an exception to
surface in Python must call `MCPServer.call_tool()` directly rather than going
through `Client`. Verified against `mcp` 2.1.1; the evidence, including the
SDK's own unresolved maintainer TODO on when that flag fires, is at
`docs/reference/mcp-sdk-v2-api-surface.md`. The REST layer is tested against a
mocked `httpx2` transport, and that is where the interesting behaviour lives —
mutation polling, backoff, error translation, value post-processing, metadata
caching — none of which needs an MCP client in the loop.

**Tool registration** happens inside a server factory, so registration can be
guarded by configuration read at build time, before `run()`. The destructive-tool
gating in RFC 0005 depends on this and on nothing dynamic at request time.

Note for anyone reading v2 code against v1 memory: the SDK's attributes are
snake_case now — `input_schema`, `output_schema`, `is_error`,
`structured_content`. The wire format is unchanged.

## Alternatives considered

### Pin `mcp<2` and keep the v1 `FastMCP` API

The path of least resistance, and the one every existing tutorial leads to. It
would work today. Rejected because it starts a new project on a superseded major
version whose replacement already shipped, which converts a one-time migration
into a debt that grows with every tool written against the old API. The v1 branch
is in maintenance; nothing about this project needs it.

### Use the third-party `fastmcp` 4.x

An actively developed package with a larger feature surface than the official
SDK — composition, proxying, auth providers, deployment tooling. Rejected because
none of those features applies to a stdio server scoped to a single document, and
adopting it means tracking a second project's release cadence and its divergence
from the protocol specification. The official SDK's in-process test client also
directly shapes the test strategy above. This is a preference, not a judgement
about quality: if the server later needs composition or hosted transports,
revisiting it would be reasonable and would be its own RFC.

### `uv tool install` globally

Install once, and let every project invoke the same binary. Simpler `.mcp.json`,
and no per-run resolution. Rejected because it gives every project on the machine
one shared version, so upgrading for one project silently upgrades all of them —
which defeats the point of pinning and makes a regression hard to attribute.

### Vendor the server into each project

Copy the source, or add it as a submodule, and run it with `uv run`. Fully
self-contained, hackable in place, and immune to a deleted upstream. Rejected
because copies drift: a fix made in one project's copy does not reach the others,
and after a few months no two projects are running the same server. It also makes
the version question unanswerable, since a copy has no version.

### Publish to PyPI

`uvx superhumandoc-mcp==0.2.0` is the cleanest invocation of all, and the right
answer if anyone outside this machine ever uses the server. Rejected for now as
premature: it adds release mechanics and a public package to maintain in exchange
for a shorter command. A git tag already provides an immutable, pinnable
reference. Publishing becomes worth revisiting when there is a second user, and
would be its own RFC.

## Consequences

**Makes easy.** A project pins a version by editing one string in `.mcp.json`,
and upgrading is a tag bump reviewable in a diff. Nothing is installed, so
removing the server means deleting a config stanza. The test strategy needs no
subprocess, no fixture server, and no network, so the behaviour that actually
matters can be tested fast.

**Makes hard.** Shipping a fix requires cutting a release and updating each
project that pins the old tag — there is no way to patch a running install in
place. First run in a cold cache is slow and needs network. And because
`.mcp.json` carries a full git URL, moving or renaming the repository breaks
every project that references it.

**Commits us to.** The official SDK's 2.x API, including `MCPServer`, its
`ToolError` convention, and its snake_case attribute names — a `fastmcp` port
later would touch every tool definition. Also to tags as immutable release
markers, which is a discipline nothing enforces mechanically.

**Worth stating plainly, because it will mislead people.** `mcp` 2.x is weeks old
at the time of writing. The overwhelming majority of MCP tutorials, example
repositories, Stack Overflow answers, and language-model training data describe
v1 and the `mcp.server.fastmcp` import. A future session working on this project
will very likely *recall* the v1 API confidently and write code that cannot
import. That is a principal reason this RFC exists and states the import
explicitly: the correct answer here is not recoverable from memory or from a
casual search, only from the SDK itself.

**Unverified.** Whether uv re-resolves a *moved* git tag against a real remote is
not established. A local `file://` remote did re-resolve in testing, which does
not generalise to GitHub over HTTPS, and uv's documented policy is hash-based
caching. The never-move-a-tag rule above is therefore stated as a rule rather
than a preference: it is correct under either behaviour, and relying on the
uncertain one would be a silent failure. `uvx --refresh --from git+...` forces
revalidation if the situation ever arises.

## Implementation notes

Left empty at Proposed.
