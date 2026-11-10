# Research methodology and operational definitions

These definitions are explicit computational proxies. ICT terminology can differ between educators, instruments and sessions; calibrate and compare definitions before drawing conclusions.

## Core statistics

### NDOG / NWOG

- NDOG: current Forex trading-day first observed open compared with previous trading-day last observed close.
- NWOG: current trading-week first observed open compared with previous trading-week last observed close.
- Direction is up/down by open minus previous close. Fill progress is measured from the near boundary toward the far boundary, with first crossing times for 25%, 50%, 75% and 100%.
- A gap is only created when the previous trading period is fully covered and the new period is not left-censored. An incomplete prior day/week is not used to manufacture an NDOG/NWOG reference.
- A gap whose observation horizon has not ended is right-censored; an internal missing bar before the outcome is separately marked data-incomplete. Both are excluded from the corresponding completed fill-rate denominator. A confirmed 100% fill is terminal even if the period later ends early.
- Post-fill reaction is measured from the fill level at 15/30/60-minute horizons. A horizon is scored only when every expected future bar exists; a partial horizon is censored and an internal hole is separately data-incomplete. If the selected timeframe cannot resolve the horizon, it is reported as unavailable rather than stretched to a longer horizon.

### Liquidity levels

- Reference levels: Asia high/low, prior day high/low and prior week high/low.
- First interaction per level/trading day is classified as probe (exact touch), wick sweep (opens on the inside, wick penetrates and same-bar close returns inside), opening-gap reclaim (opens beyond, closes back inside), or breakout (does not return inside on the interaction bar). A later close back through a breakout level is recorded as a later reclaim.
- An opening gap is never relabelled a wick sweep. One event per level/day avoids counting every candle that remains beyond a level as another event.

### Session statistics

- Sessions use editable New York-time windows. Direction compares session close with session open.
- Continuation/reversal compares consecutive labelled sessions within the same trading-date group.
- High/low formation time refers to the timestamp of the bar containing the extreme; OHLC does not reveal the exact tick within that bar.

### Time statistics

- Daily high/low formation distribution counts the source bar's New York hour.
- Reversal candidates use a one-bar close-through of the previous candle's opposite extreme; this is a compact mechanical candidate, not a universal ICT reversal definition.

### Market structure

- Swing pivot default: unique high/low over two bars left and two bars right.
- A pivot is available only on the right-confirmation bar. BOS/MSS requires a continuous adjacent bar sequence, the break candle must open on the pre-break side of the latest confirmed opposing swing, and its close must cross that level. A weekend/session opening gap is not treated as an observed intrabar cross. Event time is the break-confirmation candle close.
- MSS means direction change relative to the prior detected structure bias; otherwise a break is BOS.
- MFE/MAE and target attainment are evaluated on exactly the next configured number of continuous bars. Incomplete future horizons are right-censored; internal holes after a fully elapsed horizon are separately excluded as data-incomplete. Risk `R` is the distance to the opposite latest confirmed swing. If target and invalidation are touched in the same OHLC bar, ordering is unknown and the signal is marked ambiguous / excluded from clean target-rate denominator. If the configured minute horizon is shorter than one selected bar, BOS/MSS events remain visible but forward outcome evaluation is explicitly unavailable.

### Daily & weekly

- Summary ranges and ADR reference samples exclude incomplete first/last daily or weekly windows. Partial periods remain available in raw records with completeness/censoring flags.
- Daily/weekly direction compares period close to period open.

### Liquidity → MSS

- Denominator: detected liquidity sweeps with every expected bar in the requested response horizon available and usable.
- Success: opposite-direction MSS confirmed within 5/15/30/60 minutes of the sweep.
- Each horizon has its own sample count. Horizons that extend beyond the loaded data are right-censored; elapsed horizons with internal bar gaps are data-incomplete. Neither is scored as a negative. Confidence intervals remain descriptive because events can cluster.

## Advanced ICT candidates

- FVG: three-candle non-overlap between first candle extreme and third candle extreme; future mitigation status is retrospective outcome metadata.
- EQH/EQL: two confirmed pivots of the same side within 0.10 ATR by default.
- Order block: last opposite candle in the six bars preceding a confirmed BOS/MSS; full candle range is the zone. Mitigation/breaker status is retrospective.
- Premium/discount and IPDA-style ranges: midpoint and range of observed rolling complete daily ranges; descriptive context only.
- CBDR: New York calendar-day 14:00–20:00 window. It is deliberately not grouped on the 17:00 Forex trading-day boundary.
- Silver Bullet: an FVG printed in one of the configured matching time windows (03:00–04:00, 10:00–11:00, 14:00–15:00 New York). Window match alone is not a complete setup.
- PO3/AMD: Asia range, first raid/reclaim, and subsequent opposite-side expansion candidate.
- Judas Swing: opening-hour raid of Asia high/low, close back inside, followed by at least 0.5 Asia-range opposite excursion within a bounded 120-bar evaluation window. Labelled candidate only.
- CISD / Three Drives: explicit body-cross / progressive swing heuristics, candidate labels only.
- SMT: compare two symbols at the same UTC bucket after aggregating both to the selected timeframe; divergence is a relative swing candidate.
- Quarterly profile/shift: profile of observed quarter and close vs previous-quarter extreme. First/last observed quarters may be partial.
- Confluence: additive evidence score (sweep 2, aligned MSS 3, aligned FVG 1, aligned OB 1, aligned EQH/EQL 1), max 8. The score is not a probability and does not imply a profitable trade.

## Forecast

- Current baseline: historical analogue matching on session, volatility regime, trend, weekday and range-position context.
- Exclusive outcomes: bullish expansion (> +0.5 ATR horizon return), bearish expansion (< -0.5 ATR), consolidation (inside ±0.5 ATR). Laplace smoothing prevents a hard zero/one from a finite sample.
- Price distribution: empirical quantiles of analogue horizon returns; expected high/low use analogue MFE/MAE.
- 1R/2R/3R in the baseline are ATR proxies, not a trade-specific stop-distance model.
- Historical replay uses only data available by as-of. It is not permitted to use future bars to construct features or select analogues.
- Forecast evaluation waits until the entire expected future horizon is available with continuous timestamp coverage. A gap in the future path is not scored as a failed forecast. The UI exposes multi-class precision/recall/support, confusion matrix, Brier score, top-class reliability bins and top-scenario accuracy.
- Forecast minute horizons must be an exact multiple of the selected chart timeframe. The UI disables incompatible choices and the API rejects them instead of silently rounding up.
- Neural models, boosted trees, HMM, GARCH and survival analysis are candidate extensions, not active trained models in this build.
