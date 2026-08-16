/**
 * Copy-to-clipboard with a fallback for non-secure contexts.
 *
 * `navigator.clipboard` is undefined when the admin is served over plain http
 * on an internal address, which is a normal way to reach it. Falling back to
 * the deprecated `execCommand` keeps the copy buttons working there instead of
 * looking broken; callers get a boolean so they can say so when even that
 * fails.
 */

export async function writeToClipboard(text: string): Promise<boolean> {
  // The cast widens rather than narrows: lib.dom declares `navigator.clipboard`
  // as always present, which is false outside a secure context.
  const clipboard = navigator.clipboard as Clipboard | undefined;
  if (clipboard) {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // Permission denied or the document lost focus; try the fallback.
    }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    // Deprecated, and the only copy path left when the async API is missing.
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(area);
  }
}
