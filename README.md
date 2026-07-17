# Music Manager

**Private, self-hosted music acquisition and library management — v0.1.1**

A FastAPI application that coordinates multiple acquisition sources, enriches tracks with metadata, fingerprints audio, and enforces strict library naming conventions. Designed to run entirely on-premises; no data leaves the host.

## Acquisition Sources

| Source | Protocol | Notes |
|---|---|---|
| slskd | Soulseek P2P | Primary peer-to-peer source |
| Prowlarr + SABnzbd | Usenet NZB | Indexer-managed newsgroup downloads |
| YouTube | HTTP stream | yt-dlp extraction |
| TIDAL | — | **Unavailable** — requires a supported, authenticated downloader; never simulated |

## Metadata & Fingerprinting

- **MusicBrainz** — canonical track/release identity (MBIDs)
- **Deezer** — supplementary metadata (BPM, gain, preview)
- **AcoustID** — acoustic fingerprinting via `fpcalc` (optional; degrades gracefully when binary absent)
- **AcoustID Lookup** — matches fingerprint against the AcoustID database when a key is configured

## Naming Convention

Files are renamed according to a strict, configurable template:

```
<AlbumArtist>/<Year> - <Album>/<DiscTrack> - <Title>.<ext>
```

Path previews and safe staging/import workflow state are computed and stored. Actual library mutation remains isolated behind future verified import execution; staging paths live under `STAGING_ROOT` and must not escape it.

Extension tokens are sanitized with the same filesystem safety rules as other naming tokens, then capped at 32 characters. The final filename component is capped at 200 characters while preserving a dot plus the bounded sanitized extension.

## Stack

- **Backend** — Python 3.12, FastAPI, SQLAlchemy 2.x (async), SQLite
- **Templates** — Jinja2 (server-side HTML for admin UI)
- **Task Queue** — persistent job and acquisition/import workflow records in SQLite (no external broker in v0.1.1)
- **Containerisation** — Docker + Docker Compose

## Requirements

- Docker + Docker Compose v2
- `fpcalc` binary (Chromaprint) available in container for fingerprinting
- slskd instance reachable on the local network
- Prowlarr + SABnzbd instances reachable on the local network
- Valid API keys for AcoustID (optional) and Deezer

## Quick Start

```bash
cp .env.example .env
# fill in .env values
docker compose up -d
```

The admin UI is served at `http://localhost:8000`.

For this direct LAN HTTP setup, keep `AUTH_COOKIE_SECURE=false` as shown in
`.env.example`; otherwise browsers will not return the session and CSRF cookies over
HTTP. Set `AUTH_COOKIE_SECURE=true` whenever Music Manager is served behind HTTPS.
`SESSION_TTL_SECONDS` controls session lifetime and defaults to 43,200 seconds
(12 hours).

## Container image

The release workflow publishes tagged builds to `noplexzone/music-manager` on Docker Hub after the quality gate passes. Until a tagged workflow has completed, build the image locally with:

```bash
docker build -f docker/Dockerfile -t music-manager:0.1.1 .
```

## Continuous integration

Pull requests and pushes to `main` run pytest, Ruff lint and formatting checks, mypy, Python package build, and a Docker image build. Version tags run the same quality gate before publishing the Docker image.

## Version

v0.1.1 — Library automation foundation (staging and workflow state, no verified import execution yet)
