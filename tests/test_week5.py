"""Week 5 test suite — morning briefing with Claude/OpenAI AI providers.
Unit tests pass without real API credentials.
Integration tests (marked) require ANTHROPIC_API_KEY / OPENAI_API_KEY / Telegram.
"""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module", autouse=True)
def ensure_db():
    """Create data_store dir and DB tables before any test runs."""
    root = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(os.path.join(root, "data_store"), exist_ok=True)
    from core.db import init_db
    init_db()


_MOCK_BRIEFING = {
    "headline": "Markets open with mixed signals — monitor key levels.",
    "alerts": ["PFC near SL threshold at -14.1%", "TATAMOTORS overbought (RSI=74)"],
    "watchlist": ["ICICIBANK", "INFY"],
    "action_items": [
        "Review PFC position — SL approaching",
        "Consider trimming TATAMOTORS on RSI divergence",
        "Maintain cash reserve above 10%",
    ],
}


# ── Config tests ──────────────────────────────────────────────────────────────

def test_ai_provider_flag_claude_or_openai():
    """AI_PROVIDER config must be 'claude' or 'openai'."""
    import config
    assert config.AI_PROVIDER in ("claude", "openai"), (
        f"AI_PROVIDER must be 'claude' or 'openai', got: {config.AI_PROVIDER}"
    )


# ── Claude client tests ───────────────────────────────────────────────────────

def test_call_claude_briefing_returns_dict():
    """call_claude_briefing returns a dict when Claude API responds with valid JSON."""
    from core.claude_client import call_claude_briefing

    mock_text = json.dumps(_MOCK_BRIEFING)
    mock_content = MagicMock()
    mock_content.text = mock_text
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        result = call_claude_briefing({}, {}, {})

    assert isinstance(result, dict)
    for key in ("headline", "alerts", "watchlist", "action_items"):
        assert key in result, f"Missing key: {key}"


def test_briefing_dict_has_required_keys():
    """Briefing result contains all four required keys with correct types."""
    from core.claude_client import _parse_briefing_response

    result = _parse_briefing_response(json.dumps(_MOCK_BRIEFING))
    assert "headline" in result
    assert "alerts" in result
    assert "watchlist" in result
    assert "action_items" in result
    assert isinstance(result["headline"], str)
    assert isinstance(result["alerts"], list)
    assert isinstance(result["watchlist"], list)
    assert isinstance(result["action_items"], list)


def test_parse_briefing_strips_markdown_fences():
    """_parse_briefing_response handles JSON wrapped in ```json ... ``` fences."""
    from core.claude_client import _parse_briefing_response

    fenced = f"```json\n{json.dumps(_MOCK_BRIEFING)}\n```"
    result = _parse_briefing_response(fenced)
    assert result["headline"] == _MOCK_BRIEFING["headline"]
    assert result["alerts"] == _MOCK_BRIEFING["alerts"]


# ── OpenAI client tests ───────────────────────────────────────────────────────

def test_call_openai_briefing_returns_dict():
    """call_openai_briefing returns a dict when OpenAI API responds with valid JSON."""
    from core.openai_client import call_openai_briefing

    mock_message = MagicMock()
    mock_message.content = json.dumps(_MOCK_BRIEFING)
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    fake_openai = MagicMock()
    fake_openai.OpenAI.return_value.chat.completions.create.return_value = mock_response

    with patch.dict("sys.modules", {"openai": fake_openai}):
        result = call_openai_briefing({}, {}, {})

    assert isinstance(result, dict)
    for key in ("headline", "alerts", "watchlist", "action_items"):
        assert key in result, f"Missing key: {key}"


# ── Prompt builder tests ──────────────────────────────────────────────────────

def test_briefing_includes_all_holdings():
    """Prompt builder includes all 8 mock holdings in the user prompt."""
    from core.claude_client import _build_prompt
    from data.portfolio import build_claude_context

    context = build_claude_context()
    null_redis = MagicMock()
    null_redis.get.return_value = None
    null_redis.setex.return_value = True

    with patch("data.technicals._redis", null_redis):
        from data.technicals import get_technicals_for_holdings
        technicals = get_technicals_for_holdings()

    news = {h["symbol"]: {"sentiment_label": "NEUTRAL"} for h in context["holdings"]}
    prompt = _build_prompt(context, technicals, news)

    for holding in context["holdings"]:
        assert holding["symbol"] in prompt, f"{holding['symbol']} missing from prompt"


# ── Scheduler wiring test ─────────────────────────────────────────────────────

def test_briefing_runs_at_right_time():
    """briefing_job is scheduled Mon-Fri at 08:30 IST in scheduler.py."""
    import inspect
    import scheduler as sched

    src = inspect.getsource(sched)
    assert "hour=8" in src, "Briefing job hour=8 not found in scheduler"
    assert "minute=30" in src, "Briefing job minute=30 not found in scheduler"
    assert "mon-fri" in src, "Briefing job mon-fri not found in scheduler"


# ── run_briefing behaviour tests ──────────────────────────────────────────────

def test_fallback_if_ai_fails():
    """run_briefing returns False but still sends a Telegram message when AI raises."""
    from agent.briefing import run_briefing

    with patch("agent.briefing.build_claude_context", return_value=_mock_context()), \
         patch("agent.briefing.generate_briefing", side_effect=Exception("API timeout")), \
         patch("agent.briefing.send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        result = asyncio.run(run_briefing())

    assert result is False, "Expected False when AI fails"
    mock_send.assert_called_once()
    sent_text = mock_send.call_args[0][0]
    assert "MORNING BRIEFING" in sent_text


def test_briefing_format_contains_provider_name():
    """Telegram message footer includes the configured AI_PROVIDER name."""
    import config
    from agent.briefing import run_briefing

    with patch("agent.briefing.build_claude_context", return_value=_mock_context()), \
         patch("agent.briefing.generate_briefing", return_value=_MOCK_BRIEFING), \
         patch("agent.briefing.send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        asyncio.run(run_briefing())

    sent_text = mock_send.call_args[0][0]
    assert config.AI_PROVIDER in sent_text, (
        f"Provider '{config.AI_PROVIDER}' not found in briefing message"
    )


# ── Integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
def test_run_briefing_sends_telegram():
    """run_briefing with mocked AI returns True and sends a real Telegram message."""
    from agent.briefing import run_briefing

    with patch("agent.briefing.generate_briefing", return_value=_MOCK_BRIEFING):
        result = asyncio.run(run_briefing())

    assert result is True, f"Expected True from run_briefing, got: {result}"


def _real_key(env_var: str) -> bool:
    """Return True only if env_var is set to a non-placeholder value."""
    val = os.getenv(env_var, "")
    return bool(val) and not val.endswith("...") and len(val) > 20


@pytest.mark.integration
@pytest.mark.skipif(not _real_key("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set or is placeholder")
def test_claude_response_format():
    """Claude API returns a valid briefing dict with all required keys (live call)."""
    from core.claude_client import call_claude_briefing
    from data.portfolio import build_claude_context

    context = build_claude_context()
    null_redis = MagicMock()
    null_redis.get.return_value = None
    null_redis.setex.return_value = True

    with patch("data.technicals._redis", null_redis):
        from data.technicals import get_technicals_for_holdings
        technicals = get_technicals_for_holdings()

    news = {h["symbol"]: {"sentiment_label": "NEUTRAL"} for h in context["holdings"]}
    result = call_claude_briefing(context, technicals, news)

    for key in ("headline", "alerts", "watchlist", "action_items"):
        assert key in result, f"Live Claude response missing key: {key}"
    assert isinstance(result["headline"], str) and len(result["headline"]) > 0
    assert isinstance(result["alerts"], list)
    assert isinstance(result["action_items"], list)


@pytest.mark.integration
@pytest.mark.skipif(not _real_key("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set or is placeholder")
def test_openai_response_format():
    """OpenAI API returns a valid briefing dict with all required keys (live call)."""
    from core.openai_client import call_openai_briefing
    from data.portfolio import build_claude_context

    context = build_claude_context()
    null_redis = MagicMock()
    null_redis.get.return_value = None
    null_redis.setex.return_value = True

    with patch("data.technicals._redis", null_redis):
        from data.technicals import get_technicals_for_holdings
        technicals = get_technicals_for_holdings()

    news = {h["symbol"]: {"sentiment_label": "NEUTRAL"} for h in context["holdings"]}
    result = call_openai_briefing(context, technicals, news)

    for key in ("headline", "alerts", "watchlist", "action_items"):
        assert key in result, f"Live OpenAI response missing key: {key}"
    assert isinstance(result["headline"], str) and len(result["headline"]) > 0
    assert isinstance(result["alerts"], list)
    assert isinstance(result["action_items"], list)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_context() -> dict:
    """Return a minimal portfolio context dict for use in tests."""
    return {
        "portfolio": {
            "total_value": 500000.0,
            "total_pnl_pct": 5.2,
            "holdings_count": 8,
        },
        "holdings": [
            {
                "symbol": "ICICIBANK",
                "pnl_pct": 3.5,
                "sl_status": "SAFE",
                "sector": "Banking",
            }
        ],
        "risk_flags": [],
        "generated_at": "2026-05-02T08:30:00",
    }
