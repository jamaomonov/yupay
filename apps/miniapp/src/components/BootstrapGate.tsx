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

import { ApiError, apiGet, getAccessToken } from "@/lib/api";
import { bootstrapAuth } from "@/lib/auth";
import { brandsQueryOptions, categoriesQueryOptions } from "@/lib/catalog";

type Phase = "booting" | "ready" | "error";

interface PrefetchSpec {
  key: readonly unknown[];
  /** Returns the query result; failures are swallowed individually. The
   *  returned value MUST match the shape the corresponding ``useQuery``
   *  hook expects — otherwise the cache will short-circuit the hook with
   *  the wrong type. */
  fetch: () => Promise<unknown>;
  /** When false, skip this prefetch (e.g. needs auth and we're anonymous). */
  required?: boolean;
}

/** Minimum splash duration in ms. Prevents flashes on instant loads. */
const MIN_SPLASH_MS = 650;

/** Hard cap on the whole bootstrap. We always release after this. */
const HARD_BOOT_TIMEOUT_MS = 8_000;

export function BootstrapGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [phase, setPhase] = useState<Phase>("booting");
  const [stage, setStage] = useState<string>("Подключаемся…");
  const [error, setError] = useState<string | null>(null);
  const startedAt = useRef<number>(Date.now());
  const attemptRef = useRef<number>(0);

  const release = useCallback(async () => {
    const elapsed = Date.now() - startedAt.current;
    const wait = Math.max(0, MIN_SPLASH_MS - elapsed);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    setPhase("ready");
  }, []);

  const run = useCallback(async () => {
    const attempt = ++attemptRef.current;
    setPhase("booting");
    setError(null);
    setStage("Подключаемся к Telegram…");
    startedAt.current = Date.now();

    // Hard timeout — release even if something is stuck so the user always
    // gets to *some* UI instead of an infinite splash.
    const hardTimer = setTimeout(() => {
      if (attemptRef.current === attempt) void release();
    }, HARD_BOOT_TIMEOUT_MS);

    try {
      const auth = await bootstrapAuth({ timeoutMs: 2_000 });
      if (attemptRef.current !== attempt) return; // newer run in flight

      if (auth.status === "failed") {
        clearTimeout(hardTimer);
        const detail = auth.error instanceof ApiError ? auth.error.detail : auth.error?.message;
        setError(detail ?? "Не удалось подтвердить Telegram-сессию.");
        setPhase("error");
        return;
      }

      setStage("Загружаем каталог…");
      const hasAuth = Boolean(getAccessToken());

      const specs: PrefetchSpec[] = [
        {
          key: brandsQueryOptions.queryKey,
          fetch: brandsQueryOptions.queryFn,
          required: true,
        },
        {
          key: categoriesQueryOptions.queryKey,
          fetch: categoriesQueryOptions.queryFn,
          required: true,
        },
        {
          key: ["me"],
          fetch: () => apiGet<unknown>("/api/v1/auth/me"),
          required: hasAuth,
        },
      ];

      // Run all prefetches in parallel; one failure should not block the others.
      await Promise.all(
        specs
          .filter((s) => s.required !== false)
          .map((s) =>
            qc
              .fetchQuery({ queryKey: s.key, queryFn: s.fetch, staleTime: 60_000 })
              .catch(() => undefined),
          ),
      );

      clearTimeout(hardTimer);
      if (attemptRef.current === attempt) await release();
    } catch (exc) {
      clearTimeout(hardTimer);
      if (attemptRef.current !== attempt) return;
      const msg = exc instanceof ApiError ? exc.detail : exc instanceof Error ? exc.message : "";
      setError(msg || "Сетевая ошибка. Проверьте подключение.");
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
          <Splash phase={phase} stage={stage} error={error} onRetry={() => void run()} />
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
  stage: string;
  error: string | null;
  onRetry: () => void;
}) {
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
      <div className="flex flex-col items-center gap-6 px-8 text-center">
        <Logo spinning={phase === "booting"} />

        <div className="space-y-1.5">
          <h1 className="text-2xl font-bold tracking-tight text-white">YuPay</h1>
          <p
            className="text-xs font-medium uppercase tracking-[0.08em]"
            style={{ color: "hsl(var(--primary))" }}
          >
            пополнение игр и сервисов
          </p>
        </div>

        <AnimatePresence mode="wait">
          {phase === "error" ? (
            <motion.div
              key="err"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-3"
            >
              <p className="max-w-[280px] text-sm leading-snug text-white/70">
                {error ?? "Не удалось загрузить приложение."}
              </p>
              <button
                onClick={onRetry}
                className="rounded-full px-5 py-2 text-sm font-semibold transition-transform active:scale-95"
                style={{
                  background: "hsl(var(--primary))",
                  color: "hsl(var(--primary-foreground))",
                }}
              >
                Повторить
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
              {stage}
            </motion.p>
          )}
        </AnimatePresence>
      </div>

      <div
        className="absolute bottom-7 text-[10px] uppercase tracking-[0.08em]"
        style={{ color: "hsl(0 0% 100% / 0.18)" }}
      >
        v0.1 · made for telegram
      </div>
    </motion.div>
  );
}

function Logo({ spinning }: { spinning: boolean }) {
  return (
    <div className="relative flex h-28 w-28 items-center justify-center">
      {/* Soft halo */}
      <div
        className="absolute inset-0 rounded-full opacity-60 blur-2xl"
        style={{
          background: "radial-gradient(circle, hsl(var(--primary) / 0.55) 0%, transparent 70%)",
        }}
      />
      {/* Rotating ring */}
      <motion.div
        className="absolute inset-0 rounded-full"
        animate={spinning ? { rotate: 360 } : { rotate: 0 }}
        transition={
          spinning ? { repeat: Infinity, duration: 1.6, ease: "linear" } : { duration: 0.3 }
        }
        style={{
          background: `conic-gradient(from 0deg, transparent 0deg, hsl(var(--primary)) 80deg, transparent 240deg)`,
          mask: "radial-gradient(circle, transparent 56%, #000 58%, #000 100%)",
          WebkitMask: "radial-gradient(circle, transparent 56%, #000 58%, #000 100%)",
          opacity: 0.9,
        }}
      />
      {/* Core mark — the real brand logo. The dark square came from the
          PNG variant we generated for apple-touch-icon, but here the
          flat SVG sits on its own dark splash background so we render
          the icon-mark SVG directly without the boxed wrapper. */}
      <img
        src="/logo-icon.svg"
        alt="YuPay"
        className="relative z-10 h-16 w-16 drop-shadow-[0_8px_32px_hsl(var(--primary)/0.5)]"
        draggable={false}
      />
    </div>
  );
}
