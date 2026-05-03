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


def generate_signals(holdings: list[dict]) -> list[dict]:
    """Call Claude to generate BUY/SELL/HOLD/REDUCE/EXIT signals from merged holdings data.

    Returns list of signal dicts. Always returns empty list on failure, never raises.
    """
    if config.USE_MOCK_AI:
        return _mock_signals()

    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package required: pip install anthropic")
        return []

    system_prompt = (
        "You are a quantitative analyst for an Indian retail investor. "
        "You generate precise BUY/SELL/HOLD/REDUCE/EXIT signals for NSE stocks. "
        "Base decisions strictly on technical indicators and news sentiment provided. "
        "Respond ONLY in valid JSON array. No preamble, no markdown, nothing outside JSON."
    )

    user_prompt = _build_signals_prompt(holdings)

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw_text = response.content[0].text
        return _parse_signals_response(raw_text)
    except Exception as exc:
        logger.error("generate_signals failed: %s", exc)
        return []


def _build_signals_prompt(holdings: list[dict]) -> str:
    """Build the user prompt for signal generation from merged holdings data."""
    holdings_json = json.dumps(holdings, indent=2, default=str)
    return (
        "Generate trading signals for these holdings based on technical + sentiment data.\n\n"
        "Holdings with Technicals + News:\n"
        f"{holdings_json}\n\n"
        "Rules you must follow:\n"
        "- Only flag a stock if there is a clear technical reason\n"
        "- RSI > 75: consider REDUCE or SELL\n"
        "- RSI < 35: consider BUY or ACCUMULATE\n"
        "- MACD histogram turning positive: BULLISH signal\n"
        "- MACD histogram turning negative: BEARISH signal\n"
        "- Price > SMA200 and RSI 45-65: HOLD\n"
        "- News sentiment BEARISH + RSI > 65: strong SELL candidate\n"
        "- News sentiment BULLISH + RSI < 45: strong BUY candidate\n"
        "- Never generate a signal without a clear reason\n\n"
        "Return a JSON array (can be empty if no clear signals):\n"
        "[\n"
        "  {\n"
        '    "symbol": "ICICIBANK",\n'
        '    "action": "BUY" | "SELL" | "HOLD" | "REDUCE" | "EXIT",\n'
        '    "confidence": 0.0-1.0,\n'
        '    "reason": "concise reason string",\n'
        '    "rsi": 58.3,\n'
        '    "macd_histogram": 2.1,\n'
        '    "news_sentiment": "BULLISH",\n'
        '    "suggested_quantity": 10,\n'
        '    "urgency": "HIGH" | "MEDIUM" | "LOW"\n'
        "  }\n"
        "]"
    )


def _parse_signals_response(raw_text: str) -> list[dict]:
    """Parse Claude's JSON array response for signals. Returns empty list on parse error."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse signals JSON: %s", exc)
        return []
    if not isinstance(parsed, list):
        logger.error("Expected JSON array from Claude, got: %s", type(parsed).__name__)
        return []
    return parsed


def _mock_signals() -> list[dict]:
    """Return realistic mock signals for local dev and testing (USE_MOCK_AI=true)."""
    return [
        {
            "symbol": "ICICIBANK",
            "action": "BUY",
            "confidence": 0.82,
            "reason": "RSI at 32 — oversold. Bullish news sentiment. MACD histogram turning positive.",
            "rsi": 32.4,
            "macd_histogram": 1.8,
            "news_sentiment": "BULLISH",
            "suggested_quantity": 15,
            "urgency": "HIGH",
        },
        {
            "symbol": "INFY",
            "action": "REDUCE",
            "confidence": 0.77,
            "reason": "RSI at 76 — overbought. Near 52-week high. MACD histogram softening.",
            "rsi": 76.1,
            "macd_histogram": -0.5,
            "news_sentiment": "NEUTRAL",
            "suggested_quantity": 10,
            "urgency": "MEDIUM",
        },
        {
            "symbol": "SUNPHARMA",
            "action": "HOLD",
            "confidence": 0.60,
            "reason": "RSI neutral at 52. Price above SMA200. No strong directional catalyst.",
            "rsi": 52.3,
            "macd_histogram": 0.3,
            "news_sentiment": "NEUTRAL",
            "suggested_quantity": 0,
            "urgency": "LOW",
        },
    ]


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
