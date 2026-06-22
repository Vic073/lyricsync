"""
scanner.py — Recursively scan a folder for MP3 files and classify each by lyrics state.
States: EMPTY, UNSYNCED, SYNCED
"""

import os
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, ID3NoHeaderError


def get_lyrics_state(path: str) -> str:
    """Return SYNCED, UNSYNCED, or EMPTY based on ID3 tag content."""
    try:
        tags = ID3(path)
        # SYLT = Synchronised Lyrics
        if any(k.startswith("SYLT") for k in tags.keys()):
            return "SYNCED"
        # USLT = Unsynchronised Lyrics
        if any(k.startswith("USLT") for k in tags.keys()):
            return "UNSYNCED"
        return "EMPTY"
    except ID3NoHeaderError:
        return "EMPTY"
    except Exception:
        return "EMPTY"


def scan_library(root_folder: str) -> list:
    """
    Walk root_folder recursively, find all .mp3 files, read ID3 metadata,
    and return a list of file info dicts.
    """
    results = []
    root = Path(root_folder)

    for mp3_path in sorted(root.rglob("*.mp3")):
        info = {
            "path": str(mp3_path),
            "filename": mp3_path.name,
            "artist": "",
            "title": "",
            "album": "",
            "duration_s": 0,
            "state": "EMPTY",
            "outcome": None,
            "source": "",
        }

        try:
            audio = MP3(str(mp3_path))
            info["duration_s"] = int(audio.info.length)

            try:
                tags = ID3(str(mp3_path))

                def get_tag(key):
                    frame = tags.get(key)
                    if frame is None:
                        return ""
                    val = str(frame)
                    return val.strip() if val else ""

                info["artist"] = get_tag("TPE1")
                info["title"]  = get_tag("TIT2")
                info["album"]  = get_tag("TALB")

                # Classify
                if any(k.startswith("SYLT") for k in tags.keys()):
                    info["state"] = "SYNCED"
                elif any(k.startswith("USLT") for k in tags.keys()):
                    info["state"] = "UNSYNCED"
                else:
                    info["state"] = "EMPTY"

            except ID3NoHeaderError:
                info["state"] = "EMPTY"

        except Exception as e:
            info["state"] = "EMPTY"
            info["title"] = mp3_path.stem  # fallback: use filename stem

        # Fallback: use filename stem if no title tag
        if not info["title"]:
            info["title"] = mp3_path.stem

        results.append(info)

    return results
