"""
Market closure portfolio report module.

Generates and sends daily portfolio closure summary at 3:30 PM IST.
Reports total portfolio value, total daily P&L %, and top 3 gainers/losers.
"""

from datetime import datetime, date
from typing import Dict, List, Optional

from core.logger import get_logger
from core.kite_client import KiteClient
from core.telegram_bot import send_alert
from core.daily_prices import get_daily_open_prices, get_fallback_prices
from data.portfolio import get_portfolio_summary

logger = get_logger(__name__)


class HoldingWithDailyPnL:
    """Data class for holding with daily P&L metrics."""
    
    def __init__(
        self,
        symbol: str,
        quantity: int,
        current_price: float,
        prev_close_price: Optional[float] = None,
        last_price: Optional[float] = None,
    ):
        """
        Initialize holding with daily P&L calculation.
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE').
            quantity: Number of shares held.
            current_price: Current market price.
            prev_close_price: Previous trading day's close price (for daily P&L ref).
            last_price: Last traded price (for fallback to current_price).
        """
        self.symbol = symbol
        self.quantity = quantity
        self.current_price = current_price
        self.prev_close_price = prev_close_price or current_price
        
        # Daily P&L calculation
        if self.prev_close_price and self.prev_close_price > 0:
            self.daily_pnl_pct = (
                (current_price - self.prev_close_price) / self.prev_close_price * 100
            )
        else:
            self.daily_pnl_pct = 0.0
        
        # Position value at current price
        self.current_value = current_price * quantity
        
        # Position value at previous close (for portfolio-level daily P&L)
        self.prev_close_value = self.prev_close_price * quantity


async def calculate_daily_pnl(
    holdings: List[dict], prev_close_prices: Optional[Dict[str, float]] = None
) -> tuple[List[HoldingWithDailyPnL], float]:
    """
    Calculate daily P&L for all holdings and portfolio total.
    
    Args:
        holdings: List of holding dicts from KiteClient().get_holdings().
        prev_close_prices: Optional dict of {symbol: previous_close_price}.
                          If None, retrieves from Redis or fallback.
    
    Returns:
        tuple: (list of HoldingWithDailyPnL, portfolio_daily_pnl_pct)
    """
    try:
        if not holdings:
            logger.warning("No holdings provided for daily P&L calculation")
            return [], 0.0
        
        # Get previous close prices if not provided
        if prev_close_prices is None:
            prev_close_prices = get_daily_open_prices()
            
            # If Redis empty, fallback to entry prices
            if not prev_close_prices:
                logger.warning("Using entry prices (average_price) as fallback for daily P&L")
                prev_close_prices = get_fallback_prices(holdings)
        
        # Calculate daily P&L for each holding
        holdings_with_pnl: List[HoldingWithDailyPnL] = []
        total_current_value = 0.0
        total_prev_close_value = 0.0
        
        for holding in holdings:
            symbol = holding["tradingsymbol"]
            quantity = holding["quantity"]
            current_price = holding["last_price"]
            prev_close = prev_close_prices.get(symbol, holding["average_price"])
            
            h = HoldingWithDailyPnL(
                symbol=symbol,
                quantity=quantity,
                current_price=current_price,
                prev_close_price=prev_close,
            )
            
            holdings_with_pnl.append(h)
            total_current_value += h.current_value
            total_prev_close_value += h.prev_close_value
        
        # Calculate portfolio daily P&L %
        if total_prev_close_value and total_prev_close_value > 0:
            portfolio_daily_pnl_pct = (
                (total_current_value - total_prev_close_value) / total_prev_close_value * 100
            )
        else:
            portfolio_daily_pnl_pct = 0.0
        
        logger.debug(
            f"Calculated daily P&L for {len(holdings_with_pnl)} holdings; "
            f"portfolio daily P&L: {portfolio_daily_pnl_pct:.2f}%"
        )
        
        return holdings_with_pnl, portfolio_daily_pnl_pct
        
    except Exception as e:
        logger.error(f"Error calculating daily P&L: {e}", exc_info=True)
        return [], 0.0


def get_top_gainers_losers(
    holdings_with_pnl: List[HoldingWithDailyPnL], top_n: int = 3
) -> tuple[List[HoldingWithDailyPnL], List[HoldingWithDailyPnL]]:
    """
    Extract top N gainers and top N losers by daily P&L %.
    
    Only includes stocks that actually gained/lost value for the day.
    Gainers: daily_pnl_pct > 0, sorted descending.
    Losers: daily_pnl_pct < 0, sorted ascending (biggest losers first).
    
    Args:
        holdings_with_pnl: List of HoldingWithDailyPnL.
        top_n: Number of top gainers/losers to extract (default 3).
    
    Returns:
        tuple: (top_gainers, top_losers) — only stocks that gained/lost.
    """
    try:
        if not holdings_with_pnl:
            return [], []
        
        # Filter for gainers: daily_pnl_pct > 0, sort descending
        gainers = sorted(
            [h for h in holdings_with_pnl if h.daily_pnl_pct > 0],
            key=lambda h: h.daily_pnl_pct,
            reverse=True
        )[:top_n]
        
        # Filter for losers: daily_pnl_pct < 0, sort ascending (most negative first)
        losers = sorted(
            [h for h in holdings_with_pnl if h.daily_pnl_pct < 0],
            key=lambda h: h.daily_pnl_pct
        )[:top_n]
        
        return gainers, losers
        
    except Exception as e:
        logger.error(f"Error extracting top gainers/losers: {e}", exc_info=True)
        return [], []


def format_closure_message(
    total_portfolio_value: float,
    portfolio_daily_pnl_pct: float,
    gainers: List[HoldingWithDailyPnL],
    losers: List[HoldingWithDailyPnL],
) -> str:
    """
    Format closure report as HTML message for Telegram.
    
    Args:
        total_portfolio_value: Current total portfolio value in ₹.
        portfolio_daily_pnl_pct: Portfolio's total daily P&L %.
        gainers: Top 3 gainers by daily P&L %.
        losers: Top 3 losers by daily P&L %.
    
    Returns:
        str: HTML-formatted message.
    """
    try:
        # Determine emoji based on portfolio P&L direction
        portfolio_emoji = "📈" if portfolio_daily_pnl_pct >= 0 else "📉"
        pnl_sign = "+" if portfolio_daily_pnl_pct >= 0 else ""
        
        # Header
        closure_time = datetime.now().strftime("%a %d %b %H:%M IST")
        message = (
            f"🔴 <b>MARKET CLOSURE</b> — {closure_time}\n\n"
            f"<b>📊 Portfolio Summary</b>\n"
            f"Total Value: <code>₹{total_portfolio_value:,.0f}</code>\n"
            f"Daily P&L: {portfolio_emoji} <b>{pnl_sign}{portfolio_daily_pnl_pct:.2f}%</b>\n\n"
        )
        
        # Top Gainers section
        if gainers:
            message += "<b>🔝 Top Gainers</b>\n"
            for h in gainers:
                message += (
                    f"<code>{h.symbol:8} +{h.daily_pnl_pct:6.2f}%  "
                    f"₹{h.current_value:10,.0f}</code>\n"
                )
            message += "\n"
        
        # Top Losers section
        if losers:
            message += "<b>🔻 Top Losers</b>\n"
            for h in losers:
                message += (
                    f"<code>{h.symbol:8} {h.daily_pnl_pct:6.2f}%  "
                    f"₹{h.current_value:10,.0f}</code>\n"
                )
            message += "\n"
        
        # Footer
        message += "<i>Market closed at 15:30 IST</i>"
        
        return message
        
    except Exception as e:
        logger.error(f"Error formatting closure message: {e}", exc_info=True)
        return "<b>Error formatting market closure report</b>"


async def send_closure_report() -> bool:
    """
    Orchestrate daily closure report: fetch data → calculate P&L → format → send.
    
    Called at 3:30 PM IST Mon-Fri by scheduler.
    
    Returns:
        bool: True if successfully sent, False on error.
    """
    try:
        logger.info("Starting market closure report generation")
        
        # Fetch current holdings (excluding zero-share holdings)
        from data.portfolio import _filter_valid_holdings
        holdings = _filter_valid_holdings(KiteClient().get_holdings())
        if not holdings:
            logger.warning("No holdings found; aborting closure report")
            return False
        
        # Get previous close prices (or fallback to entry prices)
        prev_close_prices = get_daily_open_prices()
        if not prev_close_prices:
            logger.info("Previous close prices unavailable; will use entry prices as fallback")
        
        # Calculate daily P&L for all holdings
        holdings_with_pnl, portfolio_daily_pnl_pct = await calculate_daily_pnl(
            holdings, prev_close_prices
        )
        
        if not holdings_with_pnl:
            logger.error("Failed to calculate daily P&L; aborting closure report")
            return False
        
        # Get portfolio summary for total value
        portfolio_summary = get_portfolio_summary()
        total_portfolio_value = portfolio_summary.get("total_value", 0.0)
        
        # Extract top gainers and losers
        gainers, losers = get_top_gainers_losers(holdings_with_pnl, top_n=3)
        
        # Format message
        message = format_closure_message(
            total_portfolio_value, portfolio_daily_pnl_pct, gainers, losers
        )
        
        # Send via Telegram
        success = await send_alert(
            title="Market Closure Report",
            body=message,
            alert_type="INFO",
        )
        
        if success:
            logger.info(
                f"Closure report sent successfully; "
                f"portfolio daily P&L: {portfolio_daily_pnl_pct:.2f}%"
            )
        else:
            logger.error("Failed to send closure report via Telegram")
        
        return success
        
    except Exception as e:
        logger.error(f"Error in send_closure_report: {e}", exc_info=True)
        return False
