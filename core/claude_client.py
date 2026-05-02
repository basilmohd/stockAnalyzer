"""Claude AI client for portfolio briefing analysis."""
import json
import logging

import config

logger = logging.getLogger(__name__)


def call_claude_briefing(
    portfolio_context: dict,
    technicals: dict,
    news: dict,
) -> dict:
    """Call Claude to generate a structured morning briefing for the portfolio.

    Returns dict with keys: headline, alerts, watchlist, action_items.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError("anthropic package required: pip install anthropic") from exc

    system_prompt = (
        "You are a portfolio advisor analyzing an Indian stock portfolio. "
        "Respond ONLY with a valid JSON object containing exactly these keys: "
        "headline (string), alerts (list of strings), "
        "watchlist (list of strings), action_items (list of strings). "
        "Be concise and actionable. Use Indian market context (NSE, INR)."
    )

    user_prompt = _build_prompt(portfolio_context, technicals, news)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = response.content[0].text
    return _parse_briefing_response(raw_text)


def _build_prompt(portfolio_context: dict, technicals: dict, news: dict) -> str:
    """Build the user prompt from portfolio, technicals, and news data."""
    portfolio = portfolio_context.get("portfolio", {})
    holdings = portfolio_context.get("holdings", [])
    risk_flags = portfolio_context.get("risk_flags", [])

    total_value = portfolio.get("total_value", 0)
    total_pnl_pct = portfolio.get("total_pnl_pct", 0)
    count = portfolio.get("holdings_count", len(holdings))

    lines = [
        f"Portfolio Summary: ₹{total_value:,.0f} total value, "
        f"{total_pnl_pct:+.1f}% overall P&L, {count} holdings.",
    ]

    if risk_flags:
        lines.append("\nRisk Flags:")
        for flag in risk_flags:
            lines.append(f"  - {flag}")

    lines.append("\nHoldings Detail:")
    for h in holdings:
        symbol = h.get("symbol", "?")
        pnl_pct = h.get("pnl_pct", 0.0)
        sl_status = h.get("sl_status", "OK")
        sector = h.get("sector", "Other")

        ind = technicals.get(symbol)
        tech_str = ""
        if ind and not isinstance(ind, dict):
            above_dma = "above" if ind.above_200sma else "below"
            macd_cross = "bullish" if ind.macd > ind.macd_signal else "bearish"
            tech_str = (
                f" | RSI={ind.rsi:.0f} MACD={macd_cross} "
                f"200DMA={above_dma} Vol={ind.volume_ratio:.1f}x"
            )

        news_data = news.get(symbol, {})
        sentiment_label = news_data.get("sentiment_label", "NEUTRAL")
        news_str = f" | News={sentiment_label}"

        lines.append(
            f"  {symbol} ({sector}): {pnl_pct:+.1f}% SL={sl_status}"
            f"{tech_str}{news_str}"
        )

    lines.append(
        "\nGenerate a concise morning briefing with key alerts, "
        "stocks to watch, and top 3 action items."
    )

    return "\n".join(lines)


def _parse_briefing_response(raw_text: str) -> dict:
    """Parse and validate the JSON response from Claude or OpenAI."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()

    parsed = json.loads(text)

    return {
        "headline":     str(parsed.get("headline", "Morning briefing generated.")),
        "alerts":       list(parsed.get("alerts", [])),
        "watchlist":    list(parsed.get("watchlist", [])),
        "action_items": list(parsed.get("action_items", [])),
    }
