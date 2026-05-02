# Portfolio Agent — AI Stock Management System

## What This Is
Python-based AI agent for managing an Indian equity portfolio (20+ NSE stocks).
Built by Basil Mohd Sufyan. Local dev on Windows/WSL, deploys to AWS EC2 t3.small Mumbai.

## Architecture — Two Separate Processes
- webhook_server.py → FastAPI + Uvicorn on port 8000
  Handles: Telegram button tap callbacks, Kite OAuth redirect, /health endpoint
- scheduler.py → APScheduler with AsyncIOScheduler (timezone: Asia/Kolkata)
  Handles: All timed jobs — briefing 8:30AM, SL monitor every 5min, signals 11AM+2PM,
  scanner 12:30PM, post-market 4PM, health report Sunday 7PM

## Shared State
- Redis → live price cache (60s TTL), Kite access token (24hr TTL), indicator cache (1hr TTL)
- SQLite → audit trail, signals, orders, approvals, portfolio snapshots
- .env → all secrets, loaded by both processes via python-dotenv

## Tech Stack
Python 3.11, FastAPI, Uvicorn, APScheduler, SQLAlchemy, SQLite, Redis,
kiteconnect, anthropic, python-telegram-bot, pandas-ta, yfinance,
newsapi-python, httpx, python-dotenv, pytest

## Folder Structure
portfolio-agent/
├── webhook_server.py       ← Entry point A
├── scheduler.py            ← Entry point B
├── config.py               ← All settings and risk rules
├── .env                    ← Secrets (never commit)
├── .env.example            ← Key names with empty values
├── requirements.txt
├── CLAUDE.md
├── core/                   ← Shared services (used by both processes)
│   ├── kite_client.py      ← Kite auth, holdings, orders, WebSocket
│   ├── telegram_bot.py     ← Send messages, format alerts
│   ├── claude_client.py    ← Claude API wrapper
│   ├── approval.py         ← Token gen, validation, expiry
│   ├── redis_client.py     ← Redis get/set/delete wrappers
│   └── db.py               ← SQLAlchemy engine + SessionLocal + Base
├── models/                 ← SQLAlchemy table definitions
│   ├── signal.py
│   ├── order.py
│   ├── approval.py
│   └── portfolio_snap.py
├── data/                   ← Market data pipeline
│   ├── portfolio.py        ← Holdings fetch + context builder
│   ├── technicals.py       ← pandas-ta indicators
│   ├── news.py             ← NewsAPI + sentiment
│   └── screener.py         ← Nifty 200 scanner
├── agent/                  ← Intelligence modules
│   ├── stoploss.py
│   ├── briefing.py
│   ├── signals.py
│   ├── scanner.py
│   └── health.py
├── routes/                 ← FastAPI route handlers
│   ├── kite_routes.py
│   ├── telegram_routes.py
│   └── approval_routes.py
├── mocks/                  ← Local dev mock data
│   ├── kite_mock.py
│   └── news_mock.py
├── tests/                  ← pytest test files
│   └── test_skeleton.py
├── logs/                   ← Rotating log files (gitignored)
├── data_store/             ← SQLite db file (gitignored)
└── deploy/                 ← EC2 deployment scripts
    ├── setup.sh
    ├── portfolio-webhook.service
    └── portfolio-scheduler.service

## Dev Rules — READ EVERY SESSION
- USE_MOCK=true in .env during local dev — never call real Kite API locally
- All secrets in .env only — never hardcode any key or token
- Every function needs a docstring and type hints
- Both processes share Redis + SQLite — never share state any other way
- Do not mix scheduler logic into webhook_server.py or vice versa
- Processes never call each other directly — communicate via SQLite only
- Always run pytest after creating any new module

## Current Status
Week 0 COMPLETE ✓
- Project skeleton fully built
- Both entry points (webhook_server.py + scheduler.py) running
- All 4 DB models created and tested
- Mock data layer working (8 stocks, news sentiment)
- 11/11 skeleton tests passing

Week 1 COMPLETE ✓ (mock mode)
- KiteClient wrapper built with full mock/live switch
- Holdings fetch, quote, historical data, order placement all working
- Portfolio context builder with SL status and risk flags
- Technical indicators: RSI, MACD, Bollinger, 200DMA computed via pandas-ta
- OAuth route handlers built (/kite/login, /callback, /status)
- 13/13 Week 1 tests passing on mock data

Week 2 COMPLETE ✓
- Telegram bot fully integrated — real messages sending
- All 4 message types working: briefing, signal, SL breach, weekly report
- Approval token engine: generate, validate, approve, skip, expire
- Callback handler wired in telegram_routes.py
- Tested live on phone: briefing, SL alert, signal alert, health report all received
- 37/37 tests passing

Week 3 COMPLETE ✓
- Stop-loss monitor built — checks all 20+ holdings
- Rule-based: no Claude API, pure Python math
- Cooldown system prevents duplicate alerts (30 min)
- ngrok tunnel working — Telegram buttons respond correctly
- Full SL breach simulation tested end-to-end on phone
- Heartbeat job added (7AM daily)
- Token cleanup job added (midnight daily)
- 63/63 tests passing (11 week0 + 13 week1 + 13 week2 + 16 stoploss unit + 11 week3)

Week 4 COMPLETE ✓
- data/technicals.py: IndicatorResult dataclass, fetch_ohlc, compute_indicators (pandas-ta), get_technicals_for_holdings
- RSI-14, MACD 12/26/9, Bollinger Bands 20, SMA 50/200, volume ratio, 52w high/low computed for all holdings
- data/news.py: get_news_sentiment with keyword-based scoring, mock+live mode, Redis cache (2h TTL)
- Redis cache (1h TTL) for indicators, cache-aside pattern with graceful Redis fallback
- 10/10 Week 4 tests passing
Next: Week 5 — Agent briefing (agent/briefing.py)

## Indian Market Context
- Market hours: 09:15 to 15:30 IST, Monday to Friday
- Exchange: NSE
- Broker: Zerodha Kite Connect API
- Portfolio: 20+ delivery (CNC) equity holdings
- All orders: CNC product type (delivery, not intraday)
- Stop loss default: -15% from entry price
- Max single position: 20% of portfolio value
- Signal confidence threshold: 0.75 (75%)