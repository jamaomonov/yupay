/** Mirrors `SavedSegmentOut` in apps/api/src/yupay/modules/admin/schemas.py. */

export interface SavedSegment {
  id: string;
  name: string;
  path: string;
  params: Record<string, string | number | boolean | null>;
  created_at: string;
}

export interface SavedSegmentList {
  items: SavedSegment[];
}

export interface SavedSegmentIn {
  name: string;
  path: string;
  params: Record<string, string | number | boolean | null>;
}

export function buildSegmentHref(segment: SavedSegment): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(segment.params)) {
    if (v === null || v === undefined) continue;
    usp.set(k, String(v));
  }
  const qs = usp.toString();
  return qs ? `${segment.path}?${qs}` : segment.path;
}
