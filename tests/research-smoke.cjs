const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(path.join(__dirname, '../assets/research-engine.js'), 'utf8'));
const bars = [];
let price = 2000;
const start = Date.UTC(2026, 0, 1);
for (let i = 0; i < 5000; i++) {
  const drift = Math.sin(i / 19) * 0.18 + Math.cos(i / 71) * 0.12;
  const open = price;
  const close = open + drift;
  const high = Math.max(open, close) + 0.08 + (i % 7) * 0.002;
  const low = Math.min(open, close) - 0.07 - (i % 5) * 0.002;
  bars.push({ time: start + i * 60_000, open, high, low, close, volume: 10, quality: 'ok' });
  price = close;
}
for (const module of ['gaps', 'liquidity', 'sessions', 'time', 'structure', 'daily-weekly', 'liquidity-mss']) {
  const result = ICTResearch.runCore(module, bars, { dayStartHour: 17, timeframeMinutes: 1 });
  if (result.status !== 'ok' || !result.metrics) throw new Error(`${module} failed.`);
}
const advanced = ICTResearch.advanced(bars);
if (!advanced.metrics) throw new Error('Advanced candidate engine failed.');
const forecast = ICTResearch.forecast(bars, { horizonMinutes: 60, timeframeMinutes: 1 });
if (!forecast.status) throw new Error('Forecast engine returned no status.');
console.log('Research engines smoke test: PASS (7 core modules, advanced candidates, analogue forecast)');
