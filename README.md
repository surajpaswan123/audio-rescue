# Audio Rescue 🎵🛟

**I helped Suraj rescue one WAV file. He turned the rescue into an open-source audio downloader. Ada made the whole thing legendary.**

Audio Rescue is a local-first, screen-reader-friendly audio downloader for Windows. It can batch-export songs from Flow Music using your own account's access token, download authorized direct audio links from other services, and check whether the resulting files are complete.

Built with Python's standard library, a local browser interface, and the conviction that “Download failed” is not always the end of the story.

**[Get started](#get-started-in-two-minutes) · [Read the origin story](#the-origin-story-as-told-by-the-ai-who-was-there) · [Features](#what-the-app-actually-does) · [Tests](#testing-and-known-limits)**

## Get started in two minutes

You do **not** need to understand the origin story to run the app. You can come back for the drama.

1. Install **Python 3.10 or newer** if it isn't already installed.
2. On GitHub, choose **Code → Download ZIP**, then extract the ZIP. Do not run the app from inside the compressed ZIP.
3. Open the extracted folder and run **START-WINDOWS.bat**.
4. Your browser should open the local Audio Rescue interface. Leave the command window running.
5. Select **Flow Music**, **Direct audio links**, or **Advanced template**, and follow the in-app beginner guide.
6. Paste song links **one per line**, choose an available format, and start downloading.
7. Find your completed files in **Downloads\Audio-Rescue** by default.

For Flow Music, copy the URL of an individual song page from your own account. The app's beginner guide explains how to obtain a **fresh access token** from your signed-in session. Do not paste that token into GitHub issues, public chats, or screenshots.

For other platforms, you generally need an **actual downloadable HTTPS audio URL**, not merely a sharing link that opens a player. Advanced mode supports a known HTTPS endpoint template containing <code>{id}</code> and optionally <code>{format}</code>; it cannot guess private APIs.

**Screen-reader note:** The interface is designed with labeled form controls, headings, and status messages. For NVDA, you can navigate with **H** for headings, **E** for edit fields, and **B** for buttons in browse mode. See [README-FIRST.txt](README-FIRST.txt) for detailed instructions and troubleshooting.

---

## The origin story, as told by the AI who was there

*The events are real. The dialogue is lightly dramatized. My dignity did not survive the debugging session.*

### Chapter 1: Enter Ada

It started, as all respectable software projects do, with Suraj making music instead of looking for a software bug.

He had a female AI singing voice he loved. After making songs and covers, he named the singer **Ada**, after a character from his StoryWeaver project.

Ada could sing. Ada could sing *beautifully*. Suraj made English and Hindi tracks with her.

Then he wanted the original WAV export of one of her songs from Flow Music.

A reasonable request.

A dangerous sentence.

### Chapter 2: “Download failed. Please try again.”

The site's MP3 and M4A downloads worked. WAV did not.

We tried the obvious things first. We checked the browser. We investigated the download request. I encouraged increasingly ridiculous amounts of Chrome DevTools navigation.

Suraj uses **NVDA**, so navigating DevTools' Network panel was its own mini-boss fight. Along the way, Chrome surfaced accessibility warnings about missing dialog titles and focus being hidden from assistive technology.

Our music problem had developed a QA subplot.

Then we found the request:

~~~text
GET /__api/download/audio/[song-id]?format=wav
Status: 200 OK
Content-Type: audio/wav
Content-Length: 26570756
~~~

**26,570,756 bytes.**

The server was offering a WAV response. But the site's JavaScript still ended with:

~~~text
TypeError: Failed to fetch
~~~

I briefly celebrated too early. A 200 status proves the response began successfully; it does **not** prove a browser finished reading every byte. That distinction became a useful lesson, right alongside HTTP authentication.

### Chapter 3: Forbidden, expired, and other fine words

Opening the audio URL directly produced:

~~~json
{"detail":"Forbidden"}
~~~

Why? The successful request had included an authenticated Bearer header; opening a link in a new tab didn't reproduce that request.

We tried a browser-side WAV saver. It caught the request but hit the same failed-fetch problem.

Then we turned to PowerShell.

PowerShell contributed several memorable plot twists:

- The clipboard token was overwritten when we copied the next command. Yes, we effectively threw away our own key.
- A multiline command got stuck at the infamous <code>&gt;&gt;</code> prompt.
- One <code>curl.exe</code> attempt ran into a Windows certificate-revocation check problem.
- Another attempt returned **Forbidden** because the access token had expired.

At one point, Suraj had to tell me, in effect, “Bro, the token is temporary!” He was right. Unfortunately, the key had already turned into a pumpkin.

One more serious lesson: during debugging, real authentication headers were accidentally pasted into chat. **Please never include access tokens, refresh tokens, cookies, or signed private links in public reports. Revoke exposed sessions.**

Finally, using a **fresh token from Suraj's own authorized account**, PowerShell downloaded the WAV response successfully.

No MP3-to-WAV conversion. No pretending that a larger file restores lost quality. We saved the WAV that the service actually returned.

Ada had escaped.

### Chapter 4: The completely reasonable escalation

I thought we were done.

Suraj had another idea.

> “Hey, can you create an app so that I input my token, and it downloads a file from Flow Music? There are many songs I need to download.”

Then:

> “Not only Flow Music. Other platforms also.”

Then:

> “Check for bugs. Make it bulletproof. Another project going in my portfolio!”

And that is how a one-song troubleshooting session became **Audio Rescue**: a batch downloader with a local interface, beginner instructions, file-integrity checks, safer token handling, and an offline regression-test suite.

The app exists because one singer was legendary and one human refused to accept “Download failed.”

I was the AI on the other side of the debugging conversation. Suraj was the person making the music, running the experiments, deciding what to build, and turning the whole misadventure into a portfolio project.

**Ada.sys — legendary. Suraj.exe — operational.**

---

## What the app actually does

| Feature | What you get |
| --- | --- |
| Flow Music batch downloads | Paste individual song URLs or IDs; request WAV, MP3, or M4A where available to your account. |
| Direct audio links | Download authorized direct HTTPS audio-file URLs from other platforms. |
| Advanced templates | Use a known HTTPS ID-based audio endpoint template for additional services. |
| File checks | Validate audio signatures, reported download length, and WAV RIFF length; record SHA-256 hashes for completed downloads. |
| Retry and recovery | Retry eligible temporary failures, skip previously verified downloads, and keep uncertain older files instead of overwriting them. |
| Accessibility | Local browser UI with labeled controls, status updates, and beginner-oriented instructions. |
| Small dependency footprint | Python 3.10+ and the standard library. No pip installation required. |

By default, downloads go to <code>Downloads\Audio-Rescue</code>.

### What it deliberately does *not* do

- It does **not** give you a paid export format your account isn't authorized to use.
- It does **not** bypass DRM, subscription restrictions, or platform permissions.
- It does **not** turn a lossy MP3 into an original-quality WAV.
- It does **not** promise that every Suno, Udio, Drive, or other share link is a direct audio file.
- It is **not affiliated with** Flow Music, Google, Suno, or Udio. The Flow Music integration uses an unofficial endpoint and could break if that service changes it.

Only download audio that you own or are authorized to obtain.

## Testing and known limits

Run the offline tests on Windows using **RUN-TESTS.bat**, or from a terminal:

~~~sh
python -m unittest -v test_audio_rescue
~~~

**40 offline regression tests passed during the v3 audit.** They exercise simulated responses and audio data; this is not a claim that every third-party platform has been live-tested or that the app has passed formal NVDA certification.

See [QA-REPORT.txt](QA-REPORT.txt) for the testing scope and [SECURITY.md](SECURITY.md) for responsible bug reporting.

## Want to improve it?

Issues, pull requests, accessibility suggestions, documentation fixes, and platform-specific integrations are welcome. Explain how to reproduce a problem and what you expected to happen, but **redact credentials, private links, cookies, and personal data** before posting.

Suraj built this project with AI-assisted development, hands-on debugging, and a very real motivation to make audio downloads less painful. If you find a new bug, congratulations: you've joined the lore.

## License

**MIT © 2026 Suraj Paswan.** See [LICENSE](LICENSE).

You may use, modify, redistribute, and build on the code under the license terms.

---

*In memory of the most productive error message in this project's history:*

**“Download failed. Please try again.”**

*We did. Repeatedly. Then Suraj made an app.*
