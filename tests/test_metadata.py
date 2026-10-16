import json
import shutil
import subprocess

import pytest

import app as webapp
import downloader


def test_metadata_normalizes_optional_fields():
    assert downloader.validate_metadata() == {}
    assert downloader.validate_metadata({"title": "  Signal  ", "artist": "  ", "track": "3/12"}) == {
        "title": "Signal", "track": "3/12",
    }
    assert downloader.validate_metadata({"comment": "Line one\nLine two"})["comment"] == "Line one\nLine two"


@pytest.mark.parametrize("metadata", [
    [], "Signal", False, {"unsupported": "tag"}, {"artist": 123}, {"title": None},
    {"title": "x" * 256}, {"comment": "x" * 2001}, {"title": "Bad\x00name"},
    {"artist": "Line\nbreak"}, {"year": "26"}, {"year": "202x"},
    {"track": "0"}, {"track": "-1"}, {"track": "2/1"}, {"track": "3/0"},
    {"disc": "1.5"}, {"disc": "10000"}, {"disc": "2/1"},
])
def test_invalid_metadata_rejected_before_job_created(monkeypatch, metadata):
    def no_worker(*_args, **_kwargs):
        pytest.fail("Invalid metadata must not start a download")
    monkeypatch.setattr(webapp.threading, "Thread", no_worker)
    response = webapp.app.test_client().post("/api/convert", json={
        "url": "https://youtu.be/test", "metadata": metadata,
    })
    assert response.status_code == 400
    assert response.json["error"]


@pytest.mark.parametrize("output_format", ["mp3", "mp4"])
def test_api_passes_metadata_to_worker_and_download(monkeypatch, tmp_path, output_format):
    captured = {}
    class InlineThread:
        def __init__(self, target, args, **_kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    def convert(**kwargs):
        captured.update(kwargs)
        path = tmp_path / f"Custom name.{output_format}"
        path.write_bytes(b"tagged media")
        return downloader.ConversionResult(kwargs["metadata"]["title"], path.name, path, kwargs["url"])
    monkeypatch.setattr(webapp.threading, "Thread", InlineThread)
    monkeypatch.setattr(webapp, "convert_youtube", convert)
    monkeypatch.setattr(webapp, "DOWNLOADS_DIR", tmp_path)
    client = webapp.app.test_client()
    response = client.post("/api/convert", json={
        "url": "https://youtu.be/test", "format": output_format,
        "metadata": {"title": " Custom name ", "artist": "ONI", "album": ""},
    })
    assert response.status_code == 202
    job_id = response.json["job_id"]
    try:
        job = client.get(f"/api/jobs/{job_id}").json
        assert job["status"] == "done"
        assert job["title"] == "Custom name"
        assert job["metadata"] == captured["metadata"] == {"title": "Custom name", "artist": "ONI"}
        assert client.get(job["download_url"]).data == b"tagged media"
    finally:
        webapp._jobs.pop(job_id, None)


@pytest.fixture(params=["mp3", "mp4"])
def tagged_source(request, tmp_path):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg and ffprobe are required for metadata integration tests")
    output_format = request.param
    path = tmp_path / f"source.{output_format}"
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    if output_format == "mp4":
        command += ["-f", "lavfi", "-i", "color=c=blue:s=96x64:r=25:d=1", "-c:v", "libx264", "-c:a", "aac", "-shortest"]
    else:
        command += ["-c:a", "libmp3lame", "-q:a", "0"]
    command += ["-metadata", "title=Source title", "-metadata", "artist=Source artist", "-metadata", "album=Source album", str(path)]
    subprocess.run(command, check=True, capture_output=True)
    return path, output_format


def probe(path):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-show_packets",
        "-show_data_hash", "sha256", "-of", "json", str(path),
    ], check=True, capture_output=True, encoding="utf-8")
    return json.loads(result.stdout)


def test_all_tags_embedded_without_reencoding(tagged_source, tmp_path):
    source, output_format = tagged_source
    destination = tmp_path / f"tagged.{output_format}"
    metadata = {
        "title": 'Night / Signal "緑"', "artist": "Björk & ONI", "album": "CyberAcme",
        "album_artist": "Various Artists", "genre": "Jungle", "year": "2026", "track": "3/12",
        "disc": "1/2", "composer": "ACME", "comment": "22:22 to 27:14\nCustom section",
    }
    downloader._write_metadata(source, destination, metadata, output_format)
    before, after = probe(source), probe(destination)
    tags = after["format"]["tags"]
    for key, value in metadata.items():
        assert tags["date" if key == "year" else key] == value
    assert [(s["codec_type"], s["codec_name"]) for s in before["streams"]] == [
        (s["codec_type"], s["codec_name"]) for s in after["streams"]
    ]
    # Compare encoded packet contents, rather than just checking codec names.
    assert [p["data_hash"] for p in before["packets"]] == [p["data_hash"] for p in after["packets"]]
    assert abs(float(before["format"]["duration"]) - float(after["format"]["duration"])) < .01


def test_blank_fields_preserve_source_tags(tagged_source, tmp_path):
    source, output_format = tagged_source
    destination = tmp_path / f"tagged.{output_format}"
    overrides = downloader.validate_metadata({"title": " ", "artist": "New artist", "album": ""})
    downloader._write_metadata(source, destination, overrides, output_format)
    tags = probe(destination)["format"]["tags"]
    assert tags["title"] == "Source title"
    assert tags["album"] == "Source album"
    assert tags["artist"] == "New artist"


def test_custom_title_names_full_download_and_handles_duplicates(monkeypatch, tagged_source, tmp_path):
    source, output_format = tagged_source
    class CopySourceYoutubeDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def download(self, _urls):
            shutil.copyfile(source, downloader.Path(self.options["outtmpl"]).parent / source.name)
    monkeypatch.setattr(downloader, "_read_video_info", lambda _url: {"title": "Original source", "duration": 1})
    monkeypatch.setattr(downloader, "YoutubeDL", CopySourceYoutubeDL)
    for index, suffix in enumerate(["", " (2)"]):
        result = downloader.convert_youtube(
            "https://youtu.be/test", tmp_path / "downloads", tmp_path / "temp", output_format=output_format,
            metadata={"title": "My / Signal", "artist": "ONI"},
        )
        assert result.title == "My / Signal"
        assert result.filename == f"My _ Signal{suffix}.{output_format}"
        assert probe(result.path)["format"]["tags"]["title"] == "My / Signal"
        assert len(list((tmp_path / "downloads").iterdir())) == index + 1
    assert list((tmp_path / "temp").iterdir()) == []


def test_failed_tagging_does_not_publish_file(monkeypatch, tagged_source, tmp_path):
    source, output_format = tagged_source
    class CopySourceYoutubeDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def download(self, _urls):
            shutil.copyfile(source, downloader.Path(self.options["outtmpl"]).parent / source.name)
    def failed_write(*_args):
        raise downloader.ConverterError("Could not save tags")
    monkeypatch.setattr(downloader, "_read_video_info", lambda _url: {"title": "Original source", "duration": 1})
    monkeypatch.setattr(downloader, "YoutubeDL", CopySourceYoutubeDL)
    monkeypatch.setattr(downloader, "_write_metadata", failed_write)
    with pytest.raises(downloader.ConverterError, match="Could not save tags"):
        downloader.convert_youtube(
            "https://youtu.be/test", tmp_path / "downloads", tmp_path / "temp", output_format=output_format,
            metadata={"artist": "ONI"},
        )
    assert list((tmp_path / "downloads").iterdir()) == []
    assert list((tmp_path / "temp").iterdir()) == []
