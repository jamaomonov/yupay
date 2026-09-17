import { Shell } from "./Shell";

import type { Metadata } from "next";

/** The cabinet is a signed-in, client-rendered surface: never indexed. */
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function CabinetLayout({ children }: { children: React.ReactNode }) {
  return <Shell>{children}</Shell>;
}
