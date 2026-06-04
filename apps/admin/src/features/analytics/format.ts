/** Format a string-decimal as USD for display. */
export function usd(s: string): string {
  return `$${Number(s).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}`;
}

/** Format a string-decimal as USDT (supplier wholesale cost) for display. */
export function usdt(s: string): string {
  return `${Number(s).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} USDT`;
}
