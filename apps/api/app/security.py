import hashlib
import hmac
import secrets
import time
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Header
from app.config import settings
from app.db import db


def _fernet() -> Fernet:
    if not settings.encryption_key:
        raise RuntimeError("ICTQL_ENCRYPTION_KEY is not configured")
    try:
        key = settings.encryption_key.encode("utf-8")
        return Fernet(key)
    except Exception as exc:
        raise RuntimeError("ICTQL_ENCRYPTION_KEY must be a valid Fernet key") from exc


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Unable to decrypt stored cTrader credentials. Check encryption key continuity.") from exc


def hash_token(token: str) -> str:
    if not settings.session_secret:
        raise RuntimeError("ICTQL_SESSION_SECRET is not configured; refusing to issue or verify sessions")
    pepper = settings.session_secret.encode("utf-8")
    return hmac.new(pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_session() -> str:
    token = secrets.token_urlsafe(48)
    expires = int(time.time()) + settings.session_ttl_hours * 3600
    with db() as conn:
        conn.execute("INSERT INTO sessions(token_hash, expires_at) VALUES (?, ?)", (hash_token(token), expires))
    return token


def revoke_session(token: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))


def authenticate_token(token: str) -> bool:
    with db() as conn:
        row = conn.execute("SELECT expires_at FROM sessions WHERE token_hash = ?", (hash_token(token),)).fetchone()
        if not row:
            return False
        if int(row["expires_at"]) < int(time.time()):
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
            return False
        return True


async def require_auth(authorization: str | None = Header(default=None)) -> str:
    if not settings.session_secret:
        raise HTTPException(status_code=503, detail="Backend authentication is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    if not authenticate_token(token):
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return token


def verify_admin(username: str, password: str) -> bool:
    if not settings.admin_password:
        return False
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(password, settings.admin_password)
