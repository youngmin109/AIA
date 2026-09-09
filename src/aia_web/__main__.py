"""Run the local AIA Security Console."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "aia_web.app:app",
        host=os.environ.get("AIA_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("AIA_WEB_PORT", "8787")),
        reload=False,
    )


if __name__ == "__main__":
    main()
