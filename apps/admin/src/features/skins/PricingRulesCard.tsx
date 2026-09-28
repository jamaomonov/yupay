/**
 * The pricing document as a form: expenses, the storefront and B2B markup brackets,
 * liquidity bands, category and weapon adjustments, margin floor, rounding, Steam cap.
 * Saved whole with PUT; the server validates and reprices the catalogue. A refusal is
 * shown and the operator's input is kept. One Idempotency-Key per save attempt, kept
 * across a retry of the same document and dropped on success or on the next edit.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useRef, useState } from "react";

import { T } from "./api";
import { putPricing, refusal, type PricingRules } from "./pricing-api";
import { BracketRows, Card, INPUT, MapRows, NumberField } from "./pricing-ui";

import { qk } from "@/lib/queryKeys";

const P = T.pricing.rules;

/** Every number filled in: an empty field would reach the server as 0 or "". */
function complete(r: PricingRules): boolean {
  const filled = (v: string) => v.trim() !== "";
  return (
    [r.expenses_percent, r.min_margin_usd, r.price_floor_usd].every(filled) &&
    Number.isInteger(r.uzs_round_to) &&
    r.uzs_round_to >= 1 &&
    [...r.retail, ...r.b2b].every((b) => filled(b.from_usd) && filled(b.percent)) &&
    r.liquidity.every((b) => Number.isInteger(b.min_count) && filled(b.pp)) &&
    Object.values({ ...r.category_pp, ...r.weapon_pp }).every(filled)
  );
}

export function PricingRulesCard({
  rules,
  categories,
}: {
  rules: PricingRules;
  categories: string[];
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<PricingRules>(rules);
  const [newWeapon, setNewWeapon] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const key = useRef<string | null>(null);
  // Bumped on every edit: a save's answer replaces the form only if nothing was typed
  // while it was in flight — otherwise the newer input is kept (and not yet saved).
  const version = useRef(0);

  const edit = (patch: Partial<PricingRules>) => {
    key.current = null;
    version.current += 1;
    setMessage(null);
    setDraft((d) => ({ ...d, ...patch }));
  };

  const save = useMutation({
    mutationFn: (sentAt: number) => {
      key.current ??= `skins-pricing-${crypto.randomUUID()}`;
      return putPricing(draft, key.current).then((out) => ({ out, sentAt }));
    },
    onSuccess: ({ out, sentAt }) => {
      key.current = null;
      if (sentAt === version.current) setDraft(out.rules);
      setMessage({ ok: true, text: P.saved });
      void qc.invalidateQueries({ queryKey: qk.skinPricing() });
    },
    onError: (err) => {
      setMessage({ ok: false, text: refusal(err) });
    },
  });

  return (
    <Card title={P.title}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <NumberField
          label={P.expenses}
          value={draft.expenses_percent}
          onChange={(v) => {
            edit({ expenses_percent: v });
          }}
        />
        <NumberField
          label={P.minMargin}
          value={draft.min_margin_usd}
          onChange={(v) => {
            edit({ min_margin_usd: v });
          }}
        />
        <NumberField
          label={P.floor}
          value={draft.price_floor_usd}
          onChange={(v) => {
            edit({ price_floor_usd: v });
          }}
        />
        <NumberField
          label={P.roundTo}
          step="1"
          value={String(draft.uzs_round_to)}
          onChange={(v) => {
            edit({ uzs_round_to: Number(v) });
          }}
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={draft.cap_at_steam}
          onChange={(e) => {
            edit({ cap_at_steam: e.target.checked });
          }}
        />
        {P.capAtSteam}
      </label>
      <div className="grid gap-4 md:grid-cols-2">
        <BracketRows
          title={P.retail}
          rows={draft.retail}
          onChange={(retail) => {
            edit({ retail });
          }}
        />
        <BracketRows
          title={P.b2b}
          rows={draft.b2b}
          onChange={(b2b) => {
            edit({ b2b });
          }}
        />
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{P.liquidity}</legend>
        {draft.liquidity.map((band, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              aria-label={`${P.minCount} ${String(i + 1)}`}
              type="number"
              step="1"
              value={band.min_count}
              onChange={(e) => {
                edit({
                  liquidity: draft.liquidity.map((b, j) =>
                    j === i ? { ...b, min_count: Number(e.target.value) } : b,
                  ),
                });
              }}
              className={INPUT}
            />
            <input
              aria-label={`${P.pp} ${String(i + 1)}`}
              type="number"
              step="0.01"
              value={band.pp}
              onChange={(e) => {
                edit({
                  liquidity: draft.liquidity.map((b, j) =>
                    j === i ? { ...b, pp: e.target.value } : b,
                  ),
                });
              }}
              className={INPUT}
            />
          </div>
        ))}
      </fieldset>
      <MapRows
        title={P.categories}
        keys={categories}
        values={draft.category_pp}
        onChange={(category_pp) => {
          edit({ category_pp });
        }}
      />
      <MapRows
        title={P.weapons}
        keys={Object.keys(draft.weapon_pp)}
        values={draft.weapon_pp}
        onChange={(weapon_pp) => {
          edit({ weapon_pp });
        }}
      />
      <div className="flex items-center gap-2">
        <input
          aria-label={P.weapon}
          placeholder={P.weapon}
          value={newWeapon}
          onChange={(e) => {
            setNewWeapon(e.target.value);
          }}
          className={`${INPUT} max-w-48`}
        />
        <Button
          variant="ghost"
          size="sm"
          disabled={newWeapon.trim() === ""}
          onClick={() => {
            edit({ weapon_pp: { ...draft.weapon_pp, [newWeapon.trim()]: "0" } });
            setNewWeapon("");
          }}
        >
          {P.addRow}
        </Button>
      </div>
      <div className="flex items-center gap-3">
        <Button
          disabled={save.isPending}
          onClick={() => {
            if (!complete(draft)) {
              setMessage({ ok: false, text: P.incomplete });
              return;
            }
            save.mutate(version.current);
          }}
        >
          {P.save}
        </Button>
        {message && (
          <p
            role={message.ok ? "status" : "alert"}
            className={`text-sm ${message.ok ? "text-[var(--success-fg)]" : "text-[var(--danger)]"}`}
          >
            {message.text}
          </p>
        )}
      </div>
    </Card>
  );
}
