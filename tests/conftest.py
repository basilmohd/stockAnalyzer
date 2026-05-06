"""
Shared pytest configuration — forces mock mode for all tests so the test
suite never calls the real Kite API regardless of .env settings.
"""
import pytest


@pytest.fixture(autouse=True, scope="session")
def _force_mock_kite():
    """Patch USE_MOCK_KITE=True in every module that reads it at import time."""
    import config as _cfg
    import core.kite_client as _kite_mod

    _cfg.USE_MOCK_KITE = True
    _kite_mod.USE_MOCK_KITE = True

    # kite_routes reads USE_MOCK_KITE as a module-level name too
    try:
        import routes.kite_routes as _kite_routes
        _kite_routes.USE_MOCK_KITE = True
    except Exception:
        pass

    yield
    # No teardown needed — session ends after tests complete
