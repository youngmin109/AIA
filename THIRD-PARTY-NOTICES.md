# Third-party notices

AIA itself is licensed under the [Apache License 2.0](LICENSE). The Windows
build and installer also contain the third-party components below. Each keeps
its own license; follow the links for each project's full license text.

AIA 자체는 Apache License 2.0을 따릅니다. Windows 빌드와 설치 파일에는 아래 외부
구성 요소가 함께 들어 있으며, 각 구성 요소는 자신의 라이선스를 따릅니다.

Versions are the ones pinned in `uv.lock` and `frontend/package-lock.json` at
release time.

## Runtime and bundling

| Component | License | Notes |
|---|---|---|
| [Python](https://www.python.org/) 3.13 | PSF-2.0 | Runtime embedded by PyInstaller |
| [PyInstaller](https://pyinstaller.org/) bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception | The exception allows distributing the built executables under any license |

## Python packages

| Package | License |
|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | MIT |
| [Starlette](https://github.com/Kludex/starlette) | BSD-3-Clause |
| [Pydantic](https://github.com/pydantic/pydantic), pydantic-core | MIT |
| [annotated-types](https://github.com/annotated-types/annotated-types), [annotated-doc](https://github.com/fastapi/annotated-doc), [typing-inspection](https://github.com/pydantic/typing-inspection) | MIT |
| [typing_extensions](https://github.com/python/typing_extensions) | PSF-2.0 |
| [AnyIO](https://github.com/agronholm/anyio) | MIT |
| [Uvicorn](https://github.com/Kludex/uvicorn) | BSD-3-Clause |
| [h11](https://github.com/python-hyper/h11) | MIT |
| [Click](https://github.com/pallets/click) | BSD-3-Clause |
| [idna](https://github.com/kjd/idna) | BSD-3-Clause |
| [websockets](https://github.com/python-websockets/websockets) | BSD-3-Clause |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause |
| [watchdog](https://github.com/gorakhargosh/watchdog) | Apache-2.0 |
| [pywebview](https://github.com/r0x0r/pywebview) | BSD-3-Clause |
| [bottle](https://bottlepy.org/), [proxy_tools](https://github.com/jtushman/proxy_tools) | MIT |
| [pythonnet](https://github.com/pythonnet/pythonnet), [clr-loader](https://github.com/pythonnet/clr-loader) | MIT |
| [cffi](https://github.com/python-cffi/cffi) | MIT-0 |
| [pycparser](https://github.com/eliben/pycparser) | BSD-3-Clause |
| [pywinpty](https://github.com/andfoy/pywinpty) | MIT |

## Screen (frontend) packages

| Package | License |
|---|---|
| [React](https://github.com/facebook/react), react-dom, scheduler | MIT |
| [xterm.js](https://github.com/xtermjs/xterm.js) (`@xterm/xterm`, `@xterm/addon-fit`) | MIT |

## Fonts

| Font | License |
|---|---|
| [Pretendard](https://github.com/orioncactus/pretendard) Variable | SIL Open Font License 1.1, see [`src/aia_web/static/fonts/OFL.txt`](src/aia_web/static/fonts/OFL.txt) |

## Not bundled

Microsoft Edge WebView2 Runtime and the Codex CLI are required but are not
included in the AIA installer; they are installed separately under their own
terms.
