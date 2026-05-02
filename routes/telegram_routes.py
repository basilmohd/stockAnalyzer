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
    """
    Receive Telegram update payloads. Logs update type and approval callbacks.
    Full callback handling wired in Week 2.
    """
    payload: Any = await request.json()

    if "callback_query" in payload:
        data = payload["callback_query"].get("data", "")
        logger.info("Approval callback received: %s", data)
    elif "message" in payload:
        logger.info("Telegram update type: message")
    else:
        update_type = next(iter(payload.keys()), "unknown")
        logger.info("Telegram update type: %s", update_type)

    return {"status": "ok"}
