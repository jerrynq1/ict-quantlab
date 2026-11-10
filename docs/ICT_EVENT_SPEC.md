# ICT Event Engine contract

## Event schema
Immutable fields: event_id, event_type, definition_version, symbol_id, timeframe, event_time_utc (when occurred), known_at_utc (when knowable), reference_level, event_price, direction, session_id, source_candle_ids, parent_event_ids, parameters, quality_flags. Definition changes require new version and recomputation; never silently mutate old result sets.

## Sweep state machine
`LEVEL_ACTIVE -> PROBED -> RECLAIMED` (confirmed sweep) or `ACCEPTED_BEYOND` (breakout).
- High probe: high > level + tolerance; low probe: low < level - tolerance.
- High reclaim: close < level; low reclaim: close > level.
- Probe and reclaim in same candle may qualify by OHLC, but intrabar path is unknown; add `same_bar_path_unknown`.
- Repeated probes attach to one episode until resolution/reset; count episodes, not every tick-like re-touch.

## MSS state machine
- Pivot at bar i is eligible only after right_bars subsequent bars close; keep pivot_time and known_at distinct.
- Bullish MSS requires prior qualifying low sweep and candle close above latest eligible, unbroken swing high. Bearish inverse.
- Wick-only break is not MSS by default. Displacement/body filter is explicit optional parameter.
- No sweep context => BOS/structure break, not MSS.

## Gap lifecycle
Trading calendar defines prior close/current open. Create NDOG/NWOG only if difference exceeds tick size. Store bounds, direction, size, created_at and thresholds. Fill threshold is linear from open toward prior close; wick-touch default; if candle opens beyond threshold, fill timestamp is candle open, not invented intrabar time.
