from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
import psycopg
from sqlalchemy import func, or_, select, text
from starlette.concurrency import run_in_threadpool

from routing_guides.config import get_settings
from routing_guides.db import sessions
from routing_guides.models import Guide, GuidePage, Retailer, ReleaseHead
from routing_guides.retailer_icons import MAX_ICON_BYTES, normalize_icon
from routing_guides.storage import InvalidUpload, guide_directory, save_original
from routing_guides.tasks import dsn, prepare_guide

router = APIRouter(prefix="/api", tags=["Guide library"])
GuideStatus = Literal["queued", "preparing", "ready", "needs_attention", "failed"]


class GuideSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    retailer_id: str
    title: str
    version_label: str | None
    effective_date: date | None
    filename: str
    size_bytes: int
    created_at: datetime
    status: GuideStatus
    page_count: int | None
    processed_pages: int
    attention_pages: int
    error: str | None


class RetailerCount(BaseModel):
    id: str
    name: str
    guide_count: int
    icon_url: str | None = None


class GuideLibrary(BaseModel):
    items: list[GuideSummary]
    total: int
    offset: int
    limit: int
    retailers: list[RetailerCount]
    max_upload_mb: int


class GuidePageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    page_index: int
    text_status: str
    image_status: str
    issue: str | None


class GuideDetail(GuideSummary):
    pages: list[GuidePageSummary]
    can_retry: bool


class GuidePageDetail(GuidePageSummary):
    text: str | None


class UploadResult(BaseModel):
    guide: GuideSummary
    existing: bool = False


@router.get("/guides", response_model=GuideLibrary)
async def list_guides(
    retailer_id: str | None = None,
    q: str = Query(default="", max_length=250),
    status: GuideStatus | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    sort: Literal["created_at", "title", "retailer", "effective_date"] = "created_at",
    direction: Literal["asc", "desc"] = "desc",
) -> GuideLibrary:
    filters = []
    if retailer_id:
        filters.append(Guide.retailer_id == retailer_id)
    if q.strip():
        filters.append(or_(*(column.icontains(q.strip(), autoescape=True) for column in
            (Guide.title, Guide.filename, Guide.version_label, Retailer.name))))
    if status:
        filters.append(Guide.status == status)
    column = {"created_at": Guide.created_at, "title": func.lower(Guide.title),
              "retailer": func.lower(Retailer.name), "effective_date": Guide.effective_date}[sort]
    ordering = (column.asc() if direction == "asc" else column.desc()).nulls_last()
    async with sessions() as session:
        total = await session.scalar(select(func.count()).select_from(Guide).join(Retailer).where(*filters))
        guides = (await session.scalars(select(Guide).join(Retailer).where(*filters)
            .order_by(ordering, Guide.id).offset(offset).limit(limit))).all()
        counts = (await session.execute(
            select(Retailer.id, Retailer.name, Retailer.icon_version, func.count(Guide.id))
            .outerjoin(Guide, Retailer.id == Guide.retailer_id)
            .group_by(Retailer.id, Retailer.name, Retailer.icon_version).order_by(Retailer.name)
        )).all()
    return GuideLibrary(items=[GuideSummary.model_validate(g) for g in guides], total=total, offset=offset, limit=limit,
        retailers=[RetailerCount(id=id, name=name, guide_count=count, icon_url=retailer_icon_url(id, version))
            for id, name, version, count in counts],
        max_upload_mb=get_settings().max_upload_mb)


@router.post("/guides", response_model=UploadResult, status_code=201)
async def upload_guide(
    file: Annotated[UploadFile, File()],
    retailer_id: Annotated[str, Form(max_length=50)],
    title: Annotated[str, Form(min_length=1, max_length=250)],
    version_label: Annotated[str, Form(max_length=100)] = "",
    effective_date: Annotated[date | None, Form()] = None,
) -> UploadResult:
    title = title.strip()
    if not title:
        raise HTTPException(422, "Enter a guide title.")
    async with sessions() as session:
        if not await session.get(Retailer, retailer_id):
            raise HTTPException(422, "Choose a retailer from the library.")
    guide_id = uuid4()
    filename = Path((file.filename or "guide.pdf").replace("\\", "/")).name[:250]
    try:
        digest, size = await run_in_threadpool(save_original, guide_id, file.file)
    except InvalidUpload as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        await file.close()
    existing = False
    try:
        # The guide row and its job either both commit or both roll back.
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "INSERT INTO guides (id, retailer_id, title, version_label, effective_date, filename, sha256, size_bytes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (guide_id, retailer_id, title, version_label.strip() or None, effective_date, filename, digest, size),
            )
            await prepare_guide.configure(connection=connection, lock=f"guide:{guide_id}").defer_async(guide_id=str(guide_id))
    except psycopg.errors.UniqueViolation as exc:
        if exc.diag.constraint_name != "uq_guide_retailer_hash":
            raise
        # Only discard a known duplicate. Unknown commit outcomes retain the original.
        directory = guide_directory(guide_id)
        (directory / "original.pdf").unlink()
        directory.rmdir()
        async with sessions() as session:
            guide_id = await session.scalar(select(Guide.id).where(Guide.retailer_id == retailer_id, Guide.sha256 == digest))
        existing = True
    async with sessions() as session:
        guide = await session.get(Guide, guide_id)
        return UploadResult(guide=GuideSummary.model_validate(guide), existing=existing)


@router.get("/guides/{guide_id}", response_model=GuideDetail)
async def get_guide(guide_id: UUID) -> GuideDetail:
    async with sessions() as session:
        guide = await session.get(Guide, guide_id)
        if guide is None:
            raise HTTPException(404, "Guide not found.")
        # Text content is loaded only for the selected page.
        rows = (await session.execute(select(GuidePage.page_index, GuidePage.text_status, GuidePage.image_status, GuidePage.issue)
            .where(GuidePage.guide_id == guide_id).order_by(GuidePage.page_index))).all()
        pages = [GuidePageSummary(page_index=r.page_index, text_status=r.text_status, image_status=r.image_status, issue=r.issue) for r in rows]
        can_retry = guide.status == "failed" or (guide.status == "needs_attention" and any(p.text_status == "failed" or p.image_status == "failed" for p in pages))
        return GuideDetail(**GuideSummary.model_validate(guide).model_dump(), pages=pages, can_retry=can_retry)


class GuideRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=250)
    expected_title: str = Field(min_length=1, max_length=250)

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value


@router.patch("/guides/{guide_id}", response_model=GuideSummary)
async def rename_guide(guide_id: UUID, body: GuideRename, request: Request) -> GuideSummary:
    if request.headers.get("X-Requested-With") != "routing-guide-parser":
        raise HTTPException(403, "Use the application to rename guides.")
    async with sessions.begin() as session:
        guide = await session.get(Guide, guide_id, with_for_update=True)
        if guide is None:
            raise HTTPException(404, "Guide not found.")
        if guide.title != body.expected_title:
            raise HTTPException(409, "This guide was renamed elsewhere. Cancel and try again with the current title.")
        guide.title = body.title
        await session.flush()
        return GuideSummary.model_validate(guide)


@router.post("/guides/{guide_id}/retry", status_code=202)
async def retry_preparation(guide_id: UUID) -> dict[str, str]:
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute("SELECT status FROM guides WHERE id = %s FOR UPDATE", (guide_id,))
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(404, "Guide not found.")
        if row[0] not in {"failed", "needs_attention"}:
            raise HTTPException(409, "This guide does not need preparation retried.")
        await connection.execute("UPDATE guides SET status = 'queued', error = NULL WHERE id = %s", (guide_id,))
        await prepare_guide.configure(connection=connection, lock=f"guide:{guide_id}").defer_async(guide_id=str(guide_id))
    return {"status": "queued"}


@router.get("/guides/{guide_id}/original")
async def original_pdf(guide_id: UUID) -> FileResponse:
    async with sessions() as session:
        guide = await session.get(Guide, guide_id)
        if guide is None:
            raise HTTPException(404, "Guide not found.")
        filename = guide.filename
    path = guide_directory(guide_id) / "original.pdf"
    if not path.is_file():
        raise HTTPException(404, "The original file is unavailable.")
    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.get("/guides/{guide_id}/pages/{page_index}", response_model=GuidePageDetail)
async def page_detail(guide_id: UUID, page_index: int) -> GuidePageDetail:
    async with sessions() as session:
        page = await session.get(GuidePage, (guide_id, page_index))
        if page is None:
            raise HTTPException(404, "Page not found.")
        return GuidePageDetail.model_validate(page)


@router.get("/guides/{guide_id}/pages/{page_index}/image")
async def page_image(guide_id: UUID, page_index: int) -> FileResponse:
    async with sessions() as session:
        page = await session.get(GuidePage, (guide_id, page_index))
        if page is None or page.image_status != "ready":
            raise HTTPException(404, "This page preview is not available yet.")
    path = guide_directory(guide_id) / f"page-{page_index}.png"
    if not path.is_file():
        raise HTTPException(404, "This page preview is unavailable.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


def retailer_icon_url(retailer_id: str, version: str | None) -> str | None:
    return f"/api/retailers/{retailer_id}/icon?v={version}" if version else None


class RetailerIconResult(BaseModel):
    icon_url: str | None


def require_retailer_editor(request: Request) -> None:
    # Matches Connections' same-origin browser write guard; this is not user auth.
    if request.headers.get('X-Requested-With') != 'routing-guide-parser':
        raise HTTPException(403, 'Use the application to manage retailers.')


@router.put('/retailers/{retailer_id}/icon', response_model=RetailerIconResult)
async def upload_retailer_icon(retailer_id: str, request: Request, file: Annotated[UploadFile, File()]):
    require_retailer_editor(request)
    try:
        async with sessions() as session:
            if not await session.get(Retailer, retailer_id):
                raise HTTPException(404, 'Retailer not found.')
        content = await file.read(MAX_ICON_BYTES + 1)
        try:
            image = await run_in_threadpool(normalize_icon, content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        version = sha256(image).hexdigest()
        async with sessions.begin() as session:
            retailer = await session.get(Retailer, retailer_id)
            if retailer is None:
                raise HTTPException(404, 'Retailer not found.')
            retailer.icon_png = image
            retailer.icon_version = version
        return RetailerIconResult(icon_url=retailer_icon_url(retailer_id, version))
    finally:
        await file.close()


@router.delete('/retailers/{retailer_id}/icon', response_model=RetailerIconResult)
async def delete_retailer_icon(retailer_id: str, request: Request):
    require_retailer_editor(request)
    async with sessions.begin() as session:
        retailer = await session.get(Retailer, retailer_id)
        if retailer is None:
            raise HTTPException(404, 'Retailer not found.')
        retailer.icon_png = None
        retailer.icon_version = None
    return RetailerIconResult(icon_url=None)


@router.get('/retailers/{retailer_id}/icon')
async def get_retailer_icon(retailer_id: str):
    async with sessions() as session:
        content = await session.scalar(select(Retailer.icon_png).where(Retailer.id == retailer_id))
    if content is None:
        raise HTTPException(404, 'Retailer icon not found.')
    return Response(content, media_type='image/png', headers={
        'Cache-Control': 'private, max-age=0, must-revalidate', 'X-Content-Type-Options': 'nosniff'})


class RetailerInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value):
        return ' '.join(value.split()) if isinstance(value, str) else value


class RetailerUpdate(RetailerInput):
    expected_name: str = Field(min_length=1, max_length=100)


@router.get('/retailers', response_model=list[RetailerCount])
async def list_retailers():
    async with sessions() as session:
        rows = (await session.execute(select(Retailer.id, Retailer.name, Retailer.icon_version, func.count(Guide.id))
            .outerjoin(Guide, Retailer.id == Guide.retailer_id)
            .group_by(Retailer.id, Retailer.name, Retailer.icon_version)
            .order_by(func.lower(Retailer.name), Retailer.id))).all()
    return [RetailerCount(id=id, name=name, guide_count=count, icon_url=retailer_icon_url(id, version))
            for id, name, version, count in rows]


@router.post('/retailers', response_model=RetailerCount, status_code=201)
async def create_retailer(body: RetailerInput, request: Request):
    require_retailer_editor(request)
    async with sessions.begin() as session:
        # Serialize name changes to reject simultaneous case-insensitive duplicates.
        await session.execute(text('SELECT pg_advisory_xact_lock(914823)'))
        if await session.scalar(select(Retailer.id).where(func.lower(Retailer.name) == body.name.lower())):
            raise HTTPException(409, 'A retailer with this name already exists.')
        retailer_id = 'retailer-' + uuid4().hex
        session.add(Retailer(id=retailer_id, name=body.name, discovery_note=''))
        await session.flush()
        session.add(ReleaseHead(retailer_id=retailer_id, release_id=None))
    return RetailerCount(id=retailer_id, name=body.name, guide_count=0)


@router.put('/retailers/{retailer_id}', response_model=RetailerCount)
async def rename_retailer(retailer_id: str, body: RetailerUpdate, request: Request):
    require_retailer_editor(request)
    async with sessions.begin() as session:
        await session.execute(text('SELECT pg_advisory_xact_lock(914823)'))
        retailer = await session.get(Retailer, retailer_id, with_for_update=True)
        if retailer is None:
            raise HTTPException(404, 'Retailer not found.')
        if retailer.name != body.expected_name:
            raise HTTPException(409, 'This retailer was renamed elsewhere. Cancel and try again with the current name.')
        duplicate = await session.scalar(select(Retailer.id).where(
            func.lower(Retailer.name) == body.name.lower(), Retailer.id != retailer_id))
        if duplicate:
            raise HTTPException(409, 'A retailer with this name already exists.')
        retailer.name = body.name
        count = await session.scalar(select(func.count()).select_from(Guide).where(Guide.retailer_id == retailer_id))
        return RetailerCount(id=retailer.id, name=retailer.name, guide_count=count,
                             icon_url=retailer_icon_url(retailer.id, retailer.icon_version))
