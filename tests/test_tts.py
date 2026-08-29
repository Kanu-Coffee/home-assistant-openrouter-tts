"""Tests for the OpenRouter TTS entity platform."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.tts import SpeechManager
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import PlatformData

from custom_components.openrouter_tts.const import (
    CONF_MODEL,
    CONF_SPEED,
    CONF_VOICE,
    DEFAULT_LANGUAGE,
    DOMAIN,
    SUPPORTED_LANGUAGES,
)
from custom_components.openrouter_tts.exceptions import (
    AccessError,
    AuthenticationError,
    ServerError,
)
from custom_components.openrouter_tts.models import (
    AudioResult,
    CatalogSnapshot,
    FreeStatus,
    TTSModel,
)
from custom_components.openrouter_tts.tts import (
    OpenRouterTTSEntity,
    async_setup_entry,
)


def _model(
    *,
    available: bool = True,
    unavailable_voices: frozenset[str] = frozenset(),
) -> TTSModel:
    return TTSModel(
        model_id="provider/speech-model",
        name="Speech model",
        voices=("Live Voice", "Removed Voice"),
        free_status=FreeStatus.UNKNOWN,
        pricing={"prompt": "0.1", "completion": "0"},
        available=available,
        unavailable_voices=unavailable_voices,
        speed_supported=True,
    )


def _entity(
    hass: HomeAssistant,
    *,
    model: TTSModel | None = None,
    speed: float = 1.25,
) -> tuple[OpenRouterTTSEntity, SimpleNamespace, SimpleNamespace]:
    selected = model or _model()
    snapshot = CatalogSnapshot(models=(selected,), fetched_at=datetime.now(UTC))
    catalog = SimpleNamespace(
        snapshot=snapshot,
        async_get=AsyncMock(return_value=snapshot),
    )
    client = SimpleNamespace(
        async_generate_speech=AsyncMock(
            return_value=AudioResult(
                data=b"validated audio bytes",
                extension="wav",
                content_type="audio/wav",
            )
        )
    )
    runtime = SimpleNamespace(catalog=catalog, client=client)
    entry = SimpleNamespace(
        entry_id="test-entry-id",
        options={
            CONF_MODEL: selected.model_id,
            CONF_VOICE: "Live Voice",
            CONF_SPEED: speed,
        },
        runtime_data=runtime,
        async_start_reauth=MagicMock(),
    )
    entity = OpenRouterTTSEntity(hass, entry)
    entity.hass = hass
    return entity, entry, runtime


def test_entity_advertises_languages_and_configured_defaults(
    hass: HomeAssistant,
) -> None:
    """The native HA language and configured model options are exposed."""
    hass.config.language = "ko-KR"
    entity, _entry, _runtime = _entity(hass)

    assert entity.unique_id == "test-entry-id"
    assert entity.supported_languages == list(SUPPORTED_LANGUAGES)
    assert entity.default_language == "ko"
    assert entity.supported_options == [CONF_MODEL, CONF_VOICE, CONF_SPEED]
    assert entity.default_options == {
        CONF_MODEL: "provider/speech-model",
        CONF_VOICE: "Live Voice",
        CONF_SPEED: 1.25,
    }


def test_entity_falls_back_to_default_language(hass: HomeAssistant) -> None:
    hass.config.language = "fr-FR"

    entity, _entry, _runtime = _entity(hass)

    assert entity.default_language == DEFAULT_LANGUAGE


def test_only_currently_live_voices_are_advertised(hass: HomeAssistant) -> None:
    model = _model(unavailable_voices=frozenset({"Removed Voice"}))
    entity, _entry, runtime = _entity(hass, model=model)

    voices = entity.async_get_supported_voices("ko")

    assert voices is not None
    assert [(voice.voice_id, voice.name) for voice in voices] == [
        ("Live Voice", "Live Voice")
    ]

    runtime.catalog.snapshot = CatalogSnapshot(
        models=(model.with_availability(False),),
        fetched_at=datetime.now(UTC),
        stale=True,
    )
    assert entity.async_get_supported_voices("ko") is None
    runtime.catalog.snapshot = None
    assert entity.async_get_supported_voices("ko") is None


async def test_platform_setup_adds_one_tts_entity(hass: HomeAssistant) -> None:
    _entity_instance, entry, _runtime = _entity(hass)
    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    add_entities.assert_called_once()
    added = add_entities.call_args.args[0]
    assert len(added) == 1
    assert isinstance(added[0], OpenRouterTTSEntity)


async def test_translated_entity_name_is_available_to_tts_manager(
    hass: HomeAssistant,
) -> None:
    """The media-source path requires a concrete engine name before generation."""
    entity, _entry, _runtime = _entity(hass)
    entity.platform_data = PlatformData(
        hass,
        domain="tts",
        platform_name=DOMAIN,
    )
    entity.platform_data.platform_translations = {
        f"component.{DOMAIN}.entity.tts.openrouter_tts.name": "OpenRouter TTS"
    }
    entity.async_internal_get_tts_audio = AsyncMock(
        return_value=("mp3", b"audio bytes")
    )
    manager = SpeechManager(
        hass,
        use_file_cache=False,
        cache_dir="tts",
        memory_cache_maxage=300,
    )

    generated = b"".join(
        [
            chunk
            async for chunk in manager._async_generate_tts_audio(
                entity,
                "Safe test sentence",
                "en",
                {},
            )
        ]
    )

    assert entity.name == "OpenRouter TTS"
    assert generated == b"audio bytes"


async def test_audio_success_returns_extension_and_bytes(hass: HomeAssistant) -> None:
    entity, entry, runtime = _entity(hass)
    message = "Short private test sentence"

    extension, audio = await entity.async_get_tts_audio(message, "ko", {})

    assert extension == "wav"
    assert audio == b"validated audio bytes"
    runtime.catalog.async_get.assert_awaited_once_with(
        preserve_model_id="provider/speech-model",
        preserve_voice="Live Voice",
    )
    runtime.client.async_generate_speech.assert_awaited_once_with(
        text=message,
        model=_model(),
        voice="Live Voice",
        speed=1.25,
        response_format="mp3",
    )
    entry.async_start_reauth.assert_not_called()


@pytest.mark.parametrize(
    "speed",
    [None, "not-a-number", 0.49, 2.01, float("nan"), float("inf"), True],
)
async def test_invalid_speed_is_a_translated_error(
    hass: HomeAssistant,
    speed: object,
) -> None:
    entity, _entry, runtime = _entity(hass)

    with pytest.raises(HomeAssistantError) as raised:
        await entity.async_get_tts_audio(
            "Safe short sentence",
            "en",
            {CONF_SPEED: speed},
        )

    assert raised.value.translation_domain == "openrouter_tts"
    assert raised.value.translation_key == "invalid_speed"
    assert raised.value.__cause__ is None
    if isinstance(speed, str):
        assert speed not in repr(raised.value)
    runtime.catalog.async_get.assert_not_awaited()
    runtime.client.async_generate_speech.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "translation_key"),
    [
        (AuthenticationError("credential rejected"), "invalid_auth"),
        (AccessError("credential lacks access"), "access_denied"),
    ],
)
async def test_authentication_failure_starts_reauth_and_is_translated(
    hass: HomeAssistant,
    error: Exception,
    translation_key: str,
) -> None:
    entity, entry, runtime = _entity(hass)
    runtime.client.async_generate_speech.side_effect = error

    with pytest.raises(HomeAssistantError) as raised:
        await entity.async_get_tts_audio("Safe short sentence", "en", {})

    entry.async_start_reauth.assert_called_once_with(hass)
    assert raised.value.translation_domain == "openrouter_tts"
    assert raised.value.translation_key == translation_key


async def test_provider_failure_is_translated_without_leaking_text_or_key(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    message = "private-message-sentinel"
    key = "fake-key-sentinel"
    upstream_detail = f"provider echoed {message} and {key}"
    entity, entry, runtime = _entity(hass)
    entry.data = {"api_key": key}
    runtime.client.async_generate_speech.side_effect = ServerError(upstream_detail)

    with pytest.raises(HomeAssistantError) as raised:
        await entity.async_get_tts_audio(message, "en", {})

    assert raised.value.translation_domain == "openrouter_tts"
    assert raised.value.translation_key == "server_error"
    assert upstream_detail not in str(raised.value)
    assert message not in repr(raised.value)
    assert key not in repr(raised.value)
    assert message not in caplog.text
    assert key not in caplog.text
    entry.async_start_reauth.assert_not_called()
