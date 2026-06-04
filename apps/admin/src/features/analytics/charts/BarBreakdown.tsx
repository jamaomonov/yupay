import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { TOOLTIP_STYLE } from "./theme";

interface BarBreakdownProps {
  data: { name: string; value: number }[];
  height?: number;
}

export function BarBreakdown({ data, height = 240 }: BarBreakdownProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
        <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} />
        <YAxis tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} width={48} />
        <Tooltip contentStyle={TOOLTIP_STYLE} />
        <Bar dataKey="value" fill="var(--accent)" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
