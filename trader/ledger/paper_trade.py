"""
Paper-trading ledger: simulated MIS intraday fills, position management, NAV calculation.

All fills are SIMULATED — no broker API is called in Phase 1.

MIS (intraday) rules:
  - Entry window: 09:15–11:00 IST only
  - All positions MUST be squared off by 15:15 IST same day
  - No overnight holdings — equity_value_inr is always 0 at end of day
  - Positions are ephemeral (Redis-backed during the day; only completed
    round-trips are written to DynamoDB after squareoff)

Fill price policy:
  BUY entry    → prior-day close + 3 bps slippage (simulated 09:20 open fill)
  SELL squareoff → 15:15 IST close price − 3 bps slippage
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
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

_SQUAREOFF_TIME = "15:15"   # always — hard-coded as the simulation exit time
_ENTRY_TIME_DEFAULT = "09:20"  # simulated first-candle fill proxy


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class Position:
    """A single open intraday (MIS) position. Always closed same day."""
    ticker: str
    sector: str
    qty: int
    avg_price: float
    entry_date: str           # "yyyy-mm-dd"
    entry_time_ist: str       # "HH:MM" — simulated entry time (default 09:20)
    stop_loss_price: float
    target_price: float
    current_price: float = 0.0  # updated intraday for MTM NAV


@dataclass
class SimulatedFill:
    """Result of a single simulated trade leg (BUY entry or SELL squareoff)."""
    ticker: str
    side: str                 # "BUY" or "SELL"
    qty: int
    fill_price: float         # close price ± slippage
    trade_value_inr: float
    regulatory_cost_inr: float
    slippage_inr: float
    total_cost_inr: float     # regulatory + slippage
    cost_bps: float           # total / trade_value × 10000
    product_type: str = "MIS"  # always MIS — CNC is forbidden in Phase 1
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trade_date: str = ""

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
class CompletedTrade:
    """A completed MIS round-trip (entry + squareoff). Written to DynamoDB at 15:20 IST."""
    ticker: str
    qty: int
    entry_price: float
    exit_price: float
    entry_time_ist: str
    exit_time_ist: str          # always "15:15" for auto-squareoff
    trade_value_inr: float      # entry_price × qty
    gross_pnl_inr: float        # (exit_price - entry_price) × qty
    total_cost_inr: float       # all MIS charges, both legs combined
    net_pnl_inr: float          # gross_pnl - total_cost
    net_pnl_bps: float          # net_pnl / trade_value × 10000
    cost_bps: float
    was_squaredoff_auto: bool   # True = 15:15 mandatory squareoff
    trade_id: str
    trade_date: str

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_time_ist": self.entry_time_ist,
            "exit_time_ist": self.exit_time_ist,
            "trade_value_inr": self.trade_value_inr,
            "gross_pnl_inr": self.gross_pnl_inr,
            "total_cost_inr": self.total_cost_inr,
            "net_pnl_inr": self.net_pnl_inr,
            "net_pnl_bps": self.net_pnl_bps,
            "cost_bps": self.cost_bps,
            "was_squaredoff_auto": self.was_squaredoff_auto,
            "trade_id": self.trade_id,
            "trade_date": self.trade_date,
            "product_type": "MIS",
        }


@dataclass
class NAVSnapshot:
    nav_inr: float
    cash_inr: float
    equity_value_inr: float   # 0 at EOD (all MIS squared off)
    open_positions: int
    daily_return_pct: float
    cumulative_return_pct: float
    drawdown_pct: float        # positive value; 0 = no drawdown
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
    In-memory intraday MIS ledger for a single trading day.

    Lifecycle (morning run, 08:45 IST):
      1. Instantiate via from_scratch() or from_dynamo_snapshot().
      2. For each ticker with a BUY decision: simulate_fill() → update_positions().
      3. Persist open positions to Redis for intraday tracking.

    Lifecycle (squareoff run, 15:20 IST):
      4. squareoff_all_positions(closing_prices) closes all open positions.
      5. Returns list[CompletedTrade] for DynamoDB persistence.
      6. calculate_nav(eod=True) → equity_value_inr is always 0 at EOD.
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
        self.completed_trades: list[CompletedTrade] = []

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_scratch(cls, trade_date: str) -> "PaperTradingLedger":
        """Create a fresh ledger with initial capital, no open positions."""
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
        trade_date: str,
    ) -> "PaperTradingLedger":
        """
        Reconstruct cash/NAV state from the previous day's DynamoDB nav_daily record.
        Intraday positions are NOT loaded here — MIS positions never persist across days.
        """
        settings = get_settings()
        cash = float(nav_item.get("cash_inr", settings.initial_capital_inr))
        peak = float(nav_item.get("peak_nav_inr", nav_item.get("nav_inr", settings.initial_capital_inr)))
        return cls(
            cash_inr=cash,
            positions={},          # always empty at start of day — MIS only
            peak_nav_inr=peak,
            initial_capital_inr=settings.initial_capital_inr,
            trade_date=trade_date,
        )

    # ── Portfolio snapshot (input to PM agent) ────────────────────────────────

    def portfolio_snapshot(self, current_prices: dict[str, float] | None = None) -> dict:
        """Return a dict summarising the portfolio for use as PM agent context."""
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
        """Return the current intraday position for a ticker, or empty dict if flat."""
        pos = self.positions.get(ticker)
        if pos is None or pos.qty == 0:
            return {}
        return {
            "qty": pos.qty,
            "avg_price": pos.avg_price,
            "entry_time_ist": pos.entry_time_ist,
            "entry_date": pos.entry_date,
            "stop_loss_price": pos.stop_loss_price,
            "target_price": pos.target_price,
        }

    # ── Fill simulation — BUY entry ───────────────────────────────────────────

    def simulate_fill(
        self,
        ticker: str,
        decision: str,
        quantity_shares: int,
        close_price: float,
        stop_loss_price: float = 0.0,
        target_price: float = 0.0,
        entry_time_ist: str = _ENTRY_TIME_DEFAULT,
    ) -> SimulatedFill | None:
        """
        Simulate a BUY entry fill. Returns None for SKIP or any non-BUY decision.

        Fill price = close_price + 3 bps slippage (proxy for next-day open).
        Exits are handled exclusively via squareoff_position() / squareoff_all_positions().
        """
        if decision != "BUY":
            return None

        if quantity_shares <= 0:
            logger.warning("[ledger] BUY with qty=0 for %s — skipping fill", ticker)
            return None

        slippage_bps = 3
        fill_price = close_price * (1 + slippage_bps / 10_000)
        trade_value = fill_price * quantity_shares
        slippage_inr = float(slippage_amount(trade_value, bps=slippage_bps))

        cost_breakdown = calculate_trade_cost(trade_value, TradeType.INTRADAY, "BUY")
        regulatory_cost = float(cost_breakdown.total)
        total_cost = regulatory_cost + slippage_inr
        cost_bps = (total_cost / trade_value * 10_000) if trade_value > 0 else 0.0

        fill = SimulatedFill(
            ticker=ticker,
            side="BUY",
            qty=quantity_shares,
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
            "[ledger] BUY fill: %s %d @ %.2f (TV=₹%.0f, cost=₹%.2f / %.1f bps)",
            ticker, quantity_shares, fill_price, trade_value, total_cost, cost_bps,
        )
        self.fills.append(fill)
        return fill

    def update_positions(
        self,
        fill: SimulatedFill,
        stop_loss_price: float = 0.0,
        target_price: float = 0.0,
        entry_time_ist: str = _ENTRY_TIME_DEFAULT,
    ) -> None:
        """
        Apply a BUY fill to the in-memory position book and deduct cash.
        Rejects if max positions reached or insufficient cash.
        """
        if fill.side != "BUY":
            logger.warning("[ledger] update_positions called with non-BUY fill — ignored")
            return

        settings = self._settings
        ticker = fill.ticker
        total_outlay = fill.trade_value_inr + fill.total_cost_inr

        # Enforce max concurrent intraday positions
        open_count = sum(1 for p in self.positions.values() if p.qty > 0)
        if ticker not in self.positions and open_count >= settings.max_open_positions:
            logger.warning(
                "[ledger] Max intraday positions (%d) reached — BUY for %s rejected",
                settings.max_open_positions, ticker,
            )
            self.fills.pop()
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
            # Add to existing intraday position (weighted avg price)
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
                entry_time_ist=entry_time_ist,
                stop_loss_price=stop_loss_price,
                target_price=target_price,
                current_price=fill.fill_price,
            )

        self.cash_inr -= total_outlay
        self.cash_inr = round(self.cash_inr, 2)

    # ── Squareoff — MIS mandatory exit ────────────────────────────────────────

    def squareoff_position(
        self,
        ticker: str,
        close_price: float,
        exit_time_ist: str = _SQUAREOFF_TIME,
        auto: bool = True,
    ) -> CompletedTrade | None:
        """
        Simulate the mandatory 15:15 IST squareoff for one position.
        Fill price = close_price − 3 bps slippage (unfavourable for seller).
        Returns a CompletedTrade record and updates cash. Returns None if no position.
        """
        pos = self.positions.get(ticker)
        if pos is None or pos.qty == 0:
            return None

        slippage_bps = 3
        exit_fill_price = close_price * (1 - slippage_bps / 10_000)
        qty = pos.qty
        trade_value = pos.avg_price * qty  # based on entry value for cost calculation

        # SELL leg costs
        sell_slippage = float(slippage_amount(exit_fill_price * qty, bps=slippage_bps))
        sell_cost = calculate_trade_cost(exit_fill_price * qty, TradeType.INTRADAY, "SELL")
        sell_regulatory = float(sell_cost.total)
        sell_total_cost = sell_regulatory + sell_slippage

        # BUY leg costs (already paid at entry — tracked separately for round-trip total)
        # We look up the matching entry fill if available; otherwise estimate from avg_price
        entry_trade_value = pos.avg_price * qty
        buy_cost = calculate_trade_cost(entry_trade_value, TradeType.INTRADAY, "BUY")
        buy_regulatory = float(buy_cost.total)
        entry_slippage = float(slippage_amount(entry_trade_value, bps=slippage_bps))
        buy_total_cost = buy_regulatory + entry_slippage

        total_round_trip_cost = buy_total_cost + sell_total_cost

        gross_pnl = (exit_fill_price - pos.avg_price) * qty
        net_pnl = gross_pnl - total_round_trip_cost
        net_pnl_bps = (net_pnl / entry_trade_value * 10_000) if entry_trade_value > 0 else 0.0
        cost_bps = (total_round_trip_cost / entry_trade_value * 10_000) if entry_trade_value > 0 else 0.0

        # Add exit proceeds to cash
        proceeds = exit_fill_price * qty - sell_total_cost
        self.cash_inr += proceeds
        self.cash_inr = round(self.cash_inr, 2)

        # Close the position
        pos.qty = 0

        completed = CompletedTrade(
            ticker=ticker,
            qty=qty,
            entry_price=round(pos.avg_price, 2),
            exit_price=round(exit_fill_price, 2),
            entry_time_ist=pos.entry_time_ist,
            exit_time_ist=exit_time_ist,
            trade_value_inr=round(entry_trade_value, 2),
            gross_pnl_inr=round(gross_pnl, 2),
            total_cost_inr=round(total_round_trip_cost, 2),
            net_pnl_inr=round(net_pnl, 2),
            net_pnl_bps=round(net_pnl_bps, 2),
            cost_bps=round(cost_bps, 2),
            was_squaredoff_auto=auto,
            trade_id=str(uuid.uuid4()),
            trade_date=self.trade_date,
        )

        logger.info(
            "[ledger] Squareoff %s: %d @ %.2f → %.2f | gross ₹%.0f net ₹%.0f (%.1f bps)",
            ticker, qty, pos.avg_price, exit_fill_price,
            gross_pnl, net_pnl, net_pnl_bps,
        )
        self.completed_trades.append(completed)
        return completed

    def squareoff_all_positions(
        self,
        closing_prices: dict[str, float],
        exit_time_ist: str = _SQUAREOFF_TIME,
    ) -> list[CompletedTrade]:
        """
        Unconditionally close ALL open intraday positions at their closing prices.
        Called at 15:20 IST by squareoff_run.py. Must run regardless of P&L.
        Returns the list of CompletedTrade records for DynamoDB persistence.
        """
        results: list[CompletedTrade] = []
        open_tickers = [t for t, p in self.positions.items() if p.qty > 0]

        for ticker in open_tickers:
            price = closing_prices.get(ticker)
            if price is None:
                logger.error(
                    "[ledger] No closing price for %s — using avg_price as fallback", ticker
                )
                price = self.positions[ticker].avg_price  # worst-case fallback

            trade = self.squareoff_position(ticker, price, exit_time_ist=exit_time_ist, auto=True)
            if trade:
                results.append(trade)

        remaining_open = sum(1 for p in self.positions.values() if p.qty > 0)
        if remaining_open > 0:
            logger.error(
                "[ledger] %d positions still open after squareoff_all_positions — investigate",
                remaining_open,
            )

        return results

    # ── NAV calculation ───────────────────────────────────────────────────────

    def calculate_nav(
        self,
        current_prices: dict[str, float] | None = None,
        previous_nav_inr: float | None = None,
        eod: bool = False,
    ) -> NAVSnapshot:
        """
        Compute the current NAV and return a snapshot.

        Args:
            current_prices:    {ticker: price} for mark-to-market during the day.
            previous_nav_inr:  Yesterday's closing NAV for daily_return_pct.
            eod:               True at end-of-day after squareoff. Forces
                               equity_value_inr = 0 (all MIS positions closed).
        """
        self._update_current_prices(current_prices or {})

        if eod:
            # End-of-day: all MIS positions must be zero
            equity = 0.0
            open_count = 0
            nav = self.cash_inr
        else:
            equity = sum(
                p.qty * p.current_price for p in self.positions.values() if p.qty > 0
            )
            open_count = sum(1 for p in self.positions.values() if p.qty > 0)
            nav = self.cash_inr + equity

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

    # ── Position serialisation ────────────────────────────────────────────────

    def open_positions_as_dicts(self) -> list[dict]:
        """Return all open intraday positions as dicts for Redis serialisation."""
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
                "entry_time_ist": pos.entry_time_ist,
                "stop_loss_price": pos.stop_loss_price,
                "target_price": pos.target_price,
                "current_price": pos.current_price,
                "product_type": "MIS",
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
        if self.peak_nav_inr <= 0:
            return 0.0
        drawdown = (self.peak_nav_inr - current_nav) / self.peak_nav_inr * 100
        return max(0.0, round(drawdown, 4))

    def _update_current_prices(self, prices: dict[str, float]) -> None:
        for ticker, pos in self.positions.items():
            if pos.qty > 0 and ticker in prices:
                pos.current_price = prices[ticker]
