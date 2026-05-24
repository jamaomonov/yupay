import { type ReactNode } from "react";

import { BottomNav } from "./BottomNav";
import { Header } from "./Header";

export function Shell({ children }: { children: ReactNode }) {
  // Header used to hide on /topup/* to give the game hero an
  // immersive top edge — but operators kept losing access to the
  // balance pill and the brand mark in the middle of checkout.
  // Universal header is the safer default; the hero just sits below
  // a 64px bar like every other page.
  return (
    <div className="bg-background text-foreground flex min-h-screen w-full justify-center">
      <div className="bg-background border-border/50 relative flex min-h-screen w-full max-w-[430px] flex-col overflow-hidden border-x shadow-2xl">
        <Header />
        <main className="flex-1 overflow-y-auto scroll-smooth pb-[108px] pt-16">{children}</main>
        <BottomNav />
      </div>
    </div>
  );
}
