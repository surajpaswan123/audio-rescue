"""Offline regression tests. No real audio services, access tokens or outside networking used."""
from __future__ import annotations

import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import audio_rescue as a

FLOW_ID='cc83430c-be31-4350-bcd7-5561794fede6'
FLOW_URL=f'https://www.flowmusic.app/song/{FLOW_ID}'


def wav_bytes():
    out=io.BytesIO()
    with wave.open(out,'wb') as wf:
        wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(8000)
        wf.writeframes(b'\x11\x00'*80)
    return out.getvalue()

WAV=wav_bytes()


class FakeResponse:
    def __init__(self, data=WAV, ct='audio/wav', claimed=None, status=200, content_range=None):
        self.data=io.BytesIO(data)
        self.headers={'Content-Type':ct,'Content-Length':str(len(data) if claimed is None else claimed)}
        self.status=status
        if content_range:self.headers['Content-Range']=content_range
    def read(self,n):return self.data.read(n)
    def __enter__(self):return self
    def __exit__(self,*a):pass


class FakeOpener:
    def __init__(self, responses):self.responses=list(responses);self.calls=[]
    def open(self,req,timeout=0):
        self.calls.append(req)
        resp=self.responses.pop(0)
        if isinstance(resp,Exception):raise resp
        return resp


class AudioTests(unittest.TestCase):
    def item(self):return a.make_items('flow',f'Ada | {FLOW_URL}','wav','')[0]
    def direct(self):return a.make_items('direct','Test | https://audio.example.test/file.wav','wav','')[0]
    def download(self,item,responses,token='',host=''):
        opener=FakeOpener(responses)
        with tempfile.TemporaryDirectory() as folder,patch.object(a.urllib.request,'build_opener',return_value=opener):
            root=Path(folder)
            out=a.download_one(item,root,token,host,threading.Event())
            return out,[(p.name,p.read_bytes()) for p in root.glob('*.wav')],opener.calls

    def test_wav_signature(self):self.assertEqual(a.detect_format(WAV,'','',None),'wav')
    def test_mp3_signature(self):
        self.assertEqual(a.detect_format(b'ID3' + b'\0'*32,'','',None),'mp3')
        self.assertEqual(a.detect_format(b'\xff\xfb'+b'\0'*32,'','',None),'mp3')
    def test_aac_is_not_mp3(self):self.assertEqual(a.detect_format(b'\xff\xf1'+b'\0'*32,'','',None),'aac')
    def test_other_signatures(self):
        self.assertEqual(a.detect_format(b'fLaC' + b'\0'*32,'','',None),'flac')
        self.assertEqual(a.detect_format(b'OggS' + b'\0'*32,'','',None),'ogg')
        self.assertEqual(a.detect_format(b'\0\0\0\x18ftypisom'+b'\0'*24,'','',None),'m4a')
    def test_false_content_type_not_enough(self):self.assertEqual(a.detect_format(b'<html>login</html>','audio/wav','',None),'')
    def test_flow_id_and_duplicates(self):
        results=a.make_items('flow',FLOW_URL+'\n'+FLOW_ID,'wav','')
        self.assertEqual(len(results),1)
        self.assertEqual(a.flow_id(FLOW_URL),FLOW_ID)
    def test_url_rejection(self):
        for bad in ['http://example.test/a.wav','https://user:pass@example.test/a.wav',
                    'https://example.test.evil.com/song/'+FLOW_ID]:
            with self.subTest(bad=bad):
                self.assertEqual(a.hostname(bad),'') if bad.startswith('http://') or 'user:pass' in bad else self.assertEqual(a.flow_id(bad),'')
        with self.assertRaises(ValueError):a.make_items('flow','https://notflowmusic.app/song/'+FLOW_ID,'wav','')
    def test_template(self):
        x=a.make_items('template','https://example.test/song/my_song','wav','https://cdn.example.test/audio/{id}?fmt={format}')
        self.assertEqual(x[0].url,'https://cdn.example.test/audio/my_song?fmt=wav')
    def test_template_malformed(self):
        for tmpl in ['http://cdn.example.test/{id}','https://cdn.example.test/{name}',
                     'https://cdn.example.test/{id}/{id}']:
            with self.subTest(tmpl=tmpl),self.assertRaises(ValueError):
                a.make_items('template','sample_id','wav',tmpl)
    def test_filename_sanitization(self):
        self.assertEqual(a.clean_name('Ada: Still/Here?'),'Ada_ Still_Here_')
        self.assertEqual(a.clean_name('CON'),'Audio')
        self.assertEqual(a.clean_name('../<bad>'),'__bad_')
    def test_too_many(self):
        with self.assertRaises(ValueError):a.make_items('direct','\n'.join(f'https://a.test/{i}.wav' for i in range(201)),'wav','')
    def test_no_cross_host_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(a.DownloadError):a.download_one(self.item(),Path(tmp),'TEST','wrong.test',threading.Event())
    def test_cross_host_redirect_blocked(self):
        with self.assertRaises(a.DownloadError):
            a.RedirectGuard('www.flowmusic.app').redirect_request(None,None,302,'',{},'https://bad.test/a.wav')
    def test_http_redirect_blocked(self):
        with self.assertRaises(a.DownloadError):
            a.RedirectGuard('').redirect_request(None,None,302,'',{},'http://bad.test/a.wav')
    def test_success_token_header_and_exact_length(self):
        ret,files,calls=self.download(self.item(),[FakeResponse()],'FAKE_TEST_TOKEN','www.flowmusic.app')
        self.assertEqual(ret[0],'Downloaded')
        self.assertEqual(files[0][1],WAV)
        self.assertEqual(calls[0].get_header('Authorization'),'Bearer FAKE_TEST_TOKEN')
    def test_manifest_skip_only_if_hash_matches(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse()])):
            folder=Path(temp);item=self.item()
            self.assertEqual(a.download_one(item,folder,'','',threading.Event())[0],'Downloaded')
            first=next(folder.glob('*.wav'))
            self.assertEqual(a.download_one(item,folder,'','',threading.Event())[0],'Skipped')
            first.write_bytes(WAV[:-20])
            with patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse()])):
                self.assertEqual(a.download_one(item,folder,'','',threading.Event())[0],'Downloaded')
            self.assertEqual(len(list(folder.glob('*.wav'))),2)
            self.assertEqual(first.read_bytes(),WAV[:-20])
    def test_legacy_wav_skip_with_full_riff(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); item=self.item();a.dest_path(folder,item,'wav').write_bytes(WAV)
            self.assertEqual(a.download_one(item,folder,'','',threading.Event())[0],'Skipped')
    def test_legacy_truncated_wav_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse()])):
            folder=Path(tmp);item=self.item();a.dest_path(folder,item,'wav').write_bytes(WAV[:-20])
            self.assertEqual(a.download_one(item,folder,'','',threading.Event())[0],'Downloaded')
            self.assertEqual(len(list(folder.glob('*.wav'))),2)
    def test_length_mismatch_removes_partial(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse(claimed=len(WAV)+10) for _ in range(3)])):
            with self.assertRaisesRegex(a.DownloadError,'Incomplete audio'):
                a.download_one(self.item(),Path(tmp),'','',threading.Event())
            self.assertFalse(list(Path(tmp).glob('*.part')))
            self.assertFalse(list(Path(tmp).glob('*.wav')))
    def test_wav_header_mismatch(self):
        data=WAV[:4]+(len(WAV)+100).to_bytes(4,'little')+WAV[8:]
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse(data) for _ in range(3)])):
            with self.assertRaisesRegex(a.DownloadError,'WAV header'):
                a.download_one(self.item(),Path(tmp),'','',threading.Event())
    def test_retry_incomplete_then_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            opener=FakeOpener([FakeResponse(claimed=len(WAV)+10),FakeResponse()])
            with patch.object(a.urllib.request,'build_opener',return_value=opener):
                status,_=a.download_one(self.item(),Path(tmp),'','',threading.Event())
            self.assertEqual(status,'Downloaded')
            self.assertEqual(len(opener.calls),2)
            self.assertFalse(list(Path(tmp).glob('*.part')))
    def test_jwt_expired_claim(self):
        import base64
        def tok(exp):
            body=base64.urlsafe_b64encode(json.dumps({'exp':exp}).encode()).decode().rstrip('=')
            return f'header.{body}.sig'
        self.assertTrue(a.token_is_expired(tok(time.time()-5)))
        self.assertFalse(a.token_is_expired(tok(time.time()+3600)))
        self.assertFalse(a.token_is_expired('opaque-test-token'))
    def test_mislabeled_mp3_as_wav(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse(b'ID3'+b'\0'*90)])):
            with self.assertRaisesRegex(a.DownloadError,'MP3, not the requested WAV'):
                a.download_one(self.item(),Path(tmp),'','',threading.Event())
    def test_html_as_audio_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse(b'<html>no</html>',ct='text/html')])):
            with self.assertRaisesRegex(a.DownloadError,'webpage'):
                a.download_one(self.item(),Path(tmp),'','',threading.Event())
    def test_partial_response_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse(status=206)])):
            with self.assertRaisesRegex(a.DownloadError,'partial response'):
                a.download_one(self.item(),Path(tmp),'','',threading.Event())
    def test_giant_size_guard(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse(claimed=a.MAX_AUDIO+1)])):
            with self.assertRaisesRegex(a.DownloadError,'2 GiB'):
                a.download_one(self.item(),Path(tmp),'','',threading.Event())
    def test_auth_403_stops_batch(self):
        e=urllib.error.HTTPError(FLOW_URL,403,'Forbidden',{},None)
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([e])):
            a.report(status='running',total=1,done=0,failed=0,skipped=0,results=[],cancel=threading.Event())
            a.do_batch([self.item()],Path(tmp),'TEST','www.flowmusic.app',a.job.cancel)
            self.assertEqual(a.snapshot()['status'],'stopped')
            self.assertEqual(a.snapshot()['failed'],1)
    def test_cancel_is_not_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            event=threading.Event();event.set()
            a.report(status='running',total=1,done=0,failed=0,skipped=0,results=[],cancel=event)
            a.do_batch([self.item()],Path(tmp),'','',event)
            self.assertEqual(a.snapshot()['status'],'stopped')
            self.assertEqual(a.snapshot()['failed'],0)
    def test_cancel_midstream_cleans_part(self):
        class CancelResponse(FakeResponse):
            def read(self,n):
                data=super().read(50)
                event.set()
                return data
        event=threading.Event()
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([CancelResponse()])):
            with self.assertRaises(a.StoppedError):
                a.download_one(self.item(),Path(tmp),'','',event)
            self.assertFalse(list(Path(tmp).glob('*.part')))
            self.assertFalse(list(Path(tmp).glob('*.wav')))
    def test_http_429_then_success(self):
        e=urllib.error.HTTPError(FLOW_URL,429,'Rate limited',{'Retry-After':'1'},None)
        opener=FakeOpener([e,FakeResponse()])
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=opener),patch.object(a.threading.Event,'wait',return_value=False):
            self.assertEqual(a.download_one(self.item(),Path(tmp),'','',threading.Event())[0],'Downloaded')
            self.assertEqual(len(opener.calls),2)
    def test_manifest_does_not_store_token_or_url(self):
        item=self.item()
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse()])):
            a.download_one(item,Path(tmp),'SENSITIVE_TOKEN','www.flowmusic.app',threading.Event())
            contents=a.manifest_path(Path(tmp)).read_text()
            self.assertNotIn('SENSITIVE_TOKEN',contents)
            self.assertNotIn(item.url,contents)
            self.assertIn('sha256',contents)
    def test_ui_accessibility_basics(self):
        self.assertIn('aria-live="polite"',a.PAGE)
        self.assertIn('for="token"',a.PAGE)
        self.assertIn('for="urls"',a.PAGE)
        self.assertIn('NVDA tips',a.PAGE)


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),a.Handler)
        self.t=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.t.start()
        self.base=f'http://127.0.0.1:{self.server.server_address[1]}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.t.join(timeout=2)
        a.report(status='idle')
    def req(self,path,data=None,origin=None,host=None):
        headers={'Host':host or self.base.removeprefix('http://')}
        if data is not None:
            headers['Content-Type']='application/json'
            if origin:headers['Origin']=origin
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=2) as res:return res.status,json.load(res)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_status_route(self):self.assertEqual(self.req('/api/status')[0],200)
    def test_cross_origin_rejected(self):
        self.assertEqual(self.req('/api/stop',{},origin='https://evil.example')[0],403)
    def test_missing_origin_rejected(self):self.assertEqual(self.req('/api/stop',{})[0],403)
    def test_malicious_host_rejected(self):
        self.assertEqual(self.req('/api/status',host='evil.example:3333')[0],403)
    def test_oversized_json_rejected(self):
        self.assertEqual(self.req('/api/start',{'urls':'x'*(a.MAX_BODY+1)},origin=self.base)[0],400)
    def test_end_to_end_local_direct_batch(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(a.urllib.request,'build_opener',return_value=FakeOpener([FakeResponse()])):
            body={'mode':'direct','urls':'Test | https://files.example.test/test.wav',
                  'token':'','format':'wav','folder':tmp,'host':'','template':''}
            status,obj=self.req('/api/start',body,origin=self.base)
            self.assertEqual(status,200)
            deadline=time.time()+3
            while time.time()<deadline:
                status,obj=self.req('/api/status')
                if obj['status']!='running':break
                time.sleep(.03)
            self.assertEqual(obj['status'],'done',obj)
            self.assertEqual(obj['done'],1)
            self.assertEqual(len(list(Path(tmp).glob('*.wav'))),1)
            self.assertEqual(next(Path(tmp).glob('*.wav')).read_bytes(),WAV)
    def test_reject_expired_jwt_at_start(self):
        import base64
        exp=base64.urlsafe_b64encode(json.dumps({'exp':int(time.time())-10}).encode()).decode().rstrip('=')
        body={'mode':'flow','urls':FLOW_URL,'token':f'h.{exp}.s','format':'wav'}
        status,obj=self.req('/api/start',body,origin=self.base)
        self.assertEqual(status,400)
        self.assertIn('expired',obj['error'])
    def test_parallel_start_no_deadlock(self):
        a.report(status='running')
        status,obj=self.req('/api/start',{'mode':'flow','token':'FAKE','urls':FLOW_URL,'format':'wav'},origin=self.base)
        self.assertEqual(status,409)
        self.assertIn('already running',obj['error'])


if __name__=='__main__':unittest.main(verbosity=2)
