import { ReactNode } from "react";
import { Header } from "./Header";
import { BottomNav } from "./BottomNav";

export function Shell({ children }: { children: ReactNode }) {
  // Header used to hide on /topup/* to give the game hero an
  // immersive top edge — but operators kept losing access to the
  // balance pill and the brand mark in the middle of checkout.
  // Universal header is the safer default; the hero just sits below
  // a 64px bar like every other page.
  return (
    <div className="min-h-screen bg-background text-foreground flex justify-center w-full">
      <div className="w-full max-w-[430px] min-h-screen relative shadow-2xl flex flex-col bg-background overflow-hidden border-x border-border/50">
        <Header />
        <main className="flex-1 overflow-y-auto scroll-smooth pt-16 pb-[108px]">
          {children}
        </main>
        <BottomNav />
      </div>
    </div>
  );
}
