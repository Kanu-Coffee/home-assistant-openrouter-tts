"""Home Assistant TTS entity backed by OpenRouter."""

from __future__ import annotations

from typing import Any

from homeassistant.components.tts import TextToSpeechEntity
from homeassistant.components.tts.models import Voice
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OpenRouterConfigEntry
from .catalog import validate_model_voice
from .const import (
    CONF_MODEL,
    CONF_SPEED,
    CONF_VOICE,
    DEFAULT_LANGUAGE,
    DEFAULT_SPEED,
    DOMAIN,
    MAX_SPEED,
    MIN_SPEED,
    PROVIDER_DEFAULT_VOICE_ID,
    SUPPORTED_LANGUAGES,
)
from .exceptions import AccessError, AuthenticationError, OpenRouterTTSError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenRouterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the OpenRouter TTS entity."""
    async_add_entities([OpenRouterTTSEntity(hass, entry)])


class OpenRouterTTSEntity(TextToSpeechEntity):
    """Generate speech with the entry's selected model and voice."""

    # Do not set ``_attr_name`` to ``None``: that shadows Home Assistant's
    # translated entity name, while the TTS media-source pipeline requires a
    # concrete engine name when the generated URL is fetched.
    _attr_has_entity_name = True
    _attr_translation_key = "openrouter_tts"

    def __init__(self, hass: HomeAssistant, entry: OpenRouterConfigEntry) -> None:
        self._entry = entry
        self._provider_default_voice_name = (
            "공급자 기본 음성"
            if hass.config.language.casefold().startswith("ko")
            else "Provider default voice"
        )
        self._attr_unique_id = entry.entry_id
        self._attr_supported_languages = list(SUPPORTED_LANGUAGES)
        self._attr_supported_options = [CONF_MODEL, CONF_VOICE, CONF_SPEED]
        language = hass.config.language.split("-", 1)[0].casefold()
        self._attr_default_language = (
            language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        )
        self._attr_default_options = {
            CONF_MODEL: str(entry.options.get(CONF_MODEL, "")),
            CONF_VOICE: str(entry.options.get(CONF_VOICE, "")),
            CONF_SPEED: float(entry.options.get(CONF_SPEED, DEFAULT_SPEED)),
        }

    @callback
    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        """Return cached voices for the configured model without network I/O."""
        snapshot = self._entry.runtime_data.catalog.snapshot
        if snapshot is None:
            return None
        model_id = str(self._entry.options.get(CONF_MODEL, ""))
        model = snapshot.by_id(model_id)
        if model is None or not model.available:
            return None
        voices = [
            Voice(
                voice_id=voice,
                name=(
                    self._provider_default_voice_name
                    if voice == PROVIDER_DEFAULT_VOICE_ID
                    else voice
                ),
            )
            for voice in model.voices
            if voice not in model.unavailable_voices
        ]
        return voices or None

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> tuple[str | None, bytes | None]:
        """Generate validated audio without logging the message."""
        runtime = self._entry.runtime_data
        model_id = str(
            options.get(CONF_MODEL) or self._entry.options.get(CONF_MODEL, "")
        )
        configured_model = str(self._entry.options.get(CONF_MODEL, ""))
        configured_voice = str(self._entry.options.get(CONF_VOICE, ""))
        voice = str(
            options.get(CONF_VOICE)
            or (configured_voice if model_id == configured_model else "")
        )
        raw_speed = options.get(
            CONF_SPEED, self._entry.options.get(CONF_SPEED, DEFAULT_SPEED)
        )
        if isinstance(raw_speed, bool):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_speed"
            )
        try:
            speed = float(raw_speed)
        except (TypeError, ValueError):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_speed"
            ) from None
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_speed"
            )
        try:
            snapshot = await runtime.catalog.async_get(
                preserve_model_id=configured_model or None,
                preserve_voice=configured_voice or None,
            )
            model = validate_model_voice(
                snapshot.models,
                model_id,
                voice,
                allow_preserved_unavailable=(
                    model_id == configured_model and voice == configured_voice
                ),
            )
            audio = await runtime.client.async_generate_speech(
                text=message,
                model=model,
                voice=voice,
                speed=speed,
                response_format="mp3",
            )
        except (AuthenticationError, AccessError) as err:
            self._entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=err.translation_key
            ) from None
        except OpenRouterTTSError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=err.translation_key
            ) from None
        return audio.extension, audio.data
