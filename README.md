# Audio Rescue

**Accessible, local-first audio downloads for Windows.**

Audio Rescue is a Python standard-library download manager for music and audio that you own or are authorized to export. It was born when an original WAV export failed in a music website’s browser interface, even though the authenticated audio endpoint returned the file.

## Features

- Batch download your Flow Music songs by song URL or ID; WAV, MP3, and M4A when available to your account.
- Download actual direct HTTPS audio-file links from other platforms.
- Advanced endpoint templates for additional services with known, permitted ID-based download APIs.
- Validate audio signatures, HTTP response length, WAV RIFF length, and SHA-256 integrity records.
- Retry temporary failures, skip verified files, preserve completed files on cancellation, and avoid overwriting uncertain older files.
- An accessible local browser UI with labeled controls and beginner instructions.

**Platform support is not universal:** A Suno/Udio/Drive sharing link is often just a player or preview page, not a downloadable audio URL. Audio Rescue does not bypass platform permissions or DRM and cannot recover original WAV quality by converting MP3. Flow Music integration uses an unofficial endpoint that may change. This project is not affiliated with Flow Music, Google, Suno, or Udio.

## Download and run (Windows)

1. Install Python 3.10+ if needed.
2. From this repository, select **Code → Download ZIP**, then **Extract All**.
3. Open the extracted folder and double-click `START-WINDOWS.bat`. Do not run it while still inside the ZIP.
4. The app opens in your browser. Leave the command window running.
5. Read the in-app Beginner Guide. Paste one song URL per line.
6. Choose the mode and format; Flow Music requires a fresh access token from **your own account**, described in the app.
7. Start the batch. Default folder: `Downloads\Audio-Rescue`.

If your browser does not open, use the `http://127.0.0.1:.../` address printed in the command window. On other operating systems, run `python audio_rescue.py` with Python 3.10+.

## Link types

| Mode | Input |
| --- | --- |
| Flow Music | Individual song URLs or IDs and a fresh account access token |
| Direct audio links | Actual HTTPS audio-file URLs, not share/player pages |
| Advanced | Known HTTPS endpoint template with `{id}` and optional `{format}` |

**Keep credentials private.** Never post access tokens, refresh tokens, cookies, signed private links, or raw request headers in GitHub issues, screenshots, or chats. The app uses access tokens in memory for the batch and only sends them to the selected authorized HTTPS hostname; it does not persist tokens in its file-integrity manifest.

## Tests

On Windows run `RUN-TESTS.bat`, or run:

```sh
python -m unittest -v test_audio_rescue
```

40 offline regression tests passed during the September 2026 v3 audit. They simulate network responses and audio bytes, **not live downloads from every platform or hands-on NVDA certification**. See `QA-REPORT.txt` for the test scope and known limitations; `README-FIRST.txt` has detailed usage and troubleshooting.

## Contributions

Bug reports, accessibility feedback, documentation improvements and pull requests are welcome. Please remove personal data and credentials from reports. See `SECURITY.md`.

## License

MIT © 2026 Suraj Paswan. See [LICENSE](LICENSE).
