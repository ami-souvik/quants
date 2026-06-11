"""
Tests for the paper-trading ledger, circuit breakers, and MIS intraday constraints.

All tests run without DynamoDB/S3/Redis — purely in-memory ledger state.

Key MIS invariants tested:
  - All positions squared off same day (no overnight holdings)
  - EOD equity_value_inr is always 0
  - Max 5 concurrent intraday positions
  - Max 15% NAV per position
  - 5% daily drawdown halts new entries
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
    sector: str = "Energy",
) -> PaperTradingLedger:
    """Return a ledger with one open intraday position already in it."""
    ledger = _fresh_ledger()
    position_value = qty * avg_price
    ledger.cash_inr = _INITIAL_CAPITAL - position_value
    ledger.positions[ticker] = Position(
        ticker=ticker,
        sector=sector,
        qty=qty,
        avg_price=avg_price,
        entry_date=_TRADE_DATE,
        entry_time_ist="09:20",
        stop_loss_price=avg_price * 0.995,
        target_price=avg_price * 1.01,
        current_price=avg_price,
    )
    return ledger


# ── max_positions_enforced ────────────────────────────────────────────────────

class TestMaxPositionsEnforced:
    def test_buy_rejected_at_max_positions(self):
        """With 5 open intraday positions, a BUY must be rejected."""
        ledger = _fresh_ledger()
        tickers = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]

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
                entry_time_ist="09:20",
                stop_loss_price=share_price * 0.995,
                target_price=share_price * 1.01,
                current_price=share_price,
            )
        ledger.cash_inr = _INITIAL_CAPITAL - 5 * per_position_value

        fill = ledger.simulate_fill(
            ticker="HINDUNILVR",
            decision="BUY",
            quantity_shares=50,
            close_price=2400.0,
        )
        if fill:
            ledger.update_positions(fill)

        open_count = sum(1 for p in ledger.positions.values() if p.qty > 0)
        assert open_count == 5, f"Expected 5 open positions, got {open_count}"

    def test_squareoff_allowed_at_max_positions(self):
        """Squareoff should process even when at max positions."""
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
                entry_time_ist="09:20",
                stop_loss_price=share_price * 0.995,
                target_price=share_price * 1.01,
                current_price=share_price,
            )
        ledger.cash_inr = 0.0

        pre_cash = ledger.cash_inr
        trade = ledger.squareoff_position("RELIANCE", 510.0)

        assert trade is not None
        assert ledger.positions["RELIANCE"].qty == 0
        assert ledger.cash_inr > pre_cash


# ── max_position_size ─────────────────────────────────────────────────────────

class TestMaxPositionSize:
    def test_buy_within_budget_succeeds(self):
        """BUY that fits within cash should open a position."""
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill(
            ticker="RELIANCE",
            decision="BUY",
            quantity_shares=50,
            close_price=2500.0,
        )
        assert fill is not None
        assert fill.qty == 50

    def test_buy_rejected_when_cash_insufficient(self):
        """BUY that costs more than available cash is rejected by update_positions."""
        ledger = _fresh_ledger()
        ledger.cash_inr = 1000.0  # almost empty
        fill = ledger.simulate_fill(
            ticker="RELIANCE",
            decision="BUY",
            quantity_shares=500,
            close_price=2500.0,  # ₹1.25L — far exceeds ₹1000 cash
        )
        if fill:
            pre_positions = dict(ledger.positions)
            ledger.update_positions(fill)
            post = ledger.positions.get("RELIANCE")
            open_qty = post.qty if post else 0
            assert open_qty == 0


# ── NAV calculation ───────────────────────────────────────────────────────────

class TestNAVCalculation:
    def test_nav_with_no_positions(self):
        """NAV with no positions = initial capital."""
        ledger = _fresh_ledger()
        snap = ledger.calculate_nav()
        assert snap.nav_inr == pytest.approx(_INITIAL_CAPITAL, abs=1)
        assert snap.open_positions == 0
        assert snap.equity_value_inr == pytest.approx(0.0)

    def test_nav_with_one_position(self):
        """Intraday NAV = cash + mark-to-market position value."""
        ledger = _ledger_with_position(qty=10, avg_price=3000.0)
        snap = ledger.calculate_nav({"RELIANCE": 3200.0})
        expected_equity = 10 * 3200.0
        expected_nav = ledger.cash_inr + expected_equity
        assert snap.equity_value_inr == pytest.approx(expected_equity, abs=1)
        assert snap.nav_inr == pytest.approx(expected_nav, abs=1)

    def test_eod_nav_equity_is_zero(self):
        """End-of-day NAV must have equity_value_inr = 0 (all MIS squared off)."""
        ledger = _ledger_with_position(qty=10, avg_price=3000.0)
        snap = ledger.calculate_nav(eod=True)
        assert snap.equity_value_inr == pytest.approx(0.0), (
            "EOD equity_value_inr must be 0 — all MIS positions closed"
        )
        assert snap.open_positions == 0
        assert snap.nav_inr == pytest.approx(snap.cash_inr, abs=1)

    def test_cumulative_return_positive_on_gain(self):
        """Cumulative return is positive when NAV > initial capital."""
        ledger = _ledger_with_position(qty=100, avg_price=2800.0)
        snap = ledger.calculate_nav({"RELIANCE": 3000.0})
        assert snap.cumulative_return_pct > 0

    def test_drawdown_zero_when_at_peak(self):
        """Drawdown is 0 when NAV = peak."""
        ledger = _fresh_ledger()
        snap = ledger.calculate_nav()
        assert snap.drawdown_pct == pytest.approx(0.0)

    def test_drawdown_positive_after_loss(self):
        """Drawdown is positive when NAV < peak."""
        ledger = _fresh_ledger()
        ledger.peak_nav_inr = _INITIAL_CAPITAL
        ledger.cash_inr = _INITIAL_CAPITAL * 0.90
        snap = ledger.calculate_nav()
        assert snap.drawdown_pct == pytest.approx(10.0, abs=0.1)


# ── simulate_fill (BUY only) ──────────────────────────────────────────────────

class TestSimulateFill:
    def test_buy_fill_price_includes_slippage(self):
        """BUY fill price is close + 3 bps slippage."""
        ledger = _fresh_ledger()
        close = 2500.0
        fill = ledger.simulate_fill("RELIANCE", "BUY", 10, close)
        assert fill is not None
        assert fill.fill_price > close
        assert fill.fill_price == pytest.approx(close * (1 + 3 / 10_000), rel=1e-5)

    def test_skip_returns_none(self):
        """SKIP decision generates no fill."""
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "SKIP", 0, 2500.0)
        assert fill is None

    def test_non_buy_decision_returns_none(self):
        """Any non-BUY decision returns None."""
        ledger = _fresh_ledger()
        for decision in ("SKIP", "HOLD", "EXIT", "SQUAREOFF", ""):
            assert ledger.simulate_fill("RELIANCE", decision, 10, 2500.0) is None

    def test_fill_cost_includes_regulatory_and_slippage(self):
        """Total cost = regulatory charges + slippage INR."""
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "BUY", 10, 2500.0)
        assert fill is not None
        assert fill.total_cost_inr == pytest.approx(
            fill.regulatory_cost_inr + fill.slippage_inr, abs=0.01
        )

    def test_fill_product_type_is_mis(self):
        """All fills must have product_type MIS."""
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "BUY", 10, 2500.0)
        assert fill is not None
        assert fill.product_type == "MIS"


# ── squareoff ─────────────────────────────────────────────────────────────────

class TestSquareoff:
    def test_squareoff_fill_price_below_close(self):
        """Squareoff fill price is close − 3 bps slippage."""
        ledger = _ledger_with_position(qty=10, avg_price=2800.0)
        close = 2900.0
        trade = ledger.squareoff_position("RELIANCE", close)
        assert trade is not None
        assert trade.exit_price < close
        assert trade.exit_price == pytest.approx(close * (1 - 3 / 10_000), rel=1e-5)

    def test_squareoff_no_position_returns_none(self):
        """Squareoff on ticker with no open position returns None."""
        ledger = _fresh_ledger()
        trade = ledger.squareoff_position("RELIANCE", 2500.0)
        assert trade is None

    def test_squareoff_closes_position(self):
        """After squareoff, position qty is 0."""
        ledger = _ledger_with_position(qty=20, avg_price=2800.0)
        ledger.squareoff_position("RELIANCE", 2900.0)
        assert ledger.positions["RELIANCE"].qty == 0

    def test_squareoff_increases_cash(self):
        """Squareoff adds proceeds to cash."""
        ledger = _ledger_with_position(qty=20, avg_price=2800.0)
        pre_cash = ledger.cash_inr
        ledger.squareoff_position("RELIANCE", 2900.0)
        assert ledger.cash_inr > pre_cash

    def test_squareoff_all_closes_every_position(self):
        """squareoff_all_positions must close ALL open positions unconditionally."""
        ledger = _fresh_ledger()
        tickers = ["RELIANCE", "TCS", "HDFCBANK"]
        for t in tickers:
            ledger.positions[t] = Position(
                ticker=t, sector="Misc", qty=10,
                avg_price=500.0, entry_date=_TRADE_DATE,
                entry_time_ist="09:20", stop_loss_price=490.0,
                target_price=510.0, current_price=500.0,
            )
        ledger.cash_inr = _INITIAL_CAPITAL - 3 * 10 * 500.0

        prices = {"RELIANCE": 510.0, "TCS": 495.0, "HDFCBANK": 520.0}
        trades = ledger.squareoff_all_positions(prices)

        assert len(trades) == 3
        assert all(p.qty == 0 for p in ledger.positions.values())

    def test_squareoff_all_returns_zero_open_after_run(self):
        """After squareoff_all_positions, no open positions remain."""
        ledger = _ledger_with_position(qty=10, avg_price=2800.0)
        ledger.squareoff_all_positions({"RELIANCE": 2850.0})
        open_count = sum(1 for p in ledger.positions.values() if p.qty > 0)
        assert open_count == 0

    def test_eod_nav_equity_zero_after_squareoff(self):
        """After squareoff_all_positions, EOD NAV has equity_value = 0."""
        ledger = _ledger_with_position(qty=10, avg_price=2800.0)
        ledger.squareoff_all_positions({"RELIANCE": 2850.0})
        snap = ledger.calculate_nav(eod=True)
        assert snap.equity_value_inr == pytest.approx(0.0)
        assert snap.open_positions == 0

    def test_completed_trade_has_correct_fields(self):
        """CompletedTrade record has all required fields for DynamoDB write."""
        ledger = _ledger_with_position(qty=20, avg_price=2800.0)
        trade = ledger.squareoff_position("RELIANCE", 2850.0)
        assert trade is not None
        assert trade.ticker == "RELIANCE"
        assert trade.qty == 20
        assert trade.entry_price == pytest.approx(2800.0, abs=1)
        assert trade.exit_price == pytest.approx(2850.0 * (1 - 3 / 10_000), rel=1e-4)
        assert trade.exit_time_ist == "15:15"
        assert trade.was_squaredoff_auto is True
        assert trade.trade_date == _TRADE_DATE
        assert trade.trade_value_inr == pytest.approx(20 * 2800.0, abs=1)

    def test_profitable_trade_positive_net_pnl(self):
        """A position exited above entry price should show positive net P&L."""
        ledger = _ledger_with_position(qty=100, avg_price=1000.0)
        trade = ledger.squareoff_position("RELIANCE", 1020.0)  # +2%
        assert trade is not None
        assert trade.gross_pnl_inr > 0
        assert trade.net_pnl_inr > 0

    def test_losing_trade_negative_net_pnl(self):
        """A position exited below entry price should show negative net P&L."""
        ledger = _ledger_with_position(qty=100, avg_price=1000.0)
        trade = ledger.squareoff_position("RELIANCE", 985.0)  # −1.5%
        assert trade is not None
        assert trade.gross_pnl_inr < 0
        assert trade.net_pnl_inr < 0


# ── cash_tracking ─────────────────────────────────────────────────────────────

class TestCashTracking:
    def test_cash_decreases_on_buy(self):
        ledger = _fresh_ledger()
        fill = ledger.simulate_fill("RELIANCE", "BUY", 20, 2800.0)
        assert fill is not None
        ledger.update_positions(fill)
        expected_outlay = fill.trade_value_inr + fill.total_cost_inr
        assert ledger.cash_inr == pytest.approx(_INITIAL_CAPITAL - expected_outlay, abs=1)

    def test_cash_increases_on_squareoff(self):
        ledger = _ledger_with_position(qty=20, avg_price=2800.0)
        pre_cash = ledger.cash_inr
        ledger.squareoff_position("RELIANCE", 2900.0)
        assert ledger.cash_inr > pre_cash

    def test_position_closed_after_squareoff(self):
        ledger = _ledger_with_position(qty=20, avg_price=2800.0)
        ledger.squareoff_position("RELIANCE", 2900.0)
        assert ledger.positions["RELIANCE"].qty == 0


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
            drawdown_pct=5.5,
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
            daily_llm_cost_usd=1.01,
        )
        assert status.llm_cost_triggered is True

    def test_sector_cap_triggered_at_40pct(self):
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
