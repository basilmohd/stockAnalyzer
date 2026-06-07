"""Trade journal — records what happened to each signal by updating its ActionLog.

update_action_log() is the single entry point: given a signal_id or an approval
token, it flips the matching PENDING ActionLog row to APPROVED / SKIPPED / EXPIRED
and stamps the response time. Trade creation happens in Week 10; until then this is
the authoritative record of the user's response to every alert.
"""
from datetime import datetime, timezone

from core.db import get_db
from core.logger import get_logger
from models.action_log import ActionLog
from models.approval import Approval

logger = get_logger(__name__)


def _resolve_signal_id(signal_id_or_token) -> int | None:
    """Return a signal_id from either an int signal_id or a str approval token."""
    if signal_id_or_token is None:
        return None
    if isinstance(signal_id_or_token, int):
        return signal_id_or_token
    # Treat anything else as an approval token → look up its signal_id.
    token = str(signal_id_or_token)
    with get_db() as db:
        approval = db.query(Approval).filter(Approval.token == token).first()
        return approval.signal_id if approval else None


def update_action_log(signal_id_or_token, action_taken: str) -> int | None:
    """Update the latest PENDING ActionLog for a signal to *action_taken*.

    Accepts either a signal_id (int) or an approval token (str). Stamps
    action_taken_at = now (UTC) and response_time_sec = seconds elapsed since
    telegram_sent_at. No-ops (returns None) when the signal can't be resolved or no
    PENDING row exists. Never raises — journalling must not break the approval flow.

    Args:
        signal_id_or_token: signal_id (int) or approval token (str).
        action_taken: new status — "APPROVED", "SKIPPED", or "EXPIRED".

    Returns:
        The updated ActionLog row id, or None if nothing was updated.
    """
    try:
        signal_id = _resolve_signal_id(signal_id_or_token)
        if signal_id is None:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with get_db() as db:
            row = (
                db.query(ActionLog)
                .filter(
                    ActionLog.signal_id == signal_id,
                    ActionLog.action_taken == "PENDING",
                )
                .order_by(ActionLog.id.desc())
                .first()
            )
            if row is None:
                logger.debug(
                    "No PENDING ActionLog for signal_id=%s (%s)", signal_id, action_taken
                )
                return None

            row.action_taken = action_taken
            row.action_taken_at = now
            if row.telegram_sent_at is not None:
                delta = (now - row.telegram_sent_at).total_seconds()
                row.response_time_sec = max(0, int(delta))
            row_id = row.id
            db.commit()

        logger.info("ActionLog #%s signal_id=%s → %s", row_id, signal_id, action_taken)
        return row_id
    except Exception as exc:
        logger.warning(
            "update_action_log failed (%s → %s): %s",
            signal_id_or_token, action_taken, exc,
        )
        return None
