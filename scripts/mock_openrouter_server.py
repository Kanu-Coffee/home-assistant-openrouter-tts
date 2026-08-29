#!/usr/bin/env python3
"""Local OpenRouter-shaped server for Docker and HAOS integration tests."""

from __future__ import annotations

import argparse
import io
import logging
import wave

from aiohttp import web

_LOGGER = logging.getLogger("openrouter_tts.mock_server")
_VALID_AUTHORIZATION = "Bearer mock-test-key"


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\x00\x00" * 2_400)
    return output.getvalue()


@web.middleware
async def _redacted_request_log(
    request: web.Request, handler: web.RequestHandler
) -> web.StreamResponse:
    response = await handler(request)
    _LOGGER.info("%s %s -> %d", request.method, request.path, response.status)
    return response


def _authorized(request: web.Request) -> bool:
    return request.headers.get("Authorization") == _VALID_AUTHORIZATION


async def _key(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.json_response(
            {"error": {"code": 401, "message": "invalid test credential"}},
            status=401,
        )
    return web.json_response({"data": {"label": "HAOS mock key"}})


async def _models(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.json_response(
            {"error": {"code": 401, "message": "invalid test credential"}},
            status=401,
        )
    return web.json_response(
        {
            "data": [
                {
                    "id": "test/mock-speech:free",
                    "name": "Mock speech",
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["speech"],
                    },
                    "supported_voices": ["TestVoice", "SecondVoice"],
                    "supported_parameters": ["speed"],
                    "pricing": {"prompt": "0", "completion": "0"},
                }
            ]
        }
    )


async def _speech(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.json_response(
            {"error": {"code": 401, "message": "invalid test credential"}},
            status=401,
        )
    payload = await request.json()
    if payload.get("model") != "test/mock-speech:free" or payload.get("voice") not in {
        "TestVoice",
        "SecondVoice",
    }:
        return web.json_response(
            {"error": {"code": 422, "message": "invalid mock selection"}},
            status=422,
        )
    return web.Response(
        body=_wav_bytes(),
        content_type="audio/wav",
        headers={"X-Generation-Id": "mock-generation"},
    )


def _application() -> web.Application:
    application = web.Application(middlewares=[_redacted_request_log])
    application.router.add_get("/api/v1/key", _key)
    application.router.add_get("/api/v1/models", _models)
    application.router.add_post("/api/v1/audio/speech", _speech)
    return application


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8766, type=int)
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    arguments = _parse_args()
    web.run_app(
        _application(),
        host=arguments.host,
        port=arguments.port,
        print=None,
        access_log=None,
    )
