"""
Portfolio context builder — fetches holdings, computes SL status,
and produces structured data for Claude prompts.
"""
from datetime import datetime
from typing import Optional

from config import DEFAULT_SL_PCT, MAX_HOLDING_WEIGHT_PCT, SL_OVERRIDES
from core.kite_client import KiteClient
from core.logger import get_logger

logger = get_logger(__name__)

_SECTOR_MAP: dict[str, str] = {
    "IRCTC":      "Travel",
    "POLYCAB":    "Industrials",
    "RELIANCE":   "Oil & Gas",
    "OLECTRA":    "EV & Auto",
    "MARUTI":     "Auto",
    "KOTAKGOLD":  "Gold ETF",
    "VARUNBEV":   "FMCG",
    "TATAMTRDVR": "Auto",
    "MOTHERSON":  "Auto Ancillary",
    "EXIDEIND":   "Auto Ancillary",
    "SGBSEP31":   "Sovereign Bond",
}


def _sl_pct(symbol: str) -> float:
    """Return the stop-loss percentage for a symbol (override or default)."""
    return SL_OVERRIDES.get(symbol, DEFAULT_SL_PCT)


def _filter_valid_holdings(holdings: list[dict]) -> list[dict]:
    """
    Filter out holdings with zero quantity, zero average price, or zero current price.
    
    Args:
        holdings: List of holding dicts from KiteClient.get_holdings()
    
    Returns:
        Filtered list containing only holdings with:
        - quantity > 0 (shares exist)
        - average_price > 0 (valid entry price)
        - last_price > 0 (valid current price)
    """
    valid = [
        h for h in holdings
        if h.get("quantity", 0) > 0
        and h.get("average_price", 0) > 0
        and h.get("last_price", 0) > 0
    ]
    if len(valid) < len(holdings):
        filtered_out = len(holdings) - len(valid)
        logger.warning(
            f"Filtered out {filtered_out} holding(s): zero quantity, "
            f"zero average_price, or zero last_price (migrated stocks)"
        )
    return valid


def get_holdings_with_sl_status() -> list[dict]:
    """
    Fetch holdings from KiteClient and enrich each with SL fields and portfolio weight.

    Returns list sorted by holding value descending. Excludes holdings with 0 shares.
    """
    raw: list[dict] = KiteClient().get_holdings()
    raw = _filter_valid_holdings(raw)

    enriched: list[dict] = []
    for h in raw:
        avg: float = h["average_price"]
        lp: float  = h["last_price"]
        qty: int   = h["quantity"]
        symbol: str = h["tradingsymbol"]

        # Final defensive check: skip if avg or lp is zero/invalid
        if avg <= 0 or lp <= 0:
            logger.debug(f"Skipping {symbol}: avg={avg}, lp={lp}")
            continue

        sl_pct_val = _sl_pct(symbol)
        sl_price = round(avg * (1 + sl_pct_val / 100), 2)
        
        # Ensure sl_price is valid and non-zero to prevent division by zero
        if sl_price <= 0:
            logger.warning(
                f"Invalid SL price for {symbol}: avg={avg}, sl_pct={sl_pct_val}, "
                f"sl_price={sl_price}. Skipping."
            )
            continue
        
        sl_distance_pct = round(((lp - sl_price) / sl_price) * 100, 2)

        if sl_distance_pct < 0:
            sl_status = "BREACH"
        elif sl_distance_pct <= 5:
            sl_status = "WARNING"
        else:
            sl_status = "SAFE"

        value = round(lp * qty, 2)

        enriched.append({
            **h,
            "sl_price":         sl_price,
            "sl_distance_pct":  sl_distance_pct,
            "sl_status":        sl_status,
            "value":            value,
            "weight_pct":       None,
        })

    total_value: float = sum(e["value"] for e in enriched)
    for e in enriched:
        e["weight_pct"] = round((e["value"] / total_value) * 100, 2) if total_value else 0.0

    return sorted(enriched, key=lambda x: x["value"], reverse=True)


def get_portfolio_summary() -> dict:
    """
    Return high-level portfolio metrics including P&L, SL counts, and sector weights.
    """
    holdings = get_holdings_with_sl_status()

    total_value   = round(sum(h["value"] for h in holdings), 2)
    total_pnl     = round(sum(h["pnl"] for h in holdings), 2)
    invested      = sum(h["average_price"] * h["quantity"] for h in holdings)
    total_pnl_pct = round((total_pnl / invested) * 100, 2) if invested else 0.0

    breach_count  = sum(1 for h in holdings if h["sl_status"] == "BREACH")
    warning_count = sum(1 for h in holdings if h["sl_status"] == "WARNING")

    # Handle edge case: no valid holdings after filtering
    if holdings:
        top_gainer: dict = max(holdings, key=lambda h: h["pnl_pct"])
        top_loser:  dict = min(holdings, key=lambda h: h["pnl_pct"])
    else:
        top_gainer = {}
        top_loser = {}

    sector_weights: dict[str, float] = {}
    for h in holdings:
        sector = _SECTOR_MAP.get(h["tradingsymbol"], "Other")
        sector_weights[sector] = round(
            sector_weights.get(sector, 0.0) + (h["weight_pct"] or 0.0), 2
        )

    return {
        "total_value":    total_value,
        "total_pnl":      total_pnl,
        "total_pnl_pct":  total_pnl_pct,
        "holdings_count": len(holdings),
        "breach_count":   breach_count,
        "warning_count":  warning_count,
        "top_gainer":     top_gainer,
        "top_loser":      top_loser,
        "sector_weights": sector_weights,
        "generated_at":   datetime.now().isoformat(),
    }


def build_claude_context() -> dict:
    """
    Build a clean, structured dict ready for use as Claude prompt context.

    Includes portfolio summary, per-holding detail, and natural-language risk flags.
    """
    summary  = get_portfolio_summary()
    holdings = get_holdings_with_sl_status()

    structured_holdings = []
    for h in holdings:
        symbol = h["tradingsymbol"]
        structured_holdings.append({
            "symbol":           symbol,
            "exchange":         h["exchange"],
            "qty":              h["quantity"],
            "avg_price":        h["average_price"],
            "cmp":              h["last_price"],
            "pnl_pct":          h["pnl_pct"],
            "value":            h["value"],
            "weight_pct":       h["weight_pct"],
            "sl_price":         h["sl_price"],
            "sl_distance_pct":  h["sl_distance_pct"],
            "sl_status":        h["sl_status"],
            "sector":           _SECTOR_MAP.get(symbol, "Other"),
        })

    risk_flags: list[str] = []

    for h in structured_holdings:
        sym   = h["symbol"]
        dist  = h["sl_distance_pct"]
        wt    = h["weight_pct"]
        pnl   = h["pnl_pct"]
        status = h["sl_status"]

        if status == "BREACH":
            risk_flags.append(
                f"{sym} is {pnl:+.1f}% from entry, stop-loss breached "
                f"(SL: ₹{h['sl_price']:,.2f}, CMP: ₹{h['cmp']:,.2f})"
            )
        elif status == "WARNING":
            risk_flags.append(
                f"{sym} is {dist:.1f}% above stop-loss — approaching trigger"
            )

        if wt is not None and wt > MAX_HOLDING_WEIGHT_PCT:
            risk_flags.append(
                f"{sym} exceeds {MAX_HOLDING_WEIGHT_PCT:.0f}% portfolio weight at {wt:.1f}%"
            )

    return {
        "portfolio":    summary,
        "holdings":     structured_holdings,
        "risk_flags":   risk_flags,
        "generated_at": datetime.now().isoformat(),
    }
