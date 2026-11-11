/**
 * One USDT receiving chain: on/off switch and receiving address, saved on its
 * own (`PATCH /networks/{code}`). A changed address closes that chain's pending
 * reservations, so it goes through a confirm dialog that says so.
 *
 * Local state syncs from this card's own save response only: saving one chain
 * never wipes an address being typed into another (BEP20 and ERC20 often
 * share one).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useId, useRef, useState } from "react";

import {
  fill,
  saveNetwork,
  T,
  usdtErrorMessage,
  type UsdtNetwork,
  type UsdtNetworkPatch,
  type UsdtSettings,
} from "./api";

import type { ApiError } from "@/lib/api";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { qk } from "@/lib/queryKeys";

const N = T.networks;

interface Props {
  network: UsdtNetwork;
}

export function UsdtNetworkCard({ network }: Props) {
  const qc = useQueryClient();
  const hintId = useId();
  const [enabled, setEnabled] = useState(network.enabled);
  const [address, setAddress] = useState(network.address ?? "");
  const [confirming, setConfirming] = useState(false);
  const [saved, setSaved] = useState(false);
  const idemKey = useRef<string | null>(null);

  const code = network.network;
  const label = N.labels[code];
  const trimmed = address.trim();
  const nextAddress = trimmed === "" ? null : trimmed;
  const addressChanged = nextAddress !== network.address;
  const dirty = addressChanged || enabled !== network.enabled;

  const save = useMutation<UsdtSettings, ApiError>({
    mutationFn: () => {
      idemKey.current ??= crypto.randomUUID();
      const body: UsdtNetworkPatch = {
        ...(enabled !== network.enabled ? { enabled } : {}),
        ...(addressChanged ? { address: nextAddress } : {}),
      };
      return saveNetwork(code, body, idemKey.current);
    },
    onSuccess: (next) => {
      idemKey.current = null;
      setConfirming(false);
      qc.setQueryData(qk.usdtSettings(), next);
      const mine = next.networks.find((n) => n.network === code);
      if (mine) {
        setEnabled(mine.enabled);
        setAddress(mine.address ?? "");
      }
      void qc.invalidateQueries({ queryKey: qk.usdtReservations() });
      setSaved(true);
    },
    onError: () => {
      setConfirming(false);
    },
  });

  const edited = () => {
    idemKey.current = null;
    setSaved(false);
  };

  return (
    <section
      aria-label={label}
      className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-medium">{label}</h3>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              setEnabled(e.target.checked);
              edited();
            }}
          />
          {N.enabled}
        </label>
      </div>
      <label className="mb-1 block text-sm">
        <span className="mb-1 block text-xs text-[var(--text-secondary)]">{N.address}</span>
        <Input
          className="font-mono text-xs"
          spellCheck={false}
          autoComplete="off"
          aria-describedby={hintId}
          value={address}
          onChange={(e) => {
            setAddress(e.target.value);
            edited();
          }}
        />
      </label>
      <p id={hintId} className="mb-2 text-xs text-[var(--text-secondary)]">
        {code === "trc20" ? N.hints.trc20 : `${N.hints.evm}. ${N.sameAddress}`}
      </p>
      {enabled && trimmed === "" ? (
        <p role="status" className="mb-2 text-sm text-[var(--danger)]">
          {N.noAddress}
        </p>
      ) : null}
      <p className="mb-3 text-xs text-[var(--text-secondary)]">
        {network.cursor === null
          ? N.cursorNone
          : fill(N.cursor, { cursor: String(network.cursor) })}
      </p>
      {save.isError ? (
        <p role="alert" className="mb-2 text-sm text-[var(--danger)]">
          {usdtErrorMessage(save.error)}
        </p>
      ) : null}
      {saved ? <p className="mb-2 text-sm text-[var(--success-fg)]">{N.saved}</p> : null}
      <Button
        disabled={!dirty || save.isPending}
        onClick={() => {
          if (addressChanged) setConfirming(true);
          else save.mutate();
        }}
      >
        {save.isPending ? N.saving : N.save}
      </Button>
      {confirming ? (
        <ConfirmDialog
          title={fill(N.confirmTitle, { network: N.short[code] })}
          confirmLabel={N.confirm}
          cancelLabel={N.cancel}
          tone="danger"
          busy={save.isPending}
          onConfirm={() => {
            save.mutate();
          }}
          onCancel={() => {
            setConfirming(false);
          }}
        >
          <p className="text-sm">
            {nextAddress === null
              ? fill(N.confirmBodyCleared, { network: N.short[code] })
              : fill(N.confirmBody, { network: N.short[code], address: nextAddress })}
          </p>
          <p className="mt-2 rounded-md bg-[var(--warning-soft)] p-2 text-xs text-[var(--warning-fg)]">
            {N.addressWarning}
          </p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
