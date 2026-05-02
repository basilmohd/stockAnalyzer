"""News fetcher and sentiment scoring for portfolio symbols."""

import json
import logging
from datetime import datetime, timedelta

import config
from core.redis_client import RedisClient

logger = logging.getLogger(__name__)
_redis = RedisClient(config.REDIS_URL)

_BULLISH_KEYWORDS = {"gain", "beat", "surge", "strong", "bullish", "rally", "jump", "rise", "profit"}
_BEARISH_KEYWORDS = {"loss", "miss", "down", "weak", "bearish", "fall", "drop", "decline"}


def get_news_sentiment(symbol: str) -> dict:
    """Return news headlines and 0-1 sentiment score for *symbol*, cached in Redis (TTL 2h).

    Returns dict with keys: headlines (list of 3), sentiment_score (0-1), fetched_at.
    """
    cache_key = f"news:{symbol}"
    cached = _redis.get(cache_key)
    if cached:
        logger.info("News cache hit: %s", symbol)
        return json.loads(cached)

    result = _fetch_and_score(symbol)
    _redis.setex(cache_key, 7200, json.dumps(result))
    return result


def _fetch_and_score(symbol: str) -> dict:
    """Fetch headlines from NewsAPI (or mock) and compute sentiment."""
    if config.USE_MOCK:
        return _fetch_from_mock(symbol)
    return _fetch_from_newsapi(symbol)


def _fetch_from_mock(symbol: str) -> dict:
    """Return pre-built mock headlines for local development."""
    from mocks.news_mock import get_mock_news
    data = get_mock_news(symbol)
    headlines = []
    for h in data["headlines"][:3]:
        if isinstance(h, str):
            headlines.append({"title": h, "description": "", "url": ""})
        else:
            headlines.append(h)
    while len(headlines) < 3:
        headlines.append({"title": "", "description": "", "url": ""})
    return {
        "headlines":       headlines,
        "sentiment_score": float(data["sentiment_score"]),
        "fetched_at":      datetime.utcnow().isoformat(),
    }


def _fetch_from_newsapi(symbol: str) -> dict:
    """Call NewsAPI for the last 24 hrs and score sentiment."""
    try:
        from newsapi import NewsApiClient
        client = NewsApiClient(api_key=config.NEWS_API_KEY)
        to_dt = datetime.utcnow()
        from_dt = to_dt - timedelta(hours=24)
        response = client.get_everything(
            q=f"{symbol} NSE OR BSE",
            from_param=from_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            to=to_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            language="en",
            sort_by="publishedAt",
            page_size=10,
        )
        articles = response.get("articles", [])
    except Exception as exc:
        logger.warning("NewsAPI error for %s: %s", symbol, exc)
        articles = []

    headlines = []
    for art in articles[:3]:
        headlines.append({
            "title":       art.get("title", "") or "",
            "description": art.get("description", "") or "",
            "url":         art.get("url", "") or "",
        })
    while len(headlines) < 3:
        headlines.append({"title": "", "description": "", "url": ""})

    return {
        "headlines":       headlines,
        "sentiment_score": _score_sentiment(headlines),
        "fetched_at":      datetime.utcnow().isoformat(),
    }


def _score_sentiment(headlines: list[dict]) -> float:
    """Return a 0-1 sentiment score by counting bullish vs bearish keywords in headlines."""
    text = " ".join(
        (h.get("title", "") + " " + h.get("description", "")).lower()
        for h in headlines
    )
    bullish_count = sum(1 for kw in _BULLISH_KEYWORDS if kw in text)
    bearish_count = sum(1 for kw in _BEARISH_KEYWORDS if kw in text)
    total = bullish_count + bearish_count
    if total == 0:
        return 0.5
    return round(bullish_count / total, 2)


# ── New-format API (fetch_news_for_symbol / compute_sentiment_score) ──────────

_POSITIVE_KEYWORDS = [
    "surge", "gain", "profit", "growth", "beat", "strong", "upgrade",
    "buy", "outperform", "record", "rally",
]
_NEGATIVE_KEYWORDS = [
    "fall", "drop", "loss", "weak", "downgrade", "sell", "underperform",
    "concern", "risk", "cut", "miss",
]


def fetch_news_for_symbol(symbol: str, days: int = 3) -> list[dict]:
    """Fetch up to 5 news articles for *symbol*, cached in Redis (TTL 2h).

    Each article: {title, summary, published_at, source, url}.
    Uses mock data when USE_MOCK=true, NewsAPI otherwise.
    """
    cache_key = f"news_articles:{symbol}"
    cached = _redis.get(cache_key)
    if cached:
        logger.info("News articles cache hit: %s", symbol)
        return json.loads(cached)

    articles = _fetch_articles(symbol, days)
    try:
        _redis.setex(cache_key, 7200, json.dumps(articles))
    except Exception as exc:
        logger.warning("Redis setex failed for %s: %s", cache_key, exc)
    return articles


def _fetch_articles(symbol: str, days: int) -> list[dict]:
    """Route to mock or live NewsAPI depending on USE_MOCK flag."""
    if config.USE_MOCK:
        from mocks.news_mock import get_mock_articles
        return get_mock_articles(symbol, days)
    return _fetch_articles_from_newsapi(symbol, days)


def _fetch_articles_from_newsapi(symbol: str, days: int) -> list[dict]:
    """Call NewsAPI and return articles in normalised format (max 5)."""
    try:
        from newsapi import NewsApiClient
        client = NewsApiClient(api_key=config.NEWS_API_KEY)
        to_dt = datetime.utcnow()
        from_dt = to_dt - timedelta(days=days)
        response = client.get_everything(
            q=f"{symbol} stock India",
            from_param=from_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            to=to_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            language="en",
            sort_by="publishedAt",
            page_size=5,
        )
        raw = response.get("articles", [])[:5]
    except Exception as exc:
        logger.warning("NewsAPI fetch failed for %s: %s", symbol, exc)
        return []

    return [
        {
            "title":        art.get("title", "") or "",
            "summary":      art.get("description", "") or "",
            "published_at": art.get("publishedAt", "") or "",
            "source":       (art.get("source") or {}).get("name", "") or "",
            "url":          art.get("url", "") or "",
        }
        for art in raw
    ]


def compute_sentiment_score(articles: list[dict]) -> dict:
    """Score sentiment from article titles and summaries using keyword matching.

    Returns {overall_score, sentiment_label, article_count, articles}.
    BULLISH if overall_score >= 2, BEARISH if <= -2, else NEUTRAL.
    """
    overall_score = 0
    for article in articles:
        text = (
            (article.get("title", "") or "") + " " +
            (article.get("summary", "") or "")
        ).lower()
        overall_score += sum(1 for kw in _POSITIVE_KEYWORDS if kw in text)
        overall_score -= sum(1 for kw in _NEGATIVE_KEYWORDS if kw in text)

    if overall_score >= 2:
        label = "BULLISH"
    elif overall_score <= -2:
        label = "BEARISH"
    else:
        label = "NEUTRAL"

    return {
        "overall_score":   overall_score,
        "sentiment_label": label,
        "article_count":   len(articles),
        "articles":        articles,
    }


def get_news_sentiment_all_holdings() -> dict[str, dict]:
    """Fetch and score news sentiment for every holding in the portfolio.

    Returns {symbol: compute_sentiment_score result, ...}.
    """
    from core.kite_client import KiteClient
    holdings = KiteClient().get_holdings()
    results: dict[str, dict] = {}
    for holding in holdings:
        symbol: str = holding["tradingsymbol"]
        articles = fetch_news_for_symbol(symbol)
        results[symbol] = compute_sentiment_score(articles)
    return results
