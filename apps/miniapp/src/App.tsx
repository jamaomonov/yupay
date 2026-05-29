import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "framer-motion";
import { useEffect } from "react";
import { Switch, Route, Router as WouterRouter } from "wouter";

import { BootstrapGate } from "@/components/BootstrapGate";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Shell } from "@/components/layout/Shell";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { I18nProvider, useT } from "@/lib/i18n";
import { useTelegramBackButton } from "@/lib/use-telegram-back-button";
import History from "@/pages/History";
import Home from "@/pages/Home";
import OrderSuccess from "@/pages/OrderSuccess";
import Settings from "@/pages/Settings";
import TopUp from "@/pages/TopUp";
import Wallet from "@/pages/Wallet";
import WalletTopUp from "@/pages/WalletTopUp";

function NotFound() {
  const { t } = useT();
  return <div className="mt-20 p-4 text-center">{t("app.notFound")}</div>;
}

const queryClient = new QueryClient();

function Router() {
  // Sync Telegram's native BackButton with the route — shown on every
  // non-root page, taps the browser history (or falls back to Home).
  useTelegramBackButton();
  return (
    <Shell>
      <Switch>
        <Route path="/" component={Home} />
        <Route path="/topup/:gameId" component={TopUp} />
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
              <Toaster />
            </TooltipProvider>
          </MotionConfig>
        </I18nProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
