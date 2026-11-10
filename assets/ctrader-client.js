/* Browser-only cTrader Open API client (JSON over secure WebSocket, port 5036). */
(() => {
  'use strict';
  const PT = { APP_AUTH_REQ:2100, APP_AUTH_RES:2101, ACCOUNT_AUTH_REQ:2102, ACCOUNT_AUTH_RES:2103,
    SYMBOLS_REQ:2114, SYMBOLS_RES:2115, GET_TRENDBARS_REQ:2137, GET_TRENDBARS_RES:2138,
    ACCOUNTS_REQ:2149, ACCOUNTS_RES:2150, ERROR_RES:2142, HEARTBEAT:51 };
  const PERIOD = { M1:1 };
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const n = v => Number(v ?? 0);
  const uniqueId = () => (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);

  class CTraderClient extends EventTarget {
    constructor() {
      super(); this.ws = null; this.pending = new Map(); this.accounts = []; this.symbols = [];
      this.accountId = ''; this.environment = ''; this.connected = false; this.authorized = false;
      this.heartbeatTimer = null; this.coverage = new Map(); this.bars = new Map(); this.requestQueue = Promise.resolve();
    }
    emit(type, detail={}) { this.dispatchEvent(new CustomEvent(type, {detail})); }
    status(status, detail) { this.emit('status', {status, detail}); }
    endpoint(env) { return `wss://${env === 'live' ? 'live' : 'demo'}.ctraderapi.com:5036`; }
    closeSocket() {
      clearInterval(this.heartbeatTimer); this.heartbeatTimer = null;
      if (this.ws) { try { this.ws.close(1000, 'Client reset'); } catch (_) {} }
      this.ws = null; this.connected = false; this.authorized = false;
      for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new Error('cTrader connection closed')); }
      this.pending.clear();
    }
    disconnect() { this.closeSocket(); this.status('offline', 'Disconnected'); }
    async open(env) {
      this.closeSocket(); this.environment = env; this.status('connecting', `Connecting to ${env.toUpperCase()}...`);
      await new Promise((resolve, reject) => {
        const ws = new WebSocket(this.endpoint(env)); this.ws = ws; let settled = false;
        const timer = setTimeout(() => { if (!settled) { settled = true; try { ws.close(); } catch (_) {} reject(new Error('Connection timeout. Check network or cTrader endpoint.')); } }, 15000);
        ws.onopen = () => { if (settled) return; settled = true; clearTimeout(timer); this.connected = true; resolve(); };
        ws.onerror = () => { if (this.ws !== ws) return; if (!settled) { settled = true; clearTimeout(timer); reject(new Error('WebSocket connection failed. Browser/network may block cTrader Open API.')); } else this.status('error', 'WebSocket error'); };
        ws.onclose = e => { if (this.ws !== ws) return; this.connected = false; this.authorized = false; clearInterval(this.heartbeatTimer); this.status('offline', e.reason || `Connection closed (${e.code})`); };
        ws.onmessage = event => { this.onMessage(event.data).catch(error => this.emit('error', {message:error.message})); };
      });
      this.heartbeatTimer = setInterval(() => { if (this.ws?.readyState === WebSocket.OPEN) this.sendRaw(PT.HEARTBEAT, {}); }, 10000);
      this.status('connected', `${env.toUpperCase()} WebSocket connected`);
    }
    sendRaw(payloadType, payload, clientMsgId=uniqueId()) {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) throw new Error('cTrader WebSocket is not open');
      this.ws.send(JSON.stringify({clientMsgId, payloadType, payload})); return clientMsgId;
    }
    request(payloadType, payload, expectedType, timeout=20000) {
      const id = uniqueId();
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`cTrader request ${payloadType} timed out`)); }, timeout);
        this.pending.set(id, {resolve, reject, timer, expectedType});
        try { this.sendRaw(payloadType, payload, id); }
        catch (e) { clearTimeout(timer); this.pending.delete(id); reject(e); }
      });
    }
    async onMessage(raw) {
      let msg; try {
        if (typeof raw === 'string') msg = JSON.parse(raw);
        else if (typeof Blob !== 'undefined' && raw instanceof Blob) msg = JSON.parse(await raw.text());
        else msg = JSON.parse(new TextDecoder().decode(raw));
      } catch (_) { this.emit('rawmessage', {raw}); return; }
      const id = msg.clientMsgId; const pending = id && this.pending.get(id);
      if (pending) {
        clearTimeout(pending.timer); this.pending.delete(id);
        if (Number(msg.payloadType) === PT.ERROR_RES || msg.errorCode || msg.payload?.errorCode) {
          const p = msg.payload || msg; pending.reject(new Error(`${p.errorCode || 'cTrader error'}${p.description ? `: ${p.description}` : ''}`));
        } else if (pending.expectedType && Number(msg.payloadType) !== pending.expectedType) {
          pending.reject(new Error(`Unexpected cTrader response type ${msg.payloadType}; expected ${pending.expectedType}.`));
        } else pending.resolve(msg.payload || {});
      }
      this.emit('message', msg);
      if (Number(msg.payloadType) === PT.ERROR_RES && !pending) {
        const p = msg.payload || {}; this.emit('error', {message:`${p.errorCode || 'cTrader error'} ${p.description || ''}`.trim()});
      }
    }
    async appAuth(config) {
      await this.request(PT.APP_AUTH_REQ, {clientId:config.clientId, clientSecret:config.clientSecret}, PT.APP_AUTH_RES);
      this.status('app-authorized', 'Application authorization accepted');
    }
    async listAccounts(accessToken) {
      const data = await this.request(PT.ACCOUNTS_REQ, {accessToken}, PT.ACCOUNTS_RES);
      const raw = data.ctidTraderAccount || data.ctidTraderAccountId || data.accounts || [];
      this.accounts = (Array.isArray(raw) ? raw : [raw]).filter(Boolean).map(a => ({
        account_id:String(a.ctidTraderAccountId ?? a.accountId ?? a.id ?? ''),
        is_live:Boolean(a.isLive), trader_login:String(a.traderLogin ?? ''), broker:a.brokerTitleShort || a.brokerName || 'cTrader'
      })).filter(a => a.account_id);
      return this.accounts;
    }
    async authorizeAccount(accountId, accessToken) {
      if (!accountId) throw new Error('Account ID is required to authorize an account');
      await this.request(PT.ACCOUNT_AUTH_REQ, {ctidTraderAccountId:String(accountId), accessToken}, PT.ACCOUNT_AUTH_RES);
      this.accountId = String(accountId); this.authorized = true;
      this.status('authorized', `Account ${accountId} authorized on ${this.environment.toUpperCase()}`);
      return true;
    }
    async connect(config) {
      const envChoice = config.environment || 'auto'; const requestedId = String(config.accountId || '').trim();
      if (!config.clientId || !config.clientSecret || !config.accessToken) throw new Error('Nhập đầy đủ Client ID, Client Secret và Access Token.');
      const candidates = envChoice === 'auto' ? ['demo','live'] : [envChoice];
      let lastError;
      for (const env of candidates) {
        try {
          await this.open(env);
          await this.appAuth(config);
          const accounts = await this.listAccounts(config.accessToken);
          let account = requestedId ? accounts.find(a => a.account_id === requestedId) : (envChoice === 'auto' ? accounts[0] : accounts.find(a => a.is_live === (env === 'live')));
          // Manual Account ID is deliberately supported even if account-list metadata is absent.
          // Auto mode retries the other environment if AccountAuth fails on this endpoint.
          if (!account && requestedId) account = {account_id:requestedId,is_live:env === 'live',broker:'Manual account'};
          if (!account && accounts.length) account = accounts.find(a => a.is_live === (env === 'live')) || (envChoice === 'auto' ? accounts[0] : null);
          if (!account) throw new Error(`Không tìm thấy tài khoản trong môi trường ${env.toUpperCase()}. Kiểm tra Access Token / Account ID hoặc chọn đúng Demo/Live.`);
          if (envChoice === 'auto' && account.is_live !== (env === 'live')) {
            await this.closeAndSwitch(account.is_live ? 'live' : 'demo', config);
          }
          await this.authorizeAccount(account.account_id, config.accessToken);
          this.selectedAccount = account;
          await this.loadSymbols();
          return {account, accounts:this.accounts, symbols:this.symbols, environment:this.environment};
        } catch (e) { lastError = e; this.closeSocket(); if (envChoice !== 'auto') break; }
      }
      throw lastError || new Error('Unable to connect to cTrader');
    }
    async closeAndSwitch(env, config) {
      await this.open(env); await this.appAuth(config);
      // The manually supplied account ID is retained; the token grants its account access.
    }
    async loadSymbols() {
      if (!this.authorized) throw new Error('Authorize an account first');
      const data = await this.request(PT.SYMBOLS_REQ, {ctidTraderAccountId:this.accountId, includeArchivedSymbols:false}, PT.SYMBOLS_RES);
      this.symbols = (data.symbol || []).map(s => ({symbol_id:String(s.symbolId), name:s.symbolName || String(s.symbolId), enabled:s.enabled !== false, digits:5})).filter(s=>s.symbol_id);
      this.emit('symbols', {symbols:this.symbols}); return this.symbols;
    }
    async loadSymbolDetails(symbolId) {
      // Request full symbol metadata to obtain broker digits when available.
      const data = await this.request(2116, {ctidTraderAccountId:this.accountId, symbolId:[String(symbolId)]}, 2117);
      const s = (data.symbol || [])[0]; if (s) {
        const target=this.symbols.find(x=>x.symbol_id===String(symbolId)); if(target) target.digits=Number(s.digits ?? 5);
      }
      return this.symbols.find(x=>x.symbol_id===String(symbolId)) || {digits:5};
    }
    async requestBars(symbolId, fromMs, toMs) {
      const data = await this.request(PT.GET_TRENDBARS_REQ, {
        ctidTraderAccountId:this.accountId, symbolId:String(symbolId), period:PERIOD.M1,
        fromTimestamp:String(Math.floor(fromMs)), toTimestamp:String(Math.floor(toMs)), count:2000
      }, PT.GET_TRENDBARS_RES, 30000);
      const meta=this.symbols.find(x=>x.symbol_id===String(symbolId)) || {digits:5}; const scale=100000;
      return (data.trendbar || []).map(t => {
        const low=n(t.low)/scale; const open=(n(t.low)+n(t.deltaOpen))/scale;
        const close=(n(t.low)+n(t.deltaClose))/scale; const high=(n(t.low)+n(t.deltaHigh))/scale;
        return {time:n(t.utcTimestampInMinutes)*60000,open:Number(open.toFixed(meta.digits)),high:Number(high.toFixed(meta.digits)),low:Number(low.toFixed(meta.digits)),close:Number(close.toFixed(meta.digits)),volume:n(t.volume),quality:(high>=Math.max(open,close,low)&&low<=Math.min(open,close,high))?'ok':'suspect_ohlc'};
      }).filter(b=>b.time>0).sort((a,b)=>a.time-b.time);
    }
    getMissingRanges(symbolId, from, to) {
      const ranges=(this.coverage.get(String(symbolId))||[]).slice().sort((a,b)=>a[0]-b[0]);
      const missing=[]; let cursor=from;
      for(const [a,b] of ranges){ if(b<=cursor||a>=to) continue; if(a>cursor) missing.push([cursor,Math.min(a,to)]); cursor=Math.max(cursor,b); if(cursor>=to) break; }
      if(cursor<to) missing.push([cursor,to]); return missing.filter(x=>x[1]>x[0]);
    }
    async loadHistory(symbolId, fromMs, toMs, onProgress=()=>{}) {
      if (!this.authorized) throw new Error('Connect cTrader before loading market data');
      const id=String(symbolId); await this.loadSymbolDetails(id);
      const store=this.bars.get(id)||new Map(); let ranges=this.getMissingRanges(id,fromMs,toMs);
      const total=ranges.reduce((s,x)=>s+(x[1]-x[0]),0); let done=0,newBars=0,requests=0;
      for(const [a,b] of ranges){
        let cursor=a;
        while(cursor<b){
          const end=Math.min(cursor+24*60*60*1000,b);
          const rows=await this.requestBars(id,cursor,end);
          for(const bar of rows){if(bar.time>=cursor&&bar.time<=end){if(!store.has(bar.time))newBars++;store.set(bar.time,bar);}}
          const cover=this.coverage.get(id)||[]; cover.push([cursor,end]); this.coverage.set(id,cover);
          done+=end-cursor; cursor=end; requests++; onProgress({percent:total?Math.min(100,Math.round((done/total)*100)):100,requests,newBars});
          if(cursor<b) await pause(230); // historical limit: <= 5 requests/second
        }
      }
      this.bars.set(id,store);
      const result=[...store.values()].filter(b=>b.time>=fromMs&&b.time<=toMs).sort((a,b)=>a.time-b.time);
      this.emit('bars', {symbolId:id,bars:result});
      return {bars:result,count:result.length,newBars,requests,coverage:this.coverage.get(id)||[]};
    }
    sendHeartbeat() { if(this.ws?.readyState===WebSocket.OPEN) this.sendRaw(PT.HEARTBEAT,{}); }
  }
  window.CTraderClient = CTraderClient;
})();
