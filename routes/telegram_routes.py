"""
Telegram bot webhook routes.
"""
import logging
from typing import Any

from fastapi import APIRouter, Request

from agent.journal import update_action_log
from core.approval import mark_approved, mark_skipped, validate_token
from core.telegram_bot import get_bot, send_alert, send_message
from core.exception_handler import safe_run

logger = logging.getLogger(__name__)

router = APIRouter()


async def _answer_callback_query(query_id: str, text: str) -> None:
    """Dismiss the inline button loading spinner and surface a toast to the user."""
    bot = get_bot()
    await bot.answer_callback_query(callback_query_id=query_id, text=text)


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    """
    Receive Telegram update payloads. Routes callback_query actions to the
    approval engine; plain messages are logged and ignored.
    """
    payload: Any = await request.json()
    redis = request.app.state.redis

    if "callback_query" in payload:
        cq = payload["callback_query"]
        callback_data: str = cq.get("data", "")
        query_id: str = cq["id"]

        parts = callback_data.split(":", 1)
        if len(parts) != 2:
            logger.warning("Malformed callback_data: %s", callback_data)
            return {"status": "ok"}

        action, token = parts

        if action == "approve":
            result = validate_token(token)
            if not result["valid"]:
                await _answer_callback_query(query_id, f"❌ {result['reason']}")
            else:
                mark_approved(token)
                update_action_log(token, "APPROVED")
                redis.set(f"approved:{token}", "1")
                await _answer_callback_query(query_id, "✅ Approved! Order will be placed shortly.")
                await send_alert(
                    "Order Approved",
                    f"Token {token[:8]}... approved. Execution in progress.",
                    alert_type="SUCCESS",
                )

        elif action == "execute":
            await _answer_callback_query(query_id, "⚙️ Placing order…")
            from routes.approval_routes import handle_signal_execution
            order_result = await handle_signal_execution(token)
            if order_result.get("status") != "ok":
                logger.warning("Signal execution failed: %s", order_result.get("reason"))

        elif action == "skip":
            result = validate_token(token)
            if not result["valid"]:
                await _answer_callback_query(query_id, f"❌ {result['reason']}")
            else:
                mark_skipped(token)
                update_action_log(token, "SKIPPED")
                await _answer_callback_query(query_id, "⏭ Skipped.")
                await send_alert(
                    "Signal Skipped",
                    f"Signal {token[:8]}… skipped by user.",
                    alert_type="INFO",
                )

        else:
            logger.warning("Unknown callback action: %s", action)

    elif "message" in payload:
        message = payload["message"]
        text = message.get("text", "")
        user_id = str(message.get("from", {}).get("id", "unknown"))

        if text.startswith("/chat "):
            # Handle /chat command
            user_query = text[6:].strip()  # Remove "/chat " prefix
            await safe_run(
                "chat_handler",
                _handle_chat_command,
                user_id,
                user_query,
                request.app.state.redis,
            )
        else:
            logger.info("Telegram message (not chat): %s", text[:50])
    else:
        update_type = next(iter(payload.keys()), "unknown")
        logger.info("Telegram update type: %s", update_type)

    return {"status": "ok"}


async def _handle_chat_command(
    user_id: str, user_query: str, redis
) -> None:
    """Handle /chat command: build portfolio context, call LLM, return response."""
    import config
    from core.chat_client import call_chat
    from data.portfolio import build_claude_context
    from data.technicals import get_technicals_for_holdings
    from data.news import get_news_sentiment_all_holdings

    # Check rate limit
    daily_count = redis.get_daily_chat_count(user_id)
    if daily_count > config.CHAT_DAILY_LIMIT:
        await send_message(
            f"⛔ Daily chat limit ({config.CHAT_DAILY_LIMIT} queries) reached. "
            f"Reset at midnight IST."
        )
        return

    try:
        # Build portfolio context
        portfolio_context = build_claude_context()
        technicals = get_technicals_for_holdings()
        news = get_news_sentiment_all_holdings()

        # Get conversation history
        conversation_history = redis.get_chat_history(user_id)

        # Call LLM
        llm_response = call_chat(
            portfolio_context,
            technicals,
            news,
            conversation_history,
            user_query,
        )

        # Append to history
        redis.append_chat_message(user_id, "user", user_query)
        redis.append_chat_message(user_id, "assistant", llm_response)

        # Send response to user
        await send_message(llm_response, parse_mode="HTML")

    except Exception as exc:
        logger.error("Chat handler failed: %s", exc)
        await send_alert(
            "❌ Chat Error",
            str(exc),
            alert_type="WARNING",
        )

