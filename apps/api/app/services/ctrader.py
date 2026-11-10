"""cTrader OAuth and official Spotware Python SDK adapter.

The SDK uses Twisted. We run one reactor thread and make short-lived API
connections per operation, avoiding reactor restart problems inside ASGI.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from app.config import settings
from app.db import db
from app.services.store import get_value, set_value
from app.security import encrypt, decrypt

TOKEN_URL = "https://openapi.ctrader.com/apps/token"
AUTH_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"


def get_config() -> dict:
    return get_value("ctrader_config", {}) or {}


def save_config(payload: dict) -> dict:
    old = get_config()
    client_id = str(payload.get("client_id") or old.get("client_id") or "").strip()
    secret = str(payload.get("client_secret") or "").strip()
    if not client_id:
        raise ValueError("Client ID is required")
    if not secret and not old.get("client_secret_enc"):
        raise ValueError("Client Secret is required on first save")
    if secret:
        secret_enc = encrypt(secret)
    else:
        secret_enc = old["client_secret_enc"]
    redirect_uri = str(payload.get("redirect_uri") or old.get("redirect_uri") or "").strip()
    if not redirect_uri and settings.public_api_url:
        redirect_uri = settings.public_api_url.rstrip("/") + "/api/v1/ctrader/oauth/callback"
    if not redirect_uri:
        raise ValueError("Redirect URI is required. Set ICTQL_PUBLIC_API_URL or enter the exact callback URL.")
    env = str(payload.get("environment") or old.get("environment") or "demo").lower()
    if env not in {"demo", "live"}:
        raise ValueError("Environment must be demo or live")
    scope = str(payload.get("scope") or "accounts").strip()
    if scope != "accounts":
        raise ValueError("ICT QuantLab is read-only; OAuth scope must be 'accounts'.")
    config = {"client_id": client_id, "client_secret_enc": secret_enc,
              "redirect_uri": redirect_uri, "environment": env,
              "scope": scope}
    identity_changed = (
        client_id != old.get("client_id")
        or (secret and secret_enc != old.get("client_secret_enc"))
        or env != old.get("environment", "demo")
        or redirect_uri != old.get("redirect_uri")
    )
    set_value("ctrader_config", config)
    if identity_changed:
        # OAuth tokens are bound to the app/redirect/environment configuration.
        set_value("ctrader_token", {})
        set_value("ctrader_accounts", [])
        set_value("ctrader_selected_account", None)
    return public_config()


def public_config() -> dict:
    cfg = get_config()
    token = get_value("ctrader_token", {}) or {}
    return {
        "configured": bool(cfg.get("client_id") and cfg.get("client_secret_enc") and cfg.get("redirect_uri")),
        "client_id": cfg.get("client_id", ""),
        "redirect_uri": cfg.get("redirect_uri", ""),
        "environment": cfg.get("environment", "demo"),
        "scope": cfg.get("scope", "accounts"),
        "secret_saved": bool(cfg.get("client_secret_enc")),
        "authorized": bool(token.get("refresh_token_enc")),
        "token_expires_at": token.get("expires_at"),
        "selected_account_id": get_value("ctrader_selected_account", None),
    }


def _client_secret(cfg: dict) -> str:
    return decrypt(cfg["client_secret_enc"])


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def create_oauth_url() -> str:
    cfg = get_config()
    if not cfg:
        raise ValueError("Save cTrader credentials first")
    state = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (int(time.time()) - 600,))
        conn.execute("INSERT INTO oauth_states(state_hash, created_at, redirect_uri) VALUES (?, ?, ?)",
                     (_state_hash(state), int(time.time()), cfg["redirect_uri"]))
    params = {"client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"],
              "scope": cfg.get("scope", "accounts"), "product": "web", "state": state}
    return AUTH_URL + "?" + urlencode(params)


def consume_oauth_state(state: str) -> str:
    with db() as conn:
        row = conn.execute("SELECT created_at, redirect_uri FROM oauth_states WHERE state_hash = ?",
                           (_state_hash(state),)).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state_hash = ?", (_state_hash(state),))
    if not row or int(time.time()) - int(row["created_at"]) > 600:
        raise ValueError("OAuth state invalid or expired")
    return row["redirect_uri"]


async def exchange_code(code: str, redirect_uri: str) -> dict:
    cfg = get_config()
    params = {"grant_type": "authorization_code", "code": code,
              "redirect_uri": redirect_uri, "client_id": cfg["client_id"],
              "client_secret": _client_secret(cfg)}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(TOKEN_URL, params=params, headers={"Accept": "application/json"})
    response.raise_for_status()
    payload = response.json()
    if payload.get("errorCode") or not payload.get("accessToken"):
        raise ValueError(payload.get("description") or payload.get("errorCode") or "Token exchange failed")
    _save_token(payload)
    return {"expires_at": get_value("ctrader_token", {}).get("expires_at")}


def _save_token(payload: dict) -> None:
    now = int(time.time())
    old = get_value("ctrader_token", {}) or {}
    refresh = payload.get("refreshToken")
    if not refresh and old.get("refresh_token_enc"):
        refresh_enc = old["refresh_token_enc"]
    elif refresh:
        refresh_enc = encrypt(refresh)
    else:
        raise ValueError("Token response did not include a refresh token")
    data = {
        "access_token_enc": encrypt(payload["accessToken"]),
        "refresh_token_enc": refresh_enc,
        "expires_at": now + int(payload.get("expiresIn", 0)),
        "token_type": payload.get("tokenType", "Bearer"),
    }
    set_value("ctrader_token", data)


async def access_token(force_refresh: bool = False) -> str:
    token = get_value("ctrader_token", {}) or {}
    if not token.get("refresh_token_enc"):
        raise ValueError("cTrader has not been authorized")
    if not force_refresh and int(token.get("expires_at", 0)) > int(time.time()) + 120:
        return decrypt(token["access_token_enc"])

    async with _token_refresh_lock:
        # Another request may have refreshed the token while this coroutine waited.
        latest = get_value("ctrader_token", {}) or {}
        if not latest.get("refresh_token_enc"):
            raise ValueError("cTrader has not been authorized")
        if latest.get("access_token_enc") != token.get("access_token_enc") and int(latest.get("expires_at", 0)) > int(time.time()) + 120:
            return decrypt(latest["access_token_enc"])
        if not force_refresh and int(latest.get("expires_at", 0)) > int(time.time()) + 120:
            return decrypt(latest["access_token_enc"])
        cfg = get_config()
        params = {"grant_type": "refresh_token", "refresh_token": decrypt(latest["refresh_token_enc"]),
                  "client_id": cfg["client_id"], "client_secret": _client_secret(cfg)}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TOKEN_URL, params=params, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        if payload.get("errorCode") or not payload.get("accessToken"):
            raise ValueError(payload.get("description") or payload.get("errorCode") or "Token refresh failed")
        _save_token(payload)
        return payload["accessToken"]


class _ReactorRunner:
    def __init__(self):
        self._lock = threading.Lock()
        self._started = threading.Event()
        self._reactor = None
        self._thread = None

    def ensure_started(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            from twisted.internet import reactor
            self._reactor = reactor
            reactor.callWhenRunning(self._started.set)
            self._thread = threading.Thread(
                target=lambda: reactor.run(installSignalHandlers=False),
                name="ctrader-twisted-reactor", daemon=True,
            )
            self._thread.start()
        if not self._started.wait(timeout=10):
            raise RuntimeError("cTrader SDK reactor did not start")

    async def request(self, environment: str, client_id: str, client_secret: str,
                      token: str, account_id: int | None, request_factory):
        self.ensure_started()
        future: concurrent.futures.Future = concurrent.futures.Future()

        def start_request():
            client = None
            finished = {"value": False}
            timeout_call = {"value": None}

            def finish(result=None, error=None):
                if finished["value"]:
                    return
                finished["value"] = True
                delayed = timeout_call["value"]
                if delayed is not None and delayed.active():
                    delayed.cancel()
                if client is not None:
                    try:
                        client.stopService()
                    except Exception:
                        pass
                if future.done():
                    return
                if error is not None:
                    future.set_exception(error if isinstance(error, Exception) else RuntimeError(str(error)))
                else:
                    future.set_result(result)

            try:
                from ctrader_open_api import Client, TcpProtocol, EndPoints
                host = EndPoints.PROTOBUF_LIVE_HOST if environment == "live" else EndPoints.PROTOBUF_DEMO_HOST
                client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
            except Exception as exc:
                finish(error=RuntimeError(f"cTrader Open API SDK is unavailable or failed to initialize: {exc}"))
                return

            def send_final():
                try:
                    request = request_factory()
                    deferred = client.send(request)
                    deferred.addCallbacks(lambda result: finish(result=result), lambda failure: finish(error=RuntimeError(str(failure))))
                except Exception as exc:
                    finish(error=exc)

            def on_account_auth(_response):
                send_final()

            def on_app_auth(_response):
                if account_id is None:
                    send_final()
                    return
                try:
                    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAccountAuthReq
                    account_req = ProtoOAAccountAuthReq()
                    account_req.ctidTraderAccountId = int(account_id)
                    account_req.accessToken = token
                    client.send(account_req).addCallbacks(on_account_auth, lambda failure: finish(error=RuntimeError(str(failure))))
                except Exception as exc:
                    finish(error=exc)

            def connected(_client):
                try:
                    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
                    auth_req = ProtoOAApplicationAuthReq()
                    auth_req.clientId = client_id
                    auth_req.clientSecret = client_secret
                    client.send(auth_req).addCallbacks(on_app_auth, lambda failure: finish(error=RuntimeError(str(failure))))
                except Exception as exc:
                    finish(error=exc)

            def disconnected(_client, reason):
                if not finished["value"]:
                    finish(error=RuntimeError(f"cTrader disconnected: {reason}"))

            client.setConnectedCallback(connected)
            client.setDisconnectedCallback(disconnected)
            try:
                client.startService()
                timeout_call["value"] = self._reactor.callLater(40, lambda: finish(error=TimeoutError("cTrader request timed out")))
            except Exception as exc:
                finish(error=exc)

        self._reactor.callFromThread(start_request)
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=45)


_runner = _ReactorRunner()
_token_refresh_lock = asyncio.Lock()


async def _sdk_request(environment: str, account_id: int | None, token: str, request_factory):
    cfg = get_config()
    return await _runner.request(environment, cfg["client_id"], _client_secret(cfg), token, account_id, request_factory)


async def list_accounts() -> list[dict]:
    token = await access_token()
    cfg = get_config()
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetAccountListByAccessTokenReq
    accounts: dict[str, dict] = {}
    # cTrader accounts can belong to demo or live hosts; query both endpoints.
    for env in ("demo", "live"):
        try:
            response = await _sdk_request(env, None, token, lambda: _account_list_req(token))
            for item in response.ctidTraderAccount:
                aid = str(item.ctidTraderAccountId)
                accounts[aid] = {"account_id": aid, "is_live": bool(getattr(item, "isLive", env == "live")),
                                 "trader_login": str(getattr(item, "traderLogin", "")),
                                 "broker": getattr(item, "brokerTitleShort", "")}
        except Exception:
            # One environment may not contain this token's account; the other may.
            continue
    if not accounts:
        raise RuntimeError("No cTrader account was returned. Check OAuth permission and Demo/Live account access.")
    result = sorted(accounts.values(), key=lambda x: (x["is_live"], x["broker"], x["account_id"]))
    set_value("ctrader_accounts", result)
    return result


def _account_list_req(token: str):
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetAccountListByAccessTokenReq
    request = ProtoOAGetAccountListByAccessTokenReq()
    request.accessToken = token
    return request


async def _selected_account() -> tuple[str, bool]:
    selected = get_value("ctrader_selected_account", None)
    accounts = get_value("ctrader_accounts", []) or []
    if not selected:
        if len(accounts) == 1:
            selected = accounts[0]["account_id"]
            set_value("ctrader_selected_account", selected)
        else:
            raise ValueError("Select a cTrader account first")
    item = next((x for x in accounts if x["account_id"] == str(selected)), None)
    if not item:
        raise ValueError("Selected cTrader account is not available. Refresh accounts.")
    return str(selected), bool(item["is_live"])


async def set_selected_account(account_id: str) -> dict:
    accounts = get_value("ctrader_accounts", []) or []
    item = next((x for x in accounts if x["account_id"] == str(account_id)), None)
    if not item:
        raise ValueError("Unknown account ID")
    token = await access_token()
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAccountAuthReq
    account_req = ProtoOAAccountAuthReq()
    account_req.ctidTraderAccountId = int(account_id)
    account_req.accessToken = token
    await _sdk_request("live" if item["is_live"] else "demo", None, token, lambda: account_req)
    set_value("ctrader_selected_account", str(account_id))
    return item


async def get_symbols() -> list[dict]:
    account_id, is_live = await _selected_account()
    token = await access_token()
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListReq
    def build():
        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = int(account_id)
        req.includeArchivedSymbols = False
        return req
    response = await _sdk_request("live" if is_live else "demo", int(account_id), token, build)
    symbols = []
    with db() as conn:
        conn.execute("DELETE FROM symbols WHERE account_id = ?", (account_id,))
        for item in response.symbol:
            symbol = {"symbol_id": str(item.symbolId), "name": item.symbolName,
                      "description": getattr(item, "description", ""),
                      "digits": int(getattr(item, "digits", 0)) if getattr(item, "digits", None) is not None else None}
            symbols.append(symbol)
            conn.execute("INSERT OR REPLACE INTO symbols(account_id, symbol_id, name, digits, description) VALUES(?, ?, ?, ?, ?)",
                         (account_id, symbol["symbol_id"], symbol["name"], symbol["digits"], symbol["description"]))
    return symbols


def _decode_trendbar(row, digits: int | None = None) -> dict:
    """Decode cTrader relative trendbar prices into symbol price units."""
    low_raw = int(row.low)
    open_raw = low_raw + int(row.deltaOpen)
    close_raw = low_raw + int(row.deltaClose)
    high_raw = low_raw + int(row.deltaHigh)
    bad_high = high_raw < max(low_raw, open_raw, close_raw)
    bad_low = low_raw > min(open_raw, close_raw)
    bad_ohlc = bad_high or bad_low
    # Preserve the raw decoded extremes for audit; chart coordinates use a safe
    # envelope while the analytics engine excludes a suspect candle.
    high_safe = max(high_raw, low_raw, open_raw, close_raw)
    low_safe = min(low_raw, open_raw, close_raw)
    def price(raw):
        value = raw / 100_000.0
        return round(value, digits) if digits is not None and digits >= 0 else value
    return {
        "time": int(row.utcTimestampInMinutes) * 60_000,
        "open": price(open_raw), "high": price(high_safe), "low": price(low_safe),
        "raw_high": price(high_raw), "raw_low": price(low_raw), "close": price(close_raw),
        "volume": int(row.volume),
        "quality": "suspect_ohlc" if bad_ohlc else "ok",
        "quality_reason": "high_below_open_close_or_low" if bad_high else "low_above_open_close" if bad_low else None,
        "analytics_usable": not bad_ohlc,
        "price_basis": "ctrader_relative_1e5",
    }


async def get_trendbars(symbol_id: int, start_ms: int, end_ms: int, period: str = "M1") -> list[dict]:
    account_id, is_live = await _selected_account()
    token = await access_token()
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
    def build():
        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = int(account_id)
        req.symbolId = int(symbol_id)
        req.period = ProtoOATrendbarPeriod.Value(period)
        req.fromTimestamp = int(start_ms)
        req.toTimestamp = int(end_ms)
        req.count = 10_000
        return req
    response = await _sdk_request("live" if is_live else "demo", int(account_id), token, build)
    with db() as conn:
        symbol_row = conn.execute("SELECT digits FROM symbols WHERE account_id=? AND symbol_id=?", (account_id,str(symbol_id))).fetchone()
    digits = int(symbol_row["digits"]) if symbol_row and symbol_row["digits"] is not None else None
    return [_decode_trendbar(row, digits) for row in response.trendbar]
