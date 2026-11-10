from datetime import datetime
from typing import Literal
from pydantic import BaseModel,Field
class ForecastScenario(BaseModel):
 label: str; probability: float=Field(ge=0,le=1)
 expected_time_minutes: int|None=None; price_low: float|None=None; price_high: float|None=None
 liquidity_target: float|None=None; invalidation: str|None=None
class ForecastRecord(BaseModel):
 forecast_id: str; mode: Literal['live','historical_replay']; symbol_id: str; as_of_utc: datetime
 horizon_minutes: int; model_name: str; model_version: str; feature_definition_version: str
 training_cutoff_utc: datetime|None; sample_size: int; scenarios: list[ForecastScenario]
 validation_status: Literal['baseline','in_sample','out_of_sample','not_validated']
 notes: list[str]=Field(default_factory=list)
