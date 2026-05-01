"""
Kite Connect OAuth and broker callback routes.
"""
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/callback")
async def kite_oauth_callback() -> dict:
    """Stub: Kite OAuth redirect target after user authorises."""
    logger.info("Kite OAuth callback received")
    return {"status": "callback_received"}
