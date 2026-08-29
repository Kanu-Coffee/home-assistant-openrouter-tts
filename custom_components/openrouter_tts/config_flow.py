"""Config and options flows for OpenRouter TTS."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import OpenRouterConfigEntry, default_storage_root
from .api import OpenRouterClient
from .catalog import (
    choose_recommended_model,
    filter_models,
    validate_model_voice,
)
from .const import (
    CONF_API_KEY,
    CONF_MODEL,
    CONF_MODEL_FILTER,
    CONF_SPEED,
    CONF_STORAGE_ROOT,
    CONF_VOICE,
    DEFAULT_SPEED,
    DOMAIN,
    MAX_SPEED,
    MIN_SPEED,
    MODEL_FILTER_ALL,
    MODEL_FILTER_FREE_ONLY,
    NAME,
)
from .exceptions import (
    AccessError,
    AuthenticationError,
    InvalidCatalogError,
    NetworkError,
    NoFreeModelsError,
    OpenRouterTTSError,
)
from .models import CatalogSnapshot, FreeStatus, TTSModel
from .storage import validate_storage_root

_LOGGER = logging.getLogger(__name__)


def _password_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def _text_selector() -> selector.TextSelector:
    return selector.TextSelector(selector.TextSelectorConfig(multiline=False))


def _select_selector(
    options: list[selector.SelectOptionDict],
) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _speed_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=MIN_SPEED,
            max=MAX_SPEED,
            step=0.05,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _flow_error(error: Exception) -> str:
    if isinstance(error, AuthenticationError):
        return "invalid_auth"
    if isinstance(error, AccessError):
        return "access_denied"
    if isinstance(error, InvalidCatalogError):
        return "no_tts_models"
    if isinstance(error, NetworkError):
        return "cannot_connect"
    if isinstance(error, OpenRouterTTSError):
        return error.translation_key
    return "unknown"


class _ModelLabelsMixin:
    hass: Any

    def _filter_options(self) -> list[selector.SelectOptionDict]:
        """Return locale-aware labels for the model-scope selector."""
        korean = str(self.hass.config.language).casefold().startswith("ko")
        return [
            {
                "value": MODEL_FILTER_ALL,
                "label": "전체 음성 모델" if korean else "All speech models",
            },
            {
                "value": MODEL_FILTER_FREE_ONLY,
                "label": (
                    "확인된 무료 모델만" if korean else "Verified free models only"
                ),
            },
        ]

    def _model_options(
        self, models: tuple[TTSModel, ...]
    ) -> list[selector.SelectOptionDict]:
        korean = str(self.hass.config.language).casefold().startswith("ko")
        options: list[selector.SelectOptionDict] = []
        for model in models:
            label = model.name
            if model.free_status is FreeStatus.FREE:
                label += " (무료)" if korean else " (Free)"
            if not model.available:
                label += (
                    " (사용 불가 · 저장된 설정)" if korean else " (Unavailable; saved)"
                )
            options.append({"value": model.model_id, "label": label})
        return options

    def _voice_options(
        self,
        model: TTSModel,
        *,
        preserve_voice: str | None = None,
    ) -> list[selector.SelectOptionDict]:
        korean = str(self.hass.config.language).casefold().startswith("ko")
        options: list[selector.SelectOptionDict] = []
        for voice in model.voices:
            if voice in model.unavailable_voices and voice != preserve_voice:
                continue
            label = voice
            if voice in model.unavailable_voices:
                label += (
                    " (사용 불가 · 유지 전용)"
                    if korean
                    else " (Unavailable; keep only)"
                )
            options.append({"value": voice, "label": label})
        return options


class OpenRouterTTSConfigFlow(
    _ModelLabelsMixin, config_entries.ConfigFlow, domain=DOMAIN
):
    """Create an OpenRouter TTS config entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key = ""
        self._models: tuple[TTSModel, ...] = ()
        self._selected_model = ""

    async def _validate_and_load(self, api_key: str) -> tuple[TTSModel, ...]:
        client = OpenRouterClient(async_get_clientsession(self.hass), api_key)
        await client.async_validate_key()
        return await client.async_fetch_catalog()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate the API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            api_key = str(user_input[CONF_API_KEY]).strip()
            try:
                self._models = await self._validate_and_load(api_key)
            except (
                Exception
            ) as err:  # Flow must convert all client failures to safe keys.
                errors["base"] = _flow_error(err)
                if errors["base"] == "unknown":
                    _LOGGER.warning(
                        "Unexpected error while validating OpenRouter settings "
                        "(type=%s)",
                        type(err).__name__,
                    )
            else:
                self._api_key = api_key
                model, _ = choose_recommended_model(self._models)
                self._selected_model = model.model_id
                return await self.async_step_model()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _password_selector()}),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a live speech model from the immutable setup snapshot."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = str(user_input[CONF_MODEL])
            if any(model.model_id == selected for model in self._models):
                self._selected_model = selected
                return await self.async_step_voice()
            errors["base"] = "model_not_found"

        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL, default=self._selected_model
                    ): _select_selector(self._model_options(self._models))
                }
            ),
            errors=errors,
        )

    async def async_step_voice(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Commit model, voice, speed, and root together."""
        model = next(
            item for item in self._models if item.model_id == self._selected_model
        )
        _, recommended_voice = choose_recommended_model((model,))
        errors: dict[str, str] = {}
        if user_input is not None:
            voice = str(user_input[CONF_VOICE])
            root = str(user_input[CONF_STORAGE_ROOT])
            try:
                validate_model_voice(self._models, self._selected_model, voice)
                validate_storage_root(root, self.hass.config.config_dir)
            except OpenRouterTTSError as err:
                errors["base"] = err.translation_key
            else:
                return self.async_create_entry(
                    title=NAME,
                    data={CONF_API_KEY: self._api_key},
                    options={
                        CONF_MODEL: self._selected_model,
                        CONF_VOICE: voice,
                        CONF_SPEED: float(user_input[CONF_SPEED]),
                        CONF_STORAGE_ROOT: root,
                        CONF_MODEL_FILTER: MODEL_FILTER_ALL,
                    },
                )

        return self.async_show_form(
            step_id="voice",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_VOICE, default=recommended_voice
                    ): _select_selector(self._voice_options(model)),
                    vol.Required(CONF_SPEED, default=DEFAULT_SPEED): _speed_selector(),
                    vol.Required(
                        CONF_STORAGE_ROOT, default=default_storage_root(self.hass)
                    ): _text_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start API key replacement."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate a replacement key before atomically updating the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = str(user_input[CONF_API_KEY]).strip()
            try:
                await self._validate_and_load(api_key)
            except Exception as err:
                errors["base"] = _flow_error(err)
                if errors["base"] == "unknown":
                    _LOGGER.warning(
                        "Unexpected error while reauthenticating OpenRouter (type=%s)",
                        type(err).__name__,
                    )
            else:
                entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _password_selector()}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: OpenRouterConfigEntry,
    ) -> OpenRouterTTSOptionsFlow:
        """Return the atomic options flow."""
        return OpenRouterTTSOptionsFlow()


class OpenRouterTTSOptionsFlow(_ModelLabelsMixin, config_entries.OptionsFlowWithReload):
    """Change behavior only after a complete model/voice transaction."""

    def __init__(self) -> None:
        self._snapshot: CatalogSnapshot | None = None
        self._filtered_models: tuple[TTSModel, ...] = ()
        self._selected_filter = MODEL_FILTER_ALL
        self._selected_model = ""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer configuration and an independent refresh action."""
        return self.async_show_menu(
            step_id="init", menu_options=["configure", "refresh"]
        )

    async def async_step_refresh(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Refresh price, free status, availability, and voices on demand."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self.config_entry
            try:
                snapshot = await entry.runtime_data.catalog.async_get(
                    force=True,
                    preserve_model_id=str(entry.options.get(CONF_MODEL, "")) or None,
                    preserve_voice=str(entry.options.get(CONF_VOICE, "")) or None,
                )
                if snapshot.stale:
                    raise NetworkError(
                        "Catalog refresh failed; the last good catalog was retained"
                    )
            except (AuthenticationError, AccessError) as err:
                entry.async_start_reauth(self.hass)
                errors["base"] = err.translation_key
            except OpenRouterTTSError as err:
                errors["base"] = err.translation_key
            else:
                return self.async_abort(
                    reason="catalog_refreshed",
                    description_placeholders={"count": str(len(snapshot.models))},
                )
        return self.async_show_form(
            step_id="refresh", data_schema=vol.Schema({}), errors=errors
        )

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose all models or only conservatively verified free models."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        if self._snapshot is None:
            try:
                self._snapshot = await entry.runtime_data.catalog.async_get(
                    preserve_model_id=str(entry.options.get(CONF_MODEL, "")) or None,
                    preserve_voice=str(entry.options.get(CONF_VOICE, "")) or None,
                )
            except OpenRouterTTSError as err:
                errors["base"] = err.translation_key

        if user_input is not None and self._snapshot is not None:
            requested_filter = str(user_input[CONF_MODEL_FILTER])
            try:
                self._filtered_models = filter_models(
                    self._snapshot.models,
                    free_only=requested_filter == MODEL_FILTER_FREE_ONLY,
                )
            except NoFreeModelsError:
                errors["base"] = "no_free_models"
            else:
                self._selected_filter = requested_filter
                current_model = str(entry.options.get(CONF_MODEL, ""))
                if any(
                    model.model_id == current_model for model in self._filtered_models
                ):
                    self._selected_model = current_model
                else:
                    self._selected_model = choose_recommended_model(
                        self._filtered_models
                    )[0].model_id
                return await self.async_step_model()

        current_filter = str(entry.options.get(CONF_MODEL_FILTER, MODEL_FILTER_ALL))
        return self.async_show_form(
            step_id="configure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL_FILTER, default=current_filter
                    ): _select_selector(self._filter_options())
                }
            ),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose one model from the snapshot selected in the prior step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = str(user_input[CONF_MODEL])
            if any(model.model_id == selected for model in self._filtered_models):
                self._selected_model = selected
                return await self.async_step_voice()
            errors["base"] = "model_not_found"
        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL, default=self._selected_model
                    ): _select_selector(self._model_options(self._filtered_models))
                }
            ),
            errors=errors,
        )

    async def async_step_voice(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and commit the model/voice/settings atomically."""
        assert self._snapshot is not None
        entry = self.config_entry
        model = next(
            item
            for item in self._filtered_models
            if item.model_id == self._selected_model
        )
        current_model = str(entry.options.get(CONF_MODEL, ""))
        current_voice = str(entry.options.get(CONF_VOICE, ""))
        preserving_pair = self._selected_model == current_model
        available_voices = self._voice_options(
            model, preserve_voice=current_voice if preserving_pair else None
        )
        default_voice = (
            current_voice
            if preserving_pair
            and any(item["value"] == current_voice for item in available_voices)
            else available_voices[0]["value"]
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            voice = str(user_input[CONF_VOICE])
            root = str(user_input[CONF_STORAGE_ROOT])
            try:
                validate_model_voice(
                    self._snapshot.models,
                    self._selected_model,
                    voice,
                    allow_preserved_unavailable=(
                        preserving_pair and voice == current_voice
                    ),
                )
                validate_storage_root(root, self.hass.config.config_dir)
            except OpenRouterTTSError as err:
                errors["base"] = err.translation_key
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **entry.options,
                        CONF_MODEL_FILTER: self._selected_filter,
                        CONF_MODEL: self._selected_model,
                        CONF_VOICE: voice,
                        CONF_SPEED: float(user_input[CONF_SPEED]),
                        CONF_STORAGE_ROOT: root,
                    },
                )

        return self.async_show_form(
            step_id="voice",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VOICE, default=default_voice): _select_selector(
                        available_voices
                    ),
                    vol.Required(
                        CONF_SPEED,
                        default=float(entry.options.get(CONF_SPEED, DEFAULT_SPEED)),
                    ): _speed_selector(),
                    vol.Required(
                        CONF_STORAGE_ROOT,
                        default=str(
                            entry.options.get(CONF_STORAGE_ROOT)
                            or default_storage_root(self.hass)
                        ),
                    ): _text_selector(),
                }
            ),
            errors=errors,
        )
