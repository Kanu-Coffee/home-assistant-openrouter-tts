"""Privacy-preserving diagnostics for OpenRouter TTS."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from . import OpenRouterConfigEntry
from .const import CONF_API_KEY, CONF_STORAGE_ROOT

_DATA_TO_REDACT = {CONF_API_KEY}
_OPTIONS_TO_REDACT = {CONF_STORAGE_ROOT}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OpenRouterConfigEntry
) -> dict[str, Any]:
    """Return settings and catalog status, never text, audio, or credentials."""
    snapshot = entry.runtime_data.catalog.snapshot
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), _DATA_TO_REDACT),
            "options": async_redact_data(dict(entry.options), _OPTIONS_TO_REDACT),
        },
        "catalog": None
        if snapshot is None
        else {
            "fetched_at": snapshot.fetched_at.isoformat(),
            "stale": snapshot.stale,
            "models": [
                {
                    "id": model.model_id,
                    "free_status": model.free_status,
                    "available": model.available,
                    "voice_count": len(model.voices),
                }
                for model in snapshot.models
            ],
        },
    }
