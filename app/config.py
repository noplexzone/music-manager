from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False
    secret_key: str = Field(..., min_length=1)

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/music_manager.db"

    # Library naming
    naming_template: str = "{album_artist}/{year} - {album}/{disc_track} - {title}.{ext}"
    library_root: Path = Path("/music")

    # slskd
    slskd_url: str = ""
    slskd_api_key: str = ""

    # Prowlarr
    prowlarr_url: str = ""
    prowlarr_api_key: str = ""

    # SABnzbd
    sabnzbd_url: str = ""
    sabnzbd_api_key: str = ""

    # yt-dlp
    ytdlp_cookies_file: str = ""

    # MusicBrainz
    musicbrainz_app_name: str = "music-manager"
    musicbrainz_app_version: str = "0.1.0"
    musicbrainz_contact: str = ""

    # Deezer
    deezer_api_url: str = "https://api.deezer.com"

    # AcoustID
    acoustid_api_key: str = ""

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @property
    def musicbrainz_user_agent(self) -> str:
        contact = self.musicbrainz_contact or "unknown"
        return f"{self.musicbrainz_app_name}/{self.musicbrainz_app_version} ({contact})"

    @property
    def slskd_configured(self) -> bool:
        return bool(self.slskd_url and self.slskd_api_key)

    @property
    def prowlarr_configured(self) -> bool:
        return bool(self.prowlarr_url and self.prowlarr_api_key)

    @property
    def sabnzbd_configured(self) -> bool:
        return bool(self.sabnzbd_url and self.sabnzbd_api_key)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def override_settings(s: Settings) -> None:
    global _settings
    _settings = s


# Alias used as FastAPI dependency
settings_dep = Field(default_factory=get_settings)
