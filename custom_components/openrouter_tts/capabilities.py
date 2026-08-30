"""Extensible provider capability adapters for incomplete catalog metadata."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .const import FISH_AUDIO_S21_PRO_FREE_MODEL_ID, PROVIDER_DEFAULT_VOICE_ID


@dataclass(frozen=True, slots=True)
class SpeedCapabilityAdapter:
    """One documented rule for models whose catalog omits ``speed``."""

    name: str
    matches: Callable[[str, Sequence[str]], bool]


def _is_microsoft_mai_voice(model_id: str, voices: Sequence[str]) -> bool:
    """Match Microsoft's documented Azure MAI Voice family by provider and voice IDs."""
    return model_id.casefold().startswith("microsoft/") and any(
        voice.casefold().endswith(":mai-voice-2") for voice in voices
    )


_SPEED_ADAPTERS = (
    SpeedCapabilityAdapter("microsoft_mai_voice_2", _is_microsoft_mai_voice),
)


@dataclass(frozen=True, slots=True)
class ProviderDefaultVoiceAdapter:
    """One fail-closed rule for a documented provider-default voice."""

    name: str
    model_id: str

    def matches(self, raw_model: Mapping[str, Any]) -> bool:
        """Match only an exact model whose catalog explicitly reports null voices."""
        return (
            raw_model.get("id") == self.model_id
            and "supported_voices" in raw_model
            and raw_model["supported_voices"] is None
        )


_PROVIDER_DEFAULT_VOICE_ADAPTERS = (
    ProviderDefaultVoiceAdapter(
        "fish_audio_s21_pro_free_provider_default",
        FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
    ),
)


def supports_speed(
    model_id: str,
    supported_parameters: frozenset[str],
    voices: Sequence[str],
) -> bool:
    """Return true only for explicit catalog support or a documented adapter."""
    if "speed" in supported_parameters:
        return True
    return any(adapter.matches(model_id, voices) for adapter in _SPEED_ADAPTERS)


def supports_provider_default_voice(raw_model: Mapping[str, Any]) -> bool:
    """Return true only for an exact, audited null-voice catalog exception."""
    return any(
        adapter.matches(raw_model) for adapter in _PROVIDER_DEFAULT_VOICE_ADAPTERS
    )


def is_provider_default_voice_selection(model_id: str, voice: str) -> bool:
    """Validate the internal selection against the exact adapter registry."""
    return voice == PROVIDER_DEFAULT_VOICE_ID and any(
        adapter.model_id == model_id for adapter in _PROVIDER_DEFAULT_VOICE_ADAPTERS
    )
