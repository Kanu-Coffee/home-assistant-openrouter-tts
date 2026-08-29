"""OpenRouter TTS integration setup and administrator services."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, cast

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.storage import Store

from .api import OpenRouterClient
from .catalog import CatalogManager, validate_model_voice
from .const import (
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
    DEFAULT_SPEED,
    DOMAIN,
    MAX_INPUT_LENGTH,
    PLATFORMS,
    SERVICE_DELETE_FILE,
    SERVICE_GENERATE_FILE,
    SERVICE_REFRESH_CATALOG,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .exceptions import (
    AccessError,
    AuthenticationError,
    FileAlreadyExistsError,
    InvalidRequestError,
    ModelVoiceMismatchError,
    NetworkError,
    OpenRouterTTSError,
    RateLimitError,
    ServerError,
    StorageError,
    UnsafePathError,
)
from .models import CatalogSnapshot
from .storage import SecureFileStore, normalize_filename, validate_subdirectory


@dataclass(slots=True)
class OpenRouterRuntimeData:
    """Per-entry objects shared by the entity and services."""

    client: OpenRouterClient
    catalog: CatalogManager
    storage: SecureFileStore


type OpenRouterConfigEntry = ConfigEntry[OpenRouterRuntimeData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_GENERATE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_TEXT): vol.All(
            cv.string, vol.Length(min=1, max=MAX_INPUT_LENGTH)
        ),
        vol.Required(ATTR_FILENAME): vol.All(cv.string, vol.Length(min=1, max=240)),
        vol.Optional(ATTR_SUBDIRECTORY, default=""): vol.All(
            cv.string, vol.Length(max=1000)
        ),
        vol.Optional(ATTR_FORMAT, default="mp3"): vol.In({"mp3", "wav"}),
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
    },
    extra=vol.PREVENT_EXTRA,
)
_DELETE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_FILENAME): vol.All(cv.string, vol.Length(min=1, max=240)),
        vol.Optional(ATTR_SUBDIRECTORY, default=""): vol.All(
            cv.string, vol.Length(max=1000)
        ),
    },
    extra=vol.PREVENT_EXTRA,
)
_REFRESH_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}, extra=vol.PREVENT_EXTRA
)


def default_storage_root(hass: HomeAssistant) -> str:
    """Return the installation-specific equivalent of /config/www/audio/tts."""
    return hass.config.path("www", "audio", "tts")


def _translation_error(
    error: OpenRouterTTSError,
    *,
    validation: bool = False,
) -> HomeAssistantError:
    error_type = ServiceValidationError if validation else HomeAssistantError
    return error_type(
        translation_domain=DOMAIN,
        translation_key=error.translation_key,
    )


def _entry_for_call(hass: HomeAssistant, call: ServiceCall) -> OpenRouterConfigEntry:
    requested_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if requested_id:
        entry = next((item for item in loaded if item.entry_id == requested_id), None)
        if entry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="config_entry_not_loaded"
            )
        return cast(OpenRouterConfigEntry, entry)
    if len(loaded) != 1:
        key = "config_entry_required" if loaded else "config_entry_not_loaded"
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key=key)
    return cast(OpenRouterConfigEntry, loaded[0])


async def _snapshot_for_entry(
    entry: OpenRouterConfigEntry, *, force: bool = False
) -> CatalogSnapshot:
    return await entry.runtime_data.catalog.async_get(
        force=force,
        preserve_model_id=str(entry.options.get(CONF_MODEL, "")) or None,
        preserve_voice=str(entry.options.get(CONF_VOICE, "")) or None,
    )


async def _handle_generate_file(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    entry = _entry_for_call(hass, call)
    runtime = entry.runtime_data
    model_id = str(entry.options.get(CONF_MODEL, ""))
    voice = str(entry.options.get(CONF_VOICE, ""))
    speed = float(entry.options.get(CONF_SPEED, DEFAULT_SPEED))
    if not str(call.data[ATTR_TEXT]).strip():
        raise _translation_error(
            InvalidRequestError("Speech text cannot contain only whitespace"),
            validation=True,
        )
    try:
        # Reject deterministic path failures before a potentially billable
        # generation request. SecureFileStore repeats these checks at write time.
        validate_subdirectory(str(call.data[ATTR_SUBDIRECTORY]) or None)
        normalize_filename(str(call.data[ATTR_FILENAME]), str(call.data[ATTR_FORMAT]))
        snapshot = await _snapshot_for_entry(entry)
        model = validate_model_voice(
            snapshot.models,
            model_id,
            voice,
            allow_preserved_unavailable=True,
        )
        audio = await runtime.client.async_generate_speech(
            text=str(call.data[ATTR_TEXT]),
            model=model,
            voice=voice,
            speed=speed,
            response_format=str(call.data[ATTR_FORMAT]),
        )
        stored = await hass.async_add_executor_job(
            partial(
                runtime.storage.save,
                filename=str(call.data[ATTR_FILENAME]),
                subdirectory=str(call.data[ATTR_SUBDIRECTORY]) or None,
                data=audio.data,
                actual_extension=audio.extension,
                overwrite=bool(call.data[ATTR_OVERWRITE]),
            )
        )
    except (AuthenticationError, AccessError) as err:
        entry.async_start_reauth(hass)
        raise _translation_error(err) from None
    except (
        UnsafePathError,
        FileAlreadyExistsError,
        InvalidRequestError,
        ModelVoiceMismatchError,
    ) as err:
        raise _translation_error(err, validation=True) from None
    except OpenRouterTTSError as err:
        raise _translation_error(err) from None

    return {
        "filename": stored.relative_path,
        "url": stored.url,
        "format": audio.extension,
        "size": stored.size,
        "model": model.model_id,
    }


async def _handle_delete_file(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    entry = _entry_for_call(hass, call)
    try:
        deleted = await hass.async_add_executor_job(
            partial(
                entry.runtime_data.storage.delete,
                filename=str(call.data[ATTR_FILENAME]),
                subdirectory=str(call.data[ATTR_SUBDIRECTORY]) or None,
            )
        )
    except FileNotFoundError:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="file_not_found"
        ) from None
    except UnsafePathError as err:
        raise _translation_error(err, validation=True) from None
    except StorageError as err:
        raise _translation_error(err) from None
    return {
        "filename": deleted.relative_path,
        "url": deleted.url,
        "deleted": True,
    }


async def _handle_refresh_catalog(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    entry = _entry_for_call(hass, call)
    try:
        snapshot = await _snapshot_for_entry(entry, force=True)
        if snapshot.stale:
            raise ServerError(
                "Catalog refresh failed; the last good catalog was retained"
            )
    except (AuthenticationError, AccessError) as err:
        entry.async_start_reauth(hass)
        raise _translation_error(err) from None
    except OpenRouterTTSError as err:
        raise _translation_error(err) from None
    return {
        "model_count": len(snapshot.models),
        "free_model_count": sum(
            model.free_status == "free" for model in snapshot.models
        ),
        "stale": snapshot.stale,
        "fetched_at": snapshot.fetched_at.isoformat(),
    }


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register integration-level administrator services exactly once."""
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_GENERATE_FILE,
        partial(_handle_generate_file, hass),
        schema=_GENERATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_FILE,
        partial(_handle_delete_file, hass),
        schema=_DELETE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_REFRESH_CATALOG,
        partial(_handle_refresh_catalog, hass),
        schema=_REFRESH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenRouterConfigEntry) -> bool:
    """Set up one OpenRouter TTS config entry."""
    client = OpenRouterClient(
        async_get_clientsession(hass), str(entry.data[CONF_API_KEY])
    )
    catalog = CatalogManager(hass, entry.entry_id, client)
    await catalog.async_load()
    try:
        await client.async_validate_key()
    except (AuthenticationError, AccessError) as err:
        raise ConfigEntryAuthFailed("OpenRouter rejected the API key") from err
    except (NetworkError, RateLimitError, ServerError) as err:
        if catalog.snapshot is None:
            raise ConfigEntryNotReady("OpenRouter is temporarily unavailable") from err

    try:
        await catalog.async_get(
            preserve_model_id=str(entry.options.get(CONF_MODEL, "")) or None,
            preserve_voice=str(entry.options.get(CONF_VOICE, "")) or None,
        )
    except (AuthenticationError, AccessError) as err:
        raise ConfigEntryAuthFailed("OpenRouter rejected the API key") from err
    except OpenRouterTTSError as err:
        raise ConfigEntryNotReady("The OpenRouter catalog is unavailable") from err

    root = str(entry.options.get(CONF_STORAGE_ROOT) or default_storage_root(hass))
    entry.runtime_data = OpenRouterRuntimeData(
        client=client,
        catalog=catalog,
        storage=SecureFileStore(root, hass.config.config_dir),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenRouterConfigEntry) -> bool:
    """Unload the TTS entity without touching generated files."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: OpenRouterConfigEntry) -> None:
    """Delete non-secret catalog metadata; saved audio is intentionally retained."""
    store = Store[dict[str, Any]](
        hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry.entry_id}"
    )
    await store.async_remove()
