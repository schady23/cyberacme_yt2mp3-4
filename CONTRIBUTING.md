# Contributing

Bug reports and pull requests are welcome.

1. Fork the repository and create a branch for your change.
2. Follow the setup instructions in [README.md](README.md), including FFmpeg and ffprobe.
3. Install development dependencies with `python -m pip install -r requirements-dev.txt`.
4. Run `python -m pytest -q`. For frontend changes, also check the interface in a browser with keyboard navigation and Motion turned off. JavaScript syntax can be checked with `node --check static/app.js`, `node --check static/oni.js`, and `node --check static/crt.js`.
5. Explain the behavior changed and how you checked it in the pull request.

Tests use generated local media and do not download videos from YouTube. Keep tests reproducible and avoid credentials, cookies, downloaded media, and machine-specific paths in commits. FFmpeg tests are skipped if FFmpeg or ffprobe is missing, so install both when changing conversion behavior.

For a conversion bug, include the output format, optional start/end times, runtime versions, and relevant error text. Remove tokens, signed media URLs, cookies, and personal paths from logs before sharing them. A public video URL is useful when you are comfortable sharing it.

Contributions are made under the project's [MIT license](LICENSE). See [NOTICE.md](NOTICE.md) for visual references and third-party rights.
