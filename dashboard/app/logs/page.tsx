"use client";

import { useEffect, useState, useCallback } from "react";
import {
  api,
  type LogSession,
  type LogLine,
  type LogSessionDetailResponse,
} from "@/lib/api";

// ── helpers ───────────────────────────────────────────────────────────────────

function today(): string {
  return new Date().toLocaleDateString("en-CA");
}

function fmtIst(iso: string): string {
  if (!iso) return "—";
  const dt = iso.includes("T") ? iso : iso + "T00:00:00";
  return (
    new Date(dt).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }) + " IST"
  );
}

function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(2)} MB`;
}

// ── sub-components ────────────────────────────────────────────────────────────

function LevelBadge({ level }: { level: LogLine["level"] }) {
  const base =
    "inline-block w-16 text-center text-[10px] font-mono font-semibold px-1 py-0.5 shrink-0";
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

function rowBg(level: LogLine["level"]): string {
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

// ── Full log detail panel ─────────────────────────────────────────────────────

function LogDetailPanel({
  sessionKey,
  onClose,
}: {
  sessionKey: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<LogSessionDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"ALL" | "ERROR" | "WARNING">("ALL");

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .logSession(sessionKey)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [sessionKey]);

  const visibleLines =
    data?.lines.filter((l) => {
      if (filter === "ERROR") return l.level === "ERROR" || l.level === "CRITICAL";
      if (filter === "WARNING") return l.level === "WARNING";
      return true;
    }) ?? [];

  // Key name for the header
  const runLabel = sessionKey.split("/").pop()?.replace(/^run-/, "").replace(/\.log$/, "") ?? sessionKey;
  const runTime = runLabel.split("T")[1]?.replace(/-/g, ":") ?? runLabel;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-bg">
      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-surface shrink-0">
        <div className="flex items-center gap-4">
          <button
            onClick={onClose}
            className="text-muted hover:text-text text-[13px] flex items-center gap-1.5 transition-colors"
          >
            ← Back
          </button>
          <div>
            <span className="text-[13px] font-semibold text-text font-mono">
              run-{runLabel}.log
            </span>
            {data && (
              <span className="ml-3 text-[11px] text-subtle">
                {data.total.toLocaleString()} lines
              </span>
            )}
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-1 text-[11px]">
          {(["ALL", "ERROR", "WARNING"] as const).map((f) => {
            const count =
              f === "ALL"
                ? data?.total
                : f === "ERROR"
                ? data?.error_count
                : data?.warning_count;
            const active = filter === f;
            const colorActive =
              f === "ERROR"
                ? "bg-bear/20 text-bear border-bear/30"
                : f === "WARNING"
                ? "bg-gold/20 text-gold border-gold/30"
                : "bg-accent/15 text-accent border-accent/30";
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 border rounded font-mono transition-colors ${
                  active
                    ? colorActive
                    : "border-border text-subtle hover:text-text"
                }`}
              >
                {f} {count !== undefined ? `(${count})` : ""}
              </button>
            );
          })}
        </div>
      </div>

      {/* Log content */}
      <div className="flex-1 overflow-auto">
        {loading && (
          <div className="text-subtle text-[13px] py-16 text-center">
            Loading log…
          </div>
        )}
        {error && (
          <div className="p-6 text-bear text-[12px] font-mono">{error}</div>
        )}
        {!loading && data && (
          <table className="w-full text-[11px] font-mono border-collapse">
            <thead className="sticky top-0 bg-surface z-10">
              <tr className="border-b border-border text-subtle text-[10px]">
                <th className="text-left px-4 py-2 w-40 shrink-0">#&nbsp;&nbsp;Time</th>
                <th className="text-left px-3 py-2 w-20 shrink-0">Level</th>
                <th className="text-left px-3 py-2 w-52 shrink-0 hidden md:table-cell">
                  Logger
                </th>
                <th className="text-left px-3 py-2">Message</th>
              </tr>
            </thead>
            <tbody>
              {visibleLines.map((line, i) => (
                <tr
                  key={i}
                  className={`${rowBg(line.level)} hover:bg-border/20 transition-colors`}
                >
                  <td className="px-4 py-1 text-muted whitespace-nowrap align-top select-none">
                    <span className="text-border mr-2 text-[9px]">
                      {String(i + 1).padStart(4, "0")}
                    </span>
                    {line.timestamp.slice(11)}
                  </td>
                  <td className="px-3 py-1 align-top">
                    <LevelBadge level={line.level} />
                  </td>
                  <td className="px-3 py-1 text-subtle align-top hidden md:table-cell max-w-[13rem] truncate">
                    {line.logger}
                  </td>
                  <td className="px-3 py-1 text-text align-top break-all whitespace-pre-wrap">
                    {line.message}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!loading && data && visibleLines.length === 0 && (
          <div className="text-subtle text-[12px] text-center py-16">
            No {filter !== "ALL" ? filter.toLowerCase() + " " : ""}lines found.
          </div>
        )}
      </div>
    </div>
  );
}

// ── Session list row ──────────────────────────────────────────────────────────

function SessionRow({
  session,
  onClick,
}: {
  session: LogSession;
  onClick: () => void;
}) {
  const runTime = session.run_datetime.includes("T")
    ? session.run_datetime.split("T")[1]
    : session.run_datetime;

  return (
    <button
      onClick={onClick}
      className="w-full text-left group hover:bg-surface transition-colors border-b border-border last:border-b-0"
    >
      <div className="flex items-center gap-4 px-5 py-4">
        {/* Status dot */}
        <div
          className={`w-2 h-2 rounded-full shrink-0 ${
            session.has_error ? "bg-bear" : "bg-bull"
          }`}
        />

        {/* Run time */}
        <div className="w-28 shrink-0">
          <div className="text-[13px] font-mono text-text">{runTime}</div>
          <div className="text-[10px] text-subtle mt-0.5">
            {fmtIst(session.run_datetime)}
          </div>
        </div>

        {/* Stats chips */}
        <div className="flex items-center gap-2 flex-1 flex-wrap">
          <span className="text-[11px] text-subtle border border-border px-2 py-0.5 font-mono">
            {session.line_count.toLocaleString()} lines
          </span>
          {session.error_count > 0 && (
            <span className="text-[11px] text-bear border border-bear/30 bg-bear/8 px-2 py-0.5 font-mono">
              {session.error_count} error{session.error_count !== 1 ? "s" : ""}
            </span>
          )}
          {session.warning_count > 0 && (
            <span className="text-[11px] text-gold border border-gold/30 bg-gold/8 px-2 py-0.5 font-mono">
              {session.warning_count} warning{session.warning_count !== 1 ? "s" : ""}
            </span>
          )}
          {!session.has_error && session.error_count === 0 && (
            <span className="text-[11px] text-bull border border-bull/30 bg-bull/8 px-2 py-0.5 font-mono">
              clean
            </span>
          )}
        </div>

        {/* Size + arrow */}
        <div className="hidden lg:flex items-center gap-4 text-[11px] text-subtle">
          <span>{fmtBytes(session.size_bytes)}</span>
          <span className="font-mono">{session.key.split("/").pop()}</span>
        </div>

        <span className="text-muted text-[12px] ml-2 group-hover:text-text transition-colors">
          →
        </span>
      </div>
    </button>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LogsPage() {
  const [date, setDate] = useState(today());
  const [sessions, setSessions] = useState<LogSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);

  const load = useCallback(async (d: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.logSessions(d);
      setSessions(data.sessions);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load";
      // 404 just means no sessions yet for that day — not an error
      if (msg.includes("404") || msg.includes("No sessions")) {
        setSessions([]);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(date);
  }, [date, load]);

  // Show detail panel full-screen when a session is selected
  if (activeKey) {
    return (
      <LogDetailPanel
        sessionKey={activeKey}
        onClose={() => setActiveKey(null)}
      />
    );
  }

  const totalErrors = sessions.reduce((s, x) => s + x.error_count, 0);
  const totalWarnings = sessions.reduce((s, x) => s + x.warning_count, 0);

  return (
    <div className="max-w-[1200px] mx-auto px-6 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between pb-6 border-b border-border">
        <div>
          <h1 className="text-xl font-semibold text-text">Run Logs</h1>
          <p className="text-[12px] text-subtle mt-0.5">
            Each row is one completed run · stored in S3 · click to view full log
          </p>
        </div>
        <input
          type="date"
          value={date}
          max={today()}
          onChange={(e) => setDate(e.target.value)}
          className="bg-surface border border-border text-text text-[12px] px-3 py-1.5 font-mono focus:outline-none focus:border-accent"
        />
      </div>

      {/* Day-level summary strip */}
      {sessions.length > 0 && (
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="px-3 py-1 border border-border text-subtle font-mono">
            {sessions.length} session{sessions.length !== 1 ? "s" : ""}
          </span>
          <span className="px-3 py-1 border border-border text-subtle font-mono">
            {sessions.reduce((s, x) => s + x.line_count, 0).toLocaleString()} total lines
          </span>
          {totalErrors > 0 ? (
            <span className="px-3 py-1 border border-bear/30 bg-bear/8 text-bear font-mono">
              {totalErrors} error{totalErrors !== 1 ? "s" : ""}
            </span>
          ) : (
            <span className="px-3 py-1 border border-bull/30 bg-bull/8 text-bull font-mono">
              0 errors
            </span>
          )}
          {totalWarnings > 0 && (
            <span className="px-3 py-1 border border-gold/30 bg-gold/8 text-gold font-mono">
              {totalWarnings} warning{totalWarnings !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="text-subtle text-[13px] py-16 text-center">
          Loading sessions…
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="border border-bear/40 bg-bear/8 p-4 text-bear text-[12px] font-mono">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && sessions.length === 0 && (
        <div className="border border-border py-20 text-center">
          <p className="text-muted text-[13px]">No log sessions for {date}</p>
          <p className="text-subtle text-[11px] mt-2">
            Run the daily pipeline — it uploads its log to S3 on completion.
          </p>
        </div>
      )}

      {/* Session list — CloudWatch log streams style */}
      {!loading && sessions.length > 0 && (
        <div className="border border-border bg-bg">
          {/* Column headers */}
          <div className="flex items-center gap-4 px-5 py-2 border-b border-border bg-surface text-[10px] font-semibold tracking-widest text-muted uppercase">
            <div className="w-2 shrink-0" />
            <div className="w-28 shrink-0">Run time</div>
            <div className="flex-1">Summary</div>
            <div className="hidden lg:block">File</div>
            <div className="w-6" />
          </div>
          {sessions.map((s) => (
            <SessionRow
              key={s.key}
              session={s}
              onClick={() => setActiveKey(s.key)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
