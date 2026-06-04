import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { TOOLTIP_STYLE } from "./theme";

interface LineTrendProps {
  data: { x: string; y: number }[];
  height?: number;
}

export function LineTrend({ data, height = 240 }: LineTrendProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
        <XAxis dataKey="x" tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} />
        <YAxis tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} width={48} />
        <Tooltip contentStyle={TOOLTIP_STYLE} />
        <Line type="monotone" dataKey="y" stroke="var(--accent)" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
