from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from downloader import (
    DEFAULT_MAX_DURATION_SECONDS, ConverterError, convert_youtube,
    inspect_youtube, validate_metadata, validate_section, validate_youtube_url,
)


BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
TEMP_DIR = BASE_DIR / "temp"
MAX_DURATION_SECONDS = int(os.getenv("MAX_DURATION_SECONDS", str(DEFAULT_MAX_DURATION_SECONDS)))

DOWNLOADS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _update_job(job_id: str, **values: object) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(values)


def _job_snapshot(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_job(job_id: str, url: str, output_format: str, start_time=None, end_time=None, metadata=None) -> None:
    try:
        def on_progress(update: dict) -> None:
            _update_job(job_id, **update)

        result = convert_youtube(
            url=url,
            downloads_dir=DOWNLOADS_DIR,
            temp_root=TEMP_DIR,
            output_format=output_format,
            progress_callback=on_progress,
            max_duration_seconds=MAX_DURATION_SECONDS,
            start_time=start_time,
            end_time=end_time,
            metadata=metadata,
        )
        _update_job(
            job_id,
            status="done",
            progress=100,
            title=result.title,
            filename=result.filename,
            output_format=output_format,
            download_url=f"/downloads/{quote(result.filename, safe='')}",
        )
    except (ConverterError, ValueError) as exc:
        _update_job(job_id, status="error", error=str(exc))
    except Exception:
        app.logger.exception("Unhandled conversion error for job %s", job_id)
        _update_job(job_id, status="error", error="Unexpected conversion error. Check the terminal for details.")


@app.get("/")
def index():
    return render_template(
        "index.html", max_minutes=MAX_DURATION_SECONDS // 60 if MAX_DURATION_SECONDS > 0 else None,
        max_duration_seconds=MAX_DURATION_SECONDS,
    )


@app.post("/api/inspect")
def inspect():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with a YouTube URL."}), 400
    try:
        return jsonify(inspect_youtube(payload.get("url", "")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except ConverterError as exc:
        return jsonify({"error": str(exc)}), 422


@app.post("/api/convert")
def convert():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with a YouTube URL."}), 400
    url = payload.get("url", "")
    output_format = payload.get("format", "mp3")

    try:
        url = validate_youtube_url(url)
        if not isinstance(output_format, str) or output_format not in {"mp3", "mp4"}:
            raise ValueError("Choose MP3 or MP4 as the output format.")
        start_time, end_time = validate_section(
            payload.get("start_time"), payload.get("end_time"), max_duration_seconds=MAX_DURATION_SECONDS,
        )
        metadata = validate_metadata(payload.get("metadata"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "title": None,
            "filename": None,
            "output_format": output_format,
            "download_url": None,
            "error": None,
            "speed": None,
            "eta": None,
            "start_time": start_time,
            "end_time": end_time,
            "metadata": metadata,
        }

    worker = threading.Thread(target=_run_job, args=(job_id, url, output_format, start_time, end_time, metadata), daemon=True)
    worker.start()

    return jsonify({"job_id": job_id}), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    job = _job_snapshot(job_id)
    if not job:
        abort(404)
    return jsonify(job)


@app.get("/downloads/<path:filename>")
def download_file(filename: str):
    # send_from_directory performs safe path joining. Requiring basename is an
    # additional guard against nested paths in this local-only endpoint.
    if Path(filename).name != filename or Path(filename).suffix.lower() not in {".mp3", ".mp4"}:
        abort(404)
    return send_from_directory(DOWNLOADS_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    # Deliberately local-only. Do not change this to 0.0.0.0 unless you intend
    # to expose the service to your network and add appropriate protections.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
