/**
 * Typed fetch wrapper for the FastAPI backend.
 *
 * All functions are async and throw on non-2xx responses.
 * Use in Server Components (no auth header exposed to browser) or
 * Route Handlers when you need client-triggered refreshes.
 */

// Two-URL pattern for Docker deployments:
//   API_URL           — server-side only (SSR/Server Components inside the container)
//                       Set to http://trader-api:8000 in docker-compose so the Next.js
//                       server can reach the FastAPI container via Docker's internal DNS.
//   NEXT_PUBLIC_API_URL — baked at build time; used by the browser (client components).
//                       Set to http://localhost:8000 so the browser hits the mapped port.
//
// In local dev (npm run dev), both resolve to localhost:8000 and only
// NEXT_PUBLIC_API_URL is needed.
const BASE_URL =
  (typeof window === "undefined"
    ? process.env.API_URL          // server-side: docker internal hostname
    : undefined) ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

const API_KEY  = process.env.NEXT_PUBLIC_API_KEY  ?? "changeme-local-dev";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
    // Next.js 14 caching: revalidate every 60s (matches Redis TTL on the API)
    next: { revalidate: 60 },
  });

  if (!res.ok) {
    throw new Error(`API ${path} returned ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

// ─── Response types (mirrors api/schemas.py) ─────────────────────────────────

export interface HealthResponse {
  status: string;
  last_run: string | null;
  paper_mode: boolean;
  circuit_breakers_active: string[];
  daily_llm_cost_usd: number;
  environment: string;
  version: string;
}

export interface PositionResponse {
  ticker: string;
  qty: number;
  avg_price: number;
  days_held: number;
  current_price: number | null;
  unrealized_pnl_inr: number | null;
  unrealized_pnl_pct: number | null;
  stop_loss_price: number;
  target_price: number;
  kill_conditions: string[];
  entry_date: string;
  horizon_days: number;
  sector: string;
}

export interface PositionsResponse {
  positions: PositionResponse[];
  open_count: number;
  max_positions: number;
  cash_inr: number;
  equity_value_inr: number;
  nav_inr: number;
}

// ─── Logs ─────────────────────────────────────────────────────────────────────

export interface LogLine {
  timestamp: string;
  level: "INFO" | "WARNING" | "ERROR" | "CRITICAL" | "DEBUG";
  logger: string;
  message: string;
  raw: string;
}

export interface LogsResponse {
  date: string;
  lines: LogLine[];
  total: number;
  has_error: boolean;
}

export interface AgentDecisionDetail {
  agent: string;
  model: string | null;
  sentiment_score: number | null;
  sentiment_label: string | null;
  key_events: string[];
  data_quality: string | null;
  technical_signal: string | null;
  trend: string | null;
  momentum: string | null;
  volume_signal: string | null;
  suggested_stop_loss_pct: number | null;
  suggested_target_pct: number | null;
  fundamental_bias: string | null;
  valuation: string | null;
  institutional_flow: string | null;
  macro_tailwind: boolean | null;
  red_flags: string[];
  bull_thesis: string[];
  bear_thesis: string[];
  debate_winner: string | null;
  conviction_delta: number | null;
  key_risk: string | null;
  decision: string | null;
  quantity_shares: number | null;
  estimated_trade_value_inr: number | null;
  horizon_days: number | null;
  target_price: number | null;
  stop_loss_price: number | null;
  primary_thesis: string | null;
  agent_agreement: string | null;
  estimated_cost_bps: number | null;
  risk_reward_ratio: number | null;
  confidence: number | null;
  reasoning: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  schema_valid: boolean | null;
  retry_count: number | null;
}

export interface SimulatedFill {
  side: string;
  qty: number;
  fill_price: number;
  trade_value_inr: number;
  simulated_cost_inr: number;
  simulated_cost_bps: number;
  slippage_bps: number;
}

export interface DecisionResponse {
  ticker: string;
  date: string;
  pm_decision: string | null;
  pm_confidence: number | null;
  pm_reasoning: string | null;
  agent_agreement: string | null;
  news_sentiment: string | null;
  technical_signal: string | null;
  fundamental_bias: string | null;
  debate_winner: string | null;
  estimated_cost_bps: number | null;
  risk_reward_ratio: number | null;
  skip_reason: string | null;
  actual_fill: SimulatedFill | null;
  agents: AgentDecisionDetail[];
}

export interface DecisionsResponse {
  date: string;
  decisions: DecisionResponse[];
  total: number;
}

export interface BenchmarkPoint { date: string; nav: number; }

export interface BenchmarkComparison {
  nifty50_tri: BenchmarkPoint[];
  equal_weight: BenchmarkPoint[];
  momentum_5d: BenchmarkPoint[];
  mean_reversion_5d: BenchmarkPoint[];
  buy_and_hold: BenchmarkPoint[];
}

export interface MetricsSummaryResponse {
  nav: number;
  initial_capital_inr: number;
  cumulative_return_pct: number;
  daily_return_pct: number;
  sharpe: number;
  sortino: number;
  max_drawdown_pct: number;
  current_drawdown_pct: number;
  win_rate: number;
  profit_factor: number;
  avg_win_loss_ratio: number;
  total_trades: number;
  total_llm_cost_usd: number;
  days_running: number;
  data_warning: string | null;
  benchmark_comparison: BenchmarkComparison;
}

export interface DailyNavPoint {
  date: string;
  nav: number;
  daily_return_pct: number;
  nifty_return_pct: number;
  drawdown_pct: number;
  llm_cost_usd: number;
  open_positions: number;
}

export interface DailyNavResponse {
  points: DailyNavPoint[];
  from_date: string | null;
  to_date: string | null;
}

export interface AgentHitRate {
  agent: string;
  hit_rate: number;
  n_calls: number;
  avg_confidence: number;
}

export interface AgentCostBreakdown {
  agent: string;
  model: string;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  call_count: number;
}

export interface PerformanceAnalyticsResponse {
  sharpe: number;
  sortino: number;
  max_drawdown_pct: number;
  win_rate: number;
  profit_factor: number;
  agent_hit_rates: AgentHitRate[];
  agent_cost_breakdown: AgentCostBreakdown[];
  benchmark_comparison: BenchmarkComparison;
  statistical_warning: string;
}

// ─── Daily Report ─────────────────────────────────────────────────────────────

export interface ReportMacro {
  nifty_close: number;
  nifty_1d_pct: number;
  nifty_5d_pct: number;
  rbi_rate: number;
  usd_inr: number;
  fii_net_buy_cr: number;
  dii_net_buy_cr: number;
  fii_dii_source: string;
}

export interface ReportSummary {
  tickers_total: number;
  tickers_completed: number;
  tickers_skipped: number;
  tickers_errored: number;
  decision_counts: Record<string, number>;
  total_llm_cost_usd: number;
  schema_errors: number;
  nav_inr: number;
  cash_inr: number;
  daily_return_pct: number;
  cumulative_return_pct: number;
  drawdown_pct: number;
  open_positions: number;
}

export interface ReportTickerTokens {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface ReportTicker {
  ticker: string;
  company_name: string;
  sector: string;
  status: "completed" | "skipped" | "errored";
  skip_reason: string | null;
  errors: string[];
  processing_time_ms: number;
  close_price: number;
  pct_change_1d: number;
  news_output: Record<string, unknown> | null;
  technical_output: Record<string, unknown> | null;
  fundamentals_output: Record<string, unknown> | null;
  bull_bear_output: Record<string, unknown> | null;
  pm_output: Record<string, unknown> | null;
  simulated_fill: Record<string, unknown> | null;
  tokens_used: Record<string, ReportTickerTokens>;
  ticker_cost_usd: number;
}

export interface DailyReportResponse {
  run_date: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number;
  macro: ReportMacro;
  summary: ReportSummary;
  run_errors: string[];
  tickers: ReportTicker[];
}

// ─── API functions ────────────────────────────────────────────────────────────

export const api = {
  health: () =>
    apiFetch<HealthResponse>("/api/health"),

  positions: () =>
    apiFetch<PositionsResponse>("/api/positions"),

  decisions: (date?: string) =>
    apiFetch<DecisionsResponse>(`/api/decisions${date ? `?date=${date}` : ""}`),

  metricsSummary: () =>
    apiFetch<MetricsSummaryResponse>("/api/metrics/summary"),

  dailyNav: (from?: string, to?: string) => {
    const params = new URLSearchParams();
    if (from) params.set("from_date", from);
    if (to)   params.set("to_date",   to);
    const qs = params.toString();
    return apiFetch<DailyNavResponse>(`/api/metrics/daily${qs ? `?${qs}` : ""}`);
  },

  analytics: () =>
    apiFetch<PerformanceAnalyticsResponse>("/api/metrics/analytics"),

  logs: (date?: string) =>
    apiFetch<LogsResponse>(`/api/logs${date ? `?date=${date}` : ""}`),

  report: (date?: string) =>
    apiFetch<DailyReportResponse>(`/api/report${date ? `?date=${date}` : ""}`),
};

// ─── Indian number formatting helpers ────────────────────────────────────────

/** Format a number in Indian lakh/crore notation with ₹ prefix. */
export function formatINR(value: number, decimals = 0): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_00_00_000) {
    return `${sign}₹${(abs / 1_00_00_000).toFixed(2)} Cr`;
  }
  if (abs >= 1_00_000) {
    return `${sign}₹${(abs / 1_00_000).toFixed(2)} L`;
  }
  return `${sign}₹${abs.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

/** Format a percentage with sign and fixed decimals. */
export function formatPct(value: number, decimals = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

/** Return Tailwind colour class based on positive/negative value. */
export function pnlColor(value: number): string {
  if (value > 0) return "text-bull";
  if (value < 0) return "text-bear";
  return "text-subtle";
}

/** Map a PM decision string to a badge colour class. */
export function decisionColor(decision: string | null): string {
  switch (decision) {
    case "BUY":  return "bg-bull/20 text-bull";
    case "EXIT":
    case "SELL": return "bg-bear/20 text-bear";
    case "HOLD": return "bg-gold/20 text-gold";
    case "SKIP": return "bg-muted/20 text-subtle";
    default:     return "bg-muted/20 text-subtle";
  }
}
