"use client";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { DailyNavPoint, BenchmarkPoint, formatINR } from "@/lib/api";

interface Props {
  navPoints: DailyNavPoint[];
  niftyPoints: BenchmarkPoint[];
  initialCapital: number;
}

interface ChartPoint {
  date: string;
  portfolio: number;
  nifty: number;
}

function shortDate(isoDate: string): string {
  const d = new Date(isoDate);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

export function NavChart({ navPoints, niftyPoints, initialCapital }: Props) {
  const niftyMap = new Map(niftyPoints.map((p) => [p.date, p.nav]));

  const data: ChartPoint[] = navPoints.map((p) => ({
    date: shortDate(p.date),
    portfolio: p.nav,
    nifty: niftyMap.get(p.date) ?? initialCapital,
  }));

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-muted text-sm">
        No NAV data yet — first run will populate this chart.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="2 4" stroke="#222222" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: "#666666", fontSize: 10, fontFamily: "Inter, sans-serif" }}
          axisLine={false}
          tickLine={false}
          dy={6}
        />
        <YAxis
          tickFormatter={(v) => formatINR(v)}
          tick={{ fill: "#666666", fontSize: 10, fontFamily: "Inter, sans-serif" }}
          axisLine={false}
          tickLine={false}
          width={80}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1a1a1a",
            border: "1px solid #2a2a2a",
            borderRadius: 0,
            color: "#f0f0f0",
            fontSize: 11,
            fontFamily: "Inter, sans-serif",
          }}
          formatter={(value: number, name: string) => [
            formatINR(value, 0),
            name === "portfolio" ? "Portfolio" : "Nifty 50 TRI",
          ]}
          labelStyle={{ color: "#999999", marginBottom: 4 }}
        />
        <Line
          type="monotone"
          dataKey="portfolio"
          stroke="#c8c0a8"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: "#c8c0a8", stroke: "#c8c0a8" }}
        />
        <Line
          type="monotone"
          dataKey="nifty"
          stroke="#444444"
          strokeWidth={1.5}
          strokeDasharray="4 4"
          dot={false}
          activeDot={{ r: 3, fill: "#666666", stroke: "#666666" }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
