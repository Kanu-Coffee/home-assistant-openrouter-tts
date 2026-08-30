# Verification matrix

This file records what has actually been exercised for the exact source revision. A test
or workflow existing in the repository is not evidence that it passed. Update the status,
date, revision, command, and evidence after every release-candidate run; leave failed or
skipped checks visible.

## Current release status

Status as of 2026-08-30 for the final `v0.2.0` release source. Earlier beta results
remain below as historical evidence and are kept separate from final-source validation:

| Area | Target | Status | Evidence or next action |
| --- | --- | --- | --- |
| Mock unit/integration suite | Final v0.2.0 source and locked Python environment | Passed | 212 tests passed. Branch-enabled combined coverage: 89.26%. No real OpenRouter key was used by the suite. |
| Ruff | Final v0.2.0 Python source and tests | Passed | `ruff check` and `ruff format --check` both passed. |
| Mypy | Final v0.2.0 integration package | Passed | Strict package type checking completed without an issue. |
| Minimum-version compatibility | Home Assistant 2025.12.0 container | Passed | Import, service/resource parsing, setup → unload → setup, and host-UID mode-0755 bind-mount save/read (mode 0600)/delete passed. Image digest: `sha256:8951fcbb794da8f261e1639c668639bc90f9520b48099b5715f6d5fbfef08a0e`. |
| Current-stable compatibility | Home Assistant 2026.8.3 container | Passed | The same lifecycle and secure-storage checks passed. Image digest: `sha256:14931c6b13756317849f46da1d01b45937a1150db66c081cfe529d48215943fe`. |
| hassfest | Final v0.2.0 repository | Passed | Local official validation reported one integration and zero invalid integrations. |
| HACS validation | Public v0.2.0 release source | Passed; repeated on tag target | The pinned HACS job passed in [Quality run 33288925411](https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/actions/runs/33288925411). The My Home Assistant badge and redirect returned HTTP 200 with the intended owner/repository/category. The same pinned job is required to pass again on the final documentation commit before tagging. |
| HAOS end-to-end | HAOS 18.2 / Core 2026.8.3, final v0.2.0 component bytes | Passed with explicit generation gap | Config Flow exposed Fish as free and the provider-default voice, Options committed `free_only` atomically, one real Core restart preserved settings, manual refresh returned a fresh catalog, explicit entry reload passed, and the TTS entity loaded. Cleanup, final Core restart, zero entry/store/audio/token/credential-pattern counts, empty backup/snapshot lists, and VM shutdown passed. This final-source run intentionally made zero speech POSTs. |
| OpenRouter live provider | `fish-audio/s2.1-pro-free:free`, direct and controlled HAOS paths | Passed provider behavior; final-source generation not repeated | Exactly 10 point-in-time attempts produced 9 successes; all 8 provider-default calls passed and one explicit public reference ID returned HTTP 400 without retry. Metadata/meter observations were zero-cost. The cap was already consumed, so final v0.2.0 bytes were validated with catalog/key GETs and mock wire assertions, not another generation POST. |
| Secret scan | Final tracked worktree and complete Git history | Passed | Gitleaks 8.30.1 found no leak after the release commits. Explicit long key/bearer and private-address checks found zero tracked files; no audio remained. Trivy found no secret in the production component, whose manifest declares no runtime package requirements. |
| Upstream dev/test advisory | `cryptography==48.0.1` via Home Assistant 2026.8.3 | Dismissed as `not_used`; tracked | [GHSA-g6cj-pr64-35w5](https://github.com/advisories/GHSA-g6cj-pr64-35w5) affects PKCS#7 EnvelopedData decryption, which this integration and its tests do not call or expose. Home Assistant pins 48.0.1 exactly; reassess when upstream permits 50.0.0 or later. A full-development Trivy scan also flags CVE-2026-69249, but the [upstream advisory](https://github.com/advisories/GHSA-jwv3-5hgf-82ww) affects versions before 48.0.0, so locked 48.0.1 is outside its published range. |

The stable tag is created only after the exact public revision's required workflows pass.

## Current mock test scope

The repository contains mock/pure tests for these areas. This list describes intended
scope, not the outcome of the next full run:

- `test_pricing.py`: `:free`, complete zero-price, positive-price, missing, null,
  malformed, conditional, and future pricing fields.
- `test_catalog.py`: capability/voice parsing, availability, filtering, TTL/persistence,
  stale last-known-good behavior, refresh, disappeared models/voices, price changes, and
  the exact Fish `supported_voices: null` adapter without widening the exception to a
  missing key, empty list, other Fish model, or unrelated model.
- `test_audio.py`: MP3, WAV, raw PCM conversion, MIME/magic mismatches, malformed data,
  and response-size limits.
- `test_storage.py`: lexical path checks, absolute paths, traversal, symlink escape,
  encoded URLs, overwrite protection, deletion, trusted ownership/mode checks, staging
  permissions, directory-identity races, and atomic publish.
- `test_api.py`: authentication/access/validation/rate-limit/server statuses, separated
  timeout errors, bounded bodies, `Retry-After`, request fields, Fish provider-default
  `voice`/unsupported `speed` omission, and sensitive-data redaction.
- `test_config_flow.py`: setup, invalid credentials, reauthentication, Options Flow,
  empty-free-filter behavior, exact Fish provider-default UI labeling, and atomic
  model/voice validation.
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

The checked items above describe the earlier beta runs. The following v0.2.0 delta was
checked separately against the final component bytes:

- [x] Confirm `fish-audio/s2.1-pro-free:free` appears in both **All voice models** and
  **Confirmed free only** only when the catalog explicitly contains
  `supported_voices: null` and the required speech/price metadata.
- [x] Confirm the UI shows the localized provider-default option, saves the
  exact model/pseudo-voice pair atomically, and preserves it through restart,
  unload/reload, catalog refresh, and Options Flow.
- [x] Confirm final-source mock wire tests omit both `voice` and unsupported `speed`, and
  reject forged sentinels and null/missing/empty metadata outside the exact adapter.
- [ ] Repeat a live final-source `generate_file` or `tts.speak` request. **Not run:** the
  user-approved ten-attempt Fish cap had already been consumed. The separate live probe
  below remains the provider-behavior evidence; no eleventh generation was sent.
- [x] Remove the catalog store and test entry, revoke the test refresh token, restart
  Core, and confirm zero entry/store/audio/credential-pattern counts without recording
  credentials, messages, private URLs, or entity IDs.
- [x] Open the README My Home Assistant badge and confirm it targets owner
  `Kanu-Coffee`, repository `home-assistant-openrouter-tts`, category `integration`.

The final-source HAOS harness permitted only OpenRouter `GET /key`, speech-catalog GET,
and exact-model endpoint GET requests. It reported speech-generation requests 0 and an
unchanged key meter after 60 seconds. The deployed component tree matched the local
candidate byte for byte. Backups and libvirt snapshots remained at zero, and the VM was
shut down after cleanup. A physical speaker, runtime reauthentication, and an invalid-pair
UI submission remain not run on this final-source pass; their mock or earlier-beta
coverage is recorded separately.

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

Under the beta.2 rule that required nonempty advertised voices, the refreshed OpenRouter
catalog contained exactly one conservatively eligible free TTS model:
`deepgram/flux-tts:free`, with 36 advertised voices. Its metadata did not advertise speed
support, so the integration omitted the speed field. No paid or unknown-price model was
used.

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

### 2026-08-30 Fish exact-model compatibility probe

OpenRouter's current catalog identified `fish-audio/s2.1-pro-free:free` as text input and
speech output with explicit zero pricing, but returned `supported_voices: null` and no
advertised speed parameter. OpenRouter documents that `voice` may be omitted only for a
provider with a documented default, and Fish Audio's quick start identifies its
voice-less examples as using the default voice. A temporary, exact-ID test adapter
therefore exposed one provider-default pseudo voice and omitted both `voice` and `speed`
on the wire. It did not accept a missing voice key, an empty list, another Fish model, or
another model with null metadata.

The run reserved and enforced exactly ten generation attempts. It did not automatically
retry any failed generation request:

| Attempt | Path and voice mode | Result |
| --- | --- | --- |
| 1 | Direct, provider default, English MP3 | Passed: valid 35,943-byte, 44.1 kHz mono MP3. |
| 2 | Direct, one public Fish reference ID, MP3 | HTTP 400; no response body or reference ID retained, and no retry. |
| 3 | Direct, a different public Fish reference ID, MP3 | Passed: valid 32,181-byte, 44.1 kHz mono MP3. This does not establish a supported product voice list. |
| 4 | Direct, provider default, response format omitted | Passed: raw PCM normalized to a valid 167,980-byte, 44.1 kHz, 16-bit mono WAV. |
| 5 | Direct, provider default, numeric/punctuation text, PCM | Passed: valid 413,740-byte, 44.1 kHz, 16-bit mono WAV. |
| 6 | Direct, provider default, Korean MP3 | Passed: valid 41,794-byte, 44.1 kHz mono MP3. |
| 7 | Direct, provider default, expressive mixed-language MP3 | Passed: valid 66,454-byte, 44.1 kHz mono MP3. |
| 8 | HAOS, provider default, `generate_file` MP3 | Passed: saved file and `/local` retrieval both validated. |
| 9 | HAOS, provider default, Korean `generate_file` WAV/PCM | Passed: saved WAV structure and `/local` retrieval both validated. |
| 10 | HAOS, provider default, `tts.speak` | Passed through a controlled media-player sink that fetched the TTS proxy exactly once. |

The outcome was 9 successes and one HTTP 400. All eight provider-default requests
succeeded. Successful direct generation records identified the exact model and Fish
Audio provider and reported total cost/usage 0. The key usage and remaining values had
delta 0 through a final 60-second observation. Those facts are a point-in-time
observation, not a guarantee of free future use; OpenRouter describes this variant as
low-volume/testing use without production latency or availability guarantees.

No physical Chromecast or speaker was exercised. The public reference-ID success is not
used by the product and does not justify advertising arbitrary Fish voices. The HAOS
entry, audio files, `/local` artifacts, TTS cache, catalog store, temporary sink, test
overlay, and local credential material were removed; Core was restored and the VM was
shut down. The credential owner must still revoke the temporary upstream key. Final
v0.2.0 UI, atomic-options, restart, refresh, reload, cleanup, and mock wire behavior were
subsequently validated as described above; live generation was intentionally not repeated
after the ten-call cap.

Official references: [OpenRouter model page](https://openrouter.ai/fish-audio/s2.1-pro-free:free),
[OpenRouter TTS guide](https://openrouter.ai/docs/guides/overview/multimodal/tts), and
[Fish Audio quick start](https://docs.fish.audio/developer-guide/getting-started/quickstart).

## Manual OpenRouter smoke test

`.github/workflows/live-smoke.yml` is `workflow_dispatch` only and reads the
`OPENROUTER_API_KEY` secret from the protected `live-openrouter-test` environment. Its
default mode validates the key and current catalog without generating speech. If the
operator explicitly enables generation, the script:

1. fetches the live catalog;
2. requires a conservatively verified free TTS model with advertised voices or an
   explicitly supported provider-default adapter;
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
Revision/tag: v0.2.0 release source (the tag target is recorded by the GitHub Release)
Date (Asia/Seoul): 2026-08-30
Local: Ruff/format/strict mypy passed; 212 pytest cases passed; branch-enabled combined coverage 89.26%
Docker minimum: HA Core 2025.12.0 passed lifecycle and secure-storage checks; digest sha256:8951fcbb794da8f261e1639c668639bc90f9520b48099b5715f6d5fbfef08a0e
Docker stable: HA Core 2026.8.3 passed the same checks; digest sha256:14931c6b13756317849f46da1d01b45937a1150db66c081cfe529d48215943fe
hassfest: passed locally; one integration, zero invalid
HACS validation: pinned HACS job passed in Quality run 33288925411 on the release source; badge/redirect HTTP 200; the same job is required on the final docs-only tag target
HAOS: final component bytes passed Fish Free/provider-default Config Flow, atomic free_only Options Flow, real restart persistence, fresh manual refresh, explicit reload, TTS entity load, cleanup, final restart, zero credential/artifact counts, and VM shutdown; speech POST count 0
Live OpenRouter: separate Fish exact-model behavior probe completed exactly 10 attempts: 9 passed, 1 explicit public reference-ID request returned HTTP 400 without retry; all 8 provider-default attempts passed; successful metadata and 60-second meter observation reported zero cost/delta; final-source generation intentionally not repeated after the cap
Secret scan: Gitleaks 8.30.1 passed after the release commits; explicit long key/bearer/private-IP checks and workspace audio count were zero
Known failures/skips: the Fish catalog reports supported_voices null and the provider chooses an unpinned default voice; production latency/availability and future free pricing are not guaranteed; final-source live generation, physical-speaker playback, HAOS runtime reauthentication, and invalid-pair UI exercise were not run; temporary-key owner revocation is pending; the documented upstream dev/test cryptography advisory awaits a compatible Home Assistant pin
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
