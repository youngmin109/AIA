from __future__ import annotations

import argparse
import sys

from aia_desktop.launcher import main as desktop_main


def _server_main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="AIA --server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(arguments)

    from aia_web.__main__ import run

    run(host=args.host, port=args.port)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        return _server_main(sys.argv[2:])
    if len(sys.argv) > 1:
        # AIA.exe is also the trusted packaged entry point for its local
        # diagnostics and Hook runtime.  Dispatching arguments here lets the
        # desktop build avoid the separately packaged unsigned aia-cli.exe.
        from aia.cli import main as cli_main

        return cli_main(sys.argv[1:])
    return desktop_main()


if __name__ == "__main__":
    raise SystemExit(main())
