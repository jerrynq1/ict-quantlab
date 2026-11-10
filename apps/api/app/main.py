from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.settings import settings
from app.api.routes import router
from app.storage.database import initialize_database


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    initialize_database()
    yield


app = FastAPI(title="ICT QuantLab API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router, prefix="/api/v1")


@app.get("/")
def root():
    return {"name": "ICT QuantLab API", "version": app.version}
