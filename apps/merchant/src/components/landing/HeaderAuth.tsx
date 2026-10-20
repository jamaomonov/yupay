"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

import { hasSession } from "@/lib/api";
import { pathFor } from "@/lib/locale-href";

interface HeaderAuthProps {
  locale: string;
  login: string;
  register: string;
  openCabinet: string;
}

// The session lives in this browser's localStorage, which the server cannot see: the
// server and the first paint render the signed-out pair, then the client swaps in the
// cabinet link. No subscription — a sign-in elsewhere in the tab navigates away anyway.
const subscribe = () => () => undefined;
const signedOutOnServer = () => false;

/**
 * The header's account links. A reseller who is already signed in and opens the landing
 * gets one button back into the cabinet, not «Войти», which asked for the password of a
 * session that was still alive.
 */
export function HeaderAuth({ locale, login, register, openCabinet }: HeaderAuthProps) {
  const signedIn = useSyncExternalStore(subscribe, hasSession, signedOutOnServer);
  if (signedIn) {
    return (
      <Link
        href={pathFor(locale, "/cabinet")}
        className="bg-primary text-primary-foreground rounded-btn px-4 py-2 font-bold"
      >
        {openCabinet}
      </Link>
    );
  }
  return (
    <>
      <Link
        href={pathFor(locale, "/login")}
        className="border-border rounded-btn text-foreground border px-4 py-2 font-semibold"
      >
        {login}
      </Link>
      <Link
        href={pathFor(locale, "/register")}
        className="bg-primary text-primary-foreground rounded-btn px-4 py-2 font-bold"
      >
        {register}
      </Link>
    </>
  );
}
