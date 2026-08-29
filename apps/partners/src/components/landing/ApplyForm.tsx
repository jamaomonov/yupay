"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { apiBase } from "@/lib/api";

import { SHELL } from "./shell";

/**
 * The application form, as the page's closing band.
 *
 * Lime, full-bleed, black type: the one place the page inverts, so the ask is
 * the last thing anyone can miss. The fields are all still here — only the
 * email is required, and the rest are what an admin needs to reply to a person
 * rather than to an address.
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

  // Dark-on-lime, so the inputs read as wells cut into the band rather than as
  // pale boxes sitting on top of it. `black/50` rather than `/25`: at a quarter
  // the border sat at 1.82:1 against the band, under the 3:1 WCAG 1.4.11 asks
  // of a control boundary, and the fields read as ghosts. And no `outline-none`
  // — it was removing the only focus indicator on the form this page exists
  // for, leaving a border darkening as the whole signal.
  const field =
    "focus-ring-invert h-12 w-full rounded-full border border-black/50 bg-black/[0.06] px-5 text-[14px] text-black transition placeholder:text-black/40 focus:border-black";
  const label = "mb-2 block text-[12.5px] font-semibold text-black/60";

  return (
    <section id="apply" className="bg-primary text-primary-foreground">
      <div className={`${SHELL} grid grid-cols-1 gap-10 py-14 lg:grid-cols-2 lg:gap-16 lg:py-16`}>
        <div>
          {/* `break-words` as a floor, not a plan: a locale whose longest word does
              not fit should wrap rather than run off the band. */}
          <h2 className="font-display break-words text-[clamp(2rem,5.4vw,2.9rem)] font-extrabold leading-[1.02] tracking-[-0.035em]">
            {t("bandTitle")}
          </h2>
          <p className="mt-3.5 max-w-md text-pretty text-[15px] font-medium leading-relaxed text-black/65">
            {state === "done" ? t("doneBody") : t("bandSubtitle")}
          </p>
        </div>

        {state === "done" ? (
          <div className="flex items-center">
            <p
              // Announced rather than merely rendered: the form it replaces is
              // gone from the tab order, so a screen-reader user gets no other
              // signal that anything happened.
              role="status"
              className="font-display rounded-2xl border border-black/25 bg-black/[0.06] px-6 py-5 text-[18px] font-bold"
            >
              {t("doneTitle")}
            </p>
          </div>
        ) : (
          <form onSubmit={(e) => void submit(e)} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="block">
              <span className={label}>{t("email")}</span>
              <input name="email" type="email" required autoComplete="email" className={field} />
            </label>
            <label className="block">
              <span className={label}>{t("name")}</span>
              <input
                name="name"
                type="text"
                maxLength={128}
                autoComplete="name"
                className={field}
              />
            </label>
            <label className="block">
              <span className={label}>{t("contact")}</span>
              <input name="contact" type="text" maxLength={128} className={field} />
            </label>
            <label className="block">
              <span className={label}>{t("channel")}</span>
              <input name="channel" type="text" maxLength={512} className={field} />
              <span className="mt-2 block text-[12px] font-medium text-black/60">
                {t("channelHint")}
              </span>
            </label>

            <div className="sm:col-span-2">
              {/* Black, not `red-900`: on this band the red cleared contrast but
                  was the one foreign hue on the page, and the weight already
                  reads as alarm. */}
              {state === "error" && (
                <p role="alert" className="mb-3 text-[13px] font-bold text-black">
                  {t("errGeneric")}
                </p>
              )}
              <button
                type="submit"
                disabled={state === "sending"}
                className="focus-ring-invert text-primary h-12 w-full rounded-full bg-black text-[15px] font-bold transition hover:brightness-125 disabled:opacity-50 sm:w-auto sm:px-9"
              >
                {state === "sending" ? t("submitting") : t("submit")}
              </button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
