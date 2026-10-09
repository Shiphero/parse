from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from routing_guides.config import get_settings
from routing_guides.contracts import RuleCandidate, ScenarioSnapshot
from routing_guides.db import engine, sessions
from routing_guides.models import Retailer, ServiceHeartbeat
from routing_guides.providers import ProviderStatus, provider_statuses
from routing_guides.guides_api import router as guides_router
from routing_guides.tasks import task_queue
from routing_guides.workflow_api import router as workflow_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().storage_root.mkdir(parents=True, exist_ok=True)
    async with task_queue.open_async():
        yield
    await engine.dispose()


app = FastAPI(title="Routing Guides API", version="0.1.0", lifespan=lifespan)
app.include_router(guides_router)
app.include_router(workflow_router)


class RetailerSummary(BaseModel):
    id: str
    name: str
    discovery_note: str


class WorkspaceStatus(BaseModel):
    stage: Literal["foundation"] = "foundation"
    database: Literal["connected"] = "connected"
    worker: Literal["online", "waiting"]
    worker_last_seen: datetime | None
    providers: list[ProviderStatus]
    retailers: list[RetailerSummary]


@app.get("/api/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ready")
async def ready() -> dict[str, str]:
    try:
        async with sessions() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ready"}


@app.get("/api/workspace", response_model=WorkspaceStatus)
async def workspace() -> WorkspaceStatus:
    try:
        async with sessions() as session:
            retailers = (await session.scalars(select(Retailer).order_by(Retailer.name))).all()
            heartbeat = await session.get(ServiceHeartbeat, "worker")
    except SQLAlchemyError:
        logger.warning("Workspace database query failed")
        raise HTTPException(status_code=503, detail="Workspace temporarily unavailable") from None
    seen = heartbeat.last_seen if heartbeat else None
    online = seen is not None and (datetime.now(timezone.utc) - seen).total_seconds() < 60
    return WorkspaceStatus(
        worker="online" if online else "waiting", worker_last_seen=seen,
        providers=provider_statuses(),
        retailers=[RetailerSummary(id=r.id, name=r.name, discovery_note=r.discovery_note) for r in retailers],
    )


@app.get("/api/contracts")
async def contracts() -> dict:
    return {
        "status": "draft", "version": "0.1",
        "rule_candidate": RuleCandidate.model_json_schema(),
        "scenario_snapshot": ScenarioSnapshot.model_json_schema(),
    }
