# OpenAI "AI Analysis Unavailable" Error - Root Cause & Fix

## Problem
**Morning briefing error**: "AI analysis unavailable" with alert "AI provider error — check logs"

### Root Cause
The error was **NOT from OpenAI**, but from **Kite API timeout** when fetching portfolio holdings.

**Error in logs**:
```
HTTPSConnectionPool(host='api.kite.trade', port=443): Read timed out. (read timeout=7)
```

The briefing fails at the **portfolio data fetch stage** (before it even reaches OpenAI):
1. `build_claude_context()` → calls `get_holdings_with_sl_status()`
2. `get_holdings()` → calls `self.kite.holdings()` 
3. Kite API timeout (7 seconds) → exception raised
4. Briefing catches exception and returns error message

## Solution Implemented

Added **retry logic with exponential backoff** and **Redis cache fallback** to [core/kite_client.py](core/kite_client.py):

### Changes
1. **`get_holdings()`** - 3 retry attempts with 1s, 2s, 4s delays
2. **`get_quote()`** - 3 retry attempts with exponential backoff
3. **`get_historical_data()`** - 3 retry attempts with exponential backoff
4. **Cache fallback** - If all retries fail, uses 5-minute cached holdings from Redis

### How It Works
```python
# Pseudocode
for attempt in range(3):
    try:
        data = kite_api_call()
        cache_result(data)  # Cache on success
        return data
    except timeout:
        if attempt < 2:
            sleep(retry_delay)  # 1s → 2s → 4s
            retry_delay *= 2
        else:
            # All retries failed
            if cache_exists:
                return cached_data  # Use stale data
            else:
                raise error
```

## Benefits
- **Handles transient Kite API timeouts** gracefully (network hiccup)
- **Falls back to cached data** if API is persistently slow
- **No impact on mock mode** (tests still pass)
- **Logs all attempts** for debugging

## Testing
✅ All 119 tests pass, including:
- `test_kite_client_get_holdings`
- `test_kite_client_get_quote`
- Briefing generation tests
- Cache tests

## Next Steps if Issue Persists
1. **Check Kite API status** - Market may be closed or API may be overloaded
2. **Increase timeout** - Modify kiteconnect config if needed
3. **Check Redis** - Ensure Redis is running for cache fallback
4. **Monitor logs** - Watch `logs/core.kite_client.log` for retry patterns

## Files Modified
- [core/kite_client.py](core/kite_client.py) - Added retry logic and cache fallback
