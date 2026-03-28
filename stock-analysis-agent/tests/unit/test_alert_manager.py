"""
tests/unit/test_alert_manager.py

Unit tests for orchestrator/alert_manager.py (Phase 5 Step 5.4).

Uses a temporary SQLite DB so tests are fully offline and isolated.

Coverage:
  - initialize_db() creates both tables idempotently
  - store/get conversation_ref round-trips correctly
  - Upsert overwrites stale references
  - queue_alert returns a valid alert_id
  - get_pending_alerts returns undelivered alerts with embedded conv ref
  - get_pending_alerts(user_id=...) filters correctly
  - mark_alert_delivered removes alert from pending list
  - get_pending_alerts returns [] when all delivered
  - No conversation_ref stored → ref is None in pending alert
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))


# ── Test DB fixture ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for each test."""
    db_file = str(tmp_path / "test_alerts.db")
    monkeypatch.setenv("DB_PATH", db_file)
    yield db_file


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_monitor_result(
    ticker="AAPL",
    user_id="user:1",
    score=7.5,
    direction="bullish",
    verdict_value="APPROVED",
    adjusted_qty=33,
    proposed_qty=33,
):
    """Build a lightweight MonitorResult stand-in (same attribute access pattern)."""
    class _Verdict:
        value = verdict_value

    class _Signal:
        pass

    class _Risk:
        pass

    class _Result:
        pass

    sig = _Signal()
    sig.ticker    = ticker
    sig.score     = score
    sig.direction = direction
    sig.summary   = f"📈 {direction.capitalize()} signal ({score:+.1f})"
    sig.price     = 150.0
    sig.rsi       = 28.0
    sig.fired     = True

    risk = _Risk()
    risk.verdict      = _Verdict()
    risk.adjusted_qty = adjusted_qty
    risk.reason       = "all_rules_passed"
    risk.narrative    = ""

    result = _Result()
    result.ticker       = ticker
    result.user_id      = user_id
    result.signal       = sig
    result.risk         = risk
    result.proposed_qty = proposed_qty
    return result


_SAMPLE_REF = {
    "serviceUrl":    "https://smba.trafficmanager.net/emea/",
    "channelId":     "msteams",
    "conversation":  {"id": "conv:abc123", "isGroup": False, "tenantId": "tenant:t1"},
    "bot":           {"id": "bot:botid",    "name": "StockBot"},
    "user":          {"id": "user:u1",      "name": "Test User"},
}


# ── initialize_db ──────────────────────────────────────────────────────────────

class TestInitializeDb:

    def test_creates_tables(self):
        from orchestrator.alert_manager import initialize_db, _conn
        initialize_db()
        with _conn() as c:
            tables = {
                row[0]
                for row in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "conversation_refs" in tables
        assert "alert_queue" in tables

    def test_idempotent(self):
        from orchestrator.alert_manager import initialize_db
        initialize_db()
        initialize_db()  # should not raise


# ── conversation_refs ──────────────────────────────────────────────────────────

class TestConversationRefs:

    def test_store_and_get(self):
        from orchestrator.alert_manager import store_conversation_ref, get_conversation_ref
        store_conversation_ref("user:1", _SAMPLE_REF)
        stored = get_conversation_ref("user:1")
        assert stored == _SAMPLE_REF

    def test_get_returns_none_for_unknown_user(self):
        from orchestrator.alert_manager import get_conversation_ref
        assert get_conversation_ref("user:unknown") is None

    def test_upsert_overwrites_stale_ref(self):
        from orchestrator.alert_manager import store_conversation_ref, get_conversation_ref
        store_conversation_ref("user:1", _SAMPLE_REF)
        new_ref = {**_SAMPLE_REF, "serviceUrl": "https://updated.example.com/"}
        store_conversation_ref("user:1", new_ref)
        stored = get_conversation_ref("user:1")
        assert stored["serviceUrl"] == "https://updated.example.com/"

    def test_different_users_isolated(self):
        from orchestrator.alert_manager import store_conversation_ref, get_conversation_ref
        ref2 = {**_SAMPLE_REF, "user": {"id": "user:2", "name": "User Two"}}
        store_conversation_ref("user:1", _SAMPLE_REF)
        store_conversation_ref("user:2", ref2)
        assert get_conversation_ref("user:1")["user"]["name"] == "Test User"
        assert get_conversation_ref("user:2")["user"]["name"] == "User Two"


# ── queue_alert ────────────────────────────────────────────────────────────────

class TestQueueAlert:

    def test_returns_alert_id(self):
        from orchestrator.alert_manager import queue_alert
        alert_id = queue_alert("user:1", _make_monitor_result())
        assert isinstance(alert_id, int)
        assert alert_id >= 1

    def test_sequential_ids(self):
        from orchestrator.alert_manager import queue_alert
        id1 = queue_alert("user:1", _make_monitor_result("AAPL"))
        id2 = queue_alert("user:1", _make_monitor_result("NVDA"))
        assert id2 > id1

    def test_multiple_users(self):
        from orchestrator.alert_manager import queue_alert
        id1 = queue_alert("user:1", _make_monitor_result("AAPL", "user:1"))
        id2 = queue_alert("user:2", _make_monitor_result("AAPL", "user:2"))
        assert id1 != id2


# ── get_pending_alerts ─────────────────────────────────────────────────────────

class TestGetPendingAlerts:

    def test_returns_queued_alert(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts
        queue_alert("user:1", _make_monitor_result("AAPL"))
        alerts = get_pending_alerts()
        assert len(alerts) == 1
        assert alerts[0]["ticker"] == "AAPL"
        assert alerts[0]["user_id"] == "user:1"

    def test_signal_fields_present(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts
        queue_alert("user:1", _make_monitor_result("AAPL", score=7.5, direction="bullish"))
        alert = get_pending_alerts()[0]
        assert alert["signal"]["score"]     == 7.5
        assert alert["signal"]["direction"] == "bullish"
        assert alert["signal"]["price"]     == 150.0

    def test_risk_fields_present(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts
        queue_alert("user:1", _make_monitor_result("AAPL", verdict_value="RESIZE", adjusted_qty=20))
        alert = get_pending_alerts()[0]
        assert alert["risk"]["verdict"]      == "RESIZE"
        assert alert["risk"]["adjusted_qty"] == 20

    def test_conv_ref_embedded_when_stored(self):
        from orchestrator.alert_manager import queue_alert, store_conversation_ref, get_pending_alerts
        store_conversation_ref("user:1", _SAMPLE_REF)
        queue_alert("user:1", _make_monitor_result())
        alert = get_pending_alerts()[0]
        assert alert["conversation_ref"] is not None
        assert alert["conversation_ref"]["channelId"] == "msteams"

    def test_conv_ref_is_none_when_not_stored(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts
        queue_alert("user:1", _make_monitor_result())
        alert = get_pending_alerts()[0]
        assert alert["conversation_ref"] is None

    def test_filter_by_user_id(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts
        queue_alert("user:1", _make_monitor_result("AAPL", "user:1"))
        queue_alert("user:2", _make_monitor_result("NVDA", "user:2"))
        alerts_u1 = get_pending_alerts(user_id="user:1")
        assert len(alerts_u1) == 1
        assert alerts_u1[0]["ticker"] == "AAPL"

    def test_returns_multiple_pending(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts
        queue_alert("user:1", _make_monitor_result("AAPL"))
        queue_alert("user:1", _make_monitor_result("NVDA"))
        assert len(get_pending_alerts()) == 2

    def test_empty_when_none_queued(self):
        from orchestrator.alert_manager import get_pending_alerts
        assert get_pending_alerts() == []


# ── mark_alert_delivered ──────────────────────────────────────────────────────

class TestMarkAlertDelivered:

    def test_delivered_alert_not_in_pending(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts, mark_alert_delivered
        alert_id = queue_alert("user:1", _make_monitor_result())
        mark_alert_delivered(alert_id)
        assert get_pending_alerts() == []

    def test_only_delivered_alert_removed(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts, mark_alert_delivered
        id1 = queue_alert("user:1", _make_monitor_result("AAPL"))
        _id2 = queue_alert("user:1", _make_monitor_result("NVDA"))
        mark_alert_delivered(id1)
        pending = get_pending_alerts()
        assert len(pending) == 1
        assert pending[0]["ticker"] == "NVDA"

    def test_idempotent_delivery(self):
        from orchestrator.alert_manager import queue_alert, get_pending_alerts, mark_alert_delivered
        alert_id = queue_alert("user:1", _make_monitor_result())
        mark_alert_delivered(alert_id)
        mark_alert_delivered(alert_id)  # second call should not raise
        assert get_pending_alerts() == []
