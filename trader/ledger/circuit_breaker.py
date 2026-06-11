"""
Circuit breaker conditions for the paper-trading ledger (MIS intraday).

When a circuit breaker is active, a pending BUY becomes SKIP (not HOLD — there
is no HOLD concept in MIS; you either enter same-day or you don't).

- DRAWDOWN:      intraday portfolio drawdown >= 5% of opening NAV → SKIP all new entries
- CONCENTRATION: any single intraday position >= 15% of NAV → SKIP adds to that position
- SECTOR_CAP:    any sector >= 40% of NAV → SKIP new entries in that sector
- LLM_COST:      daily LLM spend > $1.00 → degrade to cheaper models (alert only here)
- RESTRICTED:    ticker on NSE ASM/GSM/T2T list → block entry; force squareoff if open
"""
from __future__ import annotations

from dataclasses import dataclass, field

from trader.config.settings import get_settings


@dataclass
class CircuitBreakerStatus:
    drawdown_triggered: bool = False
    concentration_triggered: bool = False   # per-position concentration
    sector_cap_triggered: bool = False      # per-sector cap
    llm_cost_triggered: bool = False
    restricted_triggered: bool = False

    # Which sector / position triggered (for diagnostics)
    concentration_ticker: str = ""
    sector_cap_sector: str = ""

    @property
    def any_active(self) -> bool:
        return (
            self.drawdown_triggered
            or self.concentration_triggered
            or self.sector_cap_triggered
            or self.llm_cost_triggered
            or self.restricted_triggered
        )

    @property
    def blocks_new_buy(self) -> bool:
        """True when a new BUY order must be refused."""
        return (
            self.drawdown_triggered
            or self.concentration_triggered
            or self.sector_cap_triggered
        )

    def active_names(self) -> list[str]:
        names = []
        if self.drawdown_triggered:
            names.append("DRAWDOWN")
        if self.concentration_triggered:
            names.append(f"CONCENTRATION({self.concentration_ticker})")
        if self.sector_cap_triggered:
            names.append(f"SECTOR_CAP({self.sector_cap_sector})")
        if self.llm_cost_triggered:
            names.append("LLM_COST")
        if self.restricted_triggered:
            names.append("RESTRICTED")
        return names


def check_circuit_breakers(
    ticker: str,
    ticker_sector: str,
    is_restricted: bool,
    drawdown_pct: float,
    nav_inr: float,
    positions: dict[str, dict],   # symbol → {qty, avg_price, current_price, sector}
    daily_llm_cost_usd: float,
) -> CircuitBreakerStatus:
    """
    Evaluate all circuit breakers for a given ticker at decision time.

    Args:
        ticker:             The ticker being evaluated.
        ticker_sector:      The sector of the ticker.
        is_restricted:      True if the ticker is on NSE ASM/GSM/T2T.
        drawdown_pct:       Current portfolio drawdown as a positive percentage (e.g., 11.2).
        nav_inr:            Current NAV in INR.
        positions:          All open positions; each has {qty, avg_price, current_price, sector}.
        daily_llm_cost_usd: Cumulative LLM spend today.

    Returns:
        CircuitBreakerStatus with all relevant flags set.
    """
    settings = get_settings()
    status = CircuitBreakerStatus()

    # 1. Restricted ticker
    if is_restricted:
        status.restricted_triggered = True

    # 2. Portfolio drawdown
    if drawdown_pct >= settings.circuit_breaker_drawdown * 100:
        status.drawdown_triggered = True

    # 3. Position concentration (only relevant for the ticker being evaluated)
    if ticker in positions and nav_inr > 0:
        pos = positions[ticker]
        position_value = pos.get("qty", 0) * pos.get("current_price", pos.get("avg_price", 0))
        if position_value / nav_inr >= settings.max_position_pct:
            status.concentration_triggered = True
            status.concentration_ticker = ticker

    # 4. Sector cap (40% of NAV in any single sector)
    if nav_inr > 0:
        sector_values: dict[str, float] = {}
        for sym, pos in positions.items():
            sec = pos.get("sector", "Unknown")
            val = pos.get("qty", 0) * pos.get("current_price", pos.get("avg_price", 0))
            sector_values[sec] = sector_values.get(sec, 0.0) + val

        if sector_values.get(ticker_sector, 0.0) / nav_inr >= 0.40:
            status.sector_cap_triggered = True
            status.sector_cap_sector = ticker_sector

    # 5. LLM cost
    if daily_llm_cost_usd >= settings.daily_llm_budget_usd:
        status.llm_cost_triggered = True

    return status


def enforce_decision(
    decision: str,
    cb_status: CircuitBreakerStatus,
) -> tuple[str, str]:
    """
    Apply circuit-breaker rules to an agent decision.

    Returns (enforced_decision, rationale).
    - BUY is overridden to SKIP if any buy-blocking breaker is active.
      (MIS has no HOLD — you either enter same-day or you don't.)
    - EXIT always passes through (needed to squareoff a restricted position).
    - RESTRICTED forces EXIT (squareoff any open intraday position immediately).
    """
    if cb_status.restricted_triggered:
        return "EXIT", "RESTRICTED"

    if decision == "BUY" and cb_status.blocks_new_buy:
        if cb_status.drawdown_triggered:
            return "SKIP", "DRAWDOWN"
        if cb_status.concentration_triggered:
            return "SKIP", "CONCENTRATION"
        if cb_status.sector_cap_triggered:
            return "SKIP", "SECTOR_CAP"

    return decision, ""
