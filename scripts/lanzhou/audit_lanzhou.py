"""Small live Lanzhou Marathon crawl and field/coverage audit. Run from any cwd."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import socket
import time
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from dotenv import dotenv_values
from loguru import logger

from apis.xhs_pc_apis import XHS_Apis
from tag_crawler import init_db, upsert_note
from xhs_utils.xhs_pc import XHSPcAuth
from xhs_utils.xhs_util import generate_search_id
QUERIES = ["兰州马拉松", "#兰州马拉松", "兰马"]
SORTS = {"general": 0, "time_descending": 1}


def quiet_call(func, *args, **kwargs):
    # Third-party diagnostics can contain credentials: do not copy them to reports.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


def inspect_note(note_id, card):
    user = card.get("user") or {}
    interaction = card.get("interact_info") or {}
    images = card.get("image_list") or []
    video = card.get("video") or {}
    tags = [t.get("name", "") for t in card.get("tag_list", []) if isinstance(t, dict)]
    title, desc = card.get("title") or "", card.get("desc") or ""
    def has_url(value):
        if isinstance(value, str):
            return value.startswith(("https://", "http://"))
        if isinstance(value, dict):
            return any(has_url(v) for v in value.values())
        if isinstance(value, list):
            return any(has_url(v) for v in value)
        return False
    return {
        "note_id": note_id, "url": f"https://www.xiaohongshu.com/explore/{note_id}",
        "title": title, "description": desc, "type": card.get("type"),
        "author_name": user.get("nickname"), "author_id": user.get("user_id"),
        "published_at_raw": card.get("time"), "last_update_raw": card.get("last_update_time"),
        "tags": tags, "image_count": len(images),
        "missing_image_urls": sum(not has_url(i) for i in images),
        "video_url_present": has_url(video),
        "liked_count": interaction.get("liked_count"),
        "collected_count": interaction.get("collected_count"),
        "comment_count": interaction.get("comment_count"),
        "share_count": interaction.get("share_count"),
        "keyword_in_content": any(k in title + desc for k in ["兰州马拉松", "兰马"]),
        "exact_topic_match": "兰州马拉松" in tags,
    }


def write_reports(out, report, notes):
    report["details"] = notes
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["title", "description", "author_name", "author_id", "published_at_raw",
              "liked_count", "collected_count", "comment_count", "share_count", "tags"]
    missing = {k: sum(n.get(k) in (None, "", []) for n in notes) for k in fields}
    report["field_missing_counts"] = missing
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if notes:
        with (out / "posts.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(notes[0]))
            w.writeheader()
            for n in notes:
                row = dict(n, tags=json.dumps(n["tags"], ensure_ascii=False))
                # Keep spreadsheet applications from interpreting scraped content as formulas.
                row = {k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for k, v in row.items()}
                w.writerow(row)
    lines = ["# 兰州马拉松试采审计", "", f"状态：{report['status']}",
             f"独立搜索结果：{report.get('unique_notes', 0)}；详情成功：{len(notes)}；详情失败：{len(report.get('detail_failures', []))}", "",
             "## 字段缺失（仅在详情成功的样本中统计）", "",
             "| 字段 | 缺失数 | 样本数 |", "|---|---:|---:|"]
    lines += [f"| {k} | {v} | {len(notes)} |" for k, v in missing.items()]
    lines += ["", "## 解释边界", "",
              "这是关键词搜索试采，不是话题 ID 的全量遍历。未建立总体清单，不能计算召回率。",
              "标题和正文已保存接口返回原文；尚未与网页逐字比对，不能断言未截断。",
              "未抓评论正文、未下载图片或视频、未验证媒体 URL 的可访问性。",
              "无标签或无正文可能是帖子本身没有该字段，需人工查看样本区分。",
              "keyword_in_content 为字面匹配，不能替代人工相关性判定；兰马也可能有歧义。",
              "详情样本按排序轮换取样，不是随机样本，缺失率不能外推至平台。"]
    if report.get("blocking_reason"):
        lines += ["", "阻塞原因：" + report["blocking_reason"]]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pages", type=int, default=2)
    p.add_argument("--details", type=int, default=20)
    p.add_argument("--sleep", type=float, default=1.5)
    args = p.parse_args()
    if args.pages < 1 or args.details < 0 or args.sleep < 0:
        p.error("pages must be positive; details and sleep must be nonnegative")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "data" / "lanzhou_audit" / stamp
    out.mkdir(parents=True, mode=0o700)
    report = {"status": "started", "created_at": stamp, "queries": QUERIES,
              "pages_per_query_sort": args.pages, "pages": [], "detail_failures": []}
    notes, conn, auth = [], None, None
    logger.remove()
    try:
        for host in ["www.xiaohongshu.com", "so.xiaohongshu.com", "edith.xiaohongshu.com"]:
            try:
                socket.getaddrinfo(host, 443)
            except OSError:
                report["blocking_reason"] = f"无法解析域名 {host}，尚未发送采集请求"
                raise RuntimeError("DNS preflight failed")
        cookie = os.environ.get("COOKIES") or dotenv_values(ROOT / ".env").get("COOKIES")
        if not cookie:
            report["blocking_reason"] = "未找到 COOKIES 配置"
            raise RuntimeError("Missing cookies")
        auth = quiet_call(XHSPcAuth.from_cookie, cookie)
        api = quiet_call(XHS_Apis(auth).bootstrap)
        conn = init_db(out / "crawl.db")
        groups, all_ids = [], set()
        for query in QUERIES:
            for sort, choice in SORTS.items():
                ids, search_id = [], generate_search_id()
                for page in range(1, args.pages + 1):
                    ok, _msg, res = quiet_call(api.search_note, query, page=page,
                                              sort_type_choice=choice, search_id=search_id)
                    data = (res or {}).get("data") or {}
                    items = [i for i in data.get("items", []) if i.get("model_type") == "note" and i.get("id") and i.get("note_card")]
                    page_ids = [i["id"] for i in items]
                    entry = {"query": query, "sort": sort, "page": page, "success": bool(ok),
                             "api_code": (res or {}).get("code"), "items": len(items),
                             "new_unique": len(set(page_ids) - all_ids),
                             "duplicates_with_previous_pages_and_queries": len(page_ids) - len(set(page_ids) - all_ids),
                             "has_more": data.get("has_more"), "note_ids": page_ids}
                    report["pages"].append(entry)
                    print(json.dumps({k: v for k, v in entry.items() if k != "note_ids"}, ensure_ascii=False), flush=True)
                    if not ok:
                        break
                    for item in items:
                        upsert_note(conn, item, query, sort, page)
                    conn.commit()
                    ids.extend(page_ids)
                    all_ids.update(page_ids)
                    time.sleep(args.sleep)
                    if not data.get("has_more") or not items:
                        break
                groups.append(ids)
        report["unique_notes"] = len(all_ids)
        selected = []
        for index in range(max((len(g) for g in groups), default=0)):
            for group in groups:
                if index < len(group) and group[index] not in selected:
                    selected.append(group[index])
        report["detail_attempts"] = min(args.details, len(selected))
        for note_id in selected[:args.details]:
            url = conn.execute("SELECT url FROM notes WHERE note_id=?", (note_id,)).fetchone()[0]
            ok, _msg, info = quiet_call(api.get_note_info, url)
            items = ((info or {}).get("data") or {}).get("items") or []
            matching = next((i for i in items if (i.get("id") or (i.get("note_card") or {}).get("note_id")) == note_id), None)
            if ok and matching and matching.get("note_card"):
                notes.append(inspect_note(note_id, matching["note_card"]))
                conn.execute("UPDATE notes SET detail_json=? WHERE note_id=?", (json.dumps(info, ensure_ascii=False), note_id))
                conn.commit()
            else:
                report["detail_failures"].append({"note_id": note_id, "api_code": (info or {}).get("code"), "response_id_matched": bool(matching)})
            print(f"详情 {len(notes)} 成功 / {len(report['detail_failures'])} 失败", flush=True)
            time.sleep(args.sleep)
        report["note_types"] = dict(Counter(n["type"] for n in notes))
        report["status"] = "completed" if notes and all(x["success"] for x in report["pages"]) and not report["detail_failures"] else "partial"
    except Exception as exc:
        report["status"] = "blocked" if not notes else "partial"
        report["error_type"] = type(exc).__name__
        report.setdefault("blocking_reason", "登录、网络或请求失败；异常内容未导出，避免包含凭证")
    finally:
        if conn is not None:
            conn.close()
        if auth is not None:
            quiet_call(auth.close)
        write_reports(out, report, notes)
    print(f"REPORT_DIR={out}", flush=True)
    print(f"STATUS={report['status']}", flush=True)
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
