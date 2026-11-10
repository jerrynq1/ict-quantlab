(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const STORE = { api: 'ictql_api_base', clientId: 'ictql_client_id', redirect: 'ictql_redirect_uri', env: 'ictql_ctrader_env', token: 'ictql_api_token' };
  const state = { view: 'overview', config: null, modules: [], token: sessionStorage.getItem(STORE.token) || '', apiBase: localStorage.getItem(STORE.api) || '', busy: false, pendingCredentialDraft: null };

  const navItems = [
    ['overview','Overview'],['data-center','Data Center'],['gap','Gap Statistics'],['liquidity','Liquidity Statistics'],['sessions','Session Statistics'],['time','Time Statistics'],['structure','Market Structure'],['daily-weekly','Daily & Weekly'],['liquidity-mss','Liquidity → MSS'],['forecast','Forecast Lab'],['research','Research & Evaluation']
  ];
  const details = {
    gap: { title:'Gap Statistics', subtitle:'Thống kê NDOG và NWOG, mức độ lấp gap và phản ứng giá sau khi chạm.', sections:[['NDOG / NWOG','Gap được xác định từ close của trading period trước tới open của trading period mới. Trading-day/week boundary phải theo calendar của symbol.'],['Fill Progress','Theo dõi wick-touch tại 25%, 50%, 75% và 100%. Close-confirmed fill là một bộ lọc riêng.'],['Fill Latency','Đo thời gian thị trường tới lần chạm đầu tiên, phân nhóm theo session và weekday.'],['Post-fill Reaction','Đo excursion sau lần fill đầu tại các horizon cố định; không dùng nến tương lai làm feature.']] },
    liquidity: { title:'Liquidity Statistics', subtitle:'Theo dõi liquidity pool, sweep, breakout và reclaim theo định nghĩa có thể kiểm chứng.', sections:[['Asia High / Low','Mốc high/low của Asia range đã cấu hình theo New York local time.'],['PDH / PDL','High/low của trading day hoàn tất trước đó theo lịch giao dịch của symbol.'],['PWH / PWL','High/low của trading week hoàn tất trước đó.'],['Sweep vs Breakout','Probe là wick vượt level theo tick tolerance. Sweep cần reclaim; close tiếp diễn ngoài level được phân loại breakout/acceptance.']] },
    sessions: { title:'Session Statistics', subtitle:'Phân tích range, direction, high/low timing và tương tác liquidity của từng session.', sections:[['Asia','Mặc định 19:00–00:00 New York time; khoảng qua nửa đêm.'],['London','Mặc định 02:00–05:00 New York time.'],['New York AM','Mặc định 08:30–11:00 New York time.'],['New York PM','Mặc định 13:30–16:00 New York time.']] },
    time: { title:'Time Statistics', subtitle:'Phân phối thời gian xuất hiện của event và thời điểm hình thành extreme.', sections:[['Event Time','Thời điểm sweep, MSS, reversal, expansion và first-touch của key levels.'],['Daily Extremes','Tìm lần đầu đạt final high/low sau khi trading day kết thúc; chỉ dùng retrospective.'],['Weekly Extremes','Thống kê weekday và NY time bucket hình thành weekly high/low.'],['Heatmap','Phải hiển thị count, sample size và coverage bên cạnh density.']] },
    structure: { title:'Market Structure Statistics', subtitle:'Đo lường quan hệ Liquidity Sweep → MSS, hiệu suất dịch chuyển và thời gian đạt mục tiêu.', sections:[['Confirmed Swing','Pivot chỉ có thể sử dụng sau khi đủ right-bars đóng; known_at không được backdate.'],['MSS','Bullish MSS cần downside sweep hợp lệ trước đó và candle close phá swing high đã xác nhận; bearish MSS là đối xứng.'],['MFE / MAE','Tính từ entry reference được định nghĩa cố định, mặc định break close; đo bằng giá và R.'],['Ambiguous OHLC','Nếu cùng một candle chạm target và stop mà không biết thứ tự, đánh dấu ambiguous hoặc dùng giả định conservative.']] },
    'daily-weekly': { title:'Daily & Weekly Statistics', subtitle:'Đánh giá direction, range, thời điểm hình thành high/low và tương tác previous-period levels.', sections:[['Direction','Close so với open với neutral tolerance cấu hình theo tick/volatility.'],['Range','High–low theo giá, ticks và ATR-normalized range.'],['Extreme Timing','Weekday và NY local-time bucket tạo final high/low.'],['Key-level Interaction','Tách touch, probe, confirmed sweep, breakout và reclaim.']] },
    'liquidity-mss': { title:'Liquidity → MSS Probability', subtitle:'Xác suất có điều kiện từ một liquidity sweep tới MSS theo horizon cụ thể.', sections:[['Conditional Event','Ví dụ: P(bullish MSS trong 30 market minutes | Asia Low confirmed sweep, NY AM).'],['Eligible Denominator','Mỗi observation bắt đầu từ một qualifying sweep; chính sách loại trùng theo level/day được version hóa.'],['Uncertainty','Hiển thị numerator, denominator, Wilson interval và data coverage.'],['Dependence','Event chồng lấn không được coi là mẫu độc lập; không cộng xác suất của các event không loại trừ nhau.']] },
    forecast: { title:'Hybrid Forecast Lab', subtitle:'Kết hợp dự báo sự kiện ICT và phân phối giá; hỗ trợ Live Forecast và Historical Scenario Replay.', sections:[['Event Forecast','Dự báo next-state theo các nhãn loại trừ lẫn nhau: reversal, continuation hoặc range/no-event.'],['Price Forecast','Dự báo quantile/range cho 15/30/60 phút; target-touch phải có reference price và risk distance.'],['Live Mode','Chỉ dùng candle đã đóng và event đã được xác nhận tại thời điểm as-of.'],['Historical Replay','Đóng băng feature tại timestamp trong quá khứ rồi mới mở dữ liệu tương lai để score.']] },
    research: { title:'Research & Evaluation', subtitle:'Đo hiệu quả out-of-sample và độ tin cậy của mô hình trước khi công bố xác suất.', sections:[['Walk-forward','Chia train/test theo thời gian; purge/embargo outcome horizon chồng lấn.'],['Event Models','Brier score, log loss, calibration, precision/recall tại threshold đã chốt.'],['Price Models','Pinball loss, interval coverage và CRPS nếu được triển khai.'],['Release Gate','Chỉ bật model nếu cải thiện baseline ngoài mẫu và calibration ổn định qua symbol/session/regime.']] }
  };

  function esc(value='') { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function apiUrl(path) { return (state.apiBase || '').replace(/\/$/, '') + '/api/v1' + path; }
  async function request(path, options={}) {
    if (!state.apiBase) throw new Error('Chưa cấu hình URL backend FastAPI. HTML tĩnh không tự chạy backend.');
    const headers = { 'Content-Type':'application/json', ...(options.headers || {}) };
    if (state.token) headers.Authorization = 'Bearer ' + state.token;
    const response = await fetch(apiUrl(path), { ...options, headers, mode:'cors', cache:'no-store' });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `API error ${response.status}`);
    return body;
  }
  function toast(message) {
    const el = $('#toast'); el.textContent = message; el.classList.add('show');
    clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove('show'), 3800);
  }
  function setConnection(label, online=false) {
    $('#connection-label').textContent = label;
    $('#connection-pill').classList.toggle('online', online);
  }
  function heading(title, subtitle, actions='') {
    return `<div class="page-heading"><div><div class="eyebrow">ICT QUANTLAB / ${esc(title.toUpperCase())}</div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="heading-actions">${actions}</div></div>`;
  }
  function metric(label,value,note) {
    return `<div class="metric-card"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(value)}</div><div class="metric-note">${esc(note)}</div></div>`;
  }
  function panel(title, subtitle, content, chip='RESEARCH MODULE') {
    return `<section class="panel"><div class="panel-head"><div><h2>${esc(title)}</h2>${subtitle?`<p class="panel-sub">${esc(subtitle)}</p>`:''}</div><span class="chip">${esc(chip)}</span></div>${content}</section>`;
  }
  function emptyState(title, text) {
    return `<div class="empty-state"><div class="empty-icon">⌁</div><b>${esc(title)}</b><p>${esc(text)}</p></div>`;
  }
  function overviewView() {
    return heading('Research Dashboard','Workspace nghiên cứu thống kê ICT và dự báo định lượng.') +
      `<div class="grid metric-grid">${metric('CTRADER APP',state.config?.configured?'Credentials saved':'Not configured','Client ID / Secret được lưu ở backend nếu đã thiết lập')}${metric('OAUTH STATUS',state.config?.oauth_status==='oauth_tokens_saved_account_pending'?'Token acquired':'Pending','OAuth token chưa đồng nghĩa account đã được xác thực')}${metric('ACTIVE SYMBOLS','—','Chờ account authorization và dynamic symbol discovery')}${metric('FORECAST READINESS','Standby','Không hiển thị xác suất chưa được kiểm chứng')}</div>` +
      `<div class="grid two-col">${panel('Market Research','M1 là nguồn canonical; higher timeframes được tổng hợp từ M1.',emptyState('Waiting for verified market data','Kết nối backend, xác thực tài khoản cTrader và tải dữ liệu M1 đã kiểm tra. Không hiển thị dữ liệu minh họa như giá thật.'),'M1 CANONICAL')}${panel('Analytics pipeline','Các lớp phụ thuộc chính trong hệ thống.',`<div class="module-list">${[['01','Data ingestion & smart cache','Tải range thiếu, de-duplicate timestamp.'],['02','ICT Event Engine','Sweep, gap, swing, MSS với known_at.'],['03','Statistics Engine','7 module Phase 1, sample size và CI.'],['04','Hybrid Forecast','Event + price scenarios, live và replay.'],['05','Evaluation','Walk-forward, calibration, baseline comparison.']].map(x=>`<div class="module-row"><span class="module-number">${x[0]}</span><div><b>${x[1]}</b><small>${x[2]}</small></div><span class="module-status">PENDING</span></div>`).join('')}</div>`,'SYSTEM MAP')}</div>` +
      panel('Hybrid Forecast Engine','Hai bài toán riêng, một giao diện nghiên cứu.',`<div class="notice info"><strong>Event Forecast:</strong> next-state/event probabilities. &nbsp; <strong>Price Forecast:</strong> conditional quantiles và target-touch probability. Mọi feature phải có known_at ≤ forecast as-of; model cần walk-forward validation và calibration trước khi hiển thị xác suất.</div>`,'EVENT + PRICE');
  }
  function dataCenterView() {
    const redirect = localStorage.getItem(STORE.redirect) || '';
    const clientId = state.config?.client_id || localStorage.getItem(STORE.clientId) || '';
    const env = state.config?.environment || localStorage.getItem(STORE.env) || 'demo';
    return heading('Data Center','Cấu hình API, bảo mật credentials cTrader và kiểm tra trạng thái kết nối.') +
      panel('Backend API','GitHub Pages chỉ host HTML/CSS/JS. FastAPI cần chạy ở một host riêng.',`<div class="form-grid"><div class="field full"><label>FASTAPI BASE URL</label><input id="api-base-input" type="url" placeholder="https://your-api-host.example.com" value="${esc(state.apiBase)}"><span class="hint">Ví dụ: URL Render/VPS của backend. Không thêm /api/v1 ở cuối.</span></div><div class="field full"><button class="button button-secondary" id="save-api-url">Save API URL &amp; test connection</button></div></div><div id="api-test-result" class="status-line" style="margin-top:12px"><span class="status-led"></span>${state.apiBase?'Chưa kiểm tra backend':'Chưa cấu hình backend'}</div>`,'API CONNECTION') +
      panel('cTrader Open API credentials','Client Secret không được lưu trong localStorage. Nhập Secret để gửi trực tiếp tới backend qua HTTPS.',`<form id="ctrader-form" class="form-grid">
        <div class="field"><label>CLIENT ID</label><input id="ctrader-client-id" required value="${esc(clientId)}" placeholder="Paste Client ID"></div>
        <div class="field"><label>CLIENT SECRET ${state.config?.secret_saved?'<span style="color:var(--green)">· SAVED ON SERVER</span>':''}</label><input id="ctrader-client-secret" type="password" autocomplete="new-password" placeholder="${state.config?.secret_saved?'Đã lưu — để trống nếu giữ nguyên':'Paste Client Secret'}"><span class="hint">Không lưu Secret vào GitHub, localStorage hay file HTML.</span></div>
        <div class="field full"><label>REDIRECT URI</label><input id="ctrader-redirect" required type="url" value="${esc(state.config?.redirect_uri || redirect)}" placeholder="https://YOUR-API/api/v1/integrations/ctrader/callback"><span class="hint">Phải là callback backend và trùng chính xác URI đã đăng ký trong cTrader Developer Portal.</span></div>
        <div class="field"><label>ENVIRONMENT</label><select id="ctrader-env"><option value="demo" ${env==='demo'?'selected':''}>Demo</option><option value="live" ${env==='live'?'selected':''}>Live</option></select></div>
        <div class="field"><label>OAUTH STATUS</label><div class="status-line" style="height:39px"><span class="status-led ${state.config?.oauth_status==='oauth_tokens_saved_account_pending'?'ok':''}"></span>${esc(state.config?.oauth_status || 'Chưa tải trạng thái')}</div></div>
        <div class="field full"><div class="notice warning"><strong>Bảo mật:</strong> Client Secret chỉ được lưu mã hóa ở backend. Trường Secret sẽ luôn trống sau reload. GitHub Pages là static hosting nên không thể tự giữ Secret an toàn.</div></div>
        <div class="field full" style="display:flex;flex-wrap:wrap;gap:8px"><button class="button button-primary" type="submit">Save credentials to backend</button><button class="button button-secondary" type="button" id="authorize-ctrader">Authorize cTrader account</button><button class="button button-quiet" type="button" id="refresh-config">Refresh status</button></div>
        <div class="field full"><div id="ctrader-message" class="form-error"></div></div>
      </form>`,'CTRADER OPEN API') +
      panel('Connection steps','Không đánh dấu Connected chỉ vì Client ID/Secret đã lưu.',`<div class="steps"><div class="step"><div><b>Configure app credentials.</b> Save Client ID, Client Secret, Redirect URI và môi trường.</div></div><div class="step"><div><b>OAuth consent.</b> Chuyển sang cTrader để chấp thuận scope accounts.</div></div><div class="step"><div><b>Exchange tokens.</b> Backend đổi authorization code và lưu access/refresh token mã hóa.</div></div><div class="step"><div><b>Account authorization.</b> Protobuf transport xác thực ứng dụng, liệt kê và chọn account.</div></div><div class="step"><div><b>Market data.</b> Tải symbol catalog và M1, sau đó mới kích hoạt statistics.</div></div></div>`,'AUTH FLOW');
  }
  function moduleView(key) {
    const d = details[key];
    const cards = d.sections.map(([title,body])=>`<div class="definition-card"><h3>${esc(title)}</h3><p>${esc(body)}</p></div>`).join('');
    const note = key==='forecast' ? 'Chưa có model đã được huấn luyện và kiểm định; không hiển thị forecast giả.' : 'Module đang ở trạng thái đặc tả/triển khai. Chưa có kết quả thống kê cho tới khi nạp và xác thực dữ liệu M1.';
    return heading(d.title,d.subtitle) + `<div class="grid definition-grid">${cards}</div><div style="height:14px"></div>${panel('Result workspace','Kết quả sẽ được tính theo global filters và định nghĩa event đã version hóa.',emptyState('No validated results yet',note),'AWAITING DATA')}`;
  }
  function loginModal(show=true) { $('#login-modal').classList.toggle('hidden',!show); if(show) $('#login-username').focus(); }

  function render() {
    const title = navItems.find(x=>x[0]===state.view)?.[1] || 'Overview';
    $('#breadcrumb-current').textContent = title.toUpperCase();
    $$('.nav-item').forEach(btn=>btn.classList.toggle('active',btn.dataset.view===state.view));
    $('#view-root').innerHTML = state.view==='overview' ? overviewView() : state.view==='data-center' ? dataCenterView() : moduleView(state.view);
    $('#sidebar').classList.remove('open');
    bindViewActions();
  }
  function setView(view) { state.view = view; location.hash = view; render(); }
  async function refreshConfig() {
    if (!state.token || !state.apiBase) { state.config = null; setConnection(state.apiBase?'BACKEND SET · SIGN IN':'API NOT CONFIGURED',false); render(); return; }
    try {
      state.config = await request('/integrations/ctrader/config');
      const ready = state.config.oauth_status === 'oauth_tokens_saved_account_pending';
      setConnection(ready?'OAUTH TOKENS SAVED':'CREDENTIALS SAVED',false);
    } catch (error) {
      if (/401|Session expired|sign in/i.test(error.message)) { state.token=''; sessionStorage.removeItem(STORE.token); }
      setConnection('API AUTH REQUIRED',false);
    }
    if (state.view==='data-center' || state.view==='overview') render();
  }
  async function testApi() {
    const result = $('#api-test-result');
    result.innerHTML = '<span class="status-led"></span>Testing API…';
    try {
      const response = await fetch(state.apiBase.replace(/\/$/,'')+'/api/v1/system/health',{mode:'cors',cache:'no-store'});
      if (!response.ok) throw new Error('HTTP '+response.status);
      const data = await response.json();
      result.innerHTML = '<span class="status-led ok"></span>API ONLINE · '+esc(data.service || 'FastAPI');
      setConnection('API ONLINE',true); toast('Kết nối backend thành công.');
    } catch (error) {
      result.innerHTML = '<span class="status-led"></span>'+esc(error.message)+' · Kiểm tra URL, HTTPS và CORS.';
      setConnection('API NOT REACHABLE',false);
    }
  }
  function openLogin() { loginModal(true); }

  function bindViewActions() {
    const saveApi = $('#save-api-url');
    if (saveApi) saveApi.addEventListener('click', async () => {
      const value = $('#api-base-input').value.trim().replace(/\/$/,'');
      if (!/^https:\/\//i.test(value)) { toast('Backend URL phải dùng HTTPS.'); return; }
      state.apiBase = value; localStorage.setItem(STORE.api,value); await testApi();
      if (state.token) await refreshConfig();
    });
    const form = $('#ctrader-form');
    if (form) form.addEventListener('submit', async e => {
      e.preventDefault();
      state.apiBase = (localStorage.getItem(STORE.api)||'').replace(/\/$/,'');
      const payload = {
        client_id: $('#ctrader-client-id').value.trim(),
        client_secret: $('#ctrader-client-secret').value,
        redirect_uri: $('#ctrader-redirect').value.trim(),
        environment: $('#ctrader-env').value
      };
      localStorage.setItem(STORE.clientId,payload.client_id);
      localStorage.setItem(STORE.redirect,payload.redirect_uri);
      localStorage.setItem(STORE.env,payload.environment);
      if (!state.apiBase) { $('#ctrader-message').textContent='Hãy cấu hình và test backend URL trước. HTML static không thể lưu Client Secret an toàn.'; return; }
      if (!state.token) { state.pendingCredentialDraft = payload; $('#ctrader-message').textContent='Đăng nhập backend để lưu credentials. Secret chưa được lưu.'; openLogin(); return; }
      $('#ctrader-message').textContent='Saving…';
      try {
        state.config = await request('/integrations/ctrader/config',{method:'PUT',body:JSON.stringify(payload)});
        $('#ctrader-client-secret').value='';
        $('#ctrader-message').innerHTML='Credentials saved securely on backend. Secret is not returned to this page.';
        setConnection('CREDENTIALS SAVED',false); toast('Đã lưu cấu hình cTrader ở backend.'); render();
      } catch (error) { $('#ctrader-message').textContent=error.message; }
    });
    const authorize = $('#authorize-ctrader');
    if (authorize) authorize.addEventListener('click', async () => {
      if (!state.apiBase) { $('#ctrader-message').textContent='Hãy cấu hình backend URL trước khi authorize.'; return; }
      if (!state.token) { openLogin(); $('#ctrader-message').textContent='Đăng nhập backend trước khi authorize.'; return; }
      try {
        const data = await request('/integrations/ctrader/authorize-url',{method:'POST',body:'{}'});
        location.href = data.authorization_url;
      } catch (error) { $('#ctrader-message').textContent=error.message; }
    });
    const refresh = $('#refresh-config');
    if (refresh) refresh.addEventListener('click', refreshConfig);
  }

  $('#main-nav').addEventListener('click', e => {
    const button = e.target.closest('[data-view]'); if (button) setView(button.dataset.view);
  });
  $('#open-settings').addEventListener('click', () => setView('data-center'));
  $('#mobile-menu').addEventListener('click', () => $('#sidebar').classList.toggle('open'));
  $$('[data-close-modal]').forEach(btn=>btn.addEventListener('click',()=>loginModal(false)));
  $('#login-modal').addEventListener('click',e=>{if(e.target.id==='login-modal') loginModal(false);});
  $('#login-form').addEventListener('submit', async e => {
    e.preventDefault(); $('#login-error').textContent=''; $('#login-submit').disabled=true;
    try {
      const response = await fetch(apiUrl('/auth/login'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('#login-username').value,password:$('#login-password').value}),mode:'cors'});
      const body = await response.json().catch(()=>({})); if(!response.ok) throw new Error(body.detail||'Login failed');
      state.token = body.access_token; sessionStorage.setItem(STORE.token,state.token); loginModal(false); $('#login-password').value='';
      toast('Đăng nhập backend thành công.'); await refreshConfig();
      if (state.pendingCredentialDraft) {
        const draft = state.pendingCredentialDraft; state.pendingCredentialDraft = null;
        $('#ctrader-client-id').value = draft.client_id; $('#ctrader-client-secret').value = draft.client_secret;
        $('#ctrader-redirect').value = draft.redirect_uri; $('#ctrader-env').value = draft.environment;
        $('#ctrader-message').textContent = 'Đã đăng nhập. Nhấn Save credentials để lưu cấu hình.';
      }
    } catch(error) { $('#login-error').textContent=error.message; }
    finally { $('#login-submit').disabled=false; }
  });
  $('#apply-filters').addEventListener('click',()=>toast('Bộ lọc sẽ được áp dụng khi có dữ liệu M1 đã xác thực.'));

  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const hashView = location.hash.replace(/^#/,'').split('?')[0];
  if (navItems.some(x=>x[0]===hashView)) state.view=hashView;
  if (params.get('ctrader')) {
    if (params.get('ctrader')==='oauth_saved') toast('OAuth code đã được backend xử lý. Account authorization vẫn đang chờ.');
    else toast('OAuth chưa hoàn tất: '+params.get('ctrader'));
  }
  if (state.token && state.apiBase) refreshConfig(); else setConnection(state.apiBase?'BACKEND SET · SIGN IN':'API NOT CONFIGURED',false);
  render();
})();
