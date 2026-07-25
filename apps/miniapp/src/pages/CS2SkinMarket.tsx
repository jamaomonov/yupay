import { Clock } from "lucide-react";

import { useT } from "@/lib/i18n";
import { useDocumentTitle } from "@/lib/use-document-title";

export default function CS2SkinMarket() {
  const { t } = useT();
  useDocumentTitle(t("cs2.docTitle"));

  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center px-6 text-center">
      <div
        className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl border"
        style={{
          background: "hsl(var(--surface-2))",
          borderColor: "hsl(var(--border) / 0.6)",
        }}
      >
        <Clock className="text-primary h-8 w-8" strokeWidth={1.75} />
      </div>

      <span className="text-primary mb-3 text-xs font-semibold uppercase tracking-[0.14em]">
        {t("cs2.soonBadge")}
      </span>

      <h1 className="max-w-[300px] text-xl font-bold leading-tight tracking-tight text-white">
        {t("cs2.soonTitle")}
      </h1>
      <p className="text-body-muted mt-2.5 max-w-[300px] text-sm leading-relaxed">
        {t("cs2.soonSubtitle")}
      </p>
    </div>
  );
}
