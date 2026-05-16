import { ReactNode } from "react";
import { useLocation } from "wouter";
import { Header } from "./Header";
import { BottomNav } from "./BottomNav";

export function Shell({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const isTopUp = location.startsWith("/topup/");

  return (
    <div className="min-h-screen bg-background text-foreground flex justify-center w-full">
      <div className="w-full max-w-[430px] min-h-screen relative shadow-2xl flex flex-col bg-background overflow-hidden border-x border-border/50">
        {!isTopUp && <Header />}
        <main
          className={`flex-1 overflow-y-auto scroll-smooth ${
            isTopUp ? "pt-0 pb-[140px]" : "pt-16 pb-[108px]"
          }`}
        >
          {children}
        </main>
        <BottomNav />
      </div>
    </div>
  );
}
