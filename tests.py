"""Tests hors réseau de Media Select Pro V6."""
from __future__ import annotations
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
import decouverte

import moteur
import serveur


class TestMoteur(unittest.TestCase):
    def test_allowed_urls(self):
        for link in ('https://youtube.com/watch?v=xxx', 'https://vimeo.com/124', 'http://example.org/media'):
            self.assertEqual(moteur.validate_url(link), link)

    def test_reject_urls(self):
        for link in ('file:///x', 'https://localhost:2222/a', 'http://192.168.1.5/a', 'ftp://example.com/a',
                     'http://127.0.0.1', 'javascript:alert(1)', 'https://u:p@vimeo.com/a'):
            with self.subTest(link=link), self.assertRaises(ValueError):
                moteur.validate_url(link)

    def test_youtube_root_to_videos(self):
        u, changed = moteur.normalize_channel('https://www.youtube.com/@someone', True)
        self.assertTrue(changed)
        self.assertEqual(u, 'https://www.youtube.com/@someone/videos')
        u, changed = moteur.normalize_channel('https://www.youtube.com/@someone/shorts', True)
        self.assertFalse(changed)
        self.assertTrue(u.endswith('/shorts'))
        u, changed = moteur.normalize_channel('https://www.youtube.com/@someone', False)
        self.assertFalse(changed)

    def test_preview_limit(self):
        cmd = moteur.make_preview_command('python', 'https://x.com/abc')
        self.assertIn('--flat-playlist', cmd)
        self.assertEqual(cmd[cmd.index('--playlist-end')+1], '251')
        frozen = moteur.make_preview_command(['MediaSelectPro.exe', '--run-yt-dlp'],
                                             'https://x.com/abc')
        self.assertEqual(frozen[:2], ['MediaSelectPro.exe', '--run-yt-dlp'])

    def test_parse_single_and_playlist(self):
        single = moteur.parse_entries({'id': '123', 'title': 'Titre', 'uploader': 'Chaîne test',
                                       'thumbnail': 'https://img.example/test.jpg'})
        self.assertEqual(len(single['entries']), 1)
        self.assertFalse(single['has_playlist'])
        self.assertEqual(single['entries'][0]['channel'], 'Chaîne test')
        self.assertEqual(single['entries'][0]['thumbnail'], 'https://img.example/test.jpg')
        youtube = moteur.parse_entries({'extractor_key': 'YoutubeTab', 'entries': [
            {'id': 'BaW_jenozKc', 'title': 'Vidéo sans miniature'}]})
        self.assertEqual(youtube['entries'][0]['thumbnail'],
                         'https://i.ytimg.com/vi/BaW_jenozKc/hqdefault.jpg')
        playlist = moteur.parse_entries({'title': 'Collection', 'entries':[
            {'id': 'a', 'title': 'Intro'}, {'id':'b', 'url':'https://youtube.com/shorts/b', 'title':'Extrait'},
            {'_type':'playlist','title':'Sous-collection'}]})
        self.assertTrue(playlist['entries'][1]['short'])
        self.assertTrue(playlist['entries'][2]['nested'])

    def test_preview_truncation(self):
        result = moteur.parse_entries({'entries':[{'id':str(i)} for i in range(251)]})
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['entries']), 250)

    def test_audio_profiles(self):
        with tempfile.TemporaryDirectory() as dir:
            for mode in ('audio_original','audio_mp3','audio_m4a'):
                c = moteur.make_download_command('python','https://example.com/playlist',dir,mode,'best',[1,3,5])
                self.assertEqual(c[c.index('--playlist-items')+1], '1,3,5')
                self.assertIn('--download-archive', c)
                self.assertIn('-P',c)
                self.assertEqual(Path(c[c.index('-P')+1]).name, 'Audio')
                self.assertTrue((Path(dir) / 'Audio').is_dir())
                self.assertEqual(c[-1], 'https://example.com/playlist')
                self.assertIn('--extract-audio', c)
                self.assertIn('best' if mode == 'audio_original' else ('mp3' if mode == 'audio_mp3' else 'm4a'), c)

    def test_video_profiles(self):
        with tempfile.TemporaryDirectory() as dir:
            a = moteur.make_download_command('python','https://example.com/playlist',dir,'video_best','2160',None)
            self.assertIn('mkv',a)
            self.assertIn('height<=?2160',a[a.index('-f')+1])
            self.assertEqual(Path(a[a.index('-P')+1]).name, 'Video')
            self.assertTrue((Path(dir) / 'Video').is_dir())
            self.assertNotIn('--playlist-items',a)
            b = moteur.make_download_command('python','https://example.com/playlist',dir,'video_mp4','1080',[2])
            self.assertIn('mp4',b)
            self.assertIn('avc1',b[b.index('-f')+1])
            self.assertIn('height<=?1080',b[b.index('-f')+1])


    def test_target_sites_and_multilinks(self):
        ph='https://fr.pornhub.com/view_video.php?viewkey=example'
        ep='https://www.eporner.com/video-123/example/'
        self.assertEqual(moteur.recognize_site(ph), 'Pornhub')
        self.assertEqual(moteur.recognize_site(ep), 'Eporner')
        self.assertEqual(moteur.parse_source_urls(ph+'\n'+ep), [ph, ep])
        self.assertEqual(moteur.parse_source_urls(ph+'\n'), [ph])
        with self.assertRaises(ValueError):
            moteur.parse_source_urls(ph+'\n'+ph)
        with self.assertRaises(ValueError):
            moteur.parse_source_urls('\n'.join('https://example.org/v'+str(x) for x in range(31)))

    def test_multi_command_and_platform_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            urls=['https://fr.pornhub.com/view_video.php?viewkey=a',
                  'https://www.eporner.com/video-123/example/']
            cmd=moteur.make_download_command('python', urls, directory, 'video_best','1080', None)
            self.assertEqual(cmd[-2:], urls)
            self.assertNotIn('--playlist-items', cmd)
            self.assertIn('extractor_key', cmd[cmd.index('-o') + 1])
            with self.assertRaises(ValueError):
                moteur.make_download_command('python', urls, directory, 'video_best','best',[1])

    def test_bad_selection(self):
        with tempfile.TemporaryDirectory() as dir:
            for indices in ([], [0], [True], [1]*251):
                with self.subTest(indices=indices[:2]), self.assertRaises(ValueError):
                    moteur.make_download_command('python','https://example.com/x',dir,'audio_original','best',indices)
            with self.assertRaises(ValueError):
                moteur.make_download_command('python','https://example.com/x',dir,'bad_mode','best',[1])

    def test_missing_destination(self):
        with self.assertRaises(ValueError):
            moteur.make_download_command('python','https://example.com/x','/missing/directory/xx','audio_original','best',[1])

    def test_existing_download_archive_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = moteur.archive_path(directory, 'video_mp4', '1080')
            archive.write_text('youtube abc123def45\nyoutube xyz987uvw65\n', encoding='utf-8')
            self.assertEqual(moteur.read_archive_ids(directory, 'video_mp4', '1080'),
                             {'abc123def45', 'xyz987uvw65'})


class TestServeur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = serveur.ThreadingHTTPServer(('127.0.0.1',0),serveur.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def call(self,path,data=None,token=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        if data is None:
            conn.request('GET',path)
        else:
            headers={'Content-Type':'application/json'}
            if token: headers['X-Local-Token']=serveur.STATE.token
            conn.request('POST',path,body=json.dumps(data),headers=headers)
        res=conn.getresponse()
        status=res.status
        b=res.read()
        conn.close()
        return status,b

    def test_html_and_status(self):
        code, raw=self.call('/')
        self.assertEqual(code,200)
        self.assertIn(b'Media Select Pro',raw)
        self.assertNotIn(b'__LOCAL_TOKEN__',raw)
        code,raw=self.call('/api/status')
        self.assertEqual(code,200)
        self.assertIn('ffmpeg',json.loads(raw))
        code,raw=self.call('/api/history',{})
        self.assertEqual(code,200)
        self.assertIn('entries',json.loads(raw))

    def test_access_control(self):
        code,raw=self.call('/api/cancel',{},False)
        self.assertEqual(code,403)

    def test_youtube_thumbnail_is_served_locally(self):
        image = b'\xff\xd8fake-jpeg\xff\xd9'
        with patch.object(serveur, 'fetch_youtube_thumbnail', return_value=image):
            code, raw = self.call('/api/thumbnail/BaW_jenozKc')
        self.assertEqual(code, 200)
        self.assertEqual(raw, image)

    def test_history_exposes_live_download_progress(self):
        with serveur.STATE.lock:
            previous = (serveur.STATE.history, serveur.STATE.running,
                        serveur.STATE.active_history_id, serveur.STATE.progress, serveur.STATE.status)
            serveur.STATE.history = [{'id':'live1','title':'Playlist','status':'En cours'}]
            serveur.STATE.running = True
            serveur.STATE.active_history_id = 'live1'
            serveur.STATE.progress = '42.5%'
            serveur.STATE.status = 'Téléchargement de la vidéo 2'
        try:
            code, raw = self.call('/api/history', {})
            entry = json.loads(raw)['entries'][0]
            self.assertEqual(code, 200)
            self.assertTrue(entry['running'])
            self.assertEqual(entry['progress'], '42.5%')
            self.assertEqual(entry['status'], 'Téléchargement de la vidéo 2')
        finally:
            with serveur.STATE.lock:
                (serveur.STATE.history, serveur.STATE.running,
                 serveur.STATE.active_history_id, serveur.STATE.progress,
                 serveur.STATE.status) = previous

    def test_download_info_marks_existing_video(self):
        with tempfile.TemporaryDirectory() as directory:
            moteur.archive_path(directory, 'video_mp4', 'best').write_text(
                'youtube abc123def45\n', encoding='utf-8')
            with serveur.STATE.lock:
                previous = serveur.STATE.preview_media
                serveur.STATE.preview_media = {
                    1: {'id':'abc123def45','title':'Déjà là'},
                    2: {'id':'new123video','title':'Nouvelle'}
                }
            try:
                code, raw = self.call('/api/download-info', {
                    'mode':'video_mp4','quality':'best','folder':directory})
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(raw)['downloaded_indices'], [1])
            finally:
                with serveur.STATE.lock:
                    serveur.STATE.preview_media = previous

    def test_success_marker_records_downloaded_video(self):
        with serveur.STATE.lock:
            previous = (serveur.STATE.downloads, serveur.STATE.active_items,
                        serveur.STATE.last_command_mode, serveur.STATE.active_quality,
                        serveur.STATE.active_folder)
            serveur.STATE.downloads = {}
            serveur.STATE.active_items = {'abc123def45': {
                'id':'abc123def45','title':'Vidéo terminée','thumbnail':'https://img/test.jpg'}}
            serveur.STATE.last_command_mode = 'video_mp4'
            serveur.STATE.active_quality = '1080'
            serveur.STATE.active_folder = 'C:/Videos'
        try:
            with patch.object(serveur.STATE, '_save_downloads'):
                serveur.STATE.log('MEDIA_SELECT_DONE:abc123def45')
            record = next(iter(serveur.STATE.downloads.values()))
            self.assertEqual(record['title'], 'Vidéo terminée')
            self.assertEqual(record['mode'], 'video_mp4')
            self.assertEqual(record['quality'], '1080')
        finally:
            with serveur.STATE.lock:
                (serveur.STATE.downloads, serveur.STATE.active_items,
                 serveur.STATE.last_command_mode, serveur.STATE.active_quality,
                 serveur.STATE.active_folder) = previous

    def test_preview_mocked(self):
        with patch.object(serveur,'preview',return_value={'title':'Test','entries':[],'truncated':False,'has_playlist':True}):
            code,raw=self.call('/api/preview',{'url':'https://youtube.com/@chan','exclude_shorts':True})
            self.assertEqual(code,200)
            got=json.loads(raw)
            self.assertEqual(got['effective_url'],'https://youtube.com/@chan/videos')
            self.assertTrue(got['adjusted_channel'])

    def test_start_selected_and_block_unreviewed_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            with serveur.STATE.lock:
                serveur.STATE.preview_urls = ('https://example.com/playlist',)
                serveur.STATE.preview_has_playlist = True
                serveur.STATE.preview_valid_indices = {1, 2, 3, 4, 5}
                serveur.STATE.running = False
                serveur.STATE.previewing = False
            finished = threading.Event()
            def fake_download(cmd):
                with serveur.STATE.lock:
                    serveur.STATE.running=False
                finished.set()
            with patch.object(serveur, 'work_download', side_effect=fake_download):
                code, raw = self.call('/api/start', {'url':'https://example.com/playlist',
                    'folder':tmp,'mode':'video_mp4','quality':'1080','selection':'selected','indices':[1,3,5]})
                self.assertEqual(code,200,raw)
                self.assertTrue(finished.wait(2))
            with serveur.STATE.lock:
                serveur.STATE.running=False
            code,raw=self.call('/api/start', {'url':'https://example.com/playlist',
                'folder':tmp,'mode':'audio_original','quality':'best','selection':'selected','indices':[99]})
            self.assertEqual(code,400)


    def test_preview_multi_links_and_selected_download(self):
        ph='https://fr.pornhub.com/view_video.php?viewkey=abc'
        ep='https://www.eporner.com/video-test/example/'
        with patch.object(serveur,'preview_one',side_effect=[
                {'title':'P','entries':[{'index':1,'id':'a','title':'Premier','nested':False,'short':False,'duration':40}], 'has_playlist':False},
                {'title':'E','entries':[{'index':1,'id':'b','title':'Second','nested':False,'short':False,'duration':50}], 'has_playlist':False}]):
            code, raw=self.call('/api/preview', {'url':ph+'\n'+ep})
        self.assertEqual(code,200,raw)
        payload=json.loads(raw)
        self.assertTrue(payload['batch_links'])
        self.assertEqual(len(payload['entries']),2)
        self.assertEqual(payload['entries'][1]['index'],2)
        finished=threading.Event()
        captured=[]
        def fake_download(cmd):
            captured.append(cmd)
            with serveur.STATE.lock:
                serveur.STATE.running=False
            finished.set()
        with tempfile.TemporaryDirectory() as directory, patch.object(serveur,'work_download',side_effect=fake_download):
            code,raw=self.call('/api/start',{'url':ph+'\n'+ep,'folder':directory,
                'mode':'video_best','quality':'1080','selection':'selected','indices':[2]})
            self.assertEqual(code,200,raw)
            self.assertTrue(finished.wait(2))
        self.assertEqual(captured[0][0][-1],ep)
        self.assertNotIn(ph,captured[0][0])
        self.assertNotIn('--playlist-items',captured[0][0])

    def test_preview_multi_rejects_list_links(self):
        with patch.object(serveur, 'preview_one',return_value={
                'title':'X','entries':[{'title':'one','nested':False},{'title':'two','nested':False}],
                'has_playlist':True}):
            code,raw=self.call('/api/preview',{'url':'https://example.org/list\nhttps://example.org/other'})
            self.assertEqual(code,400)
            self.assertIn('vidéo individuelle',raw.decode())

    def test_single_media_does_not_use_playlist_indices(self):
        url='https://www.eporner.com/video-1/a/'
        with serveur.STATE.lock:
            serveur.STATE.preview_urls=(url,)
            serveur.STATE.preview_valid_indices={1}
            serveur.STATE.preview_has_playlist=False
            serveur.STATE.running=False
            serveur.STATE.previewing=False
        captured=[]
        finished=threading.Event()
        def fake_download(cmd):
            captured.append(cmd)
            with serveur.STATE.lock: serveur.STATE.running=False
            finished.set()
        with tempfile.TemporaryDirectory() as directory, patch.object(serveur, 'work_download',side_effect=fake_download):
            code,raw=self.call('/api/start',{'url':url,'folder':directory,
              'mode':'video_best','quality':'best','selection':'selected','indices':[1]})
            self.assertEqual(code,200,raw)
            self.assertTrue(finished.wait(2))
        self.assertNotIn('--playlist-items',captured[0][0])

    def test_start_requires_matching_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(serveur,'work_download'):
                code,raw=self.call('/api/start',{'url':'https://example.com/new','folder':tmp,'mode':'audio_original','quality':'best','selection':'selected','indices':[1]})
                self.assertEqual(code,400)
                self.assertIn('Analyse',str(raw))


class TestDecouverte(unittest.TestCase):
    EP_HTML = '''<html><head><title>Jessy18 uploaded videos</title></head><body>
<a href="/video-A1/video-un/" title="La vidéo A"> <img alt="A" /> Vidéo un </a>
<a href="https://www.eporner.com/video-B2/video-deux/">Vidéo deux</a>
<a href="/video-A1/video-un/">Doublon du premier</a>
<a href="https://evil.example.com/video-Z5/vol/">Ne pas prendre</a>
<a href="?page=2">NEXT</a>
</body></html>'''
    DJ_HTML = '''<html><title>Accueil Djatoya</title>
<a href="/video/84895/baise-deux-go/">Première vidéo</a>
<a href="/video/9234/autre/">Autre vidéo</a>
<a href="/category/1">Catégorie</a>
<a href="?page=2">En avant</a></html>'''

    def test_urls_and_normalization(self):
        ep = 'https://www.eporner.com/profile/Jessy18/'
        self.assertTrue(decouverte.is_listing_page(ep))
        self.assertEqual(decouverte.normalize_listing_url(ep),
                         'https://www.eporner.com/profile/Jessy18/uploaded-videos/')
        self.assertTrue(decouverte.is_listing_page('https://djatoya.com/'))
        self.assertFalse(decouverte.is_listing_page('https://djatoya.com/video/84895/baise-deux-go/'))
        self.assertFalse(decouverte.is_listing_page('https://www.eporner.com/video-A1/anything/'))
        self.assertFalse(decouverte.is_listing_page('https://random.example.com/'))

    def test_eporner_profile_listing_dedup_and_next(self):
        r = decouverte.discover('https://www.eporner.com/profile/Jessy18/',
                                fetcher=lambda url: self.EP_HTML)
        self.assertEqual(len(r['entries']), 2)
        self.assertEqual(r['entries'][0]['title'], 'Vidéo un')
        self.assertEqual(r['entries'][1]['index'], 2)
        self.assertEqual(r['next_page'], 'https://www.eporner.com/profile/Jessy18/uploaded-videos/?page=2')
        self.assertTrue(r['discovered_links'])

    def test_djatoya_homepage_listing(self):
        r = decouverte.discover('https://djatoya.com/', fetcher=lambda url: self.DJ_HTML)
        self.assertEqual(len(r['entries']), 2)
        self.assertEqual(r['entries'][0]['url'], 'https://djatoya.com/video/84895/baise-deux-go/')
        self.assertEqual(r['next_page'], 'https://djatoya.com/?page=2')

    def test_reject_outbound_and_private_network(self):
        for url in ('http://djatoya.com/', 'https://localhost/',
                    'https://evil.example.net/', 'https://djatoya.com:444/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                decouverte.validate_fetch_url(url, 'djatoya')
        with patch.object(decouverte.socket, 'getaddrinfo', return_value=[
            (2, 1, 0, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                decouverte.validate_fetch_url('https://djatoya.com/', 'djatoya')


class TestDiscoveryIntegration(unittest.TestCase):
    def test_profile_returns_links_and_download_only_selected(self):
        url = 'https://www.eporner.com/profile/Jessy18/'
        fake = {'title':'Profil', 'entries':[
                {'index':1,'url':'https://www.eporner.com/video-A1/a/', 'title':'A','nested':False,'short':False},
                {'index':2,'url':'https://www.eporner.com/video-B2/b/', 'title':'B','nested':False,'short':False},
                {'index':3,'url':'https://www.eporner.com/video-C3/c/', 'title':'C','nested':False,'short':False}],
                'has_playlist':True,'discovered_links':True, 'truncated':False,'warning':'test'}
        with patch.object(serveur, 'discover', return_value=fake):
            p = serveur.preview([url])
        self.assertTrue(p['discovered_links'])
        self.assertEqual(serveur.STATE.preview_discovered[2], 'https://www.eporner.com/video-B2/b/')
        events=[]
        def fake_work(cmds):
            events.extend(cmds)
            with serveur.STATE.lock: serveur.STATE.running=False
        with tempfile.TemporaryDirectory() as temp, patch.object(serveur,'work_download',side_effect=fake_work):
            handler = TestServeur()
            TestServeur.setUpClass()
            try:
                handler.port = TestServeur.port
                code, raw = handler.call('/api/start', {'url':url,'folder':temp,
                    'mode':'video_mp4','quality':'1080', 'selection':'selected','indices':[2]})
                self.assertEqual(code,200,raw)
                for _ in range(100):
                    if events: break
                    import time; time.sleep(0.005)
                self.assertEqual(len(events),1)
                self.assertEqual(events[0][-1], 'https://www.eporner.com/video-B2/b/')
                self.assertNotIn(url, events[0])
                self.assertIn('--no-playlist', events[0])
            finally:
                TestServeur.tearDownClass()

    def test_discovered_all_excludes_catalogue(self):
        url = 'https://djatoya.com/'
        entries = [dict(index=i+1, title=f'Titre {i+1}',
                        url=f'https://djatoya.com/video/{i+1}/titre/',
                        short=False, nested=False) for i in range(19)]
        mock = dict(title='Accueil', entries=entries, discovered_links=True,
                    has_playlist=True, truncated=False)
        with patch.object(serveur, 'discover', return_value=mock):
            serveur.preview([url])
        completed = threading.Event()
        commands = []
        def fake_work(cmds):
            commands.extend(cmds)
            with serveur.STATE.lock: serveur.STATE.running=False
            completed.set()
        with tempfile.TemporaryDirectory() as folder, patch.object(serveur,'work_download',side_effect=fake_work):
            TestServeur.setUpClass()
            try:
                handler=TestServeur()
                handler.port=TestServeur.port
                code, raw=handler.call('/api/start', {
                    'url':url,'folder':folder,'mode':'video_best','quality':'best',
                    'selection':'all','indices':None})
                self.assertEqual(code,200,raw)
                self.assertTrue(completed.wait(2))
                self.assertEqual(len(commands), 3)
                self.assertNotIn(url, sum(commands, []))
                self.assertIn('--no-playlist',commands[0])
                self.assertEqual(sum(len([x for x in c if x.startswith('https://djatoya.com/video/')])
                                     for c in commands),19)
            finally:
                TestServeur.tearDownClass()

    def test_discovered_limit_batched(self):
        with tempfile.TemporaryDirectory() as temp:
            links = ['https://www.eporner.com/video-%02d/example/'%i for i in range(19)]
            result = [moteur.make_download_command('python', links[i:i+8], temp,
                      'video_best', 'best', None, direct_links=True) for i in range(0,len(links),8)]
            self.assertEqual(len(result),3)
            self.assertEqual(len(result[-1][-3:]),3)
            self.assertIn('--no-playlist', result[0])


if __name__ == '__main__':
    unittest.main()
