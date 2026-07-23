from __future__ import annotations

_DISPLAY_NAMES: dict[str, str] = {
    "slskd": "Soulseek (slskd)",
    "prowlarr": "Prowlarr",
    "sabnzbd": "SABnzbd",
    "youtube": "YouTube (yt-dlp)",
    "tidal": "TIDAL",
    "musicbrainz": "MusicBrainz",
    "deezer": "Deezer",
    "itunes": "iTunes / Apple Music",
}


def display_name(key: str) -> str:
    return _DISPLAY_NAMES.get(key, key)
