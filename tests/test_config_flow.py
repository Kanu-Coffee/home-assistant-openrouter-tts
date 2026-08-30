"""Config, reauthentication, and atomic options flow tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, flush_store

from custom_components.openrouter_tts.const import (
    CONF_API_KEY,
    CONF_MODEL,
    CONF_MODEL_FILTER,
    CONF_SPEED,
    CONF_STORAGE_ROOT,
    CONF_VOICE,
    DOMAIN,
    FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
    MODEL_FILTER_ALL,
    MODEL_FILTER_FREE_ONLY,
    PROVIDER_DEFAULT_VOICE_ID,
)
from custom_components.openrouter_tts.exceptions import AuthenticationError
from custom_components.openrouter_tts.models import (
    CatalogSnapshot,
    FreeStatus,
    TTSModel,
)


def _models() -> tuple[TTSModel, ...]:
    return (
        TTSModel(
            model_id="provider/paid-speech",
            name="Paid speech",
            voices=("Sulafat", "Other"),
            free_status=FreeStatus.PAID,
            pricing={"prompt": "0.1", "completion": "0"},
        ),
        TTSModel(
            model_id="provider/free-speech:free",
            name="Free speech",
            voices=("FreeVoice",),
            free_status=FreeStatus.FREE,
            pricing={"prompt": "0", "completion": "0"},
        ),
    )


def _fish_model() -> TTSModel:
    return TTSModel(
        model_id=FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
        name="Fish Audio S2.1 Pro Free",
        voices=(PROVIDER_DEFAULT_VOICE_ID,),
        free_status=FreeStatus.FREE,
        pricing={"prompt": "0", "completion": "0"},
        provider_default_voice=True,
    )


async def test_config_flow_success(hass: HomeAssistant) -> None:
    """A key, model, voice, speed, and root are committed at the final step."""
    with (
        patch(
            "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_validate_key",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_fetch_catalog",
            new=AsyncMock(return_value=_models()),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "secret-test-value"}
        )
        assert result["step_id"] == "model"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_MODEL: "provider/paid-speech"}
        )
        assert result["step_id"] == "voice"

        root = hass.config.path("www", "audio", "tts")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_VOICE: "Sulafat",
                CONF_SPEED: 1.0,
                CONF_STORAGE_ROOT: root,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: "secret-test-value"}
    assert result["options"] == {
        CONF_MODEL: "provider/paid-speech",
        CONF_VOICE: "Sulafat",
        CONF_SPEED: 1.0,
        CONF_STORAGE_ROOT: root,
        CONF_MODEL_FILTER: MODEL_FILTER_ALL,
    }


@pytest.mark.parametrize(
    ("language", "expected_label"),
    [("en", "Provider default voice"), ("ko-KR", "공급자 기본 음성")],
)
async def test_config_flow_exposes_and_saves_fish_provider_default_atomically(
    hass: HomeAssistant,
    language: str,
    expected_label: str,
) -> None:
    """The exact Fish adapter appears as a localized, selectable voice mode."""
    hass.config.language = language
    with (
        patch(
            "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_validate_key",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_fetch_catalog",
            new=AsyncMock(return_value=(_fish_model(),)),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "fish-test-secret"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_MODEL: FISH_AUDIO_S21_PRO_FREE_MODEL_ID}
        )

        voice_selector = next(
            value
            for key, value in result["data_schema"].schema.items()
            if key.schema == CONF_VOICE
        )
        assert voice_selector.config["options"] == [
            {"value": PROVIDER_DEFAULT_VOICE_ID, "label": expected_label}
        ]

        root = hass.config.path("www", "audio", "tts")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_VOICE: PROVIDER_DEFAULT_VOICE_ID,
                CONF_SPEED: 1.0,
                CONF_STORAGE_ROOT: root,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        CONF_MODEL: FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
        CONF_VOICE: PROVIDER_DEFAULT_VOICE_ID,
        CONF_SPEED: 1.0,
        CONF_STORAGE_ROOT: root,
        CONF_MODEL_FILTER: MODEL_FILTER_ALL,
    }


async def test_config_flow_invalid_key(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A rejected key stays on the form and is never included in logs."""
    key = "secret-invalid-value"
    with patch(
        "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_validate_key",
        new=AsyncMock(side_effect=AuthenticationError("rejected")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: key}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert key not in caplog.text


async def test_unexpected_validation_error_redacts_exception_message(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Unknown dependency errors cannot leak credentials through exception text."""
    key = "sentinel-credential-never-log"
    with patch(
        "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_validate_key",
        new=AsyncMock(side_effect=RuntimeError(f"upstream included {key}")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: key}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
    assert key not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_reauthentication_updates_only_key(hass: HomeAssistant) -> None:
    """Reauthentication validates before replacing credential data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_API_KEY: "old-secret"},
        options={CONF_MODEL: "provider/paid-speech", CONF_VOICE: "Sulafat"},
    )
    entry.add_to_hass(hass)
    reload_entry = AsyncMock()
    with (
        patch(
            "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_validate_key",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_fetch_catalog",
            new=AsyncMock(return_value=_models()),
        ),
        patch.object(hass.config_entries, "async_reload", new=reload_entry),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=dict(entry.data),
        )
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-secret"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_API_KEY: "new-secret"}
    assert entry.options[CONF_MODEL] == "provider/paid-speech"
    reload_entry.assert_awaited_once_with(entry.entry_id)
    await flush_store(hass.config_entries._store)


async def test_failed_reauthentication_preserves_stored_key(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_API_KEY: "old-secret"},
        options={CONF_MODEL: "provider/paid-speech", CONF_VOICE: "Sulafat"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.openrouter_tts.config_flow.OpenRouterClient.async_validate_key",
        new=AsyncMock(side_effect=AuthenticationError("rejected")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=dict(entry.data),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "rejected-new-secret"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data == {CONF_API_KEY: "old-secret"}


def _options_entry(
    hass: HomeAssistant, models: tuple[TTSModel, ...]
) -> MockConfigEntry:
    snapshot = CatalogSnapshot(models=models, fetched_at=datetime.now(UTC))
    catalog = SimpleNamespace(
        snapshot=snapshot, async_get=AsyncMock(return_value=snapshot)
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_API_KEY: "stored-secret"},
        options={
            CONF_MODEL: "provider/paid-speech",
            CONF_VOICE: "Sulafat",
            CONF_SPEED: 1.0,
            CONF_STORAGE_ROOT: hass.config.path("www", "audio", "tts"),
            CONF_MODEL_FILTER: MODEL_FILTER_ALL,
        },
    )
    entry.runtime_data = SimpleNamespace(catalog=catalog)
    entry.add_to_hass(hass)
    return entry


async def test_options_flow_commits_model_and_voice_atomically(
    hass: HomeAssistant,
) -> None:
    """Intermediate filter/model steps do not mutate stored options."""
    entry = _options_entry(hass, _models())
    original_options = dict(entry.options)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "configure"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MODEL_FILTER: MODEL_FILTER_FREE_ONLY}
    )
    assert result["step_id"] == "model"
    assert entry.options == original_options

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MODEL: "provider/free-speech:free"}
    )
    assert result["step_id"] == "voice"
    assert entry.options == original_options

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_VOICE: "FreeVoice",
            CONF_SPEED: 1.25,
            CONF_STORAGE_ROOT: hass.config.path("private_audio"),
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODEL] == "provider/free-speech:free"
    assert result["data"][CONF_VOICE] == "FreeVoice"
    assert result["data"][CONF_MODEL_FILTER] == MODEL_FILTER_FREE_ONLY


async def test_options_flow_switches_to_fish_provider_default_atomically(
    hass: HomeAssistant,
) -> None:
    """Fish model and provider-default sentinel are committed in one final update."""
    entry = _options_entry(hass, (*_models(), _fish_model()))
    original_options = dict(entry.options)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "configure"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MODEL_FILTER: MODEL_FILTER_FREE_ONLY}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MODEL: FISH_AUDIO_S21_PRO_FREE_MODEL_ID}
    )

    assert result["step_id"] == "voice"
    assert entry.options == original_options
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_VOICE: PROVIDER_DEFAULT_VOICE_ID,
            CONF_SPEED: 1.5,
            CONF_STORAGE_ROOT: hass.config.path("www", "audio", "tts"),
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODEL] == FISH_AUDIO_S21_PRO_FREE_MODEL_ID
    assert result["data"][CONF_VOICE] == PROVIDER_DEFAULT_VOICE_ID
    assert result["data"][CONF_MODEL_FILTER] == MODEL_FILTER_FREE_ONLY


async def test_no_free_models_keeps_existing_options(hass: HomeAssistant) -> None:
    """An empty free filter returns to scope selection without any mutation."""
    entry = _options_entry(hass, (_models()[0],))
    original_options = dict(entry.options)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "configure"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MODEL_FILTER: MODEL_FILTER_FREE_ONLY}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configure"
    assert result["errors"] == {"base": "no_free_models"}
    assert entry.options == original_options


async def test_options_refresh_catalog(hass: HomeAssistant) -> None:
    """The separate refresh action forces metadata refresh without changing options."""
    entry = _options_entry(hass, _models())
    original_options = dict(entry.options)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "refresh"}
    )
    assert result["step_id"] == "refresh"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "catalog_refreshed"
    assert entry.options == original_options
    entry.runtime_data.catalog.async_get.assert_awaited_once_with(
        force=True,
        preserve_model_id="provider/paid-speech",
        preserve_voice="Sulafat",
    )
