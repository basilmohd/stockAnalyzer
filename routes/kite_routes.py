"""
Kite Connect OAuth and broker status routes.
"""
import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from config import USE_MOCK, USE_MOCK_KITE, REDIS_URL
from core.kite_client import KiteClient
from core.redis_client import RedisClient

logger = logging.getLogger(__name__)

router = APIRouter()

_redis = RedisClient(REDIS_URL)

_SUCCESS_HTML = """<html><body>
<h2>&#x2705; Authentication successful!</h2>
<p>You can close this tab. The agent is now active.</p>
</body></html>"""

_ERROR_HTML = "<html><body><h2>&#x274C; Authentication failed</h2><p>{msg}</p></body></html>"


@router.get("/login")
async def kite_login() -> dict:
    """Return the Kite OAuth login URL."""
    url = KiteClient().get_login_url()
    return {"login_url": url, "message": "Open this URL to authenticate"}


@router.get("/callback")
async def kite_oauth_callback(
    request_token: str = "",
    state: Optional[str] = None,
) -> HTMLResponse:
    """
    Handle Kite OAuth redirect. Exchanges request_token for access token
    and persists it in Redis via generate_session.
    """
    try:
        token = request_token
        if USE_MOCK_KITE and not token:
            token = "mock_request_token"

        KiteClient().generate_session(token)
        logger.info("Kite OAuth complete. User authenticated.")
        return HTMLResponse(content=_SUCCESS_HTML)
    except Exception as exc:
        logger.error("Kite OAuth callback error: %s", exc)
        return HTMLResponse(
            content=_ERROR_HTML.format(msg=str(exc)),
            status_code=400,
        )


@router.get("/status")
async def kite_status() -> dict:
    """Return authentication state and Redis token TTL."""
    authenticated = KiteClient().is_authenticated()

    ttl: Optional[int] = None
    if _redis.available:
        try:
            raw_ttl = _redis._client.ttl("kite:access_token")
            ttl = raw_ttl if raw_ttl >= 0 else None
        except Exception:
            pass

    return {
        "authenticated": authenticated,
        "mode": "mock" if USE_MOCK_KITE else "live",
        "token_ttl_seconds": ttl,
    }
