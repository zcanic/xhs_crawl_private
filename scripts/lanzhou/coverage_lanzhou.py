"""Bounded baseline / crossed-keyword / tag-BFS search coverage experiment."""
from __future__ import annotations
import itertools
import json
import os
import sqlite3
import time
from collections import Counter
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
from xhs_utils.xhs_pc import XHSPcAuth
from xhs_utils.xhs_util import generate_search_id
from tag_crawler import init_db, upsert_note
from audit_lanzhou import quiet_call, inspect_note
SORTS = {"general": 0, "latest": 1}


def metrics(a, b):
    return {"intersection": len(a & b), "union": len(a | b),
            "jaccard": len(a & b) / len(a | b) if a | b else None,
            "overlap_coefficient": len(a & b) / min(len(a), len(b)) if a and b else None,
            "only_a": len(a - b), "only_b": len(b - a)}


def summarize(runs):
    sets = {r["label"]: set(r["ids"]) for r in runs if r["strategy"] != "repeat"}
    strategies = {s: set().union(*(set(r["ids"]) for r in runs if r["strategy"] == s))
                  for s in ["baseline", "crossed", "bfs"]}
    union = set().union(*sets.values()) if sets else set()
    freq = Counter(i for ids in sets.values() for i in ids)
    unique = {s: len(v - set().union(*(w for t, w in strategies.items() if t != s)))
              for s, v in strategies.items()}
    # Average the marginal contribution over all strategy orders to avoid one fixed order.
    marginal = Counter()
    for order in itertools.permutations(strategies):
        seen = set()
        for s in order:
            marginal[s] += len(strategies[s] - seen) / 6
            seen |= strategies[s]
    seen, curve = set(), []
    for r in runs:
        if r["strategy"] == "repeat":
            continue
        ids = set(r["ids"])
        curve.append({"label": r["label"], "strategy": r["strategy"], "size": len(ids),
                      "new": len(ids - seen), "cumulative": len(seen | ids)})
        seen |= ids
    pairwise = [{"a": a, "b": b, **metrics(sets[a], sets[b])}
                for a, b in itertools.combinations(sets, 2)]
    repeats = []
    for r in runs:
        if r["strategy"] == "repeat":
            first = next(x for x in runs if x["label"] == r["repeat_of"])
            repeats.append({"first": first["label"], "repeat": r["label"],
                            **metrics(set(first["ids"]), set(r["ids"]))})
    return {"observed_union": len(union), "strategy_sizes": {k:len(v) for k,v in strategies.items()},
            "strategy_unique": unique, "average_marginal_contribution": dict(marginal),
            "strategy_pairs": [{"a": a, "b": b, **metrics(strategies[a], strategies[b])}
                               for a,b in itertools.combinations(strategies,2)],
            "incidence_histogram": dict(sorted(Counter(freq.values()).items())),
            "seen_once": sum(v == 1 for v in freq.values()), "accumulation": curve,
            "pairwise": pairwise, "repeat_checks": repeats,
            "union_capture_fraction": {s:len(v)/len(union) if union else None for s,v in strategies.items()}}


def run():
    os.chdir(ROOT)
    out = ROOT/'data'/'lanzhou_coverage'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, mode=0o700)
    db = init_db(out/'crawl.db')
    runs, details, edges, tried_tags = [], {}, [], set()
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "runs": runs,
              "bfs_edges": edges, "details": details, "detail_failures": []}
    def save():
        report['statistics'] = summarize(runs)
        (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    def search(api, strategy, query, depth=0, parent=None, repeat_of=None):
        label = f'{strategy}:{query}'
        r = {"label":label,"strategy":strategy,"query":query,"depth":depth,"parent":parent,
             "repeat_of":repeat_of,"ids":[],"pages":[],"started_at":datetime.now(timezone.utc).isoformat()}
        runs.append(r)
        for sort, choice in SORTS.items():
            sid = generate_search_id()
            for page in [1,2]:
                ok, _, res = quiet_call(api.search_note, query, page=page, sort_type_choice=choice, search_id=sid)
                data = (res or {}).get('data') or {}
                items = [x for x in data.get('items',[]) if x.get('model_type')=='note' and x.get('id') and x.get('note_card')]
                ids = [x['id'] for x in items]
                prev = set(r['ids'])
                r['pages'].append({'sort':sort,'page':page,'success':bool(ok),'code':(res or {}).get('code'),
                                   'has_more':data.get('has_more'),'ids':ids,'count':len(ids),'new_in_query':len(set(ids)-prev)})
                if not ok:
                    save()
                    raise RuntimeError('Search rejected; stopped rather than counting failure as exhausted search')
                for item in items:
                    upsert_note(db,item,query,sort,page)
                db.commit()
                r['ids']=sorted(prev|set(ids))
                save()
                print(f'{label} {sort} p{page}: {len(ids)} results / {len(r["ids"])} unique',flush=True)
                time.sleep(1.5)
                if not data.get('has_more') or not items:
                    break
        return r
    def detail(api, ids, limit):
        ids=[i for i in ids if i not in details and i not in {x['note_id'] for x in report['detail_failures']}]
        # Deterministic even spacing: avoids selecting only the first search result.
        if len(ids)>limit:
            ids=[ids[int(j*len(ids)/limit)] for j in range(limit)]
        for nid in ids:
            url=db.execute('select url from notes where note_id=?',(nid,)).fetchone()[0]
            ok,_,res=quiet_call(api.get_note_info,url)
            items=((res or {}).get('data') or {}).get('items') or []
            item=next((i for i in items if (i.get('id') or (i.get('note_card') or {}).get('note_id'))==nid),None)
            if ok and item and item.get('note_card'):
                details[nid]=inspect_note(nid,item['note_card'])
                db.execute('update notes set detail_json=? where note_id=?',(json.dumps(res,ensure_ascii=False),nid));db.commit()
            else:
                report['detail_failures'].append({'note_id':nid,'code':(res or {}).get('code')})
            save();time.sleep(1.5)
    def frontier():
        counts=Counter();sources={}
        excluded={'跑步','马拉松','跑步打卡','跑友圈','运动','跑步日常','跑步的意义','兰州马拉松','兰马'}
        for nid,n in details.items():
            text=n['title']+' '+n['description']+' '.join(n['tags'])
            if not ('兰州马拉松' in text or '兰马' in text):continue
            for tag in set(n['tags']):
                if tag in excluded or tag in tried_tags or len(tag)>18:continue
                counts[tag]+=1;sources.setdefault(tag,[]).append(nid)
        return [(tag,count,sources[tag]) for tag,count in sorted(counts.items(),key=lambda x:(-x[1],x[0]))[:3]]
    auth=None
    logger.remove()
    try:
        auth=quiet_call(XHSPcAuth.from_cookie,dotenv_values(ROOT/'.env')['COOKIES'])
        api=quiet_call(XHS_Apis(auth).bootstrap)
        for q in ['兰州马拉松','兰马']:
            search(api,'baseline',q)
        for seed,aspect in itertools.product(['兰州马拉松','兰马'],['赛记','攻略']):
            search(api,'crossed',f'#{seed} #{aspect}')
        first_ids=sorted(set().union(*(set(r['ids']) for r in runs)))
        detail(api,first_ids,16)
        for depth in [1,2]:
            level=frontier()
            if not level:break
            # A later BFS layer must contain newly discovered tags, not merely
            # previously known tags that missed the preceding top-three cutoff.
            tried_tags.update(t for n in details.values() for t in n['tags'])
            for tag,count,sources in level:
                tried_tags.add(tag)
                edge={'tag':tag,'depth':depth,'source_note_ids':sources,'frequency_in_detail_sample':count}
                edges.append(edge)
                r=search(api,'bfs',f'#兰州马拉松 #{tag}',depth=depth,parent=sources)
                detail(api,r['ids'],3)
        search(api,'repeat','兰州马拉松',repeat_of='baseline:兰州马拉松')
        # Depth is tag expansion depth; it does not imply chronological traversal.
        report['status']='completed'
    except Exception as e:
        report['status']='partial';report['error_type']=type(e).__name__
    finally:
        if auth is not None:quiet_call(auth.close)
        db.close();save()
    stats=report['statistics'];lines=['# 兰州马拉松：交叉搜索与标签 BFS 覆盖实验','',f'状态：{report["status"]}；观察并集：{stats["observed_union"]} 条。','',
        '|策略|独立结果|其它策略未发现|平均边际贡献|占观察并集|','|---|---:|---:|---:|---:|']
    for s,n in stats['strategy_sizes'].items():
        fraction=stats['union_capture_fraction'][s]
        lines.append(f'|{s}|{n}|{stats["strategy_unique"][s]}|{stats["average_marginal_contribution"].get(s,0):.1f}|{fraction:.1%}|' if fraction is not None else f'|{s}|0|0|0|不可计算|')
    lines+=['','## 策略间重叠','', '|A|B|交集|Jaccard：交/并|重叠系数：交/较小集合|','|---|---|---:|---:|---:|']
    for x in stats['strategy_pairs']:
        lines.append(f'|{x["a"]}|{x["b"]}|{x["intersection"]}|{x["jaccard"] if x["jaccard"] is not None else "NA"}|{x["overlap_coefficient"] if x["overlap_coefficient"] is not None else "NA"}|')
    lines+=['','## 累计发现','', '|查询|返回独立数量|相对之前新增|累计|','|---|---:|---:|---:|']
    lines += [f'|{x["label"]}|{x["size"]}|{x["new"]}|{x["cumulative"]}|' for x in stats['accumulation']]
    lines+=['','## 重复查询稳定性','',json.dumps(stats['repeat_checks'],ensure_ascii=False,indent=2),'',
      '## 方法与限制','',
      '每个查询同预算：综合、最新各最多2页；交叉项为2个赛事称谓×2个内容维度。组合词不是平台保证的标签AND操作。',
      'BFS按已获取详情里的真实共现标签扩展两层，每层最多3个标签；每个扩展查询最多补3条新详情。来源帖子和边保存在JSON。',
      '每页请求完成后至少间隔1.5秒；详情固定间隔1.5秒。失败即停止，不把风控或网络失败当作没有更多。',
      '平均边际贡献是对3种策略所有6种加入顺序的新增量取均值；策略预算不同且BFS依赖前序样本，不是随机对照实验。',
      '占观察并集仅是本次已发现集合的覆盖比例，不是平台真实召回率。搜索相关性不等于确切话题成员资格。',
      '低重叠说明可互补，也可能来自搜索漂移或无关结果；末尾重复基线用于量化漂移。高重叠不能证明全量。',
      '只有每条查询都采到停止且新增曲线趋平才有更强的饱和证据；本实验是固定页数试采。',
      '各查询非独立、非等概率捕获，因此不将捕获再捕获估计包装为总体数量或真实覆盖率。',
      '正文等详情样本和精确标签匹配标志保存在JSON；评论和媒体文件未下载。']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    print('REPORT_DIR='+str(out),flush=True)
    print(json.dumps({k:v for k,v in stats.items() if k not in ['pairwise','accumulation']},ensure_ascii=False),flush=True)


if __name__=='__main__':run()
