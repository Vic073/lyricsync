"""
embedder.py — Embed lyrics into MP3 ID3 tags using mutagen.
Handles SYLT (synced) and USLT (unsynced) frames.
Atomic write: write to temp file first, then replace original.

Synced lyrics strategy (for mobile compatibility):
  1. USLT  — raw LRC text WITH timestamps (most mobile players parse these)
  2. SYLT  — structured binary sync data (for desktop players like foobar2000)
  3. .lrc  — external sidecar file (universal gold standard for mobile)
"""

import os
import re
import shutil
import tempfile
from pathlib import Path

from mutagen.id3 import (
    ID3, ID3NoHeaderError, SYLT, USLT,
    Encoding, ID3TimeStamp
)
from mutagen.mp3 import MP3


def parse_lrc(lrc_text: str) -> list[tuple[int, str]]:
    """
    Parse LRC format into list of (milliseconds, line_text) tuples.
    Handles [mm:ss.xx] and [mm:ss:xx] and [mm:ss] formats.
    """
    pattern = re.compile(r'\[(\d{1,2}):(\d{2})[\.:,]?(\d{0,3})\](.*)')
    result = []
    for line in lrc_text.splitlines():
        m = pattern.match(line.strip())
        if m:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            ms_str = m.group(3).ljust(3, "0")[:3]
            millis = int(ms_str)
            text = m.group(4).strip()
            total_ms = (minutes * 60 + seconds) * 1000 + millis
            result.append((total_ms, text))
    return result


def write_lrc_file(mp3_path: str, lrc_text: str):
    """
    Write an external .lrc sidecar file next to the MP3.
    e.g. /music/Song.mp3 → /music/Song.lrc
    The .lrc file uses the exact LRC text from the API.
    """
    mp3 = Path(mp3_path)
    lrc_path = mp3.with_suffix(".lrc")
    try:
        lrc_path.write_text(lrc_text, encoding="utf-8")
    except Exception:
        raise


def embed_lyrics(path: str, synced_lrc: str = None, plain_text: str = None,
                 generate_lrc: bool = True):
    """
    Embed lyrics into an MP3 file.
    - synced_lrc: LRC-format string → writes SYLT + USLT (with timestamps) + .lrc file
    - plain_text: plain lyrics string → writes USLT frame only
    Atomic: writes to a temp file then replaces the original.
    Preserves all other ID3 tags.

    Mobile compatibility strategy:
      When synced_lrc is provided:
        1. USLT gets the RAW LRC text (with [mm:ss.xx] timestamps intact).
           Mobile players like OTO, Musicolet, Poweramp parse these timestamps
           from USLT and display synced/karaoke lyrics.
        2. SYLT gets the structured binary sync data for desktop players
           (foobar2000, MusicBee, etc.) that support the SYLT frame.
        3. An external .lrc sidecar file is written (if generate_lrc=True).
           This is the universal gold standard — virtually every mobile player
           supports reading .lrc files.
    """
    if not synced_lrc and not plain_text:
        raise ValueError("No lyrics provided")

    path = Path(path)

    # Load existing tags
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()

    if synced_lrc:
        # Remove any existing SYLT and USLT frames
        for key in list(tags.keys()):
            if key.startswith("SYLT") or key.startswith("USLT"):
                del tags[key]

        parsed = parse_lrc(synced_lrc)
        if not parsed:
            # Malformed LRC — fall back to plain embed
            if plain_text:
                _embed_uslt(tags, plain_text)
        else:
            # ── SYLT frame (for desktop players) ──
            # SYLT expects list of (text_str, timestamp_int) tuples
            sylt_data = [(line, ms) for ms, line in parsed]
            tags.add(SYLT(
                encoding=Encoding.UTF8,
                lang="eng",
                format=2,       # milliseconds
                type=1,         # lyrics
                text=sylt_data
            ))

            # ── USLT frame (for mobile players) ──
            # Embed the RAW LRC text WITH timestamps so mobile players
            # (OTO, Musicolet, Poweramp, etc.) can parse and sync them.
            _embed_uslt(tags, synced_lrc)

            # ── External .lrc sidecar file ──
            if generate_lrc:
                write_lrc_file(str(path), synced_lrc)

    elif plain_text:
        # Remove existing USLT only; leave SYLT alone
        for key in list(tags.keys()):
            if key.startswith("USLT"):
                del tags[key]
        _embed_uslt(tags, plain_text)

    # Atomic write: save to temp file in same directory, then replace
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.close(tmp_fd)
        shutil.copy2(str(path), tmp_path)

        # Write tags to temp copy
        tmp_tags = ID3(tmp_path)
        # Clear lyrics frames on temp copy and re-add our new ones
        for key in list(tmp_tags.keys()):
            if key.startswith("SYLT") or key.startswith("USLT"):
                del tmp_tags[key]
        for frame in tags.values():
            if frame.FrameID in ("SYLT", "USLT"):
                tmp_tags.add(frame)
        tmp_tags.save(tmp_path, v2_version=3)

        # Replace original
        shutil.move(tmp_path, str(path))

    except Exception:
        # Clean up temp file on error, leave original intact
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _embed_uslt(tags, text: str):
    tags.add(USLT(
        encoding=Encoding.UTF8,
        lang="eng",
        desc="",
        text=text
    ))


def get_lyrics_state(path: str) -> str:
    """Return SYNCED, UNSYNCED, or EMPTY."""
    try:
        tags = ID3(str(path))
        if any(k.startswith("SYLT") for k in tags.keys()):
            return "SYNCED"
        if any(k.startswith("USLT") for k in tags.keys()):
            # Check if USLT contains LRC timestamps — if so, it's synced
            for key, frame in tags.items():
                if key.startswith("USLT"):
                    text = getattr(frame, 'text', '')
                    if re.search(r'\[\d{1,2}:\d{2}', text):
                        return "SYNCED"
            return "UNSYNCED"
        return "EMPTY"
    except ID3NoHeaderError:
        return "EMPTY"
    except Exception:
        return "EMPTY"
