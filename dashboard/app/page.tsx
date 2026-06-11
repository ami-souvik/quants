/**
 * Main dashboard — server component.
 * Fetches health, positions, metrics summary, and 30-day NAV in parallel.
 * Revalidates every 60 seconds (matches Redis TTL on the backend).
 */
import { api, formatINR, formatPct, pnlColor } from "@/lib/api";
import { NavChart } from "@/components/NavChart";
import { PositionsTable } from "@/components/PositionsTable";
import { CircuitBreakerBanner } from "@/components/CircuitBreakerBanner";
import { AgentCostWidget } from "@/components/AgentCostWidget";
import { RefreshButton } from "@/components/RefreshButton";
import clsx from "clsx";

export const revalidate = 60;

async function getData() {
  try {
    const [health, positions, metrics, nav] = await Promise.all([
      api.health(),
      api.positions(),
      api.metricsSummary(),
      api.dailyNav(),
    ]);
    return { health, positions, metrics, nav, error: null };
  } catch (err) {
    return {
      health: null,
      positions: null,
      metrics: null,
      nav: null,
      error: err instanceof Error ? err.message : "Failed to load data",
    };
  }
}

export default async function DashboardPage() {
  const { health, positions, metrics, nav, error } = await getData();

  if (error || !health || !positions || !metrics || !nav) {
    return (
      <div className="flex flex-col items-center justify-center py-32 gap-4">
        <div className="text-bear text-4xl">⚠</div>
        <h2 className="text-text text-lg font-semibold">API Unavailable</h2>
        <p className="text-subtle text-sm max-w-md text-center">
          {error ?? "Could not reach the FastAPI backend. Make sure the API server is running."}
        </p>
        <code className="text-xs bg-surface px-3 py-1.5 rounded font-mono text-subtle">
          docker compose up trader-api
        </code>
      </div>
    );
  }

  const cumRetColor = pnlColor(metrics.cumulative_return_pct);
  const dailyRetColor = pnlColor(metrics.daily_return_pct);
  const drawdownColor = metrics.current_drawdown_pct < -5 ? "text-bear" : "text-subtle";

  return (
    <div className="space-y-6">
      {/* Circuit breakers */}
      <CircuitBreakerBanner health={health} />

      {/* Header bar */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text">Portfolio Overview</h1>
          <p className="text-xs text-subtle mt-0.5">
            {health.last_run
              ? `Last run: ${new Date(health.last_run).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST`
              : "No run yet today"}
            {" · "}{metrics.days_running} day{metrics.days_running !== 1 ? "s" : ""} of data
          </p>
        </div>
        <RefreshButton />
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Portfolio NAV" value={formatINR(metrics.nav)} />
        <StatCard
          label="Today's Return"
          value={formatPct(metrics.daily_return_pct)}
          valueClass={dailyRetColor}
        />
        <StatCard
          label="Cumulative Return"
          value={formatPct(metrics.cumulative_return_pct)}
          valueClass={cumRetColor}
        />
        <StatCard
          label="Drawdown"
          value={formatPct(metrics.current_drawdown_pct)}
          valueClass={drawdownColor}
        />
      </div>

      {/* NAV Chart */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-subtle mb-4">
          NAV vs Nifty 50 TRI (30 days)
        </h2>
        <NavChart
          navPoints={nav.points}
          niftyPoints={metrics.benchmark_comparison.nifty50_tri}
          initialCapital={metrics.initial_capital_inr}
        />
      </div>

      {/* Two-column: positions + side panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Positions table — spans 2 cols */}
        <div className="lg:col-span-2 rounded-xl border border-border bg-surface p-4">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-subtle">
              Open Positions
            </h2>
            <span className="text-xs text-subtle">
              {positions.open_count} / {positions.max_positions} slots
            </span>
          </div>
          <PositionsTable
            positions={positions.positions}
            openCount={positions.open_count}
            maxPositions={positions.max_positions}
          />
        </div>

        {/* Side panel: cash + metrics + cost */}
        <div className="space-y-4">
          {/* Cash breakdown */}
          <div className="rounded-xl border border-border bg-surface p-4 space-y-3">
            <h2 className="text-sm font-semibold text-subtle">Portfolio Breakdown</h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-subtle">Cash</span>
                <span className="font-mono">{formatINR(positions.cash_inr)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-subtle">Equity</span>
                <span className="font-mono">{formatINR(positions.equity_value_inr)}</span>
              </div>
              <div className="flex justify-between border-t border-border pt-2">
                <span className="text-subtle font-medium">Total NAV</span>
                <span className="font-mono font-semibold">{formatINR(positions.nav_inr)}</span>
              </div>
            </div>
          </div>

          {/* Key metrics */}
          <div className="rounded-xl border border-border bg-surface p-4 space-y-3">
            <h2 className="text-sm font-semibold text-subtle">Performance</h2>
            <div className="space-y-2 text-sm">
              <MetricRow label="Sharpe" value={metrics.sharpe.toFixed(2)} />
              <MetricRow label="Sortino" value={metrics.sortino.toFixed(2)} />
              <MetricRow label="Max DD" value={formatPct(metrics.max_drawdown_pct)} />
              <MetricRow label="Win Rate" value={formatPct(metrics.win_rate * 100, 1)} />
              <MetricRow label="Profit Factor" value={metrics.profit_factor.toFixed(2)} />
              <MetricRow label="Total Trades" value={String(metrics.total_trades)} />
            </div>
            {metrics.data_warning && (
              <p className="text-xs text-gold/80 mt-2">
                ⚠ {metrics.data_warning}
              </p>
            )}
          </div>

          {/* LLM cost widget */}
          <div className="rounded-xl border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold text-subtle mb-3">LLM Budget</h2>
            <AgentCostWidget
              costUsd={health.daily_llm_cost_usd}
              budgetUsd={1.0}
            />
            <p className="text-xs text-subtle mt-2">
              Total all-time: ${metrics.total_llm_cost_usd.toFixed(4)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-xs text-subtle">{label}</p>
      <p className={clsx("text-xl font-semibold font-mono mt-1", valueClass ?? "text-text")}>
        {value}
      </p>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-subtle">{label}</span>
      <span className="font-mono text-text">{value}</span>
    </div>
  );
}
