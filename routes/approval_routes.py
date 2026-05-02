"""
Signal approval routes — HTTP fallback for local dev (Telegram webhooks not reachable locally).
"""
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from core.approval import mark_approved, mark_skipped, validate_token
from core.telegram_bot import send_alert

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{token}")
async def approve_signal(
    token: str,
    action: str = Query(default="approve"),
) -> JSONResponse:
    """
    HTTP fallback endpoint to approve or skip a signal token.
    Used during local dev since Telegram cannot POST to localhost.
    action: "approve" (default) | "skip"
    """
    if action not in ("approve", "skip"):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "action must be 'approve' or 'skip'"},
        )

    logger.info("HTTP approval: action=%s token=%s...", action, token[:8])

    result = validate_token(token)
    if not result["valid"]:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": result["reason"]},
        )

    if action == "approve":
        mark_approved(token)
        await send_alert(
            "Order Approved",
            f"Token {token[:8]}... approved via HTTP fallback. Execution in progress.",
            alert_type="SUCCESS",
        )
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "message": "Token approved"},
        )

    mark_skipped(token)
    await send_alert(
        "Signal Skipped",
        f"Token {token[:8]}... skipped via HTTP fallback.",
        alert_type="INFO",
    )
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "message": "Token skipped"},
    )
