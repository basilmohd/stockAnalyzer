"""Position sizing engine — risk-based quantity from entry/stop-loss distance.

All capital figures are read from config at call time (config.TOTAL_CAPITAL,
MAX_RISK_PER_TRADE, MAX_POSITION_PCT, CASH_RESERVE_PCT, MIN_ORDER_VALUE) — never
hardcode them here, and never bind them at import (so they stay overridable/testable).
"""
import config
from core.logger import get_logger

logger = get_logger(__name__)


def calculate_position(
    entry_price: float, stop_loss_price: float, strategy_type: str
) -> dict:
    """Size a position so the loss at stop-loss equals a fixed fraction of capital.

    Risks ``TOTAL_CAPITAL * MAX_RISK_PER_TRADE`` per trade, derives the rupee
    position from the stop-loss distance, caps it at ``MAX_POSITION_PCT`` of
    capital, then floors to a whole share count.

    Args:
        entry_price: Intended entry price per share.
        stop_loss_price: Stop-loss price per share (must be below entry).
        strategy_type: Strategy label, echoed back in the result for traceability.

    Returns:
        On success: dict with valid=True plus quantity, position_value,
        entry_price, stop_loss_price, sl_distance_pct, max_loss, max_loss_pct,
        capital_used_pct, strategy_type.
        On failure: {"valid": False, "reason": <why>}.
    """
    total_capital = config.TOTAL_CAPITAL

    # Step 1 — fixed rupee risk budget for this trade.
    risk_amount = total_capital * config.MAX_RISK_PER_TRADE

    # Step 2 — stop-loss distance; reject a stop at/above entry (no downside room).
    sl_distance = entry_price - stop_loss_price
    if entry_price <= 0 or sl_distance <= 0:
        return {"valid": False, "reason": "Invalid stop loss"}
    sl_distance_pct = sl_distance / entry_price

    # Step 3 — rupee position implied by the risk budget and stop distance.
    position_value = risk_amount / sl_distance_pct

    # Step 4 — never exceed the per-position cap.
    max_allowed = total_capital * config.MAX_POSITION_PCT
    position_value = min(position_value, max_allowed)

    # Step 5 — floor to whole shares.
    quantity = int(position_value / entry_price)
    if quantity < 1:
        return {"valid": False, "reason": "Position too small for capital"}

    # Step 6 — actual capital deployed after flooring.
    actual_position_value = quantity * entry_price

    # Step 7 — skip tiny orders.
    if actual_position_value < config.MIN_ORDER_VALUE:
        return {"valid": False, "reason": "Below minimum order value"}

    # Step 8 — worst-case loss if the stop triggers.
    max_loss = quantity * sl_distance
    max_loss_pct = max_loss / total_capital

    return {
        "valid": True,
        "quantity": quantity,
        "position_value": round(actual_position_value, 2),
        "entry_price": round(entry_price, 2),
        "stop_loss_price": round(stop_loss_price, 2),
        "sl_distance_pct": round(sl_distance_pct, 4),
        "max_loss": round(max_loss, 2),
        "max_loss_pct": round(max_loss_pct, 4),
        "capital_used_pct": round(actual_position_value / total_capital, 4),
        "strategy_type": strategy_type,
    }


def get_available_capital() -> dict:
    """Return deployable capital after open positions and the cash reserve.

    deployable = TOTAL_CAPITAL - open_positions_value - (TOTAL_CAPITAL * CASH_RESERVE_PCT)

    open_positions_value is the mark-to-market value (quantity × current price) of all
    OPEN rows in the Trade table — the real ledger, not the Week 9 ActionLog proxy.

    Returns:
        dict with total_capital, open_positions_value, available, reserve_required,
        deployable.
    """
    from agent.journal import get_open_positions_summary

    total_capital = config.TOTAL_CAPITAL
    open_positions_value = get_open_positions_summary()["total_value"]
    available = round(total_capital - open_positions_value, 2)
    reserve_required = round(total_capital * config.CASH_RESERVE_PCT, 2)
    deployable = round(available - reserve_required, 2)

    result = {
        "total_capital": total_capital,
        "open_positions_value": open_positions_value,
        "available": available,
        "reserve_required": reserve_required,
        "deployable": deployable,
    }
    logger.debug("Available capital: %s", result)
    return result
