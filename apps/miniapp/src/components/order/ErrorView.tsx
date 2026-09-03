import { ShoppingBag } from "lucide-react";

import { useT } from "@/lib/i18n";

/**
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function ErrorView({
  title,
  subtitle,
  onHome,
}: {
  title: string;
  subtitle: string;
  onHome: () => void;
}) {
  const { t } = useT();
  return (
    <div className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
      <ShoppingBag size={40} className="text-white/20" />
      <div>
        <p className="font-semibold text-white">{title}</p>
        <p className="mt-1 text-xs text-white/45">{subtitle}</p>
      </div>
      <button
        onClick={onHome}
        className="rounded-full px-5 py-2 text-sm font-semibold"
        style={{
          background: "hsl(var(--primary))",
          color: "hsl(var(--primary-foreground))",
        }}
      >
        {t("common.toHome")}
      </button>
    </div>
  );
}
