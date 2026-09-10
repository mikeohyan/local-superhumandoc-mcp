"""MCP server for a single Superhuman Docs document."""

from importlib.metadata import PackageNotFoundError, version


def running_version() -> str:
    """The installed version of this server, or `"unknown"`.

    Read from installed metadata -- the same source `init` pins a scaffolded
    project to -- so the startup line and a project's `.mcp.json` pin can be
    compared directly. An uninstalled source tree has no metadata, and that
    must degrade rather than raise: a missing version is not a reason to
    refuse to serve.
    """
    try:
        return version("superhumandoc-mcp")
    except PackageNotFoundError:
        return "unknown"
