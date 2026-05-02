"""
Signal approval routes — Telegram button tap targets.
"""
import logging
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.db import SessionLocal
from models.approval import Approval

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{token}")
async def approve_signal(token: str) -> JSONResponse:
    """
    Validate a one-time approval token against the SQLite approvals table.
    Order execution wired in Week 2.
    """
    logger.info("Approval request received for token: %s", token)

    with SessionLocal() as db:
        record: Approval | None = db.query(Approval).filter_by(token=token).first()

    if record is None:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Token not found"},
        )

    if record.expires_at < datetime.utcnow():
        return JSONResponse(
            status_code=410,
            content={"status": "error", "message": "Token expired"},
        )

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "message": "Token valid — execution coming in Week 2"},
    )
