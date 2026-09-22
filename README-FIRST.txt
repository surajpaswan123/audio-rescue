AUDIO RESCUE 3.0 - START HERE
============================

A local, screen-reader-friendly audio download manager for your own songs
and permitted audio files. Windows 10/11, Python 3.10+, no pip installs.

QUICK START
-----------
1. Right-click the ZIP and choose Extract All. Do not run it inside the ZIP.
2. Open the extracted folder and double-click START-WINDOWS.bat.
3. The app opens in your browser. Leave its command window running.
4. Select Flow Music, Direct audio links, or Advanced template.
5. Paste song URLs one per line. Optional: Song title | https://link
6. For Flow Music, add your own fresh access token using the in-app guide.
7. Press Start downloading. The default folder is Downloads\Audio-Rescue.

FLOW MUSIC LINKS AND TOKENS
---------------------------
Open an individual song on flowmusic.app. Press Alt+D, Ctrl+C to copy its
song-page link, then paste it into the app. Repeat for multiple songs.
The in-app token guide contains instructions for copying your own short-lived
access token from your signed-in Chrome session. Never share the token, session
cookies, or screenshots of request headers. You should never need to copy
refresh tokens. If a token is rejected or expires, sign in and get a fresh
one; completed files are not removed. The app accepts WAV, MP3 or M4A when
Flow Music supplies them to your account.

OTHER PLATFORMS
---------------
Direct audio links mode accepts direct HTTPS audio files, including signed
links where you are authorized to use them. Ordinary Suno/Udio/Drive share
links may lead to a song page or preview, not to the downloadable file.
Use the site's official Download/Export control first. Advanced template
mode requires an actual known HTTPS endpoint, not a guessed endpoint.
The app does not bypass subscription limits or convert MP3 to original WAV.

WHAT CHANGED IN 3.0
-------------------
- Fixed a real local web-server deadlock when Start was pressed twice.
- Corrected AAC/MP3 format recognition.
- Retries incomplete downloads, uses limited backoff, honors numeric
  Retry-After response headers up to 60 seconds, and stops on rejected auth.
- Verifies file signatures, stated byte length, and RIFF WAV size.
- Uses SHA-256 records for files it downloaded, so valid repeats are
  skipped and corrupted/uncertain files are kept while a numbered new
  copy is downloaded. Older intact RIFF WAV downloads can also be skipped.
- Never overwrites an existing audio file during normal single-instance use.
- Uses unique temporary files and removes them after failure/cancel.
- Limits downloads to 2 GiB per file and 200 links per batch.
- Only sends Bearer tokens to their designated HTTPS host; blocks
  redirects to other hosts and insecure HTTP URLs.
- Rejects cross-origin writes to the local API and binds to 127.0.0.1.
- Detects near-expired JWT tokens when an expiration claim exists.
- Updated Windows launcher to require Python 3.10+ gracefully.

PRIVACY
-------
Runs locally. Access tokens are used in memory during a batch, not written
into download logs or saved settings. The hidden file named
.audio_rescue_manifest.json in the download folder contains filenames,
source URL hashes, byte counts, and SHA-256 file hashes; no access tokens,
refresh tokens or source URLs. Clear your clipboard after pasting a token.
Don't share private download links or credentials in bug reports.

NVDA KEYBOARD TIPS
------------------
Press H for headings, E for edit fields, B for buttons, and F for form
controls in browse mode. Chrome downloads: Ctrl+J. A screen-reader-only
review of label/landmark markup is not a substitute for hands-on testing
with NVDA on a real Windows installation.

TROUBLESHOOTING
---------------
- Forbidden: copy a fresh token; ensure that account can export the format.
- Received webpage, not audio: use a direct file link, not a sharing page.
- Incomplete audio: the app retries three times then reports failure.
- Existing file changed/corrupted: app keeps it and downloads (2), etc.
- App did not open browser: look for the local http://127.0.0.1 URL in the
  command window and open it manually.
- A batch stopped: paste links again; verified completed files are skipped.
- Windows/antivirus blocked the script: inspect source code; don't disable
  system protections simply to run the app.

To stop one batch use Stop downloading. To exit the app, focus the command
window and press Ctrl+C; closing the browser tab alone does not stop it.

TESTS AND SOURCE
----------------
All implementation source is in audio_rescue.py; no third-party packages.
RUN-TESTS.bat runs the offline test suite on Windows. To run manually:
python -m unittest -v test_audio_rescue

The tests use artificial WAV bytes and simulated HTTP responses: they do
not contact Flow Music, Suno, Udio, or other outside services. Live exports
and NVDA interaction should be tested on the user's own Windows computer.
The Flow Music download endpoint is unofficial and may change.
