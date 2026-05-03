"""
ORM model for daily portfolio snapshots.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class PortfolioSnapshot(Base):
    """Point-in-time snapshot of holdings and P&L, stored once per day."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)
    holdings_json: Mapped[str] = mapped_column(Text, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    day_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    overall_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    health_score_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
