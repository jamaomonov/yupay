import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { MotionConfig } from "framer-motion";
import { lazy, Suspense, useEffect } from "react";
import { Switch, Route, Router as WouterRouter, useLocation } from "wouter";

import { BootstrapGate } from "@/components/BootstrapGate";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Shell } from "@/components/layout/Shell";
import { OrderDeliveredDialog } from "@/components/OrderDeliveredDialog";
import { CatchUpReviewDialog } from "@/components/review/CatchUpReviewDialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useOrderSocket } from "@/hooks/useOrderSocket";
import { I18nProvider, useT } from "@/lib/i18n";
import { parseReviewLaunchParam } from "@/lib/review-ask";
import { getWebApp, showSettingsButton, watchTelegramActivity } from "@/lib/telegram";
import { useTelegramBackButton } from "@/lib/use-telegram-back-button";
import CS2SkinMarket from "@/pages/CS2SkinMarket";
import History from "@/pages/History";
import Home from "@/pages/Home";
import OrderSuccess from "@/pages/OrderSuccess";
import Settings from "@/pages/Settings";
import TopUp from "@/pages/TopUp";
import Wallet from "@/pages/Wallet";
import WalletTopUp from "@/pages/WalletTopUp";

// The Steam Gifts screens are the first code-split routes in the app — the
// miniapp is already over its 120KB bundle budget (see AGENTS.md §10), and
// this catalog/game pair (plus its own sheets) is sizeable enough that
// deferring it until someone actually opens `/gifts` is worth the extra
// `Suspense` boundary.
const GiftsCatalog = lazy(() => import("@/pages/GiftsCatalog"));
const GiftGame = lazy(() => import("@/pages/GiftGame"));

function NotFound() {
  const { t } = useT();
  return <div className="mt-20 p-4 text-center">{t("app.notFound")}</div>;
}

/** Suspense fallback for the lazy gifts routes — a generic grid skeleton,
 *  close enough to both `GiftsCatalog` and `GiftGame`'s loaded shape that it
 *  doesn't read as a layout jump once the chunk resolves. */
function GiftsRouteSkeleton() {
  return (
    <div className="space-y-4 px-4 pt-4">
      <Skeleton className="h-6 w-40" />
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="aspect-[3/4] rounded-2xl" />
        ))}
      </div>
    </div>
  );
}

const queryClient = new QueryClient();

/**
 * Mounts the order-updates WebSocket (no-op while signed out) and the global
 * "order delivered → rate" dialog it opens. A separate component (rather than
 * inlining both calls in `App`) keeps `useOrderSocket`'s `useMe()` /
 * `useQueryClient()` reads scoped to something that re-renders on its own,
 * not on every `App` render.
 */
function RealtimeUpdates() {
  useOrderSocket();
  return <OrderDeliveredDialog />;
}

/**
 * Telegram "Оценить заказ" opens the Mini App with ``?review=<orderId>`` (or
 * a ``start_param``). Land on that order so the inline RateAsk is waiting.
 */
function ReviewLaunchGate() {
  const [, navigate] = useLocation();
  useEffect(() => {
    const id = parseReviewLaunchParam(
      window.location.search,
      getWebApp()?.initDataUnsafe.start_param,
    );
    if (id) navigate(`/order/${id}`);
  }, [navigate]);
  return null;
}

/**
 * Native Settings entry (client ⋮ menu) → our settings route, and background
 * work paused while the app is minimised.
 *
 * Polling is gated on `isAppActive()` inside the queries themselves; all this
 * has to do is refetch the moment the customer comes back, so a payment that
 * completed while minimised is on screen immediately instead of one tick later.
 */
function useTelegramIntegration() {
  const [, navigate] = useLocation();
  const qc = useQueryClient();
  useEffect(() => {
    const hideSettings = showSettingsButton(() => {
      navigate("/settings");
    });
    const unwatch = watchTelegramActivity((active) => {
      if (active) void qc.invalidateQueries();
    });
    return () => {
      hideSettings();
      unwatch();
    };
  }, [navigate, qc]);
}

function Router() {
  // Sync Telegram's native BackButton with the route — shown on every
  // non-root page, taps the browser history (or falls back to Home).
  useTelegramBackButton();
  useTelegramIntegration();
  return (
    <Shell>
      <ReviewLaunchGate />
      <CatchUpReviewDialog />
      <Switch>
        <Route path="/" component={Home} />
        <Route path="/cs2-market" component={CS2SkinMarket} />
        <Route path="/topup/:gameId" component={TopUp} />
        <Route path="/gifts">
          <Suspense fallback={<GiftsRouteSkeleton />}>
            <GiftsCatalog />
          </Suspense>
        </Route>
        <Route path="/gifts/:appId">
          <Suspense fallback={<GiftsRouteSkeleton />}>
            <GiftGame />
          </Suspense>
        </Route>
        <Route path="/order/:id" component={OrderSuccess} />
        <Route path="/wallet" component={Wallet} />
        <Route path="/wallet/topup" component={WalletTopUp} />
        <Route path="/history" component={History} />
        <Route path="/settings" component={Settings} />
        <Route component={NotFound} />
      </Switch>
    </Shell>
  );
}

function App() {
  useEffect(() => {
    document.documentElement.classList.add("dark");
  }, []);

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        {/* I18nProvider wraps everything below QueryClientProvider so the
            bootstrap splash and all pages can translate. It derives the
            active locale from ``me.locale`` (TanStack Query). */}
        <I18nProvider>
          {/* reducedMotion="user" makes framer-motion honour the OS preference
              (WCAG 2.3.3). Combined with the @media query in index.css that
              handles raw CSS transitions, every motion in the app collapses
              when the user has motion sensitivity enabled. */}
          <MotionConfig reducedMotion="user">
            <TooltipProvider>
              <BootstrapGate>
                <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
                  <Router />
                </WouterRouter>
              </BootstrapGate>
              <RealtimeUpdates />
              <Toaster />
            </TooltipProvider>
          </MotionConfig>
        </I18nProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
