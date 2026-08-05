/**
 * Gates the app behind a branded loading screen until:
 *
 *   1. ``window.Telegram.WebApp.initData`` arrives (cold-launch race fix).
 *   2. ``/auth/telegram/webapp`` returns a session (or we decide to fall back
 *      to anonymous mode — plain browser or no-init-data).
 *   3. Essential read APIs are warm in the React Query cache (catalog, ``me``).
 *
 * On failure the gate stays mounted and shows a retry button — the user no
 * longer needs to close-and-reopen the miniapp to recover.
 */

import { useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { SplashWordmark } from "@/components/SplashWordmark";
import { ApiError, apiGet, getAccessToken } from "@/lib/api";
import { bootstrapAuth, decideBoot } from "@/lib/auth";
import { brandsQueryOptions, categoriesQueryOptions } from "@/lib/catalog";
import { useT, type MessageKey } from "@/lib/i18n";
import { launchedFromTelegram } from "@/lib/telegram";

type Phase = "booting" | "ready" | "error";

/**
 * Either a raw detail from the server (already localized by the API) or a
 * catalog key for our own fallback copy. Stored unresolved so the ``run``
 * callback never depends on ``t`` — otherwise the locale settling once ``me``
 * loads would re-trigger the whole bootstrap.
 */
type BootError = { detail: string } | { key: MessageKey };

/** Minimum splash duration in ms. Prevents flashes on instant loads. */
const MIN_SPLASH_MS = 650;

/**
 * How long the wordmark reveal runs end-to-end (see SplashWordmark.tsx +
 * the ``yp-*`` keyframes in index.css): U pops at 0.1s, Y/P A Y finish
 * sliding at ≈1.55s, and the tagline fades in last, settling at ≈1.8s.
 * On a warm-cache boot the data is ready well before that, so we hold the
 * splash until the reveal finishes instead of cutting it off mid-slide —
 * but only on the first launch (see ``release``).
 */
const SPLASH_ANIM_MS = 1_850;

/** Hard cap on a single bootstrap attempt. */
const HARD_BOOT_TIMEOUT_MS = 10_000;

/**
 * When opened from Telegram but the session isn't ready yet (cold-launch race,
 * or a transient login failure), retry silently behind the splash this many
 * times before surfacing a manual retry button — the app is NEVER released
 * signed out inside Telegram.
 */
const AUTO_RETRY_MAX = 4;
const AUTO_RETRY_DELAY_MS = 700;

/**
 * Whether the user asked the OS to minimise motion. The reveal's CSS
 * keyframes collapse to their end state under this (global rule in
 * index.css), so there's nothing to wait for — we must skip the animation
 * floor or the user would stare at a static, finished wordmark for ~1.8s.
 */
function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function BootstrapGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [phase, setPhase] = useState<Phase>("booting");
  const [stage, setStage] = useState<MessageKey>("bootstrap.connecting");
  const [error, setError] = useState<BootError | null>(null);
  const startedAt = useRef<number>(Date.now());
  const attemptRef = useRef<number>(0);
  const autoRetryRef = useRef<number>(0);

  const release = useCallback(async () => {
    // First cold launch holds for the full wordmark reveal so a fast boot
    // doesn't truncate it mid-slide; the splash only mounts (and the CSS
    // animation only plays) once per launch, so a retry after an error has
    // nothing left to show and falls back to the anti-flash minimum.
    const floor =
      attemptRef.current <= 1 && !prefersReducedMotion() ? SPLASH_ANIM_MS : MIN_SPLASH_MS;
    const elapsed = Date.now() - startedAt.current;
    const wait = Math.max(0, floor - elapsed);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    setPhase("ready");
  }, []);

  const run = useCallback(async () => {
    const attempt = ++attemptRef.current;
    setPhase("booting");
    setError(null);
    setStage("bootstrap.connectingTelegram");
    startedAt.current = Date.now();

    // Never release the app SIGNED OUT when we were opened from Telegram: retry
    // silently behind the splash (cold-launch races settle within a few tries),
    // then fall back to a manual retry button — still never an anonymous app.
    const retryOrSurface = (err?: ApiError | Error) => {
      if (attemptRef.current !== attempt) return;
      if (autoRetryRef.current < AUTO_RETRY_MAX) {
        autoRetryRef.current += 1;
        setStage("bootstrap.connectingTelegram");
        setTimeout(() => {
          if (attemptRef.current === attempt) void run();
        }, AUTO_RETRY_DELAY_MS);
        return;
      }
      const detail = err instanceof ApiError ? err.detail : err?.message;
      setError(detail ? { detail } : { key: "bootstrap.errorSession" });
      setPhase("error"); // manual retry — but children stay unmounted
    };

    // Hard timeout — a single attempt shouldn't hang forever. A stuck attempt
    // never reached a clean release (that clears this timer), so inside Telegram
    // it means no fresh session → retry, never an anonymous release.
    const hardTimer = setTimeout(() => {
      if (attemptRef.current !== attempt) return;
      if (launchedFromTelegram()) retryOrSurface();
      else void release();
    }, HARD_BOOT_TIMEOUT_MS);

    try {
      const auth = await bootstrapAuth();
      if (attemptRef.current !== attempt) return; // newer run in flight

      // Only a FRESH login counts as authenticated — a stale localStorage token
      // from a past session must not release the app (it would 401 on /me and
      // strand the user signed out, the original bug in a subtler form).
      const decision = decideBoot(auth.status === "ok", launchedFromTelegram());
      if (decision === "retry") {
        // Opened from Telegram but no session yet (race or transient failure).
        clearTimeout(hardTimer);
        retryOrSurface(auth.status === "failed" ? auth.error : undefined);
        return;
      }

      // decision is "ready" (authenticated) or "anonymous" (plain-browser dev).
      setStage("bootstrap.loadingCatalog");
      const hasAuth = Boolean(getAccessToken());

      // Catalog warms in the BACKGROUND — every page renders skeletons for
      // it, so blocking the whole splash on it just turned a slow network
      // into seconds of black screen. Only ``me`` (cheap, single call) gates
      // the release: the header/profile chrome looks broken without it.
      void qc.prefetchQuery({ ...brandsQueryOptions, staleTime: 60_000 }).catch(() => undefined);
      void qc
        .prefetchQuery({ ...categoriesQueryOptions, staleTime: 60_000 })
        .catch(() => undefined);
      if (hasAuth) {
        await qc
          .fetchQuery({
            queryKey: ["me"],
            queryFn: () => apiGet<unknown>("/api/v1/auth/me"),
            staleTime: 60_000,
          })
          .catch(() => undefined);
      }

      clearTimeout(hardTimer);
      if (attemptRef.current === attempt) await release();
    } catch (exc) {
      clearTimeout(hardTimer);
      if (attemptRef.current !== attempt) return;
      const err = exc instanceof Error ? exc : new Error(String(exc));
      // A thrown error inside Telegram is still retryable — don't strand the user
      // on an error screen when the next attempt would likely succeed.
      if (launchedFromTelegram()) {
        retryOrSurface(err);
        return;
      }
      const msg = exc instanceof ApiError ? exc.detail : err.message;
      setError(msg ? { detail: msg } : { key: "bootstrap.errorNetwork" });
      setPhase("error");
    }
  }, [qc, release]);

  useEffect(() => {
    void run();
  }, [run]);

  return (
    <>
      <AnimatePresence>
        {phase !== "ready" && (
          <Splash
            phase={phase}
            stage={stage}
            error={error}
            onRetry={() => {
              autoRetryRef.current = 0; // a manual retry earns a fresh round of silent retries
              void run();
            }}
          />
        )}
      </AnimatePresence>
      {phase === "ready" && children}
    </>
  );
}

// ─── Splash UI ───────────────────────────────────────────────────────────────

function Splash({
  phase,
  stage,
  error,
  onRetry,
}: {
  phase: Phase;
  stage: MessageKey;
  error: BootError | null;
  onRetry: () => void;
}) {
  const { t } = useT();
  const errorText = error
    ? "detail" in error
      ? error.detail
      : t(error.key)
    : t("bootstrap.errorGeneric");
  return (
    <motion.div
      key="splash"
      initial={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.32 }}
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center"
      style={{
        background:
          "radial-gradient(circle at 50% 35%, hsl(228 32% 14%) 0%, hsl(228 36% 8%) 60%, hsl(228 40% 5%) 100%)",
      }}
    >
      <div className="flex flex-col items-center gap-7 px-8 text-center">
        {/* The wordmark already reads "YuPay", so no separate <h1> here —
            it would just double the brand name on screen. */}
        <SplashWordmark />

        {/* Tagline fades in only after the wordmark's slide settles
            (U pops at 0.1s, letters finish their slide at ≈1.55s). */}
        <motion.p
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.4, duration: 0.4 }}
          className="-mt-1 text-xs font-medium uppercase tracking-[0.08em]"
          style={{ color: "hsl(var(--primary))" }}
        >
          {t("bootstrap.tagline")}
        </motion.p>

        <AnimatePresence mode="wait">
          {phase === "error" ? (
            <motion.div
              key="err"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-3"
            >
              <p className="max-w-[280px] text-sm leading-snug text-white/70">{errorText}</p>
              <button
                onClick={onRetry}
                className="rounded-full px-5 py-2 text-sm font-semibold transition-transform active:scale-95"
                style={{
                  background: "hsl(var(--primary))",
                  color: "hsl(var(--primary-foreground))",
                }}
              >
                {t("common.retry")}
              </button>
            </motion.div>
          ) : (
            <motion.p
              key={`stage-${stage}`}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="text-xs text-white/40"
            >
              {t(stage)}
            </motion.p>
          )}
        </AnimatePresence>
      </div>

      <div
        className="absolute bottom-7 text-[10px] uppercase tracking-[0.08em]"
        style={{ color: "hsl(0 0% 100% / 0.18)" }}
      >
        {t("bootstrap.madeFor")}
      </div>
    </motion.div>
  );
}
