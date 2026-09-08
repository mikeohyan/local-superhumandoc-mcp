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
from superhumandoc_mcp.server import build_server


def _configure_logging(config: Config) -> None:
    """Apply the resolved level to the logging module.

    stderr, not stdout: stdout carries the MCP transport. `force=True`
    because basicConfig is a no-op once the root logger has handlers, and
    this must be able to lower a level a library already raised.
    """
    logging.basicConfig(
        level=config.log_level,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="superhumandoc-mcp")
    parser.add_argument("--env-file", dest="env_file", default=None)
    args = parser.parse_args()

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
