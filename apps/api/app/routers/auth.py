import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.security import verify_admin, issue_session, revoke_session, require_auth
from app.config import settings

router=APIRouter(prefix="/auth",tags=["authentication"])

class LoginBody(BaseModel):
    username: str = Field(min_length=1,max_length=100)
    password: str = Field(min_length=1,max_length=300)

@router.post("/login")
async def login(body: LoginBody):
    if not settings.admin_password or not settings.session_secret:
        raise HTTPException(status_code=503, detail="Backend authentication is not configured. Set ICTQL_ADMIN_PASSWORD and ICTQL_SESSION_SECRET.")
    if not verify_admin(body.username,body.password):
        raise HTTPException(status_code=401,detail="Invalid username or password")
    return {"access_token":issue_session(),"token_type":"bearer"}

@router.post("/logout")
async def logout(token: str=Depends(require_auth)):
    revoke_session(token)
    return {"ok":True}

@router.get("/me")
async def me(_: str=Depends(require_auth)):
    return {"authenticated":True}
