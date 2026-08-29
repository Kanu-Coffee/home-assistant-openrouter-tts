# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Prerelease versions may contain breaking changes while the integration is being validated.

## [Unreleased]

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

[Unreleased]: https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/compare/v0.1.0-beta.1...HEAD
[0.1.0-beta.1]: https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/releases/tag/v0.1.0-beta.1
