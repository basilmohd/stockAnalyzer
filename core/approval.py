"""
Approval token engine — generate, validate, and expire one-time action tokens.
"""
import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.db import get_db
from models.approval import Approval
import models.signal  # noqa: F401 — ensures 'signals' table is registered for FK resolution
from config import APPROVAL_EXPIRY_MINS, SL_APPROVAL_EXPIRY_MINS, TIMEZONE

logger = logging.getLogger(__name__)
IST = ZoneInfo(TIMEZONE)


def generate_token(
    action_type: str,
    signal_id: int | None = None,
    symbol: str | None = None,
    expiry_mins: int | None = None,
) -> str:
    """Create a PENDING approval token and persist it to SQLite. Returns the token string."""
    if expiry_mins is None:
        expiry_mins = (
            SL_APPROVAL_EXPIRY_MINS if action_type == "STOPLOSS" else APPROVAL_EXPIRY_MINS
        )

    token = str(uuid.uuid4())
    expires_at = datetime.now(IST) + timedelta(minutes=expiry_mins)

    with get_db() as db:
        record = Approval(
            token=token,
            signal_id=signal_id,
            action_type=action_type,
            symbol=symbol,
            status="PENDING",
            expires_at=expires_at,
        )
        db.add(record)
        db.commit()

    logger.info("Approval token generated: %s... expires in %dmin", token[:8], expiry_mins)
    return token


def validate_token(token: str) -> dict:
    """Check whether a token is valid and still PENDING. Returns a result dict."""
    with get_db() as db:
        approval = db.query(Approval).filter(Approval.token == token).first()

        if approval is None:
            return {"valid": False, "reason": "Token not found"}

        if approval.status != "PENDING":
            return {"valid": False, "reason": f"Token already {approval.status}"}

        if approval.expires_at.replace(tzinfo=IST) < datetime.now(IST):
            approval.status = "EXPIRED"
            db.commit()
            return {"valid": False, "reason": "Token expired"}

        return {
            "valid": True,
            "token": token,
            "action_type": approval.action_type,
            "signal_id": approval.signal_id,
            "symbol": approval.symbol,
            "expires_at": str(approval.expires_at),
        }


def mark_approved(token: str) -> bool:
    """Transition a PENDING token to APPROVED. Returns False if not found or not PENDING."""
    with get_db() as db:
        approval = db.query(Approval).filter(Approval.token == token).first()
        if approval is None or approval.status != "PENDING":
            return False
        approval.status = "APPROVED"
        approval.responded_at = datetime.now(IST)
        db.commit()

    logger.info("Token %s... APPROVED", token[:8])
    return True


def mark_skipped(token: str) -> bool:
    """Transition a PENDING token to SKIPPED. Returns False if not found or not PENDING."""
    with get_db() as db:
        approval = db.query(Approval).filter(Approval.token == token).first()
        if approval is None or approval.status != "PENDING":
            return False
        approval.status = "SKIPPED"
        approval.responded_at = datetime.now(IST)
        db.commit()

    logger.info("Token %s... SKIPPED", token[:8])
    return True


def cleanup_expired_tokens() -> int:
    """Mark all PENDING tokens past their expiry as EXPIRED. Returns count cleaned up."""
    now = datetime.now(IST)
    with get_db() as db:
        expired = (
            db.query(Approval)
            .filter(Approval.status == "PENDING", Approval.expires_at < now)
            .all()
        )
        for record in expired:
            record.status = "EXPIRED"
        db.commit()
        count = len(expired)

    logger.info("Cleaned up %d expired tokens", count)
    return count
