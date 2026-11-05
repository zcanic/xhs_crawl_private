"""Resume detail collection for the frozen 551-candidate search union; no labeling."""
import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
from loguru import logger
from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth
from audit_lanzhou import quiet_call


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sleep',type=float,default=15)
    p.add_argument('--initial-delay',type=float,default=0)
    p.add_argument('--batch-size',type=int,default=20)
    p.add_argument('--batch-pause',type=float,default=180)
    a=p.parse_args()
    if min(a.sleep,a.initial_delay,a.batch_pause)<0 or a.batch_size<1:p.error('delays must be nonnegative and batch-size positive')
    os.chdir(ROOT)
    source=ROOT/'data/lanzhou_coverage/20261029T113955Z'
    original=json.loads((source/'report.json').read_text())
    ids=sorted({i for r in original['runs'] if r['strategy']!='repeat' for i in r['ids']})
    out=source/'detail_completion';out.mkdir(mode=0o700,exist_ok=True)
    target=out/'crawl.db'
    if not target.exists():
        src=sqlite3.connect((source/'crawl.db').as_uri()+'?mode=ro',uri=True)
        dst=sqlite3.connect(target);src.backup(dst);dst.close();src.close()
    db=sqlite3.connect(target)
    db.execute('CREATE TABLE IF NOT EXISTS detail_jobs(note_id TEXT PRIMARY KEY,status TEXT NOT NULL,attempts INTEGER DEFAULT 0,api_code TEXT,updated_at TEXT)')
    now=lambda:datetime.now(timezone.utc).isoformat(timespec='seconds')
    for nid in ids:
        row=db.execute('SELECT detail_json FROM notes WHERE note_id=?',(nid,)).fetchone()
        assert row is not None,'Frozen search union must exist in local DB'
        ok=False
        if row[0]:
            res=json.loads(row[0]);items=(res.get('data') or {}).get('items') or []
            ok=any((i.get('id') or (i.get('note_card') or {}).get('note_id'))==nid and i.get('note_card') for i in items)
        db.execute('INSERT OR IGNORE INTO detail_jobs(note_id,status,updated_at) VALUES(?,?,?)',(nid,'success' if ok else 'pending',now()))
    db.commit()
    status={'scope':'frozen 551 candidate IDs; not platform-wide exhaustive search','total':len(ids),'started_at':now()}
    status['pacing']={'interval_seconds':a.sleep,'batch_size':a.batch_size,'batch_pause_seconds':a.batch_pause}
    def checkpoint(state):
        counts=dict(db.execute('SELECT status,count(*) FROM detail_jobs GROUP BY status'))
        status.update(state=state,counts=counts,updated_at=now())
        tmp=out/'status.json.tmp';tmp.write_text(json.dumps(status,ensure_ascii=False,indent=2));tmp.replace(out/'status.json')
        print(json.dumps(status,ensure_ascii=False),flush=True)
    logger.remove();auth=None;fail_streak=0
    try:
        if a.initial_delay:
            status['cooldown_seconds']=a.initial_delay
            checkpoint('cooling_down')
            time.sleep(a.initial_delay)
        checkpoint('running')
        auth=quiet_call(XHSPcAuth.from_cookie,dotenv_values(ROOT/'.env')['COOKIES'])
        api=quiet_call(XHS_Apis(auth).bootstrap)
        jobs=db.execute("SELECT note_id FROM detail_jobs WHERE status NOT IN ('success','browser_text') ORDER BY note_id").fetchall()
        for job_index,(nid,) in enumerate(jobs):
            url=db.execute('SELECT url FROM notes WHERE note_id=?',(nid,)).fetchone()[0]
            success=False;code=None
            for attempt in range(2):
                db.execute('UPDATE detail_jobs SET attempts=attempts+1 WHERE note_id=?',(nid,));db.commit()
                ok,_msg,res=quiet_call(api.get_note_info,url)
                code=(res or {}).get('code')
                items=((res or {}).get('data') or {}).get('items') or []
                matched=next((i for i in items if (i.get('id') or (i.get('note_card') or {}).get('note_id'))==nid and i.get('note_card')),None)
                if ok and code in (0,None) and matched:
                    db.execute('UPDATE notes SET detail_json=?,last_seen_at=? WHERE note_id=?',(json.dumps(res,ensure_ascii=False),now(),nid))
                    success=True;break
                # Do not retry explicit authentication / captcha / rate-limit responses.
                msg=str(_msg).lower()
                event={'checked_at':now(),'note_id':nid,'success_flag':ok,'api_code':code,
                       'message':str(_msg)[:400],'matching_detail':bool(matched)}
                with (out/'detail_errors.jsonl').open('a') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
                status['last_error']=event
                if code==300013 or any(x in msg for x in ['captcha','验证码','频繁','登录','risk','rate limit']):
                    status['stop_reason']='rate_limited' if code==300013 or '频繁' in msg else 'authentication_or_challenge'
                    break
                if attempt==0:time.sleep(3)
            db.execute('UPDATE detail_jobs SET status=?,api_code=?,updated_at=? WHERE note_id=?',('success' if success else 'failed',str(code),now(),nid));db.commit()
            fail_streak=0 if success else fail_streak+1
            checkpoint('running')
            if status.get('stop_reason') or fail_streak>=3:
                status.setdefault('stop_reason','three consecutive detail failures; stopped for diagnosis')
                checkpoint('stopped');return 2
            if (job_index+1)%a.batch_size==0 and job_index+1<len(jobs):
                checkpoint('batch_pause');time.sleep(a.batch_pause)
            else:time.sleep(a.sleep)
        failed=db.execute("SELECT count(*) FROM detail_jobs WHERE status NOT IN ('success','browser_text')").fetchone()[0]
        checkpoint('complete' if not failed else 'partial')
        return 0 if not failed else 2
    except Exception as exc:
        status['error_type']=type(exc).__name__;checkpoint('stopped');return 2
    finally:
        if auth is not None:quiet_call(auth.close)
        db.close()


if __name__=='__main__':raise SystemExit(main())
