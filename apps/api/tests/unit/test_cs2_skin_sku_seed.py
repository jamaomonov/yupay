"""The CS2 skin SKU's amount window must admit every price the pricing rules produce.

``orders`` refuses a line under the SKU's ``min_amount_usd``; a floor above the pricing
floor leaves the cheapest skins on sale and unbuyable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from yupay.modules.skins.pricing import DEFAULT_RULES

SEED_PATH = Path(__file__).resolve().parents[4] / "scripts" / "seed" / "2026-09-29_cs2_skin_sku.py"


def _load_seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cs2_skin_sku_seed", SEED_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_sku_floor_is_not_above_the_pricing_floor() -> None:
    seed = _load_seed()
    floor = seed.SKU_MIN_AMOUNT_USD
    assert floor <= DEFAULT_RULES.price_floor_usd
