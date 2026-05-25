import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  Info,
  LifeBuoy,
  LogOut,
  RefreshCcw,
  Shield,
} from "lucide-react";
import { useState } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useToast } from "@/hooks/use-toast";
import { useLogout, useMe } from "@/lib/auth";
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
  (import.meta.env.VITE_SUPPORT_URL as string | undefined) ?? "https://t.me/yupay_support";
const APP_VERSION = (import.meta.env.VITE_APP_VERSION as string | undefined) ?? "0.1.0";

// Legal doc URLs — surfaced only when set so we don't ship rows that link
// to drafts or 404s. Operators flip them on by populating the env vars at
// build time (see infra/docker/miniapp.Dockerfile).
const TERMS_URL = import.meta.env.VITE_TERMS_URL as string | undefined;
const PRIVACY_URL = import.meta.env.VITE_PRIVACY_URL as string | undefined;
const REFUND_URL = import.meta.env.VITE_REFUND_URL as string | undefined;
const HAS_LEGAL_DOCS = Boolean(TERMS_URL || PRIVACY_URL || REFUND_URL);

const COMPANY_NAME = import.meta.env.VITE_COMPANY_NAME as string | undefined;
const COMPANY_REGISTRATION = import.meta.env.VITE_COMPANY_REGISTRATION as string | undefined;
const COMPANY_SINCE = import.meta.env.VITE_COMPANY_SINCE as string | undefined;
const HAS_COMPANY_INFO = Boolean(COMPANY_NAME || COMPANY_REGISTRATION || COMPANY_SINCE);

export default function Settings() {
  useDocumentTitle("Настройки");
  const me = useMe();
  const logout = useLogout();
  const user = me.data;
  const { toast } = useToast();

  const [aboutOpen, setAboutOpen] = useState(false);
  const [tgIdCopied, setTgIdCopied] = useState(false);

  // The Telegram user id is what every operator / support agent will
  // ask for — internal UUID is meaningless to them. Read it from the
  // SDK's ``initDataUnsafe`` (server already verified the signed
  // ``initData`` at login, so for *display* this is fine).
  const tgId = getWebApp()?.initDataUnsafe.user?.id ?? null;

  const copyTgId = async () => {
    if (tgId == null) return;
    try {
      await navigator.clipboard.writeText(tgId.toString());
      getWebApp()?.HapticFeedback?.notificationOccurred("success");
      setTgIdCopied(true);
      window.setTimeout(() => {
        setTgIdCopied(false);
      }, 1500);
    } catch {
      toast({ title: "Не удалось скопировать", variant: "destructive" });
    }
  };

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
      className="space-y-4 p-4"
    >
      <h1 className="mb-2 text-2xl font-bold tracking-tight text-white">Настройки</h1>

      {!user && !me.isLoading && (
        <div className="flex items-start gap-3 rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-4">
          <AlertTriangle size={18} className="mt-0.5 flex-shrink-0 text-yellow-400" />
          <div className="text-sm">
            <p className="font-semibold text-yellow-200">Не авторизованы</p>
            <p className="mt-1 text-xs text-yellow-100/70">
              Откройте приложение из Telegram, чтобы войти и видеть свой профиль.
            </p>
          </div>
        </div>
      )}

      {/* Profile card */}
      <div className="bg-card border-border relative overflow-hidden rounded-3xl border p-4">
        <div className="bg-primary/8 pointer-events-none absolute right-0 top-0 -mr-12 -mt-12 h-40 w-40 rounded-full blur-3xl" />

        <div className="relative z-10 flex items-center gap-4">
          <Avatar className="border-primary/30 h-16 w-16 shrink-0 border-2 shadow-lg">
            {user?.photo_url ? (
              <AvatarImage src={user.photo_url} alt={user.display_name ?? "user"} />
            ) : (
              <AvatarImage
                src={`https://api.dicebear.com/9.x/pixel-art/svg?seed=${
                  user?.id ?? "anon"
                }&backgroundColor=1e2a3a`}
              />
            )}
            <AvatarFallback className="bg-primary/20 text-primary text-lg font-bold">
              {initials(user?.display_name) || "👤"}
            </AvatarFallback>
          </Avatar>

          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-bold leading-tight text-white">
              {user?.display_name ?? "Гость"}
            </h2>
            <div className="mt-1 flex items-center gap-1.5">
              {user && tgId != null ? (
                <button
                  type="button"
                  onClick={copyTgId}
                  className="border-border/60 bg-background/40 hover:bg-background/70 flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs transition-colors"
                  aria-label="Скопировать Telegram ID"
                  data-testid="copy-tg-id"
                >
                  <span className="text-muted-foreground">ID:</span>
                  <span className="font-mono text-white">{tgId.toString()}</span>
                  {tgIdCopied ? (
                    <Check size={12} className="text-primary" />
                  ) : (
                    <Copy size={12} className="text-muted-foreground/70" />
                  )}
                </button>
              ) : (
                <span className="text-muted-foreground text-xs">
                  {user ? `ID: ${user.id.slice(0, 8)}…` : "Авторизация через Telegram"}
                </span>
              )}
            </div>
            {user?.email && (
              <p className="text-muted-foreground/70 mt-0.5 truncate text-[11px]">{user.email}</p>
            )}
          </div>
        </div>
      </div>

      {/* Real settings */}
      <div className="space-y-1.5">
        <p className="text-muted-foreground mb-2 px-1 text-[11px] font-bold uppercase tracking-[0.08em]">
          Приложение
        </p>

        <div className="bg-card border-border overflow-hidden rounded-3xl border">
          {/* Currency picker hidden while the storefront ships UZ-only.
              Each region will get its own native currency (UZ→UZS,
              RU→RUB, EN→USD) on its own catalog. When we re-open the
              picker, it'll be limited to currencies relevant to the
              user's market, not a free-form preference. */}
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
            onClick={() => {
              setAboutOpen(true);
            }}
            last
          />
        </div>
      </div>

      {/* Legal docs — hidden when no URL configured so we don't ship
          dead links during the pre-launch period. */}
      {HAS_LEGAL_DOCS && (
        <div className="space-y-1.5">
          <p className="text-muted-foreground mb-2 px-1 text-[11px] font-bold uppercase tracking-[0.08em]">
            Документы
          </p>
          <div className="bg-card border-border overflow-hidden rounded-3xl border">
            {TERMS_URL && (
              <SettingsRow
                icon={FileText}
                iconClass="text-blue-400"
                label="Условия использования"
                onClick={() => window.open(TERMS_URL, "_blank", "noopener")}
                chevron={<ExternalLink size={14} className="text-muted-foreground/50" />}
                last={!PRIVACY_URL && !REFUND_URL}
              />
            )}
            {PRIVACY_URL && (
              <SettingsRow
                icon={Shield}
                iconClass="text-emerald-400"
                label="Политика конфиденциальности"
                onClick={() => window.open(PRIVACY_URL, "_blank", "noopener")}
                chevron={<ExternalLink size={14} className="text-muted-foreground/50" />}
                last={!REFUND_URL}
              />
            )}
            {REFUND_URL && (
              <SettingsRow
                icon={RefreshCcw}
                iconClass="text-amber-400"
                label="Условия возврата"
                onClick={() => window.open(REFUND_URL, "_blank", "noopener")}
                chevron={<ExternalLink size={14} className="text-muted-foreground/50" />}
                last
              />
            )}
          </div>
        </div>
      )}

      {/* Logout */}
      {user && (
        <button
          onClick={() => {
            logout.mutate();
          }}
          className="text-muted-foreground hover:text-destructive flex w-full items-center justify-center gap-2 py-3.5 text-sm font-medium transition-colors"
          data-testid="btn-logout"
        >
          <LogOut size={15} />
          Выйти из аккаунта
        </button>
      )}

      {/* About sheet */}
      <Sheet open={aboutOpen} onOpenChange={setAboutOpen}>
        <SheetContent side="bottom" className="rounded-t-3xl">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Info size={16} className="text-primary" aria-hidden="true" />О приложении
            </SheetTitle>
          </SheetHeader>
          <div className="mt-4 space-y-3 text-sm">
            <div className="border-border flex items-center justify-between rounded-2xl border p-3">
              <span className="text-white/60">Версия</span>
              <code className="font-mono text-white">v{APP_VERSION}</code>
            </div>

            {HAS_COMPANY_INFO && (
              <div className="border-border space-y-1.5 rounded-2xl border p-3">
                {COMPANY_NAME && (
                  <p className="font-semibold leading-tight text-white">{COMPANY_NAME}</p>
                )}
                {COMPANY_REGISTRATION && (
                  <p className="font-mono text-xs leading-snug text-white/55">
                    {COMPANY_REGISTRATION}
                  </p>
                )}
                {COMPANY_SINCE && (
                  <p className="text-[11px] leading-snug text-white/40">
                    Работаем с {COMPANY_SINCE} года
                  </p>
                )}
              </div>
            )}

            <p className="leading-relaxed text-white/60">
              YuPay — пополнение игр, ваучеры и подписки. Лицензия — проприетарная; код в приватном
              репо.
            </p>
            <p className="text-xs leading-relaxed text-white/40">
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
  icon: typeof Info;
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
      className={`flex w-full items-center justify-between px-4 py-3.5 transition-colors hover:bg-white/5 ${
        last ? "" : "border-border/40 border-b"
      }`}
    >
      <div className="flex items-center gap-3">
        <div className="bg-background/80 border-border/60 flex h-8 w-8 items-center justify-center rounded-xl border">
          <Icon size={15} className={iconClass} />
        </div>
        <span className="text-foreground text-sm font-medium">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {value && <span className="text-muted-foreground text-xs font-medium">{value}</span>}
        {chevron ?? <ChevronRight size={16} className="text-muted-foreground/50" />}
      </div>
    </button>
  );
}
