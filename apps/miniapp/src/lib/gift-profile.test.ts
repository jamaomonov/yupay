import { afterEach, describe, expect, test, vi } from "vitest";

import {
  checkGiftProfile,
  profileCheckBlocks,
  profileCheckState,
  type GiftProfileCheck,
} from "./gift-profile";

/**
 * The pre-purchase recipient check on the Mini App
 * (`POST /api/v1/gifts/steam-profile`).
 *
 * The one rule the whole feature turns on: only a definitive `not_found` —
 * Steam itself saying the profile does not exist — may stand between the
 * buyer and Buy. Everything else (`unsupported`, `unavailable`, a thrown
 * fetch, a 500, a link nobody checked) has to leave the purchase available,
 * because a check that fails on our side must never cost a sale.
 *
 * This app's Vitest suite is node-env with no jsdom/RTL, so the render
 * decision lives in `profileCheckState` and is tested here directly rather
 * than by mounting `GiftBuyPanel` — same convention as `walletPayState` /
 * `giftPayHint` in `GiftGame.test.tsx`.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

type FetchMock = ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;

/** The one call the check makes, without a non-null assertion on the mock's
 *  call list — a `fetch` that never fired should fail loudly here rather than
 *  destructure `undefined` further down. */
function onlyCall(mock: FetchMock): [url: string, init?: RequestInit] {
  const call = mock.mock.calls[0];
  if (!call) throw new Error("fetch was never called");
  return call;
}

function personaResponse(nickname: string | null, avatarUrl: string | null = null): Response {
  return jsonResponse({
    status: "found",
    steam_id: "76561198000000000",
    nickname,
    avatar_url: avatarUrl,
  });
}

const LINK = "https://steamcommunity.com/id/neo";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("checkGiftProfile", () => {
  test("narrows a found verdict to the nickname and avatar the card renders", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(personaResponse("Neo", "https://avatars.steamstatic.com/a_full.jpg")),
    );
    await expect(checkGiftProfile(LINK)).resolves.toEqual({
      status: "found",
      nickname: "Neo",
      avatarUrl: "https://avatars.steamstatic.com/a_full.jpg",
    });
  });

  test("keeps a found verdict with no avatar — the nickname alone still confirms", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(personaResponse("Neo", null)));
    await expect(checkGiftProfile(LINK)).resolves.toEqual({
      status: "found",
      nickname: "Neo",
      avatarUrl: null,
    });
  });

  test.each(["not_found", "unsupported", "unavailable"] as const)(
    "passes a %s verdict straight through",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            jsonResponse({ status, steam_id: null, nickname: null, avatar_url: null }),
          ),
      );
      await expect(checkGiftProfile(LINK)).resolves.toEqual({ status });
    },
  );

  test("degrades a nameless found verdict to unavailable rather than an empty card", async () => {
    // The API contract says this cannot happen: `found` is only returned once
    // Steam actually gave us a persona. If it ever did, a green confirmation
    // card wrapped around nothing is the worst possible answer — and blocking
    // would be worse still, so it lands on the non-blocking status.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(personaResponse(null, "https://avatars.steamstatic.com/a.jpg")),
    );
    await expect(checkGiftProfile(LINK)).resolves.toEqual({ status: "unavailable" });
  });

  test("folds a network error into unavailable — never into a blocking verdict", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await expect(checkGiftProfile(LINK)).resolves.toEqual({ status: "unavailable" });
  });

  test("folds our own 500 into unavailable too", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "boom" }, 500)));
    await expect(checkGiftProfile(LINK)).resolves.toEqual({ status: "unavailable" });
  });

  test("folds a 404 into unavailable — the flag-off surface must not block a sale", async () => {
    // Unlike every catalog fetcher in `lib/gifts.ts`, a 404 here is NOT a
    // distinct "feature isn't live" signal worth surfacing: the check is
    // advisory, so an API build predating it degrades to "we couldn't ask".
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "not found" }, 404)));
    await expect(checkGiftProfile(LINK)).resolves.toEqual({ status: "unavailable" });
  });

  test("posts the link in the body, never in a query string, and sends no bearer token", async () => {
    // The query string is what Caddy's access log records verbatim and ships
    // to Loki, so a GET here would park a *third party's* Steam identity in
    // our logs. The body is not logged; see `GiftProfileIn` on the API side.
    const fetchMock: FetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(
        jsonResponse({ status: "unavailable", steam_id: null, nickname: null, avatar_url: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await checkGiftProfile("https://steamcommunity.com/id/neo mad");
    const [url, init] = onlyCall(fetchMock);
    // `apiBase` is "" under vitest (no VITE_API_BASE_URL), so the request URL
    // is root-relative — resolved against a base purely to inspect it.
    const parsed = new URL(url, "https://api.yupay.uz");
    expect(parsed.pathname).toBe("/api/v1/gifts/steam-profile");
    expect(parsed.search).toBe("");
    expect(init?.method).toBe("POST");
    const raw = init?.body;
    // Narrowed rather than cast: `BodyInit` also covers Blob/FormData/streams,
    // none of which `JSON.parse` would take.
    if (typeof raw !== "string") throw new Error("expected a JSON string body");
    const body: unknown = JSON.parse(raw);
    expect(body).toEqual({ invite_url: "https://steamcommunity.com/id/neo mad" });
    expect(new Headers(init?.headers).get("Authorization")).toBeNull();
  });

  test("strips bidi overrides out of the persona before anyone renders it", async () => {
    // A recipient picks their own Steam name and the buyer has never seen it
    // before. `U+202E` reverses everything after it, so in the confirm dialog
    // — where the name sits in the same row as the link the buyer is being
    // told to verify — it could reorder that link one tap before an
    // irreversible payment.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(personaResponse("Neo\u202Eevil")));
    await expect(checkGiftProfile(LINK)).resolves.toEqual({
      status: "found",
      nickname: "Neoevil",
      avatarUrl: null,
    });
  });

  test("keeps a genuinely right-to-left name intact — only the controls go", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(personaResponse("שלום")));
    await expect(checkGiftProfile(LINK)).resolves.toEqual({
      status: "found",
      nickname: "שלום",
      avatarUrl: null,
    });
  });

  test("the directional MARKS survive — they are not what makes a name dangerous", async () => {
    // The test above only proves Hebrew *letters* survive, which the character
    // set could never have touched. This is the regression it cannot catch
    // (2026-09-04 review round 1): U+200E/U+200F (LRM/RLM) are the marks a
    // real Hebrew, Arabic or Persian persona uses to pin the direction of the
    // punctuation and digits around it. They are *not* overrides — they add no
    // scope and reorder nothing — so widening the strip to "all the direction
    // characters" would silently mangle genuine names while every other test
    // here stayed green. `.trim()` leaves them too: they are Cf, not
    // whitespace.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(personaResponse("\u200Fשלום 7\u200E")));
    await expect(checkGiftProfile(LINK)).resolves.toEqual({
      status: "found",
      nickname: "\u200Fשלום 7\u200E",
      avatarUrl: null,
    });
  });

  test("degrades a name that was nothing but bidi controls to unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(personaResponse("\u202E\u2066")));
    await expect(checkGiftProfile(LINK)).resolves.toEqual({ status: "unavailable" });
  });

  test("carries an abort signal so a hung request can't spin the button forever", async () => {
    const fetchMock: FetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(
        jsonResponse({ status: "unavailable", steam_id: null, nickname: null, avatar_url: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await checkGiftProfile(LINK);
    const [, init] = onlyCall(fetchMock);
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    // Built from an `AbortController`, not `AbortSignal.timeout` — the latter
    // is missing before iOS 15.4, where it would throw before the request was
    // ever sent and make *every* check report «Steam не отвечает». Our buyers
    // are mass-market CIS mobile users and nothing here sets a browser floor.
    expect(init?.signal?.aborted).toBe(false);
  });

  test("folds the abort itself into unavailable, like any other failure", async () => {
    // What the browser actually does when the signal fires: reject the fetch.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("The operation was aborted.", "AbortError")),
    );
    await expect(checkGiftProfile(LINK)).resolves.toEqual({ status: "unavailable" });
  });
});

describe("profileCheckBlocks", () => {
  test("blocks only on a definitive not_found", () => {
    expect(profileCheckBlocks({ status: "not_found" })).toBe(true);
  });

  test.each(["unsupported", "unavailable"] as const)(
    "does not block on %s — that failure is ours, not the recipient's",
    (status) => {
      expect(profileCheckBlocks({ status })).toBe(false);
    },
  );

  test("does not block a found verdict", () => {
    expect(profileCheckBlocks({ status: "found", nickname: "Neo", avatarUrl: null })).toBe(false);
  });

  test("does not block a link nobody checked — the check is advisory, not required", () => {
    // Deliberately the opposite of `blocksCheckout` in `player-check-state.ts`,
    // where an unchecked id does block: there the check is a gate on a top-up,
    // here it is a second pair of eyes the buyer may skip.
    expect(profileCheckBlocks(null)).toBe(false);
  });
});

// The whole render decision for the check, pulled out pure — this app has no
// jsdom/RTL, so this is where the state matrix is actually pinned down.
describe("profileCheckState", () => {
  const found: GiftProfileCheck = { status: "found", nickname: "Neo", avatarUrl: null };
  /** The state of a field holding `link` and nothing else pending. */
  function forLink(link: string, check: GiftProfileCheck | null, attempted = false) {
    return profileCheckState({
      result: check === null ? null : { canonicalUrl: LINK, check },
      canonicalInvite: link,
      inviteHasValue: true,
      attempted,
    });
  }

  test("nothing to show before any check has run", () => {
    expect(forLink(LINK, null)).toEqual({
      found: null,
      alertKey: null,
      noteKey: null,
      blocks: false,
    });
  });

  test("found collapses the field into a card and says nothing in the note line", () => {
    expect(forLink(LINK, found)).toEqual({
      found: { nickname: "Neo", avatarUrl: null },
      alertKey: null,
      noteKey: null,
      blocks: false,
    });
  });

  test("not_found is the one verdict that blocks, and reads as an error", () => {
    expect(forLink(LINK, { status: "not_found" })).toEqual({
      found: null,
      alertKey: "gifts.game.profileNotFound",
      noteKey: null,
      blocks: true,
    });
  });

  test("unsupported is an advisory note beside a purchase that stays available", () => {
    expect(forLink(LINK, { status: "unsupported" })).toEqual({
      found: null,
      alertKey: null,
      noteKey: "gifts.game.profileUnsupported",
      blocks: false,
    });
  });

  test("unavailable is an advisory note too — our outage never costs a sale", () => {
    expect(forLink(LINK, { status: "unavailable" })).toEqual({
      found: null,
      alertKey: null,
      noteKey: "gifts.game.profileUnavailable",
      blocks: false,
    });
  });

  test("a verdict for a different profile is discarded, not shown", () => {
    // Two things at once: pointing the field at someone else resets the check
    // with no effect to keep in sync, and an answer landing after the buyer
    // already corrected the link is never shown against a profile they no
    // longer mean.
    const state = forLink("https://steamcommunity.com/id/neo2", { status: "not_found" });
    expect(state.blocks).toBe(false);
    expect(state.alertKey).toBeNull();
  });

  test("a stale found verdict stops confirming the moment the profile changes", () => {
    expect(forLink("https://steamcommunity.com/id/neo2", found).found).toBeNull();
  });

  // 2026-09-04 review round 1: the guard used to key on the raw field text, so
  // a cosmetic edit that resolves to the SAME profile — deleting a trailing
  // slash, dropping the scheme — discarded the verdict as stale. Harmless for
  // the four non-blocking states, but it meant a buyer could dismiss the ONE
  // verdict allowed to block a purchase by accident, and re-enable Buy for a
  // profile Steam had just said does not exist. The key is the canonical link
  // (`validateInviteUrl`'s output), which every such edit maps onto.
  test("a cosmetic edit that resolves to the same profile keeps the blocking verdict", () => {
    // `steamcommunity.com/id/neo/` and `https://steamcommunity.com/id/neo` are
    // one profile; both canonicalize to `LINK`.
    const state = profileCheckState({
      result: { canonicalUrl: LINK, check: { status: "not_found" } },
      canonicalInvite: LINK,
      inviteHasValue: true,
      attempted: false,
    });
    expect(state.blocks).toBe(true);
    expect(state.alertKey).toBe("gifts.game.profileNotFound");
  });

  test("a field that no longer parses at all drops the verdict", () => {
    // `canonicalInvite === null` — there is no profile to hold a verdict
    // against, so nothing is shown and nothing blocks.
    const state = profileCheckState({
      result: { canonicalUrl: LINK, check: { status: "not_found" } },
      canonicalInvite: null,
      inviteHasValue: true,
      attempted: false,
    });
    expect(state.blocks).toBe(false);
    expect(state.found).toBeNull();
  });

  test("«Проверить» on an empty field says what is missing instead of nothing", () => {
    // The invite field's own error needs a non-empty value, so without this
    // the button is a silent no-op. Reuses the Buy button's own wording for
    // the same missing thing rather than forking a fourth sentence.
    expect(
      profileCheckState({
        result: null,
        canonicalInvite: null,
        inviteHasValue: false,
        attempted: true,
      }),
    ).toEqual({
      found: null,
      alertKey: null,
      noteKey: "gifts.game.payHintInvite",
      blocks: false,
    });
  });

  test("a wrong (non-empty) link gets no note — its own field error already speaks", () => {
    expect(
      profileCheckState({
        result: null,
        canonicalInvite: null,
        inviteHasValue: true,
        attempted: true,
      }).noteKey,
    ).toBeNull();
  });

  test("the empty-field hint never overrides a real verdict", () => {
    expect(forLink(LINK, { status: "unavailable" }, true).noteKey).toBe(
      "gifts.game.profileUnavailable",
    );
  });

  test("a blocking verdict speaks through the alert, never twice through the note", () => {
    expect(forLink(LINK, { status: "not_found" }, true).noteKey).toBeNull();
  });
});
