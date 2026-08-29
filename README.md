# OpenRouter TTS for Home Assistant

<p align="center">
  <img src="docs/assets/openrouter-tts-icon.png" alt="OpenRouter TTS icon" width="160">
</p>

An unofficial Home Assistant custom integration that turns text into speech through
[OpenRouter](https://openrouter.ai/) and exposes the result as a Home Assistant TTS
entity. It can speak text immediately with `tts.speak`, or safely save reusable MP3
or WAV announcements for later playback.

> [!IMPORTANT]
> This community project is not affiliated with, endorsed by, or supported by
> Home Assistant, Nabu Casa, OpenRouter, or any model provider. Model availability,
> pricing, rate limits, capabilities, and provider routing can change at any time.

The integration is intended for general-purpose announcements. Laundry and appliance
notifications are useful examples, but no part of the implementation is tied to a
specific appliance or automation.

## Features

- UI setup through a Home Assistant Config Flow, including API-key validation and
  reauthentication.
- A dynamic catalog limited to models for which audio output and supported voices can
  be established from the current OpenRouter metadata.
- Atomic model and voice selection, configurable speed, and a conservative
  **All voice models / Confirmed free only** filter.
- A Home Assistant TTS entity for `tts.speak`.
- Administrator-only services to generate and delete reusable announcement files and
  refresh the model catalog.
- MP3, WAV, and known raw-PCM response handling, with a default 20 MiB response limit.
- A catalog cache with expiry, last-known-good fallback, and manual refresh.
- English and Korean UI translations.
- Safe path validation, overwrite protection, and atomic file replacement.

## Before you install

You need:

- Home Assistant 2025.12.0 or newer, on an installation type that allows custom
  integrations.
- An OpenRouter API key.
- Access to at least one audio-capable model and provider through that key.
- A media player that can retrieve media from your Home Assistant URL if you plan to
  play saved files on Chromecast or another network player.

An API key being valid does **not** prove that the account has enough balance, that a
particular model is enabled for the account, or that an upstream provider is currently
available. A successful setup check therefore cannot guarantee that every later speech
request will succeed.

## Installation

### HACS custom repository

Until this project is listed in the default HACS catalog, add it as a custom repository:

1. Open HACS in Home Assistant and select **Integrations**.
2. Open the menu in the upper-right corner and select **Custom repositories**.
3. Add `https://github.com/Kanu-Coffee/home-assistant-openrouter-tts` with category
   **Integration**.
4. Search for **OpenRouter TTS**, open it, and select **Download**.
5. Restart Home Assistant when HACS asks you to.
6. Go to **Settings → Devices & services → Add integration**, search for
   **OpenRouter TTS**, and enter your API key.

### Manual installation

1. Download a release archive from the repository's Releases page. Avoid using an
   arbitrary development-branch snapshot on a production Home Assistant instance.
2. Copy the complete `custom_components/openrouter_tts` directory into your Home
   Assistant configuration directory so the final path is:

   ```text
   /config/custom_components/openrouter_tts/
   ```

3. Restart Home Assistant.
4. Add **OpenRouter TTS** from **Settings → Devices & services → Add integration**.

Do not place your API key in `configuration.yaml`, automations, issue reports, or the
integration directory.

## Configuration

During the Config Flow, the integration validates the API key, retrieves the current
catalog, and then asks for the initial model, voice, speed, and storage root. Configuration
is stored by Home Assistant as a config entry. Treat Home Assistant backups and the hidden
`.storage` directory as sensitive because config-entry secrets are not a substitute for an
encrypted secret manager.

Open **Settings → Devices & services → OpenRouter TTS → Configure** to use the Options
Flow and change:

| Option | Meaning |
| --- | --- |
| Model display scope | Show all confirmed voice models, or only models conservatively classified as free. |
| Model | Default model used for speech generation. |
| Voice | A voice confirmed for the selected model. |
| Speed | Requested speech speed. `1.0` may be omitted from the upstream request for compatibility. Models without confirmed or adapted speed support are not sent this field. |
| Storage root | Root directory for saved announcement files. The default is `/config/www/audio/tts`. |
| Refresh catalog | Discard the current catalog TTL for this update and fetch fresh capability, voice, availability, and pricing metadata. |

Model and voice are validated and saved together. Changing the filter never silently
replaces the currently configured paid model. If the selected voice is invalid for a
new model, the options form requires you to choose a valid pair before it saves.

If a configured model temporarily disappears from OpenRouter's catalog, the integration
retains the current setting and the last known good catalog where possible. Generation
can still fail if OpenRouter or the upstream provider no longer serves that model.

### Free-model filter

**Confirmed free only** is intentionally conservative:

- A candidate must first have confirmed audio-output capability and supported voices.
- An official `:free` suffix is recognized as a free-variant signal, but it does not
  override missing, ambiguous, conditional, or explicitly positive price metadata.
- Otherwise, all pricing fields relevant to TTS must be present, understandable, and
  exactly zero. Decimal values are evaluated without binary floating-point rounding.
- Any positive relevant price makes the model paid.
- Missing, `null`, ambiguous, or incomplete pricing is classified as **unknown**, not
  free.
- Generic routers such as `openrouter/free` are excluded unless their metadata also
  confirms TTS output and voice support.

Free models are labeled **(Free)** in English or the corresponding translated label.
If no free TTS model is confirmed, the form says so and leaves your saved model/voice
unchanged; return to **All voice models** to continue.

> [!WARNING]
> “Free” describes the catalog metadata at the time it was fetched. It is not a price
> guarantee. OpenRouter or a routed provider may change pricing, rate limits, routing,
> or availability between catalog refresh and generation. Review current pricing in
> OpenRouter before relying on the filter.

### Reauthentication

When OpenRouter rejects the stored credential, Home Assistant starts a reauthentication
flow. Enter a replacement key there. If you suspect exposure, revoke the old key in
OpenRouter first; reauthentication in Home Assistant does not revoke it remotely.

## Speak immediately with `tts.speak`

Find the entity created by this integration under **Settings → Devices & services** and
use its actual entity ID in place of `tts.openrouter_tts`:

```yaml
action: tts.speak
target:
  entity_id: tts.openrouter_tts
data:
  media_player_entity_id: media_player.announcement_speaker
  message: "The scheduled task is complete."
  cache: false
```

The selected config-entry model, voice, and speed are used. Speech generation requests
are not automatically retried without limit: a failed request may already have been
billed, so retry behavior is deliberately conservative.

For privacy-sensitive messages, keep `cache: false`. Home Assistant's core TTS cache is
outside this custom integration: depending on the Home Assistant version and audio
format, it can derive cache keys from the message and can write message metadata into a
cached file. Clear the core cache after testing with:

```yaml
action: tts.clear_cache
```

`cache: false` is not a complete secrecy boundary. Home Assistant automation traces,
service-call tooling, core TTS diagnostics, and other enabled logging can retain the
message or service data before this integration receives it. This integration redacts
its own API-key, response-body, and complete-message diagnostics, but it cannot redact
records owned by Home Assistant core or other integrations. Review and delete traces and
logs before sharing them. Reusable public announcements are better generated with
`generate_file` using deliberately non-sensitive text.

## Save a reusable announcement

`openrouter_tts.generate_file` is an administrator-only service. It uses the current
model, voice, and speed from the selected config entry.

```yaml
action: openrouter_tts.generate_file
data:
  text: "The appliance cycle is complete."
  filename: appliance_complete
  subdirectory: household
  format: wav
  overwrite: false
response_variable: generated_audio
```

Service fields:

| Field | Required | Description |
| --- | --- | --- |
| `config_entry_id` | Only with multiple entries | Selects the OpenRouter TTS config entry. The service UI provides a selector. |
| `text` | Yes | Text sent to OpenRouter and the routed model provider. |
| `filename` | Yes | A single filename, either without an extension or with `.mp3`/`.wav`. Absolute paths, separators, `..`, null bytes, hidden names, and other extensions are rejected. |
| `subdirectory` | No | A relative path below the configured storage root. Traversal and symlink escapes are rejected. |
| `format` | No | `mp3` or `wav`; defaults to `mp3`. |
| `overwrite` | No | Defaults to `false`. Existing files are preserved unless an administrator explicitly enables replacement. |

The response contains only non-sensitive metadata: `filename`, `url` when a local URL
can be derived, `format`, `size`, and `model`. It does not echo the complete input text.
If `filename` includes `.mp3` or `.wav`, the validated response format still wins and the
integration replaces the supplied extension when necessary. Use the returned `filename`,
`format`, and `url` rather than assuming an upstream provider honored the requested
container. In particular, a provider may return known 24 kHz, 16-bit, mono raw PCM; the
integration wraps such data in a valid WAV container instead of saving mislabeled bytes.

Files are completely downloaded and validated before an atomic move into place. Failed
requests should not leave a partial destination file. Audio is checked using response
headers, magic bytes, requested extension, and size; HTML/JSON error bodies and files
over the configured limit are rejected.

### Storage trust boundary and filesystems

The Home Assistant config directory is an administrator-selected trust anchor. Within
that directory, storage paths owned by root, the Home Assistant process effective UID, or
the config directory's numeric owner are trusted. A process running as one of those
identities is already privileged with respect to Home Assistant configuration and is not
an attacker this file-store layer can isolate from.

Existing config and storage directories must not be group- or world-writable. Unsafe
ownership, writable modes, symlinks, or directory identity changes make the operation fail
closed. Newly published audio is mode 0600; private staging is mode 0700, and ordinary
created directories request mode 0755 subject to the process umask. Files served from
`/config/www` are still reachable through `/local` as described below because Home
Assistant reads and serves them under its own identity.

Use a local POSIX filesystem when possible. Depending on mount options, CIFS, FAT, or NFS
may not provide stable Unix ownership/modes or the directory-descriptor, hard-link, atomic
rename, and `fsync` behavior required by the safety checks. Generation or deletion can be
rejected on such a mount rather than silently weakening confinement. If this happens,
move the storage root to a compatible path inside the Home Assistant config directory or
correct the mount's ownership and permission mapping.

### Play a saved file

With the default storage root, the example above is stored as:

```text
/config/www/audio/tts/household/appliance_complete.wav
```

Home Assistant exposes files below `/config/www` through `/local`, so a corresponding
URL is:

```text
/local/audio/tts/household/appliance_complete.wav
```

If `/config/www` did not exist when Home Assistant started and this integration creates
it for the first saved file, restart Home Assistant once so the `/local` static route is
registered. Creating later files below an already active `www` directory should not need
another restart.

For Chromecast and similar devices, use an absolute Home Assistant URL that the player
can reach:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.announcement_speaker
data:
  media_content_id: "http://homeassistant.local:8123/local/audio/tts/household/appliance_complete.wav"
  media_content_type: "audio/wav"
```

Use HTTPS and an appropriate internal or external hostname for your installation.
Changing the storage root to a directory outside `/config/www` does not automatically
publish that directory, and the service response may therefore have no `/local` URL.

> [!CAUTION]
> `/config/www` is a web-published directory. Files under `/local/...` may be retrievable
> without Home Assistant authentication by anyone who can reach and guess or learn the
> URL. The integration does not add access control to these files. Do not store private
> speech there. Use non-predictable filenames where appropriate, restrict network
> exposure, or choose a non-web storage root and serve files through an authenticated
> mechanism. Home Assistant documents the unauthenticated behavior in its
> [resource-registration guide](https://developers.home-assistant.io/docs/frontend/custom-ui/registering-resources/).

Names and URL path segments are encoded independently when a URL is returned. Never
construct a public URL from untrusted input without encoding it.

## Catalog maintenance

The catalog is cached to reduce API usage. Refresh it from the Options Flow with
**Refresh catalog**, or call the administrator-only service:

```yaml
action: openrouter_tts.refresh_catalog
data: {}
```

Supply `config_entry_id` when more than one OpenRouter TTS entry exists. Refreshing also
updates free-status and pricing metadata. It does not guarantee that a provider remains
available for the lifetime of the cache.

## Delete generated files

Use the administrator-only cleanup service rather than accepting an arbitrary filesystem
path from an automation:

```yaml
action: openrouter_tts.delete_file
data:
  filename: appliance_complete.wav
  subdirectory: household
```

For deletion, `filename` includes the `.mp3` or `.wav` extension. `config_entry_id` is
required only when multiple entries exist. The same root confinement and symlink checks
used for generation apply to deletion.

You can also remove files manually from the configured storage root using Home Assistant
File editor, Samba, SSH, or another trusted administrator tool. Verify the exact root
before deleting anything. Removing the integration does not automatically delete audio
files, because those files may still be referenced by your automations.

## Privacy, credentials, and cost

- Every message submitted for generation leaves your Home Assistant instance. It is sent
  to OpenRouter and may be sent onward to the selected model provider under their current
  privacy and retention terms.
- Avoid names, addresses, health information, credentials, alarm codes, or other sensitive
  content. Home Assistant automation traces or service-call tooling may retain inputs even
  though this integration avoids logging complete prompts.
- Generated audio is stored locally when `generate_file` is used. Under `/config/www`, it
  carries the exposure warning described above.
- The integration does not log API keys or complete upstream response bodies by design.
  Still inspect and redact diagnostic downloads, traces, screenshots, and logs before
  sharing them.
- Never commit an API key. For opt-in development tests, inject it through an environment
  variable or a GitHub Actions secret and remove or rotate it afterward.
- Pricing, free status, quotas, model access, provider availability, and rate limits can
  change without an integration update. OpenRouter's current billing page is the source
  of truth for charges.

## Troubleshooting

### No models or voices are shown

Refresh the catalog, switch the display scope to **All voice models**, and verify current
OpenRouter model metadata. Models without confirmed audio output and voices are excluded;
unknown pricing is also excluded from **Confirmed free only**.

### The key is accepted but generation fails

Check account balance, model access, provider availability, and model-specific limits in
OpenRouter. Key validation alone does not test every provider/model combination. A 401 or
403 usually requires credential or access correction; a 429 means a rate limit and may
include a `Retry-After` delay; a 5xx response indicates a transient upstream failure.

### A model or voice stopped working

Refresh the catalog and choose a currently valid model/voice pair in Configure. Providers
may remove voices or capabilities. The previous selection is retained rather than silently
changed, but it may no longer generate audio.

### Speed appears to have no effect

Not every model supports speed. The integration omits the field when capability metadata
does not confirm support, and some routed providers may ignore it even when accepted.

### A saved file is not reachable at `/local`

Confirm that the storage root is below `/config/www`, URL-encode names, and verify the
media player can reach the Home Assistant hostname. If the `www` directory was first
created after Home Assistant started, restart Home Assistant once. A custom storage root
outside `/config/www` has no automatic `/local` mapping.

### The storage path is reported as unsafe

The integration rejects symbolic links and directories that are writable by another OS
user or group, because those permissions allow the destination tree to be moved during
an atomic write. Keep the configuration directory, storage root, and intervening
directories owned by root or the Home Assistant process identity and remove group/world
write bits. Do not change permissions blindly on a shared or managed installation; use
the installation's supported file-management method or choose another private directory
below the Home Assistant configuration root.

### Enable debug logging

Temporarily add:

```yaml
logger:
  default: info
  logs:
    custom_components.openrouter_tts: debug
```

Restart Home Assistant, reproduce the issue once, and then disable debug logging. Before
sharing output, search for and remove keys, bearer headers, private hostnames, messages,
file paths, config-entry IDs, and other personal data. Do not post an entire Home Assistant
diagnostic archive publicly unless you have reviewed it.

See [SUPPORT.md](SUPPORT.md) for the information useful in a support request.

## Removal

1. Delete unwanted generated audio with `openrouter_tts.delete_file` or a trusted file
   management method. Audio files are intentionally not removed automatically.
2. Remove the config entry under **Settings → Devices & services → OpenRouter TTS**.
3. Remove the integration through HACS, or delete only
   `/config/custom_components/openrouter_tts` for a manual installation.
4. Restart Home Assistant.
5. Revoke the OpenRouter key if it was dedicated to this installation or may have been
   exposed.

## Development and release status

This project is under active development. A feature appearing in source or documentation
does not mean it has passed a particular Home Assistant, HACS, Docker, HAOS, provider, or
real-API test. Consult the checks attached to the exact commit or release and its release
notes for verified environments and known limitations. Normal CI is mock-based and must
not require an OpenRouter API key; any live-provider check is explicit and opt-in.

The manual `.github/workflows/live-smoke.yml` workflow reads its API credential only from
the `OPENROUTER_API_KEY` GitHub environment secret. By default it validates the key and
catalog without generating audio. Its optional generation switch sends exactly one short
`Test.` request only when the current catalog contains a conservatively verified free TTS
model; otherwise it sends no generation request. It never selects a paid or unknown-cost
model as a fallback.

Latest recorded verification for the 2026-08-29 `v0.1.0-beta.1` release candidate:

- The local mock suite passed all 193 tests on Python 3.14.4 with 88.57%
  branch-enabled combined coverage. Ruff lint, Ruff formatting, and strict mypy checks
  also passed.
- Home Assistant Core 2025.12.5 and 2026.8.3 Docker checks both passed integration import
  and config-entry setup → unload → setup. On both versions, a host-UID-owned mode-0755
  config bind mount also passed actual save/read as mode 0600 and deletion. Hassfest
  reported zero invalid integrations.
- On HAOS 18.2 with Core 2026.8.3, the isolated test path passed a new installation,
  invalid-key handling, options and restart persistence, catalog refresh, 24 kHz/16-bit/
  mono WAV file generation, `/local` retrieval, and `tts.speak` MP3 media-source fetch.
- Config-entry reload, generated-file deletion, integration removal, and a credential
  pattern log scan also passed on that HAOS test path. Home Assistant core retained the
  complete non-sensitive `Test.` text while reporting a deliberately encountered
  pre-fix TTS error, confirming the cache/trace/log privacy limitation documented above.
  Runtime reauthentication, an invalid model/voice submission through the HAOS UI, and
  `tts.clear_cache` were not exercised. The public repository's HACS validation passed.
  No real OpenRouter API call has been made, and the live smoke workflow has not been
  run.
- Gitleaks found no secret in the complete local Git history, explicit OpenRouter-key and
  bearer-token pattern checks found no credential, and Trivy reported no unfixed high or
  critical production dependency finding.

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and
[CHANGELOG.md](CHANGELOG.md). The current verification matrix, including pending checks,
is maintained in [docs/TESTING.md](docs/TESTING.md).

## 한국어 요약

OpenRouter TTS는 OpenRouter의 음성 모델을 Home Assistant `tts.speak` 및 고정 안내
파일 생성에 연결하는 **비공식** 커스텀 통합입니다. 설정 화면에서 모델·voice·속도·
저장 경로와 전체/무료 확인 모델 필터를 변경할 수 있습니다.

- 음성 생성 문장은 OpenRouter와 선택된 모델 공급자에게 외부 전송됩니다.
- 무료 표시는 마지막 카탈로그 조회 시점의 보수적 판정이며 실제 무료 사용이나
  향후 가격을 보장하지 않습니다.
- API 키가 유효해도 잔액, 모델 권한, 공급자 가용성은 보장되지 않습니다.
- 기본 저장 경로 `/config/www/audio/tts`는 `/local/audio/tts/...`로 노출됩니다.
  `/config/www`의 파일은 URL을 아는 네트워크 사용자가 인증 없이 가져갈 수 있으므로
  민감한 음성을 저장하지 마세요. Home Assistant 시작 당시 `www` 폴더가 없었다면 최초
  생성 후 `/local` 경로 등록을 위해 한 번 재시작해야 할 수 있습니다.
- 설치는 HACS의 사용자 저장소에
  `https://github.com/Kanu-Coffee/home-assistant-openrouter-tts`를 Integration 유형으로
  추가하거나, 릴리스의 `custom_components/openrouter_tts` 폴더를
  `/config/custom_components/` 아래에 복사한 뒤 Home Assistant를 재시작하면 됩니다.
- 고정 파일은 `openrouter_tts.generate_file`, 카탈로그 갱신은
  `openrouter_tts.refresh_catalog`, 안전한 정리는 `openrouter_tts.delete_file` 서비스를
  사용하세요. 세 서비스는 관리자 전용입니다.
- 문제를 공유하기 전에 로그·진단·자동화 trace에서 키, 전체 문장, 개인 주소와 경로를
  반드시 제거하세요.
- 최소 지원 버전은 Home Assistant 2025.12.0이며, 민감한 `tts.speak` 호출에는
  `cache: false`를 사용하고 테스트 후 `tts.clear_cache`를 실행하세요. 다만 자동화
  trace와 Home Assistant 코어의 서비스 호출 기록까지 이 통합이 삭제할 수는 없습니다.

## License

[MIT](LICENSE)
