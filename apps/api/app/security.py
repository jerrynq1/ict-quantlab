import base64
import hashlib
import hmac
import time
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request, status
from app.settings import settings

SESSION_TTL = 8 * 60 * 60

def cipher() -> Fernet:
    if not settings.encryption_key:
        raise HTTPException(503, "ICTQL_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(settings.encryption_key.encode())
    except Exception as exc:
        raise HTTPException(503, "ICTQL_ENCRYPTION_KEY is invalid.") from exc

def encrypt_secret(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()

def decrypt_secret(value: str) -> str:
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(503, "Cannot decrypt saved credential; verify encryption key.") from exc

def signature(payload: str) -> str:
    if not settings.session_secret:
        raise HTTPException(503, "ICTQL_SESSION_SECRET is not configured.")
    raw = hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def create_session(username: str) -> str:
    payload = f"{username}:{int(time.time()) + SESSION_TTL}"
    return payload + "." + signature(payload)

def valid_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, sig = token.rsplit(".", 1)
    try:
        username, expiry_text = payload.rsplit(":", 1)
        expiry = int(expiry_text)
    except ValueError:
        return False
    return bool(username) and expiry >= int(time.time()) and hmac.compare_digest(sig, signature(payload))

def bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None

def require_workspace(request: Request) -> str:
    token = bearer_token(request)
    if not valid_session(token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    return token.split(":", 1)[0]

def verify_admin(username: str, password: str) -> bool:
    return (
        bool(settings.admin_username and settings.admin_password)
        and hmac.compare_digest(username, settings.admin_username)
        and hmac.compare_digest(password, settings.admin_password)
    )
