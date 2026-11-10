from __future__ import annotations
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def to_ny(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC).astimezone(NY)


def from_ny_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=NY) if dt.tzinfo is None else dt.astimezone(NY)


def trading_date(ms: int, day_start_hour: int = 17) -> date:
    """Return the closing-date label for a trading day.

    With the Forex default of 17:00 New York, Sunday 17:00–Monday 16:59
    belongs to Monday's trading date; Monday 17:00 starts Tuesday's date.
    A 00:00 day start uses the ordinary calendar date.
    """
    local = to_ny(ms)
    if day_start_hour > 0 and local.hour >= day_start_hour:
        return local.date() + timedelta(days=1)
    return local.date()


def trading_week(ms: int, day_start_hour: int = 17) -> date:
    """Monday date of the week containing the trading-date label.

    For a 17:00 New York start, Sunday evening is labelled Monday and thus
    begins the new trading week.
    """
    d = trading_date(ms, day_start_hour)
    return d - timedelta(days=d.weekday())


# Research profile defaults, all in America/New_York and therefore DST-aware.
# NY AM and London Close are separate, non-overlapping labels to preserve both.
SESSION_WINDOWS = {
    "Asia": (20 * 60, 24 * 60),
    "London": (2 * 60, 5 * 60),
    "NY AM": (7 * 60, 10 * 60),
    "London Close": (10 * 60, 12 * 60),
    "NY PM": (13 * 60, 16 * 60),
}
SESSION_ORDER = {name: i for i, name in enumerate(("Asia", "London", "NY AM", "London Close", "NY PM"))}


def set_session_windows(windows: dict[str, tuple[int, int]]) -> None:
    """Replace research session windows; input values are NY-time minute pairs."""
    global SESSION_WINDOWS
    required = {"Asia", "London", "NY AM", "London Close", "NY PM"}
    if set(windows) != required:
        raise ValueError(f"Session profile must contain exactly: {', '.join(sorted(required))}")
    cleaned = {}
    occupied: dict[int, str] = {}
    for name, pair in windows.items():
        start, end = int(pair[0]), int(pair[1])
        if not (0 <= start < 1440 and 0 <= end <= 1440) or start == end:
            raise ValueError(f"Invalid session window for {name}")
        # HH:MM 00:00 as an end is midnight, not an empty interval.
        end_exclusive = 1440 if end == 0 and start > 0 else end
        minutes = list(range(start, end_exclusive)) if start < end_exclusive else (list(range(start, 1440)) + list(range(0, end)))
        for minute in minutes:
            if minute in occupied:
                raise ValueError(f"Session overlap: {name} overlaps {occupied[minute]}")
            occupied[minute] = name
        cleaned[name] = (start, end)
    SESSION_WINDOWS = cleaned


def session_name(ms: int) -> str:
    dt = to_ny(ms)
    minute = dt.hour * 60 + dt.minute
    for name, (start, end) in SESSION_WINDOWS.items():
        inside = start <= minute < end if start < end else minute >= start or minute < end
        if inside:
            return name
    return "Off-session"


def session_trade_date(ms: int, day_start_hour: int = 17):
    """Trading-date key used to align Asia, London and New York sessions."""
    return trading_date(ms, day_start_hour)


def bucket_start_ms(ms: int, minutes: int) -> int:
    width = minutes * 60_000
    return (ms // width) * width


def infer_bar_duration_ms(bars: list[dict], default: int = 60_000) -> int:
    """Infer the nominal interval from positive timestamp deltas (ignores session gaps)."""
    if len(bars) < 2:
        return default
    deltas = [int(bars[i]["time"]) - int(bars[i - 1]["time"])
              for i in range(1, len(bars))]
    deltas = [d for d in deltas if 0 < d <= 24 * 60 * 60 * 1000]
    if not deltas:
        return default
    deltas.sort()
    return deltas[len(deltas) // 2]
