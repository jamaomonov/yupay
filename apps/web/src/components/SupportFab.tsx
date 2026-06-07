import { MessageCircle } from "lucide-react";
import { getTranslations } from "next-intl/server";

/**
 * Persistent support entry — a floating "chat" pill that opens the Telegram
 * support handle, making support a visible, always-reachable channel rather
 * than a buried footer link. Desktop-only (lg+) so it never collides with the
 * mobile sticky pay bar; on smaller screens support lives in the menu, the
 * trust band and the footer.
 */
export async function SupportFab() {
  const t = await getTranslations("web.nav");
  return (
    <a
      href="https://t.me/yupay_support"
      target="_blank"
      rel="noreferrer noopener"
      aria-label={t("support")}
      className="border-border-2 bg-card/95 text-foreground hover:border-primary/40 hover:bg-card-2 fixed bottom-6 right-6 z-40 hidden items-center gap-2.5 rounded-full border px-4 py-3 shadow-[0_12px_30px_-10px_rgba(0,0,0,0.6)] backdrop-blur-xl transition hover:-translate-y-0.5 lg:flex"
    >
      <span className="bg-primary/15 text-primary flex h-7 w-7 items-center justify-center rounded-full">
        <MessageCircle size={16} strokeWidth={2.4} />
      </span>
      <span className="text-sm font-semibold">{t("support")}</span>
    </a>
  );
}
