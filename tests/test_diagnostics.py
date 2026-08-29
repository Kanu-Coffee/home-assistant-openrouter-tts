"""Tests for privacy-preserving config-entry diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import REDACTED

from custom_components.openrouter_tts.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.openrouter_tts.models import (
    CatalogSnapshot,
    FreeStatus,
    TTSModel,
)


async def test_diagnostics_redact_key_and_only_summarize_catalog(
    hass: HomeAssistant,
) -> None:
    key = "diagnostic-secret-sentinel"
    model = TTSModel(
        model_id="provider/speech",
        name="Speech",
        voices=("First", "Second"),
        free_status=FreeStatus.UNKNOWN,
        pricing={"prompt": "private-pricing-sentinel", "completion": "0"},
    )
    snapshot = CatalogSnapshot(
        models=(model,), fetched_at=datetime(2026, 8, 29, tzinfo=UTC), stale=True
    )
    entry = SimpleNamespace(
        data={"api_key": key},
        options={
            "model": model.model_id,
            "voice": "First",
            "storage_root": "/config/private-location",
        },
        runtime_data=SimpleNamespace(catalog=SimpleNamespace(snapshot=snapshot)),
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["entry"]["data"]["api_key"] == REDACTED
    assert result["entry"]["options"]["voice"] == "First"
    assert result["entry"]["options"]["storage_root"] == REDACTED
    assert result["catalog"]["stale"] is True
    assert result["catalog"]["models"] == [
        {
            "id": "provider/speech",
            "free_status": FreeStatus.UNKNOWN,
            "available": True,
            "voice_count": 2,
        }
    ]
    assert key not in repr(result)
    assert "private-pricing-sentinel" not in repr(result)


async def test_diagnostics_support_missing_catalog(hass: HomeAssistant) -> None:
    entry = SimpleNamespace(
        data={"api_key": "secret"},
        options={},
        runtime_data=SimpleNamespace(catalog=SimpleNamespace(snapshot=None)),
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["catalog"] is None
