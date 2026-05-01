"""
Telegram bot webhook routes.
"""
import logging
from typing import Any

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    """Stub: receive Telegram update payloads."""
    payload: Any = await request.json()
    logger.info("Telegram webhook received: %s", payload)
    return {"status": "ok"}
