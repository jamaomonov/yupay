"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { LocaleAlternatesProvider } from "@/components/LocaleAlternates";
import { Toaster } from "@/components/ui/Toaster";
import { RealtimeProvider } from "@/hooks/useOrderSocket";
import { AuthProvider } from "@/lib/auth";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <RealtimeProvider>
          <LocaleAlternatesProvider>{children}</LocaleAlternatesProvider>
        </RealtimeProvider>
        {/* One viewport for every toast on the storefront (see store/useToast). */}
        <Toaster />
      </AuthProvider>
    </QueryClientProvider>
  );
}
