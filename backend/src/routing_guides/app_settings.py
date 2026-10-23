"""Non-secret preferences. Deployment defaults are imported once by bootstrap."""
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from routing_guides.db import sessions
from routing_guides.models import ApplicationSetting


class UploadSettings(BaseModel):
    max_upload_mb: int = Field(default=256, ge=1, le=1024)


async def setting(name: str, default):
    async with sessions() as session:
        row = await session.get(ApplicationSetting, name)
        return row.value['value'] if row else default


async def save_setting(name: str, value):
    async with sessions.begin() as session:
        await session.execute(insert(ApplicationSetting).values(name=name, value={'value': value})
            .on_conflict_do_update(index_elements=['name'], set_={'value': {'value': value}}))


async def upload_settings() -> UploadSettings:
    return UploadSettings(max_upload_mb=await setting('max_upload_mb', 256))
