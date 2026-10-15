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
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from assetcodec import name_hash,decode,write_image
from sync import configured_game,master_manifest

BLOCK_SIZE=65536
MAX_PACKAGE_SIZE=256*1024*1024

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
    def __init__(self,resource,budget,opener=urllib.request.urlopen):
        self.resource=resource
        self.size=resource['size']
        if type(self.size) is not int or not 0<self.size<=MAX_PACKAGE_SIZE:raise ValueError('Asset package size rejected')
        parsed=urllib.parse.urlsplit(resource['uri'])
        if parsed.scheme not in {'http','https'} or not parsed.hostname:raise ValueError('Asset package protocol rejected')
        self.url=urllib.parse.urlunsplit(parsed._replace(scheme='https'))
        self.budget=budget
        self.opener=opener
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
        if self.complete is not None:return self.complete[index*BLOCK_SIZE:(index+1)*BLOCK_SIZE]
        if index in self.blocks:return self.blocks[index]
        self.budget.check()
        start=index*BLOCK_SIZE
        end=min(self.size,start+BLOCK_SIZE)-1
        request=urllib.request.Request(self.url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity','User-Agent':'MonStatus asset sync'})
        with self.opener(request,timeout=30) as response:
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
            index,offset=divmod(self.position,BLOCK_SIZE)
            block=self.block(index)
            part=block[offset:offset+count]
            if not part:raise ValueError('Asset range did not advance')
            chunks.append(part);self.position+=len(part);count-=len(part)
        return b''.join(chunks)

def package_identity(resource):
    public={key:resource.get(key) for key in ['path','version','size','crc']}
    public['locationDigest']=hashlib.sha256(resource['uri'].encode()).hexdigest()
    return hashlib.sha256(json.dumps(public,sort_keys=True).encode()).hexdigest()

def image_resources(resources):
    paths={row.get('path') for row in resources if not row.get('disable')}
    selected=[]
    for row in resources:
        path=row.get('path','')
        if row.get('disable') or not path.endswith('.zip') or re.fullmatch(r'/resource/(?:bgm\d*|sound\d*|se\d*)\.zip',path):continue
        if path.endswith('_s.zip') and path[:-6]+'_n.zip' in paths:continue
        selected.append(row)
    return sorted(selected,key=lambda row:(not row['path'].startswith('/resource/c_banner'),not row['path'].endswith('_n.zip'),-(max([int(n) for n in re.findall(r'\d+',row['path'])] or [0])),row['path']))

def image_targets(catalog):
    targets={}
    def add(category,identity,name,relative):
        digest=name_hash(name)
        item={'category':category,'identity':str(identity),'name':name,'relative':relative,'hash':digest}
        bucket=targets.setdefault(digest,[])
        if item not in bucket:bucket.append(item)
    for row in catalog['tables']['chars']:
        skin=row.get('skin_id') or row['id']
        if type(skin) is not int or skin<=0:continue
        add('characters',skin,f'cb/cb{skin:04d}.png',f'characters/{skin%100:02d}/{skin}.webp')
    for row in catalog['tables']['stage_groups']:
        name=row.get('banner_file_name')
        if isinstance(name,str) and name:
            digest=name_hash(name);add('quests',name,name,f'quests/{digest[:2].lower()}/{digest}.webp')
    for row in catalog.get('gachaBanners',[]):
        name=row.get('file_name')
        if isinstance(name,str) and name:add('gachas',name,name,f'gachas/{name_hash(name)}.webp')
    return targets

def sync_assets(catalog,resources,seed,site,manifest,state,opener=urllib.request.urlopen):
    site=Path(site)
    manifest=json.loads(json.dumps(manifest))
    old_sources=state.get('images',{})
    previous=state.get('resources',{})
    state={'schemaVersion':1,'resources':{},'images':dict(old_sources)}
    budget=TransferBudget()
    targets=image_targets(catalog)
    unique={digest:items[0] for digest,items in targets.items() if len(items)==1}
    failures=[];readers={};records={}
    packages=image_resources(resources)
    def index(row):
        path=row['path'];fingerprint=package_identity(row)
        if previous.get(path,{}).get('fingerprint')==fingerprint:return path,previous[path],None,None
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
                if digest in unique and digest not in providers:providers[digest]=path
    requests={};missing={};reused=0
    for digest,target in unique.items():
        category,identity=target['category'],target['identity'];path=providers.get(digest)
        manifest.setdefault(category,{})
        existing=manifest[category].get(identity)
        existing_file=site/existing if isinstance(existing,str) and re.fullmatch(r'assets/[A-Za-z0-9_./-]+',existing) and '..' not in existing.split('/') else None
        source_key=category+':'+identity
        if path:
            fingerprint=state['resources'][path]['fingerprint']
            if existing_file and existing_file.is_file() and (source_key not in old_sources or old_sources[source_key]==fingerprint):
                state['images'][source_key]=fingerprint;reused+=1
            else:requests.setdefault(path,[]).append(target)
        elif not existing_file or not existing_file.is_file():missing[source_key]='pending' if failures else 'not-located'
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
                manifest.setdefault('imageVersions',{})[relative]=target['imageDigest'][:16]
                state['images'][target['category']+':'+target['identity']]=state['resources'][path]['fingerprint'];updated+=1
            done={target['category']+':'+target['identity'] for target in completed}
            for target in requests[path]:
                key=target['category']+':'+target['identity']
                if key not in done:missing[key]='download-or-decode-error'
    for error in failures:
        if error.get('asset'):missing[error['asset']]='download-or-decode-error'
    for digest,items in targets.items():
        if len(items)>1:
            for target in items:missing[target['category']+':'+target['identity']]='ambiguous-filename-hash'
    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest['counts']={key:len(manifest.get(key,{})) for key in ['characters','quests','gachas','gimmicks','attributes']}
    manifest['sync']={'state':'partial' if failures else 'success','lastAttemptAt':timestamp,'lastSuccessAt':manifest.get('sync',{}).get('lastSuccessAt') if failures else timestamp,'updatedImages':updated,'reusedImages':reused,'indexedPackages':len(state['resources']),'packageCount':len(packages),'downloadedBytes':budget.used,'unlocatedImages':len(missing),'failures':failures}
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
    manifest=json.loads((data/'assets.json').read_text(encoding='utf-8'))
    index=data/'asset-index.json'
    state=json.loads(index.read_text(encoding='utf-8')) if index.exists() else {}
    resources=master_manifest(configured_game()).get('resources')
    if not isinstance(resources,list) or not resources:raise ValueError('Game asset manifest missing')
    manifest,state=sync_assets(catalog,resources,seed,site,manifest,state)
    for name,value in [('assets.json',manifest),('asset-index.json',state)]:
        target=data/name;temporary=target.with_suffix('.json.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')),encoding='utf-8');os.replace(temporary,target)
    print(json.dumps(manifest['sync'],ensure_ascii=False))
    if manifest['sync']['state']!='success':raise SystemExit(1)

if __name__=='__main__':
    try:main()
    except Exception as error:
        target=Path(__file__).resolve().parents[1]/'data'/'assets.json'
        manifest=json.loads(target.read_text(encoding='utf-8'))
        previous=manifest.get('sync',{})
        manifest['sync']={'state':'error','lastAttemptAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'lastSuccessAt':previous.get('lastSuccessAt'),'errorType':type(error).__name__}
        temporary=target.with_suffix('.json.tmp');temporary.write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')),encoding='utf-8');os.replace(temporary,target)
        print(json.dumps(manifest['sync']))
        raise SystemExit(1)
