interface Props {
  costUsd: number;
  budgetUsd?: number;
}

export function AgentCostWidget({ costUsd, budgetUsd = 1.0 }: Props) {
  const pct = Math.min((costUsd / budgetUsd) * 100, 100);
  const nearBudget = pct > 80;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-between items-baseline">
        <span className="text-[11px] text-muted">Today</span>
        <span className={`font-mono text-base font-semibold ${nearBudget ? "text-accent" : "text-text"}`}>
          ${costUsd.toFixed(4)}
        </span>
      </div>
      <div className="h-px bg-surface2">
        <div
          className={`h-px transition-all ${nearBudget ? "bg-accent" : "bg-subtle"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between text-[11px] text-muted">
        <span>$0</span>
        <span>{pct.toFixed(0)}% of ${budgetUsd.toFixed(2)}</span>
      </div>
    </div>
  );
}
