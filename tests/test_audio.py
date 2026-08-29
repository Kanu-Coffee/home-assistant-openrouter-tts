"""Tests for validating and normalizing OpenRouter audio responses."""

from __future__ import annotations

import io
import wave

import pytest

from custom_components.openrouter_tts.audio import (
    normalize_audio_response,
    wrap_pcm_as_wav,
)
from custom_components.openrouter_tts.exceptions import (
    AudioTooLargeError,
    InvalidAudioError,
)
from custom_components.openrouter_tts.models import AudioCapabilities


def _mp3_bytes() -> bytes:
    # One 417-byte MPEG-1 Layer III frame: 128 kbit/s, 44.1 kHz, no padding.
    return b"\xff\xfb\x90\x64" + (b"\x00" * 413)


def _wav_bytes(pcm: bytes = b"\x00\x00\x01\x00") -> bytes:
    return wrap_pcm_as_wav(pcm, sample_rate=24_000, channels=1, sample_width=2)


def test_mp3_magic_and_content_type_are_accepted() -> None:
    result = normalize_audio_response(
        _mp3_bytes(),
        content_type="audio/mpeg; charset=binary",
        requested_format="mp3",
        headers={"X-Generation-Id": "generation-123"},
    )

    assert result.extension == "mp3"
    assert result.content_type == "audio/mpeg"
    assert result.data == _mp3_bytes()
    assert result.generation_id == "generation-123"


def test_valid_wav_magic_and_structure_are_accepted() -> None:
    wav_data = _wav_bytes()

    result = normalize_audio_response(
        wav_data,
        content_type="application/octet-stream",
        requested_format="wav",
    )

    assert result.extension == "wav"
    assert result.content_type == "audio/wav"
    assert result.data == wav_data


def test_raw_pcm_is_wrapped_with_explicit_capabilities() -> None:
    pcm = b"\x00\x00\x01\x00\x02\x00\x03\x00"
    capabilities = AudioCapabilities(
        raw_pcm=True,
        sample_rate=16_000,
        channels=1,
        sample_width=2,
    )

    result = normalize_audio_response(
        pcm,
        content_type="application/octet-stream",
        requested_format="mp3",
        capabilities=capabilities,
    )

    assert result.extension == "wav"
    with wave.open(io.BytesIO(result.data), "rb") as audio_file:
        assert audio_file.getframerate() == 16_000
        assert audio_file.getnchannels() == 1
        assert audio_file.getsampwidth() == 2
        assert audio_file.readframes(audio_file.getnframes()) == pcm


def test_raw_pcm_content_type_and_header_determine_sample_rate() -> None:
    result = normalize_audio_response(
        b"\x00\x00\x01\x00",
        content_type="audio/pcm",
        requested_format="pcm",
        headers={"X-Audio-Sample-Rate": "48000"},
    )

    with wave.open(io.BytesIO(result.data), "rb") as audio_file:
        assert audio_file.getframerate() == 48_000


@pytest.mark.parametrize(
    "header_value",
    ["not-a-number", "7999", "192001"],
)
def test_invalid_pcm_sample_rate_header_is_rejected(header_value: str) -> None:
    with pytest.raises(InvalidAudioError) as caught:
        normalize_audio_response(
            b"\x00\x00\x01\x00",
            content_type="audio/pcm",
            requested_format="pcm",
            headers={"X-Audio-Sample-Rate": header_value},
        )

    assert caught.value.__cause__ is None
    assert header_value not in repr(caught.value)


def test_provider_controlled_pcm_parameters_are_not_retained_in_error_chain() -> None:
    marker = "private-provider-header-sentinel"

    with pytest.raises(InvalidAudioError) as caught:
        normalize_audio_response(
            b"\x00\x00\x01\x00",
            content_type=f"audio/pcm; rate={marker}",
            requested_format="pcm",
        )

    assert caught.value.__cause__ is None
    assert marker not in repr(caught.value)


@pytest.mark.parametrize(
    "body",
    [b'{"error":"provider failed"}', b"<html>gateway error</html>", b"error"],
)
def test_textual_body_mislabeled_as_pcm_is_rejected(body: bytes) -> None:
    with pytest.raises(InvalidAudioError):
        normalize_audio_response(
            body,
            content_type="audio/pcm",
            requested_format="pcm",
        )


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (b"", "audio/mpeg"),
        (b'{"error":"not audio"}', "application/json"),
        (b"upstream failure", "text/plain"),
        (b"unrecognized opaque bytes", "application/octet-stream"),
        (b"RIFF\x01\x00\x00\x00WAVEbroken", "audio/wav"),
    ],
)
def test_empty_non_audio_and_malformed_audio_are_rejected(
    data: bytes,
    content_type: str,
) -> None:
    with pytest.raises(InvalidAudioError):
        normalize_audio_response(
            data,
            content_type=content_type,
            requested_format="mp3",
        )


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (_wav_bytes(), "audio/mpeg"),
        (_wav_bytes(), "audio/pcm"),
        (_mp3_bytes(), "audio/wav"),
        (_mp3_bytes(), "audio/pcm"),
        (b"not an mp3 frame", "audio/mpeg"),
        (b"not a wav stream", "audio/wav"),
    ],
)
def test_content_type_and_body_mismatch_is_rejected(
    data: bytes,
    content_type: str,
) -> None:
    with pytest.raises(InvalidAudioError):
        normalize_audio_response(
            data,
            content_type=content_type,
            requested_format="mp3",
        )


def test_response_size_limit_is_checked_before_format_detection() -> None:
    with pytest.raises(AudioTooLargeError):
        normalize_audio_response(
            _mp3_bytes(),
            content_type="audio/mpeg",
            requested_format="mp3",
            max_bytes=8,
        )


def test_pcm_wav_header_must_also_fit_response_size_limit() -> None:
    pcm = b"\x00\x00\x01\x00"
    with pytest.raises(AudioTooLargeError):
        normalize_audio_response(
            pcm,
            content_type="audio/pcm",
            requested_format="pcm",
            max_bytes=len(pcm) + 1,
        )


def test_truncated_wav_data_chunk_is_rejected() -> None:
    wav_data = _wav_bytes()

    with pytest.raises(InvalidAudioError):
        normalize_audio_response(
            wav_data[:-1],
            content_type="audio/wav",
            requested_format="wav",
        )


@pytest.mark.parametrize(
    ("pcm", "capabilities"),
    [
        (b"\x00", AudioCapabilities(raw_pcm=True, sample_width=2)),
        (
            b"\x00\x00\x00\x00\x00\x00",
            AudioCapabilities(raw_pcm=True, channels=2, sample_width=2),
        ),
    ],
)
def test_truncated_raw_pcm_frame_is_rejected(
    pcm: bytes,
    capabilities: AudioCapabilities,
) -> None:
    with pytest.raises(InvalidAudioError):
        normalize_audio_response(
            pcm,
            content_type="audio/pcm",
            requested_format="pcm",
            capabilities=capabilities,
        )
