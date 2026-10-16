import hashlib
import io
import json
import os
import plistlib
import re
import uuid
from PIL import Image
from assetcodec import name_hash,write_image

ATLAS_NAMES=('cp_again','cp_favorite_317','fountain_cmn','journey','kyuri_2_sub2','nevada_all','nibu_itemga','ocean','sazae_2_sub2_cmn','seesaw_c','ui_items','wallbreak','wonder_all','yatai_1_sub1')


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


def sync_item_atlases(rows,read,providers,site,manifest,state,missing):
    wanted={row['image_name'] for row in rows if isinstance(row.get('image_name'),str) and row['image_name'].endswith('.png')}
    manifest.setdefault('items',{});selections={};ambiguous=set();failures=[];updated=0
    for base in ATLAS_NAMES:
        plist_hash=name_hash('dlme/'+base+'.plist');png_hash=name_hash('dlme/'+base+'.png')
        if plist_hash not in providers or png_hash not in providers:continue
        sources=[providers[plist_hash],providers[png_hash]]
        fingerprint=hashlib.sha256(json.dumps([state['resources'][path]['fingerprint'] for path in sources],sort_keys=True).encode()).hexdigest()
        try:
            plist=plistlib.loads(re.sub(br'<!DOCTYPE[^>]*>',b'',read(sources[0],plist_hash).rstrip(b'\0'),flags=re.S));frames=plist['frames'];selected=wanted&frames.keys()
            if not selected:continue
            with Image.open(io.BytesIO(read(sources[1],png_hash))) as image:
                if max(image.size)>4096:raise ValueError('Atlas image dimensions rejected')
                sheet=image.convert('RGBA')
                for name in selected:
                    plain=frame_png(sheet,frames[name]);digest=hashlib.sha256(plain).hexdigest()
                    if name in selections and selections[name][1]!=digest:ambiguous.add(name)
                    else:selections[name]=(plain,digest,fingerprint)
        except Exception as error:failures.append({'atlas':base,'errorType':type(error).__name__})
    for name,(plain,digest,fingerprint) in selections.items():
        if name in ambiguous:missing['items:'+name]='ambiguous-atlas-frame';continue
        relative=manifest['items'].get(name) or 'assets/items/'+hashlib.sha256(name.encode()).hexdigest()[:24]+'.webp'
        if not isinstance(relative,str) or not re.fullmatch(r'assets/items/[a-f0-9]+\.webp',relative):relative='assets/items/'+hashlib.sha256(name.encode()).hexdigest()[:24]+'.webp'
        destination=site/relative
        if state['images'].get('items:'+name)!=fingerprint or not destination.is_file():
            destination.parent.mkdir(parents=True,exist_ok=True);temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
            try:write_image(plain,temporary);os.replace(temporary,destination);updated+=1
            finally:
                if temporary.exists():temporary.unlink()
        manifest['items'][name]=relative;manifest.setdefault('imageVersions',{})[relative]=digest[:16];state['images']['items:'+name]=fingerprint
    for row in rows:
        name=row.get('image_name')
        if name in manifest['items'] and name not in ambiguous:manifest['items'][str(row['id'])]=manifest['items'][name]
        elif name and str(row['id']) not in manifest['items']:missing['items:'+str(row['id'])]='ambiguous-atlas-frame' if name in ambiguous else 'not-located'
    return updated,failures
