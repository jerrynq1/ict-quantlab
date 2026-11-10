from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.db import init_db
from app.routers.auth import router as auth_router
from app.routers.ctrader import router as ctrader_router
from app.routers.data import router as data_router
from app.routers.analytics import router as analytics_router
from app.routers.research import router as research_router
from app.routers.settings import router as settings_router
from app.services.store import get_value
from app.engines.time_utils import set_session_windows

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    profile = get_value("session_profile", None)
    if profile:
        try:
            from app.routers.settings import parse_session_profile
            set_session_windows(parse_session_profile(profile))
        except Exception:
            pass
    yield

app=FastAPI(title="ICT QuantLab API",version="1.0.0",description="Research and forecasting backend for ICT QuantLab",lifespan=lifespan,
            docs_url="/docs" if settings.environment!="production" else None,
            redoc_url=None)
allowed_hosts = [x.strip() for x in settings.trusted_hosts.split(",") if x.strip()] or ["*"]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origin_list,allow_credentials=False,
                   allow_methods=["GET","POST","PUT","DELETE","OPTIONS"],allow_headers=["Authorization","Content-Type","X-Client-Run"])
app.include_router(auth_router,prefix=settings.api_prefix)
app.include_router(ctrader_router,prefix=settings.api_prefix)
app.include_router(data_router,prefix=settings.api_prefix)
app.include_router(analytics_router)
app.include_router(research_router,prefix=settings.api_prefix)
app.include_router(settings_router,prefix=settings.api_prefix)

@app.get("/")
async def root():
    return {"service": "ict-quantlab-api", "docs": "/docs" if settings.environment != "production" else None}

@app.get("/api/v1/system/health")
async def health():
    return {"status":"ok","service":"ict-quantlab-api","version":"1.0.0"}

@app.get("/api/v1/system/readiness")
async def readiness():
    missing=[]
    if not settings.admin_password: missing.append("ICTQL_ADMIN_PASSWORD")
    if not settings.encryption_key: missing.append("ICTQL_ENCRYPTION_KEY")
    if not settings.session_secret: missing.append("ICTQL_SESSION_SECRET")
    return JSONResponse(status_code=503 if missing else 200,content={"ready":not missing,"missing_configuration":missing})
