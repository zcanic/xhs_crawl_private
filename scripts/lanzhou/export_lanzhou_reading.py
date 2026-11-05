"""Export collected full text for one-by-one reading; never infer annotations."""
import html
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE=ROOT/'data/lanzhou_coverage/20261029T113955Z'


def main():
    source=json.loads((BASE/'report.json').read_text())
    ids=sorted({i for r in source['runs'] if r['strategy']!='repeat' for i in r['ids']})
    db=sqlite3.connect((BASE/'detail_completion/crawl.db').as_uri()+'?mode=ro',uri=True)
    out=BASE/'detail_completion/reading';out.mkdir(mode=0o700,exist_ok=True)
    rows=[];field_counts=Counter();types=Counter();unavailable=[];rendered=[]
    fallback_path=BASE/'detail_completion/browser_text_overrides.json'
    browser_text=json.loads(fallback_path.read_text()) if fallback_path.exists() else {}
    for index,nid in enumerate(ids,1):
        row=db.execute('SELECT detail_json,url FROM notes WHERE note_id=?',(nid,)).fetchone()
        if not row:unavailable.append(nid);continue
        response=json.loads(row[0]) if row[0] else {};items=(response.get('data') or {}).get('items') or []
        item=next((i for i in items if (i.get('id') or (i.get('note_card') or {}).get('note_id'))==nid),None)
        fallback=None
        if not item or not item.get('note_card'):
            fallback=browser_text.get(nid)
            if not fallback:unavailable.append(nid);continue
            card={'desc':fallback['body'],'title':fallback.get('title',''),'type':fallback['type'],
                  'user':{'nickname':fallback.get('author_name')},'tag_list':[{'name':x} for x in fallback['tag_names']]}
        else:card=item['note_card']
        body=card.get('desc') or '';title=card.get('title') or '';user=card.get('user') or {}
        tags=[t.get('name','') for t in card.get('tag_list',[]) if isinstance(t,dict)]
        queries=[r['query'] for r in source['runs'] if r['strategy']!='repeat' and nid in r['ids']]
        record={'reading_id':f'C-{index:03d}','note_id':nid,'title':title,'body':body,
                'type':card.get('type'),'author_name':user.get('nickname'),
                'published_at_raw':card.get('time'),'tag_names':tags,'queries':queries,
                'source_url':row[1],'image_count':len(card.get('image_list') or []),
                'image_urls':[i.get('url_default') or i.get('url_pre') for i in card.get('image_list',[])],
                'video_metadata':card.get('video'),'label_status':'unannotated',
                'image_review':'not_reviewed','video_review':'not_reviewed','comments_review':'not_collected'}
        record['text_source']='browser_visible_dom' if fallback else 'detail_api'
        if fallback:record['browser_text_evidence']=fallback['evidence']
        rows.append(record);types[card.get('type')]+=1
        for k,v in [('title',title),('body',body),('author_id',user.get('user_id')),('published_at',card.get('time')),('tags',tags)]:
            if v not in (None,'',[]):field_counts[k]+=1
        text=f'# {record["reading_id"]} {title or "（无标题）"}\n\n帖子 ID：{nid}\n\n类型：{card.get("type")}\n\n原始链接：{row[1]}\n\n## 正文全文\n\n{body}\n\n## 原始话题\n\n'+json.dumps(tags,ensure_ascii=False)+'\n\n## 检索来源\n\n'+'\n'.join(queries)+'\n\n## 阅读状态\n\n正文已保存；未作标注。图片、视频画面及评论尚未核验。C编号只是候选阅读序号，不是正式试采M编号。\n'
        text=text.replace('## 正文全文',f'文本来源：{record["text_source"]}\n\n## 正文全文',1)
        (out/f'{record["reading_id"]}_{nid}.md').write_text(text)
        rendered.append('<article id="'+record['reading_id']+'"><h2>'+html.escape(record['reading_id']+' '+(title or '（无标题）'))+'</h2><p>帖子ID：'+nid+'；类型：'+html.escape(str(card.get('type')))+'；未标注</p><a href="'+html.escape(row[1],quote=True)+'" target="_blank" rel="noopener noreferrer">原始帖子</a><pre>'+html.escape(body)+'</pre><p>话题：'+html.escape('、'.join(tags))+'</p></article>')
    db.close()
    with (out/'posts.jsonl').open('w') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    (out/'index.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>兰州马拉松候选全文阅读</title><style>body{font:17px/1.7 sans-serif;max-width:950px;margin:40px auto;padding:20px}article{margin-bottom:80px;border-bottom:1px solid #ddd}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}</style><h1>兰州马拉松候选全文阅读</h1><p>候选阅读序号 C 不代表正式试采样本。此页面仅呈现文本，不代表图片视频和评论已核验。原链接和媒体可能包含临时访问参数，请保留在本地。</p>'+''.join(rendered)+'</html>')
    summary={'target_count':len(ids),'valid_detail_count':len(rows),'text_sources':dict(Counter(p['text_source'] for p in rows)),'unavailable_ids':unavailable,'nonempty_fields':dict(field_counts),'types':dict(types),'scope':'frozen candidate union; text-only requested scope; media and comments not fully verified'}
    (out/'collection_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
