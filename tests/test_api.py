"""Tests for the secret-safe asynchronous OpenRouter API client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, call

import aiohttp
import pytest
from aiohttp import web

from custom_components.openrouter_tts import api as api_module
from custom_components.openrouter_tts.api import OpenRouterClient
from custom_components.openrouter_tts.const import (
    API_KEY_PATH,
    MAX_INPUT_LENGTH,
    MODELS_PATH,
    SPEECH_PATH,
)
from custom_components.openrouter_tts.exceptions import (
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
from custom_components.openrouter_tts.models import FreeStatus, TTSModel

_BASE_URL = "https://openrouter.invalid/api/v1"
_KEY_URL = f"{_BASE_URL}{API_KEY_PATH}"
_CATALOG_URL = f"{_BASE_URL}{MODELS_PATH}"
_SPEECH_URL = f"{_BASE_URL}{SPEECH_PATH}"
_API_KEY = "unit-test-api-key-not-real"


class _FakeContent:
    """Small StreamReader stand-in with controllable chunks and read failures."""

    def __init__(
        self,
        chunks: tuple[bytes, ...],
        *,
        read_error: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self._read_error = read_error

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            for offset in range(0, len(chunk), size):
                yield chunk[offset : offset + size]
        if self._read_error is not None:
            raise self._read_error


class _FakeResponse:
    """Minimal response surface consumed by OpenRouterClient."""

    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        chunks: tuple[bytes, ...] | None = None,
        headers: Mapping[str, str] | None = None,
        content_length: int | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self.content_length = content_length
        self.content = _FakeContent(
            chunks if chunks is not None else (body,),
            read_error=read_error,
        )


class _FakeRequestContext:
    """Async context manager returned by the fake session methods."""

    def __init__(self, result: _FakeResponse | Exception) -> None:
        self._result = result

    async def __aenter__(self) -> _FakeResponse:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def __aexit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        return None


@dataclass(slots=True)
class _RecordedRequest:
    method: str
    url: str
    kwargs: dict[str, Any]


class _FakeSession:
    """Queue responses while recording every request without network access."""

    def __init__(self) -> None:
        self._results: list[_FakeResponse | Exception] = []
        self.requests: list[_RecordedRequest] = []

    def queue(self, *results: _FakeResponse | Exception) -> None:
        self._results.extend(results)

    def _request(self, method: str, url: str, **kwargs: Any) -> _FakeRequestContext:
        self.requests.append(_RecordedRequest(method, url, kwargs))
        if not self._results:
            raise AssertionError(f"Unexpected {method} request to {url}")
        return _FakeRequestContext(self._results.pop(0))

    def get(self, url: str, **kwargs: Any) -> _FakeRequestContext:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> _FakeRequestContext:
        return self._request("POST", url, **kwargs)


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


def _client(session: _FakeSession, *, api_key: str = _API_KEY) -> OpenRouterClient:
    return OpenRouterClient(session, api_key, base_url=_BASE_URL)  # type: ignore[arg-type]


def _model(*, supports_speed: bool = False) -> TTSModel:
    return TTSModel(
        model_id="provider/speech-model",
        name="Speech model",
        voices=("Voice One",),
        free_status=FreeStatus.UNKNOWN,
        supported_parameters=(frozenset({"speed"}) if supports_speed else frozenset()),
    )


def _catalog_payload(*, padding: str = "") -> dict[str, object]:
    return {
        "data": [
            {
                "id": "provider/speech-model",
                "name": "Speech model",
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["speech"],
                },
                "supported_voices": ["Voice One"],
                "supported_parameters": ["speed"],
                "pricing": {"prompt": "0", "completion": "0"},
            }
        ],
        "padding": padding,
    }


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload).encode()


def _json_response(payload: Mapping[str, object]) -> _FakeResponse:
    return _FakeResponse(
        body=_json_bytes(payload),
        headers={"Content-Type": "application/json"},
    )


def _mp3_bytes(size: int = 417) -> bytes:
    """Return a valid MPEG-1 Layer III frame followed by optional padding."""
    if size < 417:
        raise ValueError("An MP3 test body must contain one complete frame")
    return b"\xff\xfb\x90\x64" + (b"\x00" * (size - 4))


async def test_validate_key_uses_expected_secret_bearing_header(
    session: _FakeSession,
) -> None:
    """Key validation uses the key endpoint and never puts the key in the URL."""
    session.queue(_json_response({"data": {"label": "test key"}}))
    client = _client(session)

    await client.async_validate_key()

    request = session.requests[0]
    assert request.method == "GET"
    assert request.url == _KEY_URL
    assert request.kwargs["headers"]["Authorization"] == f"Bearer {_API_KEY}"
    assert request.kwargs["allow_redirects"] is False
    assert _API_KEY not in request.url


async def test_fetch_catalog_accumulates_a_multichunk_json_response(
    session: _FakeSession,
) -> None:
    """Catalog metadata split across read chunks is accumulated and parsed."""
    raw = _json_bytes(_catalog_payload(padding="x" * (70 * 1024)))
    session.queue(
        _FakeResponse(
            chunks=(raw[:100], raw[100:65_536], raw[65_536:]),
            headers={"Content-Type": "application/json"},
        )
    )
    client = _client(session)

    models = await client.async_fetch_catalog()

    assert len(models) == 1
    assert models[0].model_id == "provider/speech-model"
    assert models[0].voices == ("Voice One",)
    request = session.requests[0]
    assert request.method == "GET"
    assert request.url == _CATALOG_URL
    assert request.kwargs["params"] == {"output_modalities": "speech"}
    assert request.kwargs["allow_redirects"] is False


async def test_generate_speech_accumulates_audio_chunks_and_metadata(
    session: _FakeSession,
) -> None:
    """Audio split across multiple read chunks is returned completely."""
    audio = _mp3_bytes(70 * 1024)
    session.queue(
        _FakeResponse(
            chunks=(audio[:200], audio[200:65_536], audio[65_536:]),
            headers={
                "Content-Type": "audio/mpeg",
                "X-Generation-Id": "generation-123",
            },
        )
    )
    client = _client(session)

    result = await client.async_generate_speech(
        text="Read this aloud",
        model=_model(),
        voice="Voice One",
        speed=1.0,
    )

    assert result.data == audio
    assert len(result.data) == 70 * 1024
    assert result.extension == "mp3"
    assert result.content_type == "audio/mpeg"
    assert result.generation_id == "generation-123"
    request = session.requests[0]
    assert request.kwargs["allow_redirects"] is False
    assert request.kwargs["headers"]["Accept-Encoding"] == "identity"


async def test_generation_forces_identity_content_encoding_on_wire(
    aiohttp_server: Any,
    socket_enabled: None,
) -> None:
    """The HA session codec set cannot alter the explicit wire-coding request."""
    received_encodings: list[list[str]] = []
    request_count = 0

    async def speech(request: web.Request) -> web.Response:
        nonlocal request_count
        request_count += 1
        received_encodings.append(request.headers.getall("Accept-Encoding", []))
        await request.json()
        return web.Response(body=_mp3_bytes(), content_type="audio/mpeg")

    app = web.Application()
    app.router.add_post("/api/v1/audio/speech", speech)
    server = await aiohttp_server(app)

    async with aiohttp.ClientSession() as client_session:
        client = OpenRouterClient(
            client_session,
            "wire-header-key",
            base_url=str(server.make_url("/api/v1")),
        )
        result = await client.async_generate_speech(
            text="Wire header test",
            model=_model(),
            voice="Voice One",
            speed=1.0,
        )

    assert result.extension == "mp3"
    assert request_count == 1
    assert received_encodings == [["identity"]]


async def test_generation_redirect_does_not_replay_private_input(
    aiohttp_server: Any,
    socket_enabled: None,
) -> None:
    """A 307 cannot resend a potentially billable body to another origin."""
    forwarded_payloads: list[object] = []

    async def receive_redirect(request: web.Request) -> web.Response:
        forwarded_payloads.append(await request.json())
        return web.Response(status=418)

    sink_app = web.Application()
    sink_app.router.add_post("/sink", receive_redirect)
    sink_server = await aiohttp_server(sink_app)

    async def redirect_generation(_request: web.Request) -> web.Response:
        return web.Response(
            status=307,
            headers={"Location": str(sink_server.make_url("/sink"))},
        )

    source_app = web.Application()
    source_app.router.add_post("/api/v1/audio/speech", redirect_generation)
    source_server = await aiohttp_server(source_app)
    api_key = "redirect-key-sentinel"
    text = "redirect-private-input-sentinel"

    async with aiohttp.ClientSession() as client_session:
        client = OpenRouterClient(
            client_session,
            api_key,
            base_url=str(source_server.make_url("/api/v1")),
        )
        with pytest.raises(ServerError, match="307") as caught:
            await client.async_generate_speech(
                text=text,
                model=_model(),
                voice="Voice One",
                speed=1.0,
            )

    assert forwarded_payloads == []
    assert caught.value.__cause__ is None
    assert api_key not in repr(caught.value)
    assert text not in repr(caught.value)


async def test_key_redirect_loop_does_not_retain_authorization_in_error(
    aiohttp_server: Any,
    socket_enabled: None,
) -> None:
    """A key-endpoint redirect is rejected before aiohttp records secret history."""
    requests = 0

    async def redirect_key(_request: web.Request) -> web.Response:
        nonlocal requests
        requests += 1
        return web.Response(status=302, headers={"Location": "/api/v1/key"})

    app = web.Application()
    app.router.add_get("/api/v1/key", redirect_key)
    server = await aiohttp_server(app)
    api_key = "redirect-loop-key-sentinel"

    async with aiohttp.ClientSession() as client_session:
        client = OpenRouterClient(
            client_session,
            api_key,
            base_url=str(server.make_url("/api/v1")),
        )
        with pytest.raises(ServerError, match="302") as caught:
            await client.async_validate_key()

    assert requests == 1
    assert caught.value.__cause__ is None
    assert api_key not in repr(caught.value)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AuthenticationError),
        (403, AccessError),
        (402, InsufficientCreditsError),
        (404, ModelNotFoundError),
        (422, InvalidRequestError),
        (429, RateLimitError),
        (500, ServerError),
        (503, ServerError),
        (599, ServerError),
    ],
)
async def test_http_statuses_map_to_specific_safe_errors(
    session: _FakeSession,
    status: int,
    error_type: type[Exception],
) -> None:
    """Documented authentication, billing, request, and provider statuses map safely."""
    session.queue(_FakeResponse(status=status, headers={"Retry-After": "7"}))
    client = _client(session)

    with pytest.raises(error_type) as caught:
        await client.async_validate_key()

    if isinstance(caught.value, RateLimitError):
        assert caught.value.retry_after == 7.0


@pytest.mark.parametrize(
    ("transport_error", "error_type"),
    [
        (aiohttp.ConnectionTimeoutError(), ConnectTimeoutError),
        (aiohttp.SocketTimeoutError(), ReadTimeoutError),
        (TimeoutError(), ReadTimeoutError),
        (aiohttp.ClientConnectionError("offline"), NetworkError),
        (aiohttp.ClientError("broken request"), NetworkError),
    ],
    ids=[
        "connect-timeout",
        "socket-read-timeout",
        "total-timeout",
        "connection-error",
        "client-error",
    ],
)
async def test_transport_failures_map_to_api_errors(
    session: _FakeSession,
    transport_error: Exception,
    error_type: type[Exception],
) -> None:
    """aiohttp connection and timeout failures are translated for callers."""
    session.queue(transport_error)
    client = _client(session)

    with pytest.raises(error_type):
        await client.async_validate_key()


async def test_catalog_retries_only_the_configured_number_of_times(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient catalog failures use bounded exponential retries."""
    sleep = AsyncMock()
    monkeypatch.setattr(api_module.asyncio, "sleep", sleep)
    session.queue(*(_FakeResponse(status=503) for _ in range(3)))
    client = _client(session)

    with pytest.raises(ServerError):
        await client.async_fetch_catalog()

    assert len(session.requests) == 3
    assert sleep.await_args_list == [call(0.5), call(1.0)]


async def test_catalog_honors_a_short_retry_after_delay(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short server-specified retry delay is used before a successful retry."""
    sleep = AsyncMock()
    monkeypatch.setattr(api_module.asyncio, "sleep", sleep)
    session.queue(
        _FakeResponse(status=429, headers={"Retry-After": "0.25"}),
        _json_response(_catalog_payload()),
    )
    client = _client(session)

    models = await client.async_fetch_catalog()

    assert models[0].model_id == "provider/speech-model"
    assert len(session.requests) == 2
    sleep.assert_awaited_once_with(0.25)


async def test_catalog_does_not_wait_or_retry_for_a_long_retry_after(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry-After values over the safety cap fail immediately."""
    sleep = AsyncMock()
    monkeypatch.setattr(api_module.asyncio, "sleep", sleep)
    session.queue(_FakeResponse(status=429, headers={"Retry-After": "30.01"}))
    client = _client(session)

    with pytest.raises(RateLimitError) as caught:
        await client.async_fetch_catalog()

    assert caught.value.retry_after == 30.01
    assert len(session.requests) == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(429, RateLimitError), (503, ServerError)],
)
async def test_generation_status_failures_are_never_retried(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    error_type: type[Exception],
) -> None:
    """Potentially billable speech POSTs are attempted once for transient statuses."""
    sleep = AsyncMock()
    monkeypatch.setattr(api_module.asyncio, "sleep", sleep)
    session.queue(_FakeResponse(status=status, headers={"Retry-After": "0.01"}))
    client = _client(session)

    with pytest.raises(error_type):
        await client.async_generate_speech(
            text="One billable request",
            model=_model(),
            voice="Voice One",
            speed=1.0,
        )

    assert len(session.requests) == 1
    sleep.assert_not_awaited()


async def test_generation_read_timeout_is_mapped_without_retry(
    session: _FakeSession,
) -> None:
    """An ambiguous body-read timeout reports that generation was not retried."""
    session.queue(
        _FakeResponse(
            headers={"Content-Type": "audio/mpeg"},
            read_error=aiohttp.SocketTimeoutError(),
        )
    )
    client = _client(session)

    with pytest.raises(ReadTimeoutError, match="not retried"):
        await client.async_generate_speech(
            text="One billable request",
            model=_model(),
            voice="Voice One",
            speed=1.0,
        )

    assert len(session.requests) == 1


@pytest.mark.parametrize(
    ("supports_speed", "speed", "expected_speed"),
    [
        (True, 1.0, None),
        (False, 1.5, None),
        (True, 1.5, 1.5),
    ],
)
async def test_speed_is_sent_only_when_supported_and_non_default(
    session: _FakeSession,
    supports_speed: bool,
    speed: float,
    expected_speed: float | None,
) -> None:
    """The optional speed field follows explicit model capabilities."""
    session.queue(
        _FakeResponse(
            body=_mp3_bytes(),
            headers={"Content-Type": "audio/mpeg"},
        )
    )
    client = _client(session)

    await client.async_generate_speech(
        text="Speed payload",
        model=_model(supports_speed=supports_speed),
        voice="Voice One",
        speed=speed,
    )

    payload = session.requests[0].kwargs["json"]
    if expected_speed is None:
        assert "speed" not in payload
    else:
        assert payload["speed"] == expected_speed


@pytest.mark.parametrize("declared_size", [False, True], ids=["streamed", "declared"])
async def test_audio_response_size_is_limited_before_normalization(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    declared_size: bool,
) -> None:
    """Both Content-Length and accumulated bytes enforce the audio safety limit."""
    monkeypatch.setattr(api_module, "MAX_AUDIO_BYTES", 8)
    session.queue(
        _FakeResponse(
            body=_mp3_bytes(),
            headers={"Content-Type": "audio/mpeg"},
            content_length=417 if declared_size else None,
        )
    )
    client = _client(session)

    with pytest.raises(AudioTooLargeError):
        await client.async_generate_speech(
            text="Bound this response",
            model=_model(),
            voice="Voice One",
            speed=1.0,
        )


async def test_oversized_catalog_is_invalid_and_is_not_retried(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The metadata limit is translated to InvalidCatalogError without retrying."""
    monkeypatch.setattr(api_module, "_MAX_CATALOG_BYTES", 8)
    session.queue(
        _FakeResponse(
            body=b'{"data": []}',
            headers={"Content-Type": "application/json"},
            content_length=12,
        )
    )
    client = _client(session)

    with pytest.raises(InvalidCatalogError):
        await client.async_fetch_catalog()

    assert len(session.requests) == 1


@pytest.mark.parametrize(
    ("text", "voice"),
    [
        ("", "Voice One"),
        ("x" * (MAX_INPUT_LENGTH + 1), "Voice One"),
        ("valid text", "Unknown Voice"),
    ],
    ids=["empty-input", "long-input", "unsupported-voice"],
)
async def test_invalid_generation_input_fails_before_network_access(
    session: _FakeSession,
    text: str,
    voice: str,
) -> None:
    """Local input validation cannot create a potentially billable request."""
    client = _client(session)

    with pytest.raises(InvalidRequestError):
        await client.async_generate_speech(
            text=text,
            model=_model(),
            voice=voice,
            speed=1.0,
        )

    assert session.requests == []


async def test_api_key_and_input_are_absent_from_repr_errors_and_logs(
    session: _FakeSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Secret request values never escape through user-visible diagnostics."""
    api_key = "secret-key-that-must-not-leak"
    text = "private speech input that must not leak"
    session.queue(
        _FakeResponse(
            status=422,
            body=f'{{"error": {text!r}, "key": {api_key!r}}}'.encode(),
            headers={"Content-Type": "application/json"},
        )
    )
    client = _client(session, api_key=api_key)

    assert api_key not in repr(client)
    assert "api_key=<redacted>" in repr(client)

    with pytest.raises(InvalidRequestError) as caught:
        await client.async_generate_speech(
            text=text,
            model=_model(),
            voice="Voice One",
            speed=1.0,
        )

    diagnostics = f"{caught.value!s}\n{caught.value!r}\n{caplog.text}"
    assert api_key not in diagnostics
    assert text not in diagnostics
