"""ORM model for the Trade ledger — the real open/closed position record.

Replaces the Week 9 ActionLog "APPROVED row = open position" proxy. Every approved
signal opens a Trade row (paper or live); exits close it with realized PnL. The exit
monitor queries OPEN rows constantly, so status/symbol/entry_date are indexed.
"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class Trade(Base):
    """A single position — open while held, closed on exit with realized PnL."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_type: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # ── Entry ───────────────────────────────────────────────────────────────────
    entry_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    position_value: Mapped[float] = mapped_column(Float, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss_price: Mapped[float] = mapped_column(Float, nullable=False)
    time_stop_date: Mapped[date] = mapped_column(Date, nullable=False)  # entry + N days per strategy

    # ── Lifecycle ───────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(15), default="OPEN", nullable=False)  # OPEN/CLOSED/CANCELLED

    # ── Exit ────────────────────────────────────────────────────────────────────
    exit_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)  # TARGET/STOPLOSS/TIME_STOP/MANUAL
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Order linkage ───────────────────────────────────────────────────────────
    order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)       # PAPER-xxx or real Kite order id
    exit_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Source linkage ──────────────────────────────────────────────────────────
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)      # FK → signals.id
    action_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # FK → action_logs.id

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    __table_args__ = (
        Index("ix_trades_status", "status"),
        Index("ix_trades_symbol", "symbol"),
        Index("ix_trades_entry_date", "entry_date"),
    )
