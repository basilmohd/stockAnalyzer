"""OpenAI GPT-4 client for portfolio briefing analysis."""
import json
import logging

import config
from core.claude_client import _build_prompt, _parse_briefing_response
from core.logger import get_logger

logger = get_logger(__name__)


def call_openai_briefing(
    portfolio_context: dict,
    technicals: dict,
    news: dict,
) -> dict:
    """Call OpenAI GPT-4 to generate a structured morning briefing.

    Returns dict with keys: headline, alerts, watchlist, action_items.
    """
    try:
        import openai
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    system_prompt = (
        "You are a portfolio advisor analyzing an Indian stock portfolio. "
        "Respond ONLY with a valid JSON object containing exactly these keys: "
        "headline (string), alerts (list of strings), "
        "watchlist (list of strings), action_items (list of strings). "
        "Be concise and actionable. Use Indian market context (NSE, INR)."
    )

    user_prompt = _build_prompt(portfolio_context, technicals, news)

    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4-turbo",
        temperature=0.7,
        max_tokens=1000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )

    raw_text = response.choices[0].message.content
    return _parse_briefing_response(raw_text)


def generate_global_market_research_report(research_context: dict) -> str:
    """Call OpenAI GPT-4 to generate a comprehensive global market research report.

    Args:
        research_context: dict with keys: indices, portfolio, timestamp
            - indices: {index_name: {articles, sentiment_label, article_count, ...}, ...}
            - portfolio: {context, technicals, news}
            - timestamp: ISO format timestamp

    Returns: markdown formatted report string (plain text, not JSON)
    """
    try:
        import openai
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    # Build user prompt from research context
    indices_summary = _build_indices_summary(research_context.get("indices", {}))
    portfolio_summary = _build_portfolio_summary(research_context.get("portfolio", {}))

    user_prompt = f"""
# Global Market Research Report — Week Ahead Analysis

## International Market Context
{indices_summary}

## Portfolio Overview
{portfolio_summary}

Timestamp: {research_context.get('timestamp', 'N/A')}

Please provide a comprehensive analysis with the following sections:

1. **Market Outlook** — What is the likely trend for global equities this week? Consider US, European, and Indian market signals.

2. **Sector Analysis** — Which sectors are rallying/declining globally? Identify key themes and trends.

3. **Portfolio Stock Impact** — For each stock in the portfolio, analyze how global market trends affect it. Be specific about implications.

4. **Rebalancing Checklist** — Provide specific actionable recommendations:
   - Which stocks to BUY (and suggested allocation %)
   - Which stocks to HOLD (explain why)
   - Which stocks to REDUCE (and suggested % to exit)
   - Any SELL recommendations

Be concise but thorough. Include confidence levels for recommendations. Use markdown formatting.
"""

    system_prompt = (
        "You are a professional global markets researcher with deep expertise in international equities, "
        "cross-market correlations, and geopolitical analysis. Analyze the provided international market data "
        "and Indian portfolio context to generate actionable investment recommendations. "
        "Your analysis should account for currency risks, sector rotations, and macroeconomic trends. "
        "Format your response in clear markdown with sections, bullet points, and emphasis where needed."
    )

    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4-turbo",
        temperature=0.7,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return response.choices[0].message.content


def _build_indices_summary(indices: dict) -> str:
    """Build a text summary of global indices data."""
    if not indices:
        return "No indices data available."

    lines = []
    for index_name, data in indices.items():
        sentiment = data.get("sentiment_label", "NEUTRAL")
        article_count = data.get("article_count", 0)
        articles = data.get("articles", [])[:2]  # Top 2 headlines

        lines.append(f"\n### {index_name} — {sentiment}")
        lines.append(f"*{article_count} articles found, trending topics:*")
        for art in articles:
            title = art.get("title", "")
            if title:
                lines.append(f"- {title}")

    return "\n".join(lines)


def _build_portfolio_summary(portfolio_data: dict) -> str:
    """Build a text summary of portfolio data."""
    if not portfolio_data:
        return "No portfolio data available."

    context = portfolio_data.get("context", {})
    technicals = portfolio_data.get("technicals", {})
    news = portfolio_data.get("news", {})

    lines = []

    # Portfolio summary
    portfolio_info = context.get("portfolio", {})
    if portfolio_info:
        total_value = portfolio_info.get("total_value", 0)
        total_pnl_pct = portfolio_info.get("total_pnl_pct", 0)
        holdings_count = portfolio_info.get("holdings_count", 0)
        lines.append(f"**Portfolio Value:** ₹{total_value:,.0f} | **P&L:** {total_pnl_pct:+.1f}% | **Holdings:** {holdings_count}")

    # Top holdings with sentiment
    holdings = context.get("holdings", [])[:5]
    if holdings:
        lines.append("\n**Key Holdings:**")
        for holding in holdings:
            symbol = holding.get("tradingsymbol", "")
            qty = holding.get("quantity", 0)
            pnl_pct = holding.get("pnl_pct", 0)
            if symbol:
                sentiment = "NEUTRAL"
                if symbol in news:
                    sentiment = news[symbol].get("sentiment_label", "NEUTRAL")
                lines.append(f"- **{symbol}**: {qty} shares | P&L {pnl_pct:+.1f}% | Sentiment: {sentiment}")

    # Risk flags
    risk_flags = context.get("risk_flags", [])
    if risk_flags:
        lines.append(f"\n**Risk Flags:** {', '.join(risk_flags)}")

    return "\n".join(lines)
