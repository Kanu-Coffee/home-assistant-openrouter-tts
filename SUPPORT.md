# Support

Use [GitHub Issues](https://github.com/Kanu-Coffee/home-assistant-openrouter-tts/issues)
for reproducible integration bugs and focused feature requests. General Home Assistant,
HACS, network, Chromecast, OpenRouter account, billing, and provider questions may be
better answered by those projects' support channels.

Before opening an issue:

1. Update to the latest appropriate release and restart Home Assistant.
2. Refresh the OpenRouter model catalog.
3. Confirm the selected model and voice are still available and that the account has
   access and balance.
4. Reproduce the issue once with a short, non-sensitive message.
5. Check the existing issues and the troubleshooting section in [README.md](README.md).

Include:

- Home Assistant version and installation type.
- OpenRouter TTS version and HACS/manual installation method.
- Model ID and requested output format; omit the generated text if it is private.
- Whether the problem affects `tts.speak`, `generate_file`, catalog refresh, or cleanup.
- Exact steps, expected behavior, and actual behavior.
- A minimal redacted log excerpt and whether the issue survives reload/restart.

Never include an API key or bearer header. Also redact config-entry IDs, account IDs,
private hostnames/IP addresses, filesystem paths containing personal information, complete
prompts, generated personal audio, Home Assistant backups, `.storage` data, and automation
traces. If unsure, describe the symptom without attaching diagnostics and ask what subset
is needed.

Security vulnerabilities belong in a private report as described in
[SECURITY.md](SECURITY.md), not in a support issue.
