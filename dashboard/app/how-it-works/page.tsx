export const metadata = { title: "How It Works — Quants" };

// ─── types ───────────────────────────────────────────────────────────────────
interface Agent {
  id: string;
  name: string;
  role: string;
  model: string;
  inputs: string[];
  output: string;
  feeds?: string;
}

interface DataSource {
  name: string;
  count: number;
  examples: string[];
}

interface CircuitBreaker {
  name: string;
  trigger: string;
  effect: string;
}

interface InfraItem {
  service: string;
  purpose: string;
  detail: string;
}

// ─── data ─────────────────────────────────────────────────────────────────────
const AGENTS: Agent[] = [
  {
    id: "news",
    name: "News & Sentiment",
    role: "Scores news flow polarity (0–1) for each ticker over the last 24 h",
    model: "Gemini 2.5 Flash",
    inputs: ["8 RSS articles (filtered to ticker)", "Corporate announcements", "Price Δ 1d"],
    output: "sentiment_score, sentiment_label, key_events, news_window, confidence",
    feeds: "8 feeds",
  },
  {
    id: "technical",
    name: "Technical Analyst",
    role: "Reads momentum, trend, and volatility signals from 30-day OHLCV",
    model: "Gemini 2.5 Flash",
    inputs: ["RSI, MACD, Bollinger Bands, ADX, ATR", "5-day OHLCV candles", "Current open position"],
    output: "technical_signal (BUY/SELL/HOLD/EXIT_LONG), trend, stop_loss, target, confidence",
    feeds: "1 feed (corporate actions for price adjustment)",
  },
  {
    id: "fundamentals",
    name: "Fundamentals Analyst",
    role: "Evaluates valuation, institutional flows, and macro fit",
    model: "Claude Haiku 4.5",
    inputs: ["P/E, P/B, RoE, D/E, revenue growth", "FII / DII net flows (₹ crore)", "USD/INR, RBI rate, Nifty trend"],
    output: "fundamental_bias, valuation, institutional_flow, macro_tailwind, red_flags, confidence",
    feeds: "13 feeds",
  },
  {
    id: "bull_bear",
    name: "Bull vs Bear Debate",
    role: "Runs a structured adversarial debate using the 3 prior agent outputs",
    model: "Claude Haiku 4.5",
    inputs: ["News agent output", "Technical agent output", "Fundamentals agent output"],
    output: "bull_thesis[3], bear_thesis[3], debate_winner, conviction_delta, key_risk, confidence",
  },
  {
    id: "pm",
    name: "Portfolio Manager",
    role: "Final executable trade decision — the only agent that touches the ledger",
    model: "Claude Haiku 4.5 (→ Sonnet 4.6 if confidence < 0.5)",
    inputs: ["All 4 prior agent outputs", "Live portfolio snapshot (cash, positions, drawdown)", "Hard constraints"],
    output: "decision (BUY/SELL/HOLD/EXIT/SKIP), qty, target, stop_loss, horizon_days, confidence",
  },
];

const DATA_SOURCES: DataSource[] = [
  {
    name: "NSE Official",
    count: 6,
    examples: ["Financial Results", "Board Meetings", "Corporate Actions", "Insider Trading"],
  },
  {
    name: "Economic Times",
    count: 6,
    examples: ["ET Markets", "ET Stocks", "ET Company", "Banking", "Energy", "Economy"],
  },
  {
    name: "Livemint",
    count: 2,
    examples: ["Livemint Markets", "Livemint Companies"],
  },
  {
    name: "Business Standard",
    count: 4,
    examples: ["Stock Market", "Quarterly Results", "Finance", "Economy & Policy"],
  },
];

const CIRCUIT_BREAKERS: CircuitBreaker[] = [
  {
    name: "Portfolio Drawdown",
    trigger: "Drawdown ≥ 10% of initial NAV",
    effect: "No new BUY entries — only HOLD or EXIT allowed",
  },
  {
    name: "LLM Cost Overrun",
    trigger: "Daily LLM spend > $1.00",
    effect: "Alert fired; cheaper model substituted automatically",
  },
  {
    name: "Concentration Cap",
    trigger: "Any single position ≥ 15% NAV",
    effect: "No further adds to that position",
  },
  {
    name: "Sector Cap",
    trigger: "Any sector ≥ 40% NAV",
    effect: "No new entries in that sector",
  },
  {
    name: "Restricted Ticker",
    trigger: "Stock on NSE ASM / GSM / T2T list",
    effect: "Force EXIT; skip agents entirely",
  },
  {
    name: "Quiet Skip",
    trigger: "No news in 24 h AND price Δ < 1.5%",
    effect: "Skip full pipeline; inherit prior position; log as QUIET_SKIP",
  },
];

const INFRA: InfraItem[] = [
  { service: "AWS ECS Fargate", purpose: "Runs the daily pipeline", detail: "1 vCPU · 2 GB · triggered by EventBridge" },
  { service: "EventBridge Cron", purpose: "Schedules the daily run", detail: "cron(30 11 ? * MON-FRI *) = 17:00 IST" },
  { service: "DynamoDB", purpose: "Single-table trade store", detail: "Positions · Decisions · Trades · NAV — on-demand billing" },
  { service: "S3", purpose: "Raw data archive", detail: "Bhavcopy CSVs · full LLM prompts/outputs · 90-day lifecycle" },
  { service: "Secrets Manager", purpose: "API key storage", detail: "Anthropic · Gemini · (Kite in Phase 2)" },
  { service: "CloudWatch", purpose: "Logs & alerts", detail: "Per-agent token costs · circuit breaker notifications" },
  { service: "Redis (local/ElastiCache)", purpose: "Hot cache", detail: "Market data TTL 23 h · news per-agent TTL 1 h" },
  { service: "SNS", purpose: "Alert delivery", detail: "Email on circuit breaker trigger or LLM budget overrun" },
];

// ─── sub-components ────────────────────────────────────────────────────────────
function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[13px] font-semibold text-text mb-4 flex items-center gap-2 uppercase tracking-widest">
      {children}
    </h2>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block px-2 py-0.5 border border-border text-subtle text-[10px] font-mono">
      {children}
    </span>
  );
}

function Arrow({ vertical = false }: { vertical?: boolean }) {
  if (vertical) {
    return (
      <div className="flex justify-center my-1">
        <div className="flex flex-col items-center gap-0.5">
          <div className="w-px h-4 bg-border" />
          <div className="w-0 h-0 border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-border" />
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center self-center mx-1 shrink-0">
      <div className="h-px w-6 bg-border" />
      <div className="w-0 h-0 border-t-4 border-b-4 border-l-4 border-t-transparent border-b-transparent border-l-border" />
    </div>
  );
}

// ─── page ─────────────────────────────────────────────────────────────────────
export default function HowItWorksPage() {
  return (
    <div className="max-w-[1200px] mx-auto px-6 py-8 space-y-12 pb-12">

      {/* ── hero ──────────────────────────────────────────────────────────── */}
      <div className="border border-border bg-surface p-6">
        <div className="flex items-start justify-between flex-wrap gap-6">
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-semibold text-text mb-3">How the System Works</h1>
            <p className="text-subtle max-w-2xl text-[13px] leading-relaxed">
              Every weekday at <strong className="text-text">17:00 IST</strong> (after NSE market close),
              an automated pipeline runs for all <strong className="text-text">15 large-cap Nifty 50 stocks</strong>.
              Five LLM agents debate each stock sequentially, a Portfolio Manager produces a structured
              trade decision, and a simulated fill is recorded in the paper ledger.
              No real money is ever touched.
            </p>
          </div>
          <div className="flex flex-col gap-2 shrink-0">
            <div className="border border-border px-3 py-1.5 text-[11px] font-mono text-subtle">
              Paper Trading Only
            </div>
            <div className="border border-border px-3 py-1.5 text-[11px] font-mono text-accent">
              ₹10,00,000 Virtual Capital
            </div>
            <div className="border border-border px-3 py-1.5 text-[11px] font-mono text-subtle">
              Max 5 Open Positions
            </div>
          </div>
        </div>
      </div>

      {/* ── daily pipeline overview ───────────────────────────────────────── */}
      <div>
        <SectionHeading>
          <span className="text-accent font-mono">01</span> Daily Pipeline (17:00 IST, Mon–Fri)
        </SectionHeading>

        <div className="overflow-x-auto pb-2">
          <div className="flex items-stretch min-w-[700px] gap-0">
            {[
              { label: "Data Ingestion", sub: "OHLCV · News · FII/DII" },
              null,
              { label: "5 LLM Agents", sub: "Sequential · per ticker" },
              null,
              { label: "PM Decision", sub: "BUY / EXIT / HOLD / SKIP" },
              null,
              { label: "Paper Ledger", sub: "Simulated fill + cost" },
              null,
              { label: "Persist", sub: "DynamoDB · S3 · Redis" },
              null,
              { label: "Dashboard", sub: "Next.js — this UI" },
            ].map((item, i) => {
              if (item === null) return <Arrow key={i} />;
              return (
                <div
                  key={i}
                  className="flex-1 border border-border bg-surface p-3 text-center min-w-[100px]"
                >
                  <div className="text-[12px] font-medium text-text">{item.label}</div>
                  <div className="text-[11px] text-subtle mt-1">{item.sub}</div>
                </div>
              );
            })}
          </div>
        </div>

        <p className="text-[11px] text-subtle mt-3 leading-relaxed">
          All 15 tickers are processed <strong className="text-text">sequentially</strong> (not in parallel)
          to stay within LLM rate limits, keep daily cost observable, and avoid Redis race conditions.
          A ticker is skipped entirely (QUIET_SKIP) if there is no news in the last 24 h
          and price Δ &lt; 1.5 %.
        </p>
      </div>

      {/* ── data sources ─────────────────────────────────────────────────── */}
      <div>
        <SectionHeading>
          <span className="text-accent font-mono">02</span> Data Sources (18 RSS Feeds + Market Data)
        </SectionHeading>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          {DATA_SOURCES.map((src) => (
            <div key={src.name} className="border border-border bg-surface p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="font-medium text-text text-[13px]">{src.name}</span>
                <Chip>{src.count} feeds</Chip>
              </div>
              <ul className="space-y-1">
                {src.examples.map((ex) => (
                  <li key={ex} className="text-[11px] text-subtle">· {ex}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="border border-border bg-surface p-4 grid grid-cols-1 sm:grid-cols-3 gap-4 text-[13px]">
          <div>
            <div className="text-subtle text-[10px] uppercase tracking-widest mb-1.5">Market Data</div>
            <div className="text-text font-mono text-[12px]">jugaad-data · nselib</div>
            <div className="text-subtle text-[11px] mt-1">30-day OHLCV, bhavcopy, Nifty 50 index — cached in Redis (TTL 23 h)</div>
          </div>
          <div>
            <div className="text-subtle text-[10px] uppercase tracking-widest mb-1.5">Technical Indicators</div>
            <div className="text-text font-mono text-[12px]">pandas-ta</div>
            <div className="text-subtle text-[11px] mt-1">RSI-14 · SMA 5/20/50 · EMA 12/26 · MACD · Bollinger · ATR · ADX · VWAP · Volume ratio</div>
          </div>
          <div>
            <div className="text-subtle text-[10px] uppercase tracking-widest mb-1.5">FII / DII Flows</div>
            <div className="text-text font-mono text-[12px]">nselib</div>
            <div className="text-subtle text-[11px] mt-1">Net buy/sell in ₹ crore — passed to Fundamentals & Portfolio Manager agents</div>
          </div>
        </div>

        <div className="mt-3 border border-border bg-surface p-3 text-[11px] text-subtle">
          <strong className="text-text">Deduplication:</strong> all articles are embedded with
          <code className="text-accent mx-1 font-mono">all-MiniLM-L6-v2</code>
          (sentence-transformers, local, free). Articles with cosine similarity &gt; 0.85 to an
          already-kept article are dropped before being passed to any agent.
          Headlines + URLs + max 2-sentence summaries only — never full body text.
        </div>
      </div>

      {/* ── five agents ──────────────────────────────────────────────────── */}
      <div>
        <SectionHeading>
          <span className="text-accent font-mono">03</span> The Five-Agent Pipeline
        </SectionHeading>

        <div className="space-y-2">
          {AGENTS.map((agent, idx) => (
            <div key={agent.id}>
              <div className="border border-border bg-surface p-4 grid grid-cols-1 md:grid-cols-[auto_1fr_1fr] gap-4">
                {/* index + name */}
                <div className="flex items-start gap-3 min-w-[200px]">
                  <span className="text-accent font-mono text-lg font-bold leading-none mt-0.5">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <div className="font-medium text-text text-[13px]">{agent.name}</div>
                    <div className="text-[11px] font-mono text-muted mt-0.5">{agent.model}</div>
                    {agent.feeds && (
                      <div className="text-[11px] text-subtle mt-1">{agent.feeds}</div>
                    )}
                  </div>
                </div>

                {/* inputs */}
                <div>
                  <div className="text-subtle text-[10px] uppercase tracking-widest mb-1.5">Inputs</div>
                  <ul className="space-y-1">
                    {agent.inputs.map((inp) => (
                      <li key={inp} className="text-[11px] text-text flex gap-1.5">
                        <span className="text-border shrink-0">▸</span>{inp}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* output */}
                <div>
                  <div className="text-subtle text-[10px] uppercase tracking-widest mb-1.5">JSON Output Fields</div>
                  <div className="text-[11px] font-mono text-subtle bg-bg p-2 leading-relaxed break-all">
                    {agent.output}
                  </div>
                  <div className="text-[11px] text-subtle mt-2 leading-relaxed">{agent.role}</div>
                </div>
              </div>

              {idx < AGENTS.length - 1 && <Arrow vertical />}
            </div>
          ))}
        </div>

        <div className="mt-4 border border-border bg-surface p-4 text-[11px] text-subtle grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <strong className="text-text block mb-1">Anthropic Prompt Caching</strong>
            The shared system context (<code className="text-accent font-mono">prompts/system_shared.md</code>, ≥ 1 024 tokens)
            is sent with <code className="text-accent font-mono">cache_control: ephemeral</code>.
            This gives a ~90 % discount on re-reads across all 15 ticker calls in a single daily run.
          </div>
          <div>
            <strong className="text-text block mb-1">Schema Validation &amp; Retry</strong>
            Every agent output is validated against a Pydantic model.
            On validation failure the call is retried once.
            If it still fails, a <Chip>HOLD fallback</Chip> decision
            is written with <code className="text-accent font-mono">schema_valid=false</code> —
            the pipeline never crashes over a single bad LLM output.
          </div>
        </div>
      </div>

      {/* ── trade cost model ─────────────────────────────────────────────── */}
      <div>
        <SectionHeading>
          <span className="text-accent font-mono">04</span> Transaction Cost Model (India 2025–26)
        </SectionHeading>

        <div className="border border-border bg-surface overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border text-subtle text-[10px] uppercase tracking-widest">
                <th className="text-left p-3">Charge</th>
                <th className="text-right p-3">Delivery (CNC) — Phase 1</th>
                <th className="text-right p-3">Intraday (MIS) — reference</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {[
                ["Brokerage", "₹0 (Zerodha free delivery)", "min(₹20, 0.03%) per order"],
                ["STT", "0.1% BUY + 0.1% SELL", "0.025% on SELL only"],
                ["NSE Txn Charge", "0.00297% both sides", "0.00297% both sides"],
                ["GST", "18% on (brokerage + txn + SEBI)", "18% on (brokerage + txn + SEBI)"],
                ["SEBI Fee", "₹10/crore = 0.0001%", "₹10/crore = 0.0001%"],
                ["Stamp Duty", "0.015% on BUY only", "0.003% on BUY only"],
                ["DP Charges", "₹15.93 on SELL only", "₹0"],
                ["Slippage buffer", "3 bps (Nifty 50 estimate)", "3 bps"],
              ].map(([charge, delivery, intraday]) => (
                <tr key={charge} className="hover:bg-border/20">
                  <td className="p-3 text-text">{charge}</td>
                  <td className="p-3 text-right font-mono text-[11px] text-subtle">{delivery}</td>
                  <td className="p-3 text-right font-mono text-[11px] text-subtle">{intraday}</td>
                </tr>
              ))}
              <tr className="bg-border/20 font-semibold">
                <td className="p-3 text-text">Round-trip total</td>
                <td className="p-3 text-right text-accent font-mono text-[12px]">~25.5–28 bps</td>
                <td className="p-3 text-right text-muted font-mono text-[12px]">~10.6–13 bps</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p className="text-[11px] text-subtle mt-2">
          The Portfolio Manager uses a <strong className="text-text">28 bps cost hurdle</strong> —
          an expected move must exceed this to be worth entering.
          All monetary values are stored as <code className="text-accent font-mono">Decimal</code> in DynamoDB, never float.
        </p>
      </div>

      {/* ── circuit breakers ─────────────────────────────────────────────── */}
      <div>
        <SectionHeading>
          <span className="text-accent font-mono">05</span> Circuit Breakers &amp; Safety Gates
        </SectionHeading>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {CIRCUIT_BREAKERS.map((cb) => (
            <div key={cb.name} className="border border-border bg-surface p-4">
              <div className="font-medium text-[13px] text-text mb-2">{cb.name}</div>
              <div className="text-[11px] text-subtle mb-1.5">
                <span className="text-muted">Trigger: </span>{cb.trigger}
              </div>
              <div className="text-[11px] text-subtle">
                <span className="text-muted">Effect: </span>{cb.effect}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-3 border border-border bg-surface p-3 text-[11px] text-subtle">
          <strong className="text-text">Idempotency:</strong> running <code className="text-accent font-mono">daily_run.py</code> twice
          on the same date is safe — the pipeline checks DynamoDB for an existing
          <code className="text-accent font-mono mx-1">DATE#YYYY-MM-DD / PORTFOLIO</code> record before processing.
          If found, the run is a no-op.
        </div>
      </div>

      {/* ── positions & ledger ───────────────────────────────────────────── */}
      <div>
        <SectionHeading>
          <span className="text-accent font-mono">06</span> Paper Ledger &amp; Position Rules
        </SectionHeading>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          {[
            { label: "Initial Capital", value: "₹10,00,000", sub: "10 lakh virtual INR" },
            { label: "Max Positions", value: "5", sub: "simultaneous open" },
            { label: "Max Position Size", value: "15% NAV", sub: "per single stock" },
            { label: "Max Hold Duration", value: "5 days", sub: "auto-exit after 5 trading days" },
          ].map(({ label, value, sub }) => (
            <div key={label} className="border border-border bg-surface p-4 text-center">
              <div className="text-xl font-bold text-accent">{value}</div>
              <div className="text-[11px] text-text mt-1">{label}</div>
              <div className="text-[10px] text-subtle mt-0.5">{sub}</div>
            </div>
          ))}
        </div>

        <div className="border border-border bg-surface p-4 text-[11px] text-subtle">
          <strong className="text-text block mb-2">Fill simulation logic</strong>
          Fills are simulated at the <strong className="text-text">previous day&apos;s close price</strong>
          (the next-day open is not available at 17:00 IST when the pipeline runs)
          plus a <strong className="text-text">3 bps slippage buffer</strong>.
          Actual transaction costs are calculated via the exact Indian cost model above and deducted from cash.
          <strong className="text-text"> Phase 1 only uses CNC (delivery) — no intraday squared positions.</strong>
        </div>
      </div>

      {/* ── infra ─────────────────────────────────────────────────────────── */}
      <div>
        <SectionHeading>
          <span className="text-accent font-mono">07</span> AWS Infrastructure (ap-south-1)
        </SectionHeading>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {INFRA.map(({ service, purpose, detail }) => (
            <div key={service} className="border border-border bg-surface p-3 flex gap-3">
              <code className="text-accent text-[11px] font-mono shrink-0 w-36">{service}</code>
              <div>
                <div className="text-[12px] text-text">{purpose}</div>
                <div className="text-[11px] text-subtle mt-0.5">{detail}</div>
              </div>
            </div>
          ))}
        </div>

        <p className="text-[11px] text-subtle mt-3">
          Target monthly cost: <strong className="text-text">&lt; ₹2,000</strong> (LLM + AWS combined).
          LLM target: <strong className="text-text">&lt; $0.40/run</strong> per daily execution.
          All infrastructure is defined as Terraform IaC under <code className="text-accent font-mono">infra/</code>.
        </p>
      </div>

      {/* ── phase roadmap ─────────────────────────────────────────────────── */}
      <div>
        <SectionHeading>
          <span className="text-accent font-mono">08</span> Phase Roadmap
        </SectionHeading>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="border border-accent/30 bg-surface p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="border border-accent/40 text-accent text-[10px] font-mono px-2 py-0.5">
                Active — Phase 1
              </span>
              <span className="text-[13px] font-medium text-text">Paper Trading</span>
            </div>
            <ul className="space-y-1 text-[11px] text-subtle">
              <li>· 5-agent LLM pipeline runs daily</li>
              <li>· Decisions recorded in DynamoDB, never executed</li>
              <li>· Performance benchmarked vs Nifty 50 TRI</li>
              <li>· Goal: 30 days of validated paper data</li>
            </ul>
          </div>

          <div className="border border-border bg-surface p-4 opacity-50">
            <div className="flex items-center gap-2 mb-3">
              <span className="border border-border text-subtle text-[10px] font-mono px-2 py-0.5">
                Future — Phase 2
              </span>
              <span className="text-[13px] font-medium text-text">Live Trading (Zerodha)</span>
            </div>
            <ul className="space-y-1 text-[11px] text-subtle">
              <li>· Zerodha Kite API integration</li>
              <li>· Real order placement (CNC delivery only)</li>
              <li>· TOTP-based access token refresh</li>
              <li>· Unlocks only after Phase 1 performance validation</li>
            </ul>
          </div>
        </div>
      </div>

    </div>
  );
}
