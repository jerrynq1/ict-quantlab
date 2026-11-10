from datetime import datetime
from zoneinfo import ZoneInfo
UTC=ZoneInfo('UTC'); NEW_YORK=ZoneInfo('America/New_York')
def to_new_york(value: datetime):
 if value.tzinfo is None or value.utcoffset() is None: raise ValueError('Expected timezone-aware datetime')
 return value.astimezone(NEW_YORK)
def to_utc(value: datetime):
 if value.tzinfo is None or value.utcoffset() is None: raise ValueError('Expected timezone-aware datetime')
 return value.astimezone(UTC)
