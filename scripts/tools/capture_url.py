# encoding: utf-8
"""通用：用 Chrome 打开指定 URL 并打印 API 请求。用法: python capture_url.py <url>"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]

CHROME = "/usr/bin/google-chrome-stable"
PORT = 9226
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
    target_url = sys.argv[1]
    cookies = parse_cookies(dotenv_values(ROOT / ".env").get("COOKIES") or "")
    profile = f"/tmp/xhs-cap-{int(time.time())}"
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
                await send("Network.setCookies", {"cookies": cookies})
                await send("Page.navigate", {"url": target_url})

                seen = set()
                deadline = time.time() + 25
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    if data.get("method") != "Network.requestWillBeSent":
                        continue
                    p = data["params"]
                    u = p["request"]["url"]
                    if "/api/" not in u and "/web_api/" not in u:
                        continue
                    key = (p["request"]["method"], u)
                    if key in seen:
                        continue
                    seen.add(key)
                    body = p["request"].get("postData") or ""
                    print(f"{p['request']['method']:5} {u[:200]}")
                    if body:
                        print(f"      body: {body[:300]}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
