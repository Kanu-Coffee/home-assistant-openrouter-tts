# Security Policy

## Supported versions

Security fixes are made on the latest stable minor release and the default branch. Users
should run the newest patched release compatible with their Home Assistant installation.

| Version | Supported |
| --- | --- |
| 0.2.x | Yes |
| 0.1.x prereleases and development snapshots | No |

## Report a vulnerability privately

Do not open a public issue for a vulnerability or suspected credential leak. Use
[GitHub's private vulnerability reporting](https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/security/advisories/new).

Include only what is necessary to reproduce the problem:

- A concise description and likely impact.
- Affected version or commit.
- Reproduction steps using placeholder credentials and non-sensitive text.
- Relevant code locations and a suggested mitigation, if known.

Do **not** attach real API keys, authorization headers, Home Assistant backups, `.storage`
contents, private prompts, personal audio, private hostnames, or unredacted logs. If a
proof requires a secret, create a limited disposable credential, redact it from the report,
and revoke it immediately afterward.

The maintainers will make a best-effort acknowledgement, investigate, coordinate a fix,
and credit reporters who want attribution. Please allow time for a patched release before
public disclosure.

## Security-relevant areas

Reports are especially useful for:

- API-key exposure through logs, exceptions, diagnostics, services, or storage.
- Authorization bypasses for administrator-only file or catalog services.
- Writes or deletes outside the configured storage root, including traversal, symlink,
  TOCTOU, or overwrite issues.
- Unsafe handling of oversized, malformed, mislabeled, or non-audio responses.
- Requests to unintended hosts or leakage through redirects and error bodies.
- Persistent prompt disclosure or supposedly anonymized hashes that allow guessing short
  announcements.

Provider outages, model-quality complaints, ordinary OpenRouter rate limits, account
billing disputes, and expected `/config/www` public exposure are not vulnerabilities in
this project. They may still be appropriate support issues when no private data is shared.

## If a key may be exposed

1. Revoke the key in OpenRouter immediately.
2. Create a replacement with the least access and spending limit appropriate for the
   installation.
3. Complete the Home Assistant reauthentication flow.
4. Remove the key from logs, issue comments, artifacts, automation traces, shell history,
   screenshots, backups, and Git history where applicable. Deleting a GitHub comment alone
   should not be treated as sufficient revocation.
5. Review OpenRouter usage and billing for unexpected activity.

Home Assistant config-entry storage and backups should be protected as sensitive data.
This integration cannot revoke upstream credentials for you.

## Live-test environment

Do not add `OPENROUTER_API_KEY` as an ordinary repository secret. Store it only in the
`live-openrouter-test` GitHub environment after restricting deployment branches to
`main`. Add a required reviewer and prevent self-review when another trusted maintainer
is available. The manual workflow checks and checks out `main`, and third-party actions
are pinned to commits, but those YAML controls do not replace the server-side environment
policy because a workflow dispatched from another ref can contain different YAML.

## Upstream development dependency advisory

The locked development/test graph includes Home Assistant 2026.8.3, which pins
`cryptography==48.0.1`. GitHub therefore reports
[GHSA-g6cj-pr64-35w5](https://github.com/advisories/GHSA-g6cj-pr64-35w5); version 50.0.0
is the first patched release. This repository has no packaged runtime dependency on
`cryptography`, and neither the integration nor its tests call the affected PKCS#7
EnvelopedData decryption APIs or expose an adaptive decryption service. The alert is
dismissed as `not_used` for this repository because forcing version 50 would violate the
tested Home Assistant package constraint. Reassess the dismissal as soon as upstream
Home Assistant permits version 50 or later. Users should still install Home Assistant
security updates; this project cannot remediate Home Assistant's own dependency graph.

An include-development-dependencies Trivy scan also reports CVE-2026-69249 against the
locked 48.0.1 version. The upstream
[GHSA-jwv3-5hgf-82ww](https://github.com/advisories/GHSA-jwv3-5hgf-82ww) advisory marks
versions earlier than 48.0.0 as affected and rates the issue Low, so 48.0.1 is outside
that published range. This is recorded as a scanner-database mismatch rather than hidden
as a fixed dependency.

## Storage trust boundary

The administrator-selected Home Assistant config directory is the storage trust anchor.
Below that anchor, the implementation treats root, the Home Assistant process effective
UID, and the config directory's numeric owner as trusted. A process with any of those
identities can already alter Home Assistant configuration or generated audio; the storage
layer does not claim to sandbox it.

Existing config and storage directories must not be group- or world-writable. The store
also checks ownership, rejects symlinks, pins directory file descriptors, and revalidates
directory identity before publishing or deleting. Generated audio is mode 0600, and its
private staging directory is mode 0700. Files below `/config/www` nevertheless remain
reachable through Home Assistant's unauthenticated `/local` HTTP mapping because Home
Assistant serves them using its own filesystem access.

These checks rely on POSIX filesystem behavior. CIFS, FAT, and NFS behavior varies by
server and mount options; ownership/mode emulation, missing hard-link support, weak
`fsync`, or nonstandard rename/directory-descriptor semantics can be incompatible. The
integration may reject an unsafe-looking path or fail a save/delete rather than bypass
its checks. Use a local POSIX filesystem or configure the mount to provide stable Unix
UIDs, modes, hard links, atomic rename, directory file descriptors, and `fsync` semantics.
Do not make the config tree group/world-writable as a workaround.
