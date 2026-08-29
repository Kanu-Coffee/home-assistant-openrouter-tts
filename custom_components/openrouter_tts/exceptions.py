"""Safe, user-facing exceptions for OpenRouter TTS."""

from __future__ import annotations


class OpenRouterTTSError(Exception):
    """Base exception whose message is safe to expose to a user."""

    translation_key = "unknown"


class AuthenticationError(OpenRouterTTSError):
    """The API key was rejected."""

    translation_key = "invalid_auth"


class AccessError(OpenRouterTTSError):
    """The key cannot access the requested resource."""

    translation_key = "access_denied"


class InsufficientCreditsError(OpenRouterTTSError):
    """The account cannot fund this request."""

    translation_key = "insufficient_credits"


class ModelNotFoundError(OpenRouterTTSError):
    """The selected model is unavailable."""

    translation_key = "model_not_found"


class InvalidRequestError(OpenRouterTTSError):
    """OpenRouter rejected request parameters."""

    translation_key = "invalid_request"


class RateLimitError(OpenRouterTTSError):
    """OpenRouter rate limited the request."""

    translation_key = "rate_limited"

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(OpenRouterTTSError):
    """OpenRouter or an upstream provider failed."""

    translation_key = "server_error"


class NetworkError(OpenRouterTTSError):
    """A connection failure occurred."""

    translation_key = "cannot_connect"


class ConnectTimeoutError(NetworkError):
    """Connecting to OpenRouter timed out."""

    translation_key = "connect_timeout"


class ReadTimeoutError(NetworkError):
    """Waiting for OpenRouter timed out."""

    translation_key = "read_timeout"


class InvalidCatalogError(OpenRouterTTSError):
    """The model catalog was malformed."""

    translation_key = "invalid_catalog"


class InvalidAudioError(OpenRouterTTSError):
    """The response was not valid supported audio."""

    translation_key = "invalid_audio"


class AudioTooLargeError(InvalidAudioError):
    """The response exceeded the configured hard limit."""

    translation_key = "audio_too_large"


class UnsafePathError(OpenRouterTTSError):
    """A requested storage path was unsafe."""

    translation_key = "unsafe_path"


class FileAlreadyExistsError(OpenRouterTTSError):
    """The destination exists and overwrite was not enabled."""

    translation_key = "file_exists"


class StorageError(OpenRouterTTSError):
    """The filesystem could not complete a safe save or delete operation."""

    translation_key = "storage_error"


class ModelVoiceMismatchError(OpenRouterTTSError):
    """The selected model does not advertise the selected voice."""

    translation_key = "model_voice_mismatch"


class NoFreeModelsError(OpenRouterTTSError):
    """No conservatively verified free TTS models are available."""

    translation_key = "no_free_models"
