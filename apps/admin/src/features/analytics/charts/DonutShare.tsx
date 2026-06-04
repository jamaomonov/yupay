import { Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const PALETTE = ["var(--accent)", "#6aa3ff", "#f4a261", "#9b8cff", "#4cc9a0", "#e07a8b"] as const;
const FALLBACK_COLOR = PALETTE[0];

interface DonutShareProps {
  data: { name: string; value: number }[];
  height?: number;
}

export function DonutShare({ data, height = 240 }: DonutShareProps) {
  // Recharts v3 deprecates <Cell>; per-slice colours are now supplied via a
  // `fill` field on each datum (the documented migration path).
  const coloured = data.map((d, i) => ({
    ...d,
    fill: PALETTE[i % PALETTE.length] ?? FALLBACK_COLOR,
  }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={coloured}
          dataKey="value"
          nameKey="name"
          innerRadius={56}
          outerRadius={88}
          paddingAngle={2}
        />
        <Tooltip
          contentStyle={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
