import { beforeEach, expect, it, vi } from "vitest";

import { switchSkusChunked } from "./bulkSwitch";
import { MAX_BULK_SKU_IDS } from "./types";

import { apiPut } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiPut: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      public statusText: string,
      public body: unknown,
    ) {
      super(`${status.toString()} ${statusText}`);
    }
  },
  formatApiError: (err: { message: string }) => err.message,
}));

const mockedApiPut = vi.mocked(apiPut);

beforeEach(() => {
  mockedApiPut.mockReset();
});

it("sends one request when the selection fits under the cap", async () => {
  mockedApiPut.mockResolvedValue({
    items: [{ sku_id: "a", ok: true, error: null }],
  });

  const out = await switchSkusChunked(["a"], "force_supplier", "nova");

  expect(mockedApiPut).toHaveBeenCalledTimes(1);
  expect(out.items).toEqual([{ sku_id: "a", ok: true, error: null }]);
});

it("chunks a selection above MAX_BULK_SKU_IDS into multiple requests and merges the results", async () => {
  const skuIds = Array.from({ length: MAX_BULK_SKU_IDS + 50 }, (_, i) => `sku-${i.toString()}`);
  mockedApiPut.mockImplementation((_url, body) => {
    const b = body as { sku_ids: string[] };
    return Promise.resolve({
      items: b.sku_ids.map((sku_id) => ({ sku_id, ok: true, error: null })),
    });
  });

  const out = await switchSkusChunked(skuIds, "auto", null);

  expect(mockedApiPut).toHaveBeenCalledTimes(2);
  const firstBody = mockedApiPut.mock.calls[0]?.[1] as { sku_ids: string[] };
  const secondBody = mockedApiPut.mock.calls[1]?.[1] as { sku_ids: string[] };
  expect(firstBody.sku_ids).toHaveLength(MAX_BULK_SKU_IDS);
  expect(secondBody.sku_ids).toHaveLength(50);
  expect(out.items).toHaveLength(skuIds.length);
  expect(out.items.map((i) => i.sku_id)).toEqual(skuIds);
});

it("mints a fresh Idempotency-Key per chunk, never reusing one", async () => {
  const skuIds = Array.from({ length: MAX_BULK_SKU_IDS + 1 }, (_, i) => `sku-${i.toString()}`);
  mockedApiPut.mockResolvedValue({ items: [] });

  await switchSkusChunked(skuIds, "force_inventory", null);

  const key1 = (mockedApiPut.mock.calls[0]?.[2] as Record<string, string>)["Idempotency-Key"];
  const key2 = (mockedApiPut.mock.calls[1]?.[2] as Record<string, string>)["Idempotency-Key"];
  expect(key1).toBeTruthy();
  expect(key2).toBeTruthy();
  expect(key1).not.toEqual(key2);
});

it("never reuses a key across a retry of the same selection", async () => {
  mockedApiPut.mockResolvedValue({ items: [{ sku_id: "a", ok: true, error: null }] });

  await switchSkusChunked(["a"], "force_supplier", "nova");
  await switchSkusChunked(["a"], "force_supplier", "nova");

  const key1 = (mockedApiPut.mock.calls[0]?.[2] as Record<string, string>)["Idempotency-Key"];
  const key2 = (mockedApiPut.mock.calls[1]?.[2] as Record<string, string>)["Idempotency-Key"];
  expect(key1).not.toEqual(key2);
});

it("turns a whole-chunk transport failure into per-SKU failures without aborting later chunks", async () => {
  const skuIds = Array.from({ length: MAX_BULK_SKU_IDS + 1 }, (_, i) => `sku-${i.toString()}`);
  let call = 0;
  mockedApiPut.mockImplementation((_url, body) => {
    call += 1;
    const b = body as { sku_ids: string[] };
    if (call === 1) {
      return Promise.reject(new Error("network down"));
    }
    return Promise.resolve({
      items: b.sku_ids.map((sku_id) => ({ sku_id, ok: true, error: null })),
    });
  });

  const out = await switchSkusChunked(skuIds, "manual", null);

  expect(mockedApiPut).toHaveBeenCalledTimes(2);
  const firstChunkResults = out.items.slice(0, MAX_BULK_SKU_IDS);
  const secondChunkResults = out.items.slice(MAX_BULK_SKU_IDS);
  expect(firstChunkResults.every((i) => !i.ok)).toBe(true);
  expect(secondChunkResults.every((i) => i.ok)).toBe(true);
});
