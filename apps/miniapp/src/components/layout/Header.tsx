import { Link, useLocation } from "wouter";
import { Gamepad2 } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

export function Header() {
  return (
    <header className="fixed top-0 left-0 right-0 h-16 bg-background/80 backdrop-blur-xl border-b border-border z-50 flex items-center justify-between px-4 max-w-[430px] mx-auto">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-primary">
          <Gamepad2 size={20} />
        </div>
        <span className="font-black tracking-wider text-lg">PIXELPAY</span>
      </div>
      <div className="flex items-center gap-3 bg-card px-3 py-1.5 rounded-full border border-border">
        <span className="text-primary font-bold text-sm tracking-wide">₽ 3 250</span>
        <Avatar className="w-6 h-6 border border-border">
          <AvatarImage src="https://api.dicebear.com/9.x/avataaars/svg?seed=Felix" />
          <AvatarFallback>JD</AvatarFallback>
        </Avatar>
      </div>
    </header>
  );
}
