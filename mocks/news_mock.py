"""Mock NewsAPI responses — fallback when USE_MOCK=true or NewsAPI is unavailable."""

from datetime import datetime
from typing import Any

# Sentiment design:
#   BULLISH  (score ≥  2): IRCTC, POLYCAB, OLECTRA, VARUNBEV, EXIDEIND
#   BEARISH  (score ≤ -2): (none currently)
#   NEUTRAL  (-1 ≤ score ≤ 1): RELIANCE, MARUTI, KOTAKGOLD, TATAMTRDVR, MOTHERSON, SGBSEP31

_ARTICLES_DATA: dict[str, list[dict[str, str]]] = {
    "IRCTC": [
        {
            "title": "IRCTC Q4 profit surges on record rail tourism bookings",
            "summary": "Strong growth in premium train categories drives revenue beat; buy reiterated by brokerages",
            "published_at": "2026-05-01T09:30:00",
            "source": "Economic Times",
            "url": "https://example.com/irctc-q4-profit",
        },
        {
            "title": "IRCTC catering business rally continues with new station wins",
            "summary": "Outperform rating maintained on consistent earnings growth and monopoly advantage",
            "published_at": "2026-04-30T11:00:00",
            "source": "Moneycontrol",
            "url": "https://example.com/irctc-catering-rally",
        },
        {
            "title": "IRCTC upgraded on strong digital ticketing surge and rising ARPU",
            "summary": "Record online bookings drive profit growth; analysts raise target price",
            "published_at": "2026-04-29T08:45:00",
            "source": "Business Standard",
            "url": "https://example.com/irctc-upgrade",
        },
    ],
    "POLYCAB": [
        {
            "title": "Polycab Q4 profit surges on infrastructure boom and B2C growth",
            "summary": "Revenue beat driven by wires & cables segment; buy call maintained",
            "published_at": "2026-05-01T10:00:00",
            "source": "Mint",
            "url": "https://example.com/polycab-q4",
        },
        {
            "title": "Polycab India gains record market share in FMEG segment",
            "summary": "Strong outperform trajectory on electrification tailwind across Tier-2/3 cities",
            "published_at": "2026-04-30T12:00:00",
            "source": "CNBC TV18",
            "url": "https://example.com/polycab-fmeg",
        },
        {
            "title": "Polycab upgraded on Capex cycle rally and strong order pipeline",
            "summary": "Buy rating reiterated; growth momentum remains intact for FY27",
            "published_at": "2026-04-29T09:15:00",
            "source": "Economic Times",
            "url": "https://example.com/polycab-upgrade",
        },
    ],
    "RELIANCE": [
        {
            "title": "Reliance Industries Q4 results in line with estimates across segments",
            "summary": "Retail and Jio steady; refining margins show moderate recovery",
            "published_at": "2026-05-01T08:30:00",
            "source": "Economic Times",
            "url": "https://example.com/reliance-q4",
        },
        {
            "title": "Reliance Jio 5G subscriber growth stable; no major near-term triggers",
            "summary": "Analysts maintain neutral outlook pending new energy segment clarity",
            "published_at": "2026-04-30T10:30:00",
            "source": "Business Standard",
            "url": "https://example.com/reliance-jio",
        },
        {
            "title": "Reliance retail expansion continues with cautious store opening guidance",
            "summary": "Management guidance broadly in line; no significant upside catalyst near term",
            "published_at": "2026-04-29T14:00:00",
            "source": "Moneycontrol",
            "url": "https://example.com/reliance-retail",
        },
    ],
    "OLECTRA": [
        {
            "title": "Olectra Greentech wins record 1,000 electric bus order from MSRTC",
            "summary": "Strong order book surge drives revenue visibility for next 3 years; buy reiterated",
            "published_at": "2026-05-01T09:00:00",
            "source": "Business Standard",
            "url": "https://example.com/olectra-order",
        },
        {
            "title": "Olectra EV bus deliveries rally as government fleet electrification accelerates",
            "summary": "Outperform rating on record order pipeline and improving margins",
            "published_at": "2026-04-30T11:30:00",
            "source": "Mint",
            "url": "https://example.com/olectra-delivery",
        },
        {
            "title": "Olectra upgraded on strong Q4 profit growth and export opportunity",
            "summary": "Buy rating maintained; new bus models to drive growth in FY27",
            "published_at": "2026-04-29T10:00:00",
            "source": "Economic Times",
            "url": "https://example.com/olectra-upgrade",
        },
    ],
    "MARUTI": [
        {
            "title": "Maruti Suzuki monthly sales broadly stable amid new competition",
            "summary": "Market share steady; analysts maintain cautious guidance for Q1 FY27",
            "published_at": "2026-05-01T09:45:00",
            "source": "CNBC TV18",
            "url": "https://example.com/maruti-sales",
        },
        {
            "title": "Maruti SUV portfolio shows steady demand; CNG segment outperforms",
            "summary": "Revenue in line; no major near-term triggers expected by analysts",
            "published_at": "2026-04-30T14:00:00",
            "source": "Business Standard",
            "url": "https://example.com/maruti-suv",
        },
        {
            "title": "Maruti Suzuki India trading range-bound ahead of Q4 results",
            "summary": "Neutral rating maintained; FY27 volume guidance awaited by investors",
            "published_at": "2026-04-29T10:30:00",
            "source": "Economic Times",
            "url": "https://example.com/maruti-outlook",
        },
    ],
    "KOTAKGOLD": [
        {
            "title": "Gold ETFs see steady inflows as global uncertainty drives demand",
            "summary": "Kotak Gold ETF tracks international gold prices; no stock-specific triggers",
            "published_at": "2026-05-01T09:00:00",
            "source": "Moneycontrol",
            "url": "https://example.com/kotakgold-inflows",
        },
        {
            "title": "Gold prices broadly stable as Fed rate outlook remains uncertain",
            "summary": "ETF performance mirrors commodity; analyst outlook neutral for near term",
            "published_at": "2026-04-30T10:00:00",
            "source": "Economic Times",
            "url": "https://example.com/gold-stable",
        },
        {
            "title": "Kotak Gold ETF trading in normal range; no operational triggers",
            "summary": "Performance tied to spot gold; suitable as portfolio hedge",
            "published_at": "2026-04-29T11:00:00",
            "source": "Business Standard",
            "url": "https://example.com/kotakgold-range",
        },
    ],
    "VARUNBEV": [
        {
            "title": "Varun Beverages Q4 profit surges on record summer season volumes",
            "summary": "PepsiCo franchise growth beats estimates; buy rating reiterated by multiple brokers",
            "published_at": "2026-05-01T08:00:00",
            "source": "Economic Times",
            "url": "https://example.com/varunbev-q4",
        },
        {
            "title": "Varun Beverages gains record market share in Africa expansion",
            "summary": "Strong outperform on international geography rally and new SKU launches",
            "published_at": "2026-04-30T09:45:00",
            "source": "Moneycontrol",
            "url": "https://example.com/varunbev-africa",
        },
        {
            "title": "Varun Beverages upgraded on strong FY27 volume growth guidance",
            "summary": "Consistent profit expansion drives buy thesis; summer demand surge ahead",
            "published_at": "2026-04-29T11:00:00",
            "source": "Business Standard",
            "url": "https://example.com/varunbev-upgrade",
        },
    ],
    "TATAMTRDVR": [
        {
            "title": "Tata Motors JLR volumes stabilise after earlier supply disruptions",
            "summary": "Results broadly in line; analysts maintain cautious outlook on EV margin",
            "published_at": "2026-05-01T10:15:00",
            "source": "Economic Times",
            "url": "https://example.com/tatamtrdvr-jlr",
        },
        {
            "title": "Tata Motors DVR discount narrows as investors reassess EV strategy",
            "summary": "Mixed near-term signals; no strong catalyst for DVR re-rating",
            "published_at": "2026-04-30T13:00:00",
            "source": "Business Standard",
            "url": "https://example.com/tatamtrdvr-dvr",
        },
        {
            "title": "Tata Motors commercial vehicle segment shows steady recovery",
            "summary": "Domestic CV demand stable; global uncertainty weighs on JLR outlook",
            "published_at": "2026-04-28T09:30:00",
            "source": "Mint",
            "url": "https://example.com/tatamtrdvr-cv",
        },
    ],
    "MOTHERSON": [
        {
            "title": "Motherson Sumi revenue grows on European auto recovery",
            "summary": "Steady performance across geographies; margins improving gradually",
            "published_at": "2026-05-01T09:45:00",
            "source": "Moneycontrol",
            "url": "https://example.com/motherson-q4",
        },
        {
            "title": "Motherson wins new EV wiring harness orders from European OEMs",
            "summary": "Order win supports growth outlook; analysts maintain neutral-to-positive view",
            "published_at": "2026-04-30T14:00:00",
            "source": "Business Standard",
            "url": "https://example.com/motherson-ev",
        },
        {
            "title": "Motherson trading in range; auto ancillary sector broadly stable",
            "summary": "No major near-term triggers; valuation fair at current levels",
            "published_at": "2026-04-29T10:30:00",
            "source": "Economic Times",
            "url": "https://example.com/motherson-range",
        },
    ],
    "EXIDEIND": [
        {
            "title": "Exide Industries Q4 profit surges on EV battery and replacement demand",
            "summary": "Strong growth in Li-ion segment beats analyst estimates; buy reiterated",
            "published_at": "2026-05-01T08:15:00",
            "source": "Economic Times",
            "url": "https://example.com/exideind-q4",
        },
        {
            "title": "Exide Industries gains on EV battery JV ramp-up and export rally",
            "summary": "Outperform rating on strong transition from lead-acid to Li-ion",
            "published_at": "2026-04-30T12:30:00",
            "source": "Moneycontrol",
            "url": "https://example.com/exideind-ev",
        },
        {
            "title": "Exide upgraded on record aftermarket battery demand and margin improvement",
            "summary": "Profit growth trajectory intact; buy call maintained by top brokers",
            "published_at": "2026-04-28T11:00:00",
            "source": "Business Standard",
            "url": "https://example.com/exideind-upgrade",
        },
    ],
    "SGBSEP31": [
        {
            "title": "Sovereign Gold Bond 2031 series trades at premium to gold NAV",
            "summary": "2.5% interest plus gold appreciation makes SGB attractive long-term hold",
            "published_at": "2026-05-01T09:00:00",
            "source": "Economic Times",
            "url": "https://example.com/sgb-2031",
        },
        {
            "title": "Gold bonds broadly stable as RBI maintains monetary policy stance",
            "summary": "SGB redemption price tracks IBJA gold rate; no near-term catalyst",
            "published_at": "2026-04-30T10:00:00",
            "source": "Moneycontrol",
            "url": "https://example.com/sgb-rbi",
        },
        {
            "title": "SGB investors hold steady; no significant secondary market triggers",
            "summary": "Long-term gold exposure with sovereign guarantee; neutral trading outlook",
            "published_at": "2026-04-29T11:00:00",
            "source": "Business Standard",
            "url": "https://example.com/sgb-hold",
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
    "IRCTC": {
        "headlines": [
            "IRCTC Q4 profit surges 22% on record rail tourism and catering revenues",
            "IRCTC digital ticketing platform crosses 1.2 million daily bookings milestone",
            "IRCTC premium train segment grows 30% as leisure travel demand surges",
        ],
        "sentiment_score": 0.79,
    },
    "POLYCAB": {
        "headlines": [
            "Polycab India Q4 net profit beats estimates on strong wires and cables demand",
            "Polycab gains record FMEG market share as infrastructure spend accelerates",
            "Polycab upgraded to buy on robust capex cycle and distribution expansion",
        ],
        "sentiment_score": 0.82,
    },
    "RELIANCE": {
        "headlines": [
            "Reliance Industries Q4 results in line with estimates across all segments",
            "Reliance Jio 5G network expansion reaches 500 cities across India",
            "Reliance Retail maintains cautious store expansion guidance for FY27",
        ],
        "sentiment_score": 0.54,
    },
    "OLECTRA": {
        "headlines": [
            "Olectra Greentech wins 1,000 electric bus order in largest state fleet deal",
            "Olectra EV bus deliveries surge as GSRTC, MSRTC expand green fleet",
            "Olectra upgraded to buy on strong order pipeline and margin improvement",
        ],
        "sentiment_score": 0.80,
    },
    "MARUTI": {
        "headlines": [
            "Maruti Suzuki monthly sales stable; SUV segment maintains market leadership",
            "Maruti Suzuki cautious on near-term guidance amid rising EV competition",
            "Maruti FY27 volume outlook neutral as analysts await new model launches",
        ],
        "sentiment_score": 0.50,
    },
    "KOTAKGOLD": {
        "headlines": [
            "Kotak Gold ETF sees steady inflows as gold prices hold above key levels",
            "Gold ETFs broadly neutral as Fed rate signals keep bullion range-bound",
            "Kotak Gold ETF performance tied to international spot prices; no equity triggers",
        ],
        "sentiment_score": 0.52,
    },
    "VARUNBEV": {
        "headlines": [
            "Varun Beverages Q4 profit surges on record summer beverage demand",
            "Varun Beverages Africa expansion delivers strong volume growth beat",
            "Varun Beverages upgraded on consistent earnings growth and new territory wins",
        ],
        "sentiment_score": 0.81,
    },
    "TATAMTRDVR": {
        "headlines": [
            "Tata Motors JLR volumes stabilise; CV segment shows steady domestic recovery",
            "Tata Motors DVR discount narrows as investors reassess long-term EV positioning",
            "Tata Motors results broadly in line; mixed near-term outlook maintained",
        ],
        "sentiment_score": 0.48,
    },
    "MOTHERSON": {
        "headlines": [
            "Motherson wins new EV wiring harness orders from European auto OEMs",
            "Motherson auto ancillary revenues grow on global OEM recovery",
            "Motherson rated neutral; valuation fair amid global auto uncertainty",
        ],
        "sentiment_score": 0.53,
    },
    "EXIDEIND": {
        "headlines": [
            "Exide Industries profit surges on Li-ion EV battery JV ramp-up",
            "Exide gains record replacement battery market share in two-wheeler segment",
            "Exide Industries upgraded to buy on strong FY27 EV battery growth outlook",
        ],
        "sentiment_score": 0.78,
    },
    "SGBSEP31": {
        "headlines": [
            "Sovereign Gold Bond 2031 series appreciates 162% since issue on gold rally",
            "SGB investors benefit from 2.5% annual interest plus capital appreciation",
            "Gold bond secondary market stable; RBI maintains redemption schedule",
        ],
        "sentiment_score": 0.60,
    },
}

_DEFAULT_SENTIMENT = 0.55
_DEFAULT_HEADLINES = [
    "{symbol} reports steady quarterly performance in line with estimates",
    "{symbol} management guidance remains cautious for next two quarters",
    "Analysts maintain neutral rating on {symbol} pending sector clarity",
]


def get_mock_news(symbol: str) -> dict[str, Any]:
    """Return mock news headlines and sentiment score for a given symbol."""
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
