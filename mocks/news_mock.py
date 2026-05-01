"""Mock NewsAPI responses for local development (USE_MOCK=true)."""

from datetime import datetime
from typing import Any


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
