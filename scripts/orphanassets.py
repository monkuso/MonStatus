import hashlib
import io
import json
import zipfile
from pathlib import Path
from PIL import Image
from assets import ROOT,DESTINATION,decode,name_hash,seed_material,write_image

CANDIDATES={3269:'data62.bin',5078:'data1300.bin',5674:'data1306.bin',9855:'data75.bin',24506:'data1445.bin',50000:'data2300.bin',50001:'data2300.bin',50002:'data2300.bin',50003:'data2300.bin',50004:'data2300.bin',50005:'data2300.bin',50006:'data2300.bin',50007:'data2300.bin',92400:'data84.bin'}

def main():
    catalog=json.loads((DESTINATION/'data'/'catalog.json').read_text(encoding='utf-8'))
    referenced={row.get('skin_id') or row['id'] for row in catalog['tables']['chars']}
    assets=json.loads((DESTINATION/'data'/'assets.json').read_text(encoding='utf-8'))
    known={}
    for category in ['quests','gachas']:
        for name in assets.get(category,{}):
            if not name.isdigit():known.setdefault(name_hash(name),[]).append({'category':category,'resourceName':name})
    seed=seed_material()
    target=DESTINATION/'assets'/'internal'
    target.mkdir(parents=True,exist_ok=True)
    rows=[]
    for skin,package in CANDIDATES.items():
        virtual=f'cb/cb{skin:04d}.png'
        digest=name_hash(virtual)
        with zipfile.ZipFile(ROOT/'Data'/package) as archive:
            entries=[entry for entry in archive.infolist() if Path(entry.filename).name.upper()==digest]
            if len(entries)!=1:raise ValueError('Asset identity mismatch')
            plain=decode(archive.read(entries[0]),seed)
        if not plain.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('PNG signature mismatch')
        with Image.open(io.BytesIO(plain)) as image:
            image.load()
            width,height=image.size
        write_image(plain,target/f'{skin}.webp')
        rows.append({'id':skin,'name':f'名前ハッシュ候補 {skin}','image':f'assets/internal/{skin}.webp','resourceNameCandidate':virtual,'identityConfidence':'filename-hash-match','otherKnownReferences':known.get(digest,[]),'member':digest,'package':package,'width':width,'height':height,'sha256':hashlib.sha256(plain).hexdigest(),'referencedByCharacter':skin in referenced,'status':'decoded-png-verified'})
    (DESTINATION/'data'/'orphanassets.json').write_text(json.dumps({'schemaVersion':1,'source':'local-game-asset-packages','scannedUniqueMembers':76666,'characterNameRange':[1,100000],'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'verifiedImages':len(rows),'unreferenced':sum(not row['referencedByCharacter'] for row in rows),'dimensions':sorted({(row['width'],row['height']) for row in rows})}))

if __name__=='__main__':main()
