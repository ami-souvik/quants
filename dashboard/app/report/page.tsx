"use client";

import { useEffect, useState, useCallback } from "react";
import {
  api,
  formatINR,
  formatPct,
  pnlColor,
  decisionColor,
  type DailyReportResponse,
  type ReportTicker,
} from "@/lib/api";

// ── helpers ──────────────────────────────────────────────────────────────────

function today(): string {
  return new Date().toLocaleDateString("en-CA"); // yyyy-mm-dd local
}

function fmtIst(iso: string | null | undefined): string {
  if (!iso) return "—";
  return (
    new Date(iso).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }) + " IST"
  );
}

function fmtDuration(s: number): string {
  if (s < 60) return `${s.toFixed(0)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function signed(v: number, decimals = 2): string {
  return (v >= 0 ? "+" : "") + v.toFixed(decimals) + "%";
}

// ── sub-components ────────────────────────────────────────────────────────────

function Pill({
  label,
  variant = "neutral",
}: {
  label: string;
  variant?: "bull" | "bear" | "neutral" | "gold" | "error";
}) {
  const cls = {
    bull: "bg-bull/15 text-bull border-bull/30",
    bear: "bg-bear/15 text-bear border-bear/30",
    gold: "bg-gold/15 text-gold border-gold/30",
    error: "bg-bear/20 text-bear border-bear/40",
    neutral: "bg-surface text-subtle border-border",
  }[variant];
  return (
    <span
      className={`inline-block text-[10px] font-mono px-1.5 py-0.5 border rounded ${cls}`}
    >
      {label}
    </span>
  );
}

function KV({ k, v, accent }: { k: string; v: React.ReactNode; accent?: boolean }) {
  return (
    <div className="flex justify-between items-baseline gap-4 text-[12px]">
      <span className="text-subtle shrink-0">{k}</span>
      <span className={`font-mono text-right ${accent ? "text-text" : "text-muted"}`}>{v}</span>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-semibold tracking-widest text-muted uppercase mb-2 mt-4 first:mt-0">
      {children}
    </div>
  );
}

function AgentBlock({
  label,
  data: rawData,
}: {
  label: string;
  data: Record<string, unknown> | null | undefined;
}) {
  if (!rawData) return null;
  // cast to any so JSX can render dynamic agent fields without type errors
  // biome-ignore lint: intentional any for dynamic agent output
  const data = rawData as any; // eslint-disable-line
  const conf = data.confidence as number | undefined;
  return (
    <div className="border border-border rounded p-3 space-y-1.5">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] font-semibold text-text">{label}</span>
        {conf !== undefined && (
          <span className="text-[10px] font-mono text-subtle">
            conf {(conf * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {/* News Sentiment */}
      {data.sentiment_label && (
        <>
          <KV k="Sentiment" v={data.sentiment_label as string} accent />
          <KV k="Score" v={(data.sentiment_score as number)?.toFixed(2) ?? "—"} />
          {(data.key_events as string[])?.length > 0 && (
            <div className="text-[11px] text-subtle space-y-0.5 mt-1">
              {(data.key_events as string[]).map((e, i) => (
                <div key={i} className="flex gap-1.5">
                  <span className="text-muted mt-0.5">·</span>
                  <span>{e}</span>
                </div>
              ))}
            </div>
          )}
          {data.reasoning && (
            <p className="text-[11px] text-subtle italic mt-1">{data.reasoning as string}</p>
          )}
        </>
      )}

      {/* Technical */}
      {data.technical_signal && (
        <>
          <KV k="Signal" v={data.technical_signal as string} accent />
          <KV k="Trend" v={data.trend as string} />
          <KV k="Momentum" v={data.momentum as string} />
          <KV k="Volume" v={data.volume_signal as string} />
          {data.reasoning && (
            <p className="text-[11px] text-subtle italic mt-1">{data.reasoning as string}</p>
          )}
        </>
      )}

      {/* Fundamentals */}
      {data.fundamental_bias && (
        <>
          <KV k="Bias" v={data.fundamental_bias as string} accent />
          <KV k="Valuation" v={data.valuation as string} />
          <KV k="Inst. Flow" v={data.institutional_flow as string} />
          <KV
            k="Macro Tailwind"
            v={data.macro_tailwind ? "Yes" : "No"}
          />
          {(data.red_flags as string[])?.length > 0 && (
            <div className="text-[11px] text-bear mt-1">
              ⚠ {(data.red_flags as string[]).join(", ")}
            </div>
          )}
          {data.reasoning && (
            <p className="text-[11px] text-subtle italic mt-1">{data.reasoning as string}</p>
          )}
        </>
      )}

      {/* Bull/Bear */}
      {data.bull_thesis && (
        <>
          <div className="grid grid-cols-2 gap-3 mt-1">
            <div>
              <div className="text-[10px] font-semibold text-bull mb-1">BULL</div>
              {(data.bull_thesis as string[]).map((b, i) => (
                <div key={i} className="text-[11px] text-subtle flex gap-1.5 mb-0.5">
                  <span className="text-bull mt-0.5">↑</span>
                  <span>{b}</span>
                </div>
              ))}
            </div>
            <div>
              <div className="text-[10px] font-semibold text-bear mb-1">BEAR</div>
              {(data.bear_thesis as string[]).map((b, i) => (
                <div key={i} className="text-[11px] text-subtle flex gap-1.5 mb-0.5">
                  <span className="text-bear mt-0.5">↓</span>
                  <span>{b}</span>
                </div>
              ))}
            </div>
          </div>
          <KV k="Winner" v={data.debate_winner as string} accent />
          {data.key_risk && (
            <p className="text-[11px] text-gold italic mt-1">
              Risk: {data.key_risk as string}
            </p>
          )}
        </>
      )}

      {/* Portfolio Manager */}
      {data.decision && !data.bull_thesis && !data.technical_signal && !data.sentiment_label && !data.fundamental_bias && (
        <>
          <KV k="Decision" v={data.decision as string} accent />
          <KV k="Qty" v={String(data.quantity_shares ?? 0)} />
          <KV
            k="Value"
            v={formatINR(data.estimated_trade_value_inr as number ?? 0)}
          />
          <KV k="Horizon" v={`${data.horizon_days ?? 0}d`} />
          <KV k="Target" v={formatINR(data.target_price as number ?? 0)} />
          <KV k="Stop Loss" v={formatINR(data.stop_loss_price as number ?? 0)} />
          <KV k="R/R" v={(data.risk_reward_ratio as number ?? 0).toFixed(1)} />
          <KV k="Agent Agree" v={data.agent_agreement as string} />
          {data.primary_thesis && (
            <p className="text-[11px] text-subtle italic mt-1">
              {data.primary_thesis as string}
            </p>
          )}
          {(data.kill_conditions as string[])?.length > 0 && (
            <div className="text-[11px] text-subtle mt-1 space-y-0.5">
              {(data.kill_conditions as string[]).map((k, i) => (
                <div key={i} className="flex gap-1.5">
                  <span className="text-bear">✕</span>
                  <span>{k}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TickerCard({ t }: { t: ReportTicker }) {
  const [open, setOpen] = useState(false);

  const pm = t.pm_output as Record<string, unknown> | null;
  const decision = (pm?.decision as string) ?? (t.skip_reason ? "SKIP" : "—");
  const hasErrors = t.errors.length > 0;

  const statusColors = {
    completed: "border-l-2 border-l-border",
    skipped: "border-l-2 border-l-muted opacity-60",
    errored: "border-l-2 border-l-bear",
  }[t.status];

  const totalTokens = Object.values(t.tokens_used).reduce(
    (s, v) => s + v.input_tokens + v.output_tokens,
    0
  );

  return (
    <div className={`border border-border rounded ${statusColors} bg-bg`}>
      {/* Header row — always visible */}
      <button
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-surface transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        {/* Ticker + company */}
        <div className="w-28 shrink-0">
          <div className="text-[13px] font-semibold text-text font-mono">{t.ticker}</div>
          <div className="text-[10px] text-subtle truncate">{t.company_name}</div>
        </div>

        {/* Sector */}
        <div className="hidden sm:block w-24 shrink-0 text-[11px] text-subtle">{t.sector}</div>

        {/* Price + change */}
        <div className="hidden md:block w-28 shrink-0 text-[11px]">
          <span className="text-text font-mono">{formatINR(t.close_price)}</span>
          <span className={`ml-1.5 ${pnlColor(t.pct_change_1d)}`}>
            {signed(t.pct_change_1d)}
          </span>
        </div>

        {/* Decision badge */}
        <div className="flex-1 flex items-center gap-2">
          {decision !== "—" && (
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded ${decisionColor(decision)}`}
            >
              {decision}
            </span>
          )}
          {t.status === "skipped" && (
            <span className="text-[10px] text-subtle">
              SKIP · {t.skip_reason ?? ""}
            </span>
          )}
          {hasErrors && (
            <span className="text-[10px] text-bear font-medium">
              {t.errors.length} error{t.errors.length > 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Cost + timing */}
        <div className="hidden lg:flex items-center gap-4 text-[11px] text-subtle">
          <span>${t.ticker_cost_usd.toFixed(4)}</span>
          <span>{(t.processing_time_ms / 1000).toFixed(1)}s</span>
          {totalTokens > 0 && (
            <span>{totalTokens.toLocaleString()} tok</span>
          )}
        </div>

        <span className="text-muted text-[12px] ml-2">{open ? "▲" : "▼"}</span>
      </button>

      {/* Expanded detail */}
      {open && (
        <div className="border-t border-border px-4 pb-4 pt-3 space-y-4">
          {/* Errors section */}
          {hasErrors && (
            <div className="bg-bear/8 border border-bear/30 rounded p-3 space-y-1">
              <div className="text-[10px] font-semibold tracking-widest text-bear uppercase mb-2">
                Errors
              </div>
              {t.errors.map((e, i) => (
                <div key={i} className="text-[11px] text-bear font-mono break-all">
                  {i + 1}. {e}
                </div>
              ))}
            </div>
          )}

          {/* Skip info */}
          {t.status === "skipped" && t.skip_reason && (
            <div className="bg-surface border border-border rounded p-3 text-[12px] text-subtle">
              Skipped: <span className="text-text font-mono">{t.skip_reason}</span>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {/* Agent outputs */}
            <AgentBlock label="News Sentiment" data={t.news_output} />
            <AgentBlock label="Technical" data={t.technical_output} />
            <AgentBlock label="Fundamentals" data={t.fundamentals_output} />
            <AgentBlock label="Bull / Bear Debate" data={t.bull_bear_output} />
            <AgentBlock label="Portfolio Manager" data={t.pm_output} />

            {/* Simulated fill */}
            {t.simulated_fill && (
              <div className="border border-bull/30 bg-bull/5 rounded p-3 space-y-1.5">
                <div className="text-[11px] font-semibold text-bull mb-1">Simulated Fill</div>
                {Object.entries(t.simulated_fill).map(([k, v]) => (
                  <KV key={k} k={k} v={String(v)} />
                ))}
              </div>
            )}

            {/* Token usage */}
            {Object.keys(t.tokens_used).length > 0 && (
              <div className="border border-border rounded p-3 space-y-1.5">
                <div className="text-[11px] font-semibold text-text mb-1">Token Usage</div>
                {Object.entries(t.tokens_used).map(([agent, tok]) => (
                  <div key={agent} className="text-[11px]">
                    <div className="text-subtle mb-0.5">{agent}</div>
                    <div className="flex gap-3 text-muted font-mono text-[10px]">
                      <span>in {tok.input_tokens.toLocaleString()}</span>
                      <span>out {tok.output_tokens.toLocaleString()}</span>
                      <span className="text-text">${tok.cost_usd.toFixed(5)}</span>
                    </div>
                  </div>
                ))}
                <div className="border-t border-border pt-1 mt-1 flex justify-between text-[11px]">
                  <span className="text-subtle">Total</span>
                  <span className="font-mono text-text">${t.ticker_cost_usd.toFixed(5)}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ReportPage() {
  const [date, setDate] = useState(today());
  const [report, setReport] = useState<DailyReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (d: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.report(d);
      setReport(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load report";
      if (msg.includes("404")) {
        setError(`No report found for ${d}. The daily run may not have completed yet.`);
      } else {
        setError(msg);
      }
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(date);
  }, [date, load]);

  const s = report?.summary;
  const hasRunErrors = (report?.run_errors?.length ?? 0) > 0;
  const hasAnyError =
    hasRunErrors || (report?.tickers ?? []).some((t) => t.errors.length > 0);

  return (
    <div className="max-w-[1400px] mx-auto px-6 py-8 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between pb-6 border-b border-border">
        <div>
          <h1 className="text-xl font-semibold text-text">Daily Run Report</h1>
          <p className="text-[12px] text-subtle mt-0.5">
            Full pipeline trace — agent outputs, errors, fills, and costs
          </p>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="date"
            value={date}
            max={today()}
            onChange={(e) => setDate(e.target.value)}
            className="bg-surface border border-border text-text text-[12px] px-3 py-1.5 rounded font-mono focus:outline-none focus:border-accent"
          />
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="text-subtle text-[13px] py-12 text-center">Loading report…</div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="border border-bear/40 bg-bear/8 rounded p-6 text-center">
          <p className="text-bear text-[13px]">{error}</p>
        </div>
      )}

      {/* Report content */}
      {!loading && report && (
        <div className="space-y-6">
          {/* Run-level error banner */}
          {hasRunErrors && (
            <div className="border border-bear/40 bg-bear/8 rounded p-4 space-y-1">
              <div className="text-[10px] font-semibold tracking-widest text-bear uppercase mb-2">
                Run-Level Errors
              </div>
              {report.run_errors.map((e, i) => (
                <div key={i} className="text-[12px] text-bear font-mono">
                  {i + 1}. {e}
                </div>
              ))}
            </div>
          )}

          {/* ── Summary grid ──────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {[
              {
                label: "NAV",
                value: formatINR(s?.nav_inr ?? 0),
                sub: signed(s?.daily_return_pct ?? 0),
                subColor: pnlColor(s?.daily_return_pct ?? 0),
              },
              {
                label: "Cumulative Return",
                value: signed(s?.cumulative_return_pct ?? 0),
                sub: `Drawdown ${(s?.drawdown_pct ?? 0).toFixed(2)}%`,
                subColor: pnlColor(-(s?.drawdown_pct ?? 0)),
              },
              {
                label: "LLM Cost",
                value: `$${(s?.total_llm_cost_usd ?? 0).toFixed(4)}`,
                sub: `${s?.schema_errors ?? 0} schema errors`,
                subColor: (s?.schema_errors ?? 0) > 0 ? "text-bear" : "text-subtle",
              },
              {
                label: "Duration",
                value: fmtDuration(report.duration_seconds),
                sub: `${fmtIst(report.started_at)}`,
                subColor: "text-subtle",
              },
              {
                label: "Tickers",
                value: String(s?.tickers_total ?? 0),
                sub: `${s?.tickers_completed ?? 0} done · ${s?.tickers_skipped ?? 0} skipped · ${s?.tickers_errored ?? 0} errored`,
                subColor: (s?.tickers_errored ?? 0) > 0 ? "text-bear" : "text-subtle",
              },
              {
                label: "Open Positions",
                value: `${s?.open_positions ?? 0} / 5`,
                sub: formatINR(s?.cash_inr ?? 0) + " cash",
                subColor: "text-subtle",
              },
            ].map(({ label, value, sub, subColor }) => (
              <div key={label} className="border border-border rounded p-3 bg-surface">
                <div className="text-[10px] text-subtle mb-1">{label}</div>
                <div className="text-[16px] font-semibold font-mono text-text">{value}</div>
                <div className={`text-[10px] mt-0.5 ${subColor}`}>{sub}</div>
              </div>
            ))}
          </div>

          {/* ── Decision counts + macro ───────────────────────────────────── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Decisions */}
            <div className="border border-border rounded p-4">
              <SectionLabel>Decisions</SectionLabel>
              <div className="flex flex-wrap gap-2 mt-2">
                {Object.entries(s?.decision_counts ?? {}).map(([d, n]) => (
                  <div
                    key={d}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-[12px] font-mono ${decisionColor(d)}`}
                  >
                    <span className="font-semibold">{d}</span>
                    <span className="opacity-70">×{n}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Macro */}
            <div className="border border-border rounded p-4">
              <SectionLabel>Macro Context</SectionLabel>
              <div className="grid grid-cols-2 gap-x-8 gap-y-1 mt-2">
                <KV k="Nifty 50" v={report.macro.nifty_close.toLocaleString("en-IN")} accent />
                <KV k="Nifty 1d" v={signed(report.macro.nifty_1d_pct)} />
                <KV k="FII Net" v={`₹${report.macro.fii_net_buy_cr.toFixed(0)} Cr`} />
                <KV k="DII Net" v={`₹${report.macro.dii_net_buy_cr.toFixed(0)} Cr`} />
                <KV k="USD/INR" v={report.macro.usd_inr.toFixed(2)} />
                <KV k="RBI Rate" v={`${report.macro.rbi_rate}%`} />
              </div>
            </div>
          </div>

          {/* ── Per-ticker cards ──────────────────────────────────────────── */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <SectionLabel>Ticker Detail</SectionLabel>
              {hasAnyError && (
                <span className="text-[11px] text-bear">
                  ⚠ Tickers with errors are highlighted
                </span>
              )}
            </div>
            <div className="space-y-2">
              {report.tickers.map((t) => (
                <TickerCard key={t.ticker} t={t} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
