# encoding: utf-8
"""有头 Chrome 打开话题页抓包，必要时人工过验证码。"""

import asyncio
import json
import subprocess
import time
import urllib.parse
from pathlib import Path

import aiohttp
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]

CHROME = "/usr/bin/google-chrome-stable"
PORT = 9224
TOPIC_ID = "5be426f747b058000196e1c6"
TOPIC_NAME = "北京赏秋"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)


def parse_cookies(raw: str) -> list[dict]:
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        out.append(
            {
                "name": name,
                "value": value,
                "domain": ".xiaohongshu.com",
                "path": "/",
                "secure": True,
            }
        )
    return out


async def wait_chrome(session: aiohttp.ClientSession) -> None:
    for _ in range(80):
        try:
            async with session.get(f"http://127.0.0.1:{PORT}/json/version") as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError("Chrome CDP 未就绪")


async def main() -> None:
    cookies = parse_cookies(dotenv_values(ROOT / ".env").get("COOKIES") or "")
    profile = f"/tmp/xhs-headed-{int(time.time())}"
    proc = subprocess.Popen(
        [
            CHROME,
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1200,900",
            "--window-position=80,80",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        async with aiohttp.ClientSession() as session:
            await wait_chrome(session)
            async with session.put(
                f"http://127.0.0.1:{PORT}/json/new?about:blank"
            ) as r:
                target = await r.json()
            async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
                msg_id = 0

                async def send(method: str, params: dict | None = None) -> None:
                    nonlocal msg_id
                    msg_id += 1
                    await ws.send_json(
                        {"id": msg_id, "method": method, "params": params or {}}
                    )

                await send("Network.enable")
                await send("Page.enable")
                await send("Network.setCookies", {"cookies": cookies})
                url = (
                    f"https://www.xiaohongshu.com/page/topics/{TOPIC_ID}"
                    f"?name={urllib.parse.quote(TOPIC_NAME)}"
                )
                await send("Page.navigate", {"url": url})

                reqs: dict[str, dict] = {}
                deadline = time.time() + 90
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    method = data.get("method")
                    params = data.get("params", {})
                    if method == "Network.requestWillBeSent":
                        req_url = params["request"]["url"]
                        if "/api/" in req_url or "/web_api/" in req_url:
                            reqs[params["requestId"]] = {
                                "url": req_url,
                                "method": params["request"]["method"],
                                "postData": params["request"].get("postData"),
                                "status": None,
                            }
                            if "page/notes" in req_url or "page/topic" in req_url:
                                print(
                                    "HIT",
                                    params["request"]["method"],
                                    req_url[:220],
                                    flush=True,
                                )
                    elif method == "Network.responseReceived":
                        rid = params["requestId"]
                        if rid in reqs:
                            reqs[rid]["status"] = params["response"]["status"]

                out = f"/tmp/topic_capture_headed_{int(time.time())}.json"
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(list(reqs.values()), f, ensure_ascii=False, indent=2)
                print("saved", out, "requests", len(reqs))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
