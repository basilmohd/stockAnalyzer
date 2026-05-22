"""
ORM model for one-time approval tokens sent to the user via Telegram.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class Approval(Base):
    """A one-time token that lets the user approve or reject an agent action."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    signal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("signals.id"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)  # SIGNAL/STOPLOSS
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)  # For STOPLOSS actions
    status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
