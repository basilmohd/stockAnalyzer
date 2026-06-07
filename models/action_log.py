"""ORM model for logging every signal where any action is taken."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class ActionLog(Base):
    """Audit record created for every signal that passes or fails entry validation."""

    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # FK → signals.id
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    signal_action: Mapped[str | None] = mapped_column(String(10), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_sl: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_taken: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    rejection_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telegram_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    action_taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_time_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # FK → trades.id (Week 10)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_action_logs_symbol_created_at", "symbol", "created_at"),
        Index("ix_action_logs_action_taken", "action_taken"),
        Index("ix_action_logs_strategy_type", "strategy_type"),
    )
