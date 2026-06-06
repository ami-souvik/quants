/**
 * Logs page — daily run log viewer.
 *
 * Shows every log line emitted by trader.daily_run for the selected date.
 * Lines are colour-coded by level; ERRORs and WARNINGs are highlighted.
 */
import { api, LogLine } from "@/lib/api";
import { DecisionsDatePicker } from "@/components/DecisionsDatePicker";
import { RefreshButton } from "@/components/RefreshButton";

export const revalidate = 30;

interface Props {
  searchParams: { date?: string };
}

function levelBadge(level: LogLine["level"]) {
  const base = "inline-block w-16 text-center text-[10px] font-mono font-semibold rounded px-1 py-0.5 shrink-0";
  switch (level) {
    case "ERROR":
    case "CRITICAL":
      return <span className={`${base} bg-bear/20 text-bear`}>{level}</span>;
    case "WARNING":
      return <span className={`${base} bg-gold/20 text-gold`}>{level}</span>;
    case "DEBUG":
      return <span className={`${base} bg-muted/20 text-subtle`}>{level}</span>;
    default:
      return <span className={`${base} bg-accent/10 text-accent`}>{level}</span>;
  }
}

function rowBg(level: LogLine["level"]) {
  switch (level) {
    case "ERROR":
    case "CRITICAL":
      return "bg-bear/5 border-l-2 border-bear/40";
    case "WARNING":
      return "bg-gold/5 border-l-2 border-gold/30";
    default:
      return "border-l-2 border-transparent";
  }
}

export default async function LogsPage({ searchParams }: Props) {
  const selectedDate =
    searchParams.date ?? new Date().toISOString().split("T")[0];

  let data = null;
  let error: string | null = null;

  try {
    data = await api.logs(selectedDate);
  } catch (err) {
    error = err instanceof Error ? err.message : "Failed to load logs";
  }

  const errorCount  = data?.lines.filter((l) => l.level === "ERROR" || l.level === "CRITICAL").length ?? 0;
  const warnCount   = data?.lines.filter((l) => l.level === "WARNING").length ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-text">Run Logs</h1>
          <p className="text-xs text-subtle mt-0.5">
            Daily pipeline output for all agents and tickers
          </p>
        </div>
        <div className="flex items-center gap-3">
          <DecisionsDatePicker selectedDate={selectedDate} />
          <RefreshButton />
        </div>
      </div>

      {/* Error loading */}
      {error && (
        <div className="rounded-lg border border-bear/40 bg-bear/10 p-4 text-bear text-sm">
          {error}
        </div>
      )}

      {/* Summary strip */}
      {data && (
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="px-3 py-1 rounded-full border border-border text-subtle">
            {data.total} lines
          </span>
          {errorCount > 0 && (
            <span className="px-3 py-1 rounded-full border border-bear/30 bg-bear/10 text-bear">
              {errorCount} error{errorCount !== 1 ? "s" : ""}
            </span>
          )}
          {warnCount > 0 && (
            <span className="px-3 py-1 rounded-full border border-gold/30 bg-gold/10 text-gold">
              {warnCount} warning{warnCount !== 1 ? "s" : ""}
            </span>
          )}
          {data.total > 0 && errorCount === 0 && warnCount === 0 && (
            <span className="px-3 py-1 rounded-full border border-bull/30 bg-bull/10 text-bull">
              Clean run ✓
            </span>
          )}
        </div>
      )}

      {/* Empty state */}
      {!error && data && data.lines.length === 0 && (
        <div className="text-center py-24 text-subtle text-sm">
          No log entries for {selectedDate}.
          <br />
          <span className="text-xs">
            Run the daily pipeline or select a different date.
          </span>
        </div>
      )}

      {/* Log lines */}
      {data && data.lines.length > 0 && (
        <div className="rounded-lg border border-border bg-surface overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-border text-subtle">
                  <th className="text-left px-3 py-2 w-36 shrink-0">Time</th>
                  <th className="text-left px-3 py-2 w-20 shrink-0">Level</th>
                  <th className="text-left px-3 py-2 w-52 shrink-0 hidden md:table-cell">Logger</th>
                  <th className="text-left px-3 py-2">Message</th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((line, i) => (
                  <tr
                    key={i}
                    className={`${rowBg(line.level)} hover:bg-border/20 transition-colors`}
                  >
                    {/* Timestamp — strip the date prefix, keep HH:MM:SS */}
                    <td className="px-3 py-1.5 text-subtle whitespace-nowrap align-top">
                      {line.timestamp.slice(11)}
                    </td>
                    {/* Level badge */}
                    <td className="px-3 py-1.5 align-top">
                      {levelBadge(line.level)}
                    </td>
                    {/* Logger name — truncate long names */}
                    <td className="px-3 py-1.5 text-subtle align-top hidden md:table-cell max-w-[13rem] truncate">
                      {line.logger}
                    </td>
                    {/* Message */}
                    <td className="px-3 py-1.5 text-text align-top break-all whitespace-pre-wrap">
                      {line.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
