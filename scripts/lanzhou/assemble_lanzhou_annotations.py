"""Assemble authored reading decisions; this script does not assign labels."""
import json
import html
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'research/lanzhou_pilot'
BASE = ROOT / 'data/lanzhou_coverage/20261029T113955Z/detail_completion'


def main():
    posts = [json.loads(x) for x in (BASE/'reading/posts.jsonl').read_text().split('\n') if x]
    by_id = {p['note_id']: p for p in posts}
    old = json.loads((OUT/'annotations_text_v1.json').read_text())
    queue = json.loads((OUT/'reading_queue.json').read_text())
    queued = {p['note_id'] for p in old + queue}
    queue.extend(p for p in posts if p['note_id'] not in queued)
    (OUT/'reading_queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2))
    records = [dict(p, annotation_batch='initial34') for p in old]
    for shard in sorted(OUT.glob('manual_batch2_*.json')):
        for index, relation, level, quote, reason, facet, confidence, review in json.loads(shard.read_text()):
            p = queue[index-1]
            records.append(dict(note_id=p['note_id'], assessor='Codex逐条阅读初标，未进行独立人工复核',
                reading_order=34+index, annotation_batch=shard.name, queue_index=index,
                title=p['title'], scope_relevance=relation, text_only_level=level,
                evidence_quote=quote, reason=reason, content_facet=facet, confidence=confidence,
                needs_review=review, body_read_complete=True, images_reviewed=False,
                video_reviewed=False, comments_reviewed=False, final_level=None))
    records.sort(key=lambda r:r['reading_order'])
    quality=json.loads((OUT/'manual_reading_quality.json').read_text()) if (OUT/'manual_reading_quality.json').exists() else {}
    final_decisions=[]
    for shard in sorted(OUT.glob('manual_final_*.json')):final_decisions.extend(json.loads(shard.read_text()))
    compact=OUT/'manual_media_rows.jsonl'
    by_reading={p['reading_id']:p for p in posts}
    if compact.exists():
        for line in compact.read_text().split('\n'):
            if not line:continue
            rid,relation,level,year,notes,evidence,reason,confidence,followup=json.loads(line)
            p=by_reading[rid]
            assert p['type']=='normal' and len(notes)==p['image_count']
            final_decisions.append(dict(note_id=p['note_id'],reading_id=rid,scope_relevance=relation,
                event_year_evidence=year,final_level=level,all_returned_text_read=True,
                expected_images=p['image_count'],reviewed_image_ordinals=list(range(1,len(notes)+1)),
                video_review='not_applicable',comments_review='not_reviewed',image_notes=notes,
                evidence=[dict(source='body_and_all_images',observation=evidence)],reason=reason,
                confidence=confidence,research_note=followup,
                assessor='Codex逐条阅读全文并逐张看图，未经独立双人复核'))
    finals={r['note_id']:r for r in final_decisions}
    assert len(finals)==len(final_decisions),'duplicate final decision'
    seen=set()
    for r in records:
        assert r['note_id'] not in seen, r['note_id']
        seen.add(r['note_id'])
        p=by_id[r['note_id']]
        assert r['evidence_quote'] in p['title']+'\n'+p['body'], (r['reading_order'],r['evidence_quote'])
        r.update(reading_id=p['reading_id'], post_type=p['type'], image_count=p['image_count'],
                 queries=p['queries'], full_text_file=str(BASE/'reading'/f"{p['reading_id']}_{p['note_id']}.md"))
        r['text_source']=p.get('text_source','detail_api')
        r['returned_text_read_complete']=True
        r['source_body_completeness']='not_compared_with_page'
        if r['note_id'] in quality:
            q=quality[r['note_id']]
            r['source_body_completeness']=q['source_body_completeness']
            r['body_read_complete']=q.get('body_read_complete',True)
            r['reading_quality_note']=q['reason']
        peers=[x['note_id'] for x in posts if x['note_id']!=r['note_id'] and
               x['title']==p['title'] and x['body']==p['body'] and p['title']+'\n'+p['body']!='\n']
        r['exact_title_body_duplicates']=peers
        if r['note_id'] in finals:
            f=finals[r['note_id']]
            assert f['all_returned_text_read']
            assert f['expected_images']==p['image_count']
            assert sorted(f['reviewed_image_ordinals'])==list(range(1,p['image_count']+1))
            assert p['type']!='video' or f['video_review']=='fully_reviewed'
            assert r['source_body_completeness']!='suspected_incomplete'
            r.update(final_level=f['final_level'],images_reviewed=True,
                video_reviewed=f['video_review']=='fully_reviewed',final_scope_relevance=f['scope_relevance'],
                final_reason=f['reason'],final_evidence=f['evidence'],media_review_complete=True)
    summary=dict(collected=len(posts), individually_read_text=len(records),
        collected_text_unread=len(posts)-len(records), frozen_candidates=551,
        relevance=dict(Counter(r['scope_relevance'] for r in records)),
        target_text_levels=dict(Counter(r['text_only_level'] or '未定' for r in records if r['scope_relevance']=='目标赛事相关')),
        suspected_incomplete_count=sum(r['source_body_completeness']=='suspected_incomplete' for r in records),
        complete_post_annotations=len(finals), individually_reviewed_images=sum(len(f['reviewed_image_ordinals']) for f in final_decisions),
        scope='阅读顺序样本，无代表性；不是覆盖率、正式35条样本或双人编码结果',
        evidence='标题及可用正文逐条阅读全文；仅已单列整帖终标的媒体完成核验，其余媒体、评论及正文外折叠内容待核验')
    summary['requested_scope']='先完成全部正文逐条标注；未核验的图片和视频另列待办（用户已确认）'
    con=sqlite3.connect(BASE/'crawl.db')
    jobs={n:dict(status=s,attempts=a,api_code=c) for n,s,a,c in con.execute('select note_id,status,attempts,api_code from detail_jobs')}
    con.close()
    unavailable=[dict(note_id=n,**s) for n,s in jobs.items() if s['status']=='failed']
    summary['detail_unavailable']=len(unavailable)
    summary['browser_text_recovered']=sum(s['status']=='browser_text' for s in jobs.values())
    summary['detail_not_yet_attempted']=sum(s['status']=='pending' for s in jobs.values())
    exceptions=json.loads((OUT/'collection_exceptions.json').read_text()) if (OUT/'collection_exceptions.json').exists() else []
    exception_map={e['note_id']:e for e in exceptions}
    missing_md=['# 详情无法取得与未标注记录',
        '只有取得并完整读完的正文才作语义标注。接口返回不可展示时单列缺失，不以标题补标。',
        f'目前详情失败 {len(unavailable)} 条；尚待采集 {summary["detail_not_yet_attempted"]} 条。']
    for e in unavailable:
        manual=exception_map.get(e['note_id'],{})
        missing_md.extend([f"## {e['note_id']} · {manual.get('search_card_title','无可用详情')}",
            f"接口尝试 {e['attempts']} 次；错误码 {e['api_code']}。",
            manual.get('browser_check','尚无网页核验记录。'),
            manual.get('conclusion','详情未取得，不作内容判断。')])
    (OUT/'collection_exceptions.md').write_text('\n\n'.join(missing_md)+'\n')
    pending_media=[]
    for p in posts:
        if p['note_id'] in finals:continue
        if p['type']=='video' or p['image_count']:
            pending_media.append(dict(reading_id=p['reading_id'],note_id=p['note_id'],title=p['title'],
                media_type=p['type'],expected_images=p['image_count'] if p['type']=='normal' else 0,
                video_pending=p['type']=='video',text_annotation_complete=p['note_id'] in seen,
                status='待逐张核验' if p['type']=='normal' else '待完整视频核验；封面不能代替视频'))
    summary['media_pending_posts']=len(pending_media)
    summary['media_pending_images']=sum(p['expected_images'] for p in pending_media)
    summary['media_pending_videos']=sum(p['video_pending'] for p in pending_media)
    (OUT/'media_review_pending.json').write_text(json.dumps(pending_media,ensure_ascii=False,indent=2))
    media_md=['# 图片与视频待核验清单',
        '本轮按用户确认先完成正文标注。本清单不表示媒体已经阅读；下载文件也不等于核验。评论另行处理。',
        f"截至本次导出：{len(pending_media)} 条帖子待核验，含图文图片 {summary['media_pending_images']} 张、视频 {summary['media_pending_videos']} 段。另有 {551-len(posts)} 条详情尚未取得，媒体数量未知。已完成整帖图文核验 {len(finals)} 条单列保留。",
        '| 阅读编号 | 类型 | 图片数 | 标题 | 正文已逐读 |', '| --- | --- | ---: | --- | --- |']
    media_md.extend(f"| {p['reading_id']} | {'视频' if p['video_pending'] else '图文'} | {p['expected_images']} | {p['title'].replace('|','／').replace(chr(10),' ')} | {'是' if p['text_annotation_complete'] else '否'} |" for p in pending_media)
    (OUT/'media_review_pending.md').write_text('\n\n'.join(media_md[:3])+'\n\n'+'\n'.join(media_md[3:])+'\n')
    (OUT/'annotations_all_text_v1.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
    (OUT/'annotation_progress.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    md=['# 兰州马拉松候选逐条正文初标',
        f'已保存详情 {len(posts)}/551；已逐读初标 {len(records)} 条；已保存待读 {len(posts)-len(records)} 条。',
        f'本轮按用户确认，先完成全部正文逐条标注，未核验图片和视频另列待办。这是 Codex 逐条阅读初标，非双人盲标。另已保留整帖核验 {len(finals)} 条、逐张看图 {summary["individually_reviewed_images"]} 张；评论尚未全部读取。正文为空时“读完”仅表示已核对空文本，不表示看完视频。',
        '本批按读取顺序处理，混有跨年份和其他赛事，不用于估计总体覆盖率或正式样本比例。脚本仅汇总已写判断、检查引文并标记完全相同的标题正文，不自动分类。',
        '相关性计数：'+json.dumps(summary['relevance'],ensure_ascii=False)]
    articles=[]
    for r in records:
        p=by_id[r['note_id']]
        md.extend([f"## {r['reading_order']:03d} · {r['reading_id']} · {r['title'] or '无标题'}",
            f"帖子ID：{r['note_id']}；类型：{r['post_type']}。",
            f"相关性：{r['scope_relevance']}；正文层级：{r['text_only_level'] or '未定'}；置信度：{r['confidence']}。",
            '原文证据：'+json.dumps(r['evidence_quote'],ensure_ascii=False),
            '判断：'+r['reason'], '待复核：'+r['needs_review'],
            f"[保存的全文]({r['full_text_file']})"])
        if r.get('reading_quality_note'):md.append('正文完整性：'+r['reading_quality_note'])
        if r.get('media_review_complete'):md.extend(['整帖层级：'+str(r['final_level']), '整帖复核：'+r['final_reason']])
        if r['exact_title_body_duplicates']:md.append('标题正文完全重复的其他ID：'+', '.join(r['exact_title_body_duplicates']))
        h=lambda v:html.escape(str(v))
        articles.append(f"<article data-relation='{h(r['scope_relevance'])}' data-level='{h(r['text_only_level'] or '未定')}' data-type='{h(r['post_type'])}'><h2>{r['reading_order']:03d} · {h(r['reading_id'])} · {h(r['title'] or '无标题')}</h2><p>{h(r['note_id'])} · {h(r['scope_relevance'])} · 正文 {h(r['text_only_level'] or '未定')}</p><p>证据：{h(r['evidence_quote'])}</p><p>判断：{h(r['reason'])}</p><p>待复核：{h(r['needs_review'])}</p><details><summary>展开已保存正文全文</summary><pre>{h(p['body'] or '（空正文）')}</pre></details></article>")
    (OUT/'annotations_all_text_v1.md').write_text('\n\n'.join(md)+'\n')
    final_md=['# 整帖逐读标注（正文与全部图片/视频）',f'已完成 {len(finals)} 条；逐张读图 {summary["individually_reviewed_images"]} 张。由Codex单独判读，非独立双人编码。评论的读取另记，不影响是否已读完帖子本体。']
    for f in final_decisions:
        final_md.extend([f"## {f['reading_id']} · {by_id[f['note_id']]['title']}",f"ID：{f['note_id']}；层级：{f['final_level']}；相关性：{f['scope_relevance']}。",f['reason'],'年份证据：'+f['event_year_evidence']])
        final_md.extend('证据：'+json.dumps(e,ensure_ascii=False) for e in f['evidence'])
        final_md.extend(f"图片{i}：{s}" for i,s in enumerate(f['image_notes'],1))
        final_md.extend(['研究备注：'+f['research_note'],'评论状态：'+f['comments_review']])
    (OUT/'annotations_final_v2.md').write_text('\n\n'.join(final_md)+'\n')
    option=lambda x:'<option>'+html.escape(x)+'</option>'
    controls='<nav><label>相关性 <select id="relation"><option value="">全部</option>'+''.join(option(x) for x in summary['relevance'])+'</select></label> <label>正文层级 <select id="level"><option value="">全部</option>'+''.join(option(x) for x in ['L0','L1','L2','未定'])+'</select></label> <label>帖子类型 <select id="type"><option value="">全部</option><option value="normal">图文</option><option value="video">视频</option></select></label> <label>搜索全文 <input id="find" type="search" placeholder="标题、原文、判断或ID"></label><p id="shown" aria-live="polite"></p></nav>'
    filter_js='''<script>
    const controls=['relation','level','type','find'];
    function filter(){let count=0;const value=id=>document.getElementById(id).value;
      document.querySelectorAll('article').forEach(a=>{const visible=(!value('relation')||a.dataset.relation===value('relation'))&&(!value('level')||a.dataset.level===value('level'))&&(!value('type')||a.dataset.type===value('type'))&&a.textContent.toLowerCase().includes(value('find').toLowerCase());a.hidden=!visible;if(visible)count++;});
      document.getElementById('shown').textContent='当前显示 '+count+' 条；筛选仅使用已有手写判断，不生成新标签。';}
    controls.forEach(id=>document.getElementById(id).addEventListener('input',filter));filter();
    </script>'''
    (OUT/'annotations_review.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>兰马逐条正文初标</title><style>body{font:17px/1.7 sans-serif;max-width:1000px;margin:35px auto;padding:20px}article{margin:35px 0;border-bottom:1px solid #ccc;padding-bottom:25px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}nav{background:#f1f4f6;padding:15px;border-radius:10px}select,input{font:inherit;max-width:100%;margin:5px}label{display:inline-block}article[hidden]{display:none}</style><h1>逐条正文初标</h1><p>可用正文已读 '+str(len(records))+' 条；整帖媒体复核完成 '+str(len(finals))+' 条，其他媒体及评论尚未全部核验。非正式35条样本。本轮先完成正文，无法取得详情的记录另列缺失。</p>'+controls+''.join(articles)+filter_js+'</html>')
    status=json.loads((BASE/'status.json').read_text())
    diagnosis=json.loads((BASE/'access_diagnosis.json').read_text()) if (BASE/'access_diagnosis.json').exists() else {}
    check=diagnosis.get('interrupted_note_check',{})
    (BASE/'collection_status.md').write_text(f"# 详情补采状态\n\n冻结候选 551 条；成功 {len(posts)} 条；未完成 {551-len(posts)} 条。\n\n采集器状态：{status['state']}；停止原因：{status.get('stop_reason','无')}。最后记录时间（UTC）：{status['updated_at']}。\n\n单次诊断：登录检查 {diagnosis.get('login_check',{}).get('success','未执行')}；中断帖 code={check.get('code','未知')}，message={check.get('message','未知')}；诊断时间（UTC）{diagnosis.get('checked_at','未知')}。\n\n已逐条阅读并初标可用正文 {len(records)} 条；其余已保存待读 {len(posts)-len(records)} 条。发现疑似缺续文 {summary['suspected_incomplete_count']} 条。本轮按用户确认先完成正文；已另保留整帖图文核验 {len(finals)} 条、逐张读图 {summary['individually_reviewed_images']} 张，剩余媒体详见 research/lanzhou_pilot/media_review_pending.md。评论尚未全部核验。\n\n此完成率是冻结候选的详情获取进度，不是平台总体或相关帖覆盖率。\n")
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
