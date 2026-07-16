# Music Manager

**Private, self-hosted music acquisition and library management — v0.1.0**

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

Path previews are computed and stored; **no library files are moved in v0.1.0**.

## Stack

- **Backend** — Python 3.12, FastAPI, SQLAlchemy 2.x (async), SQLite
- **Templates** — Jinja2 (server-side HTML for admin UI)
- **Task Queue** — persistent job records in SQLite (no external broker in v0.1.0)
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

## Version

v0.1.0 — Foundation (path preview only, no file moves)
