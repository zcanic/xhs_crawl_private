# encoding: utf-8
"""最小爬取测试：关键词搜索 + 取第一篇笔记详情。

用法:
    .venv/bin/python scripts/tools/test_crawl.py [关键词] [数量]
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth


def main() -> None:
    load_dotenv(ROOT / ".env")
    cookies = os.getenv("COOKIES")
    if not cookies:
        raise SystemExit("请先在 .env 中填写 COOKIES，或运行 login_qr.py 扫码登录")

    keyword = sys.argv[1] if len(sys.argv) > 1 else "露营"
    num = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    auth = XHSPcAuth.from_cookie(cookies)
    try:
        api = XHS_Apis(auth)
        success, msg, notes = api.search_some_note(
            keyword, num, 0, 0, 0, 0, 0, None, None
        )
        notes = [n for n in (notes or []) if n.get("model_type") == "note"]
        print(f"[search] success={success} msg={msg} notes={len(notes)}")
        if not success or not notes:
            return

        for n in notes[:5]:
            card = n.get("note_card") or {}
            print(
                json.dumps(
                    {
                        "id": n.get("id"),
                        "title": card.get("display_title"),
                        "type": card.get("type"),
                        "liked": (card.get("interact_info") or {}).get("liked_count"),
                        "xsec_token": n.get("xsec_token"),
                    },
                    ensure_ascii=False,
                )
            )

        first = notes[0]
        url = (
            f"https://www.xiaohongshu.com/explore/{first['id']}"
            f"?xsec_token={first['xsec_token']}"
        )
        ok, detail_msg, info = api.get_note_info(url)
        print(f"\n[detail] success={ok} msg={detail_msg}")
        if ok:
            item = info["data"]["items"][0]
            note = item.get("note_card") or {}
            print(
                json.dumps(
                    {
                        "note_id": item.get("id"),
                        "title": note.get("title"),
                        "desc": (note.get("desc") or "")[:120],
                        "user": (note.get("user") or {}).get("nickname"),
                        "images": len(note.get("image_list") or []),
                        "comments": (note.get("interact_info") or {}).get(
                            "comment_count"
                        ),
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        auth.close()


if __name__ == "__main__":
    main()
