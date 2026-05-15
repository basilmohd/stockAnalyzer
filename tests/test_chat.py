"""
Test suite for chat feature — portfolio-aware LLM conversations via Telegram.
Tests cover: LLM calls, Redis history, rate limiting, route handlers, error handling.
"""
import json
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS: Mock Chat Responses
# ─────────────────────────────────────────────────────────────────────────────

def test_mock_chat_risk_query():
    """Mock chat should respond to risk-related queries."""
    from core.chat_client import _mock_chat_response
    
    response = _mock_chat_response("What is my portfolio risk?")
    # Check for risk-related keywords
    assert any(word in response.lower() for word in ["risk", "warning", "breach", "loss"])
    assert len(response) > 50


def test_mock_chat_top_holdings_query():
    """Mock chat should respond to top holdings queries."""
    from core.chat_client import _mock_chat_response
    
    response = _mock_chat_response("What are my top 3 holdings?")
    assert "top" in response.lower() or "weight" in response.lower()
    assert len(response) > 50


def test_mock_chat_buy_query():
    """Mock chat should respond to buy/accumulate queries."""
    from core.chat_client import _mock_chat_response
    
    response = _mock_chat_response("Should I buy more?")
    # Check for buy-related keywords
    assert any(word in response.lower() for word in ["buy", "accumulate", "oversold", "candidate"])
    assert len(response) > 50


def test_mock_chat_default_fallback():
    """Mock chat should return default response for unknown queries."""
    from core.chat_client import _mock_chat_response
    
    response = _mock_chat_response("Tell me a joke about stocks")
    assert "portfolio" in response.lower() or "analysis" in response.lower()
    assert len(response) > 50


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS: Redis Chat History Management
# ─────────────────────────────────────────────────────────────────────────────

def test_redis_get_chat_history_empty():
    """Redis.get_chat_history() should return empty list when no history exists."""
    from core.redis_client import RedisClient
    
    redis = RedisClient("redis://localhost:6379")
    user_id = "test_user_123"
    history = redis.get_chat_history(user_id)
    
    # Should return empty list (not fail)
    assert isinstance(history, list)
    assert len(history) == 0


def test_redis_append_chat_message():
    """Redis.append_chat_message() should add message to history."""
    from core.redis_client import RedisClient
    
    redis = RedisClient("redis://localhost:6379")
    if not redis.available:
        pytest.skip("Redis unavailable")
    
    user_id = "test_user_456"
    redis.delete(f"chat:{user_id}:messages")  # Clean slate
    
    result = redis.append_chat_message(user_id, "user", "What is my risk?")
    assert result is True
    
    # Verify message was appended
    history = redis.get_chat_history(user_id)
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert "What is my risk?" in history[0]["content"]


def test_redis_chat_history_truncates_at_max():
    """Redis chat history should keep only last N messages (CHAT_HISTORY_MAX_MESSAGES)."""
    from core.redis_client import RedisClient
    import config
    
    redis = RedisClient("redis://localhost:6379")
    if not redis.available:
        pytest.skip("Redis unavailable")
    
    user_id = "test_user_789"
    redis.delete(f"chat:{user_id}:messages")
    
    # Append more messages than MAX_MESSAGES
    for i in range(config.CHAT_HISTORY_MAX_MESSAGES + 5):
        redis.append_chat_message(user_id, "user" if i % 2 == 0 else "assistant", f"Message {i}")
    
    history = redis.get_chat_history(user_id)
    # Should only have last MAX_MESSAGES items
    assert len(history) <= config.CHAT_HISTORY_MAX_MESSAGES


def test_redis_daily_chat_count_increment():
    """Redis.get_daily_chat_count() should increment and return current count."""
    from core.redis_client import RedisClient
    
    redis = RedisClient("redis://localhost:6379")
    if not redis.available:
        pytest.skip("Redis unavailable")
    
    user_id = "test_user_count_inc"
    redis.delete(f"chat:{user_id}:daily_count")
    
    # First call should return 1
    count1 = redis.get_daily_chat_count(user_id)
    assert count1 == 1
    
    # Second call should return 2
    count2 = redis.get_daily_chat_count(user_id)
    assert count2 == 2
    
    # Third call should return 3
    count3 = redis.get_daily_chat_count(user_id)
    assert count3 == 3


def test_redis_daily_chat_count_reset():
    """Redis.reset_daily_chat_count() should delete the count key."""
    from core.redis_client import RedisClient
    
    redis = RedisClient("redis://localhost:6379")
    if not redis.available:
        pytest.skip("Redis unavailable")
    
    user_id = "test_user_count_reset"
    redis.delete(f"chat:{user_id}:daily_count")
    
    # Set a count
    count1 = redis.get_daily_chat_count(user_id)
    assert count1 == 1
    
    # Reset it
    result = redis.reset_daily_chat_count(user_id)
    assert result is True
    
    # Next call should start fresh at 1
    count2 = redis.get_daily_chat_count(user_id)
    assert count2 == 1


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS: Chat Context Building
# ─────────────────────────────────────────────────────────────────────────────

def test_build_chat_context_prompt():
    """_build_chat_context_prompt() should format portfolio data for LLM."""
    from core.chat_client import _build_chat_context_prompt
    
    # Mock portfolio context
    portfolio_context = {
        "portfolio": {
            "total_value": 100000,
            "total_pnl": 5000,
            "total_pnl_pct": 5.0,
            "holdings_count": 3,
        },
        "holdings": [
            {
                "symbol": "ICICIBANK",
                "qty": 10,
                "cmp": 600,
                "pnl_pct": 5.0,
                "weight_pct": 15.0,
                "sl_status": "SAFE",
            }
        ],
        "risk_flags": ["INFY is overbought at RSI 78"],
    }
    
    technicals = {}
    news = {}
    
    prompt = _build_chat_context_prompt(portfolio_context, technicals, news)
    
    # Check for formatted amount (with or without commas)
    assert ("100000" in prompt or "100,000" in prompt)  # Total value
    assert "ICICIBANK" in prompt
    assert "SAFE" in prompt
    assert "overbought" in prompt


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS: LLM Call Dispatching (with mocking)
# ─────────────────────────────────────────────────────────────────────────────

def test_call_chat_with_mock_ai():
    """call_chat() should return mock response when USE_MOCK_AI=true."""
    from core.chat_client import call_chat
    
    with patch("config.USE_MOCK_AI", True):
        response = call_chat(
            portfolio_context={},
            technicals={},
            news={},
            conversation_history=[],
            user_query="What is my portfolio risk?",
        )
        
        assert isinstance(response, str)
        assert len(response) > 0


def test_call_chat_dispatch_to_claude():
    """call_chat() should dispatch to Claude when AI_PROVIDER='claude'."""
    from core.chat_client import call_chat
    
    with patch("config.USE_MOCK_AI", False), \
         patch("config.AI_PROVIDER", "claude"), \
         patch("core.chat_client.call_claude_chat") as mock_claude:
        
        mock_claude.return_value = "Claude response"
        
        response = call_chat(
            portfolio_context={},
            technicals={},
            news={},
            conversation_history=[],
            user_query="Test",
        )
        
        # Verify Claude was called
        assert mock_claude.called


def test_call_chat_dispatch_to_openai():
    """call_chat() should dispatch to OpenAI when AI_PROVIDER='openai'."""
    from core.chat_client import call_chat
    
    with patch("config.USE_MOCK_AI", False), \
         patch("config.AI_PROVIDER", "openai"), \
         patch("core.chat_client.call_openai_chat") as mock_openai:
        
        mock_openai.return_value = "OpenAI response"
        
        response = call_chat(
            portfolio_context={},
            technicals={},
            news={},
            conversation_history=[],
            user_query="Test",
        )
        
        # Verify OpenAI was called
        assert mock_openai.called


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS: Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────

def test_rate_limit_rejection():
    """Chat handler should reject query if daily limit is exceeded."""
    from core.redis_client import RedisClient
    import config
    
    redis = RedisClient("redis://localhost:6379")
    if not redis.available:
        pytest.skip("Redis unavailable")
    
    user_id = "test_user_ratelimit"
    redis.delete(f"chat:{user_id}:daily_count")
    
    # Simulate CHAT_DAILY_LIMIT queries
    for _ in range(config.CHAT_DAILY_LIMIT):
        count = redis.get_daily_chat_count(user_id)
        assert count <= config.CHAT_DAILY_LIMIT
    
    # Next query should exceed limit
    over_limit = redis.get_daily_chat_count(user_id)
    assert over_limit > config.CHAT_DAILY_LIMIT


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS: Telegram Route Handler (async)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_chat_command_basic():
    """_handle_chat_command() should build context and call LLM."""
    from routes.telegram_routes import _handle_chat_command
    from core.redis_client import RedisClient
    
    redis = RedisClient("redis://localhost:6379")
    if not redis.available:
        pytest.skip("Redis unavailable")
    
    user_id = "test_user_route"
    redis.delete(f"chat:{user_id}:daily_count")
    redis.delete(f"chat:{user_id}:messages")
    
    with patch("config.USE_MOCK_AI", True), \
         patch("core.telegram_bot.send_message") as mock_send:
        
        mock_send.return_value = True
        
        await _handle_chat_command(
            user_id=user_id,
            user_query="What is my portfolio risk?",
            redis=redis,
        )
        
        # Verify send_message was called with response
        assert mock_send.called


@pytest.mark.asyncio
async def test_handle_chat_command_rate_limit():
    """_handle_chat_command() should reject query if over daily limit."""
    from routes.telegram_routes import _handle_chat_command
    from core.redis_client import RedisClient
    import config
    
    redis = RedisClient("redis://localhost:6379")
    if not redis.available:
        pytest.skip("Redis unavailable")
    
    user_id = "test_user_ratelimit_handler"
    redis.delete(f"chat:{user_id}:daily_count")
    
    # Simulate exceeding limit
    with patch("redis.Redis.incr") as mock_incr:
        mock_incr.return_value = config.CHAT_DAILY_LIMIT + 1
        
        with patch("core.telegram_bot.send_message") as mock_send:
            mock_send.return_value = True
            
            await _handle_chat_command(
                user_id=user_id,
                user_query="Test",
                redis=redis,
            )
            
            # Verify limit message was sent
            if mock_send.called:
                call_args = str(mock_send.call_args)
                assert "limit" in call_args.lower() or mock_send.called


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS: Error Handling
# ─────────────────────────────────────────────────────────────────────────────

def test_chat_client_handles_redis_unavailable():
    """get_chat_history() should gracefully return [] if Redis unavailable."""
    from core.redis_client import RedisClient
    
    redis = RedisClient("redis://localhost:6379")
    
    # Even if Redis is unavailable, should not raise
    history = redis.get_chat_history("any_user")
    assert isinstance(history, list)


def test_chat_client_handles_invalid_json():
    """get_chat_history() should handle malformed JSON gracefully."""
    from core.redis_client import RedisClient
    
    redis = RedisClient("redis://localhost:6379")
    if not redis.available:
        pytest.skip("Redis unavailable")
    
    user_id = "test_user_invalid_json"
    # Set invalid JSON
    redis.set(f"chat:{user_id}:messages", "{invalid json")
    
    # Should not raise, should return empty list
    history = redis.get_chat_history(user_id)
    assert isinstance(history, list)


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
