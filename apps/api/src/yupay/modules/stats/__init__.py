"""``stats`` — cross-module aggregates for the admin Dashboard.

This module doesn't own any tables. It reads from ``orders``, ``payments``,
``fulfillment_tasks``, ``inventory_codes`` and builds a single dashboard
payload so the SPA makes one round-trip instead of five. Cheap-enough for
the volumes we're at (skeleton). When count + group-by aggregates start
hurting we'll add a nightly rollup table; not yet.

Public surface: :mod:`yupay.modules.stats.api`.
"""
