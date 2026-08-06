import { getTranslations } from "next-intl/server";

/**
 * Keyboard bypass for the fixed header.
 *
 * Visually hidden until focused, then it lands in the top-left corner above
 * everything else. WCAG 2.4.1: without it the only way into the content is to
 * tab through the header on every page.
 */
export async function SkipLink() {
  const t = await getTranslations("web.nav");
  return (
    <a
      href="#main-content"
      className="bg-primary text-primary-foreground rounded-btn sr-only px-4 py-2 text-sm font-semibold focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[200] focus:shadow-lg"
    >
      {t("skipToContent")}
    </a>
  );
}
