"""Tests for speech catalog parsing, filtering, and stale preservation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, ClassVar

import pytest

from custom_components.openrouter_tts import catalog as catalog_module
from custom_components.openrouter_tts.catalog import (
    CatalogManager,
    filter_models,
    parse_catalog_payload,
    validate_model_voice,
)
from custom_components.openrouter_tts.const import (
    FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
    PROVIDER_DEFAULT_VOICE_ID,
)
from custom_components.openrouter_tts.exceptions import (
    AuthenticationError,
    InvalidCatalogError,
    ModelVoiceMismatchError,
    NetworkError,
    NoFreeModelsError,
)
from custom_components.openrouter_tts.models import FreeStatus, TTSModel


def _raw_model(
    model_id: str,
    *,
    input_modalities: list[str] | None = None,
    output_modalities: list[str] | None = None,
    voices: object = ("Voice One",),
    pricing: Mapping[str, object] | None = None,
    modality: str | None = None,
) -> dict[str, Any]:
    architecture: dict[str, Any] = {
        "input_modalities": input_modalities or ["text"],
        "output_modalities": output_modalities or ["speech"],
    }
    if modality is not None:
        architecture["modality"] = modality
    return {
        "id": model_id,
        "name": f"Name for {model_id}",
        "architecture": architecture,
        "supported_voices": voices,
        "supported_parameters": ["speed", "speed", "ignored"],
        "pricing": pricing
        if pricing is not None
        else {"prompt": "0", "completion": "0"},
    }


def _model(
    model_id: str,
    voices: tuple[str, ...] = ("Voice One",),
    *,
    status: FreeStatus = FreeStatus.UNKNOWN,
) -> TTSModel:
    return TTSModel(
        model_id=model_id,
        name=model_id,
        voices=voices,
        free_status=status,
        pricing={"prompt": "0", "completion": "0"},
    )


class _MemoryStore:
    """Minimal async replacement for Home Assistant Store."""

    values: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def __class_getitem__(cls, _item: object) -> type[_MemoryStore]:
        return cls

    def __init__(self, _hass: object, _version: int, key: str) -> None:
        self.key = key

    async def async_load(self) -> dict[str, Any] | None:
        value = self.values.get(self.key)
        return deepcopy(value) if value is not None else None

    async def async_save(self, value: dict[str, Any]) -> None:
        self.values[self.key] = deepcopy(value)

    async def async_remove(self) -> None:
        self.values.pop(self.key, None)


class _QueuedClient:
    """Return queued catalog versions or queued failures."""

    def __init__(self, *results: tuple[TTSModel, ...] | Exception) -> None:
        self.results = list(results)
        self.calls = 0

    async def async_fetch_catalog(self) -> tuple[TTSModel, ...]:
        self.calls += 1
        if not self.results:
            raise AssertionError("The catalog client was called more than expected")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def fake_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep catalog tests independent from a Home Assistant instance."""
    _MemoryStore.values.clear()
    monkeypatch.setattr(catalog_module, "Store", _MemoryStore)


def test_parse_catalog_requires_text_input_speech_output_and_voices() -> None:
    """Chat models, non-text speech models, and models without voices are excluded."""
    payload = {
        "data": [
            _raw_model(
                "provider/valid",
                output_modalities=["text", "speech"],
                voices=["Sulafat", "Sulafat", "Aoede", ""],
                pricing={"prompt": "0", "completion": "0"},
            ),
            _raw_model("provider/chat", output_modalities=["text"]),
            _raw_model("provider/non-text", input_modalities=["audio"]),
            _raw_model("provider/no-voices", voices=None),
            _raw_model("provider/empty-voices", voices=[]),
            _raw_model("provider/blank-id") | {"id": "  "},
            "not-a-model",
        ]
    }

    models = parse_catalog_payload(payload)

    assert len(models) == 1
    model = models[0]
    assert model.model_id == "provider/valid"
    assert model.voices == ("Sulafat", "Aoede")
    assert model.free_status is FreeStatus.FREE
    assert model.supports_speed is True


def test_exact_fish_model_uses_provider_default_only_for_explicit_null_voices() -> None:
    """The audited Fish exception is free, selectable, and has no implied speed."""
    raw = _raw_model(FISH_AUDIO_S21_PRO_FREE_MODEL_ID, voices=None)
    raw["supported_parameters"] = []

    model = parse_catalog_payload({"data": [raw]})[0]

    assert model.model_id == FISH_AUDIO_S21_PRO_FREE_MODEL_ID
    assert model.voices == (PROVIDER_DEFAULT_VOICE_ID,)
    assert model.provider_default_voice is True
    assert model.free_status is FreeStatus.FREE
    assert model.supports_speed is False
    assert TTSModel.from_dict(model.as_dict()) == model


def test_provider_default_adapter_is_exact_and_fail_closed() -> None:
    """Missing, empty, near-match, and non-free sibling metadata never opt in."""
    missing_voices = _raw_model(FISH_AUDIO_S21_PRO_FREE_MODEL_ID, voices=None)
    missing_voices.pop("supported_voices")
    payload = {
        "data": [
            _raw_model("provider/valid", voices=["Named Voice"]),
            missing_voices,
            _raw_model(FISH_AUDIO_S21_PRO_FREE_MODEL_ID, voices=[]),
            _raw_model("fish-audio/s2.1-pro-free", voices=None),
            _raw_model("fish-audio/s2.1-pro:free", voices=None),
            _raw_model("provider/forged-sentinel", voices=[PROVIDER_DEFAULT_VOICE_ID]),
            _raw_model(
                FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
                voices=[PROVIDER_DEFAULT_VOICE_ID],
            ),
        ]
    }

    models = parse_catalog_payload(payload)

    assert [model.model_id for model in models] == ["provider/valid"]
    assert all(not model.provider_default_voice for model in models)


def test_fish_named_voices_do_not_activate_provider_default_mode() -> None:
    """If the catalog later advertises voices, normal named-voice handling wins."""
    model = parse_catalog_payload(
        {
            "data": [
                _raw_model(
                    FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
                    voices=["Catalog Voice"],
                )
            ]
        }
    )[0]

    assert model.voices == ("Catalog Voice",)
    assert model.provider_default_voice is False


def test_fish_positive_price_remains_visible_but_not_verified_free() -> None:
    """The adapter never lets the :free suffix override a newly positive price."""
    model = parse_catalog_payload(
        {
            "data": [
                _raw_model(
                    FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
                    voices=None,
                    pricing={"prompt": "0", "completion": "0.000001"},
                )
            ]
        }
    )[0]

    assert model.provider_default_voice is True
    assert model.free_status is FreeStatus.PAID
    assert filter_models((model,), free_only=False) == (model,)
    with pytest.raises(NoFreeModelsError):
        filter_models((model,), free_only=True)


def test_parse_catalog_accepts_explicit_text_to_speech_modality() -> None:
    """The documented compact architecture modality is also supported."""
    raw = _raw_model(
        "provider/compact",
        input_modalities=[],
        output_modalities=[],
        modality="text->speech",
    )
    raw["architecture"].pop("input_modalities")
    raw["architecture"].pop("output_modalities")

    assert parse_catalog_payload({"data": [raw]})[0].model_id == "provider/compact"


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}}, {"data": []}])
def test_parse_catalog_rejects_missing_or_empty_candidate_set(
    payload: dict[str, object],
) -> None:
    with pytest.raises(InvalidCatalogError):
        parse_catalog_payload(payload)


def test_filter_models_returns_all_or_only_verified_free() -> None:
    free = _model("provider/free", status=FreeStatus.FREE)
    paid = _model("provider/paid", status=FreeStatus.PAID)
    unknown = _model("provider/unknown", status=FreeStatus.UNKNOWN)

    assert filter_models((free, paid, unknown), free_only=False) == (
        free,
        paid,
        unknown,
    )
    assert filter_models((free, paid, unknown), free_only=True) == (free,)


def test_filter_models_reports_when_no_verified_free_model_exists() -> None:
    with pytest.raises(NoFreeModelsError):
        filter_models(
            (
                _model("provider/paid", status=FreeStatus.PAID),
                _model("provider/unknown", status=FreeStatus.UNKNOWN),
            ),
            free_only=True,
        )


def test_filter_ignores_preserved_unavailable_free_model() -> None:
    unavailable = _model("provider/free", status=FreeStatus.FREE).with_availability(
        False
    )
    with pytest.raises(NoFreeModelsError):
        filter_models((unavailable,), free_only=True)


def test_documented_speed_adapter_fills_in_missing_catalog_parameter() -> None:
    raw = _raw_model(
        "microsoft/mai-voice-model",
        voices=["en-US-Ava:DragonHDLatestNeural:MAI-Voice-2"],
    )
    raw["supported_parameters"] = []

    model = parse_catalog_payload({"data": [raw]})[0]

    assert model.supports_speed is True


def test_ttl_cache_avoids_an_unnecessary_catalog_request() -> None:
    async def scenario() -> None:
        first = (_model("provider/first"),)
        client = _QueuedClient(first, (_model("provider/unexpected"),))
        manager = CatalogManager(object(), "cache-entry", client)

        initial = await manager.async_get()
        cached = await manager.async_get()

        assert cached is initial
        assert client.calls == 1

    asyncio.run(scenario())


def test_persisted_recent_catalog_is_loaded_without_network_access() -> None:
    async def scenario() -> None:
        first = (_model("provider/persisted", status=FreeStatus.FREE),)
        writer_client = _QueuedClient(first)
        writer = CatalogManager(object(), "persisted-entry", writer_client)
        written = await writer.async_get()

        reader_client = _QueuedClient(
            AssertionError("A recent persisted catalog should satisfy this request")
        )
        reader = CatalogManager(object(), "persisted-entry", reader_client)
        loaded = await reader.async_get()

        assert loaded.models == written.models
        assert loaded.fetched_at == written.fetched_at
        assert loaded.stale is True
        assert reader_client.calls == 0

    asyncio.run(scenario())


def test_persisted_fish_provider_default_capability_is_loaded_from_cache() -> None:
    """The safe omission capability survives the Home Assistant Store round trip."""

    async def scenario() -> None:
        fish = parse_catalog_payload(
            {"data": [_raw_model(FISH_AUDIO_S21_PRO_FREE_MODEL_ID, voices=None)]}
        )[0]
        writer = CatalogManager(
            object(), "persisted-fish-entry", _QueuedClient((fish,))
        )
        await writer.async_get()

        reader = CatalogManager(
            object(),
            "persisted-fish-entry",
            _QueuedClient(
                AssertionError("A recent Fish catalog should load from storage")
            ),
        )
        loaded = await reader.async_get()
        cached = loaded.by_id(FISH_AUDIO_S21_PRO_FREE_MODEL_ID)

        assert cached is not None
        assert cached.provider_default_voice is True
        assert cached.voices == (PROVIDER_DEFAULT_VOICE_ID,)
        assert loaded.stale is True

    asyncio.run(scenario())


def test_failed_refresh_uses_last_good_catalog_as_stale() -> None:
    async def scenario() -> None:
        first = (_model("provider/first"),)
        client = _QueuedClient(first, NetworkError("offline"))
        manager = CatalogManager(object(), "stale-entry", client)

        initial = await manager.async_get()
        stale = await manager.async_get(force=True)

        assert stale.models == initial.models
        assert stale.fetched_at == initial.fetched_at
        assert stale.stale is True
        assert client.calls == 2

    asyncio.run(scenario())


def test_authentication_failure_never_uses_stale_catalog() -> None:
    async def scenario() -> None:
        initial = (_model("provider/initial"),)
        client = _QueuedClient(initial, AuthenticationError("revoked"))
        manager = CatalogManager(object(), "auth-no-stale", client)

        await manager.async_get()
        with pytest.raises(AuthenticationError):
            await manager.async_get(force=True)

    asyncio.run(scenario())


def test_disappeared_selected_model_is_preserved_as_unavailable() -> None:
    async def scenario() -> None:
        selected = _model("provider/selected", ("Sulafat", "Aoede"))
        replacement = _model("provider/replacement")
        client = _QueuedClient((selected,), (replacement,))
        manager = CatalogManager(object(), "model-disappearance", client)

        await manager.async_get()
        refreshed = await manager.async_get(
            force=True,
            preserve_model_id=selected.model_id,
            preserve_voice="Sulafat",
        )

        preserved = refreshed.by_id(selected.model_id)
        assert preserved is not None
        assert preserved.available is False
        assert preserved.voices == selected.voices
        assert refreshed.by_id(replacement.model_id) == replacement

    asyncio.run(scenario())


def test_disappeared_fish_model_preserves_provider_default_capability() -> None:
    """The last confirmed adapter survives cache/availability fallback unchanged."""

    async def scenario() -> None:
        selected = parse_catalog_payload(
            {"data": [_raw_model(FISH_AUDIO_S21_PRO_FREE_MODEL_ID, voices=None)]}
        )[0]
        replacement = _model("provider/replacement")
        manager = CatalogManager(
            object(),
            "fish-model-disappearance",
            _QueuedClient((selected,), (replacement,)),
        )

        await manager.async_get()
        refreshed = await manager.async_get(
            force=True,
            preserve_model_id=selected.model_id,
            preserve_voice=PROVIDER_DEFAULT_VOICE_ID,
        )

        preserved = refreshed.by_id(selected.model_id)
        assert preserved is not None
        assert preserved.available is False
        assert preserved.provider_default_voice is True
        assert preserved.voices == (PROVIDER_DEFAULT_VOICE_ID,)
        assert TTSModel.from_dict(preserved.as_dict()) == preserved

    asyncio.run(scenario())


def test_fish_capability_change_preserves_selection_but_disables_adapter() -> None:
    """Explicit named voices supersede, rather than inheriting, the old adapter."""

    async def scenario() -> None:
        initial = parse_catalog_payload(
            {"data": [_raw_model(FISH_AUDIO_S21_PRO_FREE_MODEL_ID, voices=None)]}
        )[0]
        current = parse_catalog_payload(
            {
                "data": [
                    _raw_model(
                        FISH_AUDIO_S21_PRO_FREE_MODEL_ID,
                        voices=["Catalog Voice"],
                    )
                ]
            }
        )[0]
        manager = CatalogManager(
            object(),
            "fish-capability-change",
            _QueuedClient((initial,), (current,)),
        )

        await manager.async_get()
        refreshed = await manager.async_get(
            force=True,
            preserve_model_id=initial.model_id,
            preserve_voice=PROVIDER_DEFAULT_VOICE_ID,
        )

        preserved = refreshed.by_id(initial.model_id)
        assert preserved is not None
        assert preserved.provider_default_voice is False
        assert preserved.voices == ("Catalog Voice", PROVIDER_DEFAULT_VOICE_ID)
        assert preserved.unavailable_voices == frozenset({PROVIDER_DEFAULT_VOICE_ID})

    asyncio.run(scenario())


def test_disappeared_selected_voice_is_preserved_but_cannot_be_newly_selected() -> None:
    async def scenario() -> None:
        initial = _model("provider/selected", ("Current", "Removed"))
        current = _model("provider/selected", ("Current",))
        client = _QueuedClient((initial,), (current,))
        manager = CatalogManager(object(), "voice-disappearance", client)

        await manager.async_get()
        refreshed = await manager.async_get(
            force=True,
            preserve_model_id=initial.model_id,
            preserve_voice="Removed",
        )

        preserved = refreshed.by_id(initial.model_id)
        assert preserved is not None
        assert preserved.voices == ("Current", "Removed")
        assert preserved.unavailable_voices == frozenset({"Removed"})
        with pytest.raises(ModelVoiceMismatchError):
            validate_model_voice(refreshed.models, initial.model_id, "Removed")
        assert (
            validate_model_voice(
                refreshed.models,
                initial.model_id,
                "Removed",
                allow_preserved_unavailable=True,
            )
            is preserved
        )

    asyncio.run(scenario())


def test_forced_refresh_updates_changed_price_classification() -> None:
    async def scenario() -> None:
        free = _model("provider/selected", status=FreeStatus.FREE)
        paid = _model("provider/selected", status=FreeStatus.PAID)
        client = _QueuedClient((free,), (paid,))
        manager = CatalogManager(object(), "price-change", client)

        await manager.async_get()
        refreshed = await manager.async_get(
            force=True,
            preserve_model_id=free.model_id,
            preserve_voice=free.voices[0],
        )

        assert refreshed.by_id(free.model_id) is not None
        assert refreshed.by_id(free.model_id).free_status is FreeStatus.PAID  # type: ignore[union-attr]

    asyncio.run(scenario())
