import { createNavigation } from "next-intl/navigation";

import { routing } from "./routing";

/**
 * Locale-aware navigation.
 *
 * Every internal link must come from here. A plain `next/link` to `/login`
 * drops the prefix, and with `localePrefix: "as-needed"` that silently means
 * Russian: an Uzbek visitor pressing "Panelga kirish" landed on a Russian
 * form. `usePathname` here returns the path *without* the locale segment,
 * which is what the language switcher needs to rewrite it.
 *
 * It carries no query string, so anything that depends on one — the
 * set-password token — must not offer the switcher.
 */
export const { Link, usePathname, useRouter, getPathname } = createNavigation(routing);
