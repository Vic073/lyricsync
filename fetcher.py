"""
fetcher.py — Query lrclib.net for synced/plain lyrics.
Handles retries, back-off, rate limiting.
"""

import time
import requests

LRCLIB_URL = "https://lrclib.net/api/get"
HEADERS = {"User-Agent": "LyricSyncPro/1.0 (https://github.com/lyricsync)"}


def fetch_lyrics(artist: str, title: str, album: str = "", duration: int = 0,
                 max_retries: int = 3) -> dict | None:
    """
    Query lrclib.net for lyrics.
    Returns dict with 'syncedLyrics' and/or 'plainLyrics', or None if not found.
    Raises on unrecoverable errors.
    """
    if not artist and not title:
        return None

    params = {}
    if artist:
        params["artist_name"] = artist
    if title:
        params["track_name"] = title
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = duration

    backoff = 1
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(LRCLIB_URL, params=params, headers=HEADERS, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                synced = data.get("syncedLyrics") or ""
                plain  = data.get("plainLyrics")  or ""
                if not synced and not plain:
                    return None
                return {"syncedLyrics": synced, "plainLyrics": plain}

            elif resp.status_code == 404:
                return None  # No match — not an error

            elif resp.status_code == 429 or resp.status_code >= 500:
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                else:
                    raise Exception(f"HTTP {resp.status_code} after {max_retries} retries")

            else:
                return None  # Other client error — treat as not found

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                time.sleep(backoff)
                backoff *= 2
            else:
                raise Exception("Request timed out after retries")

        except requests.exceptions.ConnectionError:
            if attempt < max_retries:
                time.sleep(backoff)
                backoff *= 2
            else:
                raise Exception("Connection error — check internet connection")

    return None
