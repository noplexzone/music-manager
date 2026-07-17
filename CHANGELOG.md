# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Import Review Plan and Import forms now use dedicated POST-redirect-GET handlers, returning the browser to the refreshed review page instead of navigating to POST-only API URLs.
- Packaged Jinja templates and static CSS in built distributions for clean wheel installs.
- Edition matching now sends contradictory release attributes to review and prevents manual selection of another track's candidate.
- Import execution now rejects post-plan symlink source swaps and only marks supported formats tag-verified after Mutagen readback.
- Import filesystem changes now follow the surrounding database transaction: failed commits restore staged sources and prior library bytes, while descriptor-pinned destination directories reject ancestor swaps before atomic rename.
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

[Unreleased]: https://github.com/noplexzone/music-manager/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/noplexzone/music-manager/releases/tag/v0.1.0
