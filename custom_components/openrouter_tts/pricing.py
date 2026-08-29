"""Conservative, deterministic TTS price classification."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from .models import FreeStatus

# OpenRouter currently represents TTS character/audio pricing using prompt and
# completion. Every additional top-level price field is also treated as relevant:
# an unknown future charge must fail closed instead of being silently ignored.
_REQUIRED_PRICE_KEYS = frozenset({"prompt", "completion"})


def classify_free_status(
    model_id: str,
    pricing: Mapping[str, object] | None,
) -> FreeStatus:
    """Classify a model without guessing when pricing metadata is incomplete.

    The official ``:free`` variant is a strong signal, but it does not override
    contradictory or incomplete price metadata. Every required TTS price and
    every relevant optional price that is present must be an explicit, finite
    zero. Any positive relevant amount means paid. Missing, null, negative,
    non-numeric, NaN, or infinite values mean unknown.
    """
    official_free_variant = model_id.casefold().endswith(":free")
    if not isinstance(pricing, Mapping):
        return FreeStatus.UNKNOWN

    relevant_keys = _REQUIRED_PRICE_KEYS | {
        key for key in pricing if key != "overrides"
    }
    unknown = any(key not in pricing or pricing[key] is None for key in relevant_keys)
    if pricing.get("overrides"):
        # Conditional endpoint pricing cannot be proven free from the top-level
        # values alone.
        unknown = True

    for key in relevant_keys:
        raw_value = pricing.get(key)
        if raw_value is None or isinstance(raw_value, bool):
            unknown = True
            continue
        try:
            amount = Decimal(str(raw_value))
        except (InvalidOperation, ValueError):
            unknown = True
            continue
        if not amount.is_finite() or amount < 0:
            unknown = True
            continue
        if amount > 0:
            return FreeStatus.PAID

    if official_free_variant and unknown:
        return FreeStatus.UNKNOWN
    return FreeStatus.UNKNOWN if unknown else FreeStatus.FREE
