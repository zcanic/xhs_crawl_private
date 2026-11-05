"""Local, read-only research panel. Run with Python's standard library."""
import argparse
import json
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PANEL = Path(__file__).resolve().parent
ROOT = PANEL.parent
RESEARCH = ROOT / 'research/lanzhou_pilot'
BASE = ROOT / 'data/lanzhou_coverage/20261029T113955Z/detail_completion'


def read_json(path):
    return json.loads(path.read_text())


def dataset():
    posts = {p['note_id']: p for p in (json.loads(s) for s in
             (BASE / 'reading/posts.jsonl').read_text().split('\n') if s)}
    annotations = read_json(RESEARCH / 'annotations_all_text_v1.json')
    rows = []
    for annotation in annotations:
        p = posts[annotation['note_id']]
        r = {k: v for k, v in annotation.items() if k != 'full_text_file'}
        r.update(body=p['body'], tags=p['tag_names'], author=p.get('author_name'),
                 source_url=p['source_url'], source=p.get('text_source', 'detail_api'))
        folder = BASE / 'media' / p['note_id']
        r['local_images'] = [i for i in range(1, p['image_count'] + 1)
                             if (folder / f'image_{i:02d}.webp').is_file()]
        rows.append(r)
    return dict(posts=rows, summary=read_json(RESEARCH / 'annotation_progress.json'),
                queries=read_json(RESEARCH / 'manual_query_yield.json'),
                exceptions=read_json(RESEARCH / 'collection_exceptions.json'),
                media_pending=read_json(RESEARCH / 'media_review_pending.json'),
                updated_at=datetime.fromtimestamp((RESEARCH / 'annotations_all_text_v1.json').stat().st_mtime).astimezone().isoformat())


class Handler(BaseHTTPRequestHandler):
    def send(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/data':
            try:
                payload = json.dumps(dataset(), ensure_ascii=False).encode()
                self.send(payload, 'application/json; charset=utf-8')
            except (OSError, ValueError, KeyError):
                self.send(b'{"error":"Data files are unavailable or incomplete"}', 'application/json', 503)
            return
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path in files:
            name, mime = files[path]
            self.send((PANEL / name).read_bytes(), mime)
            return
        match = re.fullmatch(r'/media/([0-9a-f]{24})/([0-9]{1,3})', path)
        if match:
            image = BASE / 'media' / match[1] / f'image_{int(match[2]):02d}.webp'
            if image.is_file():
                self.send(image.read_bytes(), 'image/webp')
                return
        if path == '/health':
            self.send(b'{"status":"ok"}', 'application/json')
            return
        self.send(b'Not found', 'text/plain', 404)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Local: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()
