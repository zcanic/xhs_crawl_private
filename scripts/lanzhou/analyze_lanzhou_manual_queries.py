"""Join manual text judgments to frozen query sets; never infer or assign labels."""
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT=ROOT/'research/lanzhou_pilot'
SOURCE=ROOT/'data/lanzhou_coverage/20261029T113955Z/report.json'


def main():
    report=json.loads(SOURCE.read_text())
    judgments=json.loads((OUT/'annotations_all_text_v1.json').read_text())
    by_id={r['note_id']:r for r in judgments}
    posts={p['note_id']:p for p in [json.loads(s) for s in
        (ROOT/'data/lanzhou_coverage/20261029T113955Z/detail_completion/reading/posts.jsonl').read_text().split('\n') if s]}
    runs=[r for r in report['runs'] if r['strategy']!='repeat']
    groups={name:set().union(*(set(r['ids']) for r in runs if r['strategy']==name))
            for name in ['baseline','crossed','bfs']}
    union=set().union(*groups.values())
    assert len(union)==551 and set(by_id)<=union
    baseline=groups['baseline']
    con=sqlite3.connect(ROOT/'data/lanzhou_coverage/20261029T113955Z/detail_completion/crawl.db')
    jobs={n:s for n,s in con.execute('select note_id,status from detail_jobs')}
    con.close()
    failed={n for n,s in jobs.items() if s=='failed'}
    pending={n for n in union if jobs.get(n) not in ('success','browser_text','failed')}
    def summarize(ids):
        labeled=ids & by_id.keys()
        targets={n for n in labeled if by_id[n]['scope_relevance']=='目标赛事相关'}
        incidental={n for n in labeled if by_id[n]['scope_relevance']=='顺带提及目标赛事'}
        tourism={n for n in targets if by_id[n]['text_only_level']=='L2'}
        return dict(candidates=len(ids),read=len(labeled),unread=len(ids-labeled),
            unavailable_details=len(ids&failed),pending_details=len(ids&pending),
            target=len(targets),incidental=len(incidental),target_L2=len(tourism),
            target_share_of_read=round(len(targets)/len(labeled),6) if labeled else None,
            relations=dict(Counter(by_id[n]['scope_relevance'] for n in labeled)))
    group_rows=[]
    for name,ids in groups.items():
        row=dict(strategy=name,search_calls=sum(len(r['pages']) for r in runs if r['strategy']==name),**summarize(ids))
        row['outside_baseline']=summarize(ids-baseline)
        others=set().union(*(v for k,v in groups.items() if k!=name))
        row['exclusive_to_strategy']=summarize(ids-others)
        group_rows.append(row)
    query_rows=[dict(query=r['query'],strategy=r['strategy'],depth=r['depth'],
        search_calls=len(r['pages']),**summarize(set(r['ids'])),
        outside_baseline=summarize(set(r['ids'])-baseline)) for r in runs]
    for row,run in zip(query_rows,runs):
        terms=[x[1:] for x in run['query'].split() if x.startswith('#')]
        if not terms:continue
        available=set(run['ids']) & posts.keys()
        nonempty={n for n in available if posts[n]['tag_names']}
        matches={n for n in nonempty if set(terms)<=set(posts[n]['tag_names'])}
        row['literal_tag_conjunction']=dict(required_exact_tags=terms,details_available=len(available),
            nonempty_tag_lists=len(nonempty),empty_or_missing_tag_lists=len(available-nonempty),
            all_tags_present=len(matches),not_all_tags_present_in_nonempty_lists=len(nonempty-matches),
            manually_target_related=len(matches & by_id.keys() & {n for n,r in by_id.items() if r['scope_relevance']=='目标赛事相关'}),
            meaning='仅核对已采集标签字段严格共现，不自动赋予语义相关性标签')
    relevant_union={n for n in union & by_id.keys() if by_id[n]['scope_relevance']=='目标赛事相关'}
    overlaps=[]
    for i,a in enumerate(groups):
        for b in list(groups)[i+1:]:
            ra=groups[a]&relevant_union;rb=groups[b]&relevant_union
            overlaps.append(dict(a=a,b=b,raw_intersection=len(groups[a]&groups[b]),
                raw_jaccard=len(groups[a]&groups[b])/len(groups[a]|groups[b]),
                read_target_intersection=len(ra&rb),read_target_union=len(ra|rb),
                read_target_jaccard=len(ra&rb)/len(ra|rb) if ra|rb else None))
    result=dict(scope='冻结551条候选的单人逐读正文判断；包含多年份、关联系列活动；非平台召回率、非正式比例样本',
        annotation_complete=len(by_id)==551,
        all_available_text_annotated=posts.keys()<=by_id.keys(),
        all_candidates_attempted=not pending,union=summarize(union),strategies=group_rows,
        queries=query_rows,overlaps=overlaps,
        limitations=['搜索接口含多个#词不等于平台严格执行标签逻辑AND，需逐读检验',
          '基线/交叉/BFS请求量分别8/16/32，不能仅凭总新增数量评价效率或因果优劣',
          '正文无相关证据不代表未读媒体中也无相关信息；媒体另列待核验',
          '未知标签总体分母，观察池内覆盖份额不可解释为全平台覆盖率',
          '搜索页均仍有has_more；完成551条详情不等于搜索结果已穷尽',
          '跨查询重复既受检索排序又受平台召回机制影响，不满足简单独立捕获假设'])
    (OUT/'manual_query_yield.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    names={'baseline':'基线','crossed':'交叉检索','bfs':'BFS扩展'}
    md=['# 逐读标注后的检索有效性',
        f"已逐读 {len(by_id)}/551 条；详情无法取得 {len(failed)} 条，尚待采集 {len(pending)} 条。{'本候选池全部正文判断已齐。' if result['annotation_complete'] else '可用正文已全部逐读，无法取得的内容保留缺失、不作判断。' if result['all_candidates_attempted'] and result['all_available_text_annotated'] else '目前是中途结果，未读条目不能当作不相关。'}",
        '“目标相关”是手写相关性标签；L2只在目标相关内部计数。顺带提及单列，其他城市的文旅不会计入兰州L2。正文无证据的媒体帖仍保留待核验。',
        '| 策略 | 请求数 | 候选去重 | 已逐读 | 目标相关 | 顺带提及 | 目标L2 | 基线以外候选 | 其中目标相关 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in group_rows:
        md.append(f"| {names[r['strategy']]} | {r['search_calls']} | {r['candidates']} | {r['read']} | {r['target']} | {r['incidental']} | {r['target_L2']} | {r['outside_baseline']['candidates']} | {r['outside_baseline']['target']} |")
    md+=['','各策略集合重叠，行间不能相加。基线以外是集合差，不意味着它在无限加深基线后仍无法获得。','',
         '| 查询 | 深度 | 候选 | 已读 | 目标相关 | 目标L2 | 基线以外目标相关 | 标签严格共现/非空标签列表 |',
         '| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for r in query_rows:
        c=r.get('literal_tag_conjunction')
        tag_check=f"{c['all_tags_present']}/{c['nonempty_tag_lists']}" if c else '不适用'
        md.append(f"| {r['query']} | {r['depth']} | {r['candidates']} | {r['read']} | {r['target']} | {r['target_L2']} | {r['outside_baseline']['target']} | {tag_check} |")
    md+=['','标签字段共现仅按返回tag_names逐字核对，不用于替代逐读相关性判断。分母只纳入非空列表，空列表不据此判定作者无标签；字段不完整或作者未标某词均会影响结果，不能独凭此推断搜索内部算法。']
    md+=['','解释边界：']+['- '+x for x in result['limitations']]
    (OUT/'manual_query_yield.md').write_text('\n'.join(md[:1])+'\n\n'+'\n\n'.join(md[1:3])+'\n\n'+'\n'.join(md[3:])+'\n')
    print(json.dumps(dict(annotation_complete=result['annotation_complete'],union=result['union'],strategies=group_rows),ensure_ascii=False))


if __name__=='__main__':main()
