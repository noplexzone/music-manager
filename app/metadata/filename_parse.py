from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

_EXT_RE = re.compile(r"\.(?:flac|mp3|m4a|aac|ogg|opus|wav|alac|aiff?|wma)$", re.I)
_TRACK_PREFIX_RE = re.compile(r"^(?:cd\s*)?\d{1,2}(?:[-_. ]*\d{1,2})?\s*(?:[-_.:]|\s-\s)\s*", re.I)
_JUNK_TERMS = {
    "flac",
    "mp3",
    "320",
    "320kbps",
    "v0",
    "v2",
    "web",
    "webrip",
    "cd",
    "cdrip",
    "lossless",
    "24bit",
    "16bit",
    "44.1khz",
    "48khz",
    "96khz",
    "hi-res",
    "hifi",
}
_HINT_RE = re.compile(r"^(?:19|20)\d{2}$|remaster(?:ed)?|deluxe|anniversary|mono|stereo", re.I)
_BRACKET_RE = re.compile(r"\s*(\[[^\]]+\]|\([^)]*\)|\{[^}]+\})")
_SEP_RE = re.compile(r"\s*(?: - | – | — |\s+by\s+)\s*", re.I)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FilenameGuess:
    artist: str | None
    album: str | None
    title: str
    confidence: float
    hints: tuple[str, ...] = ()


def _tail(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    return PurePosixPath(normalized).name or PureWindowsPath(filename).name


def _clean_token(value: str) -> str:
    value = value.replace("_", " ").strip(" .-_\t")
    return _WS_RE.sub(" ", value).strip()


def _strip_brackets(value: str) -> tuple[str, list[str]]:
    hints: list[str] = []

    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)[1:-1].strip()
        normalized = raw.casefold().replace(" ", "")
        if normalized in _JUNK_TERMS or raw.casefold() in _JUNK_TERMS:
            return " "
        if _HINT_RE.search(raw):
            hints.append(raw)
        return " "

    return _BRACKET_RE.sub(repl, value), hints


def parse_filename(filename: str) -> FilenameGuess:
    name = _tail(filename)
    name = _EXT_RE.sub("", name)
    name, hints = _strip_brackets(name)
    name = _TRACK_PREFIX_RE.sub("", name)
    name = _clean_token(name)
    if not name:
        return FilenameGuess(None, None, _tail(filename), 0.0, tuple(hints))
    parts = [_clean_token(p) for p in _SEP_RE.split(name) if _clean_token(p)]
    artist: str | None = None
    album: str | None = None
    title = name
    confidence = 0.35
    if len(parts) >= 3:
        artist, album = parts[0], parts[1]
        title = " - ".join(parts[2:])
        confidence = 0.9
    elif len(parts) == 2:
        artist, title = parts
        confidence = 0.78
    else:
        title = parts[0]
    title = _TRACK_PREFIX_RE.sub("", title)
    title = _clean_token(title)
    if hints and confidence < 0.95:
        confidence += 0.03
    return FilenameGuess(
        artist or None, album or None, title or name, min(confidence, 0.98), tuple(hints)
    )


def compose_search_query(
    query: str = "", artist: str | None = None, album: str | None = None, track: str | None = None
) -> str:
    parts = [p.strip() for p in (artist, album, track, query) if p and p.strip()]
    return " ".join(dict.fromkeys(parts))
