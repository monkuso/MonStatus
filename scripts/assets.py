import hashlib
import io
import json
import plistlib
import re
import struct
import sys
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image
from assetcodec import name_hash,decode,write_image

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'analysis'))
from decode_static_strings import StaticStrings

def seed_material():
    reader = StaticStrings()
    try:
        encrypted = reader.read(0x91252F0, 16)
        plain = bytes(a ^ b for a, b in zip(encrypted, reader.key[:16]))
        return struct.unpack('<IIII', plain)
    finally:
        reader.close()

def parse_plist(data):
    data = re.sub(br'<!DOCTYPE[^>]*>', b'', data.rstrip(b'\0'), flags=re.S)
    return plistlib.loads(data)

def main():
    expected = {'cb/cb0001.png': 'DD0CB6BD', 'cb/cb0100.png': '14A0589A', 'pb/pb0001.png': '396B5EB5', 'ba_stage950040.png': '3EB2DC91'}
    if any(name_hash(name) != value for name, value in expected.items()):
        raise ValueError('ゲーム内ファイル名hashの既知ベクトル不一致')
    with urllib.request.urlopen('https://monkuso.github.io/MonStatus/catalog.json', timeout=30) as response:
        catalog = json.load(response)
    seed = seed_material()
    manifest = {'schemaVersion': 1, 'characters': {}, 'quests': {}, 'gachas': {}, 'gimmicks': {}, 'attributes': {},
                'provenance': {'source': 'game-asset-packages', 'filenameHash': 'Jenkins lookup2', 'characterPath': 'cb/cb%04d.png', 'skinSelector': 'skin_id or id'}}
    targets = {}
    skins = {row.get('skin_id') or row['id'] for row in catalog['tables']['chars']}
    for skin in skins:
        targets[name_hash(f'cb/cb{skin:04d}.png')] = ('characters', str(skin), f'characters/{skin % 100:02d}/{skin}.webp')
    for group in catalog['tables']['stage_groups']:
        name = group.get('banner_file_name')
        if name:
            digest = name_hash(name)
            targets[digest] = ('quests', name, f'quests/{digest[:2].lower()}/{digest}.webp')
    for banner in catalog.get('gachaBanners', []):
        name = banner.get('file_name')
        if name and name_hash(name) not in targets:
            targets[name_hash(name)] = ('gachas', name, f'gachas/{name_hash(name)}.webp')
    assets = DESTINATION / 'assets'
    for folder in ['characters', 'quests', 'gimmicks', 'gachas']:
        (assets / folder).mkdir(parents=True, exist_ok=True)
    for number, package in enumerate(sorted((ROOT / 'Data').glob('data*.bin'))):
        if not zipfile.is_zipfile(package):
            continue
        with zipfile.ZipFile(package) as archive:
            for entry in archive.infolist():
                key = Path(entry.filename).name.upper()
                selection = targets.get(key)
                if selection is None:
                    continue
                category, identity, relative = selection
                if identity in manifest[category]:
                    continue
                plain = decode(archive.read(entry), seed)
                if not plain.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise ValueError('画像マジック不一致: ' + key)
                write_image(plain, assets / relative)
                manifest[category][identity] = 'assets/' + relative
        if number % 25 == 0:
            print(json.dumps({'packagesVisited': number, 'characters': len(manifest['characters']), 'quests': len(manifest['quests'])}), flush=True)
    apks = sorted(ROOT.glob('モンスト_*.apks'))
    if not apks:
        raise FileNotFoundError('モンスト_*.apks が見つかりません')
    with zipfile.ZipFile(apks[-1]) as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read('base.apk'))) as base:
            plist = parse_plist(decode(base.read('assets/data/198483BA'), seed))
            sheet = Image.open(io.BytesIO(decode(base.read('assets/data/6A84E770'), seed))).convert('RGBA')
            attr_plist = parse_plist(decode(base.read('assets/data/BAB6B052'), seed))
            attr_sheet = Image.open(io.BytesIO(decode(base.read('assets/data/E2B56297'), seed))).convert('RGBA')
    (assets / 'attributes').mkdir(parents=True, exist_ok=True)
    for key, aid in {'not': 0, 'fire': 1, 'ice': 2, 'plant': 3, 'light': 4, 'dark': 5}.items():
        frame = attr_plist['frames'].get(f'attribute_icon_{key}.png')
        if not frame:
            continue
        x, y, w, h = map(int, re.findall(r'-?\d+', frame['frame']))
        sx, sy, _, _ = map(int, re.findall(r'-?\d+', frame['sourceColorRect']))
        sw, sh = map(int, re.findall(r'-?\d+', frame['sourceSize']))
        piece = attr_sheet.crop((x, y, x + w, y + h))
        if frame.get('rotated'):
            piece = piece.rotate(90, expand=True)
        canvas = Image.new('RGBA', (sw, sh))
        canvas.paste(piece, (sx, sy))
        canvas.save(assets / 'attributes' / f'{aid}.webp', format='WEBP', lossless=True)
        manifest['attributes'][str(aid)] = f'assets/attributes/{aid}.webp'
    labels = {2: 'gb', 1: 'dw', 4: 'warp', 24: 'bomb', 32: 'block', 64: 'magic', 128: 'wind',
              256: 'speeddown', 2048: 'transfer', 4096: 'speeddown_floor', 512: 'attacktype', 1024: 'attacktype2'}
    for mask, suffix in labels.items():
        frame = plist['frames'][f'icon_gimmick_{suffix}.png']
        if frame.get('rotated'):
            raise ValueError('ギミックframeに未検証の回転があります')
        x, y, w, h = map(int, re.findall(r'-?\d+', frame['frame']))
        sx, sy, _, _ = map(int, re.findall(r'-?\d+', frame['sourceColorRect']))
        sw, sh = map(int, re.findall(r'-?\d+', frame['sourceSize']))
        canvas = Image.new('RGBA', (sw, sh))
        canvas.paste(sheet.crop((x, y, x + w, y + h)), (sx, sy))
        path = assets / 'gimmicks' / f'{mask}.webp'
        canvas.save(path, format='WEBP', lossless=True)
        manifest['gimmicks'][str(mask)] = f'assets/gimmicks/{mask}.webp'
    manifest['counts'] = {key: len(manifest[key]) for key in ['characters', 'quests', 'gachas', 'gimmicks', 'attributes']}
    manifest['provenance']['assetSetDigest'] = hashlib.sha256(json.dumps(manifest['counts'], sort_keys=True).encode()).hexdigest()
    (DESTINATION / 'data' / 'assets.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': 'success', **manifest['counts']}), flush=True)

if __name__ == '__main__':
    main()
