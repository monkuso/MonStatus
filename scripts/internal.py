import hashlib
import json
import re
from pathlib import Path

SCHEMAS=json.loads(Path(__file__).with_name('internal-schema.json').read_text(encoding='utf-8'))

def gacha_table(name):
    return 'gacha' in name or name=='selectable_pickup_gacha_display_weights'

def content_table(name):
    return gacha_table(name) or name in {'chars','stages','stage_groups','strike_shots','fight_types','assist_skills','assist_skill_effects','connect_skills','connect_skill_conditions','connect_skill_effects','item_texts'} or name.startswith(('char_','stage_','skill_','shot_'))

def internal_rows(table,rows):
    if not content_table(table):raise ValueError('Unrelated internal table')
    def scrub(value):
        if isinstance(value,dict):return {key:scrub(item) for key,item in value.items() if not re.search(r'(^|_)(password|secret|session|token|credential|authorization)(_|$)',key,re.I)}
        if isinstance(value,list):return [scrub(item) for item in value]
        return value
    return [scrub(row) if isinstance(row,dict) else {'_value':scrub(row)} for row in rows]

def write_internal(tables,timestamp,evidence,destination):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    index={'schemaVersion':1,'updatedAt':timestamp,'source':'verified-game-master','tables':{},'entities':{'chars':[],'stage_groups':[],'stages':[]},'relations':{}}
    versions={row['table']:row for row in evidence}
    friendship_names={}
    for row in tables.get('char_skills',[]):
        if isinstance(row,dict) and row.get('name'):friendship_names.setdefault(row.get('char_id'),[]).append(row['name'])
    for table in sorted(name for name in tables if content_table(name)):
        schema=SCHEMAS.get(table,{'nativeClass':None,'fields':[]})
        rows=internal_rows(table,tables[table])
        identity='id' if all(type(row.get('id')) is int for row in rows) else '_recordIndex'
        if identity=='_recordIndex':
            for number,row in enumerate(rows):
                if '_recordIndex' in row:raise ValueError('Reserved record index field')
                row['_recordIndex']=number
        rows.sort(key=lambda row:row[identity])
        chunks=[]
        for offset in range(0,len(rows),256):
            selected=rows[offset:offset+256]
            file=f'{table}-{offset//256:04d}.json'
            payload=json.dumps({'schemaVersion':1,'table':table,'updatedAt':timestamp,'rows':selected},ensure_ascii=False,separators=(',',':')).encode('utf-8')
            (destination/file).write_bytes(payload)
            chunks.append({'file':file,'firstId':selected[0][identity],'lastId':selected[-1][identity],'rows':len(selected),'sha256':hashlib.sha256(payload).hexdigest()})
        fields=sorted({key for row in rows for key in row if key!='_recordIndex'})
        index['tables'][table]={'nativeClass':schema['nativeClass'],'rows':len(rows),'fields':fields,'registeredFields':schema['fields'],'identityField':identity,'chunks':chunks,'verification':versions.get(table)}
        if table in index['entities']:
            keys={'id','name','rarity','attribute_id','skin_id','sort_id','virtual_char_id','collection_enable_at','time_limited','updated_at','released_at','test_flag','banner_file_name','stage_class_id','stage_group_id','level_max','hp_max','attack_max','power_max','species_id','hit_type','fight_type'}
            index['entities'][table]=[{key:value for key,value in row.items() if key in keys} for row in rows]
            if table=='chars':
                for row in index['entities'][table]:row['friendshipNames']=list(dict.fromkeys(friendship_names.get(row['id'],[])))
        for row in rows:
            for field,parent in [('char_id','chars'),('stage_id','stages'),('stage_group_id','stage_groups'),('stage_phase_id','stage_phases'),('connect_skill_id','connect_skills'),('assist_skill_id','assist_skills')]:
                if type(row.get(field)) is int and row[field]>0:index['relations'].setdefault(parent,{}).setdefault(str(row[field]),{}).setdefault(table,[]).append(row[identity])
    (destination/'index.json').write_text(json.dumps(index,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return {'indexUrl':'data/internal/index.json','updatedAt':timestamp,'tables':{name:value['rows'] for name,value in index['tables'].items()}}
