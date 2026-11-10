# Implementation roadmap and acceptance gates

## Foundation in this source
- [x] Detailed seven-module Phase-1 logic and advanced ICT roadmap
- [x] Event contract, sweep/MSS/gap rules and forecast safety rules
- [x] Dark Quant Terminal, private login, cTrader credential/settings UI
- [x] Encrypted persistent credential/token store; OAuth code exchange/refresh
- [x] NY timezone helper and volatile OHLC cache contract

## Engineering stages still to implement
1. cTrader Protobuf transport: app auth, account list, account selection/auth, heartbeat/reconnect.
2. Symbol catalog from authorized account; M1 historical fetch, provider pagination, rate limiter and coverage planner.
3. Event detectors with golden fixtures and no-lookahead tests.
4. Seven statistics calculations, historical drilldown and comparison.
5. Baseline forecast and chronological replay; then ML models only if they beat baseline OOS.
6. Production deployment, persistent volume, monitoring, account isolation and security review.

Acceptance: secret never returned to browser; reload shows saved status; blank secret keeps existing one; wrong encryption key fails closed; OAuth token state is not called account-connected; NY DST tests pass; cache de-duplicates and never persists bars; MSS cannot use unconfirmed pivots; forecast cannot read bars later than as-of timestamp.
