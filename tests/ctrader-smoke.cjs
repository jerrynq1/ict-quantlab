const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

globalThis.crypto ||= webcrypto;
globalThis.window = globalThis;
globalThis.CustomEvent ||= class CustomEvent extends Event {
  constructor(type, init = {}) { super(type); this.detail = init.detail; }
};

class FakeWebSocket {
  static OPEN = 1;
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    setTimeout(() => { this.readyState = FakeWebSocket.OPEN; this.onopen?.(); }, 0);
  }
  send(raw) {
    const request = JSON.parse(raw);
    let payloadType;
    let payload = {};
    switch (request.payloadType) {
      case 2100: payloadType = 2101; break;
      case 2149:
        payloadType = 2150;
        payload = { ctidTraderAccount: [{ ctidTraderAccountId: '123456', isLive: false, traderLogin: 111, brokerTitleShort: 'DemoBroker' }] };
        break;
      case 2102: payloadType = 2103; break;
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
      case 51: return;
      default: throw new Error(`Unexpected request type ${request.payloadType}`);
    }
    setTimeout(() => this.onmessage?.({ data: JSON.stringify({ clientMsgId: request.clientMsgId, payloadType, payload }) }), 0);
  }
  close() { this.readyState = 3; this.onclose?.({ code: 1000, reason: 'closed' }); }
}
globalThis.WebSocket = FakeWebSocket;

vm.runInThisContext(fs.readFileSync(path.join(__dirname, '../assets/ctrader-client.js'), 'utf8'));

(async () => {
  const client = new CTraderClient();
  const connected = await client.connect({ clientId: 'test-id', clientSecret: 'test-secret', accessToken: 'test-token', accountId: '', environment: 'auto' });
  assert(connected.environment === 'demo', 'Auto should select the demo account in the fixture.');
  assert(client.authorized && connected.symbols[0].name === 'EURUSD', 'Account and symbol authorization should succeed.');
  const from = Date.UTC(2026, 0, 1);
  const first = await client.loadHistory('1', from, from + 60_000);
  assert(first.count === 1 && first.bars[0].open === 1.001 && first.bars[0].high === 1.003 && first.bars[0].close === 1.002, 'Trendbar relative-price decoding should be correct.');
  const second = await client.loadHistory('1', from, from + 60_000);
  assert(second.requests === 0 && second.newBars === 0, 'A repeated covered range must not trigger another request.');
  client.disconnect();
  console.log('cTrader browser transport smoke test: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });

function assert(condition, message) { if (!condition) throw new Error(message); }
