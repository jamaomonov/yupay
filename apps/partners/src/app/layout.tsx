/**
 * Root layout. The real `<html>` wrapper lives in the `[locale]` segment so
 * `lang=` is set per request — the same shape the storefront uses.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
