"""
End-to-end simulation: SL breach → Telegram alert → button tap → approval.

Usage (run from project root):
    python scripts/simulate_sl_breach.py [SYMBOL]

Default symbol: ICICIBANK
"""
import asyncio
import logging
import os
import sys

# Project root is the parent of this file's directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import REDIS_URL
from core.redis_client import RedisClient
from mocks.kite_mock import MockKiteClient
from agent.stoploss import run_sl_monitor, get_sl_threshold

# Force UTF-8 output on Windows so rupee symbol prints correctly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("simulate_sl_breach")

_DIVIDER = "=" * 55


def _find_holding(symbol: str) -> dict:
    """Return the mock holding for *symbol*, or raise with a helpful message."""
    holdings = MockKiteClient().get_holdings()
    available = [h["tradingsymbol"] for h in holdings]
    match = next((h for h in holdings if h["tradingsymbol"] == symbol), None)
    if match is None:
        raise SystemExit(
            f"Symbol '{symbol}' not in mock data.\n"
            f"Available symbols: {', '.join(available)}"
        )
    return match


def _print_breach_details(symbol: str, entry: float, threshold: float,
                           sl_price: float, breach_price: float) -> None:
    breach_pct = ((breach_price - entry) / entry) * 100
    print(f"\n{_DIVIDER}")
    print(f"  SIMULATING SL BREACH FOR {symbol}")
    print(_DIVIDER)
    print(f"  Entry price   : ₹{entry:>10,.2f}")
    print(f"  SL threshold  : {threshold:>+10.1f}%")
    print(f"  SL price      : ₹{sl_price:>10,.2f}")
    print(f"  Simulated CMP : ₹{breach_price:>10,.2f}  (3% below SL)")
    print(f"  Simulated P&L : {breach_pct:>+10.1f}%")
    print(f"{_DIVIDER}\n")


async def simulate_breach(symbol: str) -> None:
    """
    Override the mock price for *symbol* to simulate an SL breach, then run
    the full monitor so a real Telegram alert is sent.
    """
    redis = RedisClient(REDIS_URL)

    # Clear any existing cooldown so the alert fires regardless of prior runs
    cooldown_key = f"sl:alerted:{symbol}"
    if redis.available:
        redis.delete(cooldown_key)
        logger.info("Cleared cooldown key: %s", cooldown_key)
    else:
        logger.warning("Redis unavailable — cooldown key not cleared; alert may be suppressed")

    # Get baseline holding data before patching
    holding = _find_holding(symbol)
    entry: float = holding["average_price"]
    quantity: int = holding["quantity"]
    threshold: float = get_sl_threshold(symbol)
    sl_price: float = entry * (1 + threshold / 100)
    breach_price: float = round(sl_price * 0.97, 2)  # 3% below SL = confirmed breach

    _print_breach_details(symbol, entry, threshold, sl_price, breach_price)

    # Monkey-patch MockKiteClient.get_holdings at the class level so every
    # KiteClient() instance created by the monitor returns the breach price.
    original_get_holdings = MockKiteClient.get_holdings

    def patched_holdings(self) -> list[dict]:
        result = original_get_holdings(self)
        for h in result:
            if h["tradingsymbol"] == symbol:
                pnl = round((breach_price - entry) * h["quantity"], 2)
                pnl_pct = round(((breach_price - entry) / entry) * 100, 2)
                h["last_price"] = breach_price
                h["pnl"] = pnl
                h["pnl_pct"] = pnl_pct
        return result

    MockKiteClient.get_holdings = patched_holdings  # type: ignore[method-assign]

    try:
        print("Running SL monitor with breached price...")
        results = await run_sl_monitor()
        print(f"\nMonitor results: {results}")
    finally:
        MockKiteClient.get_holdings = original_get_holdings  # type: ignore[method-assign]

    print(f"\n{_DIVIDER}")
    if results.get("alerted", 0) > 0:
        print(f"  ✓ Alert SENT — check Telegram for:")
        print(f"    🚨 URGENT — STOP LOSS BREACH  ({symbol})")
        print(f"    Two buttons: [🚨 EXECUTE EXIT]  [⏸ HOLD / OVERRIDE]")
        print(f"\n  Expected flow after tapping EXECUTE EXIT:")
        print(f"    1. Webhook POST /telegram/webhook receives callback_query")
        print(f"    2. Token validated, mark_approved() called")
        print(f"    3. ✅ 'Order Approved' confirmation sent to Telegram")
    elif results.get("cooldown", 0) > 0:
        print(f"  ⚠ Alert suppressed — {symbol} is on cooldown.")
        print(f"  Clear it manually:  redis-cli DEL {cooldown_key}")
    else:
        print(f"  ⚠ No alert sent — check if breach threshold was met.")
    print(f"{_DIVIDER}\n")


if __name__ == "__main__":
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "ICICIBANK"
    asyncio.run(simulate_breach(symbol))
