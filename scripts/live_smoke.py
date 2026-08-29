#!/usr/bin/env python3
"""Manual, secret-safe OpenRouter smoke test with at most one free generation."""

from __future__ import annotations

import asyncio
import logging
import os

import aiohttp

from custom_components.openrouter_tts.api import OpenRouterClient
from custom_components.openrouter_tts.catalog import filter_models
from custom_components.openrouter_tts.exceptions import NoFreeModelsError

_LOGGER = logging.getLogger("openrouter_tts.live_smoke")


async def _run() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is required")
    generate_free = os.environ.get("GENERATE_FREE_TTS", "false").casefold() == "true"

    async with aiohttp.ClientSession() as session:
        client = OpenRouterClient(session, api_key)
        await client.async_validate_key()
        models = await client.async_fetch_catalog()
        _LOGGER.info(
            "Validated key and loaded %d voice-capable speech models", len(models)
        )
        if not generate_free:
            _LOGGER.info("No speech generation was requested")
            return

        try:
            free_models = filter_models(models, free_only=True)
        except NoFreeModelsError as err:
            raise SystemExit(
                "No conservatively verified free speech model is available; "
                "no generation request was sent"
            ) from err
        model = min(free_models, key=lambda item: item.model_id)
        voice = model.voices[0]
        result = await client.async_generate_speech(
            text="Test.",
            model=model,
            voice=voice,
            speed=1.0,
            response_format="mp3",
        )
        _LOGGER.info(
            "Completed one verified-free generation: "
            "model=%s, voice=%s, format=%s, bytes=%d",
            model.model_id,
            voice,
            result.extension,
            len(result.data),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(_run())
