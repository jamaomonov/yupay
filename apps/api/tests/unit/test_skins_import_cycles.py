"""Each skins purchase module imports cold, on its own (plan 3a/3b).

A cycle through ``fulfillment.suppliers`` (whose package imports ``waxpeer_skins``) only
shows when a module is the *first* thing imported — the full suite happened to import in an
order that hid one. A fresh interpreter per module is the only honest check.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

MODULES = [
    "yupay.modules.skins.listings",
    "yupay.modules.skins.checkout",
    "yupay.modules.skins.tradelink",
    "yupay.modules.skins.trade_view",
    "yupay.modules.fulfillment.suppliers.waxpeer_skins",
    "yupay.modules.fulfillment.suppliers.waxpeer_trades",
    "yupay.modules.fulfillment.skin_sweeps",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_cold(module: str) -> None:
    done = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-800:]
