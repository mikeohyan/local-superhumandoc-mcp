"""Console-script entry point. Speaks stdio; nothing else is wired up yet."""

from superhumandoc_mcp.server import build_server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
