"""OpenAI GPT-4 client for portfolio briefing analysis."""
import json
import logging

import config
from core.claude_client import _build_prompt, _parse_briefing_response

logger = logging.getLogger(__name__)


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
