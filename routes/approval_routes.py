"""
Signal approval routes — Telegram button tap targets.
"""
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{token}")
async def approve_signal(token: str) -> dict:
    """Stub: validate approval token and execute queued order."""
    logger.info("Approval request received for token: %s", token)
    return {"status": "not_implemented_yet"}
