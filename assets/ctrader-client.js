/*
 * ICT QuantLab — direct cTrader Open API JSON/WebSocket client.
 * Personal browser-only build. No FastAPI, worker, or backend is used.
 * Connection sequence intentionally follows the working reference integration:
 * WebSocket -> ApplicationAuth -> GetAccountListByAccessToken -> switch to the
 * account's Demo/Live host when required -> ApplicationAuth -> AccountAuth -> SymbolsList.
 */
(() => {
  'use strict';

  const PT = Object.freeze({
    COMMON_ERROR:50, HEARTBEAT:51,
    APP_AUTH_REQ:2100, APP_AUTH_RES:2101,
    ACCOUNT_AUTH_REQ:2102, ACCOUNT_AUTH_RES:2103,
    VERSION_REQ:2104, VERSION_RES:2105,
    SYMBOLS_REQ:2114, SYMBOLS_RES:2115,
    SYMBOL_BY_ID_REQ:2116, SYMBOL_BY_ID_RES:2117,
    SUBSCRIBE_SPOTS_REQ:2127, SUBSCRIBE_SPOTS_RES:2128,
    SPOT_EVENT:2131,
    SUBSCRIBE_LIVE_TRENDBAR_REQ:2135, UNSUBSCRIBE_LIVE_TRENDBAR_REQ:2136,
    GET_TRENDBARS_REQ:2137, GET_TRENDBARS_RES:2138,
    ERROR_RES:2142, ACCOUNTS_TOKEN_INVALIDATED:2147,
    CLIENT_DISCONNECT:2148, ACCOUNTS_REQ:2149, ACCOUNTS_RES:2150,
    ACCOUNT_DISCONNECT:2164, SUBSCRIBE_LIVE_TRENDBAR_RES:2165
  });
  const PERIOD = Object.freeze({M1:1});
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const n = v => Number(v ?? 0);
  const int64 = (v, label) => {
    const x = Number(v);
    if (!Number.isFinite(x) || !Number.isSafeInteger(x) || x < 0) throw new Error(`${label} không hợp lệ: ${v}`);
    return x;
  };
  const uniqueId = () => globalThis.crypto?.randomUUID?.() || `ql-${Date.now()}-${Math.random().toString(36).slice(2,10)}`;
  const isLiveFlag = v => v === true || v === 1 || v === '1' || String(v).toLowerCase() === 'true';

  class CTraderClient extends EventTarget {
    constructor() {
      super();
      this.ws = null;
      this.pending = new Map();
      this.accounts = [];
      this.symbols = [];
      this.accountId = '';
      this.environment = '';
      this.connected = false;
      this.appAuthorized = false;
      this.authorized = false;
      this.heartbeatTimer = null;
      this.coverage = new Map();
      this.bars = new Map();
      this.nextHistoryAt = 0;
      this.historyQueue = Promise.resolve();
      this.phase = 'idle';
      this.intentionalClose = false;
    }

    emit(type, detail={}) {
      this.dispatchEvent(new CustomEvent(type, {detail}));
    }
    status(status, detail='') {
      this.emit('status', {status, detail, phase:this.phase, environment:this.environment});
    }
    endpoint(env) {
      return `wss://${env === 'live' ? 'live' : 'demo'}.ctraderapi.com:5036`;
    }

    _rejectAll(error) {
      for (const [id, item] of this.pending) {
        clearTimeout(item.timer);
        item.reject(error);
        this.pending.delete(id);
      }
    }

    closeSocket({silent=true}={}) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
      const old = this.ws;
      this.ws = null; // detach before close to ignore the intentional onclose event
      this.connected = false;
      this.appAuthorized = false;
      this.authorized = false;
      this._rejectAll(new Error('Socket được đóng khi khởi tạo kết nối mới.'));
      if (old) {
        try { old.close(1000, 'Client reset'); } catch (_) {}
      }
      if (!silent) this.status('offline', 'Đã ngắt kết nối.');
    }

    disconnect() {
      this.phase = 'disconnected';
      this.closeSocket({silent:true});
      this.accountId = '';
      this.status('offline', 'Đã ngắt kết nối thủ công.');
    }

    async open(env) {
      this.closeSocket({silent:true});
      this.environment = env;
      this.phase = 'websocket';
      this.status('connecting', `Đang mở WebSocket ${env.toUpperCase()}…`);

      await new Promise((resolve, reject) => {
        let ws;
        try { ws = new WebSocket(this.endpoint(env)); }
        catch (error) { reject(new Error(`Không tạo được WebSocket: ${error.message}`)); return; }
        this.ws = ws;
        let settled = false;
        const finish = (fn, value) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          fn(value);
        };
        const timer = setTimeout(() => {
          try { ws.close(); } catch (_) {}
          finish(reject, new Error(`Timeout mở WebSocket tới ${this.endpoint(env)}. Kiểm tra mạng, DNS hoặc endpoint.`));
        }, 15000);

        ws.onopen = () => {
          if (this.ws !== ws) return;
          this.connected = true;
          this.phase = 'websocket-open';
          finish(resolve);
          this.status('connected', `WebSocket ${env.toUpperCase()} đã mở; đang xác thực ứng dụng.`);
        };
        ws.onerror = () => {
          if (this.ws !== ws) return;
          const message = `WebSocket error khi mở ${this.endpoint(env)}. Có thể mạng/trình duyệt chặn kết nối.`;
          if (!settled) finish(reject, new Error(message));
          else this.emit('error', {message, phase:this.phase});
        };
        ws.onclose = event => {
          if (this.ws !== ws) return;
          this.connected = false;
          this.appAuthorized = false;
          this.authorized = false;
          clearInterval(this.heartbeatTimer);
          this.heartbeatTimer = null;
          const reason = String(event?.reason || '').trim();
          const detail = `cTrader đóng WebSocket (${event?.code ?? 'no code'}${reason ? ` · ${reason}` : ''}) tại bước ${this.phase}.`;
          this._rejectAll(new Error(detail));
          if (!settled) finish(reject, new Error(detail));
          if (!this.intentionalClose) {
            this.status('offline', detail);
            this.emit('disconnect', {code:event?.code, reason, phase:this.phase});
          }
        };
        ws.onmessage = event => {
          this.onMessage(event.data).catch(error => this.emit('error', {message:error.message, phase:this.phase}));
        };
      });

      // The cTrader JSON reference client sends a plain HeartbeatEvent (51), without a request id.
      this.heartbeatTimer = setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) {
          try { this.ws.send(JSON.stringify({payloadType:PT.HEARTBEAT, payload:{}})); }
          catch (error) { this.emit('error', {message:`Heartbeat failed: ${error.message}`, phase:this.phase}); }
        }
      }, 10000);
    }

    sendRaw(payloadType, payload, clientMsgId=uniqueId()) {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) throw new Error('WebSocket cTrader không ở trạng thái OPEN.');
      this.ws.send(JSON.stringify({clientMsgId, payloadType, payload}));
      return clientMsgId;
    }

    request(payloadType, payload, expectedType, timeout=20000) {
      if (!this.connected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
        return Promise.reject(new Error(`Không thể gửi request ${payloadType}: WebSocket chưa mở.`));
      }
      const id = uniqueId();
      const expected = expectedType == null ? null : (Array.isArray(expectedType) ? expectedType : [expectedType]).map(Number);
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          this.pending.delete(id);
          reject(new Error(`cTrader không trả lời request ${payloadType} sau ${timeout/1000}s (bước ${this.phase}).`));
        }, timeout);
        this.pending.set(id, {resolve, reject, timer, expected});
        try { this.sendRaw(payloadType, payload, id); }
        catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
      });
    }

    async onMessage(raw) {
      let msg;
      try {
        if (typeof raw === 'string') msg = JSON.parse(raw);
        else if (typeof Blob !== 'undefined' && raw instanceof Blob) msg = JSON.parse(await raw.text());
        else msg = JSON.parse(new TextDecoder().decode(raw));
      } catch (error) {
        this.emit('protocol-error', {message:`Không giải mã được JSON từ cTrader: ${error.message}`});
        return;
      }

      const payloadType = Number(msg.payloadType);
      const payload = msg.payload || msg;
      const id = msg.clientMsgId;
      const pending = id && this.pending.get(id);

      if (pending) {
        clearTimeout(pending.timer);
        this.pending.delete(id);
        if (payloadType === PT.COMMON_ERROR || payloadType === PT.ERROR_RES || payload.errorCode || msg.errorCode) {
          pending.reject(new Error(`${payload.errorCode || msg.errorCode || `cTrader error (${payloadType})`}${payload.description ? `: ${payload.description}` : ''}`));
        } else if (pending.expected && !pending.expected.includes(payloadType)) {
          pending.reject(new Error(`cTrader trả payload ${payloadType}, cần ${pending.expected.join('/')}.`));
        } else {
          pending.resolve(payload);
        }
      }

      this.emit('message', msg);

      // Server-side asynchronous disconnect / token invalidation events must not be mistaken for a generic close.
      if (payloadType === PT.CLIENT_DISCONNECT) {
        const reason = payload.reason || 'Ứng dụng bị cTrader ngắt kết nối.';
        this.phase = 'server-disconnect';
        this.status('error', `cTrader yêu cầu ngắt kết nối: ${reason}`);
        this.emit('error', {message:`cTrader yêu cầu ngắt kết nối: ${reason}`, phase:this.phase});
      } else if (payloadType === PT.ACCOUNTS_TOKEN_INVALIDATED || payloadType === PT.ACCOUNT_DISCONNECT) {
        const reason = payload.reason || 'Token hoặc phiên tài khoản không còn hiệu lực.';
        this.authorized = false;
        this.status('error', `Phiên cTrader bị thu hồi: ${reason}`);
        this.emit('error', {message:`Phiên cTrader bị thu hồi: ${reason}`, phase:this.phase});
      } else if ((payloadType === PT.COMMON_ERROR || payloadType === PT.ERROR_RES) && !pending) {
        this.emit('error', {message:`${payload.errorCode || 'cTrader error'}${payload.description ? `: ${payload.description}` : ''}`, phase:this.phase});
      }
    }

    async appAuth(config) {
      this.phase = 'application-auth';
      this.status('connecting', `Đang xác thực ứng dụng (${this.environment.toUpperCase()})…`);
      await this.request(PT.APP_AUTH_REQ, {clientId:config.clientId, clientSecret:config.clientSecret}, PT.APP_AUTH_RES, 20000);
      this.appAuthorized = true;
      this.status('app-authorized', 'ApplicationAuth thành công.');
    }

    async listAccounts(accessToken) {
      this.phase = 'account-list';
      this.status('connecting', 'Đang lấy danh sách tài khoản theo Access Token…');
      const data = await this.request(PT.ACCOUNTS_REQ, {accessToken}, PT.ACCOUNTS_RES, 20000);
      const raw = data.ctidTraderAccount || data.ctidTraderAccounts || data.accounts || [];
      this.accounts = (Array.isArray(raw) ? raw : [raw]).filter(Boolean).map(a => ({
        account_id:String(a.ctidTraderAccountId ?? a.accountId ?? a.id ?? ''),
        is_live:isLiveFlag(a.isLive),
        trader_login:String(a.traderLogin ?? ''),
        broker:a.brokerTitleShort || a.brokerName || 'cTrader'
      })).filter(a => a.account_id);
      return this.accounts;
    }

    async authorizeAccount(accountId, accessToken) {
      if (!this.appAuthorized) throw new Error('Chưa xác thực ứng dụng cTrader.');
      const id = int64(accountId, 'Account ID');
      this.phase = 'account-auth';
      this.status('connecting', `Đang xác thực tài khoản ${id}…`);
      await this.request(PT.ACCOUNT_AUTH_REQ, {ctidTraderAccountId:id, accessToken}, PT.ACCOUNT_AUTH_RES, 20000);
      this.accountId = String(id);
      this.authorized = true;
      this.status('authorized', `Tài khoản ${id} đã xác thực trên ${this.environment.toUpperCase()}.`);
      return true;
    }

    async connect(config) {
      const envChoice = ['demo','live'].includes(config.environment) ? config.environment : 'auto';
      const requestedId = String(config.accountId || '').trim();
      if (!config.clientId || !config.clientSecret || !config.accessToken) {
        throw new Error('Nhập đầy đủ Client ID, Client Secret và Access Token.');
      }

      // Match the reference project: Auto starts on LIVE, reads the token's account list,
      // then reconnects to the environment belonging to the selected account.
      const initialEnv = envChoice === 'auto' ? 'live' : envChoice;
      this.phase = 'starting';
      await this.open(initialEnv);
      try {
        await this.appAuth(config);
        const accounts = await this.listAccounts(config.accessToken);
        if (!accounts.length) {
          throw new Error('GetAccountListByAccessToken trả về 0 tài khoản. Kiểm tra Access Token, quyền truy cập và application registration.');
        }

        let account = requestedId
          ? accounts.find(a => a.account_id === requestedId || a.trader_login === requestedId)
          : accounts[0];
        if (!account) {
          const available = accounts.map(a => `${a.account_id} (${a.is_live ? 'Live' : 'Demo'})`).join(', ');
          throw new Error(`Không tìm thấy Account ID ${requestedId} trong danh sách được Access Token cấp quyền. Tài khoản có quyền: ${available}`);
        }

        const targetEnv = account.is_live ? 'live' : 'demo';
        if (targetEnv !== this.environment) {
          this.phase = 'switch-environment';
          this.status('connecting', `Tài khoản thuộc ${targetEnv.toUpperCase()}, đang chuyển máy chủ…`);
          await this.open(targetEnv);
          await this.appAuth(config); // ApplicationAuth must be repeated on the new socket.
        }

        await this.authorizeAccount(account.account_id, config.accessToken);
        this.selectedAccount = account;
        await this.loadSymbols();
        this.phase = 'ready';
        this.status('authorized', `Kết nối hoàn tất · ${targetEnv.toUpperCase()} · ${this.symbols.length} symbols.`);
        return {account, accounts:this.accounts, symbols:this.symbols, environment:this.environment};
      } catch (error) {
        const message = error?.message || String(error);
        this.closeSocket({silent:true});
        this.phase = 'failed';
        throw new Error(message);
      }
    }

    async loadSymbols() {
      if (!this.authorized) throw new Error('Phải xác thực tài khoản trước khi lấy symbols.');
      this.phase = 'symbols-list';
      const data = await this.request(PT.SYMBOLS_REQ, {
        ctidTraderAccountId:int64(this.accountId, 'Account ID'),
        includeArchivedSymbols:false
      }, PT.SYMBOLS_RES, 30000);
      this.symbols = (data.symbol || []).map(s => ({
        symbol_id:String(s.symbolId),
        name:s.symbolName || String(s.symbolId),
        enabled:s.enabled !== false,
        digits:5
      })).filter(s => s.symbol_id && s.symbol_id !== 'undefined');
      this.emit('symbols', {symbols:this.symbols});
      return this.symbols;
    }

    async loadSymbolDetails(symbolId) {
      const sid = int64(symbolId, 'Symbol ID');
      const data = await this.request(PT.SYMBOL_BY_ID_REQ, {
        ctidTraderAccountId:int64(this.accountId, 'Account ID'), symbolId:[sid]
      }, PT.SYMBOL_BY_ID_RES, 20000);
      const symbol = (data.symbol || [])[0];
      const target = this.symbols.find(x => x.symbol_id === String(sid));
      if (target && symbol) target.digits = Number(symbol.digits ?? 5);
      return target || {digits:5};
    }

    async requestBars(symbolId, fromMs, toMs) {
      if (!this.authorized) throw new Error('Tài khoản cTrader chưa được authorize.');
      const sid = int64(symbolId, 'Symbol ID');
      const from = int64(Math.floor(fromMs), 'From timestamp');
      const to = int64(Math.floor(toMs), 'To timestamp');
      if (to <= from) throw new Error('Khoảng thời gian tải M1 không hợp lệ.');
      const data = await this.request(PT.GET_TRENDBARS_REQ, {
        ctidTraderAccountId:int64(this.accountId, 'Account ID'),
        symbolId:sid, period:PERIOD.M1,
        fromTimestamp:from, toTimestamp:to, count:2000
      }, PT.GET_TRENDBARS_RES, 30000);
      const meta = this.symbols.find(x => x.symbol_id === String(sid)) || {digits:5};
      const scale = 100000;
      return (data.trendbar || []).map(t => {
        const low = n(t.low) / scale;
        const open = (n(t.low) + n(t.deltaOpen)) / scale;
        const close = (n(t.low) + n(t.deltaClose)) / scale;
        const high = (n(t.low) + n(t.deltaHigh)) / scale;
        const valid = high >= Math.max(open, close, low) && low <= Math.min(open, close, high);
        return {
          time:n(t.utcTimestampInMinutes) * 60000,
          open:Number(open.toFixed(meta.digits)), high:Number(high.toFixed(meta.digits)),
          low:Number(low.toFixed(meta.digits)), close:Number(close.toFixed(meta.digits)),
          volume:n(t.volume), quality:valid ? 'ok' : 'suspect_ohlc'
        };
      }).filter(b => b.time > 0).sort((a,b) => a.time-b.time);
    }

    getMissingRanges(symbolId, from, to) {
      const ranges = (this.coverage.get(String(symbolId)) || []).slice().sort((a,b) => a[0]-b[0]);
      const missing = []; let cursor = from;
      for (const [a,b] of ranges) {
        if (b <= cursor || a >= to) continue;
        if (a > cursor) missing.push([cursor, Math.min(a,to)]);
        cursor = Math.max(cursor,b);
        if (cursor >= to) break;
      }
      if (cursor < to) missing.push([cursor,to]);
      return missing.filter(x => x[1] > x[0]);
    }

    async _historySlot() {
      const wait = Math.max(0, this.nextHistoryAt - Date.now());
      if (wait) await pause(wait);
      this.nextHistoryAt = Date.now() + 230;
    }

    async loadHistory(symbolId, fromMs, toMs, onProgress=()=>{}) {
      if (!this.authorized) throw new Error('Connect cTrader before loading market data.');
      const id = String(int64(symbolId, 'Symbol ID'));
      const from = int64(Math.floor(fromMs), 'From timestamp');
      const to = int64(Math.floor(toMs), 'To timestamp');
      if (to <= from) throw new Error('Khoảng thời gian tải M1 không hợp lệ.');

      const run = async () => {
        await this.loadSymbolDetails(id);
        const store = this.bars.get(id) || new Map();
        const ranges = this.getMissingRanges(id, from, to);
        const total = ranges.reduce((sum, x) => sum + x[1] - x[0], 0);
        let done = 0, newBars = 0, requests = 0;
        for (const [start,end] of ranges) {
          let cursor = start;
          while (cursor < end) {
            const chunkEnd = Math.min(cursor + 24*60*60*1000, end);
            await this._historySlot();
            const rows = await this.requestBars(id, cursor, chunkEnd);
            for (const bar of rows) {
              if (bar.time >= cursor && bar.time <= chunkEnd) {
                if (!store.has(bar.time)) newBars++;
                store.set(bar.time, bar);
              }
            }
            const coverage = this.coverage.get(id) || [];
            coverage.push([cursor,chunkEnd]);
            this.coverage.set(id, coverage);
            done += chunkEnd - cursor;
            cursor = chunkEnd;
            requests++;
            onProgress({percent:total ? Math.min(100,Math.round(done/total*100)) : 100,requests,newBars});
          }
        }
        this.bars.set(id,store);
        const bars = [...store.values()].filter(b => b.time >= from && b.time <= to).sort((a,b) => a.time-b.time);
        this.emit('bars', {symbolId:id,bars});
        return {bars,count:bars.length,newBars,requests,coverage:this.coverage.get(id)||[]};
      };
      const task = this.historyQueue.then(run,run);
      this.historyQueue = task.catch(()=>{});
      return task;
    }
  }

  window.CTraderClient = CTraderClient;
  window.CTRADER_PAYLOAD_TYPES = PT;
})();
