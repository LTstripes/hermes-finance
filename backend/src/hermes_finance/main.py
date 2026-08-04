from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from hermes_finance import __version__


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


app = FastAPI(title="Hermes Finance API", version=__version__)


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
