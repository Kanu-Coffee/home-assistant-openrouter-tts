# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Prerelease versions may contain breaking changes while the integration is being validated.

## [Unreleased]

## [0.2.0] - 2026-08-30

### Added

- Added a narrowly scoped compatibility adapter for the exact model
  `fish-audio/s2.1-pro-free:free`. When OpenRouter explicitly returns
  `supported_voices: null` for that model, the UI exposes **Provider default voice** /
  **공급자 기본 음성** and the speech request omits the `voice` field.
- Added the official My Home Assistant HACS repository badge and direct link, pre-filled
  with owner `Kanu-Coffee`, repository `home-assistant-openrouter-tts`, and category
  `integration` for one-click custom-repository setup.

### Changed

- The dynamic catalog now recognizes either nonempty advertised voices or the exact Fish
  provider-default adapter as a usable voice mode. A missing voice key, empty list, any
  other Fish model, or an unrelated model with null voice metadata remains excluded.
- Fish S2.1 Pro Free remains eligible for **Confirmed free only** only while its current
  catalog metadata passes the same conservative speech and zero-price checks as other
  candidates. Free labels remain point-in-time observations, not cost guarantees.
- Speed is not sent for Fish S2.1 Pro Free while OpenRouter advertises no speed capability.
  The provider-default choice is not a stable named voice and may change upstream.

### Validation

- Recorded a separate exact-model provider-behavior probe capped at ten generation POSTs:
  nine passed, while one request using a public Fish reference ID returned HTTP 400 and
  was not retried. All eight provider-default requests passed across direct English,
  Korean, mixed-language, MP3 and PCM/WAV cases plus controlled HAOS `generate_file`
  MP3/WAV, `/local` retrieval, and `tts.speak` media-source fetching. Successful direct
  records identified Fish Audio and reported zero cost/usage; key usage and remaining
  values had delta 0 over a 60-second observation. The public-reference success is not
  exposed as a supported voice feature, and no physical speaker was tested.
- The final v0.2.0 source passed 212 mock tests with 89.26% branch-enabled combined
  coverage, Ruff, strict mypy, hassfest, and Home Assistant 2025.12.0/2026.8.3 Docker
  lifecycle plus secure-storage checks. Final component bytes also passed a zero-speech-
  POST HAOS Config/Options UI, real restart persistence, fresh catalog refresh, explicit
  reload, cleanup, and credential-pattern review. Live generation was intentionally not
  repeated after the separate ten-call Fish cap; final wire omission is covered by mock
  tests. Python/hassfest/HACS, Docker compatibility, CodeQL, and dependency-graph
  workflows passed on the pushed release source; the exact final tag target repeats the
  same required checks before publication.

### Documentation

- Documented why the Fish adapter is exact-model-only, the current
  `supported_voices: null` limitation, provider-selected voice behavior, the absence of
  reference-ID/voice-cloning UI, and the lack of future pricing, latency, availability,
  or voice-identity guarantees.

## [0.1.0-beta.2] - 2026-08-30

### Changed

- Speech-generation POSTs now send `Accept-Encoding: identity`, asking OpenRouter to
  return the binary audio representation without an additional HTTP content coding and
  avoiding runtime-specific decoder negotiation. A successful HAOS call after this
  change is correlation only; the root cause of two earlier `invalid_audio` responses
  was not proven.

### Validation

- Recorded an opt-in HAOS 18.2/Core 2026.8.3 live-provider check against the exact
  `v0.1.0-beta.1` component bytes: one paid Gemini/Sulafat `generate_file` request and
  one catalog-confirmed free Deepgram Flux `tts.speak` request through a controlled
  one-fetch media-player sink. Audio structure, `/local` retrieval, local artifact
  cleanup, empty HA backup and VM snapshot lists, restart, and credential-pattern scans
  passed; upstream key revocation remains an owner action.
- Recorded the 2026-08-30 verified-free matrix. The current catalog had exactly one
  eligible model, `deepgram/flux-tts:free`, with 36 voices and no advertised speed
  support. Exactly five generation attempts were made: two pre-change HAOS Alexis calls
  failed with `invalid_audio`; direct Bree and Alexis calls returned valid 13,248-byte
  and 12,384-byte MP3s with Deepgram metadata and zero generation cost/usage; and the
  final HAOS Alexis call with `Accept-Encoding: identity` returned a 14,688-byte, 24 kHz
  mono MP3 that was retrieved through `/local`. `/key` usage remained USD 0.001683, and
  both usage and remaining had delta 0 over 60 seconds. The hard cap prevented another
  WAV or `tts.speak` call; Flux `tts.speak` had already passed on 2026-08-29. Local
  artifacts were removed, while upstream key revocation remains an owner action.

## [0.1.0-beta.1] - 2026-08-29

### Added

- Initial Home Assistant custom-integration structure for OpenRouter-backed TTS.
- Config Flow, reauthentication, Options Flow, and English/Korean UI resources.
- Dynamic audio-model and voice catalog with a conservative free-model classifier.
- TTS entity support for `tts.speak`.
- Administrator services for atomic audio-file generation, catalog refresh, and safe
  generated-file deletion.
- MP3, WAV, and capability-driven raw-PCM normalization with bounded response handling.
- Mock-based tests and CI scaffolding for static analysis, Home Assistant/HACS validation,
  Docker compatibility, security checks, and a manual live smoke test.
- HACS metadata, project documentation, contribution guidance, and security policy.

### Security

- Storage-root confinement, traversal and symlink protections, overwrite protection,
  atomic writes, bounded downloads, and secret-safe error handling.
- Documentation for Home Assistant core cache/trace limitations and unauthenticated
  `/config/www` exposure.
- Documented and reviewed the upstream Home Assistant development/test dependency alert
  for GHSA-g6cj-pr64-35w5; the affected PKCS#7 code path is not used by this integration.

[Unreleased]: https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/compare/v0.1.0-beta.2...v0.2.0
[0.1.0-beta.2]: https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/compare/v0.1.0-beta.1...v0.1.0-beta.2
[0.1.0-beta.1]: https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/releases/tag/v0.1.0-beta.1
