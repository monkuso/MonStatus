import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib
import msgpack

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import release
import sync

class ReleaseSyncTests(unittest.TestCase):
    def test_release_update_is_detected_without_mutating_credentials(self):
        config={'app_version':'33.0.0','headers':{'x-ds-session':'fixture'}}
        with patch('release.latest_release',return_value={'status':'verified','version':'34.0.0','platform':'ios'}):
            result=release.version_metadata(config,{'versionInfo':{'version':'33.0.0'}})
        self.assertTrue(result['changedSinceLastSync'])
        self.assertEqual(result['version'],'34.0.0')
        self.assertEqual(config,{'app_version':'33.0.0','headers':{'x-ds-session':'fixture'}})

    def test_store_outage_is_reported_without_inventing_a_version(self):
        with patch('release.latest_release',side_effect=TimeoutError()):result=release.version_metadata({})
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('version',result)

    def test_future_version_follows_new_manifest_and_verifies_archives(self):
        tables={name:[] for name in sync.TABLES}
        tables.update({'stages':[{'id':1,'name':'ステージ','stage_group_id':2}],'stage_groups':[{'id':2,'name':'クエスト'}],'gacha_groups':[{'id':3,'name':'ガチャ'}],'chars':[{'id':4,'name':'キャラ'}]})
        tables['stage_group_events']=[{'id':1,'stage_group_id':2,'start_at':100,'end_at':200}]
        config={'url':'https://api.monster-strike.com/master/version','headers':{'x-ds-session':'fixture','x-ds-requesthash':'fixture'},'password_b64':base64.b64encode(b'').decode()}
        for version in ['33.0.0','34.1.2']:
            resources={};entries=[]
            for name,rows in tables.items():
                buffer=io.BytesIO()
                with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('data',msgpack.packb({'result':0,'masters':[{name:rows}]}))
                raw=buffer.getvalue();url=f'https://assets.example.test/{version}/{name}'
                resources[url]=raw;entries.append({'name':name,'uri':url,'version':version,'size':len(raw),'crc':zlib.crc32(raw)&0xffffffff})
            resources[config['url']]=msgpack.packb({'result':0,'master_versions':entries,'daily_versions':[]})
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory,patch('sync.download',side_effect=lambda url,*args:resources[url]) as download,contextlib.redirect_stdout(io.StringIO()):
                snapshot=sync.build_snapshot(config,destination=directory,version_info={'version':version,'platform':'ios'})
            self.assertEqual(snapshot['appVersion'],version)
            self.assertIsNone(snapshot['configuredClientVersion'])
            self.assertEqual(len(snapshot['verification']),len(tables))
            self.assertTrue(all(f'/{version}/' in call.args[0] for call in download.call_args_list[1:]))

    def test_failed_refresh_preserves_published_files_and_success_time(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root=Path(directory);data=root/'data';data.mkdir();(data/'internal').mkdir()
            previous={'updatedAt':'2026-10-15T00:00:00Z'}
            (data/'catalog.json').write_text(json.dumps(previous),encoding='utf-8')
            (data/'events.json').write_text('old events',encoding='utf-8')
            (data/'internal'/'index.json').write_text('old index',encoding='utf-8')
            def fail(config,previous,destination,version_info):
                (destination/'internal').mkdir();(destination/'internal'/'index.json').write_text('incomplete',encoding='utf-8')
                raise sync.SyncError('fixture session rejection',code=200)
            with patch('sync.__file__',str(root/'scripts'/'sync.py')),patch('sync.configured_game',return_value={}),patch('sync.version_metadata',return_value={'version':'34.0.0'}),patch('sync.build_snapshot',side_effect=fail):
                with self.assertRaises(sync.SyncError):sync.run()
            self.assertEqual(json.loads((data/'catalog.json').read_text()),previous)
            self.assertEqual((data/'events.json').read_text(),'old events')
            self.assertEqual((data/'internal'/'index.json').read_text(),'old index')
            status=json.loads((data/'sync-status.json').read_text())
            self.assertEqual(status['state'],'error')
            self.assertEqual(status['reason'],'connection-config')
            self.assertEqual(status['lastSuccessAt'],previous['updatedAt'])
            self.assertFalse(list(data.glob('.sync-*')))

if __name__=='__main__':unittest.main()
