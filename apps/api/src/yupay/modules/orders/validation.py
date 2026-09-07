"""Validate ``fulfillment_data`` against a product's ``required_fields`` schema.

Pure functions — no DB, no FastAPI. Easy to unit-test.
"""

from __future__ import annotations

import re
from typing import Any

from yupay.core.errors import ValidationError

# ``pattern`` (below) is admin-authored and matched inline, synchronously, with
# no timeout — a pathological pattern risks catastrophic backtracking and
# would block the event loop. ``catalog/schemas.py`` rejects the obviously
# dangerous constructs at write time, but as defense in depth we also cap the
# input length here: a short bound sharply limits how much work any
# backtracking regex engine can do, regardless of the pattern. Real values
# (player ids, emails, voucher codes) are always well under this.
_MAX_PATTERN_INPUT_LENGTH = 256


def _required_fields_schema(product: Any) -> list[dict[str, Any]]:
    fields = getattr(product, "required_fields", None) or []
    return list(fields)


def validate_fulfillment_data(
    *,
    product: Any,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Return a cleaned ``fulfillment_data`` dict or raise ``ValidationError``.

    - Every required field with ``required: true`` must be present and non-empty.
    - ``type`` is enforced (``text``/``email``/``number``/``select``).
    - ``pattern`` (regex) is enforced for text/email when supplied.
    - ``select`` values must be one of the declared options.
    - Unknown keys are **rejected**, not stripped: a key the product does not
      declare fails the whole call with ``reason: "extra"``. A dropped key is
      invisible, and on the machine API (whose README documents this) a typo'd
      field name would otherwise become an order delivered to nobody.
    """
    schema = _required_fields_schema(product)
    allowed_keys = {field["key"] for field in schema}
    cleaned: dict[str, Any] = {}

    for field in schema:
        key = field["key"]
        ftype = field.get("type", "text")
        required = field.get("required", True)
        raw = data.get(key)

        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if required:
                raise ValidationError(
                    f"field '{key}' is required",
                    extra={"field": key, "reason": "missing"},
                )
            continue

        if ftype == "number":
            try:
                cleaned[key] = float(raw) if not isinstance(raw, (int, float)) else raw
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"field '{key}' must be a number",
                    extra={"field": key, "reason": "type"},
                ) from exc
            continue

        if not isinstance(raw, str):
            raise ValidationError(
                f"field '{key}' must be a string",
                extra={"field": key, "reason": "type"},
            )

        value = raw.strip()

        if ftype == "select":
            options = {o["value"] for o in (field.get("options") or [])}
            if value not in options:
                raise ValidationError(
                    f"field '{key}' has unsupported value",
                    extra={"field": key, "reason": "option", "value": value},
                )
        else:
            pattern = field.get("pattern")
            if pattern:
                if len(value) > _MAX_PATTERN_INPUT_LENGTH:
                    raise ValidationError(
                        f"field '{key}' is too long",
                        extra={"field": key, "reason": "length"},
                    )
                try:
                    if re.fullmatch(pattern, value) is None:
                        raise ValidationError(
                            f"field '{key}' does not match the expected format",
                            extra={"field": key, "reason": "pattern"},
                        )
                except re.error as exc:
                    raise ValidationError(
                        f"field '{key}' has an invalid schema pattern",
                        extra={"field": key, "reason": "schema"},
                    ) from exc
            if ftype == "email" and "@" not in value:
                raise ValidationError(
                    f"field '{key}' must be a valid email",
                    extra={"field": key, "reason": "email"},
                )

        cleaned[key] = value

    # Reject unexpected keys explicitly. This protects fulfilment from
    # surprising payloads.
    extra_keys = set(data) - allowed_keys
    if extra_keys:
        raise ValidationError(
            f"unexpected fields: {sorted(extra_keys)}",
            extra={"reason": "extra", "keys": sorted(extra_keys)},
        )
    return cleaned


__all__ = ["validate_fulfillment_data"]
