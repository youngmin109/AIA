"""Run the local AIA Security Console."""

from __future__ import annotations

import os

import uvicorn


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_local_bind(host: str, port: int) -> None:
    """Validate the console's local-only network boundary."""

    if host.strip().lower() not in _LOOPBACK_HOSTS:
        raise ValueError(
            "AIA console is local-only; host must be 127.0.0.1, localhost, or ::1"
        )
    if not 1 <= port <= 65_535:
        raise ValueError("port must be between 1 and 65535")


def run(*, host: str | None = None, port: int | None = None) -> None:
    """Start the local console with explicit values or environment defaults."""

    selected_host = host if host is not None else os.environ.get("AIA_WEB_HOST", "127.0.0.1")
    selected_port = port if port is not None else int(os.environ.get("AIA_WEB_PORT", "8787"))
    validate_local_bind(selected_host, selected_port)
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
