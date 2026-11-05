# encoding: utf-8
"""用本机 Chrome + CDP 打开小红书话题页，抓取真实 XHR 接口。"""

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
PORT = 9222
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


async def wait_chrome(session: aiohttp.ClientSession) -> dict:
    for _ in range(60):
        try:
            async with session.get(f"http://127.0.0.1:{PORT}/json/version") as r:
                if r.status == 200:
                    return await r.json()
        except Exception:
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError("Chrome CDP 未就绪")


async def main() -> None:
    raw_cookies = dotenv_values(ROOT / ".env").get("COOKIES") or ""
    cookies = parse_cookies(raw_cookies)
    profile = f"/tmp/xhs-cdp-{int(time.time())}"
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            f"--user-agent={UA}",
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
                await send(
                    "Network.setUserAgentOverride",
                    {"userAgent": UA, "platform": "Win32"},
                )
                await send(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": (
                            "Object.defineProperty(navigator,'webdriver',"
                            "{get:()=>undefined})"
                        )
                    },
                )
                await send("Network.setCookies", {"cookies": cookies})
                await send(
                    "Page.navigate",
                    {"url": "https://www.xiaohongshu.com/explore"},
                )
                await asyncio.sleep(4)
                url = (
                    f"https://www.xiaohongshu.com/page/topics/{TOPIC_ID}"
                    f"?name={urllib.parse.quote(TOPIC_NAME)}"
                )
                await send("Page.navigate", {"url": url})

                reqs: dict[str, dict] = {}
                deadline = time.time() + 25
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
                        if "/api/" in req_url:
                            reqs[params["requestId"]] = {
                                "url": req_url,
                                "method": params["request"]["method"],
                                "postData": params["request"].get("postData"),
                                "status": None,
                            }
                    elif method == "Network.responseReceived":
                        rid = params["requestId"]
                        if rid in reqs:
                            reqs[rid]["status"] = params["response"]["status"]
                            reqs[rid]["mime"] = params["response"].get("mimeType")

                print(json.dumps(list(reqs.values()), ensure_ascii=False, indent=2))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
