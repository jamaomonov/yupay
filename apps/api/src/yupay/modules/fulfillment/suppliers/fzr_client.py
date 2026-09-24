"""HTTP client for FazerCards' public API v2 (api.fzr.cards).

Almost nothing is here, and that is the point: FazerCards publishes the panel
v2 protocol that ``panel_client`` already speaks. Verified against their live
API and their v2 documentation on 2026-09-24 — every ``/api/v2`` path this
integration calls exists under the same name, with the same ``X-API-Key``
header, the same ``{ok, …}`` envelope and the same cursor paging.

What is worth writing down is where they differ from NOVA, because each
difference is somewhere an assumption carried across would be wrong:

* **A reused ``Idempotency-Key`` replays** — their documentation says so and,
  unlike NOVA's, it is true. Verified 2026-09-24: one gift-card create sent
  twice under a single key answered ``200`` both times with the same
  ``ord-1549395``, and the balance moved once. This is what makes a retry of
  a create safe here where it is not safe on NOVA, and it is why ``fzr`` is
  absent from ``fulfillment.service.KEY_BURNED_ON_USE``.

  A 409 is still graded undecided rather than as a free retry: that branch
  now describes a vendor behaving unlike itself, which is exactly when
  caution is worth its cost.
* **Rate limits are published and per-category**: 60 order creates a minute,
  120 status polls, 120 catalogue reads, 30 account reads, each on its own
  sliding window keyed by the API key, and only the category you exceed
  returns 429. A 429 carries ``Retry-After``.
* **It is a subscription product.** An expired plan answers 403 with
  ``code: "subscription_inactive"`` on every product route, and the Steam
  wallet rebate is tiered (bronze ≈2.5%, silver ≈3%, gold 3.55%).
* **No Fragment API.** Telegram Stars and Premium are ordinary v2 endpoints
  (``/api/v2/telegram/stars/buy``). They are deliberately not wired up: on
  2026-09-24 FazerCards quoted 0.0152625 per Star against NOVA's 0.015225 and
  was dearer on all three Premium terms, so routing Telegram here would cost
  us money. Add them if that inverts.
"""

from __future__ import annotations

from typing import Any, ClassVar

from yupay.modules.fulfillment.suppliers.panel_client import (
    PanelClient,
    PanelError,
    PanelUnavailableError,
    PanelValidation,
)


class FzrError(PanelError):
    """FazerCards refused the call (transport fine, business failure)."""


class FzrUnavailableError(PanelUnavailableError):
    """FazerCards could not be reached at all (network error, timeout, DNS)."""


#: Their machine-readable code for "your subscription lapsed". Worth a name
#: because it is the one refusal an operator can fix in a minute, and it looks
#: identical to every other 403 without it.
SUBSCRIPTION_INACTIVE = "subscription_inactive"

#: One ``POST /topups/validate-id`` answer. The platform shape.
FzrValidation = PanelValidation


class FzrClient(PanelClient):
    """Thin async client over the panel v2 endpoints this integration uses.

    Everything is inherited. The class exists to bind the slug and the two
    exception types, so ``except FzrError`` catches FazerCards and nothing
    else, and every log event reads ``fzr.*``.
    """

    slug: ClassVar[str] = "fzr"
    error_cls: ClassVar[type[PanelError]] = FzrError
    unavailable_cls: ClassVar[type[PanelUnavailableError]] = FzrUnavailableError

    async def get_subscription(self) -> dict[str, Any]:
        """``GET /subscription`` — plan, expiry and whether it is still active.

        The one endpoint with no NOVA counterpart that this integration needs:
        catalogue access here expires with the plan, so "can we still route to
        this supplier tomorrow" is a question only this call answers.
        """
        return await self._request("GET", "/api/v2/subscription")


__all__ = [
    "SUBSCRIPTION_INACTIVE",
    "FzrClient",
    "FzrError",
    "FzrUnavailableError",
    "FzrValidation",
]
