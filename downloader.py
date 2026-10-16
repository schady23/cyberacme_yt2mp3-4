from __future__ import annotations

import copy
import logging
import math
import re
import shutil
import subprocess
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, download_range_func


ProgressCallback = Callable[[dict], None]
DEFAULT_MAX_DURATION_SECONDS = 4 * 60 * 60
logger = logging.getLogger(__name__)
METADATA_FIELDS = {
    "title": "Title", "artist": "Artist", "album": "Album", "album_artist": "Album artist",
    "genre": "Genre", "year": "Year", "track": "Track", "disc": "Disc",
    "composer": "Composer", "comment": "Comment",
}


def _youtube_runtime_options() -> dict:
    """Enable installed challenge runtimes; Node is not enabled by yt-dlp by default."""
    runtimes = {}
    for name in ("deno", "node"):
        executable = shutil.which(name)
        if executable:
            runtimes[name] = {"path": executable}
    return {"js_runtimes": runtimes} if runtimes else {}


class ConverterError(RuntimeError):
    """Raised when a conversion cannot be completed safely."""


@dataclass(frozen=True)
class ConversionResult:
    title: str
    filename: str
    path: Path
    source_url: str


def validate_youtube_url(url: str) -> str:
    """Return a normalized YouTube URL or raise ValueError."""
    if not isinstance(url, str):
        raise ValueError("URL must be text.")

    url = url.strip()
    if not url or len(url) > 2048:
        raise ValueError("Enter a valid YouTube URL.")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must start with http:// or https://.")

    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed.")

    host = parsed.hostname.rstrip(".").lower()
    allowed = (
        host == "youtu.be"
        or host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtube-nocookie.com"
        or host.endswith(".youtube-nocookie.com")
    )
    if not allowed:
        raise ValueError("Only YouTube URLs are supported.")

    return url


def parse_timestamp(value: object, label: str = "Time") -> float:
    """Accept seconds, MM:SS, or HH:MM:SS, including fractional seconds."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{label} must be seconds, MM:SS, or HH:MM:SS.")
    text = str(value).strip()
    if len(text) > 32 or not re.fullmatch(r"\d+(?::\d{1,2}){0,2}(?:\.\d{1,3})?", text):
        raise ValueError(f"{label} must be seconds, MM:SS, or HH:MM:SS.")
    parts = [float(part) for part in text.split(":")]
    if any(part >= 60 for part in parts[1:]):
        raise ValueError(f"{label}: seconds and hour-format minutes must be below 60.")
    seconds = sum(part * 60 ** index for index, part in enumerate(reversed(parts)))
    if not math.isfinite(seconds):
        raise ValueError(f"{label} must be a finite time.")
    return round(seconds, 3)


def validate_section(
    start_time: object = None,
    end_time: object = None,
    *,
    duration: float | None = None,
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
) -> tuple[float | None, float | None]:
    """Validate a complete optional range, without silently clamping its ends."""
    start_empty = start_time is None or start_time == ""
    end_empty = end_time is None or end_time == ""
    if start_empty and end_empty:
        return None, None
    if start_empty or end_empty:
        raise ValueError("Enter both a start time and an end time for your section.")
    start = parse_timestamp(start_time, "Start time")
    end = parse_timestamp(end_time, "End time")
    if end <= start:
        raise ValueError("End time must be after start time.")
    if duration is not None and (start >= duration or end > duration):
        raise ValueError(f"Your section must fit within the video ({format_timestamp(duration)}).")
    if max_duration_seconds > 0 and end - start > max_duration_seconds:
        raise ValueError(f"Section is longer than the configured {max_duration_seconds // 60}-minute limit.")
    return start, end


def format_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    whole, fraction = divmod(milliseconds, 1000)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    stamp = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return stamp + (f".{fraction:03d}".rstrip("0") if fraction else "")


def validate_metadata(value: object = None) -> dict[str, str]:
    """Normalize optional tag overrides; empty fields preserve source metadata."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Metadata must be an object of text fields.")
    if value.keys() - METADATA_FIELDS.keys():
        raise ValueError("Unsupported metadata field.")
    metadata = {}
    for key, text in value.items():
        label = METADATA_FIELDS[key]
        if not isinstance(text, str):
            raise ValueError(f"{label} must be text.")
        text = text.strip()
        if not text:
            continue
        limit = 2000 if key == "comment" else 255
        if len(text) > limit:
            raise ValueError(f"{label} must be {limit} characters or fewer.")
        allowed_controls = "\n\r\t" if key == "comment" else ""
        if any(unicodedata.category(char) == "Cc" and char not in allowed_controls for char in text):
            raise ValueError(f"{label} contains an unsupported control character.")
        if key == "year" and not re.fullmatch(r"[0-9]{4}", text):
            raise ValueError("Year must contain four digits, for example 2026.")
        if key in {"track", "disc"}:
            if not re.fullmatch(r"[1-9][0-9]{0,3}(?:/[1-9][0-9]{0,3})?", text):
                raise ValueError(f"{label} must be a positive number or number/total, for example 3/12.")
            numbers = [int(part) for part in text.split("/")]
            if len(numbers) == 2 and numbers[0] > numbers[1]:
                raise ValueError(f"{label} number cannot exceed its total.")
        metadata[key] = text
    return metadata


def _read_video_info(source_url: str) -> dict:
    options = {
        **_youtube_runtime_options(),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 30,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(source_url, download=False)
    except DownloadError as exc:
        raise ConverterError(_friendly_yt_error(exc)) from exc
    if not info:
        raise ConverterError("Could not read metadata for that video.")
    if info.get("_type") in {"playlist", "multi_video"}:
        raise ConverterError("Playlists are not supported. Paste a single video URL.")
    return info


def _video_duration(info: dict) -> float | None:
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration > 0:
        return float(duration)
    return None


def inspect_youtube(url: str) -> dict:
    info = _read_video_info(validate_youtube_url(url))
    return {
        "title": str(info.get("title") or "Untitled video"),
        "duration": _video_duration(info),
        "is_live": bool(info.get("is_live")),
    }


def _safe_filename(value: str, max_length: int = 180) -> str:
    """Make a cross-platform filename while preserving readable Unicode."""
    value = unicodedata.normalize("NFKC", value or "audio")
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")

    if not value:
        value = "audio"

    # Windows reserved device names.
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if value.upper() in reserved:
        value = f"_{value}"

    return value[:max_length].rstrip(" .") or "audio"


def _unique_destination(downloads_dir: Path, stem: str, extension: str) -> Path:
    destination = downloads_dir / f"{stem}.{extension}"
    if not destination.exists():
        return destination

    counter = 2
    while True:
        candidate = downloads_dir / f"{stem} ({counter}).{extension}"
        if not candidate.exists():
            return candidate
        counter += 1


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _emit(callback: Optional[ProgressCallback], **payload: object) -> None:
    if callback:
        callback(payload)


def _trim_local(source: Path, destination: Path, start: float, end: float, output_format: str) -> None:
    """Cut a downloaded file without sending another media request to YouTube."""
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", str(start), "-i", str(source), "-t", str(round(end - start, 3)),
        "-map_metadata", "0",
    ]
    if output_format == "mp3":
        command += ["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-q:a", "0"]
    else:
        command += [
            "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "fast",
            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        ]
    try:
        completed = subprocess.run(command + [str(destination)], capture_output=True, text=True, errors="replace")
    except OSError as exc:
        raise ConverterError("Could not start FFmpeg for the local cut. Check your FFmpeg installation.") from exc
    if completed.returncode:
        # Keep full codec diagnostics in the terminal; never reflect signed media URLs.
        logger.error("Local FFmpeg cut failed: %s", completed.stderr[-6000:])
        detail = completed.stderr.lower()
        if "unknown encoder" in detail or "encoder not found" in detail:
            raise ConverterError("This FFmpeg build lacks an encoder needed for the cut. Install a full FFmpeg build with libx264 and libmp3lame.")
        raise ConverterError("FFmpeg could not cut the downloaded file. Check the terminal for codec details.")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ConverterError("The selected section did not produce a playable file. Try a different range.")


def _direct_section_failed(exc: Exception) -> bool:
    # FFmpeg on Windows exposes unsigned AVERROR_HTTP_FORBIDDEN as 3436169992.
    return bool(re.search(r"ffmpeg exited with code|HTTP Error 403|403 Forbidden", str(exc), re.IGNORECASE))


def _write_metadata(source: Path, destination: Path, metadata: dict[str, str], output_format: str) -> None:
    """Override final-file tags with stream copying, after any conversion or cut."""
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(source), "-map", "0", "-map_metadata", "0", "-c", "copy",
    ]
    for key, value in metadata.items():
        command += ["-metadata", f"{'date' if key == 'year' else key}={value}"]
    if output_format == "mp3":
        command += ["-id3v2_version", "3"]
    else:
        command += ["-movflags", "+faststart"]
    try:
        completed = subprocess.run(command + [str(destination)], capture_output=True, text=True, errors="replace")
    except OSError as exc:
        raise ConverterError("Could not start FFmpeg to save your metadata. Check your FFmpeg installation.") from exc
    if completed.returncode:
        logger.error("FFmpeg metadata write failed: %s", completed.stderr[-6000:])
        raise ConverterError("FFmpeg could not save your metadata. Check the terminal for details.")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ConverterError("Writing metadata did not produce a file. Please retry.")


def convert_youtube(
    url: str,
    downloads_dir: Path,
    temp_root: Path,
    output_format: str = "mp3",
    progress_callback: Optional[ProgressCallback] = None,
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
    start_time: object = None,
    end_time: object = None,
    metadata: object = None,
) -> ConversionResult:
    """
    Download a YouTube video as an MP3 audio file or MP4 video file.

    This function intentionally accepts only YouTube URLs. It creates an isolated
    temporary directory per conversion and moves only the final media file into the
    configured downloads directory.
    """
    source_url = validate_youtube_url(url)
    if output_format not in {"mp3", "mp4"}:
        raise ValueError("Output format must be MP3 or MP4.")
    start, end = validate_section(start_time, end_time, max_duration_seconds=max_duration_seconds)
    metadata = validate_metadata(metadata)
    is_section = start is not None

    if not _ffmpeg_available():
        raise ConverterError(
            "FFmpeg and ffprobe are required but were not found on PATH. "
            "Install FFmpeg, then restart the app."
        )

    downloads_dir = downloads_dir.resolve()
    temp_root = temp_root.resolve()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    job_temp = temp_root / uuid.uuid4().hex
    job_temp.mkdir(parents=True, exist_ok=False)

    try:
        _emit(progress_callback, status="inspecting", progress=0)

        info = _read_video_info(source_url)
        title = metadata.get("title") or str(info.get("title") or "media")
        duration = _video_duration(info)
        if is_section:
            if info.get("is_live") or duration is None:
                raise ConverterError("Sections require a finished video with a known length. Live streams cannot be trimmed.")
            validate_section(start, end, duration=duration, max_duration_seconds=max_duration_seconds)
        if (
            not is_section
            and max_duration_seconds > 0
            and duration is not None
            and duration > max_duration_seconds
        ):
            minutes = max_duration_seconds // 60
            raise ConverterError(f"Video is longer than the configured {minutes}-minute limit.")

        _emit(progress_callback, status="downloading", progress=None if is_section else 0, title=title)
        fallback_active = False

        def progress_hook(data: dict) -> None:
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                downloaded = data.get("downloaded_bytes") or 0
                percent = None
                if total:
                    percent = max(0.0, min(90.0, downloaded * 90.0 / total))

                _emit(
                    progress_callback,
                    status="downloading",
                    progress=percent,
                    speed=data.get("speed"),
                    eta=data.get("eta"),
                    title=title,
                    message="Downloading source for a local cut." if fallback_active else None,
                )
            elif status == "finished":
                _emit(progress_callback, status="converting", progress=95, title=title)

        def postprocessor_hook(data: dict) -> None:
            if data.get("status") == "started":
                _emit(progress_callback, status="converting", progress=95, title=title)

        output_template = str(job_temp / "%(title).180B [%(id)s].%(ext)s")
        download_opts = {
            **_youtube_runtime_options(),
            "format": (
                "bestaudio/best"
                if output_format == "mp3"
                else "bv[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv+ba/b"
            ),
            "outtmpl": output_template,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
            "postprocessors": [{"key": "FFmpegMetadata", "add_metadata": True}],
        }
        if is_section:
            download_opts["download_ranges"] = download_range_func(None, [(start, end)])
            # FFmpeg seeks the source streams and re-encodes this range, so cuts
            # do not jump back to the previous video keyframe.
            download_opts["force_keyframes_at_cuts"] = True
            download_opts["external_downloader_args"] = {
                "ffmpeg_i": ["-rw_timeout", "30000000"],
                "ffmpeg_o": ["-loglevel", "error"],
            }
        if output_format == "mp3":
            download_opts["postprocessors"].insert(
                0,
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                },
            )
        else:
            download_opts["merge_output_format"] = "mp4"
            download_opts["postprocessors"].insert(
                0,
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                },
            )

        try:
            with YoutubeDL(download_opts) as ydl:
                ydl.download([source_url])
        except DownloadError as exc:
            if not is_section or not _direct_section_failed(exc):
                raise ConverterError(_friendly_yt_error(exc)) from exc
            logger.warning("Direct section failed; retrying with a native download and local cut: %s", exc)
            fallback_active = True
            _emit(progress_callback, status="retrying", progress=None, title=title,
                  message="Direct stream refused. Downloading source, then cutting locally.")
            fallback_dir = job_temp / "source"
            fallback_dir.mkdir()
            fallback_opts = copy.deepcopy(download_opts)
            fallback_opts.pop("download_ranges", None)
            fallback_opts.pop("force_keyframes_at_cuts", None)
            fallback_opts.pop("external_downloader_args", None)
            fallback_opts["external_downloader"] = "native"
            fallback_opts["hls_prefer_native"] = True
            fallback_opts["outtmpl"] = str(fallback_dir / "source.%(ext)s")
            try:
                with YoutubeDL(fallback_opts) as ydl:
                    ydl.download([source_url])
            except DownloadError as retry_exc:
                raise ConverterError(_friendly_yt_error(retry_exc)) from retry_exc
            source_files = list(fallback_dir.glob(f"*.{output_format}"))
            if not source_files:
                raise ConverterError("The source download did not produce a file for trimming.")
            _emit(progress_callback, status="trimming", progress=95, title=title, message="Cutting your section locally.")
            _trim_local(max(source_files, key=lambda path: path.stat().st_mtime), job_temp / f"section.{output_format}", start, end, output_format)

        media_files = list(job_temp.glob(f"*.{output_format}"))
        if not media_files:
            raise ConverterError(f"Conversion finished, but no {output_format.upper()} file was produced.")

        # A single-video job should produce one final file. Prefer the newest if a tool
        # ever leaves more than one candidate behind.
        produced = job_temp / f"section.{output_format}" if fallback_active else max(media_files, key=lambda path: path.stat().st_mtime)
        if metadata:
            _emit(progress_callback, status="tagging", progress=98, title=title, message="Saving your file details.")
            tagged = job_temp / f"tagged.{output_format}"
            _write_metadata(produced, tagged, metadata, output_format)
            produced = tagged
        stem = _safe_filename(title, max_length=140 if is_section else 180)
        if is_section:
            section_tag = f"{format_timestamp(start)} to {format_timestamp(end)}".replace(":", "-")
            stem = f"{stem} [{section_tag}]"
        destination = _unique_destination(downloads_dir, stem, output_format)

        _emit(progress_callback, status="saving", progress=99, title=title)
        shutil.move(str(produced), str(destination))

        return ConversionResult(
            title=title,
            filename=destination.name,
            path=destination,
            source_url=source_url,
        )
    finally:
        shutil.rmtree(job_temp, ignore_errors=True)


def _friendly_yt_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()

    if "3436169992" in lowered or "-858797304" in lowered or "403" in lowered:
        return "YouTube refused the media request (HTTP 403). Update yt-dlp and retry. Some videos need authentication that this app does not support."
    if "ffmpeg exited with code" in lowered:
        return "FFmpeg could not read the media stream. Retry or update yt-dlp; check the terminal for details."

    if "private video" in lowered:
        return "That video is private and cannot be accessed."
    if "video unavailable" in lowered or "unavailable" in lowered:
        return "That video is unavailable."
    if "sign in" in lowered or "age" in lowered:
        return "YouTube requires authentication for that video; this local version does not import browser cookies."
    if "copyright" in lowered:
        return "YouTube reports that this video is unavailable for copyright reasons."
    if "timed out" in lowered or "timeout" in lowered:
        return "The request to YouTube timed out. Try again."

    # Avoid reflecting enormous extractor logs into the browser.
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) > 350:
        cleaned = cleaned[:347] + "..."
    return cleaned or "yt-dlp could not process that URL."
