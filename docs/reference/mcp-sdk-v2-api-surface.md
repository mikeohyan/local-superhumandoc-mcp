# Official Python MCP SDK (`mcp` 2.x) — verified API surface

**Date:** 2026-09-03
**Tested against:** `mcp==2.1.1`, `httpx2==2.12.0`, Python 3.11.2, resolved fresh
by `uv add mcp` into a throwaway project (no other constraints), so these are
the actual latest-compatible releases on that date.
**Method:** a disposable `uv` project; `importlib.metadata`, `inspect.signature`,
reading the installed source under `.venv/lib/`, and a real in-process
end-to-end smoke test (server construction, tool registration, in-process
client, tool calls, both error paths). Web sources (PyPI's JSON API) were used
only for release dates and to confirm "latest," never for API shape.

This file records **what is true** of the installed package. It supersedes
recollection and casual search for this subject, which the `packaging` topic
(see `_rfc/README.md`) documents as actively unreliable for `mcp` 2.x. Nothing
here is a decision — decisions built on these facts live in the RFC.

## How to read the confidence markers

Following the convention in `docs/reference/api-operational-constants.md`:

| Marker | Meaning |
|---|---|
| **[PACKAGE-VERIFIED]** | Read directly from the installed `mcp`/`httpx2` source, `importlib.metadata`, or `inspect.signature` against `mcp==2.1.1` |
| **[SMOKE-TESTED]** | Exercised end-to-end via a real running server + in-process client in this spike; script is reproducible, see below |
| **[WEB-VERIFIED]** | Confirmed against PyPI's JSON API (`https://pypi.org/pypi/<pkg>/json`), used only for release identity/dates |

---

## 1. Package versions

**[WEB-VERIFIED] + [PACKAGE-VERIFIED].** PyPI's JSON API for `mcp` (queried
2026-09-03) reports `info.version: "2.1.1"` — i.e. **2.1.1 is the latest
release today**, matching what `uv add mcp` resolved with no version
constraint. Full 2.x release history from the same query:

| Version | Uploaded |
|---|---|
| 2.0.0 | 2026-07-28T13:45:28Z |
| 2.0.0a1–rc1 | 2026-06-11 – 2026-07-27 (prereleases) |
| 2.0.1 | 2026-08-26T10:48:35Z |
| 2.1.0 | 2026-08-24T19:04:29Z |
| 2.1.1 | 2026-08-25T16:13:59Z |

`2.0.0` on 2026-07-28 and `2.1.1` on 2026-08-25 match the packaging topic's
Context section exactly. (Note the out-of-order patch: `2.0.1` was uploaded
*after* `2.1.0`/`2.1.1` — a real oddity in the SDK's own release history, not
a data error here.)

`httpx2` latest is `2.12.0`, uploaded 2026-08-18T13:22:06Z [WEB-VERIFIED];
the same version resolved transitively by `uv add mcp` [PACKAGE-VERIFIED].

## 2. `mcp.server.fastmcp` is a deliberate stub

**[PACKAGE-VERIFIED].** The module exists on disk
(`mcp/server/fastmcp.py`) but its entire body is:

```python
_MESSAGE = (
    "No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer "
    "(from mcp.server.mcpserver import MCPServer) and other APIs changed; see the migration guide at "
    "https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver "
    "or pin 'mcp<2' to keep running v1 code."
)

raise ModuleNotFoundError(_MESSAGE, name=__name__)
```

Importing `from mcp.server.fastmcp import FastMCP` raises `ModuleNotFoundError`
with that exact message. Captured verbatim from a real import attempt:

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and other APIs changed; see the migration guide at https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver or pin 'mcp<2' to keep running v1 code.
```

The module's own docstring states why it exists: "the bare 'No module named
`mcp.server.fastmcp`' gave v1 code no hint that the installed SDK is a
different major version."

## 3. The renamed class: two working import paths

**[PACKAGE-VERIFIED].** The class lives at `mcp.server.mcpserver.server.MCPServer`.
Two shorter paths both resolve to the identical class object:

```python
from mcp.server import MCPServer            # mcp/server/__init__.py re-exports it
from mcp.server.mcpserver import MCPServer  # the stub message's own recommendation
```

Verified identical: `MCPServer is MCPServer` across both imports evaluates
`True`; `MCPServer.__module__ == "mcp.server.mcpserver.server"` either way.

`mcp/server/__init__.py`, in full:

```python
from .caching import CacheHint
from .context import ServerRequestContext
from .lowlevel import NotificationOptions, Server
from .mcpserver import MCPServer
from .models import InitializationOptions

__all__ = ["CacheHint", "Server", "ServerRequestContext", "MCPServer", "NotificationOptions", "InitializationOptions"]
```

Note the stub's own migration message recommends `from mcp.server.mcpserver
import MCPServer`, not the shorter `from mcp.server import MCPServer` — both
work, but code following the stub's advice will land on the longer path.

## 4. Constructor and `run()` — transport lives on `run()`, verbatim signatures

**[PACKAGE-VERIFIED]**, via `inspect.signature(MCPServer.__init__)` and
`inspect.signature(MCPServer.run)` against `mcp==2.1.1`.

`MCPServer.__init__` — no transport-related parameter anywhere in it:

```
(self, name: 'str | None' = None, title: 'str | None' = None, description: 'str | None' = None,
 instructions: 'str | None' = None, website_url: 'str | None' = None, icons: 'list[Icon] | None' = None,
 version: 'str' = '', auth_server_provider: 'OAuthAuthorizationServerProvider[Any, Any, Any] | None' = None,
 token_verifier: 'TokenVerifier | None' = None, *, tools: 'list[Tool] | None' = None,
 resources: 'list[Resource] | None' = None, extensions: 'Sequence[Extension] | None' = None,
 debug: 'bool' = False, log_level: "Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']" = 'INFO',
 warn_on_duplicate_resources: 'bool' = True, warn_on_duplicate_tools: 'bool' = True,
 warn_on_duplicate_prompts: 'bool' = True, dependencies: 'list[str] | None' = None,
 lifespan: 'Callable[[MCPServer[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]] | None' = None,
 auth: 'AuthSettings | None' = None,
 resource_security: 'ResourceSecurity' = ResourceSecurity(reject_path_traversal=True, reject_absolute_paths=True, reject_null_bytes=True, exempt_params=frozenset()),
 request_state_security: 'RequestStateSecurity | None' = None,
 cache_hints: 'Mapping[CacheableMethod, CacheHint] | None' = None,
 subscriptions: 'SubscriptionBus | None' = None,
 middleware: 'Sequence[ServerMiddleware[Any]] | None' = None)
```

`MCPServer.run`:

```
(self, transport: "Literal['stdio', 'sse', 'streamable-http']" = 'stdio', **kwargs: 'Any') -> 'None'
```

Confirms the packaging topic's claim: transport selection (`stdio` /
`sse` / `streamable-http`, plus transport-specific `**kwargs`) is entirely a
`run()`-time concern; nothing on the constructor selects or configures a
transport.

## 5. HTTP client: `httpx2`, not `httpx`

**[PACKAGE-VERIFIED].** `importlib.metadata.requires("mcp")` for `mcp==2.1.1`
includes `httpx2>=2.5.0` as an unconditional (non-extra) dependency:

```
'httpx2>=2.5.0', 'jsonschema>=4.20.0', 'mcp-types==2.1.1', 'opentelemetry-api>=1.28.0',
'pydantic>=2.12.0', 'pyjwt[crypto]>=2.10.1', 'python-multipart>=0.0.9',
'sse-starlette>=3.0.0', 'starlette>=0.27; ...', 'typing-extensions>=4.13.0',
'typing-inspection>=0.4.1', 'uvicorn>=0.31.1; ...', 'anyio>=4.9; ...'
```

Classic `httpx` is **not** in that list, and is not importable in a fresh
`uv add mcp` environment — `import httpx` raises `ModuleNotFoundError: No
module named 'httpx'`. `httpx2.AsyncClient` exists and constructs normally;
its `__init__` signature (a classic-`httpx`-shaped async client, confirming
"httpx2" is an API-compatible successor, not a different design):

```
(self, *, auth=None, params=None, headers=None, cookies=None, verify=True, cert=None,
 http1=True, http2=False, proxy=None, mounts=None, timeout=Timeout(timeout=5.0),
 follow_redirects=False, limits=Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0),
 max_redirects=20, event_hooks=None, base_url='', transport=None, trust_env=True,
 default_encoding='utf-8') -> None
```

## 6. In-process test client — confirmed, with one load-bearing correction

**[PACKAGE-VERIFIED] + [SMOKE-TESTED].**

`mcp.Client(server)` exists, accepts an `MCPServer` instance directly (its
`server` parameter's type union includes `MCPServer`), and connects
in-process with no subprocess — confirmed by reading `mcp/client/_memory.py`
(`InMemoryTransport`, used when `server` is a `Server`/`MCPServer` instance)
and by the smoke test below actually calling a tool through it.

`Client.__init__` accepts `raise_exceptions: bool = False`, confirming the
parameter exists.

**However: `Client(server, raise_exceptions=True)` does *not* re-raise a
tool-level exception — it still returns a normal `CallToolResult(is_error=True)`,
identical to the default client.** This was tested for both a deliberate
`ToolError` and a bare, unanticipated `RuntimeError` raised inside a tool
body; in both cases, with `raise_exceptions=True`, `await
client.call_tool(...)` returned normally with `is_error=True` and did **not**
raise a Python exception into the caller.

Reading the SDK's own source explains why: `mcp/server/mcpserver/tools/base.py`
(`Tool.run`) unconditionally catches every exception from a tool body and
converts it to a `CallToolResult` (via `ToolError`/`UnexpectedToolError`)
*before* the request ever reaches the lower-level dispatcher where
`raise_exceptions` (there named `raise_handler_exceptions`, in
`mcp/server/runner.py`) is consulted. That flag only affects exceptions
escaping request *dispatch/routing* (e.g. a bug in the protocol-handling
layer itself), not exceptions raised by application tool code — which is the
scenario a test suite actually exercises. The SDK's own source carries an
unresolved `# TODO(Marcelo): When do raise_exceptions=True actually raises?`
at `mcp/client/client.py`, on the `raise_exceptions` field itself — i.e. the
SDK's own maintainers have not pinned down when this flag fires.

**[SMOKE-TESTED]** end-to-end script (`build_server()` registers three tools
— one success path, one deliberate `ToolError`, one bare `RuntimeError` —
inside a factory, mirroring claim 10; then drives both a default `Client`
and a `raise_exceptions=True` `Client` against all three):

```python
import asyncio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp import Client

def build_server() -> MCPServer:
    server = MCPServer("spike-server")

    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b

    @server.tool()
    def fail_anticipated() -> str:
        raise ToolError("a specific, anticipated failure message")

    @server.tool()
    def fail_unanticipated() -> str:
        raise RuntimeError("some internal bug detail that should be redacted")

    return server

async def main() -> None:
    server = build_server()
    async with Client(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})
        assert result.structured_content == {"result": 5}

        result = await client.call_tool("fail_anticipated", {})
        assert result.is_error is True
        assert "a specific, anticipated failure message" in result.content[0].text

        result = await client.call_tool("fail_unanticipated", {})
        assert result.is_error is True
        assert "internal bug detail" not in result.content[0].text
        assert "Error executing tool fail_unanticipated" in result.content[0].text

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("fail_anticipated", {})
        assert result.is_error is True  # NOT raised, despite raise_exceptions=True

asyncio.run(main())
```

Result: all assertions passed. `add` returned `structured_content ==
{"result": 5}`; the `ToolError` message reached the client verbatim; the bare
`RuntimeError` was redacted to `Error executing tool fail_unanticipated` with
no trace of the original message; and `raise_exceptions=True` changed nothing
observable for either failing tool.

## 7. `create_connected_server_and_client_session` — confirmed removed

**[PACKAGE-VERIFIED].** `grep -r create_connected_server_and_client_session`
over the entire installed `mcp` package tree returns zero matches. The v1
symbol is gone; `mcp.Client` (§6) is the only in-process test path in 2.x.

## 8. Snake_case attributes — confirmed

**[PACKAGE-VERIFIED].** `mcp.Tool.model_fields` (pydantic model field names)
for `mcp==2.1.1`:

```
['name', 'title', 'description', 'input_schema', 'execution', 'output_schema', 'icons', 'annotations', 'meta']
```

`mcp.types.CallToolResult.model_fields`:

```
['meta', 'content', 'structured_content', 'is_error', 'result_type']
```

`input_schema`, `output_schema`, `is_error`, `structured_content` are all
present exactly as named in the packaging topic.

## 9. `ToolError` — exists, message reaches the client, but is not re-exported anywhere convenient

**[PACKAGE-VERIFIED] + [SMOKE-TESTED].**

Defined at `mcp/server/mcpserver/exceptions.py`. **Its only importable path is**:

```python
from mcp.server.mcpserver.exceptions import ToolError
```

It is **not** re-exported from `mcp.server.mcpserver.__init__` (checked its
`__all__` — absent), **not** from `mcp.server`, and **not** from top-level
`mcp`. Any code that writes `from mcp.server.mcpserver import ToolError` or
`from mcp import ToolError` will get `ImportError` — both were tried and both
failed. The packaging topic does not currently state an exact import path for
`ToolError`; this is the fact to encode when it does.

The exception hierarchy, from the source (`mcp/server/mcpserver/exceptions.py`):

- `MCPServerError` (base)
  - `ResourceError` — anticipated resource failure; `ResourceNotFoundError` subclasses it
    - `UnexpectedResourceError` — the SDK's own wrapper around a resource-handler crash
  - `ToolError` — anticipated tool failure; **message reaches the client** in
    `content`, with `is_error=True`, logged at INFO with no traceback
    - `UnexpectedToolError` — the SDK's own wrapper around anything else a
      tool raises; message is only `Error executing tool <name>`, original
      exception withheld from the client, logged at ERROR with a traceback

**[SMOKE-TESTED]**, §6's script: a `ToolError("a specific, anticipated
failure message")` reached the client's `result.content[0].text` verbatim.
A bare `RuntimeError("some internal bug detail that should be redacted")`
reached the client only as `"Error executing tool fail_unanticipated"` — the
original message did not appear anywhere in the client-visible result. Both
confirm the packaging topic's claim precisely.

## 10. Tool registration inside a factory, before `run()` — confirmed

**[SMOKE-TESTED].** §6's `build_server()` function registers three tools via
`@server.tool()` decorators inside an ordinary factory function, returns the
configured `MCPServer`, and only afterward is it connected to a client and
called — `run()` was never invoked in this spike (the in-process `Client`
does not require it), but the registration pattern is identical to what
`run()` would see: all `@server.tool()` calls execute synchronously during
`build_server()`, before any request handling starts. Nothing in
`MCPServer.tool()` (checked its signature) takes a request-time argument or
defers registration — it registers immediately against `self._tool_manager`
when the decorator runs. This supports build-time, configuration-gated tool
registration (the mechanism the `tool-surface` topic's destructive-tool
gating depends on; see `_rfc/README.md`)
with no dynamic, per-request behavior involved.

---

## 11. The stdio client transport — a real subprocess, not the in-process client

**[PACKAGE-VERIFIED] + [SMOKE-TESTED], 2026-09-04.**

Section 6 covers `mcp.Client(server)`, which is backed by
`mcp/client/_memory.py`'s `InMemoryTransport` and never spawns a process. That
is not the transport a real client uses. The stdio client path is separate and
is **not** reachable from `mcp.Client`:

- `mcp.client.stdio.StdioServerParameters(*, command: str, args: list[str] = [], env=None, cwd=None, ...)`
- `mcp.client.stdio.stdio_client(server: StdioServerParameters, errlog=...)` —
  an async generator yielding `(read_stream, write_stream)`. It spawns a genuine
  child process using `anyio`'s process machinery.
- `mcp.client.session.ClientSession(read_stream, write_stream, ...)`, also
  exported as top-level `mcp.ClientSession`, carrying `initialize()`,
  `list_tools()` and `call_tool(name, arguments)`.

Server-side, transport selection happens at `run()` time —
`server.run("stdio")` — and there is no transport parameter on
`MCPServer.__init__` for it to have gone on instead, consistent with §4.

Driven end to end against a built wheel invoked through `uvx`, `initialize()`
returned the server's declared name, `list_tools()` listed the registered tool,
and `call_tool()` returned both `content` (text `"9"`) and `structured_content`
(`{'result': 9}`) with `is_error=False`. The full transcript, including the
scratch server and client scripts, is at
`docs/validation/2026-09-04-packaging-build-validation.md` under B8.

## Summary of discrepancies from the packaging topic's text

Everything in the packaging topic's Context and Decision sections about SDK
versions, the `fastmcp` stub, the `MCPServer` rename, `run()`-time transport
parameters, `httpx2`, snake_case attributes, the removal of
`create_connected_server_and_client_session`, and build-time tool
registration is **confirmed** against the installed package.

One claim needs amendment before the RFC is relied on for test design:

- **`Client(server, raise_exceptions=True)` does not re-raise a tool-level
  exception.** It still returns `is_error=True`. The packaging topic's
  Testing section states this flag is "what makes a failing test readable" —
  empirically, for the primary error-testing scenario (a tool raising
  `ToolError` or a bug), it makes no observable difference from the default
  client. Tests that want a Python-level exception to assert against will
  need to inspect `CallToolResult.is_error` / `.content` directly rather than
  relying on an exception propagating out of `call_tool()`, or exercise
  `MCPServer.call_tool()` directly rather than going through `Client`. The
  SDK's own source (`mcp/client/client.py`) carries an unresolved
  maintainer TODO on exactly when this flag fires, so this may be a genuinely
  unfinished corner of `mcp==2.1.1`, not a documentation gap.
