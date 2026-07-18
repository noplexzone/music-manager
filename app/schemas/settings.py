from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SettingField(BaseModel):
    value: str
    configured: bool
    locked_by_environment: bool


class SettingsSaveRequest(BaseModel):
    slskd_url: str | None = None
    slskd_api_key: str | None = None
    prowlarr_url: str | None = None
    prowlarr_api_key: str | None = None
    sabnzbd_url: str | None = None
    sabnzbd_api_key: str | None = None
    ytdlp_cookies_file: str | None = None
    tidal_config_path: str | None = None
    tidal_session_path: str | None = None
    tidal_quality: Literal["", "Normal", "High", "HiFi", "Master"] | None = None
    musicbrainz_contact: str | None = None
    acoustid_api_key: str | None = None
    library_root: str | None = None
    staging_root: str | None = None
    naming_template: str | None = None


_TESTABLE_PROVIDERS = Literal["slskd", "prowlarr", "sabnzbd", "youtube", "tidal"]


class SettingsTestRequest(BaseModel):
    provider: _TESTABLE_PROVIDERS
    slskd_url: str = ""
    slskd_api_key: str = ""
    prowlarr_url: str = ""
    prowlarr_api_key: str = ""
    sabnzbd_url: str = ""
    sabnzbd_api_key: str = ""
    ytdlp_cookies_file: str = ""
    tidal_config_path: str = ""
    tidal_session_path: str = ""
    tidal_quality: Literal["", "Normal", "High", "HiFi", "Master"] = ""
