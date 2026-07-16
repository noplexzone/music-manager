# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
