"""``SkuId``'s spelling normalisation — the shipped 500 this pins.

``UUID()`` takes four spellings; Postgres takes two. Normalise, or 500.

A .NET client formatting ids with ``Guid.ToString("B")`` sends the braced
form. Before the schema returned ``str(UUID(value))`` that reached
``where(Sku.id == "{0198…}")``, raised ``DataError``, and — with no handler
registered for ``DBAPIError`` — came back as Starlette's plain-text 500, from
the very validator whose docstring promised it could not. Our own README
calls a 500 safe to retry, so the client would have retried forever.

This used to be pinned end to end, over the live app, by
``test_merchant_validate.py::test_every_uuid_spelling_python_accepts_reaches_postgres``
(against ``POST /merchant/v1/validate/player``'s now-removed ``sku_id``
field). ``SkuId`` is still live on ``MerchantOrderCreateIn.sku_id``, so the
normalisation still ships and still needs a test; this is that test's new
home, moved down to the annotated type itself so it needs no database.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter
from yupay.modules.merchants.machine_schemas import SkuId

_CANONICAL = "0198c3cb-6a0f-7b31-9c22-2f7a1e5d4b08"

_adapter: TypeAdapter[str] = TypeAdapter(SkuId)


@pytest.mark.parametrize(
    "spelling",
    ["braced", "urn", "undashed", "upper"],
)
def test_every_uuid_spelling_python_accepts_normalises_to_the_canonical_form(
    spelling: str,
) -> None:
    written = {
        "braced": "{" + _CANONICAL + "}",
        "urn": f"urn:uuid:{_CANONICAL}",
        "undashed": _CANONICAL.replace("-", ""),
        "upper": _CANONICAL.upper(),
    }[spelling]

    assert _adapter.validate_python(written) == _CANONICAL


def test_a_non_uuid_is_refused_by_name() -> None:
    """The message names the field: the module README quotes it verbatim as
    the published example, and both id fields on this contract share it."""
    with pytest.raises(ValueError, match="sku_id must be a UUID"):
        _adapter.validate_python("not-a-uuid")
