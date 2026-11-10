from __future__ import annotations
from collections import Counter, defaultdict
from datetime import timedelta, datetime, time as dt_time, date as dt_date
from math import sqrt
from statistics import mean, median
from app.engines import time_utils
from app.engines.time_utils import (
    to_ny, trading_date, trading_week, session_name,
    session_trade_date, SESSION_ORDER, infer_bar_duration_ms,
)


def _usable(bars):
    clean = [b for b in bars if b.get("analytics_usable", True)]
    return sorted(clean, key=lambda x: x["time"])


def _ci95(success: int, n: int):
    if n <= 0:
        return None
    p = success / n
    z = 1.96
    den = 1 + z*z/n
    center = (p + z*z/(2*n)) / den
    half = z * sqrt((p*(1-p)/n) + z*z/(4*n*n)) / den
    return [max(0.0, center-half), min(1.0, center+half)]


def _day_groups(bars, day_start=17):
    out = defaultdict(list)
    for b in bars:
        out[str(trading_date(b["time"], day_start))].append(b)
    return {k: sorted(v, key=lambda x: x["time"]) for k, v in out.items()}


def _week_groups(bars, day_start=17):
    out = defaultdict(list)
    for b in bars:
        out[str(trading_week(b["time"], day_start))].append(b)
    return {k: sorted(v, key=lambda x: x["time"]) for k, v in out.items()}


def _session_groups(bars, day_start=17):
    out = defaultdict(list)
    for b in bars:
        name = session_name(b["time"])
        if name != "Off-session":
            out[(str(session_trade_date(b["time"], day_start)), name)].append(b)
    return {k: sorted(v, key=lambda x: x["time"]) for k, v in out.items()}


def _session_completeness(groups, day_start=17, bar_duration_ms=None):
    """Check full session-window coverage, including missing minutes inside a window."""
    if not groups:
        return {}
    all_rows = [row for rows in groups.values() for row in rows]
    duration = int(bar_duration_ms or infer_bar_duration_ms(all_rows))
    windows = time_utils.SESSION_WINDOWS
    flags = {}
    for (label_text, name), rows in groups.items():
        if name not in windows:
            continue
        label = dt_date.fromisoformat(label_text)
        start_minute, end_minute = windows[name]
        start_date = label - timedelta(days=1) if day_start and start_minute >= day_start * 60 else label
        end_date = start_date
        if end_minute == 0 and start_minute > 0:
            normalized_end = 1440
            end_date += timedelta(days=1)
        elif end_minute == 1440:
            normalized_end = 1440
            end_date += timedelta(days=1)
        else:
            normalized_end = end_minute
            if normalized_end < start_minute:
                end_date += timedelta(days=1)
        start_dt = datetime.combine(
            start_date, dt_time(start_minute // 60, start_minute % 60), tzinfo=to_ny(rows[0]["time"]).tzinfo
        )
        end_hour, end_minute_of_day = divmod(normalized_end % 1440, 60)
        end_dt = datetime.combine(
            end_date, dt_time(end_hour, end_minute_of_day), tzinfo=to_ny(rows[-1]["time"]).tzinfo
        )
        if normalized_end == 1440:
            end_dt = datetime.combine(end_date, dt_time(0, 0), tzinfo=to_ny(rows[-1]["time"]).tzinfo)
        start_ms, end_ms = int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
        span = max(0, end_ms - start_ms)
        divisible = span > 0 and span % duration == 0
        expected_count = span // duration if divisible else 0
        expected_times = [start_ms + i * duration for i in range(expected_count)]
        actual_times = [int(row["time"]) for row in rows]
        complete = bool(divisible and actual_times == expected_times)
        coverage = (len(set(actual_times).intersection(expected_times)) / expected_count) if expected_count else 0.0
        flags[(label_text, name)] = {
            "complete": complete,
            "left_censored": not actual_times or actual_times[0] > start_ms,
            "right_censored": not actual_times or actual_times[-1] + duration < end_ms,
            "expected_start": start_dt.isoformat(),
            "expected_end": end_dt.isoformat(),
            "expected_bars": expected_count,
            "observed_bars": len(actual_times),
            "coverage_ratio": round(coverage, 6),
            "has_internal_gaps": bool(expected_count and not complete and
                                       actual_times[0] == start_ms and actual_times[-1] + duration == end_ms),
        }
    return flags



def _period_completeness(groups, day_start=17, kind="day", bar_duration_ms=None):
    """Check boundary and internal coverage for each daily/weekly window."""
    if not groups:
        return {}
    all_rows = [row for key in sorted(groups) for row in groups[key]]
    duration = int(bar_duration_ms or infer_bar_duration_ms(all_rows))
    flags = {}
    ny = to_ny(all_rows[0]["time"]).tzinfo
    for key in sorted(groups):
        label = dt_date.fromisoformat(key)
        if kind == "day":
            start_date = label - timedelta(days=1) if day_start else label
            end_date = label if day_start else label + timedelta(days=1)
        else:
            # Forex trading week opens Sunday at day_start and closes Friday at
            # the same clock time. A midnight profile uses calendar Mon–Mon.
            if day_start:
                start_date = label - timedelta(days=1)
                end_date = label + timedelta(days=4)
            else:
                start_date = label
                end_date = label + timedelta(days=7)
        start_dt = datetime.combine(start_date, dt_time(day_start), tzinfo=ny)
        end_dt = datetime.combine(end_date, dt_time(day_start), tzinfo=ny)
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        rows = sorted(groups[key], key=lambda x: x["time"])
        actual = [int(x["time"]) for x in rows]
        span = end_ms - start_ms
        divisible = span > 0 and span % duration == 0
        expected_count = span // duration if divisible else 0
        expected = [start_ms + i * duration for i in range(expected_count)]
        first_open = actual[0] if actual else None
        last_close = actual[-1] + duration if actual else None
        left = first_open is None or first_open > start_ms
        right = last_close is None or last_close < end_ms
        coverage = (len(set(actual).intersection(expected)) / expected_count) if expected_count else 0.0
        has_internal_gaps = bool(expected_count and not (left or right) and actual != expected)
        complete = bool(divisible and actual == expected)
        flags[key] = {
            "left_censored": left, "right_censored": right,
            "has_internal_gaps": has_internal_gaps,
            "complete": complete,
            "expected_start": start_dt.isoformat(), "expected_end": end_dt.isoformat(),
            "expected_bars": expected_count, "observed_bars": len(actual),
            "coverage_ratio": round(coverage, 6),
        }
    return flags


def _range_summary(rows):
    high_bar = max(rows, key=lambda x: x["high"])
    low_bar = min(rows, key=lambda x: x["low"])
    start, end = rows[0], rows[-1]
    return {
        "open": start["open"], "close": end["close"],
        "high": high_bar["high"], "low": low_bar["low"],
        "range": high_bar["high"] - low_bar["low"],
        "direction": "bullish" if end["close"] > start["open"] else "bearish" if end["close"] < start["open"] else "flat",
        # OHLC only resolves the extreme to its source candle, not an exact tick time.
        "high_time": to_ny(high_bar["time"]).isoformat(),
        "low_time": to_ny(low_bar["time"]).isoformat(),
        "bars": len(rows),
    }


def _bar_end_ms(bars, index):
    return int(bars[index]["time"]) + infer_bar_duration_ms(bars)


def _gap_progress(gap, scan_rows, scan_all_bars, duration_ms):
    top, bottom = gap["top"], gap["bottom"]
    size, direction = gap["size"], gap["direction"]
    thresholds = (25, 50, 75, 100)
    fills = {pct: None for pct in thresholds}
    sessions = {pct: None for pct in thresholds}
    bars_to_fill = {pct: None for pct in thresholds}
    max_fill = 0.0
    threshold_indices = {}
    index_by_time = {int(bar["time"]): i for i, bar in enumerate(scan_all_bars)}
    for idx, bar in enumerate(scan_rows):
        penetration = ((top - bar["low"]) / size if direction == "up"
                       else (bar["high"] - bottom) / size)
        max_fill = max(max_fill, max(0.0, min(1.0, penetration)))
        for pct in thresholds:
            if fills[pct] is None and max_fill >= pct / 100:
                fills[pct] = to_ny(bar["time"] + duration_ms).isoformat()
                sessions[pct] = session_name(bar["time"])
                bars_to_fill[pct] = idx + 1
                threshold_indices[pct] = index_by_time.get(int(bar["time"]), idx)

    reactions = {}
    for pct in (50, 100):
        idx = threshold_indices.get(pct)
        if idx is None:
            reactions[str(pct)] = None
            continue
        event_bar = scan_all_bars[idx]
        event_ms = int(event_bar["time"]) + duration_ms
        fill_level = top - size * pct / 100 if direction == "up" else bottom + size * pct / 100
        result = {}
        for mins in (15, 30, 60):
            window_ms = mins * 60_000
            if duration_ms <= 0 or window_ms % duration_ms:
                result[f"{mins}m"] = {"value": None, "right_censored": False,
                                      "data_incomplete": True, "reason": "horizon_not_resolvable_at_selected_timeframe"}
                continue
            expected_count = window_ms // duration_ms
            future = [x for x in scan_all_bars if event_ms <= int(x["time"]) < event_ms + window_ms]
            expected_times = [event_ms + j * duration_ms for j in range(expected_count)]
            actual_times = [int(x["time"]) for x in future]
            if actual_times != expected_times:
                last_close = int(scan_all_bars[-1]["time"]) + duration_ms if scan_all_bars else 0
                is_censored = last_close < event_ms + window_ms
                observed_expected = [event_ms + j * duration_ms for j in range(expected_count)
                                     if event_ms + (j + 1) * duration_ms <= last_close]
                internal_gap = actual_times != observed_expected
                result[f"{mins}m"] = {"value": None, "right_censored": is_censored,
                                      "data_incomplete": internal_gap,
                                      "reason": "insufficient_future_bars" if is_censored else "internal_data_gap"}
                continue
            close_move = (future[-1]["close"] - fill_level) / size
            if direction == "up":
                favorable = (max(x["high"] for x in future) - fill_level) / size
                adverse = (fill_level - min(x["low"] for x in future)) / size
            else:
                favorable = (fill_level - min(x["low"] for x in future)) / size
                adverse = (max(x["high"] for x in future) - fill_level) / size
            result[f"{mins}m"] = {"value": {"close_move_gap_units": close_move,
                                             "favorable_excursion_gap_units": favorable,
                                             "adverse_excursion_gap_units": adverse},
                                  "right_censored": False, "data_incomplete": False, "reason": None}
        reactions[str(pct)] = result
    return {
        "max_fill_pct": round(max_fill * 100, 2),
        "fill_25": fills[25], "fill_50": fills[50], "fill_75": fills[75], "fill_100": fills[100],
        "fill_25_session": sessions[25], "fill_50_session": sessions[50],
        "fill_75_session": sessions[75], "fill_100_session": sessions[100],
        "bars_to_fill_25": bars_to_fill[25], "bars_to_fill_50": bars_to_fill[50],
        "bars_to_fill_75": bars_to_fill[75], "bars_to_fill_100": bars_to_fill[100],
        "fill_time": fills[100], "filled": fills[100] is not None,
        "reaction_after_fill": reactions,
    }


def gap_statistics(bars, day_start=17):
    b = _usable(bars)
    if len(b) < 2:
        return {"metrics": {"ndog_count": 0, "nwog_count": 0}, "records": []}
    duration = infer_bar_duration_ms(b)
    days, weeks = _day_groups(b, day_start), _week_groups(b, day_start)
    day_quality = _period_completeness(days, day_start, "day", duration)
    week_quality = _period_completeness(weeks, day_start, "week", duration)
    records = []
    day_keys = sorted(days)
    for i in range(1, len(day_keys)):
        prev, cur = days[day_keys[i-1]], days[day_keys[i]]
        prev_quality = day_quality.get(day_keys[i-1], {})
        cur_quality = day_quality.get(day_keys[i], {})
        if not prev_quality.get("complete", False) or cur_quality.get("left_censored"):
            continue
        prev_close, cur_open = prev[-1]["close"], cur[0]["open"]
        if abs(cur_open-prev_close) <= 1e-12:
            continue
        direction = "up" if cur_open > prev_close else "down"
        gap = {"type": "NDOG", "date": day_keys[i], "direction": direction,
               "top": max(prev_close, cur_open), "bottom": min(prev_close, cur_open),
               "size": abs(cur_open-prev_close), "created_time": to_ny(cur[0]["time"]).isoformat()}
        scan = cur
        gap.update(_gap_progress(gap, scan, b, duration))
        gap["observation_window"] = "trading_day"
        fill_idx = gap.get("bars_to_fill_100")
        observed_path = scan[:fill_idx] if fill_idx else scan
        observed_times = [int(x["time"]) for x in observed_path]
        path_complete = bool(observed_times) and all(observed_times[j] - observed_times[j-1] == duration for j in range(1, len(observed_times)))
        gap["right_censored"] = bool(not gap["filled"] and cur_quality.get("right_censored", False))
        gap["observation_data_incomplete"] = bool(not path_complete)
        records.append(gap)

    week_keys = sorted(weeks)
    for i in range(1, len(week_keys)):
        prev, cur = weeks[week_keys[i-1]], weeks[week_keys[i]]
        prev_quality = week_quality.get(week_keys[i-1], {})
        cur_quality = week_quality.get(week_keys[i], {})
        if not prev_quality.get("complete", False) or cur_quality.get("left_censored"):
            continue
        pclose, copen = prev[-1]["close"], cur[0]["open"]
        if abs(copen-pclose) <= 1e-12:
            continue
        direction = "up" if copen > pclose else "down"
        gap = {"type": "NWOG", "date": week_keys[i], "direction": direction,
               "top": max(pclose, copen), "bottom": min(pclose, copen),
               "size": abs(copen-pclose), "created_time": to_ny(cur[0]["time"]).isoformat()}
        gap.update(_gap_progress(gap, cur, b, duration))
        gap["observation_window"] = "trading_week"
        fill_idx = gap.get("bars_to_fill_100")
        observed_path = cur[:fill_idx] if fill_idx else cur
        observed_times = [int(x["time"]) for x in observed_path]
        path_complete = bool(observed_times) and all(observed_times[j] - observed_times[j-1] == duration for j in range(1, len(observed_times)))
        gap["right_censored"] = bool(not gap["filled"] and cur_quality.get("right_censored", False))
        gap["observation_data_incomplete"] = bool(not path_complete)
        records.append(gap)

    metrics = {}
    for label in ("NDOG", "NWOG"):
        subset = [x for x in records if x["type"] == label]
        observed = [x for x in subset if not x["right_censored"] and not x.get("observation_data_incomplete", False)]
        filled = sum(x["filled"] for x in observed)
        metrics[f"{label.lower()}_count"] = len(subset)
        metrics[f"{label.lower()}_fully_filled_observed"] = len(observed)
        metrics[f"{label.lower()}_fill_rate"] = filled/len(observed) if observed else None
        metrics[f"{label.lower()}_fill_rate_ci95"] = _ci95(filled, len(observed))
        metrics[f"{label.lower()}_median_gap_size"] = median([x["size"] for x in subset]) if subset else None
        metrics[f"{label.lower()}_threshold_rates"] = {
            str(p): (sum(x[f"fill_{p}"] is not None for x in observed)/len(observed) if observed else None)
            for p in (25, 50, 75, 100)
        }
    return {"metrics": metrics, "records": records,
            "methodology": "Gap fill is measured from the opening gap boundary using the observed wick. NDOG is observed through its trading day; NWOG through its trading week. A fully observed 100% fill is a terminal outcome even if the surrounding period later ends early. Unfilled truncated gaps are right-censored; an internal gap before the outcome makes the path data-incomplete."}


def _classify_level_interaction(bar, level, side):
    """Classify the first interaction without calling an opening gap a wick sweep."""
    op, high, low, close = (float(bar[k]) for k in ("open", "high", "low", "close"))
    level = float(level)
    if side == "high":
        if high < level:
            return None, "not_touched"
        if op > level and close < level:
            return "gap_reclaim", "opened_above_and_closed_back_below"
        if high == level:
            return "probe", "exact_wick_touch"
        if op <= level and high > level and close < level:
            return "sweep", "wick_penetration_and_same_bar_close_inside"
        return "breakout", "close_not_back_inside_or_opened_beyond"
    if low > level:
        return None, "not_touched"
    if op < level and close > level:
        return "gap_reclaim", "opened_below_and_closed_back_above"
    if low == level:
        return "probe", "exact_wick_touch"
    if op >= level and low < level and close > level:
        return "sweep", "wick_penetration_and_same_bar_close_inside"
    return "breakout", "close_not_back_inside_or_opened_beyond"


def liquidity_statistics(bars, day_start=17, reclaim_window=30, bar_duration_ms=None):
    b = _usable(bars)
    days, weeks, sessions = _day_groups(b, day_start), _week_groups(b, day_start), _session_groups(b, day_start)
    records = []
    day_keys, week_keys = sorted(days), sorted(weeks)
    day_levels, week_levels = {}, {}
    day_quality = _period_completeness(days, day_start, "day", bar_duration_ms)
    week_quality = _period_completeness(weeks, day_start, "week", bar_duration_ms)
    session_quality = _session_completeness(sessions, day_start, bar_duration_ms)
    for i, key in enumerate(day_keys):
        if i and day_quality.get(day_keys[i-1], {}).get("complete", True):
            prior = days[day_keys[i-1]]
            day_levels[key] = [("PDH", max(x["high"] for x in prior), "high"),
                               ("PDL", min(x["low"] for x in prior), "low")]
        else:
            day_levels[key] = []
        asia = sessions.get((key, "Asia"), [])
        if asia and session_quality.get((key, "Asia"), {}).get("complete", False):
            day_levels[key].extend([("Asia High", max(x["high"] for x in asia), "high"),
                                    ("Asia Low", min(x["low"] for x in asia), "low")])
    for i, key in enumerate(week_keys):
        if i and week_quality.get(week_keys[i-1], {}).get("complete", True):
            prior = weeks[week_keys[i-1]]
            week_levels[key] = [("PWH", max(x["high"] for x in prior), "high"),
                                ("PWL", min(x["low"] for x in prior), "low")]
        else:
            week_levels[key] = []

    for key in day_keys:
        rows = days[key]
        base_time = rows[0]["time"]
        levels = day_levels.get(key, []) + week_levels.get(str(trading_week(base_time, day_start)), [])
        for level_name, level, side in levels:
            hit = None
            for idx, bar in enumerate(rows):
                if side == "high" and bar["high"] >= level:
                    hit = (idx, bar, max(0.0, bar["high"]-level))
                    break
                if side == "low" and bar["low"] <= level:
                    hit = (idx, bar, max(0.0, level-bar["low"]))
                    break
            if not hit:
                continue
            idx, bar, penetration = hit
            event, classification_reason = _classify_level_interaction(bar, level, side)
            if event is None:
                continue
            reclaim_time = (to_ny(bar["time"] + infer_bar_duration_ms(rows)).isoformat()
                            if event in {"sweep", "gap_reclaim"} else None)
            if event == "breakout":
                for later in rows[idx+1:idx+1+reclaim_window]:
                    reclaimed = later["close"] < level if side == "high" else later["close"] > level
                    if reclaimed:
                        reclaim_time = to_ny(later["time"] + infer_bar_duration_ms(rows)).isoformat()
                        break
            event_time = int(bar["time"] + infer_bar_duration_ms(rows))
            records.append({
                "time": to_ny(event_time).isoformat(), "timestamp": event_time,
                "trading_date": key, "level_type": level_name, "level": level,
                "side": "buy-side" if side == "high" else "sell-side", "event": event,
                "penetration": penetration, "open_price": bar["open"], "close_price": bar["close"],
                "reclaimed": reclaim_time is not None, "reclaim_time": reclaim_time,
                "classification_reason": classification_reason,
                "session": session_name(bar["time"]),
                "bar_time": bar["time"], "confirmation_rule": "first level interaction; wick sweep requires open on the inside, wick penetration and same-bar close back inside; opening gaps are separate",
            })
    records.sort(key=lambda x: x["timestamp"])
    sweeps = [x for x in records if x["event"] == "sweep"]
    daily_summary = []
    by_day = defaultdict(list)
    for row in records:
        by_day[row["trading_date"]].append(row)
    for day, rows in sorted(by_day.items()):
        day_sweeps = [x for x in rows if x["event"] == "sweep"]
        buy = any(x["side"] == "buy-side" for x in day_sweeps)
        sell = any(x["side"] == "sell-side" for x in day_sweeps)
        first = min(day_sweeps, key=lambda x: x["timestamp"]) if day_sweeps else None
        daily_summary.append({"date": day, "buy_side_swept": buy, "sell_side_swept": sell,
                              "both_sides_swept": buy and sell,
                              "first_liquidity_taken": first["level_type"] if first else None,
                              "first_sweep_time": first["time"] if first else None})
    n = len(records)
    return {"metrics": {
        "levels_tested": n, "sweep_count": len(sweeps),
        "sweep_rate": len(sweeps)/n if n else None,
        "sweep_rate_ci95": _ci95(len(sweeps), n),
        "probe_count": sum(x["event"] == "probe" for x in records),
        "gap_reclaim_count": sum(x["event"] == "gap_reclaim" for x in records),
        "breakout_count": sum(x["event"] == "breakout" for x in records),
        "buy_side_sweeps": sum(x["side"] == "buy-side" for x in sweeps),
        "sell_side_sweeps": sum(x["side"] == "sell-side" for x in sweeps),
        "reclaim_rate": sum(x["reclaimed"] for x in records)/n if n else None,
        "days_both_sides_swept": sum(x["both_sides_swept"] for x in daily_summary),
        "first_liquidity_taken": Counter(x["first_liquidity_taken"] for x in daily_summary if x["first_liquidity_taken"]).most_common(),
    }, "records": records, "daily_summary": daily_summary,
       "methodology": "A wick sweep requires the bar to open on the inside, penetrate the level and close back inside. Opening beyond a level and closing back through it is classified separately as gap_reclaim, not a wick sweep. A close beyond is breakout; a later close back through is reclaim. One first interaction is recorded per level/day."}


def session_statistics(bars, day_start=17, bar_duration_ms=None):
    b = _usable(bars)
    groups = _session_groups(b, day_start)
    duration = int(bar_duration_ms or infer_bar_duration_ms(b))
    completeness = _session_completeness(groups, day_start, duration)
    rows = []
    by_day = defaultdict(list)
    for (day, name), items in groups.items():
        summary = _range_summary(items)
        quality = completeness.get((day, name), {})
        summary.update({"date": day, "session": name,
                        "start": to_ny(items[0]["time"]).isoformat(),
                        "end": to_ny(items[-1]["time"] + duration).isoformat(),
                        "sequence": SESSION_ORDER.get(name, 99),
                        **quality})
        by_day[day].append(summary)
    for day, sessions in sorted(by_day.items()):
        sessions.sort(key=lambda x: x["sequence"])
        previous_complete = None
        for row in sessions:
            if not row["complete"]:
                row["relationship_to_previous_session"] = "unclassified_incomplete"
            elif previous_complete and row["sequence"] == previous_complete["sequence"] + 1:
                if previous_complete["direction"] in ("bullish", "bearish") and row["direction"] in ("bullish", "bearish"):
                    row["relationship_to_previous_session"] = "continuation" if row["direction"] == previous_complete["direction"] else "reversal"
                else:
                    row["relationship_to_previous_session"] = "unclassified"
            else:
                row["relationship_to_previous_session"] = "unclassified"
            if row["complete"]:
                previous_complete = row
            else:
                previous_complete = None
            rows.append(row)
    complete_rows = [x for x in rows if x["complete"]]
    counts = Counter(x["session"] for x in complete_rows)
    rel = Counter(x["relationship_to_previous_session"] for x in complete_rows)
    return {"metrics": {"sessions": len(rows), "complete_sessions": len(complete_rows),
                        "incomplete_sessions_excluded": len(rows) - len(complete_rows),
                        "by_session": dict(counts),
                        "continuation_count": rel["continuation"], "reversal_count": rel["reversal"],
                        "median_range": median([x["range"] for x in complete_rows]) if complete_rows else None,
                        "median_range_by_session": {k: median([x["range"] for x in complete_rows if x["session"] == k]) for k in counts}},
            "records": rows,
            "methodology": "Session ranges and continuation/reversal baselines use only windows with complete expected bar coverage (including no internal missing bars). Incomplete windows remain visible in records with coverage and censoring fields but are excluded from aggregate metrics. Windows are New York-time and use the configured editable session profile."}


def time_statistics(bars, day_start=17):
    b = _usable(bars)
    days = _day_groups(b, day_start)
    completeness = _period_completeness(days, day_start, "day", infer_bar_duration_ms(b))
    complete_days = {key: rows for key, rows in days.items()
                     if completeness.get(key, {}).get("complete", False)}
    high_hours, low_hours, reversal_hours = Counter(), Counter(), Counter()
    ranges, reversals = [], []
    for day, rows in complete_days.items():
        high = max(rows, key=lambda x: x["high"])
        low = min(rows, key=lambda x: x["low"])
        high_hours[to_ny(high["time"]).hour] += 1
        low_hours[to_ny(low["time"]).hour] += 1
        ranges.append(_range_summary(rows)["range"])
    duration = infer_bar_duration_ms(b)
    for i in range(1, len(b)):
        prev, cur = b[i-1], b[i]
        if int(cur["time"]) - int(prev["time"]) != duration:
            continue
        if prev["close"] > prev["open"] and cur["close"] < prev["low"]:
            dt = to_ny(cur["time"] + duration)
            reversals.append({"time": dt.isoformat(), "timestamp": int(dt.timestamp()*1000),
                              "direction": "bearish", "hour": dt.strftime("%H:%M")})
            reversal_hours[dt.hour] += 1
        elif prev["close"] < prev["open"] and cur["close"] > prev["high"]:
            dt = to_ny(cur["time"] + duration)
            reversals.append({"time": dt.isoformat(), "timestamp": int(dt.timestamp()*1000),
                              "direction": "bullish", "hour": dt.strftime("%H:%M")})
            reversal_hours[dt.hour] += 1
    heat = [{"hour": h, "high_formation_days": high_hours[h], "low_formation_days": low_hours[h],
             "reversal_candidates": reversal_hours[h]} for h in range(24)]
    return {"metrics": {"days": len(days), "median_daily_range": median(ranges) if ranges else None,
                         "high_formation_by_hour": high_hours.most_common(),
                         "low_formation_by_hour": low_hours.most_common(),
                         "reversal_by_hour": reversal_hours.most_common(),
                         "high_formation_times": Counter(to_ny(max(rows, key=lambda x:x["high"])["time"]).strftime("%H:%M") for rows in complete_days.values()).most_common(12),
                         "low_formation_times": Counter(to_ny(min(rows, key=lambda x:x["low"])["time"]).strftime("%H:%M") for rows in complete_days.values()).most_common(12),
                         "complete_days": len(complete_days),
                         "incomplete_days_excluded": len(days) - len(complete_days),
                         "reversal_candidates": len(reversals), "hourly_heatmap": heat},
            "records": reversals,
            "methodology": "High/low formation-time and daily-range distributions use complete trading days only; partial edge days are excluded. Reversal candidates use all clean adjacent bars and are timestamped at confirmation-bar close."}


def structure_events(bars, left=2, right=2):
    bars = _usable(bars)
    pivots_high = {}; pivots_low = {}
    events = []; last_high = None; last_low = None; bias = 0
    duration = infer_bar_duration_ms(bars)
    # A pivot becomes usable only at confirm_idx. Event is timestamped at the
    # confirmation candle close (bar open + nominal interval), never at pivot time.
    for confirm_idx in range(left + right, len(bars)):
        pivot_idx = confirm_idx-right
        window = bars[pivot_idx-left:pivot_idx+right+1]
        if len(window) != left + right + 1 or any(
            int(window[j]["time"]) - int(window[j-1]["time"]) != duration
            for j in range(1, len(window))
        ):
            continue
        pivot = bars[pivot_idx]
        if pivot["high"] == max(x["high"] for x in window) and sum(x["high"] == pivot["high"] for x in window) == 1:
            last_high = {"price": pivot["high"], "pivot_idx": pivot_idx, "confirmed_idx": confirm_idx}
            pivots_high[pivot_idx] = last_high
        if pivot["low"] == min(x["low"] for x in window) and sum(x["low"] == pivot["low"] for x in window) == 1:
            last_low = {"price": pivot["low"], "pivot_idx": pivot_idx, "confirmed_idx": confirm_idx}
            pivots_low[pivot_idx] = last_low
        bar = bars[confirm_idx]
        prev_bar = bars[confirm_idx-1]
        # Only infer an observed candle cross when adjacent data are continuous
        # and the current candle opened on the pre-break side of the level.
        if int(bar["time"]) - int(prev_bar["time"]) != duration:
            continue
        event_type = None; direction = None; broken_level = None
        if (last_high and confirm_idx > last_high["confirmed_idx"]
                and bar["open"] <= last_high["price"] < bar["close"]
                and prev_bar["close"] <= last_high["price"]):
            direction, broken_level = "bullish", last_high["price"]
            event_type = "MSS" if bias == -1 else "BOS"
            bias = 1
        elif (last_low and confirm_idx > last_low["confirmed_idx"]
                and bar["open"] >= last_low["price"] > bar["close"]
                and prev_bar["close"] >= last_low["price"]):
            direction, broken_level = "bearish", last_low["price"]
            event_type = "MSS" if bias == 1 else "BOS"
            bias = -1
        if event_type:
            close_time = int(bar["time"] + duration)
            events.append({"type": event_type, "direction": direction, "time": close_time,
                           "time_ny": to_ny(close_time).isoformat(), "timestamp": close_time,
                           "bar_time": bar["time"], "price": bar["close"], "broken_level": broken_level,
                           "pivot_time": bars[last_high["pivot_idx"] if direction == "bullish" else last_low["pivot_idx"]]["time"],
                           "pivot_confirmation_time": to_ny(bars[last_high["confirmed_idx"] if direction == "bullish" else last_low["confirmed_idx"]]["time"] + duration).isoformat(),
                           "confirmation_time": to_ny(close_time).isoformat(),
                           "swing_low": last_low["price"] if last_low else None,
                           "swing_high": last_high["price"] if last_high else None})
    return events


def market_structure_statistics(bars, horizon=60):
    clean = _usable(bars)
    events = structure_events(clean)
    evaluations = []
    if horizon <= 0:
        return {"metrics": {"bos_count": sum(x["type"] == "BOS" for x in events),
                            "mss_count": sum(x["type"] == "MSS" for x in events),
                            "evaluated_signals": 0, "right_censored_signals": 0,
                            "data_gap_signals_excluded": 0, "ambiguous_intrabar_cases": 0,
                            "target_rate_sample": 0, "evaluation_horizon_bars": 0,
                            "evaluation_status": "unresolvable_at_selected_timeframe"},
                "records": events, "evaluations": [],
                "methodology": "BOS/MSS event detection is available, but the requested forward evaluation horizon is shorter than one selected timeframe bar and is therefore not evaluated."}
    right_censored = 0
    data_gap_signals = 0
    duration = infer_bar_duration_ms(clean)
    index_by_time = {x["time"]: i for i, x in enumerate(clean)}
    for event in events:
        idx = index_by_time.get(event["bar_time"])
        if idx is None or idx + horizon >= len(clean):
            right_censored += 1
            continue
        future = clean[idx+1:idx+1+horizon]
        if len(future) != horizon:
            right_censored += 1
            continue
        if any(int(future[j]["time"]) - int(future[j-1]["time"]) != duration for j in range(1, len(future))) or (future and int(future[0]["time"]) - int(clean[idx]["time"]) != duration):
            data_gap_signals += 1
            continue
        entry = event["price"]
        if event["direction"] == "bullish":
            invalid = event.get("swing_low")
            if invalid is None or invalid >= entry: continue
            risk = entry-invalid
            mfe = max(x["high"] for x in future)-entry
            mae = entry-min(x["low"] for x in future)
            target_hit = {r: next((j for j, x in enumerate(future) if x["high"] >= entry+r*risk), None) for r in (1,2,3)}
            invalid_hit = next((j for j, x in enumerate(future) if x["low"] <= invalid), None)
            ambiguous = invalid_hit is not None and any(j is not None and j == invalid_hit for j in target_hit.values())
        else:
            invalid = event.get("swing_high")
            if invalid is None or invalid <= entry: continue
            risk = invalid-entry
            mfe = entry-min(x["low"] for x in future)
            mae = max(x["high"] for x in future)-entry
            target_hit = {r: next((j for j, x in enumerate(future) if x["low"] <= entry-r*risk), None) for r in (1,2,3)}
            invalid_hit = next((j for j, x in enumerate(future) if x["high"] >= invalid), None)
            ambiguous = invalid_hit is not None and any(j is not None and j == invalid_hit for j in target_hit.values())
        targets = {f"{r}R": (target_hit[r] is not None and (invalid_hit is None or target_hit[r] < invalid_hit)) for r in (1,2,3)}
        first_target = min((j, r) for r, j in target_hit.items() if j is not None and (invalid_hit is None or j < invalid_hit)) if any(j is not None and (invalid_hit is None or j < invalid_hit) for j in target_hit.values()) else None
        evaluations.append({"time": event["time_ny"], "timestamp": event["time"],
                            "direction": event["direction"], "mfe": mfe, "mae": mae,
                            "risk": risk, "targets": targets, "invalidated": invalid_hit is not None,
                            "ambiguous": ambiguous, "first_target": f"{first_target[1]}R" if first_target else None,
                            "bars_to_first_target": first_target[0]+1 if first_target else None,
                            "bars_to_invalidation": invalid_hit+1 if invalid_hit is not None else None,
                            "horizon_bars": len(future)})
    valid = [x for x in evaluations if not x["ambiguous"]]
    n = len(evaluations)
    metrics = {"bos_count": sum(x["type"] == "BOS" for x in events),
               "mss_count": sum(x["type"] == "MSS" for x in events),
               "evaluated_signals": n,
               "right_censored_signals": right_censored,
               "data_gap_signals_excluded": data_gap_signals,
               "evaluation_horizon_bars": horizon,
               "evaluation_status": "ok",
               "mean_mfe": mean([x["mfe"] for x in evaluations]) if n else None,
               "mean_mae": mean([x["mae"] for x in evaluations]) if n else None,
               "target_rates": {f"{r}R": sum(x["targets"][f"{r}R"] for x in valid)/len(valid) if valid else None for r in (1,2,3)},
               "target_rate_sample": len(valid),
               "ambiguous_intrabar_cases": n-len(valid),
               "median_bars_to_first_target": median([x["bars_to_first_target"] for x in evaluations if x["bars_to_first_target"]]) if any(x["bars_to_first_target"] for x in evaluations) else None}
    return {"metrics": metrics, "records": events, "evaluations": evaluations,
            "methodology": "Pivot requires 2 consecutive bars on each side and is only activated after confirmation. Break events are timestamped at confirmation-bar close. MFE/MAE use exactly the next `horizon` bars with continuous timestamp coverage; signals without a full right-side horizon are right-censored, and signals crossing source-data gaps are excluded separately. Same-bar TP/SL ambiguity is excluded from target-rate denominator."}


def daily_weekly_statistics(bars, day_start=17, bar_duration_ms=None):
    clean = _usable(bars)
    days = _day_groups(clean, day_start)
    weeks = _week_groups(clean, day_start)
    day_quality = _period_completeness(days, day_start, "day", bar_duration_ms)
    week_quality = _period_completeness(weeks, day_start, "week", bar_duration_ms)
    daily_rows = []
    for key, rows in sorted(days.items()):
        row = _range_summary(rows)
        row["period"] = key
        row["weekday"] = dt_date.fromisoformat(key).strftime("%A")
        row.update(day_quality.get(key, {}))
        daily_rows.append(row)
    weekly_rows = []
    for key, rows in sorted(weeks.items()):
        row = _range_summary(rows)
        row["period"] = key
        row.update(week_quality.get(key, {}))
        weekly_rows.append(row)
    completed_days = [x for x in daily_rows if x.get("complete")]
    completed_weeks = [x for x in weekly_rows if x.get("complete")]
    weekday = defaultdict(list)
    for row in completed_days:
        weekday[row["weekday"]].append(row)
    weekday_stats = {k: {"samples": len(v),
                         "bullish_rate": sum(x["direction"] == "bullish" for x in v)/len(v),
                         "bullish_rate_ci95": _ci95(sum(x["direction"] == "bullish" for x in v), len(v)),
                         "median_range": median(x["range"] for x in v)} for k, v in weekday.items()}
    return {"metrics": {"days": len(daily_rows), "complete_days": len(completed_days),
                         "incomplete_days_excluded": len(daily_rows)-len(completed_days),
                         "weeks": len(weekly_rows), "complete_weeks": len(completed_weeks),
                         "incomplete_weeks_excluded": len(weekly_rows)-len(completed_weeks),
                         "weekday_statistics": weekday_stats,
                         "bullish_days": sum(x["direction"] == "bullish" for x in completed_days),
                         "bearish_days": sum(x["direction"] == "bearish" for x in completed_days),
                         "weekly_direction_counts": dict(Counter(x["direction"] for x in completed_weeks)),
                         "median_daily_range": median([x["range"] for x in completed_days]) if completed_days else None,
                         "median_weekly_range": median([x["range"] for x in completed_weeks]) if completed_weeks else None},
            "daily_records": daily_rows, "weekly_records": weekly_rows,
            "methodology": "Trading date labels the close-date of the session (Forex default: Sunday 17:00 NY through Monday 16:59 is Monday's trading date). The first/last truncated daily and weekly groups are retained in records but excluded from completed-period direction/range statistics. Weekly boundary defaults to Sunday 17:00–Friday 17:00 New York."}

def liquidity_to_mss_statistics(bars, day_start=17, bar_duration_ms=None):
    liquidity = liquidity_statistics(bars, day_start=day_start, bar_duration_ms=bar_duration_ms)
    structure = market_structure_statistics(bars, horizon=1)
    clean = _usable(bars)
    duration = int(bar_duration_ms or infer_bar_duration_ms(clean))
    final_close = int(clean[-1]["time"]) + duration if clean else 0
    sweeps = [x for x in liquidity["records"] if x["event"] == "sweep"]
    mss = [x for x in structure["records"] if x["type"] == "MSS"]
    horizons = (5, 15, 30, 60)
    rows = []
    for sweep in sweeps:
        expected = "bearish" if sweep["side"] == "buy-side" else "bullish"
        matched = {}
        censored = {}
        incomplete = {}
        for horizon in horizons:
            key = f"{horizon}m"
            window_ms = horizon * 60_000
            # A horizon must contain a whole number of selected timeframe bars.
            if duration <= 0 or window_ms % duration:
                matched[key] = None
                censored[key] = False
                incomplete[key] = True
                continue
            window_end = int(sweep["timestamp"]) + window_ms
            expected_count = window_ms // duration
            future = [x for x in clean if int(sweep["timestamp"]) <= int(x["time"]) < window_end]
            expected_times = [int(sweep["timestamp"]) + j * duration for j in range(expected_count)]
            actual_times = [int(x["time"]) for x in future]
            full_window_observed = final_close >= window_end
            is_complete = actual_times == expected_times
            censored[key] = not full_window_observed
            incomplete[key] = bool(full_window_observed and not is_complete)
            if not full_window_observed or not is_complete:
                matched[key] = None
                continue
            found = next((x for x in mss
                          if int(sweep["timestamp"]) < int(x["time"]) <= window_end
                          and x["direction"] == expected), None)
            matched[key] = bool(found)
        rows.append({"time": sweep["time"], "timestamp": sweep["timestamp"],
                     "trading_date": sweep["trading_date"], "liquidity": sweep["level_type"],
                     "side": sweep["side"], "expected_mss": expected,
                     "session": sweep["session"], "matches": matched,
                     "right_censored": censored, "data_incomplete": incomplete})
    matrix = {}
    for h in horizons:
        key = f"{h}m"
        valid = [r for r in rows if r["matches"][key] is not None]
        successes = sum(bool(r["matches"][key]) for r in valid)
        matrix[key] = {"success": successes, "sample": len(valid),
                       "right_censored": sum(bool(r["right_censored"][key]) for r in rows),
                       "data_incomplete": sum(bool(r["data_incomplete"][key]) for r in rows),
                       "probability": successes/len(valid) if valid else None,
                       "ci95": _ci95(successes, len(valid))}
    breakdown = {}
    for key in sorted({(r["liquidity"], r["session"]) for r in rows}):
        subset = [r for r in rows if (r["liquidity"], r["session"]) == key]
        breakdown[f"{key[0]} | {key[1]}"] = {}
        for h in horizons:
            horizon_key = f"{h}m"
            valid = [x for x in subset if x["matches"][horizon_key] is not None]
            successes = sum(bool(x["matches"][horizon_key]) for x in valid)
            breakdown[f"{key[0]} | {key[1]}"][horizon_key] = {
                "success": successes, "sample": len(valid),
                "right_censored": sum(bool(x["right_censored"][horizon_key]) for x in subset),
                "data_incomplete": sum(bool(x["data_incomplete"][horizon_key]) for x in subset),
                "probability": successes/len(valid) if valid else None,
                "ci95": _ci95(successes, len(valid))}
    return {"metrics": {"sweep_samples": len(rows), "probability_by_horizon": matrix,
                         "breakdown_by_liquidity_session": breakdown},
            "records": rows,
            "methodology": "A sweep is matched to a same-direction expectation MSS within each 5/15/30/60-minute horizon. Each horizon has its own denominator. A negative result is recorded only when every expected candle in the horizon is present and usable; right-censored horizons and fully elapsed windows with internal data gaps are separately excluded. Samples may overlap; Wilson intervals are descriptive and do not correct event clustering."}


MODULES = {
    "gaps": gap_statistics,
    "liquidity": liquidity_statistics,
    "sessions": session_statistics,
    "time": time_statistics,
    "structure": market_structure_statistics,
    "daily-weekly": daily_weekly_statistics,
    "liquidity-mss": liquidity_to_mss_statistics,
}


def run_module(name: str, bars: list[dict], day_start: int = 17, bar_duration_ms=None, structure_horizon_bars: int = 60):
    if name not in MODULES:
        raise ValueError(f"Unknown statistics module: {name}")
    fn = MODULES[name]
    if name in {"daily-weekly", "liquidity"}:
        return fn(bars, day_start=day_start, bar_duration_ms=bar_duration_ms)
    if name == "sessions":
        return fn(bars, day_start=day_start, bar_duration_ms=bar_duration_ms)
    if name in {"gaps", "time"}:
        return fn(bars, day_start=day_start)
    if name == "liquidity-mss":
        return fn(bars, day_start=day_start, bar_duration_ms=bar_duration_ms)
    if name == "structure":
        return fn(bars, horizon=max(0, int(structure_horizon_bars)))
    return fn(bars)
