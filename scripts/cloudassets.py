import base64
import concurrent.futures
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from assetcodec import name_hash,decode,write_image
from atlasassets import sync_atlas_images
from builtinassets import register_builtin_images
from assetinventory import discover_atlases
from sync import configured_game,master_manifest

BLOCK_SIZE=65536
MAX_PACKAGE_SIZE=256*1024*1024

class AssetFetchError(Exception):
    def __init__(self,code=None,reason=None):
        self.code=code
        self.reason_type=type(reason).__name__ if reason is not None else None
        super().__init__('Asset resource request failed')

class TransferBudget:
    def __init__(self,limit=1024*1024*1024):
        self.limit=limit
        self.used=0
        self.lock=threading.Lock()
    def record(self,count):
        with self.lock:
            self.used+=count
            if self.used>self.limit:raise ValueError('Asset transfer budget exceeded')
    def check(self):
        with self.lock:
            if self.used>self.limit:raise ValueError('Asset transfer budget exceeded')

class RemoteArchive(io.RawIOBase):
    def __init__(self,resource,budget,opener=urllib.request.urlopen,block_size=BLOCK_SIZE):
        self.resource=resource
        self.size=resource['size']
        if type(self.size) is not int or not 0<self.size<=MAX_PACKAGE_SIZE:raise ValueError('Asset package size rejected')
        parsed=urllib.parse.urlsplit(resource['uri'])
        if parsed.scheme not in {'http','https'} or not parsed.hostname:raise ValueError('Asset package protocol rejected')
        self.url=resource['uri']
        self.budget=budget
        self.opener=opener
        self.block_size=block_size
        self.position=0
        self.blocks={}
        self.complete=None
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        position=offset if whence==0 else self.position+offset if whence==1 else self.size+offset if whence==2 else -1
        if position<0:raise ValueError('Asset seek rejected')
        self.position=position
        return position
    def block(self,index):
        if self.complete is not None:return self.complete[index*self.block_size:(index+1)*self.block_size]
        if index in self.blocks:return self.blocks[index]
        self.budget.check()
        start=index*self.block_size
        end=min(self.size,start+self.block_size)-1
        request=urllib.request.Request(self.url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity','User-Agent':'MonStatus asset sync'})
        response=None
        for attempt in range(3):
            try:
                response=self.opener(request,timeout=30)
                break
            except urllib.error.HTTPError as error:
                if (error.code==429 or 500<=error.code<600) and attempt<2:time.sleep(2**attempt);continue
                raise AssetFetchError(error.code) from None
            except OSError as error:
                if attempt<2:time.sleep(2**attempt);continue
                raise AssetFetchError(reason=getattr(error,'reason',error)) from None
        with response:
            limit=end-start+1 if response.status==206 else self.size
            body=response.read(limit+1)
            self.budget.record(len(body))
            if response.status==206:
                if response.headers.get('Content-Range')!=f'bytes {start}-{end}/{self.size}' or len(body)!=limit:raise ValueError('Asset range response rejected')
                self.blocks[index]=body
                return body
            if response.status!=200 or len(body)!=self.size:raise ValueError('Asset package response rejected')
        crc=self.resource.get('crc',0)
        if crc:
            import zlib
            if zlib.crc32(body)&0xffffffff!=crc&0xffffffff:raise ValueError('Asset package CRC mismatch')
        self.complete=body
        return body[start:end+1]
    def read(self,count=-1):
        count=max(0,self.size-self.position) if count<0 else min(count,max(0,self.size-self.position))
        chunks=[]
        while count:
            index,offset=divmod(self.position,self.block_size)
            block=self.block(index)
            part=block[offset:offset+count]
            if not part:raise ValueError('Asset range did not advance')
            chunks.append(part);self.position+=len(part);count-=len(part)
        return b''.join(chunks)

def package_identity(resource):
    public={key:resource.get(key) for key in ['path','version','size','crc']}
    return hashlib.sha256(json.dumps(public,sort_keys=True).encode()).hexdigest()

def image_resources(resources):
    selected=[]
    for row in resources:
        path=row.get('path','')
        if row.get('disable') or not path.endswith('.zip') or re.fullmatch(r'/resource/(?:bgm\d*|sound\d*|se\d*)\.zip',path):continue
        selected.append(row)
    return sorted(selected,key=lambda row:(not row['path'].startswith('/resource/c_banner'),not row['path'].endswith('_n.zip'),-(max([int(n) for n in re.findall(r'\d+',row['path'])] or [0])),row['path']))

def image_targets(catalog,providers=None,manifest=None,site=None):
    targets={}
    def add(category,identity,name,relative):
        digest=name_hash(name)
        item={'category':category,'identity':str(identity),'name':name,'relative':relative,'hash':digest}
        bucket=targets.setdefault(digest,[])
        if not any(all(existing.get(key)==value for key,value in item.items()) for existing in bucket):bucket.append(item)
    for row in catalog['tables']['chars']:
        skin=row.get('skin_id') or row['id']
        if type(skin) is not int or skin<=0:continue
        choices=[('ball',f'cb/cb{skin:04d}.png',f'characters/{skin%100:02d}/{skin}.webp'),('enemy',f'en/en{skin:04d}.png',f'enemies/{skin%100:02d}/{skin}.webp'),('enemy',f'ep/ep{skin:04d}.png',f'enemy-portraits/{skin%100:02d}/{skin}.webp'),('portrait',f'pb/pb{skin:04d}.png',f'portraits/{skin%100:02d}/{skin}.webp')]
        old=(manifest or {}).get('characters',{}).get(str(skin));keep_ball=isinstance(old,str) and old.startswith('assets/characters/') and site is not None and (Path(site)/old).is_file()
        selected=choices[0] if providers is None or keep_ball else next((candidate for candidate in choices if name_hash(candidate[1]) in providers),choices[0])
        kind,name,relative=selected;add('characters',skin,name,relative)
        for target in targets[name_hash(name)]:
            if target['category']=='characters' and target['identity']==str(skin):target['kind']=kind
    for row in catalog['tables']['stage_groups']:
        boss=row.get('boss_skin_id')
        if type(boss) is int and boss>0:add('bosses',boss,f'eb/eb{boss:04d}.png',f'bosses/{boss%100:02d}/{boss}.webp')
        name=row.get('banner_file_name')
        if isinstance(name,str) and name:
            digest=name_hash(name);add('quests',name,name,f'quests/{digest[:2].lower()}/{digest}.webp')
    for row in catalog.get('gachaBanners',[]):
        name=row.get('file_name')
        if isinstance(name,str) and name:add('gachas',name,name,f'gachas/{name_hash(name)}.webp')
    for row in catalog.get('_visualRows',[]):
        for field in ['file_name','banner_name','banner_file_name','icon_name']:
            names=row.get(field)
            if not isinstance(names,str):continue
            for name in names.split('|'):
                if re.fullmatch(r'[A-Za-z0-9_./-]+\.png',name) and '..' not in name.split('/'):add('events',name,name,f'events/{name_hash(name)}.webp')
    return targets

def sync_assets(catalog,resources,seed,site,manifest,state,opener=urllib.request.urlopen):
    site=Path(site)
    manifest=json.loads(json.dumps(manifest))
    old_sources=state.get('images',{})
    previous=state.get('resources',{})
    state={'schemaVersion':1,'resources':{},'images':dict(old_sources)}
    budget=TransferBudget()
    failures=[];readers={};records={}
    packages=image_resources(resources)
    def index(row):
        path=row['path'];fingerprint=package_identity(row)
        old=previous.get(path,{})
        negative_age=time.time()-datetime.datetime.fromisoformat(old['checkedAt']).timestamp() if old.get('availability')=='not-distributed' else None
        if old.get('fingerprint')==fingerprint and (negative_age is None or 0<=negative_age<600):return path,old,None,None
        try:
            reader=RemoteArchive(row,budget,opener)
            with zipfile.ZipFile(reader) as archive:
                members={}
                for info in archive.infolist():
                    key=Path(info.filename).name.upper()
                    if re.fullmatch('[0-9A-F]{8}',key):
                        if key in members:raise ValueError('Duplicate asset member hash')
                        members[key]=info.filename
            return path,{'fingerprint':fingerprint,'members':members},reader,None
        except Exception as error:
            failure={'package':path,'errorType':type(error).__name__,'typeId':row.get('type_id')}
            if isinstance(error,AssetFetchError):
                failure['httpStatus']=error.code
                failure['reasonType']=error.reason_type
                failure['sourceScheme']=urllib.parse.urlsplit(row['uri']).scheme
                failure['sourceHost']=urllib.parse.urlsplit(row['uri']).hostname
                failure['sourcePort']=urllib.parse.urlsplit(row['uri']).port
                if error.code in {404,410}:return path,{'fingerprint':fingerprint,'members':{},'availability':'not-distributed','httpStatus':error.code,'checkedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()},None,None
            if isinstance(error,zipfile.BadZipFile):
                failure['detail']=str(error)
                try:
                    reader.seek(0);failure['header']=reader.read(8).hex()
                except Exception:pass
            return path,None,None,failure
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for path,record,reader,error in pool.map(index,packages):
            if error:failures.append(error);continue
            state['resources'][path]=record
            if reader:readers[path]=reader
    providers={}
    for row in packages:
        path=row['path'];record=state['resources'].get(path)
        if record:
            records[path]=row
            for digest in record['members']:
                if digest not in providers:providers[digest]=path
    targets=image_targets(catalog,providers,manifest,site)
    unique={digest:items[0] for digest,items in targets.items() if len({item['name'] for item in items})==1}
    requests={};missing={};reused=0
    for digest,target in unique.items():
        category,identity=target['category'],target['identity'];path=providers.get(digest)
        manifest.setdefault(category,{})
        existing=manifest[category].get(identity)
        existing_file=site/existing if isinstance(existing,str) and re.fullmatch(r'assets/[A-Za-z0-9_./-]+',existing) and '..' not in existing.split('/') else None
        source_key=category+':'+identity
        if path:
            fingerprint=state['resources'][path]['fingerprint']
            if existing_file and existing_file.is_file() and existing=='assets/'+target['relative'] and (source_key not in old_sources or old_sources[source_key]==fingerprint):
                state['images'][source_key]=fingerprint;reused+=1
                if category=='characters':manifest.setdefault('characterImageKinds',{})[identity]=target['kind']
            else:requests.setdefault(path,[]).append(target)
        elif not existing_file or not existing_file.is_file():missing[source_key]='pending' if failures or any(row.get('availability')=='not-distributed' for row in state['resources'].values()) else 'not-located'
    def extract(item):
        path,selections=item;row=records[path];completed=[];errors=[]
        try:
            reader=readers.get(path) or RemoteArchive(row,budget,opener)
            password=row.get('password','')
            if isinstance(password,str):password=password.encode()
            with zipfile.ZipFile(reader) as archive:
                for target in selections:
                    try:
                        member=state['resources'][path]['members'][target['hash']]
                        info=archive.getinfo(member)
                        if info.file_size>16*1024*1024:raise ValueError('Asset member size rejected')
                        plain=decode(archive.read(info,pwd=password or None),seed)
                        if not plain.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Decoded PNG signature mismatch')
                        destination=site/'assets'/target['relative'];destination.parent.mkdir(parents=True,exist_ok=True)
                        temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
                        try:write_image(plain,temporary);os.replace(temporary,destination)
                        finally:
                            if temporary.exists():temporary.unlink()
                        completed.append({**target,'imageDigest':hashlib.sha256(plain).hexdigest()})
                    except Exception as error:errors.append({'package':path,'asset':target['category']+':'+target['identity'],'errorType':type(error).__name__})
        except Exception as error:errors.append({'package':path,'errorType':type(error).__name__})
        return path,completed,errors
    updated=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for path,completed,errors in pool.map(extract,requests.items()):
            failures.extend(errors)
            for target in completed:
                relative='assets/'+target['relative']
                manifest[target['category']][target['identity']]=relative
                if target['category']=='characters':manifest.setdefault('characterImageKinds',{})[target['identity']]=target['kind']
                manifest.setdefault('imageVersions',{})[relative]=target['imageDigest'][:16]
                state['images'][target['category']+':'+target['identity']]=state['resources'][path]['fingerprint'];updated+=1
            done={target['category']+':'+target['identity'] for target in completed}
            for target in requests[path]:
                key=target['category']+':'+target['identity']
                if key not in done:missing[key]='download-or-decode-error'
    for error in failures:
        if error.get('asset'):missing[error['asset']]='download-or-decode-error'
    for digest,items in targets.items():
        if len({item['name'] for item in items})>1:
            for target in items:missing[target['category']+':'+target['identity']]='ambiguous-filename-hash'
        else:
            canonical=items[0];source=manifest.get(canonical['category'],{}).get(canonical['identity'])
            if source:
                for target in items:manifest.setdefault(target['category'],{})[target['identity']]=source
    all_providers={}
    for path,record in state['resources'].items():
        for digest in record['members']:all_providers.setdefault(digest,path)
    def read_atlas(path,digest):
        row=records[path];reader=readers.get(path) or RemoteArchive(row,budget,opener);readers[path]=reader
        password=row.get('password','');password=password.encode() if isinstance(password,str) else password
        with zipfile.ZipFile(reader) as archive:
            member=state['resources'][path]['members'][digest]
            if archive.getinfo(member).file_size>32*1024*1024:raise ValueError('Atlas member size rejected')
            return decode(archive.read(member,pwd=password or None),seed)
    registry_path=site/'config'/'asset-inventory.json'
    registry=json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.is_file() else {'plistPaths':['dlme/ui_items.plist'],'pngPaths':['dlme/ui_items.png']}
    item_names={row['image_name'] for row in catalog['tables'].get('items',[]) if row.get('image_name')}
    event_names={name for row in catalog.get('_visualRows',[]) for field in ['file_name','banner_name','banner_file_name','icon_name'] for name in (row.get(field,'').split('|') if isinstance(row.get(field),str) else []) if name}
    scan_readers={}
    def open_scan_archive(path):
        reader=scan_readers.setdefault(path,RemoteArchive(records[path],budget,opener,block_size=4096))
        return zipfile.ZipFile(reader)
    descriptors,discovery_failures=discover_atlases(packages,state['resources'],open_scan_archive,seed,registry,item_names|event_names)
    failures.extend(discovery_failures)
    atlas_updates,atlas_failures=sync_atlas_images(catalog['tables'].get('items',[]),event_names,descriptors,read_atlas,all_providers,site,manifest,state,missing,registry)
    updated+=atlas_updates;failures.extend(atlas_failures)
    register_builtin_images(site,manifest)
    for category in ['items','events']:
        for identity in manifest.get(category,{}):missing.pop(category+':'+identity,None)
    for row in catalog['tables'].get('items',[]):
        name=row.get('image_name')
        if name in manifest.get('items',{}):manifest['items'][str(row['id'])]=manifest['items'][name];missing.pop('items:'+str(row['id']),None)
    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest['counts']={key:len(manifest.get(key,{})) for key in ['characters','quests','gachas','bosses','gimmicks','attributes','items','events']}
    unavailable=sum(row.get('availability')=='not-distributed' for row in state['resources'].values())
    manifest['sync']={'state':'partial' if failures else 'success','lastAttemptAt':timestamp,'lastSuccessAt':manifest.get('sync',{}).get('lastSuccessAt') if failures else timestamp,'updatedImages':updated,'reusedImages':reused,'indexedPackages':len(state['resources'])-unavailable,'unavailablePackages':unavailable,'packageCount':len(packages),'downloadedBytes':budget.used,'unlocatedImages':len(missing),'failures':failures}
    manifest['pending']=missing
    manifest.setdefault('provenance',{})['automaticSource']='verified-game-resource-manifest'
    state['updatedAt']=timestamp
    return manifest,state

def main():
    site=Path(__file__).resolve().parents[1]
    data=site/'data'
    secret=json.loads(os.environ['MS_ASSET_CONFIG'])
    raw=base64.b64decode(secret['seed_b64'],validate=True)
    if len(raw)!=16 or secret.get('decoder')!='xorshift128-v1':raise ValueError('Asset decoder configuration rejected')
    seed=struct.unpack('<IIII',raw)
    catalog=json.loads((data/'catalog.json').read_text(encoding='utf-8'))
    internal_index=json.loads((data/'internal'/'index.json').read_text(encoding='utf-8'))
    catalog['_visualRows']=[]
    for name,entry in internal_index['tables'].items():
        if name!='items' and not set(entry['fields'])&{'file_name','banner_file_name','banner_name','icon_name'}:continue
        rows=[]
        for part in entry['chunks']:
            raw_part=(data/'internal'/part['file']).read_bytes()
            if hashlib.sha256(raw_part).hexdigest()!=part['sha256']:raise ValueError('Visual master chunk digest mismatch')
            rows.extend(json.loads(raw_part)['rows'])
        if name=='items':catalog['tables']['items']=rows
        else:catalog['_visualRows'].extend(rows)
    manifest=json.loads((data/'assets.json').read_text(encoding='utf-8'))
    index=data/'asset-index.json'
    state=json.loads(index.read_text(encoding='utf-8')) if index.exists() else {}
    resources=master_manifest(configured_game()).get('resources')
    if not isinstance(resources,list) or not resources:raise ValueError('Game asset manifest missing')
    manifest,state=sync_assets(catalog,resources,seed,site,manifest,state)
    for name,value in [('assets.json',manifest),('asset-index.json',state)]:
        target=data/name;temporary=target.with_suffix('.json.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,target)
    print(json.dumps(manifest['sync'],ensure_ascii=False))
    if manifest['sync']['state']!='success':raise SystemExit(1)

if __name__=='__main__':
    try:main()
    except Exception as error:
        target=Path(__file__).resolve().parents[1]/'data'/'assets.json'
        manifest=json.loads(target.read_text(encoding='utf-8'))
        previous=manifest.get('sync',{})
        manifest['sync']={'state':'error','lastAttemptAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'lastSuccessAt':previous.get('lastSuccessAt'),'errorType':type(error).__name__}
        temporary=target.with_suffix('.json.tmp');temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,target)
        print(json.dumps(manifest['sync']))
        raise SystemExit(1)
