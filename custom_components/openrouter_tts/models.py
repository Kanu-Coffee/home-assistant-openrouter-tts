"""Immutable data models used by OpenRouter TTS."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class FreeStatus(StrEnum):
    """Conservative pricing classification."""

    FREE = "free"
    PAID = "paid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AudioCapabilities:
    """Audio response hints supplied by catalog metadata."""

    raw_pcm: bool | None = None
    sample_rate: int = 24_000
    channels: int = 1
    sample_width: int = 2


@dataclass(frozen=True, slots=True)
class TTSModel:
    """A catalog model proven to support speech output and a safe voice mode."""

    model_id: str
    name: str
    voices: tuple[str, ...]
    free_status: FreeStatus
    pricing: Mapping[str, str | int | float | None] = field(default_factory=dict)
    supported_parameters: frozenset[str] = frozenset()
    audio: AudioCapabilities = AudioCapabilities()
    available: bool = True
    unavailable_voices: frozenset[str] = frozenset()
    speed_supported: bool = False
    provider_default_voice: bool = False

    @property
    def supports_speed(self) -> bool:
        """Return whether catalog metadata explicitly advertises speed."""
        return self.speed_supported or "speed" in self.supported_parameters

    @property
    def label(self) -> str:
        """Return an English display label; flows localize the suffix."""
        suffix = " (Free)" if self.free_status is FreeStatus.FREE else ""
        unavailable = " (Unavailable; saved)" if not self.available else ""
        return f"{self.name}{suffix}{unavailable}"

    def with_availability(self, available: bool) -> TTSModel:
        """Return a copy with updated availability."""
        return TTSModel(
            model_id=self.model_id,
            name=self.name,
            voices=self.voices,
            free_status=self.free_status,
            pricing=dict(self.pricing),
            supported_parameters=self.supported_parameters,
            audio=self.audio,
            available=available,
            unavailable_voices=self.unavailable_voices,
            speed_supported=self.speed_supported,
            provider_default_voice=self.provider_default_voice,
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize non-secret catalog data for persistent stale fallback."""
        return {
            "model_id": self.model_id,
            "name": self.name,
            "voices": list(self.voices),
            "free_status": self.free_status.value,
            "pricing": dict(self.pricing),
            "supported_parameters": sorted(self.supported_parameters),
            "audio": {
                "raw_pcm": self.audio.raw_pcm,
                "sample_rate": self.audio.sample_rate,
                "channels": self.audio.channels,
                "sample_width": self.audio.sample_width,
            },
            "available": self.available,
            "unavailable_voices": sorted(self.unavailable_voices),
            "speed_supported": self.speed_supported,
            "provider_default_voice": self.provider_default_voice,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TTSModel:
        """Deserialize validated-enough local cache data."""
        raw_audio = value.get("audio")
        audio: Mapping[str, Any] = raw_audio if isinstance(raw_audio, Mapping) else {}
        raw_pricing = value.get("pricing")
        pricing: Mapping[str, Any] = (
            raw_pricing if isinstance(raw_pricing, Mapping) else {}
        )
        return cls(
            model_id=str(value["model_id"]),
            name=str(value["name"]),
            voices=tuple(str(item) for item in value.get("voices", [])),
            free_status=FreeStatus(str(value.get("free_status", FreeStatus.UNKNOWN))),
            pricing={str(key): item for key, item in pricing.items()},
            supported_parameters=frozenset(
                str(item) for item in value.get("supported_parameters", [])
            ),
            audio=AudioCapabilities(
                raw_pcm=audio.get("raw_pcm"),
                sample_rate=int(audio.get("sample_rate", 24_000)),
                channels=int(audio.get("channels", 1)),
                sample_width=int(audio.get("sample_width", 2)),
            ),
            available=bool(value.get("available", True)),
            unavailable_voices=frozenset(
                str(item) for item in value.get("unavailable_voices", [])
            ),
            speed_supported=bool(value.get("speed_supported", False)),
            provider_default_voice=bool(value.get("provider_default_voice", False)),
        )


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """One successful or cached model catalog."""

    models: tuple[TTSModel, ...]
    fetched_at: datetime
    stale: bool = False

    def by_id(self, model_id: str) -> TTSModel | None:
        """Look up a model by exact OpenRouter ID."""
        return next(
            (model for model in self.models if model.model_id == model_id), None
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize the snapshot without secrets."""
        return {
            "fetched_at": self.fetched_at.astimezone(UTC).isoformat(),
            "models": [model.as_dict() for model in self.models],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CatalogSnapshot:
        """Deserialize a persisted snapshot."""
        raw_time = value.get("fetched_at")
        fetched_at = datetime.fromisoformat(str(raw_time))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        raw_models = value.get("models", [])
        if not isinstance(raw_models, list):
            raise TypeError("catalog models must be a list")
        return cls(
            models=tuple(
                TTSModel.from_dict(item)
                for item in raw_models
                if isinstance(item, Mapping)
            ),
            fetched_at=fetched_at,
            stale=True,
        )


@dataclass(frozen=True, slots=True)
class AudioResult:
    """Validated audio bytes returned by OpenRouter."""

    data: bytes
    extension: str
    content_type: str
    generation_id: str | None = None
