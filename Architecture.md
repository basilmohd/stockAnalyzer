# Portfolio Agent — Architecture & Flow

## Overview

The system is split into **two independent processes** that run side-by-side on the same EC2 instance. They never call each other directly. All shared state flows through Redis (live cache) and SQLite (audit trail).

```
                        ┌─────────────────────────────────┐
  Telegram / Browser    │         webhook_server.py        │  Port 8000 (FastAPI)
  ──────────────────►   │  OAuth · Callbacks · Approvals   │
                        └────────────┬────────────────────┘
                                     │
                              Redis + SQLite
                                     │
                        ┌────────────┴────────────────────┐
  System clock (IST)    │           scheduler.py           │  Background process
  ──────────────────►   │  Briefing · Signals · SL Monitor │
                        └─────────────────────────────────┘
```

---

## Process A — `webhook_server.py` (FastAPI + Uvicorn)

**What it is:** An HTTP server that listens for inbound events from external systems.

**What triggers it:** A human action — tapping a Telegram button, completing Kite OAuth login, or approving/rejecting a trade signal.

**What it does:**

| Route prefix | Responsibility |
|---|---|
| `GET /health` | Liveness probe for EC2 / load balancer |
| `/kite/*` | Receives the OAuth redirect from Zerodha after login; exchanges the request token for an access token and stores it in Redis |
| `/telegram/*` | Receives Telegram button-tap callbacks (inline keyboard); routes user decisions (approve / reject trade) to the approval logic |
| `/approve/*` | Token-based approval endpoints; validates one-time tokens and records decisions in SQLite |

**Startup sequence:**
1. Connect to Redis
2. Run `init_db()` to create SQLite tables if missing
3. Mount route handlers
4. Uvicorn begins accepting connections on port 8000

**Key constraint:** No scheduled or timed logic lives here. It only reacts.

---

## Process B — `scheduler.py` (APScheduler + AsyncIO)

**What it is:** A long-running background process that drives all timed market intelligence jobs.

**What triggers it:** The system clock — cron expressions and intervals evaluated against IST (Asia/Kolkata).

**What it does:**

| Job | Schedule | Purpose |
|---|---|---|
| `briefing_job` | Mon–Fri 8:30 AM IST | Morning portfolio overview + overnight news digest sent to Telegram |
| `signal_job_am` | Mon–Fri 11:00 AM IST | Mid-morning technical + news signal scan |
| `scanner_job` | Mon–Fri 12:30 PM IST | Nifty 200 opportunity scanner — finds new entry candidates |
| `signal_job_pm` | Mon–Fri 2:00 PM IST | Afternoon signal refresh |
| `post_market_job` | Mon–Fri 4:00 PM IST | Post-market summary + portfolio snapshot saved to SQLite |
| `health_job` | Sunday 7:00 PM IST | Weekly system health report |
| `stoploss_job` | Every 5 min | Live stop-loss monitor — skips automatically outside market hours (09:15–15:30) |

**Startup sequence:**
1. Connect to Redis
2. Run `init_db()` to create SQLite tables if missing
3. Check for a valid Kite access token in Redis (warns if missing)
4. Register all cron and interval jobs
5. `asyncio` event loop runs forever

**Key constraint:** No HTTP server, no inbound ports. It only acts on time.

---

## Shared State Layer

| Store | What lives there | TTL |
|---|---|---|
| Redis | Live price cache | 60 s |
| Redis | Kite access token | 24 hr |
| Redis | Indicator cache | 1 hr |
| SQLite | Signals, orders, approvals | permanent |
| SQLite | Portfolio snapshots | permanent |
| SQLite | Audit trail | permanent |

Both processes read and write to the same Redis instance and the same SQLite file. This is the **only** way they communicate — no sockets, no queues, no direct imports between them.

---

## Request Flow — Trade Signal Approval

```
scheduler.py
  └─ signal_job_am runs at 11:00 AM
       └─ Claude API analyzes portfolio + news + technicals
            └─ Confidence ≥ 0.75 → generates approval token → writes to SQLite
                 └─ Sends Telegram message with Approve / Reject buttons

User taps "Approve" on Telegram
  └─ Telegram sends callback to webhook_server.py /telegram/*
       └─ Token validated → order written to SQLite → Kite API called
            └─ Confirmation sent back to Telegram
```

---

## Deployment

Both processes run as **systemd services** on AWS EC2 t3.small (Mumbai region):

- `portfolio-webhook.service` → runs `uvicorn webhook_server:app`
- `portfolio-scheduler.service` → runs `python scheduler.py`

EC2 security group exposes only port 8000 to Telegram's webhook IP ranges and to the Kite OAuth redirect URL.
