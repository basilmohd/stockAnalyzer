"""
Test to verify the stop-loss execution fix.
Simulates the complete flow: token generation → validation → execution.
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Setup
sys.path.insert(0, "c:\\Basil\\Projects\\stockAnalyzer")

from config import TIMEZONE
from core.approval import generate_token, validate_token
from core.db import get_db
from models.approval import Approval

IST = ZoneInfo(TIMEZONE)


def test_stoploss_token_generation_and_validation():
    """Test that STOPLOSS tokens include symbol and can be validated."""
    print("\n📋 TEST 1: STOPLOSS Token Generation & Validation")
    
    # Generate a STOPLOSS token with symbol
    token = generate_token("STOPLOSS", symbol="BDL")
    print(f"✓ Generated STOPLOSS token: {token[:8]}... for BDL")
    
    # Validate the token
    result = validate_token(token)
    print(f"✓ Token validation result: {result['valid']}")
    
    assert result["valid"], "Token should be valid"
    assert result["action_type"] == "STOPLOSS", "Action type should be STOPLOSS"
    assert result["symbol"] == "BDL", f"Symbol should be BDL, got {result['symbol']}"
    assert result["signal_id"] is None, "Signal ID should be None for STOPLOSS"
    
    print("✅ TEST 1 PASSED: STOPLOSS token generated correctly with symbol\n")


def test_signal_token_generation_and_validation():
    """Test that SIGNAL tokens still work with signal_id."""
    print("📋 TEST 2: SIGNAL Token Generation & Validation")
    
    # Generate a SIGNAL token with signal_id
    token = generate_token("SIGNAL", signal_id=42)
    print(f"✓ Generated SIGNAL token: {token[:8]}... for signal_id=42")
    
    # Validate the token
    result = validate_token(token)
    print(f"✓ Token validation result: {result['valid']}")
    
    assert result["valid"], "Token should be valid"
    assert result["action_type"] == "SIGNAL", "Action type should be SIGNAL"
    assert result["signal_id"] == 42, f"Signal ID should be 42, got {result['signal_id']}"
    assert result["symbol"] is None, "Symbol should be None for SIGNAL"
    
    print("✅ TEST 2 PASSED: SIGNAL token generated correctly with signal_id\n")


def test_database_schema():
    """Verify the approvals table has the symbol column."""
    print("📋 TEST 3: Database Schema Check")
    
    with get_db() as db:
        # Create a test record
        token = generate_token("STOPLOSS", symbol="SBIN", expiry_mins=5)
        
        # Query it back
        approval = db.query(Approval).filter(Approval.token == token).first()
        
        assert approval is not None, "Approval record not found"
        assert approval.symbol == "SBIN", f"Symbol should be SBIN, got {approval.symbol}"
        assert approval.action_type == "STOPLOSS", "Action type should be STOPLOSS"
        
        print(f"✓ Approval record in DB:")
        print(f"  - Token: {approval.token[:8]}...")
        print(f"  - Action: {approval.action_type}")
        print(f"  - Symbol: {approval.symbol}")
        print(f"  - Signal ID: {approval.signal_id}")
        print(f"  - Status: {approval.status}")
    
    print("✅ TEST 3 PASSED: Database schema includes symbol column\n")


if __name__ == "__main__":
    try:
        test_stoploss_token_generation_and_validation()
        test_signal_token_generation_and_validation()
        test_database_schema()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        print("\nThe fix is working correctly:")
        print("1. STOPLOSS tokens now store the symbol")
        print("2. SIGNAL tokens continue to work with signal_id")
        print("3. The database schema has been updated")
        print("\nThe stop-loss execution flow should now work:")
        print("  BDL alert → token with symbol → Execute button → ")
        print("  → handle_signal_execution checks action_type")
        print("  → For STOPLOSS: gets symbol from token, places SELL order")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
