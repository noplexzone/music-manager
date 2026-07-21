# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-07-20

### Fixed

- Restored native server-rendered form submission by removing the global fetch interceptor, adding CSRF fields to mutating forms, adding form-based login, and redirecting POST-only UI GET paths to safe pages.

## [0.2.0] - 2026-07-20

### Added

- Added filename metadata parsing, fielded artist/album/track search, escaped MusicBrainz Lucene queries, source-priority settings, selected-result download creation, slskd transfer enqueue/status/cancel support, and TIDAL-DL operator documentation.
- Added a data-backed dashboard with bounded library totals, recent tracks and jobs, job-state counts, provider readiness, and truthful empty states.
- Added a responsive application shell with desktop and mobile navigation, accessible active states, reusable cards, forms, badges, empty states, and consistent styling across the dashboard, search, library, artists, jobs, imports, settings, setup, login, and track views.
- Added read-only Library page (`/library`) with aggregate stats (track count, artists, albums, total duration, total size, format and source breakdowns), text/artist/album/source/format filtering, deterministic sorting, and bounded pagination backed by real Track data.
- Added Artists page (`/artists`) grouping tracks by `album_artist` (falling back to `artist`), with track/album/duration aggregates, per-artist format badges, search, sort, and pagination. Artist-detail view (`/artists/detail?name=…`) shows tracks grouped by album with release metadata (MBID, label, country, catalog number) and paginated track listing.
- Tracks with no artist information appear as "Unknown" throughout library stats, listing, and artist detail; `/artists/detail?name=Unknown` works correctly.
- Added `file_format` and `file_size_bytes` columns to `Track` (migration 0007) and populate them after YouTube/TIDAL acquisition and atomic import. Library stats use SQL-aggregated totals from these persisted columns; no per-page filesystem reads.
- Added bounded startup reconciliation for legacy track format/size metadata; it reads only regular non-symlink files beneath configured library or staging roots.
- Updated global navigation to include Library and Artists links.
- Added encrypted database-backed provider and library settings with environment precedence, masked secret responses, separate connection tests, and authenticated save APIs.
- Extended first-run setup to configure acquisition, metadata, TIDAL, and library sources without requiring them to be present.
- Added an operator Settings page with explicit provider health checks and persistent source configuration.
- Added bounded tidal-dl acquisition for direct HTTPS TIDAL track URLs, with local profile readiness checks, verified audio artifacts, and persisted provenance.

### Changed

- Rebranded acquisition Jobs UI to Downloads while keeping the `/jobs` API stable.
- Free-text downloads now cap provider results to 10 by default and preserve partial success errors without marking successful batches as wholly failed.

### Fixed

- Fixed slskd search metadata population, Prowlarr music-category scoping, slskd missing-search-id handling, selected Enqueue behavior, unsafe search-template escaping, and low-confidence MusicBrainz enrichment churn.
- Library format breakdown and total size now use SQL `GROUP BY` on the persisted `file_format` and `SUM` of `file_size_bytes` columns instead of unbounded Python source-path iteration.
- Artist detail uses `selectinload` on the Release relationship to avoid N+1 queries; album groups are keyed by `release_id` for stable identity across releases sharing an album name.
- Artist format counts use a single bounded `GROUP BY` query scoped to the current page's artists only, compatible with SQLite and PostgreSQL.
- Page parameters on all catalog routes validated with `le=10_000` (422 for out-of-range values); pages beyond the last are clamped to the last valid page rather than returning empty results.
- Artist detail track list uses the persisted `track_no` field for track numbering instead of loop index.

### Security

- Provider secrets are encrypted at rest and never returned to clients; settings mutations require owner/admin authorization and CSRF validation.
- TIDAL subprocesses run without a shell or interactive input, use bounded output and timeouts, and reject unsafe profile, URL, and staging layouts.

## [0.1.2] - 2026-07-17

### Fixed

- Alembic now honors the configured `DATABASE_URL`, ensuring container migrations and the application use the same persistent SQLite database.

## [0.1.1] - 2026-07-17

### Added

- First-run owner setup, Argon2 password hashing, expiring database sessions, CSRF protection, role-based mutation authorization, and login throttling.
- Added release, candidate, import-plan, monitoring, acquisition, and import workflow state foundations for v0.1.1 safe staging.
- Added staging-root configuration and containment validation for future import execution.
- Added evidence-scored edition matching with auditable review states for unattended or manual candidate selection.
- Added duplicate/collision-aware import planning plus verified destination-temp atomic imports with Mutagen tag readback and rollback.
- Added import review API and Jinja review page surfaces for planned operations, collisions, tag verification, and rollback status.
- Added persisted quality profiles and monitoring history, non-overlapping cancellable checks, meaningful quality ranking, and verified rollback-safe upgrades.

### Fixed

- First-run owner setup now uses a database-enforced single-owner claim and returns a deterministic conflict when concurrent setup requests race.
- Background job scheduling now opens its own database session instead of reusing the request-scoped session.
- Configured pytest-asyncio fixture and test loop scopes explicitly.
- Import Review Plan and Import forms now use CSRF-protected POST-redirect-GET handlers with a non-JavaScript form fallback, returning the browser to the refreshed review page instead of navigating to POST-only API URLs.
- Packaged Jinja templates and static CSS in built distributions for clean wheel installs.
- Edition matching now sends contradictory release attributes to review and prevents manual selection of another track's candidate.
- Import execution now rejects post-plan symlink source swaps and only marks supported formats tag-verified after Mutagen readback.
- Import filesystem changes now follow the surrounding database transaction: failed commits restore staged sources and prior library bytes, rollback callbacks isolate cleanup failures, backup names are claimed atomically, and descriptor-pinned destination directories reject ancestor swaps before atomic rename.
- Import execution now rejects post-plan symlink swaps in every staged source path component.
- Monitoring upgrades now require the approved selected release candidate, verify candidate-bound track artifacts and hashes, and isolate post-commit backup cleanup from rollback.
- YouTube search now uses a bounded, cancellable yt-dlp subprocess with sanitized structured failures and truthful cookie/version health details; TIDAL reports exact lawful backend prerequisites while remaining unavailable.

## [0.1.0] - 2026-07-16

### Added

- Initial project definition and repository baseline
- Architecture decision: FastAPI + SQLAlchemy 2.x (async) + SQLite + Jinja2
- Acquisition source registry: slskd (Soulseek), Prowlarr+SABnzbd (Usenet), YouTube (yt-dlp)
- TIDAL marked permanently unavailable until a supported authenticated downloader exists; simulation prohibited
- Metadata providers: MusicBrainz (canonical identity/MBIDs), Deezer (supplementary BPM/gain/preview)
- Fingerprinting: fpcalc/Chromaprint integration with optional AcoustID lookup; degrades gracefully when binary absent
- Strict library naming convention template with path-preview computation (no file moves in v0.1.0)
- Persistent job model in SQLite (no external task broker in v0.1.0)
- Docker + Docker Compose containerisation plan
- Health check and search contracts defined (real implementations only, no mocks in production paths)
- Source capability state model: each source reports its own availability
- TDD task breakdown documented in docs/plans/2026-07-16-v0.1.0-foundation.md
- .env.example with all required and optional provider secrets and URLs
- LICENSE-NOTICE.md: private repository, no redistribution
- GitHub Actions CI workflow: quality checks (pytest, ruff, mypy, package build) and Docker image build on every PR and push to main
- GitHub Actions release workflow: quality gate then Docker Hub push to `noplexzone/music-manager` on `v*` tags

### Fixed

- Hardened job source validation, Prowlarr NZB URL trust checks, YouTube search timeout behavior, Docker build context exclusions, and filename extension preservation

[Unreleased]: https://github.com/noplexzone/music-manager/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/noplexzone/music-manager/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/noplexzone/music-manager/compare/v0.1.3...v0.2.0
[0.1.2]: https://github.com/noplexzone/music-manager/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/noplexzone/music-manager/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/noplexzone/music-manager/releases/tag/v0.1.0
