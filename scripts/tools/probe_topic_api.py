# encoding: utf-8
"""探测小红书话题笔记列表接口的真实路径。"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth

TOPIC_ID = "5be426f747b058000196e1c6"  # 北京赏秋

CANDIDATES = [
    ("POST", "/api/sns/web/v1/topic/feed",
     {"topic_id": TOPIC_ID, "page": {"cursor": "", "page_size": 20}, "sort": "hot"}),
    ("POST", "/api/sns/web/v1/topic/notes",
     {"topic_id": TOPIC_ID, "page": {"cursor": "", "page_size": 20}, "sort": "hot"}),
    ("POST", "/api/sns/web/v1/page/topic",
     {"topic_id": TOPIC_ID, "page": {"cursor": "", "page_size": 20}, "sort": "hot"}),
    ("POST", "/api/sns/web/v1/page/topic/feed",
     {"page_id": TOPIC_ID, "page": {"cursor": "", "page_size": 20}, "sort": "hot"}),
    ("POST", "/api/sns/web/v1/topic",
     {"topic_id": TOPIC_ID, "page": {"cursor": "", "page_size": 20}, "sort": "hot"}),
    ("GET", f"/api/sns/web/v1/topic/feed?topic_id={TOPIC_ID}&cursor=&sort=hot", None),
    ("GET", f"/api/sns/web/v1/page/topic?page_id={TOPIC_ID}&cursor=&sort=hot", None),
    ("GET", f"/api/sns/web/v1/topic?topic_id={TOPIC_ID}", None),
    ("POST", "/api/sns/web/v1/feed",
     {"topic_id": TOPIC_ID, "page": {"cursor": "", "page_size": 20}}),
]


def probe(api: XHS_Apis, method: str, path: str, payload) -> None:
    try:
        if method == "POST":
            headers, cookies, body = api._request_params(path, payload or {}, "POST")
            r = api.http.post(
                api.base_url + path,
                headers=headers,
                data=body.encode("utf-8"),
                cookies=cookies,
                timeout=20,
            )
        else:
            headers, cookies, _ = api._request_params(path, "", "GET")
            r = api.http.get(
                api.base_url + path,
                headers=headers,
                cookies=cookies,
                timeout=20,
            )
        text = r.text or ""
        try:
            data = r.json()
            summary = {
                "success": data.get("success"),
                "code": data.get("code"),
                "msg": data.get("msg"),
                "keys": list((data.get("data") or {}).keys())
                if isinstance(data.get("data"), dict)
                else type(data.get("data")).__name__,
            }
        except Exception:
            summary = text[:200]
        print(f"{method:4} {path[:70]:70} -> {r.status_code} {summary}")
    except Exception as e:
        print(f"{method:4} {path[:70]:70} -> ERR {type(e).__name__}: {str(e)[:120]}")


def main() -> None:
    load_dotenv(ROOT / ".env")
    auth = XHSPcAuth.from_cookie(os.getenv("COOKIES"))
    try:
        api = XHS_Apis(auth).bootstrap()
        for method, path, payload in CANDIDATES:
            probe(api, method, path, payload)
            time.sleep(0.6)
    finally:
        auth.close()


if __name__ == "__main__":
    main()
