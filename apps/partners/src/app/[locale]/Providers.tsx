"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

/**
 * One query client per browser session.
 *
 * Created in state rather than at module scope: at module scope it would be
 * shared across requests during SSR, and one visitor's cached panel data would
 * be served to the next.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Panel figures are money. A stale balance shown as current is
            // worse than a brief spinner.
            staleTime: 15_000,
            retry: 1,
            refetchOnWindowFocus: true,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
