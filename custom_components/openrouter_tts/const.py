"""Constants for the OpenRouter TTS integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "openrouter_tts"
NAME: Final = "OpenRouter TTS"
VERSION: Final = "0.1.0-beta.1"

CONF_API_KEY: Final = "api_key"
CONF_MODEL: Final = "model"
CONF_VOICE: Final = "voice"
CONF_SPEED: Final = "speed"
CONF_STORAGE_ROOT: Final = "storage_root"
CONF_MODEL_FILTER: Final = "model_filter"

MODEL_FILTER_ALL: Final = "all"
MODEL_FILTER_FREE_ONLY: Final = "free_only"

DEFAULT_SPEED: Final = 1.0
MIN_SPEED: Final = 0.5
MAX_SPEED: Final = 2.0
DEFAULT_LANGUAGE: Final = "en"
SUPPORTED_LANGUAGES: Final = ["en", "ko"]

API_BASE_URL: Final = "https://openrouter.ai/api/v1"
API_KEY_PATH: Final = "/key"
MODELS_PATH: Final = "/models"
SPEECH_PATH: Final = "/audio/speech"
CATALOG_TTL: Final = timedelta(hours=6)
CATALOG_RETRY_ATTEMPTS: Final = 3
CONNECT_TIMEOUT_SECONDS: Final = 10.0
READ_TIMEOUT_SECONDS: Final = 90.0
CATALOG_READ_TIMEOUT_SECONDS: Final = 30.0
MAX_AUDIO_BYTES: Final = 20 * 1024 * 1024
MAX_INPUT_LENGTH: Final = 4096

PROJECT_URL: Final = "https://github.com/Kanu-Coffee/home-assistant-openrouter-tts"
USER_AGENT: Final = f"{NAME}/{VERSION} ({PROJECT_URL})"

PLATFORMS: Final = ["tts"]

SERVICE_GENERATE_FILE: Final = "generate_file"
SERVICE_DELETE_FILE: Final = "delete_file"
SERVICE_REFRESH_CATALOG: Final = "refresh_catalog"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_TEXT: Final = "text"
ATTR_FILENAME: Final = "filename"
ATTR_SUBDIRECTORY: Final = "subdirectory"
ATTR_FORMAT: Final = "format"
ATTR_OVERWRITE: Final = "overwrite"

STORAGE_VERSION: Final = 1
STORAGE_KEY_PREFIX: Final = f"{DOMAIN}.catalog"
