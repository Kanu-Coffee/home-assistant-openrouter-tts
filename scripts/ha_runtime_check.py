#!/usr/bin/env python3
"""Exercise setup, unload, reload, services, and translations in real HA Core."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant

from custom_components.openrouter_tts import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.openrouter_tts.const import (
    CONF_API_KEY,
    CONF_MODEL,
    CONF_SPEED,
    CONF_STORAGE_ROOT,
    CONF_VOICE,
    DOMAIN,
)
from custom_components.openrouter_tts.models import (
    CatalogSnapshot,
    FreeStatus,
    TTSModel,
)
from custom_components.openrouter_tts.storage import SecureFileStore

_LOGGER = logging.getLogger("openrouter_tts.ha_runtime_check")


class _FakeClient:
    """Never touch the network during compatibility checks."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def async_validate_key(self) -> None:
        return None


class _FakeCatalog:
    """Return one immutable catalog without Home Assistant storage I/O."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        model = TTSModel(
            model_id="test/speech",
            name="Compatibility speech",
            voices=("TestVoice",),
            free_status=FreeStatus.UNKNOWN,
            pricing={"prompt": "0", "completion": "0"},
        )
        self.snapshot = CatalogSnapshot((model,), datetime.now(UTC))

    async def async_load(self) -> None:
        return None

    async def async_get(self, **_kwargs: object) -> CatalogSnapshot:
        return self.snapshot


def _validate_resources() -> None:
    repository = Path(__file__).resolve().parents[1]
    component = repository / "custom_components" / DOMAIN
    json.loads((component / "manifest.json").read_text(encoding="utf-8"))
    json.loads((component / "strings.json").read_text(encoding="utf-8"))
    json.loads((component / "translations" / "en.json").read_text(encoding="utf-8"))
    json.loads((component / "translations" / "ko.json").read_text(encoding="utf-8"))
    services = yaml.safe_load((component / "services.yaml").read_text(encoding="utf-8"))
    assert {"generate_file", "delete_file", "refresh_catalog"} <= set(services)


def _validate_bind_mounted_storage() -> None:
    """Exercise storage where the host-owned config UID differs from container root."""
    config_value = os.environ.get("OPENROUTER_TTS_BIND_CONFIG")
    if not config_value:
        raise AssertionError("OPENROUTER_TTS_BIND_CONFIG is required")
    config_dir = Path(config_value)
    config_stat = config_dir.stat()
    assert os.geteuid() == 0
    assert config_stat.st_uid != os.geteuid()
    assert stat.S_IMODE(config_stat.st_mode) == 0o755

    root = config_dir / "www" / "audio" / "tts"
    store = SecureFileStore(str(root), str(config_dir))
    payload = b"container storage check"
    target = root / "checks" / "compatibility.wav"
    try:
        saved = store.save(
            filename="compatibility.wav",
            subdirectory="checks",
            data=payload,
            actual_extension="wav",
        )
        assert target == root / saved.relative_path
        assert target.read_bytes() == payload
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        deleted = store.delete(filename="compatibility.wav", subdirectory="checks")
        assert deleted.size == len(payload)
        assert not target.exists()
    finally:
        with suppress(FileNotFoundError):
            target.unlink()
        for directory in (
            root / "checks" / ".openrouter-tts-staging",
            root / "checks",
            root,
            root.parent,
            root.parent.parent,
        ):
            with suppress(FileNotFoundError):
                directory.rmdir()


async def _run() -> None:
    with tempfile.TemporaryDirectory(prefix="openrouter-tts-ha-") as config_dir:
        hass = HomeAssistant(config_dir)
        hass.config_entries = ConfigEntries(hass, {})
        await hass.async_start()
        try:
            assert await async_setup(hass, {}) is True
            assert hass.services.has_service(DOMAIN, "generate_file")
            assert hass.services.has_service(DOMAIN, "delete_file")
            assert hass.services.has_service(DOMAIN, "refresh_catalog")

            entry = SimpleNamespace(
                entry_id="compatibility-entry",
                data={CONF_API_KEY: "placeholder-never-sent"},
                options={
                    CONF_MODEL: "test/speech",
                    CONF_VOICE: "TestVoice",
                    CONF_SPEED: 1.0,
                    CONF_STORAGE_ROOT: hass.config.path("www", "audio", "tts"),
                },
                runtime_data=None,
            )
            forward = AsyncMock(return_value=True)
            unload = AsyncMock(return_value=True)
            with (
                patch(
                    "custom_components.openrouter_tts.async_get_clientsession",
                    return_value=object(),
                ),
                patch("custom_components.openrouter_tts.OpenRouterClient", _FakeClient),
                patch("custom_components.openrouter_tts.CatalogManager", _FakeCatalog),
                patch.object(
                    hass.config_entries, "async_forward_entry_setups", forward
                ),
                patch.object(hass.config_entries, "async_unload_platforms", unload),
            ):
                assert await async_setup_entry(hass, entry) is True
                assert entry.runtime_data is not None
                assert await async_unload_entry(hass, entry) is True
                assert await async_setup_entry(hass, entry) is True
            assert forward.await_count == 2
            assert unload.await_count == 1
            _LOGGER.info(
                "Home Assistant compatibility check passed: services, setup, "
                "unload, and reload"
            )
        finally:
            await hass.async_stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _validate_resources()
    _validate_bind_mounted_storage()
    asyncio.run(_run())
