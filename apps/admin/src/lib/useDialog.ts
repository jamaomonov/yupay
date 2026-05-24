/**
 * Modal-dialog plumbing in one hook.
 *
 * Centralises the boring (and easy-to-forget) bits every dialog needs:
 *   - Focus restoration — store the previously-focused element on open,
 *     return focus there on close.
 *   - Esc key closes.
 *   - Tab/Shift-Tab cycles within the dialog's container ref.
 *
 * Doesn't touch styling or markup — the dialog component owns its DOM and
 * decides where `containerRef` lands. The hook only attaches/detaches the
 * keyboard handlers and bookkeeps focus.
 */

import { useEffect, useRef, type RefObject } from "react";

interface Options {
  /** Whether the dialog is currently visible. */
  open: boolean;
  /** Called on Escape and (optionally) when focus restoration is requested. */
  onClose: () => void;
  /** The dialog root — the element that should trap Tab focus. */
  containerRef: RefObject<HTMLElement | null>;
  /**
   * If provided, called after the dialog mounts to focus the right element
   * (e.g. the first input). The hook itself doesn't pick a target — that's a
   * per-dialog decision.
   */
  initialFocus?: () => void;
}

/**
 * Wire up focus restoration, Esc-to-close, and a Tab focus trap for a dialog.
 *
 * Usage:
 *
 *     const dialogRef = useRef<HTMLDivElement | null>(null);
 *     const inputRef = useRef<HTMLInputElement | null>(null);
 *     useDialog({
 *       open,
 *       onClose,
 *       containerRef: dialogRef,
 *       initialFocus: () => inputRef.current?.focus(),
 *     });
 */
export function useDialog({ open, onClose, containerRef, initialFocus }: Options): void {
  const previousFocus = useRef<HTMLElement | null>(null);

  // Focus restoration + initial focus on (re)open.
  useEffect(() => {
    if (!open) {
      const target = previousFocus.current;
      previousFocus.current = null;
      if (target && document.contains(target)) target.focus();
      return;
    }
    previousFocus.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (initialFocus) {
      // setTimeout(0) so the focus call runs after the dialog has actually mounted.
      const t = window.setTimeout(() => {
        initialFocus();
      }, 0);
      return () => {
        window.clearTimeout(t);
      };
    }
    return undefined;
  }, [open, initialFocus]);

  // Esc closes the dialog.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  // Tab focus trap.
  useEffect(() => {
    if (!open) return;
    const root = containerRef.current;
    if (!root) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const focusable = root.querySelectorAll<HTMLElement>(
        [
          "a[href]",
          "button:not([disabled])",
          "input:not([disabled])",
          "select:not([disabled])",
          "textarea:not([disabled])",
          '[tabindex]:not([tabindex="-1"])',
        ].join(","),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    root.addEventListener("keydown", onKey);
    return () => {
      root.removeEventListener("keydown", onKey);
    };
  }, [open, containerRef]);
}
