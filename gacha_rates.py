"""Parse the official in-game provided-rate text without estimating rates."""
import re


def parse_rates(text):
    text = re.sub(r'\[C\d+:([^\[\]]*)\]', r'\1', text)
    entries = []
    for block in re.findall(r'\[BG_STR:([^\]]+)\]', text):
        fields = dict(part.split(':', 1) for part in block.split('|') if ':' in part)
        name, rate = fields.get('LSTR', ''), fields.get('RSTR', '')
        if name and re.fullmatch(r'\s*\d+(?:\.\d+)?\s*%\s*', rate):
            entries.append({'name': name, 'rate': rate.strip(), 'kind': 'total' if name.startswith('★') else 'individual'})
    if not entries:
        for name, rate in re.findall(r'＜([^＞]+)＞\s*(\d+(?:\.\d+)?\s*%)', text):
            entries.append({'name': name, 'rate': rate, 'kind': 'total'})
    plain = re.sub(r'\[BG_STR:[^\]]*\]', '', text)
    plain = re.sub(r'\[LF(?:-?\d+)?\]', '\n', plain)
    plain = re.sub(r'\[(?:C\d+|LC):?([^\]]*)\]', r'\1', plain)
    plain = re.sub(r'\[[^\]]*\]', '', plain)
    plain = re.sub(r'\n{3,}', '\n\n', plain).strip()
    return entries, plain

