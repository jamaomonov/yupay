"use client";

import { ArrowLeft, Minus, Plus, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Brand, Field, PlacedOrder, PlayerCheck, Product, Sku } from "@/lib/types";

import { BrandMark } from "@/components/BrandMark";
import { useCabinet } from "@/components/CabinetContext";
import { SkuRows } from "@/components/catalog/SkuRows";
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

/**
 * Does the value satisfy the field's own pattern? A pattern the browser cannot
 * compile (they are written for Python) counts as satisfied: the server still
 * checks, and a form that refuses everything is worse than one that lets a
 * typo through to a clear error.
 */
function matches(field: Field, value: string): boolean {
  if (field.pattern === null || value === "") return true;
  try {
    return new RegExp(field.pattern).test(value);
  } catch {
    return true;
  }
}

/** The field a player check verifies — the first required text that is not a server. */
function idFieldOf(product: Product | null): Field | null {
  return (
    product?.required_fields.find(
      (f) => f.required && f.type === "text" && !/server|zone|region/i.test(f.key),
    ) ?? null
  );
}

function serverFieldOf(product: Product | null): Field | null {
  return product?.required_fields.find((f) => /server|zone|region/i.test(f.key)) ?? null;
}

function Skeleton() {
  return (
    <div aria-busy className="animate-pulse">
      <div className="bg-card-2 h-3 w-40 rounded" />
      <div className="mt-4 flex items-center gap-3.5">
        <div className="bg-card-2 h-13 w-13 rounded-xl" />
        <div className="space-y-2">
          <div className="bg-card-2 h-5 w-48 rounded" />
          <div className="bg-card-2 h-3 w-32 rounded" />
        </div>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className="bg-card border-border h-12 rounded-lg border" />
          ))}
        </div>
        <div className="bg-card border-border hidden h-40 rounded-xl border lg:block" />
      </div>
    </div>
  );
}

export default function BrandPage() {
  const t = useTranslations("merchant.catalog");
  const tOrders = useTranslations("merchant.orders");
  const tCabinet = useTranslations("merchant.cabinet");
  const locale = useLocale();
  const { locale: routeLocale, slug } = useParams<{ locale: string; slug: string }>();
  const { profile, refreshProfile } = useCabinet();
  // This brand's own subtree, fetched here: the shell only holds the grid's
  // cards. `undefined` while loading, `null` when the reseller cannot buy it.
  const [brand, setBrand] = useState<Brand | null | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    void api<Brand>(`/catalog/brands/${encodeURIComponent(slug)}`).then(
      (loaded) => {
        if (!cancelled) setBrand(loaded);
      },
      () => {
        if (!cancelled) setBrand(null);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [slug]);
  const [selected, setSelected] = useState<Sku | null>(null);
  const [count, setCount] = useState("1");
  const [data, setData] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [placed, setPlaced] = useState<PlacedOrder | null>(null);
  // Minted once per intent and held, never per request: a fresh key on every
  // attempt is the same as having none. `api.ts` says exactly this; the
  // cabinet's own order call was the one place that ignored it, so a retry
  // after a timeout could charge twice.
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [error, setError] = useState<string | null>(null);
  // The player check: `null` not asked, `"busy"` in flight, else the verdict.
  // `unsupported` hides the button for the rest of the visit — nothing on
  // this brand can be checked, and a button that always says so is noise.
  const [check, setCheck] = useState<PlayerCheck | "busy" | null>(null);
  const [checkable, setCheckable] = useState(true);

  // Steam's «any amount», Stars: one card and nothing to choose — open with it picked.
  // Once only, so closing the sheet on a phone does not bring it straight back.
  const autoPicked = useRef(false);
  useEffect(() => {
    if (autoPicked.current || !brand) return;
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
  const fields = product?.required_fields ?? [];
  const idField = idFieldOf(product);
  const serverField = serverFieldOf(product);

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
  const formOk = fields.every((field) => {
    const value = data[field.key] ?? "";
    return (!field.required || value.trim() !== "") && matches(field, value);
  });

  function pick(sku: Sku) {
    setSelected(sku);
    setPlaced(null);
    setError(null);
    setCount(sku.kind === "unit" ? String(sku.min_qty ?? 1) : "1");
  }

  function bump(delta: number) {
    if (!selected) return;
    const min = selected.min_qty ?? 1;
    const max = selected.max_qty ?? Number.MAX_SAFE_INTEGER;
    const current = Number.parseInt(count, 10);
    const next = Math.min(max, Math.max(min, (Number.isNaN(current) ? min : current) + delta));
    setCount(String(next));
  }

  async function verify() {
    if (!brand || !idField) return;
    const playerId = (data[idField.key] ?? "").trim();
    if (playerId === "") return;
    const serverId = serverField ? (data[serverField.key] ?? "").trim() : "";
    setCheck("busy");
    try {
      const verdict = await api<PlayerCheck>("/validate/player", {
        method: "POST",
        body: {
          brand: brand.slug,
          player_id: playerId,
          ...(serverId !== "" ? { server_id: serverId } : {}),
        },
      });
      setCheck(verdict);
      if (verdict.status === "unsupported") setCheckable(false);
    } catch {
      setCheck({ status: "error", name: null });
    }
  }

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
      // The server's own sentence where it wrote one (a refused id, a
      // withdrawn SKU): «Не удалось создать заказ» told a reseller nothing
      // about what to change.
      if (err instanceof ApiError && err.code === "insufficient_deposit") setError(t("notEnough"));
      else if (err instanceof ApiError && !err.message.startsWith("HTTP ")) setError(err.message);
      else setError(t("orderFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (brand === undefined) {
    return <Skeleton />;
  }
  if (brand === null) {
    return (
      <div>
        <Link href={`/${routeLocale}/cabinet/catalog`} className="text-tx-mute text-sm">
          {t("backToCatalog")}
        </Link>
      </div>
    );
  }

  // The import named most products after their brand; saying the name twice
  // under the heading told a reseller nothing, where the count of lines does.
  const skuTotal = brand.products.reduce((n, p) => n + p.skus.length, 0);
  const ownNames = brand.products
    .map((p) => p.name)
    .filter((name) => name.toLowerCase() !== brand.name.toLowerCase());
  const shape = selected ? countLabel(selected) : "none";

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
        <BrandMark name={brand.name} logoUrl={brand.logo_url} size="lg" />
        <div className="min-w-0">
          <h1 className="font-display truncate text-xl font-semibold tracking-tight">
            {brand.name}
          </h1>
          <p className="text-tx-dim mt-0.5 truncate text-xs">
            {ownNames.length > 0 ? ownNames.join(" · ") : t("skuCount", { count: skuTotal })}
          </p>
        </div>
      </div>

      {/* While a denomination is picked on a phone, the order form floats over
          the bottom of the list; the padding keeps the last row reachable. */}
      <div
        className={`mt-6 grid gap-6 lg:grid-cols-[1fr_20rem] lg:pb-0 ${selected ? "pb-80" : ""}`}
      >
        <SkuRows brand={brand} selected={selected} onPick={pick} />

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
                <div className="mt-0.5 flex min-w-0 items-center gap-2">
                  {selected.image_url !== null && (
                    /* eslint-disable-next-line @next/next/no-img-element -- see the
                       denomination rows: operator-entered absolute URL. */
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
            <p className="text-tx-dim mt-3 text-sm leading-relaxed">{t("pickOne")}</p>
          ) : (
            <div className="mt-3 lg:mt-4">
              {shape === "quantity" && (
                <div className="mb-3">
                  <span className="text-tx-mute mb-1.5 block text-sm">{t("quantity")}</span>
                  <div className="flex items-stretch gap-2">
                    <button
                      type="button"
                      aria-label="−"
                      onClick={() => {
                        bump(-1);
                      }}
                      className="border-border bg-card-2 rounded-btn flex w-11 shrink-0 items-center justify-center border"
                    >
                      <Minus size={15} />
                    </button>
                    <input
                      value={count}
                      inputMode="numeric"
                      onChange={(event) => {
                        setCount(event.target.value.replace(/[^\d]/g, ""));
                      }}
                      onBlur={() => {
                        bump(0);
                      }}
                      className="border-border bg-card-2 rounded-btn w-full border px-3 py-2 text-center font-mono text-sm"
                    />
                    <button
                      type="button"
                      aria-label="+"
                      onClick={() => {
                        bump(1);
                      }}
                      className="border-border bg-card-2 rounded-btn flex w-11 shrink-0 items-center justify-center border"
                    >
                      <Plus size={15} />
                    </button>
                  </div>
                  {(selected.min_qty !== null || selected.max_qty !== null) && (
                    <p className="text-tx-dim mt-1.5 text-[11.5px]">
                      {t("countRange", {
                        min: selected.min_qty ?? 1,
                        max: selected.max_qty ?? "∞",
                      })}
                    </p>
                  )}
                </div>
              )}
              {shape === "amount" && (
                <label className="mb-3 block">
                  <span className="text-tx-mute mb-1.5 block text-sm">{t("amountUsd")}</span>
                  <input
                    value={count}
                    inputMode="decimal"
                    onChange={(event) => {
                      setCount(event.target.value);
                    }}
                    className="border-border bg-card-2 rounded-btn w-full border px-3 py-2 font-mono text-sm"
                  />
                  {(selected.min_amount_usd !== null || selected.max_amount_usd !== null) && (
                    <span className="text-tx-dim mt-1.5 block text-[11.5px]">
                      {t("countRange", {
                        min: `$${formatPrice(selected.min_amount_usd ?? "0")}`,
                        max: selected.max_amount_usd
                          ? `$${formatPrice(selected.max_amount_usd)}`
                          : "∞",
                      })}
                    </span>
                  )}
                </label>
              )}

              {fields.map((field) => {
                const value = data[field.key] ?? "";
                const bad = touched[field.key] === true && !matches(field, value);
                const isId = idField?.key === field.key;
                return (
                  <label key={field.key} className="mb-3 block">
                    <span className="text-tx-mute mb-1.5 block text-sm">
                      {field.label[locale] ?? field.label.ru ?? field.key}
                    </span>
                    <div className="flex gap-2">
                      <input
                        value={value}
                        placeholder={field.placeholder[locale] ?? ""}
                        aria-invalid={bad}
                        onChange={(event) => {
                          setData((current) => ({ ...current, [field.key]: event.target.value }));
                          if (isId || serverField?.key === field.key) setCheck(null);
                        }}
                        onBlur={() => {
                          setTouched((current) => ({ ...current, [field.key]: true }));
                        }}
                        className={`rounded-btn bg-card-2 w-full border px-3 py-2 text-sm ${
                          bad ? "border-danger" : "border-border"
                        }`}
                      />
                      {isId && checkable && (
                        <button
                          type="button"
                          disabled={check === "busy" || value.trim() === "" || bad}
                          onClick={() => {
                            void verify();
                          }}
                          className="border-border rounded-btn shrink-0 border px-3 text-xs font-semibold disabled:opacity-50"
                        >
                          {check === "busy" ? t("checking") : t("checkId")}
                        </button>
                      )}
                    </div>
                    {bad && (
                      <span className="text-danger mt-1 block text-xs">{t("fieldInvalid")}</span>
                    )}
                    {isId &&
                      check !== null &&
                      check !== "busy" &&
                      check.status !== "unsupported" && (
                        <span
                          role="status"
                          className={`mt-1 block text-xs ${
                            check.status === "valid"
                              ? "text-primary-ink"
                              : check.status === "invalid"
                                ? "text-danger"
                                : "text-tx-dim"
                          }`}
                        >
                          {check.status === "valid"
                            ? `✓ ${t("idValid")}${check.name ? ` · ${check.name}` : ""}`
                            : check.status === "invalid"
                              ? t("idInvalid")
                              : t("idError")}
                        </span>
                      )}
                  </label>
                );
              })}

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
                disabled={busy || placed !== null || total === null || !affordable || !formOk}
                onClick={() => {
                  setTouched(Object.fromEntries(fields.map((f) => [f.key, true])));
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
                // negative number, and had to infer the rest.
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
