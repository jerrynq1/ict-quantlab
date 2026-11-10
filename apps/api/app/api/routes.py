import secrets
import time
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.settings import settings
from app.security import create_session, require_workspace, verify_admin, valid_session, bearer_token
from app.schemas.api import LoginRequest, CredentialUpdate, ConfigStatus, ModuleInfo
from app.services.ctrader import public_config, save_config, exchange_code, refresh_token
from app.storage.database import delete_credentials, save_oauth_state, consume_oauth_state

router = APIRouter()
_LOGIN_FAILURES: dict[str, list[float]] = {}

def require_allowed_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    allowed = {item.rstrip("/") for item in settings.cors_origins}
    if settings.environment.lower() == "production" and (not origin or origin.rstrip("/") not in allowed):
        raise HTTPException(403, "Origin is not allowed.")
    if origin and allowed and origin.rstrip("/") not in allowed:
        raise HTTPException(403, "Origin is not allowed.")
    return True

def check_login_rate(request: Request) -> str:
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    recent = [stamp for stamp in _LOGIN_FAILURES.get(ip, []) if now - stamp < 900]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many login attempts. Try again later.")
    _LOGIN_FAILURES[ip] = recent
    return ip

def frontend_url(relative_path: str) -> str:
    return settings.public_app_url.rstrip("/") + "/#" + relative_path.lstrip("/").replace("settings/ctrader/?", "data-center?")

MODULES = [
    ("data-center", "Data Center", "Foundation", "in_development", "cTrader, accounts, dynamic symbols, M1 coverage and cache."),
    ("gap", "Gap Statistics", "Core Statistics", "spec_ready", "NDOG/NWOG threshold fills and post-fill reaction."),
    ("liquidity", "Liquidity Statistics", "Core Statistics", "spec_ready", "Asia H/L, PDH/PDL, PWH/PWL probes, sweeps and breakouts."),
    ("session", "Session Statistics", "Core Statistics", "spec_ready", "NY-time session range, direction and interactions."),
    ("time", "Time Statistics", "Core Statistics", "spec_ready", "Event timing and retrospective daily/weekly extremes."),
    ("structure", "Market Structure", "Core Statistics", "spec_ready", "Confirmed pivots, sweep-to-MSS and MFE/MAE."),
    ("daily-weekly", "Daily & Weekly", "Core Statistics", "spec_ready", "Direction, range, extremes and previous-level interaction."),
    ("liquidity-mss", "Liquidity → MSS", "Core Statistics", "spec_ready", "Conditional transitions with denominator and interval."),
    ("forecast", "Hybrid Forecast Lab", "Forecast", "spec_ready", "Live and historical event + price scenarios."),
    ("research", "Research & Evaluation", "Research", "spec_ready", "Walk-forward, calibration and model scorecards."),
]

@router.get("/auth/status")
def auth_status(request: Request):
    return {"authenticated": valid_session(bearer_token(request))}

@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, _origin=Depends(require_allowed_origin)):
    if not settings.session_secret:
        raise HTTPException(503, "ICTQL_SESSION_SECRET is not configured.")
    ip = check_login_rate(request)
    if not verify_admin(payload.username, payload.password):
        _LOGIN_FAILURES.setdefault(ip, []).append(time.time())
        raise HTTPException(401, "Invalid username or password.")
    _LOGIN_FAILURES.pop(ip, None)
    return {"authenticated": True, "access_token": create_session(payload.username), "token_type": "bearer", "expires_in": 28800}

@router.post("/auth/logout")
def logout(_user=Depends(require_workspace), _origin=Depends(require_allowed_origin)):
    # Stateless short-lived token: client discards it. Expiry bounds any copied token.
    return {"authenticated": False}

@router.get("/system/health")
def health():
    return {"status": "ok", "service": "ict-quantlab-api"}

@router.get("/system/modules", response_model=list[ModuleInfo])
def modules(_user=Depends(require_workspace)):
    return [ModuleInfo(id=i, name=n, group=g, phase=p, status=s, purpose=u) for i,n,g,p,s,u in MODULES]

@router.get("/integrations/ctrader/config", response_model=ConfigStatus)
def config_get(_user=Depends(require_workspace)):
    return public_config()

@router.put("/integrations/ctrader/config", response_model=ConfigStatus)
def config_put(payload: CredentialUpdate, _user=Depends(require_workspace), _origin=Depends(require_allowed_origin)):
    save_config(payload.client_id, payload.client_secret, payload.redirect_uri, payload.environment)
    return public_config()

@router.delete("/integrations/ctrader/config")
def config_delete(_user=Depends(require_workspace), _origin=Depends(require_allowed_origin)):
    delete_credentials()
    return {"deleted": True}

@router.post("/integrations/ctrader/authorize-url")
def authorize_url(_user=Depends(require_workspace), _origin=Depends(require_allowed_origin)):
    cfg = public_config()
    if not cfg["configured"]:
        raise HTTPException(409, "Save Client ID, Client Secret and Redirect URI first.")
    state = secrets.token_urlsafe(32)
    save_oauth_state(state, int(time.time()) + 600)
    params = {"client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"], "scope": "accounts", "product": "web", "state": state}
    return {"authorization_url": "https://id.ctrader.com/my/settings/openapi/grantingaccess/?" + urlencode(params)}

@router.get("/integrations/ctrader/callback")
async def ctrader_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    # OAuth state is random, short-lived and one-use. It binds this callback to an
    # authorization flow started by an authenticated workspace API request.
    if not state or not consume_oauth_state(state, int(time.time())):
        return RedirectResponse(frontend_url("settings/ctrader/?ctrader=invalid_state"), 303)
    if error:
        return RedirectResponse(frontend_url("settings/ctrader/?ctrader=denied"), 303)
    if not code:
        return RedirectResponse(frontend_url("settings/ctrader/?ctrader=invalid_state"), 303)
    try:
        await exchange_code(code)
    except HTTPException:
        return RedirectResponse(frontend_url("settings/ctrader/?ctrader=token_exchange_failed"), 303)
    return RedirectResponse(frontend_url("settings/ctrader/?ctrader=oauth_saved"), 303)

@router.post("/integrations/ctrader/refresh")
async def ctrader_refresh(_user=Depends(require_workspace), _origin=Depends(require_allowed_origin)):
    await refresh_token()
    return {"status": "refreshed", "next_step": "account_authorization"}

@router.post("/integrations/ctrader/authorize-account")
def account_authorization_not_ready(_user=Depends(require_workspace), _origin=Depends(require_allowed_origin)):
    cfg = public_config()
    if cfg["oauth_status"] != "oauth_tokens_saved_account_pending":
        raise HTTPException(409, "Complete OAuth authorization first.")
    raise HTTPException(501, "OAuth tokens are stored. Protobuf account listing, account selection and account authorization still need implementation.")
