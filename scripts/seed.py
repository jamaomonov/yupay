"""Dev-only seed script. Populates a small catalog so the storefront has data to show.

Run via ``make seed`` once the catalog module is implemented. Until then this is a no-op.
"""

from __future__ import annotations


def main() -> int:
    """Seed dev data."""
    print("[seed] catalog module not yet implemented; nothing to seed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
