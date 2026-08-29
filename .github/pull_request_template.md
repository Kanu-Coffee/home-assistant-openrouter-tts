## Summary

Describe the user-visible outcome and why the change is needed.

## Related issue

Closes #

## Changes

<!-- Add a short bullet for each material change. -->

## Verification

List the exact commands and environments used. Include mock, Docker, Home Assistant, and
opt-in live-provider coverage only when actually performed.

```text
# command and result
```

Not tested:

<!-- List verification gaps explicitly; write "None" only if the full relevant matrix ran. -->

## Security, privacy, and cost review

- [ ] No API key, authorization header, private prompt, personal audio, private URL,
      Home Assistant backup, `.storage` content, or local configuration was committed.
- [ ] Errors and logs avoid credentials, full response bodies, and complete generation text.
- [ ] Billable generation is not retried unconditionally and `Retry-After` behavior remains
      conservative.
- [ ] Model/voice capability and free-price behavior remains metadata-driven and treats
      incomplete pricing as unknown.
- [ ] File changes preserve root confinement, symlink/traversal protection, size limits,
      overwrite safety, and atomic writes where applicable.
- [ ] `/config/www` exposure and external OpenRouter/provider text transfer remain clear to
      users when applicable.

## Quality checklist

- [ ] Tests cover the change or the reason they cannot is explained above.
- [ ] Ruff formatting/linting, type checks, and pytest pass locally or failures are disclosed.
- [ ] Home Assistant/HACS validation relevant to this change passes or gaps are disclosed.
- [ ] Config entry setup, reload, and unload behavior was considered.
- [ ] User-visible strings were added to both English and Korean translations.
- [ ] README, service documentation, and CHANGELOG were updated for public behavior.
- [ ] Examples use generalized entity IDs, filenames, URLs, and messages.

## Screenshots or recordings

Optional for UI changes. Redact all personal information before attaching media.
