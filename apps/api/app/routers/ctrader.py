from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from app.security import require_auth
from app.services import ctrader

router=APIRouter(prefix="/ctrader",tags=["cTrader"])

class ConfigBody(BaseModel):
    client_id: str=Field(min_length=1,max_length=150)
    client_secret: str|None=Field(default=None,max_length=500)
    redirect_uri: str|None=Field(default=None,max_length=500)
    environment: str="demo"
    scope: str="accounts"

@router.get("/config")
async def config(_:str=Depends(require_auth)):
    return ctrader.public_config()

@router.put("/config")
async def save_config(body:ConfigBody,_:str=Depends(require_auth)):
    try: return ctrader.save_config(body.model_dump())
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))

@router.post("/oauth/start")
async def oauth_start(_:str=Depends(require_auth)):
    try: return {"authorization_url":ctrader.create_oauth_url()}
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))

@router.get("/oauth/callback")
async def oauth_callback(code:str|None=None,state:str|None=None,error:str|None=None):
    cfg=ctrader.get_config()
    from app.config import settings
    frontend = settings.public_app_url.rstrip("/")
    if error:
        if state:
            try: ctrader.consume_oauth_state(state)
            except Exception: pass
        return RedirectResponse(frontend + "?" + urlencode({"ctrader_error": str(error)[:120]}))
    if not code or not state:
        raise HTTPException(status_code=400,detail="Missing OAuth code or state")
    try:
        redirect_uri=ctrader.consume_oauth_state(state)
        await ctrader.exchange_code(code,redirect_uri)
        return RedirectResponse(frontend + "?ctrader=connected")
    except Exception as exc:
        return RedirectResponse(frontend + "?" + urlencode({"ctrader_error": str(exc)[:160]}))

@router.get("/accounts")
async def accounts(_:str=Depends(require_auth)):
    try:return {"accounts":await ctrader.list_accounts()}
    except Exception as exc: raise HTTPException(status_code=502,detail=str(exc))

class SelectAccountBody(BaseModel):
    account_id:str

@router.post("/accounts/select")
async def select_account(body:SelectAccountBody,_:str=Depends(require_auth)):
    try:return {"selected":await ctrader.set_selected_account(body.account_id)}
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))

@router.get("/symbols")
async def symbols(_:str=Depends(require_auth)):
    try:return {"symbols":await ctrader.get_symbols()}
    except Exception as exc: raise HTTPException(status_code=502,detail=str(exc))
