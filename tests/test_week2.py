"""
Week 2 test suite — approval token engine, Telegram bot integration.
10 unit tests + 3 integration tests (send real Telegram messages).
All 13 must pass.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import SL_APPROVAL_EXPIRY_MINS, TIMEZONE

IST = ZoneInfo(TIMEZONE)


@pytest.fixture(scope="module", autouse=True)
def ensure_db():
    """Create data_store dir and DB tables before any approval test runs."""
    root = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(os.path.join(root, "data_store"), exist_ok=True)
    from core.db import init_db
    init_db()


# ── Approval token tests ──────────────────────────────────────────────────────

def test_generate_token_signal():
    """generate_token('SIGNAL', signal_id=1) returns a 36-char UUID string."""
    from core.approval import generate_token
    token = generate_token("SIGNAL", signal_id=1)
    assert isinstance(token, str)
    assert len(token) == 36


def test_generate_token_stoploss():
    """generate_token('STOPLOSS') succeeds without a signal_id."""
    from core.approval import generate_token
    token = generate_token("STOPLOSS")
    assert isinstance(token, str)
    assert len(token) == 36


def test_validate_token_valid():
    """A freshly generated SIGNAL token validates as valid with correct action_type."""
    from core.approval import generate_token, validate_token
    token = generate_token("SIGNAL", signal_id=1)
    result = validate_token(token)
    assert result["valid"] is True
    assert result["action_type"] == "SIGNAL"


def test_validate_token_not_found():
    """A fake token returns valid=False with 'not found' in reason."""
    from core.approval import validate_token
    result = validate_token("fake-token-that-doesnt-exist")
    assert result["valid"] is False
    assert "not found" in result["reason"].lower()


def test_validate_token_after_approval():
    """Approving a token makes it invalid; reason contains 'approved'."""
    from core.approval import generate_token, mark_approved, validate_token
    token = generate_token("SIGNAL")
    mark_approved(token)
    result = validate_token(token)
    assert result["valid"] is False
    assert "approved" in result["reason"].lower()


def test_mark_approved():
    """mark_approved returns True; token is then invalid on next validate."""
    from core.approval import generate_token, mark_approved, validate_token
    token = generate_token("SIGNAL")
    assert mark_approved(token) is True
    assert validate_token(token)["valid"] is False


def test_mark_skipped():
    """mark_skipped returns True on a PENDING token."""
    from core.approval import generate_token, mark_skipped
    token = generate_token("SIGNAL")
    assert mark_skipped(token) is True


def test_cleanup_expired_tokens():
    """cleanup_expired_tokens returns a non-negative integer."""
    from core.approval import cleanup_expired_tokens
    count = cleanup_expired_tokens()
    assert isinstance(count, int)
    assert count >= 0


def test_approval_flow_end_to_end():
    """Full lifecycle: generate → validate (valid) → approve → validate (invalid)."""
    from core.approval import generate_token, mark_approved, validate_token
    token = generate_token("SIGNAL", signal_id=42)

    assert validate_token(token)["valid"] is True

    mark_approved(token)

    result = validate_token(token)
    assert result["valid"] is False


def test_sl_token_shorter_expiry():
    """STOPLOSS tokens expire in ~SL_APPROVAL_EXPIRY_MINS (15 min), within 60s tolerance."""
    from core.approval import generate_token
    from core.db import get_db
    from models.approval import Approval

    token = generate_token("STOPLOSS")

    with get_db() as db:
        approval = db.query(Approval).filter(Approval.token == token).first()
        assert approval is not None

        # expires_at is stored as a naive datetime whose values are in IST
        now_naive = datetime.now(IST).replace(tzinfo=None)
        expected_expiry = now_naive + timedelta(minutes=SL_APPROVAL_EXPIRY_MINS)
        delta_secs = abs((approval.expires_at - expected_expiry).total_seconds())

    assert delta_secs < 60, (
        f"Expected ~{SL_APPROVAL_EXPIRY_MINS}min expiry, got {delta_secs:.1f}s off"
    )


# ── Integration tests — real Telegram messages ────────────────────────────────

@pytest.mark.integration
def test_send_message_real():
    """Send a plain text message to the real Telegram chat."""
    from core.telegram_bot import send_message
    result = asyncio.run(send_message("🧪 Test from pytest — Week 2 test suite"))
    assert result is True


@pytest.mark.integration
def test_send_alert_real():
    """Send a formatted INFO alert to the real Telegram chat."""
    from core.telegram_bot import send_alert
    result = asyncio.run(send_alert("pytest Test", "Integration test alert", "INFO"))
    assert result is True


@pytest.mark.integration
def test_morning_briefing_format():
    """Build portfolio context from mock data and send morning briefing to Telegram."""
    from core.telegram_bot import send_morning_briefing
    from data.portfolio import build_claude_context
    context = build_claude_context()
    result = asyncio.run(send_morning_briefing(context))
    assert result is True
