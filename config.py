"""
Global configuration and risk rules for the portfolio agent.
All tunable parameters live here — never hardcode these in modules.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Broker ────────────────────────────────────────────────────────────────────
KITE_API_KEY = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "")

# ── Claude ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Infrastructure ────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data_store/portfolio.db")
USE_MOCK = os.getenv("USE_MOCK", "true").lower() == "true"

# ── Market Rules ──────────────────────────────────────────────────────────────
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"
TIMEZONE = "Asia/Kolkata"

# ── Risk Rules ────────────────────────────────────────────────────────────────
DEFAULT_SL_PCT = -15.0          # Stop loss: -15% from entry price
CONFIDENCE_THRESHOLD = 0.75    # Only alert signals above 75% confidence
MAX_POSITION_PCT = 20.0        # No single stock > 20% of portfolio
CASH_RESERVE_PCT = 10.0        # Always keep 10% cash
APPROVAL_EXPIRY_MINS = 30      # Signal approval expires in 30 minutes
SL_APPROVAL_EXPIRY_MINS = 15   # SL breach approval expires in 15 minutes
SL_COOLDOWN_MINS = 30          # Don't re-alert same stock within 30 min

# ── Per-stock SL overrides (symbol: pct) ─────────────────────────────────────
SL_OVERRIDES: dict[str, float] = {}

# ── Scanner ───────────────────────────────────────────────────────────────────
MAX_OPPORTUNITIES_PER_DAY = 2  # Cap on opportunity alerts per scanner run

AI_PROVIDER = os.getenv("AI_PROVIDER", "claude").lower()  # "claude" or "openai"
USE_MOCK_AI = os.getenv("USE_MOCK_AI", "true").lower() == "true"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_ROTATION = "midnight"
LOG_BACKUP_COUNT = 7  # keep 1 week of logs
