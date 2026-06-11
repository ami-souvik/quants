"""
Tests for ledger/cost_model.py — MIS (intraday) only.
CNC delivery is forbidden in Phase 1; all tests use TradeType.INTRADAY.
All charge rates verified against Zerodha's brokerage calculator (2025-2026).

Expected values for ₹50,000 MIS round-trip (both legs at same value):
  BUY:  brokerage ₹15 + txn ~₹1.49 + SEBI ~₹0.05 + stamp ₹1.50 + GST ~₹2.97 = ~₹21.01
  SELL: brokerage ₹15 + STT ₹12.50 + txn ~₹1.49 + SEBI ~₹0.05 + GST ~₹2.97 = ~₹32.01
  Round-trip: ~₹53 = ~10.6 bps
"""
from decimal import Decimal

import pytest

from trader.ledger.cost_model import (
    COST_HURDLE_BPS,
    TradeType,
    calculate_round_trip_cost,
    calculate_trade_cost,
    exceeds_cost_hurdle,
    slippage_amount,
)


class TestIntradayCosts:
    def test_intraday_stt_sell_only(self):
        """Intraday STT (0.025%) applies on SELL only."""
        buy = calculate_trade_cost(50_000, TradeType.INTRADAY, "BUY")
        sell = calculate_trade_cost(50_000, TradeType.INTRADAY, "SELL")
        assert buy.stt == Decimal("0"), "No STT on intraday BUY"
        expected_stt = Decimal("12.50")  # 0.025% of 50_000
        assert sell.stt == expected_stt, (
            f"Intraday SELL STT ₹{sell.stt} ≠ expected ₹{expected_stt}"
        )

    def test_intraday_no_dp_charges(self):
        """No DP charges for MIS trades — dp_charges field does not exist."""
        buy = calculate_trade_cost(50_000, TradeType.INTRADAY, "BUY")
        sell = calculate_trade_cost(50_000, TradeType.INTRADAY, "SELL")
        assert not hasattr(buy, "dp_charges"), "CostBreakdown must not have dp_charges field"
        assert not hasattr(sell, "dp_charges"), "CostBreakdown must not have dp_charges field"

    def test_intraday_brokerage_below_cap(self):
        """Trade value where 0.03% < ₹20: brokerage = 0.03% × value."""
        # 0.03% of ₹50,000 = ₹15 < ₹20 cap
        cost = calculate_trade_cost(50_000, TradeType.INTRADAY, "BUY")
        assert cost.brokerage == Decimal("15"), (
            f"Expected brokerage ₹15, got ₹{cost.brokerage}"
        )

    def test_intraday_brokerage_capped_at_20(self):
        """₹5,00,000 intraday: 0.03% = ₹150 → capped at ₹20."""
        cost = calculate_trade_cost(500_000, TradeType.INTRADAY, "BUY")
        assert cost.brokerage == Decimal("20"), (
            f"Brokerage should be capped at ₹20, got ₹{cost.brokerage}"
        )

    def test_intraday_round_trip_50k(self):
        """₹50,000 intraday BUY + SELL. Expected ~₹53 (10–12 bps)."""
        buy, sell, rt_bps = calculate_round_trip_cost(50_000, TradeType.INTRADAY)
        round_trip_total = buy.total + sell.total
        assert Decimal("45") <= round_trip_total <= Decimal("65"), (
            f"Intraday round-trip ₹{round_trip_total} outside expected ₹45–65"
        )
        assert Decimal("9") <= rt_bps <= Decimal("14"), (
            f"Intraday round-trip {rt_bps} bps outside expected 9–14 bps"
        )

    def test_intraday_stamp_duty_buy_only(self):
        """Intraday stamp duty (0.003%) applies on BUY only."""
        buy = calculate_trade_cost(50_000, TradeType.INTRADAY, "BUY")
        sell = calculate_trade_cost(50_000, TradeType.INTRADAY, "SELL")
        expected = Decimal("1.50")  # 0.003% of 50_000
        assert buy.stamp_duty == expected, (
            f"Expected stamp ₹{expected}, got ₹{buy.stamp_duty}"
        )
        assert sell.stamp_duty == Decimal("0"), "No stamp duty on SELL"

    def test_intraday_rt_bps_in_published_range(self):
        """Zerodha docs: intraday round-trip ~10.6 bps applies when brokerage < ₹20 cap.
        Use ₹50,000 to stay in the uncapped regime."""
        _, _, rt_bps = calculate_round_trip_cost(50_000, TradeType.INTRADAY)
        assert Decimal("9") <= rt_bps <= Decimal("14"), (
            f"Intraday RT {rt_bps} bps outside Zerodha published range 9–14"
        )


class TestGST:
    def test_gst_applies_to_brokerage_txn_sebi_only(self):
        """GST base = brokerage + exchange_txn + sebi_fee (NOT on STT or stamp)."""
        cost = calculate_trade_cost(50_000, TradeType.INTRADAY, "BUY")
        expected_gst_base = cost.brokerage + cost.exchange_txn + cost.sebi_fee
        expected_gst = (expected_gst_base * Decimal("0.18")).quantize(Decimal("0.01"))
        # Allow ₹0.01 rounding tolerance
        assert abs(cost.gst - expected_gst) <= Decimal("0.01"), (
            f"GST ₹{cost.gst} ≠ expected ₹{expected_gst}"
        )


class TestCostHurdle:
    def test_hurdle_is_13_bps(self):
        """COST_HURDLE_BPS must be 13."""
        assert COST_HURDLE_BPS == Decimal("13")

    def test_move_above_hurdle_passes(self):
        """Expected move of 20 bps exceeds the 13 bps hurdle."""
        assert exceeds_cost_hurdle(20) is True

    def test_move_below_hurdle_fails(self):
        """Expected move of 10 bps does not clear the 13 bps hurdle."""
        assert exceeds_cost_hurdle(10) is False

    def test_move_equal_to_hurdle_fails(self):
        """Exactly 13 bps is not strictly greater — trade should not be entered."""
        assert exceeds_cost_hurdle(13) is False

    def test_minimum_viable_move_is_14_bps(self):
        """14 bps clears the hurdle; 12 does not."""
        assert exceeds_cost_hurdle(14) is True
        assert exceeds_cost_hurdle(12) is False


class TestEdgeCases:
    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side must be"):
            calculate_trade_cost(50_000, TradeType.INTRADAY, "HOLD")

    def test_zero_trade_value_raises(self):
        with pytest.raises(ValueError, match="positive"):
            calculate_trade_cost(0, TradeType.INTRADAY, "BUY")

    def test_negative_trade_value_raises(self):
        with pytest.raises(ValueError, match="positive"):
            calculate_trade_cost(-1000, TradeType.INTRADAY, "BUY")

    def test_cnc_trade_type_does_not_exist(self):
        """TradeType.DELIVERY (CNC) must not exist — it was removed in the intraday pivot."""
        assert not hasattr(TradeType, "DELIVERY"), (
            "TradeType.DELIVERY must not exist in Phase 1 (CNC is forbidden)"
        )
        members = [t.value for t in TradeType]
        assert "CNC" not in members, f"CNC must not be a TradeType value; got {members}"

    def test_large_intraday_trade_value(self):
        """₹10 lakh intraday round-trip: brokerage capped at ₹20/leg → bps fall vs small trades."""
        _, _, rt_bps = calculate_round_trip_cost(1_000_000, TradeType.INTRADAY)
        # At ₹10L: brokerage ₹40 + STT ₹250 + txn ~₹5.94 + SEBI ~₹1 + stamp ₹3 + GST ~₹8 ≈ ₹308
        # 308 / 1_000_000 × 10000 ≈ 3.1 bps (brokerage cap means low bps for large trades)
        assert Decimal("2") <= rt_bps <= Decimal("6"), (
            f"Large intraday RT {rt_bps} bps outside expected 2–6 bps"
        )


class TestSlippage:
    def test_slippage_3bps(self):
        """3 bps slippage on ₹50,000 = ₹15."""
        slip = slippage_amount(50_000, bps=3)
        assert slip == Decimal("15.00")

    def test_slippage_default_is_3bps(self):
        assert slippage_amount(100_000) == Decimal("30.00")
