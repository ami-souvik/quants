"""
Indian equity transaction cost calculator (NSE, 2025-2026).
MIS (intraday) only — CNC delivery is explicitly forbidden in Phase 1.
All charges verified against Zerodha's published brokerage calculator.

Key references:
- STT: intraday SELL 0.025% (MIS); buy side STT is zero for intraday
- NSE txn charge: 0.00297% (both sides)
- SEBI fee: ₹10 per crore = 0.0001%
- Stamp duty: Finance Act 2019 — 0.003% on BUY only for intraday
- DP charges: ₹0 for MIS — no actual delivery takes place
- GST: 18% on brokerage + exchange txn + SEBI fee

Round-trip benchmark (pure regulatory charges, no slippage):
  Intraday (MIS): ~10–11 bps
Add 3 bps slippage per leg → effective ~13 bps realistic hurdle.
Minimum expected intraday move to be worth trading: > 13 bps (0.13%).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum


class TradeType(Enum):
    INTRADAY = "MIS"  # Only mode in Phase 1 — CNC is forbidden


# ─── Charge rates (as Decimal for precision) ────────────────────────────────

# STT — intraday SELL only (buy side is zero for MIS)
_STT_INTRADAY_SELL = Decimal("0.00025")  # 0.025% on sell only

# NSE exchange transaction charge
_NSE_TXN = Decimal("0.0000297")       # 0.00297% on turnover

# SEBI fee
_SEBI_FEE = Decimal("0.000001")       # ₹10/crore = 0.0001% = 0.000001

# Stamp duty — intraday BUY only
_STAMP_INTRADAY_BUY = Decimal("0.00003")   # 0.003% on buy

# GST on (brokerage + exchange txn + SEBI)
_GST = Decimal("0.18")

# Zerodha intraday brokerage
_ZERODHA_INTRADAY_RATE = Decimal("0.0003")  # 0.03% per order
_ZERODHA_INTRADAY_MAX = Decimal("20")        # capped at ₹20

# Slippage allowance for large-cap NSE stocks (per leg)
SLIPPAGE_BPS = Decimal("3")

# Cost hurdle: minimum expected intraday move to justify entering a trade.
# = regulatory charges (~10.6 bps) + 2 × slippage (3 bps each leg) ≈ 13 bps.
COST_HURDLE_BPS = Decimal("13")


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: Decimal
    stt: Decimal
    exchange_txn: Decimal
    gst: Decimal
    sebi_fee: Decimal
    stamp_duty: Decimal
    total: Decimal        # sum of all regulatory charges (no slippage)
    total_bps: Decimal   # total / trade_value × 10000


def _d(value: float | int | str) -> Decimal:
    return Decimal(str(value))


def calculate_trade_cost(
    trade_value_inr: float,
    trade_type: TradeType,
    side: str,
    broker: str = "zerodha",
) -> CostBreakdown:
    """
    Compute the full MIS cost breakdown for a single equity leg on NSE (2025-2026).

    Args:
        trade_value_inr: Gross trade value in INR (price × quantity).
        trade_type:      Must be TradeType.INTRADAY (MIS). CNC is forbidden in Phase 1.
        side:            "BUY" or "SELL".
        broker:          Currently only "zerodha" is modelled.

    Returns:
        CostBreakdown with all components in INR and total_bps (10 000ths of trade value).

    Note:
        Does NOT include slippage. Add SLIPPAGE_BPS (3 bps) per leg for realistic fills.
        See ledger/paper_trade.py for combined cost + slippage simulation.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be 'BUY' or 'SELL', got: {side!r}")
    if trade_value_inr <= 0:
        raise ValueError("trade_value_inr must be positive")
    if trade_type != TradeType.INTRADAY:
        raise ValueError(
            f"trade_type must be TradeType.INTRADAY (MIS). "
            f"CNC delivery is forbidden in Phase 1. Got: {trade_type}"
        )

    tv = _d(trade_value_inr)
    is_buy = side == "BUY"

    raw_brokerage = tv * _ZERODHA_INTRADAY_RATE
    brokerage = min(raw_brokerage, _ZERODHA_INTRADAY_MAX)
    stt = (tv * _STT_INTRADAY_SELL) if not is_buy else Decimal("0")
    stamp_duty = (tv * _STAMP_INTRADAY_BUY) if is_buy else Decimal("0")
    # DP charges are always ₹0 for MIS — no actual delivery takes place

    exchange_txn = tv * _NSE_TXN
    sebi_fee = tv * _SEBI_FEE
    gst = (brokerage + exchange_txn + sebi_fee) * _GST

    total = brokerage + stt + exchange_txn + gst + sebi_fee + stamp_duty
    total_bps = (total / tv * Decimal("10000")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return CostBreakdown(
        brokerage=brokerage.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        stt=stt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        exchange_txn=exchange_txn.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        gst=gst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        sebi_fee=sebi_fee.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        stamp_duty=stamp_duty.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        total=total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        total_bps=total_bps,
    )


def calculate_round_trip_cost(
    trade_value_inr: float,
    trade_type: TradeType,
    broker: str = "zerodha",
) -> tuple[CostBreakdown, CostBreakdown, Decimal]:
    """
    Convenience helper: returns (buy_cost, sell_cost, round_trip_bps).
    Assumes same trade_value for both legs (ignores P&L on the position).
    """
    buy_cost = calculate_trade_cost(trade_value_inr, trade_type, "BUY", broker)
    sell_cost = calculate_trade_cost(trade_value_inr, trade_type, "SELL", broker)
    total = buy_cost.total + sell_cost.total
    tv = _d(trade_value_inr)
    round_trip_bps = (total / tv * Decimal("10000")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return buy_cost, sell_cost, round_trip_bps


def slippage_amount(trade_value_inr: float, bps: int = 3) -> Decimal:
    """Return the INR slippage cost at the given bps rate."""
    return (_d(trade_value_inr) * _d(bps) / Decimal("10000")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def exceeds_cost_hurdle(expected_move_bps: float) -> bool:
    """
    Return True if the expected intraday move is large enough to clear the MIS
    round-trip cost hurdle (~13 bps = ~10.6 bps regulatory + 6 bps slippage).
    The Portfolio Manager must not enter a trade that fails this check.
    """
    return _d(expected_move_bps) > COST_HURDLE_BPS
