import hashlib
import io
import json
import os
import re
import uuid
from PIL import Image
from assetcodec import write_image

def frame_png(sheet,frame):
    numbers=lambda value:list(map(int,re.findall(r'-?\d+',value)))
    rect=numbers(frame['frame']);source=numbers(frame['sourceColorRect']);size=numbers(frame['sourceSize'])
    if len(rect)!=4 or len(source)!=4 or len(size)!=2:raise ValueError('Atlas geometry format rejected')
    x,y,w,h=rect;sx,sy,_,_=source;sw,sh=size
    texture_w,texture_h=(h,w) if frame.get('rotated') else (w,h)
    if min(x,y,sx,sy)<0 or min(w,h,sw,sh)<=0 or max(sw,sh)>4096 or x+texture_w>sheet.width or y+texture_h>sheet.height:raise ValueError('Atlas geometry range rejected')
    piece=sheet.crop((x,y,x+texture_w,y+texture_h))
    if frame.get('rotated'):piece=piece.rotate(90,expand=True)
    if sx+piece.width>sw or sy+piece.height>sh:raise ValueError('Atlas source range rejected')
    canvas=Image.new('RGBA',(sw,sh));canvas.paste(piece,(sx,sy));buffer=io.BytesIO();canvas.save(buffer,format='PNG');return buffer.getvalue()


def sync_atlas_images(rows,event_names,descriptors,read,providers,site,manifest,state,missing,registry):
    from assetinventory import png_candidates
    wanted_items={row['image_name'] for row in rows if isinstance(row.get('image_name'),str) and row['image_name']}
    wanted_events=set(event_names)
    selections={'items':{},'events':{}};failures=[];updated=0;unresolved=[];resolved_families=set()
    for atlas in descriptors:
        family=(atlas['hash'],re.sub(r'_[ns]\.zip$','.zip',atlas['package']))
        if family in resolved_families:continue
        names=set(atlas['frames'])&(wanted_items|wanted_events)
        if not names:continue
        candidates=png_candidates(atlas['hash'],atlas['metadata'],registry,providers);sheets={}
        for digest in candidates:
            try:
                plain=read(providers[digest],digest)
                if not plain.startswith(b'\x89PNG\r\n\x1a\n'):continue
                with Image.open(io.BytesIO(plain)) as image:
                    image.load()
                    if max(image.size)>4096:continue
                    expected=list(map(int,re.findall(r'\d+',str(atlas['metadata'].get('size','')))))
                    if len(expected)==2 and image.size!=tuple(expected):continue
                    sheets[hashlib.sha256(plain).hexdigest()]=(image.convert('RGBA'),digest)
            except (ValueError,OSError):continue
        if len(sheets)!=1:
            unresolved.append({'hash':atlas['hash'],'package':atlas['package'],'texture':atlas['metadata'].get('textureFileName'),'reason':'texture-not-resolved' if not sheets else 'multiple-textures','frames':sorted(names)})
            continue
        sheet,png_hash=next(iter(sheets.values()));png_package=providers[png_hash]
        resolved_families.add(family)
        fingerprint=hashlib.sha256(json.dumps([state['resources'][atlas['package']]['fingerprint'],state['resources'][png_package]['fingerprint']],sort_keys=True).encode()).hexdigest()
        for name in names:
            try:
                plain=frame_png(sheet,atlas['frames'][name]);digest=hashlib.sha256(plain).hexdigest()
                for category,wanted in [('items',wanted_items),('events',wanted_events)]:
                    if name in wanted:selections[category].setdefault(name,{})[digest]=(plain,fingerprint,atlas['hash'])
            except (ValueError,KeyError) as error:failures.append({'atlas':atlas['hash'],'asset':name,'errorType':type(error).__name__})
    for category,by_name in selections.items():
        manifest.setdefault(category,{})
        variants_key='itemVariants' if category=='items' else 'eventVariants'
        manifest.setdefault(variants_key,{})
        for name,variants in by_name.items():
            entries=[]
            for digest,(plain,fingerprint,atlas_hash) in sorted(variants.items()):
                suffix='_'+digest[:16] if len(variants)>1 else ''
                relative='assets/'+category+'/'+hashlib.sha256(name.encode()).hexdigest()[:24]+suffix+'.webp';destination=site/relative;source_key=category+':'+name+':'+digest[:16]
                if state['images'].get(source_key)!=fingerprint or not destination.is_file():
                    destination.parent.mkdir(parents=True,exist_ok=True);temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
                    try:write_image(plain,temporary);os.replace(temporary,destination);updated+=1
                    finally:
                        if temporary.exists():temporary.unlink()
                manifest.setdefault('imageVersions',{})[relative]=digest[:16];state['images'][source_key]=fingerprint
                entries.append({'path':relative,'atlasHash':atlas_hash,'sha256':digest})
            if len(entries)==1:
                manifest[category][name]=entries[0]['path'];manifest[variants_key].pop(name,None);missing.pop(category+':'+name,None)
            else:
                manifest[category].pop(name,None);manifest[variants_key][name]=entries;missing.pop(category+':'+name,None)
    for row in rows:
        name=row.get('image_name')
        if name in manifest.get('items',{}):manifest['items'][str(row['id'])]=manifest['items'][name];missing.pop('items:'+str(row['id']),None)
        elif name in manifest.get('itemVariants',{}):manifest.setdefault('items',{}).pop(str(row['id']),None);missing.pop('items:'+str(row['id']),None)
        elif name and str(row['id']) not in manifest.get('items',{}):missing['items:'+str(row['id'])]='not-located'
    for name in wanted_events:
        if name not in manifest.get('events',{}) and name not in manifest.get('eventVariants',{}):missing.setdefault('events:'+name,'not-located')
    state['unresolvedAtlases']=unresolved
    state['atlasCoverage']={'descriptors':len(descriptors),'itemNames':len(selections['items']),'eventNames':len(selections['events']),'unresolvedTextures':len(unresolved)}
    return updated,failures
