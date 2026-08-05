# 0043. Keep `script-src 'unsafe-inline'` in the storefront CSP (accept, don't nonce)

- **Status**: Accepted
- **Date**: 2026-08-05
- **Deciders**: @jamaomonov
- **Tags**: frontend | security | infra

## Context and problem statement

The public storefront's Content-Security-Policy (`infra/caddy/Caddyfile.prod`)
allows `script-src 'self' 'unsafe-inline' …`. `'unsafe-inline'` lets the browser
run scripts written directly in the HTML, which means CSP cannot distinguish our
own inline scripts from an attacker-injected `<script>` — so it removes CSP's
protection against inline-script XSS. A security audit flagged this (finding
M2-fe, MEDIUM).

Removing `'unsafe-inline'` requires proving each inline script is ours, via a
per-request **nonce** or per-script **hash**. Both conflict with how the
storefront is built.

## Decision drivers

- The storefront is **SSG** (static generation) for SEO and to serve ~200 RPS
  from a single VPS with CDN-cacheable HTML — a core architectural constraint
  (see AGENTS.md / project scale targets).
- The audit found **no XSS injection sink** on the frontend: user content is
  rendered via React (auto-escaped), JSON-LD is escaped (`packages/utils/json-ld`),
  and the one raw-HTML path (admin Telegram preview) is whitelist-sanitized.
- `'unsafe-inline'` is only exploitable **in combination with** an actual XSS
  entry point, which does not currently exist.

## Considered options

1. **Accept `'unsafe-inline'`, document it, rely on compensating controls.**
2. **Nonce migration** — middleware injects a per-request nonce + `strict-dynamic`.
   A nonce must differ per request, but SSG serves one identical prebuilt HTML to
   everyone; adding a nonce forces **dynamic (per-request) rendering**, losing
   SSG/CDN caching → SEO and single-VPS-throughput regression.
3. **Hash allowlist** — infeasible: Next App Router emits content-dependent inline
   hydration scripts (`self.__next_f.push(...)`) whose hashes vary per page and
   can't be enumerated statically.

## Decision outcome

**Chosen option: 1.** Keep `'unsafe-inline'` and preserve SSG. Removing it would
mean converting the whole storefront to dynamic rendering — regressing the SEO
and performance the business depends on — to gain a defense-in-depth layer whose
only exploit path (a frontend XSS) does not exist today and whose main amplifier
has already been removed.

`'unsafe-inline'` is a missing safety net, not an open hole: it becomes dangerous
only if a future change introduces an XSS sink. Note that a strong backend does
**not** neutralize XSS — XSS runs in the victim's browser under their live
session, so server-side authz/IDOR checks see a legitimate user. The frontend
CSP is the layer that would matter, and we are deliberately not hardening it here.

### Compensating controls (already in place)

- **No untrusted HTML rendering.** React auto-escaping everywhere; JSON-LD
  escaped; the only `dangerouslySetInnerHTML` (admin Telegram preview) uses a
  strict whitelist sanitizer. This discipline is the real preventive control.
- **Access token moved out of localStorage into memory** (ADR-context: M1-fe), so
  even a hypothetical inline XSS cannot exfiltrate a durable token from storage.
- **Stored-content sanitization**: review body/author HTML-stripped on write;
  SVG uploads rejected (would execute on the CDN origin).
- The rest of the CSP is tight: `object-src 'none'`, `base-uri 'self'`,
  `form-action 'self'`, `frame-ancestors 'none'`.

### Negative consequences

- If a future frontend change introduces an XSS sink, `'unsafe-inline'` lets that
  script run unblocked (read on-screen data, act as the user while the tab is
  open). Mitigated by, and dependent on, the "never render untrusted HTML"
  discipline above.

## Validation

- The frontend audit found no injection sink; this decision is revisited if one
  is ever introduced or if the storefront moves to dynamic rendering for other
  reasons (at which point nonce + `strict-dynamic` becomes cheap and should be
  adopted).
- Guard: any new `dangerouslySetInnerHTML` or raw-HTML render on
  user/DB-sourced data is a security-review blocker while this CSP stands.
