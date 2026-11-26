"""Which failed status reads count as noise — see ``fulfillment.check_noise``."""

from __future__ import annotations

from yupay.modules.fulfillment.check_noise import is_transient_check_failure
from yupay.modules.fulfillment.suppliers.base import FulfillerError, MoneyOutcome
from yupay.modules.fulfillment.suppliers.fzr_client import FzrError, FzrUnavailableError


def _wrapped(cause: Exception) -> FulfillerError:
    """The adapters re-raise the client's error; the cause is what counts."""
    exc = FulfillerError(str(cause), money_outcome=MoneyOutcome.UNKNOWN)
    exc.__cause__ = cause
    return exc


def test_a_throttle_is_transient() -> None:
    assert is_transient_check_failure(_wrapped(FzrError("Повторите через 9 с.", status=429)))


def test_an_unreachable_supplier_is_transient() -> None:
    assert is_transient_check_failure(_wrapped(FzrUnavailableError("ConnectTimeout")))


def test_a_real_answer_is_not() -> None:
    assert not is_transient_check_failure(_wrapped(FzrError("order not found", status=404)))


def test_an_error_with_no_panel_cause_is_not() -> None:
    assert not is_transient_check_failure(
        FulfillerError("FZR_API_KEY is not configured", money_outcome=MoneyOutcome.UNKNOWN)
    )


def test_level_up_packs_fail_quietly() -> None:
    from yupay.modules.fulfillment.check_noise import is_quiet_failure_sku

    assert is_quiet_failure_sku("freefire_cis-level-up-6")
    assert is_quiet_failure_sku("freefire_cis-level-up-30")
    assert not is_quiet_failure_sku("freefire_cis-100-diamonds")
    assert not is_quiet_failure_sku(None)
