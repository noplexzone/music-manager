# Music Manager — Project Constraints for Claude

## What this project is

A private, self-hosted FastAPI application that coordinates music acquisition from multiple sources, enriches tracks with metadata, fingerprints audio, and enforces strict library naming conventions.

## Hard constraints

### Sources
- **slskd**, **Prowlarr+SABnzbd**, and **YouTube** are the only acquisition sources in scope for v0.1.0.
- **TIDAL support is delegated to an operator-installed, authenticated Tidal-DL backend.** Music Manager must never stub, mock, simulate, or synthesize TIDAL results; the TIDAL source reports `unavailable` with a clear reason until the backend is configured and passes a live health check. The operator is responsible for the rights/subscription required by their downloader.
- New sources must implement the `SourceAdapter` protocol and declare their capability state; capability states are surfaced to the UI without hiding failures.

### Metadata
- **MusicBrainz** is the canonical identity provider (MBIDs). All library records must carry a MBID or be marked unresolved.
- **Deezer** provides supplementary metadata (BPM, gain, preview URL). It does not replace MusicBrainz.
- External API calls must be rate-limited and retried with exponential backoff.

### Fingerprinting
- Local fingerprinting uses `fpcalc` (Chromaprint). If the binary is absent the fingerprint step is skipped with a warning; it must never block acquisition.
- AcoustID cloud lookup is optional and requires `ACOUSTID_API_KEY` to be set.

### Naming & file operations
- The universal naming convention template is exactly `{album_artist}/{year} - {album}/{disc_track} - {title}.{ext}`. One-disc releases use `TT`; multi-disc releases use `D-TT`. Track numbers are two digits.
- In v0.1.0, **compute and persist path previews only — never move, copy, rename, or delete library files**.
- Any code that performs filesystem writes to the library root is out of scope for v0.1.0 and must not be written.

### Data layer
- SQLAlchemy 2.x async with SQLite via `aiosqlite`.
- All schema changes go through Alembic migrations; never use `create_all()` in production paths.
- Job records persist in SQLite. No external broker (Redis, RabbitMQ, Celery) in v0.1.0.

### Contracts
- Health endpoints must perform real dependency checks (slskd reachable, DB writable). No fake `{"status": "ok"}`.
- Search endpoints must proxy to real source APIs. No canned or hardcoded results.

### Testing
- Follow TDD: write the test before the implementation.
- Unit tests mock external HTTP; integration tests hit real (or docker-compose) services.
- No production code path should be reachable only through mocks.

### Security
- No secrets in source control. All secrets via environment variables loaded from `.env` (never `.env.example`).
- Validate and sanitise all user-supplied naming tokens before constructing file paths. Prevent path traversal.
- SQL queries through SQLAlchemy ORM only; no raw string interpolation into queries.

### Docker
- The application and all dependencies run under Docker Compose.
- The `fpcalc` binary must be installed in the application image.
- Mount `LIBRARY_ROOT` as a read-only volume in v0.1.0.

## Style
- Python 3.12. Use `from __future__ import annotations` for forward refs.
- Prefer `async`/`await` throughout; avoid synchronous I/O on the event loop.
- Type-annotate all public functions and methods.
- Ruff for linting and formatting; mypy in strict mode.
- No commented-out code. No TODOs committed to main.

## Out of scope for v0.1.0
- File moves or library reorganisation
- In-process TIDAL credential handling or simulated TIDAL acquisition
- External task broker
- Front-end JavaScript framework (Jinja2 templates only)
- Multi-user authentication
