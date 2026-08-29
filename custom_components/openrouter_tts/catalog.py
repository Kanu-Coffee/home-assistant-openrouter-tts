"""OpenRouter speech model parsing and stale-cache coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .capabilities import supports_speed
from .const import CATALOG_TTL, STORAGE_KEY_PREFIX, STORAGE_VERSION
from .exceptions import (
    InvalidCatalogError,
    ModelVoiceMismatchError,
    NetworkError,
    NoFreeModelsError,
    RateLimitError,
    ServerError,
)
from .models import AudioCapabilities, CatalogSnapshot, FreeStatus, TTSModel
from .pricing import classify_free_status


class CatalogClient(Protocol):
    """Small protocol so cache behavior is independently testable."""

    async def async_fetch_catalog(self) -> tuple[TTSModel, ...]:
        """Fetch and parse a fresh catalog."""


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(
        dict.fromkeys(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    )


def _has_speech_output(raw_model: Mapping[str, Any]) -> bool:
    architecture = raw_model.get("architecture")
    if not isinstance(architecture, Mapping):
        return False
    output_modalities = {
        item.casefold()
        for item in _string_sequence(architecture.get("output_modalities"))
    }
    modality = str(architecture.get("modality", "")).casefold()
    input_modalities = {
        item.casefold()
        for item in _string_sequence(architecture.get("input_modalities"))
    }
    speech_output = "speech" in output_modalities or modality.endswith("->speech")
    text_input = "text" in input_modalities or modality.startswith("text->")
    return speech_output and text_input


def _audio_capabilities(raw_model: Mapping[str, Any]) -> AudioCapabilities:
    """Read only explicit format metadata; never infer from a model name."""
    raw_audio = raw_model.get("audio")
    audio = raw_audio if isinstance(raw_audio, Mapping) else {}
    raw_format = audio.get("format", raw_model.get("output_format"))
    normalized_format = str(raw_format).casefold() if raw_format is not None else ""
    explicit_pcm = audio.get("raw_pcm")
    raw_pcm = explicit_pcm if isinstance(explicit_pcm, bool) else None
    if normalized_format in {"pcm", "pcm16", "l16", "raw"}:
        raw_pcm = True

    def _bounded_int(key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(audio.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if low <= value <= high else default

    return AudioCapabilities(
        raw_pcm=raw_pcm,
        sample_rate=_bounded_int("sample_rate", 24_000, 8_000, 192_000),
        channels=_bounded_int("channels", 1, 1, 8),
        sample_width=_bounded_int("sample_width", 2, 1, 4),
    )


def parse_catalog_payload(payload: Mapping[str, Any]) -> tuple[TTSModel, ...]:
    """Return only models with explicit speech output and non-empty voices."""
    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        raise InvalidCatalogError("OpenRouter returned a catalog without a model list")

    models: list[TTSModel] = []
    seen_ids: set[str] = set()
    for item in raw_models:
        if not isinstance(item, Mapping) or not _has_speech_output(item):
            continue
        model_id = str(item.get("id", "")).strip()
        voices = _string_sequence(item.get("supported_voices"))
        if not model_id or model_id in seen_ids or not voices:
            continue
        seen_ids.add(model_id)
        raw_pricing = item.get("pricing")
        pricing = (
            {str(key): value for key, value in raw_pricing.items()}
            if isinstance(raw_pricing, Mapping)
            else {}
        )
        supported_parameters = frozenset(
            _string_sequence(item.get("supported_parameters"))
        )
        models.append(
            TTSModel(
                model_id=model_id,
                name=str(item.get("name") or model_id),
                voices=voices,
                free_status=classify_free_status(model_id, pricing),
                pricing=pricing,
                supported_parameters=supported_parameters,
                audio=_audio_capabilities(item),
                speed_supported=supports_speed(model_id, supported_parameters, voices),
            )
        )

    if not models:
        raise InvalidCatalogError(
            "OpenRouter did not return any model with both speech output and voices"
        )
    return tuple(models)


def choose_recommended_model(models: Sequence[TTSModel]) -> tuple[TTSModel, str]:
    """Choose a live default without pinning a changing OpenRouter model ID."""
    available = [model for model in models if model.available]
    if not available:
        raise InvalidCatalogError("No currently available speech model was found")

    # Preserve the project's original voice preference without coupling the
    # integration to a dated model slug. Otherwise favor a verified free model.
    model = min(
        available,
        key=lambda candidate: (
            0
            if any(voice.casefold() == "sulafat" for voice in candidate.voices)
            else 1,
            0 if candidate.free_status is FreeStatus.FREE else 1,
            candidate.name.casefold(),
        ),
    )
    voice = next(
        (voice for voice in model.voices if voice.casefold() == "sulafat"),
        model.voices[0],
    )
    return model, voice


def filter_models(
    models: Sequence[TTSModel], *, free_only: bool
) -> tuple[TTSModel, ...]:
    """Apply the conservative free filter."""
    if not free_only:
        return tuple(models)
    result = tuple(
        model
        for model in models
        if model.available and model.free_status is FreeStatus.FREE
    )
    if not result:
        raise NoFreeModelsError(
            "No verified-free speech model is in the current catalog"
        )
    return result


def validate_model_voice(
    models: Sequence[TTSModel],
    model_id: str,
    voice: str,
    *,
    allow_preserved_unavailable: bool = False,
) -> TTSModel:
    """Validate the model and voice as a single catalog transaction."""
    model = next((item for item in models if item.model_id == model_id), None)
    if (
        model is None
        or voice not in model.voices
        or (voice in model.unavailable_voices and not allow_preserved_unavailable)
    ):
        raise ModelVoiceMismatchError(
            "The selected voice is not advertised by the selected speech model"
        )
    return model


class CatalogManager:
    """TTL catalog with persistence and selected-model disappearance tolerance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        client: CatalogClient,
    ) -> None:
        self._client = client
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self._snapshot: CatalogSnapshot | None = None
        self._loaded = False
        self._lock = asyncio.Lock()
        self._load_lock = asyncio.Lock()

    @property
    def snapshot(self) -> CatalogSnapshot | None:
        """Return the in-memory catalog without I/O."""
        return self._snapshot

    async def async_load(self) -> None:
        """Load the last good non-secret snapshot once."""
        async with self._load_lock:
            if self._loaded:
                return
            try:
                stored = await self._store.async_load()
                if stored:
                    self._snapshot = CatalogSnapshot.from_dict(stored)
            except (KeyError, TypeError, ValueError):
                self._snapshot = None
            finally:
                self._loaded = True

    async def async_get(
        self,
        *,
        force: bool = False,
        preserve_model_id: str | None = None,
        preserve_voice: str | None = None,
    ) -> CatalogSnapshot:
        """Get a fresh-enough catalog, falling back to the last good snapshot."""
        await self.async_load()
        async with self._lock:
            now = datetime.now(UTC)
            if (
                not force
                and self._snapshot is not None
                and now - self._snapshot.fetched_at < CATALOG_TTL
            ):
                return self._snapshot

            previous = self._snapshot
            try:
                fresh_models = list(await self._client.async_fetch_catalog())
            except (InvalidCatalogError, NetworkError, RateLimitError, ServerError):
                if previous is None:
                    raise
                self._snapshot = CatalogSnapshot(
                    models=previous.models,
                    fetched_at=previous.fetched_at,
                    stale=True,
                )
                return self._snapshot

            if preserve_model_id and not any(
                model.model_id == preserve_model_id for model in fresh_models
            ):
                preserved = previous.by_id(preserve_model_id) if previous else None
                if preserved is not None:
                    fresh_models.append(preserved.with_availability(False))
            elif preserve_model_id and preserve_voice:
                fresh = next(
                    model
                    for model in fresh_models
                    if model.model_id == preserve_model_id
                )
                if preserve_voice not in fresh.voices:
                    preserved_model = (
                        previous.by_id(preserve_model_id) if previous else None
                    )
                    if preserved_model and preserve_voice in preserved_model.voices:
                        index = fresh_models.index(fresh)
                        fresh_models[index] = TTSModel(
                            model_id=fresh.model_id,
                            name=fresh.name,
                            voices=(*fresh.voices, preserve_voice),
                            free_status=fresh.free_status,
                            pricing=fresh.pricing,
                            supported_parameters=fresh.supported_parameters,
                            audio=fresh.audio,
                            available=fresh.available,
                            unavailable_voices=frozenset({preserve_voice}),
                            speed_supported=fresh.speed_supported,
                        )

            self._snapshot = CatalogSnapshot(
                models=tuple(fresh_models), fetched_at=now, stale=False
            )
            await self._store.async_save(self._snapshot.as_dict())
            return self._snapshot

    async def async_remove(self) -> None:
        """Remove only the non-secret catalog cache for a deleted config entry."""
        await self._store.async_remove()
        self._snapshot = None
