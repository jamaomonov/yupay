import { MessageCircle } from "lucide-react";
import { getTranslations } from "next-intl/server";

/**
 * Persistent support entry — a floating "chat" pill that opens the Telegram
 * support handle, making support a visible, always-reachable channel rather
 * than a buried footer link. Desktop-only (lg+) so it never collides with the
 * mobile sticky pay bar; on smaller screens support lives in the menu, the
 * trust band and the footer.
 *
 * Just the round icon until the window is wide enough for the label to sit in
 * the margin: at 1280px the full pill reached into the order panel beside it
 * (design review 2026-10-26). 1400px leaves the label clear of the 1100px
 * content column and its 40px padding.
 */
export async function SupportFab() {
  const t = await getTranslations("web.nav");
  return (
    <a
      href="https://t.me/yupay_support"
      target="_blank"
      rel="noreferrer noopener"
      aria-label={t("support")}
      className="border-border-2 bg-card/95 text-foreground hover:border-primary/40 hover:bg-card-2 fixed bottom-6 right-6 z-40 hidden items-center gap-2.5 rounded-full border p-2.5 shadow-[0_12px_30px_-10px_rgba(0,0,0,0.6)] backdrop-blur-xl transition hover:-translate-y-0.5 lg:flex min-[1400px]:px-4 min-[1400px]:py-3"
    >
      <span className="bg-primary/15 text-primary flex h-7 w-7 items-center justify-center rounded-full">
        <MessageCircle size={16} strokeWidth={2.4} />
      </span>
      <span className="hidden text-sm font-semibold min-[1400px]:inline">{t("support")}</span>
    </a>
  );
}
