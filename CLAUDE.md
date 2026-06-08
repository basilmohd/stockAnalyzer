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

Week 5 COMPLETE ✓
- core/claude_client.py: call_claude_briefing wraps Anthropic API, _build_prompt, _parse_briefing_response
- core/openai_client.py: call_openai_briefing wraps OpenAI GPT-4, reuses prompt/parser from claude_client
- agent/briefing.py: generate_briefing (provider dispatch), run_briefing (format + send to Telegram)
- scheduler.py: briefing_job wired at 08:30 IST Mon-Fri
- webhook_server.py: POST /briefing/trigger for on-demand briefing without waiting for cron
- AI_PROVIDER=claude/openai in .env, USE_MOCK_AI=true for tests
- 92/93 tests passing (1 integration test skipped — placeholder ANTHROPIC_API_KEY in .env)

Week 6 COMPLETE ✓
- agent/signals.py: full signal pipeline — scan holdings → filter by confidence threshold → store to SQLite → send Telegram alert with EXECUTE/SKIP buttons
- core/claude_client.py: generate_signals() added — Claude analyzes technicals + news and returns structured signal list
- core/kite_client.py: place_order() added with mock + live mode (CNC product type, NSE exchange)
- routes/approval_routes.py: handle_signal_execution() wired — on approval, places order via Kite
- routes/telegram_routes.py: EXECUTE/SKIP callback handlers for signal action buttons
- scheduler.py: signal_job wired at 11:00 AM and 2:00 PM IST Mon-Fri
- webhook_server.py: POST /signals/trigger (on-demand) and GET /signals/latest endpoints added
- tests/test_week6.py: 13 new tests covering signal generation, order placement, and approval flow
- 83/83 tests passing

Week 7 COMPLETE ✓ — MVP1 DONE
- core/exception_handler.py: safe_run() wraps all jobs — catches exceptions, logs full traceback, sends Telegram ⚠️ alert (non-blocking), returns None
- core/heartbeat.py: send_heartbeat() collects Redis/DB status, last SL check, last briefing timestamp → sends formatted daily status to Telegram
- core/logger.py: get_logger(__name__) factory — midnight-rotating file handler (7-day retention) + stream handler; used in all agent + core modules
- config.py: LOG_LEVEL, LOG_ROTATION, LOG_BACKUP_COUNT added
- scheduler.py: final 10-job table (heartbeat daily, briefing/signals/opportunity Mon-Fri, health Sunday, sl+technicals+news interval, token cleanup midnight); ALL wrapped in safe_run()
- webhook_server.py: POST /scanner/trigger, POST /health/trigger, GET /health/latest debug endpoints added
- agent/health.py: data.technicals import made lazy to avoid top-level pandas_ta load at import time
- All 8 modules updated to use get_logger(__name__): agent/stoploss, briefing, signals, scanner, health; core/claude_client, kite_client
- tests/test_week7.py: 13 new tests — screener filters, opportunity scan, health score, safe_run
- 118/119 tests passing (1 skipped — placeholder ANTHROPIC_API_KEY integration test)

Week 8 COMPLETE ✓
- agent/strategy.py: classify_strategy (MEAN_REVERSION/SWING_TRADE/TREND_FOLLOW/EXIT_SIGNAL/NO_TRADE) + validate_entry rules; SECTOR_MAP, NIFTY50_SYMBOLS
- models/action_log.py: ActionLog audit model (strategy_type, suggested_sl/target, action_taken, rejection_reason, response_time_sec)
- agent/signals.py: pipeline classifies + validates each signal → AUTO_REJECTED / PENDING ActionLog; signals carry strategy_type, suggested_sl, suggested_target
- tests/test_week8.py: 10 tests — classifier, validator, ActionLog DB writes

Week 9 COMPLETE ✓
- core/exception_handler.py: safe_run hardened — logger.exception full traceback + root logs/errors.log handler (WARNING+ from ALL loggers); Telegram alert carries exc type + first 200 chars; "[job] completed OK" on success
- config.py: TOTAL_CAPITAL, MAX_RISK_PER_TRADE, MAX_POSITION_PCT (0.25), CASH_RESERVE_PCT (0.20), MAX_OPEN_POSITIONS, MAX_SAME_SECTOR, WEEKLY_LOSS_LIMIT, MIN_ORDER_VALUE; MAX_HOLDING_WEIGHT_PCT (percent-scale reporting, separate from the sizing cap)
- agent/sizing.py: calculate_position (risk-based qty, 25% cap, min-order guard) + get_available_capital (cash reserve); reads config.* at call time
- agent/portfolio_guard.py: check_guards (6 ordered hard limits) + get_open_positions_summary (APPROVED-ActionLog proxy; TODO Trade table Wk10)
- agent/signals.py: pipeline sizes + guards each entry; guard-blocked → AUTO_REJECTED (no Telegram); PENDING written only after send confirmed, else SEND_FAILED; 💰 Position block added to Telegram alert
- agent/journal.py: update_action_log(signal_id_or_token, action_taken) flips PENDING ActionLog → APPROVED/SKIPPED/EXPIRED with response_time_sec; wired into approval + telegram routes and token expiry
- webhook_server.py: GET /sizing/preview, GET /guard/status debug endpoints
- tests/test_week9.py: 13 tests (10 spec + 3 regression extras); full suite 185 passed / 2 skipped

Week 10 COMPLETE ✓ — Trade ledger + paper trading + exit monitor
- config.py: PAPER_TRADE_MODE (default true; checked BEFORE every real-order path so live is unreachable in paper mode); TIME_STOP_BY_STRATEGY (SWING 10 / TREND 30 / MEAN_REVERSION 15); .env.example updated
- webhook_server.py + scheduler.py: startup banner prints "⚠️ PAPER TRADE MODE ACTIVE" / "🔴 LIVE TRADING MODE" on every boot
- models/trade.py: Trade ledger ORM (entry/exit/pnl/time_stop/is_paper/links), indexed on status+symbol+entry_date; registered in core/db.py; action_logs.trade_id safety migration added
- core/kite_client.py: place_order paper-aware — PAPER_TRADE_MODE branch FIRST, "fills" at live quote, returns PAPER-{symbol}-{ts} + fill_price + is_paper; real broker never reached in paper mode
- agent/journal.py: open_trade (links ActionLog.trade_id), close_trade (realized pnl/pnl_pct), get_open_trades, get_closed_trades(since), get_trade, get_open_positions_summary (REAL Trade reads, mark-to-market value + realized week_pnl) — replaces Week 9 proxy
- agent/sizing.py + agent/portfolio_guard.py: rewired to real Trade table (get_open_positions_summary / get_available_capital read OPEN trades at current price); _open_positions_proxy removed
- routes/approval_routes.py: APPROVE path opens a real Trade on BUY (✅ Trade Opened (PAPER)), records EXECUTION_FAILED on order failure
- agent/exit_monitor.py: check_exit_conditions (STOPLOSS → TARGET → TIME_STOP, 30-min Redis cooldown per trade), format_exit_telegram, execute_exit (paper-aware SELL → close_trade → ✅ Position Closed), handle_exit_hold (2h cooldown); run_with_market_check gate
- scheduler.py: exit_monitor job every 5 min (market-hours gated); routes/telegram_routes.py: exit_sell / exit_hold callbacks wired
- webhook_server.py: GET /trades/open, GET /trades/closed, GET /trades/summary, POST /exit/check debug endpoints
- tests/test_week10.py: 11 tests (isolated temp SQLite, PAPER_TRADE_MODE forced); test_week1 + test_week6 mock-order tests now pin PAPER_TRADE_MODE=False; full suite 196 passed / 2 skipped

Week 11 COMPLETE ✓ — Performance analytics + weekly report + paper-trade dashboard
- agent/analytics.py: compute_performance_stats(since) — win_rate, expectancy, avg win/loss, total_pnl, best/worst trade, avg_hold_days; by_strategy (SWING/MEAN_REVERSION/TREND_FOLLOW), by_exit_reason (TARGET/STOPLOSS/TIME_STOP/MANUAL), weekly_pnl (last 8 ISO weeks newest-first), open_positions (mark-to-market via Redis quote:{symbol}, falls back to entry), capital block; empty-but-valued dict when no closed trades
- CONVENTION: every ratio is a FRACTION (win_rate, avg_win_pct, avg_loss_pct, expectancy, avg_pnl_pct, total_return_pct, best/worst pnl_pct) matching Trade.pnl_pct as stored; Telegram renders with percent format specifiers (0.024 → "+2.40%")
- agent/analytics.py: format_weekly_report (rich HTML — This Week / All-Time / Best Strategy / Exit Breakdown / Open Positions / best+worst; PAPER watermark; ⚠️ negative-expectancy "do not go live" warning; ✅ positive-edge nudge when expectancy>0 & win_rate>0.55 & trades≥10; no-trades placeholder), send_weekly_report (sends Telegram + caches stats to Redis analytics:latest, 7-day TTL)
- agent/analytics.py: get_best_strategy (highest expectancy, min 3 trades/strategy, else None), should_go_live (5 conditions: ≥20 trades, win_rate≥0.55, expectancy>0, ≥4 weeks, max weekly drawdown <10% of capital → ready/conditions/missing/message)
- scheduler.py: weekly_analytics_job → send_weekly_report at Sunday 09:00 IST (safe_run wrapped, 2h misfire grace)
- webhook_server.py: GET /performance (full, ?since=YYYY-MM-DD), GET /performance/summary, GET /performance/strategy, GET /performance/go-live, POST /performance/report (sends report + returns stats)
- tests/test_week11.py: 12 tests (isolated temp SQLite, PAPER_TRADE_MODE forced; make_trade helper inserts closed trades; should_go_live tests monkeypatch compute_performance_stats); full suite 208 passed / 2 skipped

## Indian Market Context
- Market hours: 09:15 to 15:30 IST, Monday to Friday
- Exchange: NSE
- Broker: Zerodha Kite Connect API
- Portfolio: 20+ delivery (CNC) equity holdings
- All orders: CNC product type (delivery, not intraday)
- Stop loss default: -15% from entry price
- Max single position: 20% of portfolio value
- Signal confidence threshold: 0.75 (75%)