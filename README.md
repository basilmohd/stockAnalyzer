# Portfolio Agent — AI Stock Management System

## What This Is

An automated AI-driven portfolio management system for Indian equity (NSE) stocks. It monitors 20+ Zerodha holdings, generates AI-powered trade signals, fires stop-loss alerts, and delivers a morning briefing — all through Telegram. Every trade action requires explicit human approval before execution.

**Built by:** Basil Mohd Sufyan  
**Market:** NSE (India), CNC delivery orders only  
**Broker:** Zerodha Kite Connect  
**AI:** Anthropic Claude (primary) / OpenAI GPT-4 (fallback)  
**Deployed on:** AWS EC2 t3.small, Mumbai region

---

## Architecture: Two Independent Processes

The system is split into two long-running processes that share state only through Redis and SQLite. They never import from each other or call each other over HTTP.

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
            (shared state only)
                     │
  ┌──────────────────┴──────────────────────┐
  │             scheduler.py                 │  APScheduler + AsyncIO
  │  Briefing · Signals · SL Monitor ·       │
  │  Scanner · Health · Heartbeat            │
  └─────────────────────────────────────────┘
          │
          ▼
  System clock (IST)
```

**webhook_server.py** — reacts to inbound HTTP events (human taps, OAuth redirects).  
**scheduler.py** — fires all timed jobs on IST cron/interval schedules.

---

## Scheduled Jobs

All jobs are wrapped in `safe_run()` which catches exceptions, logs the traceback, and sends a non-blocking Telegram warning alert. Jobs that require market hours skip automatically outside 09:15–15:30 IST Mon–Fri.

| # | Job Name | Schedule | What It Does |
|---|----------|----------|--------------|
| 1 | `heartbeat_job` | **Daily 07:00 IST** | Sends a system status ping to Telegram: Redis/DB connectivity, last SL check timestamp, last briefing timestamp. Confirms both processes are alive. |
| 2 | `morning_briefing_job` | **Mon–Fri 08:30 IST** | Fetches portfolio holdings, computes technicals, pulls overnight news, then calls Claude (or OpenAI) to generate a structured briefing. Sends headline + alerts + watchlist + action items to Telegram. |
| 3 | `opportunity_scan_job` | **Mon–Fri 10:00 IST** | Scans the Nifty 200 universe for stocks entering buy zones (RSI oversold, volume spike, near support). Excludes existing holdings. Sends up to 2 watch alerts to Telegram. |
| 4 | `signal_scan_morning_job` | **Mon–Fri 11:00 IST** | Runs the full AI signal pipeline: fetches holdings + technicals + news → calls Claude → filters by confidence ≥ 0.75 → stores to SQLite → sends Telegram alerts with EXECUTE/SKIP buttons for each actionable signal. |
| 5 | `signal_scan_afternoon_job` | **Mon–Fri 14:00 IST** | Same full signal pipeline as 11 AM. Catches signals that develop during mid-session. |
| 6 | `weekly_health_job` | **Sunday 09:00 IST** | Computes a 4-dimension portfolio health score (0–100): diversification, momentum, risk, quality. Sends full breakdown to Telegram and saves a snapshot to SQLite. |
| 7 | `sl_monitor_job` | **Every 5 min** (market hours only) | Checks every holding against its stop-loss threshold (default −15%). Sends urgent EXIT approval alert on breach, warning alert when within 3% of threshold. 30-minute cooldown per symbol prevents duplicate alerts. |
| 8 | `refresh_technicals_job` | **Every 60 min** (market hours only) | Recomputes RSI-14, MACD 12/26/9, Bollinger Bands 20, SMA 50/200, and volume ratio for all holdings via pandas-ta. Writes results to Redis cache (1h TTL). |
| 9 | `refresh_news_job` | **Every 120 min** (market hours only) | Fetches last-24h headlines from NewsAPI for each holding symbol. Scores sentiment via keyword matching (bullish/bearish). Caches to Redis (2h TTL). |
| 10 | `token_cleanup_job` | **Daily 00:00 IST** | Marks all PENDING approval tokens older than their expiry time as EXPIRED in SQLite. Prevents stale approvals from being honoured. |

---

## API Routes (webhook_server.py)

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/` | Service identity probe |
| `GET` | `/health` | EC2 liveness check for load balancer |
| `GET` | `/technicals/{symbol}` | Return cached technical indicators for a symbol |
| `GET` | `/news/{symbol}` | Return cached news sentiment for a symbol |
| `POST` | `/briefing/trigger` | On-demand morning briefing (without waiting for 08:30) |
| `POST` | `/signals/trigger` | On-demand signal scan |
| `GET` | `/signals/latest` | Return cached result of last signal pipeline run |
| `POST` | `/scanner/trigger` | On-demand Nifty 200 opportunity scan |
| `POST` | `/health/trigger` | On-demand weekly health report |
| `GET` | `/health/latest` | Return latest portfolio health snapshot from SQLite |
| `GET` | `/kite/login` | Redirect to Zerodha OAuth login URL |
| `GET` | `/kite/callback` | Receive Kite OAuth redirect and exchange request token |
| `GET` | `/kite/status` | Show auth status and access token TTL from Redis |
| `POST` | `/telegram/webhook` | Receive Telegram inline button callbacks |
| `POST` | `/approve/{token}` | HTTP fallback to approve a signal (non-Telegram) |
| `POST` | `/approve/{token}/skip` | HTTP fallback to skip a signal |

---

## External System Integrations

Functions are grouped by the external system they talk to. Each function is listed with its file location, signature, and purpose.

---

### Zerodha Kite Connect API (`core/kite_client.py`)

Wraps the `kiteconnect` SDK. In local dev (`USE_MOCK=true`) every function returns realistic mock data without hitting the real API.

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_login_url` | `() → str` | Returns the Zerodha OAuth URL the user must open to authorize the app. |
| `generate_session` | `(request_token: str) → dict` | Exchanges the OAuth `request_token` for a live `access_token`. Stores it in Redis with a 24h TTL. Returns user profile dict. |
| `is_authenticated` | `() → bool` | Returns `True` if a valid access token exists in Redis (or mock mode is active). Used as a guard before any API call. |
| `get_holdings` | `() → list[dict]` | Fetches the full portfolio from Kite. Returns normalised list with `pnl`, `pnl_pct`, `current_value`, and `weight` fields added. |
| `get_quote` | `(symbols: list[str]) → dict` | Returns OHLCV quote data keyed by `"NSE:SYMBOL"`. Used by the SL monitor for live price checks. |
| `get_historical_data` | `(instrument_token: int, from_date: str, to_date: str, interval: str) → list[dict]` | Returns OHLCV candles for the given date range (up to 200 days). Used by `data/technicals.py` to compute indicators. |
| `place_order` | `(symbol: str, action: str, quantity: int) → dict` | Places a CNC MARKET order on NSE. `action` is `BUY`, `SELL`, `REDUCE` (50% of holdings), or `EXIT` (full position). Never raises — returns an error dict on failure. |

---

### Telegram Bot API (`core/telegram_bot.py`)

Uses the `python-telegram-bot` SDK. All functions are async. Sends to the chat ID configured in `.env`.

| Function | Signature | Description |
|----------|-----------|-------------|
| `set_webhook` | `(public_url: str) → bool` | Registers `{public_url}/telegram/webhook` as the Telegram webhook URL. Called at startup or when the EC2 IP changes. |
| `delete_webhook` | `() → bool` | Removes the registered webhook, reverting Telegram to polling mode. |
| `get_webhook_info` | `() → dict` | Returns current webhook registration details from Telegram (URL, pending updates, error info). |
| `send_message` | `(text: str, parse_mode: str) → bool` | Sends a plain HTML/Markdown text message to the configured chat. |
| `send_alert` | `(title: str, body: str, alert_type: str) → bool` | Sends a formatted alert. `alert_type` controls the icon and colour: `INFO`, `BUY`, `SELL`, `URGENT`, `SUCCESS`, `WARNING`. |
| `send_approval_request` | `(token: str, title: str, body: str, approve_label, skip_label, expiry_mins) → bool` | Sends an inline keyboard message with APPROVE and SKIP buttons. The `token` is embedded in each button's `callback_data`. |
| `send_signal_alert` | `(symbol, action, confidence, reasoning, entry_price, target_price, stop_loss, suggested_qty, token, indicators) → bool` | Sends a full trade signal card: confidence bar, RSI/MACD summary, price levels, suggested quantity, and EXECUTE/SKIP inline buttons. |
| `send_sl_breach_alert` | `(symbol, entry_price, current_price, pnl_pct, quantity, token) → bool` | Sends an urgent stop-loss breach notification with the loss percentage and an EXIT button. |
| `send_weekly_health_report` | `(score, breakdown, portfolio_summary, recommendations) → bool` | Sends the weekly 4-dimension health score with per-dimension grades and top recommendations. |

---

### Claude Anthropic API (`core/claude_client.py`)

Wraps `anthropic` SDK. Uses `claude-sonnet-4-6` model. Returns `{}` or `[]` on failure — never raises to callers.

| Function | Signature | Description |
|----------|-----------|-------------|
| `call_claude_briefing` | `(portfolio_context: dict, technicals: dict, news: dict) → dict` | Sends a structured prompt with the full portfolio state, technical indicators, and overnight news. Returns a dict with keys: `headline`, `alerts`, `watchlist`, `action_items`. |
| `generate_signals` | `(holdings: list[dict]) → list[dict]` | Sends each holding's price data, technicals, and news sentiment to Claude and asks it to recommend BUY/SELL/REDUCE/EXIT/HOLD with a confidence score (0–1) and reasoning. Returns list of signal dicts. |

---

### OpenAI GPT-4 API (`core/openai_client.py`)

Alternative AI provider. Reuses the same prompt builder and response parser as `claude_client.py`. Activated by setting `AI_PROVIDER=openai` in `.env`.

| Function | Signature | Description |
|----------|-----------|-------------|
| `call_openai_briefing` | `(portfolio_context: dict, technicals: dict, news: dict) → dict` | Same contract as `call_claude_briefing`. Calls GPT-4 via the OpenAI SDK and returns the same `headline/alerts/watchlist/action_items` structure. |

---

### NewsAPI (`data/news.py`)

Fetches stock-related headlines. Cached in Redis for 2 hours to avoid rate limits.

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_news_sentiment` | `(symbol: str) → dict` | Returns headline list and a 0–1 sentiment score for the given symbol. Checks Redis cache first (2h TTL); falls back to a live NewsAPI call. |
| `fetch_news_for_symbol` | `(symbol: str) → list[dict]` | Calls NewsAPI `everything` endpoint with query `"{symbol} NSE OR BSE"`, filtered to last 24 hours. Returns raw article list. |
| `compute_sentiment_score` | `(articles: list[dict]) → dict` | Scores articles using a keyword list (e.g. "growth", "profit" → bullish; "loss", "fraud" → bearish). Returns `{score: float, bullish: int, bearish: int, neutral: int}`. |
| `get_news_sentiment_all_holdings` | `() → dict[str, dict]` | Calls `get_news_sentiment` for every holding in the portfolio. Returns dict keyed by symbol. |

---

## Data Flow: Trade Signal Lifecycle

```
scheduler.py @ 11:00 AM IST
 │
 ├─ build_claude_context()           # portfolio summary + per-holding data
 ├─ get_technicals_for_holdings()    # RSI, MACD, Bollinger from Redis cache
 ├─ get_news_sentiment_all_holdings()# bullish/bearish scores from Redis cache
 │
 ├─ generate_signals(holdings)       # → Claude API → signal list
 │
 ├─ filter_signals()                 # drop HOLD, drop confidence < 0.75, dedupe
 │
 └─ send_signal_alerts()
     ├─ store_signals() → SQLite
     ├─ generate_token() → SQLite (PENDING, expires 30 min)
     └─ send_signal_alert() → Telegram
           [✅ EXECUTE] [⏭ SKIP]
                │
                ▼ (user taps EXECUTE)
         Telegram → POST /telegram/webhook
                │
         telegram_routes.py
         ├─ validate_token() → PENDING + not expired
         ├─ handle_signal_execution()
         │   ├─ fetch Signal from SQLite
         │   ├─ place_order() → Kite API
         │   ├─ store Order → SQLite
         │   └─ send_alert(SUCCESS) → Telegram
         └─ mark_approved() → APPROVED in SQLite
```

---

## Shared State

| Store | Key | TTL | Written by | Read by |
|-------|-----|-----|------------|---------|
| Redis | `kite:access_token` | 24 h | `kite_client.generate_session` | all Kite calls |
| Redis | `indicators:{symbol}` | 1 h | `refresh_technicals_job` | signal pipeline, briefing |
| Redis | `news:{symbol}` | 2 h | `refresh_news_job` | signal pipeline, briefing |
| Redis | `signals:last_run` | 2 h | `run_signal_pipeline` | `/signals/latest` route |
| Redis | `scanner:opportunities` | 6 h | `send_opportunity_alerts` | `/scanner/trigger` route |
| Redis | `sl:alerted:{symbol}` | 30 min | `run_sl_monitor` | `is_on_cooldown` |
| Redis | `briefing:latest` | — | `run_briefing` | heartbeat |
| Redis | `sl_monitor:last_run` | — | `run_sl_monitor` | heartbeat |
| SQLite | `signals` | permanent | `store_signals` | approval routes |
| SQLite | `orders` | permanent | `handle_signal_execution` | audit |
| SQLite | `approvals` | permanent | `generate_token` | `validate_token`, `token_cleanup_job` |
| SQLite | `portfolio_snapshots` | permanent | `send_weekly_health_report` | `/health/latest` |

---

## Risk Rules (config.py)

| Rule | Value | Description |
|------|-------|-------------|
| `DEFAULT_SL_PCT` | −15% | Stop-loss threshold from entry price |
| `CONFIDENCE_THRESHOLD` | 0.75 | Minimum AI confidence to send a signal alert |
| `MAX_POSITION_PCT` | 20% | No single stock may exceed 20% of portfolio |
| `CASH_RESERVE_PCT` | 10% | Always maintain 10% cash |
| `APPROVAL_EXPIRY_MINS` | 30 min | Signal approval token expires after 30 minutes |
| `SL_APPROVAL_EXPIRY_MINS` | 15 min | SL breach approval token expires after 15 minutes |
| `SL_COOLDOWN_MINS` | 30 min | No repeat SL alert for the same stock within 30 minutes |
| `MAX_OPPORTUNITIES_PER_DAY` | 2 | Scanner sends at most 2 watch alerts per day |

---

## Deployment

Both processes run as **systemd services** on AWS EC2 t3.small (ap-south-1, Mumbai):

```bash
# Webhook server
systemctl start portfolio-webhook    # uvicorn webhook_server:app --host 0.0.0.0 --port 8000

# Scheduler
systemctl start portfolio-scheduler  # python scheduler.py
```

EC2 security group exposes only port 8000 to Telegram's webhook IP ranges and to the Kite OAuth redirect URL. Both services auto-restart on failure via `Restart=always`.

---

## Local Development

```bash
# .env must have:
USE_MOCK=true          # Never call real Kite API locally
USE_MOCK_AI=true       # Use mock signals (skip real Claude/OpenAI calls)
AI_PROVIDER=claude     # or openai

# Run both processes:
uvicorn webhook_server:app --reload --port 8000
python scheduler.py

# Run tests:
pytest tests/ -v       # 118/119 passing (1 skipped — real API integration test)
```

Mock data lives in `mocks/kite_mock.py` (8 holdings) and `mocks/news_mock.py`. The mock/live switch is a single `USE_MOCK` env flag — all modules check it at call time, not import time.
