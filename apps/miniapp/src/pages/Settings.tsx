import { LOCALES, type Locale } from "@yupay/i18n";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  Info,
  Languages,
  LifeBuoy,
} from "lucide-react";
import { useState } from "react";

import enFlag from "@/assets/flags/en.png";
import ruFlag from "@/assets/flags/ru.png";
import uzFlag from "@/assets/flags/uz.png";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useToast } from "@/hooks/use-toast";
import { useMe } from "@/lib/auth";
import { useLocale, useT } from "@/lib/i18n";
import { useUpdateLocale } from "@/lib/i18n/use-update-locale";
import { legalUrl } from "@/lib/legal";
import { getWebApp, openExternalLink } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";

// Language autonyms — shown in their own language regardless of UI locale,
// which is the conventional way to present a language picker.
const LANGUAGE_NAMES: Record<Locale, string> = {
  ru: "Русский",
  en: "English",
  uz: "O'zbekcha",
};

// Circular flag icons (en → Union Jack). Decorative: the autonym beside each
// one carries the meaning, so the <img> is aria-hidden with empty alt.
const LANGUAGE_FLAGS: Record<Locale, string> = {
  ru: ruFlag,
  en: enFlag,
  uz: uzFlag,
};

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

/**
 * Legal documents, in the order a customer looks for them: the agreement that
 * governs use of the service, the privacy policy, then everything else — the
 * offer, refund terms and seller details — behind the index.
 *
 * These used to be three env-gated rows in a card, and the env vars were never
 * set in production, so the section shipped invisible for the whole of the
 * app's life. Naming the documents in code removes the way that fails, and the
 * index means adding a sixth document doesn't need a Mini App release.
 */
const LEGAL_LINKS = [
  { doc: "agreement", key: "settings.agreement" },
  { doc: "privacy", key: "settings.privacy" },
  { doc: undefined, key: "settings.allDocs" },
] as const;

const COMPANY_NAME = import.meta.env.VITE_COMPANY_NAME as string | undefined;
const COMPANY_REGISTRATION = import.meta.env.VITE_COMPANY_REGISTRATION as string | undefined;
const COMPANY_SINCE = import.meta.env.VITE_COMPANY_SINCE as string | undefined;
const HAS_COMPANY_INFO = Boolean(COMPANY_NAME || COMPANY_REGISTRATION || COMPANY_SINCE);

export default function Settings() {
  const { t } = useT();
  const locale = useLocale();
  const updateLocale = useUpdateLocale();
  useDocumentTitle(t("settings.title"));
  const me = useMe();
  const user = me.data;
  const { toast } = useToast();

  const [aboutOpen, setAboutOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
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
      toast({ title: t("common.copyFailed"), variant: "destructive" });
    }
  };

  const pickLanguage = (next: Locale) => {
    setLangOpen(false);
    if (next !== locale) updateLocale.mutate(next);
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
      <h1 className="mb-2 text-2xl font-bold tracking-tight text-white">{t("settings.title")}</h1>

      {!user && !me.isLoading && (
        <div className="flex items-start gap-3 rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-4">
          <AlertTriangle size={18} className="mt-0.5 flex-shrink-0 text-yellow-400" />
          <div className="text-sm">
            <p className="font-semibold text-yellow-200">{t("settings.notAuthorized")}</p>
            <p className="mt-1 text-xs text-yellow-100/70">{t("settings.notAuthorizedBody")}</p>
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
              {user?.display_name ?? t("common.guest")}
            </h2>
            <div className="mt-1 flex items-center gap-1.5">
              {user && tgId != null ? (
                <button
                  type="button"
                  onClick={copyTgId}
                  className="border-border/60 bg-background/40 hover:bg-background/70 flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs transition-colors"
                  aria-label={t("settings.copyTgId")}
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
                  {user ? `ID: ${user.id.slice(0, 8)}…` : t("settings.authViaTelegram")}
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
          {t("settings.sectionApp")}
        </p>

        <div className="bg-card border-border overflow-hidden rounded-3xl border">
          {/* Currency picker hidden while the storefront ships UZ-only.
              Each region will get its own native currency (UZ→UZS,
              RU→RUB, EN→USD) on its own catalog. When we re-open the
              picker, it'll be limited to currencies relevant to the
              user's market, not a free-form preference. */}
          <SettingsRow
            icon={Languages}
            iconClass="text-violet-400"
            label={t("settings.language")}
            value={LANGUAGE_NAMES[locale]}
            valueIcon={
              <img
                src={LANGUAGE_FLAGS[locale]}
                alt=""
                aria-hidden="true"
                className="h-5 w-5 rounded-full object-cover"
              />
            }
            onClick={() => {
              setLangOpen(true);
            }}
          />
          <SettingsRow
            icon={LifeBuoy}
            iconClass="text-blue-400"
            label={t("settings.support")}
            value={t("settings.supportValue")}
            onClick={openSupport}
            chevron={<ExternalLink size={14} className="text-muted-foreground/50" />}
          />
          <SettingsRow
            icon={Info}
            iconClass="text-muted-foreground"
            label={t("settings.about")}
            value={`v${APP_VERSION}`}
            onClick={() => {
              setAboutOpen(true);
            }}
            last
          />
        </div>
      </div>

      {/* No sign-out. The session is not something the customer holds — it is
          derived from the `initData` Telegram signs on every launch, so
          clearing it just re-authenticates the same account on the next open.
          The button offered an exit that led straight back in. */}

      {/* Quiet links at the foot of the page rather than a settings card.
          Nobody opens this screen looking for the offer — they go looking once
          something has already gone wrong, and then they scroll to the bottom.
          Shown to guests too: a guest needs the documents more than a
          signed-in customer does. */}
      <nav
        aria-label={t("settings.legalLabel")}
        className="flex flex-col items-center gap-2.5 pb-1 pt-2"
      >
        {LEGAL_LINKS.map(({ doc, key }) => {
          const href = legalUrl(locale, doc);
          return (
            <a
              key={key}
              href={href}
              // A real href — so it reads as a link, survives a long-press, and
              // still works outside Telegram — but the tap goes through the
              // native bridge. A plain target="_blank" inside the WebView is
              // treated as in-place navigation and replaces the Mini App.
              onClick={(e) => {
                e.preventDefault();
                openExternalLink(href);
              }}
              className="text-muted-foreground/60 hover:text-foreground text-[13px] transition-colors"
              data-testid={`legal-${doc ?? "index"}`}
            >
              {t(key)}
            </a>
          );
        })}
      </nav>

      {/* Language picker sheet */}
      <Sheet open={langOpen} onOpenChange={setLangOpen}>
        <SheetContent side="bottom" className="rounded-t-3xl">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Languages size={16} className="text-primary" aria-hidden="true" />
              {t("settings.languageSheetTitle")}
            </SheetTitle>
          </SheetHeader>
          <div className="mt-4 space-y-1.5">
            {LOCALES.map((loc) => {
              const active = loc === locale;
              return (
                <button
                  key={loc}
                  type="button"
                  onClick={() => {
                    pickLanguage(loc);
                  }}
                  className={`flex w-full items-center justify-between rounded-2xl border px-4 py-3 text-left transition-colors ${
                    active ? "border-primary/50 bg-primary/10" : "border-border hover:bg-white/5"
                  }`}
                  data-testid={`lang-${loc}`}
                >
                  <span className="flex items-center gap-3">
                    <img
                      src={LANGUAGE_FLAGS[loc]}
                      alt=""
                      aria-hidden="true"
                      className="h-6 w-6 rounded-full object-cover"
                    />
                    <span className="text-sm font-medium text-white">{LANGUAGE_NAMES[loc]}</span>
                  </span>
                  {active && <Check size={16} className="text-primary" />}
                </button>
              );
            })}
          </div>
        </SheetContent>
      </Sheet>

      {/* About sheet */}
      <Sheet open={aboutOpen} onOpenChange={setAboutOpen}>
        <SheetContent side="bottom" className="rounded-t-3xl">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Info size={16} className="text-primary" aria-hidden="true" />
              {t("settings.about")}
            </SheetTitle>
          </SheetHeader>
          <div className="mt-4 space-y-3 text-sm">
            <div className="border-border flex items-center justify-between rounded-2xl border p-3">
              <span className="text-white/60">{t("settings.aboutVersion")}</span>
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
                    {t("settings.companySince", { year: COMPANY_SINCE })}
                  </p>
                )}
              </div>
            )}

            <p className="leading-relaxed text-white/60">{t("settings.aboutBlurb")}</p>
            <p className="text-xs leading-relaxed text-white/40">{t("settings.aboutSupport")}</p>
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
  valueIcon,
  onClick,
  chevron,
  last,
}: {
  icon: typeof Info;
  iconClass?: string;
  label: string;
  value?: string;
  valueIcon?: React.ReactNode;
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
        {valueIcon}
        {value && <span className="text-muted-foreground text-xs font-medium">{value}</span>}
        {chevron ?? <ChevronRight size={16} className="text-muted-foreground/50" />}
      </div>
    </button>
  );
}
