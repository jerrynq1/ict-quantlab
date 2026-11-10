from collections import defaultdict


def aggregate_bars(m1_bars: list[dict], timeframe_minutes: int) -> list[dict]:
    """Aggregate UTC-aligned M1 bars and flag any bucket without full minute coverage.

    Incomplete buckets remain available for chart display, but are excluded from
    statistics so a partial five-minute/hourly bar is never treated as a full bar.
    """
    if timeframe_minutes <= 1:
        return list(m1_bars)
    groups = defaultdict(list)
    width = timeframe_minutes * 60_000
    for bar in m1_bars:
        bucket = (int(bar["time"]) // width) * width
        groups[bucket].append(bar)
    result = []
    for bucket, rows in sorted(groups.items()):
        rows.sort(key=lambda x: x["time"])
        expected_times = [bucket + i * 60_000 for i in range(timeframe_minutes)]
        actual_times = [int(x["time"]) for x in rows]
        coverage = len(set(actual_times).intersection(expected_times)) / timeframe_minutes
        complete = actual_times == expected_times
        source_usable = all(x.get("analytics_usable", True) for x in rows)
        source_suspect = any(x.get("quality") not in (None, "ok") for x in rows)
        quality = "suspect" if source_suspect else "ok" if complete else "partial_bucket"
        result.append({
            "time": bucket,
            "open": rows[0]["open"],
            "high": max(x["high"] for x in rows),
            "low": min(x["low"] for x in rows),
            "close": rows[-1]["close"],
            "volume": sum(x.get("volume", 0) for x in rows),
            "quality": quality,
            "quality_reason": ("source_ohlc_suspect" if source_suspect else
                               "source_minute_missing_or_duplicate" if not complete else None),
            "analytics_usable": bool(complete and source_usable and not source_suspect),
            "source_count": len(rows),
            "expected_count": timeframe_minutes,
            "coverage_ratio": round(coverage, 6),
            "complete": complete,
        })
    return result
