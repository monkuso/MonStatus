import base64
import datetime
import hashlib
import io
import json
import os
import re
from pathlib import Path
import sys
import urllib.parse
import urllib.request
import zipfile
import zlib
import msgpack
from catalog_sync import CATALOG_TABLES,build_catalog
from game_protocol import signed_headers,read_game
from gacha_rates import parse_rates

TABLES={'stage_groups','stage_group_events','stage_group_kind_events','stage_group_cycle_events','stages','stage_gimmicks','chars','wanted_bosses','wanted_boss_groups'}
TABLES|=CATALOG_TABLES
EVENT_TABLES={'stage_group_events','stage_group_kind_events','stage_group_cycle_events'}
HEADER_NAMES={'content-type','user-agent','x-ds-eit','x-ds-session','x-ds-requesthash-ver','x-ds-requesthash'}
ADVANTAGE={1:2,2:3,3:1,4:5,5:4}
RECOMMENDED_PER_EVENT=6

def clear_group_ids(catalog,now):
    return sorted({row['stageGroupId'] for row in catalog['stageEvents'] if row['sourceTable']=='stage_group_events' and row['startAt']<=now<=row['endAt']})

def merge_clear_results(catalog,details,timestamp):
    rows=details.get('recommends')
    if not isinstance(rows,list):raise SyncError('Clear character response rejected')
    fields={'stage_id','aggregate_range','event_char_ids','gacha_char_ids','response_time'}
    merged={row['stage_id']:row for row in catalog['recommendations']}
    stage_ids={row['id'] for row in catalog['tables']['stages']}
    for row in rows:
        if row.get('stage_id') not in stage_ids or any(not isinstance(row.get(key),list) or any(type(value) is not int or value<0 for value in row[key]) for key in ['event_char_ids','gacha_char_ids']):raise SyncError('Clear character identity rejected')
        public={key:row[key] for key in fields if key in row}
        public['fetched_at']=timestamp
        merged[public['stage_id']]=public
    catalog['recommendations']=list(merged.values())
    catalog['community']['fetchedStages']=len(merged)

def sync_clear_groups(catalog,config,timestamp):
    requested=clear_group_ids(catalog,datetime.datetime.fromisoformat(timestamp).timestamp())
    failures=[]
    for group_id in requested:
        try:
            details=read_game(config,f'/char/recommend?stage_id=0&stage_group_id={group_id}')
            merge_clear_results(catalog,details,timestamp)
        except Exception as error:
            failures.append({'stageGroupId':group_id,'errorType':type(error).__name__})
    catalog['community'].update({'status':'partial' if failures else 'verified','requestedGroups':len(requested),'failedGroups':failures,'observedAt':timestamp})

class SyncError(Exception):
    pass

def download(url,limit,headers=None):
    if urllib.parse.urlsplit(url).scheme not in {'http','https'}:
        raise SyncError('Unsupported resource protocol')
    request=urllib.request.Request(url,headers=headers or {},method='GET')
    with urllib.request.urlopen(request,timeout=30) as response:
        payload=response.read(limit+1)
        if response.status!=200 or len(payload)>limit:
            raise SyncError('Resource response rejected')
    return payload

def unpack(payload):
    value=msgpack.unpackb(payload,raw=False,strict_map_key=False)
    if not isinstance(value,dict) or value.get('result')!=0:
        result=value.get('result') if isinstance(value,dict) else 'format'
        hints=''
        if isinstance(value,dict):
            keys=sorted(k for k in value.keys() if isinstance(k,str))[:16]
            hints=f' keys={keys}'
            if result==200:
                hints+=' hint=session_or_signature_rejected; refresh MS_GAME_CONFIG secret with a current x-ds-session, x-ds-requesthash, x-ds-requesthash-ver, x-ds-eit capture'
        raise SyncError(f'Application response result: {result}{hints}')
    return value

def table_from_archive(raw,entry,password):
    if len(raw)!=entry['size'] or zlib.crc32(raw)&0xFFFFFFFF!=entry['crc']:
        raise SyncError('Resource size or CRC mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members=archive.infolist()
        if len(members)!=1 or members[0].file_size>96*1024*1024:
            raise SyncError('Resource archive layout rejected')
        decoded=unpack(archive.read(members[0],pwd=password))
    bundles=decoded.get('masters',[])+decoded.get('daily_masters',[])
    matching=[bundle[entry['name']] for bundle in bundles if isinstance(bundle,dict) and entry['name'] in bundle]
    if len(matching)!=1 or not isinstance(matching[0],list):
        raise SyncError('Resource table is missing')
    return matching[0]

def build_gimmick_index(tables):
    stages_by_group={}
    for row in tables['stages']:
        gid=row.get('stage_group_id')
        sid=row.get('id')
        if type(gid) is not int or type(sid) is not int:
            raise SyncError('Stage structure rejected')
        stages_by_group.setdefault(gid,[]).append(sid)
    gimmicks_by_stage={}
    for row in tables['stage_gimmicks']:
        sid=row.get('stage_id')
        flag=row.get('gimmick_flag')
        highlight=row.get('highlight_gimmick_flag')
        if type(sid) is not int or type(flag) is not int or type(highlight) is not int:
            raise SyncError('Stage gimmick structure rejected')
        if flag<0 or flag>=1<<32 or highlight<0 or highlight>=1<<32:
            raise SyncError('Stage gimmick flag range rejected')
        gimmicks_by_stage[sid]=(flag,highlight)
    return stages_by_group,gimmicks_by_stage

def union_gimmicks_for_group(group_id,stages_by_group,gimmicks_by_stage):
    flag=0
    highlight=0
    stages_with_gimmicks=0
    for sid in stages_by_group.get(group_id,[]):
        pair=gimmicks_by_stage.get(sid)
        if pair is None:
            continue
        flag|=pair[0]
        highlight|=pair[1]
        stages_with_gimmicks+=1
    return flag,highlight,stages_with_gimmicks

def char_profile(row):
    cid=row.get('id')
    name=row.get('name')
    if type(cid) is not int or not isinstance(name,str):
        raise SyncError('Character structure rejected')
    rarity=row.get('rarity')
    attribute=row.get('attribute_id')
    return {'id':cid,'name':name,'rarity':rarity if type(rarity) is int else None,'attributeId':attribute if type(attribute) is int else None}

def build_char_index(tables):
    index={}
    for row in tables['chars']:
        profile=char_profile(row)
        index[profile['id']]=profile
    return index

def recommended_char_ids(attribute_id,char_index,limit=RECOMMENDED_PER_EVENT):
    target=ADVANTAGE.get(attribute_id)
    if target is None:
        return []
    candidates=[p for p in char_index.values() if p['attributeId']==target]
    candidates.sort(key=lambda p:(-(p['rarity'] or 0),p['id']))
    return [p['id'] for p in candidates[:limit]]

def build_wanted_boss_index(tables):
    groups_by_id={}
    for row in tables['wanted_boss_groups']:
        gid=row.get('id')
        if type(gid) is not int:
            raise SyncError('Wanted boss group structure rejected')
        start=row.get('start_at')
        groups_by_id[gid]={'startAt':start if type(start) is int else None}
    bosses_by_group={}
    for row in tables['wanted_bosses']:
        bid=row.get('id')
        gid=row.get('wanted_boss_group_id')
        cid=row.get('char_id')
        if type(bid) is not int or type(gid) is not int or type(cid) is not int:
            raise SyncError('Wanted boss structure rejected')
        start=row.get('start_at')
        bosses_by_group.setdefault(gid,[]).append({'charId':cid,'order':row.get('order') if type(row.get('order')) is int else 0,'startAt':start if type(start) is int else None})
    for group in bosses_by_group.values():
        group.sort(key=lambda b:(b['order'],b['charId']))
    return groups_by_id,bosses_by_group

def active_wanted_bosses(start_at,end_at,groups_by_id,bosses_by_group):
    results={}
    for gid,bosses in bosses_by_group.items():
        group=groups_by_id.get(gid)
        if group is None:
            continue
        gstart=group['startAt']
        if gstart is None or gstart>end_at:
            continue
        for boss in bosses:
            if boss['startAt'] is not None and boss['startAt']>end_at:
                continue
            results.setdefault(boss['charId'],boss['order'])
    return [cid for cid,_ in sorted(results.items(),key=lambda it:(it[1],it[0]))]

def normalize_events(tables):
    groups={row['id']:row for row in tables['stage_groups']}
    stages_by_group,gimmicks_by_stage=build_gimmick_index(tables)
    char_index=build_char_index(tables)
    boss_groups,boss_rows=build_wanted_boss_index(tables)
    referenced_chars=set()
    events=[]
    for table in sorted(EVENT_TABLES):
        for row in tables[table]:
            if type(row.get('start_at')) is not int or type(row.get('end_at')) is not int or row['start_at']>row['end_at']:
                raise SyncError('Event date structure rejected')
            group=groups.get(row.get('stage_group_id'),{})
            name=row.get('name') or group.get('name') or '名称未設定'
            if not isinstance(name,str):
                raise SyncError('Event name structure rejected')
            gid=row.get('stage_group_id')
            flag,highlight,stages_with_gimmicks=union_gimmicks_for_group(gid,stages_by_group,gimmicks_by_stage) if type(gid) is int else (0,0,0)
            stage_count=len(stages_by_group.get(gid,[])) if type(gid) is int else 0
            attribute_id=group.get('attribute_id')
            recommended=recommended_char_ids(attribute_id,char_index) if type(attribute_id) is int else []
            wanted=active_wanted_bosses(row['start_at'],row['end_at'],boss_groups,boss_rows)[:RECOMMENDED_PER_EVENT]
            for cid in recommended+wanted:
                referenced_chars.add(cid)
            events.append({'id':f'{table}:{row["id"]}','name':name,'questName':group.get('name'),'stageGroupId':gid,'startAt':row['start_at'],'endAt':row['end_at'],'sourceTable':table,'typeId':row.get('type_id'),'attributeId':attribute_id,'stageClassId':group.get('stage_class_id'),'gimmickFlag':flag,'highlightGimmickFlag':highlight,'stageCount':stage_count,'stagesWithGimmicks':stages_with_gimmicks,'recommendedCharIds':recommended,'wantedBossCharIds':wanted})
    if not events or len({row['id'] for row in events})!=len(events):
        raise SyncError('Event identity structure rejected')
    char_profiles={str(cid):char_index[cid] for cid in sorted(referenced_chars) if cid in char_index}
    return events,char_profiles

def build_snapshot(config):
    parsed=urllib.parse.urlsplit(config['url'])
    if parsed.scheme!='https' or parsed.hostname!='api.monster-strike.com' or parsed.path!='/master/version':
        raise SyncError('Master endpoint rejected')
    headers=signed_headers(config,parsed.path+('?' + parsed.query if parsed.query else '')) if config.get('signing_seed_b64') else {k:v for k,v in config['headers'].items() if k.lower() in HEADER_NAMES}
    if not {'x-ds-session','x-ds-requesthash'}<={key.lower() for key in headers}:
        raise SyncError('Game connection configuration is incomplete')
    manifest=unpack(download(config['url'],4*1024*1024,headers))
    password=base64.b64decode(config['password_b64'],validate=True)
    tables={}
    evidence=[]
    for entry in manifest['master_versions']+manifest['daily_versions']:
        name=entry['name']
        if name not in TABLES:
            continue
        if name in tables:
            raise SyncError('Duplicate resource version entry')
        raw=download(entry['uri'],32*1024*1024)
        tables[name]=table_from_archive(raw,entry,password)
        evidence.append({'table':name,'version':entry['version'],'rows':len(tables[name]),'crc':entry['crc'],'sha256':hashlib.sha256(raw).hexdigest()})
    if TABLES!=tables.keys():
        raise SyncError('Required event tables are missing')
    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    events,char_profiles=normalize_events(tables)
    catalog=build_catalog(tables,timestamp,evidence,events)
    read_requests=[(path,request) for path,value in config.get('reads',{}).items() for request in (value if isinstance(value,list) else [value])]
    for path,request in read_requests:
        endpoint=urllib.parse.urlsplit(request['url'])
        if endpoint.scheme!='https' or endpoint.hostname!='api.monster-strike.com' or endpoint.path!=path or path not in {'/information/list','/char/recommend'}:
            raise SyncError('Detail read endpoint rejected')
        read_headers=signed_headers(config,endpoint.path+('?' + endpoint.query if endpoint.query else '')) if config.get('signing_seed_b64') else {k:v for k,v in request['headers'].items() if k.lower() in HEADER_NAMES}
        details=unpack(download(request['url'],16*1024*1024,read_headers))
        if path=='/information/list':
            rows=details.get('gacha_group_events')
            if not isinstance(rows,list):raise SyncError('Gacha schedule response rejected')
            fields={'id','name','gacha_group_id','start_at','end_at','visible_at','header_title','footer_title','popup_url'}
            catalog['gachaEvents']=[{key:row[key] for key in fields if key in row} for row in rows]
            catalog['gachaScheduleStatus']='verified'
            catalog['detailObservedAt']=timestamp
            lucky_rows=details.get('weekly_max_luck_bonuses')
            if isinstance(lucky_rows,list):
                lucky_fields={'id','description','max_level','start_at','end_at','visible_at','drop_ids'}
                catalog['weeklyMaxLuckBonuses']=[{key:row[key] for key in lucky_fields if key in row} for row in lucky_rows]
                catalog['weeklyMaxLuckBonusesStatus']='verified'
            banner_rows=details.get('gacha_group_banners')
            if isinstance(banner_rows,list):
                banner_fields={'id','gacha_group_id','file_name','priority','type_id','start_at','end_at'}
                catalog['gachaBanners']=[{key:row[key] for key in banner_fields if key in row} for row in banner_rows]
                catalog['gachaBannersStatus']='verified'
            messages=details.get('event_messages')
            if isinstance(messages,list):
                catalog['gachaMessages']=[]
                catalog['gachaRates']=[]
                for index,row in enumerate(messages):
                    metadata={'messageId':row['id'],'gachaGroupId':row.get('gacha_group_id',0),'messageIndex':index,
                              'startAt':row['start_at'],'endAt':row['end_at'],'disabled':row.get('disabled',0),'priority':row.get('priority',0)}
                    catalog['gachaMessages'].append(metadata)
                    raw_details=row.get('message','')
                    character_ids=list(dict.fromkeys(int(value) for value in re.findall(r'\[IPLJ(\d+)\]',raw_details)))
                    detail_text=re.sub(r'\[u:[^|\]]+\|([^\]]+)\]',r'\1',raw_details)
                    detail_text=re.sub(r'\[C\d+:([^\[\]]*)\]',r'\1',detail_text)
                    detail_text=re.sub(r'\[BLOCK:([^\]]+)\]',r'\1',detail_text)
                    _,explanation=parse_rates(detail_text)
                    for field,title in [('summary','通常の提供割合'),('inc_prob_gacha_summary','初回10連の提供割合（対象条件あり）')]:
                        text=row.get(field,'')
                        if not text:continue
                        entries,notes=parse_rates(text)
                        catalog['gachaRates'].append({**metadata,'title':title,'entries':entries,'notes':notes,'rawText':text,
                                                      'detailText':explanation,'detailCharacterIds':character_ids,
                                                      'source':'official-game-provided-rates','observedAt':timestamp})
        else:
            merge_clear_results(catalog,details,timestamp)
            catalog['community']['status']='verified'
    if config.get('signing_seed_b64'):sync_clear_groups(catalog,config,timestamp)
    return {'schemaVersion':3,'updatedAt':timestamp,'source':f'モンスト{config.get("app_version", "33.0.0")} 実サーバー日次マスター','events':events,'charProfiles':char_profiles,'catalog':catalog,'verification':evidence,'sync':{'mode':'github-actions','intervalMinutes':30,'lastSuccessAt':timestamp,'transport':'https'}}

def run():
    encoded=os.environ.get('MS_GAME_CONFIG')
    if not encoded:
        raise SyncError('MS_GAME_CONFIG secret is not configured')
    snapshot=build_snapshot(json.loads(encoded))
    root=Path(__file__).resolve().parent
    catalog=snapshot.pop('catalog')
    catalog_temporary=root/'catalog.json.tmp'
    catalog_temporary.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    os.replace(catalog_temporary,root/'catalog.json')
    temporary=root/'events.json.tmp'
    temporary.write_text(json.dumps(snapshot,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    os.replace(temporary,root/'events.json')
    print(json.dumps({'result':'success','events':len(snapshot['events']),'chars':len(snapshot['charProfiles']),'updatedAt':snapshot['updatedAt'],'tables':snapshot['verification'],'catalogRelations':catalog['relations'],'gimmickLabels':catalog['gimmicks']},ensure_ascii=False))

if __name__=='__main__':
    try:
        run()
    except SyncError as error:
        print(f'Synchronization stopped: {error}',file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f'Synchronization stopped: {type(error).__name__}',file=sys.stderr)
        sys.exit(1)
