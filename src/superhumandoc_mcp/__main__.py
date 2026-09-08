"""Console-script entry point."""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from superhumandoc_mcp.client import DocsClient, TokenIdentity
from superhumandoc_mcp.config import (
    Config, ConfigError, format_startup_line, load_config,
)
from superhumandoc_mcp.errors import AuthFailure, ClientError
from superhumandoc_mcp.init import run_init
from superhumandoc_mcp.server import build_server


def _configure_logging(config: Config) -> None:
    """Apply the resolved level to this package's own logger, not the root.

    stderr, not stdout: stdout carries the MCP transport. Scoped to the
    `superhumandoc_mcp` logger, rather than `logging.basicConfig` on root,
    because raising root's level switches on every library's own logging too
    -- `httpx`, for one, would start emitting a line per API call for a user
    who never asked for that. `propagate = False` keeps those same records
    from reaching root's handlers a second time. The logger's handlers are
    replaced outright, not appended to, so a second call (or a repeated
    lowering of the level) does not accumulate duplicate output.

    Because of `propagate = False`, pytest's `caplog` fixture -- which
    listens on the root logger -- never sees anything emitted on the
    `superhumandoc_mcp` logger, even inside `caplog.at_level(...)`. A test
    that wants to assert on this package's log output should attach its own
    handler to the `superhumandoc_mcp` logger instead of relying on `caplog`.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    logger = logging.getLogger("superhumandoc_mcp")
    logger.handlers = [handler]
    logger.setLevel(config.log_level)
    logger.propagate = False


def main() -> None:
    parser = argparse.ArgumentParser(prog="superhumandoc-mcp")
    parser.add_argument("--env-file", dest="env_file", default=None)
    # Registered without `required=True` on purpose: the bare, subcommand-free
    # invocation that every deployed .mcp.json emits must keep parsing exactly
    # as it did before this subcommand existed, and keep reaching the server
    # path below. Unrecognised arguments still fail closed.
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser(
        "init", help="scaffold the current directory into a consuming project"
    )
    args = parser.parse_args()

    # Before configuration resolution, deliberately: `init` is offline, handles
    # no credentials, and exists to serve the empty directory in which
    # `load_config` would have nothing to find.
    if args.command == "init":
        raise SystemExit(run_init(Path.cwd(), sys.stdout, sys.stderr))

    try:
        config = load_config(args.env_file, os.environ, Path.cwd())
    except ConfigError as error:
        # stderr, not stdout: stdout is the MCP transport.
        print(f"superhumandoc-mcp: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    _configure_logging(config)

    identity = asyncio.run(_identify(config))
    print(format_startup_line(config, identity), file=sys.stderr)
    build_server(config).run("stdio")


async def _identify(
    config: Config, client: DocsClient | None = None
) -> TokenIdentity | None:
    """A 401 stops the server: the token is not valid and every tool would
    fail. Anything else starts it. A 403 in particular is what a token teaches
    per call, not a verdict on the token, so it is reported rather than fatal,
    and so is a timeout, a 5xx or a 429 — the line then says scope is unknown.

    `client` is injectable so this asymmetry can be exercised against a mock
    transport rather than the network.
    """
    client = client or DocsClient(config)
    try:
        return await client.whoami()
    except AuthFailure as error:
        if error.status == 401:
            print(f"superhumandoc-mcp: {error}", file=sys.stderr)
            raise SystemExit(2) from error
        return None
    except ClientError:
        return None
    finally:
        await client.aclose()


if __name__ == "__main__":
    main()
