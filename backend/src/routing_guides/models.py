from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from routing_guides.db import Base


class Retailer(Base):
    __tablename__ = "retailers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    discovery_note: Mapped[str] = mapped_column(Text)
    icon_png: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    icon_version: Mapped[str | None] = mapped_column(String(64))


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"

    service: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Guide(Base):
    __tablename__ = "guides"
    __table_args__ = (UniqueConstraint("retailer_id", "sha256", name="uq_guide_retailer_hash"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    retailer_id: Mapped[str] = mapped_column(ForeignKey("retailers.id"), index=True)
    series_id: Mapped[UUID | None] = mapped_column(ForeignKey("guides.id"), index=True)
    previous_guide_id: Mapped[UUID | None] = mapped_column(ForeignKey("guides.id"))
    edition_number: Mapped[int] = mapped_column(Integer, server_default="1")
    title: Mapped[str] = mapped_column(String(250))
    version_label: Mapped[str | None] = mapped_column(String(100))
    effective_date: Mapped[date | None] = mapped_column(Date)
    filename: Mapped[str] = mapped_column(String(250))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(30), server_default="queued")
    page_count: Mapped[int | None] = mapped_column(Integer)
    processed_pages: Mapped[int] = mapped_column(Integer, server_default="0")
    attention_pages: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)


class GuidePage(Base):
    __tablename__ = "guide_pages"

    guide_id: Mapped[UUID] = mapped_column(ForeignKey("guides.id"), primary_key=True)
    page_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str | None] = mapped_column(Text)
    text_status: Mapped[str] = mapped_column(String(20), server_default="pending")
    image_status: Mapped[str] = mapped_column(String(20), server_default="pending")
    issue: Mapped[str | None] = mapped_column(Text)


from sqlalchemy.dialects.postgresql import JSONB


class AnalysisRun(Base):
    __tablename__ = 'analysis_runs'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    guide_id: Mapped[UUID] = mapped_column(ForeignKey('guides.id'), index=True)
    status: Mapped[str] = mapped_column(String(30), default='queued')
    version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSONB)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuleRelease(Base):
    __tablename__ = 'rule_releases'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    retailer_id: Mapped[str] = mapped_column(ForeignKey('retailers.id'), index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey('analysis_runs.id'), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    effective_date: Mapped[date] = mapped_column(Date)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReleaseHead(Base):
    __tablename__ = 'release_heads'
    retailer_id: Mapped[str] = mapped_column(ForeignKey('retailers.id'), primary_key=True)
    release_id: Mapped[UUID | None] = mapped_column(ForeignKey('rule_releases.id'))


class Scenario(Base):
    __tablename__ = 'scenarios'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    retailer_id: Mapped[str] = mapped_column(ForeignKey('retailers.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evaluation(Base):
    __tablename__ = 'evaluations'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    scenario_id: Mapped[UUID] = mapped_column(ForeignKey('scenarios.id'))
    release_id: Mapped[UUID] = mapped_column(ForeignKey('rule_releases.id'))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
