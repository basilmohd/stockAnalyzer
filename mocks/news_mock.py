"""Mock NewsAPI responses for local development (USE_MOCK=true)."""

from datetime import datetime
from typing import Any

# ── New-format articles (title, summary, published_at, source, url) ──────────
# Designed so keyword-based sentiment scoring yields the intended label:
#   BULLISH  (score ≥  2): ICICIBANK, INFY, HDFCBANK, BHARTIARTL, APOLLOHOSP
#   BEARISH  (score ≤ -2): TATAMOTORS, PFC
#   NEUTRAL  (-1 ≤ score ≤ 1): SUNPHARMA

_ARTICLES_DATA: dict[str, list[dict[str, str]]] = {
    "ICICIBANK": [
        {
            "title": "ICICI Bank Q4 profit surges on strong retail growth",
            "summary": "Record earnings beat analyst estimates with 18% gain in net interest income",
            "published_at": "2026-05-01T09:30:00",
            "source": "Economic Times",
            "url": "https://example.com/icicibank-q4-profit",
        },
        {
            "title": "ICICI Bank upgraded to buy as digital rally gains momentum",
            "summary": "Outperform rating maintained on strong growth trajectory and credit quality",
            "published_at": "2026-04-30T11:00:00",
            "source": "Moneycontrol",
            "url": "https://example.com/icicibank-upgrade",
        },
        {
            "title": "ICICI Bank raises dividend on record quarterly performance",
            "summary": "Strong asset quality and buy call reiterated by multiple brokerages",
            "published_at": "2026-04-29T08:45:00",
            "source": "Business Standard",
            "url": "https://example.com/icicibank-dividend",
        },
    ],
    "INFY": [
        {
            "title": "Infosys wins record $1.5B deal, outperforms sector peers",
            "summary": "Strong deal pipeline drives revenue growth beat in Q4",
            "published_at": "2026-05-01T10:00:00",
            "source": "Reuters",
            "url": "https://example.com/infy-deal",
        },
        {
            "title": "Infosys AI platform profit surges on enterprise adoption",
            "summary": "Buy recommendation reiterated by top brokerages on strong guidance",
            "published_at": "2026-04-30T12:00:00",
            "source": "CNBC TV18",
            "url": "https://example.com/infy-ai-profit",
        },
        {
            "title": "Infosys upgraded to outperform on strong FY26 guidance",
            "summary": "Rally in IT sector led by growth momentum at Infosys",
            "published_at": "2026-04-29T09:15:00",
            "source": "Mint",
            "url": "https://example.com/infy-upgrade",
        },
    ],
    "HDFCBANK": [
        {
            "title": "HDFC Bank Q4 profit surges, beats analyst consensus",
            "summary": "Record net interest income drives strong performance across segments",
            "published_at": "2026-05-01T08:30:00",
            "source": "Economic Times",
            "url": "https://example.com/hdfc-q4",
        },
        {
            "title": "HDFC Bank upgraded to buy on improving asset quality",
            "summary": "Rally expected as growth picks up in retail and SME segments",
            "published_at": "2026-04-30T10:30:00",
            "source": "Moneycontrol",
            "url": "https://example.com/hdfc-upgrade",
        },
        {
            "title": "HDFC Bank gains record credit card market share",
            "summary": "Outperform rating maintained by analysts on strong fundamentals",
            "published_at": "2026-04-28T14:00:00",
            "source": "Business Line",
            "url": "https://example.com/hdfc-cards",
        },
    ],
    "BHARTIARTL": [
        {
            "title": "Airtel 5G subscriber rally continues with record additions",
            "summary": "Strong ARPU growth beats analyst estimates for Q4",
            "published_at": "2026-05-01T09:00:00",
            "source": "Business Standard",
            "url": "https://example.com/airtel-5g-rally",
        },
        {
            "title": "Bharti Airtel profit surges on Africa mobile money gains",
            "summary": "Buy rating maintained on outperform trajectory across markets",
            "published_at": "2026-04-30T11:30:00",
            "source": "Mint",
            "url": "https://example.com/airtel-profit",
        },
        {
            "title": "Airtel upgraded on strong 5G monetisation and growth",
            "summary": "Record subscriber additions drive revenue beat in latest quarter",
            "published_at": "2026-04-29T10:00:00",
            "source": "CNBC TV18",
            "url": "https://example.com/airtel-upgrade",
        },
    ],
    "APOLLOHOSP": [
        {
            "title": "Apollo Hospitals profit surges on strong occupancy growth",
            "summary": "Record revenue beats analyst estimates across all segments",
            "published_at": "2026-05-01T08:00:00",
            "source": "Economic Times",
            "url": "https://example.com/apollo-profit",
        },
        {
            "title": "Apollo digital pharmacy gains record market share",
            "summary": "Buy rating reiterated on robust outperform thesis",
            "published_at": "2026-04-30T09:45:00",
            "source": "Moneycontrol",
            "url": "https://example.com/apollo-pharmacy",
        },
        {
            "title": "Apollo Hospitals upgraded on strong operational rally",
            "summary": "Consistent profit growth drives investor confidence in long-term outlook",
            "published_at": "2026-04-29T11:00:00",
            "source": "Reuters",
            "url": "https://example.com/apollo-upgrade",
        },
    ],
    "TATAMOTORS": [
        {
            "title": "Tata Motors EV sales miss targets amid competition concerns",
            "summary": "Risk of market share loss as volumes fall sharply in Q4",
            "published_at": "2026-05-01T10:15:00",
            "source": "Economic Times",
            "url": "https://example.com/tatamotors-miss",
        },
        {
            "title": "JLR supply chain concerns trigger weak demand outlook",
            "summary": "Analysts downgrade Tata Motors to sell on margin cut risk",
            "published_at": "2026-04-30T13:00:00",
            "source": "Business Standard",
            "url": "https://example.com/jlr-concerns",
        },
        {
            "title": "Tata Motors underperforms peers as drop in deliveries continues",
            "summary": "Loss in EV share raises further concerns among institutional investors",
            "published_at": "2026-04-28T09:30:00",
            "source": "Mint",
            "url": "https://example.com/tatamotors-underperform",
        },
    ],
    "SUNPHARMA": [
        {
            "title": "Sun Pharma specialty segment shows steady growth trajectory",
            "summary": "Strong US business delivers consistent profit in Q4",
            "published_at": "2026-05-01T09:45:00",
            "source": "Moneycontrol",
            "url": "https://example.com/sunpharma-growth",
        },
        {
            "title": "Sun Pharma faces concern over generic competition in Europe",
            "summary": "Risk to margins noted by analysts in latest review",
            "published_at": "2026-04-30T14:00:00",
            "source": "Business Standard",
            "url": "https://example.com/sunpharma-concern",
        },
        {
            "title": "Sun Pharma India business stable with mixed near-term signals",
            "summary": "Revenue broadly in line; weak generic pricing a headwind",
            "published_at": "2026-04-29T10:30:00",
            "source": "Economic Times",
            "url": "https://example.com/sunpharma-india",
        },
    ],
    "PFC": [
        {
            "title": "PFC flags rising NPA concern in state utility loans",
            "summary": "Risk of credit loss as discom repayments fall sharply",
            "published_at": "2026-05-01T08:15:00",
            "source": "Business Line",
            "url": "https://example.com/pfc-npa",
        },
        {
            "title": "Power Finance Corp downgraded to sell on weak collections",
            "summary": "Drop in loan quality raises underperform concerns for FY26",
            "published_at": "2026-04-30T12:30:00",
            "source": "Economic Times",
            "url": "https://example.com/pfc-downgrade",
        },
        {
            "title": "PFC provisioning cut signals weak financial health outlook",
            "summary": "NPA risk concerns weigh on sentiment; loss in investor confidence",
            "published_at": "2026-04-28T11:00:00",
            "source": "Moneycontrol",
            "url": "https://example.com/pfc-weak",
        },
    ],
}

_DEFAULT_ARTICLES: list[dict[str, str]] = [
    {
        "title": "{symbol} reports steady quarterly results in line with estimates",
        "summary": "Performance broadly in line with market expectations, no major surprises",
        "published_at": "2026-05-01T09:00:00",
        "source": "Economic Times",
        "url": "https://example.com/{symbol}-q4",
    },
    {
        "title": "{symbol} management maintains cautious guidance for next two quarters",
        "summary": "Analysts await sector clarity before revising outlook",
        "published_at": "2026-04-30T10:00:00",
        "source": "Moneycontrol",
        "url": "https://example.com/{symbol}-guidance",
    },
    {
        "title": "{symbol} trading within normal range ahead of results",
        "summary": "No significant triggers expected near term per analyst commentary",
        "published_at": "2026-04-29T11:00:00",
        "source": "Business Standard",
        "url": "https://example.com/{symbol}-outlook",
    },
]


def get_mock_articles(symbol: str, days: int = 3) -> list[dict[str, str]]:
    """Return mock articles in new format for *symbol*, up to 5 articles."""
    articles = _ARTICLES_DATA.get(symbol.upper())
    if articles:
        return articles[:5]
    return [
        {k: v.replace("{symbol}", symbol) for k, v in a.items()}
        for a in _DEFAULT_ARTICLES
    ]


# ── Legacy format (used by get_news_sentiment in data/news.py) ────────────────

_NEWS_DATA: dict[str, dict[str, Any]] = {
    "ICICIBANK": {
        "headlines": [
            "ICICI Bank Q4 profit surges 18% YoY, beats analyst estimates",
            "ICICI Bank expands retail loan book with new digital offerings",
            "ICICI Bank raises home loan limits amid strong demand in metros",
        ],
        "sentiment_score": 0.78,
    },
    "INFY": {
        "headlines": [
            "Infosys wins $1.5B digital transformation deal with European bank",
            "Infosys AI platform sees 40% adoption jump among Fortune 500 clients",
            "Infosys raises FY26 revenue guidance on strong deal pipeline",
        ],
        "sentiment_score": 0.72,
    },
    "HDFCBANK": {
        "headlines": [
            "HDFC Bank net interest margin improves to 3.8% in Q4",
            "HDFC Bank credit card spends hit all-time high in March",
            "HDFC Bank accelerates rural branch expansion to 1,200 new outlets",
        ],
        "sentiment_score": 0.81,
    },
    "BHARTIARTL": {
        "headlines": [
            "Airtel 5G subscriber base crosses 80 million milestone",
            "Bharti Airtel to invest $2B in network expansion across Tier-2 cities",
            "Airtel Africa revenue grows 14% driven by mobile money services",
        ],
        "sentiment_score": 0.75,
    },
    "APOLLOHOSP": {
        "headlines": [
            "Apollo Hospitals opens new 500-bed facility in Hyderabad",
            "Apollo HealthCo digital pharmacy crosses ₹2,000 Cr annualised revenue",
            "Apollo Hospitals rated top private hospital chain in India by NABH",
        ],
        "sentiment_score": 0.83,
    },
    "TATAMOTORS": {
        "headlines": [
            "Tata Motors JLR supply chain disruptions weigh on Q4 deliveries",
            "Tata Motors EV sales miss targets amid intensifying competition from BYD",
            "Tata Motors faces margin pressure as input costs rise in passenger segment",
        ],
        "sentiment_score": 0.32,
    },
    "SUNPHARMA": {
        "headlines": [
            "Sun Pharma specialty segment revenue grows 22% driven by US market",
            "Sun Pharma receives USFDA approval for generic Revlimid",
            "Sun Pharma dermatology brand Ilumya gains market share in Europe",
        ],
        "sentiment_score": 0.76,
    },
    "PFC": {
        "headlines": [
            "PFC flags rising NPA concerns in renewable energy project loans",
            "Power Finance Corp faces headwinds as discom repayments slow",
            "PFC provisioning increases sharply amid state utility credit stress",
        ],
        "sentiment_score": 0.28,
    },
}

_DEFAULT_SENTIMENT = 0.55
_DEFAULT_HEADLINES = [
    "{symbol} reports steady quarterly performance in line with estimates",
    "{symbol} management guidance remains cautious for next two quarters",
    "Analysts maintain neutral rating on {symbol} pending sector clarity",
]


def get_mock_news(symbol: str) -> dict[str, Any]:
    """Return mock news headlines and sentiment score for a given symbol.

    TATAMOTORS and PFC intentionally carry negative sentiment (0.2–0.4)
    to reflect their underperformance in the mock holdings data.
    """
    data = _NEWS_DATA.get(symbol.upper())
    if data:
        headlines = data["headlines"]
        sentiment_score = data["sentiment_score"]
    else:
        headlines = [h.format(symbol=symbol) for h in _DEFAULT_HEADLINES]
        sentiment_score = _DEFAULT_SENTIMENT

    return {
        "headlines":       headlines,
        "sentiment_score": sentiment_score,
        "fetched_at":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
