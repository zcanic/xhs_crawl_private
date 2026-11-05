# 兰马研究台（本机只读面板）

访问：http://127.0.0.1:8787

读取现有逐读标注、全文、检索评估及媒体待办。刷新按钮重新读取本机结果文件，不会启动爬虫或修改标签。图片预览仅使用已保存文件，视频通过原帖查看。筛选结果可导出JSON。

本机服务由用户级systemd管理，不依赖聊天保持运行：

```bash
systemctl --user start xhs-lanzhou-panel
systemctl --user status xhs-lanzhou-panel
systemctl --user stop xhs-lanzhou-panel
```

目前只启动服务，没有设置开机自启。也可手动运行：

```bash
python /home/zcanic/文件/xhs_crawl_try/Spider_XHS/web_panel/server.py --port 8787
```

仅监听127.0.0.1；不公开到局域网或互联网。不将项目目录作为静态根目录，接口只提供面板所需的研究数据和指定本地图片。
