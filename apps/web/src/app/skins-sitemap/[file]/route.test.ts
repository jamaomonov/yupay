import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

import { apiGet, apiGetOrNull } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiGet: vi.fn(), apiGetOrNull: vi.fn() }));
const mockedApiGet = vi.mocked(apiGet);
const mockedFacets = vi.mocked(apiGetOrNull);

const call = (file: string) =>
  GET(new Request("https://yupay.uz"), { params: Promise.resolve({ file }) });

describe("GET /skins-sitemap/<n>.xml", () => {
  beforeEach(() => {
    mockedApiGet.mockReset();
    vi.stubEnv("SKINS_ENABLED", "true");
  });

  it("lists that slice of item pages", async () => {
    mockedApiGet.mockResolvedValue({ items: ["ak-47-redline-field-tested"], total: 12_001 });
    const res = await call("2.xml");
    expect(res.headers.get("Content-Type")).toContain("xml");
    expect(await res.text()).toContain(
      "<loc>https://yupay.uz/skins/ak-47-redline-field-tested</loc>",
    );
    expect(mockedApiGet.mock.calls[0]?.[0]).toBe("/skins/seo/slugs?offset=10000&limit=5000");
  });

  it("404s a name that is not a file", async () => {
    expect((await call("x.xml")).status).toBe(404);
    expect((await call("-1.xml")).status).toBe(404);
    expect((await call("1")).status).toBe(404);
  });

  it("404s a slice past the end", async () => {
    mockedApiGet.mockResolvedValue({ items: [], total: 10 });
    expect((await call("3.xml")).status).toBe(404);
  });

  it("lists the category and weapon landing pages", async () => {
    mockedFacets.mockResolvedValue({
      categories: [{ value: "knives", count: 3505 }],
      weapons: [{ value: "AK-47", count: 594 }],
      exteriors: [],
      rarities: [],
    });
    const body = await (await call("landings.xml")).text();
    expect(body).toContain("<loc>https://yupay.uz/skins/category/knives</loc>");
    expect(body).toContain("<loc>https://yupay.uz/en/skins/weapon/ak-47</loc>");
  });
});
