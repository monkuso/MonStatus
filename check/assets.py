import io
from pathlib import Path
import re
import sys
import tempfile
import unittest
import zipfile
import zlib
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from assetcodec import name_hash,decode
from cloudassets import RemoteArchive,TransferBudget,image_resources,sync_assets

class AssetSyncTests(unittest.TestCase):
    seed=(1,2,3,4)
    def png(self,color=(255,0,0,255)):
        out=io.BytesIO();Image.new('RGBA',(12,12),color).save(out,format='PNG');return out.getvalue()
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
    def test_manifest_http_urls_are_upgraded_to_https(self):
        raw,row=self.package({'cb/cb13103.png':self.png()});row['uri']='http://assets.example.test/package'
        reader=RemoteArchive(row,TransferBudget(),self.opener(raw,[]))
        self.assertEqual(reader.url,'https://assets.example.test/package')
        with zipfile.ZipFile(reader) as archive:self.assertTrue(archive.namelist())
    def test_large_archive_uses_ranges_instead_of_full_download(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_STORED) as archive:
            archive.writestr('UNRELATED',bytes(1024*1024))
            archive.writestr('12345678',b'target')
        raw=buffer.getvalue();row={'uri':'https://assets.example.test/package','size':len(raw),'crc':zlib.crc32(raw)&0xffffffff};budget=TransferBudget();calls=[]
        with zipfile.ZipFile(RemoteArchive(row,budget,self.opener(raw,calls))) as archive:self.assertEqual(archive.read('12345678'),b'target')
        self.assertLess(budget.used,len(raw)//2)
    def test_audio_and_duplicate_small_packages_are_excluded(self):
        rows=[{'path':path} for path in ['/resource/bgm42.zip','/resource/sound3.zip','/resource/c_banner12_s.zip','/resource/c_banner12_n.zip']]
        self.assertEqual([row['path'] for row in image_resources(rows)],['/resource/c_banner12_n.zip'])

if __name__=='__main__':unittest.main()
