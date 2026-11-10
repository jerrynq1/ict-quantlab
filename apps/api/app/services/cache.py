from dataclasses import dataclass,field
from datetime import datetime
from threading import RLock
from app.domain.market_data import CandleM1,DataRangeState
@dataclass
class SymbolCache:
 candles_by_timestamp: dict[datetime,CandleM1]=field(default_factory=dict)
 ranges: list[DataRangeState]=field(default_factory=list)
class SessionOHLCMemoryCache:
 """RAM-only OHLC cache; deliberately no disk/database persistence."""
 def __init__(self): self._symbols={}; self._lock=RLock()
 def upsert(self,workspace,environment,symbol_id,candles):
  key=(workspace,environment,symbol_id)
  with self._lock:
   bucket=self._symbols.setdefault(key,SymbolCache())
   for candle in candles: bucket.candles_by_timestamp[candle.timestamp_utc]=candle
   return len(bucket.candles_by_timestamp)
 def get(self,workspace,environment,symbol_id,start,end):
  with self._lock:
   bucket=self._symbols.get((workspace,environment,symbol_id))
   if not bucket: return []
   return [bucket.candles_by_timestamp[t] for t in sorted(bucket.candles_by_timestamp) if start<=t<end]
 def add_range(self,workspace,environment,symbol_id,coverage):
  with self._lock: self._symbols.setdefault((workspace,environment,symbol_id),SymbolCache()).ranges.append(coverage)
 def clear(self):
  with self._lock: self._symbols.clear()
ohlc_cache=SessionOHLCMemoryCache()
