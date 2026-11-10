from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo
import hashlib,json,re
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from app.security import require_auth
from app.services.ctrader import _selected_account
from app.services.cache import bar_cache
from app.engines.data_processing import aggregate_bars
from app.engines.stats_engine import run_module
from app.engines.advanced_ict import advanced_ict_statistics, smt_divergence
from app.engines.forecast_engine import generate_forecast, forecast_metrics, MODEL_VERSION
from app.services.store import set_value
from app.db import db
from app.engines.time_utils import infer_bar_duration_ms, to_ny, trading_date
from app.engines.forecast_engine import _features_at

router=APIRouter(tags=["statistics and forecast"])
NY=ZoneInfo("America/New_York")

class AnalyticsRequest(BaseModel):
    symbol_id:str
    timeframe:str="M1"
    filters:dict=Field(default_factory=dict)
    day_start_hour:int=17
    structure_horizon_minutes:int=Field(default=60, ge=1, le=10080)

class ForecastRequest(BaseModel):
    symbol_id: str
    as_of: str | None = None
    horizon_minutes: int = Field(default=60, ge=1, le=10080)
    timeframe: str = "M1"

class SMTRequest(BaseModel):
    primary_symbol_id:str
    secondary_symbol_id:str
    timeframe:str="M1"

class CompareRequest(BaseModel):
    symbol_id: str
    timeframe: str = "M1"
    period_a_start: str
    period_a_end: str
    period_b_start: str
    period_b_end: str
    filters: dict = Field(default_factory=dict)
    day_start_hour: int = 17
    structure_horizon_minutes: int = Field(default=60, ge=1, le=10080)


def _run_id(run_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}",run_id or ""):
        raise HTTPException(status_code=400,detail="Invalid client run identifier")
    return run_id


def _bars(run_id,account_id,symbol_id):
    return bar_cache.get_bars(run_id,account_id,symbol_id)


def _clip_completed_bars(bars: list[dict], cutoff_ms: int, duration_ms: int) -> list[dict]:
    """Only include candles fully closed at or before the as-of cutoff."""
    return [x for x in bars if int(x["time"]) + duration_ms <= int(cutoff_ms)]


def _filter_cutoff_ms(filters: dict | None) -> int:
    raw = (filters or {}).get("end")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            dt = dt.replace(tzinfo=NY) if dt.tzinfo is None else dt.astimezone(NY)
            return min(int(dt.timestamp() * 1000), int(datetime.now(ZoneInfo("UTC")).timestamp() * 1000))
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid end filter; use an ISO date/time in New York time") from exc
    return int(datetime.now(ZoneInfo("UTC")).timestamp() * 1000)


def _row_datetime(row):
    timestamp = row.get("timestamp")
    if timestamp is not None:
        try:
            return datetime.fromtimestamp(float(timestamp)/1000, ZoneInfo("UTC")).astimezone(NY)
        except Exception:
            pass
    value = row.get("time") or row.get("created_time") or row.get("period") or row.get("date")
    if value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.replace(tzinfo=NY) if dt.tzinfo is None else dt.astimezone(NY)
        except Exception:
            try:
                return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=NY)
            except Exception:
                return None
    return None


def _apply_filters(result, filters, module="", bars=None, day_start=17):
    """Filter displayed rows after event detection; contextual filters are causal as-of each event."""
    from app.engines.time_utils import session_name
    from app.engines.stats_engine import _day_groups
    keys = ["records", "daily_records", "weekly_records", "daily_summary", "evaluations", "fvg_records",
            "liquidity_pools", "order_blocks", "cbdr_records", "silver_bullet_records",
            "po3_records", "ipda_records", "judas_records", "cisd_records", "three_drive_records",
            "confluence_records", "quarterly_records"]
    total = visible = 0
    start_dt = None; end_dt = None
    # Context features must be computed from usable candles only. Suspect OHLC
    # remains available for audit/charting but cannot influence bias or volatility.
    clean_bars = [x for x in (bars or []) if x.get("analytics_usable", True)]
    bar_times = [int(x["time"]) for x in clean_bars]
    day_groups = _day_groups(clean_bars, day_start) if clean_bars else {}
    feature_cache = {}
    for field, target in (("start", "start_dt"), ("end", "end_dt")):
        value = filters.get(field)
        if value:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                dt = dt.replace(tzinfo=NY) if dt.tzinfo is None else dt.astimezone(NY)
                if target == "start_dt": start_dt = dt
                else: end_dt = dt
            except Exception:
                pass
    for key in keys:
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        total += len(rows)
        kept = []
        for row in rows:
            dt = _row_datetime(row)
            if dt:
                if start_dt and dt < start_dt: continue
                if end_dt and dt > end_dt: continue
                if filters.get("year") and dt.year != int(filters["year"]): continue
                if filters.get("month") and dt.month != int(filters["month"]): continue
                if filters.get("day_of_week") and dt.strftime("%A").lower() != str(filters["day_of_week"]).lower(): continue
            if filters.get("session"):
                row_session = row.get("session")
                # Daily/weekly aggregates have no session dimension; don't fabricate one.
                if row_session is None and key in {"daily_records", "weekly_records", "daily_summary"}:
                    # The session dimension does not exist for daily/weekly aggregates;
                    # preserve them and report that this filter is not applicable.
                    pass
                else:
                    if row_session is None and dt is not None:
                        row_session = session_name(int(dt.timestamp()*1000))
                    if row_session is not None and row_session != filters["session"]: continue
            event_ms = None
            if row.get("timestamp") is not None:
                try: event_ms = int(row["timestamp"])
                except Exception: event_ms = None
            elif dt is not None:
                event_ms = int(dt.timestamp() * 1000)
            contextual = None
            if bars and event_ms is not None and bar_times:
                from bisect import bisect_left
                idx = bisect_left(bar_times, event_ms) - 1  # event is timestamped at bar close
                if idx >= 0:
                    cache_key = (idx, day_start)
                    contextual = feature_cache.get(cache_key)
                    if contextual is None:
                        day_key = str(trading_date(bar_times[idx], day_start))
                        day_rows = day_groups.get(day_key, [])
                        if day_rows:
                            close_now = clean_bars[idx]["close"]
                            day_open = day_rows[0]["open"]
                            bias = "bullish" if close_now > day_open else "bearish" if close_now < day_open else "flat"
                        else:
                            bias = None
                        feat = _features_at(clean_bars, idx)
                        contextual = {"daily_bias": bias, "volatility_regime": feat["volatility_regime"]}
                        feature_cache[cache_key] = contextual
                    row.setdefault("daily_bias", contextual["daily_bias"])
                    row.setdefault("volatility_regime", contextual["volatility_regime"])
            if filters.get("daily_bias"):
                # Daily bias is contextual state known as-of an event. Do not
                # substitute the completed day's final direction (look-ahead).
                bias = row.get("daily_bias")
                if bias != filters["daily_bias"]: continue
            if filters.get("volatility_regime"):
                regime = row.get("volatility_regime") or (contextual or {}).get("volatility_regime")
                if regime != filters["volatility_regime"]: continue
            if filters.get("direction"):
                row_direction = row.get("direction") or row.get("expected_mss")
                if row_direction is not None and row_direction != filters["direction"]: continue
                if row_direction is None and key not in {"daily_records", "weekly_records"}: continue
            kept.append(row)
        result[key] = kept
        visible += len(kept)

    # Recalculate the main event-count metrics on the displayed subset where possible.
    rows = result.get("records", [])
    if module == "gaps":
        for kind in ("NDOG", "NWOG"):
            subset = [x for x in rows if x.get("type") == kind]
            result.setdefault("metrics", {})[f"{kind.lower()}_count"] = len(subset)
            observed = [x for x in subset if not x.get("right_censored") and not x.get("observation_data_incomplete", False)]
            filled = sum(bool(x.get("filled")) for x in observed)
            result["metrics"][f"{kind.lower()}_fully_filled_observed"] = len(observed)
            result["metrics"][f"{kind.lower()}_data_incomplete"] = sum(bool(x.get("observation_data_incomplete")) for x in subset)
            result["metrics"][f"{kind.lower()}_right_censored"] = sum(bool(x.get("right_censored")) for x in subset)
            result["metrics"][f"{kind.lower()}_fill_rate"] = filled/len(observed) if observed else None
            from app.engines.stats_engine import _ci95
            result["metrics"][f"{kind.lower()}_fill_rate_ci95"] = _ci95(filled, len(observed))
            result["metrics"][f"{kind.lower()}_threshold_rates"] = {
                str(p): sum(x.get(f"fill_{p}") is not None for x in observed)/len(observed) if observed else None
                for p in (25, 50, 75, 100)
            }
    elif module == "liquidity":
        sweeps = [x for x in rows if x.get("event") == "sweep"]
        result.setdefault("metrics", {}).update({"levels_tested": len(rows), "sweep_count": len(sweeps),
            "sweep_rate": len(sweeps)/len(rows) if rows else None,
            "buy_side_sweeps": sum(x.get("side") == "buy-side" for x in sweeps),
            "sell_side_sweeps": sum(x.get("side") == "sell-side" for x in sweeps),
            "probe_count": sum(x.get("event") == "probe" for x in rows),
            "gap_reclaim_count": sum(x.get("event") == "gap_reclaim" for x in rows),
            "breakout_count": sum(x.get("event") == "breakout" for x in rows),
            "reclaim_rate": sum(bool(x.get("reclaimed")) for x in rows)/len(rows) if rows else None,
            "sweep_rate_ci95": __import__("app.engines.stats_engine", fromlist=["_ci95"])._ci95(len(sweeps), len(rows))})
    elif module == "sessions":
        from statistics import median
        complete_rows = [x for x in rows if x.get("complete") is True]
        names = sorted({x.get("session") for x in complete_rows if x.get("session")})
        ranges = [x["range"] for x in complete_rows if isinstance(x.get("range"), (int, float))]
        result.setdefault("metrics", {}).update({"sessions": len(rows),
            "complete_sessions": len(complete_rows),
            "incomplete_sessions_excluded": len(rows) - len(complete_rows),
            "by_session": {k: sum(x.get("session") == k for x in complete_rows) for k in names},
            "continuation_count": sum(x.get("relationship_to_previous_session") == "continuation" for x in complete_rows),
            "reversal_count": sum(x.get("relationship_to_previous_session") == "reversal" for x in complete_rows),
            "median_range": median(ranges) if ranges else None})
    elif module == "time":
        # Recompute daily high/low time distributions inside the selected date
        # window. Edge days are then censored by the engine, not treated as full.
        if clean_bars:
            selected = []
            for candle in clean_bars:
                dt = to_ny(candle["time"])
                if start_dt and dt < start_dt: continue
                if end_dt and dt > end_dt: continue
                if filters.get("year") and dt.year != int(filters["year"]): continue
                if filters.get("month") and dt.month != int(filters["month"]): continue
                if filters.get("day_of_week") and dt.strftime("%A").lower() != str(filters["day_of_week"]).lower(): continue
                selected.append(candle)
            if selected:
                from app.engines.stats_engine import time_statistics
                scoped = time_statistics(selected, day_start)
                result.setdefault("metrics", {}).update(scoped["metrics"])
            else:
                result.setdefault("metrics", {}).update({"complete_days": 0, "incomplete_days_excluded": 0,
                    "median_daily_range": None, "high_formation_by_hour": [], "low_formation_by_hour": [],
                    "reversal_by_hour": [], "hourly_heatmap": [{"hour":h,"high_formation_days":0,"low_formation_days":0,"reversal_candidates":0} for h in range(24)]})
        result.setdefault("metrics", {})["distribution_scope_note"] = "High/low time distribution is date-scoped and based on complete days; session/direction filters apply to event records, not to daily extrema."
    elif module == "daily-weekly":
        from statistics import median
        from app.engines.stats_engine import daily_weekly_statistics
        scoped = []
        for candle in clean_bars:
            dt = to_ny(candle["time"])
            if start_dt and dt < start_dt: continue
            if end_dt and dt > end_dt: continue
            if filters.get("year") and dt.year != int(filters["year"]): continue
            if filters.get("month") and dt.month != int(filters["month"]): continue
            if filters.get("day_of_week") and dt.strftime("%A").lower() != str(filters["day_of_week"]).lower(): continue
            scoped.append(candle)
        scoped_result = daily_weekly_statistics(scoped, day_start, infer_bar_duration_ms(scoped) if scoped else None)
        daily = scoped_result.get("daily_records", [])
        weekly = scoped_result.get("weekly_records", [])
        if filters.get("direction"):
            daily = [x for x in daily if x.get("direction") == filters["direction"]]
            weekly = [x for x in weekly if x.get("direction") == filters["direction"]]
        result["daily_records"] = daily
        result["weekly_records"] = weekly
        complete_days = [x for x in daily if x.get("complete")]
        complete_weeks = [x for x in weekly if x.get("complete")]
        weekday_groups = {}
        for row in complete_days:
            weekday_groups.setdefault(row.get("weekday"), []).append(row)
        weekday_stats = {name: {"samples": len(group),
                                "bullish_rate": sum(x.get("direction") == "bullish" for x in group)/len(group),
                                "median_range": median([x["range"] for x in group if isinstance(x.get("range"), (int,float))]) if any(isinstance(x.get("range"), (int,float)) for x in group) else None}
                         for name, group in weekday_groups.items() if group}
        from app.engines.stats_engine import _ci95
        result.setdefault("metrics", {}).update({
            "days": len(daily), "complete_days": len(complete_days),
            "incomplete_days_excluded": len(daily)-len(complete_days),
            "weeks": len(weekly), "complete_weeks": len(complete_weeks),
            "incomplete_weeks_excluded": len(weekly)-len(complete_weeks),
            "weekday_statistics": weekday_stats,
            "bullish_days": sum(x.get("direction") == "bullish" for x in complete_days),
            "bearish_days": sum(x.get("direction") == "bearish" for x in complete_days),
            "bullish_day_rate": sum(x.get("direction") == "bullish" for x in complete_days)/len(complete_days) if complete_days else None,
            "bullish_day_rate_ci95": _ci95(sum(x.get("direction") == "bullish" for x in complete_days), len(complete_days)),
            "weekly_direction_counts": {k: sum(x.get("direction") == k for x in complete_weeks) for k in ("bullish", "bearish", "flat")},
            "median_daily_range": median([x["range"] for x in complete_days if isinstance(x.get("range"), (int,float))]) if any(isinstance(x.get("range"), (int,float)) for x in complete_days) else None,
            "median_weekly_range": median([x["range"] for x in complete_weeks if isinstance(x.get("range"), (int,float))]) if any(isinstance(x.get("range"), (int,float)) for x in complete_weeks) else None,
        })
    elif module == "structure":
        evals = result.get("evaluations", [])
        clean_evals = [x for x in evals if not x.get("ambiguous")]
        result.setdefault("metrics", {}).update({"bos_count": sum(x.get("type") == "BOS" for x in rows),
            "mss_count": sum(x.get("type") == "MSS" for x in rows),
            "evaluated_signals": len(evals),
            "mean_mfe": (sum(x["mfe"] for x in evals)/len(evals)) if evals else None,
            "mean_mae": (sum(x["mae"] for x in evals)/len(evals)) if evals else None,
            "target_rate_sample": len(clean_evals),
            "target_rates": {f"{r}R": sum(x["targets"].get(f"{r}R", False) for x in clean_evals)/len(clean_evals) if clean_evals else None for r in (1,2,3)},
            "target_rate_ci95": {f"{r}R": __import__("app.engines.stats_engine", fromlist=["_ci95"])._ci95(sum(x["targets"].get(f"{r}R", False) for x in clean_evals), len(clean_evals)) for r in (1,2,3)}})
    elif module == "liquidity-mss":
        from app.engines.stats_engine import _ci95
        mat = {}
        for h in (5,15,30,60):
            key = f"{h}m"
            valid = [x for x in rows if x.get("matches", {}).get(key) is not None]
            hits = sum(bool(x.get("matches", {}).get(key)) for x in valid)
            mat[key] = {"success": hits, "sample": len(valid),
                        "right_censored": sum(bool(x.get("right_censored", {}).get(key)) for x in rows),
                        "data_incomplete": sum(bool(x.get("data_incomplete", {}).get(key)) for x in rows),
                        "probability": hits/len(valid) if valid else None,
                        "ci95": _ci95(hits, len(valid))}
        result.setdefault("metrics", {}).update({"sweep_samples": len(rows), "probability_by_horizon": mat})
    visible = sum(len(result.get(key, [])) for key in keys if isinstance(result.get(key), list))
    result["filter_summary"] = {"total_records": total, "visible_records": visible,
        "filters": filters,
        "note": "Event detection runs on cached context up to the selected end time; filters are applied afterward. Daily/weekly aggregates have no session dimension and are retained unchanged by a session filter. Daily/weekly completeness is recalculated inside the selected date window. Load sufficient prior history for reference levels."}
    return result

@router.post("/api/v1/analytics/{module}")
async def analytics(module:str,body:AnalyticsRequest,run_id:str=Header(alias="X-Client-Run"),_:str=Depends(require_auth)):
    run_id=_run_id(run_id)
    try: account_id,_=await _selected_account()
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
    bars=_bars(run_id,account_id,body.symbol_id)
    if not bars: raise HTTPException(status_code=409,detail="No cached M1 data. Download history in Data Center first.")
    mins={"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(body.timeframe)
    if not mins: raise HTTPException(status_code=400,detail="Unsupported timeframe")
    series=aggregate_bars(bars,mins)
    series=_clip_completed_bars(series,_filter_cutoff_ms(body.filters),mins*60_000)
    if not series: raise HTTPException(status_code=409,detail="No fully closed candles exist before the selected analysis end time.")
    try:
        horizon_bars = (int(body.structure_horizon_minutes) // mins
                        if int(body.structure_horizon_minutes) % mins == 0 else 0)
        result=run_module(module,series,body.day_start_hour,bar_duration_ms=mins*60_000,
                          structure_horizon_bars=horizon_bars)
        return _apply_filters(result,body.filters,module,series,body.day_start_hour)
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500,detail=f"Analytics engine failed: {exc}")


def _parse_period_boundary(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid comparison date/time: {value}") from exc
    return dt.replace(tzinfo=NY) if dt.tzinfo is None else dt.astimezone(NY)


def _period_summary(module: str, result: dict, start: datetime, end: datetime) -> dict:
    """Summarize only records whose event/period timestamp falls inside [start, end)."""
    primary_keys = {
        "gaps": ["records"], "liquidity": ["records"], "sessions": ["records"],
        "time": ["records"], "structure": ["records"],
        "daily-weekly": ["daily_records", "weekly_records"],
        "liquidity-mss": ["records"],
    }
    rows = []
    for key in primary_keys.get(module, ["records"]):
        for row in result.get(key, []) or []:
            dt = _row_datetime(row)
            if dt is not None and start <= dt < end:
                item = dict(row)
                item["_record_group"] = key
                rows.append(item)

    def count_by(field):
        counts = {}
        for row in rows:
            value = row.get(field)
            if value is not None:
                label = str(value)
                counts[label] = counts.get(label, 0) + 1
        return counts

    def nums(field):
        return [float(x[field]) for x in rows if isinstance(x.get(field), (int, float))]

    def avg(values):
        return sum(values) / len(values) if values else None

    range_values = nums("range")
    summary = {
        "start": start.isoformat(), "end": end.isoformat(),
        "record_count": len(rows),
        "by_type": count_by("type"), "by_direction": count_by("direction"),
        "by_session": count_by("session"), "by_event": count_by("event"),
        "median_range": median(range_values) if range_values else None,
        "mean_range": avg(range_values),
    }

    if module == "gaps":
        gaps = [x for x in rows if x.get("type") in {"NDOG", "NWOG"}]
        observed = [x for x in gaps if not x.get("right_censored") and not x.get("observation_data_incomplete", False)]
        summary["gap_samples"] = len(gaps)
        summary["observed_gap_samples"] = len(observed)
        summary["right_censored_gaps"] = sum(bool(x.get("right_censored")) for x in gaps)
        summary["data_incomplete_gaps"] = sum(bool(x.get("observation_data_incomplete")) for x in gaps)
        summary["fill_rates"] = {
            f"{pct}%": (sum(x.get(f"fill_{pct}") is not None for x in observed) / len(observed)) if observed else None
            for pct in (25, 50, 75, 100)
        }
    elif module == "liquidity":
        summary["sweep_count"] = sum(x.get("event") == "sweep" for x in rows)
        summary["sweep_rate"] = summary["sweep_count"] / len(rows) if rows else None
        summary["reclaim_rate"] = sum(bool(x.get("reclaimed")) for x in rows) / len(rows) if rows else None
    elif module == "sessions":
        complete_rows = [x for x in rows if x.get("complete") is True]
        summary["complete_sessions"] = len(complete_rows)
        summary["incomplete_sessions_excluded"] = len(rows) - len(complete_rows)
        summary["continuation_count"] = sum(x.get("relationship_to_previous_session") == "continuation" for x in complete_rows)
        summary["reversal_count"] = sum(x.get("relationship_to_previous_session") == "reversal" for x in complete_rows)
        ranges = nums("range")
        summary["median_complete_session_range"] = median([x["range"] for x in complete_rows if isinstance(x.get("range"), (int, float))]) if any(isinstance(x.get("range"), (int, float)) for x in complete_rows) else None
    elif module == "structure":
        evals = []
        for row in result.get("evaluations", []) or []:
            dt = _row_datetime(row)
            if dt is not None and start <= dt < end:
                evals.append(row)
        clean = [x for x in evals if not x.get("ambiguous")]
        summary.update({
            "bos_count": sum(x.get("type") == "BOS" for x in rows),
            "mss_count": sum(x.get("type") == "MSS" for x in rows),
            "evaluation_samples": len(evals),
            "ambiguous_excluded": len(evals) - len(clean),
            "mean_mfe": avg([float(x["mfe"]) for x in evals if isinstance(x.get("mfe"), (int, float))]),
            "mean_mae": avg([float(x["mae"]) for x in evals if isinstance(x.get("mae"), (int, float))]),
            "target_rates": {f"{r}R": (sum(bool(x.get("targets", {}).get(f"{r}R")) for x in clean) / len(clean)) if clean else None for r in (1, 2, 3)},
        })
    elif module == "daily-weekly":
        daily = [x for x in rows if x.get("_record_group") == "daily_records"]
        weekly = [x for x in rows if x.get("_record_group") == "weekly_records"]
        daily_complete = [x for x in daily if x.get("complete")]
        weekly_complete = [x for x in weekly if x.get("complete")]
        daily_ranges = [float(x["range"]) for x in daily_complete if isinstance(x.get("range"), (int, float))]
        weekly_ranges = [float(x["range"]) for x in weekly_complete if isinstance(x.get("range"), (int, float))]
        summary.update({
            "daily_samples": len(daily), "weekly_samples": len(weekly),
            "complete_daily_periods": len(daily_complete), "complete_weekly_periods": len(weekly_complete),
            "incomplete_periods": (len(daily)-len(daily_complete)) + (len(weekly)-len(weekly_complete)),
            "bullish_daily_rate": (sum(x.get("direction") == "bullish" for x in daily_complete) / len(daily_complete)) if daily_complete else None,
            "bullish_weekly_rate": (sum(x.get("direction") == "bullish" for x in weekly_complete) / len(weekly_complete)) if weekly_complete else None,
            "median_complete_daily_range": median(daily_ranges) if daily_ranges else None,
            "median_complete_weekly_range": median(weekly_ranges) if weekly_ranges else None,
        })
    elif module == "liquidity-mss":
        horizons = (5, 15, 30, 60)
        summary["probability_by_horizon"] = {}
        for h in horizons:
            key = f"{h}m"
            valid = [x for x in rows if x.get("matches", {}).get(key) is not None]
            success = sum(bool(x.get("matches", {}).get(key)) for x in valid)
            from app.engines.stats_engine import _ci95
            summary["probability_by_horizon"][key] = {
                "success": success, "sample": len(valid),
                "right_censored": sum(bool(x.get("right_censored", {}).get(key)) for x in rows),
                "data_incomplete": sum(bool(x.get("data_incomplete", {}).get(key)) for x in rows),
                "probability": success/len(valid) if valid else None,
                "ci95": _ci95(success, len(valid))}

    return summary

@router.post("/api/v1/analytics/advanced-ict")
async def advanced_ict(body:AnalyticsRequest,run_id:str=Header(alias="X-Client-Run"),_:str=Depends(require_auth)):
    run_id=_run_id(run_id)
    try: account_id,_=await _selected_account()
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
    bars=_bars(run_id,account_id,body.symbol_id)
    if not bars: raise HTTPException(status_code=409,detail="No cached M1 data. Download history first.")
    mins={"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(body.timeframe,1)
    series=aggregate_bars(bars,mins)
    series=_clip_completed_bars(series,_filter_cutoff_ms(body.filters),mins*60_000)
    if not series: raise HTTPException(status_code=409,detail="No fully closed candles exist before the selected analysis end time.")
    return _apply_filters(advanced_ict_statistics(series,body.day_start_hour,bar_duration_ms=mins*60_000),body.filters,"advanced",series,body.day_start_hour)

@router.post("/api/v1/analytics/smt")
async def smt(body:SMTRequest,run_id:str=Header(alias="X-Client-Run"),_:str=Depends(require_auth)):
    run_id=_run_id(run_id)
    try: account_id,_=await _selected_account()
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
    a=_bars(run_id,account_id,body.primary_symbol_id); b=_bars(run_id,account_id,body.secondary_symbol_id)
    if not a or not b: raise HTTPException(status_code=409,detail="Download both symbols over matching dates before calculating SMT")
    mins={"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(body.timeframe)
    if not mins: raise HTTPException(status_code=400,detail="Unsupported timeframe")
    cutoff = int(datetime.now(ZoneInfo("UTC")).timestamp() * 1000)
    a_series=_clip_completed_bars(aggregate_bars(a,mins),cutoff,mins*60_000)
    b_series=_clip_completed_bars(aggregate_bars(b,mins),cutoff,mins*60_000)
    return smt_divergence(a_series,b_series)

def _realized_forecast_outcome(series: list[dict], asof_ms: int, horizon_bars: int, atr: float):
    """Score a forecast with clean, continuous future bars beginning at the first bar opening at/after as-of."""
    from app.engines.stats_engine import _usable
    series = _usable(series)
    duration = infer_bar_duration_ms(series)
    idx = max((i for i, x in enumerate(series) if x["time"] + duration <= asof_ms), default=-1)
    if idx < 0 or atr <= 0:
        return None
    future = [x for x in series if int(x["time"]) >= asof_ms][:horizon_bars]
    if len(future) < horizon_bars:
        return None
    if any(int(future[j]["time"]) - int(future[j-1]["time"]) != duration for j in range(1, len(future))):
        return None
    base = series[idx]["close"]
    ret = (future[-1]["close"] - base) / atr
    scenario = "Bullish expansion" if ret > 0.5 else "Bearish expansion" if ret < -0.5 else "Consolidation"
    return {"scenario": scenario, "return_atr": ret,
            "max_favourable_atr": (max(x["high"] for x in future) - base) / atr,
            "max_adverse_atr": (base - min(x["low"] for x in future)) / atr,
            "horizon_bars": len(future),
            "strictly_after_forecast_time": all(int(x["time"]) >= asof_ms for x in future)}


@router.post("/api/v1/forecast")
async def forecast(body:ForecastRequest,run_id:str=Header(alias="X-Client-Run"),_:str=Depends(require_auth)):
    run_id=_run_id(run_id)
    try: account_id,_=await _selected_account()
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
    bars=_bars(run_id,account_id,body.symbol_id)
    if not bars: raise HTTPException(status_code=409,detail="Download M1 history first")
    mins={"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(body.timeframe)
    if not mins: raise HTTPException(status_code=400,detail="Unsupported timeframe")
    series=aggregate_bars(bars,mins)
    asof = None
    if body.as_of:
        try:
            dt = datetime.fromisoformat(body.as_of.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=NY)
            asof = int(dt.timestamp() * 1000)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid as_of timestamp; use ISO-8601 New York time") from exc
    if body.horizon_minutes % mins:
        raise HTTPException(status_code=422, detail="Forecast horizon must be an exact multiple of the selected timeframe. Choose a lower timeframe or a larger horizon.")
    horizon_bars = body.horizon_minutes // mins
    duration = infer_bar_duration_ms(series)
    latest_closed_end = max((int(x["time"]) + duration for x in series), default=0)
    now_ms = int(datetime.now(ZoneInfo("UTC")).timestamp() * 1000)
    if asof is None:
        asof = latest_closed_end
    elif asof > now_ms or asof > latest_closed_end:
        raise HTTPException(status_code=422, detail="Forecast as_of cannot be later than the latest fully closed candle or current time")
    elif asof < int(series[0]["time"]) + duration:
        raise HTTPException(status_code=422, detail="Forecast as_of is earlier than the available completed history")
    result=generate_forecast(series,asof,horizon_bars,horizon_minutes=horizon_bars*mins)
    if result.get("status")!="ok": return result
    # Historical replay is scored only with bars opening at/after the as-of timestamp.
    actual = None
    if body.as_of is not None:
        actual = _realized_forecast_outcome(series, asof, horizon_bars, result["context"]["atr"])
        if actual:
            actual["horizon_minutes"] = actual["horizon_bars"] * mins
    result["timeframe"] = body.timeframe
    result["symbol_id"] = body.symbol_id
    audit_context = {"context": result.get("context", {}), "horizon_minutes": result.get("horizon_minutes"),
                     "timeframe": body.timeframe, "as_of": result.get("as_of")}
    input_hash = hashlib.sha256(json.dumps(audit_context, sort_keys=True).encode()).hexdigest()
    payload_json = json.dumps(result, separators=(",", ":"))
    with db() as conn:
        existing = conn.execute("SELECT id FROM forecast_runs WHERE symbol=? AND as_of=? AND model_version=? AND input_hash=? ORDER BY id DESC LIMIT 1",
                                (body.symbol_id, result["as_of"], MODEL_VERSION, input_hash)).fetchone()
        if existing:
            result["forecast_record_id"] = int(existing["id"])
        else:
            cur = conn.execute("INSERT INTO forecast_runs(created_at,symbol,as_of,model_version,input_hash,payload_json,outcome_json,evaluated_at) VALUES(datetime('now'),?,?,?,?,?,?,CASE WHEN ? IS NULL THEN NULL ELSE datetime('now') END)",
                               (body.symbol_id, result["as_of"], MODEL_VERSION, input_hash, payload_json,
                                json.dumps(actual) if actual else None, json.dumps(actual) if actual else None))
            result["forecast_record_id"] = int(cur.lastrowid)
    result["historical_outcome"] = actual
    return result

@router.get("/api/v1/forecast/evaluation")
async def evaluation(run_id: str = Header(alias="X-Client-Run"), _:str=Depends(require_auth)):
    run_id = _run_id(run_id)
    # Close pending live forecasts when later history is downloaded in this page session.
    try:
        account_id, _is_live = await _selected_account()
    except Exception:
        account_id = None
    if account_id is not None:
        with db() as conn:
            pending = conn.execute("SELECT id,symbol,as_of,payload_json FROM forecast_runs WHERE outcome_json IS NULL ORDER BY id DESC LIMIT 500").fetchall()
        for row in pending:
            try:
                payload = json.loads(row["payload_json"])
                symbol_id = str(payload.get("symbol_id") or row["symbol"])
                timeframe = payload.get("timeframe", "M1")
                mins = {"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}.get(timeframe)
                if not mins:
                    continue
                raw = bar_cache.get_bars(run_id, account_id, symbol_id)
                if not raw:
                    continue
                series = aggregate_bars(raw, mins)
                asof_dt = datetime.fromisoformat(str(row["as_of"]).replace("Z", "+00:00"))
                if asof_dt.tzinfo is None:
                    asof_dt = asof_dt.replace(tzinfo=NY)
                asof_ms = int(asof_dt.timestamp() * 1000)
                outcome = _realized_forecast_outcome(series, asof_ms, int(payload.get("horizon_bars", 1)),
                                                     float(payload.get("context", {}).get("atr", 0) or 0))
                if outcome:
                    outcome["horizon_minutes"] = int(payload.get("horizon_minutes", 0) or 0)
                    with db() as conn:
                        conn.execute("UPDATE forecast_runs SET outcome_json=?, evaluated_at=datetime('now') WHERE id=? AND outcome_json IS NULL",
                                     (json.dumps(outcome, separators=(",", ":")), row["id"]))
            except Exception:
                # A single unavailable symbol or malformed historic row must not block the audit page.
                continue
    with db() as conn:
        rows=conn.execute("SELECT id,created_at,symbol,as_of,model_version,payload_json,outcome_json FROM forecast_runs ORDER BY id DESC LIMIT 500").fetchall()
    runs=[{"id":r["id"],"created_at":r["created_at"],"symbol":r["symbol"],"as_of":r["as_of"],
           "payload":json.loads(r["payload_json"]),"outcome":json.loads(r["outcome_json"]) if r["outcome_json"] else None} for r in rows]
    metrics=forecast_metrics(runs)
    return {"metrics":metrics,"records":[{"id":r["id"],"created_at":r["created_at"],"symbol":r["symbol"],"as_of":r["as_of"],
                                               "model_version":r["payload"].get("model_version"),"sample_size":r["payload"].get("sample_size"),
                                               "status":r["payload"].get("status"),"outcome":r["outcome"]} for r in runs]}


@router.post("/api/v1/analytics/{module}/compare")
async def compare_analytics(module: str, body: CompareRequest,
                            run_id: str = Header(alias="X-Client-Run"),
                            _: str = Depends(require_auth)):
    run_id = _run_id(run_id)
    supported = {"gaps", "liquidity", "sessions", "time", "structure", "daily-weekly", "liquidity-mss"}
    if module not in supported:
        raise HTTPException(status_code=404, detail=f"Comparison is not supported for module: {module}")
    try:
        account_id, _ = await _selected_account()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    bars = _bars(run_id, account_id, body.symbol_id)
    if not bars:
        raise HTTPException(status_code=409, detail="No cached M1 data. Download history in Data Center first.")
    mins = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}.get(body.timeframe)
    if not mins:
        raise HTTPException(status_code=400, detail="Unsupported timeframe")
    periods = [
        (_parse_period_boundary(body.period_a_start), _parse_period_boundary(body.period_a_end)),
        (_parse_period_boundary(body.period_b_start), _parse_period_boundary(body.period_b_end)),
    ]
    for index, (start, end) in enumerate(periods, start=1):
        if end <= start:
            raise HTTPException(status_code=422, detail=f"Period {index}: end must be later than start")
    all_series = aggregate_bars(bars, mins)
    now_ms = int(datetime.now(ZoneInfo("UTC")).timestamp() * 1000)
    try:
        # Each period gets only information available by its own end. This is
        # essential for gap lifecycle and other forward-observed measurements.
        filters = {k: v for k, v in (body.filters or {}).items() if k not in {"start", "end"} and v not in (None, "")}
        period_results = []
        for start, end in periods:
            cutoff = min(int(end.timestamp() * 1000), now_ms)
            scoped_series = _clip_completed_bars(all_series, cutoff, mins * 60_000)
            if not scoped_series:
                period_results.append({"records": []})
                continue
            horizon_bars = (int(body.structure_horizon_minutes) // mins
                            if int(body.structure_horizon_minutes) % mins == 0 else 0)
            result = run_module(module, scoped_series, body.day_start_hour, bar_duration_ms=mins * 60_000,
                                structure_horizon_bars=horizon_bars)
            period_results.append(_apply_filters(result, filters, module, scoped_series, body.day_start_hour))
        a = _period_summary(module, period_results[0], *periods[0])
        b = _period_summary(module, period_results[1], *periods[1])
        keys = sorted(set(a) | set(b))
        deltas = {}
        for key in keys:
            av, bv = a.get(key), b.get(key)
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                deltas[key] = {"absolute": bv - av,
                               "relative": ((bv - av) / abs(av)) if av else None}
        return {"module": module, "timeframe": body.timeframe,
                "symbol_id": body.symbol_id,
                "period_a": a, "period_b": b,
                "deltas_b_minus_a": deltas,
                "note": "Each period is independently recomputed using only bars available up to that period end; cached history before the period is retained as context. Events require the selected ranges plus relevant prior history. Ratios with zero Period A are not reported as relative deltas."}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Comparison engine failed: {exc}")
