# Plan: Intraday Trading Assessment + Telegram Stock Query Feature

## Context

Two goals:
1. **Assessment** — understand what gaps exist to evolve the current swing-trading agent into an intraday/short-term trading system. No implementation yet; this is a gap analysis + roadmap.
2. **Telegram Query Feature** — allow the user to send any free-text stock question via Telegram and get an LLM-powered answer back. Any NSE stock supported: portfolio stocks use cached data, non-portfolio stocks fetch on-demand. Single-shot Q&A. Respects `AI_PROVIDER` env var.

---

## Part 1: Intraday Trading — Assessment

### What the current app does well (usable as-is for swing/positional)
- Daily OHLCV indicators: RSI-14, MACD 12/26/9, Bollinger, SMA50/200, volume ratio
- AI signal generation (Claude/OpenAI) at 11 AM and 2 PM — suitable for end-of-day decisions
- CNC (delivery) order execution with human approval gate
- SL monitoring every 5 min with -15% rule
- Portfolio health scoring and weekly reporting

### Gap analysis for intraday/short-term trading

| Gap | Severity | What's needed |
|-----|----------|---------------|
| **No MIS order support** | Critical | `place_order()` only uses `PRODUCT_CNC`. Must add `product_type` param and support `PRODUCT_MIS` (4x intraday leverage) |
| **No intraday indicators** | Critical | `fetch_ohlc()` fetches daily data only. Need 1-min, 5-min, 15-min candles. Need VWAP, intraday RSI/MACD |
| **Slow signal cadence** | Critical | Only 2 scans/day (11 AM, 2 PM). Intraday needs signals every 5-15 min |
| **No real-time streaming** | Critical | Currently polls historical data. Kite WebSocket (`on_ticks()`) needed for live price feed |
| **No limit orders** | High | Only market orders. Intraday needs limit orders with IOC/GTD time-in-force |
| **No broker-side SL** | High | Current SL is rule-based + manual approval. For intraday, need Kite SL-M or bracket orders for automated stop-outs |
| **No forced square-off** | High | MIS positions must be closed before 15:20 IST. No auto-exit logic exists |
| **No margin check** | High | No call to Kite's `margins()` API before placing orders |
| **No intraday profit target** | Medium | `Signal.target_price` field exists but unused. Need target tracking + exit trigger |
| **Human approval latency** | Medium | Approval gate adds 30-60s delay. For intraday, signals can go stale. Need optional auto-execute mode |
| **No tick data capture** | Medium | No storage of intraday candles; everything re-fetched from Kite API each time |
| **No risk-per-trade sizing** | Low | Position sizing is LLM-suggested quantity. Intraday needs ATR-based or % equity sizing |

### Proposed intraday roadmap (future weeks)

**Week 8 — Intraday Data Foundation**
- Add `interval` param to `fetch_ohlc()` (e.g., "5minute", "15minute")
- Add VWAP computation to `compute_indicators()`
- Add intraday indicator dataclass (`IntradayIndicators`)
- Add Kite WebSocket listener (`on_ticks()`) in `core/kite_client.py`

**Week 9 — MIS Order + Short-term Signals**
- Add `product_type` param to `place_order()`: `CNC | MIS`
- Add `order_type` param: `MARKET | LIMIT | SL-M`
- Add margin availability check before MIS order
- Add intraday signal job at 09:30, 10:00, 10:30, 11:00, 12:00, 13:00, 14:00, 14:30, 15:00 IST
- Add forced square-off job at 15:15 IST for all MIS positions

**Week 10 — Bracket Orders + Auto-execute**
- Add bracket order support (entry + SL + target in one call)
- Add `AUTO_EXECUTE` config flag for high-confidence signals (skip human approval for `confidence >= 0.90`)
- Add real-time P&L tracker via WebSocket ticks
- Add intraday trade log and performance reporting

**Week 11 — Risk & Backtesting**
- ATR-based position sizing
- Backtesting module using historical 5-min data
- Daily intraday P&L report to Telegram at 15:35 IST

---

## Part 2: Telegram Stock Query Feature — Implementation

### Design

- User sends any free-text message to Telegram bot
- System parses message for NSE stock symbols (uppercase tokens, 2-12 chars)
- For **portfolio stocks**: use cached Redis data (technicals + news) — fast
- For **non-portfolio stocks detected in query**: fetch technicals + news on-demand (~5-10s)
- If no symbol detected: answer using portfolio-wide context + LLM training knowledge
- LLM answers in plain text (not JSON), conversational tone
- Provider: respects `AI_PROVIDER` env var (claude or openai)
- No conversation history (single-shot per message)

### Files to create/modify

**New file: `agent/query.py`**
- `handle_stock_query(user_query: str) -> str` — orchestrator
  - Detects stock symbols via regex (`[A-Z]{2,12}`) cross-referenced against portfolio holdings
  - Fetches data for detected non-portfolio symbols on-demand
  - Calls `query_stock_ai()` or `query_stock_ai_openai()` based on `AI_PROVIDER`
  - Returns formatted response string

**Modify: `core/claude_client.py`**
- Add `query_stock_ai(user_query, portfolio_context, technicals, news) -> str`
  - System prompt: conversational portfolio advisor, plain text response (no JSON), be concise
  - User prompt: inject query + available data context
  - Returns raw LLM text (no JSON parsing)

**Modify: `core/openai_client.py`**
- Add `query_stock_ai_openai(user_query, portfolio_context, technicals, news) -> str`
  - Mirrors Claude version; uses GPT-4 Turbo, `response_format` NOT forced to JSON
  - Returns raw LLM text

**Modify: `routes/telegram_routes.py`**
- In `telegram_webhook()`, after the callback query block, add handler for `payload["message"]["text"]`
- Call `handle_stock_query(text)` and send response via `send_message()`
- Wrap in try/except with fallback error message to user

**New file: `tests/test_week8.py`**
- Test symbol detection for portfolio and non-portfolio stocks
- Test `query_stock_ai()` with mock data (USE_MOCK_AI=true)
- Test `telegram_webhook()` with plain text payload
- Test fallback when symbol data unavailable

### Detailed flow

```
User Telegram message: "What's happening with HDFCBANK today?"
   │
   ▼
routes/telegram_routes.py: telegram_webhook()
   → detect it's a "message" not "callback_query"
   → extract text: "What's happening with HDFCBANK today?"
   │
   ▼
agent/query.py: handle_stock_query(text)
   → detect symbol: ["HDFCBANK"]
   → portfolio holdings check: HDFCBANK not in mock portfolio
   → fetch on-demand: fetch_ohlc("HDFCBANK") → compute_indicators()
   → fetch on-demand: get_news_sentiment("HDFCBANK")
   → build portfolio context (for reference)
   → call LLM with all context + user query
   │
   ▼
core/claude_client.py OR core/openai_client.py (AI_PROVIDER)
   → returns: "HDFCBANK is trading near its 52w high with RSI at 72 (slightly overbought)..."
   │
   ▼
core/telegram_bot.py: send_message(response)
   → Telegram delivers reply to user
```

### Symbol detection logic

```python
import re

PORTFOLIO_SYMBOLS = set(...)  # loaded from holdings at runtime

def detect_symbols(query: str) -> list[str]:
    # Match uppercase sequences that look like NSE symbols
    candidates = re.findall(r'\b[A-Z]{2,12}\b', query)
    # Filter out common English words
    stopwords = {"RSI", "BUY", "SELL", "NSE", "BSE", "AI", "LLM", "AND", "THE", "FOR"}
    return [c for c in candidates if c not in stopwords]
```

### Critical files & line references

| File | What changes | Key existing functions to reuse |
|------|-------------|---------------------------------|
| `routes/telegram_routes.py:81` | Add text message handler (currently just logs) | `_answer_callback_query()`, `send_message()` |
| `core/claude_client.py` | Add `query_stock_ai()` | Reuse `_build_prompt()` pattern, `anthropic.Anthropic()` client |
| `core/openai_client.py` | Add `query_stock_ai_openai()` | Reuse `call_openai_briefing()` client setup |
| `data/technicals.py:41` | `fetch_ohlc()` reused as-is for on-demand fetch | Already works for any symbol |
| `data/news.py` | `get_news_sentiment()` reused as-is | Already works for any symbol |
| `data/portfolio.py` | `build_claude_context()` reused for portfolio context | Already returns holdings + risk flags |
| `agent/query.py` | New file | Follows `agent/briefing.py` module pattern |

### Config additions (`config.py`)
```python
QUERY_MAX_SYMBOLS = 3          # max symbols to fetch on-demand per query
QUERY_FETCH_TIMEOUT_SECS = 10  # on-demand fetch timeout
```

---

## Verification

1. Run `pytest tests/test_week8.py -v` — all new query tests pass
2. Start webhook server locally with `USE_MOCK=true`
3. Send Telegram message: "How is RELIANCE doing?" (portfolio stock) → fast response using cache
4. Send Telegram message: "Give me info on HDFCBANK" (non-portfolio) → ~5-10s then response
5. Send Telegram message: "Should I buy or hold any stocks today?" (no specific symbol) → portfolio-wide advice
6. Send button callback (approve/skip) → verify existing approval flow still works unaffected
7. Run full test suite `pytest` — all 119 tests still passing plus new week 8 tests
