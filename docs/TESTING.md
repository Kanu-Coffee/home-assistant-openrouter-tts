# Verification matrix

This file records what has actually been exercised for the exact source revision. A test
or workflow existing in the repository is not evidence that it passed. Update the status,
date, revision, command, and evidence after every release-candidate run; leave failed or
skipped checks visible.

## Current pre-release status

Status as of 2026-08-29 for the `v0.1.0-beta.1` release candidate:

| Area | Target | Status | Evidence or next action |
| --- | --- | --- | --- |
| Mock unit/integration suite | Python 3.14.4 local environment | Passed | 193 passed. Branch-enabled combined coverage: 88.57% (1,212/1,337 statements and 261/326 branch outcomes covered). |
| Ruff | Python source and tests | Passed | `ruff check` and `ruff format --check` both passed on the final local candidate. |
| Mypy | Integration package | Passed | Strict package type checking completed without an issue. |
| Minimum-version compatibility | Home Assistant 2025.12.5 container | Passed | Import and config-entry setup → unload → setup passed. A host-UID-owned mode-0755 `/config` bind mount also passed real save/read as mode 0600 and deletion. Image digest: `sha256:9a5a3eb4a213dfb25932dee9dc6815c9305f78cecb5afa716fa2483163d8fb5b`. |
| Current-stable compatibility | Home Assistant 2026.8.3 container | Passed | Import and config-entry setup → unload → setup passed. A host-UID-owned mode-0755 `/config` bind mount also passed real save/read as mode 0600 and deletion. Image digest: `sha256:14931c6b13756317849f46da1d01b45937a1150db66c081cfe529d48215943fe`. |
| hassfest | Repository | Passed | Official validation reported 0 invalid integrations. |
| HACS validation | Public repository | Passed | The pinned HACS validation action completed successfully in the first public [Quality run](https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/actions/runs/33239859740). |
| HAOS end-to-end | HAOS 18.2 / Core 2026.8.3 | Passed with gaps below | The mock-backed path passed install, flows, restart persistence, refresh, file generation/retrieval/deletion, `tts.speak`, reload, and removal. Runtime reauthentication and a deliberately invalid Options pair were not exercised on the VM. |
| OpenRouter live smoke | Manual workflow | Not run | Use a temporary secret only after release-candidate approval; generation is optional and verified-free only. |
| Secret scan | Tracked files and Git history | Passed | Gitleaks 8.30.1 scanned the complete candidate history with no leak; explicit OpenRouter-key and literal bearer-token patterns found no credential. Trivy 0.74.0 reported zero unfixed high/critical production dependency findings. |

Do not change **Pending**, **In progress**, or **Not run** to **Passed** until the named
check has completed successfully on the candidate revision.

## Current mock test scope

The repository contains mock/pure tests for these areas. This list describes intended
scope, not the outcome of the next full run:

- `test_pricing.py`: `:free`, complete zero-price, positive-price, missing, null,
  malformed, conditional, and future pricing fields.
- `test_catalog.py`: capability/voice parsing, availability, filtering, TTL/persistence,
  stale last-known-good behavior, refresh, disappeared models/voices, and price changes.
- `test_audio.py`: MP3, WAV, raw PCM conversion, MIME/magic mismatches, malformed data,
  and response-size limits.
- `test_storage.py`: lexical path checks, absolute paths, traversal, symlink escape,
  encoded URLs, overwrite protection, deletion, trusted ownership/mode checks, staging
  permissions, directory-identity races, and atomic publish.
- `test_api.py`: authentication/access/validation/rate-limit/server statuses, separated
  timeout errors, bounded bodies, `Retry-After`, request fields, and sensitive-data
  redaction.
- `test_config_flow.py`: setup, invalid credentials, reauthentication, Options Flow,
  empty-free-filter behavior, and atomic model/voice validation.
- `test_init.py`: config-entry setup/unload and administrator service registration,
  schemas, responses, reauthentication, and safe error mapping.
- `test_tts.py`: TTS entity properties, speech generation, option forwarding, and
  secret-safe failures.
- `test_diagnostics.py`: API-key redaction and non-sensitive catalog summaries, including
  a missing-catalog state.

Normal CI and local tests must use mocked OpenRouter responses. They must not require,
read, or condition behavior on a real API key.

## Release-candidate commands

Run from the repository root with the locked development environment:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python -m pytest
```

Then run the repository's Docker compatibility script for both images recorded in the
matrix and the official hassfest and HACS validations. Record the exact commands, image
tags and immutable digests, exit status, test count, skipped count, coverage, and revision
in the result log below.

### Storage filesystem compatibility

The two Docker checks deliberately used a mode-0755 bind-mounted config directory owned
by a host UID different from the container process EUID. Both versions created, read, and
deleted a real file through `SecureFileStore`; the published file was mode 0600. This
validates the common Linux bind-mount case, not every network or non-POSIX filesystem.

The config directory is an administrator-selected trust anchor. Below it, root, the Home
Assistant process EUID, and the config directory's numeric owner are trusted. Existing
config/storage directories that are group- or world-writable are rejected. CIFS, FAT, or
NFS mounts may not preserve the ownership, mode, directory-descriptor, hard-link, atomic
rename, or `fsync` semantics required by the safety checks. On an incompatible mount,
save/delete can fail closed; that is an expected safety outcome rather than permission to
relax the checks. Use a local POSIX filesystem or a mount configuration that exposes
stable Unix ownership and permissions.

## HAOS end-to-end checklist

Use only generalized, non-sensitive text such as `Test.` and do not capture the API key,
private Home Assistant URL, entity IDs, generated audio, or full service payloads in the
repository.

- [x] Install the candidate as a new custom integration.
- [x] Confirm that the Config Flow rejects an invalid API key without exposing it.
- [x] Complete the Config Flow and confirm model, voice, speed, and storage root.
- [x] Restart Home Assistant and confirm that settings persist.
- [x] Change the all/free model filter and model/voice/speed/root through the Options Flow.
- [ ] Confirm that an invalid model/voice pair is not saved.
- [x] Call `tts.speak`; fetch the returned MP3 through its media-source URL.
- [x] Call `openrouter_tts.generate_file`; validate the result as 24 kHz, 16-bit, mono WAV.
- [x] Retrieve the saved result through `/local/audio/tts/...`.
- [x] Refresh the catalog and confirm that the action completes successfully.
- [ ] Exercise a safe API-error recovery path and reauthentication.
- [x] Unload and reload the config entry.
- [x] Delete the generated file and remove the config entry; confirm unrelated files are
  not removed.
- [ ] Run `tts.clear_cache`. Every test call used `cache: false`, so no deliberate disk
  cache entry was created; the generated file and temporary test artifacts were removed.
- [x] Review Home Assistant logs. No mock credential or OpenRouter-key pattern was found.
  Home Assistant core did record the complete non-sensitive `Test.` input while reporting
  the pre-fix TTS-engine-name failure, demonstrating the documented core privacy limit.

The completed HAOS checks used an isolated non-live test path. No request was sent to the
real OpenRouter API, and no private host, entity ID, storage path, credential, or generated
audio is retained in this repository.

## Manual OpenRouter smoke test

`.github/workflows/live-smoke.yml` is `workflow_dispatch` only and reads the
`OPENROUTER_API_KEY` secret from the protected `live-openrouter-test` environment. Its
default mode validates the key and current catalog without generating speech. If the
operator explicitly enables generation, the script:

1. fetches the live catalog;
2. requires a conservatively verified free, voice-capable TTS model;
3. sends exactly one `Test.` request; and
4. exits without generation if no such model exists.

It never falls back to a paid or unknown-cost model. Even a verified-free result reflects
only the catalog and provider at that time and does not guarantee the final bill. Do not
enable generation merely to make the matrix green.

## Secret and privacy verification

Before a commit, tag, push, or release:

- scan the worktree and complete Git history with `gitleaks` or an equivalent scanner;
- search explicitly for OpenRouter key prefixes, bearer headers, private Home Assistant
  hostnames, local entity IDs, and copied service payloads;
- inspect CI logs, coverage reports, screenshots, audio files, and release archives;
- confirm no live key is embedded in fixtures, cassettes, environment files, GitHub
  issues, or workflow defaults; and
- rotate/delete any temporary credential after live testing.

Home Assistant core owns its TTS cache, automation traces, and service-call diagnostics.
The integration redacts its own messages and credentials but cannot scrub those external
records. Use `cache: false`, run `tts.clear_cache`, and remove traces after sensitive tests.

## Result log template

Current result log:

```text
Revision/tag: v0.1.0-beta.1 release candidate (tag pending publication approval)
Date (UTC): 2026-08-29
Local: Python 3.14.4; 193 passed; branch-enabled combined coverage 88.57%; Ruff/format/mypy passed
Docker minimum: HA Core 2025.12.5; lifecycle and host-UID bind-mount save/read(0600)/delete passed
Docker stable: HA Core 2026.8.3; lifecycle and host-UID bind-mount save/read(0600)/delete passed
hassfest: passed; 0 invalid integrations
HACS validation: passed in public GitHub Actions Quality run 33239859740
HAOS: 18.2 / Core 2026.8.3; mock-backed checklist passed except the explicit gaps above
Live OpenRouter: not run
Secret scan: Gitleaks 8.30.1 Git history and explicit credential patterns passed; Trivy 0.74.0 high/critical production findings 0
Known failures/skips: live API, HAOS runtime reauthentication/invalid-pair UI exercise, and `tts.clear_cache` remain
```

For later candidates, copy the template below and replace every placeholder:

```text
Revision/tag: <commit or tag>
Date (UTC): <YYYY-MM-DD>
Local: <ruff, mypy, pytest counts/coverage>
Docker minimum: <image tag + digest + result>
Docker stable: <image tag + digest + result>
hassfest: <result + run URL or local command>
HACS validation: <result + run URL or local command>
HAOS: <version + checklist result; no private host/entity data>
Live OpenRouter: <not run | catalog only | one verified-free Test. call>
Secret scan: <tool/version/result>
Known failures/skips: <explicit list>
```
