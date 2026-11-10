const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const assert = (condition, message) => { if (!condition) throw new Error(message); };

globalThis.crypto ||= webcrypto;
globalThis.window = globalThis;
globalThis.CustomEvent ||= class CustomEvent extends Event {
  constructor(type, init = {}) { super(type); this.detail = init.detail; }
};

class FakeWebSocket {
  static OPEN = 1;
  static instances = [];
  constructor(url) {
    this.url = url; this.readyState = 0; this.sent = [];
    FakeWebSocket.instances.push(this);
    setTimeout(() => { this.readyState = FakeWebSocket.OPEN; this.onopen?.(); }, 0);
  }
  send(raw) {
    const request = JSON.parse(raw); this.sent.push(request);
    let payloadType; let payload = {};
    switch (request.payloadType) {
      case 2100: payloadType = 2101; break;
      case 2149:
        payloadType = 2150;
        payload = { ctidTraderAccount: [{ ctidTraderAccountId: '123456', isLive: false, traderLogin: 111, brokerTitleShort: 'DemoBroker' }] };
        break;
      case 2102: payloadType = 2103; payload = { ctidTraderAccountId: request.payload.ctidTraderAccountId }; break;
      case 2114:
        payloadType = 2115;
        payload = { symbol: [{ symbolId: '1', symbolName: 'EURUSD', enabled: true }] };
        break;
      case 2116:
        payloadType = 2117;
        payload = { symbol: [{ symbolId: '1', digits: 5, symbolName: 'EURUSD' }] };
        break;
      case 2137:
        payloadType = 2138;
        payload = { trendbar: [{ utcTimestampInMinutes: Math.floor(Date.UTC(2026, 0, 1) / 60000), low: 100000, deltaOpen: 100, deltaClose: 200, deltaHigh: 300, volume: 10 }] };
        break;
      case 9999:
        payloadType = 50; payload = { errorCode: 'INVALID_REQUEST', description: 'Simulated request error' }; break;
      case 51: return;
      default: throw new Error(`Unexpected request type ${request.payloadType}`);
    }
    setTimeout(() => this.onmessage?.({ data: JSON.stringify({ clientMsgId: request.clientMsgId, payloadType, payload }) }), 0);
  }
  close(code=1000, reason='closed') { this.readyState = 3; this.onclose?.({ code, reason }); }
}
globalThis.WebSocket = FakeWebSocket;

vm.runInThisContext(fs.readFileSync(path.join(__dirname, '../assets/ctrader-client.js'), 'utf8'));

(async () => {
  const client = new CTraderClient();
  const connected = await client.connect({ clientId: 'test-id', clientSecret: 'test-secret', accessToken: 'test-token', accountId: '', environment: 'auto' });
  assert(FakeWebSocket.instances.length === 2, 'Auto should switch socket when selected account belongs to the other environment.');
  assert(FakeWebSocket.instances[0].url.includes('live.ctraderapi.com'), 'Auto must begin on LIVE like the working reference client.');
  assert(FakeWebSocket.instances[1].url.includes('demo.ctraderapi.com'), 'Demo account must switch to DEMO host.');
  assert(connected.environment === 'demo', 'Auto should select the demo account in the fixture.');
  assert(client.authorized && connected.symbols[0].name === 'EURUSD', 'Account and symbol authorization should succeed.');

  const allSent = FakeWebSocket.instances.flatMap(ws => ws.sent);
  assert(allSent.filter(x => x.payloadType === 2100).length === 2, 'ApplicationAuth must be repeated after switching hosts.');
  const accountAuth = allSent.find(x => x.payloadType === 2102);
  assert(typeof accountAuth.payload.ctidTraderAccountId === 'number', 'Account ID must be sent as a JSON integer.');
  const symbolList = allSent.find(x => x.payloadType === 2114);
  assert(typeof symbolList.payload.ctidTraderAccountId === 'number', 'SymbolsList account ID must be a JSON integer.');

  const from = Date.UTC(2026, 0, 1);
  const first = await client.loadHistory('1', from, from + 60_000);
  assert(first.count === 1 && first.bars[0].open === 1.001 && first.bars[0].high === 1.003 && first.bars[0].close === 1.002, 'Trendbar relative-price decoding should be correct.');
  const historyReq = FakeWebSocket.instances[1].sent.find(x => x.payloadType === 2137);
  assert(typeof historyReq.payload.ctidTraderAccountId === 'number' && typeof historyReq.payload.symbolId === 'number', 'Historical account/symbol IDs must be sent as JSON integers.');
  assert(typeof historyReq.payload.fromTimestamp === 'number' && typeof historyReq.payload.toTimestamp === 'number', 'Trendbar timestamps must be sent in milliseconds as JSON numbers.');
  const second = await client.loadHistory('1', from, from + 60_000);
  assert(second.requests === 0 && second.newBars === 0, 'A repeated covered range must not trigger another request.');

  let protocolError = '';
  try { await client.request(9999, {}, 10000, 2000); } catch (error) { protocolError = error.message; }
  assert(protocolError.includes('INVALID_REQUEST') && protocolError.includes('Simulated request error'), 'Common protocol ErrorRes (50) must be surfaced with its description.');

  client.disconnect();
  console.log('cTrader browser transport smoke test: PASS (auto host selection, host switch, auth sequence, numeric IDs, M1 decode/cache, protocol errors)');
})().catch(error => { console.error(error); process.exitCode = 1; });
