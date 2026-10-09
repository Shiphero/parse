from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from routing_guides.db import Base


class Retailer(Base):
    __tablename__ = "retailers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    discovery_note: Mapped[str] = mapped_column(Text)


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"

    service: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Guide(Base):
    __tablename__ = "guides"
    __table_args__ = (UniqueConstraint("retailer_id", "sha256", name="uq_guide_retailer_hash"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    retailer_id: Mapped[str] = mapped_column(ForeignKey("retailers.id"), index=True)
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
