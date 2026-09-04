"""Console-script entry point."""

import argparse
import os
import sys
from pathlib import Path

from superhumandoc_mcp.config import ConfigError, format_startup_line, load_config
from superhumandoc_mcp.server import build_server


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

    print(format_startup_line(config), file=sys.stderr)
    build_server(config).run("stdio")


if __name__ == "__main__":
    main()
