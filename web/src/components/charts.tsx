"use client";

import { Table2 } from "lucide-react";
import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "@/lib/utils";

import { Card } from "./ui/primitives";

/** Chart card: title, optional table view (every chart is also readable as data). */
export function ChartCard({
  title,
  subtitle,
  rows,
  columns,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  rows: (string | number)[][];
  columns: string[];
  children: React.ReactNode;
  className?: string;
}) {
  const [table, setTable] = React.useState(false);
  return (
    <Card className={cn("p-5", className)}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-bold">{title}</h3>
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        {rows.length > 0 && (
          <button
            type="button"
            onClick={() => setTable(!table)}
            aria-pressed={table}
            className={cn("rounded-lg p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground", table && "bg-muted text-foreground")}
            aria-label={table ? "Show chart" : "Show as table"}
            title={table ? "Show chart" : "Show as table"}
          >
            <Table2 className="size-4" />
          </button>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="flex h-48 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">No data yet</p>
      ) : table ? (
        <div className="max-h-56 overflow-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
              <tr>{columns.map((c) => <th key={c} className="px-3 py-2 text-left font-semibold">{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t">
                  {r.map((v, j) => <td key={j} className={cn("px-3 py-1.5", j > 0 && "tabular-nums")}>{v}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-52">{children}</div>
      )}
    </Card>
  );
}

function ChartTooltip({ active, payload, label, unit, labelFormat }: {
  active?: boolean; payload?: { value: number }[]; label?: string; unit: string; labelFormat?: (l: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border bg-popover px-3 py-2 text-sm shadow-lg">
      <p className="text-xs text-muted-foreground">{labelFormat ? labelFormat(String(label)) : label}</p>
      <p className="font-semibold tabular-nums text-foreground">
        {payload[0].value}
        {unit}
      </p>
    </div>
  );
}

const axis = { stroke: "var(--muted-foreground)", fontSize: 11, tickLine: false, axisLine: false } as const;

export function SimpleBars({ data, x, y, unit = "", horizontal, labelFormat }: {
  data: Record<string, string | number>[]; x: string; y: string; unit?: string; horizontal?: boolean; labelFormat?: (l: string) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 4, right: 8, bottom: 0, left: horizontal ? 8 : -16 }}>
        <CartesianGrid stroke="var(--border)" strokeWidth={1} horizontal={!horizontal} vertical={!!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" {...axis} allowDecimals={false} />
            <YAxis type="category" dataKey={x} {...axis} width={92} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} {...axis} tickFormatter={labelFormat} minTickGap={12} />
            <YAxis {...axis} allowDecimals={false} />
          </>
        )}
        <Tooltip cursor={{ fill: "var(--muted)", opacity: 0.6 }} content={<ChartTooltip unit={unit} labelFormat={labelFormat} />} />
        <Bar dataKey={y} fill="var(--lang)" maxBarSize={24} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SimpleLine({ data, x, y, unit = "", domain, labelFormat }: {
  data: Record<string, string | number>[]; x: string; y: string; unit?: string; domain?: [number, number]; labelFormat?: (l: string) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}>
        <CartesianGrid stroke="var(--border)" strokeWidth={1} vertical={false} />
        <XAxis dataKey={x} {...axis} tickFormatter={labelFormat} minTickGap={16} />
        <YAxis {...axis} domain={domain ?? ["auto", "auto"]} allowDecimals={false} />
        <Tooltip cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }} content={<ChartTooltip unit={unit} labelFormat={labelFormat} />} />
        <Line
          type="monotone"
          dataKey={y}
          stroke="var(--lang)"
          strokeWidth={2}
          strokeLinecap="round"
          dot={{ r: 4, fill: "var(--lang)", stroke: "var(--card)", strokeWidth: 2 }}
          activeDot={{ r: 6, fill: "var(--lang)", stroke: "var(--card)", strokeWidth: 2 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** GitHub-style activity heatmap: one sequential hue (the language accent), light → dark. */
export function Heatmap({ days }: { days: { date: string; xp: number; minutes: number }[] }) {
  const scroller = React.useRef<HTMLDivElement>(null);
  // on narrow screens start scrolled to the most recent weeks
  React.useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [days]);
  const byDate = new Map(days.map((d) => [d.date, d]));
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 7 * 52 - today.getDay());
  const cells: { date: string; xp: number; minutes: number; future: boolean }[] = [];
  for (let d = new Date(start); cells.length < 53 * 7; d.setDate(d.getDate() + 1)) {
    const iso = d.toLocaleDateString("en-CA");
    const v = byDate.get(iso);
    cells.push({ date: iso, xp: v?.xp ?? 0, minutes: v?.minutes ?? 0, future: d > today });
  }
  const max = Math.max(1, ...days.map((d) => d.xp));
  const level = (xp: number) => (xp <= 0 ? 0 : Math.min(4, Math.ceil((xp / max) * 4)));
  const shades = ["var(--muted)", "color-mix(in oklab, var(--lang) 30%, var(--card))", "color-mix(in oklab, var(--lang) 55%, var(--card))", "color-mix(in oklab, var(--lang) 78%, var(--card))", "var(--lang)"];
  const active = days.filter((d) => d.xp > 0).length;
  return (
    <div>
      <div ref={scroller} className="overflow-x-auto pb-1 scrollbar-none">
        <div className="grid w-max grid-flow-col grid-rows-7 gap-[3px]" role="img" aria-label={`Activity heatmap: active on ${active} days in the last year`}>
          {cells.map((c) => (
            <span
              key={c.date}
              title={c.future ? "" : `${new Date(c.date).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}: ${c.xp} XP · ${c.minutes} min`}
              className="size-[11px] rounded-[3px]"
              style={{ background: c.future ? "transparent" : shades[level(c.xp)] }}
            />
          ))}
        </div>
      </div>
      <div className="mt-2 flex items-center justify-end gap-1.5 text-[11px] text-muted-foreground">
        Less {shades.map((s, i) => <span key={i} className="size-[11px] rounded-[3px]" style={{ background: s }} />)} More
      </div>
    </div>
  );
}
