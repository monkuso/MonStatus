import io
import plistlib
from pathlib import Path
import re
import sys
import tempfile
import unittest
import urllib.error
import zipfile
import zlib
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from assetcodec import name_hash,decode
from cloudassets import RemoteArchive,TransferBudget,image_resources,sync_assets
from atlasassets import frame_png
from assetinventory import discover_atlases
from prettyjson import format_public_json
import hashlib
import json

class AssetSyncTests(unittest.TestCase):
    seed=(1,2,3,4)
    def test_discovery_finds_unlisted_atlas_and_reuses_verified_inventory(self):
        name='new_event.png';frame={'frame':'{{0,0},{2,3}}','sourceColorRect':'{{0,0},{2,3}}','sourceSize':'{2,3}'}
        raw,row=self.package({'new/new.plist':plistlib.dumps({'frames':{name:frame},'metadata':{'textureFileName':'new.png'}})})
        digest=name_hash('new/new.plist');states={row['path']:{'members':{digest:digest}}};calls=[]
        def open_archive(path):calls.append(path);return zipfile.ZipFile(io.BytesIO(raw))
        found,errors=discover_atlases([row],states,open_archive,self.seed,{}, {name})
        self.assertEqual(errors,[]);self.assertEqual(found[0]['frames'][name],frame);self.assertTrue(states[row['path']]['atlasScanComplete'])
        again,errors=discover_atlases([row],states,open_archive,self.seed,{}, {name})
        self.assertEqual(again,found);self.assertEqual(len(calls),1)
    def test_distinct_atlas_images_with_same_frame_name_remain_visible_variants(self):
        name='uiitem_shared.png';frame={'frame':'{{0,0},{2,3}}','sourceColorRect':'{{0,0},{2,3}}','sourceSize':'{2,3}'}
        files={}
        for prefix,color in [('a',(255,0,0,255)),('b',(0,0,255,255))]:
            files[prefix+'.plist']=plistlib.dumps({'frames':{name:frame},'metadata':{'textureFileName':prefix+'.png','size':'{12,12}'}});files[prefix+'.png']=self.png(color)
        raw,row=self.package(files);catalog=self.catalog(());catalog['tables']['items']=[{'id':1,'image_name':name}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root=Path(directory);(root/'config').mkdir();(root/'config'/'asset-inventory.json').write_text(json.dumps({'plistPaths':['a.plist','b.plist'],'pngPaths':['a.png','b.png']}),encoding='utf-8')
            manifest,state=sync_assets(catalog,[row],self.seed,root,{}, {},self.opener(raw,[]))
            self.assertEqual(len(manifest['itemVariants'][name]),2);self.assertNotIn(name,manifest['items']);self.assertNotIn('1',manifest['items'])
            self.assertTrue(all((root/entry['path']).is_file() for entry in manifest['itemVariants'][name]))
    def png(self,color=(255,0,0,255)):
        out=io.BytesIO();Image.new('RGBA',(12,12),color).save(out,format='PNG');return out.getvalue()
    def test_official_attribute_frames_fill_icon_cutout_without_filling_portrait_center(self):
        root=Path(__file__).resolve().parents[1]
        for attribute in range(1,6):
            with Image.open(root/'assets'/'character-frames'/'33.0.0'/f'{attribute}.webp') as image:
                self.assertEqual(image.size,(120,120));alpha=image.convert('RGBA').getchannel('A');self.assertEqual(alpha.getpixel((16,16)),255);self.assertEqual(alpha.getpixel((60,60)),0)
    def test_enemy_resource_uses_exact_declared_skin_and_records_image_kind(self):
        raw,row=self.package({'en/en0042.png':self.png()});catalog=self.catalog(())
        catalog['tables']['chars']=[{'id':20420,'skin_id':42}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            manifest,state=sync_assets(catalog,[row],self.seed,directory,{}, {},self.opener(raw,[]))
            self.assertEqual(manifest['characterImageKinds']['42'],'enemy');self.assertIn('42',manifest['characters']);self.assertNotIn('20420',manifest['characters'])
    def test_pretty_print_updates_index_hash_without_changing_data(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root=Path(directory);(root/'internal').mkdir();row={'schemaVersion':1,'table':'items','rows':[{'id':1,'name':'オーブ'}]};raw=json.dumps(row,ensure_ascii=False).encode();(root/'internal'/'items-0000.json').write_bytes(raw)
            part={'file':'items-0000.json','sha256':hashlib.sha256(raw).hexdigest()};(root/'internal'/'index.json').write_text(json.dumps({'tables':{'items':{'chunks':[part]}}}),encoding='utf-8');(root/'legacy.json').write_text('{"a":[1,2]}',encoding='utf-8')
            format_public_json(root);formatted=(root/'internal'/'items-0000.json').read_bytes();index=json.loads((root/'internal'/'index.json').read_text())
            self.assertEqual(json.loads(formatted),row);self.assertIn(b'\n  "schemaVersion"',formatted);self.assertEqual(index['tables']['items']['chunks'][0]['sha256'],hashlib.sha256(formatted).hexdigest());self.assertIn('\n  "a"',(root/'legacy.json').read_text())
    def test_item_atlas_preserves_transparent_padding_and_rejects_out_of_bounds(self):
        sheet=Image.new('RGBA',(12,12),(255,0,0,255))
        frame={'frame':'{{0,0},{2,3}}','sourceColorRect':'{{1,1},{2,3}}','sourceSize':'{4,5}','rotated':False}
        with Image.open(io.BytesIO(frame_png(sheet,frame))) as image:
            self.assertEqual(image.size,(4,5));self.assertEqual(image.getpixel((0,0))[3],0);self.assertEqual(image.getpixel((1,1)),(255,0,0,255))
        with self.assertRaises(ValueError):frame_png(sheet,{**frame,'frame':'{{11,0},{2,3}}'})
        rotated={'frame':'{{0,0},{2,3}}','sourceColorRect':'{{1,1},{2,3}}','sourceSize':'{4,5}','rotated':True}
        with Image.open(io.BytesIO(frame_png(sheet,rotated))) as image:self.assertEqual(image.getbbox(),(1,1,3,4))
    def test_item_atlas_connects_shared_frame_to_multiple_item_ids(self):
        frames={'uiitem_0001.png':{'frame':'{{0,0},{2,3}}','sourceColorRect':'{{1,1},{2,3}}','sourceSize':'{4,5}','rotated':False}}
        raw,row=self.package({'dlme/ui_items.plist':plistlib.dumps({'frames':frames,'metadata':{'textureFileName':'ui_items.png','size':'{12,12}'}}),'dlme/ui_items.png':self.png()})
        catalog=self.catalog(());catalog['tables']['items']=[{'id':1,'image_name':'uiitem_0001.png'},{'id':2,'image_name':'uiitem_0001.png'}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            manifest,state=sync_assets(catalog,[row],self.seed,directory,{}, {},self.opener(raw,[]))
            self.assertEqual(manifest['sync']['state'],'success')
            self.assertEqual(manifest['items']['1'],manifest['items']['2'])
            self.assertTrue(Path(directory,manifest['items']['1']).is_file())
    def test_same_virtual_image_name_across_categories_is_an_alias_not_hash_collision(self):
        name='ba_gacha11252_01.png';raw,row=self.package({name:self.png()});catalog=self.catalog(())
        catalog['_visualRows']=[{'file_name':name}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            manifest,state=sync_assets(catalog,[row],self.seed,directory,{}, {},self.opener(raw,[]))
            self.assertEqual(manifest['events'][name],manifest['gachas'][name])
            self.assertNotIn('events:'+name,manifest['pending'])
    def package(self,images,version=1):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_STORED) as archive:
            for name,plain in images.items():
                stream=decode(bytes(len(plain)),self.seed)
                archive.writestr(name_hash(name),bytes(a^b for a,b in zip(plain,stream)))
        raw=buffer.getvalue()
        return raw,{'path':'/resource/c_banner12_n.zip','uri':'https://assets.example.test/package','version':version,'size':len(raw),'crc':zlib.crc32(raw)&0xffffffff,'password':''}
    def opener(self,raw,calls):
        def open_range(request,timeout=0):
            value=request.get_header('Range');calls.append(value)
            start,end=map(int,re.fullmatch(r'bytes=(\d+)-(\d+)',value).groups())
            response=io.BytesIO(raw[start:end+1]);response.status=206;response.headers={'Content-Range':f'bytes {start}-{end}/{len(raw)}'};return response
        return open_range
    def catalog(self,ids=(13103,)):
        return {'tables':{'chars':[{'id':i} for i in ids],'stage_groups':[]},'gachaBanners':[{'file_name':'ba_gacha11252_01.png'}]}
    def test_known_filename_hash_vectors(self):
        for name,digest in {'cb/cb0001.png':'DD0CB6BD','cb/cb0100.png':'14A0589A','pb/pb0001.png':'396B5EB5','ba_stage950040.png':'3EB2DC91'}.items():self.assertEqual(name_hash(name),digest)
    def test_download_decode_webp_registration_and_unchanged_cache(self):
        raw,row=self.package({'cb/cb13103.png':self.png(),'ba_gacha11252_01.png':self.png()});calls=[]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            site=Path(directory)
            manifest,state=sync_assets(self.catalog(),[row],self.seed,site,{}, {},self.opener(raw,calls))
            self.assertEqual(manifest['sync']['state'],'success');self.assertEqual(manifest['sync']['updatedImages'],2)
            for image in [manifest['characters']['13103'],manifest['gachas']['ba_gacha11252_01.png']]:
                with Image.open(site/image) as picture:self.assertEqual(picture.format,'WEBP');self.assertEqual(picture.size,(12,12))
            first_count=len(calls)
            again,index=sync_assets(self.catalog(),[row],self.seed,site,manifest,state,self.opener(raw,calls))
            self.assertEqual(len(calls),first_count);self.assertEqual(again['sync']['updatedImages'],0)
            self.assertEqual(index['resources'],state['resources'])
    def test_new_package_version_discovers_missing_image_and_refreshes_existing(self):
        old,old_row=self.package({'cb/cb13103.png':self.png()});new,new_row=self.package({'cb/cb13103.png':self.png((0,0,255,255)),'cb/cb13104.png':self.png()},version=2)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            manifest,state=sync_assets(self.catalog((13103,13104)),[old_row],self.seed,directory,{}, {},self.opener(old,[]))
            self.assertEqual(manifest['pending']['characters:13104'],'not-located')
            digest=manifest['imageVersions'][manifest['characters']['13103']]
            latest,state=sync_assets(self.catalog((13103,13104)),[new_row],self.seed,directory,manifest,state,self.opener(new,[]))
            self.assertEqual(latest['sync']['updatedImages'],2);self.assertIn('13104',latest['characters'])
            self.assertNotEqual(digest,latest['imageVersions'][latest['characters']['13103']])
    def test_decoder_failure_does_not_register_image_and_is_retryable(self):
        raw,row=self.package({'cb/cb13103.png':self.png()})
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            broken,state=sync_assets(self.catalog(),[row],(4,3,2,1),directory,{}, {},self.opener(raw,[]))
            self.assertEqual(broken['sync']['state'],'partial');self.assertNotIn('13103',broken['characters'])
            fixed,state=sync_assets(self.catalog(),[row],self.seed,directory,broken,state,self.opener(raw,[]))
            self.assertEqual(fixed['sync']['state'],'success');self.assertIn('13103',fixed['characters'])
    def test_failed_refresh_keeps_existing_image_and_retries_changed_source(self):
        raw,row=self.package({'cb/cb13103.png':self.png()});changed={**row,'version':2}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            manifest,state=sync_assets(self.catalog(),[row],self.seed,directory,{}, {},self.opener(raw,[]))
            original=Path(directory,manifest['characters']['13103']).read_bytes()
            broken,index=sync_assets(self.catalog(),[changed],(4,3,2,1),directory,manifest,state,self.opener(raw,[]))
            self.assertEqual(original,Path(directory,broken['characters']['13103']).read_bytes())
            fixed,index=sync_assets(self.catalog(),[changed],self.seed,directory,broken,index,self.opener(raw,[]))
            self.assertEqual(fixed['sync']['updatedImages'],1)
    def test_range_header_mismatch_is_rejected(self):
        raw,row=self.package({'cb/cb13103.png':self.png()})
        def bad(request,timeout=0):
            response=io.BytesIO(raw);response.status=206;response.headers={'Content-Range':'bytes 0-0/1'};return response
        with self.assertRaises(ValueError):RemoteArchive(row,TransferBudget(),bad).read(10)
    def test_manifest_source_protocol_is_preserved_without_login_headers(self):
        raw,row=self.package({'cb/cb13103.png':self.png()});row['uri']='http://assets.example.test/package'
        reader=RemoteArchive(row,TransferBudget(),self.opener(raw,[]))
        self.assertEqual(reader.url,'http://assets.example.test/package')
        with zipfile.ZipFile(reader) as archive:self.assertTrue(archive.namelist())
    def test_delivery_url_rotation_does_not_invalidate_unchanged_package(self):
        raw,row=self.package({'cb/cb13103.png':self.png()});calls=[]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            manifest,state=sync_assets(self.catalog(),[row],self.seed,directory,{}, {},self.opener(raw,calls))
            count=len(calls);rotated={**row,'uri':'http://another.example.test/package?signature=changed'}
            manifest,state=sync_assets(self.catalog(),[rotated],self.seed,directory,manifest,state,self.opener(raw,calls))
            self.assertEqual(len(calls),count)
    def test_large_archive_uses_ranges_instead_of_full_download(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_STORED) as archive:
            archive.writestr('UNRELATED',bytes(1024*1024))
            archive.writestr('12345678',b'target')
        raw=buffer.getvalue();row={'uri':'https://assets.example.test/package','size':len(raw),'crc':zlib.crc32(raw)&0xffffffff};budget=TransferBudget();calls=[]
        with zipfile.ZipFile(RemoteArchive(row,budget,self.opener(raw,calls))) as archive:self.assertEqual(archive.read('12345678'),b'target')
        self.assertLess(budget.used,len(raw)//2)
    def test_audio_is_excluded_and_normal_images_precede_small_image_packages(self):
        rows=[{'path':path} for path in ['/resource/bgm42.zip','/resource/sound3.zip','/resource/c_banner12_s.zip','/resource/c_banner12_n.zip']]
        self.assertEqual([row['path'] for row in image_resources(rows)],['/resource/c_banner12_n.zip','/resource/c_banner12_s.zip'])
    def test_undistributed_resource_is_cached_and_rechecked_after_expiry(self):
        raw,row=self.package({'cb/cb13103.png':self.png()});calls=[]
        def absent(request,timeout=0):
            calls.append(1);raise urllib.error.HTTPError(request.full_url,404,'Not Found',None,None)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            manifest,state=sync_assets(self.catalog(),[row],self.seed,directory,{}, {},absent)
            self.assertEqual(manifest['sync']['state'],'success');self.assertEqual(manifest['sync']['unavailablePackages'],1)
            self.assertEqual(manifest['pending']['characters:13103'],'pending')
            count=len(calls)
            manifest,state=sync_assets(self.catalog(),[row],self.seed,directory,manifest,state,absent)
            self.assertEqual(len(calls),count)
            state['resources'][row['path']]['checkedAt']='2020-01-01T00:00:00+00:00'
            manifest,state=sync_assets(self.catalog(),[row],self.seed,directory,manifest,state,self.opener(raw,[]))
            self.assertIn('13103',manifest['characters']);self.assertEqual(manifest['sync']['unavailablePackages'],0)

if __name__=='__main__':unittest.main()
