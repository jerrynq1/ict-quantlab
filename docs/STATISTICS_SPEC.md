# Statistics output contract

Common rules: validate/deduplicate M1, apply filters before aggregation, store filter JSON and definition version, use eligible opportunities as denominators, expose numerator/denominator/interval and missing coverage. Event clustering is grouped by day or liquidity episode. Every aggregate drills down to source event IDs.

- Gap: valid gap count; threshold fill rate; time-to-fill distribution; session of first touch; post-fill excursion at 5/15/30/60 minutes.
- Liquidity: eligible pools; probe/sweep/breakout rates; penetration quantiles; reclaim latency; first pool; both-side-swept rate.
- Session: range quantiles; bullish/bearish/neutral mix; high/low timing; overlaps; sweep and continuation/reversal rates.
- Time: event count/density by NY local time; reversal delay; daily/weekly extreme timing.
- Structure: MSS per eligible sweep; direction; MFE/MAE; 1R/2R/3R-before-stop under explicit path policy; time-to-target.
- Daily/Weekly: direction mix; range distributions; extreme timing; PDH/PDL/PWH/PWL interactions.
- Liquidity→MSS: pool × sweep direction × MSS direction × delay × session × regime matrix with sample count and Wilson interval.

No FVG Fill Statistics in Phase 1.
