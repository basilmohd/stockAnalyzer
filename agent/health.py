"""Weekly portfolio health scoring — 4-dimension 0-100 score with grade and commentary."""

import json
from datetime import datetime

import config
from core.db import get_db
from core.telegram_bot import send_message
from data.news import compute_sentiment_score, fetch_news_for_symbol
from data.portfolio import get_holdings_with_sl_status
from models.portfolio_snap import PortfolioSnapshot

from core.logger import get_logger
logger = get_logger(__name__)

_SECTOR_MAP: dict[str, str] = {
    "ICICIBANK":   "Financials",
    "INFY":        "IT",
    "HDFCBANK":    "Financials",
    "BHARTIARTL":  "Telecom",
    "APOLLOHOSP":  "Healthcare",
    "TATAMOTORS":  "Auto",
    "SUNPHARMA":   "Pharma",
    "PFC":         "Financials",
}


def _get_sector(symbol: str, holding: dict) -> str:
    """Resolve sector for a holding.

    Priority: holding dict field → live cached universe → hardcoded map → "Other".
    """
    from data.screener import get_cached_sector
    return holding.get("sector") or get_cached_sector(symbol) or _SECTOR_MAP.get(symbol, "Other")


def _get_grade(score: int) -> str:
    """Map a 0-100 score to a letter grade."""
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _score_diversification(holdings: list[dict]) -> dict:
    """Compute the diversification dimension score (0-25).

    Measures sector concentration; penalises any single stock > 20% of portfolio.
    """
    total = len(holdings)
    if total == 0:
        return {"score": 0, "comment": "No holdings"}

    sector_counts: dict[str, int] = {}
    for h in holdings:
        sector = _get_sector(h["tradingsymbol"], h)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    top_sector = max(sector_counts, key=sector_counts.__getitem__)
    top_count = sector_counts[top_sector]
    concentration = top_count / total

    if concentration < 0.30:
        base = 25
    elif concentration < 0.50:
        base = 15
    else:
        base = 5

    overweight = any((h.get("weight_pct") or 0) > config.MAX_POSITION_PCT for h in holdings)
    penalty = 5 if overweight else 0
    score = max(0, base - penalty)

    top_pct = round(concentration * 100)
    comment = (
        f"{top_sector} overweight at {top_pct}% of holdings"
        if concentration >= 0.30
        else f"Well diversified — top sector {top_sector} at {top_pct}%"
    )
    if overweight:
        comment += " | Single-stock concentration penalty applied"

    return {"score": score, "comment": comment}


def _score_momentum(holdings: list[dict], technicals: dict) -> dict:
    """Compute the momentum dimension score (0-25).

    Fraction of holdings above their 200DMA; bonus if >80%.
    """
    total = len(holdings)
    if total == 0:
        return {"score": 0, "comment": "No holdings"}

    above_count = 0
    for h in holdings:
        symbol = h["tradingsymbol"]
        ind = technicals.get(symbol)
        if ind and not isinstance(ind, dict) and ind.above_200sma:
            above_count += 1

    pct_above = above_count / total
    base = round(25 * pct_above)
    bonus = 3 if pct_above > 0.80 else 0
    score = min(25, base + bonus)

    comment = f"{above_count}/{total} holdings above 200DMA"
    if pct_above > 0.80:
        comment += " — strong trend"
    elif pct_above < 0.40:
        comment += " — weak trend"

    return {"score": score, "comment": comment}


def _score_risk(holdings: list[dict]) -> dict:
    """Compute the risk dimension score (0-25).

    Based on average SL distance; penalises any active SL breach.
    """
    total = len(holdings)
    if total == 0:
        return {"score": 0, "comment": "No holdings"}

    sl_distances = [h.get("sl_distance_pct", 0.0) for h in holdings]
    avg_dist = sum(sl_distances) / total
    has_breach = any(h.get("sl_status") == "BREACH" for h in holdings)

    if avg_dist > 12:
        base = 25
    elif avg_dist >= 8:
        base = 18
    elif avg_dist >= 5:
        base = 10
    else:
        base = 5

    penalty = 5 if has_breach else 0
    score = max(0, base - penalty)

    comment = f"Avg SL distance {avg_dist:.1f}%"
    if has_breach:
        comment += " | ⚠️ Active SL breach detected"
    elif avg_dist < 5:
        comment += " — danger zone"

    return {"score": score, "comment": comment}


def _score_quality(holdings: list[dict], technicals: dict, news_all: dict) -> dict:
    """Compute the quality dimension score (0-25).

    Uses RSI zone scoring as a momentum quality proxy; bonus for net bullish news.
    """
    total = len(holdings)
    if total == 0:
        return {"score": 0, "comment": "No holdings"}

    ideal_count = 0
    quality_points = 0
    for h in holdings:
        symbol = h["tradingsymbol"]
        ind = technicals.get(symbol)
        rsi = ind.rsi if (ind and not isinstance(ind, dict)) else 50.0
        if 40 <= rsi <= 65:
            quality_points += 3
            ideal_count += 1
        elif rsi > 75 or rsi < 35:
            quality_points += 1

    max_points = 3 * total
    raw_pct = quality_points / max_points if max_points > 0 else 0
    base = round(25 * raw_pct)

    bullish = sum(1 for v in news_all.values() if v.get("sentiment_label") == "BULLISH")
    bearish = sum(1 for v in news_all.values() if v.get("sentiment_label") == "BEARISH")
    bonus = 3 if bullish > bearish else 0
    score = min(25, base + bonus)

    comment = f"{ideal_count}/{total} holdings in ideal RSI zone (40-65)"
    if bonus:
        comment += " | Net bullish news sentiment"

    return {"score": score, "comment": comment}


def _top_concern(div: dict, mom: dict, risk: dict, qual: dict) -> str:
    """Return a plain-English recommendation targeting the lowest-scoring dimension."""
    dims = [
        (div["score"],  "diversification", "Reduce sector concentration for better diversification"),
        (mom["score"],  "momentum",        "Portfolio momentum weak — review holdings below 200DMA"),
        (risk["score"], "risk",            "SL distances are tight — review position sizing"),
        (qual["score"], "quality",         "RSI quality below ideal — consider trimming overbought positions"),
    ]
    dims.sort(key=lambda x: x[0])
    return dims[0][2]


def compute_health_score() -> dict:
    """Compute the weekly 4-dimension portfolio health score (0-100).

    Returns a structured dict with per-dimension scores, comments, grade, and top concern.
    """
    from data.technicals import get_technicals_for_holdings
    holdings = get_holdings_with_sl_status()
    technicals = get_technicals_for_holdings()

    news_all: dict = {}
    for h in holdings:
        symbol = h["tradingsymbol"]
        articles = fetch_news_for_symbol(symbol)
        news_all[symbol] = compute_sentiment_score(articles)

    div = _score_diversification(holdings)
    mom = _score_momentum(holdings, technicals)
    risk = _score_risk(holdings)
    qual = _score_quality(holdings, technicals, news_all)

    total = div["score"] + mom["score"] + risk["score"] + qual["score"]

    return {
        "total_score":     total,
        "grade":           _get_grade(total),
        "diversification": div,
        "momentum":        mom,
        "risk":            risk,
        "quality":         qual,
        "top_concern":     _top_concern(div, mom, risk, qual),
        "computed_at":     datetime.now().isoformat(),
    }


def format_health_telegram(health: dict) -> str:
    """Format a health score dict as an HTML Telegram weekly health report."""
    total = health.get("total_score", 0)
    grade = health.get("grade", "?")
    div = health.get("diversification", {})
    mom = health.get("momentum", {})
    risk = health.get("risk", {})
    qual = health.get("quality", {})
    concern = health.get("top_concern", "")

    return (
        f"🏥 <b>Weekly Portfolio Health Report</b>\n"
        f"\n"
        f"Overall Score: <b>{total}/100</b> — Grade: <b>{grade}</b>\n"
        f"\n"
        f"📊 Diversification: {div.get('score', 0)}/25\n"
        f"{div.get('comment', '')}\n"
        f"\n"
        f"📈 Momentum: {mom.get('score', 0)}/25\n"
        f"{mom.get('comment', '')}\n"
        f"\n"
        f"🛡 Risk: {risk.get('score', 0)}/25\n"
        f"{risk.get('comment', '')}\n"
        f"\n"
        f"⭐ Quality: {qual.get('score', 0)}/25\n"
        f"{qual.get('comment', '')}\n"
        f"\n"
        f"⚠️ Top Concern: {concern}"
    )


async def send_weekly_health_report() -> None:
    """Compute health score, send to Telegram, and persist snapshot to SQLite."""
    health = compute_health_score()
    text = format_health_telegram(health)
    await send_message(text, parse_mode="HTML")

    holdings = get_holdings_with_sl_status()
    total_value = sum(h["value"] for h in holdings)
    overall_pnl = sum(h["pnl"] for h in holdings)

    with get_db() as db:
        snap = PortfolioSnapshot(
            snap_date=datetime.now().date(),
            holdings_json=json.dumps([h["tradingsymbol"] for h in holdings]),
            total_value=round(total_value, 2),
            day_pnl=0.0,
            overall_pnl=round(overall_pnl, 2),
            health_score_json=json.dumps(health),
        )
        db.add(snap)
        db.commit()
        logger.info("Health snapshot stored: score=%d grade=%s", health["total_score"], health["grade"])
