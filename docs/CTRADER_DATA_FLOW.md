# cTrader Open API connection and market-data flow

## Authentication
1. User enters Client ID, Client Secret, callback URI and Demo/Live environment. Backend encrypts Secret and stores the record in a persistent database. Browser only sees a saved/not-saved flag.
2. Browser starts cTrader's authorization page with `scope=accounts` (read-only account/statistics permission). Callback URI must be registered exactly in the Open API application settings.
3. cTrader redirects with a short-lived authorization code. Backend exchanges it at `https://openapi.ctrader.com/apps/token` using the configured app credentials and redirect URI. Access token and refresh token are encrypted at rest.
4. Access token is normally about 30 days; refresh token is used to obtain a new access/refresh pair. Replace stored tokens atomically after refresh.
5. A connected Protobuf transport then sends `ProtoOAApplicationAuthReq` with Client ID/Secret, requests accounts using `ProtoOAGetAccountListByAccessTokenReq`, presents those accounts for explicit selection, and sends `ProtoOAAccountAuthReq` for the chosen `ctidTraderAccountId`.
6. Only after account authorization may the workspace report account-connected. Demo and Live use separate connections/configuration. Maintain heartbeat/reconnect in a long-lived worker, not in a short HTTP request handler.

## Market data
- Request all symbols visible to the authorized account; store provider symbol IDs, names, digits, tick size and trading metadata. Do not assume a symbol called XAUUSD or any fixed ticker exists.
- Historical M1 bars are requested through `ProtoOAGetTrendbarsReq` using account ID, symbol ID, M1 period, UTC Unix-millisecond `fromTimestamp`/`toTimestamp` and provider-supported range/count.
- cTrader trendbar prices use relative encoding: `low / 100000`; high/open/close are `(low + respective delta) / 100000`, rounded to that symbol's digits. Do not interpret raw protobuf integers as market prices.
- Historical request rate is documented as lower than non-historical requests (5 requests/second vs 50 per second per connection); use a token-bucket limiter and bounded pagination. Retry transient failures with backoff and persist the range state, not the raw bars.
- Official Python SDK is maintained by Spotware and uses Twisted callbacks. Keep its event loop/connection lifecycle in a dedicated service/worker boundary; don't start/stop the reactor for each FastAPI request.
- cTrader connection guidance recommends heartbeat messages every 10 seconds and at most one connection for each account environment (Demo and Live). Verify operational limits against current official docs before scaling.

## Incremental M1 cache planner
Given requested half-open interval `[start,end)`:
1. Read coverage ledger for `(workspace,environment,account,symbol,M1)`.
2. Subtract `loaded`, `no_data_confirmed` and currently `in_progress` intervals to produce missing subranges. Failed ranges remain retry candidates.
3. Merge adjacent uncovered intervals when within provider request limits; split oversized windows into provider-compliant pages.
4. Coalesce identical concurrent jobs; rate-limit history calls; mark every range in-progress before request.
5. Normalize each response to UTC, validate OHLC, dedupe by `(symbol_id,timestamp_utc)`, merge into RAM cache and mark coverage loaded. Mark valid empty responses as no_data_confirmed only when provider semantics confirm no bars; network/API error is failed.
6. A later larger date request fetches only uncovered subranges. A narrower/previous request uses cache. A backend restart clears OHLC RAM; the persistent database keeps credentials/tokens but not bars.
