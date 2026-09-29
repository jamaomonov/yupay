import { Shell } from "./Shell";

import type { Metadata } from "next";

/**
 * The cabinet is a signed-in, client-rendered surface: never indexed. Never machine
 * translated either (`notranslate`): Chrome's translator rewrites text nodes React still
 * owns, so balances and counts froze at «—», and it turned Free Fire into «Bepul olov».
 * The cabinet speaks ru / en / uz itself — the switch is in the top bar.
 */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
  other: { google: "notranslate" },
};

export default function CabinetLayout({ children }: { children: React.ReactNode }) {
  return <Shell>{children}</Shell>;
}
