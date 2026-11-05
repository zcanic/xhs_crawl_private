"""Save image URLs already returned with collected notes; never assign labels."""
import argparse
import json
import time
import urllib.request
from pathlib import Path
from datetime import datetime,timezone

ROOT = Path(__file__).resolve().parents[2]
BASE=ROOT/'data/lanzhou_coverage/20261029T113955Z/detail_completion'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reading-ids',nargs='+',default=[])
    p.add_argument('--all-normal',action='store_true')
    p.add_argument('--sleep',type=float,default=2)
    a=p.parse_args()
    if not a.reading_ids and not a.all_normal:p.error('choose reading-ids or all-normal')
    rs=[json.loads(s) for s in (BASE/'reading/posts.jsonl').read_text().split('\n') if s]
    fail_streak=0
    for r in rs:
        if r['reading_id'] not in a.reading_ids and not (a.all_normal and r['type']=='normal'):continue
        out=BASE/'media'/r['note_id'];out.mkdir(parents=True,exist_ok=True,mode=0o700)
        manifest=[]
        for i,url in enumerate(r['image_urls'],1):
            dest=out/f'image_{i:02d}.webp'
            entry={'ordinal':i,'source_url':url,'path':str(dest),'reviewed':False}
            already_saved=dest.exists() and dest.stat().st_size
            if already_saved:
                entry.update(status='saved',bytes=dest.stat().st_size)
            else:
                try:
                    req=urllib.request.Request(url,headers={'Referer':'https://www.xiaohongshu.com/'})
                    with urllib.request.urlopen(req,timeout=25) as response:
                        mime=response.headers.get('Content-Type','')
                        data=response.read(20_000_001)
                    if not mime.startswith('image/') or len(data)>20_000_000:raise ValueError('unexpected_image_response')
                    dest.write_bytes(data)
                    entry.update(status='saved',bytes=len(data),content_type=mime)
                except Exception as exc:
                    entry.update(status='failed',error_type=type(exc).__name__,http_code=getattr(exc,'code',None))
            manifest.append(entry)
            (out/'manifest.json').write_text(json.dumps({'note_id':r['note_id'],'reading_id':r['reading_id'],
                'expected':r['image_count'],'images':manifest,'updated_at':datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2))
            print(json.dumps({'reading_id':r['reading_id'],'ordinal':i,'status':entry['status'],
                'http_code':entry.get('http_code'),'path':str(dest) if entry['status']=='saved' else None}),flush=True)
            if entry['status']=='failed':
                fail_streak+=1
                if fail_streak>=3:return
                break
            fail_streak=0
            if not already_saved:time.sleep(a.sleep)


if __name__=='__main__':main()
