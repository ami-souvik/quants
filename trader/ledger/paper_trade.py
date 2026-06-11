"""
Paper-trading ledger: simulated fills, position management, NAV calculation.

All fills are SIMULATED — no broker API is called in Phase 1.

Fill price policy:
  BUY  → yesterday's close + 3 bps slippage
  EXIT → yesterday's close − 3 bps slippage (unfavourable for seller)
  HOLD / SKIP → no fill generated

Position state is maintained in memory during a single daily run and
persisted to DynamoDB after each ticker via the orchestration layer.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from trader.config.settings import get_settings
from trader.config.tickers import get_ticker
from trader.ledger.circuit_breaker import (
    CircuitBreakerStatus,
    check_circuit_breakers,
    enforce_decision,
)
from trader.ledger.cost_model import (
    TradeType,
    calculate_trade_cost,
    slippage_amount,
)

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class Position:
    ticker: str
    sector: str
    qty: int
    avg_price: float
    entry_date: str           # "yyyy-mm-dd"
    days_held: int
    stop_loss_price: float
    target_price: float
    kill_conditions: list[str] = field(default_factory=list)
    horizon_days: int = 3
    current_price: float = 0.0  # updated each day before NAV calculation


@dataclass
class SimulatedFill:
    ticker: str
    side: str                 # "BUY" or "EXIT"
    qty: int
    fill_price: float         # close price ± slippage
    trade_value_inr: float
    regulatory_cost_inr: float
    slippage_inr: float
    total_cost_inr: float     # regulatory + slippage
    cost_bps: float           # total / trade_value × 10000
    product_type: str         # always "MIS" — CNC is forbidden in Phase 1
    trade_id: str
    trade_date: str           # "yyyy-mm-dd"

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "side": self.side,
            "qty": self.qty,
            "fill_price": self.fill_price,
            "trade_value_inr": self.trade_value_inr,
            "regulatory_cost_inr": self.regulatory_cost_inr,
            "slippage_inr": self.slippage_inr,
            "total_cost_inr": self.total_cost_inr,
            "cost_bps": self.cost_bps,
            "product_type": self.product_type,
            "trade_id": self.trade_id,
            "trade_date": self.trade_date,
        }


@dataclass
class NAVSnapshot:
    nav_inr: float
    cash_inr: float
    equity_value_inr: float
    open_positions: int
    daily_return_pct: float
    cumulative_return_pct: float
    drawdown_pct: float           # positive value; 0 = no drawdown
    peak_nav_inr: float

    def as_dict(self) -> dict:
        return {
            "nav_inr": self.nav_inr,
            "cash_inr": self.cash_inr,
            "equity_value_inr": self.equity_value_inr,
            "open_positions": self.open_positions,
            "daily_return_pct": self.daily_return_pct,
            "cumulative_return_pct": self.cumulative_return_pct,
            "drawdown_pct": self.drawdown_pct,
            "peak_nav_inr": self.peak_nav_inr,
        }


# ── PaperTradingLedger ─────────────────────────────────────────────────────────

class PaperTradingLedger:
    """
    Maintains the in-memory paper-trading portfolio state during a daily run.

    Lifecycle:
      1. Instantiate with the persisted state from DynamoDB (or initial state).
      2. For each ticker: call simulate_fill() → update_positions().
      3. At end of run: call calculate_nav() → persist the NAV snapshot.
    """

    def __init__(
        self,
        cash_inr: float,
        positions: dict[str, Position],
        peak_nav_inr: float,
        initial_capital_inr: float,
        trade_date: str,
    ) -> None:
        self._settings = get_settings()
        self.cash_inr = cash_inr
        self.positions: dict[str, Position] = positions  # ticker → Position
        self.peak_nav_inr = peak_nav_inr
        self.initial_capital = initial_capital_inr
        self.trade_date = trade_date
        self.fills: list[SimulatedFill] = []

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_scratch(cls, trade_date: str) -> "PaperTradingLedger":
        """Create a fresh ledger with initial capital, no positions."""
        settings = get_settings()
        capital = settings.initial_capital_inr
        return cls(
            cash_inr=capital,
            positions={},
            peak_nav_inr=capital,
            initial_capital_inr=capital,
            trade_date=trade_date,
        )

    @classmethod
    def from_dynamo_snapshot(
        cls,
        nav_item: dict,
        position_items: list[dict],
        trade_date: str,
    ) -> "PaperTradingLedger":
        """Reconstruct the ledger from DynamoDB items persisted at end of previous run."""
        settings = get_settings()

        positions: dict[str, Position] = {}
        for item in position_items:
            ticker = item["PK"].removeprefix("TICKER#")
            try:
                sector = get_ticker(ticker).sector
            except ValueError:
                sector = "Unknown"
            positions[ticker] = Position(
                ticker=ticker,
                sector=sector,
                qty=int(item.get("qty", 0)),
                avg_price=float(item.get("avg_price", 0)),
                entry_date=item.get("entry_date", trade_date),
                days_held=int(item.get("days_held", 0)),
                stop_loss_price=float(item.get("stop_loss_price", 0)),
                target_price=float(item.get("target_price", 0)),
                kill_conditions=list(item.get("kill_conditions", [])),
                horizon_days=int(item.get("horizon_days", 3)),
                current_price=float(item.get("avg_price", 0)),
            )

        cash = float(nav_item.get("cash_inr", settings.initial_capital_inr))
        peak = float(nav_item.get("peak_nav_inr", nav_item.get("nav_inr", settings.initial_capital_inr)))

        return cls(
            cash_inr=cash,
            positions=positions,
            peak_nav_inr=peak,
            initial_capital_inr=settings.initial_capital_inr,
            trade_date=trade_date,
        )

    # ── Portfolio snapshot (input to PM agent) ────────────────────────────────

    def portfolio_snapshot(self, current_prices: dict[str, float] | None = None) -> dict:
        """
        Return a dict summarising the portfolio for use as PM agent context.
        Pass current_prices to get accurate NAV; omit to use avg_price as proxy.
        """
        self._update_current_prices(current_prices or {})
        nav = self._nav_inr()
        equity = sum(
            p.qty * p.current_price for p in self.positions.values() if p.qty > 0
        )
        drawdown = self._drawdown_pct(nav)
        return {
            "cash_inr": self.cash_inr,
            "equity_value_inr": equity,
            "nav_inr": nav,
            "open_positions": len([p for p in self.positions.values() if p.qty > 0]),
            "drawdown_pct": drawdown,
        }

    def current_position_for(self, ticker: str) -> dict:
        """Return the current position for a ticker, or empty dict if none."""
        pos = self.positions.get(ticker)
        if pos is None or pos.qty == 0:
            return {}
        return {
            "qty": pos.qty,
            "avg_price": pos.avg_price,
            "entry_date": pos.entry_date,
            "days_held": pos.days_held,
            "stop_loss_price": pos.stop_loss_price,
            "target_price": pos.target_price,
            "kill_conditions": pos.kill_conditions,
        }

    # ── Fill simulation ───────────────────────────────────────────────────────

    def simulate_fill(
        self,
        ticker: str,
        decision: str,
        quantity_shares: int,
        close_price: float,
        stop_loss_price: float = 0.0,
        target_price: float = 0.0,
        kill_conditions: list[str] | None = None,
        horizon_days: int = 3,
    ) -> SimulatedFill | None:
        """
        Simulate a trade fill based on the PM decision.

        Returns a SimulatedFill for BUY or EXIT decisions; None for HOLD/SKIP.
        Fill price = close_price ± 3 bps slippage.
        """
        if decision not in ("BUY", "EXIT"):
            return None

        if quantity_shares <= 0 and decision == "BUY":
            logger.warning("[ledger] BUY with qty=0 for %s — skipping fill", ticker)
            return None

        # Apply slippage: BUY pays more, EXIT receives less
        slippage_bps = 3
        if decision == "BUY":
            fill_price = close_price * (1 + slippage_bps / 10_000)
            qty = quantity_shares
        else:
            # EXIT: close out the current position
            pos = self.positions.get(ticker)
            if pos is None or pos.qty == 0:
                logger.warning("[ledger] EXIT for %s but no open position", ticker)
                return None
            fill_price = close_price * (1 - slippage_bps / 10_000)
            qty = pos.qty

        trade_value = fill_price * qty
        slippage_inr = float(slippage_amount(trade_value, bps=slippage_bps))

        side = "BUY" if decision == "BUY" else "SELL"
        cost_breakdown = calculate_trade_cost(trade_value, TradeType.INTRADAY, side)
        regulatory_cost = float(cost_breakdown.total)
        total_cost = regulatory_cost + slippage_inr
        cost_bps = (total_cost / trade_value * 10_000) if trade_value > 0 else 0.0

        fill = SimulatedFill(
            ticker=ticker,
            side=side,
            qty=qty,
            fill_price=round(fill_price, 2),
            trade_value_inr=round(trade_value, 2),
            regulatory_cost_inr=round(regulatory_cost, 2),
            slippage_inr=round(slippage_inr, 2),
            total_cost_inr=round(total_cost, 2),
            cost_bps=round(cost_bps, 2),
            product_type="MIS",
            trade_id=str(uuid.uuid4()),
            trade_date=self.trade_date,
        )

        logger.info(
            "[ledger] Fill: %s %s %d @ %.2f (TV=₹%.0f, cost=₹%.2f / %.1f bps)",
            ticker, side, qty, fill_price, trade_value, total_cost, cost_bps,
        )
        self.fills.append(fill)
        return fill

    def update_positions(
        self,
        fill: SimulatedFill,
        stop_loss_price: float = 0.0,
        target_price: float = 0.0,
        kill_conditions: list[str] | None = None,
        horizon_days: int = 3,
    ) -> None:
        """
        Apply a fill to the in-memory position book and adjust cash.

        BUY  → open or add to position; deduct cash
        SELL → close position; add proceeds to cash
        """
        settings = self._settings
        ticker = fill.ticker

        if fill.side == "BUY":
            total_outlay = fill.trade_value_inr + fill.total_cost_inr

            # Enforce max-positions limit
            open_count = sum(1 for p in self.positions.values() if p.qty > 0)
            if ticker not in self.positions and open_count >= settings.max_open_positions:
                logger.warning(
                    "[ledger] Max positions (%d) reached — BUY for %s rejected",
                    settings.max_open_positions, ticker,
                )
                self.fills.pop()  # remove the fill we just added
                return

            if total_outlay > self.cash_inr + 1:  # 1 INR tolerance for rounding
                logger.warning(
                    "[ledger] Insufficient cash for %s BUY (need ₹%.0f, have ₹%.0f)",
                    ticker, total_outlay, self.cash_inr,
                )
                self.fills.pop()
                return

            existing = self.positions.get(ticker)
            if existing and existing.qty > 0:
                # Add to existing position (weighted avg price)
                total_qty = existing.qty + fill.qty
                new_avg = (existing.avg_price * existing.qty + fill.fill_price * fill.qty) / total_qty
                existing.qty = total_qty
                existing.avg_price = round(new_avg, 2)
            else:
                try:
                    sector = get_ticker(ticker).sector
                except ValueError:
                    sector = "Unknown"
                self.positions[ticker] = Position(
                    ticker=ticker,
                    sector=sector,
                    qty=fill.qty,
                    avg_price=fill.fill_price,
                    entry_date=self.trade_date,
                    days_held=0,
                    stop_loss_price=stop_loss_price,
                    target_price=target_price,
                    kill_conditions=kill_conditions or [],
                    horizon_days=horizon_days,
                    current_price=fill.fill_price,
                )

            self.cash_inr -= total_outlay
            self.cash_inr = round(self.cash_inr, 2)

        elif fill.side == "SELL":
            pos = self.positions.get(ticker)
            if pos is None or pos.qty == 0:
                return

            proceeds = fill.trade_value_inr - fill.total_cost_inr
            self.cash_inr += proceeds
            self.cash_inr = round(self.cash_inr, 2)

            # Close the position
            pos.qty = 0
            pos.days_held = 0

    def advance_day(self, current_prices: dict[str, float]) -> None:
        """
        Called at the start of each daily run to:
        - Update current prices
        - Increment days_held for open positions
        - Auto-exit any positions held beyond max_hold_days
        """
        settings = self._settings
        self._update_current_prices(current_prices)

        for ticker, pos in list(self.positions.items()):
            if pos.qty == 0:
                continue
            pos.days_held += 1

            if pos.days_held > settings.max_hold_days:
                logger.info(
                    "[ledger] Auto-exit %s: held %d days (max=%d)",
                    ticker, pos.days_held, settings.max_hold_days,
                )
                # The orchestration will pick this up via the position dict
                # and generate an EXIT decision in the graph.
                pos.days_held = settings.max_hold_days  # cap to signal auto-exit

    # ── NAV calculation ───────────────────────────────────────────────────────

    def calculate_nav(
        self,
        current_prices: dict[str, float],
        previous_nav_inr: float | None = None,
    ) -> NAVSnapshot:
        """
        Compute the current NAV and return a snapshot.

        Args:
            current_prices:    {ticker: close_price} for all tickers.
            previous_nav_inr:  Yesterday's NAV; used for daily_return_pct.
        """
        self._update_current_prices(current_prices)
        nav = self._nav_inr()
        equity = sum(
            p.qty * p.current_price for p in self.positions.values() if p.qty > 0
        )
        open_count = sum(1 for p in self.positions.values() if p.qty > 0)

        # Update peak NAV
        if nav > self.peak_nav_inr:
            self.peak_nav_inr = nav

        cumulative_return = (nav - self.initial_capital) / self.initial_capital * 100
        drawdown = self._drawdown_pct(nav)
        daily_return = (
            (nav - previous_nav_inr) / previous_nav_inr * 100
            if previous_nav_inr and previous_nav_inr > 0
            else 0.0
        )

        return NAVSnapshot(
            nav_inr=round(nav, 2),
            cash_inr=round(self.cash_inr, 2),
            equity_value_inr=round(equity, 2),
            open_positions=open_count,
            daily_return_pct=round(daily_return, 4),
            cumulative_return_pct=round(cumulative_return, 4),
            drawdown_pct=round(drawdown, 4),
            peak_nav_inr=round(self.peak_nav_inr, 2),
        )

    def check_circuit_breakers(
        self,
        ticker: str,
        is_restricted: bool,
        daily_llm_cost_usd: float,
    ) -> CircuitBreakerStatus:
        """Evaluate circuit breakers for the given ticker against the current portfolio."""
        try:
            ticker_sector = get_ticker(ticker).sector
        except ValueError:
            ticker_sector = "Unknown"

        nav = self._nav_inr()
        drawdown = self._drawdown_pct(nav)

        pos_data = {
            sym: {
                "qty": p.qty,
                "avg_price": p.avg_price,
                "current_price": p.current_price if p.current_price > 0 else p.avg_price,
                "sector": p.sector,
            }
            for sym, p in self.positions.items()
            if p.qty > 0
        }

        return check_circuit_breakers(
            ticker=ticker,
            ticker_sector=ticker_sector,
            is_restricted=is_restricted,
            drawdown_pct=drawdown,
            nav_inr=nav,
            positions=pos_data,
            daily_llm_cost_usd=daily_llm_cost_usd,
        )

    # ── Position serialisation for DynamoDB ───────────────────────────────────

    def open_positions_as_dicts(self) -> list[dict]:
        """Return all open positions as a list of dicts for DynamoDB persistence."""
        result = []
        for ticker, pos in self.positions.items():
            if pos.qty == 0:
                continue
            result.append({
                "ticker": ticker,
                "sector": pos.sector,
                "qty": pos.qty,
                "avg_price": pos.avg_price,
                "entry_date": pos.entry_date,
                "days_held": pos.days_held,
                "stop_loss_price": pos.stop_loss_price,
                "target_price": pos.target_price,
                "kill_conditions": pos.kill_conditions,
                "horizon_days": pos.horizon_days,
                "current_price": pos.current_price,
            })
        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    def _nav_inr(self) -> float:
        equity = sum(
            p.qty * (p.current_price if p.current_price > 0 else p.avg_price)
            for p in self.positions.values()
            if p.qty > 0
        )
        return self.cash_inr + equity

    def _drawdown_pct(self, current_nav: float) -> float:
        """Return drawdown as a positive percentage (e.g., 11.2 for 11.2% drawdown)."""
        if self.peak_nav_inr <= 0:
            return 0.0
        drawdown = (self.peak_nav_inr - current_nav) / self.peak_nav_inr * 100
        return max(0.0, round(drawdown, 4))

    def _update_current_prices(self, prices: dict[str, float]) -> None:
        for ticker, pos in self.positions.items():
            if pos.qty > 0 and ticker in prices:
                pos.current_price = prices[ticker]
