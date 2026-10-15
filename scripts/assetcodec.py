import io
import struct
from PIL import Image

def mix(a, b, c):
    for target, left, right, shift, direction in (
        ('a', 'b', 'c', 13, 'r'), ('b', 'c', 'a', 8, 'l'), ('c', 'a', 'b', 13, 'r'),
        ('a', 'b', 'c', 12, 'r'), ('b', 'c', 'a', 16, 'l'), ('c', 'a', 'b', 5, 'r'),
        ('a', 'b', 'c', 3, 'r'), ('b', 'c', 'a', 10, 'l'), ('c', 'a', 'b', 15, 'r'),
    ):
        values = {'a': a, 'b': b, 'c': c}
        value = (values[target] - values[left] - values[right]) & 0xFFFFFFFF
        value = (value ^ (values[right] >> shift if direction == 'r' else values[right] << shift)) & 0xFFFFFFFF
        if target == 'a':
            a = value
        elif target == 'b':
            b = value
        else:
            c = value
    return a, b, c

def name_hash(name):
    data = name.encode('utf-8')
    a = b = 0x9E3779B9
    c = 0xFEEDBEEF
    cursor = 0
    while len(data) - cursor >= 12:
        x, y, z = struct.unpack_from('<III', data, cursor)
        a, b, c = mix((a + x) & 0xFFFFFFFF, (b + y) & 0xFFFFFFFF, (c + z) & 0xFFFFFFFF)
        cursor += 12
    c = (c + len(data)) & 0xFFFFFFFF
    for index, byte in enumerate(data[cursor:]):
        if index < 4:
            a = (a + (byte << (index * 8))) & 0xFFFFFFFF
        elif index < 8:
            b = (b + (byte << ((index - 4) * 8))) & 0xFFFFFFFF
        else:
            c = (c + (byte << ((index - 7) * 8))) & 0xFFFFFFFF
    return f'{mix(a, b, c)[2]:08X}'

def decode(data, initial):
    if data.startswith((b'\x89PNG\r\n\x1a\n', b'<?xml', b'<plist')):
        return data
    x, y, z, w = initial
    output = bytearray(len(data))
    for offset in range(0, len(data), 4):
        t = (x ^ (x << 11)) & 0xFFFFFFFF
        x, y, z = y, z, w
        w = (w ^ (w >> 19) ^ t ^ (t >> 8)) & 0xFFFFFFFF
        key = struct.pack('<I', w)
        for index, value in enumerate(data[offset:offset + 4]):
            output[offset + index] = value ^ key[index]
    return bytes(output)

def write_image(data, target):
    with Image.open(io.BytesIO(data)) as image:
        if image.width > 4096 or image.height > 4096:
            raise ValueError('画像寸法の上限を超えています')
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        image.convert('RGBA').save(target, format='WEBP', quality=88, method=4)
