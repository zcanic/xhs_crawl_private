'use strict';
let data, filtered = [], selected = null, page = 1, quick = 'all', queryFilter = '';
const size = 25;
const $ = id => document.getElementById(id);
const h = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const levelOf = p => p.text_only_level || '未定';
const typeOf = p => p.post_type === 'video' ? '视频' : '图文';
const names = {baseline:'基线检索', crossed:'交叉检索', bfs:'BFS 扩展'};
const pct = (n,d) => d ? (100*n/d).toFixed(1)+'%' : '—';
const chip = p => `<span class="chip ${p.scope_relevance==='目标赛事相关'?'target':''}">${h(p.scope_relevance)}</span> <span class="chip ${levelOf(p)==='L2'?'l2':'level'}">${h(levelOf(p))}</span>`;
function showView(view) {
  document.querySelectorAll('.view').forEach(el => el.hidden = el.id !== view+'-view');
  document.querySelectorAll('.nav').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  $('page-title').textContent = {posts:'帖子与标注',queries:'检索效果',media:'媒体待核验',exceptions:'异常与说明'}[view];
}
function filterPosts(resetPage=true) {
  if (!data) return;
  const word = $('search').value.trim().toLowerCase();
  filtered = data.posts.filter(p => {
    if (quick==='target' && p.scope_relevance!=='目标赛事相关') return false;
    if (quick==='l2' && !(p.scope_relevance==='目标赛事相关' && levelOf(p)==='L2')) return false;
    if (quick==='uncertain' && !(levelOf(p)==='未定' || ['信息不足','赛事身份存疑'].includes(p.scope_relevance))) return false;
    if ($('relation').value && p.scope_relevance!==$('relation').value) return false;
    if ($('level').value && levelOf(p)!==$('level').value) return false;
    if ($('type').value && p.post_type!==$('type').value) return false;
    if (queryFilter && !p.queries.includes(queryFilter)) return false;
    return !word || [p.reading_id,p.note_id,p.title,p.body,p.evidence_quote,p.reason,p.needs_review,p.author,...p.tags].join(' ').toLowerCase().includes(word);
  });
  if (resetPage) page=1;
  if (!filtered.some(p=>p.note_id===selected)) selected=filtered[0]?.note_id || null;
  renderList(); renderDetail();
}
function renderList() {
  $('result-count').textContent = `${filtered.length} 条结果`+(queryFilter ? ` · ${queryFilter}` : '');
  const slice = filtered.slice((page-1)*size,page*size);
  $('post-list').innerHTML = slice.map(p=>`<div role="listitem"><button class="post-row ${selected===p.note_id?'selected':''}" data-id="${h(p.note_id)}" aria-label="${h(p.reading_id+' '+(p.title||'无标题'))}" aria-current="${selected===p.note_id}"><div class="row-top"><span class="rid">${h(p.reading_id)}</span><span>·</span><span>${typeOf(p)}</span><span>·</span><span>${h(p.author||'作者未记录')}</span></div><div class="row-title">${h(p.title||'（无标题）')}</div><div class="row-bottom"><span>${chip(p)}</span><small>${p.media_review_complete?'图文已核验':'媒体待核验'}</small></div></button></div>`).join('') || '<div class="empty">没有符合条件的帖子<br>试试更换关键词或重置筛选</div>';
  $('page-count').textContent=`${filtered.length? page:0} / ${Math.max(1,Math.ceil(filtered.length/size))} 页`;
  $('prev-page').disabled=page<=1; $('next-page').disabled=page*size>=filtered.length;
}
function renderDetail() {
  const p=data.posts.find(p=>p.note_id===selected);
  if (!p) { $('detail').innerHTML='<div class="empty">没有可展示的帖子</div>'; return; }
  const index=filtered.findIndex(r=>r.note_id===selected);
  let original='';
  try {const u=new URL(p.source_url); if(u.protocol==='https:' && (u.hostname==='www.xiaohongshu.com'||u.hostname==='xiaohongshu.com')) original=`<a href="${h(u.href)}" target="_blank" rel="noopener noreferrer">打开小红书原帖 ↗</a>`;}catch{}
  const local=p.local_images||[];
  const media=local.length ? `<details><summary>本地图片 ${local.length} / ${p.image_count} 张 · 展开查看（查看不改变核验状态）</summary><div class="media-grid">${local.map(i=>`<a href="/media/${p.note_id}/${i}" target="_blank" rel="noopener"><img loading="lazy" src="/media/${p.note_id}/${i}" alt="${h(p.reading_id)} 图片 ${i}"></a>`).join('')}</div></details>` : `<span class="muted">${p.post_type==='video'?'视频未在面板播放，可打开原帖查看。':'本帖图片尚未保存到本机。'}</span>`;
  $('detail').innerHTML=`<div class="detail-meta"><span>${h(p.reading_id)}</span><span>·</span><span>${typeOf(p)}</span>${chip(p)}<span>置信度 ${h(p.confidence)}</span></div><h2>${h(p.title||'（无标题）')}</h2><div class="detail-author"><span>${h(p.author||'作者未记录')} · ${p.source==='browser_visible_dom'?'网页补回正文':'详情接口正文'}</span>${original}</div><section class="detail-section"><div class="section-label">正文全文</div><div class="body-text">${h(p.body||'（本帖正文为空；视频与图片内容不以标题代替。）')}</div></section><section class="detail-section"><div class="section-label">逐读判断</div><div class="judgment"><strong>${h(p.content_facet)}</strong><blockquote>${h(p.evidence_quote)}</blockquote><div class="reason">${h(p.reason)}</div></div></section><section class="detail-section"><div class="section-label">初标备注与当前媒体状态</div><div class="review-note">初标时记录：${h(p.needs_review)}<br>${p.media_review_complete?'已另行完成整帖图文核验。':'当前只完成正文逐读，媒体内容待核验。'} 评论未全部读取。</div></section>${p.media_review_complete?`<section class="detail-section"><div class="section-label">已完成的整帖核验</div><div class="judgment"><strong>整帖 ${h(p.final_level||'未定')}</strong><p>${h(p.final_reason)}</p></div></section>`:''}<section class="detail-section"><div class="section-label">检索来源</div><div class="tags">${p.queries.map(q=>`<span class="tag">${h(q)}</span>`).join('')}</div></section><section class="detail-section"><div class="section-label">原始话题</div><div class="tags">${p.tags.length?p.tags.map(t=>`<span class="tag">#${h(t)}</span>`).join(''):'<span class="muted">标签字段为空或未返回</span>'}</div></section><section class="detail-section"><div class="section-label">媒体预览</div>${media}</section><div class="mono">${h(p.note_id)}</div><div class="detail-bottom"><button class="button" id="previous-note" ${index<=0?'disabled':''}>← 上一条</button><span class="local-pill">${index+1} / ${filtered.length}</span><button class="button" id="next-note" ${index>=filtered.length-1?'disabled':''}>下一条 →</button></div>`;
  $('previous-note').onclick=()=>selectAdjacent(-1); $('next-note').onclick=()=>selectAdjacent(1);
  history.replaceState(null,'','#'+p.note_id);
}
function selectAdjacent(step) {const i=filtered.findIndex(p=>p.note_id===selected)+step; if(!filtered[i])return; selected=filtered[i].note_id;page=Math.floor(i/size)+1;renderList();renderDetail();$('detail').scrollTop=0;}
function resetFilters() {quick='all';queryFilter='';['search','relation','level','type'].forEach(id=>$(id).value='');document.querySelectorAll('.quick').forEach(el=>el.classList.toggle('active',el.dataset.quick==='all'));}
function renderMetrics() {
  const s=data.summary;
  const values=[['冻结候选',s.frozen_candidates,'14 个非重复检索'],['正文已读',s.individually_read_text,'全部可用正文已标注'],['目标相关',s.relevance['目标赛事相关'],'单人逐读相关性判断'],['目标正文 L2',s.target_text_levels.L2,'含实际体验、攻略与意向'],['详情缺失',s.detail_unavailable,'单列记录，不补造正文']];
  $('metrics').innerHTML=values.map((v,i)=>`<div class="metric"><div class="metric-name">${v[0]}</div><b class="${i===2||i===3?'metric-accent':''}">${v[1]}</b><em>${v[2]}</em></div>`).join('');
  document.querySelector('.nav small').textContent=s.individually_read_text;
  $('updated').textContent='数据更新 '+new Date(data.updated_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
}
function renderQueries() {
  const q=data.queries;
  $('queries-view').innerHTML=`<div class="strategy-grid">${q.strategies.map(r=>`<div class="card"><div class="strategy-name">${names[r.strategy]} · ${r.search_calls} 次请求</div><div class="strategy-number">${r.target}<small class="muted" style="font-size:12px"> 条目标相关</small></div><div class="bar"><span style="width:${100*r.target/r.read}%"></span></div><p>在 ${r.read} 条已读正文中占 ${pct(r.target,r.read)}<br>目标正文 L2：${r.target_L2} 条${r.strategy!=='baseline'?`<br>基线以外新增相关：${r.outside_baseline.target} 条`:''}</p></div>`).join('')}</div><div class="card"><h2>每个查询，带回了什么？</h2><p>策略集合有重叠，不能将各行直接相加。请求配额不同；这里的相关份额是本候选池逐读结果，不是平台召回率。</p><div class="table-wrap"><table><thead><tr><th>查询</th><th>深度</th><th>候选</th><th>已读</th><th>目标相关</th><th>目标 L2</th><th>基线外相关</th><th></th></tr></thead><tbody>${q.queries.map(r=>`<tr><td>${h(r.query)}</td><td>${r.depth}</td><td>${r.candidates}</td><td>${r.read}</td><td>${r.target}</td><td>${r.target_L2}</td><td>${r.outside_baseline.target}</td><td><button class="inline-open query-open" data-query="${h(r.query)}">查看帖子 ↗</button></td></tr>`).join('')}</tbody></table></div></div><div class="card"><h2>集合重叠</h2><p>Jaccard = 交集 / 并集。低重叠提示结果互补，但本身不能证明高覆盖率。</p><div class="table-wrap"><table><thead><tr><th>检索集合</th><th>原候选交集</th><th>原候选 Jaccard</th><th>相关帖交集</th><th>相关帖 Jaccard</th></tr></thead><tbody>${q.overlaps.map(r=>`<tr><td>${names[r.a]} × ${names[r.b]}</td><td>${r.raw_intersection}</td><td>${pct(r.raw_jaccard,1)}</td><td>${r.read_target_intersection}</td><td>${pct(r.read_target_jaccard,1)}</td></tr>`).join('')}</tbody></table></div></div><div class="card"><h2>统计解释边界</h2><ul class="note-list">${q.limitations.map(t=>`<li>${h(t)}</li>`).join('')}</ul></div>`;
  document.querySelectorAll('.query-open').forEach(el=>el.onclick=()=>{resetFilters();queryFilter=el.dataset.query;showView('posts');filterPosts();window.scrollTo(0,0);});
}
function renderMedia() {
  const s=data.summary;
  $('media-view').innerHTML=`<div class="card"><h2>文字读完，媒体状态单独记录</h2><p>本轮按你的要求先完成正文。已保留 ${s.complete_post_annotations} 条整帖图文核验、${s.individually_reviewed_images} 张逐张读图记录；其余媒体尚未核验。下载或在面板查看图片，不会自动改变标注状态。</p><div class="stat-inline"><div><b>${s.media_pending_posts}</b><span>帖子待媒体核验</span></div><div><b>${s.media_pending_images}</b><span>图文图片</span></div><div><b>${s.media_pending_videos}</b><span>视频</span></div></div></div><div class="card"><h2>待核验清单</h2><div class="table-wrap"><table><thead><tr><th>编号</th><th>标题</th><th>媒体</th><th>正文状态</th><th></th></tr></thead><tbody>${data.media_pending.map(r=>`<tr><td>${h(r.reading_id)}</td><td>${h(r.title||'（无标题）')}</td><td>${r.video_pending?'视频':r.expected_images+' 张图片'}</td><td class="complete-text">${r.text_annotation_complete?'已逐读':'未读'}</td><td><button class="inline-open note-open" data-id="${h(r.note_id)}">看正文 ↗</button></td></tr>`).join('')}</tbody></table></div></div>`;
  document.querySelectorAll('.note-open').forEach(el=>el.onclick=()=>{resetFilters();selected=el.dataset.id;showView('posts');filterPosts();page=Math.floor(filtered.findIndex(p=>p.note_id===selected)/size)+1;renderList();window.scrollTo(0,0);});
}
function renderExceptions() {
  const recovered=data.posts.filter(p=>p.source==='browser_visible_dom');
  $('exceptions-view').innerHTML=`<div class="card"><h2>每条候选都有处理状态</h2><p>551 条冻结候选：547 条取得接口详情，3 条从正常网页补回正文，1 条无法取得。550 份可用正文均已逐条读取、写下判断。缺失不会被归成“不相关”。</p></div>${data.exceptions.map(r=>`<div class="card missing"><h2>${h(r.search_card_title)}</h2><div class="mono">${h(r.note_id)}</div><p>接口尝试 ${r.api_attempts} 次，错误码 ${r.api_code}：${h(r.api_message)}</p><p>${h(r.browser_check)}</p><p>${h(r.conclusion)}</p><div class="review-note">${h(r.handling)}</div></div>`).join('')}<div class="card"><h2>网页补回的正文</h2><p>接口返回成功码却没有匹配详情的帖子，经正常网页核验补回文字。原接口详情未伪造；视频、图片和绝对发布时间没有据此补填。</p><table><thead><tr><th>编号</th><th>标题 / 正文摘要</th><th></th></tr></thead><tbody>${recovered.map(r=>`<tr><td>${h(r.reading_id)}</td><td>${h(r.title||r.body.slice(0,55))}</td><td><button class="inline-open recovered-open" data-id="${h(r.note_id)}">查看 ↗</button></td></tr>`).join('')}</tbody></table></div><div class="card"><h2>怎样理解这份标注</h2><ul class="note-list"><li>L0：没有可观察的目的地呈现；不等于不相关或没有研究价值。</li><li>L1：城市、场所、地标、海拔天气等作为比赛地点或环境出现。</li><li>L2：赛事与地方吃住行游、景观、文化等绑定，可能是实际体验、攻略、意向或文创表达。</li><li>多城市赛记中，其他城市的旅游内容不会自动归给兰州；主兰马、兰州新区及系列活动仍需按正式样本口径筛选。</li><li>这是 Codex 单独逐读初标，没有进行独立双人编码。原帖中的医疗、成绩、争议等说法不因标注而获得事实背书。</li></ul></div>`;
  document.querySelectorAll('.recovered-open').forEach(el=>el.onclick=()=>{resetFilters();selected=el.dataset.id;showView('posts');filterPosts();page=Math.floor(filtered.findIndex(p=>p.note_id===selected)/size)+1;renderList();window.scrollTo(0,0);});
}
async function load() {
  $('refresh').disabled=true; $('error').hidden=true;
  try {
    const response=await fetch('/api/data');if(!response.ok)throw new Error('本机数据暂时无法读取，请确认标注结果文件完整。');
    data=await response.json();
    $('relation').innerHTML='<option value="">全部相关性</option>'+Object.keys(data.summary.relevance).map(r=>`<option>${h(r)}</option>`).join('');
    renderMetrics();renderQueries();renderMedia();renderExceptions();
    if(!selected && /^[0-9a-f]{24}$/.test(location.hash.slice(1)))selected=location.hash.slice(1);
    filterPosts();
  } catch(e) {$('error').textContent=e.message||'读取失败';$('error').hidden=false;}
  finally {$('refresh').disabled=false;}
}
document.querySelectorAll('.nav').forEach(el=>el.onclick=()=>showView(el.dataset.view));
document.querySelectorAll('.quick').forEach(el=>el.onclick=()=>{quick=el.dataset.quick;document.querySelectorAll('.quick').forEach(x=>x.classList.toggle('active',x===el));filterPosts();});
['search','relation','level','type'].forEach(id=>$(id).addEventListener('input',()=>filterPosts()));
$('reset').onclick=()=>{resetFilters();filterPosts();};$('refresh').onclick=load;
$('post-list').onclick=e=>{const row=e.target.closest('.post-row');if(row){selected=row.dataset.id;renderList();renderDetail();$('detail').scrollTop=0;}};
$('prev-page').onclick=()=>{if(page>1){page--;renderList();$('post-list').scrollTop=0;}};
$('next-page').onclick=()=>{if(page*size<filtered.length){page++;renderList();$('post-list').scrollTop=0;}};
$('download').onclick=()=>{if(!data)return;const payload=filtered.map(p=>({reading_id:p.reading_id,note_id:p.note_id,title:p.title,body:p.body,scope_relevance:p.scope_relevance,text_only_level:p.text_only_level,evidence_quote:p.evidence_quote,reason:p.reason,needs_review:p.needs_review,source:p.source}));const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`兰马正文标注_${payload.length}条.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
load();
