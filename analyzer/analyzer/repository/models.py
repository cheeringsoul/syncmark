"""SQLAlchemy ORM models — mirror .bodhi/entities/*.yaml."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"
    __table_args__ = (UniqueConstraint("channel_id", "message_id", name="uq_tgmsg_channel_msg"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    channel_name: Mapped[str] = mapped_column(String(255))
    message_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    media_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    telegram_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sentiment: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    related_symbols: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(32)), nullable=True)
    importance: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=0)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EconomicEvent(Base):
    __tablename__ = "economic_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(5))
    importance: Mapped[str] = mapped_column(String(10))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    forecast: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actual: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, default=0)
    ai_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AiAnalysis(Base):
    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ref_type: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(50))
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Kline(Base):
    __tablename__ = "klines"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol", "interval", "open_time", name="uq_kline"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(20))
    interval: Mapped[str] = mapped_column(String(5))
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 8))
    quote_volume: Mapped[Decimal] = mapped_column(Numeric(30, 8))
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RotationSignal(Base):
    __tablename__ = "rotation_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20))
    signal_type: Mapped[str] = mapped_column(String(20))
    benchmark: Mapped[str] = mapped_column(String(20))
    rs_current: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    rs_peak: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    rs_delta: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    coin_return_long: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    coin_return_short: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    benchmark_return_short: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    volatility: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    status: Mapped[int] = mapped_column(SmallInteger, default=0)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


NEWS_STATUS_RAW = 0
NEWS_STATUS_ANALYZING = 1
NEWS_STATUS_ANALYZED = 2
NEWS_STATUS_PUBLISHED = 3

ECON_STATUS_SCHEDULED = 0
ECON_STATUS_UPCOMING = 1
ECON_STATUS_PUBLISHED = 2

ROTATION_STATUS_DETECTED = 0
ROTATION_STATUS_ACTIVE = 1
ROTATION_STATUS_EXPIRED = 2
ROTATION_STATUS_VERIFIED = 3
