"""Tests for integration setup, lifecycle, and administrator services."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import openrouter_tts as integration
from custom_components.openrouter_tts.const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_FILENAME,
    ATTR_FORMAT,
    ATTR_OVERWRITE,
    ATTR_SUBDIRECTORY,
    ATTR_TEXT,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_SPEED,
    CONF_STORAGE_ROOT,
    CONF_VOICE,
    DOMAIN,
    FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
    PLATFORMS,
    PROVIDER_DEFAULT_VOICE_ID,
    SERVICE_DELETE_FILE,
    SERVICE_GENERATE_FILE,
    SERVICE_REFRESH_CATALOG,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from custom_components.openrouter_tts.exceptions import (
    AuthenticationError,
    FileAlreadyExistsError,
    InvalidRequestError,
    ModelVoiceMismatchError,
    NetworkError,
    ServerError,
    UnsafePathError,
)
from custom_components.openrouter_tts.models import (
    AudioResult,
    CatalogSnapshot,
    FreeStatus,
    TTSModel,
)
from custom_components.openrouter_tts.storage import StoredFile


def _model(
    *,
    status: FreeStatus = FreeStatus.FREE,
    voices: tuple[str, ...] = ("Live Voice",),
) -> TTSModel:
    return TTSModel(
        model_id="provider/speech-model:free",
        name="Speech model",
        voices=voices,
        free_status=status,
        pricing={"prompt": "0", "completion": "0"},
        speed_supported=True,
    )


def _snapshot(
    *models: TTSModel,
    stale: bool = False,
) -> CatalogSnapshot:
    return CatalogSnapshot(
        models=models or (_model(),),
        fetched_at=datetime(2026, 8, 29, 1, 2, 3, tzinfo=UTC),
        stale=stale,
    )


def _entry(
    hass: HomeAssistant,
    *,
    runtime: object | None = None,
    loaded: bool = False,
    api_key: str = "fake-api-key",
    model_id: str = "provider/speech-model:free",
    voice: str = "Live Voice",
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_API_KEY: api_key},
        options={
            CONF_MODEL: model_id,
            CONF_VOICE: voice,
            CONF_SPEED: 1.25,
            CONF_STORAGE_ROOT: hass.config.path("www", "audio", "tts"),
        },
        state=(config_entries.ConfigEntryState.LOADED if loaded else None),
    )
    if runtime is not None:
        entry.runtime_data = runtime
    entry.add_to_hass(hass)
    return entry


def _service_runtime(
    *,
    snapshot: CatalogSnapshot | None = None,
) -> SimpleNamespace:
    current = snapshot or _snapshot()
    return SimpleNamespace(
        catalog=SimpleNamespace(
            snapshot=current,
            async_get=AsyncMock(return_value=current),
        ),
        client=SimpleNamespace(
            async_generate_speech=AsyncMock(
                return_value=AudioResult(
                    data=b"validated audio",
                    extension="wav",
                    content_type="audio/wav",
                )
            )
        ),
        storage=SimpleNamespace(
            save=MagicMock(
                return_value=StoredFile(
                    absolute_path="/private/config/www/audio/tts/shared/result.wav",
                    relative_path="shared/result.wav",
                    url="/local/audio/tts/shared/result.wav",
                    size=len(b"validated audio"),
                )
            ),
            delete=MagicMock(),
        ),
    )


def _generate_call(
    hass: HomeAssistant,
    *,
    text: str = "Short private sentence",
    entry_id: str | None = None,
    filename: str = "result",
    subdirectory: str = "shared",
) -> ServiceCall:
    data: dict[str, Any] = {
        ATTR_TEXT: text,
        ATTR_FILENAME: filename,
        ATTR_SUBDIRECTORY: subdirectory,
        ATTR_FORMAT: "wav",
        ATTR_OVERWRITE: False,
    }
    if entry_id is not None:
        data[ATTR_CONFIG_ENTRY_ID] = entry_id
    return ServiceCall(hass, DOMAIN, SERVICE_GENERATE_FILE, data)


async def test_async_setup_registers_admin_services_and_schemas(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register = MagicMock()
    monkeypatch.setattr(integration, "async_register_admin_service", register)

    assert await integration.async_setup(hass, {}) is True

    assert register.call_count == 3
    calls = {call.args[2]: call for call in register.call_args_list}
    assert set(calls) == {
        SERVICE_GENERATE_FILE,
        SERVICE_DELETE_FILE,
        SERVICE_REFRESH_CATALOG,
    }
    for call in calls.values():
        assert call.args[:2] == (hass, DOMAIN)
        assert call.kwargs["supports_response"] is SupportsResponse.OPTIONAL
        assert isinstance(call.kwargs["schema"], vol.Schema)

    generate_schema = calls[SERVICE_GENERATE_FILE].kwargs["schema"]
    validated = generate_schema(
        {
            ATTR_TEXT: "Safe sentence",
            ATTR_FILENAME: "announcement",
        }
    )
    assert validated[ATTR_SUBDIRECTORY] == ""
    assert validated[ATTR_FORMAT] == "mp3"
    assert validated[ATTR_OVERWRITE] is False
    with pytest.raises(vol.Invalid):
        generate_schema(
            {
                ATTR_TEXT: "Safe sentence",
                ATTR_FILENAME: "announcement",
                ATTR_FORMAT: "flac",
            }
        )
    with pytest.raises(vol.Invalid):
        generate_schema({ATTR_TEXT: "", ATTR_FILENAME: "announcement"})


async def test_setup_entry_builds_runtime_and_forwards_tts_platform(
    hass: HomeAssistant,
) -> None:
    entry = _entry(hass)
    client = SimpleNamespace(async_validate_key=AsyncMock())
    catalog = SimpleNamespace(
        snapshot=None,
        async_load=AsyncMock(),
        async_get=AsyncMock(return_value=_snapshot()),
    )
    storage = object()
    session = object()

    with (
        patch.object(integration, "async_get_clientsession", return_value=session),
        patch.object(
            integration, "OpenRouterClient", return_value=client
        ) as client_cls,
        patch.object(
            integration, "CatalogManager", return_value=catalog
        ) as catalog_cls,
        patch.object(
            integration, "SecureFileStore", return_value=storage
        ) as storage_cls,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ) as forward,
    ):
        assert await integration.async_setup_entry(hass, entry) is True

    client_cls.assert_called_once_with(session, "fake-api-key")
    catalog_cls.assert_called_once_with(hass, entry.entry_id, client)
    catalog.async_load.assert_awaited_once_with()
    client.async_validate_key.assert_awaited_once_with()
    catalog.async_get.assert_awaited_once_with(
        preserve_model_id="provider/speech-model:free",
        preserve_voice="Live Voice",
    )
    storage_cls.assert_called_once_with(
        hass.config.path("www", "audio", "tts"), hass.config.config_dir
    )
    assert entry.runtime_data.client is client
    assert entry.runtime_data.catalog is catalog
    assert entry.runtime_data.storage is storage
    forward.assert_awaited_once_with(entry, PLATFORMS)


@pytest.mark.parametrize(
    "error",
    [AuthenticationError("rejected"), integration.AccessError("forbidden")],
)
async def test_setup_entry_auth_failure_raises_config_entry_auth_failed(
    hass: HomeAssistant,
    error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key = "fake-auth-key-sentinel"
    entry = _entry(hass, api_key=key)
    client = SimpleNamespace(async_validate_key=AsyncMock(side_effect=error))
    catalog = SimpleNamespace(
        snapshot=None,
        async_load=AsyncMock(),
        async_get=AsyncMock(),
    )

    with (
        patch.object(integration, "async_get_clientsession", return_value=object()),
        patch.object(integration, "OpenRouterClient", return_value=client),
        patch.object(integration, "CatalogManager", return_value=catalog),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ) as forward,
        pytest.raises(ConfigEntryAuthFailed) as raised,
    ):
        await integration.async_setup_entry(hass, entry)

    assert key not in str(raised.value)
    assert key not in caplog.text
    catalog.async_get.assert_not_awaited()
    forward.assert_not_awaited()


async def test_setup_entry_transient_failure_without_cache_is_not_ready(
    hass: HomeAssistant,
) -> None:
    entry = _entry(hass)
    client = SimpleNamespace(
        async_validate_key=AsyncMock(side_effect=NetworkError("offline"))
    )
    catalog = SimpleNamespace(
        snapshot=None,
        async_load=AsyncMock(),
        async_get=AsyncMock(),
    )

    with (
        patch.object(integration, "async_get_clientsession", return_value=object()),
        patch.object(integration, "OpenRouterClient", return_value=client),
        patch.object(integration, "CatalogManager", return_value=catalog),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ) as forward,
        pytest.raises(ConfigEntryNotReady),
    ):
        await integration.async_setup_entry(hass, entry)

    catalog.async_get.assert_not_awaited()
    forward.assert_not_awaited()


async def test_setup_entry_uses_stale_cache_during_transient_validation_failure(
    hass: HomeAssistant,
) -> None:
    entry = _entry(hass)
    stale = _snapshot(stale=True)
    client = SimpleNamespace(
        async_validate_key=AsyncMock(side_effect=NetworkError("offline"))
    )
    catalog = SimpleNamespace(
        snapshot=stale,
        async_load=AsyncMock(),
        async_get=AsyncMock(return_value=stale),
    )
    storage = object()

    with (
        patch.object(integration, "async_get_clientsession", return_value=object()),
        patch.object(integration, "OpenRouterClient", return_value=client),
        patch.object(integration, "CatalogManager", return_value=catalog),
        patch.object(integration, "SecureFileStore", return_value=storage),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ) as forward,
    ):
        assert await integration.async_setup_entry(hass, entry) is True

    assert entry.runtime_data.catalog is catalog
    catalog.async_get.assert_awaited_once()
    forward.assert_awaited_once_with(entry, PLATFORMS)


async def test_setup_entry_catalog_failure_without_cache_is_not_ready(
    hass: HomeAssistant,
) -> None:
    entry = _entry(hass)
    client = SimpleNamespace(async_validate_key=AsyncMock())
    catalog = SimpleNamespace(
        snapshot=None,
        async_load=AsyncMock(),
        async_get=AsyncMock(side_effect=ServerError("provider unavailable")),
    )

    with (
        patch.object(integration, "async_get_clientsession", return_value=object()),
        patch.object(integration, "OpenRouterClient", return_value=client),
        patch.object(integration, "CatalogManager", return_value=catalog),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ) as forward,
        pytest.raises(ConfigEntryNotReady),
    ):
        await integration.async_setup_entry(hass, entry)

    forward.assert_not_awaited()


async def test_unload_entry_forwards_platform_unload(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ) as unload:
        assert await integration.async_unload_entry(hass, entry) is True

    unload.assert_awaited_once_with(entry, PLATFORMS)


async def test_remove_entry_deletes_only_catalog_cache(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _service_runtime()
    entry = _entry(hass, runtime=runtime)

    class RemoveStore:
        args: ClassVar[tuple[object, int, str] | None] = None
        removed: ClassVar[int] = 0

        @classmethod
        def __class_getitem__(cls, _item: object) -> type[RemoveStore]:
            return cls

        def __init__(self, store_hass: object, version: int, key: str) -> None:
            type(self).args = (store_hass, version, key)

        async def async_remove(self) -> None:
            type(self).removed += 1

    monkeypatch.setattr(integration, "Store", RemoveStore)

    await integration.async_remove_entry(hass, entry)

    assert RemoveStore.args == (
        hass,
        STORAGE_VERSION,
        f"{STORAGE_KEY_PREFIX}.{entry.entry_id}",
    )
    assert RemoveStore.removed == 1
    runtime.storage.delete.assert_not_called()


async def test_generate_file_returns_only_non_sensitive_relative_metadata(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    text = "private-generate-text-sentinel"
    key = "fake-generate-key-sentinel"
    runtime = _service_runtime()
    entry = _entry(hass, runtime=runtime, loaded=True, api_key=key)

    response = await integration._handle_generate_file(
        hass, _generate_call(hass, text=text, entry_id=entry.entry_id)
    )

    assert response == {
        "filename": "shared/result.wav",
        "url": "/local/audio/tts/shared/result.wav",
        "format": "wav",
        "size": len(b"validated audio"),
        "model": "provider/speech-model:free",
    }
    serialized = json.dumps(response)
    assert "/private/config" not in serialized
    assert text not in serialized
    assert key not in serialized
    assert not any("hash" in name.casefold() for name in response)
    assert text not in caplog.text
    assert key not in caplog.text
    runtime.client.async_generate_speech.assert_awaited_once_with(
        text=text,
        model=_model(),
        voice="Live Voice",
        speed=1.25,
        response_format="wav",
    )
    runtime.storage.save.assert_called_once_with(
        filename="result",
        subdirectory="shared",
        data=b"validated audio",
        actual_extension="wav",
        overwrite=False,
    )


async def test_generate_file_uses_fish_provider_default_selection(
    hass: HomeAssistant,
) -> None:
    """The administrator service accepts the same validated Fish voice mode."""
    model = TTSModel(
        model_id=FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
        name="Fish Audio S2.1 Pro Free",
        voices=(PROVIDER_DEFAULT_VOICE_ID,),
        free_status=FreeStatus.FREE,
        pricing={"prompt": "0", "completion": "0"},
        provider_default_voice=True,
    )
    runtime = _service_runtime(snapshot=_snapshot(model))
    entry = _entry(
        hass,
        runtime=runtime,
        loaded=True,
        model_id=FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
        voice=PROVIDER_DEFAULT_VOICE_ID,
    )

    response = await integration._handle_generate_file(
        hass, _generate_call(hass, entry_id=entry.entry_id)
    )

    assert response["model"] == FISH_AUDIO_S21_PRO_FREE_MODEL_ID
    runtime.client.async_generate_speech.assert_awaited_once_with(
        text="Short private sentence",
        model=model,
        voice=PROVIDER_DEFAULT_VOICE_ID,
        speed=1.25,
        response_format="wav",
    )


async def test_generate_file_rejects_whitespace_as_translated_validation_error(
    hass: HomeAssistant,
) -> None:
    runtime = _service_runtime()
    _entry(hass, runtime=runtime, loaded=True)

    with pytest.raises(ServiceValidationError) as raised:
        await integration._handle_generate_file(
            hass, _generate_call(hass, text=" \n\t ")
        )

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "invalid_request"
    runtime.client.async_generate_speech.assert_not_awaited()
    runtime.storage.save.assert_not_called()


@pytest.mark.parametrize(
    ("filename", "subdirectory"),
    [
        ("../escape.wav", "shared"),
        ("result.wav", "../escape"),
        ("result.txt", "shared"),
    ],
)
async def test_generate_file_rejects_unsafe_paths_before_billable_request(
    hass: HomeAssistant,
    filename: str,
    subdirectory: str,
) -> None:
    runtime = _service_runtime()
    _entry(hass, runtime=runtime, loaded=True)

    with pytest.raises(ServiceValidationError) as raised:
        await integration._handle_generate_file(
            hass,
            _generate_call(
                hass,
                filename=filename,
                subdirectory=subdirectory,
            ),
        )

    assert raised.value.translation_key == "unsafe_path"
    runtime.catalog.async_get.assert_not_awaited()
    runtime.client.async_generate_speech.assert_not_awaited()
    runtime.storage.save.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "translation_key"),
    [
        (UnsafePathError("private absolute path"), "unsafe_path"),
        (FileAlreadyExistsError("private destination"), "file_exists"),
    ],
)
async def test_generate_file_maps_storage_failures_to_validation_errors(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
    translation_key: str,
) -> None:
    runtime = _service_runtime()
    runtime.storage.save.side_effect = failure
    _entry(hass, runtime=runtime, loaded=True)

    with pytest.raises(ServiceValidationError) as raised:
        await integration._handle_generate_file(hass, _generate_call(hass))

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == translation_key
    assert str(failure) not in str(raised.value)
    assert str(failure) not in caplog.text


@pytest.mark.parametrize(
    ("failure", "expected_type", "translation_key", "reauth_expected"),
    [
        (
            InvalidRequestError("private invalid settings"),
            ServiceValidationError,
            "invalid_request",
            False,
        ),
        (
            ModelVoiceMismatchError("private voice"),
            ServiceValidationError,
            "model_voice_mismatch",
            False,
        ),
        (
            ServerError("private provider response"),
            HomeAssistantError,
            "server_error",
            False,
        ),
        (
            AuthenticationError("private credential response"),
            HomeAssistantError,
            "invalid_auth",
            True,
        ),
    ],
)
async def test_generate_file_maps_client_failures_without_sensitive_details(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
    expected_type: type[HomeAssistantError],
    translation_key: str,
    reauth_expected: bool,
) -> None:
    runtime = _service_runtime()
    entry = _entry(hass, runtime=runtime, loaded=True)
    if isinstance(failure, ModelVoiceMismatchError):
        runtime.catalog.async_get.return_value = _snapshot(_model(voices=("Other",)))
    else:
        runtime.client.async_generate_speech.side_effect = failure

    with (
        patch.object(entry, "async_start_reauth") as start_reauth,
        pytest.raises(expected_type) as raised,
    ):
        await integration._handle_generate_file(hass, _generate_call(hass))

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == translation_key
    assert str(failure) not in str(raised.value)
    assert str(failure) not in caplog.text
    if reauth_expected:
        start_reauth.assert_called_once_with(hass)
    else:
        start_reauth.assert_not_called()


async def test_refresh_catalog_returns_current_non_sensitive_counts(
    hass: HomeAssistant,
) -> None:
    current = _snapshot(
        _model(status=FreeStatus.FREE),
        TTSModel(
            model_id="provider/paid",
            name="Paid",
            voices=("Voice",),
            free_status=FreeStatus.PAID,
            pricing={"prompt": "1", "completion": "0"},
        ),
    )
    runtime = _service_runtime(snapshot=current)
    entry = _entry(hass, runtime=runtime, loaded=True)
    call = ServiceCall(
        hass,
        DOMAIN,
        SERVICE_REFRESH_CATALOG,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
    )

    response = await integration._handle_refresh_catalog(hass, call)

    assert response == {
        "model_count": 2,
        "free_model_count": 1,
        "stale": False,
        "fetched_at": "2026-08-29T01:02:03+00:00",
    }
    runtime.catalog.async_get.assert_awaited_once_with(
        force=True,
        preserve_model_id="provider/speech-model:free",
        preserve_voice="Live Voice",
    )
    assert "pricing" not in response


async def test_refresh_catalog_reports_stale_fallback_as_translated_failure(
    hass: HomeAssistant,
) -> None:
    stale = _snapshot(stale=True)
    runtime = _service_runtime(snapshot=stale)
    _entry(hass, runtime=runtime, loaded=True)
    call = ServiceCall(hass, DOMAIN, SERVICE_REFRESH_CATALOG, {})

    with pytest.raises(HomeAssistantError) as raised:
        await integration._handle_refresh_catalog(hass, call)

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "server_error"
