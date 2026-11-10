# Hybrid Forecast Engine

Event task: one mutually exclusive next-state label per as-of timestamp/horizon. Price task: conditional return quantiles/distribution and target-touch outcome for 15/30/60 minutes with explicit reference and target/stop rule.

Features are timestamped: recent M1 returns/range/realized volatility; session/day/week context; range position; confirmed liquidity levels/sweeps; confirmed structure; gap lifecycle; regime estimate. Feature `known_at_utc` must be <= forecast `as_of_utc`.

Model ladder: unconditional frequency baseline; conditional-frequency baseline; logistic regression; regime/volatility models; gradient boosting; survival for time-to-event; quantile regression for price bands; sequence models only after proven OOS gains.

Display sample size, training cutoff, validation interval, calibration, mutually exclusive probabilities summing to 1, and invalidation. Shrink thin conditional estimates to a declared broader prior or report insufficient evidence. No prediction without OOS calibration.

Evaluation: chronological walk-forward; purge/embargo outcomes crossing fold boundaries; Brier/log loss/calibration for event labels; pinball loss/coverage for quantiles; stability across year/symbol/session/regime. Store every historical replay and score it when future bars become available.
