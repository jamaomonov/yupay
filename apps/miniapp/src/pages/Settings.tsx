import { motion } from "framer-motion";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Bell, Globe, Shield, HelpCircle, Info, ChevronRight, LogOut, Plus } from "lucide-react";

export default function Settings() {
  const MENU_ITEMS = [
    { icon: Bell, label: "Уведомления", color: "text-blue-400" },
    { icon: Globe, label: "Язык (Русский)", color: "text-violet-400" },
    { icon: Shield, label: "Безопасность", color: "text-green-400" },
    { icon: HelpCircle, label: "Поддержка", color: "text-yellow-400" },
    { icon: Info, label: "О приложении", color: "text-muted-foreground" },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="p-4 space-y-4"
    >
      <h1 className="text-2xl font-bold tracking-tight text-white mb-2">Настройки</h1>

      {/* Profile card */}
      <div className="bg-card border border-border rounded-3xl p-4 relative overflow-hidden">
        <div className="absolute right-0 top-0 w-40 h-40 bg-primary/8 rounded-full blur-3xl -mr-12 -mt-12 pointer-events-none" />

        <div className="flex items-center gap-4 z-10 relative">
          <Avatar className="w-16 h-16 border-2 border-primary/30 shadow-lg shrink-0">
            <AvatarImage src="https://api.dicebear.com/9.x/pixel-art/svg?seed=pixelpay777&backgroundColor=1e2a3a" />
            <AvatarFallback className="bg-primary/20 text-primary font-black text-lg">ИГ</AvatarFallback>
          </Avatar>

          <div className="flex-1 min-w-0">
            <h2 className="font-black text-lg text-white leading-tight">Игрок_777</h2>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-xs text-muted-foreground">Баланс:</span>
              <span className="text-sm font-black text-primary">3 250 ₽</span>
            </div>
          </div>
        </div>

        {/* Top-up balance button */}
        <button
          className="mt-4 w-full flex items-center justify-center gap-2 h-11 rounded-2xl bg-primary text-black font-bold text-sm hover:bg-primary/90 active:scale-[0.98] transition-all"
          data-testid="btn-topup-balance"
        >
          <Plus size={16} />
          Пополнить баланс
        </button>
      </div>

      {/* Settings list */}
      <div className="space-y-1.5">
        <p className="text-[11px] font-bold text-muted-foreground uppercase tracking-widest px-1 mb-2">
          Приложение
        </p>

        <div className="bg-card border border-border rounded-3xl overflow-hidden">
          {MENU_ITEMS.map((item, index) => (
            <button
              key={index}
              className="w-full flex items-center justify-between px-4 py-3.5 hover:bg-white/5 transition-colors border-b border-border/40 last:border-0"
              data-testid={`settings-menu-${index}`}
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-xl bg-background/80 border border-border/60 flex items-center justify-center">
                  <item.icon size={15} className={item.color} />
                </div>
                <span className="font-medium text-sm text-foreground">{item.label}</span>
              </div>
              <ChevronRight size={16} className="text-muted-foreground/50" />
            </button>
          ))}
        </div>
      </div>

      {/* Logout — subtle, not alarming */}
      <button
        className="w-full flex items-center justify-center gap-2 py-3.5 text-muted-foreground text-sm font-medium hover:text-destructive transition-colors"
        data-testid="btn-logout"
      >
        <LogOut size={15} />
        Выйти из аккаунта
      </button>
    </motion.div>
  );
}
