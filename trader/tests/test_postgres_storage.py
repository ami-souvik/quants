"""
Tests for PostgreSQL / Supabase storage layer.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from trader.storage import postgres


def test_serialize_for_json():
    from decimal import Decimal
    from datetime import date, datetime

    data = {
        "dec": Decimal("10.5"),
        "date": date(2026, 6, 1),
        "nested": {"val": Decimal("25.1234")},
        "list": [Decimal("1.1"), date(2026, 6, 2)],
    }
    serialized = postgres._serialize_for_json(data)
    assert serialized["dec"] == 10.5
    assert serialized["date"] == "2026-06-01"
    assert serialized["nested"]["val"] == 25.1234
    assert serialized["list"] == [1.1, "2026-06-02"]


def test_put_position_dry_run():
    with patch("trader.storage.postgres.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(dry_run=True)
        # Should not raise or connect to DB
        postgres.put_position({"ticker": "RELIANCE", "qty": 10, "avg_price": 2500.0})


def test_put_decision_dry_run():
    with patch("trader.storage.postgres.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(dry_run=True)
        postgres.put_decision({"date": "2026-06-01", "ticker": "TCS", "agent": "NewsSentiment", "decision": "BUY"})


def test_put_trade_dry_run():
    with patch("trader.storage.postgres.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(dry_run=True)
        postgres.put_trade({"ticker": "INFY", "side": "BUY", "qty": 15, "price": 1800.0, "trade_value_inr": 27000.0})


def test_put_nav_dry_run():
    with patch("trader.storage.postgres.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(dry_run=True)
        postgres.put_nav({"date": "2026-06-01", "nav_inr": 1000000.0, "cash_inr": 1000000.0, "equity_value_inr": 0.0})
