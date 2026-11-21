# Security Policy

## Supported Versions

Security fixes go into the latest `main` branch of **Graphical Studio**:

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |

## Security Architecture (Web Wrapper)

* **Login-Gated API & Media**: Every UI, API, upload, and media endpoint requires an HMAC-signed session cookie issued after single-use HMAC ticket verification ([web/sso.py](web/sso.py), [web/auth.py](web/auth.py)).
* **Host, Origin & CSRF Protection**: Requests are validated against a strict `GS_WEB_ALLOWED_HOSTS` allow-list, same-origin checks, and a required `X-GS-CSRF` header on mutating API calls ([web/server.py](web/server.py)).
* **Path Traversal Confinement**: All static and output media routes resolve paths strictly inside their allowed base directory via `Path.resolve()` containment checks.
* **Image Sanitization & Input Allow-Lists**: Uploaded images are decoded with Pillow (`MAX_IMAGE_PIXELS` bounded) and re-encoded as clean PNGs before reaching generators; model/sampler/scheduler choices and numeric bounds are validated in [web/specs.py](web/specs.py) and passed as `argv` lists without a shell.
* **Safety-minded defaults**: Ships dataset-scrubbed official models and safety-aligned local instruct LLMs.

## Reporting a Vulnerability

If you discover a potential security vulnerability, please report it privately via email to **todd.0042.git@gmail.com** or through [GitHub Private Vulnerability Reporting](https://github.com/Todd0042/graphical-studio-public/security/advisories/new) rather than filing a public issue. Security reports will receive an acknowledgment within 48 hours.
