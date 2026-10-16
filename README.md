# CyberAcme YouTube → MP3 / MP4

[![Tests](https://github.com/schady23/cyberacme_yt2mp3-4/actions/workflows/tests.yml/badge.svg)](https://github.com/schady23/cyberacme_yt2mp3-4/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A self-hosted Flask application that saves a single YouTube video as MP3 audio or MP4 video. Download the full video or an exact section, edit the file's title and music tags, and follow progress through a CyberAcme-inspired interface with a cursor-following, dithered hologram.

Files are saved in `downloads/` on the machine running the app and can also be downloaded through the browser. The app runs on Windows, macOS, and Linux. It binds to localhost by default; [Linux Mint hosting instructions](docs/linux-mint.md) cover running it on a trusted home network.

Use it only for media you own or are authorized to download.

## Requirements

- Python 3.10+
- Git to clone the repository, or use GitHub's **Code → Download ZIP**
- FFmpeg **and ffprobe** available on your `PATH`
- Internet access while converting
- Deno (recommended) or Node.js 22+ on `PATH` for YouTube's JavaScript challenges. The app enables either automatically.

`yt-dlp` uses FFmpeg/ffprobe for audio extraction and conversion.

Install a current [Deno release](https://docs.deno.com/runtime/getting_started/installation/) or a supported Node.js release before downloading from YouTube. The project's `yt-dlp[default]` dependency includes the companion JavaScript challenge scripts. No YouTube credentials or API keys are needed for public, accessible videos.

## Get the project

```bash
git clone https://github.com/schady23/cyberacme_yt2mp3-4.git
cd cyberacme_yt2mp3-4
```

## Setup

### macOS

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

### Windows

Install FFmpeg and make sure `ffmpeg.exe` and `ffprobe.exe` are on `PATH`, then in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

### Linux (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5000
```

The server intentionally binds only to `127.0.0.1`.

To launch again on Windows without activating the environment:

```powershell
cd path\to\cyberacme_yt2mp3-4
.\.venv\Scripts\python.exe app.py
```

## Download a section

1. Paste a YouTube URL and choose MP3 or MP4.
2. Optionally click **Load** to load the title, source length, and draggable trim handles.
3. Choose **Section**. Enter the start and end times, or drag the IN and OUT handles after loading the source.
4. Click **Extract MP3** or **Extract MP4**. The live duration shows how much media will be saved.

For two minutes from an hour-long video, enter **46:00** as the start and **48:00** as the end. Times accept seconds (`2760`), `MM:SS` (`46:00`), or `HH:MM:SS` (`00:46:00`), with up to three decimal places for seconds. Quick buttons set the end 30 seconds, one minute, or two minutes after your start time.

The output filename includes the selected range. Both endpoints are required; the end must follow the start and fit within the video. Sections require a finished video with a known length. FFmpeg extracts the requested range, and video cuts are re-encoded for accurate boundaries. Some source formats may still require extra data to be transferred or processed. Switch back to **Full** to download the entire video.

The CyberAcme-themed interface has a large ONI-style holographic head behind a translucent control panel. A deliberately low-resolution, color-preserving ordered-dither point cloud adds soft depth and cursor tracking. Blurred cobalt monitor shapes form the background. Rendering stops when the pose settles or the tab is hidden. Use **Motion** to pause the effect; reduced-motion system preferences are respected. The PNG remains as a static fallback if canvas is unavailable. All extraction controls also work with a keyboard or touch. See [NOTICE.md](NOTICE.md) for the background's provenance and third-party rights.

The main controls are centered in a large translucent panel with hard right-angle corners and square controls. Decorative code, memory dumps, and spectrum readouts wrap around both sides like an inverse CRT. These feeds are generated visual effects; they do not read local files or run code. The Motion toggle pauses their updates together with the head. Side feeds are hidden on narrower screens to keep the controls usable.

## Set the file name and tags

Enter **Title / file name** and **Artist** under **File details** before extracting. Open **More metadata** for album, album artist, genre, year, track, disc, composer, and comment. All fields are optional; blank fields keep the available source tags. Year accepts four digits; track and disc accept a positive number or a number/total such as `3/12`.

Your title becomes the embedded title and the output filename. File names replace characters Windows cannot use; section downloads still include their selected range and duplicate names receive a numbered suffix. Tags are written into the final MP3 or MP4 after conversion and trimming. Adding tags copies the encoded media without another quality-changing conversion.

## FFmpeg HTTP 403 errors

The Windows exit code `3436169992` corresponds to FFmpeg's HTTP 403 error: the remote server rejected the media request. The app enables installed Deno/Node challenge runtimes and includes yt-dlp's official challenge solver dependency. If a direct section request fails, the app retries using yt-dlp's native downloader, then cuts the downloaded file locally. This fallback downloads the full source and may take longer; the progress panel explains the retry. Private or otherwise inaccessible videos can still fail.

Update the downloader and its companion scripts together:

```powershell
.\.venv\Scripts\python.exe -m pip install -U "yt-dlp[default]"
```

## Configuration

Outputs up to 4 hours (240 minutes, 14,400 seconds) are supported by default for both MP3 and MP4. For full downloads the limit applies to the source length; for sections it applies to the selected duration, so short clips from longer videos are allowed. Change the limit with `MAX_DURATION_SECONDS` before starting the app. Set it to `0` to disable the duration limit. Restart the app after changing the limit; an existing environment override still takes precedence.

macOS/Linux example:

```bash
MAX_DURATION_SECONDS=3600 python app.py
```

PowerShell example:

```powershell
$env:MAX_DURATION_SECONDS=3600
python app.py
```

## Features

- Single-video YouTube URLs only
- YouTube-domain validation
- Best available source-audio selection
- MP3 audio or MP4 video output with FFmpeg
- Optional timestamp sections with source inspection and draggable trim controls
- Editable file title, artist, album, album artist, genre, year, track, disc, composer, and comment for MP3 and MP4
- Local progress display
- Isolated temporary folders and automatic cleanup
- Cross-platform filename sanitization
- Duplicate-filename handling
- Local `downloads/` output directory

## Notes

- Converting a lossy YouTube audio stream to MP3 does not increase its underlying fidelity, even when a high MP3 quality setting is used.
- Private, age-restricted, region-restricted, or otherwise unavailable videos may fail. The app does not import browser cookies.
- Finished downloads stay on the server until you remove them. Downloaded media, temporary files, local credentials, and the original visual reference are excluded from Git.
- The app has no authentication, download quotas, or durable job queue. Use it locally or on a trusted home network. The hosting guide uses one Gunicorn worker because job progress is held in process memory. Restarting the server interrupts active jobs and clears their status; completed files remain on disk.
- YouTube changes periodically. Keeping `yt-dlp` current is often necessary:

```bash
python -m pip install -U "yt-dlp[default]"
```

## Tests

The included tests cover URL, timestamp, and metadata validation, output formats, duration limits, API jobs, and real FFmpeg section extraction and metadata embedding using generated local fixtures (no YouTube download needed). To run them:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions runs the tests with FFmpeg on Linux using Python 3.10 and 3.13, and checks JavaScript syntax. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## Project layout

```text
app.py                    Flask pages, conversion jobs, and download endpoints
downloader.py             YouTube validation, conversion, trimming, and metadata
templates/                HTML interface
static/                   Styles, JavaScript, and background asset
tests/                    Validation, API, and real-media integration tests
docs/linux-mint.md        Home-network hosting and systemd setup
deploy/yt2mp3.service     Example Linux service
downloads/                Saved media (ignored by Git)
temp/                     Per-job working files (ignored by Git)
```

## License

The software is available under the [MIT license](LICENSE): free to use, modify, share, and use commercially, with the copyright and license notice retained. Third-party dependencies and pre-existing visual references retain their own rights; see [NOTICE.md](NOTICE.md). The software license does not grant permission to download someone else's media.
