"""
End-to-end test simulating the exact BDL stop-loss execution scenario from May 21, 2026.

Flow:
1. Stop-loss alert generated for BDL (token with symbol)
2. User clicks "Execute exit" button
3. Handler validates token and executes the exit
"""
import sys
import asyncio
sys.path.insert(0, "c:\\Basil\\Projects\\stockAnalyzer")

from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo

from config import TIMEZONE
from core.approval import generate_token, validate_token
from core.db import get_db
from models.approval import Approval

IST = ZoneInfo(TIMEZONE)


async def test_bdl_stoploss_scenario():
    """Simulate the exact BDL scenario: alert → token → execution."""
    print("\n" + "="*70)
    print("SCENARIO: BDL Stop-Loss Alert → User Clicks Execute → Order Placed")
    print("="*70)
    
    # ─ PHASE 1: Stop-Loss Alert Generated ─────────────────────────────────
    print("\n📋 PHASE 1: Stop-Loss Alert Generation")
    print("-" * 70)
    
    symbol = "BDL"
    token = generate_token("STOPLOSS", symbol=symbol)
    print(f"✓ Generated STOPLOSS token: {token[:16]}...")
    print(f"  - Action Type: STOPLOSS")
    print(f"  - Symbol: {symbol}")
    
    # Validate the token
    result = validate_token(token)
    print(f"✓ Token validated: {result['valid']}")
    print(f"  - Action: {result['action_type']}")
    print(f"  - Symbol: {result['symbol']}")
    assert result["valid"], "Token should be valid"
    assert result["symbol"] == symbol, f"Symbol mismatch: {result['symbol']}"
    assert result["action_type"] == "STOPLOSS"
    print("✅ PHASE 1 PASSED: Token generated with symbol\n")
    
    # ─ PHASE 2: User Clicks Execute Exit ─────────────────────────────────
    print("📋 PHASE 2: User Clicks 'Execute exit' Button")
    print("-" * 70)
    
    from routes.approval_routes import handle_signal_execution
    
    # Mock the dependencies
    with patch("core.kite_client.KiteClient") as MockKite, \
         patch("core.telegram_bot.send_alert", new_callable=AsyncMock) as mock_alert:
        
        # Setup KiteClient mock
        mock_kite_instance = MagicMock()
        MockKite.return_value = mock_kite_instance
        
        # Mock holdings (BDL with 100 shares)
        mock_kite_instance.get_holdings.return_value = [
            {"tradingsymbol": "BDL", "quantity": 100, "average_price": 500, "last_price": 425},
            {"tradingsymbol": "SBIN", "quantity": 50, "average_price": 600, "last_price": 580},
        ]
        
        # Mock successful order placement
        mock_kite_instance.place_order.return_value = {
            "status": "COMPLETE",
            "order_id": "4521001234567890",
        }
        
        # Mock Redis
        # (Note: redis delete will be called but we don't need to mock it for this test)
        
        print(f"✓ User clicked 'EXECUTE EXIT' for token: {token[:16]}...")
        
        # Call the handler
        order_result = await handle_signal_execution(token)
        
        print(f"✓ Handler executed: {order_result['status']}")
        
        # Verify the order was placed correctly
        assert order_result["status"] == "ok", f"Expected 'ok', got {order_result['status']}"
        assert order_result["symbol"] == symbol, f"Symbol mismatch in result"
        assert order_result["action"] == "SELL", f"Action should be SELL"
        
        # Verify Kite API was called correctly
        mock_kite_instance.get_holdings.assert_called()
        mock_kite_instance.place_order.assert_called_once_with(symbol, "SELL", 100)
        
        print(f"✓ Order placed via Kite API:")
        print(f"  - Symbol: {order_result['symbol']}")
        print(f"  - Action: {order_result['action']}")
        print(f"  - Quantity: 100 (from holdings)")
        print(f"  - Order ID: {order_result['order_id']}")
        
        # Verify alert was sent
        mock_alert.assert_called_once()
        alert_call = mock_alert.call_args
        assert "Executed" in alert_call[0][0] or "EXECUTED" in alert_call[0][1]
        print(f"✓ Telegram alert sent confirming execution")
        
        # Verify token was marked approved
        validated_after = validate_token(token)
        print(f"✓ Token status after execution: {validated_after['reason']}")
        
        print("✅ PHASE 2 PASSED: Order executed successfully\n")
    
    # ─ PHASE 3: Verify Database State ─────────────────────────────────
    print("📋 PHASE 3: Verify Database State")
    print("-" * 70)
    
    with get_db() as db:
        approval = db.query(Approval).filter(Approval.token == token).first()
        assert approval is not None, "Approval record should exist"
        assert approval.action_type == "STOPLOSS", "Action type should be STOPLOSS"
        assert approval.symbol == symbol, "Symbol should be BDL"
        assert approval.signal_id is None, "Signal ID should be None for STOPLOSS"
        assert approval.status == "APPROVED", f"Status should be APPROVED, got {approval.status}"
        
        print(f"✓ Approval record in database:")
        print(f"  - Token: {approval.token[:16]}...")
        print(f"  - Action: {approval.action_type}")
        print(f"  - Symbol: {approval.symbol}")
        print(f"  - Status: {approval.status}")
        print(f"  - Created: {approval.created_at}")
        print("✅ PHASE 3 PASSED: Database state correct\n")
    
    # ─ FINAL SUMMARY ─────────────────────────────────────────────────
    print("="*70)
    print("✅ END-TO-END TEST PASSED!")
    print("="*70)
    print("\n🎯 FIX CONFIRMED:")
    print("   Stop-loss for BDL with 'Execute exit' button now works correctly!")
    print("   Token includes symbol → Handler identifies STOPLOSS action →")
    print("   Gets quantity from holdings → Places SELL order → Success ✓")


if __name__ == "__main__":
    try:
        asyncio.run(test_bdl_stoploss_scenario())
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
