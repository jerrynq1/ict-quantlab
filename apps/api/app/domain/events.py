from datetime import datetime
from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field
EventType=Literal['ndog_created','nwog_created','gap_fill_25','gap_fill_50','gap_fill_75','gap_fill_100','liquidity_probe','liquidity_sweep','liquidity_breakout','bullish_mss','bearish_mss','bullish_bos','bearish_bos','session_high','session_low','daily_high','daily_low','weekly_high','weekly_low']
class ICTEvent(BaseModel):
 model_config=ConfigDict(frozen=True)
 event_id: str; event_type: EventType; definition_version: str; symbol_id: str; timeframe: str
 event_time_utc: datetime; known_at_utc: datetime
 reference_level: float|None=None; event_price: float|None=None
 direction: Literal['bullish','bearish','neutral']|None=None
 session_id: str|None=None; source_candle_ids: list[str]=Field(default_factory=list)
 parent_event_ids: list[str]=Field(default_factory=list); parameters: dict[str,Any]=Field(default_factory=dict)
 quality_flags: list[str]=Field(default_factory=list)
