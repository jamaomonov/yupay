import { motion } from "framer-motion";
import { Copy } from "lucide-react";

import { COPYABLE_ARTIFACT_LABEL, labelForField, pickArtifactDisplay } from "./order-helpers";

import type { ArtifactKind, DeliveryOut } from "@/lib/orders";

import { useToast } from "@/hooks/use-toast";
import { useT } from "@/lib/i18n";
import { getActiveLocale, translate } from "@/lib/i18n/core";

function labelForKind(kind: ArtifactKind): string {
  switch (kind) {
    case "voucher_code":
      return translate("success.kind.voucher");
    case "license_key":
      return translate("success.kind.license");
    case "topup_receipt":
      return translate("success.kind.receipt");
  }
}

function CopyableValue({
  value,
  label,
  onCopy,
}: {
  value: string;
  label: string;
  onCopy: (v: string) => void;
}) {
  return (
    <button
      onClick={() => {
        onCopy(value);
      }}
      className="group flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors active:scale-[0.99]"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1.5px solid hsl(var(--primary) / 0.45)",
      }}
    >
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-wide text-white/40">{label}</p>
        <p className="mt-0.5 break-all font-mono text-sm text-white">{value}</p>
      </div>
      <div
        className="flex size-8 flex-shrink-0 items-center justify-center rounded-lg transition-colors"
        style={{ background: "hsl(var(--primary) / 0.18)" }}
      >
        <Copy size={13} style={{ color: "hsl(var(--primary))" }} />
      </div>
    </button>
  );
}

/**
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function ArtifactBlock({ delivery }: { delivery: DeliveryOut }) {
  const { toast } = useToast();
  const { t } = useT();

  const onCopy = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast({ title: t("success.copied", { label }) });
    } catch {
      toast({
        title: t("common.copyFailed"),
        description: t("common.copyManual"),
        variant: "destructive",
      });
    }
  };

  const display = pickArtifactDisplay(delivery.artifact);

  return (
    <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-3">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.08em]"
          style={{ color: "hsl(var(--primary))" }}
        >
          {labelForKind(delivery.artifact_kind)}
        </span>
        <span className="text-[10px] text-white/25">·</span>
        <span className="text-[10px] text-white/35">
          {new Date(delivery.delivered_at).toLocaleString(getActiveLocale(), {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      {display.kind === "copyable" && (
        <CopyableValue
          value={display.value}
          label={t(COPYABLE_ARTIFACT_LABEL[display.artifactKey])}
          onCopy={(v) => void onCopy(v, t(COPYABLE_ARTIFACT_LABEL[display.artifactKey]))}
        />
      )}
      {display.kind === "text" && (
        <div
          className="rounded-xl px-3 py-2.5 text-xs leading-snug text-white/75"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <span className="text-white/45">{t("success.credited")} · </span>
          <span>{display.value}</span>
        </div>
      )}
      {display.kind === "fields" && (
        <div
          className="space-y-1.5 rounded-xl p-3"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          {display.entries.map(([field, value]) => (
            <div key={field} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-white/50">{labelForField(field)}</span>
              <span className="max-w-[60%] truncate text-right font-mono text-white">{value}</span>
            </div>
          ))}
        </div>
      )}
      {display.kind === "empty" && (
        <div
          className="rounded-xl px-3 py-2.5 text-xs leading-snug text-white/60"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          {t("success.credited")}
        </div>
      )}
    </motion.div>
  );
}
