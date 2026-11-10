from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import asyncio, re
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from app.security import require_auth
from app.services.cache import bar_cache
from app.services.ctrader import get_trendbars, _selected_account
from app.config import settings

router=APIRouter(prefix="/data",tags=["market data"])
NY=ZoneInfo("America/New_York")

class BarsRequest(BaseModel):
    symbol_id:str
    start:str
    end:str
    timeframe:str="M1"

class RefreshRequest(BaseModel):
    symbol_id: str


def _parse_date(value:str)->datetime:
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None: dt=dt.replace(tzinfo=NY)
    return dt.astimezone(timezone.utc)


def _validate_run_id(run_id:str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}",run_id or ""):
        raise HTTPException(status_code=400,detail="Invalid client run identifier")
    return run_id

@router.post("/bars")
async def bars(body:BarsRequest, run_id:str=Header(alias="X-Client-Run"), _:str=Depends(require_auth)):
    run_id=_validate_run_id(run_id)
    if body.timeframe!="M1":
        raise HTTPException(status_code=400,detail="Download source data as M1. Higher timeframes are aggregated from M1.")
    try:
        start=_parse_date(body.start); end=_parse_date(body.end)
    except Exception: raise HTTPException(status_code=400,detail="Date must be ISO-8601; naive dates are interpreted in America/New_York")
    start_ms=int(start.timestamp()*1000); end_ms=int(end.timestamp()*1000)
    if end_ms<=start_ms: raise HTTPException(status_code=400,detail="End must be after start")
    if (end_ms-start_ms)>3660*24*60*60*1000:
        raise HTTPException(status_code=400,detail="A single request is limited to 10 years; use multiple ranges for longer research")
    # Avoid fetching a massive history only to reject it after consuming API quota.
    if (end_ms-start_ms) > settings.max_bars_per_symbol * 2 * 60_000:
        raise HTTPException(status_code=413,detail="Requested window is too large for the configured RAM bar cap. Split it into smaller ranges.")
    if not body.symbol_id.isdigit(): raise HTTPException(status_code=400,detail="Invalid symbol ID")
    try: account_id,_=await _selected_account()
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
    missing=bar_cache.get_missing(run_id,account_id,body.symbol_id,start_ms,end_ms)
    chunk_ms=6*24*60*60*1000
    fetched=0
    try:
        for a,b in missing:
            cursor=a
            while cursor<b:
                chunk_end=min(cursor+chunk_ms,b)
                chunk=await get_trendbars(int(body.symbol_id),cursor,chunk_end-1,"M1")
                bar_cache.put_window(run_id,account_id,body.symbol_id,cursor,chunk_end,chunk)
                fetched+=len(chunk)
                cursor=chunk_end
                # Keep the request rate conservative across chunked history calls.
                await asyncio.sleep(0.22)
    except Exception as exc:
        raise HTTPException(status_code=502,detail=f"cTrader historical data request failed. Completed chunks remain cached; the failed chunk was not marked loaded: {exc}")
    result=bar_cache.get_bars(run_id,account_id,body.symbol_id,start_ms,end_ms)
    if len(result)>settings.max_bars_per_symbol:
        raise HTTPException(status_code=413,detail="Requested range exceeds configured in-memory bar cap")
    return {"symbol_id":body.symbol_id,"timeframe":"M1","bars":result,"count":len(result),
            "new_bars_fetched":fetched,"cache":bar_cache.status(run_id,account_id,body.symbol_id),
            "quality":{"suspect_high":sum(x.get("quality")=="suspect_ohlc" for x in result),
                       "suspect_ohlc":sum(x.get("quality")=="suspect_ohlc" for x in result),
                       "analytics_usable":sum(x.get("analytics_usable",True) for x in result),
                       "price_basis":"ctrader_relative_1e5_decoded"},
            "timezone":"UTC source; display America/New_York"}

@router.get("/cache")
async def cache_status(symbol_id:str,run_id:str=Header(alias="X-Client-Run"),_:str=Depends(require_auth)):
    run_id=_validate_run_id(run_id)
    try: account_id,_=await _selected_account()
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))
    return bar_cache.status(run_id,account_id,symbol_id)

@router.post("/refresh")
async def refresh_latest_m1(body: RefreshRequest, run_id: str = Header(alias="X-Client-Run"), _: str = Depends(require_auth)):
    """Fetch a small recent window for an M1 polling forecast; no tick-stream claim."""
    run_id = _validate_run_id(run_id)
    if not body.symbol_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid symbol ID")
    try:
        account_id, _ = await _selected_account()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = now_ms - 12 * 60_000
        recent = await get_trendbars(int(body.symbol_id), start_ms, now_ms - 1, "M1")
        # cTrader may return the currently forming minute. Only closed M1 bars
        # are admitted to analytics/forecast to avoid partial-candle look-ahead.
        closed = [x for x in recent if int(x["time"]) + 60_000 <= now_ms]
        added = bar_cache.upsert_bars(run_id, account_id, body.symbol_id, closed)
        result = bar_cache.get_bars(run_id, account_id, body.symbol_id, now_ms - 24 * 60 * 60_000, None)
        return {"symbol_id": body.symbol_id, "timeframe": "M1", "bars": result,
                "count": len(result), "new_bars": added,
                "latest_closed_time": result[-1]["time"] if result else None,
                "cache": bar_cache.status(run_id, account_id, body.symbol_id),
                "poll_interval_seconds": 60, "mode": "historical_endpoint_polling_not_tick_stream"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not refresh recent M1 bars: {exc}") from exc
