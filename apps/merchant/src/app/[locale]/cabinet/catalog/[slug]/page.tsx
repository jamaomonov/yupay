"use client";

import { ArrowLeft, Check, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";

import type { PlacedOrder, Product, Sku } from "@/lib/types";

import { useCabinet } from "@/components/CabinetContext";
import { ApiError, api } from "@/lib/api";
import { soleSku } from "@/lib/catalog";
import { orderStatusLabel } from "@/lib/labels";
import { pathFor } from "@/lib/locale-href";
import { fixedTotal, formatPrice, formatUsd, scaledTotal, toCents } from "@/lib/money";

/** What this SKU is sized by, and therefore which box the form shows. */
function countLabel(sku: Sku): "none" | "quantity" | "amount" {
  if (sku.kind === "unit") return "quantity";
  if (sku.kind === "amount") return "amount";
  return "none";
}

export default function BrandPage() {
  const t = useTranslations("merchant.catalog");
  const tOrders = useTranslations("merchant.orders");
  const tCabinet = useTranslations("merchant.cabinet");
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

  // Steam's «any amount», Stars: one card and nothing to choose — open with it picked.
  // Once only, so closing the sheet on a phone does not bring it straight back.
  const autoPicked = useRef(false);
  useEffect(() => {
    if (autoPicked.current || brand === null) return;
    autoPicked.current = true;
    const only = soleSku(brand);
    if (only !== null) {
      setSelected(only);
      setCount(only.kind === "unit" ? String(only.min_qty ?? 1) : "1");
    }
  }, [brand]);
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

      {/* While a denomination is picked on a phone, the order form floats over
          the bottom of the list; the padding keeps the last row reachable. */}
      <div
        className={`mt-6 grid gap-6 lg:grid-cols-[1fr_20rem] lg:pb-0 ${selected ? "pb-80" : ""}`}
      >
        <div className="space-y-6">
          {brand.products.map((item) => (
            <section key={item.product_id}>
              <h2 className="text-tx-mute text-sm font-medium">{item.name}</h2>
              {/* Two columns from the smallest phone up: one column made PUBG's
                  28 denominations a 4700px scroll, and the form under it. */}
              <div className="mt-3 grid grid-cols-2 gap-2 2xl:grid-cols-3">
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
                      aria-pressed={active}
                      className={`relative flex min-h-[4.5rem] flex-col justify-between rounded-lg border p-3 text-left transition ${
                        active
                          ? "border-primary bg-card-2"
                          : "border-border bg-card hover:border-border-2"
                      }`}
                    >
                      <div className="flex items-start gap-2 pr-5">
                        <span className="bg-card-2 border-border h-10 w-10 shrink-0 overflow-hidden rounded-md border">
                          {sku.image_url !== null && (
                            /* eslint-disable-next-line @next/next/no-img-element -- an
                               operator-entered absolute URL on a host we do not
                               control; same reason the brand logo above uses <img>. */
                            <img
                              src={sku.image_url}
                              alt=""
                              className="h-full w-full object-contain"
                            />
                          )}
                        </span>
                        <p className="line-clamp-2 text-sm font-medium leading-snug">{sku.name}</p>
                      </div>
                      {active && (
                        <span
                          aria-label={t("selected")}
                          className="bg-primary text-primary-foreground absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full"
                        >
                          <Check size={12} strokeWidth={3} />
                        </span>
                      )}
                      <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2 font-mono text-sm">
                        <span>{price ? `$${formatPrice(price)}` : "—"}</span>
                        {sku.kind === "amount" && price && (
                          <span className="text-tx-dim font-sans text-[11px]">
                            {t("perDollar")}
                          </span>
                        )}
                        {sku.retail_price_usd && (
                          <span className="text-tx-dim text-xs line-through">
                            ${formatPrice(sku.retail_price_usd)}
                          </span>
                        )}
                      </p>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        {/* On a phone the form is a sheet pinned above the tab bar, shown only
            once something is picked: under the list it sat 4000px below the
            denomination the reseller had just tapped, with nothing saying it
            was there. From `lg` it is the sticky column it always was. */}
        <aside
          className={`border-border bg-card z-30 h-fit border p-5 lg:sticky lg:inset-auto lg:top-20 lg:block lg:rounded-xl ${
            selected
              ? "fixed inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] max-h-[70dvh] overflow-y-auto rounded-t-2xl shadow-[0_-12px_40px_rgba(0,0,0,0.45)] md:bottom-0 lg:max-h-none lg:overflow-visible lg:shadow-none"
              : "hidden"
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-semibold">{t("orderSummary")}</p>
              {selected !== null && (
                <div className="mt-0.5 flex min-w-0 items-center gap-2 lg:hidden">
                  {selected.image_url !== null && (
                    /* eslint-disable-next-line @next/next/no-img-element -- see the
                       denomination tiles: operator-entered absolute URL. */
                    <img
                      src={selected.image_url}
                      alt=""
                      className="h-8 w-8 shrink-0 rounded-md object-contain"
                    />
                  )}
                  <p className="text-tx-mute truncate text-sm">{selected.name}</p>
                </div>
              )}
            </div>
            {selected !== null && (
              <button
                type="button"
                aria-label={tCabinet("close")}
                onClick={() => {
                  setSelected(null);
                  setPlaced(null);
                  setError(null);
                }}
                className="border-border text-tx-mute flex h-8 w-8 shrink-0 items-center justify-center rounded-full border lg:hidden"
              >
                <X size={15} />
              </button>
            )}
          </div>
          {selected === null ? (
            <p className="text-tx-dim mt-3 text-sm">—</p>
          ) : (
            <div className="mt-3 lg:mt-4">
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
                <p role="alert" translate="no" className="text-danger mt-3 text-sm">
                  {error}
                </p>
              )}
              {placed && (
                <p role="status" translate="no" className="text-primary-ink mt-3 text-sm">
                  {t("created")} · {orderStatusLabel(placed.status, tOrders)}
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

              {!affordable && total !== null && (
                // The string existed and was unreachable: `notEnough` was only
                // set from an API error, and the request can never be sent
                // because the button above is disabled. So a fresh account —
                // every account, on day one — saw a greyed button and a red
                // negative number, and had to infer the rest. The dashboard
                // card that explains it is two screens away and does not
                // follow you here.
                <p className="text-danger mt-3 text-[12px] leading-relaxed">
                  {t("notEnough")}{" "}
                  <a
                    href="https://t.me/yupay_support"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    {tCabinet("requestDeposit")}
                  </a>
                </p>
              )}

              <p className="text-tx-dim mt-3 text-[12px] leading-relaxed">{t("whatsNext")}</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
