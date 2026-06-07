"""Portfolio guard — hard limits enforced before any order is proposed.

check_guards() runs each limit in order and returns (False, reason) on the FIRST
failure, or (True, "") when every guard passes. These are non-negotiable gates:
position sizing, max open positions, duplicates, sector concentration, deployable
capital, and the weekly loss circuit breaker. Risk limits are read from config at
call time so they stay overridable/testable.
"""
import config
from agent.sizing import _open_positions_proxy, get_available_capital
from agent.strategy import SECTOR_MAP
from core.logger import get_logger

logger = get_logger(__name__)


def get_open_positions_summary() -> dict:
    """Snapshot of currently open positions for guard checks and reporting.

    PROXY (Week 9): open positions come from APPROVED ActionLog rows; realized
    weekly PnL is not yet tracked (no exit/close records) so week_pnl is 0.0.
    TODO(Week 10): replace proxy reads with OPEN/CLOSED rows from the Trade table.

    Returns:
        dict with open_count, symbols, by_sector, total_value, week_pnl.
    """
    positions = _open_positions_proxy()
    symbols = [p["symbol"] for p in positions]

    by_sector: dict[str, int] = {}
    for p in positions:
        sector = SECTOR_MAP.get(p["symbol"], "Unknown")
        by_sector[sector] = by_sector.get(sector, 0) + 1

    total_value = round(sum(p["value"] for p in positions), 2)

    # TODO(Week 10): sum realized PnL of positions closed this week (Trade table).
    week_pnl = 0.0

    return {
        "open_count": len(positions),
        "symbols": symbols,
        "by_sector": by_sector,
        "total_value": total_value,
        "week_pnl": week_pnl,
    }


def check_guards(signal: dict, position: dict) -> tuple[bool, str]:
    """Run hard portfolio limits in order; return (False, reason) on first failure.

    Args:
        signal: must carry 'symbol' and 'strategy_type'.
        position: the sizing result from agent.sizing.calculate_position
            (carries 'valid', 'reason', 'position_value', 'quantity').

    Returns:
        (True, "") if every guard passes, otherwise (False, "<reason>").
    """
    symbol = signal.get("symbol", "")

    # GUARD 1 — position sizing must be valid (cheapest check, no DB read).
    if not position.get("valid"):
        return False, f"Sizing failed: {position.get('reason', 'unknown')}"

    summary = get_open_positions_summary()

    # GUARD 2 — cap on concurrent open positions.
    if summary["open_count"] >= config.MAX_OPEN_POSITIONS:
        return False, f"Max open positions ({config.MAX_OPEN_POSITIONS}) reached"

    # GUARD 3 — no duplicate position in the same symbol.
    if symbol in summary["symbols"]:
        return False, f"{symbol} already held — no duplicate"

    # GUARD 4 — sector concentration cap.
    sector = SECTOR_MAP.get(symbol, "Unknown")
    sector_count = summary["by_sector"].get(sector, 0)
    if sector_count >= config.MAX_SAME_SECTOR:
        return False, f"Max {config.MAX_SAME_SECTOR} positions in {sector} sector"

    # GUARD 5 — enough deployable capital after the cash reserve.
    cap = get_available_capital()
    position_value = position.get("position_value", 0.0)
    if position_value > cap["deployable"]:
        return False, (
            f"Insufficient deployable capital "
            f"(need ₹{position_value:,.0f}, have ₹{cap['deployable']:,.0f})"
        )

    # GUARD 6 — weekly loss circuit breaker.
    week_pnl = summary["week_pnl"]
    week_loss_pct = abs(week_pnl) / config.TOTAL_CAPITAL if week_pnl < 0 else 0.0
    if week_loss_pct >= config.WEEKLY_LOSS_LIMIT:
        return False, (
            f"Weekly loss limit hit ({week_loss_pct:.1%}) — trading paused this week"
        )

    return True, ""
