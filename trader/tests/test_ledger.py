"""
Tests for the paper-trading ledger, circuit breakers, and related constraints.

All tests run without DynamoDB/S3 — purely in-memory ledger state.
"""
from __future__ import annotations

import pytest

from trader.config.settings import get_settings
from trader.ledger.circuit_breaker import (
    CircuitBreakerStatus,
    check_circuit_breakers,
    enforce_decision,
)
from trader.ledger.paper_trade import PaperTradingLedger, Position, SimulatedFill


# ── Helpers ───────────────────────────────────────────────────────────────────

_TRADE_DATE = "2026-05-26"
_INITIAL_CAPITAL = 1_000_000.0  # ₹10 lakh


def _fresh_ledger() -> PaperTradingLedger:
    return PaperTradingLedger.from_scratch(_TRADE_DATE)


def _ledger_with_position(
    ticker: str = "RELIANCE",
    qty: int = 20,
    avg_price: float = 2800.0,
    days_held: int = 1,
    sector: str = "Energy",
) -> PaperTradingLedger:
    """Return a ledger with one open position already in it."""
    ledger = _fresh_ledger()
    position_value = qty * avg_price
    ledger.cash_inr = _INITIAL_CAPITAL - position_value
    ledger.positions[ticker] = Position(
        ticker=ticker,
        sector=sector,
        qty=qty,
        avg_price=avg_price,
        entry_date=_TRADE_DATE,
        days_held=days_held,
        stop_loss_price=avg_price * 0.95,
        target_price=avg_price * 1.05,
        current_price=avg_price,
    )
    return ledger


# ── max_positions_enforced ────────────────────────────────────────────────────

class TestMaxPositionsEnforced:
    def test_buy_rejected_at_max_positions(self):
        """With 5 open positions, a BUY decision must be rejected."""
        ledger = _fresh_ledger()
        tickers = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]

        # Open 5 positions, each costing ₹1 lakh
        per_position_value = 100_000.0
        share_price = 500.0
        qty = int(per_position_value / share_price)

        for t in tickers:
            ledger.positions[t] = Position(
                ticker=t,
                sector="Misc",
                qty=qty,
                avg_price=share_price,
                entry_date=_TRADE_DATE,
                days_held=0,
                stop_loss_price=share_price * 0.95,
                target_price=share_price * 1.05,
                current_price=share_price,
            )
        ledger.cash_inr = _INITIAL_CAPITAL - 5 * per_position_value

        pre_fills = len(ledger.fills)
        fill = ledger.simulate_fill(
            ticker="HINDUNILVR",
            decision="BUY",
            quantity_shares=50,
            close_price=2400.0,
        )
        if fill:
            ledger.update_positions(fill)

        # update_positions rejects when at max — fills list stays unchanged
        open_count = sum(1 for p in ledger.positions.values() if p.qty > 0)
        assert open_count == 5  # not 6

    def test_exit_allowed_at_max_positions(self):
        """EXIT should be processed even when at max positions."""
        ledger = _fresh_ledger()
        tickers = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]
        share_price = 500.0
        qty = 200

        for t in tickers:
            ledger.positions[t] = Position(
                ticker=t,
                sector="Misc",
                qty=qty,
                avg_price=share_price,
                entry_date=_TRADE_DATE,
                days_held=1,
                stop_loss_price=share_price * 0.95,
                target_price=share_price * 1.05,
                current_price=share_price,
            )
        ledger.cash_inr = 0.0

        pre_cash = ledger.cash_inr
        fill = ledger.simulate_fill(
            ticker="RELIANCE",
            decision="EXIT",
            quantity_shares=0,
            close_price=510.0,
        )
        if fill:
            ledger.update_positions(fill)

        assert ledger.positions["RELIANCE"].qty == 0
        assert ledger.cash_inr > pre_cash


# ── max_position_size ─────────────────────────────────────────────────────────

class TestMaxPositionSize:
    def test_buy_within_budget_succeeds(self):
        """BUY that fits within cash should open a position."""
        ledger = _fresh_ledger()
        # 15% of ₹10L = ₹1.5L; buying 50 shares @ ₹2500 = ₹1.25L (fits)
        fill = ledger.simulate_fill(
            ticker="RELIANCE",
            decision="BUY",
            quantity_shares=50,
            close_price=2500.0,
        )
        assert fill is not None
        assert fill.qty == 50

    def test_buy_rejected_when_cash_insufficient(self):
        """BUY that costs more than available cash should be rejected by update_positions."""
        ledger = _fresh_ledger()
        ledger.cash_inr = 1000.0  # almost empty
        fill = ledger.simulate_fill(
            ticker="RELIANCE",
            decision="BUY",
            quantity_shares=500,
            close_price=2500.0,  # ₹1.25L — exceeds ₹1000 cash
        )
        if fill:
            pre_qty = ledger.positions.get("RELIANCE", Position(
                ticker="RELIANCE", sector="Energy", qty=0, avg_price=0,
                entry_date=_TRADE_DATE, days_held=0, stop_loss_price=0, target_price=0,
            )).qty
            ledger.update_positions(fill)
            post = ledger.positions.get("RELIANCE")
            # either the fill was removed or the qty didn't increase
            open_qty = post.qty if post else 0
            assert open_qty == pre_qty


# ── auto_exit_held_too_long ───────────────────────────────────────────────────

class TestAutoExitHeldTooLong:
    def test_advance_day_caps_days_held(self):
        """advance_day caps days_held at max_hold_days to signal auto-exit readiness."""
        from trader.config.settings import get_settings
        settings = get_settings()
        max_days = settings.max_hold_days

        ledger = _ledger_with_position(days_held=max_days)
        ledger.advance_day({"RELIANCE": 2850.0})

        pos = ledger.positions["RELIANCE"]
        # After advance_day increments, days_held == max_days (capped)
        assert pos.days_held == max_days

    def test_days_held_increments_on_advance(self):
        """advance_day increments days_held for open positions."""
        ledger = _ledger_with_position(days_held=2)
        ledger.advance_day({"RELIANCE": 2850.0})
        assert ledger.positions["RELIANCE"].days_held == 3

    def test_closed_position_not_incremented(self):
        """Closed positions (qty=0) are not incremented."""
        ledger = _ledger_with_position(days_held=1)
        ledger.positions["RELIANCE"].qty = 0
        ledger.advance_day({"RELIANCE": 2850.0})
        assert ledger.positions["RELIANCE"].days_held == 1  # unchanged


# ── nav_calculation ───────────────────────────────────────────────────────────

class TestNAVCalculation:
    def test_nav_with_no_positions(self):
        """NAV with no positions = initial capital."""
        ledger = _fresh_ledger()
        snap = ledger.calculate_nav({})
        assert snap.nav_inr == pytest.approx(_INITIAL_CAPITAL, abs=1)
        assert snap.open_positions == 0
        assert snap.equity_value_inr == pytest.approx(0.0)

    def test_nav_with_one_position(self):
        """NAV = cash + position_value using current price."""
        ledger = _ledger_with_position(qty=10, avg_price=3000.0)
        # position_value = 10 × 3000 = 30,000; cash = 1,000,000 - 30,000 = 970,000
        snap = ledger.calculate_nav({"RELIANCE": 3200.0})  # price moved up
        expected_equity = 10 * 3200.0
        expected_nav = ledger.cash_inr + expected_equity
        assert snap.equity_value_inr == pytest.approx(expected_equity, abs=1)
        assert snap.nav_inr == pytest.approx(expected_nav, abs=1)

    def test_cumulative_return_positive_on_gain(self):
        """Cumulative return is positive when NAV > initial capital."""
        ledger = _ledger_with_position(qty=100, avg_price=2800.0)
        snap = ledger.calculate_nav({"RELIANCE": 3000.0})  # unrealised gain
        assert snap.cumulative_return_pct > 0

    def test_drawdown_zero_when_at_peak(self):
        """Drawdown is 0 when NAV equals or exceeds peak."""
        ledger = _fresh_ledger()
        snap = ledger.calculate_nav({})
        assert snap.drawdown_pct == pytest.approx(0.0)

    def test_drawdown_positive_after_loss(self):
        """Drawdown is positive when NAV < peak."""
        ledger = _fresh_ledger()
        ledger.peak_nav_inr = _INITIAL_CAPITAL  # peak = initial
        ledger.cash_inr = _INITIAL_CAPITAL * 0.90  # simulate 10% loss
        snap = ledger.calculate_nav({})
        assert snap.drawdown_pct == pytest.approx(10.0, abs=0.1)


# ── simulate_fill ─────────────────────────────────────────────────────────────

class TestSimulateFill:
    def test_buy_fill_price_includes_slippage(self):
        """BUY fill price is slightly above close (3 bps slippage)."""
        ledger = _fresh_ledger()
        close = 2500.0
        fill = ledger.simulate_fill("RELIANCE", "BUY", 10, close)
        assert fill is not None
        assert fill.fill_price > close
        assert fill.fill_price == pytest.approx(close * (1 + 3 / 10_000), rel=1e-5)

    def test_exit_fill_price_below_close(self):
        """EXIT fill price is slightly below close (3 bps slippage)."""
        ledger = _ledger_with_position(qty=10, avg_price=2800.0)
        close = 2900.0
        fill = ledger.simulate_fill("RELIANCE", "EXIT", 0, close)
        assert fill is not None
        assert fill.fill_price < close

    def test_hold_returns_none(self):
        """HOLD decision generates no fill."""
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "HOLD", 0, 2500.0)
        assert fill is None

    def test_skip_returns_none(self):
        """SKIP decision generates no fill."""
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "SKIP", 0, 2500.0)
        assert fill is None

    def test_exit_without_position_returns_none(self):
        """EXIT on a ticker with no position returns None."""
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "EXIT", 0, 2500.0)
        assert fill is None

    def test_fill_cost_includes_regulatory_and_slippage(self):
        """Total cost = regulatory charges + slippage INR."""
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "BUY", 10, 2500.0)
        assert fill is not None
        assert fill.total_cost_inr == pytest.approx(
            fill.regulatory_cost_inr + fill.slippage_inr, abs=0.01
        )


# ── circuit_breakers ──────────────────────────────────────────────────────────

class TestCircuitBreakers:
    def _positions(self, ticker: str, qty: int, price: float, sector: str = "Energy") -> dict:
        return {
            ticker: {
                "qty": qty,
                "avg_price": price,
                "current_price": price,
                "sector": sector,
            }
        }

    def test_drawdown_triggered_at_5pct(self, monkeypatch):
        """Intraday daily drawdown breaker fires at >= 5% of opening NAV."""
        monkeypatch.setattr(get_settings(), "circuit_breaker_drawdown", 0.05)
        status = check_circuit_breakers(
            ticker="RELIANCE",
            ticker_sector="Energy",
            is_restricted=False,
            drawdown_pct=5.5,        # ≥5%
            nav_inr=1_000_000.0,
            positions={},
            daily_llm_cost_usd=0.0,
        )
        assert status.drawdown_triggered is True
        assert status.blocks_new_buy is True

    def test_drawdown_not_triggered_below_5pct(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "circuit_breaker_drawdown", 0.05)
        status = check_circuit_breakers(
            ticker="RELIANCE",
            ticker_sector="Energy",
            is_restricted=False,
            drawdown_pct=4.9,
            nav_inr=1_000_000.0,
            positions={},
            daily_llm_cost_usd=0.0,
        )
        assert status.drawdown_triggered is False

    def test_restricted_triggered(self):
        status = check_circuit_breakers(
            ticker="RELIANCE",
            ticker_sector="Energy",
            is_restricted=True,
            drawdown_pct=0.0,
            nav_inr=1_000_000.0,
            positions={},
            daily_llm_cost_usd=0.0,
        )
        assert status.restricted_triggered is True

    def test_llm_cost_triggered_at_budget(self):
        status = check_circuit_breakers(
            ticker="RELIANCE",
            ticker_sector="Energy",
            is_restricted=False,
            drawdown_pct=0.0,
            nav_inr=1_000_000.0,
            positions={},
            daily_llm_cost_usd=1.01,  # over $1 budget
        )
        assert status.llm_cost_triggered is True

    def test_sector_cap_triggered_at_40pct(self):
        # Energy sector = ₹420,000 out of NAV ₹1,000,000 = 42% → triggers
        positions = self._positions("RELIANCE", qty=100, price=4200.0, sector="Energy")
        status = check_circuit_breakers(
            ticker="ADANIENT",
            ticker_sector="Energy",
            is_restricted=False,
            drawdown_pct=0.0,
            nav_inr=1_000_000.0,
            positions=positions,
            daily_llm_cost_usd=0.0,
        )
        assert status.sector_cap_triggered is True

    def test_sector_cap_not_triggered_below_40pct(self):
        # Energy sector = ₹350,000 / ₹1,000,000 = 35% → OK
        positions = self._positions("RELIANCE", qty=100, price=3500.0, sector="Energy")
        status = check_circuit_breakers(
            ticker="ADANIENT",
            ticker_sector="Energy",
            is_restricted=False,
            drawdown_pct=0.0,
            nav_inr=1_000_000.0,
            positions=positions,
            daily_llm_cost_usd=0.0,
        )
        assert status.sector_cap_triggered is False

    def test_enforce_buy_blocked_on_drawdown(self):
        status = CircuitBreakerStatus(drawdown_triggered=True)
        decision, rationale = enforce_decision("BUY", status)
        assert decision == "HOLD"
        assert rationale == "DRAWDOWN"

    def test_enforce_exit_passes_through(self):
        status = CircuitBreakerStatus(drawdown_triggered=True)
        decision, rationale = enforce_decision("EXIT", status)
        assert decision == "EXIT"

    def test_enforce_hold_passes_through(self):
        status = CircuitBreakerStatus(sector_cap_triggered=True)
        decision, rationale = enforce_decision("HOLD", status)
        assert decision == "HOLD"

    def test_enforce_restricted_forces_exit(self):
        status = CircuitBreakerStatus(restricted_triggered=True)
        decision, rationale = enforce_decision("BUY", status)
        assert decision == "EXIT"
        assert rationale == "RESTRICTED"

    def test_enforce_no_breakers_passes_through(self):
        status = CircuitBreakerStatus()
        decision, rationale = enforce_decision("BUY", status)
        assert decision == "BUY"
        assert rationale == ""


# ── ledger_cash_tracking ──────────────────────────────────────────────────────

class TestCashTracking:
    def test_cash_decreases_on_buy(self):
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "BUY", 20, 2800.0)
        assert fill is not None
        ledger.update_positions(fill)
        expected_outlay = fill.trade_value_inr + fill.total_cost_inr
        assert ledger.cash_inr == pytest.approx(_INITIAL_CAPITAL - expected_outlay, abs=1)

    def test_cash_increases_on_exit(self):
        ledger = _ledger_with_position(qty=20, avg_price=2800.0)
        pre_cash = ledger.cash_inr
        fill = ledger.simulate_fill("RELIANCE", "EXIT", 0, 2900.0)
        assert fill is not None
        ledger.update_positions(fill)
        expected_proceeds = fill.trade_value_inr - fill.total_cost_inr
        assert ledger.cash_inr == pytest.approx(pre_cash + expected_proceeds, abs=1)

    def test_position_closed_after_exit(self):
        ledger = _ledger_with_position(qty=20, avg_price=2800.0)
        fill = ledger.simulate_fill("RELIANCE", "EXIT", 0, 2900.0)
        assert fill is not None
        ledger.update_positions(fill)
        assert ledger.positions["RELIANCE"].qty == 0
