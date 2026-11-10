# Browser-only architecture

## Runtime boundaries

- GitHub Pages serves only `index.html`, `assets/styles.css` and browser JavaScript.
- `assets/ctrader-client.js` opens a secure JSON WebSocket to cTrader on port 5036. It performs app auth, lists accounts, account auth, symbol discovery and M1 historical requests.
- `assets/research-engine.js` performs deterministic calculations on client-side OHLC arrays.
- `assets/app.js` connects the UI and browser storage.

There is no login service, FastAPI, backend API, database, Worker or server-side secret store in this personal-use build.

## cTrader request flow

1. User manually enters Client ID, Client Secret, Access Token, optional Account ID and Demo/Live/Auto.
2. Browser stores the fields in `localStorage`; this is plaintext and is suitable only for a trusted personal device.
3. Browser opens `wss://demo.ctraderapi.com:5036` or `wss://live.ctraderapi.com:5036` and sends JSON messages using `{clientMsgId, payloadType, payload}`.
4. Authenticate application (2100), list token-authorized accounts (2149), authorize selected account (2102), request symbol list (2114), request symbol metadata (2116), then retrieve M1 bars (2137).
5. User manually replaces expired access tokens. The app does not perform OAuth code exchange or refresh-token lifecycle in this browser-only edition.

## Historical M1 and cache

A trendbar contains `low`, `deltaOpen`, `deltaClose`, `deltaHigh` and `utcTimestampInMinutes`. Prices are reconstructed from `low` and deltas, divided by 100000 and rounded to symbol digits. Validate values against broker charts. The cache keeps a `Map` of candles and loaded time intervals per symbol in RAM. Range subtraction requests only missing intervals; OHLC is not persisted.

Historical requests use 24-hour chunks and are paced below five requests per second. A range is marked covered only after its request succeeds.

## Research integrity

- All timestamps remain UTC in memory; New York wall time is derived with `America/New_York` and its daylight-saving rules.
- Higher timeframes are aggregated from M1, and a bucket is accepted only with the expected number of constituent bars.
- Confirmed pivots require right-side bars; their confirmation timestamp is distinct from the pivot candle.
- Incomplete forward horizons are reported as censored and should not be treated as a negative outcome.
- Advanced concepts that are not implemented in the current JavaScript engine must remain labelled as roadmap/heuristic, never as validated signal probabilities.

## Browser persistence and threat model

Credentials, forecast audit records, research notes and session profiles are stored locally by origin. They survive reload but are readable to scripts running in that origin. An XSS vulnerability or browser extension can expose them. Do not share credentials, browser profiles or source commits. For multi-user or public use, move credentials to a proper backend/Worker with per-user OAuth and server-side secret handling.
