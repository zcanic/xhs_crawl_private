# scripts

本地研究与采集脚本。所有脚本都以仓库根目录为基准定位 `.env`、`data/` 和
`research/`，可以从任意工作目录运行。

首次使用前：

```bash
cp .env.example .env      # 填入 COOKIES，或运行登录脚本自动写入
```

## lanzhou/ — 兰州马拉松研究流水线

| 脚本 | 用途 |
| --- | --- |
| `audit_lanzhou.py` | 小规模实时采集与字段/覆盖审计 |
| `coverage_lanzhou.py` | baseline / 交叉关键词 / tag-BFS 搜索覆盖实验 |
| `complete_lanzhou_details.py` | 续采冻结的 551 条候选详情 |
| `diagnose_lanzhou_access.py` | 单次登录态与中断帖诊断，不循环重试 |
| `export_lanzhou_reading.py` | 导出已采集正文，供逐条阅读 |
| `collect_lanzhou_images.py` | 保存笔记返回的图片 URL 对应图片 |
| `assemble_lanzhou_annotations.py` | 汇总逐条阅读标注 |
| `analyze_lanzhou_manual_queries.py` | 将人工判断与冻结检索集关联 |

```bash
.venv/bin/python scripts/lanzhou/audit_lanzhou.py --pages 2
.venv/bin/python scripts/lanzhou/export_lanzhou_reading.py
```

## tools/ — 抓包、登录与接口探测

| 脚本 | 用途 |
| --- | --- |
| `login_qr.py` / `login_phone.py` | 登录并把 Cookie 写入仓库根目录 `.env` |
| `test_crawl.py` | 最小搜索 + 详情抓取测试 |
| `capture_topic.py` / `capture_topic_headed.py` | 用 Chrome CDP 抓取话题页 XHR |
| `capture_url.py` | 打开指定 URL 并打印 API 请求 |
| `extract_topic_links.py` | 从笔记页话题链接提取真实 `page_id` |
| `list_assets.py` | 列出话题页加载的 JS 资源 |
| `probe_topic_api.py` | 探测话题笔记列表接口路径 |

```bash
.venv/bin/python scripts/tools/login_qr.py
.venv/bin/python scripts/tools/test_crawl.py 露营 10
.venv/bin/python scripts/tools/capture_url.py "https://www.xiaohongshu.com/..."
```

## tag_crawler.py — 通用标签采集器

```bash
.venv/bin/python scripts/tag_crawler.py --tags "#露营" --detail
```

默认写入 `data/xhs_tags.db`，可用 `--db` 指定其他 SQLite 路径。
