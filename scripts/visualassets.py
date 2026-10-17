import re


def is_visual_field(field):
    return bool(re.search(r'(?:^|_)(?:image|texture|icon|banner|file)(?:_|$)',field))


def image_names(row):
    names=[]
    for field,value in row.items():
        if not is_visual_field(field) or not isinstance(value,str):continue
        for name in value.split('|'):
            if re.fullmatch(r'[A-Za-z0-9_./@-]+\.png',name) and '..' not in name.split('/') and name not in names:names.append(name)
    return names
