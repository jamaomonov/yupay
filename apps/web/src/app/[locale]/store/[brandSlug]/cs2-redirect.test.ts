import { expect, it, vi } from "vitest";

const redirected = vi.hoisted(() => ({ to: null as string | null }));

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("notFound");
  },
  permanentRedirect: (to: string) => {
    redirected.to = to;
    throw new Error("redirect");
  },
}));

it("sends the CS2 skins brand's store page to the skins market", async () => {
  const { default: BrandPage } = await import("./page");
  await expect(
    BrandPage({ params: Promise.resolve({ locale: "ru", brandSlug: "cs2-skins" }) }),
  ).rejects.toThrow("redirect");
  expect(redirected.to).toBe("/skins");
});
