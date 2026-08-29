"""Extensible provider capability adapters for incomplete catalog metadata."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


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


def supports_speed(
    model_id: str,
    supported_parameters: frozenset[str],
    voices: Sequence[str],
) -> bool:
    """Return true only for explicit catalog support or a documented adapter."""
    if "speed" in supported_parameters:
        return True
    return any(adapter.matches(model_id, voices) for adapter in _SPEED_ADAPTERS)
