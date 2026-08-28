"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { apiBase } from "@/lib/api";

/**
 * The application form.
 *
 * It answers the same whether the address is new or has already applied,
 * because the API does — telling someone "you already applied" would let
 * anyone with a list of addresses discover which of them are partners. So
 * there is one success state and it is reached either way.
 */

type State = "idle" | "sending" | "done" | "error";

/**
 * One text field out of a form, as a string or null.
 *
 * `FormData.get` is typed `string | File | null` — every entry could be a file
 * upload as far as the type system knows. Coercing with `String()` would
 * happily produce "[object File]" and post it as an email address.
 */
function text(form: FormData, name: string): string | null {
  const value = form.get(name);
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export function ApplyForm() {
  const t = useTranslations("partners.apply");
  const [state, setState] = useState<State>("idle");

  async function submit(event: React.SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (state === "sending") return;
    const form = new FormData(event.currentTarget);
    setState("sending");
    try {
      const res = await fetch(`${apiBase()}/api/v1/affiliate/applications`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: text(form, "email") ?? "",
          display_name: text(form, "name"),
          contact: text(form, "contact"),
          channel: text(form, "channel"),
        }),
      });
      setState(res.ok ? "done" : "error");
    } catch {
      setState("error");
    }
  }

  if (state === "done") {
    return (
      <section id="apply" className="mx-auto max-w-2xl px-5 py-20 sm:py-24">
        <div className="border-primary/40 bg-primary/5 rounded-2xl border p-8 text-center">
          <h2 className="font-display text-xl font-bold">{t("doneTitle")}</h2>
          <p className="text-tx-mute mt-2 text-[14px] leading-relaxed">{t("doneBody")}</p>
        </div>
      </section>
    );
  }

  const field =
    "border-border bg-card-2 rounded-btn h-12 w-full border px-4 text-[15px] outline-none focus:border-primary/60";

  return (
    <section id="apply" className="mx-auto max-w-2xl px-5 py-20 sm:py-24">
      <h2 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">{t("title")}</h2>
      <p className="text-tx-mute mt-2 text-[14px]">{t("subtitle")}</p>

      <form onSubmit={(e) => void submit(e)} className="mt-8 space-y-4">
        <label className="block">
          <span className="text-tx-mute mb-2 block text-[13px]">{t("email")}</span>
          <input name="email" type="email" required autoComplete="email" className={field} />
        </label>
        <label className="block">
          <span className="text-tx-mute mb-2 block text-[13px]">{t("name")}</span>
          <input name="name" type="text" maxLength={128} autoComplete="name" className={field} />
        </label>
        <label className="block">
          <span className="text-tx-mute mb-2 block text-[13px]">{t("contact")}</span>
          <input name="contact" type="text" maxLength={128} className={field} />
        </label>
        <label className="block">
          <span className="text-tx-mute mb-2 block text-[13px]">{t("channel")}</span>
          <input name="channel" type="text" maxLength={512} className={field} />
          <span className="text-tx-dim mt-1.5 block text-[12px]">{t("channelHint")}</span>
        </label>

        {state === "error" && <p className="text-[13px] text-red-400">{t("errGeneric")}</p>}

        <button
          type="submit"
          disabled={state === "sending"}
          className="bg-primary text-primary-foreground rounded-btn h-12 w-full text-[15px] font-semibold transition hover:brightness-110 disabled:opacity-50"
        >
          {state === "sending" ? t("submitting") : t("submit")}
        </button>
      </form>
    </section>
  );
}
