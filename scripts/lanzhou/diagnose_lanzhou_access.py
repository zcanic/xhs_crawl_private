"""One login-state request and one interrupted-note request; no retry loop."""
import json
import sqlite3
import argparse
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
OUT=ROOT/'data/lanzhou_coverage/20261029T113955Z/detail_completion'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control',action='store_true')
    args=parser.parse_args()
    logger.remove()
    report={'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    auth=None
    try:
        auth=quiet_call(XHSPcAuth.from_cookie,dotenv_values(ROOT/'.env')['COOKIES'])
        api=XHS_Apis(auth)
        ok,msg,res=quiet_call(api.get_user_me)
        report['login_check']={'success':ok,'code':(res or {}).get('code'),'message':str(msg)[:400],
            'user_id_present':bool(((res or {}).get('data') or {}).get('user_id'))}
        uid=((res or {}).get('data') or {}).get('user_id')
        if ok and uid:
            auth.set_user_id(uid)
            with sqlite3.connect((OUT/'crawl.db').as_uri()+'?mode=ro',uri=True) as db:
                query="SELECT n.note_id,n.url FROM notes n JOIN detail_jobs j USING(note_id) WHERE j.status='success' ORDER BY n.note_id DESC LIMIT 1" if args.control else "SELECT n.note_id,n.url FROM notes n JOIN detail_jobs j USING(note_id) WHERE j.status!='success' ORDER BY n.note_id LIMIT 1"
                nid,url=db.execute(query).fetchone()
            ok,msg,res=quiet_call(api.get_note_info,url)
            items=((res or {}).get('data') or {}).get('items') or []
            report['interrupted_note_check']={'note_id':nid,'success':ok,'code':(res or {}).get('code'),
                'message':str(msg)[:400],'matching_detail':any((i.get('id') or (i.get('note_card') or {}).get('note_id'))==nid and bool(i.get('note_card')) for i in items),
                'data_keys':list(((res or {}).get('data') or {}).keys())}
            report['comparison_type']='previously_successful_control' if args.control else 'interrupted_note'
    except Exception as exc:
        report['exception_type']=type(exc).__name__
    finally:
        if auth is not None:quiet_call(auth.close)
    (OUT/('access_control_diagnosis.json' if args.control else 'access_diagnosis.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
