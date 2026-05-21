import { useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Coins,
  ExternalLink,
  FileText,
  Info,
  LifeBuoy,
  LogOut,
  RefreshCcw,
  Shield,
} from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useLogout, useMe } from "@/lib/auth";
import {
  CURRENCY_LABEL,
  CURRENCY_SYMBOL,
  DISPLAY_CURRENCIES,
  type DisplayCurrency,
  useDisplayCurrency,
  useUpdateDisplayCurrency,
} from "@/lib/currency";
import { getWebApp } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";

function initials(name: string | null | undefined): string {
  if (!name) return "👤";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("");
}

const SUPPORT_URL =
  (import.meta.env.VITE_SUPPORT_URL as string | undefined) ??
  "https://t.me/yupay_support";
const APP_VERSION = (import.meta.env.VITE_APP_VERSION as string | undefined) ?? "0.1.0";

// Legal doc URLs — surfaced only when set so we don't ship rows that link
// to drafts or 404s. Operators flip them on by populating the env vars at
// build time (see infra/docker/miniapp.Dockerfile).
const TERMS_URL = import.meta.env.VITE_TERMS_URL as string | undefined;
const PRIVACY_URL = import.meta.env.VITE_PRIVACY_URL as string | undefined;
const REFUND_URL = import.meta.env.VITE_REFUND_URL as string | undefined;
const HAS_LEGAL_DOCS = Boolean(TERMS_URL || PRIVACY_URL || REFUND_URL);

const COMPANY_NAME = import.meta.env.VITE_COMPANY_NAME as string | undefined;
const COMPANY_REGISTRATION = import.meta.env
  .VITE_COMPANY_REGISTRATION as string | undefined;
const COMPANY_SINCE = import.meta.env.VITE_COMPANY_SINCE as string | undefined;
const HAS_COMPANY_INFO = Boolean(
  COMPANY_NAME || COMPANY_REGISTRATION || COMPANY_SINCE,
);

export default function Settings() {
  useDocumentTitle("Настройки");
  const me = useMe();
  const logout = useLogout();
  const user = me.data;

  const currency = useDisplayCurrency();
  const updateCurrency = useUpdateDisplayCurrency();
  const [currencyOpen, setCurrencyOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);

  const openSupport = () => {
    const wa = getWebApp();
    if (wa?.openTelegramLink && SUPPORT_URL.startsWith("https://t.me/")) {
      wa.openTelegramLink(SUPPORT_URL);
    } else if (wa?.openLink) {
      wa.openLink(SUPPORT_URL);
    } else {
      window.open(SUPPORT_URL, "_blank");
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="p-4 space-y-4"
    >
      <h1 className="text-2xl font-bold tracking-tight text-white mb-2">Настройки</h1>

      {!user && !me.isLoading && (
        <div className="rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-4 flex items-start gap-3">
          <AlertTriangle size={18} className="text-yellow-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-yellow-200">Не авторизованы</p>
            <p className="text-yellow-100/70 text-xs mt-1">
              Откройте приложение из Telegram, чтобы войти и видеть свой профиль.
            </p>
          </div>
        </div>
      )}

      {/* Profile card */}
      <div className="bg-card border border-border rounded-3xl p-4 relative overflow-hidden">
        <div className="absolute right-0 top-0 w-40 h-40 bg-primary/8 rounded-full blur-3xl -mr-12 -mt-12 pointer-events-none" />

        <div className="flex items-center gap-4 z-10 relative">
          <Avatar className="w-16 h-16 border-2 border-primary/30 shadow-lg shrink-0">
            {user?.photo_url ? (
              <AvatarImage src={user.photo_url} alt={user.display_name ?? "user"} />
            ) : (
              <AvatarImage
                src={`https://api.dicebear.com/9.x/pixel-art/svg?seed=${
                  user?.id ?? "anon"
                }&backgroundColor=1e2a3a`}
              />
            )}
            <AvatarFallback className="bg-primary/20 text-primary font-bold text-lg">
              {initials(user?.display_name) || "👤"}
            </AvatarFallback>
          </Avatar>

          <div className="flex-1 min-w-0">
            <h2 className="font-bold text-lg text-white leading-tight truncate">
              {user?.display_name ?? "Гость"}
            </h2>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-xs text-muted-foreground">
                {user ? `ID: ${user.id.slice(0, 8)}…` : "Авторизация через Telegram"}
              </span>
            </div>
            {user?.email && (
              <p className="text-[11px] text-muted-foreground/70 mt-0.5 truncate">
                {user.email}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Real settings */}
      <div className="space-y-1.5">
        <p className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.08em] px-1 mb-2">
          Приложение
        </p>

        <div className="bg-card border border-border rounded-3xl overflow-hidden">
          <SettingsRow
            icon={Coins}
            iconClass="text-primary"
            label="Валюта отображения"
            value={`${CURRENCY_SYMBOL[currency]} · ${currency}`}
            onClick={() => setCurrencyOpen(true)}
          />
          <SettingsRow
            icon={LifeBuoy}
            iconClass="text-blue-400"
            label="Поддержка"
            value="Telegram"
            onClick={openSupport}
            chevron={<ExternalLink size={14} className="text-muted-foreground/50" />}
          />
          <SettingsRow
            icon={Info}
            iconClass="text-muted-foreground"
            label="О приложении"
            value={`v${APP_VERSION}`}
            onClick={() => setAboutOpen(true)}
            last
          />
        </div>
      </div>

      {/* Legal docs — hidden when no URL configured so we don't ship
          dead links during the pre-launch period. */}
      {HAS_LEGAL_DOCS && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-bold text-muted-foreground uppercase tracking-[0.08em] px-1 mb-2">
            Документы
          </p>
          <div className="bg-card border border-border rounded-3xl overflow-hidden">
            {TERMS_URL && (
              <SettingsRow
                icon={FileText}
                iconClass="text-blue-400"
                label="Условия использования"
                onClick={() => window.open(TERMS_URL, "_blank", "noopener")}
                chevron={
                  <ExternalLink size={14} className="text-muted-foreground/50" />
                }
                last={!PRIVACY_URL && !REFUND_URL}
              />
            )}
            {PRIVACY_URL && (
              <SettingsRow
                icon={Shield}
                iconClass="text-emerald-400"
                label="Политика конфиденциальности"
                onClick={() => window.open(PRIVACY_URL, "_blank", "noopener")}
                chevron={
                  <ExternalLink size={14} className="text-muted-foreground/50" />
                }
                last={!REFUND_URL}
              />
            )}
            {REFUND_URL && (
              <SettingsRow
                icon={RefreshCcw}
                iconClass="text-amber-400"
                label="Условия возврата"
                onClick={() => window.open(REFUND_URL, "_blank", "noopener")}
                chevron={
                  <ExternalLink size={14} className="text-muted-foreground/50" />
                }
                last
              />
            )}
          </div>
        </div>
      )}

      {/* Logout */}
      {user && (
        <button
          onClick={() => logout.mutate()}
          className="w-full flex items-center justify-center gap-2 py-3.5 text-muted-foreground text-sm font-medium hover:text-destructive transition-colors"
          data-testid="btn-logout"
        >
          <LogOut size={15} />
          Выйти из аккаунта
        </button>
      )}

      {/* Currency sheet */}
      <Sheet open={currencyOpen} onOpenChange={setCurrencyOpen}>
        <SheetContent side="bottom" className="rounded-t-3xl">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Coins size={16} className="text-primary" />
              Валюта отображения
            </SheetTitle>
            <SheetDescription className="text-left text-white/60 leading-relaxed">
              Влияет на цены в каталоге. Балансы и старые заказы остаются в своей
              валюте.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-4 space-y-2">
            {DISPLAY_CURRENCIES.map((c) => (
              <CurrencyOption
                key={c}
                code={c}
                active={currency === c}
                onSelect={() => {
                  if (c !== currency) updateCurrency.mutate(c);
                  setCurrencyOpen(false);
                }}
              />
            ))}
          </div>
        </SheetContent>
      </Sheet>

      {/* About sheet */}
      <Sheet open={aboutOpen} onOpenChange={setAboutOpen}>
        <SheetContent side="bottom" className="rounded-t-3xl">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Info size={16} className="text-primary" aria-hidden="true" />
              О приложении
            </SheetTitle>
          </SheetHeader>
          <div className="mt-4 space-y-3 text-sm">
            <div className="rounded-2xl border border-border p-3 flex items-center justify-between">
              <span className="text-white/60">Версия</span>
              <code className="font-mono text-white">v{APP_VERSION}</code>
            </div>

            {HAS_COMPANY_INFO && (
              <div className="rounded-2xl border border-border p-3 space-y-1.5">
                {COMPANY_NAME && (
                  <p className="text-white font-semibold leading-tight">
                    {COMPANY_NAME}
                  </p>
                )}
                {COMPANY_REGISTRATION && (
                  <p className="text-white/55 text-xs leading-snug font-mono">
                    {COMPANY_REGISTRATION}
                  </p>
                )}
                {COMPANY_SINCE && (
                  <p className="text-white/40 text-[11px] leading-snug">
                    Работаем с {COMPANY_SINCE} года
                  </p>
                )}
              </div>
            )}

            <p className="text-white/60 leading-relaxed">
              YuPay — пополнение игр, ваучеры и подписки. Лицензия —
              проприетарная; код в приватном репо.
            </p>
            <p className="text-white/40 text-xs leading-relaxed">
              По любым вопросам пишите в поддержку — ответим в течение часа.
            </p>
          </div>
        </SheetContent>
      </Sheet>
    </motion.div>
  );
}

function SettingsRow({
  icon: Icon,
  iconClass,
  label,
  value,
  onClick,
  chevron,
  last,
}: {
  icon: typeof Coins;
  iconClass?: string;
  label: string;
  value?: string;
  onClick: () => void;
  chevron?: React.ReactNode;
  last?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center justify-between px-4 py-3.5 hover:bg-white/5 transition-colors ${
        last ? "" : "border-b border-border/40"
      }`}
    >
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-xl bg-background/80 border border-border/60 flex items-center justify-center">
          <Icon size={15} className={iconClass} />
        </div>
        <span className="font-medium text-sm text-foreground">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {value && (
          <span className="text-xs text-muted-foreground font-medium">{value}</span>
        )}
        {chevron ?? (
          <ChevronRight size={16} className="text-muted-foreground/50" />
        )}
      </div>
    </button>
  );
}

function CurrencyOption({
  code,
  active,
  onSelect,
}: {
  code: DisplayCurrency;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className="w-full flex items-center justify-between p-3.5 rounded-2xl transition-all"
      style={{
        background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
        border: active
          ? "1.5px solid hsl(var(--primary) / 0.7)"
          : "1px solid hsl(var(--border))",
      }}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center font-bold text-sm"
          style={{
            background: active ? "hsl(var(--primary) / 0.18)" : "hsl(var(--surface-3))",
            color: active ? "hsl(var(--primary))" : "rgba(255,255,255,0.7)",
          }}
        >
          {CURRENCY_SYMBOL[code]}
        </div>
        <div className="text-left">
          <p className="text-white font-bold text-sm">{code}</p>
          <p className="text-white/40 text-xs">{CURRENCY_LABEL[code]}</p>
        </div>
      </div>
      {active && (
        <div
          className="w-5 h-5 rounded-full flex items-center justify-center"
          style={{ background: "hsl(var(--primary))" }}
        >
          <Check size={11} strokeWidth={3} className="text-black" />
        </div>
      )}
    </button>
  );
}
