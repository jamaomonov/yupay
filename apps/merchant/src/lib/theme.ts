/**
 * Theme preference, remembered per browser.
 *
 * Dark is the default (spec §11) and the storefront's ground; light is the
 * same tokens with different values, so nothing here knows a colour.
 */

export type Theme = "dark" | "light";

export const THEME_KEY = "yupay.merchant.theme";

/** Read the stored choice, or `null` when there is none to honour. */
export function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === "dark" || value === "light" ? value : null;
  } catch {
    return null;
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* the choice then lasts for this tab only, which is better than failing */
  }
}

/**
 * The script that runs before first paint.
 *
 * Inlined into `<head>` so the ground colour is right on the very first frame.
 * Without it every visit to a light-theme cabinet begins with a dark flash —
 * the class of bug that cannot be fixed in React, because React runs after the
 * document has already painted once.
 */
export const THEME_BOOTSTRAP = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_KEY,
)});if(t==="light"||t==="dark"){document.documentElement.dataset.theme=t}}catch(e){}})()`;
