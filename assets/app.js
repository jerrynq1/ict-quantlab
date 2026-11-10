(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const API_KEY = 'ictql_api_base';
  const TOKEN_KEY = 'ictql_session_token';
  const state = {
    apiBase: localStorage.getItem(API_KEY) || '',
    token: sessionStorage.getItem(TOKEN_KEY) || '',
    runId: (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, ''),
    accounts: [], symbols: [], selectedAccountId: '', bars: [], barsSymbolId: '', currentSymbol: '', currentSymbolName: '',
    lastStats: null, statsModule: 'gaps', statsRecords: [], advanced: null, advancedRecords: [],
    forecastMode: 'live', dayStartHour: Number(localStorage.getItem('ictql_day_start')||17), currentView: 'overview', liveRefreshTimer: null, lastLiveBarTime: null, lastForecastAsOf: null
  };

  const MODULES = {
    gaps: ['Gap Statistics','NDOG/NWOG gap formation, progressive fill thresholds and fill timing.'],
    liquidity: ['Liquidity Statistics','Asia High/Low, PDH/PDL and PWH/PWL probe, sweep, breakout and reclaim.'],
    sessions: ['Session Statistics','Range, direction, continuation/reversal and high/low formation time by session.'],
    time: ['Time Statistics','High/low formation time, reversal candidates and intraday timing distribution.'],
    structure: ['Market Structure','Confirmed swing breaks, MSS/BOS, MFE/MAE and 1R/2R/3R outcomes.'],
    'daily-weekly': ['Daily & Weekly Statistics','Day-of-week direction, daily/weekly range and extreme formation time.'],
    'liquidity-mss': ['Liquidity → MSS Probability','Conditional probability of directional MSS after a liquidity sweep.']
  };

  function toast(message, type='info', timeout=4200) {
    const node = document.createElement('div'); node.className = `toast ${type}`; node.textContent = message;
    $('toastStack').appendChild(node); setTimeout(() => node.remove(), timeout);
  }
  function setText(id, value) { const el = $(id); if (el) el.textContent = value; }
  function baseUrl() { return (state.apiBase || '').trim().replace(/\/+$/, ''); }
  function saveApiBase(value) {
    state.apiBase = String(value || '').trim().replace(/\/+$/, '');
    localStorage.setItem(API_KEY, state.apiBase);
    $('apiBaseInput').value = state.apiBase;
    $('loginApiBase').value = state.apiBase;
  }
  function authHeaders(extra={}) {
    const headers = { ...extra, 'X-Client-Run': state.runId };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    return headers;
  }
  async function api(path, options={}) {
    if (!baseUrl()) throw new Error('Chưa cấu hình FastAPI URL. Vào Settings hoặc API Setup để nhập URL backend.');
    const headers = authHeaders(options.headers || {});
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const response = await fetch(`${baseUrl()}${path}`, { ...options, headers });
    const type = response.headers.get('content-type') || '';
    const payload = type.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) {
      if (response.status === 401 && state.token) {
        state.token = ''; sessionStorage.removeItem(TOKEN_KEY); showLogin('Session expired. Please sign in again.');
      }
      const message = payload && payload.detail ? payload.detail : (typeof payload === 'string' ? payload : `Request failed (${response.status})`);
      throw new Error(message);
    }
    return payload;
  }
  function showLogin(message='') {
    $('loginGate').classList.remove('hidden'); $('appShell').classList.add('hidden');
    $('loginApiBase').value = state.apiBase; $('loginError').textContent = message;
  }
  function hideLogin() { $('loginGate').classList.add('hidden'); $('appShell').classList.remove('hidden'); }
  function nyDateInput(date) {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23' }).formatToParts(date);
    const p = Object.fromEntries(parts.map(x => [x.type,x.value]));
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
  }
  function initDates() {
    const now = new Date(); const before = new Date(now.getTime() - 30*24*3600*1000);
    $('globalEnd').value = nyDateInput(now); $('globalStart').value = nyDateInput(before);
    $('dataEnd').value = nyDateInput(now); $('dataStart').value = nyDateInput(before);
    $('forecastAsOf').value = nyDateInput(new Date(now.getTime()-24*3600*1000));
    const half = new Date(now.getTime()-15*24*3600*1000);
    $('compareAStart').value = nyDateInput(before); $('compareAEnd').value = nyDateInput(half);
    $('compareBStart').value = nyDateInput(half); $('compareBEnd').value = nyDateInput(now);
  }
  function updateClock() {
    const now = new Date();
    setText('nyClock', new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(now));
    setText('nyDate', new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York',weekday:'short',month:'short',day:'2-digit',year:'numeric'}).format(now));
  }
  function setView(name) {
    state.currentView = name;
    document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
    document.querySelectorAll('.nav-link[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === name));
    const titles = {overview:'OVERVIEW',data:'DATA CENTER',statistics:'MARKET STATISTICS',advanced:'ADVANCED ICT LAB',forecast:'FORECAST LAB',research:'RESEARCH & EVALUATION',settings:'SYSTEM SETTINGS'};
    setText('pageCrumb', titles[name] || name.toUpperCase());
    if (name === 'research') loadResearch();
    if (name === 'settings') { $('apiBaseInput').value = state.apiBase; loadSessionProfile(); }
    if (typeof updateLivePollingState === 'function') updateLivePollingState();
  }
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
  document.querySelectorAll('[data-goto]').forEach(button => button.addEventListener('click', () => setView(button.dataset.goto)));
  $('quickSettings').addEventListener('click', () => setView('settings'));

  async function testApi() {
    try {
      const res = await fetch(`${baseUrl()}/api/v1/system/health`);
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') throw new Error('Health endpoint did not return OK');
      $('sidebarApiLed').classList.add('online'); setText('sidebarApiState','API online'); setText('sidebarApiText',data.version || 'FastAPI connected');
      setText('settingsApiStatus','ONLINE'); setText('apiTestResult',`Connected · ${data.service} · ${data.version}`);
      return true;
    } catch (e) {
      $('sidebarApiLed').classList.remove('online'); setText('sidebarApiState','API offline'); setText('sidebarApiText','Check backend URL');
      setText('settingsApiStatus','OFFLINE'); setText('apiTestResult',e.message);
      return false;
    }
  }
  $('saveLoginApi').addEventListener('click', async () => { saveApiBase($('loginApiBase').value); if (await testApi()) toast('Backend URL saved and reachable.','success'); else toast('API chưa phản hồi. Kiểm tra URL backend.','error'); });
  $('saveApiBtn').addEventListener('click', async () => { saveApiBase($('apiBaseInput').value); const ok=await testApi(); toast(ok?'API URL saved.':'Saved, but backend is unreachable.',ok?'success':'error'); });
  $('testApiBtn').addEventListener('click', testApi);
  $('settingsTestApiBtn').addEventListener('click', testApi);

  $('loginForm').addEventListener('submit', async (event) => {
    event.preventDefault(); $('loginError').textContent='';
    try {
      const response = await fetch(`${baseUrl()}/api/v1/auth/login`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('loginUsername').value,password:$('loginPassword').value})});
      const payload = await response.json(); if (!response.ok) throw new Error(payload.detail || 'Login failed');
      state.token=payload.access_token; sessionStorage.setItem(TOKEN_KEY,state.token); $('loginPassword').value=''; hideLogin(); await initializeWorkspace(); toast('Signed in to private workspace.','success');
    } catch (e) { $('loginError').textContent=e.message; }
  });
  $('logoutBtn').addEventListener('click', async () => {
    try { await api('/api/v1/auth/logout',{method:'POST'}); } catch (_) {}
    state.token='';sessionStorage.removeItem(TOKEN_KEY);if(state.liveRefreshTimer){clearInterval(state.liveRefreshTimer);state.liveRefreshTimer=null;}showLogin('Signed out.');
  });

  async function initializeWorkspace() {
    hideLogin(); await testApi();
    try { await api('/api/v1/auth/me'); } catch (e) { showLogin(e.message); return; }
    setText('userLabel','Private workspace');
    await loadCTraderConfig();
    const params = new URLSearchParams(location.search);
    if (params.get('ctrader')==='connected') {
      toast('cTrader OAuth complete. Refresh the account list to continue.','success',7000);
      history.replaceState({},'',location.pathname);
      await refreshAccounts();
    }
    if (params.get('ctrader_error')) { toast(`cTrader OAuth: ${params.get('ctrader_error')}`,'error',8000); history.replaceState({},'',location.pathname); }
    await loadEvaluation();
  }

  async function loadCTraderConfig() {
    try {
      const cfg=await api('/api/v1/ctrader/config');
      $('ctraderClientId').value=cfg.client_id||''; $('ctraderRedirectUri').value=cfg.redirect_uri||`${baseUrl()}/api/v1/ctrader/oauth/callback`;
      $('ctraderEnvironment').value=cfg.environment||'demo'; $('ctraderScope').value='accounts';
      $('secretSavedBadge').classList.toggle('hidden',!cfg.secret_saved);
      $('authorizeCTraderBtn').disabled=!cfg.configured;
      $('ctraderStatePill').textContent=cfg.authorized?'OAUTH AUTHORIZED':cfg.configured?'CREDENTIALS SAVED':'NOT CONFIGURED';
      $('oauthStep').classList.toggle('done',!!cfg.authorized); $('accountStep').classList.toggle('done',!!cfg.selected_account_id);
    } catch (e) { setText('configSaveState',e.message); }
  }
  $('ctraderConfigForm').addEventListener('submit', async (event) => {
    event.preventDefault(); const secret=$('ctraderClientSecret').value;
    try {
      const cfg=await api('/api/v1/ctrader/config',{method:'PUT',body:JSON.stringify({client_id:$('ctraderClientId').value,client_secret:secret||null,redirect_uri:$('ctraderRedirectUri').value||`${baseUrl()}/api/v1/ctrader/oauth/callback`,environment:$('ctraderEnvironment').value,scope:'accounts'})});
      $('ctraderClientSecret').value=''; $('secretSavedBadge').classList.remove('hidden'); $('authorizeCTraderBtn').disabled=false;
      setText('ctraderStatePill','CREDENTIALS SAVED'); setText('configSaveState','Saved securely on backend.'); toast('cTrader credentials saved (secret encrypted server-side).','success');
    } catch (e) { setText('configSaveState',e.message);toast(e.message,'error'); }
  });
  $('authorizeCTraderBtn').addEventListener('click', async () => {
    try { const r=await api('/api/v1/ctrader/oauth/start',{method:'POST'}); location.href=r.authorization_url; }
    catch(e){toast(e.message,'error');}
  });
  $('refreshAccountsBtn').addEventListener('click',refreshAccounts);
  async function refreshAccounts() {
    try {
      const data=await api('/api/v1/ctrader/accounts'); state.accounts=data.accounts||[];
      $('accountSelect').innerHTML='<option value="">Choose account…</option>'+state.accounts.map(a=>`<option value="${escapeAttr(a.account_id)}">${a.broker||'Broker'} · ${a.trader_login||a.account_id} · ${a.is_live?'LIVE':'DEMO'}</option>`).join('');
      const cfg=await api('/api/v1/ctrader/config');
      $('accountSelect').disabled=!state.accounts.length; $('selectAccountBtn').disabled=!state.accounts.length;
      state.selectedAccountId=cfg.selected_account_id||'';
      if(cfg.selected_account_id) $('accountSelect').value=cfg.selected_account_id;
      if(cfg.selected_account_id){const a=state.accounts.find(x=>x.account_id===cfg.selected_account_id);if(a){setText('selectedAccountName',`${a.broker||'cTrader'} · ${a.trader_login||a.account_id}`);setText('selectedAccountMeta',`${a.account_id} · ${a.is_live?'Live account':'Demo account'}`);}}
      $('accountStep').classList.toggle('done',!!cfg.authorized); setText('ctraderStatePill','ACCOUNTS AVAILABLE');
      toast(`${state.accounts.length} cTrader account(s) found.`,'success');
    } catch(e){toast(e.message,'error');}
  }
  $('selectAccountBtn').addEventListener('click',async()=>{
    const id=$('accountSelect').value;if(!id)return;
    try{
      await api('/api/v1/ctrader/accounts/select',{method:'POST',body:JSON.stringify({account_id:id})});
      if(state.selectedAccountId&&state.selectedAccountId!==id){
        state.bars=[];state.barsSymbolId='';state.currentSymbol='';state.currentSymbolName='';state.symbols=[];
        ['globalSymbol','dataSymbol','smtPrimary','smtSecondary'].forEach(key=>$(key).innerHTML='<option value="">Select symbol</option>');
        $('symbolList').innerHTML='<div class="empty-state small-empty">Load symbols for the selected account.</div>';
        $('symbolSearch').value='';$('symbolSearch').disabled=true;drawChart([]);$('chartEmpty').classList.remove('hidden');
        setText('dataBarCount','0');setText('dataStatusPill','NO MARKET DATA');
      }
      state.selectedAccountId=id;
      const a=state.accounts.find(x=>x.account_id===id);setText('selectedAccountName',`${a.broker||'cTrader'} · ${a.trader_login||a.account_id}`);setText('selectedAccountMeta',`${a.account_id} · ${a.is_live?'Live account':'Demo account'}`);$('refreshSymbolsBtn').disabled=false;$('symbolStep').classList.remove('done');toast('Trading account selected and authorized.','success');
    }catch(e){toast(e.message,'error');}
  });
  $('refreshSymbolsBtn').addEventListener('click',refreshSymbols);
  async function refreshSymbols(){
    try{const data=await api('/api/v1/ctrader/symbols');state.symbols=data.symbols||[];populateSymbolSelectors();$('symbolSearch').disabled=false;$('symbolStep').classList.add('done');renderSymbolList();toast(`${state.symbols.length} symbols loaded from broker account.`,'success');}
    catch(e){toast(e.message,'error');}
  }
  function populateSymbolSelectors(){
    const options=state.symbols.map(s=>`<option value="${escapeAttr(s.symbol_id)}">${escapeHTML(s.name)}</option>`).join('');
    ['globalSymbol','dataSymbol','smtPrimary','smtSecondary'].forEach(id=>{const el=$(id);const old=el.value;const first=id==='smtPrimary'?'Select primary':id==='smtSecondary'?'Select comparison':'Select symbol';el.innerHTML=`<option value="">${first}</option>${options}`;if(old&&state.symbols.some(s=>s.symbol_id===old))el.value=old;});
    if(!state.currentSymbol&&state.symbols.length){state.currentSymbol=state.symbols[0].symbol_id;state.currentSymbolName=state.symbols[0].name;$('globalSymbol').value=state.currentSymbol;$('dataSymbol').value=state.currentSymbol;}
  }
  function renderSymbolList(){
    const q=$('symbolSearch').value.toLowerCase();const rows=state.symbols.filter(s=>s.name.toLowerCase().includes(q));
    $('symbolList').innerHTML=rows.slice(0,250).map(s=>`<div class="symbol-row"><span><strong>${escapeHTML(s.name)}</strong><small> #${escapeHTML(s.symbol_id)}</small></span><button data-use-symbol="${escapeAttr(s.symbol_id)}">Use symbol</button></div>`).join('')||'<div class="empty-state small-empty">No matching symbols.</div>';
    $('symbolList').querySelectorAll('[data-use-symbol]').forEach(b=>b.addEventListener('click',()=>selectSymbol(b.dataset.useSymbol)));
  }
  $('symbolSearch').addEventListener('input',renderSymbolList);
  function selectSymbol(id){const s=state.symbols.find(x=>x.symbol_id===id);if(!s)return;if(state.currentSymbol&&state.currentSymbol!==id){state.bars=[];state.barsSymbolId='';drawChart([]);$('chartEmpty').classList.remove('hidden');setText('dataBarCount','0');setText('dataStatusPill','NO MARKET DATA');}state.currentSymbol=id;state.currentSymbolName=s.name;$('globalSymbol').value=id;$('dataSymbol').value=id;$('chartSymbol').textContent=s.name;toast(`${s.name} selected. Load its history to analyse it.`,'success');}
  $('globalSymbol').addEventListener('change',e=>selectSymbol(e.target.value));
  $('dataSymbol').addEventListener('change',e=>selectSymbol(e.target.value));

  function mirrorRange(from,to){$(to).value=$(from).value;}
  $('globalStart').addEventListener('change',()=>mirrorRange('globalStart','dataStart'));
  $('globalEnd').addEventListener('change',()=>mirrorRange('globalEnd','dataEnd'));
  $('dataStart').addEventListener('change',()=>mirrorRange('dataStart','globalStart'));
  $('dataEnd').addEventListener('change',()=>mirrorRange('dataEnd','globalEnd'));
  $('loadHistoryBtn').addEventListener('click',loadHistory);
  $('downloadM1Btn').addEventListener('click',loadHistory);
  async function loadHistory(){
    const symbolId=$('dataSymbol').value||$('globalSymbol').value;
    if(!symbolId){toast('Select an available cTrader symbol first.','error');return;}
    const start=$('dataStart').value;const end=$('dataEnd').value;
    if(!start||!end||new Date(end)<=new Date(start)){toast('Check the start and end dates.','error');return;}
    const button=$('downloadM1Btn');button.disabled=true;$('downloadProgress').classList.remove('hidden');setText('downloadProgressText','Requesting missing M1 windows…');setText('downloadProgressPercent','…');$('downloadProgressBar').style.width='18%';
    try{
      const response=await api('/api/v1/data/bars',{method:'POST',body:JSON.stringify({symbol_id:symbolId,start,end,timeframe:'M1'})});
      const priorBars=state.barsSymbolId===symbolId?state.bars:[];
      const byTime=new Map(priorBars.map(b=>[b.time,b]));
      response.bars.forEach(b=>byTime.set(b.time,b));state.bars=[...byTime.values()].sort((a,b)=>a.time-b.time);state.barsSymbolId=symbolId;state.currentSymbol=symbolId;
      const symbol=state.symbols.find(s=>s.symbol_id===symbolId);state.currentSymbolName=symbol?.name||symbolId;
      setText('downloadProgressText','M1 history loaded');setText('downloadProgressPercent','100%');$('downloadProgressBar').style.width='100%';
      setText('dataBarCount',number(response.count));setText('dataNewBars',number(response.new_bars_fetched));setText('dataSuspect',number(response.quality.suspect_high));setText('dataWindows',number(response.cache.loaded_windows));
      setText('ovBars',number(response.count));setText('ovQuality',response.quality.suspect_high?'REVIEW':'CLEAN');setText('ovQualityFoot',`${response.quality.suspect_high} suspect high(s)`);
      setText('dataStatusPill',`${response.count.toLocaleString()} M1 BARS`);setText('chartSymbol',state.currentSymbolName);setText('chartRangeLabel',`${start.replace('T',' ')} → ${end.replace('T',' ')} NY`);
      setText('engineData','ACTIVE');$('engineData').classList.add('running');drawChart(state.bars);$('chartEmpty').classList.add('hidden');
      toast(`${response.count.toLocaleString()} M1 bars available; fetched ${response.new_bars_fetched.toLocaleString()} new bars.`, 'success',6500);
      await loadEvaluation();
    }catch(e){toast(e.message,'error',7000);setText('downloadProgressText','Download failed; failed range was not marked cached.');setText('downloadProgressPercent','ERROR');}
    finally{button.disabled=false;setTimeout(()=>$('downloadProgress').classList.add('hidden'),2200);}
  }

  function drawChart(bars){
    const canvas=$('priceChart');const ctx=canvas.getContext('2d');const dpr=window.devicePixelRatio||1;const w=canvas.clientWidth||700;const h=280;canvas.width=w*dpr;canvas.height=h*dpr;ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
    if(!bars.length){$('chartEmpty').classList.remove('hidden');return;}
    const sample=bars.slice(-Math.min(180,bars.length));const min=Math.min(...sample.map(x=>x.low));const max=Math.max(...sample.map(x=>x.high));const pad=(max-min)*.08||1;const lo=min-pad,hi=max+pad;const left=12,right=56,top=12,bottom=24;const cw=w-left-right,ch=h-top-bottom;const y=v=>top+(hi-v)/(hi-lo)*ch;
    ctx.strokeStyle='#1c2b3e';ctx.lineWidth=1;ctx.fillStyle='#60758d';ctx.font='9px DM Mono';ctx.textAlign='left';
    for(let i=0;i<=4;i++){const yy=top+ch*i/4;ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(w-right,yy);ctx.stroke();const val=hi-(hi-lo)*i/4;ctx.fillText(val.toFixed(3),w-right+7,yy+3);}
    const step=cw/sample.length;const body=Math.max(1,Math.min(7,step*.62));
    sample.forEach((b,i)=>{const x=left+(i+.5)*step;const up=b.close>=b.open;ctx.strokeStyle=up?'#5ee0bd':'#f07e8b';ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.moveTo(x,y(b.high));ctx.lineTo(x,y(b.low));ctx.stroke();const yo=y(Math.max(b.open,b.close));const hh=Math.max(1,Math.abs(y(b.open)-y(b.close)));ctx.fillRect(x-body/2,yo,body,hh);if(b.quality==='suspect_ohlc'){ctx.fillStyle='#e8bd73';ctx.fillRect(x-1,y(b.high)-3,3,3);}});
    ctx.fillStyle='#71869d';ctx.font='9px DM Mono';ctx.textAlign='left';ctx.fillText(new Date(sample[0].time).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'2-digit'}),left,h-6);ctx.textAlign='right';ctx.fillText(new Date(sample[sample.length-1].time).toLocaleString('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit'}),w-right,h-6);
  }
  window.addEventListener('resize',()=>{if(state.bars.length)drawChart(state.bars);});

  function currentFilters(){return {start:$('globalStart').value,end:$('globalEnd').value,session:$('filterSession').value,direction:$('filterDirection').value,daily_bias:$('filterDailyBias').value,volatility_regime:$('filterVolatility').value,day_of_week:$('filterDay').value.toLowerCase(),month:$('filterMonth').value,year:$('filterYear').value};}
  document.querySelectorAll('.module-choice').forEach(b=>b.addEventListener('click',()=>selectStatsModule(b.dataset.module)));
  function selectStatsModule(name){state.statsModule=name;document.querySelectorAll('.module-choice').forEach(b=>b.classList.toggle('active',b.dataset.module===name));setText('statsTitle',MODULES[name][0]);setText('statsDescription',MODULES[name][1]);}
  $('runStatsBtn').addEventListener('click',runStatistics);
  async function runStatistics(){
    const symbolId=$('globalSymbol').value||state.currentSymbol;if(!symbolId){toast('Select symbol and load M1 history first.','error');return;}
    try{
      setText('engineStats','RUNNING');$('engineStats').classList.add('running');
      const result=await api(`/api/v1/analytics/${state.statsModule}`,{method:'POST',body:JSON.stringify({symbol_id:symbolId,timeframe:$('globalTimeframe').value,filters:currentFilters(),day_start_hour:state.dayStartHour})});
      state.lastStats=result;state.statsRecords=getRecords(result);renderStats(result);setText('engineStats','COMPLETE');setText('engineIct','COMPLETE');$('engineIct').classList.add('running');
      const count=state.statsRecords.length;setText('ovEvents',number(count));setText('statsSample',`${count.toLocaleString()} RECORDS`);toast(`${MODULES[state.statsModule][0]} completed.`, 'success');
    }catch(e){setText('engineStats','ERROR');toast(e.message,'error',7000);}
  }
  function getRecords(result){
    if(Array.isArray(result.records)&&Array.isArray(result.evaluations)&&result.evaluations.length){
      const byTime=new Map(result.evaluations.map(x=>[String(x.timestamp),x]));
      return result.records.map(x=>({...x,performance:byTime.get(String(x.timestamp))||null}));
    }
    if(Array.isArray(result.daily_records)||Array.isArray(result.weekly_records)){
      return [...(result.daily_records||[]).map(x=>({...x,record_group:'daily'})),
              ...(result.weekly_records||[]).map(x=>({...x,record_group:'weekly'}))];
    }
    for(const key of ['records','daily_summary','evaluations','fvg_records','liquidity_pools','order_blocks','cbdr_records','silver_bullet_records','po3_records','ipda_records','judas_records','cisd_records','three_drive_records','confluence_records','quarterly_records'])if(Array.isArray(result[key]))return result[key];return [];
  }
  function formatMetric(value,key=''){if(value===null||value===undefined)return '—';if(typeof value==='number'){if(!Number.isFinite(value))return '—';const ratio=/(rate|probability|accuracy|ratio|_pct)$/i.test(key);return ratio?`${(value*100).toFixed(1)}%`:value.toLocaleString(undefined,{maximumFractionDigits:5});}if(Array.isArray(value))return value.length?`${value.length} items`:'—';if(typeof value==='object')return 'View details';return String(value);}
  function renderMetrics(container,metrics){
    const entries=Object.entries(metrics||{}).filter(([k,v])=>!Array.isArray(v)&&!(v&&typeof v==='object'));
    if(!entries.length){container.innerHTML='<div class="metric-placeholder">No metrics available for this sample.</div>';return;}
    container.innerHTML=entries.slice(0,12).map(([k,v])=>`<div class="metric-tile"><small>${escapeHTML(k.replaceAll('_',' ').toUpperCase())}</small><strong>${escapeHTML(formatMetric(v,k))}</strong><em>${typeof v==='number'&&/(rate|probability|accuracy|ratio|_pct)$/i.test(k)?'Observed rate / ratio':''}</em></div>`).join('');
  }
  function renderStats(result){
    renderMetrics($('statsMetrics'),result.metrics||{});
    const records=getRecords(result);state.statsRecords=records;
    const search=($('recordSearch').value||'').toLowerCase();const filtered=records.filter(x=>JSON.stringify(x).toLowerCase().includes(search));
    $('statsTableBody').innerHTML=filtered.slice(0,500).map((x)=>`<tr data-stats-record="${records.indexOf(x)}" tabindex="0" title="Click to inspect full event"><td>${escapeHTML(x.time_ny||x.time||x.date||x.period||'—')}</td><td>${escapeHTML(x.type||x.session||x.level_type||x.direction||'Record')}</td><td>${escapeHTML(x.event||x.side||x.weekday||x.state||x.liquidity||'—')}</td><td>${escapeHTML(x.price??x.level??x.range??x.size??x.mfe??'—')}</td></tr>`).join('')||'<tr><td colspan="4" class="empty-cell">No records match the current filters.</td></tr>';
    setText('statsTableFoot',`${filtered.length} visible / ${records.length} returned records. ${result.filter_summary?.note||'Click module records to inspect the historical event population.'}`);
    drawStatsVisualization(result);
  }

  function drawStatsVisualization(result){
    const canvas=$('statsChart'); if(!canvas)return;
    const ctx=canvas.getContext('2d'); const dpr=window.devicePixelRatio||1;
    const w=Math.max(320,canvas.clientWidth||700), h=190;
    canvas.width=Math.floor(w*dpr);canvas.height=Math.floor(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
    const metrics=result.metrics||{};let labels=[],series=[],caption='';
    if(state.statsModule==='time'&&Array.isArray(metrics.hourly_heatmap)){
      labels=metrics.hourly_heatmap.map(x=>String(x.hour).padStart(2,'0'));
      series=[{name:'High formation',values:metrics.hourly_heatmap.map(x=>x.high_formation_days||0)},{name:'Low formation',values:metrics.hourly_heatmap.map(x=>x.low_formation_days||0)},{name:'Reversal',values:metrics.hourly_heatmap.map(x=>x.reversal_candidates||0)}];
      caption='Hourly event distribution · New York local time';
    } else {
      const records=getRecords(result);let field='type';
      if(state.statsModule==='liquidity')field='event';else if(state.statsModule==='sessions')field='session';else if(state.statsModule==='liquidity-mss')field='liquidity';else if(state.statsModule==='structure'||state.statsModule==='time')field='direction';else if(state.statsModule==='daily-weekly')field='weekday';
      const counts=new Map();records.forEach(r=>{const k=String(r[field]??'Unclassified');counts.set(k,(counts.get(k)||0)+1);});
      labels=[...counts.keys()].slice(0,14);series=[{name:'Records',values:labels.map(k=>counts.get(k))}];
      if(state.statsModule==='gaps'&&records.length){const filled=records.filter(x=>x.fill_100!==null&&x.fill_100!==undefined).length;labels=['25% filled','50% filled','75% filled','100% filled'];series=[{name:'Gap events',values:[25,50,75,100].map(p=>records.filter(x=>x[`fill_${p}`]!==null&&x[`fill_${p}`]!==undefined).length)}];caption=`Cumulative fill thresholds · ${filled} full fills in returned records`;}
      else caption=`Distribution by ${field.replaceAll('_',' ')} · ${records.length} records`;
    }
    if(!labels.length||!series.length||!series.some(s=>s.values.some(v=>v>0))){ctx.fillStyle='#71869d';ctx.font='11px DM Mono';ctx.textAlign='center';ctx.fillText('No distribution available for the current sample',w/2,h/2);setText('statsVizState','NO DISTRIBUTION');setText('statsVizCaption',caption||'No historical records returned.');return;}
    const max=Math.max(1,...series.flatMap(s=>s.values));const left=30,right=12,top=12,bottom=35,cw=w-left-right,ch=h-top-bottom;
    ctx.font='9px DM Mono';ctx.strokeStyle='#1c2b3e';ctx.fillStyle='#71869d';ctx.textAlign='right';
    for(let i=0;i<=3;i++){const y=top+ch*i/3;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.fillText(String(Math.round(max*(1-i/3))),left-7,y+3);}
    const group=cw/labels.length,barGroup=Math.min(group*.72,38),barW=Math.max(2,barGroup/series.length-2);
    const palette=['#48c7d8','#61d5ad','#d7b46a'];
    labels.forEach((label,i)=>{series.forEach((s,j)=>{const val=s.values[i]||0;const bh=val/max*ch;const x=left+i*group+(group-barGroup)/2+j*(barW+2);ctx.fillStyle=palette[j%palette.length];ctx.fillRect(x,top+ch-bh,barW,bh);});ctx.fillStyle='#8ca0b7';ctx.textAlign='center';const shown=label.length>9?label.slice(0,8)+'…':label;ctx.fillText(shown,left+(i+.5)*group,h-12);});
    setText('statsVizState','DISTRIBUTION READY');setText('statsVizCaption',`${caption}. ${series.map(x=>x.name).join(' · ')}`);
  }
  window.addEventListener('resize',()=>{if(state.lastStats)drawStatsVisualization(state.lastStats);});

  function comparisonDisplay(summary,module){
    const keys={gaps:['record_count','gap_samples','observed_gap_samples'],liquidity:['record_count','sweep_count','sweep_rate','reclaim_rate'],sessions:['record_count','complete_sessions','incomplete_sessions_excluded','continuation_count','reversal_count','median_complete_session_range'],time:['record_count'],structure:['record_count','bos_count','mss_count','evaluation_samples','ambiguous_excluded','mean_mfe','mean_mae'], 'daily-weekly':['daily_samples','weekly_samples','complete_daily_periods','complete_weekly_periods','incomplete_periods','bullish_daily_rate','bullish_weekly_rate','median_complete_daily_range','median_complete_weekly_range'], 'liquidity-mss':['record_count']}[module]||['record_count'];
    const lines=keys.map(k=>[k,summary[k]]).filter(([,v])=>v!==undefined&&v!==null).map(([k,v])=>`<div class="compare-line"><span>${escapeHTML(k.replaceAll('_',' ').toUpperCase())}</span><strong>${escapeHTML(formatCompareValue(k,v))}</strong></div>`);
    if(summary.fill_rates)for(const [k,v] of Object.entries(summary.fill_rates))lines.push(`<div class="compare-line"><span>GAP ${escapeHTML(k)} FILL RATE</span><strong>${escapeHTML(formatCompareValue('rate',v))}</strong></div>`);
    if(summary.target_rates)for(const [k,v] of Object.entries(summary.target_rates))lines.push(`<div class="compare-line"><span>${escapeHTML(k)} TARGET RATE</span><strong>${escapeHTML(formatCompareValue('rate',v))}</strong></div>`);
    if(summary.probability_by_horizon)for(const [k,v] of Object.entries(summary.probability_by_horizon))lines.push(`<div class="compare-line"><span>MSS WITHIN ${escapeHTML(k)}</span><strong>${escapeHTML(formatCompareValue('rate',v.probability))} · n=${escapeHTML(v.sample)}</strong></div>`);
    for(const [k,v] of Object.entries(summary.by_event||{}))lines.push(`<div class="compare-line"><span>${escapeHTML(k)}</span><strong>${escapeHTML(v)}</strong></div>`);
    return lines.join('')||'<div class="empty-state small-empty">No records in this period.</div>';
  }
  function formatCompareValue(key,value){if(value===null||value===undefined)return '—';if(typeof value==='number'){if(/rate|probability|accuracy|ratio/i.test(key))return `${(value*100).toFixed(1)}%`;return value.toLocaleString(undefined,{maximumFractionDigits:5});}return String(value);}
  $('comparePeriodsBtn').addEventListener('click',async()=>{
    const symbolId=$('globalSymbol').value||state.currentSymbol;if(!symbolId){toast('Select a symbol and load M1 history first.','error');return;}
    const payload={symbol_id:symbolId,timeframe:$('globalTimeframe').value,period_a_start:$('compareAStart').value,period_a_end:$('compareAEnd').value,period_b_start:$('compareBStart').value,period_b_end:$('compareBEnd').value,filters:currentFilters(),day_start_hour:state.dayStartHour};
    if(!payload.period_a_start||!payload.period_a_end||!payload.period_b_start||!payload.period_b_end){toast('Complete both comparison windows.','error');return;}
    const button=$('comparePeriodsBtn');button.disabled=true;setText('compareOutput','Calculating comparison…');
    try{const r=await api(`/api/v1/analytics/${state.statsModule}/compare`,{method:'POST',body:JSON.stringify(payload)});const a=r.period_a||{},b=r.period_b||{};const delta=r.deltas_b_minus_a||{};const change=Object.entries(delta).filter(([k,v])=>typeof v.absolute==='number').slice(0,5).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v.absolute>0?'+':''}${v.absolute.toFixed(4)}`).join(' · ');$('compareOutput').innerHTML=`<div class="compare-grid"><article class="compare-card"><h4>PERIOD A · ${escapeHTML(a.start||'')} → ${escapeHTML(a.end||'')}</h4>${comparisonDisplay(a,state.statsModule)}</article><article class="compare-card"><h4>PERIOD B · ${escapeHTML(b.start||'')} → ${escapeHTML(b.end||'')}</h4>${comparisonDisplay(b,state.statsModule)}</article></div><div class="compare-delta">B − A · ${escapeHTML(change||'No comparable numeric deltas')}<br>${escapeHTML(r.note||'')}</div>`;toast('Period comparison completed.','success');}
    catch(e){$('compareOutput').innerHTML=`<div class="empty-state small-empty">${escapeHTML(e.message)}</div>`;toast(e.message,'error');}
    finally{button.disabled=false;}
  });
  function openRecordDetail(record){if(!record)return;$('recordModalTitle').textContent=record.type||record.session||record.level_type||record.phase||'Research record';$('recordModalBody').textContent=JSON.stringify(record,null,2);$('recordModal').classList.remove('hidden');$('recordModalClose').focus();}
  function closeRecordDetail(){$('recordModal').classList.add('hidden');}
  $('recordModalClose').addEventListener('click',closeRecordDetail);
  $('recordModal').addEventListener('click',e=>{if(e.target===$('recordModal'))closeRecordDetail();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('recordModal').classList.contains('hidden'))closeRecordDetail();});
  $('statsTableBody').addEventListener('click',e=>{const row=e.target.closest('[data-stats-record]');if(row)openRecordDetail(state.statsRecords[Number(row.dataset.statsRecord)]);});
  $('statsTableBody').addEventListener('keydown',e=>{if(e.key==='Enter'){const row=e.target.closest('[data-stats-record]');if(row)openRecordDetail(state.statsRecords[Number(row.dataset.statsRecord)]);}});
  $('advancedTableBody').addEventListener('click',e=>{const row=e.target.closest('[data-advanced-record]');if(row)openRecordDetail(state.advancedRecords[Number(row.dataset.advancedRecord)]);});
  $('advancedTableBody').addEventListener('keydown',e=>{if(e.key==='Enter'){const row=e.target.closest('[data-advanced-record]');if(row)openRecordDetail(state.advancedRecords[Number(row.dataset.advancedRecord)]);}});
  $('recordSearch').addEventListener('input',()=>{if(state.lastStats)renderStats(state.lastStats);});
  $('exportRecordsBtn').addEventListener('click',()=>{
    const rows=state.statsRecords;if(!rows.length){toast('No records to export.','error');return;}
    const keys=[...new Set(rows.flatMap(x=>Object.keys(x)))];const csv=[keys.join(','),...rows.map(r=>keys.map(k=>`"${String(typeof r[k]==='object'?JSON.stringify(r[k]):r[k]??'').replaceAll('"','""')}"`).join(','))].join('\n');
    downloadBlob(csv,`${state.statsModule}-records.csv`,'text/csv');
  });

  $('runAdvancedBtn').addEventListener('click',runAdvanced);
  async function runAdvanced(){const symbolId=$('globalSymbol').value||state.currentSymbol;if(!symbolId){toast('Select a symbol and load history first.','error');return;}
    try{const result=await api('/api/v1/analytics/advanced-ict',{method:'POST',body:JSON.stringify({symbol_id:symbolId,timeframe:$('globalTimeframe').value,filters:currentFilters(),day_start_hour:state.dayStartHour})});state.advanced=result;renderMetrics($('advancedMetrics'),result.metrics);const all=[...(result.fvg_records||[]),...(result.liquidity_pools||[]),...(result.order_blocks||[]),...(result.cbdr_records||[]),...(result.silver_bullet_records||[]),...(result.po3_records||[]),...(result.judas_records||[]),...(result.cisd_records||[]),...(result.three_drive_records||[]),...(result.ipda_records||[]),...(result.confluence_records||[]),...(result.quarterly_records||[])].sort((a,b)=>(b.timestamp||0)-(a.timestamp||0));state.advancedRecords=all;$('advancedTableBody').innerHTML=all.slice(0,500).map((x,i)=>`<tr data-advanced-record="${i}" tabindex="0" title="Click to inspect full event"><td>${escapeHTML(x.time||'—')}</td><td>${escapeHTML(x.type||x.phase||'ICT Event')}</td><td>${escapeHTML(x.direction||x.side||'—')}</td><td>${escapeHTML(x.price??`${x.bottom??x.low??''} – ${x.top??x.high??''}`)}</td><td>${escapeHTML(x.state||x.status||x.distribution||x.shift_candidate||x.classification||'—')}</td></tr>`).join('')||'<tr><td colspan="5" class="empty-cell">No advanced events identified in this sample.</td></tr>';setText('advancedCount',`${all.length} EVENTS`);setText('ovEvents',number((state.lastStats?state.statsRecords.length:0)+all.length));toast(`Advanced scan found ${all.length} event records.`,'success');}
    catch(e){toast(e.message,'error',7000);}
  }
  $('runSmtBtn').addEventListener('click',async()=>{const p=$('smtPrimary').value,s=$('smtSecondary').value;if(!p||!s||p===s){toast('Choose two different symbols.','error');return;}try{const r=await api('/api/v1/analytics/smt',{method:'POST',body:JSON.stringify({primary_symbol_id:p,secondary_symbol_id:s,timeframe:$('globalTimeframe').value})});$('smtResult').innerHTML=`<b>${r.metrics.divergences??0} SMT candidate(s)</b><br><span class="muted">${r.metrics.samples} aligned timestamps · ${escapeHTML(r.metrics.status||'Aligned swing comparison')}</span>`+(r.records||[]).slice(-12).map(x=>`<div class="symbol-row"><strong>${escapeHTML(x.type)}</strong><small>${escapeHTML(x.time)}</small></div>`).join('');}catch(e){toast(e.message,'error');}});

  document.querySelectorAll('[data-forecast-mode]').forEach(b=>b.addEventListener('click',()=>setForecastMode(b.dataset.forecastMode)));
  function setForecastMode(mode){state.forecastMode=mode;document.querySelectorAll('[data-forecast-mode]').forEach(b=>b.classList.toggle('active',b.dataset.forecastMode===mode));$('forecastAsOfWrap').classList.toggle('hidden',mode!=='historical');setText('forecastModeTitle',mode==='live'?'Live context forecast':'Historical scenario replay');setText('forecastModeDescription',mode==='live'?'Uses the latest fully closed candle; optional 60-second M1 polling refreshes the context.':'Pick a past timestamp. The model trains only on observations available before that timestamp; later candles are used only for evaluation.');updateLivePollingState();}
  function syncForecastHorizonOptions(){
    const timeframeMinutes={M1:1,M5:5,M15:15,M30:30,H1:60,H4:240,D1:1440}[$('globalTimeframe').value]||1;
    const select=$('forecastHorizon');
    [...select.options].forEach(option=>{option.disabled=Number(option.value)%timeframeMinutes!==0;});
    if(select.selectedOptions[0]?.disabled){
      const first=[...select.options].find(option=>!option.disabled);
      if(first)select.value=first.value;
    }
    setText('forecastHorizonHelp',`Selected ${$('globalTimeframe').value}: forecast horizons must be multiples of ${timeframeMinutes} minute(s).`);
  }
  $('globalTimeframe').addEventListener('change',syncForecastHorizonOptions);
  syncForecastHorizonOptions();
  $('runForecastBtn').addEventListener('click',()=>runForecast());
  async function runForecast(options={}){const symbolId=$('globalSymbol').value||state.currentSymbol;if(!symbolId){if(!options.silent)toast('Load M1 history first.','error');return;}const body={symbol_id:symbolId,horizon_minutes:Number($('forecastHorizon').value),timeframe:$('globalTimeframe').value};if(state.forecastMode==='historical'){if(!$('forecastAsOf').value){if(!options.silent)toast('Choose a historical as-of timestamp.','error');return;}body.as_of=$('forecastAsOf').value;}
    try{if(!options.silent){setText('engineForecast','RUNNING');$('engineForecast').classList.add('running');}const r=await api('/api/v1/forecast',{method:'POST',body:JSON.stringify(body)});if(options.silent&&r.as_of&&r.as_of===state.lastForecastAsOf){setText('forecastLiveStatus','UP TO DATE');return;}renderForecast(r);if(r.as_of)state.lastForecastAsOf=r.as_of;setText('engineForecast',r.status==='ok'?'COMPLETE':String(r.status||'error').toUpperCase());setText('ovForecast',r.status==='ok'?'BASELINE READY':'INSUFFICIENT');if(r.status==='ok'){if(!options.silent)toast(`Forecast generated from ${r.sample_size} historical analogs.`,'success');await loadEvaluation();}else if(!options.silent)toast(r.message||'Forecast withheld due to sample limits.','error');}
    catch(e){if(!options.silent){setText('engineForecast','ERROR');toast(e.message,'error',7000);}else setText('forecastLiveStatus','POLL ERROR');}}

  function updateLivePollingState(){
    const enabled=$('forecastAutoRefresh').checked;
    const eligible=!!state.token&&state.forecastMode==='live'&&state.currentView==='forecast';
    setText('forecastLiveStatus',!enabled?'POLLING OFF':eligible?'AUTO · 60S':'PAUSED');
    if(!enabled||!eligible){if(state.liveRefreshTimer){clearInterval(state.liveRefreshTimer);state.liveRefreshTimer=null;}return;}
    if(!state.liveRefreshTimer){setText('forecastLiveStatus','AUTO · 60S');state.liveRefreshTimer=setInterval(()=>refreshLiveM1(),60_000);}
  }
  async function refreshLiveM1(){
    if(!state.token||state.forecastMode!=='live'||state.currentView!=='forecast')return;
    const symbolId=$('globalSymbol').value||state.currentSymbol;
    if(!symbolId||state.barsSymbolId!==symbolId){setText('forecastLiveStatus','LOAD M1 FIRST');return;}
    try{
      setText('forecastLiveStatus','REFRESHING');
      const r=await api('/api/v1/data/refresh',{method:'POST',body:JSON.stringify({symbol_id:symbolId})});
      const previous=state.lastLiveBarTime??(state.bars.length?state.bars[state.bars.length-1].time:null);
      const byTime=new Map(state.bars.map(x=>[Number(x.time),x]));
      (r.bars||[]).forEach(x=>byTime.set(Number(x.time),x));
      state.bars=[...byTime.values()].sort((a,b)=>a.time-b.time);
      const latest=Number(r.latest_closed_time||0);
      if(latest>0&&latest>Number(previous||0)){
        state.lastLiveBarTime=latest;
        drawChart(state.bars);
        setText('dataBarCount',number(state.bars.length));
        setText('forecastLiveStatus','NEW M1 · FORECASTING');
        await runForecast({silent:true});
      }else setText('forecastLiveStatus','UP TO DATE');
    }catch(e){setText('forecastLiveStatus','POLL ERROR');setText('forecastLiveNote',e.message);}
  }
  $('forecastAutoRefresh').addEventListener('change',()=>{
    updateLivePollingState();
    if($('forecastAutoRefresh').checked&&state.forecastMode==='live'){
      runForecast({silent:true});
      refreshLiveM1();
    }
  });
  function renderForecast(r){
    if(r.status!=='ok'){$('forecastOutput').innerHTML=`<article class="panel forecast-empty"><div class="empty-orbit">◈</div><h2>${escapeHTML(r.status||'Forecast unavailable')}</h2><p>${escapeHTML(r.message||'Insufficient history.')}</p><p class="muted small">Sample size: ${escapeHTML(r.sample_size??'—')} · No probability was published.</p></article>`;return;}
    const scenarios=(r.scenarios||[]).map(s=>`<div class="scenario-item"><div class="scenario-top"><b>${escapeHTML(s.name)}</b><strong>${(s.probability*100).toFixed(1)}%</strong></div><div class="scenario-bar"><span style="width:${(s.probability*100).toFixed(1)}%"></span></div><small>${escapeHTML(s.definition)}</small></div>`).join('');
    const p=r.price_range||{};const event=r.event_forecast||{};const targets=r.target_attainment?.levels||{};
    $('forecastOutput').innerHTML=`<div class="forecast-result-grid"><article class="panel"><div class="panel-header"><div><div class="eyebrow">EXCLUSIVE SCENARIOS</div><h2>${Number(r.horizon_minutes||60)}-minute scenario mix</h2><p class="muted">${r.sample_size} analogs · ${escapeHTML(r.analogs_used)}</p></div><span class="pill green-pill">SUM 100%</span></div><div class="scenario-list">${scenarios}</div><p class="field-help">${escapeHTML(r.risk_note||'')}</p></article><article class="panel"><div class="panel-header"><div><div class="eyebrow">PRICE DISTRIBUTION</div><h2>Empirical price range</h2><p class="muted">Current context price ${Number(r.context.last_price).toFixed(5)} · ATR ${Number(r.context.atr).toFixed(5)}</p></div></div><div class="price-range"><div><small>P10 · LOWER</small><b>${Number(p.p10).toFixed(5)}</b></div><div><small>P50 · MEDIAN</small><b>${Number(p.p50).toFixed(5)}</b></div><div><small>P90 · UPPER</small><b>${Number(p.p90).toFixed(5)}</b></div></div><div class="divider"></div><div class="metric-grid three"><div class="metric-tile"><small>BUY-SIDE SWEEP</small><strong>${(event.buy_side_sweep_probability*100).toFixed(1)}%</strong></div><div class="metric-tile"><small>SELL-SIDE SWEEP</small><strong>${(event.sell_side_sweep_probability*100).toFixed(1)}%</strong></div><div class="metric-tile"><small>BULLISH MSS</small><strong>${(event.bullish_mss_probability*100).toFixed(1)}%</strong></div><div class="metric-tile"><small>BEARISH MSS</small><strong>${(event.bearish_mss_probability*100).toFixed(1)}%</strong></div><div class="metric-tile"><small>VOL REGIME</small><strong>${escapeHTML(r.context.volatility_regime)}</strong></div></div><div class="data-note">P50 expected high ${Number(p.expected_high_p50).toFixed(5)} · P50 expected low ${Number(p.expected_low_p50).toFixed(5)} · Bullish 1R ${(targets.bullish_1r?.probability*100||0).toFixed(1)}% · Bearish 1R ${(targets.bearish_1r?.probability*100||0).toFixed(1)}%</div><div class="data-note">As-of: ${escapeHTML(r.as_of)} · ${escapeHTML(r.context.session)} · ${escapeHTML(r.context.trend)}</div></article></div>${r.historical_outcome?`<article class="panel" style="margin-top:14px"><div class="eyebrow">HISTORICAL OUTCOME · NOT USED IN TRAINING</div><h3>${escapeHTML(r.historical_outcome.scenario)}</h3><p class="muted small">Realized return ${Number(r.historical_outcome.return_atr).toFixed(2)} ATR · MFE ${Number(r.historical_outcome.max_favourable_atr).toFixed(2)} ATR · MAE ${Number(r.historical_outcome.max_adverse_atr).toFixed(2)} ATR</p></article>`:''}`;
  }
  $('refreshEvaluationBtn').addEventListener('click',loadEvaluation);
  async function loadEvaluation(){try{
    const r=await api('/api/v1/forecast/evaluation');const m=r.metrics||{};
    const values=[['EVALUATED FORECASTS',m.evaluated_runs??0,'Forecasts with known horizon outcomes'],['BRIER SCORE',m.brier_score==null?'—':m.brier_score.toFixed(4),'Lower is better · 0 is perfect'],['TOP SCENARIO ACCURACY',m.top_scenario_accuracy==null?'—':`${(m.top_scenario_accuracy*100).toFixed(1)}%`,'Argmax scenario accuracy'],['MODEL VERSION',r.records?.[0]?.model_version||'HYBRID 0.2','Historical analogue baseline']];
    $('evaluationMetrics').innerHTML=values.map(x=>`<article class="metric-card"><div class="metric-label">${x[0]}</div><div class="metric-value ${String(x[1]).length>12?'compact-value':''}">${escapeHTML(x[1])}</div><div class="metric-foot">${escapeHTML(x[2])}</div></article>`).join('');
    $('evaluationTable').innerHTML=(r.records||[]).map(x=>`<tr><td>${escapeHTML(x.created_at)}</td><td>${escapeHTML(x.symbol)}</td><td>${escapeHTML(x.as_of)}</td><td>${escapeHTML(x.model_version||'—')}</td><td>${escapeHTML(x.sample_size??'—')}</td><td>${escapeHTML(x.status||'—')}</td><td>${escapeHTML(x.outcome?.scenario||'Pending')}</td></tr>`).join('')||'<tr><td colspan="7" class="empty-cell">No forecast records have been saved.</td></tr>';
    const labels=['Bullish expansion','Bearish expansion','Consolidation'];
    const pct=v=>v==null?'—':`${(Number(v)*100).toFixed(1)}%`;
    const pr=m.precision_recall_by_scenario||{};
    $('evaluationClassTable').innerHTML=labels.map(name=>{const x=pr[name]||{};return `<tr><td>${escapeHTML(name)}</td><td>${pct(x.precision)}</td><td>${pct(x.recall)}</td><td>${escapeHTML(x.support??0)}</td></tr>`;}).join('')||'<tr><td colspan="4" class="empty-cell">No evaluated forecasts yet.</td></tr>';
    const reliability=m.top_class_reliability_bins||[];
    $('evaluationReliabilityTable').innerHTML=reliability.map(x=>`<tr><td>${escapeHTML(x.confidence_bin)}</td><td>${escapeHTML(x.count)}</td><td>${pct(x.mean_confidence)}</td><td>${pct(x.accuracy)}</td></tr>`).join('')||'<tr><td colspan="4" class="empty-cell">No evaluated forecasts yet.</td></tr>';
    const cm=m.confusion_matrix||{};
    $('evaluationConfusionTable').innerHTML=labels.map(actual=>`<tr><td>${escapeHTML(actual)}</td>${labels.map(predicted=>`<td>${escapeHTML(cm[actual]?.[predicted]??0)}</td>`).join('')}</tr>`).join('');
    setText('engineEval','UPDATED');
  }catch(e){setText('engineEval','UNAVAILABLE');}}

  $('newNoteBtn').addEventListener('click',()=>$('noteForm').classList.toggle('hidden'));
  $('noteForm').addEventListener('submit',async(e)=>{e.preventDefault();try{await api('/api/v1/research/notes',{method:'POST',body:JSON.stringify({title:$('noteTitle').value,body:$('noteBody').value,tags:$('noteTags').value.split(',').map(x=>x.trim()).filter(Boolean)})});$('noteForm').reset();$('noteForm').classList.add('hidden');await loadResearch();toast('Research note saved.','success');}catch(err){toast(err.message,'error');}});
  async function loadResearch(){try{const r=await api('/api/v1/research/notes');$('notesList').innerHTML=(r.notes||[]).map(n=>`<article class="note-item"><b>${escapeHTML(n.title)}</b><small>${escapeHTML(n.created_at)} · ${(n.tags||[]).map(escapeHTML).join(', ')}</small><p>${escapeHTML(n.body)}</p><button data-delete-note="${n.id}">Delete</button></article>`).join('')||'<div class="empty-state small-empty">No research notes yet.</div>';$('notesList').querySelectorAll('[data-delete-note]').forEach(b=>b.addEventListener('click',async()=>{try{await api(`/api/v1/research/notes/${b.dataset.deleteNote}`,{method:'DELETE'});await loadResearch();}catch(e){toast(e.message,'error');}}));}catch(e){}}

  $('dayStartHour').value=String(state.dayStartHour);
  $('dayStartHour').addEventListener('change',e=>{state.dayStartHour=Number(e.target.value);localStorage.setItem('ictql_day_start',String(state.dayStartHour));toast('Trading day profile updated for subsequent analyses.','success');});
  const SESSION_FIELDS={Asia:['sessionAsiaStart','sessionAsiaEnd'],London:['sessionLondonStart','sessionLondonEnd'],'NY AM':['sessionNyAmStart','sessionNyAmEnd'],'London Close':['sessionLondonCloseStart','sessionLondonCloseEnd'],'NY PM':['sessionNyPmStart','sessionNyPmEnd']};
  async function loadSessionProfile(){try{const r=await api('/api/v1/settings/session-profile');for(const [name,ids] of Object.entries(SESSION_FIELDS)){const w=r.windows?.[name];if(w){$(ids[0]).value=w.start;$(ids[1]).value=w.end;}}}catch(e){setText('apiTestResult',e.message);}}
  $('saveSessionProfileBtn').addEventListener('click',async()=>{const windows={};for(const [name,ids] of Object.entries(SESSION_FIELDS)){windows[name]={start:$(ids[0]).value,end:$(ids[1]).value};}try{await api('/api/v1/settings/session-profile',{method:'PUT',body:JSON.stringify({windows})});toast('New York session profile saved on backend.','success');}catch(e){toast(e.message,'error');}});
  function number(v){return Number(v||0).toLocaleString();}
  function escapeHTML(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function escapeAttr(v){return escapeHTML(v).replace(/`/g,'&#96;');}
  function downloadBlob(content,name,type){const blob=new Blob([content],{type});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);}

  async function boot(){initDates();updateClock();setInterval(updateClock,1000);$('apiBaseInput').value=state.apiBase;$('loginApiBase').value=state.apiBase;
    const params=new URLSearchParams(location.search);if(params.get('ctrader')==='connected'&&state.token){/* parsed after login */}
    if(!state.apiBase){showLogin('Enter the FastAPI backend URL to continue.');return;}
    if(!state.token){showLogin('Sign in with the backend admin credentials.');return;}
    await initializeWorkspace();
  }
  boot();
})();
