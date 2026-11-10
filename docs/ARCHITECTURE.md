# Architecture and module contracts

## Separation of responsibilities

- `index.html`, `assets/styles.css`, `assets/app.js`: static user interface. No secrets and no server-side assumptions.
- `apps/api/app/routers`: HTTP boundaries, validation and authorization.
- `apps/api/app/services/ctrader.py`: OAuth token lifecycle and Spotware SDK transport.
- `apps/api/app/services/cache.py`: per-run/account/symbol M1 interval cache.
- `apps/api/app/engines`: pure deterministic research calculations.
- SQLite: encrypted settings/tokens, auth sessions, forecast audit trail, research notes. Raw OHLC remains transient.

## cTrader flow

1. Admin saves Client ID, Client Secret, environment and the exact backend callback URI.
2. Backend encrypts Client Secret and stores it. Public config only reports `secret_saved`.
3. Backend creates a cryptographically random OAuth state, stores only its SHA-256 hash, and sends the user to cTrader authorization.
4. Callback consumes the state exactly once, exchanges code server-side, encrypts access/refresh tokens, and redirects to the Pages URL.
5. Backend authenticates the app, obtains cTrader account IDs, then performs selected-account authorization.
6. Symbol discovery is dynamic. Historical M1 requests are fetched in bounded chunks.

Use HTTPS for the backend and OAuth callback. cTrader authorization codes are short-lived, so exchange immediately. Token refresh must preserve the latest refresh token returned by cTrader.

## Historical trendbars

A trendbar carries `low`, `deltaOpen`, `deltaClose`, `deltaHigh` and `utcTimestampInMinutes`. The adapter converts the relative deltas to absolute raw prices, then normalizes using the cTrader 1e5 price scale. Every decoded OHLC tuple is validated. If `high < max(open, close, low)` or `low > min(open, close, high)`, the candle is tagged `suspect_ohlc` and excluded from analytics, while raw high/low are preserved for inspection. Validate this conversion against the broker's symbol digits and representative chart prices before relying on the data for a particular instrument; price-basis differences must not be silently assumed.

Requests are chunked below the 10,000 trendbar count and rate-limited below 5 historical requests/second/connection. The requested range is recorded in cache only after a successful response.

## Cache contract

Cache key: `browser_run_id : account_id : symbol_id : M1`.

A cache entry stores bars keyed by UTC open timestamp and successful queried half-open windows `[start_ms, end_ms)`. Failed windows are not stored. Empty successful windows are stored to avoid repeatedly asking for a no-data interval. The client run ID changes on page load; therefore a reload begins with an empty logical cache. Higher timeframes are derived on demand and do not need independent source caches.

## Time contract

All bar timestamps are UTC milliseconds. Conversion to New York time happens at display/filter/session boundaries with IANA zone `America/New_York`, never a fixed UTC offset. Forex trading date defaults to 17:00 New York. Asia 20:00–00:00 is assigned to the same trading-date label as the following London and NY sessions. Session windows are workspace-configurable and validated for overlap.

## Event and statistical contract

Every detected event should carry a type, direction (where applicable), price/zone, event timestamp, bar timestamp, timeframe context and a mechanical definition. Pivot-based logic uses left/right confirmation bars; the event timestamp is the confirmation bar close, never backdated to the pivot.

Historical conditional statistics use an explicit denominator and disclose sample count. Wilson 95% intervals are used for binomial proportions. Right-censored observations are excluded from completed-outcome rates. Same-bar TP/SL collisions are ambiguous with OHLC and are not counted as clean target wins. Repeated events within a day/session are dependent observations; do not interpret naive confidence intervals as independence-adjusted inference.

## Forecast contract

The active forecast baseline uses historical analogues that have completed their target horizon before the forecast as-of time. No bar after the as-of timestamp enters the forecast features/training sample. Output scenarios are mutually exclusive and sum to 100%; price outputs are empirical quantiles. Insufficient analog count means no probability is emitted. Future outcomes are scored only after a full horizon is present, using bars whose open timestamp is greater than or equal to the forecast as-of timestamp.

Forecast audit rows survive OHLC cache reset. They contain the as-of time, symbol, model version, context hash, prediction payload and later outcome. This is distinct from permanent OHLC storage, which is intentionally disabled.
