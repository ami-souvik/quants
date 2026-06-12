import { api, formatINR, formatPct } from "@/lib/api";
import { NavChart } from "@/components/NavChart";
import { PositionsTable } from "@/components/PositionsTable";
import { CircuitBreakerBanner } from "@/components/CircuitBreakerBanner";
import { AgentCostWidget } from "@/components/AgentCostWidget";
import { RefreshButton } from "@/components/RefreshButton";

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

function signed(v: number) {
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}

export default async function DashboardPage() {
  const { health, positions, metrics, nav, error } = await getData();

  if (error || !health || !positions || !metrics || !nav) {
    return (
      <div className="border border-border p-16 text-center mt-16">
        <p className="text-5xl font-semibold mb-4 text-muted">API Offline</p>
        <p className="text-subtle text-sm max-w-sm mx-auto mb-6">
          {error ?? "Could not reach the FastAPI backend. Start the API server and refresh."}
        </p>
        <code className="text-[12px] font-mono text-muted border border-border px-4 py-2">
          docker compose up trader-api
        </code>
      </div>
    );
  }

  const lastRun = health.last_run
    ? new Date(health.last_run).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }) + " IST"
    : "—";

  return (
    <div>
      <CircuitBreakerBanner health={health} />

      {/* ── Hero ─────────────────────────────────────────────────────────────── */}
      <div className="flex items-end justify-between mb-10 pb-8 border-b border-border">
        <div>
          <p className="text-[12px] text-muted mb-3">
            NSE Intraday · MIS · Nifty 50 Basket
          </p>
          <h1 className="text-[5.5rem] font-semibold leading-none tracking-tight text-text">
            Portfolio
          </h1>
        </div>
        <div className="text-right pb-1">
          <p className="text-[11px] text-muted mb-1">Last run</p>
          <p className="font-mono text-[13px] text-text">{lastRun}</p>
          <p className="text-[12px] text-muted mt-1">
            {metrics.days_running} day{metrics.days_running !== 1 ? "s" : ""} of data
          </p>
          <div className="mt-4">
            <RefreshButton />
          </div>
        </div>
      </div>

      {/* ── Stat row ─────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-4 gap-px bg-border mb-px">
        <StatCard
          label="Portfolio NAV"
          value={formatINR(metrics.nav)}
          accent
        />
        <StatCard
          label="Today's Return"
          value={signed(metrics.daily_return_pct)}
          negative={metrics.daily_return_pct < 0}
        />
        <StatCard
          label="Cumulative Return"
          value={signed(metrics.cumulative_return_pct)}
          negative={metrics.cumulative_return_pct < 0}
        />
        <StatCard
          label="Max Drawdown"
          value={signed(metrics.max_drawdown_pct)}
          negative={metrics.max_drawdown_pct < -5}
        />
      </div>

      {/* ── Chart + metrics ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-px bg-border mb-px">
        {/* Chart */}
        <div className="col-span-2 bg-bg p-8">
          <div className="flex items-center justify-between mb-6">
            <p className="text-[12px] text-muted">NAV vs Nifty 50 TRI — 30 days</p>
            <div className="flex items-center gap-5 text-[11px] text-muted">
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-4 h-px bg-accent" />
                Portfolio
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-4 h-px border-t border-dashed border-muted" />
                Nifty 50
              </span>
            </div>
          </div>
          <NavChart
            navPoints={nav.points}
            niftyPoints={metrics.benchmark_comparison.nifty50_tri}
            initialCapital={metrics.initial_capital_inr}
          />
        </div>

        {/* Performance metrics */}
        <div className="bg-bg p-8">
          <p className="text-[12px] text-muted mb-6">Performance</p>
          <table className="w-full">
            <tbody className="divide-y divide-border">
              {[
                { label: "Sharpe Ratio",   value: metrics.sharpe.toFixed(2) },
                { label: "Sortino Ratio",  value: metrics.sortino.toFixed(2) },
                { label: "Win Rate",       value: formatPct(metrics.win_rate * 100, 1) },
                { label: "Profit Factor",  value: metrics.profit_factor.toFixed(2) },
                { label: "Total Trades",   value: String(metrics.total_trades) },
                { label: "Open Positions", value: `${positions.open_count} / ${positions.max_positions}` },
              ].map(({ label, value }) => (
                <tr key={label}>
                  <td className="py-3 text-[13px] text-muted">{label}</td>
                  <td className="py-3 text-[13px] font-mono text-right text-text font-medium">
                    {value}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {metrics.data_warning && (
            <p className="text-[11px] text-muted mt-4 border-l border-border pl-3 leading-relaxed">
              {metrics.data_warning}
            </p>
          )}
        </div>
      </div>

      {/* ── Positions + allocation + cost ───────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-px bg-border mb-px">
        {/* Positions */}
        <div className="col-span-2 bg-bg p-8">
          <div className="flex items-center justify-between mb-6">
            <p className="text-[12px] text-muted">Open Intraday Positions · MIS</p>
            <p className="text-[12px] font-mono text-muted">
              {positions.open_count} / {positions.max_positions} slots
            </p>
          </div>
          <PositionsTable
            positions={positions.positions}
            openCount={positions.open_count}
            maxPositions={positions.max_positions}
          />
        </div>

        {/* Sidebar */}
        <div className="bg-bg divide-y divide-border">
          {/* Capital allocation */}
          <div className="p-8">
            <p className="text-[12px] text-muted mb-6">Capital Allocation</p>
            <div className="space-y-5">
              <AllocRow
                label="Cash"
                value={formatINR(positions.cash_inr)}
                pct={Math.round((positions.cash_inr / positions.nav_inr) * 100)}
              />
              <AllocRow
                label="Equity"
                value={formatINR(positions.equity_value_inr)}
                pct={Math.round((positions.equity_value_inr / positions.nav_inr) * 100)}
              />
              <div className="pt-4 border-t border-border flex items-baseline justify-between">
                <span className="text-[12px] text-muted">Total NAV</span>
                <span className="text-[1.75rem] font-semibold leading-none">
                  {formatINR(positions.nav_inr)}
                </span>
              </div>
            </div>
          </div>

          {/* LLM cost */}
          <div className="p-8">
            <p className="text-[12px] text-muted mb-4">LLM Budget</p>
            <AgentCostWidget costUsd={health.daily_llm_cost_usd} budgetUsd={1.0} />
            <div className="flex justify-between mt-5 pt-5 border-t border-border">
              <span className="text-[12px] text-muted">All-time</span>
              <span className="font-mono text-[13px] text-text">
                ${metrics.total_llm_cost_usd.toFixed(4)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Status bar ───────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-px bg-border">
        <StatusCell label="Mode" value="PAPER TRADING" />
        <StatusCell
          label="Circuit Breakers"
          value={
            health.circuit_breakers_active?.length
              ? health.circuit_breakers_active.join(" · ")
              : "NONE ACTIVE"
          }
          alert={!!health.circuit_breakers_active?.length}
        />
        <StatusCell label="Universe" value="15 NSE STOCKS · NIFTY 50" />
      </div>
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  accent,
  negative,
}: {
  label: string;
  value: string;
  accent?: boolean;
  negative?: boolean;
}) {
  const bg = accent ? "bg-accent" : negative ? "bg-surface" : "bg-bg";
  const labelColor = accent ? "text-accent-fg/60" : "text-muted";
  const valueColor = accent ? "text-accent-fg" : negative ? "text-subtle" : "text-text";

  return (
    <div className={`${bg} p-8 py-10`}>
      <p className={`text-[11px] tracking-wider uppercase mb-4 ${labelColor}`}>{label}</p>
      <p className={`text-4xl font-semibold leading-none whitespace-nowrap ${valueColor}`}>{value}</p>
    </div>
  );
}

function AllocRow({ label, value, pct }: { label: string; value: string; pct: number }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] text-muted">{label}</span>
        <span className="font-mono text-[13px] text-text">{value}</span>
      </div>
      <div className="h-px bg-border">
        <div
          className="h-px bg-subtle"
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      <p className="text-[11px] text-muted mt-1">{pct}%</p>
    </div>
  );
}

function StatusCell({
  label,
  value,
  alert,
}: {
  label: string;
  value: string;
  alert?: boolean;
}) {
  return (
    <div className={`px-6 py-4 flex items-center justify-between ${alert ? "bg-accent" : "bg-bg"}`}>
      <span className={`text-[11px] tracking-wider uppercase ${alert ? "text-accent-fg/60" : "text-muted"}`}>
        {label}
      </span>
      <span className={`text-[12px] font-mono ${alert ? "text-accent-fg" : "text-subtle"}`}>
        {value}
      </span>
    </div>
  );
}
