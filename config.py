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
USE_MOCK_KITE = os.getenv("USE_MOCK_KITE", str(USE_MOCK).lower()).lower() == "true"

# ── Market Rules ──────────────────────────────────────────────────────────────
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"
TIMEZONE = "Asia/Kolkata"

# ── Risk Rules ────────────────────────────────────────────────────────────────
DEFAULT_SL_PCT = -15.0          # Stop loss: -15% from entry price
CONFIDENCE_THRESHOLD = 0.75    # Only alert signals above 75% confidence
MAX_HOLDING_WEIGHT_PCT = 20.0  # Reporting: flag a holding over 20% of current portfolio value (percent-scale)
APPROVAL_EXPIRY_MINS = 30      # Signal approval expires in 30 minutes
SL_APPROVAL_EXPIRY_MINS = 15   # SL breach approval expires in 15 minutes
SL_COOLDOWN_MINS = 30          # Don't re-alert same stock within 30 min

# ── Capital & Position Sizing ─────────────────────────────────────────────────
# NOTE: MAX_POSITION_PCT and CASH_RESERVE_PCT are FRACTIONS (0.25 = 25%), used by
# the Week 9 sizing engine (agent/sizing.py) and portfolio guard against TOTAL_CAPITAL.
# This is distinct from the percent-scale MAX_HOLDING_WEIGHT_PCT (Risk Rules), which
# drives portfolio-concentration reporting in data/portfolio.py and agent/health.py.
TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", "25000"))          # Deployable trading capital (₹)
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "0.02"))  # Risk 2% of capital per trade
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.25"))      # Max 25% of capital in one position
CASH_RESERVE_PCT = float(os.getenv("CASH_RESERVE_PCT", "0.20"))      # Always keep 20% cash reserve
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "4"))       # Max concurrent open positions
MAX_SAME_SECTOR = int(os.getenv("MAX_SAME_SECTOR", "2"))             # Max open positions per sector
WEEKLY_LOSS_LIMIT = float(os.getenv("WEEKLY_LOSS_LIMIT", "0.05"))    # Pause trading after 5% weekly loss
MIN_ORDER_VALUE = float(os.getenv("MIN_ORDER_VALUE", "2000"))        # Skip orders below ₹2000

# ── Cache Settings ────────────────────────────────────────────────────────────
HOLDINGS_CACHE_TTL = 60         # Holdings cache TTL in seconds (1 minute for fresher SL monitoring)
# ── Per-stock SL overrides (symbol: pct) ─────────────────────────────────────
SL_OVERRIDES: dict[str, float] = {}

# ── Scanner ───────────────────────────────────────────────────────────────────
MAX_OPPORTUNITIES_PER_DAY = 2  # Cap on opportunity alerts per scanner run

AI_PROVIDER = os.getenv("AI_PROVIDER", "claude").lower()  # "claude" or "openai"
USE_MOCK_AI = os.getenv("USE_MOCK_AI", "true").lower() == "true"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── Chat Feature ──────────────────────────────────────────────────────────────
CHAT_DAILY_LIMIT = 20                       # Max queries per user per day
CHAT_HISTORY_MAX_MESSAGES = 10              # Keep last N messages in conversation
CHAT_HISTORY_TTL = 86400                    # 24 hours in seconds
CHAT_CONTEXT_SOURCES = ["portfolio", "technicals", "news", "risk_flags"]  # Data to include in context

# ── Global Market Research ───────────────────────────────────────────────────
GLOBAL_RESEARCH_INDICES = [
    "S&P 500", "Dow Jones", "NASDAQ",           # US markets
    "DAX", "FTSE 100", "Euronext 50",           # European markets
    "Nifty 50", "Sensex"                        # Indian markets
]
GLOBAL_RESEARCH_CACHE_TTL = 604800              # 7 days (weekly data)
GLOBAL_RESEARCH_MAX_CHUNK_SIZE = 3500           # For Telegram chunking (leaves margin for formatting)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_ROTATION = "midnight"
LOG_BACKUP_COUNT = 7  # keep 1 week of logs
