#!/usr/bin/env python3
"""Audio Rescue: local-only, accessible multi-site audio download utility. Python stdlib."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION = "3.0.0"
DOWNLOADS = Path.home() / "Downloads" / "Audio-Rescue"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FILE_TYPES = {"wav", "mp3", "m4a", "flac", "ogg", "aac", "mp4"}
CT_EXT = {"audio/wav":"wav", "audio/x-wav":"wav", "audio/wave":"wav", "audio/vnd.wave":"wav",
          "audio/mpeg":"mp3", "audio/mp3":"mp3", "audio/mp4":"m4a", "audio/x-m4a":"m4a",
          "audio/flac":"flac", "audio/x-flac":"flac", "audio/ogg":"ogg", "application/ogg":"ogg",
          "audio/aac":"aac", "video/mp4":"mp4"}
RETRYABLE = {429, 500, 502, 503, 504}
MAX_ENTRIES = 200
MAX_BODY = 256 * 1024
MAX_AUDIO = 2 * 1024 * 1024 * 1024  # avoid filling a disk from an accidental endless response
MAX_URL = 8192
MAX_TOKEN = 16000


def clean_name(s: str) -> str:
    s = BAD_NAME.sub("_", s).strip().rstrip(". ")
    s = re.sub(r"[\u202a-\u202e\u2066-\u2069]", "", s)  # invisible bidirectional filename controls
    s = re.sub(r"\s+", " ", s)[:115].strip(". ")
    if not s or s.upper().split('.')[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1,10)), *(f"LPT{i}" for i in range(1,10))}:
        return "Audio"
    return s


def hostname(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password:
            return ""
        return p.hostname.lower()
    except ValueError:
        return ""


@dataclass(frozen=True)
class Item:
    url: str
    label: str
    file_id: str
    fmt: str | None
    referer: str = ""
    flow: bool = False


def parse_lines(raw: str) -> list[tuple[str, str, int]]:
    result = []
    for n, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if '|' in line:
            title, value = (part.strip() for part in line.rsplit('|', 1))
        else:
            title, value = '', line
        if not value:
            raise ValueError(f"Line {n}: the link or ID is missing.")
        result.append((title, value, n))
    if not result:
        raise ValueError("Paste at least one song link or direct audio URL.")
    if len(result) > MAX_ENTRIES:
        raise ValueError(f"Maximum {MAX_ENTRIES} links in one batch.")
    return result


def flow_id(value: str) -> str:
    if UUID_RE.fullmatch(value):
        return value.lower()
    parsed = urllib.parse.urlsplit(value)
    if hostname(value) not in {"flowmusic.app", "www.flowmusic.app"}:
        return ""
    match = re.fullmatch(r"/(?:song|__api/download/audio)/([0-9a-fA-F-]{36})/?", parsed.path)
    return match.group(1).lower() if match and UUID_RE.fullmatch(match.group(1)) else ""


def make_items(mode: str, raw: str, fmt: str, template: str) -> list[Item]:
    result = []
    seen: set[str] = set()
    if len(raw) > MAX_BODY: raise ValueError("Song list is too long.")
    if mode == 'flow' and fmt not in {'wav', 'mp3', 'm4a'}:
        raise ValueError("Flow Music format must be WAV, MP3 or M4A.")
    if mode == 'template':
        if len(template) > MAX_URL or '{id}' not in template or not hostname(template.replace('{id}', 'example').replace('{format}', 'wav')):
            raise ValueError("Advanced mode needs an HTTPS audio URL template containing {id}.")
        if re.findall(r'\{(.*?)\}', template).count('id') != 1 or any(x not in {'id', 'format'} for x in re.findall(r'\{(.*?)\}', template)):
            raise ValueError("Use {id} once and optionally {format} in the template.")
        if fmt not in FILE_TYPES:
            raise ValueError("Select an audio format for advanced mode.")
    for title, value, line in parse_lines(raw):
        if len(value) > MAX_URL: raise ValueError(f"Line {line}: URL or ID is too long.")
        referer = ""
        if mode == 'flow':
            ident = flow_id(value)
            if not ident:
                raise ValueError(f"Line {line}: not a valid Flow Music song link or song ID.")
            url = f"https://www.flowmusic.app/__api/download/audio/{ident}?format={fmt}"
            referer = f"https://www.flowmusic.app/song/{ident}"
            label = clean_name(title) if title else ident
            item = Item(url, label, ident, fmt, referer, True)
        elif mode == 'direct':
            if not hostname(value):
                raise ValueError(f"Line {line}: enter an HTTPS *direct file link*. Song pages are not audio files.")
            url = value
            key = hashlib.sha256(url.encode()).hexdigest()[:12]
            pathbase = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name
            base = re.sub(r'\.(?:wav|mp3|m4a|flac|ogg|aac|mp4)$', '', pathbase, flags=re.I)
            label = clean_name(title or base or 'Audio')
            item = Item(url, label, key, None)
        elif mode == 'template':
            # Accept IDs, or full song pages whose final path part is the ID.
            if value.startswith('https://'):
                if not hostname(value):
                    raise ValueError(f"Line {line}: invalid HTTPS song link.")
                ident = urllib.parse.unquote(urllib.parse.urlsplit(value).path.rstrip('/').split('/')[-1])
                referer = value
            else:
                ident = value
            if not re.fullmatch(r'[A-Za-z0-9_-]{4,128}', ident):
                raise ValueError(f"Line {line}: could not identify a song ID at the end of this link. Advanced mode needs an ID ending the URL.")
            url = template.replace('{id}', urllib.parse.quote(ident, safe='')).replace('{format}', fmt)
            if not hostname(url):
                raise ValueError(f"Line {line}: generated audio URL is not a valid HTTPS link.")
            label = clean_name(title or ident)
            item = Item(url, label, hashlib.sha256(url.encode()).hexdigest()[:12], fmt, referer)
        else:
            raise ValueError("Choose a supported platform mode.")
        if item.url not in seen:
            result.append(item)
            seen.add(item.url)
    return result


@dataclass
class Job:
    status: str = 'idle'
    directory: str = str(DOWNLOADS)
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    current: str = ''
    bytes_done: int = 0
    bytes_total: int = 0
    message: str = 'Ready.'
    results: list[dict[str,str]] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)

job = Job()
lock = threading.Lock()


def report(**k: Any) -> None:
    with lock:
        for key, value in k.items():
            setattr(job, key, value)


def snapshot() -> dict[str, Any]:
    with lock:
        keys = ('status','directory','total','done','skipped','failed','current','bytes_done','bytes_total','message')
        return {key:getattr(job,key) for key in keys} | {'results':list(job.results)}


def result(name: str, status: str, reason: str) -> None:
    with lock:
        job.results.append({'name':name,'status':status,'detail':reason})
        setattr(job, {'Downloaded':'done','Skipped':'skipped','Failed':'failed'}[status], getattr(job, {'Downloaded':'done','Skipped':'skipped','Failed':'failed'}[status])+1)


class DownloadError(Exception): pass
class AuthorizationError(DownloadError): pass
class StoppedError(DownloadError): pass
class IncompleteDownload(DownloadError): pass


class RedirectGuard(urllib.request.HTTPRedirectHandler):
    def __init__(self, authorized_host: str):
        self.authorized_host = authorized_host
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.authorized_host and hostname(newurl) != self.authorized_host:
            raise DownloadError('Download redirected to another site; no token was forwarded. Use a direct link on that site without this token.')
        if not hostname(newurl):
            raise DownloadError('Download redirected to a non-HTTPS URL; refused.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def detect_format(header: bytes, ctype: str, url: str, desired: str | None) -> str:
    if header[:4] == b'RIFF' and header[8:12] == b'WAVE': return 'wav'
    if header[:4] == b'RF64' and header[8:12] == b'WAVE': return 'wav'
    if header[:4] == b'fLaC': return 'flac'
    if header[:4] == b'OggS': return 'ogg'
    if len(header)>=12 and header[4:8]==b'ftyp':
        return 'mp4' if desired == 'mp4' or 'video/mp4' in ctype else 'm4a'
    if header[:3] == b'ID3': return 'mp3'
    if len(header)>=2 and header[0]==0xff and header[1]&0xf0==0xf0 and header[1]&0x06==0: return 'aac'
    if len(header)>=2 and header[0]==0xff and header[1]&0xe0==0xe0 and header[1]&0x06: return 'mp3'
    return ''


def token_is_expired(token: str) -> bool:
    """Only decode the public expiration claim; no signature/permissions validation."""
    try:
        parts = token.split('.')
        if len(parts) != 3: return False  # opaque provider token
        body=parts[1].replace('-','+').replace('_','/')
        body+='='*((-len(body))%4)
        obj=json.loads(base64.b64decode(body))
        exp=obj.get('exp')
        return isinstance(exp,(int,float)) and not isinstance(exp,bool) and exp < time.time()+45
    except (ValueError,UnicodeError,TypeError):
        return False


def dest_path(folder: Path, item: Item, fmt: str) -> Path:
    base = f'{item.label} [{item.file_id}]' if item.label != item.file_id else item.file_id
    return folder / f'{base}.{fmt}'


def manifest_path(folder: Path) -> Path:
    return folder / '.audio_rescue_manifest.json'


def manifest_load(folder: Path) -> dict:
    try:
        obj = json.loads(manifest_path(folder).read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def manifest_save(folder: Path, obj: dict) -> None:
    # No tokens, cookies or original signed URLs are written here.
    temp = folder / f'.audio_rescue_manifest_{secrets.token_hex(8)}.tmp'
    try:
        temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, manifest_path(folder))
    finally:
        temp.unlink(missing_ok=True)


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        while block := fh.read(1024*1024):
            h.update(block)
    return h.hexdigest()


def valid_existing(path: Path, item: Item, fmt: str, meta: dict | None) -> bool:
    try:
        size = path.stat().st_size
        if size <= 44 or size > MAX_AUDIO: return False
        with path.open('rb') as fh: header = fh.read(32)
        if detect_format(header, '', item.url, fmt) != fmt: return False
        if isinstance(meta, dict):
            return (meta.get('source') == hashlib.sha256(item.url.encode()).hexdigest()
                    and meta.get('size') == size and meta.get('sha256') == file_digest(path))
        # Legacy WAV: the RIFF header gives us a trustworthy length check.
        if fmt == 'wav' and header[:4] == b'RIFF':
            declared = int.from_bytes(header[4:8], 'little') + 8
            return declared >= 44 and declared == size
        return False
    except (OSError, ValueError, TypeError):
        return False


def unused_path(target: Path) -> Path:
    if not target.exists(): return target
    for n in range(2, 10001):
        proposal = target.with_name(f'{target.stem} ({n}){target.suffix}')
        if not proposal.exists(): return proposal
    raise DownloadError('Too many files with the same name in the selected folder.')


def download_one(item: Item, folder: Path, token: str, auth_host: str, cancel: threading.Event) -> tuple[str,str]:
    if token and hostname(item.url) != auth_host:
        raise DownloadError('Token not sent: download hostname differs from the chosen authorized hostname.')
    manifest = manifest_load(folder)
    if item.fmt:
        target = dest_path(folder,item,item.fmt)
        if target.is_file() and valid_existing(target,item,item.fmt,manifest.get(target.name)):
            return 'Skipped', ('Existing audio passed SHA-256 integrity checks.' if manifest.get(target.name) else 'Existing WAV passed RIFF header and length checks (no previous hash record).')
    headers = {'Accept':'audio/*,application/octet-stream;q=0.8,*/*;q=0.3',
               'Accept-Encoding':'identity',
               'User-Agent':('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36' if item.flow else 'AudioRescue/3.0 (local personal backup utility)')}
    if token: headers['Authorization'] = 'Bearer ' + token
    if item.referer and hostname(item.referer) == hostname(item.url): headers['Referer'] = item.referer
    opener = urllib.request.build_opener(RedirectGuard(auth_host if token else ''))
    part = folder / ('.audio_rescue_' + secrets.token_hex(12) + '.part')
    try:
        for attempt in range(3):
            try:
                if cancel.is_set(): raise StoppedError('Stopped by user.')
                request = urllib.request.Request(item.url, headers=headers)
                with opener.open(request, timeout=40) as resp:
                    ct = resp.headers.get('Content-Type','').lower().split(';')[0].strip()
                    length = resp.headers.get('Content-Length','0') or '0'
                    try: advertised = int(length)
                    except (ValueError,TypeError): raise DownloadError('Server returned an invalid Content-Length header.') from None
                    if advertised < 0 or advertised > MAX_AUDIO:
                        raise DownloadError('Audio exceeds the 2 GiB per-file safety limit.')
                    if ct in {'text/html','application/json','text/plain','application/xml'}:
                        raise DownloadError('Link returned a webpage or error message, not audio. Copy the actual file link.')
                    if resp.status == 206 or resp.headers.get('Content-Range'):
                        raise DownloadError('The server returned only a partial response; full audio is required.')
                    report(bytes_done=0, bytes_total=advertised)
                    n=0; prefix=b''; digest=hashlib.sha256()
                    with part.open('wb') as out:
                        while True:
                            if cancel.is_set(): raise StoppedError('Stopped by user.')
                            block=resp.read(128*1024)
                            if not block: break
                            if len(prefix)<32: prefix += block[:32-len(prefix)]
                            n+=len(block)
                            if n > MAX_AUDIO:
                                raise DownloadError('Audio exceeds the 2 GiB per-file safety limit.')
                            out.write(block); digest.update(block)
                            report(bytes_done=n)
                    if advertised and n!=advertised:
                        raise IncompleteDownload(f'Incomplete audio: {n:,} of {advertised:,} bytes.')
                    identified=detect_format(prefix,ct,item.url,item.fmt)
                    if not identified:
                        raise DownloadError('Received bytes do not resemble a supported audio file.')
                    if item.fmt and identified!=item.fmt:
                        raise DownloadError(f'Site returned {identified.upper()}, not the requested {item.fmt.upper()}. No format conversion performed.')
                    if identified == 'wav' and prefix[:4] == b'RIFF':
                        declared = int.from_bytes(prefix[4:8],'little') + 8
                        if declared > n or declared < 44:
                            raise IncompleteDownload('WAV header indicates a truncated or invalid file.')
                    target=dest_path(folder,item,identified)
                    if target.is_file() and valid_existing(target,item,identified,manifest.get(target.name)):
                        return 'Skipped', ('Existing audio passed SHA-256 integrity checks.' if manifest.get(target.name) else 'Existing WAV passed RIFF header and length checks (no previous hash record).')
                    target=unused_path(target)
                    os.replace(part,target)
                    manifest[target.name] = {'source':hashlib.sha256(item.url.encode()).hexdigest(),
                                             'size':n,'sha256':digest.hexdigest()}
                    try:
                        manifest_save(folder,manifest)
                    except OSError:
                        return 'Downloaded', f'{target.name} — {n:,} bytes (warning: could not save local integrity record)'
                    return 'Downloaded', f'{target.name} — {n:,} bytes'
            except IncompleteDownload as e:
                if attempt < 2 and not cancel.is_set():
                    report(message=f'Audio was incomplete; retrying {item.label}...')
                    if cancel.wait(2**attempt): raise StoppedError('Stopped by user.')
                    continue
                raise
            except urllib.error.HTTPError as e:
                if e.code in {401,403}:
                    if token: raise AuthorizationError(f'HTTP {e.code}: token expired, lacks permission, or site requires other authentication.') from None
                    raise DownloadError(f'HTTP {e.code}: this file requires access or the link has expired.') from None
                if e.code in RETRYABLE and attempt<2:
                    report(message=f'Temporary HTTP {e.code}; retrying {item.label}...')
                    try: wait = min(60,max(1,int((e.headers or {}).get('Retry-After','') or 0)))
                    except (ValueError,TypeError): wait = 2**attempt
                    if cancel.wait(wait): raise StoppedError('Stopped by user.')
                    continue
                raise DownloadError(f'HTTP {e.code}: server refused the download.') from None
            except (urllib.error.URLError,TimeoutError,socket.timeout,ConnectionError,http.client.IncompleteRead,OSError) as e:
                if attempt<2 and not cancel.is_set():
                    report(message=f'Connection issue; retrying {item.label}...')
                    if cancel.wait(2**attempt):raise StoppedError('Stopped by user.')
                    continue
                if cancel.is_set():raise StoppedError('Stopped by user.') from None
                raise DownloadError(f'Connection or file error ({type(e).__name__}).') from None
            finally:
                part.unlink(missing_ok=True)
        raise DownloadError('Retries exhausted.')
    finally:
        part.unlink(missing_ok=True)


def do_batch(items: list[Item], folder: Path, token: str, auth_host: str, cancel: threading.Event) -> None:
    try:
        folder.mkdir(parents=True,exist_ok=True)
        for idx,item in enumerate(items,1):
            if cancel.is_set():report(status='stopped',message='Stopped. Finished files were kept.');return
            report(current=f'{idx} of {len(items)}: {item.label}',message=f'Downloading {item.label}...',bytes_done=0,bytes_total=0)
            try:
                status,why=download_one(item,folder,token,auth_host,cancel)
                result(item.label,status,why)
            except StoppedError:
                report(status='stopped', current='', message='Stopped by user. Completed audio kept; partial file removed.')
                return
            except AuthorizationError as e:
                result(item.label,'Failed',str(e))
                report(status='stopped',current='',message='Authorization rejected. Sign in again and supply a fresh token for this platform. Already completed files remain saved.')
                return
            except DownloadError as e:
                result(item.label,'Failed',str(e))
            except Exception as e:
                result(item.label,'Failed',f'Unexpected {type(e).__name__}; see the file or folder permissions.')
        s=snapshot()
        report(status='done',current='',bytes_done=0,bytes_total=0,
               message=f"Finished: {s['done']} downloaded, {s['skipped']} skipped, {s['failed']} failed. Folder: {folder}")
    except OSError:
        report(status='stopped',message='Cannot create or write to this folder. Try your normal Downloads folder.')
    finally:
        token=''


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audio Rescue — multi-platform audio downloader</title>
<style>
:root{font:100%/1.6 system-ui,Segoe UI,Arial,sans-serif;color-scheme:light dark}
body{max-width:830px;margin:1rem auto;padding:0 1rem}h1,h2,h3{line-height:1.25}p{margin:.5rem 0 1rem}
label{display:block;font-weight:650;margin:.9rem 0 .2rem}input,select,textarea,button{font:inherit;box-sizing:border-box}
input,select,textarea{width:100%;padding:.55rem;border:1px solid #777;border-radius:.3rem}
textarea{min-height:10rem}button{padding:.7rem 1.1rem;margin:.6rem .7rem .6rem 0;cursor:pointer}
:focus-visible{outline:3px solid #2178dc;outline-offset:3px}small{display:block;margin:.2rem 0 .6rem}
.notice{border-left:4px solid #777;padding:.7rem 1rem;background:rgba(127,127,127,.12)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;border:1px solid #777}progress{width:100%;height:1.3rem}
li{margin:.5rem 0}details{margin:1rem 0}summary{cursor:pointer;font-weight:600}#results{padding-left:1.5rem}
</style></head><body><main>
<h1>Audio Rescue</h1><p><strong>Save your own songs and permitted audio files from different platforms.</strong> Accessible with NVDA, TalkBack and ordinary browsers. Runs on your computer, not an upload service.</p>
<p class="notice">Select <strong>Flow Music</strong> for Flow Music song links; <strong>Direct audio links</strong> for files from other sites; or <strong>Advanced template</strong> for sites with a known direct download URL pattern. This app cannot turn every sharing page into an audio file, remove download limits, or unlock a format your account does not have.</p>
<nav aria-label="Page sections"><a href="#guide">Beginner guide</a> · <a href="#downloader">Downloader</a> · <a href="#token-guide">Token instructions</a> · <a href="#other-sites">Other platforms</a></nav>
<section id="guide"><h2>Start here — no technical experience needed</h2><ol>
<li>Open the song on its original website. For Flow Music, the browser address is enough. For another site, look for its <strong>Download</strong> or <strong>Export</strong> menu.</li>
<li>Copy a link: for Flow Music, press <kbd>Alt+D</kbd> then <kbd>Ctrl+C</kbd> on the song page. For another site, use <strong>Copy link address</strong> on an actual audio download link; a Share link normally leads to a webpage, not to WAV audio.</li>
<li>Return here. Select the correct mode, then paste song links into the big box, <strong>one per line</strong>. Give each a name using <code>Song title | https://...</code> if you want.</li>
<li>For Flow Music only, follow the <a href="#token-guide">token guide</a> and paste a fresh access token. This is not your account password. Never paste it into chats, email or screenshots.</li>
<li>Choose WAV when your account offers original WAV, then press <strong>Start downloading</strong>. Keep the black command window open until the batch finishes.</li>
<li>Open <strong>Downloads\Audio-Rescue</strong> in File Explorer to find your files. The results section below also tells you each filename.</li>
</ol><p><strong>NVDA tips:</strong> press H to move among headings, E for edit boxes, B for buttons, F for form fields. Chrome downloads: Ctrl+J. If a website’s download control is an unlabeled button, the website may have an accessibility bug; the song-page link is easier on Flow Music.</p></section>
<section id="downloader"><h2>Downloader</h2><form id="download-form">
<label for="mode">1. Platform / link type</label>
<select id="mode"><option value="flow">Flow Music — song links or IDs</option><option value="direct">Other platforms — direct audio file links</option><option value="template">Advanced — site-specific audio URL template</option></select>
<small id="mode-help">Flow Music mode understands ordinary song-page links. Direct mode needs the actual audio file URL, not the page you listen on.</small>
<div id="format-area"><label for="format">2. Requested audio format</label><select id="format"><option value="wav">WAV — original file, if available</option><option value="mp3">MP3</option><option value="m4a">M4A</option><option value="flac">FLAC</option><option value="ogg">OGG</option><option value="aac">AAC</option><option value="mp4">MP4</option></select><small>Direct-file mode detects the actual file type. It does not convert or upgrade compressed files into masters.</small></div>
<div id="advanced-area" hidden><label for="template">Advanced: actual audio URL template</label><input id="template" autocomplete="off" spellcheck="false" placeholder="https://audio.example.com/download/{id}?format={format}"><small>Use only a URL pattern documented or observed for a service you use. Put {id} where its song ID goes; {format} is optional. The ID must be the final part of a song link, or you can paste IDs alone. Do not guess private endpoints.</small></div>
<label for="urls">3. Songs or file links — one per line</label><textarea id="urls" spellcheck="false" required placeholder="https://www.flowmusic.app/song/cc83430c-be31-4350-bcd7-5561794fede6&#10;Ada - Still Here | https://www.flowmusic.app/song/another-song-id"></textarea>
<small>Optional naming: <code>My song | https://example.com/download/song.wav</code>. Maximum 200 per batch; duplicate links are ignored.</small>
<label for="token">4. Access token (only if needed)</label><input id="token" type="password" autocomplete="off" spellcheck="false" aria-describedby="token-help">
<small id="token-help">Required for Flow Music. For other platforms, leave blank unless you have a token authorized for that platform's file host. In Flow Music mode, tokens go only to www.flowmusic.app. For other modes, choose the correct provider hostname; never reuse a Flow Music token on another site.</small>
<div id="host-area" hidden><label for="host">Site allowed to receive this token (hostname only)</label><input id="host" placeholder="audio.example.com" autocomplete="off" spellcheck="false"><small>Needed only when using a token with direct links or an advanced template. All download links must use this exact hostname; the token will not follow redirects to another site.</small></div>
<label for="folder">5. Save folder on your computer</label><input id="folder" value="__DOWNLOADS__"><small>Leave unchanged to save to Downloads\Audio-Rescue. Existing files are never overwritten. Verified copies are skipped; uncertain existing files get a new numbered filename.</small>
<button type="submit" id="start">Start downloading</button><button type="button" id="stop" disabled>Stop downloading</button></form>
<h2>Download progress</h2><p role="status" aria-live="polite" aria-atomic="true" id="message">Ready.</p><p id="current"></p><progress id="bar" max="1" value="0" aria-label="Current file download progress"></progress><p id="counts"></p>
<h2>Results and saved filenames</h2><ol id="results" aria-label="Completed and failed downloads"></ol></section>
<section id="token-guide"><h2>How to get your Flow Music access token</h2>
<p>Only for your own account. A temporary token is like a temporary password: keep it private and use a fresh one if it expires. The app checks a JWT expiration time before starting when available. This app stores it in memory during downloads, not in a saved settings file.</p>
<ol><li>Sign in at <strong>www.flowmusic.app</strong> and open a song. The browser address should include <code>/song/</code>.</li>
<li>Press <kbd>Ctrl+Shift+J</kbd> in Chrome to open the Console. NVDA users: you do not need to navigate the Network panel.</li>
<li>Read the short code below. If Chrome refuses pasting, you can type <code>allow pasting</code> manually and press Enter, but only after checking code you trust. Never paste random Console code from other people.</li>
<li>Copy the entire code below, paste it into the Console, and press Enter. It will say <code>Access token copied to clipboard.</code> It does NOT display or send the token to anyone.</li>
<li>Return straight to this local app, focus the <strong>Access token</strong> box and press <kbd>Ctrl+V</kbd>. Click Start. You can paste all your song links before copying the token if that's easier.</li></ol>
<pre><code>(() =&gt; {
  const parts = document.cookie.split(';').map(s =&gt; s.trim())
    .filter(s =&gt; /^sb-sb-auth-token\.\d+=/.test(s))
    .sort((a,b) =&gt; Number(a.match(/token\.(\d+)/)[1]) - Number(b.match(/token\.(\d+)/)[1]))
    .map(s =&gt; s.slice(s.indexOf('=')+1));
  if (!parts.length) { console.log('No readable session cookie.'); return; }
  const session = JSON.parse(atob(parts.join('').replace(/^base64-/,'')));
  copy(session.access_token);
  console.log('Access token copied to clipboard. Return to Audio Rescue.');
})();</code></pre>
<p><strong>What if this fails?</strong> Flow Music may have changed its login system or your session may have expired. Sign in again and retry. Never share a screenshot of headers, cookies, or authentication tokens. This is an unofficial downloader; the endpoint may change.</p>
<h3>How to copy a Flow Music song link</h3><ol><li>Open the specific song page (not just your Library).</li><li>Press <kbd>Alt+D</kbd>, then <kbd>Ctrl+C</kbd>.</li><li>Paste that URL here. It should resemble <code>https://www.flowmusic.app/song/</code> followed by a long song ID. Repeat for each song.</li></ol>
</section>
<section id="other-sites"><h2>Other platforms: how to get the right link</h2>
<p><strong>Suno:</strong> in your Library or Workspace, open the song's More Actions (…) menu and choose Download, then the format your subscription provides. Suno's sharing link is not a direct WAV link. The official download menu is usually simpler; if the site provides an actual HTTPS audio download link, you can paste it using Direct audio links mode.</p>
<p><strong>Udio and other music services:</strong> use the service's own Download/Export option when available. If an actual audio link can be copied, use Direct audio links mode. A URL that merely opens a song player will not work as a file URL.</p>
<p><strong>Google Drive, Dropbox, personal websites, cloud storage:</strong> a direct HTTPS file URL can work if it actually serves audio and its permissions allow download. A preview or login-page link will generally fail.</p>
<details><summary>How do I copy a direct audio link?</summary><ol><li>Find an actual link to download the audio on the platform.</li><li>With a mouse, right-click that link and select <strong>Copy link address</strong>; with NVDA, focus a real link and try <kbd>Shift+F10</kbd> for its context menu. A button may not have a link address.</li><li>Paste it into Direct audio links mode, one per line.</li><li>If it downloads an HTML page instead or says Forbidden, that site needs its own authorized export mechanism. Use its built-in Download button; this app does not automatically extract files from protected pages.</li></ol></details>
<details><summary>Advanced mode — adding a similar site</summary><p>For sites that use an audio endpoint with a song ID, select Advanced. Provide an HTTPS URL template, such as <code>https://audio.example.com/download/{id}?format={format}</code>, and paste song IDs or links ending in IDs. Only use a template the platform supports and your account is permitted to access. When supplying a token, fill in the exact audio-host name as well so it is not sent anywhere else. A Share link by itself cannot reveal an undocumented endpoint.</p></details>
<p><strong>A WAV file is only a true WAV master if the platform supplies it.</strong> Renaming MP3 to WAV, or converting MP3 to WAV, cannot restore lost detail. Audio Rescue checks that requested file formats match the bytes it receives.</p></section>
<p>Privacy: access tokens stay in program memory for the batch. A local integrity index stores file sizes and hashes, never tokens or source URLs. Files are limited to 2 GiB each. Closing the browser tab does not stop an active download.</p>
<p>To exit, return to the command window and press Ctrl+C. Closing this browser tab alone does not stop the local app.</p>
</main><script>
const $=id=>document.getElementById(id);
let lastMessage='',lastLen=-1;
function updateMode(){const m=$('mode').value;$('advanced-area').hidden=m!=='template';$('format-area').hidden=m==='direct';$('host-area').hidden=m==='flow';$('token').required=m==='flow';$('mode-help').textContent=m==='flow'?'Paste Flow Music song page URLs or IDs. A fresh Flow Music token is required.':m==='direct'?'Paste real HTTPS audio file URLs. A song-sharing page is not a direct file link.':'Paste song IDs or links ending with song IDs and a known HTTPS download URL template.';}
$('mode').addEventListener('change',updateMode);updateMode();
function busy(b){$('start').disabled=b;$('stop').disabled=!b;}
function render(s){busy(s.status==='running');if(s.message!==lastMessage){$('message').textContent=s.message;lastMessage=s.message;}$('current').textContent=s.current;$('bar').max=s.bytes_total||1;$('bar').value=s.bytes_done||0;$('counts').textContent=`${s.done} downloaded, ${s.skipped} already present, ${s.failed} failed, out of ${s.total}.`;if(s.results.length!==lastLen){$('results').replaceChildren();for(const entry of s.results){const li=document.createElement('li');li.textContent=`${entry.name}: ${entry.status}. ${entry.detail}`;$('results').appendChild(li)}lastLen=s.results.length}}
async function poll(){try{const r=await fetch('/api/status',{cache:'no-store'});if(r.ok)render(await r.json())}catch{$('message').textContent='Cannot reach the local app. Keep its command window open.'}}
$('download-form').addEventListener('submit',async e=>{e.preventDefault();busy(true);$('message').textContent='Starting...';try{const body={mode:$('mode').value,format:$('format').value,template:$('template').value,urls:$('urls').value,token:$('token').value.trim(),host:$('host').value.trim(),folder:$('folder').value.trim()};const r=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok){$('message').textContent=data.error||'Could not start.';busy(false);return;}$('token').value='';lastLen=-1;lastMessage='';await poll()}catch{$('message').textContent='Could not start local download.';busy(false)}});
$('stop').addEventListener('click',async()=>{try{await fetch('/api/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});await poll()}catch{$('message').textContent='Unable to stop app.'}});
poll();setInterval(poll,1000);
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    server_version='AudioRescueLocal/3.0'
    def log_message(self, *args: Any) -> None: pass
    def send(self,code: int,data:bytes,ct:str):
        self.send_response(code)
        for k,v in {'Content-Type':ct,'Content-Length':str(len(data)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'"}.items():self.send_header(k,v)
        self.end_headers();self.wfile.write(data)
    def js(self,code:int,data:dict):self.send(code,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8')
    def do_GET(self):
        if not re.fullmatch(r'(?:127\.0\.0\.1|localhost):\d+', self.headers.get('Host','')):
            self.js(403,{'error':'Local app only.'});return
        if self.path in {'/','/index.html'}:
            self.send(200,PAGE.replace('__DOWNLOADS__',escape(str(DOWNLOADS),quote=True)).encode(),'text/html; charset=utf-8')
        elif self.path=='/api/status':self.js(200,snapshot())
        else:self.js(404,{'error':'Not found'})
    def do_POST(self):
        if self.path not in {'/api/start','/api/stop'}:self.js(404,{'error':'Not found'});return
        host=self.headers.get('Host','');origin=self.headers.get('Origin','')
        if not re.fullmatch(r'(?:127\.0\.0\.1|localhost):\d+',host) or origin != 'http://'+host:
            self.js(403,{'error':'Only this local app is allowed.'});return
        if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
            self.js(415,{'error':'Expected JSON.'});return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<1 or n>MAX_BODY:raise ValueError('Request too large or empty.')
            obj=json.loads(self.rfile.read(n))
            if not isinstance(obj,dict):raise ValueError('Expected form fields.')
        except (ValueError,UnicodeError,TypeError) as e:self.js(400,{'error':str(e)});return
        if self.path=='/api/stop':
            with lock:
                if job.status=='running':job.cancel.set();job.message='Stopping...'
            self.js(200,{'ok':True});return
        try:
            mode=str(obj.get('mode','flow'))
            token=str(obj.get('token','')).strip()
            if token.lower().startswith('bearer '):token=token[7:].strip()
            if len(token)>MAX_TOKEN or any(c.isspace() for c in token):raise ValueError('The token cannot contain spaces or line breaks.')
            if mode=='flow' and not token:raise ValueError('Flow Music requires a fresh access token. See the beginner token guide below.')
            if token and token_is_expired(token):raise ValueError('This access token is expired or expires in under 45 seconds. Sign in and copy a fresh one.')
            items=make_items(mode,str(obj.get('urls','')),str(obj.get('format','wav')),str(obj.get('template','')).strip())
            auth_host='www.flowmusic.app' if mode=='flow' else str(obj.get('host','')).strip().lower()
            if token and (not auth_host or not re.fullmatch(r'[a-z0-9.-]+',auth_host) or any(hostname(i.url)!=auth_host for i in items)):
                raise ValueError('To protect your token, supply its exact authorized audio hostname. All links must belong to that host.')
            if not token:auth_host=''
            folder=str(obj.get('folder','')).strip()
            target=Path(os.path.expandvars(os.path.expanduser(folder))).resolve() if folder else DOWNLOADS
            if not target.is_absolute():raise ValueError('Use an absolute save folder path.')
        except (ValueError,OSError,TypeError) as e:self.js(400,{'error':str(e)});return
        with lock:
            already_running = job.status=='running'
            if not already_running:
                job.status='running';job.directory=str(target);job.total=len(items);job.done=job.skipped=job.failed=0
                job.current='';job.bytes_done=job.bytes_total=0;job.message='Starting...';job.results=[];job.cancel=threading.Event();cancel=job.cancel
        if already_running:
            self.js(409,{'error':'A batch is already running.'})
            return
        threading.Thread(target=do_batch,args=(items,target,token,auth_host,cancel),daemon=True,name='AudioRescueWorker').start()
        self.js(200,{'ok':True})


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_address[1]}/'
    print('Audio Rescue',VERSION,'- Accessible multi-platform audio downloader')
    print('Opening:',url,'\nDefault save folder:',DOWNLOADS)
    print('Leave this window open while downloading. Press Ctrl+C to quit.')
    threading.Timer(.5,lambda:webbrowser.open(url)).start()
    try:server.serve_forever(poll_interval=.4)
    except KeyboardInterrupt:print('\nClosed.')
    finally:server.server_close()

if __name__=='__main__':main()
