# TIDAL-DL backend configuration

Music Manager does not authenticate to TIDAL directly and never simulates TIDAL results. TIDAL support is delegated to an operator-installed, authenticated Tidal-DL backend. The source remains disabled/unavailable until that backend passes a live health check.

## Operator setup

1. Install Tidal-DL on the host or in a companion container next to the Music Manager compose stack.
2. Authenticate with Tidal-DL using the tool's documented login flow: <https://github.com/yaronzz/Tidal-Media-Downloader>. Do not copy tokens into Music Manager source or `.env.example`.
3. Configure Tidal-DL output quality in its own config file. Choose the quality your subscription and rights allow.
4. Set Tidal-DL's output directory to a path mounted under Music Manager `STAGING_ROOT`, for example `/staging/music-manager/tidal`.
5. If the backend is exposed over HTTP, set `TIDAL_BACKEND_URL`. If it is wrapped as a CLI, set `TIDAL_BACKEND_PATH`. Set `TIDAL_STAGING_DIR` to the output directory.
6. Set `TIDAL_ENABLED=true` only after the backend is authenticated and reachable.

## Environment variables

- `TIDAL_ENABLED`: defaults to `false`; disabled sources are skipped.
- `TIDAL_BACKEND_URL`: URL for an operator-provided backend wrapper with live health/search/enqueue/status support.
- `TIDAL_BACKEND_PATH`: local command path for an operator-provided CLI wrapper.
- `TIDAL_STAGING_DIR`: backend output directory; must be contained by `STAGING_ROOT`.

## Troubleshooting

- `backend_not_configured`: TIDAL is disabled or no backend URL/path is configured.
- `health_check_failed`: backend did not answer a live health request.
- `auth_expired`: refresh authentication using Tidal-DL's own login/refresh flow.
- `invalid_staging_path`: backend output is not under `STAGING_ROOT`; fix the mounted output path.
