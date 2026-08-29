# Contributing

Thank you for helping improve OpenRouter TTS. This is a community project and is not an
official Home Assistant, Nabu Casa, OpenRouter, or model-provider product.

## Before opening a change

- Search existing issues and pull requests.
- Use a GitHub Security Advisory rather than a public issue for vulnerabilities; see
  [SECURITY.md](SECURITY.md).
- Keep proposals provider-neutral and useful for general Home Assistant announcements.
- Do not include API keys, authorization headers, complete private prompts, generated
  personal audio, Home Assistant backups, private URLs, or unredacted diagnostics.

Small bug fixes can go directly to a pull request. For a new service, storage-format
change, compatibility break, or provider-specific adapter, open a feature request first
so the public contract can be discussed.

## Development environment

The repository uses Python tooling declared in `pyproject.toml`. A typical `uv` workflow
is:

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python -m pytest
```

If the exact dependency-group or command changes, follow `pyproject.toml` and the current
GitHub Actions workflows rather than copying an old command from an issue. Do not install
or upgrade global tools solely for this project.

Normal tests must use mocked OpenRouter responses. A live test must be explicit and
opt-in, use a short non-sensitive sentence, minimize billable calls, and receive its key
through `OPENROUTER_API_KEY` or a repository secret. It must never print the key or write
it into fixtures, snapshots, cassettes, reports, screenshots, or Git history.

The minimum supported Home Assistant version is 2025.12.0. Compatibility checks should
cover that minimum and the current stable version recorded in
[docs/TESTING.md](docs/TESTING.md), rather than assuming a successful import on one local
Python version proves both environments.

### Manual live smoke test

The GitHub Actions workflow `.github/workflows/live-smoke.yml` is manual-only. Configure
`OPENROUTER_API_KEY` as a secret in the protected `live-openrouter-test` GitHub
environment, then use **Actions → Manual OpenRouter smoke test → Run workflow**. Before
adding the secret, restrict that environment's deployment branches to `main`; where the
repository has another trusted maintainer, also require approval and prevent self-review.
The workflow itself refuses non-`main` refs and checks out `main`, but the GitHub
environment policy is the enforceable secret boundary and must not be omitted.

- Leave **Generate one short clip** disabled to validate only the key and catalog.
- Enabling it permits at most one `Test.` generation, and only with a model that the
  freshly fetched catalog classifies as free.
- If no verified-free TTS model exists, the script exits without a generation request.
- Paid and unknown-cost models are never fallback choices.
- Do not upload returned audio or raw workflow logs as release artifacts.

Delete or rotate temporary test credentials after the run. A live success proves only
the tested key/model/provider at that moment; it is not a price or availability guarantee.

## Design expectations

- Use Home Assistant's shared asynchronous HTTP session; never block the event loop.
- Keep API errors actionable but redact credentials, authorization headers, full response
  bodies, and private prompts.
- Treat speech generation as potentially billable. Do not add unconditional automatic
  retries. Catalog reads may use limited backoff and `Retry-After` handling.
- Keep model behavior capability-driven. Do not infer audio format solely from a model
  name or permanently hardcode one provider's current model ID.
- Validate model and voice together. A filter change must not silently replace a user's
  configured model.
- Keep free-model classification centralized, deterministic, Decimal-based, and covered
  by tests. Unknown or incomplete prices are not free.
- Confine generated files to the configured storage root and preserve the protections for
  traversal, symlink escape, race conditions, maximum size, and atomic replacement.
- Do not log full generation text or add hashes of short text as if they were anonymous.
- Add or update both English and Korean strings when changing user-visible behavior.

For this custom integration, `translations/en.json` and `translations/ko.json` are the
runtime locale files. The repository also retains `strings.json` because the initial
project requirements explicitly requested it, even though the current custom-integration
development guidance uses the files under `translations/`. Keep the English content in
sync across both locations.

Brand assets must remain original and must not reproduce Home Assistant branded images or
OpenRouter's official mark. See [docs/BRANDING.md](docs/BRANDING.md) for the asset source
and policy rationale.

## Tests

Add focused tests for new behavior and regressions. Depending on the change, relevant
coverage includes:

- Config Flow, reauthentication, and Options Flow.
- Model/voice parsing, cache expiry, last-known-good behavior, and pricing changes.
- Free, paid, and unknown classifications.
- MP3/WAV/raw-PCM validation and malformed or oversized responses.
- Timeout, authentication, rate-limit, provider, and server errors.
- Traversal, absolute paths, symlink escape, overwrite protection, deletion, and atomic
  file replacement.
- Secret redaction in exceptions and logs.
- Config-entry setup, unload, and reload plus service registration schemas.

Run the smallest relevant tests while developing and the full local checks before opening
a pull request. Record the exact result and any skipped environment in
[docs/TESTING.md](docs/TESTING.md). Validation performed by CI is authoritative for the
submitted commit; the presence of a workflow file alone is not evidence that it passed.

## Documentation and commits

- Update README examples, service descriptions, translations, and the Unreleased changelog
  when public behavior changes.
- Use generalized entity names and messages. Do not commit local Home Assistant addresses,
  entity IDs, generated audio, configuration storage, or automation traces.
- Keep commits focused and use clear imperative messages, for example
  `Add conservative free-model classification`.
- Do not mix unrelated formatting or dependency changes into a functional patch.

## Pull requests

Complete the pull-request template, explain the user-visible effect, state exactly what
you tested, and disclose anything not tested. Screenshots are welcome for UI changes only
after all personal data has been removed.

By submitting a contribution, you agree that it is licensed under the repository's
[MIT License](LICENSE).
