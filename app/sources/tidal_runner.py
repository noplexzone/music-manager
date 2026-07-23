from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--quality", required=True)
    args = parser.parse_args()

    import tidal_dl

    errors: list[str] = []
    original_error = tidal_dl.Printf.err

    def capture_error(message: object) -> None:
        errors.append(str(message))
        original_error(message)

    tidal_dl.Printf.err = capture_error
    tidal_dl.SETTINGS.read(tidal_dl.getProfilePath())
    tidal_dl.TOKEN.read(tidal_dl.getTokenPath())
    tidal_dl.TIDAL_API.apiKey = tidal_dl.apiKey.getItem(tidal_dl.SETTINGS.apiKeyIndex)

    # Never enter tidal-dl's interactive device-login fallback in a web worker.
    if not tidal_dl.loginByConfig():
        print("audiohoard: TIDAL authentication is required", file=sys.stderr)
        return 41

    tidal_dl.SETTINGS.downloadPath = args.output
    tidal_dl.SETTINGS.audioQuality = tidal_dl.SETTINGS.getAudioQuality(args.quality)
    tidal_dl.SETTINGS.albumFolderFormat = "{AlbumID}"
    tidal_dl.SETTINGS.playlistFolderFormat = "{PlaylistUUID}"
    tidal_dl.SETTINGS.trackFileFormat = "{TrackID}"
    tidal_dl.SETTINGS.videoFileFormat = "{VideoID}"
    tidal_dl.SETTINGS.usePlaylistFolder = False
    tidal_dl.SETTINGS.saveCovers = False
    tidal_dl.SETTINGS.saveAlbumInfo = False
    tidal_dl.SETTINGS.lyricFile = False
    tidal_dl.SETTINGS.showProgress = False
    tidal_dl.start(args.url)
    if errors:
        print("audiohoard: tidal-dl download failed", file=sys.stderr)
        return 42
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
