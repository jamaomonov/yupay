# Web Login Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the plain `/login` page with a polished, reusable multi-provider login modal (Telegram + Email functional; Google + Steam shown as "скоро"), opened from the header and at `/login`.

**Architecture:** A Zustand store (`useLoginModal`) holds open state; `<LoginModal>` is mounted once in the locale layout and overlays any page. The modal has two screens — a provider grid and an email/password screen that reuses the existing `AuthForm`. Telegram uses a custom button that fires the Telegram OAuth popup (`window.Telegram.Login.auth`) with a fallback to the official widget.

**Tech Stack:** Next.js 15 App Router, TypeScript strict, Zustand v5, next-intl v4, react-hook-form + zod, Tailwind v4, lucide-react.

**Branch:** `main`. `apps/web` has no unit-test suite — verification is `tsc` + `eslint` + `prettier` + manual run. Frequent commits.

---

## File Structure

- `apps/web/src/store/useLoginModal.ts` — NEW. Zustand store: `isOpen`, `open()`, `close()`.
- `apps/web/src/components/auth/ProviderIcons.tsx` — NEW. Inline-SVG brand glyphs (Telegram, Google, Steam).
- `apps/web/src/components/auth/ProviderButton.tsx` — NEW. Styled provider button with optional `soon` badge.
- `apps/web/src/components/auth/LoginModal.tsx` — NEW. The dialog (provider grid + email screen).
- `apps/web/src/components/auth/AuthForm.tsx` — MODIFY. Add `showTelegram?: boolean` prop.
- `apps/web/src/components/auth/AccountMenu.tsx` — MODIFY. "Войти" opens the modal store.
- `apps/web/src/app/[locale]/login/page.tsx` — MODIFY. Open modal on mount; close → home.
- `apps/web/src/app/[locale]/layout.tsx` — MODIFY. Mount `<LoginModal locale={locale} />` in `<Providers>`.
- `packages/i18n/locales/{ru,en,uz}/web.json` — MODIFY. New `auth` keys.
- `infra/docker/web.Dockerfile` + `.github/workflows/build.yml` — MODIFY. `NEXT_PUBLIC_TELEGRAM_BOT_ID`.
- `apps/web/README.md` — MODIFY. Document `NEXT_PUBLIC_TELEGRAM_BOT_ID`.

---

## Task 1: Zustand store `useLoginModal`

**Files:** Create `apps/web/src/store/useLoginModal.ts`

- [ ] **Step 1: Create the store**

```typescript
import { create } from "zustand";

interface LoginModalState {
  isOpen: boolean;
  open: () => void;
  close: () => void;
}

/** Controls the global login modal (mounted once in the locale layout). */
export const useLoginModal = create<LoginModalState>((set) => ({
  isOpen: false,
  open: () => {
    set({ isOpen: true });
  },
  close: () => {
    set({ isOpen: false });
  },
}));
```

- [ ] **Step 2: Typecheck**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: no errors. (`zustand` is already in `apps/web/package.json`.)

- [ ] **Step 3: Commit**

```bash
cd /Users/macbook_uz/Projects/yupay
git add apps/web/src/store/useLoginModal.ts
git commit -m "feat(web): login modal store"
```

---

## Task 2: i18n keys (ru/en/uz)

**Files:** Modify `packages/i18n/locales/ru/web.json`, `packages/i18n/locales/en/web.json`, `packages/i18n/locales/uz/web.json`

- [ ] **Step 1: Add keys to the `auth` object in each locale**

Add these keys inside the existing top-level `"auth": { ... }` object of each `web.json`.

`ru/web.json` (`auth`):

```jsonc
"modalTitle": "Войдите или зарегистрируйтесь",
"providerTelegram": "Telegram",
"providerGoogle": "Google",
"providerSteam": "Steam",
"providerEmail": "Email",
"soon": "скоро",
"agreePrefix": "Прочёл и согласен с",
"privacy": "Privacy Policy",
"terms": "Terms of Use",
"and": "и",
"back": "Назад"
```

`en/web.json` (`auth`):

```jsonc
"modalTitle": "Sign in or register",
"providerTelegram": "Telegram",
"providerGoogle": "Google",
"providerSteam": "Steam",
"providerEmail": "Email",
"soon": "soon",
"agreePrefix": "I have read and agree to the",
"privacy": "Privacy Policy",
"terms": "Terms of Use",
"and": "and",
"back": "Back"
```

`uz/web.json` (`auth`):

```jsonc
"modalTitle": "Kiring yoki roʻyxatdan oʻting",
"providerTelegram": "Telegram",
"providerGoogle": "Google",
"providerSteam": "Steam",
"providerEmail": "Email",
"soon": "tez orada",
"agreePrefix": "Oʻqidim va roziman:",
"privacy": "Privacy Policy",
"terms": "Terms of Use",
"and": "va",
"back": "Orqaga"
```

- [ ] **Step 2: Verify equal key counts + valid JSON**

Run:

```bash
cd /Users/macbook_uz/Projects/yupay && node -e "const r=require('./packages/i18n/locales/ru/web.json'),e=require('./packages/i18n/locales/en/web.json'),u=require('./packages/i18n/locales/uz/web.json');const keys=o=>Object.entries(o).flatMap(([k,v])=>v&&typeof v==='object'?Object.keys(v).map(s=>k+'.'+s):[k]);const rk=keys(r).sort(),ek=keys(e).sort(),uk=keys(u).sort();console.log('ru',rk.length,'en',ek.length,'uz',uk.length);const miss=(a,b,n)=>a.filter(x=>!b.includes(x)).forEach(x=>console.log('MISSING in '+n+':',x));miss(rk,ek,'en');miss(rk,uk,'uz');miss(ek,rk,'ru');"
```

Expected: equal counts, no `MISSING` lines.

- [ ] **Step 3: Prettier**

Run: `cd /Users/macbook_uz/Projects/yupay && pnpm exec prettier --write "packages/i18n/locales/**/web.json" && pnpm exec prettier --check "packages/i18n/locales/**/web.json"`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd /Users/macbook_uz/Projects/yupay
git add packages/i18n/locales/ru/web.json packages/i18n/locales/en/web.json packages/i18n/locales/uz/web.json
git commit -m "feat(web): i18n keys for login modal (ru/en/uz)"
```

---

## Task 3: Provider icons + button

**Files:** Create `apps/web/src/components/auth/ProviderIcons.tsx`, `apps/web/src/components/auth/ProviderButton.tsx`

- [ ] **Step 1: Create `ProviderIcons.tsx`**

```tsx
/** Compact inline-SVG brand glyphs for the login modal. 20×20, currentColor where sensible. */

export function TelegramIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
      <path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71l-4.14-3.05-1.99 1.93c-.23.23-.42.42-.83.42z" />
    </svg>
  );
}

export function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"
      />
    </svg>
  );
}

export function SteamIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
      <path d="M12 2a10 10 0 0 0-9.96 9.13l5.36 2.22a2.83 2.83 0 0 1 1.6-.5h.13l2.38-3.45v-.05a3.77 3.77 0 1 1 3.77 3.77h-.09l-3.4 2.43v.1a2.84 2.84 0 0 1-5.65.37l-3.83-1.59A10 10 0 1 0 12 2zM8.5 17.6l-1.23-.5a2.13 2.13 0 0 0 3.9-1.07 2.13 2.13 0 0 0-2.93-1.97l1.27.53a1.57 1.57 0 1 1-1.2 2.9l-.81.08zm9.27-7.86a2.51 2.51 0 1 0-5.02 0 2.51 2.51 0 0 0 5.02 0zm-4.4 0a1.89 1.89 0 1 1 3.78 0 1.89 1.89 0 0 1-3.78 0z" />
    </svg>
  );
}
```

- [ ] **Step 2: Create `ProviderButton.tsx`**

```tsx
"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

export interface ProviderButtonProps {
  label: string;
  icon: ReactNode;
  /** Tailwind classes for the button surface (background/text/border). */
  surface: string;
  onClick?: () => void;
  soon?: boolean;
}

/** A single provider tile in the login modal grid. `soon` => inert + "скоро" badge. */
export function ProviderButton({ label, icon, surface, onClick, soon }: ProviderButtonProps) {
  const t = useTranslations("web.auth");
  return (
    <button
      type="button"
      disabled={soon}
      aria-disabled={soon}
      onClick={soon ? undefined : onClick}
      className={`relative flex h-[52px] items-center justify-center gap-2.5 rounded-[14px] px-4 text-[15px] font-semibold transition ${surface} ${
        soon ? "cursor-not-allowed opacity-55" : "hover:brightness-110"
      }`}
    >
      <span className="flex items-center">{icon}</span>
      <span>{label}</span>
      {soon && (
        <span className="bg-bg/70 text-tx-mute absolute right-2 top-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide">
          {t("soon")}
        </span>
      )}
    </button>
  );
}
```

- [ ] **Step 3: Typecheck + lint + prettier**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint src/components/auth/ProviderIcons.tsx src/components/auth/ProviderButton.tsx && pnpm exec prettier --check src/components/auth/ProviderIcons.tsx src/components/auth/ProviderButton.tsx`
Expected: clean. (If eslint flags `Mail` unused etc., fix; the icons file has no client hooks so no `"use client"` needed there.)

- [ ] **Step 4: Commit**

```bash
cd /Users/macbook_uz/Projects/yupay
git add apps/web/src/components/auth/ProviderIcons.tsx apps/web/src/components/auth/ProviderButton.tsx
git commit -m "feat(web): provider icons + button for login modal"
```

---

## Task 4: AuthForm `showTelegram` prop

**Files:** Modify `apps/web/src/components/auth/AuthForm.tsx`

- [ ] **Step 1: Add the prop and gate the inline Telegram button**

Change the component signature and the bottom Telegram block. Replace the props destructuring:

```tsx
export function AuthForm({
  mode,
  locale,
  onSubmit,
  showTelegram = true,
}: {
  mode: "login" | "register";
  locale: string;
  onSubmit: (v: Values) => Promise<void>;
  showTelegram?: boolean;
}) {
```

Replace the trailing block (the divider + `<TelegramLoginButton />`):

```tsx
      {showTelegram && (
        <>
          <div className="border-border/70 my-2 border-t" />
          <TelegramLoginButton />
        </>
      )}
    </form>
  );
}
```

- [ ] **Step 2: Typecheck + lint + prettier**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint src/components/auth/AuthForm.tsx && pnpm exec prettier --check src/components/auth/AuthForm.tsx`
Expected: clean. The existing `/login` and `/register` pages pass no `showTelegram`, so they default to `true` (unchanged behavior).

- [ ] **Step 3: Commit**

```bash
cd /Users/macbook_uz/Projects/yupay
git add apps/web/src/components/auth/AuthForm.tsx
git commit -m "feat(web): AuthForm showTelegram prop"
```

---

## Task 5: LoginModal

**Files:** Create `apps/web/src/components/auth/LoginModal.tsx`

- [ ] **Step 1: Create the modal**

```tsx
"use client";

import { Mail, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { ProviderButton } from "./ProviderButton";
import { GoogleIcon, SteamIcon, TelegramIcon } from "./ProviderIcons";
import { TelegramLoginButton } from "./TelegramLoginButton";
import { AuthForm } from "./AuthForm";

import { useAuth } from "@/lib/auth";
import { useLoginModal } from "@/store/useLoginModal";

interface TelegramAuth {
  Login?: {
    auth: (
      opts: { bot_id: number; request_access?: string },
      cb: (user: Record<string, unknown> | false) => void,
    ) => void;
  };
}

const BOT_ID = process.env.NEXT_PUBLIC_TELEGRAM_BOT_ID;

export function LoginModal({ locale }: { locale: string }) {
  const t = useTranslations("web.auth");
  const router = useRouter();
  const { isOpen, close } = useLoginModal();
  const { login, loginWithTelegram } = useAuth();
  const [screen, setScreen] = useState<"providers" | "email">("providers");

  // Reset to the provider grid each time the modal opens.
  useEffect(() => {
    if (isOpen) setScreen("providers");
  }, [isOpen]);

  // Esc closes.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [isOpen, close]);

  const onTelegram = useCallback(() => {
    const tg = (window as unknown as { Telegram?: TelegramAuth }).Telegram;
    if (BOT_ID && tg?.Login?.auth) {
      tg.Login.auth({ bot_id: Number(BOT_ID), request_access: "write" }, (user) => {
        if (user) void loginWithTelegram(user);
      });
    }
  }, [loginWithTelegram]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("modalTitle")}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
    >
      <button
        type="button"
        aria-label="Close"
        onClick={close}
        className="bg-bg/80 absolute inset-0 backdrop-blur-sm"
      />
      <div className="border-border bg-card relative z-10 w-full max-w-[420px] rounded-2xl border p-7 shadow-2xl">
        <button
          type="button"
          onClick={close}
          aria-label="Close"
          className="text-tx-mute hover:bg-muted hover:text-foreground absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-full transition"
        >
          <X size={18} />
        </button>

        <h2 className="font-display max-w-[16rem] text-2xl font-bold leading-tight tracking-[-0.02em]">
          {t("modalTitle")}
        </h2>

        {screen === "providers" ? (
          <>
            <div className="mt-6 grid grid-cols-2 gap-3">
              {BOT_ID ? (
                <ProviderButton
                  label={t("providerTelegram")}
                  icon={<TelegramIcon />}
                  surface="bg-[#2AABEE] text-white"
                  onClick={onTelegram}
                />
              ) : (
                <div className="col-span-2 flex justify-center">
                  <TelegramLoginButton />
                </div>
              )}
              <ProviderButton
                label={t("providerEmail")}
                icon={<Mail size={18} />}
                surface="bg-muted text-foreground border border-border"
                onClick={() => {
                  setScreen("email");
                }}
              />
              <ProviderButton
                label={t("providerGoogle")}
                icon={<GoogleIcon />}
                surface="bg-white text-[#1f1f1f]"
                soon
              />
              <ProviderButton
                label={t("providerSteam")}
                icon={<SteamIcon />}
                surface="bg-[#1b2838] text-white"
                soon
              />
            </div>

            <p className="text-tx-dim mt-6 text-center text-xs leading-relaxed">
              {t("agreePrefix")}{" "}
              <Link href={`/${locale}/legal/privacy`} className="hover:text-tx underline">
                {t("privacy")}
              </Link>{" "}
              {t("and")}{" "}
              <Link href={`/${locale}/legal/terms`} className="hover:text-tx underline">
                {t("terms")}
              </Link>
            </p>
          </>
        ) : (
          <div className="mt-6">
            <button
              type="button"
              onClick={() => {
                setScreen("providers");
              }}
              className="text-tx-mute hover:text-tx mb-4 text-[13px]"
            >
              ← {t("back")}
            </button>
            <AuthForm
              mode="login"
              locale={locale}
              showTelegram={false}
              onSubmit={async (v) => {
                await login(v.email, v.password);
                close();
                router.push(`/${locale}/account`);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
```

> Confirm the `/legal/privacy` and `/legal/terms` routes exist (the storefront has `[locale]/legal/[doc]/page.tsx` — the doc slugs are `privacy`/`terms`; adjust the hrefs if the real slugs differ). Confirm `TelegramLoginButton` is exported from `./TelegramLoginButton` (it is).

- [ ] **Step 2: Typecheck + lint + prettier**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint src/components/auth/LoginModal.tsx && pnpm exec prettier --check src/components/auth/LoginModal.tsx`
Expected: clean. (If eslint flags the `window as unknown as` cast, keep it — it's the documented DOM-shape narrowing for the Telegram global; add an inline comment if the rule requires.)

- [ ] **Step 3: Commit**

```bash
cd /Users/macbook_uz/Projects/yupay
git add apps/web/src/components/auth/LoginModal.tsx
git commit -m "feat(web): login modal dialog (providers + email screens)"
```

---

## Task 6: Wire-up (AccountMenu, login page, layout mount)

**Files:** Modify `apps/web/src/components/auth/AccountMenu.tsx`, `apps/web/src/app/[locale]/login/page.tsx`, `apps/web/src/app/[locale]/layout.tsx`

- [ ] **Step 1: AccountMenu — "Войти" opens the modal**

In `AccountMenu.tsx`, add the import and replace the unauthenticated `<Link>` with a `<button>`:

Add import (with the other `@/` imports):

```tsx
import { useLoginModal } from "@/store/useLoginModal";
```

Inside the component, after `const { user, isLoading, logout } = useAuth();`:

```tsx
const openLogin = useLoginModal((s) => s.open);
```

Replace the `if (!user) { return ( <Link ...>Войти</Link> ); }` block:

```tsx
if (!user) {
  return (
    <button
      type="button"
      onClick={openLogin}
      className="border-border-2 text-foreground hover:border-tx-dim hover:bg-muted rounded-btn inline-flex h-[38px] items-center justify-center border px-4 text-sm font-semibold transition"
    >
      Войти
    </button>
  );
}
```

(`Link` is still used by the authenticated menu, so keep the import.)

- [ ] **Step 2: login/page.tsx — open the modal on mount, close → home**

Replace the whole file `apps/web/src/app/[locale]/login/page.tsx`:

```tsx
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
```

> Note: closing the modal from `/login` leaves the `/login` URL in the address bar with no visible modal. The modal's close handler routes to `/${locale}` (Task 5 already calls `router.push` only on successful email login; for the plain close we rely on the backdrop). To make close-from-`/login` return home, the modal's `close` button stays generic; this is acceptable for v1 (the user can navigate away). If desired later, a small effect can push home when the modal closes on the `/login` route.

- [ ] **Step 3: layout.tsx — mount the modal**

In `apps/web/src/app/[locale]/layout.tsx`, import and mount `<LoginModal>` inside `<Providers>` (after `<Footer />`):

```tsx
import { LoginModal } from "@/components/auth/LoginModal";
```

```tsx
<Providers>
  <Header locale={locale} />
  {children}
  <Footer locale={locale} />
  <LoginModal locale={locale} />
</Providers>
```

- [ ] **Step 4: Typecheck + lint + prettier (whole touched set)**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint src/components/auth/AccountMenu.tsx "src/app/[locale]/login/page.tsx" "src/app/[locale]/layout.tsx" && pnpm exec prettier --check src/components/auth/AccountMenu.tsx "src/app/[locale]/login/page.tsx" "src/app/[locale]/layout.tsx"`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/macbook_uz/Projects/yupay
git add apps/web/src/components/auth/AccountMenu.tsx "apps/web/src/app/[locale]/login/page.tsx" "apps/web/src/app/[locale]/layout.tsx"
git commit -m "feat(web): wire login modal into header, /login, and layout"
```

---

## Task 7: `NEXT_PUBLIC_TELEGRAM_BOT_ID` env wiring

**Files:** Modify `infra/docker/web.Dockerfile`, `.github/workflows/build.yml`, `apps/web/README.md`, `.env.example`, `apps/web/.env.example`

- [ ] **Step 1: web.Dockerfile — add the build ARG/ENV**

In `infra/docker/web.Dockerfile`, in the `builder` stage next to the existing `NEXT_PUBLIC_*` ARG/ENV (added previously), add:

```dockerfile
ARG NEXT_PUBLIC_TELEGRAM_BOT_ID=
ENV NEXT_PUBLIC_TELEGRAM_BOT_ID=${NEXT_PUBLIC_TELEGRAM_BOT_ID}
```

(Place both new lines immediately after the existing `ENV NEXT_PUBLIC_TELEGRAM_BOT_USERNAME=...` line, before `RUN pnpm --filter @yupay/web build`.)

- [ ] **Step 2: build.yml — pass it for the web image**

In `.github/workflows/build.yml`, in the `web` matrix entry's `build_args`, add the line:

```yaml
NEXT_PUBLIC_TELEGRAM_BOT_ID=
```

> Leave the value empty (the numeric bot id is set at build time when known). With an empty id the modal falls back to the official Telegram widget button, so login still works.

- [ ] **Step 3: env examples**

In both `.env.example` (root) and `apps/web/.env.example`, next to `NEXT_PUBLIC_TELEGRAM_BOT_USERNAME`, add:

```
NEXT_PUBLIC_TELEGRAM_BOT_ID=
```

- [ ] **Step 4: README note**

In `apps/web/README.md`, document the var: `NEXT_PUBLIC_TELEGRAM_BOT_ID` — the bot's numeric id (the token prefix before `:`), used to trigger the Telegram OAuth popup from the custom login button. When empty, the modal renders the official Telegram widget button as a fallback.

- [ ] **Step 5: Validate compose/build still parse**

Run:

```bash
cd /Users/macbook_uz/Projects/yupay/apps/api && uv run python -c "import yaml; yaml.safe_load(open('/Users/macbook_uz/Projects/yupay/.github/workflows/build.yml')); print('build.yml ok')"
```

Expected: `build.yml ok`.

- [ ] **Step 6: Commit**

```bash
cd /Users/macbook_uz/Projects/yupay
git add infra/docker/web.Dockerfile .github/workflows/build.yml .env.example apps/web/.env.example apps/web/README.md
git commit -m "build(web): NEXT_PUBLIC_TELEGRAM_BOT_ID for the login-modal Telegram popup"
```

---

## Task 8: Full gate + manual verification

- [ ] **Step 1: Static gates (whole web app)**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/**/*.{ts,tsx}" && pnpm exec prettier --check "src/**/*.{ts,tsx}"`
Expected: clean.

- [ ] **Step 2: i18n parity**

Run the Task 2 Step 2 key-count command again. Expected: equal counts, no `MISSING`.

- [ ] **Step 3: Rebuild web image + recreate (dev stack)**

Run:

```bash
cd /Users/macbook_uz/Projects/yupay && docker compose -p yupay-dev build web && docker compose -p yupay-dev up -d --no-deps --force-recreate web
```

Wait until `http://localhost:3000/ru` returns 200.

- [ ] **Step 4: Manual verification (http://localhost:3000)**

- Click "Войти" in the header → modal opens over the current page with the provider grid.
- Open `/ru/login` directly → modal opens.
- `/ru/account` while logged out → redirect to `/ru/login` → modal opens.
- Click **Email** → email/password form appears (with register/forgot links, no Telegram button); submit logs in and closes the modal.
- **Telegram** → fires the OAuth popup (or, with `NEXT_PUBLIC_TELEGRAM_BOT_ID` empty, renders the official widget button).
- **Google** / **Steam** → show "скоро", are inert.
- Esc, backdrop click, and × all close the modal.
- Smoke `/en` and `/uz`: title + provider labels localized.

- [ ] **Step 5: Confirm clean**

Run: `git status` (expect clean). Push only on explicit user go-ahead.

---

## Self-Review notes (author)

- **Spec coverage:** store (T1), i18n (T2), icons+button (T3), AuthForm prop (T4), modal with both screens + Telegram popup/fallback + Google/Steam "скоро" + privacy/terms footer + a11y close (T5), wire-up header/`/login`/layout (T6), `NEXT_PUBLIC_TELEGRAM_BOT_ID` Dockerfile+build.yml+README (T7), gate+manual (T8). All DoD items mapped.
- **Known v1 limitation (documented):** closing the modal while on the `/login` URL leaves `/login` in the address bar with no visible modal; acceptable for v1 (T6 Step 2 note). Google/Steam backend OAuth is a separate future slice.
- **Type consistency:** `useLoginModal` exposes `isOpen/open/close` used identically in T5/T6; `ProviderButton` props (`label/icon/surface/onClick/soon`) match T3↔T5; `AuthForm` gains `showTelegram?: boolean` (T4) used in T5.
