# Product logic and complete feature catalogue

## Global contract
Every result stores symbol, broker/account, date range, New York timezone, timeframe, filters, definition version, sample size, numerator/denominator, missing-data coverage and contributing event IDs. Percentages without eligible denominator are not shown. Every chart/table can drill down to event records.

## Workspace overview
Show separate readiness states: credentials saved; OAuth consent granted; cTrader app authenticated; trading account authorized; symbols discovered; M1 history loaded; analytics computed; forecast validated. Never collapse these into one green "connected" state.

## Data Center
- Client ID, Client Secret, callback URI, Demo/Live selector; OAuth scope `accounts` only.
- After account discovery user selects one account; environment/account are part of every cache key.
- Dynamic symbol catalog comes from the selected authorized account, never a hardcoded allowlist.
- M1 is canonical source. Progressive loading computes uncovered time intervals and fetches only gaps; overlapping jobs are coalesced, bars deduplicated by UTC timestamp and sorted.
- Range ledger states: loaded, in-progress, failed, no-data-confirmed. API error/timeout is failed, not a no-candle period.
- Higher timeframes are aggregated from M1 with explicit UTC/calendar boundaries; broker candles may be compared but not mixed silently.
- OHLC remains RAM-only for the current backend session. Browser reload does not necessarily clear server RAM; server restart/worker replacement does. Multi-worker deployment needs volatile shared cache with TTL, not durable OHLC storage.
- cTrader history requests must be rate-limited; provider currently documents a lower historical request limit than non-historical requests. Pagination and request windows are provider-aware.

## Phase-1 Statistics (exactly seven)
1. **Gap Statistics — NDOG/NWOG only.** NDOG = prior completed trading-day close to current trading-day open; NWOG = prior completed trading-week close to current trading-week open. Record gap size/direction. Fill progress at 25/50/75/100% is measured from current open toward prior close. Default trigger wick-touch; close-confirmed is a separate filter. Record first fill time, NY session, elapsed market minutes and post-fill MFE/MAE at fixed horizons. FVG fill is excluded from Phase 1.
2. **Liquidity Statistics.** Levels: Asia H/L, PDH/PDL, PWH/PWL. `probe` = wick trades beyond a level by configured tick tolerance. `confirmed sweep` = probe followed by close back across the level. Close beyond without reclaim = breakout/acceptance, not sweep. Record penetration, first pool taken, reclaim latency, opposite-side sweep and subsequent MSS.
3. **Session Statistics.** Configurable New York windows (defaults documented in `SESSION_RULES.md`): Asia 19:00–00:00, London 02:00–05:00, NY AM 08:30–11:00, NY PM 13:30–16:00. These are research windows, not universal exchange hours. Calculate range, direction, high/low time, overlap, sweep/continuation/reversal; neutral requires a configured tolerance. DST handled by IANA zone.
4. **Time Statistics.** Distribution of sweep/MSS/reversal/expansion event times; time-to-event; daily/weekly final high/low formation time. Final extreme formation time is retrospective (after close); it must never be used in an as-of feature before the period ended.
5. **Market Structure Statistics.** Swing pivot uses configurable left/right bars. Pivot only becomes usable after right bars close; `known_at` is confirmation time, never the pivot bar. Bullish MSS = after qualifying downside sweep, close breaks latest eligible confirmed swing high; bearish inverse. Standalone break is BOS, not automatically MSS. Measure MFE/MAE from fixed reference (default break close), 1R/2R/3R and time-to-target. Same-candle TP+SL ambiguity is flagged or conservatively resolved.
6. **Daily & Weekly Statistics.** Direction (open-close with neutral tolerance), range, normalized range, high/low formation weekday/time, previous-period level interactions. Trading day/week boundaries are symbol/broker calendar-aware, not assumed UTC midnight.
7. **Liquidity → MSS Probability.** Conditional probability with explicit estimand, e.g. P(bullish MSS within 30 market minutes | confirmed Asia Low sweep, NY AM, symbol/regime). One eligible sweep episode per pool/day by default; fixed outcome window; numerator/denominator/Wilson interval; report clustering and missing coverage.

## Advanced ICT roadmap (after Phase 1)
FVG/imbalance lifecycle (not fill stats in Phase 1); EQH/EQL and liquidity pools; Judas Swing; session interaction; ADR 5/20/50, CBDR/IPDA, Quarterly Shift, PO3/AMD and bias; BOS/MSS refinements; SMT divergence; Premium/Discount/Equilibrium/Dealing Range; OB/Breaker/CISD/Silver Bullet/Three Drives and explicit entry-risk models. Each needs a written event definition and versioned parameters before it becomes a statistic.

## Hybrid Forecast
Two separate supervised targets, presented together:
- Event forecast: next mutually exclusive state within fixed horizon (bullish reversal sequence, bearish reversal sequence, continuation up/down, range/no qualifying event).
- Price forecast: conditional return quantiles/range for 15/30/60 minutes, target-touch probabilities and time-to-target, conditional on reference price and risk distance.
Modes: Live (only fully closed bars and confirmed events as-of now); Historical Scenario (freeze feature snapshot at chosen past timestamp, forecast, then reveal future bars only for scoring). Save forecast/model/version/features/training cutoff/scenarios/expiry and later outcome. Scenarios must be mutually exclusive and probabilities total 100%; include uncertain/no-event and invalidation. Model stack: unconditional/conditional baseline first, logistic regression, regime/volatility model, gradient boosting, survival model, quantile regression; sequence models only if walk-forward tests prove added value. Evaluation: Brier/log loss/calibration, precision/recall at fixed threshold, pinball loss/interval coverage for price ranges, year/symbol/session/regime consistency.

## Research safeguards
Chronological walk-forward, purge/embargo overlapping outcome horizons, no future bars in features, no pivot backdating, unconditional vs conditional probabilities separate, clustered uncertainty for repeated events, explicit intrabar ambiguity policy, sample size and intervals shown. Forecasts are research outputs, not trade instructions.
