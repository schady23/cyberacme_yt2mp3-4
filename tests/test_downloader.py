import pytest

import downloader
from downloader import _safe_filename, convert_youtube, validate_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    ],
)
def test_youtube_urls_are_accepted(url):
    assert validate_youtube_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com.example.org/watch?v=x",
        "https://example.org/?next=youtube.com",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "",
    ],
)
def test_non_youtube_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_youtube_url(url)


def test_filename_sanitization():
    assert _safe_filename('  A <song>: "test"?  ') == "A _song__ _test__"


def test_convert_endpoint_rejects_unknown_output_format():
    from app import app

    response = app.test_client().post(
        "/api/convert",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "format": "avi"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Choose MP3 or MP4 as the output format."


def test_mp4_conversion_uses_ffmpeg_postprocessor(monkeypatch, tmp_path):
    captured_options = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            captured_options.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, download=False):
            assert download is False
            return {"title": "Test video", "duration": 60}

        def download(self, _urls):
            output_dir = downloader.Path(self.options["outtmpl"]).parent
            (output_dir / "Test video.mp4").write_bytes(b"video")

    monkeypatch.setattr(downloader, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(downloader, "_ffmpeg_available", lambda: True)

    result = convert_youtube(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        tmp_path / "downloads",
        tmp_path / "temp",
        output_format="mp4",
    )

    download_options = captured_options[1]
    assert download_options["merge_output_format"] == "mp4"
    assert {
        "key": "FFmpegVideoConvertor",
        "preferedformat": "mp4",
    } in download_options["postprocessors"]
    assert result.path == tmp_path / "downloads" / "Test video.mp4"
    assert result.path.read_bytes() == b"video"


@pytest.mark.parametrize("output_format", ["mp3", "mp4"])
@pytest.mark.parametrize(
    "duration,limit,accepted",
    [(10_801, None, True), (14_400, None, True), (14_401, None, False),
     (3_601, 3_600, False), (18_000, 0, True)],
)
def test_conversion_duration_boundary(monkeypatch, tmp_path, output_format, duration, limit, accepted):
    downloads = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, download=False):
            return {"title": "Long video", "duration": duration}

        def download(self, urls):
            downloads.extend(urls)
            output_dir = downloader.Path(self.options["outtmpl"]).parent
            (output_dir / f"Long video.{output_format}").write_bytes(b"converted media")

    monkeypatch.setattr(downloader, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(downloader, "_ffmpeg_available", lambda: True)
    options = {} if limit is None else {"max_duration_seconds": limit}
    args = ("https://youtu.be/test", tmp_path / "downloads", tmp_path / "temp")

    if accepted:
        result = convert_youtube(*args, output_format=output_format, **options)
        assert result.path.read_bytes() == b"converted media"
        assert len(downloads) == 1
    else:
        minutes = (limit if limit is not None else 14_400) // 60
        with pytest.raises(downloader.ConverterError, match=f"{minutes}-minute limit"):
            convert_youtube(*args, output_format=output_format, **options)
        assert downloads == []
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.parametrize("limit,expected", [(14_400, "240 MIN MAX"), (3_600, "60 MIN MAX"), (0, "NO DURATION LIMIT")])
def test_page_displays_configured_duration(monkeypatch, limit, expected):
    import app as webapp

    monkeypatch.setattr(webapp, "MAX_DURATION_SECONDS", limit)
    response = webapp.app.test_client().get("/")
    assert response.status_code == 200
    assert expected in response.get_data(as_text=True)


def test_worker_passes_duration_limit(monkeypatch):
    import app as webapp

    captured = {}

    def fake_convert(**kwargs):
        captured.update(kwargs)
        raise downloader.ConverterError("Stop before download")

    monkeypatch.setattr(webapp, "MAX_DURATION_SECONDS", 14_400)
    monkeypatch.setattr(webapp, "convert_youtube", fake_convert)
    webapp._run_job("test-duration", "https://youtu.be/test", "mp3")
    assert captured["max_duration_seconds"] == 14_400
