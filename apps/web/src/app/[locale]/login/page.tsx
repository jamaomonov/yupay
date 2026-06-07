"use client";

import { useEffect } from "react";

import { useLoginModal } from "@/store/useLoginModal";

/**
 * The /login route renders nothing itself — it opens the global login modal
 * (mounted in the layout) so direct links and the /account auth-gate redirect
 * still land on the modal over the storefront.
 */
export default function LoginPage() {
  const open = useLoginModal((s) => s.open);
  useEffect(() => {
    open();
  }, [open]);
  return null;
}
