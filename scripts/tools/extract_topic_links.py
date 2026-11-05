# encoding: utf-8
"""打开笔记页，提取话题链接里的真实 page_id。"""

import asyncio
import json
import subprocess
import time
from pathlib import Path

import aiohttp
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]

CHROME = "/usr/bin/google-chrome-stable"
PORT = 9225
NOTE_URL = (
    "https://www.xiaohongshu.com/explore/6adb01530000000031026ba5"
    "?xsec_token=ABhUl1PhnxOHaTDy2htmfLedNusJdJnxBqweqxzDFsRAM="
)
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
    profile = f"/tmp/xhs-links-{int(time.time())}"
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

                async def send(method: str, params: dict | None = None) -> int:
                    nonlocal msg_id
                    msg_id += 1
                    await ws.send_json(
                        {"id": msg_id, "method": method, "params": params or {}}
                    )
                    return msg_id

                await send("Network.enable")
                await send("Page.enable")
                await send("Runtime.enable")
                await send(
                    "Network.setUserAgentOverride",
                    {"userAgent": UA, "platform": "Win32"},
                )
                await send("Network.setCookies", {"cookies": cookies})
                await send("Page.navigate", {"url": NOTE_URL})
                await asyncio.sleep(10)

                expr = """
                (() => {
                  const els = Array.from(document.querySelectorAll(
                    '[data-topic], a.mention, a[href*="topic"], a[href*="search_result"], a[href*="keyword"]'
                  ));
                  return JSON.stringify({
                    title: document.title,
                    bodyLen: (document.body.innerText||'').length,
                    count: els.length,
                    items: els.slice(0, 20).map(e => ({
                      tag: e.tagName,
                      cls: String(e.className||'').slice(0,60),
                      href: e.getAttribute('href'),
                      dataTopic: e.getAttribute('data-topic'),
                      text: (e.textContent||'').trim().slice(0,50),
                      html: e.outerHTML.slice(0,300)
                    }))
                  });
                })()
                """
                eval_id = await send(
                    "Runtime.evaluate",
                    {"expression": expr, "returnByValue": True},
                )
                deadline = time.time() + 10
                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    if data.get("id") == eval_id:
                        value = (
                            data.get("result", {})
                            .get("result", {})
                            .get("value")
                        )
                        print(value)
                        break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
