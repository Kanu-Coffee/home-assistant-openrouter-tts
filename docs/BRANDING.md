# Branding

The bundled icon is an original, AI-assisted illustration for this unofficial project.
It depicts a home, a speaker, routing nodes, and sound waves. It deliberately does not
copy or combine the Home Assistant, Nabu Casa, or OpenRouter logos. The
[Home Assistant Brands requirements](https://github.com/home-assistant/brands#image-specification)
prohibit Home Assistant-branded images for custom integrations because they can imply an
official integration. Reusing OpenRouter's official mark in a combined derivative could
also imply endorsement that this project does not have.

The source was generated with Codex's built-in image generation tool and then resized
locally to transparent 256 px and 512 px PNG assets. The final generation prompt was:

> Create an original visual mark for an unofficial OpenRouter-powered text-to-speech
> integration: a simple home outline containing a small speaker cone, with three
> flowing route nodes transforming into two clean sound waves. Use a crisp,
> vector-friendly geometric style in dark charcoal, warm coral-red, and soft
> off-white. Do not reproduce or imitate official logos, include text, or add a
> watermark.

The 256 px and 512 px files live in `custom_components/openrouter_tts/brand/`. Local
custom-integration brand directories are supported starting with Home Assistant 2026.3;
the minimum supported Home Assistant 2025.12 release can ignore these local assets and
show a fallback icon. This visual difference does not affect integration behavior. See
the official [brand-image documentation](https://developers.home-assistant.io/docs/core/integration/brand_images/).

The project distributes the resulting icon under the repository's MIT license. Do not
reuse the icon to imply affiliation with Home Assistant, Nabu Casa, OpenRouter, or any
model provider.
