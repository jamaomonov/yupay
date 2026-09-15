import Link from "next/link";

/**
 * The 404 for anything outside `[locale]`.
 *
 * `app/[locale]/not-found.tsx` only catches a miss *inside* a matched locale
 * segment; a path that never matched the segment at all — `/nope` — falls
 * through to the root, where Next's own unbranded page was showing. This one
 * cannot use `getTranslations`, because there is no locale to translate into,
 * so it says the short version in all three and leans on the link.
 */
export default function RootNotFound() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-5 py-12">
      <h1 className="font-display text-2xl font-semibold tracking-tight">404</h1>
      <p className="text-tx-mute mt-2 text-sm leading-relaxed">
        Страница не найдена · Page not found · Sahifa topilmadi
      </p>
      <Link
        href="/"
        className="bg-primary text-primary-foreground rounded-btn mt-6 self-start px-4 py-2.5 text-sm font-semibold"
      >
        YuPay
      </Link>
    </main>
  );
}
