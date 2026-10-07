"""Screenshot the preview console at 1440x900 with headless Edge (EPIC-020).

Steps run in order; each is ``click:<visible text>``, ``wait:<seconds>``,
``eval:<javascript>``, ``type:<css selector>=<text>`` or ``drag:<x1>,<y1>,<x2>,<y2>``
(a real mouse drag in page pixels). ``url:<address>`` and
``size:<w>x<h>`` change the page and viewport (defaults: preview server, 1440x900). A screenshot is saved
after the last step.

    .venv\\Scripts\\python.exe scripts\\dev\\ui_shot.py out.png click:기록 wait:1
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
URL = "http://127.0.0.1:8899/"

CLICK_JS = """
(() => {
  const want = %s;
  const nodes = [...document.querySelectorAll('button, a, [role="tab"], summary, label')]
    .filter(node => node.getClientRects().length && node.textContent.trim().includes(want));
  nodes.sort((a, b) => a.textContent.length - b.textContent.length);
  if (!nodes[0]) return 'missing: ' + want;
  nodes[0].click();
  return 'clicked: ' + nodes[0].textContent.trim().slice(0, 40);
})()
"""

TYPE_JS = """
(() => {
  const node = document.querySelector(%s);
  if (!node) return 'missing';
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node), 'value').set;
  setter.call(node, %s);
  node.dispatchEvent(new Event('input', { bubbles: true }));
  return 'typed';
})()
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def run(out: Path, steps: list[str], width: int, height: int, port: int, url: str) -> None:
    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    page = next(target for target in targets if target["type"] == "page")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000) as socket:
        counter = 0

        async def call(method: str, **params):
            nonlocal counter
            counter += 1
            await socket.send(json.dumps({"id": counter, "method": method, "params": params}))
            while True:
                message = json.loads(await socket.recv())
                if message.get("id") == counter:
                    return message.get("result", {})

        await call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        await call("Page.navigate", url=url)
        await asyncio.sleep(3)
        for step in steps:
            kind, _, value = step.partition(":")
            if kind == "wait":
                await asyncio.sleep(float(value))
            elif kind == "click":
                result = await call("Runtime.evaluate", expression=CLICK_JS % json.dumps(value), returnByValue=True)
                print(result.get("result", {}).get("value"))
                await asyncio.sleep(0.8)
            elif kind == "type":
                selector, _, text = value.partition("=")
                result = await call("Runtime.evaluate", expression=TYPE_JS % (json.dumps(selector), json.dumps(text)), returnByValue=True)
                print(result.get("result", {}).get("value"))
            elif kind == "drag":
                x1, y1, x2, y2 = (float(part) for part in value.split(","))
                await call("Input.dispatchMouseEvent", type="mouseMoved", x=x1, y=y1)
                await call("Input.dispatchMouseEvent", type="mousePressed", x=x1, y=y1, button="left", clickCount=1)
                for index in range(1, 11):
                    await call("Input.dispatchMouseEvent", type="mouseMoved", x=x1 + (x2 - x1) * index / 10,
                               y=y1 + (y2 - y1) * index / 10, button="left", buttons=1)
                    await asyncio.sleep(0.02)
                await call("Input.dispatchMouseEvent", type="mouseReleased", x=x2, y=y2, button="left", clickCount=1)
                await asyncio.sleep(0.5)
            elif kind == "eval":
                result = await call("Runtime.evaluate", expression=value, returnByValue=True, awaitPromise=True)
                print(result.get("result", {}).get("value"))
        shot = await call("Page.captureScreenshot", format="png")
        out.write_bytes(base64.b64decode(shot["data"]))
        print(f"saved {out}")


def main() -> None:
    out = Path(sys.argv[1])
    steps = sys.argv[2:]
    width, height = 1440, 900
    url = URL
    for step in list(steps):
        if step.startswith("url:"):
            url = step[4:]
            steps.remove(step)
        if step.startswith("size:"):
            width, height = (int(part) for part in step[5:].split("x"))
            steps.remove(step)
    out.parent.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="aia-ui-shot-")
    port = free_port()
    edge = subprocess.Popen(
        [EDGE, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--hide-scrollbars", f"--window-size={width},{height}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
                break
            except OSError:
                asyncio.run(asyncio.sleep(0.2))
        asyncio.run(run(out, steps, width, height, port, url))
    finally:
        # Edge spawns child processes; end the whole tree so no browser keeps the profile or port.
        subprocess.run(["taskkill", "/PID", str(edge.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Headless Edge relaunches outside that tree; stop what still uses this run's own profile.
        name = Path(profile).name
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             f"Where-Object {{ $_.CommandLine -like '*{name}*' }} | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
