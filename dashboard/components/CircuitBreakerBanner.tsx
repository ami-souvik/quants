import { HealthResponse } from "@/lib/api";

interface Props {
  health: HealthResponse;
}

export function CircuitBreakerBanner({ health }: Props) {
  const active = health.circuit_breakers_active;
  if (!active || active.length === 0) return null;

  const labels: Record<string, string> = {
    DRAWDOWN:      "Portfolio drawdown ≥ 5% — no new BUY orders today",
    CONCENTRATION: "Position concentration ≥ 15% NAV — no adds",
    SECTOR_CAP:    "Sector allocation ≥ 40% NAV — no adds in that sector",
    LLM_COST:      "Daily LLM budget exceeded — downgraded to cheaper models",
    RESTRICTED:    "Stock on NSE ASM/GSM list — forced skip active",
  };

  return (
    <div className="bg-accent text-accent-fg px-6 py-3 mb-8 flex items-center gap-6">
      <span className="text-[11px] font-semibold tracking-widest uppercase shrink-0">
        Circuit Breaker{active.length > 1 ? "s" : ""}
      </span>
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        {active.map((cb) => (
          <span key={cb} className="text-[11px] font-mono opacity-70">
            {cb}: {labels[cb] ?? cb}
          </span>
        ))}
      </div>
    </div>
  );
}
