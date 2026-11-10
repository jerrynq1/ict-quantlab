from __future__ import annotations
from collections import Counter
from math import sqrt
from statistics import mean, median
from app.engines.stats_engine import _usable, structure_events, _ci95
from app.engines.time_utils import to_ny, session_name, infer_bar_duration_ms

MODEL_VERSION = "ictql-hybrid-0.2-analog"
MIN_ANALOGS = 30


def _true_ranges(bars):
    vals=[]; prev=None
    for bar in bars:
        tr=bar["high"]-bar["low"]
        if prev is not None: tr=max(tr,abs(bar["high"]-prev),abs(bar["low"]-prev))
        vals.append(tr); prev=bar["close"]
    return vals


def _features_at(bars, idx):
    bar=bars[idx]; prev=bars[max(0,idx-30):idx]
    ranges=_true_ranges(bars[max(0,idx-60):idx+1])
    current_atr=mean(ranges[-14:]) if ranges else max(bar["high"]-bar["low"],1e-9)
    previous_ranges=[]
    source=_true_ranges(bars[max(0,idx-240):idx])
    for end in range(20,len(source)+1,10):
        previous_ranges.append(mean(source[max(0,end-14):end]))
    if previous_ranges:
        vol_rank=sum(x<=current_atr for x in previous_ranges)/len(previous_ranges)
    else:
        vol_rank=0.5
    trend=(bar["close"]-prev[0]["open"]) if prev else 0
    direction="up" if trend>0 else "down" if trend<0 else "flat"
    regime="high" if vol_rank>=0.8 else "low" if vol_rank<=0.2 else "normal"
    dt=to_ny(bar["time"])
    # Range position is calculated only from bars already closed at this index.
    recent=bars[max(0,idx-60):idx+1]
    hi=max(x["high"] for x in recent); lo=min(x["low"] for x in recent)
    position=(bar["close"]-lo)/(hi-lo) if hi>lo else 0.5
    return {"session":session_name(bar["time"]),"hour_bucket":dt.hour//2,
            "weekday":dt.weekday(),"trend":direction,"volatility_regime":regime,
            "volatility_rank":vol_rank,"range_position":position,
            "atr":max(current_atr,1e-9),"price":bar["close"],"time":bar["time"]}


def _similarity_key(f):
    return (f["session"],f["volatility_regime"],f["trend"],f["hour_bucket"])


def _historical_analogs(bars, asof_ms, horizon_bars=60):
    # A training label is admitted only if its entire forward horizon ends strictly
    # before the forecast timestamp. Feature extraction uses the past at sample i.
    duration=infer_bar_duration_ms(bars)
    stop=next((i for i,x in enumerate(bars) if x["time"]+duration>=asof_ms),len(bars))
    train_end=max(0,stop-horizon_bars)
    samples=[]
    structure=structure_events(bars[:stop])
    struct_by_bar={}
    for event in structure:
        struct_by_bar.setdefault(event["bar_time"],[]).append(event)
    for i in range(60,train_end):
        target_idx=i+horizon_bars
        if target_idx>=stop: break
        feat=_features_at(bars,i)
        future=bars[i+1:target_idx+1]
        if len(future)<horizon_bars: continue
        if any(int(future[j]["time"])-int(future[j-1]["time"]) != duration for j in range(1,len(future))) or int(future[0]["time"])-int(bars[i]["time"]) != duration:
            continue
        atr=feat["atr"]
        ret=(future[-1]["close"]-bars[i]["close"])/atr
        max_up=(max(x["high"] for x in future)-bars[i]["close"])/atr
        max_down=(bars[i]["close"]-min(x["low"] for x in future))/atr
        recent=bars[max(0,i-30):i]
        if not recent: continue
        high_ref=max(x["high"] for x in recent); low_ref=min(x["low"] for x in recent)
        sweep_high=any(x["high"]>high_ref and x["close"]<high_ref for x in future)
        sweep_low=any(x["low"]<low_ref and x["close"]>low_ref for x in future)
        future_events=[event for bar in future for event in struct_by_bar.get(bar["time"],[])]
        bullish_mss=any(e["type"]=="MSS" and e["direction"]=="bullish" for e in future_events)
        bearish_mss=any(e["type"]=="MSS" and e["direction"]=="bearish" for e in future_events)
        def time_to(predicate):
            return next((j+1 for j,x in enumerate(future) if predicate(x)),None)
        samples.append({"key":_similarity_key(feat),"features":feat,"return_atr":ret,
                        "mfe_atr":max_up,"mae_atr":max_down,
                        "sweep_high":sweep_high,"sweep_low":sweep_low,
                        "bullish_mss":bullish_mss,"bearish_mss":bearish_mss,
                        "bars_to_up_1r":time_to(lambda x:x["high"]>=bars[i]["close"]+atr),
                        "bars_to_down_1r":time_to(lambda x:x["low"]<=bars[i]["close"]-atr)})
    return samples


def _wilson(success,n):
    return _ci95(success,n)


def generate_forecast(bars, asof_ms=None, horizon_bars=60, horizon_minutes=None, min_analogs=MIN_ANALOGS):
    b=_usable(bars)
    if len(b)<120:
        return {"status":"insufficient_data","message":"Cần tối thiểu 120 nến sạch để tạo baseline; hiện chưa đủ dữ liệu.",
                "sample_size":len(b),"model_version":MODEL_VERSION}
    duration=infer_bar_duration_ms(b)
    asof_ms=int(asof_ms or (b[-1]["time"]+duration))
    # Only completed candles are visible at the forecast timestamp; cTrader's bar timestamp marks the candle open.
    idx=max((i for i,x in enumerate(b) if x["time"]+duration<=asof_ms),default=-1)
    if idx<60:
        return {"status":"insufficient_data","message":"Không đủ lookback trước thời điểm dự báo.","sample_size":idx+1,"model_version":MODEL_VERSION}
    hist=b[:idx+1]
    feat=_features_at(hist,len(hist)-1)
    samples=_historical_analogs(b,asof_ms,horizon_bars)
    key=_similarity_key(feat)
    pool=[s for s in samples if s["key"]==key]; relaxation="exact_context"
    if len(pool)<min_analogs:
        pool=[s for s in samples if s["key"][:2]==key[:2]]; relaxation="same_session_and_regime"
    if len(pool)<min_analogs:
        pool=[s for s in samples if s["key"][1]==feat["volatility_regime"]]; relaxation="same_volatility_regime"
    if len(pool)<min_analogs:
        return {"status":"insufficient_samples","message":f"Chỉ có {len(pool)} historical analogs; yêu cầu tối thiểu {min_analogs}. Không công bố xác suất dự báo.",
                "sample_size":len(pool),"model_version":MODEL_VERSION,
                "context":{k:v for k,v in feat.items() if k not in {"time","features"}}}
    n=len(pool)
    ups=sum(s["return_atr"]>0.5 for s in pool)
    downs=sum(s["return_atr"]<-0.5 for s in pool)
    cons=n-ups-downs
    denom=n+3
    scenarios=[
        {"name":"Bullish expansion","probability":(ups+1)/denom,"successes":ups,"sample":n,
         "ci95":_wilson(ups,n),"definition":"Horizon close return > +0.5 ATR"},
        {"name":"Bearish expansion","probability":(downs+1)/denom,"successes":downs,"sample":n,
         "ci95":_wilson(downs,n),"definition":"Horizon close return < -0.5 ATR"},
        {"name":"Consolidation","probability":(cons+1)/denom,"successes":cons,"sample":n,
         "ci95":_wilson(cons,n),"definition":"Horizon close return within ±0.5 ATR"},
    ]
    def quantile(values,p):
        values=sorted(values)
        if not values: return None
        return values[min(len(values)-1,max(0,round((len(values)-1)*p)))]
    returns=[s["return_atr"] for s in pool]
    mfe=[s["mfe_atr"] for s in pool]; mae=[s["mae_atr"] for s in pool]
    price=feat["price"]; atr=feat["atr"]
    event_high=sum(s["sweep_high"] for s in pool)
    event_low=sum(s["sweep_low"] for s in pool)
    bullish_mss=sum(s["bullish_mss"] for s in pool)
    bearish_mss=sum(s["bearish_mss"] for s in pool)
    attainment={}
    for r in (1,2,3):
        up=sum(s["mfe_atr"]>=r for s in pool)
        down=sum(s["mae_atr"]>=r for s in pool)
        attainment[f"bullish_{r}r"]={"success":up,"sample":n,"probability":up/n,"ci95":_wilson(up,n)}
        attainment[f"bearish_{r}r"]={"success":down,"sample":n,"probability":down/n,"ci95":_wilson(down,n)}
    up_1r=sum(x["bars_to_up_1r"] is not None for x in pool)
    down_1r=sum(x["bars_to_down_1r"] is not None for x in pool)
    time_up=[x["bars_to_up_1r"] for x in pool if x["bars_to_up_1r"] is not None]
    time_down=[x["bars_to_down_1r"] for x in pool if x["bars_to_down_1r"] is not None]
    actual_horizon_minutes=horizon_minutes or int(round(horizon_bars*duration/60_000))
    return {
        "status":"ok","model_version":MODEL_VERSION,"as_of":to_ny(asof_ms).isoformat(),
        "sample_size":n,"analogs_used":relaxation,"horizon_minutes":actual_horizon_minutes,
        "horizon_bars":horizon_bars,
        "context":{"session":feat["session"],"trend":feat["trend"],
                   "volatility_regime":feat["volatility_regime"],"volatility_rank":feat["volatility_rank"],
                   "range_position":feat["range_position"],"atr":atr,"last_price":price},
        "scenarios":scenarios,
        "price_range":{"p10":price+quantile(returns,.10)*atr,"p25":price+quantile(returns,.25)*atr,
                        "p50":price+quantile(returns,.50)*atr,"p75":price+quantile(returns,.75)*atr,
                        "p90":price+quantile(returns,.90)*atr,
                        "expected_high_p50":price+quantile(mfe,.50)*atr,
                        "expected_low_p50":price-quantile(mae,.50)*atr,
                        "lower_atr":quantile(returns,.10),"median_atr":quantile(returns,.50),
                        "upper_atr":quantile(returns,.90),"mfe_p50_atr":quantile(mfe,.50),
                        "mae_p50_atr":quantile(mae,.50)},
        "event_forecast":{"buy_side_sweep_probability":(event_high+1)/(n+2),
                           "buy_side_sweep_ci95":_wilson(event_high,n),
                           "sell_side_sweep_probability":(event_low+1)/(n+2),
                           "sell_side_sweep_ci95":_wilson(event_low,n),
                           "bullish_mss_probability":(bullish_mss+1)/(n+2),
                           "bullish_mss_ci95":_wilson(bullish_mss,n),
                           "bearish_mss_probability":(bearish_mss+1)/(n+2),
                           "bearish_mss_ci95":_wilson(bearish_mss,n)},
        "target_attainment":{"unit":"ATR as R proxy (not a trade-specific stop model)",
                             "levels":attainment,
                             "bullish_1r_probability":up_1r/n,"bearish_1r_probability":down_1r/n,
                             "bullish_1r_ci95":_wilson(up_1r,n),"bearish_1r_ci95":_wilson(down_1r,n),
                             "median_bars_to_bullish_1r":median(time_up) if time_up else None,
                             "median_bars_to_bearish_1r":median(time_down) if time_down else None},
        "risk_note":"Empirical historical-analogue baseline with Laplace-smoothed exclusive scenarios. These are not production-calibrated probabilities; use walk-forward tests and instrument/session-specific validation before decision-making.",
        "limitations":["MFE/MAE and event labels use OHLC bars; intrabar event ordering is unknown.",
                       "The baseline uses a compact context key rather than a trained neural or boosted model.",
                       "Confidence intervals describe binomial sampling uncertainty and do not remove overlapping-sample dependence."],
    }


def forecast_metrics(runs):
    """Evaluate stored outcomes with proper scoring and transparent class diagnostics.

    Reliability bins describe top-class confidence only; overlapping forecasts are
    dependent and this report does not pretend to be a de-clustered inference test.
    """
    evaluated = [x for x in runs if x.get("outcome")]
    if not evaluated:
        return {"evaluated_runs": 0, "status": "no_evaluated_forecasts"}

    names = ["Bullish expansion", "Bearish expansion", "Consolidation"]
    brier_values = []
    accuracy = []
    by_horizon = Counter()
    brier_by_horizon = {}
    outcomes = Counter()
    confusion = {actual: {predicted: 0 for predicted in names} for actual in names}
    class_counts = {name: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for name in names}
    reliability = {
        "<0.40": {"count": 0, "confidence_sum": 0.0, "correct": 0},
        "0.40-0.55": {"count": 0, "confidence_sum": 0.0, "correct": 0},
        "0.55-0.70": {"count": 0, "confidence_sum": 0.0, "correct": 0},
        ">=0.70": {"count": 0, "confidence_sum": 0.0, "correct": 0},
    }

    valid_count = 0
    for run in evaluated:
        probs = run.get("payload", {}).get("scenarios", [])
        outcome = run.get("outcome", {}).get("scenario")
        if not probs or outcome not in names:
            continue
        p = {x.get("name"): float(x.get("probability", 0.0)) for x in probs if x.get("name") in names}
        if not p or any(not 0.0 <= value <= 1.0 for value in p.values()):
            continue
        # Require all mutually-exclusive classes so Brier is comparable across runs.
        p = {name: p.get(name, 0.0) for name in names}
        predicted = max(names, key=lambda name: p[name])
        score = sum((p[name] - (1.0 if name == outcome else 0.0)) ** 2 for name in names)
        brier_values.append(score)
        accuracy.append(predicted == outcome)
        valid_count += 1
        horizon = str(run.get("payload", {}).get("horizon_minutes", "unknown"))
        by_horizon[horizon] += 1
        brier_by_horizon.setdefault(horizon, []).append(score)
        outcomes[outcome] += 1
        confusion[outcome][predicted] += 1
        for name in names:
            class_counts[name]["support"] += int(outcome == name)
            if predicted == name and outcome == name:
                class_counts[name]["tp"] += 1
            elif predicted == name and outcome != name:
                class_counts[name]["fp"] += 1
            elif predicted != name and outcome == name:
                class_counts[name]["fn"] += 1
        confidence = p[predicted]
        bucket = "<0.40" if confidence < 0.40 else "0.40-0.55" if confidence < 0.55 else "0.55-0.70" if confidence < 0.70 else ">=0.70"
        reliability[bucket]["count"] += 1
        reliability[bucket]["confidence_sum"] += confidence
        reliability[bucket]["correct"] += int(predicted == outcome)

    precision_recall = {}
    for name, counts in class_counts.items():
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision_recall[name] = {
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "support": counts["support"], "true_positive": tp,
            "false_positive": fp, "false_negative": fn,
        }
    reliability_rows = []
    for label, bucket in reliability.items():
        count = bucket["count"]
        reliability_rows.append({
            "confidence_bin": label, "count": count,
            "mean_confidence": bucket["confidence_sum"] / count if count else None,
            "accuracy": bucket["correct"] / count if count else None,
        })
    return {
        "status": "ok" if valid_count else "no_valid_evaluations",
        "evaluated_runs": valid_count,
        "brier_score": mean(brier_values) if brier_values else None,
        "brier_by_horizon": {key: mean(values) for key, values in brier_by_horizon.items()},
        "top_scenario_accuracy": mean(accuracy) if accuracy else None,
        "outcome_distribution": dict(outcomes),
        "evaluated_by_horizon": dict(by_horizon),
        "confusion_matrix": confusion,
        "precision_recall_by_scenario": precision_recall,
        "top_class_reliability_bins": reliability_rows,
        "calibration_note": "Reliability bins compare top-class confidence with top-class accuracy; this is a diagnostic, not full class-wise calibration. Brier is computed from stored historical replays only. Overlapping horizons and repeated sessions are dependent; cluster by date/session before inferential claims.",
    }
