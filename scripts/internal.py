import hashlib
import json
import re
from pathlib import Path

SCHEMAS=json.loads(Path(__file__).with_name('internal-schema.json').read_text(encoding='utf-8'))
CHARACTER_ITEM_RULE={'minimum':10000,'maximum':9999999,'offset':10000,'verifiedClientVersion':'33.0.0','nativeFunction':'SysItem::decodeIID','nativeAddress':'0x5cf8a54'}

def gacha_table(name):
    return 'gacha' in name or name=='selectable_pickup_gacha_display_weights'

def content_table(name):
    return bool(re.fullmatch(r'[a-z][a-z0-9_]*',name))


def table_category(name):
    if name=='chars' or name.startswith(('char_','strike_','shot_','skill_','connect_','assist_','fight_')):return 'characters'
    if name.startswith(('stage_','stages','wanted_boss','enemy_')):return 'quests'
    if 'gacha' in name:return 'gachas'
    if name.endswith(('_events','_campaigns')) or name in {'login_stamp_groups','campaign_items'}:return 'events'
    if 'reward' in name or 'bonus' in name or 'achievement' in name:return 'rewards'
    if name=='items' or name.startswith(('item_','purchase_','shop_','exchange_')):return 'items'
    return 'systems'


def reference_tables(tables):
    keys={}
    for name in tables:
        singular=name[:-3]+'y' if name.endswith('ies') else name[:-1] if name.endswith('s') else name
        keys[singular+'_id']=name
    keys.update({'char_id':'chars','stage_id':'stages','stage_group_id':'stage_groups','stage_phase_id':'stage_phases','species_id':'char_species','strike_shot_id':'strike_shots','shot_skill_id':'shot_skills','item_id':'items'})
    references={}
    for name,rows in tables.items():
        fields={key for row in rows if isinstance(row,dict) for key in row}
        targets={}
        for field in fields:
            target=keys.get(field)
            if not target:
                if re.search(r'(^|_)char_id[0-9]*$',field):target='chars'
                elif re.search(r'(^|_)item_id[0-9]*$',field):target='items'
                elif re.fullmatch(r'connect_skill_conditions_id_[12]_[12]',field):target='connect_skill_conditions'
                elif re.fullmatch(r'assist_skill_effect_id_[123]',field):target='assist_skill_effects'
                else:target=next((parent for suffix,parent in [('stage_group_id','stage_groups'),('stage_phase_id','stage_phases'),('stage_id','stages'),('strike_shot_id','strike_shots')] if field.endswith('_'+suffix)),None)
            if target is not None:targets[field]=target
        references[name]=targets
    return references

def internal_rows(table,rows):
    if not content_table(table):raise ValueError('Unrelated internal table')
    def scrub(value):
        if isinstance(value,dict):return {key:scrub(item) for key,item in value.items() if not re.search(r'(^|_)(password|secret|session|token|credential|authorization)(_|$)',key,re.I)}
        if isinstance(value,list):return [scrub(item) for item in value]
        return value
    return [scrub(row) if isinstance(row,dict) else {'_value':scrub(row)} for row in rows]

def write_internal(tables,timestamp,evidence,destination,manifest=None,failures=None):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    index={'schemaVersion':1,'updatedAt':timestamp,'source':'verified-game-master','tables':{},'entities':{'chars':[],'stage_groups':[],'stages':[]},'relations':{},'collections':{'events':[],'items':[]},'references':reference_tables(tables),'referenceRules':{'characterItem':CHARACTER_ITEM_RULE}}
    character_ids={row['id'] for row in tables.get('chars',[])}
    versions={row['table']:row for row in evidence}
    friendship_names={}
    for row in tables.get('char_skills',[]):
        if isinstance(row,dict) and row.get('name'):friendship_names.setdefault(row.get('char_id'),[]).append(row['name'])
    for table in sorted(name for name in tables if content_table(name)):
        schema=SCHEMAS.get(table,{'nativeClass':None,'fields':[]})
        rows=internal_rows(table,tables[table])
        identity='id' if all(type(row.get('id')) is int for row in rows) and len({row['id'] for row in rows})==len(rows) else '_recordIndex'
        if identity=='_recordIndex':
            for number,row in enumerate(rows):
                if '_recordIndex' in row:raise ValueError('Reserved record index field')
                row['_recordIndex']=number
        rows.sort(key=lambda row:row[identity])
        chunks=[]
        for offset in range(0,len(rows),256):
            selected=rows[offset:offset+256]
            file=f'{table}-{offset//256:04d}.json'
            payload=json.dumps({'schemaVersion':1,'table':table,'updatedAt':timestamp,'rows':selected},ensure_ascii=False,indent=2).encode('utf-8')
            (destination/file).write_bytes(payload)
            chunks.append({'file':file,'firstId':selected[0][identity],'lastId':selected[-1][identity],'rows':len(selected),'sha256':hashlib.sha256(payload).hexdigest()})
        fields=sorted({key for row in rows for key in row if key!='_recordIndex'})
        category=table_category(table)
        index['tables'][table]={'nativeClass':schema['nativeClass'],'rows':len(rows),'fields':fields,'registeredFields':schema['fields'],'identityField':identity,'chunks':chunks,'verification':versions.get(table),'category':category,'status':versions.get(table,{}).get('status','verified')}
        collection=category if category=='events' else 'items' if table=='items' else None
        if collection:
            preview={'id','name','title','description','summary','message','start_at','end_at','visible_at','released_at','updated_at','file_name','banner_file_name','banner_name','icon_name','image_id','image_name','skin_id','char_id','stage_group_id','gacha_group_id','_recordIndex'}
            index['collections'][collection].extend({'table':table,**{key:value for key,value in row.items() if key in preview or key.endswith('_at')}} for row in rows)
        if table in index['entities']:
            keys={'id','name','rarity','attribute_id','skin_id','sort_id','virtual_char_id','collection_enable_at','time_limited','updated_at','released_at','test_flag','banner_file_name','stage_class_id','stage_group_id','level_max','hp_max','attack_max','power_max','species_id','hit_type','fight_type'}
            index['entities'][table]=[{key:value for key,value in row.items() if key in keys} for row in rows]
            if table=='chars':
                for row in index['entities'][table]:row['friendshipNames']=list(dict.fromkeys(friendship_names.get(row['id'],[])))
        for row in rows:
            for field,parent in index['references'].get(table,{}).items():
                if type(row.get(field)) is int and row[field]>0:index['relations'].setdefault(parent,{}).setdefault(str(row[field]),{}).setdefault(table,[]).append(row[identity])
                if parent=='items' and type(row.get(field)) is int and CHARACTER_ITEM_RULE['minimum']<=row[field]<=CHARACTER_ITEM_RULE['maximum']:
                    character=row[field]-CHARACTER_ITEM_RULE['offset']
                    if character in character_ids:index['relations'].setdefault('chars',{}).setdefault(str(character),{}).setdefault(table,[]).append(row[identity])
    for failed in failures or []:
        name=failed['table']
        index['tables'][name]={'rows':None,'fields':[],'registeredFields':SCHEMAS.get(name,{}).get('fields',[]),'identityField':'id','chunks':[],'category':table_category(name),'status':'error','failure':failed}
    expected=sorted({entry['name'] for entry in manifest}) if manifest is not None else sorted(tables)
    index['coverage']={'expected':len(expected),'verified':sum(v['status']=='verified' for v in index['tables'].values()),'limitedIntegrity':sum(v['status']=='manifest-integrity-unavailable' for v in index['tables'].values()),'notDistributed':sum(v['status']=='not-distributed' for v in index['tables'].values()),'failed':failures or [],'missing':[name for name in expected if name not in index['tables']],'expectedTables':expected}
    (destination/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'indexUrl':'data/internal/index.json','updatedAt':timestamp,'tables':{name:value['rows'] for name,value in index['tables'].items()}}
