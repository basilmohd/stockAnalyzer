"""
Signal approval routes — HTTP fallback for local dev (Telegram webhooks not reachable locally).
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from core.approval import mark_approved, mark_skipped, validate_token
from core.telegram_bot import send_alert

logger = logging.getLogger(__name__)

router = APIRouter()


async def handle_signal_execution(token: str) -> dict:
    """Execute a Kite order for the signal linked to *token*.

    Called when user taps [✅ EXECUTE] on a signal alert. Validates the token,
    fetches the linked signal from SQLite, places the order, records it, and
    sends a Telegram confirmation. Never raises — returns error dict on failure.
    """
    result = validate_token(token)
    if not result["valid"]:
        await send_alert(
            "Token Expired",
            "⚠️ Token expired or invalid — please resend the signal.",
            alert_type="WARNING",
        )
        return {"status": "error", "reason": result["reason"]}

    signal_id = result.get("signal_id")
    if not signal_id:
        await send_alert(
            "Execution Error",
            "⚠️ No signal linked to this token.",
            alert_type="WARNING",
        )
        return {"status": "error", "reason": "No signal_id on token"}

    from core.db import get_db
    from core.kite_client import KiteClient
    from models.order import Order
    from models.signal import Signal

    with get_db() as db:
        signal = db.query(Signal).filter(Signal.id == signal_id).first()
        if not signal:
            return {"status": "error", "reason": f"Signal {signal_id} not found"}
        symbol = signal.symbol
        action = signal.action
        quantity = signal.suggested_qty or 1

    kite = KiteClient()
    order_result = kite.place_order(symbol, action, quantity)

    if order_result.get("status") == "COMPLETE":
        order_id = order_result["order_id"]

        with get_db() as db:
            signal_rec = db.query(Signal).filter(Signal.id == signal_id).first()
            if signal_rec:
                signal_rec.status = "EXECUTED"
            order_rec = Order(
                signal_id=signal_id,
                kite_order_id=order_id,
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type="MARKET",
                product="CNC",
                status="COMPLETE",
                placed_at=datetime.now(),
            )
            db.add(order_rec)
            db.commit()

        mark_approved(token)

        await send_alert(
            "Order Executed",
            f"✅ Order Executed\n{symbol} | {action} | Qty: {quantity}\nOrder ID: {order_id}",
            alert_type="SUCCESS",
        )
        logger.info("Order executed: %s %s qty=%d order_id=%s", symbol, action, quantity, order_id)
        return {"status": "ok", "order_id": order_id, "symbol": symbol, "action": action}

    error = order_result.get("error", "Unknown error")
    await send_alert("Order Failed", f"❌ Order Failed — {error}", alert_type="WARNING")
    logger.error("Order execution failed: %s %s: %s", symbol, action, error)
    return {"status": "error", "reason": error}


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
