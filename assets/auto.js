/* Gold Macro Radar automatic panel. No executable remote strings or API keys in browser. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const LABEL = {bull:'利多黄金',bear:'利空黄金',mixed:'多空交织',neutral:'中性',unknown:'待确认'};
  const LABEL_CSS = {bull:'pos',bear:'neg',mixed:'warn',neutral:'flat',unknown:'flat'};
  let snapshot = null;
  let history = [];
  let selection = 'all';
  const stamp = d => {
    if (!d) return '尚未更新';
    const time = new Date(d);
    if (Number.isNaN(time.getTime())) return '时间未知';
    return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(time) + ' JST';
  };
  function tag(value) {
    const el=document.createElement('span');
    el.className='auto-signal ' + (LABEL_CSS[value] || 'flat');
    el.textContent=LABEL[value] || '待确认';
    return el;
  }
  function child(parent, elementName, value, cls) {
    const el=document.createElement(elementName);
    if (cls) el.className=cls;
    if (value!==undefined && value!==null) el.textContent=String(value);
    parent.appendChild(el);
    return el;
  }
  function href(url) { try { const u=new URL(url); return u.protocol==='https:'?u.href:null; } catch {return null;} }
  function link(parent, url, text) {
    const safe=href(url); if (!safe) return;
    const el=child(parent,'a',text,'auto-link');
    el.href=safe; el.target='_blank'; el.rel='noopener noreferrer';
  }
  function empty(container, msg) { container.replaceChildren(); child(container,'p',msg,'auto-empty'); }
  function price(x, unit) { return typeof x==='number'?x.toLocaleString('zh-CN',{maximumFractionDigits:3})+(unit?' '+unit:''):'—'; }
  function factorCard(f) {
    const box=document.createElement('div');box.className='auto-factor';
    const header=child(box,'div',null,'auto-factor-head');
    child(header,'b',f.name);header.appendChild(tag(f.signal));
    const value=child(box,'div',null,'auto-factor-value');
    child(value,'strong',price(f.value,f.unit));
    child(value,'small',`变动 ${typeof f.delta==='number'?(f.delta>0?'+':'')+price(f.delta,f.delta_unit):'—'}`);
    child(box,'p',f.reason||'未获得可靠判断','auto-explainer');
    const foot=child(box,'div',null,'auto-factor-foot');
    child(foot,'span','数据日期 '+(f.date||'—')+' · '+(f.comparison||'较前期'));
    link(foot,f.url,'原始数据 ↗');
    if (f.freshness_days>7 && ['real_rate','nominal_rate','dollar','oil','vix','breakeven','fed_policy'].includes(f.category)) {
      child(box,'small','该日频数据已超过7天未更新，请检查数据源。','auto-stale');
    }
    return box;
  }
  function makeEvent(e) {
    const row=child(document.createElement('div'),'div',null,'auto-entry');
    const meta=child(row,'div',null,'auto-entry-top');
    meta.appendChild(tag(e.signal));
    child(meta,'span',stamp(e.published_at)+(e.kind==='metric'?' · 数据观测日 '+(e.observation_date||'—'):''));
    child(row,'b',e.title||'宏观数据事件','auto-entry-title');
    child(row,'p',e.reason||'需要进一步核实。');
    const foot=child(row,'div',null,'auto-entry-bottom');
    child(foot,'span',(e.source||'来源待核实')+(e.kind==='news'?' · 新闻标题初判':''));
    link(foot,e.url||e.link,'核查来源 ↗');
    return row;
  }
  function renderHistory() {
    const el=$('autoHistory');el.replaceChildren();
    const filtered=history.filter(e=>selection==='all'||e.signal===selection).slice(0,24);
    if (!filtered.length) {empty(el,'暂时没有符合筛选条件的记录。首次部署完成后会开始记录。');return;}
    filtered.forEach(e=>el.appendChild(makeEvent(e)));
  }
  function render() {
    if (!snapshot) return;
    const status=$('autoStatus');
    const updated=$('autoUpdated');
    const summary=$('autoSummary');
    if (snapshot.status==='not_initialized') {
      status.textContent='尚未启动';status.className='auto-state warn';
      updated.textContent='请按README部署并启动一次GitHub Actions';
      summary.textContent=snapshot.summary?.reason||'部署后自动抓取。';
    } else if (snapshot.status==='stale'||snapshot.status==='unavailable') {
      status.textContent='源暂不可用';status.className='auto-state neg';
      updated.textContent='最近尝试 '+stamp(snapshot.last_attempt_at||snapshot.generated_at);
      summary.textContent='数据源暂不可用；如有上次快照，可能已经过期，不能按实时信号交易。';
    } else {
      const age=Date.now()-new Date(snapshot.generated_at).getTime();
      status.textContent=(age>4*3600*1000?'更新延迟':snapshot.status==='partial'?'部分来源失败':'正常更新');
      status.className='auto-state '+(age>4*3600*1000||snapshot.status==='partial'?'warn':'pos');
      updated.textContent='上次生成 '+stamp(snapshot.generated_at)+' · 自动扫描并非实时行情';
      summary.replaceChildren();
      summary.appendChild(tag(snapshot.summary?.signal||'unknown'));
      child(summary,'span',' '+(snapshot.summary?.reason||'缺乏数据')); 
    }
    const factors=$('autoFactors');factors.replaceChildren();
    if (!snapshot.factors?.length) empty(factors,'无自动指标快照。请在 GitHub Actions 启动更新。');
    else snapshot.factors.forEach(f=>factors.appendChild(factorCard(f)));
    const feed=$('autoNews');feed.replaceChildren();
    if (!snapshot.news?.length) empty(feed,'近14天尚无可解析的新消息，或新闻订阅源暂不可用。');
    else snapshot.news.slice(0,10).forEach(n=>feed.appendChild(makeEvent(n)));
    const errors=snapshot.errors||[];
    const err=$('autoSources');
    const coverage=snapshot.coverage;
    err.textContent=coverage?`指标成功 ${coverage.received_series}/${coverage.expected_series} · 资讯源成功 ${coverage.working_feeds}/${coverage.expected_feeds}`:'尚未采集';
    if (errors.length) {
      const details=child(err,'details',null,'auto-error-list');
      child(details,'summary',errors.length+' 个源读取失败（展开）');
      child(details,'pre',errors.join('\n'));
    }
    renderHistory();
  }
  async function refresh() {
    const button=$('autoRefresh');button.disabled=true;button.textContent='正在读取…';
    try {
      const bust='?v='+Date.now();
      const [a,b]=await Promise.all([
        fetch('data/latest.json'+bust,{cache:'no-store'}),
        fetch('data/history.json'+bust,{cache:'no-store'})
      ]);
      if (!a.ok||!b.ok) throw new Error(`HTTP ${a.status}/${b.status}`);
      snapshot=await a.json();history=(await b.json()).events||[];
      render();
    } catch (e) {
      $('autoStatus').textContent='无法读取';$('autoStatus').className='auto-state neg';
      $('autoUpdated').textContent='请在GitHub Pages或本地HTTP服务器中打开；file://直接打开无法稳定读取JSON';
      $('autoSummary').textContent='原因：'+e.message;
      empty($('autoFactors'),'等待自动更新服务启动。');
      empty($('autoNews'),'需要部署后读取网站数据。');
      empty($('autoHistory'),'需要部署后读取历史记录。');
    } finally {
      button.disabled=false;button.textContent='重新读取网站数据';
    }
  }
  document.querySelectorAll('[data-auto-filter]').forEach(b=>b.addEventListener('click',()=>{
    selection=b.dataset.autoFilter;
    document.querySelectorAll('[data-auto-filter]').forEach(x=>x.classList.toggle('active',x===b));
    renderHistory();
  }));
  $('autoRefresh').addEventListener('click',refresh);
  refresh();setInterval(refresh,15*60*1000);
})();
