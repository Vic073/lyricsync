"""
LyricSync Pro - Backend
Flask app: scan MP3s, fetch lyrics from lrclib.net, embed into ID3 tags.
"""

import os
import json
import time
import queue
import threading
import csv
import io
from pathlib import Path
from flask import Flask, request, jsonify, Response, render_template, send_file

from scanner import scan_library
from fetcher import fetch_lyrics
from embedder import embed_lyrics, get_lyrics_state

app = Flask(__name__)

# ── Global session state ──────────────────────────────────────────────────────
session = {
    "files": [],          # list of dicts per file
    "status": "idle",     # idle | scanning | ready | processing | paused | done | cancelled
    "progress": 0,
    "total_eligible": 0,
    "counts": {"synced_embedded": 0, "unsynced_embedded": 0, "not_found": 0, "failed": 0, "skipped": 0},
    "current_file": "",
    "elapsed": 0,
    "start_time": None,
    "settings": {
        "delay_ms": 350,
        "embed_unsynced_fallback": True,
        "report_folder": ""
    }
}

_pause_event = threading.Event()
_pause_event.set()   # not paused by default
_cancel_flag = threading.Event()
_sse_queue = queue.Queue()

lock = threading.Lock()


def push(event_type, data):
    _sse_queue.put(json.dumps({"type": event_type, "data": data}))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    folder = request.json.get("folder", "").strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "Invalid folder path"}), 400

    with lock:
        session["status"] = "scanning"
        session["files"] = []
        session["counts"] = {"synced_embedded": 0, "unsynced_embedded": 0, "not_found": 0, "failed": 0, "skipped": 0}
        session["progress"] = 0
        if not session["settings"]["report_folder"]:
            session["settings"]["report_folder"] = folder

    push("status", {"status": "scanning"})

    def do_scan():
        files = scan_library(folder)
        eligible = sum(1 for f in files if f["state"] in ("EMPTY", "UNSYNCED"))
        with lock:
            session["files"] = files
            session["total_eligible"] = eligible
            session["status"] = "ready"
        push("scan_done", {
            "total": len(files),
            "eligible": eligible,
            "skipped": sum(1 for f in files if f["state"] == "SYNCED"),
            "empty": sum(1 for f in files if f["state"] == "EMPTY"),
            "unsynced": sum(1 for f in files if f["state"] == "UNSYNCED"),
        })

    threading.Thread(target=do_scan, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/scan/status")
def scan_status():
    with lock:
        return jsonify({
            "status": session["status"],
            "total": len(session["files"]),
            "eligible": session["total_eligible"],
            "files": session["files"][:200]   # cap for JSON size
        })


@app.route("/process/start", methods=["POST"])
def process_start():
    with lock:
        if session["status"] not in ("ready", "paused"):
            return jsonify({"error": "Not ready"}), 400
        session["status"] = "processing"
        session["start_time"] = time.time()

    _cancel_flag.clear()
    _pause_event.set()
    push("status", {"status": "processing"})
    threading.Thread(target=process_queue, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/process/pause", methods=["POST"])
def process_pause():
    _pause_event.clear()
    with lock:
        session["status"] = "paused"
    push("status", {"status": "paused"})
    return jsonify({"ok": True})


@app.route("/process/resume", methods=["POST"])
def process_resume():
    _pause_event.set()
    with lock:
        session["status"] = "processing"
    push("status", {"status": "processing"})
    return jsonify({"ok": True})


@app.route("/process/cancel", methods=["POST"])
def process_cancel():
    _cancel_flag.set()
    _pause_event.set()  # unblock if paused
    with lock:
        session["status"] = "cancelled"
    push("status", {"status": "cancelled"})
    return jsonify({"ok": True})


@app.route("/process/stream")
def process_stream():
    def generate():
        yield "retry: 1000\n\n"
        while True:
            try:
                msg = _sse_queue.get(timeout=20)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield ": ping\n\n"
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/results")
def results():
    with lock:
        return jsonify({
            "files": session["files"],
            "counts": session["counts"],
            "status": session["status"],
            "elapsed": int(time.time() - session["start_time"]) if session["start_time"] else 0
        })


@app.route("/results/export")
def results_export():
    with lock:
        files = list(session["files"])
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "filename", "artist", "title", "album", "duration_s",
        "initial_state", "outcome", "source"
    ])
    writer.writeheader()
    for f in files:
        writer.writerow({
            "filename": f.get("filename", ""),
            "artist": f.get("artist", ""),
            "title": f.get("title", ""),
            "album": f.get("album", ""),
            "duration_s": f.get("duration_s", ""),
            "initial_state": f.get("state", ""),
            "outcome": f.get("outcome", ""),
            "source": f.get("source", ""),
        })
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=lyricsync_report.csv"}
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    with lock:
        if request.method == "POST":
            data = request.json or {}
            if "delay_ms" in data:
                session["settings"]["delay_ms"] = max(100, min(2000, int(data["delay_ms"])))
            if "embed_unsynced_fallback" in data:
                session["settings"]["embed_unsynced_fallback"] = bool(data["embed_unsynced_fallback"])
            if "report_folder" in data:
                session["settings"]["report_folder"] = data["report_folder"]
        return jsonify(session["settings"])


# ── Processing worker ─────────────────────────────────────────────────────────

def process_queue():
    with lock:
        eligible = [f for f in session["files"] if f["state"] in ("EMPTY", "UNSYNCED")]
        delay = session["settings"]["delay_ms"] / 1000.0
        fallback = session["settings"]["embed_unsynced_fallback"]

    processed = 0
    total = len(eligible)

    for file_info in eligible:
        if _cancel_flag.is_set():
            break

        # Pause support
        _pause_event.wait()
        if _cancel_flag.is_set():
            break

        path = file_info["path"]
        with lock:
            session["current_file"] = file_info["filename"]

        push("progress", {
            "current_file": file_info["filename"],
            "artist": file_info.get("artist", ""),
            "title": file_info.get("title", ""),
            "processed": processed,
            "total": total,
            "elapsed": int(time.time() - session["start_time"]),
            "counts": dict(session["counts"])
        })

        # Fetch lyrics
        try:
            result = fetch_lyrics(
                artist=file_info.get("artist", ""),
                title=file_info.get("title", ""),
                album=file_info.get("album", ""),
                duration=file_info.get("duration_s", 0)
            )
        except Exception as e:
            outcome = "FAILED"
            source = f"fetch error: {e}"
            result = None

        if result is not None:
            synced = result.get("syncedLyrics")
            plain = result.get("plainLyrics")

            if synced:
                try:
                    embed_lyrics(path, synced_lrc=synced)
                    outcome = "SYNCED_EMBEDDED"
                    source = "lrclib.net (synced)"
                except Exception as e:
                    outcome = "FAILED"
                    source = f"embed error: {e}"
            elif plain and fallback:
                try:
                    embed_lyrics(path, plain_text=plain)
                    outcome = "UNSYNCED_EMBEDDED"
                    source = "lrclib.net (plain)"
                except Exception as e:
                    outcome = "FAILED"
                    source = f"embed error: {e}"
            else:
                outcome = "NOT_FOUND"
                source = "lrclib.net: no lyrics"
        elif result is None and 'outcome' not in locals():
            outcome = "NOT_FOUND"
            source = "lrclib.net: no match"

        with lock:
            file_info["outcome"] = outcome
            file_info["source"] = source
            key = outcome.lower()
            if outcome == "SYNCED_EMBEDDED":
                session["counts"]["synced_embedded"] += 1
            elif outcome == "UNSYNCED_EMBEDDED":
                session["counts"]["unsynced_embedded"] += 1
            elif outcome == "NOT_FOUND":
                session["counts"]["not_found"] += 1
            elif outcome == "FAILED":
                session["counts"]["failed"] += 1

        push("file_done", {
            "filename": file_info["filename"],
            "outcome": outcome,
            "source": source,
            "counts": dict(session["counts"])
        })

        processed += 1
        with lock:
            session["progress"] = processed

        time.sleep(delay)

    # Mark skipped files
    with lock:
        skipped_count = 0
        for f in session["files"]:
            if f["state"] == "SYNCED" and "outcome" not in f:
                f["outcome"] = "SKIPPED"
                f["source"] = "already has synced lyrics"
                skipped_count += 1
        session["counts"]["skipped"] = skipped_count
        if not _cancel_flag.is_set():
            session["status"] = "done"
        session["current_file"] = ""

    push("done", {
        "counts": dict(session["counts"]),
        "elapsed": int(time.time() - session["start_time"]),
        "status": session["status"]
    })


if __name__ == "__main__":
    import webbrowser
    print("\n  ╔══════════════════════════════════════╗")
    print("  ║       LyricSync Pro is running       ║")
    print("  ║   Open http://127.0.0.1:5000         ║")
    print("  ╚══════════════════════════════════════╝\n")
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
