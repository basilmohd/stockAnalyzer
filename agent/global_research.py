"""Global market research agent — analyzes international market trends and portfolio impact.

Monday 8:15 AM job: research European, American, and Indian market sentiment for the week ahead.
"""

from datetime import datetime

import pytz

import config
from core.logger import get_logger
from core.telegram_bot import send_long_message
from data.news import fetch_index_news, get_news_sentiment_all_holdings
from data.portfolio import build_claude_context
from data.technicals import get_technicals_for_holdings

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")


async def run_global_market_research() -> dict:
    """Orchestrate global market research: fetch indices + portfolio data, generate report, send to Telegram.

    Returns: {success: bool, report: str, chunk_count: int, error: str}
    """
    try:
        logger.info("Starting global market research job")

        # Fetch international indices news
        logger.info("Fetching news for %d indices", len(config.GLOBAL_RESEARCH_INDICES))
        indices_data = {}
        for index_name in config.GLOBAL_RESEARCH_INDICES:
            try:
                index_news = fetch_index_news(index_name, days=7)
                indices_data[index_name] = index_news
                logger.info("Fetched news for %s: %s", index_name, index_news.get("sentiment_label", "UNKNOWN"))
            except Exception as exc:
                logger.error("Error fetching news for %s: %s", index_name, exc)
                indices_data[index_name] = {"articles": [], "sentiment_label": "UNKNOWN", "error": str(exc)}

        # Fetch portfolio context
        logger.info("Building portfolio context")
        portfolio_context = build_claude_context()

        # Fetch technicals for all holdings
        logger.info("Fetching technicals for holdings")
        holdings = portfolio_context.get("holdings", [])
        symbols = [h.get("tradingsymbol") for h in holdings if h.get("tradingsymbol")]
        technicals_data = {}
        if symbols:
            try:
                technicals_data = get_technicals_for_holdings(symbols)
            except Exception as exc:
                logger.error("Error fetching technicals: %s", exc)

        # Fetch news sentiment for all holdings
        logger.info("Fetching news sentiment for holdings")
        try:
            news_sentiment = get_news_sentiment_all_holdings()
        except Exception as exc:
            logger.error("Error fetching news sentiment: %s", exc)
            news_sentiment = {}

        # Build research context
        research_context = {
            "indices": indices_data,
            "portfolio": {
                "context": portfolio_context,
                "technicals": technicals_data,
                "news": news_sentiment,
            },
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        }

        logger.info("Research context built — calling OpenAI for report generation")

        # Generate report via OpenAI
        from core.openai_client import generate_global_market_research_report
        report = generate_global_market_research_report(research_context)

        if not report:
            logger.error("OpenAI returned empty report")
            return {"success": False, "report": "", "chunk_count": 0, "error": "Empty report from OpenAI"}

        logger.info("Report generated (%d chars)", len(report))

        # Format with header
        timestamp_str = datetime.now(IST).strftime("%A, %B %d, %Y")
        full_report = f"""📊 **Global Market Research Report**
{timestamp_str} — Week Ahead Analysis

{report}"""

        # Send to Telegram (with chunking if needed)
        logger.info("Sending report to Telegram")
        results = await send_long_message(full_report)
        successful_chunks = sum(1 for r in results if r)
        total_chunks = len(results)

        logger.info("Report sent: %d/%d chunks successful", successful_chunks, total_chunks)

        return {
            "success": successful_chunks > 0,
            "report": full_report,
            "chunk_count": total_chunks,
        }

    except Exception as exc:
        logger.exception("Global market research job failed")
        return {"success": False, "report": "", "chunk_count": 0, "error": str(exc)}
