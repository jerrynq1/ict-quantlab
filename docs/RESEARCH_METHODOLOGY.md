# Research methodology and implementation status

## Core research modules

The UI exposes seven Phase 1 modules: NDOG/NWOG gap behaviour; liquidity levels and sweeps; session behaviour; time-of-day/high-low timing; BOS/MSS structure; daily/weekly statistics; and liquidity-to-MSS conditional response. They operate on downloaded M1 data, with higher timeframes aggregated from M1.

Each result should expose the event definition, sample count and observation window. Session and higher-timeframe completeness matter: partial windows must not be silently treated as complete samples. A result built from simple deterministic rules is a mechanical proxy, not an authoritative interpretation of ICT terminology.

## Avoiding look-ahead

A pivot is not available until the required right-side bars have closed. The pivot's own candle time and the later confirmation time must remain separate. Forecast replay must slice data at the requested as-of point. An outcome is evaluable only after a full continuous forward horizon is available; otherwise it is pending/right-censored.

When one OHLC candle spans both a hypothetical stop and target, intrabar order is unknowable from OHLC alone. Use a conservative assumption or finer data; do not award the target by default.

## Forecast status

The current browser implementation is an empirical historical-analogue baseline. It compares recent context windows with past windows and groups their forward returns into bullish expansion, bearish expansion and consolidation classes. Laplace smoothing prevents zero probabilities, but smoothing does not establish calibration or a tradable edge. The minimum 30 analogue threshold is a guardrail, not statistical proof.

Before relying on any forecast, evaluate it with rolling/walk-forward out-of-sample periods, Brier score and class-wise precision/recall; compare it with a trivial base-rate benchmark; inspect calibration and performance by symbol/session/regime; account for overlapping samples and event clustering. HMM/Markov switching, GARCH, tree ensembles, survival analysis, Hawkes processes and neural sequence models are research candidates only until separately implemented and validated.

## Current implementation limits

The current client-side Advanced engine computes FVG and EQH/EQL candidates plus ADR context. SMT compares aligned M1 timestamps. Other advanced labels visible in the roadmap are not all full implementations. The live forecast mode currently refreshes the latest historical M1 window by polling; it does not yet subscribe to live trendbar events. Core event logic and forecasts should be tested against known chart intervals before making claims about accuracy.
