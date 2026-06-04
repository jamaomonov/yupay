import { Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { TOOLTIP_STYLE } from "./theme";

const PALETTE = ["var(--accent)", "#6aa3ff", "#f4a261", "#9b8cff", "#4cc9a0", "#e07a8b"] as const;
const FALLBACK_COLOR = PALETTE[0];

interface DonutShareProps {
  data: { name: string; value: number }[];
  height?: number;
}

export function DonutShare({ data, height = 240 }: DonutShareProps) {
  // recharts v3 deprecates <Cell>; we set `fill` per datum (still supported by <Pie>) to colour slices.
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
        <Tooltip contentStyle={TOOLTIP_STYLE} />
      </PieChart>
    </ResponsiveContainer>
  );
}
