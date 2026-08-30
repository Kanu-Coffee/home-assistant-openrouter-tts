"""Asynchronous OpenRouter API client using Home Assistant's shared session."""

from __future__ import annotations

import asyncio
import email.utils
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import aiohttp

from .audio import normalize_audio_response
from .capabilities import is_provider_default_voice_selection
from .catalog import parse_catalog_payload
from .const import (
    API_BASE_URL,
    API_KEY_PATH,
    CATALOG_READ_TIMEOUT_SECONDS,
    CATALOG_RETRY_ATTEMPTS,
    CONNECT_TIMEOUT_SECONDS,
    MAX_AUDIO_BYTES,
    MAX_INPUT_LENGTH,
    MODELS_PATH,
    PROJECT_URL,
    PROVIDER_DEFAULT_VOICE_ID,
    READ_TIMEOUT_SECONDS,
    SPEECH_PATH,
    USER_AGENT,
)
from .exceptions import (
    AccessError,
    AudioTooLargeError,
    AuthenticationError,
    ConnectTimeoutError,
    InsufficientCreditsError,
    InvalidCatalogError,
    InvalidRequestError,
    ModelNotFoundError,
    NetworkError,
    RateLimitError,
    ReadTimeoutError,
    ServerError,
)
from .models import AudioResult, TTSModel

_MAX_CATALOG_BYTES = 4 * 1024 * 1024
_MAX_RETRY_AFTER_SECONDS = 30.0


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (parsed - datetime.now(UTC)).total_seconds())


class OpenRouterClient:
    """Minimal secret-safe OpenRouter client."""

    __slots__ = ("_api_key", "_base_url", "_session")

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        *,
        base_url: str = API_BASE_URL,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self._base_url!r}, api_key=<redacted>)"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": PROJECT_URL,
            "X-OpenRouter-Title": "OpenRouter TTS for Home Assistant (unofficial)",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

    async def _read_limited(
        self, response: aiohttp.ClientResponse, limit: int
    ) -> bytes:
        declared = response.content_length
        if declared is not None and declared > limit:
            raise AudioTooLargeError(f"The response exceeded the {limit} byte limit")
        data = bytearray()
        async for chunk in response.content.iter_chunked(64 * 1024):
            if len(data) + len(chunk) > limit:
                raise AudioTooLargeError(
                    f"The response exceeded the {limit} byte limit"
                )
            data.extend(chunk)
        return bytes(data)

    @staticmethod
    def _raise_for_status(response: aiohttp.ClientResponse) -> None:
        status = response.status
        if 200 <= status < 300:
            return
        if status == 401:
            raise AuthenticationError("OpenRouter rejected the API key")
        if status == 403:
            raise AccessError("The API key cannot access this OpenRouter resource")
        if status == 402:
            raise InsufficientCreditsError(
                "The OpenRouter account does not have sufficient credits"
            )
        if status == 404:
            raise ModelNotFoundError("The requested OpenRouter model was not found")
        if status in (400, 409, 422):
            raise InvalidRequestError(
                f"OpenRouter rejected the request parameters (HTTP {status})"
            )
        if status == 429:
            retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
            raise RateLimitError("OpenRouter rate limited the request", retry_after)
        if status == 408:
            raise ReadTimeoutError("OpenRouter timed out while processing the request")
        if 500 <= status <= 599:
            raise ServerError(f"OpenRouter or its provider failed (HTTP {status})")
        raise ServerError(f"OpenRouter returned an unexpected HTTP status ({status})")

    async def _request_json_once(
        self, path: str, *, read_timeout: float, params: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        timeout = aiohttp.ClientTimeout(
            total=CONNECT_TIMEOUT_SECONDS + read_timeout + 5,
            connect=CONNECT_TIMEOUT_SECONDS,
            sock_connect=CONNECT_TIMEOUT_SECONDS,
            sock_read=read_timeout,
        )
        try:
            async with self._session.get(
                f"{self._base_url}{path}",
                headers=self._headers,
                params=params,
                timeout=timeout,
                allow_redirects=False,
            ) as response:
                self._raise_for_status(response)
                try:
                    raw = await self._read_limited(response, _MAX_CATALOG_BYTES)
                except AudioTooLargeError as err:
                    raise InvalidCatalogError(
                        "OpenRouter returned oversized JSON metadata"
                    ) from err
        except aiohttp.ConnectionTimeoutError:
            raise ConnectTimeoutError("Connecting to OpenRouter timed out") from None
        except aiohttp.SocketTimeoutError:
            raise ReadTimeoutError("Waiting for OpenRouter timed out") from None
        except TimeoutError:
            raise ReadTimeoutError(
                "The OpenRouter request exceeded its time limit"
            ) from None
        except aiohttp.ClientConnectionError:
            raise NetworkError("Could not connect to OpenRouter") from None
        except aiohttp.ClientError:
            raise NetworkError("The OpenRouter HTTP request failed") from None

        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InvalidCatalogError(
                "OpenRouter returned invalid JSON metadata"
            ) from None
        if not isinstance(parsed, Mapping):
            raise InvalidCatalogError("OpenRouter returned an invalid JSON object")
        return parsed

    async def async_validate_key(self) -> None:
        """Validate authentication without exposing account or balance data."""
        await self._request_json_once(
            API_KEY_PATH, read_timeout=CATALOG_READ_TIMEOUT_SECONDS
        )

    async def async_fetch_catalog(self) -> tuple[TTSModel, ...]:
        """Fetch the speech catalog with limited retries and Retry-After support."""
        last_error: Exception | None = None
        for attempt in range(CATALOG_RETRY_ATTEMPTS):
            try:
                payload = await self._request_json_once(
                    MODELS_PATH,
                    read_timeout=CATALOG_READ_TIMEOUT_SECONDS,
                    params={"output_modalities": "speech"},
                )
                return parse_catalog_payload(payload)
            except (AuthenticationError, AccessError, InvalidCatalogError):
                raise
            except (NetworkError, RateLimitError, ServerError) as err:
                last_error = err
                if attempt + 1 >= CATALOG_RETRY_ATTEMPTS:
                    raise
                retry_after = (
                    err.retry_after if isinstance(err, RateLimitError) else None
                )
                if retry_after is not None and retry_after > _MAX_RETRY_AFTER_SECONDS:
                    raise
                await asyncio.sleep(
                    retry_after if retry_after is not None else 0.5 * 2**attempt
                )
        assert last_error is not None
        raise last_error

    async def async_generate_speech(
        self,
        *,
        text: str,
        model: TTSModel,
        voice: str,
        speed: float,
        response_format: str = "mp3",
    ) -> AudioResult:
        """Generate once; potentially billable requests are never retried."""
        if not text or len(text) > MAX_INPUT_LENGTH:
            raise InvalidRequestError(
                f"Speech text must contain 1 to {MAX_INPUT_LENGTH} characters"
            )
        if voice not in model.voices:
            raise InvalidRequestError(
                "The selected voice is not supported by the model"
            )
        requested_format = "pcm" if response_format.casefold() == "wav" else "mp3"
        payload: dict[str, Any] = {
            "model": model.model_id,
            "input": text,
            "response_format": requested_format,
        }
        if voice == PROVIDER_DEFAULT_VOICE_ID:
            if (
                not model.provider_default_voice
                or not is_provider_default_voice_selection(model.model_id, voice)
            ):
                raise InvalidRequestError(
                    "The provider-default voice is not supported by the model"
                )
        else:
            payload["voice"] = voice
        if model.supports_speed and speed != 1.0:
            payload["speed"] = speed

        headers = self._headers | {
            "Accept": "audio/mpeg, audio/wav, audio/pcm, application/octet-stream",
            # Disable additional HTTP content coding for deterministic binary
            # handling across Home Assistant runtime codec sets.
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(
            total=CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS + 10,
            connect=CONNECT_TIMEOUT_SECONDS,
            sock_connect=CONNECT_TIMEOUT_SECONDS,
            sock_read=READ_TIMEOUT_SECONDS,
        )
        try:
            async with self._session.post(
                f"{self._base_url}{SPEECH_PATH}",
                headers=headers,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
            ) as response:
                self._raise_for_status(response)
                raw = await self._read_limited(response, MAX_AUDIO_BYTES)
                content_type = response.headers.get("Content-Type")
                response_headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key.casefold()
                    in {"x-generation-id", "x-audio-sample-rate", "x-sample-rate"}
                }
        except aiohttp.ConnectionTimeoutError:
            raise ConnectTimeoutError("Connecting to OpenRouter timed out") from None
        except aiohttp.SocketTimeoutError:
            raise ReadTimeoutError(
                "OpenRouter timed out; the generation was not retried because it may "
                "be billable"
            ) from None
        except TimeoutError:
            raise ReadTimeoutError(
                "OpenRouter timed out; the generation was not retried because it may "
                "be billable"
            ) from None
        except aiohttp.ClientConnectionError:
            raise NetworkError(
                "The connection ended; generation was not retried because it may be "
                "billable"
            ) from None
        except aiohttp.ClientError:
            raise NetworkError("The OpenRouter speech request failed") from None

        return normalize_audio_response(
            raw,
            content_type=content_type,
            requested_format=requested_format,
            headers=response_headers,
            capabilities=model.audio,
        )
