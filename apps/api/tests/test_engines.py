from datetime import datetime, timezone
import math

from app.engines import time_utils
from app.engines.time_utils import to_ny, trading_date, trading_week, session_name, session_trade_date, set_session_windows
from app.engines.data_processing import aggregate_bars
from app.engines.stats_engine import (
    _period_completeness, _day_groups, _week_groups, gap_statistics,
    liquidity_statistics, daily_weekly_statistics, structure_events,
)
from app.engines.advanced_ict import advanced_ict_statistics, _quarterly_profiles
from app.services.ctrader import _decode_trendbar
from app.engines.forecast_engine import generate_forecast
from app.services.cache import SessionBarCache


def ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def bar(time_ms, open_, high, low, close, *, quality="ok", usable=True):
    return {"time": time_ms, "open": open_, "high": high, "low": low,
            "close": close, "volume": 1, "quality": quality,
            "analytics_usable": usable}


def test_new_york_dst_is_automatic():
    winter = to_ny(ms("2026-01-15T15:00:00"))
    summer = to_ny(ms("2026-07-15T15:00:00"))
    assert winter.strftime("%z") == "-0500"
    assert summer.strftime("%z") == "-0400"


def test_forex_trading_date_and_week_align_sunday_asia_with_monday_sessions():
    sunday_asia = int(datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc).timestamp() * 1000)  # Sun 20:00 EST
    monday_london = int(datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc).timestamp() * 1000)  # Mon 02:00 EST
    assert trading_date(sunday_asia, 17).isoformat() == "2026-11-09"
    assert session_trade_date(sunday_asia, 17) == session_trade_date(monday_london, 17)
    assert trading_week(sunday_asia, 17).isoformat() == "2026-11-09"


def test_session_profile_rejects_overlaps_and_accepts_midnight_end():
    original = dict(time_utils.SESSION_WINDOWS)
    try:
        set_session_windows({"Asia": (1200, 0), "London": (120, 300), "NY AM": (420, 600),
                             "London Close": (600, 720), "NY PM": (780, 960)})
        assert time_utils.SESSION_WINDOWS["Asia"] == (1200, 0)
        assert session_name(int(datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc).timestamp()*1000)) == "Asia"
    finally:
        set_session_windows(original)
    try:
        set_session_windows({"Asia": (1200, 0), "London": (120, 300), "NY AM": (420, 600),
                             "London Close": (590, 720), "NY PM": (780, 960)})
    except ValueError as exc:
        assert "overlap" in str(exc).lower()
    else:
        raise AssertionError("overlapping sessions must be rejected")


def test_cache_fetches_only_missing_ranges_and_isolates_run_and_symbol():
    cache = SessionBarCache(ttl_seconds=3600)
    cache.put_window("run-abcdefghijkl", "1", "10", 0, 100, [bar(1, 1, 2, 0, 1)])
    assert cache.get_missing("run-abcdefghijkl", "1", "10", 0, 200) == [(100, 200)]
    assert cache.get_missing("other-run-abcdefgh", "1", "10", 0, 200) == [(0, 200)]
    assert cache.get_missing("run-abcdefghijkl", "1", "11", 0, 200) == [(0, 200)]


def test_timeframe_aggregation_uses_utc_bucket_and_preserves_quality():
    rows = [bar(0, 10, 12, 9, 11), bar(60_000, 11, 13, 10, 12),
            bar(120_000, 12, 14, 8, 9, quality="suspect_ohlc", usable=False)]
    agg = aggregate_bars(rows, 3)
    assert len(agg) == 1
    assert agg[0]["open"] == 10 and agg[0]["close"] == 9
    assert agg[0]["high"] == 14 and agg[0]["low"] == 8
    assert agg[0]["analytics_usable"] is False
    assert agg[0]["complete"] is True
    assert agg[0]["expected_count"] == 3


def test_gap_statistics_tracks_fill_thresholds_and_censoring():
    # Use two fully covered Forex trading days. The first opens Sun 17:00 NY;
    # the second opens Mon 17:00 NY. A sparse pair of endpoint candles must not
    # be accepted as a complete prior-day close/open reference.
    from zoneinfo import ZoneInfo
    start = int(datetime(2026, 11, 8, 17, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()*1000)
    rows = []
    for i in range(2 * 1440):
        t = start + i * 60_000
        if i < 1440:
            rows.append(bar(t, 100, 100.2, 99.8, 100))
        elif i == 1440:
            rows.append(bar(t, 101, 101.2, 100.5, 101))
        else:
            rows.append(bar(t, 100.8, 101, 100.5, 100.8))
    result = gap_statistics(rows, day_start=17)
    ndog = next(x for x in result["records"] if x["type"] == "NDOG")
    assert ndog["direction"] == "up"
    assert ndog["fill_50"] is not None
    assert ndog["fill_100"] is None
    assert ndog["right_censored"] is False


def test_daily_weekly_excludes_truncated_edge_periods_from_summary():
    rows = []
    for day, start_hour in [(8, 20), (9, 17), (10, 17), (11, 17)]:
        dt = datetime(2026, 11, day, start_hour, 0)
        t = int(dt.replace(tzinfo=__import__('zoneinfo').ZoneInfo('America/New_York')).timestamp()*1000)
        rows.append(bar(t, 100, 102, 99, 101))
    result = daily_weekly_statistics(rows, day_start=17, bar_duration_ms=60_000)
    assert result["metrics"]["incomplete_days_excluded"] >= 1
    assert any("complete" in row for row in result["daily_records"])


def test_structure_event_occurs_at_break_confirmation_close_not_pivot_time():
    t0 = 1_800_000_000_000
    values = [
        (10, 9, 9.5), (11, 9, 10), (15, 10, 12), (12, 10, 11), (11, 9, 10),
        (16, 10, 16),
    ]
    rows = [bar(t0+i*60_000, (11 if i == 5 else c), h, l, c) for i, (h, l, c) in enumerate(values)]
    events = structure_events(rows)
    bullish = next(x for x in events if x["direction"] == "bullish")
    assert bullish["pivot_time"] == t0 + 2*60_000
    assert bullish["pivot_confirmation_time"] == to_ny(t0 + 5*60_000).isoformat()
    assert bullish["time"] == t0 + 6*60_000
    assert bullish["time"] > bullish["pivot_time"]


def test_suspect_ohlc_is_excluded_from_analytics():
    rows = [bar(i*60_000, 10, 11, 9, 10) for i in range(5)]
    rows[2]["analytics_usable"] = False
    rows[2]["quality"] = "suspect_ohlc"
    result = daily_weekly_statistics(rows)
    assert result["daily_records"]
    assert all(row["bars"] == 4 for row in result["daily_records"])


def test_forecast_is_invariant_to_bars_after_historical_asof():
    rows = []
    start = 1_800_000_000_000
    for i in range(700):
        close = 100 + 0.015*i + 0.8*math.sin(i/8) + 0.25*math.sin(i/2.7)
        prev = 100 + 0.015*max(i-1, 0) + 0.8*math.sin(max(i-1,0)/8) + 0.25*math.sin(max(i-1,0)/2.7)
        op = prev if i else close
        rows.append(bar(start+i*60_000, op, max(op,close)+0.15, min(op,close)-0.15, close))
    asof = start + 520*60_000
    before = generate_forecast(rows[:521], asof, horizon_bars=5, horizon_minutes=5, min_analogs=5)
    after = generate_forecast(rows, asof, horizon_bars=5, horizon_minutes=5, min_analogs=5)
    assert before["status"] == after["status"]
    if before["status"] == "ok":
        assert before["sample_size"] == after["sample_size"]
        assert before["scenarios"] == after["scenarios"]
        assert abs(sum(x["probability"] for x in after["scenarios"]) - 1) < 1e-9


def test_advanced_ict_engine_accepts_explicit_timeframe_duration_and_returns_all_modules():
    start = int(datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
    rows = []
    for i in range(220):
        base = 100 + 0.025*i + 0.7*math.sin(i/8)
        prev = 100 + 0.025*max(i-1, 0) + 0.7*math.sin(max(i-1, 0)/8)
        rows.append(bar(start+i*60_000, prev, max(prev,base)+0.12, min(prev,base)-0.12, base))
    result = advanced_ict_statistics(rows, day_start=17, bar_duration_ms=60_000)
    for key in ("fvg_records", "liquidity_pools", "order_blocks", "cbdr_records", "silver_bullet_records",
                "po3_records", "ipda_records", "judas_records", "cisd_records", "three_drive_records",
                "confluence_records", "quarterly_records"):
        assert key in result
    assert result["metrics"]["adr"]["5"]["complete_history_only"] is True


def test_confluence_engine_is_weighted_evidence_score_not_probability():
    from unittest.mock import patch
    from app.engines.advanced_ict import _confluence_candidates
    rows = [bar(i*60_000,100,101,99,100) for i in range(100)]
    sweep = {"event":"sweep", "side":"sell-side", "timestamp":10*60_000,
             "time":"2026-01-01T00:10:00-05:00", "level_type":"Asia Low", "level":99}
    mss = {"type":"MSS", "direction":"bullish", "timestamp":20*60_000}
    fvg = {"direction":"bullish", "timestamp":25*60_000}
    ob = {"direction":"bullish", "timestamp":30*60_000}
    pool = {"type":"EQL", "timestamp":9*60_000}
    with patch("app.engines.advanced_ict.liquidity_statistics", return_value={"records":[sweep]}):
        result = _confluence_candidates(rows,17,60_000,[fvg],[pool],[ob],[mss])
    assert len(result) == 1
    assert result[0]["score"] == 8
    assert result[0]["max_score"] == 8
    assert "probability" not in result[0]
    assert result[0]["classification"].startswith("heuristic")


def test_cbdr_groups_whole_new_york_calendar_window_across_forex_1700_boundary():
    from app.engines.advanced_ict import advanced_ict_statistics
    start = int(datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc).timestamp()*1000)  # 14:00 New York
    rows = [bar(start+i*60_000,100,101+i*0.001,99,100+i*0.001) for i in range(360)]
    result = advanced_ict_statistics(rows,day_start=17,bar_duration_ms=60_000)
    assert len(result["cbdr_records"]) == 1
    assert result["cbdr_records"][0]["date"] == "2026-11-09"
    assert result["cbdr_records"][0]["complete"] is True
    assert result["cbdr_records"][0]["end"].startswith("2026-11-09T20:00:00")


def test_quarterly_profile_marks_edge_quarters_partial():
    start = int(datetime(2026, 1, 2, 17, 0, tzinfo=__import__('zoneinfo').ZoneInfo('America/New_York')).timestamp()*1000)
    rows = [bar(start+i*24*60*60_000,100+i,102+i,99+i,101+i) for i in range(100)]
    result = _quarterly_profiles(rows,17,24*60*60_000)
    assert result
    assert result[0]["complete_history_period"] is False
    assert result[-1]["complete_history_period"] is False


def test_ctrader_trendbar_relative_prices_decode_and_flag_impossible_ohlc():
    from types import SimpleNamespace
    row = SimpleNamespace(low=2_000_000, deltaOpen=10_000, deltaClose=15_000,
                          deltaHigh=20_000, utcTimestampInMinutes=30_000_000, volume=123)
    decoded = _decode_trendbar(row,digits=2)
    assert decoded["low"] == 20.00
    assert decoded["open"] == 20.10
    assert decoded["close"] == 20.15
    assert decoded["high"] == 20.20
    assert decoded["time"] == 30_000_000*60_000
    assert decoded["analytics_usable"] is True
    bad = SimpleNamespace(low=2_000_000, deltaOpen=10_000, deltaClose=15_000,
                          deltaHigh=5_000, utcTimestampInMinutes=30_000_000, volume=123)
    flagged = _decode_trendbar(bad,digits=2)
    assert flagged["quality"] == "suspect_ohlc"
    assert flagged["analytics_usable"] is False


def test_period_comparison_uses_inclusive_start_exclusive_end_and_separate_daily_weekly_samples():
    from app.routers.analytics import _period_summary
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 9, 0, 0, tzinfo=ny)
    end = datetime(2026, 11, 11, 0, 0, tzinfo=ny)
    result = {
        "daily_records": [
            {"period": "2026-11-09", "direction": "bullish", "range": 10, "complete": True},
            {"period": "2026-11-10", "direction": "bearish", "range": 20, "complete": False},
        ],
        "weekly_records": [
            {"period": "2026-11-09", "direction": "bullish", "range": 50, "complete": True},
        ],
    }
    summary = _period_summary("daily-weekly", result, start, end)
    assert summary["daily_samples"] == 2
    assert summary["weekly_samples"] == 1
    assert summary["complete_daily_periods"] == 1
    assert summary["complete_weekly_periods"] == 1
    assert summary["bullish_daily_rate"] == 1
    assert summary["median_complete_daily_range"] == 10
    assert summary["median_complete_weekly_range"] == 50


def test_market_structure_excludes_right_censored_partial_forward_horizons(monkeypatch):
    from app.engines import stats_engine
    start = 1_800_000_000_000
    rows = [bar(start+i*60_000, 100, 101, 99, 100) for i in range(20)]
    events = [
        {"type": "MSS", "direction": "bullish", "bar_time": rows[3]["time"],
         "time": rows[3]["time"]+60_000, "time_ny": "2026-01-01T00:04:00-05:00",
         "price": 100, "swing_low": 99, "swing_high": 101},
        {"type": "BOS", "direction": "bullish", "bar_time": rows[18]["time"],
         "time": rows[18]["time"]+60_000, "time_ny": "2026-01-01T00:19:00-05:00",
         "price": 100, "swing_low": 99, "swing_high": 101},
    ]
    monkeypatch.setattr(stats_engine, "structure_events", lambda _bars: events)
    result = stats_engine.market_structure_statistics(rows, horizon=5)
    assert len(result["evaluations"]) == 1
    assert result["evaluations"][0]["horizon_bars"] == 5
    assert result["metrics"]["right_censored_signals"] == 1


def test_time_statistics_uses_only_complete_edge_aware_trading_days():
    from app.engines.stats_engine import time_statistics
    ny = __import__('zoneinfo').ZoneInfo('America/New_York')
    first_start = datetime(2026, 11, 7, 17, 10, tzinfo=ny)  # partial first day
    rows = []
    for i in range(10):
        dt = first_start + __import__('datetime').timedelta(minutes=i)
        rows.append(bar(int(dt.timestamp()*1000), 100, 101+i*0.01, 99, 100.2))
    full_start = datetime(2026, 11, 8, 17, 0, tzinfo=ny)
    for i in range(1440):
        dt = full_start + __import__('datetime').timedelta(minutes=i)
        base = 100 + 0.001*i
        rows.append(bar(int(dt.timestamp()*1000), base, base+0.2, base-0.2, base+0.05))
    last_start = datetime(2026, 11, 9, 17, 0, tzinfo=ny)
    for i in range(20):
        dt = last_start + __import__('datetime').timedelta(minutes=i)
        base = 102 + i*0.01
        rows.append(bar(int(dt.timestamp()*1000), base, base+0.2, base-0.2, base+0.05))
    result = time_statistics(rows, day_start=17)
    assert result["metrics"]["complete_days"] == 1
    assert result["metrics"]["incomplete_days_excluded"] == 2


def test_liquidity_to_mss_uses_horizon_specific_samples_and_censors_unfinished_windows(monkeypatch):
    from app.engines import stats_engine
    start = 1_800_000_000_000
    rows = [bar(start+i*60_000, 100, 101, 99, 100) for i in range(20)]
    sweep_time = rows[5]["time"] + 60_000
    monkeypatch.setattr(stats_engine, "liquidity_statistics", lambda *a, **k: {"records": [{
        "event": "sweep", "side": "sell-side", "level_type": "Asia Low",
        "timestamp": sweep_time, "time": to_ny(sweep_time).isoformat(),
        "trading_date": "2026-01-01", "session": "Asia"}]})
    monkeypatch.setattr(stats_engine, "market_structure_statistics", lambda *a, **k: {"records": [{
        "type": "MSS", "direction": "bullish", "time": sweep_time+3*60_000}]})
    result = stats_engine.liquidity_to_mss_statistics(rows, bar_duration_ms=60_000)
    assert result["records"][0]["matches"]["5m"] is True
    assert result["records"][0]["matches"]["15m"] is None
    assert result["metrics"]["probability_by_horizon"]["5m"]["sample"] == 1
    assert result["metrics"]["probability_by_horizon"]["15m"]["sample"] == 0
    assert result["metrics"]["probability_by_horizon"]["15m"]["right_censored"] == 1


def test_analytics_filter_does_not_discard_daily_weekly_rows_on_session_filter():
    from app.routers.analytics import _apply_filters
    start = int(datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc).timestamp()*1000)
    rows = [bar(start+i*60_000, 100, 101, 99, 100.5) for i in range(30)]
    result = {"metrics": {}, "daily_records": [{
        "period": "2026-11-10", "weekday": "Tuesday", "direction": "bullish", "range": 2,
        "complete": True}], "weekly_records": []}
    filtered = _apply_filters(result, {"session": "London"}, "daily-weekly", rows, 17)
    assert len(filtered["daily_records"]) == 1
    assert filtered["filter_summary"]["visible_records"] >= 1


def test_analytics_filter_recensors_daily_weekly_periods_to_selected_date_window():
    from app.routers.analytics import _apply_filters
    from app.engines.stats_engine import daily_weekly_statistics
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 8, 17, 0, tzinfo=ny)
    rows = []
    for i in range(48*60):
        dt = first + __import__('datetime').timedelta(minutes=i)
        price = 100 + i*0.0001
        rows.append(bar(int(dt.timestamp()*1000), price, price+0.1, price-0.1, price+0.02))
    full = daily_weekly_statistics(rows, day_start=17, bar_duration_ms=60_000)
    filtered = _apply_filters(full, {
        "start": "2026-11-09T18:00", "end": "2026-11-11T17:00"},
        "daily-weekly", rows, 17)
    tuesday = next(x for x in filtered["daily_records"] if x["period"] == "2026-11-10")
    assert tuesday["left_censored"] is True
    assert tuesday["complete"] is False


def test_aggregate_timeframe_marks_missing_source_minutes_unusable():
    rows = [bar(i*60_000, 100, 101+i*0.1, 99, 100.2) for i in (0, 1, 3, 4)]
    agg = aggregate_bars(rows, 5)
    assert len(agg) == 1
    assert agg[0]["complete"] is False
    assert agg[0]["source_count"] == 4
    assert agg[0]["expected_count"] == 5
    assert agg[0]["coverage_ratio"] == 0.8
    assert agg[0]["quality"] == "partial_bucket"
    assert agg[0]["analytics_usable"] is False


def test_session_statistics_excludes_incomplete_or_internally_gapped_sessions():
    from app.engines.stats_engine import session_statistics
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    rows = []
    for day in (9, 10):
        start = datetime(2026, 11, day, 2, 0, tzinfo=ny)
        for i in range(180):
            if day == 9 and i == 80:  # one missing M1 candle makes this window incomplete
                continue
            dt = start + __import__("datetime").timedelta(minutes=i)
            base = 100 + i*0.001
            rows.append(bar(int(dt.timestamp()*1000), base, base+0.2, base-0.2, base+0.05))
    result = session_statistics(rows, day_start=17, bar_duration_ms=60_000)
    london = [x for x in result["records"] if x["session"] == "London"]
    assert len(london) == 2
    assert london[0]["complete"] is False
    assert london[0]["has_internal_gaps"] is True
    assert london[0]["coverage_ratio"] < 1
    assert london[1]["complete"] is True
    assert result["metrics"]["complete_sessions"] == 1
    assert result["metrics"]["incomplete_sessions_excluded"] == 1
    assert result["metrics"]["by_session"] == {"London": 1}


def test_advanced_ict_uses_live_session_profile_instead_of_stale_import():
    from app.engines import advanced_ict, time_utils as runtime_time_utils
    original = dict(runtime_time_utils.SESSION_WINDOWS)
    try:
        set_session_windows({"Asia": (1200, 0), "London": (180, 360), "NY AM": (420, 600),
                             "London Close": (600, 720), "NY PM": (780, 960)})
        assert advanced_ict.time_utils.SESSION_WINDOWS["London"] == (180, 360)
    finally:
        set_session_windows(original)


def test_confluence_requires_sell_side_to_align_with_equal_lows_not_equal_highs():
    from unittest.mock import patch
    from app.engines.advanced_ict import _confluence_candidates
    rows = [bar(i*60_000, 100, 101, 99, 100) for i in range(100)]
    sweep = {"event": "sweep", "side": "sell-side", "timestamp": 10*60_000,
             "time": "2026-01-01T00:10:00-05:00", "level_type": "Asia Low", "level": 99}
    eqh = {"type": "EQH", "timestamp": 9*60_000}
    eql = {"type": "EQL", "timestamp": 9*60_000}
    with patch("app.engines.advanced_ict.liquidity_statistics", return_value={"records": [sweep]}):
        wrong = _confluence_candidates(rows, 17, 60_000, [], [eqh], [], [])
        right = _confluence_candidates(rows, 17, 60_000, [], [eql], [], [])
    assert wrong[0]["score"] == 2
    assert right[0]["score"] == 3


def test_forecast_metrics_reports_multiclass_diagnostics_and_reliability():
    from app.engines.forecast_engine import forecast_metrics
    runs = [
        {"payload": {"horizon_minutes": 15, "scenarios": [
            {"name": "Bullish expansion", "probability": 0.7},
            {"name": "Bearish expansion", "probability": 0.2},
            {"name": "Consolidation", "probability": 0.1}]},
         "outcome": {"scenario": "Bullish expansion"}},
        {"payload": {"horizon_minutes": 15, "scenarios": [
            {"name": "Bullish expansion", "probability": 0.2},
            {"name": "Bearish expansion", "probability": 0.6},
            {"name": "Consolidation", "probability": 0.2}]},
         "outcome": {"scenario": "Consolidation"}},
    ]
    result = forecast_metrics(runs)
    assert result["evaluated_runs"] == 2
    assert result["evaluated_by_horizon"] == {"15": 2}
    assert result["confusion_matrix"]["Consolidation"]["Bearish expansion"] == 1
    assert result["precision_recall_by_scenario"]["Bullish expansion"]["recall"] == 1
    assert sum(x["count"] for x in result["top_class_reliability_bins"]) == 2
    assert result["top_class_reliability_bins"][-1]["count"] == 1
    assert 0 <= result["brier_score"] <= 2


def test_session_token_hash_fails_closed_without_session_secret(monkeypatch):
    from app import security
    monkeypatch.setattr(security.settings, "session_secret", "")
    try:
        security.hash_token("example-token")
    except RuntimeError as exc:
        assert "ICTQL_SESSION_SECRET" in str(exc)
    else:
        raise AssertionError("Session tokens must not use a public development fallback secret")


def test_liquidity_opening_gap_is_not_counted_as_wick_sweep():
    from app.engines.stats_engine import _classify_level_interaction
    high_gap = bar(0, 102, 103, 100.5, 100.8)
    high_wick = bar(60_000, 100.5, 101.5, 100.2, 100.7)
    high_break = bar(120_000, 101.1, 101.8, 100.9, 101.4)
    assert _classify_level_interaction(high_gap, 101, "high")[0] == "gap_reclaim"
    assert _classify_level_interaction(high_wick, 101, "high")[0] == "sweep"
    assert _classify_level_interaction(high_break, 101, "high")[0] == "breakout"
    low_gap = bar(0, 98, 99.5, 97, 100.5)
    low_wick = bar(60_000, 100.5, 100.8, 99.0, 100.2)
    assert _classify_level_interaction(low_gap, 100, "low")[0] == "gap_reclaim"
    assert _classify_level_interaction(low_wick, 100, "low")[0] == "sweep"


def test_unfilled_fvg_is_right_censored_even_when_bars_are_contiguous():
    from app.engines.advanced_ict import detect_fvg
    start = 1_800_000_000_000
    rows = [
        bar(start, 9.0, 10.0, 8.5, 9.5),
        bar(start+60_000, 10.5, 11.5, 10.2, 11.2),
        bar(start+120_000, 11.2, 12.0, 11.0, 11.8),
        bar(start+180_000, 11.8, 12.2, 11.2, 11.9),
    ]
    bullish = next(x for x in detect_fvg(rows) if x["direction"] == "bullish")
    assert bullish["fill_time"] is None
    assert bullish["right_censored"] is True
    assert bullish["observation_data_incomplete"] is False


def test_cbdr_flags_internal_missing_bar_instead_of_98_percent_complete():
    from app.engines.advanced_ict import advanced_ict_statistics
    start = int(datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc).timestamp()*1000)
    rows = [bar(start+i*60_000,100,101+i*0.001,99,100+i*0.001) for i in range(360) if i != 180]
    result = advanced_ict_statistics(rows,day_start=17,bar_duration_ms=60_000)
    assert len(result["cbdr_records"]) == 1
    assert result["cbdr_records"][0]["complete"] is False
    assert result["cbdr_records"][0]["has_internal_gaps"] is True
    assert result["cbdr_records"][0]["coverage_ratio"] < 1


def test_forecast_outcome_uses_first_bar_after_non_aligned_asof():
    from app.routers.analytics import _realized_forecast_outcome
    start = 1_800_000_000_000
    rows = [bar(start+i*5*60_000, 100+i, 101+i, 99+i, 100.5+i) for i in range(8)]
    # As-of at minute 7: the M5 bar opening at minute 5 is not closed yet;
    # the next evaluable bar opens at minute 10.
    result = _realized_forecast_outcome(rows, start+7*60_000, 3, 1.0)
    assert result is not None
    assert result["horizon_bars"] == 3
    assert result["strictly_after_forecast_time"] is True


def test_liquidity_mss_does_not_call_missing_future_bar_a_negative(monkeypatch):
    from app.engines import stats_engine
    t0 = 1_800_000_000_000
    rows = [bar(t0+i*60_000, 100, 101, 99, 100) for i in range(80) if i != 22]
    fake_sweep = {"event": "sweep", "time": to_ny(t0+20*60_000).isoformat(),
                  "timestamp": t0+20*60_000, "trading_date": "2026-11-09",
                  "level_type": "PDH", "side": "buy-side", "session": "NY AM"}
    monkeypatch.setattr(stats_engine, "liquidity_statistics", lambda *a, **k: {"records": [fake_sweep]})
    monkeypatch.setattr(stats_engine, "market_structure_statistics", lambda *a, **k: {"records": []})
    result = stats_engine.liquidity_to_mss_statistics(rows, bar_duration_ms=60_000)
    row = result["records"][0]
    assert row["matches"]["5m"] is None
    assert row["data_incomplete"]["5m"] is True
    assert result["metrics"]["probability_by_horizon"]["5m"]["sample"] == 0
    assert result["metrics"]["probability_by_horizon"]["5m"]["data_incomplete"] == 1


def test_structure_events_remain_available_when_evaluation_horizon_is_below_bar_size():
    from app.engines.stats_engine import market_structure_statistics, run_module
    t0 = 1_800_000_000_000
    rows = [bar(t0+i*60_000, 10, 11+i*0.01, 9, 10+i*0.01) for i in range(120)]
    result = market_structure_statistics(rows, horizon=0)
    assert result["metrics"]["evaluation_status"] == "unresolvable_at_selected_timeframe"
    assert result["metrics"]["evaluated_signals"] == 0
    routed = run_module("structure", rows, structure_horizon_bars=0)
    assert routed["metrics"]["evaluation_horizon_bars"] == 0


def test_ctrader_client_secret_is_encrypted_and_survives_backend_reload(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    from app.config import settings
    from app.db import init_db
    from app.services import ctrader
    from app.services.store import get_value
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "persisted.sqlite3"))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "public_api_url", "https://api.example.test")
    init_db()
    secret = "test-client-secret-never-return-this"
    saved = ctrader.save_config({"client_id": "12345", "client_secret": secret,
                                 "environment": "demo", "scope": "accounts"})
    stored = get_value("ctrader_config", {})
    assert stored["client_secret_enc"] != secret
    assert ctrader._client_secret(stored) == secret
    # A new public-config read (as after a browser reload) preserves status,
    # while never returning the plaintext secret to the browser.
    reread = ctrader.public_config()
    assert reread["configured"] is True and reread["secret_saved"] is True
    assert "client_secret" not in reread and secret not in str(reread)
    assert saved["client_id"] == "12345"
    # Blank secret on later save means keep the previously encrypted value.
    ctrader.save_config({"client_id": "12345", "client_secret": None,
                         "redirect_uri": "https://api.example.test/api/v1/ctrader/oauth/callback",
                         "environment": "demo", "scope": "accounts"})
    assert ctrader._client_secret(ctrader.get_config()) == secret


def test_default_asia_session_midnight_boundary_is_complete_and_aligned():
    from app.engines.stats_engine import session_statistics, liquidity_statistics, _session_completeness, _session_groups
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 8, 20, 0, tzinfo=ny)  # Sunday 20:00 EST
    rows = []
    for i in range(240):
        dt = start + __import__("datetime").timedelta(minutes=i)
        px = 100 + i * 0.001
        rows.append(bar(int(dt.timestamp()*1000), px, px+0.1, px-0.1, px+0.02))
    groups = _session_groups(rows, day_start=17)
    quality = _session_completeness(groups, day_start=17, bar_duration_ms=60_000)
    assert len(groups) == 1
    key = next(iter(groups))
    assert key == ("2026-11-09", "Asia")
    assert quality[key]["complete"] is True
    assert quality[key]["expected_bars"] == 240
    result = session_statistics(rows, day_start=17, bar_duration_ms=60_000)
    assert result["records"][0]["complete"] is True
    levels = liquidity_statistics(rows, day_start=17, bar_duration_ms=60_000)["records"]
    assert {x["level_type"] for x in levels} >= {"Asia High", "Asia Low"}
