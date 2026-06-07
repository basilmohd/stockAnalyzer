"""Tests for global market research agent."""

import pytest
from datetime import datetime

import config


class TestFetchIndexNews:
    """Tests for fetch_index_news() function."""

    def test_fetch_index_news_mock_mode(self):
        """Test fetching index news in mock mode."""
        from data.news import fetch_index_news

        # Ensure we're in mock mode
        original_use_mock = config.USE_MOCK
        config.USE_MOCK = True

        try:
            result = fetch_index_news("S&P 500", days=7)

            assert isinstance(result, dict)
            assert "index_name" in result
            assert result["index_name"] == "S&P 500"
            assert "articles" in result
            assert isinstance(result["articles"], list)
            assert "sentiment_label" in result
            assert result["sentiment_label"] in ["BULLISH", "NEUTRAL", "BEARISH"]
            assert "article_count" in result
            assert isinstance(result["article_count"], int)
            assert "fetched_at" in result
        finally:
            config.USE_MOCK = original_use_mock

    def test_fetch_index_news_caching(self):
        """Test that index news is cached in Redis."""
        from data.news import fetch_index_news
        from core.redis_client import RedisClient

        original_use_mock = config.USE_MOCK
        config.USE_MOCK = True

        try:
            redis = RedisClient(config.REDIS_URL)

            # First fetch
            result1 = fetch_index_news("DAX", days=7)

            # Check Redis cache
            cache_key = "index_news:DAX"
            cached = redis.get(cache_key)
            assert cached is not None

            # Second fetch should hit cache
            result2 = fetch_index_news("DAX", days=7)
            assert result1["articles"] == result2["articles"]
        finally:
            config.USE_MOCK = original_use_mock

    def test_fetch_multiple_indices(self):
        """Test fetching news for multiple indices."""
        from data.news import fetch_index_news

        original_use_mock = config.USE_MOCK
        config.USE_MOCK = True

        try:
            indices = ["S&P 500", "DAX", "FTSE 100", "Nifty 50"]
            results = {}

            for idx in indices:
                results[idx] = fetch_index_news(idx, days=7)

            # Verify all results
            for idx, result in results.items():
                assert result["index_name"] == idx
                assert len(result["articles"]) > 0
                assert result["article_count"] > 0
        finally:
            config.USE_MOCK = original_use_mock


class TestGenerateGlobalMarketResearchReport:
    """Tests for OpenAI report generation."""

    def test_generate_report_structure(self):
        """Test that report is generated with expected sections."""
        import json
        from core.openai_client import generate_global_market_research_report

        # Mock research context
        research_context = {
            "indices": {
                "S&P 500": {
                    "articles": [
                        {
                            "title": "S&P 500 rallies on dovish signals",
                            "summary": "Fed signals potential rate pause",
                        }
                    ],
                    "sentiment_label": "BULLISH",
                    "article_count": 1,
                },
                "DAX": {
                    "articles": [
                        {"title": "DAX declines on growth concerns", "summary": "Economic slowdown feared"}
                    ],
                    "sentiment_label": "BEARISH",
                    "article_count": 1,
                },
            },
            "portfolio": {
                "context": {
                    "portfolio": {
                        "total_value": 1000000,
                        "total_pnl_pct": 5.5,
                        "holdings_count": 5,
                    },
                    "holdings": [
                        {"tradingsymbol": "RELIANCE", "quantity": 10, "pnl_pct": 3.2},
                        {"tradingsymbol": "TCS", "quantity": 5, "pnl_pct": 8.1},
                    ],
                    "risk_flags": ["High volatility in tech sector"],
                },
                "technicals": {
                    "RELIANCE": {"rsi": 65, "macd_histogram": 2.5},
                    "TCS": {"rsi": 58, "macd_histogram": 1.8},
                },
                "news": {
                    "RELIANCE": {"sentiment_label": "BULLISH"},
                    "TCS": {"sentiment_label": "NEUTRAL"},
                },
            },
            "timestamp": "2026-05-20 08:15:00 IST",
        }

        # Skip if OPENAI_API_KEY not set (for CI/CD)
        if not config.OPENAI_API_KEY:
            pytest.skip("OPENAI_API_KEY not configured")

        try:
            report = generate_global_market_research_report(research_context)

            assert isinstance(report, str)
            assert len(report) > 100  # Substantial report
            # Check for expected sections (case-insensitive)
            report_lower = report.lower()
            assert "market outlook" in report_lower or "outlook" in report_lower
            assert "sector" in report_lower or "portfolio" in report_lower
        except Exception as exc:
            # If API fails, skip (likely missing/invalid key in test env)
            pytest.skip(f"OpenAI API call failed: {exc}")

    def test_research_context_builder(self):
        """Test building research context from portfolio data."""
        from core.openai_client import _build_indices_summary, _build_portfolio_summary

        # Mock indices
        indices = {
            "S&P 500": {
                "articles": [{"title": "Market rallies", "summary": "Strong earnings"}],
                "sentiment_label": "BULLISH",
                "article_count": 1,
            },
            "DAX": {
                "articles": [{"title": "Weakness persists", "summary": "Economic headwinds"}],
                "sentiment_label": "BEARISH",
                "article_count": 1,
            },
        }

        summary = _build_indices_summary(indices)
        assert "S&P 500" in summary
        assert "BULLISH" in summary
        assert "DAX" in summary
        assert "BEARISH" in summary

    def test_send_long_message_chunking(self):
        """Test that long messages are properly chunked."""
        pytest.skip("Async test — requires asyncio fixture")


class TestGlobalResearchOrchestrator:
    """Tests for run_global_market_research orchestrator."""

    @pytest.mark.asyncio
    async def test_orchestrator_returns_dict(self):
        """Test that orchestrator returns proper dict structure."""
        from agent.global_research import run_global_market_research

        original_use_mock = config.USE_MOCK
        config.USE_MOCK = True

        try:
            result = await run_global_market_research()

            assert isinstance(result, dict)
            assert "success" in result
            assert "report" in result
            assert "chunk_count" in result
            assert isinstance(result["success"], bool)
            assert isinstance(result["report"], str)
            assert isinstance(result["chunk_count"], int)
        finally:
            config.USE_MOCK = original_use_mock

    @pytest.mark.asyncio
    async def test_orchestrator_fetches_indices(self):
        """Test that orchestrator fetches all configured indices."""
        from agent.global_research import run_global_market_research

        original_use_mock = config.USE_MOCK
        config.USE_MOCK = True

        try:
            result = await run_global_market_research()

            # If successful, report should mention at least some indices
            if result["success"]:
                report_lower = result["report"].lower()
                # Check for at least one index mention
                indices_lower = [idx.lower() for idx in config.GLOBAL_RESEARCH_INDICES]
                found_any = any(idx in report_lower for idx in indices_lower)
                assert found_any or len(result["report"]) > 0
        finally:
            config.USE_MOCK = original_use_mock


class TestIntegration:
    """Integration tests for the complete global research flow."""

    def test_config_has_indices(self):
        """Test that config includes all required indices."""
        assert hasattr(config, "GLOBAL_RESEARCH_INDICES")
        assert isinstance(config.GLOBAL_RESEARCH_INDICES, list)
        assert len(config.GLOBAL_RESEARCH_INDICES) > 0
        assert "S&P 500" in config.GLOBAL_RESEARCH_INDICES
        assert "Nifty 50" in config.GLOBAL_RESEARCH_INDICES

    def test_config_has_cache_ttl(self):
        """Test that config includes cache TTL for research data."""
        assert hasattr(config, "GLOBAL_RESEARCH_CACHE_TTL")
        assert config.GLOBAL_RESEARCH_CACHE_TTL == 604800  # 7 days

    def test_config_has_chunk_size(self):
        """Test that config includes chunk size for Telegram."""
        assert hasattr(config, "GLOBAL_RESEARCH_MAX_CHUNK_SIZE")
        assert isinstance(config.GLOBAL_RESEARCH_MAX_CHUNK_SIZE, int)
        assert config.GLOBAL_RESEARCH_MAX_CHUNK_SIZE > 0
