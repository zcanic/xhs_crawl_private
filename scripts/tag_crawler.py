# encoding: utf-8
"""按 tag/话题批量采集小红书笔记。

用法:
    .venv/bin/python scripts/tag_crawler.py --tags "#北京赏秋,#露营" --max-pages 30
    .venv/bin/python scripts/tag_crawler.py --tags "#露营" --detail

特性:
    - 多排序取并集（综合/最新/最热/最多评论/最多收藏）
    - 按 note_id 去重，SQLite 落库
    - 每页请求失败自动重试
    - 记录每个 tag+sort 的翻页进度
    - 可选拉取笔记详情
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth

SORT_CHOICES = {
    "general": 0,
    "time_descending": 1,
    "popularity_descending": 2,
    "comment_descending": 3,
    "collect_descending": 4,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY,
    title TEXT,
    note_type TEXT,
    author_id TEXT,
    author_name TEXT,
    liked_count TEXT,
    collected_count TEXT,
    comment_count TEXT,
    shared_count TEXT,
    xsec_token TEXT,
    url TEXT,
    raw_json TEXT,
    detail_json TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS note_tags (
    note_id TEXT,
    tag TEXT,
    sort TEXT,
    page INTEGER,
    created_at TEXT,
    PRIMARY KEY (note_id, tag)
);
CREATE TABLE IF NOT EXISTS crawl_state (
    tag TEXT,
    sort TEXT,
    last_page INTEGER,
    has_more INTEGER,
    updated_at TEXT,
    PRIMARY KEY (tag, sort)
);
CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_note(conn: sqlite3.Connection, item: dict, tag: str, sort: str, page: int) -> bool:
    """写入一条搜索结果；返回是否为新笔记。"""
    note_id = item.get("id")
    card = item.get("note_card") or {}
    if not note_id or not card:
        return False
    user = card.get("user") or {}
    interact = card.get("interact_info") or {}
    url = (
        f"https://www.xiaohongshu.com/explore/{note_id}"
        f"?xsec_token={item.get('xsec_token', '')}"
    )
    ts = now()
    existing = conn.execute(
        "SELECT 1 FROM notes WHERE note_id = ?", (note_id,)
    ).fetchone()
    conn.execute(
        """
        INSERT INTO notes (
            note_id, title, note_type, author_id, author_name,
            liked_count, collected_count, comment_count, shared_count,
            xsec_token, url, raw_json, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(note_id) DO UPDATE SET
            title = excluded.title,
            note_type = excluded.note_type,
            author_id = excluded.author_id,
            author_name = excluded.author_name,
            liked_count = excluded.liked_count,
            collected_count = excluded.collected_count,
            comment_count = excluded.comment_count,
            shared_count = excluded.shared_count,
            xsec_token = excluded.xsec_token,
            url = excluded.url,
            raw_json = excluded.raw_json,
            last_seen_at = excluded.last_seen_at
        """,
        (
            note_id,
            card.get("display_title") or "",
            card.get("type") or "",
            user.get("user_id") or "",
            user.get("nickname") or "",
            str(interact.get("liked_count") or ""),
            str(interact.get("collected_count") or ""),
            str(interact.get("comment_count") or ""),
            str(interact.get("shared_count") or ""),
            item.get("xsec_token") or "",
            url,
            json.dumps(item, ensure_ascii=False),
            ts,
            ts,
        ),
    )
    conn.execute(
        """
        INSERT INTO note_tags (note_id, tag, sort, page, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(note_id, tag) DO NOTHING
        """,
        (note_id, tag, sort, page, ts),
    )
    return existing is None


def search_with_retry(
    api: XHS_Apis,
    tag: str,
    page: int,
    sort_choice: int,
    attempts: int = 4,
) -> tuple[bool, str, dict | None]:
    last_msg = ""
    for attempt in range(attempts):
        ok, msg, res = api.search_note(tag, page=page, sort_type_choice=sort_choice)
        if ok and res:
            return ok, msg, res
        last_msg = str(msg)
        if attempt + 1 < attempts:
            wait = 2.0 * (attempt + 1)
            print(f"    [retry] page={page} attempt={attempt + 1} wait={wait}s msg={last_msg[:80]}")
            time.sleep(wait)
    return False, last_msg, None


def crawl_tag(
    api: XHS_Apis,
    conn: sqlite3.Connection,
    tag: str,
    sorts: list[str],
    max_pages: int,
    sleep_s: float,
    max_empty_pages: int,
) -> int:
    total_new = 0
    for sort in sorts:
        choice = SORT_CHOICES[sort]
        empty_streak = 0
        for page in range(1, max_pages + 1):
            ok, msg, res = search_with_retry(api, tag, page, choice)
            if not ok or not res:
                print(f"  [{tag}] sort={sort} page={page} FAILED: {str(msg)[:100]}")
                break
            data = res.get("data") or {}
            items = data.get("items") or []
            new_count = 0
            for item in items:
                if item.get("model_type") != "note":
                    continue
                if upsert_note(conn, item, tag, sort, page):
                    new_count += 1
            total_new += new_count
            conn.execute(
                """
                INSERT INTO crawl_state (tag, sort, last_page, has_more, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tag, sort) DO UPDATE SET
                    last_page = excluded.last_page,
                    has_more = excluded.has_more,
                    updated_at = excluded.updated_at
                """,
                (tag, sort, page, 1 if data.get("has_more") else 0, now()),
            )
            conn.commit()
            print(
                f"  [{tag}] sort={sort:22} page={page:3} items={len(items):2} "
                f"new={new_count:2} total_new={total_new:4} has_more={data.get('has_more')}"
            )
            empty_streak = empty_streak + 1 if new_count == 0 else 0
            if not data.get("has_more") or not items:
                break
            if empty_streak >= max_empty_pages:
                print(f"  [{tag}] sort={sort} 连续 {empty_streak} 页无新笔记，停止")
                break
            time.sleep(sleep_s)
    return total_new


def fetch_details(
    api: XHS_Apis,
    conn: sqlite3.Connection,
    tag: str,
    sleep_s: float,
    limit: int = 20,
) -> int:
    rows = conn.execute(
        """
        SELECT n.note_id, n.url FROM notes n
        JOIN note_tags t ON t.note_id = n.note_id
        WHERE t.tag = ? AND (n.detail_json IS NULL OR n.detail_json = '')
        LIMIT ?
        """,
        (tag, limit),
    ).fetchall()
    done = 0
    for note_id, url in rows:
        ok, msg, info = api.get_note_info(url)
        if ok and info:
            conn.execute(
                "UPDATE notes SET detail_json = ?, last_seen_at = ? WHERE note_id = ?",
                (json.dumps(info, ensure_ascii=False), now(), note_id),
            )
            done += 1
            conn.commit()
            print(f"  [detail] {note_id} OK ({done}/{len(rows)})")
        else:
            print(f"  [detail] {note_id} FAILED: {str(msg)[:100]}")
        time.sleep(sleep_s)
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description="小红书 tag 批量采集")
    parser.add_argument("--tags", required=True, help="逗号分隔的 tag，如 '#北京赏秋,#露营'")
    parser.add_argument(
        "--sorts",
        default="general,time_descending,popularity_descending",
        help=f"逗号分隔，可选: {','.join(SORT_CHOICES)}",
    )
    parser.add_argument("--max-pages", type=int, default=30, help="每个排序最多翻多少页")
    parser.add_argument("--sleep", type=float, default=0.8, help="请求间隔秒数")
    parser.add_argument("--max-empty-pages", type=int, default=3, help="连续无新笔记多少页后停止")
    parser.add_argument("--detail", action="store_true", help="额外拉取笔记详情")
    parser.add_argument("--detail-limit", type=int, default=20, help="每个 tag 最多补多少条详情")
    parser.add_argument("--db", default=str(ROOT / "data/xhs_tags.db"), help="SQLite 路径")
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    sorts = [s.strip() for s in args.sorts.split(",") if s.strip()]
    for s in sorts:
        if s not in SORT_CHOICES:
            raise SystemExit(f"未知排序: {s}")

    load_dotenv(ROOT / ".env")
    cookies = os.getenv("COOKIES")
    if not cookies:
        raise SystemExit("请先在 .env 中填写 COOKIES")

    conn = init_db(Path(args.db))
    auth = XHSPcAuth.from_cookie(cookies)
    try:
        api = XHS_Apis(auth).bootstrap()
        grand_total = 0
        for tag in tags:
            print(f"\n=== tag: {tag} ===")
            grand_total += crawl_tag(
                api, conn, tag, sorts, args.max_pages, args.sleep, args.max_empty_pages
            )
            if args.detail:
                fetch_details(api, conn, tag, args.sleep, args.detail_limit)
        count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        print(f"\n完成：本次新增 {grand_total} 条，数据库共 {count} 条笔记 -> {args.db}")
    finally:
        auth.close()
        conn.close()


if __name__ == "__main__":
    main()
