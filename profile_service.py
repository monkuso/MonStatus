"""Public friend profiles only; credentials and raw responses stay server-side."""
import collections
import datetime
import json
import os
from pathlib import Path
import re
import threading
import time
from game_protocol import read_game, GameReadError

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
CACHE = collections.OrderedDict()
REQUESTS = collections.defaultdict(collections.deque)
CHARACTERS = None
IMAGES = None


def normalize_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:\d{9}|\d{12})', value, flags=re.ASCII) or int(value) == 0:
        raise ValueError('IDは9桁または12桁の数字で入力してください。')
    return value


def character_info(value):
    global CHARACTERS, IMAGES
    if not isinstance(value, dict) or type(value.get('char_id')) is not int or value['char_id'] <= 0:
        return None
    with LOCK:
        if CHARACTERS is None:
            catalog = json.loads((ROOT / 'catalog.json').read_text(encoding='utf-8'))
            CHARACTERS = {row['id']: {key: row.get(key) for key in ['id','name','rarity','attribute_id','skin_id']} for row in catalog['tables']['chars']}
            IMAGES = json.loads((ROOT / 'assets.json').read_text(encoding='utf-8'))['characters']
    row = CHARACTERS.get(value['char_id'])
    result = {'id': value['char_id'], 'level': value.get('level') if type(value.get('level')) is int else None}
    if row:
        result.update({'name': row['name'], 'rarity': row['rarity'], 'attributeId': row['attribute_id']})
        image = IMAGES.get(str(row['skin_id'] or row['id']))
        if image and re.fullmatch(r'assets/characters/\d+\.webp', image):
            result['imagePath'] = image
    return result


def public_profile(user, invitation_id):
    if not isinstance(user, dict) or user.get('invitation_id') != int(invitation_id):
        raise LookupError('該当するプレイヤーが見つかりませんでした。')
    if not isinstance(user.get('name'), str) or type(user.get('rank')) is not int:
        raise GameReadError()
    units = []
    main = character_info(user.get('charball'))
    if main:
        units.append(main)
    for row in user.get('attribute_helper_user_charballs', []):
        unit = character_info(row)
        if unit and unit['id'] not in {entry['id'] for entry in units}:
            units.append(unit)
    result = {'schemaVersion': 1, 'playerId': str(user['invitation_id']), 'name': user['name'],
              'rank': user['rank'], 'characters': units, 'source': 'game-public-friend-profile',
              'fetchedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    played = user.get('played_at')
    if type(played) is int and played > 0:
        result['lastPlayedHoursAgo'] = max(0, int((time.time() - played) // 3600))
    return result


def lookup(invitation_id):
    now = time.monotonic()
    with LOCK:
        cached = CACHE.get(invitation_id)
        if cached and now - cached[0] < 600:
            CACHE.move_to_end(invitation_id)
            return cached[1]
    config = json.loads(os.environ['MS_PROFILE_CONFIG'])
    try:
        response = read_game(config, '/user/get?invitation_id=' + str(int(invitation_id)))
    except GameReadError as error:
        if error.code == 6:
            raise LookupError('該当するプレイヤーが見つかりませんでした。') from None
        raise
    result = public_profile(response.get('user'), invitation_id)
    with LOCK:
        CACHE[invitation_id] = (time.monotonic(), result)
        while len(CACHE) > 512:
            CACHE.popitem(last=False)
    return result


def allow_request(address):
    now = time.monotonic()
    with LOCK:
        if len(REQUESTS) >= 2048:
            for key in list(REQUESTS):
                if key != 'global' and (not REQUESTS[key] or REQUESTS[key][-1] <= now - 60):
                    del REQUESTS[key]
            if address not in REQUESTS and len(REQUESTS) >= 2048:
                return False
        for key, limit in [(address, 20), ('global', 100)]:
            queue = REQUESTS[key]
            while queue and queue[0] <= now - 60:
                queue.popleft()
            if len(queue) >= limit:
                return False
        REQUESTS[address].append(now)
        REQUESTS['global'].append(now)
        if len(REQUESTS) > 2048:
            for key in list(REQUESTS):
                if key != 'global' and (not REQUESTS[key] or REQUESTS[key][-1] < now - 60):
                    del REQUESTS[key]
        return True


def app(environ, start_response):
    origin = environ.get('HTTP_ORIGIN', '')
    allowed_origin = os.environ.get('PROFILE_ALLOWED_ORIGIN', 'https://monkuso.github.io')
    headers = [('Content-Type','application/json; charset=utf-8'),('Vary','Origin'),
               ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]
    if origin == allowed_origin:
        headers.append(('Access-Control-Allow-Origin', allowed_origin))
    def respond(status, value):
        body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        start_response(status, [*headers, ('Content-Length', str(len(body)))])
        return [body]
    if origin and origin != allowed_origin:
        return respond('403 Forbidden', {'error':'このサイトからの検索には対応していません。'})
    if environ.get('REQUEST_METHOD') == 'OPTIONS':
        headers.extend([('Access-Control-Allow-Methods','GET, OPTIONS'),('Access-Control-Allow-Headers','Accept')])
        return respond('200 OK', {})
    if environ.get('REQUEST_METHOD') != 'GET':
        return respond('405 Method Not Allowed', {'error':'読み取り検索のみ対応しています。'})
    path = environ.get('PATH_INFO', '')
    if path in {'/','/health'}:
        return respond('200 OK', {'status':'ok','configured':bool(os.environ.get('MS_PROFILE_CONFIG'))})
    if not path.startswith('/api/profiles/'):
        return respond('404 Not Found', {'error':'検索先が見つかりません。'})
    try:
        invitation_id = normalize_id(path.removeprefix('/api/profiles/'))
    except ValueError as error:
        return respond('400 Bad Request', {'error':str(error)})
    if not allow_request(environ.get('HTTP_X_FORWARDED_FOR',environ.get('REMOTE_ADDR','unknown')).split(',')[0].strip()):
        headers.append(('Retry-After','60'))
        return respond('429 Too Many Requests', {'error':'検索が集中しています。少し待って再試行してください。'})
    if not os.environ.get('MS_PROFILE_CONFIG'):
        return respond('503 Service Unavailable', {'error':'プレイヤー検索の接続設定を準備中です。'})
    try:
        return respond('200 OK', lookup(invitation_id))
    except LookupError as error:
        return respond('404 Not Found', {'error':str(error)})
    except Exception:
        return respond('503 Service Unavailable', {'error':'ゲーム情報の取得に失敗しました。少し待って再試行してください。'})


if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    make_server('127.0.0.1', int(os.environ.get('PORT','8810')), app).serve_forever()
