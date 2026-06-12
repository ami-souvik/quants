import { PositionResponse, formatINR } from "@/lib/api";

interface Props {
  positions: PositionResponse[];
  openCount: number;
  maxPositions: number;
}

export function PositionsTable({ positions, openCount, maxPositions }: Props) {
  if (positions.length === 0) {
    return (
      <div className="py-14 text-center">
        <p className="text-4xl font-semibold text-surface2 mb-2">FLAT</p>
        <p className="text-[12px] text-muted">
          All positions squared off · Portfolio in cash
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border">
            {["Ticker", "Qty", "Entry", "Stop", "Target", "Time", "Unreal. P&L"].map(
              (h, i) => (
                <th
                  key={h}
                  className={`text-[11px] text-muted pb-3 font-normal tracking-wider uppercase ${
                    i === 0 ? "text-left pr-6" : i === 6 ? "text-right" : "text-right pr-6"
                  }`}
                >
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const pnl = pos.unrealized_pnl_pct;
            const pnlPositive = pnl !== null && pnl >= 0;

            return (
              <tr
                key={pos.ticker}
                className="border-b border-border hover:bg-surface transition-colors"
              >
                <td className="py-4 pr-6">
                  <div className="font-mono font-semibold text-[13px] text-text">{pos.ticker}</div>
                  <div className="text-[10px] text-muted mt-0.5">MIS · LONG</div>
                </td>
                <td className="py-4 pr-6 text-right font-mono text-[13px] text-text">{pos.qty}</td>
                <td className="py-4 pr-6 text-right font-mono text-[13px]">
                  ₹{pos.avg_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                </td>
                <td className="py-4 pr-6 text-right font-mono text-[13px] text-muted">
                  ₹{pos.stop_loss_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                </td>
                <td className="py-4 pr-6 text-right font-mono text-[13px]">
                  ₹{pos.target_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                </td>
                <td className="py-4 pr-6 text-right">
                  <div className="text-[12px] font-mono text-text">
                    {(pos as any).entry_time_ist ?? "09:20"}
                  </div>
                  <div className="text-[10px] text-muted">→ 15:15</div>
                </td>
                <td className="py-4 text-right">
                  {pnl !== null ? (
                    <span
                      className={`font-mono text-[13px] font-semibold px-2 py-0.5 ${
                        pnlPositive
                          ? "bg-accent text-accent-fg"
                          : "text-muted border border-border"
                      }`}
                    >
                      {pnlPositive ? "+" : ""}{pnl.toFixed(2)}%
                    </span>
                  ) : (
                    <span className="text-muted text-xs">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* Slot dots */}
      <div className="mt-5 flex items-center gap-3">
        <span className="text-[11px] text-muted">Slots used</span>
        <div className="flex gap-1.5">
          {Array.from({ length: maxPositions }, (_, i) => (
            <div
              key={i}
              className={`w-2.5 h-2.5 border ${
                i < openCount ? "bg-accent border-accent" : "border-border"
              }`}
            />
          ))}
        </div>
        <span className="text-[11px] font-mono text-muted">{openCount}/{maxPositions}</span>
      </div>
    </div>
  );
}
