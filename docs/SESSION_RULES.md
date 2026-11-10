# Session and trading-calendar rules

Default research windows use IANA zone `America/New_York`, never a hardcoded UTC-5 offset:

| Window | New York local time | Crosses midnight |
|---|---:|---|
| Asia range | 19:00–00:00 | Yes |
| London window | 02:00–05:00 | No |
| New York AM | 08:30–11:00 | No |
| New York PM | 13:30–16:00 | No |

These are configurable analysis windows, not official exchange sessions. Each versioned session
configuration stores local start/end, timezone, weekdays, holiday policy and the rule for assigning
a session that crosses midnight to its trading date. Convert each local boundary to UTC for querying
bars. Handle ambiguous/nonexistent local times through the zoneinfo timezone rules and test both DST
transitions. The trading-day/week boundary must come from symbol/broker metadata or an explicit
user configuration; never infer it from UTC midnight.
