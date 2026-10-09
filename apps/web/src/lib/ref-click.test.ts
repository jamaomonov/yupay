// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import { refFrom, reportRefClick, visitorId } from "./ref-click";

const LOC = { search: "?ref=moki", pathname: "/" };

describe("refFrom", () => {
  it("reads a partner code and upper-cases it", () => {
    expect(refFrom("?ref=moki")).toBe("MOKI");
    expect(refFrom("?utm=x&ref=Abc_1")).toBe("ABC_1");
  });
  it("ignores pages without one and junk values", () => {
    expect(refFrom("")).toBeNull();
    expect(refFrom("?ref=")).toBeNull();
    expect(refFrom("?ref=<script>")).toBeNull();
  });
});

describe("reportRefClick", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("posts the code, a stable visitor id and the path once a day", async () => {
    const send = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    expect(await reportRefClick("https://api.test", LOC, "2026-10-09", send)).toBe(true);
    expect(await reportRefClick("https://api.test", LOC, "2026-10-09", send)).toBe(false);
    expect(send).toHaveBeenCalledTimes(1);

    const [url, init] = send.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.test/api/v1/affiliate/clicks");
    const body = JSON.parse(init.body as string) as Record<string, string>; // a JSON string we sent
    expect(body).toEqual({ code: "MOKI", visitor_id: visitorId(), path: "/" });
    expect(init.keepalive).toBe(true);

    // A new day counts again, with the same visitor.
    expect(await reportRefClick("https://api.test", LOC, "2026-10-10", send)).toBe(true);
    const secondInit = (send.mock.calls[1] as [string, RequestInit])[1];
    // the body is the JSON string reportRefClick built
    const second = JSON.parse(secondInit.body as string) as { visitor_id: string };
    expect(second.visitor_id).toBe(body.visitor_id);
  });

  it("does nothing without ?ref", async () => {
    const send = vi.fn();
    expect(await reportRefClick("https://api.test", { search: "", pathname: "/" }, "d", send)).toBe(
      false,
    );
    expect(send).not.toHaveBeenCalled();
  });

  it("never throws when the network fails", async () => {
    const send = vi.fn().mockRejectedValue(new TypeError("offline"));
    expect(await reportRefClick("https://api.test", LOC, "2026-10-09", send)).toBe(false);
  });
});
