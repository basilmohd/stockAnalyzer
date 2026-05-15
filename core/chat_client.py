"""Chat client for portfolio-aware LLM conversations via Telegram."""
import config
from core.logger import get_logger

logger = get_logger(__name__)


def call_chat(
    portfolio_context: dict,
    technicals: dict,
    news: dict,
    conversation_history: list[dict],
    user_query: str,
) -> str:
    """Call LLM (Claude or OpenAI) to respond to a user query with portfolio context.

    Args:
        portfolio_context: Portfolio data dict (from data.portfolio.build_claude_context())
        technicals: Technicals dict (symbol -> IndicatorResult)
        news: News sentiment dict (symbol -> sentiment_data)
        conversation_history: List of dicts with 'role' and 'content' keys
        user_query: The user's question

    Returns:
        Raw LLM response string (conversational, not JSON-parsed)
    """
    if config.USE_MOCK_AI:
        return _mock_chat_response(user_query)

    if config.AI_PROVIDER == "openai":
        return call_openai_chat(
            portfolio_context, technicals, news, conversation_history, user_query
        )
    else:
        return call_claude_chat(
            portfolio_context, technicals, news, conversation_history, user_query
        )


def call_claude_chat(
    portfolio_context: dict,
    technicals: dict,
    news: dict,
    conversation_history: list[dict],
    user_query: str,
) -> str:
    """Call Claude to respond to a user query with portfolio context.

    Args:
        portfolio_context: Portfolio data dict
        technicals: Technicals dict
        news: News sentiment dict
        conversation_history: List of {'role': 'user'|'assistant', 'content': str}
        user_query: The user's current question

    Returns:
        Raw Claude response string
    """
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError("anthropic package required: pip install anthropic") from exc

    system_prompt = (
        "You are a knowledgeable portfolio advisor for an Indian stock investor. "
        "Analyze the user's question in the context of their current portfolio, holdings, technicals, and news. "
        "Be concise, actionable, and use Indian market terminology (NSE, INR, sectors like Banking, IT). "
        "Reference specific holdings and risk factors when relevant. "
        "If the user asks about something outside your portfolio, acknowledge it but focus on portfolio-related insights."
    )

    # Build context prompt with portfolio data
    context_prompt = _build_chat_context_prompt(
        portfolio_context, technicals, news
    )

    # Build messages list with conversation history + new query
    messages = []

    # Add context as first user message if history is empty
    if not conversation_history:
        messages.append(
            {"role": "user", "content": context_prompt + "\n\nUser query: " + user_query}
        )
    else:
        # Add context as preamble to first message if we have history
        messages.append(
            {"role": "user", "content": "Portfolio context:\n" + context_prompt}
        )
        # Add conversation history
        messages.extend(conversation_history)
        # Add current query
        messages.append({"role": "user", "content": user_query})

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1000,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
    except Exception as exc:
        logger.error("call_claude_chat failed: %s", exc)
        raise


def call_openai_chat(
    portfolio_context: dict,
    technicals: dict,
    news: dict,
    conversation_history: list[dict],
    user_query: str,
) -> str:
    """Call OpenAI GPT-4 to respond to a user query with portfolio context.

    Args:
        portfolio_context: Portfolio data dict
        technicals: Technicals dict
        news: News sentiment dict
        conversation_history: List of {'role': 'user'|'assistant', 'content': str}
        user_query: The user's current question

    Returns:
        Raw OpenAI response string
    """
    try:
        import openai
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    system_prompt = (
        "You are a knowledgeable portfolio advisor for an Indian stock investor. "
        "Analyze the user's question in the context of their current portfolio, holdings, technicals, and news. "
        "Be concise, actionable, and use Indian market terminology (NSE, INR, sectors like Banking, IT). "
        "Reference specific holdings and risk factors when relevant. "
        "If the user asks about something outside your portfolio, acknowledge it but focus on portfolio-related insights."
    )

    # Build context prompt with portfolio data
    context_prompt = _build_chat_context_prompt(
        portfolio_context, technicals, news
    )

    # Build messages list with conversation history + new query
    messages = [{"role": "system", "content": system_prompt}]

    # Add context as first user message if history is empty
    if not conversation_history:
        messages.append(
            {"role": "user", "content": context_prompt + "\n\nUser query: " + user_query}
        )
    else:
        # Add context as preamble
        messages.append(
            {"role": "user", "content": "Portfolio context:\n" + context_prompt}
        )
        # Add conversation history
        messages.extend(conversation_history)
        # Add current query
        messages.append({"role": "user", "content": user_query})

    try:
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            temperature=0.7,
            max_tokens=1000,
            messages=messages,
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.error("call_openai_chat failed: %s", exc)
        raise


def _build_chat_context_prompt(
    portfolio_context: dict,
    technicals: dict,
    news: dict,
) -> str:
    """Build a concise portfolio context string for chat prompts."""
    portfolio = portfolio_context.get("portfolio", {})
    holdings = portfolio_context.get("holdings", [])
    risk_flags = portfolio_context.get("risk_flags", [])

    total_value = portfolio.get("total_value", 0)
    total_pnl = portfolio.get("total_pnl", 0)
    total_pnl_pct = portfolio.get("total_pnl_pct", 0)
    count = portfolio.get("holdings_count", len(holdings))

    lines = [
        f"Portfolio Summary: ₹{total_value:,.0f} total value, {count} holdings, P&L: ₹{total_pnl:,.0f} ({total_pnl_pct:+.1f}%)"
    ]

    if risk_flags:
        lines.append("\nActive Risk Flags:")
        for flag in risk_flags[:5]:  # Limit to top 5 flags
            lines.append(f"  • {flag}")

    lines.append("\nHoldings Summary:")
    for h in holdings:
        symbol = h.get("symbol", "?")
        qty = h.get("qty", 0)
        cmp = h.get("cmp", 0)
        pnl_pct = h.get("pnl_pct", 0)
        weight_pct = h.get("weight_pct", 0)
        sl_status = h.get("sl_status", "OK")

        ind = technicals.get(symbol)
        tech_str = ""
        if ind and not isinstance(ind, dict):
            rsi = ind.rsi if hasattr(ind, 'rsi') else 50
            above_dma = "✓200DMA" if (hasattr(ind, 'above_200sma') and ind.above_200sma) else "✗200DMA"
            tech_str = f" | RSI:{rsi:.0f} {above_dma}"

        news_data = news.get(symbol, {})
        sentiment_label = news_data.get("sentiment_label", "—")
        news_str = f" | News:{sentiment_label}"

        lines.append(
            f"  {symbol} ({qty}@₹{cmp:.0f}): {pnl_pct:+.1f}% | {weight_pct:.1f}% | SL:{sl_status}"
            f"{tech_str}{news_str}"
        )

    return "\n".join(lines)


def _mock_chat_response(user_query: str) -> str:
    """Return a mock chat response for testing (USE_MOCK_AI=true)."""
    responses = {
        "risk": "Based on your portfolio, you have 2 positions showing SL warnings: RELIANCE is -2% from SL, INFY is at 18% weight (exceeds 20% max). I'd recommend monitoring RELIANCE closely over the next 2 trading days.",
        "top": "Your top 3 holdings by weight are: INFY (21.3%), RELIANCE (15.2%), and ICICIBANK (12.8%). INFY is slightly overbought (RSI 76), so consider trimming on rallies.",
        "buy": "Looking at technicals, ICICIBANK (RSI 32) and SBIN (RSI 28) are oversold with bullish news. Both could be accumulation candidates. However, check liquidity and sizing before adding.",
        "default": f"Based on your current portfolio context, I'm analyzing your query: '{user_query[:50]}...'. Your portfolio shows moderate risk with mixed technicals. For specific actionable trades, I'd recommend waiting for clearer technical setups.",
    }

    # Simple keyword matching
    query_lower = user_query.lower()
    if any(word in query_lower for word in ["risk", "safe", "worried", "breach"]):
        return responses["risk"]
    if any(word in query_lower for word in ["top", "largest", "biggest", "weight"]):
        return responses["top"]
    if any(word in query_lower for word in ["buy", "accumulate", "oversold", "dip"]):
        return responses["buy"]
    return responses["default"]
