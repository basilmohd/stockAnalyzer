# Portfolio Agent — Architecture & Flow

## Overview

The system is split into **two independent processes** that run side-by-side on the same EC2 instance. They never call each other directly. All shared state flows through Redis (live cache) and SQLite (audit trail).

```
  Telegram / Browser / Kite OAuth
          │
          ▼
  ┌─────────────────────────────────────────┐
  │          webhook_server.py               │  FastAPI + Uvicorn  :8000
  │  Kite OAuth · Telegram callbacks ·       │
  │  Signal approvals · On-demand triggers   │
  └──────────────────┬──────────────────────┘
                     │
              Redis + SQLite
            (only shared channel)
                     │
  ┌──────────────────┴──────────────────────┐
  │             scheduler.py                 │  APScheduler + AsyncIO
  │  Briefing · Signals · SL Monitor ·       │
  │  Scanner · Health · Heartbeat            │
  └─────────────────────────────────────────┘
          │
          ▼
  System clock (Asia/Kolkata IST)
```

---

## Process A — `webhook_server.py` (FastAPI + Uvicorn)

**What it is:** An HTTP server that listens for inbound events from external systems.

**What triggers it:** A human action — tapping a Telegram button, completing Kite OAuth login, or calling an on-demand trigger endpoint.

**Route handlers:**

| Route prefix | File | Responsibility |
|---|---|---|
| `GET /health` | `webhook_server.py` | Liveness probe for EC2 / load balancer |
| `/kite/*` | `routes/kite_routes.py` | Receives Zerodha OAuth redirect; exchanges request token for access token; stores in Redis 24h |
| `/telegram/*` | `routes/telegram_routes.py` | Receives Telegram button-tap callbacks; routes EXECUTE/SKIP decisions to the approval/order logic |
| `/approve/*` | `routes/approval_routes.py` | HTTP fallback approval endpoints for non-Telegram clients |
| `/briefing/trigger` | `webhook_server.py` | On-demand morning briefing |
| `/signals/trigger` | `webhook_server.py` | On-demand signal scan |
| `/signals/latest` | `webhook_server.py` | Returns cached last signal run result |
| `/scanner/trigger` | `webhook_server.py` | On-demand Nifty 200 opportunity scan |
| `/health/trigger` | `webhook_server.py` | On-demand weekly health report |
| `/health/latest` | `webhook_server.py` | Returns latest health snapshot from SQLite |

**Startup sequence:**
1. Load `.env` via `python-dotenv`
2. Connect to Redis
3. Run `init_db()` — creates SQLite tables if missing
4. Mount route handlers (kite, telegram, approval prefixes)
5. Uvicorn begins accepting connections on port 8000

**Key constraint:** No scheduled or timed logic lives here. It only reacts to inbound HTTP.

---

## Process B — `scheduler.py` (APScheduler + AsyncIOScheduler)

**What it is:** A long-running background process that drives all timed market intelligence jobs.

**What triggers it:** The system clock — cron expressions and intervals evaluated in `Asia/Kolkata` timezone.

**All 10 registered jobs:**

| # | Job name | Schedule | Description |
|---|----------|----------|-------------|
| 1 | `heartbeat_job` | Daily 07:00 IST | System liveness ping — Redis/DB status, last SL check, last briefing sent to Telegram |
| 2 | `morning_briefing_job` | Mon–Fri 08:30 IST | Portfolio overview + AI analysis (Claude or OpenAI) → formatted briefing to Telegram |
| 3 | `opportunity_scan_job` | Mon–Fri 10:00 IST | Nifty 200 scanner — stocks entering buy zones (RSI, volume, support) → up to 2 watch alerts |
| 4 | `signal_scan_morning_job` | Mon–Fri 11:00 IST | Full AI signal pipeline: holdings + technicals + news → Claude → filter → SQLite → Telegram |
| 5 | `signal_scan_afternoon_job` | Mon–Fri 14:00 IST | Afternoon signal refresh — same pipeline as 11 AM |
| 6 | `weekly_health_job` | Sunday 09:00 IST | 4-dimension health score (diversification, momentum, risk, quality) → Telegram + SQLite snapshot |
| 7 | `sl_monitor_job` | Every 5 min | Stop-loss monitor — skips outside 09:15–15:30; alerts on breach or within 3% of threshold |
| 8 | `refresh_technicals_job` | Every 60 min | Recompute RSI/MACD/Bollinger/SMA for all holdings → Redis (1h TTL) |
| 9 | `refresh_news_job` | Every 120 min | Refresh NewsAPI sentiment for all holdings → Redis (2h TTL) |
| 10 | `token_cleanup_job` | Daily 00:00 IST | Expire stale PENDING approval tokens in SQLite |

**Error handling:** Every job is wrapped in `safe_run()` (`core/exception_handler.py`). On any unhandled exception, `safe_run` logs the full traceback and sends a non-blocking ⚠️ Telegram alert. The scheduler never stops.

**Startup sequence:**
1. Load `.env` via `python-dotenv`
2. Connect to Redis
3. Run `init_db()` — creates SQLite tables if missing
4. Warn if no valid Kite access token is cached in Redis
5. Register all 10 jobs on `AsyncIOScheduler`
6. `asyncio` event loop runs forever

**Key constraint:** No HTTP server, no inbound ports. It only acts on time.

---

## Module Responsibilities

```
portfolio-agent/
├── webhook_server.py          Entry point A — FastAPI server
├── scheduler.py               Entry point B — APScheduler process
├── config.py                  All settings, env vars, risk rules
│
├── core/                      Shared services (used by both processes)
│   ├── kite_client.py         Kite Connect SDK wrapper (mock/live switch)
│   ├── telegram_bot.py        All Telegram message types + formatting
│   ├── claude_client.py       Anthropic Claude API wrapper
│   ├── openai_client.py       OpenAI GPT-4 alternative wrapper
│   ├── approval.py            One-time token: generate, validate, approve, expire
│   ├── db.py                  SQLAlchemy engine + SessionLocal + init_db()
│   ├── redis_client.py        Redis get/set/delete helpers
│   ├── heartbeat.py           Daily status report builder
│   ├── exception_handler.py   safe_run() job wrapper
│   └── logger.py              Rotating file logger (7-day retention)
│
├── models/                    SQLAlchemy ORM table definitions
│   ├── signal.py              Generated signals (action, confidence, status)
│   ├── order.py               Executed Kite orders
│   ├── approval.py            Approval tokens with expiry
│   └── portfolio_snap.py      Weekly snapshots with health score
│
├── data/                      Market data pipeline
│   ├── portfolio.py           Holdings fetch, SL enrichment, Claude context builder
│   ├── technicals.py          pandas-ta indicators (RSI, MACD, Bollinger, SMA)
│   ├── news.py                NewsAPI integration + keyword sentiment scoring
│   └── screener.py            Nifty 200 universe + opportunity filters
│
├── agent/                     Intelligence modules
│   ├── briefing.py            Morning briefing: gather data → call AI → send Telegram
│   ├── signals.py             Signal pipeline: scan → filter → store → alert
│   ├── stoploss.py            Rule-based SL monitor (no AI, pure math)
│   ├── scanner.py             Nifty 200 opportunity scanner
│   └── health.py              4-dimension portfolio health scoring
│
├── routes/                    FastAPI route handlers
│   ├── kite_routes.py         OAuth login, callback, status
│   ├── telegram_routes.py     Button callback webhook
│   └── approval_routes.py     HTTP fallback signal approval + order execution
│
└── mocks/                     Local dev mock data
    ├── kite_mock.py           8-stock mock portfolio
    └── news_mock.py           Mock news articles
```

---

## Shared State Layer

Both processes read and write the same Redis instance and the same SQLite file. This is the **only** communication channel between them.

### Redis (live, ephemeral)

| Key | TTL | Written by | Purpose |
|-----|-----|------------|---------|
| `kite:access_token` | 24 h | `generate_session()` | Kite API auth |
| `kite:user_id` | 24 h | `generate_session()` | User identity |
| `indicators:{symbol}` | 1 h | `refresh_technicals_job` | RSI, MACD, Bollinger, SMAs |
| `news:{symbol}` | 2 h | `refresh_news_job` | Sentiment score + headlines |
| `news_articles:{symbol}` | 2 h | `fetch_news_for_symbol()` | Raw article cache |
| `signals:last_run` | 2 h | `run_signal_pipeline()` | Last pipeline result for `/signals/latest` |
| `scanner:opportunities` | 6 h | `send_opportunity_alerts()` | Last scan result |
| `sl:alerted:{symbol}` | 30 min | `run_sl_monitor()` | Cooldown flag — prevents duplicate alerts |
| `briefing:latest` | — | `run_briefing()` | Timestamp for heartbeat display |
| `sl_monitor:last_run` | — | `run_sl_monitor()` | Timestamp for heartbeat display |

### SQLite (persistent, audit trail)

| Table | Written by | Read by |
|-------|------------|---------|
| `signals` | `store_signals()` | `handle_signal_execution()`, approval routes |
| `orders` | `handle_signal_execution()` | Audit / `/health/latest` |
| `approvals` | `generate_token()` | `validate_token()`, `token_cleanup_job` |
| `portfolio_snapshots` | `send_weekly_health_report()` | `/health/latest` |

---

## Request Flow — Trade Signal Approval

```
scheduler.py @ 11:00 AM IST
  └─ signal_scan_morning_job
       └─ run_signal_pipeline()
            ├─ build_claude_context()          → portfolio + risk flags
            ├─ get_technicals_for_holdings()   → RSI/MACD/Bollinger from Redis
            ├─ get_news_sentiment_all_holdings()→ sentiment scores from Redis
            ├─ generate_signals(holdings)      → Claude API → raw signal list
            ├─ filter_signals()                → drop HOLD, confidence < 0.75, dedupe
            └─ send_signal_alerts()
                 ├─ store_signals()            → SQLite (status: PENDING)
                 ├─ generate_token()           → SQLite (PENDING, 30min expiry)
                 └─ send_signal_alert()        → Telegram
                       [✅ EXECUTE] [⏭ SKIP]

User taps [✅ EXECUTE] on Telegram
  └─ Telegram POSTs /telegram/webhook
       └─ telegram_routes.py
            ├─ extract callback_data = "execute:{token}"
            ├─ validate_token(token)           → must be PENDING + not expired
            ├─ handle_signal_execution(token)
            │    ├─ fetch Signal from SQLite
            │    ├─ place_order(symbol, action, qty) → Kite API
            │    ├─ store Order                → SQLite
            │    └─ send_alert(SUCCESS)        → Telegram confirmation
            └─ mark_approved(token)            → APPROVED in SQLite
```

---

## Request Flow — Stop-Loss Breach

```
scheduler.py — every 5 min
  └─ sl_monitor_job
       └─ run_with_market_check()
            ├─ skip if outside 09:15–15:30 IST Mon–Fri
            └─ run_sl_monitor()
                 ├─ get_holdings()             → Kite API (live prices)
                 ├─ for each holding:
                 │    ├─ compute pnl_pct vs entry price
                 │    ├─ if pnl_pct ≤ −15%:   BREACH
                 │    └─ if pnl_pct ≤ −12%:   WARNING
                 ├─ is_on_cooldown(symbol)?    → Redis (30-min key)
                 ├─ generate_token()           → SQLite (15-min expiry)
                 └─ send_sl_breach_alert()     → Telegram
                       [🚨 EXIT NOW] [⏭ SKIP]

User taps [🚨 EXIT NOW]
  └─ same approval flow as signal execution above
```

---

## Deployment

Both processes run as **systemd services** on AWS EC2 t3.small (ap-south-1, Mumbai):

```ini
# /etc/systemd/system/portfolio-webhook.service
ExecStart=uvicorn webhook_server:app --host 0.0.0.0 --port 8000
Restart=always

# /etc/systemd/system/portfolio-scheduler.service
ExecStart=python scheduler.py
Restart=always
```

EC2 security group exposes **only port 8000** to:
- Telegram webhook IP ranges (for button callbacks)
- Kite OAuth redirect URL (for login flow)

Port 22 (SSH) is restricted to the developer's IP only. No other ports are open.

---

## Risk Rules (config.py)

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `DEFAULT_SL_PCT` | −15% | Trigger EXIT alert when P&L drops below this |
| `CONFIDENCE_THRESHOLD` | 0.75 | Only alert signals with ≥ 75% confidence |
| `MAX_POSITION_PCT` | 20% | No single stock exceeds 20% of portfolio |
| `CASH_RESERVE_PCT` | 10% | Maintain 10% cash at all times |
| `APPROVAL_EXPIRY_MINS` | 30 min | Signal approval token lifetime |
| `SL_APPROVAL_EXPIRY_MINS` | 15 min | SL breach approval token lifetime |
| `SL_COOLDOWN_MINS` | 30 min | Minimum gap between repeated SL alerts per symbol |
| `MAX_OPPORTUNITIES_PER_DAY` | 2 | Scanner alert cap |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | AI model used for briefings and signals |
