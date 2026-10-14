"""Verified version-6 signatures for a bounded set of game read endpoints."""
import base64
import hashlib
import msgpack
import urllib.parse
import urllib.request

HEADER_NAMES = {'content-type','user-agent','x-ds-eit','x-ds-session','x-ds-requesthash-ver'}
READ_PATHS = {'/user/get','/information/list','/master/version','/char/recommend'}


class GameReadError(Exception):
    def __init__(self, code=None):
        self.code = code
        super().__init__('Game read did not return a verified response')


def signed_headers(config, route):
    parsed = urllib.parse.urlsplit(route)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path not in READ_PATHS:
        raise ValueError('Read route rejected')
    seed = base64.b64decode(config['signing_seed_b64'], validate=True)
    if len(seed) != 20:
        raise ValueError('Signing material layout mismatch')
    sig_version = str(config.get('signing_version', 6))
    raw = route.encode('ascii')
    material = seed + b' ' + raw + b' ' + sig_version.encode('ascii')
    if b'?' in raw:
        material += b' ' + raw.split(b'?', 1)[1]
    material += b' ' + seed
    headers = {key.lower(): value for key, value in config['headers'].items() if key.lower() in HEADER_NAMES}
    if not headers.get('x-ds-session'):
        raise ValueError('Game read session missing')
    headers['x-ds-requesthash-ver'] = sig_version
    headers['x-ds-requesthash'] = hashlib.sha256(material).hexdigest()
    return headers


def read_game(config, route):
    request = urllib.request.Request('https://api.monster-strike.com' + route,
                                     headers=signed_headers(config, route), method='GET')
    with urllib.request.urlopen(request, timeout=25) as response:
        body = response.read(8 * 1024 * 1024 + 1)
        if response.status != 200 or len(body) > 8 * 1024 * 1024:
            raise GameReadError()
    result = msgpack.unpackb(body, raw=False, strict_map_key=False)
    if not isinstance(result, dict) or result.get('result') != 0:
        raise GameReadError(result.get('result') if isinstance(result, dict) else None)
    return result
