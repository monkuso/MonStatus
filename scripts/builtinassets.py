import hashlib
import io
import json
import plistlib
from pathlib import Path
import re
import zipfile
from PIL import Image
from assetcodec import decode
from atlasassets import frame_png
from visualassets import image_names,is_visual_field

ATTRIBUTE_FRAMES={1:'monsterwindow_fire.png',2:'monsterwindow_water.png',3:'monsterwindow_wood.png',4:'monsterwindow_light.png',5:'monsterwindow_dark.png'}


def extract_character_frames(apks,seed,site):
    site=Path(site)
    with zipfile.ZipFile(apks) as package:
        with zipfile.ZipFile(io.BytesIO(package.read('base.apk'))) as base:
            raw=decode(base.read('assets/data/BAB6B052'),seed)
            plist=plistlib.loads(re.sub(br'<!DOCTYPE[^>]*>',b'',raw.rstrip(b'\0'),flags=re.S))
            sheet=Image.open(io.BytesIO(decode(base.read('assets/data/E2B56297'),seed))).convert('RGBA')
    result={'schemaVersion':1,'gameVersion':'33.0.0','characterFrames':{}}
    for attribute,name in ATTRIBUTE_FRAMES.items():
        png=frame_png(sheet,plist['frames'][name]);relative=f'assets/character-frames/33.0.0/{attribute}.webp';target=site/relative;target.parent.mkdir(parents=True,exist_ok=True)
        with Image.open(io.BytesIO(png)) as frame:frame.save(target,format='WEBP',lossless=True)
        result['characterFrames'][str(attribute)]={'path':relative,'frame':name,'width':120,'height':120,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    destination=site/'config'/'builtin-assets.json';destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def register_builtin_images(site,manifest):
    site=Path(site);configuration=site/'config'/'builtin-assets.json'
    if not configuration.is_file():return
    entries=json.loads(configuration.read_text(encoding='utf-8'))
    for attribute,entry in entries['characterFrames'].items():
        relative=entry['path']
        if not re.fullmatch(r'assets/character-frames/[0-9.]+/[0-9]+\.webp',relative):raise ValueError('Builtin image path rejected')
        raw=(site/relative).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Builtin image checksum mismatch')
        manifest.setdefault('characterFrames',{})[attribute]=relative;manifest.setdefault('imageVersions',{})[relative]=entry['sha256'][:16]
    for category in ['items','events']:
        for name,entry in entries.get(category,{}).items():
            if name in manifest.get(category,{}) or name in manifest.get('itemVariants' if category=='items' else 'eventVariants',{}):continue
            relative=entry['path']
            if not re.fullmatch(r'assets/builtin/[0-9.]+/(items|events)/[a-f0-9]{24}\.webp',relative):raise ValueError('Builtin image path rejected')
            raw=(site/relative).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Builtin image checksum mismatch')
            manifest.setdefault(category,{})[name]=relative;manifest.setdefault('imageVersions',{})[relative]=entry['sha256'][:16];manifest.setdefault('pending',{}).pop(category+':'+name,None)


def extract_catalog_images(apks,seed,site):
    site=Path(site);configuration=site/'config'/'builtin-assets.json';result=json.loads(configuration.read_text(encoding='utf-8'))
    index=json.loads((site/'data/internal/index.json').read_text(encoding='utf-8'));wanted={'items':set(),'events':set()}
    for name,entry in index['tables'].items():
        if name!='items' and not any(is_visual_field(field) for field in entry['fields']):continue
        for part in entry['chunks']:
            raw=(site/'data/internal'/part['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=part['sha256']:raise ValueError('Builtin master checksum mismatch')
            for row in json.loads(raw)['rows']:
                if name=='items':
                    if row.get('image_name'):wanted['items'].add(row['image_name'])
                else:
                    wanted['events'].update(image_names(row))
    with zipfile.ZipFile(apks) as package:
        with zipfile.ZipFile(io.BytesIO(package.read('base.apk'))) as base:
            for plist_hash,png_hash in [('BAB6B052','E2B56297'),('198483BA','6A84E770')]:
                descriptor=plistlib.loads(re.sub(br'<!DOCTYPE[^>]*>',b'',decode(base.read('assets/data/'+plist_hash),seed).rstrip(b'\0'),flags=re.S))
                with Image.open(io.BytesIO(decode(base.read('assets/data/'+png_hash),seed))) as source:
                    sheet=source.convert('RGBA')
                    for category,names in wanted.items():
                        for name in names&descriptor['frames'].keys():
                            png=frame_png(sheet,descriptor['frames'][name]);relative='assets/builtin/'+result['gameVersion']+'/'+category+'/'+hashlib.sha256(name.encode()).hexdigest()[:24]+'.webp';target=site/relative;target.parent.mkdir(parents=True,exist_ok=True)
                            with Image.open(io.BytesIO(png)) as frame:frame.save(target,format='WEBP',lossless=True)
                            digest=hashlib.sha256(target.read_bytes()).hexdigest();previous=result.setdefault(category,{}).get(name)
                            if previous and previous['sha256']!=digest:raise ValueError('Builtin atlas frame ambiguity')
                            result[category][name]={'path':relative,'sha256':digest,'atlasHash':plist_hash,'textureHash':png_hash}
    configuration.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {category:len(result.get(category,{})) for category in wanted}
