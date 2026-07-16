"""FormField.check descriptor parsing (storefront player-check opt-in)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError
from yupay.modules.catalog.schemas import FieldCheck, FormField


def _base_field(**extra: object) -> dict[str, object]:
    return {"key": "player_id", "label": {"ru": "ID"}, "type": "text", **extra}


def test_field_without_check_defaults_to_none() -> None:
    field = FormField.model_validate(_base_field())
    assert field.check is None


def test_field_with_g2b_check_parses() -> None:
    field = FormField.model_validate(
        _base_field(check={"provider": "g2b", "server_field": "server"})
    )
    assert field.check == FieldCheck(provider="g2b", server_field="server")


def test_check_server_field_is_optional() -> None:
    field = FormField.model_validate(_base_field(check={"provider": "g2b"}))
    assert field.check is not None
    assert field.check.server_field is None


def test_unknown_provider_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        FormField.model_validate(_base_field(check={"provider": "nope"}))


def test_extra_key_in_check_forbidden() -> None:
    with pytest.raises(PydanticValidationError):
        FormField.model_validate(_base_field(check={"provider": "g2b", "wat": 1}))
