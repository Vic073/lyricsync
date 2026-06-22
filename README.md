# LyricSync Pro

Bulk synced lyrics embedder for MP3 files. Searches lrclib.net and permanently embeds lyrics into ID3 tags.

## Quick Start (Windows)

1. Make sure **Python 3.10+** is installed — https://python.org
2. Double-click **`launch.bat`**
3. Your browser opens at `http://127.0.0.1:5000`
4. Paste your music folder path → Scan → Start Processing

## What it does

- Scans your MP3 folder recursively
- **Skips** files that already have synced (SYLT) lyrics
- **Processes** files with no lyrics or only unsynced (USLT) lyrics
- Queries [lrclib.net](https://lrclib.net) for synced LRC lyrics
- Embeds synced lyrics into the `SYLT` ID3 frame (karaoke-style)
- Falls back to plain `USLT` if only plain lyrics are available
- Never touches any other metadata

## Lyrics States

| State | Meaning |
|-------|---------|
| `EMPTY` | No lyrics at all — will be processed |
| `UNSYNCED` | Has plain USLT lyrics but no timestamps — will be processed |
| `SYNCED` | Already has SYLT synced lyrics — **skipped** |

## Outcomes

| Outcome | Meaning |
|---------|---------|
| `SYNCED_EMBEDDED` | ✓ Synced LRC lyrics written to SYLT tag |
| `UNSYNCED_EMBEDDED` | ✓ Plain lyrics written to USLT tag (fallback) |
| `NOT_FOUND` | lrclib.net had no match for this song |
| `FAILED` | Error during fetch or write (file unchanged) |
| `SKIPPED` | Already had synced lyrics |

## Project Structure

```
lyricsync/
├── app.py          # Flask backend + API endpoints
├── scanner.py      # MP3 folder scanner + lyrics state classifier
├── fetcher.py      # lrclib.net API client with retry/back-off
├── embedder.py     # ID3 tag writer (SYLT/USLT) with atomic write
├── requirements.txt
├── launch.bat      # Windows launcher
├── templates/
│   └── index.html  # Main UI template
└── static/
    ├── css/style.css
    └── js/app.js
```

## Settings

- **API Delay**: ms between requests (default 350ms). Lower = faster but risks rate limiting.
- **Unsynced Fallback**: Embed plain lyrics when no synced version exists (default: ON).

## Notes

- Writes to `SYLT` (Synchronised Lyrics) + `USLT` (plain fallback) for synced songs
- Uses atomic write — if anything goes wrong during write, the original file is untouched
- Only `SYLT` and `USLT` frames are modified; all other tags preserved
- Server binds to `127.0.0.1` only — not accessible from other devices on your network
