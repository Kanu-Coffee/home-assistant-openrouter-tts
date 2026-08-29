"""Audio response detection, validation, and raw PCM conversion."""

from __future__ import annotations

import io
import struct
import wave
from collections.abc import Mapping

from .const import MAX_AUDIO_BYTES
from .exceptions import AudioTooLargeError, InvalidAudioError
from .models import AudioCapabilities, AudioResult

_MP3_CONTENT_TYPES = frozenset({"audio/mpeg", "audio/mp3", "audio/mpeg3"})
_WAV_CONTENT_TYPES = frozenset(
    {"audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave"}
)
_PCM_CONTENT_TYPES = frozenset({"audio/pcm", "audio/l16", "audio/x-pcm", "audio/raw"})
_JSON_CONTENT_TYPES = frozenset({"application/json", "text/json"})


def _base_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().casefold()


def _content_type_parameters(content_type: str | None) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for item in (content_type or "").split(";")[1:]:
        key, separator, value = item.strip().partition("=")
        if separator and key:
            parameters[key.casefold()] = value.strip().strip('"')
    return parameters


def _mp3_frame_length(data: bytes, offset: int) -> int | None:
    if len(data) < offset + 4:
        return None
    header = int.from_bytes(data[offset : offset + 4], "big")
    if header >> 21 != 0x7FF:
        return None
    version = (header >> 19) & 0b11
    layer = (header >> 17) & 0b11
    bitrate_index = (header >> 12) & 0b1111
    sample_rate_index = (header >> 10) & 0b11
    if (
        version == 0b01
        or layer == 0b00
        or bitrate_index in {0, 0b1111}
        or sample_rate_index == 0b11
    ):
        return None
    mpeg1_bitrates = {
        0b11: (32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
        0b10: (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
        0b01: (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    }
    mpeg2_bitrates = {
        0b11: (32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
        0b10: (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
        0b01: (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    }
    bitrate_table = mpeg1_bitrates if version == 0b11 else mpeg2_bitrates
    bitrate = bitrate_table[layer][bitrate_index - 1] * 1_000
    base_sample_rate = (44_100, 48_000, 32_000)[sample_rate_index]
    divisor = 1 if version == 0b11 else 2 if version == 0b10 else 4
    sample_rate = base_sample_rate // divisor
    padding = (header >> 9) & 1
    if layer == 0b11:
        return ((12 * bitrate // sample_rate) + padding) * 4
    coefficient = 144 if version == 0b11 or layer == 0b10 else 72
    return coefficient * bitrate // sample_rate + padding


def _looks_like_mp3(data: bytes) -> bool:
    if len(data) < 8:
        return False
    if not data.startswith(b"ID3"):
        frame_length = _mp3_frame_length(data, 0)
        return frame_length is not None and len(data) >= frame_length
    if len(data) < 14 or any(byte & 0x80 for byte in data[6:10]):
        return False
    tag_size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    footer_size = 10 if data[5] & 0x10 else 0
    frame_offset = 10 + tag_size + footer_size
    frame_length = _mp3_frame_length(data, frame_offset)
    return frame_length is not None and len(data) >= frame_offset + frame_length


def _looks_like_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _looks_like_textual_error(data: bytes) -> bool:
    """Reject common upstream error bodies before treating bytes as headerless PCM."""
    prefix = data[:128].lstrip().lower()
    return prefix.startswith(
        (b"{", b"[", b"<html", b"<!doctype", b"error", b"upstream error")
    )


def _validate_wav(data: bytes) -> None:
    declared_riff_size = int.from_bytes(data[4:8], "little")
    if declared_riff_size + 8 > len(data):
        raise InvalidAudioError("OpenRouter returned a truncated RIFF container")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio_file:
            if (
                audio_file.getnchannels() < 1
                or audio_file.getsampwidth() < 1
                or audio_file.getframerate() < 1
                or audio_file.getnframes() < 1
            ):
                raise InvalidAudioError(
                    "The WAV response has invalid stream parameters"
                )
            expected = (
                audio_file.getnframes()
                * audio_file.getnchannels()
                * audio_file.getsampwidth()
            )
            if len(audio_file.readframes(audio_file.getnframes())) != expected:
                raise InvalidAudioError(
                    "OpenRouter returned truncated WAV audio frames"
                )
    except (EOFError, wave.Error):
        raise InvalidAudioError("OpenRouter returned a malformed WAV stream") from None


def wrap_pcm_as_wav(
    pcm: bytes,
    *,
    sample_rate: int = 24_000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap little-endian integer PCM in a canonical RIFF/WAVE header."""
    if not pcm or sample_rate <= 0 or channels <= 0 or sample_width not in (1, 2, 3, 4):
        raise InvalidAudioError("OpenRouter returned invalid raw PCM parameters")
    frame_size = channels * sample_width
    if len(pcm) % frame_size:
        raise InvalidAudioError("OpenRouter returned a truncated raw PCM frame")
    if len(pcm) > 0xFFFFFFFF - 36:
        raise AudioTooLargeError("The audio response is too large for a WAV container")

    byte_rate = sample_rate * frame_size
    block_align = frame_size
    bits_per_sample = sample_width * 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        len(pcm),
    )
    return header + pcm


def normalize_audio_response(
    data: bytes,
    *,
    content_type: str | None,
    requested_format: str,
    headers: Mapping[str, str] | None = None,
    capabilities: AudioCapabilities | None = None,
    max_bytes: int = MAX_AUDIO_BYTES,
) -> AudioResult:
    """Return audio only after format, magic, structure, and size checks."""
    if not data:
        raise InvalidAudioError("OpenRouter returned an empty audio response")
    if requested_format.casefold() not in {"mp3", "pcm", "wav"}:
        raise InvalidAudioError("The requested audio format is unsupported")
    if len(data) > max_bytes:
        raise AudioTooLargeError(
            f"The audio response exceeded the {max_bytes} byte safety limit"
        )

    media_type = _base_content_type(content_type)
    media_parameters = _content_type_parameters(content_type)
    if media_type in _JSON_CONTENT_TYPES or media_type.startswith("text/"):
        raise InvalidAudioError("OpenRouter returned a non-audio response")

    normalized_headers = {
        key.casefold(): value for key, value in (headers or {}).items()
    }
    generation_id = normalized_headers.get("x-generation-id")

    if _looks_like_wav(data):
        if media_type in _MP3_CONTENT_TYPES or media_type in _PCM_CONTENT_TYPES:
            raise InvalidAudioError("The audio Content-Type conflicts with WAV bytes")
        _validate_wav(data)
        return AudioResult(data, "wav", "audio/wav", generation_id)
    if _looks_like_mp3(data):
        if media_type in _WAV_CONTENT_TYPES or media_type in _PCM_CONTENT_TYPES:
            raise InvalidAudioError("The audio Content-Type conflicts with MP3 bytes")
        return AudioResult(data, "mp3", "audio/mpeg", generation_id)

    hints = capabilities or AudioCapabilities()
    pcm_by_type = media_type in _PCM_CONTENT_TYPES
    pcm_by_capability = hints.raw_pcm is True
    pcm_by_header = any(
        name in normalized_headers for name in ("x-audio-sample-rate", "x-sample-rate")
    )
    if media_type in _MP3_CONTENT_TYPES | _WAV_CONTENT_TYPES:
        raise InvalidAudioError("The audio body does not match its Content-Type")
    if media_type in {"audio/l16", "audio/x-pcm", "audio/raw"} and not (
        pcm_by_capability or pcm_by_header or "rate" in media_parameters
    ):
        raise InvalidAudioError(
            "The raw PCM response did not declare its stream format"
        )
    if pcm_by_type or pcm_by_capability or pcm_by_header:
        if _looks_like_textual_error(data):
            raise InvalidAudioError(
                "OpenRouter returned a textual body instead of raw PCM audio"
            )
        sample_rate = hints.sample_rate
        channels = hints.channels
        declared_rate = media_parameters.get("rate")
        declared_channels = media_parameters.get("channels")
        if declared_rate:
            try:
                parsed_rate = int(declared_rate)
            except ValueError:
                raise InvalidAudioError(
                    "The PCM Content-Type has an invalid rate"
                ) from None
            if not 8_000 <= parsed_rate <= 192_000:
                raise InvalidAudioError("The PCM sample rate is outside safe bounds")
            sample_rate = parsed_rate
        if declared_channels:
            try:
                parsed_channels = int(declared_channels)
            except ValueError:
                raise InvalidAudioError(
                    "The PCM Content-Type has invalid channels"
                ) from None
            if not 1 <= parsed_channels <= 8:
                raise InvalidAudioError("The PCM channel count is outside safe bounds")
            channels = parsed_channels
        for header_name in ("x-audio-sample-rate", "x-sample-rate"):
            if value := normalized_headers.get(header_name):
                try:
                    parsed = int(value)
                except ValueError:
                    raise InvalidAudioError(
                        "The PCM sample-rate header is invalid"
                    ) from None
                if not 8_000 <= parsed <= 192_000:
                    raise InvalidAudioError(
                        "The PCM sample-rate header is outside safe bounds"
                    )
                if declared_rate and parsed != sample_rate:
                    raise InvalidAudioError(
                        "Conflicting PCM sample rates were returned"
                    )
                sample_rate = parsed
                break
        pcm_data = data
        if media_type == "audio/l16":
            if hints.sample_width != 2 or len(data) % 2:
                raise InvalidAudioError("The big-endian L16 stream is truncated")
            swapped = bytearray(len(data))
            swapped[0::2] = data[1::2]
            swapped[1::2] = data[0::2]
            pcm_data = bytes(swapped)
        wav_data = wrap_pcm_as_wav(
            pcm_data,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=hints.sample_width,
        )
        if len(wav_data) > max_bytes:
            raise AudioTooLargeError(
                f"The WAV audio exceeded the {max_bytes} byte safety limit"
            )
        return AudioResult(wav_data, "wav", "audio/wav", generation_id)

    raise InvalidAudioError("OpenRouter returned an unrecognized audio format")
