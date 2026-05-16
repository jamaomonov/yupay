/**
 * Root layout. The actual `<html>` wrapper lives in the `[locale]` segment so that
 * `lang=...` is set per request. This file simply forwards children.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
