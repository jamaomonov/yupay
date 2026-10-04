/** Add/edit form for one P2P card. The number is write-only. */

import { useMutation } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useRef, useState } from "react";

import {
  createCard,
  patchCard,
  T,
  p2pErrorMessage,
  type P2PCard,
  type P2PCardInput,
  type P2PNetwork,
} from "./api";

import type { ApiError } from "@/lib/api";

interface Props {
  /** The card being edited, or `null` to add a new one. */
  card: P2PCard | null;
  onDone: () => void;
  onCancel: () => void;
}

export function P2PCardForm({ card, onDone, onCancel }: Props) {
  const F = T.cards.form;
  const [label, setLabel] = useState(card?.label ?? "");
  const [pan, setPan] = useState("");
  const [holder, setHolder] = useState(card?.holder_name ?? "");
  const [network, setNetwork] = useState<P2PNetwork>(
    card?.network === "uzcard" ? "uzcard" : "humo",
  );
  const [min, setMin] = useState((card?.min_amount_uzs ?? 10000).toString());
  const [max, setMax] = useState((card?.max_amount_uzs ?? 10000000).toString());
  const [daily, setDaily] = useState(card?.daily_limit_uzs?.toString() ?? "");
  const [active, setActive] = useState(card?.active ?? true);

  // One key per logical save: reused when the same request is retried (a lost
  // response must not create a second card), dropped on any edit or success.
  const idemKey = useRef<string | null>(null);

  const save = useMutation<P2PCard, ApiError>({
    mutationFn: () => {
      const body: P2PCardInput = {
        label: label.trim(),
        holder_name: holder.trim(),
        network,
        min_amount_uzs: Number.parseInt(min, 10),
        max_amount_uzs: Number.parseInt(max, 10),
        daily_limit_uzs: daily.trim() === "" ? null : Number.parseInt(daily, 10),
        active,
        // The number goes out only when a new one was typed.
        ...(pan.trim() !== "" ? { pan: pan.trim() } : {}),
      };
      idemKey.current ??= crypto.randomUUID();
      return card ? patchCard(card.id, body, idemKey.current) : createCard(body, idemKey.current);
    },
    onSuccess: () => {
      idemKey.current = null;
      onDone();
    },
  });

  const ints = [min, max].every((v) => /^\d+$/.test(v)) && (daily === "" || /^\d+$/.test(daily));
  const canSave =
    label.trim() !== "" && holder.trim() !== "" && (card !== null || pan.trim() !== "") && ints;

  return (
    <form
      onChange={() => {
        idemKey.current = null;
      }}
      aria-label={card ? F.editTitle.replace("{label}", card.label) : F.addTitle}
      className="mb-6 max-w-3xl rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSave) save.mutate();
      }}
    >
      <h2 className="mb-3 font-medium">
        {card ? F.editTitle.replace("{label}", card.label) : F.addTitle}
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Labelled text={F.label}>
          <Input
            value={label}
            onChange={(e) => {
              setLabel(e.target.value);
            }}
            maxLength={64}
          />
        </Labelled>
        <Labelled text={F.pan} hint={F.panHint}>
          <Input
            value={pan}
            inputMode="numeric"
            autoComplete="off"
            placeholder={card ? `•••• ${card.pan_last4}` : ""}
            onChange={(e) => {
              setPan(e.target.value);
            }}
          />
        </Labelled>
        <Labelled text={F.holder}>
          <Input
            value={holder}
            onChange={(e) => {
              setHolder(e.target.value);
            }}
            maxLength={128}
          />
        </Labelled>
        <Labelled text={F.network}>
          <select
            className="h-9 w-full rounded-md border bg-[var(--bg-surface)] px-2 text-sm"
            value={network}
            onChange={(e) => {
              setNetwork(e.target.value === "uzcard" ? "uzcard" : "humo");
            }}
          >
            <option value="humo">HUMO</option>
            <option value="uzcard">UZCARD</option>
          </select>
        </Labelled>
        <Labelled text={F.min}>
          <Input
            value={min}
            inputMode="numeric"
            onChange={(e) => {
              setMin(e.target.value);
            }}
          />
        </Labelled>
        <Labelled text={F.max}>
          <Input
            value={max}
            inputMode="numeric"
            onChange={(e) => {
              setMax(e.target.value);
            }}
          />
        </Labelled>
        <Labelled text={F.daily}>
          <Input
            value={daily}
            inputMode="numeric"
            onChange={(e) => {
              setDaily(e.target.value);
            }}
          />
        </Labelled>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => {
              setActive(e.target.checked);
            }}
          />
          {F.active}
        </label>
      </div>
      {save.isError ? (
        <p role="alert" className="mt-3 text-sm text-[var(--danger)]">
          {p2pErrorMessage(save.error)}
        </p>
      ) : null}
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={save.isPending || !canSave}>
          {save.isPending ? F.saving : F.save}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {F.cancel}
        </Button>
      </div>
    </form>
  );
}

function Labelled({
  text,
  hint,
  children,
}: {
  text: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs text-[var(--text-secondary)]">{text}</span>
      {children}
      {hint ? (
        <span className="mt-1 block text-xs text-[var(--text-secondary)]">{hint}</span>
      ) : null}
    </label>
  );
}
