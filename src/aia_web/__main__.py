"""Run the local AIA Security Console."""

from __future__ import annotations

import os

import uvicorn


def run(*, host: str | None = None, port: int | None = None) -> None:
    """Start the local console with explicit values or environment defaults."""

    selected_host = host if host is not None else os.environ.get("AIA_WEB_HOST", "127.0.0.1")
    selected_port = port if port is not None else int(os.environ.get("AIA_WEB_PORT", "8787"))
    if not selected_host.strip():
        raise ValueError("host must not be empty")
    if not 1 <= selected_port <= 65_535:
        raise ValueError("port must be between 1 and 65535")
    uvicorn.run(
        "aia_web.app:app",
        host=selected_host,
        port=selected_port,
        reload=False,
    )


def main() -> None:
    run()


if __name__ == "__main__":
    main()
