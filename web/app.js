/* Retrieval Duel: front end. Talks to the Python server's /api routes. */
(function(){
const $=s=>document.querySelector(s);
const REDUCED=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const D=()=>REDUCED?0:1;
const W=600,H=430;
const WIN_LABEL={vector:'Vector',graph:'Graph',hybrid:'Hybrid',agentic:'Agentic',tie:'Tie',neither:'All wrong'};
const ROUTE_LABEL={vector:'vector search only',graph:'the graph only',both:'both, merged'};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const state={saved:{},catalog:[],pending:null,seen:new Set(),status:{},datasets:[],ds:null,data:null,questions:[],types:{},votes:{},current:null,last:null,run:0,shown:false,job:null};

const voteKey=()=>'rd-votes-'+state.ds;
function localVotes(){ try{ return JSON.parse(localStorage.getItem(voteKey())||'{}'); }catch(e){ return {}; } }
function saveLocalVotes(v){ try{ localStorage.setItem(voteKey(),JSON.stringify(v)); }catch(e){} }
async function api(path,opts={}){
  const res=await fetch(path,{headers:{'Content-Type':'application/json'},...opts,body:opts.body?JSON.stringify(opts.body):undefined});
  let data={}; try{ data=await res.json(); }catch(e){}
  if(!res.ok) throw new Error(data.error||`Request failed (${res.status})`);
  return data;
}
function showError(where,msg){ const el=$(where); el.innerHTML=`<div class="errbox">${esc(msg)}</div>`; el.hidden=false; }
const curMeta=()=>state.datasets.find(d=>d.slug===state.ds)||{};

// ================= steps =================
const STEPS=['basics','load','profile','duel','debrief'];
function renderDsBar(step){
  const show=['profile','duel','debrief'].includes(step) && !!state.data;
  $('#dsBar').hidden=!show; if(!show) return;
  const m=curMeta(), s=(state.data&&state.data.stats)||{};
  $('#dsName').textContent=m.name||state.ds;
  $('#dsStats').textContent=[s.docs!=null?`${s.docs} documents`:'', s.entities!=null?`${s.entities} entities`:'', s.communities!=null?`${s.communities} communities`:'',
    m.demo?'demo':(m.catalog?'public dataset':'your data')].filter(Boolean).join(' · ');
}
$('#dsChange').onclick=()=>{ go('load'); window.scrollTo({top:0,behavior:REDUCED?'auto':'smooth'}); };
function go(step){
  if(!STEPS.includes(step)) step='basics';
  if(['profile','duel','debrief'].includes(step) && !state.data){ step='load'; }
  if(['profile','duel','debrief'].includes(step) && !state.shown){ showIndexedNow(); }
  STEPS.forEach(s=>{ $('#step-'+s).hidden=s!==step; });
  document.querySelectorAll('nav.steps button').forEach(b=>b.setAttribute('aria-current',b.dataset.step===step?'step':'false'));
  if(step!=='load' && state.pending){ endPreview(); renderDatasets(); }
  $('#stage').hidden = step==='debrief'||step==='basics'||(step==='load'&&!!state.pending);
  $('#duelResults').hidden = !(step==='duel' && state.last);
  renderDsBar(step);
  if(step==='profile') renderProfile();
  if(step==='duel') renderDeck();
  if(step==='debrief') renderDebrief();
  if(location.hash.slice(1)!==step){ try{history.replaceState(null,'','#'+step);}catch(e){} }
}
document.querySelectorAll('nav.steps button').forEach(b=>b.onclick=()=>go(b.dataset.step));
document.querySelectorAll('[data-goto]').forEach(b=>b.onclick=()=>{go(b.dataset.goto);window.scrollTo({top:0,behavior:REDUCED?'auto':'smooth'});});
window.addEventListener('hashchange',()=>go(location.hash.slice(1)));

// ================= datasets & load step =================
async function refreshDatasets(){ state.datasets=await api('/api/datasets'); try{ state.catalog=await api('/api/catalog'); }catch(e){ state.catalog=[]; } renderDatasets(); }
function renderDatasets(){
  const cards=state.datasets.map(d=>{
    const st=d.demo?'demo · prebuilt':(d.status==='ready'?`indexed · ${d.stats?d.stats.entities+' entities':''}`:d.status==='indexing'?'indexing…':d.status==='error'?'indexing failed':'not indexed yet');
    const sel=!state.pending&&d.slug===state.ds;
    return `<div class="ds${sel?' on':''}" role="button" tabindex="0" data-slug="${d.slug}">
      <span class="tag">${sel?'Selected':(d.demo?'Demo':(d.catalog?'Public dataset':'Your data'))}</span><h3>${esc(d.name)}</h3><p>${esc(d.description||'')}</p>
      <span class="st ${d.status}">${st}</span>${d.demo?'':`<button class="del" data-del="${d.slug}" title="Delete this dataset">Delete</button>`}</div>`;}).join('');
  const catCards=state.catalog.filter(c=>!c.imported).map(c=>`<div class="ds cat${state.pending===c.id?' on':''}" role="button" tabindex="0" data-cat="${c.id}">
      <span class="tag">${state.pending===c.id?(state.status.public?'Selected · runs locally':'Selected · not downloaded yet'):(state.status.public?'Public dataset · local version':'Public dataset · import')}</span><h3>${esc(c.name)}</h3><p>${esc(c.description)}</p><span class="st">${esc(c.source)}</span></div>`).join('');
  $('#datasets').innerHTML=cards+catCards+`<button class="ds add${state.pending==='upload'?' on':''}" id="addDs"><span class="tag">Your data</span><h3>+ Add your own</h3><p>Upload text, Markdown, PDF or JSON files.</p></button>`;
  document.querySelectorAll('.ds[data-slug]').forEach(c=>{ const pick=()=>selectDataset(c.dataset.slug); c.onclick=e=>{ if(!e.target.dataset.del) pick(); }; c.onkeydown=e=>{ if(e.key==='Enter') pick(); }; });
  document.querySelectorAll('[data-del]').forEach(b=>b.onclick=async e=>{ e.stopPropagation();
    if(b.dataset.confirm!=='1'){ b.dataset.confirm='1'; b.textContent='Really delete?'; return; }
    try{ await api('/api/datasets/'+b.dataset.del,{method:'DELETE'}); if(state.ds===b.dataset.del){ state.ds=null; state.data=null; } await refreshDatasets(); if(!state.ds && state.datasets[0]) selectDataset(state.datasets[0].slug); }catch(err){ alertBox(err.message); } });
  $('#addDs').onclick=()=>{ if(state.status.public){ showLocalOnly('upload','Your own documents'); return; } preview('upload'); $('#importBox').hidden=true; $('#uploadBox').hidden=false; $('#upName').focus(); };
  document.querySelectorAll('.ds[data-cat]').forEach(c=>{ const open=()=>openImport(c.dataset.cat); c.onclick=open; c.onkeydown=e=>{ if(e.key==='Enter') open(); }; });
}
function alertBox(msg){ showError('#estimate',msg); }

function preview(what){
  state.pending=what; renderDatasets();
  ['#cta','#stage'].forEach(s=>$(s).hidden=true); document.querySelector('.peek').hidden=true;
}
function showLocalOnly(id,name){ preview(id); $('#importBox').hidden=true; $('#uploadBox').hidden=true; $('#loName').textContent=name; $('#localOnly').hidden=false; }
$('#loCancel').onclick=()=>{ endPreview(); renderDatasets(); };
function endPreview(){
  state.pending=null; $('#importBox').hidden=true; $('#uploadBox').hidden=true; $('#localOnly').hidden=true;
  $('#cta').hidden=false; $('#stage').hidden=false; document.querySelector('.peek').hidden=false;
}
async function selectDataset(slug){
  // Coming back to the dataset that's already loaded (e.g. after peeking at another card): keep everything.
  if(slug===state.ds && state.data){ endPreview(); renderDatasets(); if(state.shown) setCta('done'); return; }
  endPreview();
  state.ds=slug; state.data=null; state.shown=false; state.last=null; state.current=null; state.run++;
  try{ localStorage.setItem('rd-ds',slug); }catch(e){}
  renderDatasets(); clearViz();
  $('#estimate').hidden=true; $('#stages').hidden=true; $('#log').hidden=true;
  const m=curMeta();
  $('#indexBtn').textContent=m.demo?`Index ${m.name}`:`Index ${m.name}`;
  loadDocs();
  if(m.demo || m.status==='ready'){
    setCta('loading');
    await loadViz();
    // Show the "build it" moment the first time only; after that (or for datasets you indexed yourself) show it ready.
    if(state.seen.has(slug) || (!m.demo && m.status==='ready')) showIndexedNow(); else setCta('idle');
  } else if(m.status==='indexing' && state.job){
    setCta('running'); pollJob(state.job);
  } else {
    setCta(m.status==='error'?'error':'new');
    try{ renderEstimate(await api(`/api/datasets/${slug}/estimate`)); }catch(e){ alertBox(e.message); }
  }
}
async function loadDocs(){
  try{
    const docs=await api(`/api/datasets/${state.ds}/documents`);
    $('#articleList').innerHTML=docs.slice(0,500).map(d=>`<li><button data-id="${d.id}"><span class="d">${esc((d.date||'').replace(/, \d{4}$/,''))}</span><span>${esc(d.title)}</span></button></li>`).join('');
    const show=id=>{ const d=docs.find(x=>x.id===id); document.querySelectorAll('#articleList button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.id===id));
      $('#articleView').innerHTML=`<div class="src">${esc(curMeta().name)}${d.date?' · '+esc(d.date):''}</div><h3>${esc(d.title)}</h3><p>${esc(d.text.slice(0,4000))}${d.text.length>4000?'…':''}</p>`; };
    document.querySelectorAll('#articleList button').forEach(b=>b.onclick=()=>show(b.dataset.id));
    if(docs[0]) show(docs[0].id);
  }catch(e){}
}
function renderEstimate(e){
  const el=$('#estimate'); el.hidden=false;
  el.innerHTML=`<div><b>${e.docs}</b>documents</div><div><b>${e.words.toLocaleString()}</b>words</div><div><b>~${e.chunks_est}</b>passages</div>
    <div><b>${e.extraction_calls}</b>AI reading calls</div><div><b>~${(e.graph_tokens_est/1000).toFixed(0)}k</b>graph tokens</div>
    <div><b>~$${e.dollars_est<0.01?'0.01':e.dollars_est.toFixed(2)}</b>estimated indexing cost</div><div><b>~$${e.dollars_per_question_est.toFixed(3)}</b>per question asked</div>
    ${e.dollars_est>e.budget?`<span class="warn">This is over your $${e.budget.toFixed(2)} budget (RDUEL_MAX_INDEX_DOLLARS in .env). Indexing will stop when it reaches the budget. Try fewer documents or raise the budget.</span>`:''}
    ${!e.has_key?'<span class="warn">Building a graph needs Claude. Add your ANTHROPIC_API_KEY to the .env file and restart the app.</span>':''}
    <span style="flex-basis:100%;font-size:12px;color:var(--faint)">Estimates use ${esc(e.work_model)} for reading and ${esc(e.answer_model)} for answers, at the prices in .env. Repeat runs on the same text are cached and free.</span>`;
  $('#indexBtn').disabled=!e.has_key;
}
function setCta(s){
  const m=curMeta(); state.cta=s;
  $('#vecEmpty').hidden=$('#grEmpty').hidden= !(s==='idle'||s==='new'||s==='error'||(s==='running'&&!state.data));
  $('#indexBtn').hidden= s==='loading' || (s==='done' && !(m.demo||m.status==='ready'));
  $('#indexBtn').disabled= s==='running' || (s==='new' && !state.status.has_key);
  $('#indexBtn').classList.toggle('ghost', s==='done');
  $('#indexBtn').textContent= s==='done'?'Replay indexing':s==='running'?'Indexing…':(s==='error'?'Try indexing again':`Index ${m.name||'dataset'}`);
  $('#toProfile').hidden= s!=='done';
  const notes={
    loading:`Loading ${m.name||'the dataset'}'s indexes…`,
    idle: m.demo?'Takes about 8 seconds. The demo\'s graph was built ahead of time; this replays how it happens, step by step, in the two panels below.':'Already indexed. Click to watch the indexes being assembled in the panels below.',
    new:'This runs the real thing: passages are embedded on your computer, and Claude reads every document to build the graph.',
    running:'Working. You can watch the progress below.',
    error:(m.error?'Last attempt failed: '+m.error:'Last attempt failed.'),
    done:'Both indexes are built. Hover the dots and circles below to explore them, or move on.'};
  $('#ctaNote').textContent=notes[s]||'';
  $('#ctaNote').classList.toggle('spin', s==='loading');
  if(s==='done'){ $('#log').hidden=false; }
  const st=m.stats; if(st){ $('#howVec').textContent=`Cut ${st.docs} documents into ${st.chunks} passages and give each one coordinates on the map of meaning.`;
    $('#howGraph').textContent=`An AI reads each document and writes down the people, places and things in it and how they connect: here ${st.entities} entities and ${st.relations} relationships, grouped into ${st.communities} communities with a summary of each.`; }
}
$('#indexBtn').onclick=async ()=>{
  const m=curMeta();
  if(m.demo || m.status==='ready'){ playIndexing(); return; }
  try{ setCta('running'); const job=await api(`/api/datasets/${state.ds}/index`,{method:'POST'}); state.job=job.id; m.status='indexing'; renderDatasets(); pollJob(job.id); }
  catch(e){ setCta('error'); alertBox(e.message); }
};
$('#toProfile').onclick=()=>{ go('profile'); window.scrollTo({top:0,behavior:REDUCED?'auto':'smooth'}); };

const STAGES=[['chunk','Cut into passages'],['embed','Embed passages (vector)'],['extract','AI reads each document (graph)'],['resolve','Merge duplicate names'],['summarize','Find and summarize communities'],['questions','Write test questions']];
async function pollJob(id){
  const run=state.run; $('#stages').hidden=false; $('#log').hidden=false;
  let since=0;
  while(run===state.run){
    let j; try{ j=await api('/api/jobs/'+id+'?since='+since); }catch(e){ alertBox(e.message); return; }
    since=j.event_count;
    const cur=STAGES.findIndex(s=>s[0]===j.stage);
    $('#stages').innerHTML=STAGES.map(([k,label],i)=>{ const isCur=i===cur&&j.status==='running'; const done=i<cur||j.status==='done';
      const pct=done?100:(isCur&&j.total?100*j.done/j.total:0);
      return `<span class="lbl ${done?'done':isCur?'on':''}">${done?'✓ ':''}${label}</span><div class="bar"><i style="width:${pct}%"></i></div><span class="n">${isCur&&j.total?j.done+'/'+j.total:(done?'done':'')}</span>`; }).join('');
    $('#log').innerHTML=`<span>entities <b>${j.entities}</b></span><span>relations <b>${j.relations}</b></span><span>communities <b>${j.communities}</b></span><span>AI calls <b>${j.meter.calls||0}</b> (${j.meter.cached||0} cached)</span><span>spent <b>$${(j.meter.dollars||0).toFixed(3)}</b></span><span class="live">${esc(j.message||'')}</span>`;
    if(j.status==='done'){ delete vizCache[state.ds]; await refreshDatasets(); await loadViz(); playIndexing(); return; }
    if(j.status==='error'){ await refreshDatasets(); setCta('error'); alertBox(j.error); return; }
    await new Promise(r=>setTimeout(r,700));
  }
}

// ---------- import a public dataset ----------
let impId=null;
function openImport(id){
  const c=state.catalog.find(x=>x.id===id); if(!c) return; impId=id;
  if(state.status.public){ showLocalOnly(id,c.name); return; }
  preview(id); $('#uploadBox').hidden=true; $('#importBox').hidden=false;
  $('#impSource').textContent=c.source+' · license: '+c.license; $('#impName').textContent=c.name;
  $('#impDesc').textContent=c.description; $('#impWhy').textContent=c.why;
  $('#impSize').innerHTML=c.sizes.map(s=>`<option value="${s.id}"${s.id===c.default?' selected':''}>${esc(s.label)}</option>`).join('');
  $('#impMsg').textContent=''; $('#impGo').disabled=false;
  $('#importBox').scrollIntoView({behavior:REDUCED?'auto':'smooth',block:'nearest'});
}
$('#impCancel').onclick=()=>{ endPreview(); renderDatasets(); };
$('#impGo').onclick=async ()=>{
  $('#impGo').disabled=true; $('#impMsg').textContent='Starting download…';
  try{
    const job=await api('/api/catalog',{method:'POST',body:{id:impId,size:$('#impSize').value}});
    while(true){
      await new Promise(r=>setTimeout(r,800));
      const j=await api('/api/jobs/'+job.id);
      $('#impMsg').textContent=j.message+(j.stage==='download'&&j.total>1?` ${j.done}/${j.total}`:'');
      if(j.status==='done'){ $('#importBox').hidden=true; await refreshDatasets(); await selectDataset(j.dataset); return; }
      if(j.status==='error'){ $('#impMsg').textContent=''; showError('#impMsg',j.error); $('#impGo').disabled=false; return; }
    }
  }catch(e){ $('#impMsg').textContent=e.message; $('#impGo').disabled=false; }
};

// ---------- upload ----------
const upFiles=[];
function setFiles(list){ upFiles.length=0; [...list].forEach(f=>upFiles.push(f)); $('#upList').textContent=upFiles.length?upFiles.length+' file(s): '+upFiles.slice(0,5).map(f=>f.name).join(', ')+(upFiles.length>5?'…':''):''; }
$('#upFiles').onchange=e=>setFiles(e.target.files);
const drop=$('#drop');
drop.ondragover=e=>{e.preventDefault();drop.classList.add('over');}; drop.ondragleave=()=>drop.classList.remove('over');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');setFiles(e.dataTransfer.files);};
$('#upCancel').onclick=()=>{ endPreview(); renderDatasets(); };
$('#uploadBox').onsubmit=async e=>{
  e.preventDefault();
  if(!upFiles.length){ $('#upMsg').textContent='Choose at least one file.'; return; }
  $('#upGo').disabled=true; $('#upMsg').textContent='Reading files…';
  try{
    const files=await Promise.all(upFiles.map(f=>new Promise((res,rej)=>{ const r=new FileReader();
      if(/\.pdf$/i.test(f.name)){ r.onload=()=>res({name:f.name,content:r.result.split(',')[1],encoding:'base64'}); r.readAsDataURL(f); }
      else { r.onload=()=>res({name:f.name,content:r.result}); r.readAsText(f); } r.onerror=rej; })));
    $('#upMsg').textContent='Uploading…';
    const ds=await api('/api/datasets',{method:'POST',body:{name:$('#upName').value.trim()||'My dataset',files,chunk_words:+$('#upChunk').value}});
    $('#uploadBox').hidden=true; $('#upMsg').textContent=''; setFiles([]); $('#upName').value='';
    await refreshDatasets(); selectDataset(ds.slug);
  }catch(err){ $('#upMsg').textContent=err.message; }
  $('#upGo').disabled=false;
};

// ================= visualizations =================
const vSvg=d3.select('#vecSvg'), gSvg=d3.select('#grSvg');
function addGlow(svg,id){ const f=svg.append('defs').append('filter').attr('id',id).attr('x','-50%').attr('y','-50%').attr('width','200%').attr('height','200%');
  f.append('feGaussianBlur').attr('stdDeviation',4).attr('result','b'); const m=f.append('feMerge'); m.append('feMergeNode').attr('in','b'); m.append('feMergeNode').attr('in','SourceGraphic'); }
addGlow(vSvg,'vglow'); addGlow(gSvg,'gglow');
const V={}, G={};
const tipEl=$('#tip');
function tip(e,t,html){ tipEl.innerHTML=`<div class="t">${esc(t)}</div>${html}`; tipEl.hidden=false;
  const x=Math.min(e.pageX+14,document.documentElement.clientWidth-300); tipEl.style.left=Math.max(8,x)+'px'; tipEl.style.top=(e.pageY+14)+'px'; }
function hideTip(){ tipEl.hidden=true; }
function fit(nodes,padX,padY){
  if(!nodes.length) return;
  const xs=nodes.map(n=>n.x), ys=nodes.map(n=>n.y);
  const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
  const k=Math.min((W-2*padX)/(x1-x0||1),(H-2*padY-30)/(y1-y0||1));
  const ox=(W-(x1-x0)*k)/2, oy=(H-30-(y1-y0)*k)/2+4;
  nodes.forEach(n=>{n.x=ox+(n.x-x0)*k; n.y=oy+(n.y-y0)*k;});
}
function clearViz(){
  vSvg.selectAll('g').remove(); gSvg.selectAll('g').remove(); $('#vecOverlay').innerHTML=''; $('#grOverlay').innerHTML='';
  $('#vecMeta').textContent='passages on a map of meaning'; $('#grMeta').textContent='entities, relations and communities';
}
const vizCache={};
function vizLoading(on){
  ['#vecLoad','#grLoad'].forEach(s=>$(s).hidden=!on);
  if(on){ $('#vecEmpty').hidden=$('#grEmpty').hidden=true; }
}
async function loadViz(){
  const run=state.run, slug=state.ds;
  let c=vizCache[slug];
  if(!c){
    vizLoading(true);
    try{
      const [data,q]=await Promise.all([api(`/api/datasets/${slug}/viz`),api(`/api/datasets/${slug}/questions`)]);
      c={data,questions:q.questions,types:q.types};
    }catch(e){ vizLoading(false); alertBox(e.message); return; }
  }
  if(run!==state.run){ return; }
  state.data=c.data; state.questions=c.questions; state.types=c.types;
  state.votes=state.status.public?localVotes():await api(`/api/datasets/${slug}/votes`).catch(()=>({}));
  state.saved=state.status.public?{}:await api(`/api/datasets/${slug}/results`).catch(()=>({}));
  if(run!==state.run) return;
  await new Promise(r=>requestAnimationFrame(()=>setTimeout(r,0)));  // let the spinner paint before the layout work
  buildViz(c.data);
  vizCache[slug]=c;   // positions are now stored on c.data, so the next visit skips the layout
  vizLoading(false);
}
function buildViz(data){
  clearViz();
  const n=data.chunks.length, big=n>400;
  // ----- vector map -----
  const coords=data.vector.coords;
  V.nodes=data.chunks.map((c,i)=>({...c,i,x:(coords[i]||[0,0])[0]*300+W/2+((i*37)%11),y:(coords[i]||[0,0])[1]*300+H/2+((i*53)%13)}));
  const links=data.vector.links.map(([a,b,s])=>({source:a,target:b,s}));
  const sim=d3.forceSimulation(V.nodes).force('link',d3.forceLink(links).distance(l=>Math.max(14,90-l.s*110)).strength(l=>Math.min(1,Math.max(.05,l.s*1.4))))
    .force('charge',d3.forceManyBody().strength(big?-12:-60)).force('center',d3.forceCenter(W/2,H/2)).force('collide',d3.forceCollide(big?3:9)).stop();
  if(data._vpos){ V.nodes.forEach((d,i)=>{ d.x=data._vpos[i][0]; d.y=data._vpos[i][1]; }); }
  else { for(let i=0;i<(n>1500?80:300);i++) sim.tick(); fit(V.nodes,48,40); data._vpos=V.nodes.map(d=>[d.x,d.y]); }
  const r=big?2.6:5; V.r=r;
  const bg=vSvg.append('g');
  [60,120,180,240].forEach(rr=>bg.append('circle').attr('cx',W/2).attr('cy',H/2-12).attr('r',rr).attr('fill','none').attr('stroke','#233554').attr('stroke-dasharray','2 5').attr('opacity',.6));
  V.linkSel=vSvg.append('g').selectAll('line').data(big?[]:links.filter(l=>l.s>0.2)).join('line')
    .attr('x1',l=>l.source.x).attr('y1',l=>l.source.y).attr('x2',l=>l.target.x).attr('y2',l=>l.target.y).attr('stroke','#3fd6c8').attr('stroke-opacity',0);
  V.lineG=vSvg.append('g'); V.dotG=vSvg.append('g'); V.qG=vSvg.append('g'); V.labG=vSvg.append('g');
  V.dots=V.dotG.selectAll('circle').data(V.nodes).join('circle').attr('cx',d=>d.x).attr('cy',d=>d.y).attr('r',0)
    .attr('fill','#3fd6c8').attr('fill-opacity',.75).attr('stroke','#0b1424').attr('stroke-width',big?.5:1.5)
    .on('mousemove',(e,d)=>tip(e,`${d.date?d.date+' · ':''}${d.title}`,esc(d.text.slice(0,400)))).on('mouseleave',hideTip);
  $('#vecMeta').textContent=`${data.docs.length} documents → ${n} passages → 2D map${data.vector.semantic?'':' · word matching'}`;

  // ----- knowledge graph -----
  const comms=data.communities.filter(c=>c.id!=='misc');
  const ccol=Object.fromEntries(data.communities.map(c=>[c.id,c.color]));
  const k=comms.length||1, cols=Math.ceil(Math.sqrt(k)), rows=Math.ceil(k/cols);
  const anchors={}; comms.forEach((c,i)=>{ anchors[c.id]=[W*((i%cols)+.5)/cols, H*.95*(Math.floor(i/cols)+.5)/rows]; });
  anchors.misc=[W/2,H/2];
  G.nodes=data.entities.map((e,i)=>({...e,x:(anchors[e.c]||anchors.misc)[0]+Math.cos(i)*30,y:(anchors[e.c]||anchors.misc)[1]+Math.sin(i)*30}));
  G.by=Object.fromEntries(G.nodes.map(d=>[d.id,d]));
  G.links=data.relations.map((r,i)=>({...r,i,source:r.s,target:r.t}));
  const ne=G.nodes.length, dense=ne>80;
  const rad=d=>(dense?3:5)+Math.sqrt(d.deg||0)*(dense?1.4:2.4); G.rad=rad;
  const gsim=d3.forceSimulation(G.nodes).force('link',d3.forceLink(G.links).id(d=>d.id).distance(dense?30:58).strength(.4))
    .force('charge',d3.forceManyBody().strength(dense?-60:-320)).force('x',d3.forceX(d=>(anchors[d.c]||anchors.misc)[0]).strength(.12)).force('y',d3.forceY(d=>(anchors[d.c]||anchors.misc)[1]).strength(.12))
    .force('collide',d3.forceCollide(d=>rad(d)+(dense?4:16))).stop();
  if(data._gpos){ G.nodes.forEach((d,i)=>{ d.x=data._gpos[i][0]; d.y=data._gpos[i][1]; }); }
  else { for(let i=0;i<(ne>800?120:400);i++) gsim.tick(); fit(G.nodes,56,34); data._gpos=G.nodes.map(d=>[d.x,d.y]); }
  const hullG=gSvg.append('g'), hullLab=gSvg.append('g'); G.edgeG=gSvg.append('g'); G.edgeLabG=gSvg.append('g'); const nodeG=gSvg.append('g'); G.ringG=gSvg.append('g');
  const hullLine=d3.line().curve(d3.curveCatmullRomClosed.alpha(.6));
  G.hulls=comms.map(c=>{ const pts=[]; G.nodes.filter(d=>d.c===c.id).forEach(d=>{ for(let a=0;a<8;a++) pts.push([d.x+Math.cos(a*Math.PI/4)*(rad(d)+12),d.y+Math.sin(a*Math.PI/4)*(rad(d)+12)]); });
    const h=pts.length>=3?d3.polygonHull(pts):null; if(!h) return null; const top=h.reduce((m,p)=>p[1]<m[1]?p:m,h[0]); return {c,h,lx:d3.mean(h,p=>p[0]),ly:top[1]-6}; }).filter(Boolean);
  G.hullSel=hullG.selectAll('path').data(G.hulls).join('path').attr('d',d=>hullLine(d.h)).attr('fill',d=>d.c.color).attr('fill-opacity',0).attr('stroke',d=>d.c.color).attr('stroke-opacity',0).attr('stroke-width',1.2)
    .on('mousemove',(e,d)=>tip(e,'Community · '+d.c.title,esc(d.c.summary||''))).on('mouseleave',hideTip);
  G.hullTxt=hullLab.selectAll('text').data(G.hulls).join('text').attr('class','hlabel').attr('x',d=>d.lx).attr('y',d=>Math.max(12,d.ly)).attr('text-anchor','middle').attr('fill',d=>d.c.color).attr('opacity',0).text(d=>d.c.title);
  G.edges=G.edgeG.selectAll('line').data(G.links).join('line').attr('x1',l=>l.source.x).attr('y1',l=>l.source.y).attr('x2',l=>l.target.x).attr('y2',l=>l.target.y).attr('stroke','#8fa0bd').attr('stroke-opacity',0).attr('stroke-width',1.1);
  const labelCut=dense?[...G.nodes].sort((a,b)=>b.deg-a.deg)[Math.min(40,ne-1)].deg:-1;
  G.nodeSel=nodeG.selectAll('g').data(G.nodes).join('g').attr('transform',d=>`translate(${d.x},${d.y})`).attr('opacity',0)
    .on('mousemove',(e,d)=>tip(e,d.type+' · '+((data.communities.find(c=>c.id===d.c)||{}).title||''),`<b>${esc(d.name)}</b>. ${esc(d.desc)}`)).on('mouseleave',hideTip);
  G.nodeSel.append('circle').attr('r',rad).attr('fill',d=>ccol[d.c]||'#8fa0bd').attr('fill-opacity',.9).attr('stroke','#0b1424').attr('stroke-width',dense?1:2);
  G.nodeSel.filter(d=>d.deg>labelCut).append('text').attr('class','nlabel').attr('y',d=>rad(d)+11).attr('text-anchor','middle').text(d=>d.name.length>24?d.name.slice(0,22)+'…':d.name);
  $('#grMeta').textContent=`${ne} entities · ${G.links.length} relations · ${comms.length} communities`;
}
function resting(){
  if(!V.dots) return;
  V.dots.interrupt().attr('r',V.r).attr('fill','#3fd6c8').attr('fill-opacity',.75); V.linkSel.interrupt().attr('stroke-opacity',.12);
  G.nodeSel.interrupt().attr('opacity',1); G.edges.interrupt().attr('stroke','#8fa0bd').attr('stroke-opacity',.35).attr('stroke-width',1.1).attr('stroke-dasharray',null);
  G.hullSel.interrupt().attr('fill-opacity',.07).attr('stroke-opacity',.35); G.hullTxt.interrupt().attr('opacity',.85);
  V.qG.selectAll('*').remove(); V.lineG.selectAll('*').remove(); V.labG.selectAll('*').remove(); G.ringG.selectAll('*').remove(); G.edgeLabG.selectAll('*').remove();
}
function showIndexedNow(){ if(!state.data) return; resting(); state.shown=true; state.seen.add(state.ds); setCta('done'); logDone(); $('#vecOverlay').innerHTML=''; $('#grOverlay').innerHTML=''; }
function logDone(){ const s=state.data.stats||{}; $('#log').hidden=false;
  $('#log').innerHTML=`<span>passages <b>${s.chunks}</b></span><span>entities <b>${s.entities}</b></span><span>relations <b>${s.relations}</b></span><span>communities <b>${s.communities}</b></span><span class="live">Both indexes ready.</span>`; }

function playIndexing(){
  if(!state.data) return;
  if(REDUCED){ showIndexedNow(); return; }
  const run=++state.run; resting();
  V.dots.attr('r',0); V.linkSel.attr('stroke-opacity',0); G.nodeSel.attr('opacity',0); G.edges.attr('stroke-opacity',0); G.hullSel.attr('fill-opacity',0).attr('stroke-opacity',0); G.hullTxt.attr('opacity',0);
  setCta('running'); $('#indexBtn').textContent='Indexing…'; $('#stages').hidden=true;
  $('#stage').scrollIntoView({behavior:'smooth',block:'start'});
  const docs=state.data.docs, n=V.nodes.length;
  const vStep=Math.max(4,Math.min(70,3000/n)), aStep=Math.max(30,Math.min(230,4000/docs.length));
  const counters={p:0,a:0,e:0,r:0,c:0};
  const log=msg=>{ $('#log').hidden=false; $('#log').innerHTML=`<span>passages embedded <b>${counters.p}/${n}</b></span><span>documents read by AI <b>${counters.a}/${docs.length}</b></span><span>entities <b>${counters.e}</b></span><span>relations <b>${counters.r}</b></span><span>communities <b>${counters.c}</b></span><span class="live">${esc(msg)}</span>`; };
  $('#vecOverlay').innerHTML='<span class="chip">embedding each passage…</span>'; $('#grOverlay').innerHTML='<span class="chip">AI extracting entities from each document…</span>';
  V.dots.transition().delay((d,i)=>200+i*vStep).duration(380).ease(d3.easeBackOut).attr('r',V.r).on('start',()=>{ if(run!==state.run)return; counters.p++; log('Embedding passages…'); });
  V.linkSel.transition().delay(200+n*vStep).duration(800).attr('stroke-opacity',.12);
  const seen=new Set();
  docs.forEach((d,di)=>setTimeout(()=>{ if(run!==state.run) return; counters.a++;
    const rels=G.links.filter(l=>l.doc===d.id);
    rels.forEach(l=>{ [l.source.id,l.target.id].forEach(id=>{ if(!seen.has(id)){ seen.add(id); counters.e++; G.nodeSel.filter(x=>x.id===id).transition().duration(350).attr('opacity',1);} }); counters.r++; });
    G.edges.filter(l=>l.doc===d.id).attr('stroke','#ffb547').attr('stroke-opacity',.9).transition().delay(300).duration(700).attr('stroke','#8fa0bd').attr('stroke-opacity',.35);
    log(`Reading "${d.title.slice(0,50)}" → ${rels.length} relation${rels.length===1?'':'s'}`); },400+di*aStep));
  const tDone=400+docs.length*aStep+300;
  setTimeout(()=>{ if(run!==state.run) return;
    G.nodeSel.attr('opacity',1);
    $('#grOverlay').innerHTML='<span class="chip">detecting communities, then writing a summary of each…</span>'; log('Clustering the graph into communities…');
    G.hullSel.transition().delay((d,i)=>i*300).duration(600).attr('fill-opacity',.07).attr('stroke-opacity',.35).on('start',()=>{ if(run!==state.run)return; counters.c++; log('Summarizing communities…'); });
    G.hullTxt.transition().delay((d,i)=>i*300+200).duration(500).attr('opacity',.85); },tDone);
  setTimeout(()=>{ if(run!==state.run) return; showIndexedNow();
    $('#vecOverlay').innerHTML='<span class="chip">hover a dot to read its passage</span>'; $('#grOverlay').innerHTML='<span class="chip">hover a node or community</span>'; },
    Math.max(tDone+G.hulls.length*300+700,200+n*vStep+500));
}

// ================= profile =================
async function renderProfile(){
  const s=state.data.stats||{}, m=curMeta();
  let graphTok, costNote;
  if(m.index_cost){ graphTok=m.index_cost.tokens_in+m.index_cost.tokens_out; costNote=`Actual cost of indexing this dataset: $${m.index_cost.dollars.toFixed(3)} (${m.index_cost.calls} AI calls).`; }
  else { try{ const e=await api(`/api/datasets/${state.ds}/estimate`); graphTok=e.graph_tokens_est; costNote=`Building this graph with ${esc(e.work_model)} would cost about $${Math.max(.01,e.dollars_est).toFixed(2)}.`; }catch(err){ graphTok=0; costNote=''; } }
  const vecTok=s.vector_tokens||1, ratio=Math.round(graphTok/vecTok);
  $('#profileCards').innerHTML=`
  <div class="card"><div class="eyebrow">Size</div><div class="stats">
    <div><b>${s.docs}</b><span>documents</span></div><div><b>${s.chunks}</b><span>passages</span></div>
    <div><b>${s.entities}</b><span>entities</span></div><div><b>${s.relations}</b><span>relations</span></div></div>
    <p>${s.docs<=50?'Small enough to read yourself, so you can check every answer.':'Too big to read in one sitting, so lean on the evidence panels to check answers.'}</p></div>
  <div class="card"><div class="eyebrow">Connectedness</div><div class="big" style="color:var(--graph)">${s.pct_multi_doc}%</div>
    <p>of entities appear in two or more documents, with ${s.avg_degree} connections each on average. ${s.pct_multi_doc>=30?'Facts about the same things are spread across documents, which is where <b style="color:var(--graph)">graph</b> traversal pays off.':'Most entities live in a single document, so the graph has fewer cross-document links to exploit.'}</p></div>
  <div class="card"><div class="eyebrow">Detail survival</div><div class="big" style="color:var(--vec)">${s.numbers_kept} of ${s.numbers}</div>
    <p>numbers, dates and amounts made it into the graph. Extraction keeps relationships and drops specifics, so exact-detail questions belong to <b style="color:var(--vec)">vector</b> search.</p></div>
  <div class="card" style="grid-column:1/-1"><div class="eyebrow">Indexing cost</div>
    <div class="costbars">
      <div class="cb"><span style="color:var(--vec)">Vector</span><div class="track"><i style="width:${Math.max(1.5,100*vecTok/Math.max(graphTok,vecTok))}%;background:var(--vec)"></i></div><span>${vecTok.toLocaleString()} tok</span></div>
      <div class="cb"><span style="color:var(--graph)">Graph</span><div class="track"><i style="width:${100*graphTok/Math.max(graphTok,vecTok)}%;background:var(--graph)"></i></div><span>${graphTok.toLocaleString()} tok</span></div>
    </div>
    <p>Embedding reads each passage once, on your computer. GraphRAG sends every document through an AI with an extraction prompt, then writes a summary for each community: roughly ${ratio}× the tokens here. ${costNote}</p></div>`;
  $('#typesTable').innerHTML=`<thead><tr><th>Question type</th><th>Example for this dataset</th><th>What it tests</th><th>Likely winner</th></tr></thead><tbody>${
    state.questions.map(q=>{ const t=state.types[q.type]||{}; return `<tr><td>${esc(q.label||t.label)}</td><td class="q">${esc(q.q)}</td><td>${esc(t.tests||'')}</td><td><span class="pill ${q.expect}">${WIN_LABEL[q.expect]}</span></td></tr>`; }).join('')}</tbody>`;
}

// ================= duel =================
const when=t=>{ try{ return new Date(t*1000).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}); }catch(e){ return ''; } };
function showSavedBar(r){
  const bar=$('#savedBar'), key=state.current&&!state.current.custom?state.current.id:'q:'+state.current.q.trim().toLowerCase();
  if(r.just_saved){ state.saved[key]=Date.now()/1000; renderDeck(); }
  if(!r.saved_at && !r.just_saved){ bar.hidden=true; return; }
  const cost=(r.meter&&r.meter.dollars)||0;
  bar.hidden=false;
  $('#savedMsg').innerHTML=r.saved_at
    ? `<b>Saved result</b> from ${esc(when(r.saved_at))}. Shown instantly, at no cost.`
    : `<b>Saved.</b> Next time you pick this question, this result comes back instantly and free.`;
  $('#rerunBtn').textContent=`Run again${cost?` (about $${cost.toFixed(cost<0.01?3:2)})`:''}`;
}
function renderDeck(){
  $('#deck').innerHTML=state.questions.map(s=>`<button class="qcard" data-id="${s.id}" aria-pressed="${state.current&&state.current.id===s.id}"><span class="ty"><span>${esc(s.label)}</span><span class="done">${[state.saved[s.id]?'saved':'',state.votes[s.id]?'voted':''].filter(Boolean).join(' · ')}</span></span><span class="qq">${esc(s.q)}</span></button>`).join('')||'<p class="lede">No test questions were generated for this dataset. Type your own below.</p>';
  document.querySelectorAll('.qcard').forEach(b=>b.onclick=()=>{ const s=state.questions.find(x=>x.id===b.dataset.id); $('#q').value=s.q; ask(s); });
  updateScore();
  $('#q').placeholder=`Ask anything about ${curMeta().name||'this dataset'}`;
  $('#qLabel').textContent=`Or type your own question about ${curMeta().name||'this dataset'}`;
}
$('#rerunBtn').onclick=()=>{ if(state.current) ask(state.current,true); };
$('#askForm').onsubmit=e=>{ e.preventDefault(); const q=$('#q').value.trim(); if(!q) return;
  const match=state.questions.find(s=>s.q.toLowerCase()===q.toLowerCase()); ask(match||{id:null,type:'custom',label:'Your question',q,custom:true}); };

async function ask(item,fresh=false){
  $('#savedBar').hidden=true;
  if(!state.shown) showIndexedNow();
  state.current=item; renderDeck();
  const t=state.types[item.type]||{};
  $('#predict').innerHTML=item.custom?'':`Testing: <b>${esc(t.tests||'')}</b> Make your guess, then watch.`;
  $('#duelResults').hidden=false; $('#lesson').hidden=true;
  ['#vecVerdict','#grVerdict','#hyVerdict','#agVerdict'].forEach(s=>$(s).hidden=true);
  $('#agSteps').innerHTML='';
  const live=state.status.has_key;
  const waitMsg={vecText:['vec','Searching passages'],grText:['gr','Walking the graph'],hyText:['hy','Routing, then searching'],agText:['ag','Planning, searching, checking']};
  Object.entries(waitMsg).forEach(([id,[c,msg]])=>{ $('#'+id).innerHTML=`<span class="spin ${c}"><span>${msg}${live?' and writing an answer':''}…</span><span class="el" data-el></span></span>`; });
  $('#vecBusy').hidden=$('#grBusy').hidden=false;
  const t0=Date.now(); clearInterval(state.elTimer);
  state.elTimer=setInterval(()=>{ const s=Math.round((Date.now()-t0)/1000); document.querySelectorAll('[data-el]').forEach(e=>e.textContent=s>=2?`${s} s`:''); },500);
  ['#vecEv','#grEv'].forEach(s=>$(s).innerHTML=''); $('#hyNote').textContent='';
  $('#router').hidden=false; $('#routeWhy').innerHTML='<span class="spin hy"><span>Deciding…</span></span>'; document.querySelectorAll('#router .route').forEach(x=>x.classList.remove('on'));
  document.querySelectorAll('#votes button').forEach(b=>b.setAttribute('aria-pressed',state.votes[item.id||item.q]&&state.votes[item.id||item.q].vote===b.dataset.v));
  const run=++state.run;
  if(!REDUCED) $('#stage').scrollIntoView({behavior:'smooth',block:'start'});
  let r; try{ r=await api(`/api/datasets/${state.ds}/ask`,{method:'POST',body:{question:item.q,sample_id:item.custom?null:item.id,fresh}}); }
  catch(e){ clearInterval(state.elTimer); $('#vecBusy').hidden=$('#grBusy').hidden=true; if(run===state.run){ $('#vecText').innerHTML=$('#grText').innerHTML=$('#hyText').innerHTML=$('#agText').innerHTML=''; showError('#lesson',e.message); } return; }
  if(run!==state.run) return;
  clearInterval(state.elTimer); $('#vecBusy').hidden=$('#grBusy').hidden=true;
  state.last=r;
  showSavedBar(r);
  document.querySelector('#router .route.'+r.route.route).classList.add('on');
  $('#routeWhy').textContent=r.route.reason+(r.route.by==='llm'?' (decided by Claude)':' (decided by simple rules)');
  animateVector(r.vector,run); animateGraph(r.graph,run);
  fillAnswers(item,r,run);
  if(state.votes[item.id||item.q]) setTimeout(()=>{ if(run===state.run) showLesson(); }, REDUCED?0:2600);
}

function animateVector(v,run){
  V.qG.selectAll('*').remove(); V.lineG.selectAll('*').remove(); V.labG.selectAll('*').remove();
  const d=D(); const hitIdx=v.hits.map(h=>h.index); const hitSet=new Set(hitIdx);
  $('#vecOverlay').innerHTML='<span class="chip q">query</span>'+v.query_terms.slice(0,8).map(t=>`<span class="chip">${esc(t)}</span>`).join('');
  V.dots.interrupt().transition().duration(600*d).attr('fill-opacity',n=>hitSet.has(n.i)?1:.22).attr('r',n=>hitSet.has(n.i)?V.r*1.4:V.r*.8).attr('fill',n=>hitSet.has(n.i)?'#7ffff0':'#3fd6c8');
  if(!v.hits.length){ $('#vecOverlay').innerHTML+=' <span class="chip warn">nothing scored above zero</span>'; return; }
  const tot=d3.sum(v.hits,h=>Math.max(h.score,.001));
  const qx=d3.sum(v.hits,h=>V.nodes[h.index].x*Math.max(h.score,.001))/tot, qy=d3.sum(v.hits,h=>V.nodes[h.index].y*Math.max(h.score,.001))/tot;
  const far=d3.max(v.hits,h=>Math.hypot(V.nodes[h.index].x-qx,V.nodes[h.index].y-qy));
  V.qG.append('circle').attr('cx',qx).attr('cy',qy).attr('r',4).attr('fill','none').attr('stroke','#ff5f8f').attr('stroke-width',1.5).attr('opacity',.9)
    .transition().delay(300*d).duration(900*d).ease(d3.easeCubicOut).attr('r',far+12).attr('opacity',.35);
  V.qG.append('circle').attr('cx',qx).attr('cy',qy).attr('r',far+12).attr('fill','#ff5f8f').attr('opacity',0).transition().delay(900*d).duration(400*d).attr('opacity',.05);
  V.qG.append('circle').attr('cx',qx).attr('cy',0).attr('r',8).attr('fill','#ff5f8f').attr('filter','url(#vglow)').transition().duration(500*d).ease(d3.easeCubicOut).attr('cy',qy);
  v.hits.forEach((h,i)=>{ const n=V.nodes[h.index]; const len=Math.hypot(n.x-qx,n.y-qy);
    V.lineG.append('line').attr('x1',qx).attr('y1',qy).attr('x2',n.x).attr('y2',n.y).attr('stroke','#ff5f8f').attr('stroke-width',1.6).attr('stroke-opacity',.8)
      .attr('stroke-dasharray',len).attr('stroke-dashoffset',len).transition().delay((700+i*200)*d).duration(400*d).attr('stroke-dashoffset',0);
    V.labG.append('text').attr('x',n.x+9).attr('y',n.y-8).attr('class','elabel').style('fill','#d6fffa').text(`#${i+1} ${h.score.toFixed(2)}`)
      .attr('opacity',0).transition().delay((900+i*200)*d).duration(300*d).attr('opacity',1); });
}
function animateGraph(g,run){
  G.ringG.selectAll('*').remove(); G.edgeLabG.selectAll('*').remove();
  const d=D();
  G.nodeSel.interrupt().attr('opacity',1); G.edges.interrupt().attr('stroke-dasharray',null);
  G.hullSel.interrupt().attr('fill-opacity',.05).attr('stroke-opacity',.25); G.hullTxt.attr('opacity',.6);
  if(g.mode==='global'){
    $('#grOverlay').innerHTML='<span class="chip q">global search</span><span class="chip">reads every community summary</span><span class="chip">merges them into one answer</span>';
    G.nodeSel.transition().duration(400*d).attr('opacity',.45); G.edges.transition().duration(400*d).attr('stroke-opacity',.15).attr('stroke','#8fa0bd');
    G.hullSel.transition().delay((x,i)=>(300+i*300)*d).duration(450*d).attr('fill-opacity',.24).attr('stroke-opacity',.95).attr('stroke-width',2).transition().duration(500*d).attr('fill-opacity',.12);
    G.hullTxt.transition().delay((x,i)=>(300+i*300)*d).duration(300*d).attr('opacity',1);
    return;
  }
  const inSub=new Set(g.nodes); const key=new Set(g.key_facts);
  G.nodeSel.transition().duration(350*d).attr('opacity',x=>inSub.has(x.id)?.35:.1);
  G.edges.transition().duration(350*d).attr('stroke-opacity',.06).attr('stroke','#8fa0bd').attr('stroke-width',1.1);
  if(!g.seeds.length){
    $('#grOverlay').innerHTML='<span class="chip warn">nothing in the question matched the graph</span><span class="chip">nothing to traverse</span>';
    gSvg.transition().duration(80*d).attr('transform','translate(-6,0)').transition().duration(80*d).attr('transform','translate(6,0)').transition().duration(80*d).attr('transform','translate(0,0)');
    return;
  }
  const howTxt={named:'named',described:'by description',similar:'by similarity'};
  $('#grOverlay').innerHTML='<span class="chip q">seeds</span>'+g.seeds.slice(0,4).map(s=>`<span class="chip">${esc(s.name)} <span style="color:var(--faint)">(${howTxt[s.how]||s.how})</span></span>`).join('')+`<span class="chip">→ ${g.hops.filter(h=>h.edges.length).length} hop(s) · ${g.facts.length} facts kept</span>`;
  const seedIds=new Set(g.seeds.map(s=>s.id));
  G.nodeSel.filter(x=>seedIds.has(x.id)).transition().delay(300*d).duration(300*d).attr('opacity',1);
  g.seeds.forEach(s=>{ const n=G.by[s.id]; if(!n) return;
    G.ringG.append('circle').attr('cx',n.x).attr('cy',n.y).attr('r',G.rad(n)).attr('fill','none').attr('stroke','#ff5f8f').attr('stroke-width',2.5).attr('filter','url(#gglow)').attr('opacity',0)
      .transition().delay(300*d).duration(250*d).attr('opacity',1).attr('r',G.rad(n)+6); });
  g.hops.forEach((hop,h)=>{ const t0=(700+h*800)*d; const es=new Set(hop.edges);
    G.edges.filter(l=>es.has(l.i)).each(function(l){ const len=Math.hypot(l.source.x-l.target.x,l.source.y-l.target.y);
      d3.select(this).transition().delay(t0).duration(0).attr('stroke','#ffb547').attr('stroke-opacity',.75).attr('stroke-width',1.5).attr('stroke-dasharray',len).attr('stroke-dashoffset',len)
        .transition().duration(500*d).attr('stroke-dashoffset',0).transition().duration(0).attr('stroke-dasharray',null); });
    const ns=new Set(hop.nodes); G.nodeSel.filter(x=>ns.has(x.id)).transition().delay(t0+350*d).duration(300*d).attr('opacity',.9); });
  const tKey=(700+g.hops.length*800+200)*d;
  G.edges.filter(l=>key.has(l.i)).transition().delay(tKey).duration(400*d).attr('stroke','#ff5f8f').attr('stroke-width',3).attr('stroke-opacity',1);
  G.links.filter(l=>key.has(l.i)).forEach(l=>{ G.nodeSel.filter(x=>x.id===l.source.id||x.id===l.target.id).transition().delay(tKey).duration(300*d).attr('opacity',1);
    G.edgeLabG.append('text').attr('class','elabel').attr('x',(l.source.x+l.target.x)/2).attr('y',(l.source.y+l.target.y)/2-4).attr('text-anchor','middle').text(l.rel.slice(0,28))
      .attr('opacity',0).transition().delay(tKey+200*d).duration(300*d).attr('opacity',1); });
}

function typeText(el,text,run,delay){
  if(REDUCED){ el.textContent=text; return; }
  setTimeout(()=>{ if(run!==state.run) return; el.innerHTML=''; let i=0; const cur=document.createElement('span'); cur.className='cursor';
    const tick=()=>{ if(run!==state.run) return; i=Math.min(text.length,i+3); el.textContent=text.slice(0,i); el.appendChild(cur); if(i<text.length) requestAnimationFrame(tick); else setTimeout(()=>cur.remove(),600); };
    tick(); },delay);
}
const tokensOf=w=>{ const m=String(w).toLowerCase().match(/[a-z0-9$]+/); if(!m) return ''; let s=m[0];
  if(s.length>5&&s.endsWith('ing')) s=s.slice(0,-3); else if(s.length>4&&s.endsWith('ed')) s=s.slice(0,-2); if(s.length>3&&s.endsWith('s')&&!s.endsWith('ss')) s=s.slice(0,-1); return s; };
const markShared=(text,shared)=>esc(text).replace(/[A-Za-z0-9$]+/g,w=>shared.includes(tokensOf(w))?`<mark>${w}</mark>`:w);

function fillAnswers(item,r,run){
  const d=D(), v=r.vector, g=r.graph, hy=r.hybrid, ag=r.agent;
  const maxTok=Math.max(v.context_tokens,g.context_tokens,hy.context_tokens,ag.context_tokens,1), maxLat=Math.max(v.latency,g.latency,hy.latency,ag.latency,.1);
  const lat=x=>(r.estimated_latency?'~':'')+x.toFixed(1)+' s';
  setTimeout(()=>{ if(run!==state.run) return;
    [['vec',v],['gr',g],['hy',hy],['ag',ag]].forEach(([p,x])=>{ $('#'+p+'Bar').style.width=(100*x.context_tokens/maxTok)+'%'; $('#'+p+'Tok').textContent=x.context_tokens+' tok';
      $('#'+p+'LatBar').style.width=(100*x.latency/maxLat)+'%'; $('#'+p+'Lat').textContent=lat(x.latency); }); },600*d);
  $('#vecEv').innerHTML=v.hits.length?v.hits.map((h,i)=>`<li><span class="s">#${i+1} ${h.score.toFixed(2)}</span>${markShared(h.text.length>500?h.text.slice(0,500)+'…':h.text,h.shared)}<span class="src">${esc(h.date?h.date+' · ':'')}${esc(h.title)}</span></li>`).join(''):'<li>No passage scored above zero.</li>';
  const docTitle=Object.fromEntries(state.data.docs.map(x=>[x.id,x.title]));
  if(g.mode==='global') $('#grEv').innerHTML=g.summaries.map(c=>`<li class="comm" style="border-left-color:${c.color}"><b>${esc(c.title)}.</b> ${esc(c.summary)}<span class="src">community summary · written at index time</span></li>`).join('');
  else if(!g.seeds.length) $('#grEv').innerHTML='<li>No entities matched, so no facts were retrieved.</li>';
  else { const key=new Set(g.key_facts); const shown=g.facts.slice(0,14);
    $('#grEv').innerHTML=shown.map(f=>`<li class="${key.has(f.i)?'path':''}">${esc(f.text)}<span class="src">extracted from ${esc(docTitle[f.doc]||f.doc)}</span></li>`).join('')+(g.facts.length>14?`<li>…plus ${g.facts.length-14} more facts and ${g.nodes.length} entity descriptions</li>`:''); }
  $('#hyNote').textContent=`Routed to ${ROUTE_LABEL[r.route.route]}. It used the evidence shown in the ${r.route.route==='both'?'two cards':(r.route.route==='vector'?'Vector card':'GraphRAG card')} above, plus a small routing step.`;
  const noAns=who=>who==='vector'?(v.hits.length?'With an API key, Claude would write this answer from the passages listed below. Read them and judge: do they contain what you asked for?':'Nothing relevant was retrieved, so a careful model should say it doesn\'t know.')
    :who==='graph'?(g.mode==='global'?'This looked like a big-picture question, so GraphRAG would answer from the community summaries below.':(g.seeds.length?'With an API key, Claude would write this answer from the facts below, gathered by walking out from the entities your question named.':'Your question named nothing the graph knows about, so GraphRAG has nothing to work with. Try including a person, place or organization.'))
    :'With an API key, Claude would answer from the evidence the router picked.';
  const gd=D();
  typeText($('#vecText'),v.answer||noAns('vector'),run,1300*gd);
  typeText($('#grText'),g.answer||noAns('graph'),run,(g.mode==='global'?2000:1500+g.hops.length*500)*gd);
  typeText($('#hyText'),hy.answer||noAns('hybrid'),run,2100*gd);
  renderAgentSteps(ag,r,run);
  const agNo=ag.planner==='rules'?'Without an API key the agent follows simple rules instead of thinking, and can\'t write an answer. Its searches are shown below.':'With an API key, Claude would write this answer from everything the agent gathered.';
  typeText($('#agText'),ag.answer||agNo,run,(2400+ag.steps.length*450)*gd);
  if(!r.live && !r.canned) $('#hyNote').textContent+=' Live answers need an API key.';
  $('#footnote').textContent=r.live?`Retrieval ran on your computer. Answers were written live by ${state.status.answer_model}${r.vector.grade?', and graded against the reference answer by '+state.status.work_model:''}. Latency is measured; this question cost about $${(r.meter.dollars||0).toFixed(4)}.`
    :(r.canned?'Demo mode: retrieval ran live, but these answers were pre-written from exactly the evidence shown. Add an API key for live answers. Latency figures are typical values, not measurements.'
    :'Demo mode: retrieval ran live, but writing answers needs an API key. Latency figures are typical values, not measurements.');
}

// ---------- voting & lessons ----------
document.querySelectorAll('#votes button').forEach(b=>b.onclick=async ()=>{
  const it=state.current, r=state.last; if(!it||!r) return;
  const grades={vector:(r.vector.grade||{}).grade,graph:(r.graph.grade||{}).grade,hybrid:(r.hybrid.grade||{}).grade,agent:(r.agent.grade||{}).grade};
  if(state.status.public){ state.votes[it.id||it.q]={q:it.q,vote:b.dataset.v,grades,t:Date.now()}; saveLocalVotes(state.votes); }
  else { try{ state.votes=await api(`/api/datasets/${state.ds}/votes`,{method:'POST',body:{qid:it.id,question:it.q,vote:b.dataset.v,grades}}); }catch(e){} }
  document.querySelectorAll('#votes button').forEach(x=>x.setAttribute('aria-pressed',x===b));
  renderDeck(); showLesson(); updateScore();
});
function gradePill(sel,gr){ const el=$(sel); if(!gr){ el.hidden=true; return; } el.hidden=false; el.className='pill '+(gr.grade==='correct'?'ok':gr.grade==='wrong'?'bad':gr.grade); el.textContent=gr.grade==='correct'?'correct':gr.grade==='partial'?'partly right':gr.grade==='wrong'?'wrong or incomplete':'not graded'; el.title=gr.why||''; }
function renderAgentSteps(ag,r,run){
  const d=D(); const ol=$('#agSteps'); ol.innerHTML='';
  const cost=s=>r.live&&s.tokens?`<span class="cost">${s.tokens.toLocaleString()} tok · $${s.dollars.toFixed(4)}</span>`:'';
  const html=ag.steps.map(s=>{
    if(s.kind==='plan') return `<li class="plan"><b>Plan.</b> ${esc(s.text)}${s.rewritten?`<span class="found">Rewrote the question as: <span class="q">"${esc(s.rewritten)}"</span></span>`:''}${cost(s)}</li>`;
    if(s.kind==='search') return `<li class="search ${s.tool}"><b>Search:</b> ${esc(s.text)}<span class="found">${esc(s.found||'')}</span></li>`;
    if(s.kind==='check') return `<li class="check ${s.next?'no':''}"><b>${s.next?'Not enough yet.':'Check: enough.'}</b> ${esc(s.text)}${s.next?`<span class="found">Next: ${esc(s.next)}</span>`:''}${cost(s)}</li>`;
    return `<li class="answer"><b>Answer.</b> ${esc(s.text)}${cost(s)}</li>`; });
  if(!ag.steps.some(s=>s.kind==='answer')) html.push(`<li class="answer"><b>Answer.</b> ${r.canned?'Pre-written for the demo from the evidence gathered above.':'Writing the answer needs an API key.'}</li>`);
  html.forEach((h,i)=>setTimeout(()=>{ if(run!==state.run) return; ol.insertAdjacentHTML('beforeend',h); },(900+i*450)*d));
  const m=ag.meter||{};
  if(r.live) setTimeout(()=>{ if(run===state.run) ol.insertAdjacentHTML('afterend',`<p class="note" id="agTotal" style="color:var(--faint);font-size:12px;margin:4px 0 0">${ag.searches} searches, ${m.calls} AI calls, ${(m.tokens||0).toLocaleString()} tokens, about $${(m.dollars||0).toFixed(4)} for the agent alone.</p>`); },(900+html.length*450)*d);
  const old=$('#agTotal'); if(old) old.remove();
}
function showLesson(){
  const it=state.current, r=state.last; const L=$('#lesson'); L.hidden=false;
  const key=it.id||it.q; const vote=(state.votes[key]||{}).vote;
  gradePill('#vecVerdict',r.vector.grade); gradePill('#grVerdict',r.graph.grade); gradePill('#hyVerdict',r.hybrid.grade); gradePill('#agVerdict',r.agent.grade);
  const hyLine=`<p style="color:var(--muted)"><b style="color:var(--fg)">Hybrid</b> routed this to ${ROUTE_LABEL[r.route.route]}${r.hybrid.grade?` and the judge rated it <b>${esc(r.hybrid.grade.grade)}</b>`:''}, using ${r.hybrid.context_tokens} tokens of context.${r.route.route==='both'?' Merging is the safe choice, but it pays for both searches.':''}</p>
    <p style="color:var(--muted)"><b style="color:var(--agent)">Agentic</b> took ${r.agent.searches} search${r.agent.searches===1?'':'es'}${r.agent.grade?` and was rated <b>${esc(r.agent.grade.grade)}</b>`:''}. ${r.agent.searches>1?'Each extra round costs time and tokens; that\'s the price of being able to change course.':'When the first search is enough, the agent costs little more than the simple router.'}</p>`;
  const judged=r.live&&r.vector.grade?`<p style="color:var(--muted)">The auto-judge compared each answer with the reference answer: vector <b>${esc(r.vector.grade.grade)}</b>, graph <b>${esc(r.graph.grade.grade)}</b>, hybrid <b>${esc(r.hybrid.grade.grade)}</b>, agentic <b>${esc((r.agent.grade||{}).grade||'?')}</b>. Hover a result tag to see why.</p>`:'';
  if(it.custom){
    const g=r.graph; let msg;
    if(g.mode==='global') msg='Your question asked for the big picture, which triggers GraphRAG\'s global search over community summaries. Vector search can only return a handful of passages, so it rarely covers a whole collection.';
    else if(!g.seeds.length) msg='Nothing in your question matched the graph, so GraphRAG couldn\'t start. That\'s typical for vague or topical questions, which is vector search\'s home turf.';
    else msg=`GraphRAG started from ${g.seeds.slice(0,3).map(s=>esc(s.name)).join(', ')} and followed the connections out. If your answer needs a date, number or exact wording, check whether it survived extraction; the vector evidence keeps the original sentences.`;
    L.innerHTML=`<div style="display:flex;flex-direction:column;gap:10px"><p>${msg}</p>${hyLine}</div><div class="rule"><div class="eyebrow">Try next</div><p>Rephrase it as a different question type from the deck, and see whether the winner changes.</p></div>`;
    return;
  }
  const t=state.types[it.type]||{};
  const agree=vote===it.expect;
  L.innerHTML=`<div style="display:flex;flex-direction:column;gap:10px"><div class="row">You said <span class="pill ${vote==='neither'?'tie':vote}">${WIN_LABEL[vote]}</span> · The lesson's pick <span class="pill ${it.expect}">${WIN_LABEL[it.expect]}</span> ${agree?'<span style="color:var(--ok)">You agree with the lesson.</span>':'<span style="color:var(--muted)">You picked differently from the lesson. Compare the evidence above to see why.</span>'}</div>
    <p>${esc(it.lesson||t.lesson||'')}</p>${it.note?`<p style="color:var(--muted)">${esc(it.note)}</p>`:''}${judged}${hyLine}
    ${it.answer&&!it.canned?`<p style="color:var(--faint);font-size:13px">Reference answer: ${esc(it.answer)}</p>`:''}</div>
  <div class="rule"><div class="eyebrow">Rule of thumb</div><p>${esc(it.rule||t.rule||'')}</p></div>`;
}
function updateScore(){ const done=state.questions.filter(s=>state.votes[s.id]).length; $('#score').textContent=`${done} of ${state.questions.length} test questions tried`; }

// ================= debrief =================
function renderDebrief(){
  const qs=state.questions; const voted=qs.filter(s=>state.votes[s.id]);
  const tally={vector:0,graph:0,hybrid:0,agentic:0,tie:0,neither:0}; voted.forEach(s=>{ const v=state.votes[s.id].vote; tally[v]=(tally[v]||0)+1; });
  $('#debriefLede').textContent=voted.length?`You judged ${voted.length} of ${qs.length} test questions on ${curMeta().name}: vector won ${tally.vector}, graph ${tally.graph}, hybrid ${tally.hybrid}, agentic ${tally.agentic}, and ${tally.tie} tie${tally.tie===1?'':'s'}. Vector and graph each win a different kind of question; combining them helps, and an agent that can change course helps most, at a higher cost per question.`
    :'You haven\'t voted yet. Here is what each question type usually shows. Try a few in the duel to fill in your own column.';
  const gp=(g)=>g?`<span class="pill ${g==='correct'?'ok':g==='wrong'?'bad':g}">${g==='correct'?'right':g==='partial'?'partly':g==='wrong'?'missed':'?'}</span>`:'<span style="color:var(--faint)">not run</span>';
  const customs=Object.entries(state.votes).filter(([k])=>!qs.find(q=>q.id===k)).map(([k,v])=>({id:k,label:'Your question',q:v.q,custom:true}));
  $('#resultsTable').innerHTML=`<thead><tr><th>Question type</th><th>Question</th><th>Vector</th><th>Graph</th><th>Hybrid</th><th>Agentic</th><th>Your vote</th><th>Lesson's pick</th><th>Rule of thumb</th></tr></thead><tbody>${
    [...qs,...customs].map(s=>{ const vv=state.votes[s.id]; const gr=(vv&&vv.grades)||{}; const t=state.types[s.type]||{};
      return `<tr><td>${esc(s.label)}</td><td class="q">${esc(s.q)}</td><td>${gp(gr.vector)}</td><td>${gp(gr.graph)}</td><td style="white-space:nowrap">${gp(gr.hybrid)}</td><td>${gp(gr.agent)}</td>
      <td>${vv?`<span class="pill ${vv.vote==='neither'?'tie':vv.vote}">${WIN_LABEL[vv.vote]}</span>`:'<span style="color:var(--faint)">not tried</span>'}</td>
      <td>${s.expect?`<span class="pill ${s.expect}">${WIN_LABEL[s.expect]}</span>`:''}</td><td class="q">${esc(s.rule||t.rule||'')}</td></tr>`; }).join('')}</tbody>`;
}
$('#resetVotes').onclick=async ()=>{ if(state.status.public) saveLocalVotes({}); else await api(`/api/datasets/${state.ds}/votes`,{method:'DELETE'}); state.votes={}; renderDebrief(); renderDeck(); };

// ---------------- basics walkthrough ----------------
const dot=(x,y,cls,delay)=>`<circle cx="${x}" cy="${y}" r="7" fill="#3fd6c8" fill-opacity=".5" class="${cls||''}" style="animation-delay:${delay||0}s"/>`;
const SLIDES=[
{eyebrow:'The problem',title:'AI models don\'t know your documents',
 copy:`<p>A language model like Claude learned from a huge amount of public text, but it has never seen your company's files, your notes, or this week's local news. Ask about them and it either says it doesn't know or, worse, makes something up.</p>
 <p>Retraining the model on your documents is slow and expensive. There's a simpler trick, and it's what this whole tool is about.</p>`,
 visual:`<div class="chat">
  <div class="bub you pop"><span class="who">You</span>Who's paying for the Larkspur seawall?</div>
  <div class="bub ai pop" style="animation-delay:.6s"><span class="who">AI</span>I don't have any information about a seawall in Larkspur. Could you share more details?</div>
 </div><p class="small pop" style="animation-delay:1.1s">Larkspur Cove is a made-up town we'll use as our test case. You'll meet it at the end of this walkthrough.</p>`},
{eyebrow:'The fix',title:'RAG: search first, then answer',
 copy:`<p><span class="term">RAG</span> stands for retrieval-augmented generation. Before the AI answers, a search step finds the most relevant pieces of your documents and pastes them into the prompt. The AI then answers from that text, like a student taking an open-book exam.</p>
 <div class="catch">The AI can only use what the search hands it. If the search misses the key passage, the answer will be wrong, and often confidently wrong. So everything depends on one question: how do you search?</div>
 <p class="small">This tool compares two different ways of doing that search.</p>`,
 visual:`<div class="pipe">
  <div class="pop"><b>Question</b><span>"Who pays for the seawall?"</span></div>
  <div class="hot pop" style="animation-delay:.3s"><b>Search</b><span>through your documents</span></div>
  <div class="pop" style="animation-delay:.6s"><b>Relevant pieces</b><span>pasted into the prompt</span></div>
  <div class="pop" style="animation-delay:.9s"><b>AI reads them</b><span>and writes an answer</span></div>
  <div class="pop" style="animation-delay:1.2s"><b>Answer</b><span>"Northgate Capital"</span></div>
 </div><div class="pipelabel pop" style="animation-delay:1.5s">The search step is what we're testing</div>`},
{eyebrow:'Approach 1',title:'Vector RAG: search by similar meaning',
 copy:`<ol class="how"><li>Cut every document into short passages.</li>
 <li>An <span class="term v">embedding model</span> turns each passage into a long list of numbers that captures what it's about. Think of them as coordinates on a map of meaning: passages about similar things land near each other.</li>
 <li>Your question gets coordinates too.</li>
 <li>Grab the few passages nearest the question and give them to the AI.</li></ol>
 <div class="catch"><b>Strength:</b> fast, cheap, and keeps the exact wording. <b>Blind spot:</b> it only finds passages that resemble the question.</div>`,
 visual:`<svg viewBox="0 0 420 300" role="img" aria-label="Passages on a map of meaning, with a question finding its nearest neighbors">
  <circle cx="210" cy="150" r="140" fill="none" stroke="#233554" stroke-dasharray="2 6"/><circle cx="210" cy="150" r="80" fill="none" stroke="#233554" stroke-dasharray="2 6"/>
  ${dot(90,80)}${dot(120,66,'lit',2.1)}${dot(105,108,'lit',1.9)}${dot(140,96,'lit',2)}${dot(76,114)}
  ${dot(290,74)}${dot(318,90)}${dot(298,114)}${dot(334,110)}
  ${dot(180,212)}${dot(214,200)}${dot(200,240)}${dot(234,230)}${dot(166,244)}
  <text x="44" y="150" fill="#8fa0bd" font-size="12" font-family="JetBrains Mono, monospace">seawall &amp; money</text>
  <text x="268" y="146" fill="#8fa0bd" font-size="12" font-family="JetBrains Mono, monospace">ferry &amp; boats</text>
  <text x="160" y="280" fill="#8fa0bd" font-size="12" font-family="JetBrains Mono, monospace">lighthouse</text>
  <circle cx="114" cy="92" r="44" fill="#ff5f8f" fill-opacity=".06" stroke="#ff5f8f" stroke-width="1.5" class="ring" style="animation-delay:.9s"/>
  <line x1="114" y1="92" x2="120" y2="66" stroke="#ff5f8f" stroke-width="2" class="draw" style="animation-delay:1.6s"/>
  <line x1="114" y1="92" x2="105" y2="108" stroke="#ff5f8f" stroke-width="2" class="draw" style="animation-delay:1.5s"/>
  <line x1="114" y1="92" x2="140" y2="96" stroke="#ff5f8f" stroke-width="2" class="draw" style="animation-delay:1.55s"/>
  <circle cx="114" cy="92" r="8" fill="#ff5f8f" class="pop" style="animation-delay:.4s"/>
  <text x="14" y="26" fill="#ffc2d4" font-size="13" class="pop" style="animation-delay:.4s">Question: "Who pays for the seawall?"</text>
 </svg><p class="small">Real embeddings have hundreds of dimensions. We flatten them to two so you can see them.</p>`},
{eyebrow:'Approach 2',title:'GraphRAG: search by following connections',
 copy:`<ol class="how"><li>Before anyone asks anything, an AI reads every document and writes down the people, places and things it mentions, and how they relate: "Mara Quill chairs the Harbor Council."</li>
 <li>Together these form a <span class="term g">knowledge graph</span>: circles for things, lines for relationships.</li>
 <li>At question time, find the things your question names, then walk outward along the lines.</li>
 <li>Give the facts collected along the way to the AI.</li></ol>
 <div class="catch"><b>Strength:</b> connects facts spread across different documents. <b>Blind spot:</b> it needs a name to start from, and it only knows what the extraction wrote down.</div>`,
 visual:`<span class="chip q pop" style="align-self:flex-start">"Which business does the council chair's sister run?"</span>
 <svg viewBox="0 0 420 300" role="img" aria-label="Knowledge graph with a path from Harbor Council to The Brass Kettle">
  <g stroke="#8fa0bd" stroke-opacity=".45" stroke-width="1.5">
   <line x1="90" y1="60" x2="190" y2="140"/><line x1="190" y1="140" x2="310" y2="140"/><line x1="310" y1="140" x2="360" y2="245"/>
   <line x1="60" y1="175" x2="90" y2="60"/><line x1="60" y1="175" x2="110" y2="255"/><line x1="310" y1="140" x2="240" y2="245"/></g>
  <g stroke="#ff5f8f" stroke-width="3.5" stroke-linecap="round">
   <line x1="90" y1="60" x2="190" y2="140" class="draw" style="animation-delay:1s"/>
   <line x1="190" y1="140" x2="310" y2="140" class="draw" style="animation-delay:1.7s"/>
   <line x1="310" y1="140" x2="360" y2="245" class="draw" style="animation-delay:2.4s"/></g>
  <g font-family="JetBrains Mono, monospace" font-size="11" fill="#ffd9a0">
   <text x="148" y="92" class="pop" style="animation-delay:1.3s">chairs</text>
   <text x="222" y="130" class="pop" style="animation-delay:2s">sister of</text>
   <text x="342" y="190" class="pop" style="animation-delay:2.7s">owns</text></g>
  <circle cx="90" cy="60" r="20" fill="none" stroke="#ff5f8f" stroke-width="2.5" class="pop" style="animation-delay:.5s"/>
  <g fill="#ffb547" stroke="#0b1424" stroke-width="2">
   <circle cx="90" cy="60" r="12"/><circle cx="190" cy="140" r="12"/><circle cx="310" cy="140" r="12"/><circle cx="360" cy="245" r="12"/>
   <circle cx="60" cy="175" r="10" fill="#6b5430"/><circle cx="110" cy="255" r="10" fill="#6b5430"/><circle cx="240" cy="245" r="10" fill="#6b5430"/></g>
  <g font-size="12.5" fill="#e9eef7" text-anchor="middle">
   <text x="90" y="34">Harbor Council</text><text x="190" y="168">Mara Quill</text><text x="310" y="118">Ines Quill</text><text x="360" y="274">The Brass Kettle</text>
   <text x="60" y="200" fill="#8fa0bd">Amos Pike</text><text x="110" y="280" fill="#8fa0bd">Seawall</text><text x="240" y="272" fill="#8fa0bd">Harvest Market</text></g>
 </svg><p class="small">Each fact may come from a different article. The graph joins them.</p>`},
{eyebrow:'GraphRAG\'s extra trick',title:'Communities: the big picture, prepared in advance',
 copy:`<p>Some questions have no single right passage: "What's going on in town this year?" GraphRAG handles these by grouping densely connected parts of the graph into <span class="term g">communities</span>, then having the AI write a short summary of each one, once, while it builds the index.</p>
 <p>For a big-picture question, it reads those summaries and combines them. Vector search can't do this, because it only ever sees a handful of passages.</p>
 <div class="catch"><b>The price:</b> all that reading and summarizing happens before your first question, and it costs many times more than vector indexing.</div>`,
 visual:`<svg viewBox="0 0 420 210" role="img" aria-label="Three communities in a graph">
  <ellipse cx="105" cy="80" rx="88" ry="62" fill="#ff8a5c" fill-opacity=".14" stroke="#ff8a5c" class="pop"/>
  <ellipse cx="305" cy="78" rx="90" ry="60" fill="#5ce1c6" fill-opacity=".12" stroke="#5ce1c6" class="pop" style="animation-delay:.4s"/>
  <ellipse cx="210" cy="165" rx="110" ry="40" fill="#b49cff" fill-opacity=".14" stroke="#b49cff" class="pop" style="animation-delay:.8s"/>
  <g fill="#ff8a5c"><circle cx="80" cy="70" r="7"/><circle cx="120" cy="58" r="7"/><circle cx="110" cy="100" r="7"/><circle cx="145" cy="82" r="6"/></g>
  <g fill="#5ce1c6"><circle cx="280" cy="64" r="7"/><circle cx="320" cy="60" r="7"/><circle cx="300" cy="98" r="7"/><circle cx="345" cy="92" r="6"/></g>
  <g fill="#b49cff"><circle cx="170" cy="165" r="7"/><circle cx="215" cy="158" r="7"/><circle cx="255" cy="170" r="7"/></g>
  <g stroke="#8fa0bd" stroke-opacity=".5"><line x1="80" y1="70" x2="120" y2="58"/><line x1="120" y1="58" x2="110" y2="100"/><line x1="110" y1="100" x2="145" y2="82"/>
  <line x1="280" y1="64" x2="320" y2="60"/><line x1="320" y1="60" x2="300" y2="98"/><line x1="300" y1="98" x2="345" y2="92"/>
  <line x1="170" y1="165" x2="215" y2="158"/><line x1="215" y1="158" x2="255" y2="170"/><line x1="145" y1="82" x2="280" y2="64"/><line x1="110" y1="100" x2="170" y2="165"/></g>
 </svg>
 <ul class="evlist" style="max-height:none">
  <li class="comm pop" style="border-left-color:#ff8a5c;animation-delay:1.2s"><b>Harbor politics.</b> A seawall fight, a developer's money, a delayed vote.</li>
  <li class="comm pop" style="border-left-color:#5ce1c6;animation-delay:1.5s"><b>Coast &amp; ecology.</b> A survey says the wall would smother the eelgrass.</li>
  <li class="comm pop" style="border-left-color:#b49cff;animation-delay:1.8s"><b>Lighthouse &amp; heritage.</b> A rediscovered 1903 charter may block the condos.</li></ul>`},
{eyebrow:'The tradeoff',title:'Each one misses different things',
 copy:`<p>Neither approach is better overall. They succeed and fail on different kinds of questions.</p>
 <p>The rest of this tool lets you see that for yourself: same documents, same question, both searches running side by side, with the evidence each one found laid out so you can judge.</p>`,
 visual:`<div class="vs">
  <div class="card vecc pop"><h3>Vector RAG</h3><ul>
   <li class="plus">Finds exact facts, dates and quotes</li><li class="plus">Works on vague questions with no names</li><li class="plus">Cheap and quick to set up</li>
   <li class="minus">Misses answers spread across documents</li><li class="minus">Returns only a few passages, so lists get cut off</li><li class="minus">Can't see the big picture</li></ul></div>
  <div class="card grc pop" style="animation-delay:.3s"><h3>GraphRAG</h3><ul>
   <li class="plus">Follows chains: A's B's C</li><li class="plus">Finds everything connected to something</li><li class="plus">Answers big-picture questions</li>
   <li class="minus">Drops details like dates during extraction</li><li class="minus">Needs a name in the question to start</li><li class="minus">Expensive to build</li></ul></div>
 </div>`},
{eyebrow:'In practice',title:'Why not both?',
 copy:`<p>Because each approach's blind spots are the other's strengths, real systems often combine them. Four common patterns:</p>
 <ol class="how"><li><b>Routing:</b> check what kind of question it is, then send it to the right search.</li>
 <li><b>Run both and merge:</b> search both ways and combine the results, often with a ranking model picking the best pieces.</li>
 <li><b>Graph-enhanced vector search:</b> find passages by meaning first, then follow graph connections out from the names in them.</li>
 <li><b>Agentic:</b> give the AI the search tools and let it decide, step by step, which to use and when it has enough.</li></ol>
 <div class="catch"><b>Reality check:</b> the most common combination in production is vector search plus old-fashioned keyword search (good for exact names, codes and IDs). Full GraphRAG is used where relationships really matter, because building the graph is expensive.</div>`,
 visual:`<div class="routes">
  <div class="box pop">"Which business does the council chair's sister run?"</div>
  <div class="down pop" style="animation-delay:.3s">↓</div>
  <div class="box r pop" style="animation-delay:.5s"><b>Router</b>: what kind of question is this?</div>
  <div class="down pop" style="animation-delay:.8s">↓</div>
  <div class="branches">
   <div class="pop" style="animation-delay:1s"><b style="color:var(--vec)">Vector</b>Exact details, vague topics. "When does the ferry stop?"</div>
   <div class="pop" style="animation-delay:1.2s"><b style="color:var(--fg)">Both</b>Named things that may need details too. "Which business does the chair's sister run?"</div>
   <div class="pop" style="animation-delay:1.4s"><b style="color:var(--graph)">Graph</b>Complete lists, big picture. "List everyone connected to Gull Point."</div>
  </div>
 </div><p class="small">In the Duel, Hybrid uses a router like this. A fourth contestant, Agentic, goes further: it rewrites the question, checks its evidence, and searches again when it falls short.</p>`},
{eyebrow:'Your test lab',title:'Meet Larkspur Cove',
 copy:`<p>Larkspur Cove is an invented harbor town with 17 short news articles: a seawall fight, a lighthouse restoration, a ferry, a few feuds.</p>
 <p>Because it's fictional, the AI can't answer from its training data. Every right answer has to come from the search, which is exactly what we want to test.</p>`,
 visual:`<div class="road">
  <div class="pop"><span class="n">Step 2</span><b>Load</b>Watch both systems build their indexes from the articles.</div>
  <div class="pop" style="animation-delay:.2s"><span class="n">Step 3</span><b>Profile</b>See what kind of data this is and what that predicts.</div>
  <div class="pop" style="animation-delay:.4s"><span class="n">Step 4</span><b>Duel</b>Ask questions and watch both searches work, then judge.</div>
  <div class="pop" style="animation-delay:.6s"><span class="n">Step 5</span><b>Debrief</b>A guide to when to use which, built from your results.</div>
 </div>`},
];
let slideIdx=0; const seenSlides=new Set([0]);
function renderSlide(i){
  slideIdx=Math.max(0,Math.min(SLIDES.length-1,i)); seenSlides.add(slideIdx);
  const s=SLIDES[slideIdx];
  const el=$('#slide');
  el.className='slide'; void el.offsetWidth;
  el.innerHTML=`<div class="copy"><div class="eyebrow">${slideIdx+1} of ${SLIDES.length} · ${s.eyebrow}</div><h2>${s.title}</h2>${s.copy}</div><div class="visual">${s.visual}</div>`;
  el.querySelectorAll('.draw').forEach(l=>{ try{ l.style.setProperty('--len',Math.ceil(l.getTotalLength())+1); }catch(e){} });
  el.className='slide anim';
  $('#dots').innerHTML=SLIDES.map((x,k)=>`<button aria-label="Slide ${k+1}: ${x.eyebrow}" aria-current="${k===slideIdx}" class="${seenSlides.has(k)?'seen':''}"></button>`).join('');
  $('#dots').querySelectorAll('button').forEach((b,k)=>b.onclick=()=>renderSlide(k));
  $('#prevSlide').disabled=slideIdx===0;
  $('#nextSlide').textContent=slideIdx===SLIDES.length-1?'Build the indexes →':'Next';
  $('#nextSlide').classList.toggle('big',slideIdx===SLIDES.length-1);
}
$('#prevSlide').onclick=()=>renderSlide(slideIdx-1);
$('#nextSlide').onclick=()=>{ if(slideIdx===SLIDES.length-1){ go('load'); window.scrollTo({top:0,behavior:REDUCED?'auto':'smooth'}); } else renderSlide(slideIdx+1); };
document.addEventListener('keydown',e=>{
  if($('#step-basics').hidden||/input|textarea/i.test(e.target.tagName)) return;
  if(e.key==='ArrowRight') $('#nextSlide').click(); if(e.key==='ArrowLeft'&&slideIdx>0) renderSlide(slideIdx-1);
});



// ================= boot =================
(async function boot(){
  try{ state.status=await api('/api/status'); }catch(e){ state.status={}; }
  const chip=$('#liveChip');
  if(state.status.has_key){ chip.textContent=state.status.fake?'Test mode · stand-in AI':'Live · Claude'; chip.classList.add('live'); chip.title=`Answers by ${state.status.answer_model}; extraction by ${state.status.work_model}`; }
  else if(state.status.public){ chip.textContent='Hosted demo · pre-written answers'; chip.title='Run it on your computer for live answers and your own data'; }
  else { chip.textContent='Demo mode · no API key'; chip.title='Add ANTHROPIC_API_KEY to .env for live answers and your own datasets'; }
  await refreshDatasets();
  let pick=null; try{ pick=localStorage.getItem('rd-ds'); }catch(e){}
  if(!state.datasets.find(d=>d.slug===pick)) pick=(state.datasets[0]||{}).slug;
  renderSlide(0);
  if(pick) await selectDataset(pick);
  go(location.hash.slice(1)||'basics');
})();
})();
