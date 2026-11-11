/**
 * The root layout — a pass-through.
 *
 * `app/[locale]/layout.tsx` renders `<html>`; this exists only because
 * `app/not-found.tsx` needs a root layout above it, and without one Next
 * refuses to compile that page («not-found.tsx doesn't have a root layout»),
 * which in development took every route down with it.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
