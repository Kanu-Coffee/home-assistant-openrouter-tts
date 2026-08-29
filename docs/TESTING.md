# Verification matrix

This file records what has actually been exercised for the exact source revision. A test
or workflow existing in the repository is not evidence that it passed. Update the status,
date, revision, command, and evidence after every release-candidate run; leave failed or
skipped checks visible.

## Current release status

Status as of 2026-08-30 for the `v0.1.0-beta.2` release candidate. Results inherited from
the published `v0.1.0-beta.1` baseline are explicitly dated below:

| Area | Target | Status | Evidence or next action |
| --- | --- | --- | --- |
| Mock unit/integration suite | Python 3.14.4 local environment | Passed | 194 passed. Branch-enabled combined coverage: 88.57%. |
| Ruff | Python source and tests | Passed | `ruff check` and `ruff format --check` both passed on the final local candidate. |
| Mypy | Integration package | Passed | Strict package type checking completed without an issue. |
| Minimum-version compatibility | Home Assistant 2025.12.5 container | Passed | Import and config-entry setup → unload → setup passed. A host-UID-owned mode-0755 `/config` bind mount also passed real save/read as mode 0600 and deletion. Image digest: `sha256:9a5a3eb4a213dfb25932dee9dc6815c9305f78cecb5afa716fa2483163d8fb5b`. |
| Current-stable compatibility | Home Assistant 2026.8.3 container | Passed | Import and config-entry setup → unload → setup passed. A host-UID-owned mode-0755 `/config` bind mount also passed real save/read as mode 0600 and deletion. Image digest: `sha256:14931c6b13756317849f46da1d01b45937a1150db66c081cfe529d48215943fe`. |
| hassfest | Repository | Passed | Official validation reported 0 invalid integrations. |
| HACS validation | Public repository | Passed | The pinned HACS validation action completed successfully in the first public [Quality run](https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/actions/runs/33239859740). |
| HAOS end-to-end | HAOS 18.2 / Core 2026.8.3 | Passed with gaps below | The 2026-08-29 release-byte path passed real Config/Options flows, catalog refresh, paid file generation, verified-free `tts.speak`, cleanup, and restart. The 2026-08-30 candidate passed free Flux MP3 `generate_file` and `/local` retrieval after the identity-header change. Runtime reauthentication and a deliberately invalid Options pair were not exercised on the VM. |
| OpenRouter live provider | Direct and HAOS opt-in tests; manual workflow not used | Passed with scoped gaps below | The 2026-08-30 catalog exposed one eligible free TTS model with 36 voices. Exactly five generation attempts were made; two pre-change HAOS calls failed, two direct calls returned valid zero-cost MP3s, and the final identity-header HAOS call passed. WAV and `tts.speak` were not repeated after the hard cap. Details and the separate 2026-08-29 evidence are below. |
| Secret scan | Tracked files and Git history | Passed | Gitleaks 8.30.1 scanned the complete candidate history with no leak; explicit OpenRouter-key and literal bearer-token patterns found no credential. Trivy 0.74.0 reported zero unfixed high/critical production dependency findings. |
| Upstream dev/test advisory | `cryptography==48.0.1` via Home Assistant 2026.8.3 | Dismissed as `not_used`; tracked | [GHSA-g6cj-pr64-35w5](https://github.com/advisories/GHSA-g6cj-pr64-35w5) affects PKCS#7 EnvelopedData decryption, which this integration and its tests do not call or expose. Home Assistant pins 48.0.1 exactly; reassess when upstream permits 50.0.0 or later. A full-development Trivy scan also flags CVE-2026-69249, but the [upstream advisory](https://github.com/advisories/GHSA-jwv3-5hgf-82ww) affects versions before 48.0.0, so locked 48.0.1 is outside its published range. |

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
- [x] Run `tts.clear_cache`; restart Core after removing the generated file, temporary
  media player, and config entry.
- [x] Review Home Assistant logs. No mock credential or OpenRouter-key pattern was found.
  Home Assistant core did record the complete non-sensitive `Test.` input while reporting
  the pre-fix TTS-engine-name failure, demonstrating the documented core privacy limit.

### 2026-08-29 baseline live path

The initial HAOS checks used an isolated mock path. A later direct opt-in check used the
exact published component bytes and a temporary credential. The HA test path issued two
service-triggered live speech-generation calls, and the client does not automatically
retry generation POSTs:

- Paid `generate_file`: `google/gemini-3.1-flash-tts-preview` with `Sulafat` produced a
  78,764-byte WAV. It parsed as 24 kHz, 16-bit, mono, 39,360 frames (1.64 seconds), was
  stored with mode 0600, and matched an unauthenticated `/local` HTTP 200 response byte
  for byte.
- Verified-free `tts.speak`: `deepgram/flux-tts:free` with `flux-bree-en` was selected
  through `free_only`. A temporary MPD test sink accepted the real Home Assistant
  media-source handoff and performed exactly one TTS-proxy GET: HTTP 200, `audio/mpeg`,
  9,936 bytes, 24 kHz mono MP3 (about 1.66 seconds). This validates the full HA service,
  resolution, and fetch path, but not a physical Chromecast or speaker.
- The dedicated key reported usage 0 before the test and USD 0.001683 after both calls.
  That result is consistent with the paid request and no separately observed charge for
  the catalog-confirmed free request, but it cannot guarantee future pricing.

The generated audio, TTS cache, temporary MPD entry, OpenRouter config entry, catalog
store, driver, and sink were removed. Core was restarted. Count-only scans found zero
credential patterns in Home Assistant storage and logs; the HA backup list and libvirt VM
snapshot list were empty, and the VM was shut down. The temporary upstream key must still
be revoked by its owner; filesystem cleanup is not a substitute for revocation. No private
host, entity ID, credential, proxy URL, or generated audio is retained in this repository.

During setup, placing a safety backup beneath `custom_components` made Home Assistant
discover two manifests for the same domain and reject the flow. Moving that backup out of
the integration search tree and restarting Core resolved the issue before the API-key
step; it was a test-harness placement error, not a product-code defect. No generation was
attempted during that failure.

### 2026-08-30 verified-free matrix

The refreshed OpenRouter catalog contained exactly one model that met all conservative
free-TTS eligibility requirements: `deepgram/flux-tts:free`, with 36 nonempty advertised
voices. Its metadata did not advertise speed support, so the integration omitted the
speed field. No paid or unknown-price model was used.

The run was limited to exactly five generation attempts. Every row below represents one
generation POST; neither the integration nor the harness automatically retried it.

| Attempt | Path and voice | Result |
| --- | --- | --- |
| 1 | HAOS `generate_file`, Flux Alexis, before the identity-header change | Failed with `invalid_audio`. |
| 2 | Direct OpenRouter, Flux Bree | HTTP 200 `audio/mpeg`; valid 13,248-byte MP3. Generation metadata identified `deepgram/flux-tts:free` and Deepgram and reported total cost/usage 0. |
| 3 | HAOS `generate_file`, Flux Alexis, before the identity-header change | Failed again with `invalid_audio`. |
| 4 | Direct OpenRouter, Flux Alexis | HTTP 200 `audio/mpeg`; valid 12,384-byte MP3. Generation metadata identified `deepgram/flux-tts:free` and Deepgram and reported total cost/usage 0. |
| 5 | HAOS `generate_file`, Flux Alexis, with speech POST `Accept-Encoding: identity` | Passed: valid 14,688-byte, 24 kHz mono MP3, saved successfully and retrieved through `/local`. |

The fifth result validates the changed request path but only correlates success with
`Accept-Encoding: identity`; the two earlier HAOS response bodies were not preserved, so
the underlying failure mechanism is not proven. Response validation remains strict, and
no fallback generation or parser relaxation was introduced.

The `/key` endpoint continued to report usage USD 0.001683, while both its usage and
remaining values had delta 0 over a 60-second post-run observation. That is consistent
with the direct generation metadata reporting zero cost for attempts 2 and 4, but remains
a point-in-time observation rather than a future price guarantee.

The five-attempt hard cap was reached, so this 2026-08-30 run did not issue another WAV
or `tts.speak` request. The verified-free Flux `tts.speak` media-source flow passed on
2026-08-29 as recorded above. All local test artifacts from the current run were removed.
The temporary upstream key still must be revoked by its owner.

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
Revision/tag: v0.1.0-beta.2 release candidate
Date (Asia/Seoul): 2026-08-30
Local: Python 3.14.4; 194 passed; branch-enabled combined coverage 88.57%; Ruff/format/mypy passed
Docker minimum: HA Core 2025.12.5; lifecycle and host-UID bind-mount save/read(0600)/delete passed
Docker stable: HA Core 2026.8.3; lifecycle and host-UID bind-mount save/read(0600)/delete passed
hassfest: passed; 0 invalid integrations
HACS validation: passed in public GitHub Actions Quality run 33239859740
HAOS: 18.2 / Core 2026.8.3; 2026-08-29 baseline path and 2026-08-30 final identity-header MP3 generate_file passed except the explicit gaps above
Live OpenRouter: 2026-08-29 paid Gemini generate_file + free Flux tts.speak passed; 2026-08-30 free-only matrix made exactly 5 attempts (2 pre-change HAOS failures, 2 direct zero-cost MP3 passes, 1 identity-header HAOS MP3 pass); /key usage 0.001683 with usage and remaining deltas both 0 over 60 seconds
Secret scan: Gitleaks 8.30.1 Git history and explicit credential patterns passed; Trivy 0.74.0 high/critical production findings 0
Known failures/skips: 2026-08-30 WAV and tts.speak were not run after the five-attempt hard cap; temporary-key owner revocation is pending; HAOS runtime reauthentication, invalid-pair UI exercise, and physical-speaker playback remain; the documented upstream dev/test cryptography advisory awaits a compatible Home Assistant pin
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
