"""Tests for conservative OpenRouter TTS pricing classification."""

from __future__ import annotations

import pytest

from custom_components.openrouter_tts.models import FreeStatus
from custom_components.openrouter_tts.pricing import classify_free_status


def test_free_variant_with_positive_price_is_paid() -> None:
    """An ID suffix must never hide an explicit charge."""
    assert (
        classify_free_status(
            "provider/voice-model:free",
            {"prompt": "0", "completion": "0.00001"},
        )
        is FreeStatus.PAID
    )


def test_free_variant_with_complete_zero_prices_is_free() -> None:
    """A free variant remains free when all relevant prices confirm zero."""
    assert (
        classify_free_status(
            "provider/voice-model:free",
            {"prompt": "0", "completion": "0", "request": "0"},
        )
        is FreeStatus.FREE
    )


@pytest.mark.parametrize(
    "pricing",
    [
        {"prompt": "0", "completion": "0"},
        {"prompt": 0, "completion": 0, "request": "0.000"},
        {
            "prompt": "0E-12",
            "completion": "0.0",
            "input_character": "0",
            "output_audio": "0",
        },
    ],
)
def test_all_explicit_relevant_prices_are_free(pricing: dict[str, object]) -> None:
    """Decimal-equivalent zero values are classified without float rounding."""
    assert classify_free_status("provider/voice-model", pricing) is FreeStatus.FREE


@pytest.mark.parametrize(
    "pricing",
    [
        {"prompt": "0.000001", "completion": "0"},
        {"prompt": "0", "completion": "0.01"},
        {"prompt": "0", "completion": "0", "request": "1e-9"},
        {"prompt": "0", "completion": "0", "output_audio": 1},
    ],
)
def test_any_positive_relevant_price_is_paid(pricing: dict[str, object]) -> None:
    """A partial charge makes the model paid even when other fields are zero."""
    assert classify_free_status("provider/voice-model", pricing) is FreeStatus.PAID


def test_unknown_future_positive_price_key_is_paid() -> None:
    """A future price field cannot hide a charge from the conservative classifier."""
    assert (
        classify_free_status(
            "provider/voice-model",
            {"prompt": "0", "completion": "0", "future_speech_charge": "0.1"},
        )
        is FreeStatus.PAID
    )


def test_unknown_future_ambiguous_price_key_is_unknown() -> None:
    """An unfamiliar null price cannot be assumed irrelevant to TTS."""
    assert (
        classify_free_status(
            "provider/voice-model",
            {"prompt": "0", "completion": "0", "future_speech_charge": None},
        )
        is FreeStatus.UNKNOWN
    )


@pytest.mark.parametrize(
    "pricing",
    [
        {"prompt": "0"},
        {"completion": "0"},
        {"prompt": "0", "completion": None},
        {"prompt": None, "completion": "0"},
        {"prompt": "not-a-number", "completion": "0"},
        {"prompt": "NaN", "completion": "0"},
        {"prompt": "Infinity", "completion": "0"},
        {"prompt": "-0.01", "completion": "0"},
    ],
)
def test_incomplete_or_ambiguous_prices_are_unknown(
    pricing: dict[str, object],
) -> None:
    """Missing, null, invalid, non-finite, and negative values are not guessed."""
    assert classify_free_status("provider/voice-model", pricing) is FreeStatus.UNKNOWN


@pytest.mark.parametrize("pricing", [None, {}, {"request": "0"}])
def test_absent_pricing_is_unknown(
    pricing: dict[str, object] | None,
) -> None:
    """No catalog price data cannot prove that TTS is free."""
    assert classify_free_status("provider/voice-model", pricing) is FreeStatus.UNKNOWN


def test_conditional_price_override_is_unknown() -> None:
    """A conditional override prevents a top-level zero-price guarantee."""
    pricing: dict[str, object] = {
        "prompt": "0",
        "completion": "0",
        "overrides": [
            {"condition": {"provider": "example"}, "prompt": "0"},
        ],
    }

    assert classify_free_status("provider/voice-model", pricing) is FreeStatus.UNKNOWN


@pytest.mark.parametrize(
    "pricing",
    [
        None,
        {"prompt": "0"},
        {"prompt": "0", "completion": None},
        {
            "prompt": "0",
            "completion": "0",
            "overrides": [{"condition": {"provider": "example"}}],
        },
    ],
)
def test_free_variant_does_not_override_unknown_price_metadata(
    pricing: dict[str, object] | None,
) -> None:
    """The :free marker cannot make missing or conditional metadata certain."""
    assert (
        classify_free_status("provider/voice-model:free", pricing) is FreeStatus.UNKNOWN
    )
