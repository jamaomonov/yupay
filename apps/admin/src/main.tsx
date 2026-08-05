import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import "./styles.css";
import { router } from "./app/router";
import { useAuthStore } from "./features/auth/authStore";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/** Gate the router on the boot-time refresh-cookie re-hydration so a logged-in
 *  admin isn't bounced to /login before the in-memory token is restored. */
function AppBoot() {
  const bootstrapped = useAuthStore((s) => s.bootstrapped);
  const bootstrap = useAuthStore((s) => s.bootstrap);
  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);
  if (!bootstrapped) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[var(--text-secondary)]">
        Загрузка…
      </div>
    );
  }
  return <RouterProvider router={router} />;
}

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppBoot />
    </QueryClientProvider>
  </StrictMode>,
);
