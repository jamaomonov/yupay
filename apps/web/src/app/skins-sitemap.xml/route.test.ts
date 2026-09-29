import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

import { apiGet } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiGet: vi.fn() }));
const mockedApiGet = vi.mocked(apiGet);

describe("GET /skins-sitemap.xml", () => {
  beforeEach(() => {
    mockedApiGet.mockReset();
    vi.stubEnv("SKINS_ENABLED", "true");
  });

  it("indexes one file per 5000 items and the landing pages", async () => {
    mockedApiGet.mockResolvedValue({ items: ["a"], total: 12_001 });
    const body = await (await GET()).text();
    expect(body).toContain("https://yupay.uz/skins-sitemap/0.xml");
    expect(body).toContain("https://yupay.uz/skins-sitemap/2.xml");
    expect(body).not.toContain("https://yupay.uz/skins-sitemap/3.xml");
    expect(body).toContain("https://yupay.uz/skins-sitemap/landings.xml");
  });

  it("is not there while skins are off", async () => {
    vi.stubEnv("SKINS_ENABLED", "false");
    expect((await GET()).status).toBe(404);
  });
});
