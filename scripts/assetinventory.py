import concurrent.futures
import json
import plistlib
from pathlib import Path,PurePosixPath
import re
import zipfile
from xml.parsers.expat import ExpatError
from assetcodec import decode,name_hash


def native_image_paths(reader):
    section=reader.elf.get_section_by_name('.data');data=section.data();paths=set()
    for ending in [b'.png\0',b'.plist\0']:
        for phase in range(128):
            needle=bytes(value^reader.key[(phase+n)&127] for n,value in enumerate(ending));cursor=0
            while True:
                position=data.find(needle,cursor)
                if position<0:break
                cursor=position+1
                for length in [phase,phase+128,phase+256]:
                    start=position-length
                    if start<0:continue
                    raw=data[start:position+len(ending)];plain=bytes(value^reader.key[n&127] for n,value in enumerate(raw))
                    try:text=plain.rstrip(b'\0').decode('ascii')
                    except UnicodeError:continue
                    if re.fullmatch(r'[A-Za-z0-9_./@-]+\.(png|plist)',text) and '..' not in text.split('/'):paths.add(text)
    return paths


def header_kind(raw,seed):
    prefix=decode(raw[:128],seed).lstrip()
    if prefix.startswith(b'\x89PNG\r\n\x1a\n'):return 'png'
    if prefix.startswith((b'<?xml',b'<plist',b'bplist00')):return 'xml'
    return 'other'


def parse_atlas(raw):
    value=plistlib.loads(re.sub(br'<!DOCTYPE[^>]*>',b'',raw.rstrip(b'\0'),flags=re.S))
    return value if isinstance(value,dict) and isinstance(value.get('frames'),dict) and isinstance(value.get('metadata'),dict) else None


def build_registry(root,site,seed,plist_paths=(),png_paths=()):
    root=Path(root);site=Path(site);kinds={};atlas_hashes=set();count=0
    sources=[path for path in (root/'Data').glob('*') if path.is_file() and zipfile.is_zipfile(path)]
    apk=root/'analysis'/'v33'/'apk-build-02'/'base.apk'
    if apk.is_file():sources.append(apk)
    for path in sources:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                digest=PurePosixPath(entry.filename).name.upper()
                if not re.fullmatch(r'[A-F0-9]{8}',digest):continue
                by_crc=kinds.setdefault(digest,{})
                if str(entry.CRC) in by_crc:continue
                with archive.open(entry) as stream:prefix=stream.read(128)
                kind=header_kind(prefix,seed)
                if kind=='xml':
                    try:
                        value=parse_atlas(decode(archive.read(entry),seed))
                        if value:kind='atlas';atlas_hashes.add(digest)
                        else:kind='other'
                    except (ValueError,IndexError,ExpatError,plistlib.InvalidFileException):kind='xml-invalid'
                by_crc[str(entry.CRC)]=kind;count+=1
    value={'schemaVersion':1,'memberKinds':kinds,'atlasHashes':sorted(atlas_hashes),'plistPaths':sorted(set(plist_paths)),'pngPaths':sorted(set(png_paths))}
    target=site/'config'/'asset-inventory.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'members':len(kinds),'versions':count,'atlasHashes':len(atlas_hashes)}


def png_candidates(atlas_hash,metadata,registry,providers):
    virtuals=[p for p in registry.get('plistPaths',[]) if name_hash(p)==atlas_hash]
    directories={str(PurePosixPath(p).parent) for p in [*registry.get('plistPaths',[]),*registry.get('pngPaths',[])]}
    names={str(metadata[key]) for key in ['textureFileName','realTextureFileName'] if metadata.get(key)}
    paths=set(names)
    for name in names:
        for virtual in virtuals:paths.add(str(PurePosixPath(virtual).parent/name))
        for directory in directories:paths.add(str(PurePosixPath(directory)/name))
        paths.update(p for p in registry.get('pngPaths',[]) if PurePosixPath(p).name==PurePosixPath(name).name)
    return sorted({name_hash(path) for path in paths if name_hash(path) in providers})


def discover_atlases(packages,states,open_archive,seed,registry,wanted):
    results=[];failures=[]
    def scan(resource):
        path=resource['path'];state=states[path]
        if state.get('availability')=='not-distributed':return [],[]
        inventory=state.setdefault('headerKinds',{});descriptors=state.setdefault('atlases',{});errors=[]
        if state.get('atlasScanComplete') and all(all(name in item['frames'] for name in wanted&set(item['names'])) for item in descriptors.values()):return list(descriptors.values()),[]
        try:
            with open_archive(path) as archive:
                password=resource.get('password','');password=password.encode() if isinstance(password,str) else password
                for entry in archive.infolist():
                    digest=PurePosixPath(entry.filename).name.upper()
                    if digest not in state['members']:continue
                    kind=inventory.get(digest) or registry.get('memberKinds',{}).get(digest,{}).get(str(entry.CRC))
                    if kind is None:
                        with archive.open(entry,pwd=password or None) as stream:kind=header_kind(stream.read(128),seed)
                    inventory[digest]=kind
                    if kind not in {'atlas','xml'}:continue
                    cached=descriptors.get(digest)
                    if cached and all(name in cached['frames'] for name in wanted&set(cached['names'])):continue
                    if entry.file_size>16*1024*1024:raise ValueError('Atlas descriptor size rejected')
                    try:value=parse_atlas(decode(archive.read(entry,pwd=password or None),seed))
                    except (ValueError,IndexError,ExpatError,plistlib.InvalidFileException):inventory[digest]='xml-invalid';continue
                    if value is None:inventory[digest]='other';continue
                    inventory[digest]='atlas';frames=value['frames'];descriptors[digest]={'hash':digest,'package':path,'metadata':value['metadata'],'names':sorted(frames),'frames':{name:frame for name,frame in frames.items() if name in wanted}}
            state['atlasScanComplete']=True
        except Exception as error:errors.append({'package':path,'phase':'atlas-discovery','errorType':type(error).__name__})
        return list(descriptors.values()),errors
    available=[row for row in packages if row['path'] in states]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for found,errors in pool.map(scan,available):results.extend(found);failures.extend(errors)
    return results,failures
