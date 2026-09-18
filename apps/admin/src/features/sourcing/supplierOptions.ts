/** Supplier option lists shared by both sourcing screens — used to be
 *  copy-pasted verbatim between `SourcingPage.tsx` and
 *  `BrandSourcingPage.tsx` (same folder, same list, two places to forget to
 *  update). One definition here, imported by both. */

import { FULFILMENT_ROUTES, type FulfilmentRoute } from "@/features/integrations/types";

/** Suppliers offerable as an explicit `force_supplier` target — derived
 *  from the shared route table so a newly integrated supplier shows up
 *  without a second edit. Includes the dev-only `mock` route: the
 *  single-SKU editor (`SourcingPage`) forces one SKU at a time, where an
 *  operator routing a single dev/test SKU to the stub is a small, visible,
 *  easily-undone choice. */
export const SUPPLIER_OPTIONS: FulfilmentRoute[] = FULFILMENT_ROUTES.filter(
  (r) => r.external || r.slug === "mock",
);

/** Same list with the dev stub dropped. `BrandSourcingPage`'s bulk switch
 *  can move an entire brand — hundreds of SKUs — in one click; `set_rule`
 *  does not block `mock` as a target, so leaving it in this list means
 *  "select all → Mock (dev) → Применить" silently routes a production
 *  brand to a supplier that fulfils nothing. Dropped here rather than
 *  gated behind a dev-only check: the bulk screen has no legitimate dev use
 *  for `mock` (unlike the single-SKU editor, it's not a one-off, one-SKU
 *  test) — there is no case where offering it here is the right call. */
export const BULK_SUPPLIER_OPTIONS: FulfilmentRoute[] = SUPPLIER_OPTIONS.filter(
  (r) => r.slug !== "mock",
);
