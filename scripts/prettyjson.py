import argparse
import hashlib
import json
import os
from pathlib import Path


def pretty_bytes(value):
    return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')


def format_public_json(directory):
    root=Path(directory);index_file=root/'internal'/'index.json';index=json.loads(index_file.read_text(encoding='utf-8')) if index_file.is_file() else None
    chunks={part['file']:part for table in (index or {}).get('tables',{}).values() for part in table['chunks']}
    count=0
    for file in sorted(root.rglob('*.json')):
        if file==index_file or any(part.startswith('.') for part in file.relative_to(root).parts):continue
        raw=file.read_bytes();part=chunks.get(file.name) if file.parent==index_file.parent else None
        if part and hashlib.sha256(raw).hexdigest()!=part['sha256']:raise ValueError('Input JSON chunk digest mismatch')
        output=pretty_bytes(json.loads(raw))
        if raw!=output:
            temporary=file.with_name(file.name+'.tmp');temporary.write_bytes(output);os.replace(temporary,file)
        if part:part['sha256']=hashlib.sha256(output).hexdigest()
        count+=1
    if index is not None:
        temporary=index_file.with_name('index.json.tmp');temporary.write_bytes(pretty_bytes(index));os.replace(temporary,index_file);count+=1
    return count


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',default=str(Path(__file__).resolve().parents[1]/'data'));options=parser.parse_args();count=format_public_json(options.directory);print(f'Pretty-printed {count} JSON files; chunk checksums updated')
