"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import type { PlacedOrder, Product, Sku } from "@/lib/types";

import { useCabinet } from "@/components/CabinetContext";
import { ApiError, api } from "@/lib/api";
import { pathFor } from "@/lib/locale-href";
import { fixedTotal, formatUsd, scaledTotal, toCents } from "@/lib/money";

/** What this SKU is sized by, and therefore which box the form shows. */
function countLabel(sku: Sku): "none" | "quantity" | "amount" {
  if (sku.kind === "unit") return "quantity";
  if (sku.kind === "amount") return "amount";
  return "none";
}

export default function BrandPage() {
  const t = useTranslations("merchant.catalog");
  const tOrders = useTranslations("merchant.orders");
  const locale = useLocale();
  const { locale: routeLocale, slug } = useParams<{ locale: string; slug: string }>();
  const { catalog, profile, refreshProfile } = useCabinet();
  const [selected, setSelected] = useState<Sku | null>(null);
  const [count, setCount] = useState("1");
  const [data, setData] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [placed, setPlaced] = useState<PlacedOrder | null>(null);
  // Minted once per intent and held, never per request: a fresh key on every
  // attempt is the same as having none. `api.ts` says exactly this; the
  // cabinet's own order call was the one place that ignored it, so a retry
  // after a timeout could charge twice.
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [error, setError] = useState<string | null>(null);

  const brand = catalog?.brands.find((b) => b.slug === slug) ?? null;
  const product: Product | null =
    brand?.products.find((p) => p.skus.some((s) => s.sku_id === selected?.sku_id)) ??
    brand?.products[0] ??
    null;

  const total = useMemo(() => {
    if (!selected) return null;
    const shape = countLabel(selected);
    if (shape === "none") return selected.price_usd ? fixedTotal(selected.price_usd) : null;
    if (!selected.unit_price_usd || !count.trim()) return null;
    return scaledTotal(selected.unit_price_usd, count);
  }, [selected, count]);

  const balance = profile ? toCents(profile.balance_usd) : null;
  const after = balance !== null && total !== null ? balance - total : null;
  const affordable = after !== null && after >= 0n;

  async function order() {
    if (!selected || total === null) return;
    setBusy(true);
    setError(null);
    try {
      const shape = countLabel(selected);
      const body = {
        sku_id: selected.sku_id,
        ...(shape === "quantity" ? { quantity: Number(count) } : {}),
        ...(shape === "amount" ? { amount_usd: formatUsd(toCents(count)) } : {}),
        // The same number the summary showed, computed by the same rule the
        // server uses — so the drift check compares two identical figures and
        // a merchant is never charged something the screen did not say.
        expected_price: formatUsd(total),
        fulfillment_data: data,
      };
      const result = await api<PlacedOrder>("/orders", { method: "POST", body, idempotencyKey });
      setPlaced(result);
      // The response carries the balance the charge left behind, but the top
      // bar reads the shell's copy — so re-read rather than patch two places
      // that could then disagree.
      refreshProfile();
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "insufficient_deposit"
          ? t("notEnough")
          : t("orderFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  if (!brand) {
    return (
      <div>
        <Link href={`/${routeLocale}/cabinet/catalog`} className="text-tx-mute text-sm">
          {t("backToCatalog")}
        </Link>
      </div>
    );
  }

  return (
    <div>
      <nav className="text-tx-dim flex flex-wrap items-center gap-1.5 text-xs">
        <Link href={`/${routeLocale}/cabinet/catalog`} className="inline-flex items-center gap-1">
          <ArrowLeft size={12} />
          {t("backToCatalog")}
        </Link>
        {brand.category_name !== null && (
          <>
            <span aria-hidden>›</span>
            <Link href={`/${routeLocale}/cabinet/catalog?section=${brand.category_slug ?? ""}`}>
              {brand.category_name}
            </Link>
          </>
        )}
        <span aria-hidden>›</span>
        <span className="text-foreground">{brand.name}</span>
      </nav>

      <div className="mt-3 flex items-center gap-3.5">
        <div className="bg-card-2 border-border h-13 w-13 shrink-0 overflow-hidden rounded-xl border">
          {brand.logo_url !== null && (
            /* eslint-disable-next-line @next/next/no-img-element -- see the
               catalog grid: an operator-entered absolute URL on a host we do
               not control. */
            <img src={brand.logo_url} alt="" className="h-full w-full object-cover" />
          )}
        </div>
        <div className="min-w-0">
          <h1 className="font-display truncate text-xl font-semibold tracking-tight">
            {brand.name}
          </h1>
          <p className="text-tx-dim mt-0.5 truncate text-xs">
            {brand.products.map((item) => item.name).join(" · ")}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-6">
          {brand.products.map((item) => (
            <section key={item.product_id}>
              <h2 className="text-tx-mute text-sm font-medium">{item.name}</h2>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {item.skus.map((sku) => {
                  const price = sku.kind === "fixed" ? sku.price_usd : sku.unit_price_usd;
                  const active = selected?.sku_id === sku.sku_id;
                  return (
                    <button
                      key={sku.sku_id}
                      type="button"
                      onClick={() => {
                        setSelected(sku);
                        setPlaced(null);
                        setError(null);
                        setCount(sku.kind === "unit" ? String(sku.min_qty ?? 1) : "1");
                      }}
                      className={`rounded-lg border p-3 text-left ${
                        active ? "border-primary bg-card-2" : "border-border bg-card"
                      }`}
                    >
                      <p className="text-sm font-medium">
                        {sku.name}
                        {active && (
                          <span className="text-primary-ink ml-2 text-[11px] font-semibold">
                            ✓ {t("selected")}
                          </span>
                        )}
                      </p>
                      <p className="mt-1 font-mono text-sm">
                        {price ? `$${price}` : "—"}
                        {sku.retail_price_usd && (
                          <span className="text-tx-dim ml-2 line-through">
                            ${sku.retail_price_usd}
                          </span>
                        )}
                      </p>
                      <p className="text-tx-dim mt-1.5 font-mono text-[11px]">
                        {t("apiId")}: {sku.sku_id.slice(0, 8)}…
                      </p>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        <aside className="border-border bg-card h-fit rounded-xl border p-5">
          <p className="font-semibold">{t("orderSummary")}</p>
          {selected === null ? (
            <p className="text-tx-dim mt-3 text-sm">—</p>
          ) : (
            <div className="mt-4">
              {countLabel(selected) !== "none" && (
                <label className="mb-3 block">
                  <span className="text-tx-mute mb-1.5 block text-sm">
                    {countLabel(selected) === "quantity" ? t("quantity") : t("amountUsd")}
                  </span>
                  <input
                    value={count}
                    inputMode="decimal"
                    onChange={(event) => {
                      setCount(event.target.value);
                    }}
                    className="border-border bg-card-2 rounded-btn w-full border px-3 py-2 text-sm"
                  />
                </label>
              )}

              {(product?.required_fields ?? []).map((field) => (
                <label key={field.key} className="mb-3 block">
                  <span className="text-tx-mute mb-1.5 block text-sm">
                    {field.label[locale] ?? field.label.ru ?? field.key}
                  </span>
                  <input
                    value={data[field.key] ?? ""}
                    placeholder={field.placeholder[locale] ?? ""}
                    onChange={(event) => {
                      setData((current) => ({ ...current, [field.key]: event.target.value }));
                    }}
                    className="border-border bg-card-2 rounded-btn w-full border px-3 py-2 text-sm"
                  />
                </label>
              ))}

              <dl className="border-border mt-4 space-y-1.5 border-t pt-4 text-sm">
                <div className="flex justify-between">
                  <dt className="text-tx-mute">{t("priceNow")}</dt>
                  <dd className="font-mono font-semibold">
                    {total === null ? "—" : `$${formatUsd(total)}`}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-tx-mute">{t("priceBefore")}</dt>
                  <dd className="font-mono">{balance === null ? "—" : `$${formatUsd(balance)}`}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-tx-mute">{t("depositAfter")}</dt>
                  <dd className={`font-mono ${affordable ? "" : "text-danger"}`}>
                    {after === null ? "—" : `$${formatUsd(after)}`}
                  </dd>
                </div>
              </dl>

              {error && (
                <p role="alert" className="text-danger mt-3 text-sm">
                  {error}
                </p>
              )}
              {placed && (
                <p role="status" className="text-primary-ink mt-3 text-sm">
                  {t("created")} · <span className="font-mono">{placed.status}</span>
                  {" · "}
                  <Link
                    href={pathFor(
                      locale,
                      `/cabinet/orders/${encodeURIComponent(placed.merchant_order_id)}`,
                    )}
                    className="underline underline-offset-4"
                  >
                    {tOrders("openOrder")}
                  </Link>
                </p>
              )}

              <button
                type="button"
                disabled={busy || placed !== null || total === null || !affordable}
                onClick={() => {
                  void order();
                }}
                className="bg-primary text-primary-foreground rounded-btn mt-4 w-full py-2.5 text-sm font-semibold disabled:opacity-50"
              >
                {busy
                  ? t("creating")
                  : total === null
                    ? t("createOrder")
                    : `${t("createOrder")} · $${formatUsd(total)}`}
              </button>

              <p className="text-tx-dim mt-3 break-all font-mono text-[11px]">
                {t("apiHint")}: sku_id {selected.sku_id}
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
