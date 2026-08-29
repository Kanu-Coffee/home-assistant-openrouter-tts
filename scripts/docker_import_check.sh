#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 HOME_ASSISTANT_TAG" >&2
  exit 2
fi

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
home_assistant_tag="$1"
temporary_config="$(mktemp -d -t openrouter-tts-config.XXXXXXXXXX)"

cleanup() {
  if [[ -n "${temporary_config:-}" && -d "$temporary_config" ]]; then
    rmdir -- "$temporary_config"
  fi
}
trap cleanup EXIT

chmod 0755 "$temporary_config"
if [[ "$(id -u)" -eq 0 ]]; then
  chown 1000:1000 "$temporary_config"
fi

docker run --rm \
  --entrypoint python3 \
  --volume "${repository_root}:/workspace:ro" \
  --volume "${temporary_config}:/config-bind-test:rw" \
  --env OPENROUTER_TTS_BIND_CONFIG=/config-bind-test \
  --env PYTHONPATH=/workspace \
  "ghcr.io/home-assistant/home-assistant:${home_assistant_tag}" \
  /workspace/scripts/ha_runtime_check.py
