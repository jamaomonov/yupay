import { intlLocale } from "./seo";

/**
 * Dates in the storefront's three languages, the same on the server and in the
 * browser.
 *
 * Chrome ships no Uzbek date data: `Intl.DateTimeFormat("uz", {dateStyle:
 * "medium"})` prints «2026 M11 13» in the browser while Node prints
 * «13-noy, 2026» — wrong on screen, and a hydration mismatch for any client
 * component (2026-11-13 review). Uzbek is therefore spelled out here; Russian
 * and English go through `Intl` as before.
 */
export type DateStyle = "date" | "dateTime" | "time" | "dayMonth" | "numeric";

const UZ_MONTHS_SHORT = [
  "yan",
  "fev",
  "mar",
  "apr",
  "may",
  "iyn",
  "iyl",
  "avg",
  "sen",
  "okt",
  "noy",
  "dek",
] as const;
const UZ_MONTHS_LONG = [
  "yanvar",
  "fevral",
  "mart",
  "aprel",
  "may",
  "iyun",
  "iyul",
  "avgust",
  "sentyabr",
  "oktyabr",
  "noyabr",
  "dekabr",
] as const;

const INTL_OPTIONS: Record<DateStyle, Intl.DateTimeFormatOptions> = {
  date: { dateStyle: "medium" },
  dateTime: { dateStyle: "medium", timeStyle: "short" },
  time: { hour: "2-digit", minute: "2-digit" },
  dayMonth: { day: "numeric", month: "long" },
  // Intl's default short date, as the order lists printed before.
  numeric: {},
};

const pad = (n: number): string => String(n).padStart(2, "0");

function uzbek(d: Date, style: DateStyle): string {
  const day = d.getDate();
  const month = d.getMonth();
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const short = `${String(day)}-${UZ_MONTHS_SHORT[month] ?? ""}, ${String(d.getFullYear())}`;
  switch (style) {
    case "date":
      return short;
    case "dateTime":
      return `${short}, ${time}`;
    case "time":
      return time;
    case "dayMonth":
      return `${String(day)}-${UZ_MONTHS_LONG[month] ?? ""}`;
    case "numeric":
      return `${pad(day)}.${pad(month + 1)}.${String(d.getFullYear())}`;
    default: {
      const never: never = style;
      return never;
    }
  }
}

/** `iso` (or a Date) formatted for `locale` ("ru" | "uz" | "en", bare or tagged). */
export function formatDate(locale: string, value: string | Date, style: DateStyle): string {
  const d = typeof value === "string" ? new Date(value) : value;
  if (locale.slice(0, 2).toLowerCase() === "uz") return uzbek(d, style);
  return new Intl.DateTimeFormat(intlLocale(locale.slice(0, 2)), INTL_OPTIONS[style]).format(d);
}
