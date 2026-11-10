from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class ModuleInfo(BaseModel):
    id: str
    name: str
    status: str
