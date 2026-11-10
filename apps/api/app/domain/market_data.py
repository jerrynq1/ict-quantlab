from datetime import datetime
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
class CandleM1(BaseModel):
 model_config=ConfigDict(frozen=True)
 candle_id: str; symbol_id: str; timestamp_utc: datetime
 open: float; high: float; low: float; close: float; volume: float=Field(ge=0)
 @field_validator('timestamp_utc')
 @classmethod
 def aware(cls,v):
  if v.tzinfo is None or v.utcoffset() is None: raise ValueError('timestamp must be timezone-aware')
  return v
 @field_validator('high')
 @classmethod
 def high_check(cls,v,info):
  low=info.data.get('low')
  if low is not None and v<low: raise ValueError('high cannot be below low')
  return v
class DataRangeState(BaseModel):
 start_utc: datetime; end_utc: datetime
 state: Literal['loaded','missing','failed','in_progress','no_data_confirmed']
 detail: str|None=None
