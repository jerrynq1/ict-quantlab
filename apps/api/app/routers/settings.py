from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from app.security import require_auth
from app.services.store import get_value, set_value
from app.engines.time_utils import SESSION_WINDOWS, set_session_windows

router = APIRouter(prefix="/settings", tags=["workspace settings"])
DEFAULTS = {
    "Asia": (20*60, 0),
    "London": (2*60, 5*60),
    "NY AM": (7*60, 10*60),
    "London Close": (10*60, 12*60),
    "NY PM": (13*60, 16*60),
}


def _to_hhmm(value: int) -> str:
    value = int(value) % 1440
    return f"{value//60:02d}:{value%60:02d}"


def parse_session_profile(profile: dict) -> dict[str, tuple[int, int]]:
    parsed = {}
    for name, pair in profile.items():
        def minute(value):
            parts = str(value).split(":")
            if len(parts) != 2: raise ValueError("Time must use HH:MM")
            hour, minute_value = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute_value <= 59): raise ValueError("Invalid HH:MM")
            return hour*60+minute_value
        parsed[name] = (minute(pair["start"]), minute(pair["end"]))
    return parsed


def public_profile() -> dict:
    profile = get_value("session_profile", None)
    if profile is None:
        profile = {name: {"start": _to_hhmm(start), "end": _to_hhmm(end)} for name, (start, end) in DEFAULTS.items()}
    return {"timezone": "America/New_York", "windows": profile}


class SessionWindow(BaseModel):
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class SessionProfileBody(BaseModel):
    windows: dict[str, SessionWindow]

    @field_validator("windows")
    @classmethod
    def validate_windows(cls, value):
        expected = set(DEFAULTS)
        if set(value) != expected:
            raise ValueError(f"Provide exactly these sessions: {', '.join(sorted(expected))}")
        for name, pair in value.items():
            if pair.start == pair.end:
                raise ValueError(f"{name} start and end cannot be equal")
        return value


@router.get("/session-profile")
async def get_session_profile(_: str = Depends(require_auth)):
    return public_profile()


@router.put("/session-profile")
async def update_session_profile(body: SessionProfileBody, _: str = Depends(require_auth)):
    profile = {name: pair.model_dump() for name, pair in body.windows.items()}
    try:
        set_session_windows(parse_session_profile(profile))
        set_value("session_profile", profile)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return public_profile()
