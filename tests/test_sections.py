import functools
import http.server
import json
import shutil
import subprocess
import threading

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

import app as webapp
import downloader


@pytest.mark.parametrize("value,expected", [(0, 0), (2760, 2760), ("46:00", 2760), ("48:00", 2880), ("1:02:03.125", 3723.125), ("120.5", 120.5), (" 00:09 ", 9)])
def test_parse_timestamp(value, expected):
    assert downloader.parse_timestamp(value) == expected


@pytest.mark.parametrize("value", [True, False, None, [], {}, "", "-1", -1, "NaN", float("inf"), "1e3", "46:60", "1:60:00", "1:02:03:04", "1.2:03", "00:01.1234"])
def test_parse_timestamp_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        downloader.parse_timestamp(value)


@pytest.mark.parametrize("stamp", ["01:01.001", "01:02.123", "45:11.001"])
def test_fractional_timestamp_survives_api_to_worker_roundtrip(stamp):
    seconds = downloader.parse_timestamp(stamp)
    assert downloader.parse_timestamp(seconds) == seconds


@pytest.mark.parametrize("start,end", [(None, "01:00"), ("00:00", None), ("", "1"), ("48:00", "46:00"), (0, 0), (-1, 2)])
def test_invalid_section_rejected_before_job_created(start, end):
    response = webapp.app.test_client().post("/api/convert", json={
        "url": "https://youtu.be/test", "start_time": start, "end_time": end,
    })
    assert response.status_code == 400
    assert "error" in response.json


@pytest.mark.parametrize("endpoint", ["/api/inspect", "/api/convert"])
@pytest.mark.parametrize("payload", [[], None, "text", 42])
def test_api_requires_json_object(endpoint, payload):
    response = webapp.app.test_client().post(endpoint, json=payload)
    assert response.status_code == 400


@pytest.mark.parametrize("output_format", ["mp3", "mp4"])
def test_section_options_and_filename(monkeypatch, tmp_path, output_format):
    options = []
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            options.append(opts)
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def extract_info(self, *_args, **_kwargs):
            # Short clips may be taken from a source longer than the output limit.
            return {"title": "An hour mix", "duration": 3600}
        def download(self, _urls):
            (downloader.Path(self.opts["outtmpl"]).parent / f"clip.{output_format}").write_bytes(b"section")
    monkeypatch.setattr(downloader, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(downloader, "_ffmpeg_available", lambda: True)
    result = downloader.convert_youtube("https://youtu.be/test", tmp_path / "downloads", tmp_path / "temp",
        output_format=output_format, start_time="46:00", end_time="48:00", max_duration_seconds=120)
    assert list(options[1]["download_ranges"]({}, None)) == [{"start_time": 2760, "end_time": 2880}]
    assert options[1]["force_keyframes_at_cuts"] is True
    assert result.filename == f"An hour mix [00-46-00 to 00-48-00].{output_format}"
    assert result.path.read_bytes() == b"section"
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.parametrize("info,start,end,message", [
    ({"duration": 60}, 60, 61, "fit within"),
    ({"duration": 60}, 59, 61, "fit within"),
    ({"duration": None}, 0, 10, "known length"),
    ({"duration": 60, "is_live": True}, 0, 10, "finished video"),
])
def test_source_range_errors_clean_up_without_downloading(monkeypatch, tmp_path, info, start, end, message):
    monkeypatch.setattr(downloader, "_read_video_info", lambda _url: info)
    monkeypatch.setattr(downloader, "_ffmpeg_available", lambda: True)
    with pytest.raises((ValueError, downloader.ConverterError), match=message):
        downloader.convert_youtube("https://youtu.be/test", tmp_path / "downloads", tmp_path / "temp", start_time=start, end_time=end)
    assert list((tmp_path / "temp").iterdir()) == []


def test_section_limit():
    with pytest.raises(ValueError, match="Section is longer"):
        downloader.validate_section("00:00", "02:01", max_duration_seconds=120)
    assert downloader.validate_section("46:00", "48:00", duration=3600, max_duration_seconds=120) == (2760, 2880)
    assert downloader.validate_section(None, None) == (None, None)


def test_inspect_endpoint(monkeypatch):
    monkeypatch.setattr(downloader, "_read_video_info", lambda _url: {"title": "Hour mix", "duration": 3600})
    client = webapp.app.test_client()
    assert client.post("/api/inspect", json={"url": "https://youtu.be/test"}).json == {"title": "Hour mix", "duration": 3600, "is_live": False}
    assert client.post("/api/inspect", json={"url": "https://example.com/test"}).status_code == 400


@pytest.mark.parametrize("output_format", ["mp3", "mp4"])
def test_job_passes_section_and_returns_download(monkeypatch, tmp_path, output_format):
    captured = {}
    class InlineThread:
        def __init__(self, target, args, **_kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    def convert(**kwargs):
        captured.update(kwargs)
        path = tmp_path / f"section #1.{output_format}"
        path.write_bytes(b"clip content")
        return downloader.ConversionResult("Hour mix", path.name, path, kwargs["url"])
    monkeypatch.setattr(webapp.threading, "Thread", InlineThread)
    monkeypatch.setattr(webapp, "convert_youtube", convert)
    monkeypatch.setattr(webapp, "DOWNLOADS_DIR", tmp_path)
    client = webapp.app.test_client()
    response = client.post("/api/convert", json={"url": "https://youtu.be/test", "format": output_format, "start_time": "46:00", "end_time": "48:00"})
    assert response.status_code == 202
    job_id = response.json["job_id"]
    try:
        job = client.get(f"/api/jobs/{job_id}").json
        assert (job["start_time"], job["end_time"], job["status"]) == (2760, 2880, "done")
        assert (captured["start_time"], captured["end_time"]) == (2760, 2880)
        assert client.get(job["download_url"]).data == b"clip content"
    finally:
        webapp._jobs.pop(job_id, None)


@pytest.fixture(scope="module")
def synthetic_source(tmp_path_factory):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg and ffprobe are required for media integration tests")
    root = tmp_path_factory.mktemp("section-media")
    media = root / "source.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=25:d=8",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-vf", "drawbox=color=blue:t=fill:enable='gte(t,2)'",
        "-c:v", "libx264", "-g", "250", "-c:a", "aac", "-movflags", "+faststart", "-shortest", str(media),
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", str(media), "-c:v", "libvpx-vp9",
        "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus", str(root / "source.webm"),
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", str(media), "-vn", "-c:a", "copy",
        "-movflags", "+faststart", str(root / "audio.m4a"),
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", str(media), "-vn", "-c:a", "libopus", str(root / "audio.webm"),
    ], check=True, capture_output=True)
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("output_format,source_file", [
    ("mp3", "source.mp4"), ("mp4", "source.mp4"),
    ("mp3", "audio.m4a"), ("mp3", "audio.webm"), ("mp4", "source.webm"),
])
@pytest.mark.parametrize("force_fallback", [False, True])
def test_real_ffmpeg_section_duration_and_video_seek(monkeypatch, tmp_path, synthetic_source, output_format, source_file, force_fallback):
    updates = []
    class LocalSourceYoutubeDL(YoutubeDL):
        def download(self, urls):
            if force_fallback and self.params.get("download_ranges"):
                raise DownloadError("ERROR: ffmpeg exited with code 3436169992")
            if force_fallback:
                assert self.params["external_downloader"] == "native"
            return super().download(urls)
        def extract_info(self, url, download=True, **_kwargs):
            assert url == "https://youtu.be/test"
            return self.process_ie_result({
                "id": "local-fixture", "title": "Synthetic signal", "duration": 8,
                "url": f"{synthetic_source}/{source_file}", "ext": source_file.split(".")[-1], "extractor": "fixture",
                "webpage_url": url, "vcodec": "none" if source_file.startswith("audio") else "vp9" if source_file.endswith("webm") else "h264",
                "acodec": "opus" if source_file.endswith("webm") else "aac",
            }, download=download)
    monkeypatch.setattr(downloader, "YoutubeDL", LocalSourceYoutubeDL)
    result = downloader.convert_youtube("https://youtu.be/test", tmp_path / "downloads", tmp_path / "temp",
        output_format=output_format, start_time="00:02.25", end_time="00:05.75", progress_callback=updates.append,
        metadata={"title": "My section", "artist": "ONI", "album": "Custom mix", "track": "2/3", "year": "2026"})
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(result.path)], check=True, capture_output=True, text=True)
    data = json.loads(probe.stdout)
    assert data["format"]["tags"]["title"] == "My section"
    assert data["format"]["tags"]["artist"] == "ONI"
    assert data["format"]["tags"]["album"] == "Custom mix"
    assert data["format"]["tags"]["track"] == "2/3"
    assert data["format"]["tags"]["date"] == "2026"
    assert result.filename == f"My section [00-00-02.25 to 00-00-05.75].{output_format}"
    assert "tagging" in [update["status"] for update in updates]
    assert abs(float(data["format"]["duration"]) - 3.5) < 0.15
    kinds = {stream["codec_type"] for stream in data["streams"]}
    assert "audio" in kinds
    if output_format == "mp4":
        assert "video" in kinds
        frame = subprocess.run(["ffmpeg", "-v", "error", "-i", str(result.path), "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
        # The original starts red; the requested section starts after it turns blue.
        assert frame[2] > 200 and frame[0] < 30
    else:
        assert kinds == {"audio"}
    assert list((tmp_path / "temp").iterdir()) == []
    if force_fallback:
        assert "retrying" in [update["status"] for update in updates]
        assert "trimming" in [update["status"] for update in updates]


@pytest.mark.parametrize("message", [
    "ERROR: ffmpeg exited with code 3436169992", "ERROR: ffmpeg exited with code -858797304", "HTTP Error 403: Forbidden",
])
def test_403_error_is_actionable(message):
    assert "HTTP 403" in downloader._friendly_yt_error(DownloadError(message))
    assert "Update yt-dlp" in downloader._friendly_yt_error(DownloadError(message))


def test_installed_node_is_enabled_for_youtube(monkeypatch):
    monkeypatch.setattr(downloader.shutil, "which", lambda name: "/installed/node" if name == "node" else None)
    assert downloader._youtube_runtime_options() == {"js_runtimes": {"node": {"path": "/installed/node"}}}


def test_failed_fallback_cleans_temp(monkeypatch, tmp_path):
    class RefusedYoutubeDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def extract_info(self, *_args, **_kwargs):
            return {"title": "Refused", "duration": 60}
        def download(self, _urls):
            if self.options.get("download_ranges"):
                raise DownloadError("ERROR: ffmpeg exited with code 3436169992")
            raise DownloadError("HTTP Error 403: Forbidden")
    monkeypatch.setattr(downloader, "YoutubeDL", RefusedYoutubeDL)
    monkeypatch.setattr(downloader, "_ffmpeg_available", lambda: True)
    with pytest.raises(downloader.ConverterError, match="HTTP 403"):
        downloader.convert_youtube("https://youtu.be/test", tmp_path / "downloads", tmp_path / "temp", start_time=5, end_time=10)
    assert list((tmp_path / "temp").iterdir()) == []
