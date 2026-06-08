"""
Signal approval routes — HTTP fallback for local dev (Telegram webhooks not reachable locally).
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agent.journal import open_trade, update_action_log
from config import PAPER_TRADE_MODE
from core.approval import mark_approved, mark_skipped, validate_token
from core.db import get_db
from core.telegram_bot import send_alert

logger = logging.getLogger(__name__)

router = APIRouter()


async def handle_signal_execution(token: str) -> dict:
    """Execute a Kite order for the signal linked to *token*.

    Called when user taps [✅ EXECUTE] on a signal alert. Validates the token,
    fetches the linked signal from SQLite (or handles STOPLOSS directly),
    places the order, records it, and sends a Telegram confirmation. 
    Never raises — returns error dict on failure.
    """
    result = validate_token(token)
    if not result["valid"]:
        await send_alert(
            "Token Expired",
            "⚠️ Token expired or invalid — please resend the signal.",
            alert_type="WARNING",
        )
        return {"status": "error", "reason": result["reason"]}

    action_type = result.get("action_type")
    
    # Handle STOPLOSS execution directly (no signal_id needed)
    if action_type == "STOPLOSS":
        symbol = result.get("symbol")
        if not symbol:
            await send_alert(
                "Execution Error",
                "⚠️ No symbol linked to this stop-loss token.",
                alert_type="WARNING",
            )
            return {"status": "error", "reason": "No symbol on STOPLOSS token"}
        
        from core.kite_client import KiteClient
        
        # Determine quantity from holdings
        kite = KiteClient()
        holdings = kite.get_holdings()
        quantity = 0
        for holding in holdings:
            if holding.get("tradingsymbol") == symbol:
                quantity = holding.get("quantity", 0)
                break
        
        if quantity <= 0:
            await send_alert(
                "Execution Error",
                f"⚠️ No shares found for {symbol} in holdings.",
                alert_type="WARNING",
            )
            return {"status": "error", "reason": f"No shares of {symbol} to sell"}
        
        order_result = kite.place_order(symbol, "SELL", quantity)
        
        if order_result.get("status") == "COMPLETE":
            # Clear holdings cache so next SL/signal check gets fresh data
            from config import REDIS_URL
            from core.redis_client import RedisClient
            redis_client = RedisClient(REDIS_URL)
            cleared = redis_client.delete("kite:holdings_cache")
            logger.info("Holdings cache cleared after SL exit: %s", cleared)
            
            order_id = order_result["order_id"]
            
            with get_db() as db:
                from models.order import Order
                order_rec = Order(
                    signal_id=None,
                    kite_order_id=order_id,
                    symbol=symbol,
                    action="SELL",
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
                "Stop-Loss Exit Executed",
                f"✅ STOPLOSS EXIT EXECUTED\n{symbol} | SELL | Qty: {quantity}\nOrder ID: {order_id}",
                alert_type="SUCCESS",
            )
            logger.info("STOPLOSS exit executed: %s SELL qty=%d order_id=%s", symbol, quantity, order_id)
            return {"status": "ok", "order_id": order_id, "symbol": symbol, "action": "SELL"}
        
        error = order_result.get("error", "Unknown error")
        await send_alert("Stop-Loss Exit Failed", f"❌ Exit Failed — {error}", alert_type="WARNING")
        logger.error("STOPLOSS exit failed: %s: %s", symbol, error)
        return {"status": "error", "reason": error}
    
    # Handle SIGNAL execution (original logic)
    signal_id = result.get("signal_id")
    if not signal_id:
        await send_alert(
            "Execution Error",
            "⚠️ No signal linked to this token.",
            alert_type="WARNING",
        )
        return {"status": "error", "reason": "No signal_id on token"}

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

    # Clear holdings cache after successful order so next SL/signal check gets fresh data
    if order_result.get("status") == "COMPLETE":
        from config import REDIS_URL
        from core.redis_client import RedisClient
        redis_client = RedisClient(REDIS_URL)
        cleared = redis_client.delete("kite:holdings_cache")
        logger.info("Holdings cache cleared after order execution: %s", cleared)

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
        # Flip the signal's PENDING ActionLog → APPROVED; capture its id to link the Trade.
        action_log_id = update_action_log(signal_id, "APPROVED")

        # Open a Trade ledger row for new BUY entries (paper or live). Exit-side
        # actions (SELL/REDUCE/EXIT) close positions and are handled by the exit
        # monitor (Week 11), not opened here.
        if action.upper() == "BUY":
            from models.action_log import ActionLog

            strategy_type = suggested_sl = suggested_target = None
            sized_qty = quantity
            if action_log_id:
                with get_db() as db:
                    al = db.query(ActionLog).filter(ActionLog.id == action_log_id).first()
                    if al:
                        strategy_type = al.strategy_type
                        suggested_sl = al.suggested_sl
                        suggested_target = al.suggested_target
                        sized_qty = al.suggested_qty or quantity

            # Actual fill price (paper mode fills at the live quote). Fall back to the
            # ActionLog entry price if a fill price wasn't reported (mock/live paths).
            fill_price = order_result.get("fill_price")
            if not fill_price and action_log_id:
                fill_price = al.entry_price if al else 0.0
            fill_price = fill_price or 0.0

            signal_for_trade = {
                "symbol": symbol,
                "strategy_type": strategy_type,
                "quantity": sized_qty,
                "suggested_sl": suggested_sl,
                "suggested_target": suggested_target,
                "signal_id": signal_id,
            }
            trade_id = open_trade(signal_for_trade, fill_price, order_id, action_log_id)

            paper_tag = " (PAPER)" if PAPER_TRADE_MODE else ""
            target_str = f"₹{suggested_target:.2f}" if suggested_target else "—"
            sl_str = f"₹{suggested_sl:.2f}" if suggested_sl else "—"
            await send_alert(
                "Trade Opened",
                (
                    f"✅ *Trade Opened{paper_tag}*\n"
                    f"{symbol} | BUY {sized_qty} @ ₹{fill_price:.2f}\n"
                    f"🎯 Target: {target_str} | 🛡 SL: {sl_str}\n"
                    f"Order: {order_id}"
                ),
                alert_type="SUCCESS",
            )
            logger.info(
                "Trade opened: %s BUY qty=%d fill=%.2f order_id=%s trade_id=%s (paper=%s)",
                symbol, sized_qty, fill_price, order_id, trade_id, PAPER_TRADE_MODE,
            )
            return {
                "status": "ok", "order_id": order_id, "symbol": symbol,
                "action": action, "trade_id": trade_id,
            }

        await send_alert(
            "Order Executed",
            f"✅ Order Executed\n{symbol} | {action} | Qty: {quantity}\nOrder ID: {order_id}",
            alert_type="SUCCESS",
        )
        logger.info("Order executed: %s %s qty=%d order_id=%s", symbol, action, quantity, order_id)
        return {"status": "ok", "order_id": order_id, "symbol": symbol, "action": action}

    # Order failed — record EXECUTION_FAILED on the signal's ActionLog and alert.
    error = order_result.get("error", "Unknown error")
    update_action_log(signal_id, "EXECUTION_FAILED")
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
        update_action_log(token, "APPROVED")
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
    update_action_log(token, "SKIPPED")
    await send_alert(
        "Signal Skipped",
        f"Token {token[:8]}... skipped via HTTP fallback.",
        alert_type="INFO",
    )
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "message": "Token skipped"},
    )
