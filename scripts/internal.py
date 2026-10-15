import hashlib
import json
from pathlib import Path

SCHEMAS=json.loads(Path(__file__).with_name('internal-schema.json').read_text(encoding='utf-8'))

def internal_rows(table,rows):
    fields=set(SCHEMAS[table]['fields'])
    return [{key:value for key,value in row.items() if key in fields} for row in rows]

def write_internal(tables,timestamp,evidence,destination):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    index={'schemaVersion':1,'updatedAt':timestamp,'source':'verified-game-master','tables':{},'entities':{'chars':[],'stage_groups':[]}}
    versions={row['table']:row for row in evidence}
    for table,schema in SCHEMAS.items():
        rows=internal_rows(table,tables[table])
        rows.sort(key=lambda row:row['id'])
        chunks=[]
        for offset in range(0,len(rows),256):
            selected=rows[offset:offset+256]
            file=f'{table}-{offset//256:04d}.json'
            payload=json.dumps({'schemaVersion':1,'table':table,'updatedAt':timestamp,'rows':selected},ensure_ascii=False,separators=(',',':')).encode('utf-8')
            (destination/file).write_bytes(payload)
            chunks.append({'file':file,'firstId':selected[0]['id'],'lastId':selected[-1]['id'],'rows':len(selected),'sha256':hashlib.sha256(payload).hexdigest()})
        index['tables'][table]={'nativeClass':schema['nativeClass'],'rows':len(rows),'fields':schema['fields'],'chunks':chunks,'verification':versions.get(table)}
        if table in index['entities']:
            keys={'id','name','rarity','attribute_id','skin_id','sort_id','virtual_char_id','collection_enable_at','time_limited','updated_at','released_at','test_flag','banner_file_name','stage_class_id'}
            index['entities'][table]=[{key:value for key,value in row.items() if key in keys} for row in rows]
    (destination/'index.json').write_text(json.dumps(index,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return {'indexUrl':'data/internal/index.json','updatedAt':timestamp,'tables':{name:value['rows'] for name,value in index['tables'].items()}}
