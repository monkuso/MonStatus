import base64
import datetime
import hashlib
import io
import json
import os
import re
import concurrent.futures
import threading
import time
import tempfile
from pathlib import Path
import sys
import urllib.parse
import urllib.request
import zipfile
import zlib
import msgpack
from catalog import CATALOG_TABLES,build_catalog
from internal import write_internal,internal_rows,gacha_table
from protocol import signed_headers,read_game
from rates import parse_rates
from release import version_metadata
from gacha import retain_gacha_history

TABLES={'stage_groups','stage_group_events','stage_group_kind_events','stage_group_cycle_events','stages','stage_gimmicks','chars','wanted_bosses','wanted_boss_groups'}
TABLES|=CATALOG_TABLES
EVENT_TABLES={'stage_group_events','stage_group_kind_events','stage_group_cycle_events'}
HEADER_NAMES={'content-type','user-agent','x-ds-eit','x-ds-session','x-ds-requesthash-ver','x-ds-requesthash'}
ADVANTAGE={1:2,2:3,3:1,4:5,5:4}
RECOMMENDED_PER_EVENT=6

def clear_group_ids(catalog,now,previous=None):
    active={row['stageGroupId'] for row in catalog['stageEvents'] if row['sourceTable']=='stage_group_events' and row['startAt']<=now<=row['endAt']}
    checks={row['stageId']:row for row in (previous or {}).get('clearChecks',[])}
    selected=set()
    for row in catalog['tables']['stages']:
        check=checks.get(row['id'])
        age=now-datetime.datetime.fromisoformat(check['checkedAt']).timestamp() if check else float('inf')
        if row['stage_group_id'] in active or not check or check['status']=='error' or age<0 or age>=86400:selected.add(row['stage_group_id'])
    return sorted(selected,key=lambda group_id:(group_id not in active,group_id))

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

def sync_clear_groups(catalog,config,timestamp,previous=None):
    stage_groups={}
    for row in catalog['tables']['stages']:stage_groups.setdefault(row['stage_group_id'],[]).append(row['id'])
    stage_ids={row['id'] for row in catalog['tables']['stages']}
    current=catalog['recommendations']
    catalog['recommendations']=[row for row in (previous or {}).get('recommendations',[]) if row['stage_id'] in stage_ids]
    merge_clear_results(catalog,{'recommends':current},timestamp)
    checks={row['stageId']:row for row in (previous or {}).get('clearChecks',[]) if row['stageId'] in stage_ids}
    requested=clear_group_ids(catalog,datetime.datetime.fromisoformat(timestamp).timestamp(),previous)
    failures=[]
    pacing=threading.Lock()
    stopped=threading.Event()
    next_read=[time.monotonic()]
    def read(route):
        if stopped.is_set():raise SyncError('Clear synchronization stopped')
        with pacing:
            delay=max(0,next_read[0]-time.monotonic())
            next_read[0]=max(next_read[0],time.monotonic())+0.125
        if delay:time.sleep(delay)
        return read_game(config,route)
    def fetch(group_id):
        rows=[]
        result_checks=[]
        errors=[]
        def reject_global(error):
            if getattr(error,'code',None) in {200,429}:
                stopped.set()
                raise SyncError('Clear session or rate rejected') from None
        try:
            details=read(f'/char/recommend?stage_id=0&stage_group_id={group_id}')
            if not isinstance(details.get('recommends'),list):raise SyncError('Clear response rejected')
            rows=details['recommends']
        except Exception as error:
            reject_global(error)
        returned={row['stage_id'] for row in rows}
        for stage_id in stage_groups[group_id]:
            try:
                if stage_id not in returned:
                    individual=read(f'/char/recommend?stage_id={stage_id}&stage_group_id={group_id}')
                    if not isinstance(individual.get('recommends'),list):raise SyncError('Clear response rejected')
                    matching=[row for row in individual['recommends'] if row['stage_id']==stage_id]
                    rows.extend(matching)
                    if matching:returned.add(stage_id)
                result_checks.append({'stageId':stage_id,'status':'available' if stage_id in returned else 'not-published','checkedAt':timestamp})
            except Exception as error:
                reject_global(error)
                if not errors:errors.append({'stageGroupId':group_id,'errorType':type(error).__name__})
                result_checks.append({'stageId':stage_id,'status':'error','checkedAt':timestamp})
        return rows,result_checks,errors
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for index,result in enumerate(executor.map(fetch,requested),1):
            rows,result_checks,errors=result
            merge_clear_results(catalog,{'recommends':rows},timestamp)
            checks.update({row['stageId']:row for row in result_checks})
            failures.extend(errors)
            if index%250==0:print(json.dumps({'clearGroupsCompleted':index,'clearGroupsTotal':len(requested),'checkedStages':len(checks)}),flush=True)
    catalog['clearChecks']=sorted(checks.values(),key=lambda row:row['stageId'])
    unpublished={row['stageId'] for row in checks.values() if row['status']=='not-published'}
    catalog['recommendations']=[row for row in catalog['recommendations'] if row['stage_id'] not in unpublished]
    catalog['community'].update({'status':'partial' if failures else 'verified','description':'全ステージを対象に確認したゲームのクリアモンスター集計です。','scope':'all-stages','totalStages':len(stage_ids),'checkedStages':len(checks),'fetchedStages':len(catalog['recommendations']),'requestedGroups':len(requested),'failedGroups':failures,'observedAt':timestamp})

class SyncError(Exception):
    def __init__(self,message,code=None):
        self.code=code
        super().__init__(message)

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
        raise SyncError(f'Application response result: {result}{hints}',code=result)
    return value

def table_from_archive(raw,entry,password):
    metadata_missing=entry['crc']==0
    if (entry['size']!=0 and len(raw)!=entry['size']) or (not metadata_missing and (len(raw)!=entry['size'] or zlib.crc32(raw)&0xFFFFFFFF!=entry['crc'])):
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

def master_manifest(config):
    parsed=urllib.parse.urlsplit(config['url'])
    if parsed.scheme!='https' or parsed.hostname!='api.monster-strike.com' or parsed.path!='/master/version':
        raise SyncError('Master endpoint rejected')
    headers=signed_headers(config,parsed.path+('?' + parsed.query if parsed.query else '')) if config.get('signing_seed_b64') else {k:v for k,v in config['headers'].items() if k.lower() in HEADER_NAMES}
    if not {'x-ds-session','x-ds-requesthash'}<={key.lower() for key in headers}:
        raise SyncError('Game connection configuration is incomplete')
    manifest=unpack(download(config['url'],4*1024*1024,headers))
    if any(not isinstance(manifest.get(name),list) for name in ['master_versions','daily_versions']):raise SyncError('Master manifest schema changed')
    return manifest


def empty_master(entry):
    return not entry.get('uri') and entry.get('size')==0 and entry.get('crc')==0

def build_snapshot(config,previous=None,destination=None,version_info=None):
    destination=Path(destination) if destination is not None else Path(__file__).resolve().parents[1]/'data'
    manifest=master_manifest(config)
    password=base64.b64decode(config['password_b64'],validate=True)
    all_names=[e['name'] for e in manifest['master_versions']+manifest['daily_versions']]
    required=TABLES|set(all_names)
    print('MANIFEST_TABLES='+json.dumps(sorted(set(all_names)),ensure_ascii=False),flush=True)
    (destination/'tables.json').write_text(json.dumps(sorted(set(all_names)),ensure_ascii=False,indent=2),encoding='utf-8')
    tables={}
    evidence=[]
    failures=[]
    entries={}
    for entry in manifest['master_versions']+manifest['daily_versions']:
        if entry['name'] in required:entries.setdefault(entry['name'],entry)
    def fetch_table(entry):
        if empty_master(entry):return entry,[],None,None
        try:
            raw=download(entry['uri'],32*1024*1024)
            return entry,table_from_archive(raw,entry,password),raw,None
        except Exception as error:return entry,None,None,error
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for number,(entry,rows,raw,error) in enumerate(executor.map(fetch_table,entries.values()),1):
            name=entry['name']
            if error is not None:
                if name in TABLES or gacha_table(name) or name=='item_texts':raise error
                failures.append({'table':name,'errorType':type(error).__name__,'version':entry['version']})
                print(f'TABLE_FETCH_FAILED {name}: {type(error).__name__}',flush=True)
                continue
            tables[name]=rows
            proof={'table':name,'version':entry['version'],'rows':len(rows),'crc':zlib.crc32(raw)&0xFFFFFFFF if raw is not None else 0}
            if raw is None:proof['status']='not-distributed'
            else:
                proof['sha256']=hashlib.sha256(raw).hexdigest()
                if entry['crc']==0:proof.update({'status':'manifest-integrity-unavailable','size':len(raw),'expectedSize':entry['size'],'expectedCrc':0,'validation':['zip-member-crc','messagepack-result','table-name','array-type']})
            evidence.append(proof)
            if number%100==0:print(json.dumps({'masterTablesCompleted':number,'masterTablesTotal':len(entries)}),flush=True)
    missing=TABLES-tables.keys()
    if missing:
        raise SyncError(f'Required tables missing: {sorted(missing)}')
    schema={name:sorted({k for row in rows for k in (row.keys() if isinstance(row,dict) else [])}) for name,rows in tables.items() if rows}
    (destination/'schema.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2),encoding='utf-8')
    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    events,char_profiles=normalize_events(tables)
    catalog=build_catalog(tables,timestamp,evidence,events)
    catalog['internalData']=write_internal(tables,timestamp,evidence,destination/'internal',manifest['master_versions']+manifest['daily_versions'],failures)
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
            catalog['gachaEvents']=internal_rows('gacha_group_events',rows)
            catalog['gachaScheduleStatus']='verified'
            catalog['detailObservedAt']=timestamp
            lucky_rows=details.get('weekly_max_luck_bonuses')
            if isinstance(lucky_rows,list):
                lucky_fields={'id','description','max_level','start_at','end_at','visible_at','drop_ids'}
                catalog['weeklyMaxLuckBonuses']=[{key:row[key] for key in lucky_fields if key in row} for row in lucky_rows]
                catalog['weeklyMaxLuckBonusesStatus']='verified'
            banner_rows=details.get('gacha_group_banners')
            if isinstance(banner_rows,list):
                catalog['gachaBanners']=internal_rows('gacha_group_banners',banner_rows)
                catalog['gachaBannersStatus']='verified'
            messages=details.get('event_messages')
            if isinstance(messages,list):
                catalog['gachaMessages']=[]
                catalog['gachaRates']=[]
                for index,row in enumerate(messages):
                    raw_details=row.get('message','')
                    character_ids=list(dict.fromkeys(int(value) for value in re.findall(r'\[IPLJ(\d+)\]',raw_details)))
                    detail_text=re.sub(r'\[u:[^|\]]+\|([^\]]+)\]',r'\1',raw_details)
                    detail_text=re.sub(r'\[C\d+:([^\[\]]*)\]',r'\1',detail_text)
                    detail_text=re.sub(r'\[BLOCK:([^\]]+)\]',r'\1',detail_text)
                    _,explanation=parse_rates(detail_text)
                    metadata={'messageId':row['id'],'gachaGroupId':row.get('gacha_group_id',0),'messageIndex':index,
                              'startAt':row['start_at'],'endAt':row['end_at'],'disabled':row.get('disabled',0),'priority':row.get('priority',0),
                              'detailText':explanation,'detailCharacterIds':character_ids,'observedAt':timestamp,'source':'official-game-information'}
                    metadata['original']=internal_rows('gacha_event_messages',[row])[0]
                    catalog['gachaMessages'].append(metadata)
                    for field,title in [('summary','通常の提供割合'),('inc_prob_gacha_summary','初回10連の提供割合（対象条件あり）')]:
                        text=row.get(field,'')
                        if not text:continue
                        entries,notes=parse_rates(text)
                        catalog['gachaRates'].append({**metadata,'title':title,'entries':entries,'notes':notes,'rawText':text,
                                                      'source':'official-game-provided-rates','observedAt':timestamp})
        else:
            merge_clear_results(catalog,details,timestamp)
            catalog['community']['status']='verified'
    if catalog.get('gachaScheduleStatus')=='verified':retain_gacha_history(catalog,previous,timestamp)
    if config.get('signing_seed_b64'):sync_clear_groups(catalog,config,timestamp,previous)
    catalog['versionInfo']=version_info or {}
    return {'schemaVersion':3,'updatedAt':timestamp,'appVersion':(version_info or {}).get('version'),'configuredClientVersion':config.get('app_version'),'versionInfo':version_info or {},'source':'モンスト 実サーバー日次マスター','events':events,'charProfiles':char_profiles,'catalog':catalog,'verification':evidence,'sync':{'mode':'github-actions','intervalMinutes':30,'lastSuccessAt':timestamp,'transport':'https'}}

def configured_game():
    encoded=os.environ.get('MS_GAME_CONFIG')
    if not encoded:
        raise SyncError('MS_GAME_CONFIG secret is not configured')
    return json.loads(encoded)

def save_status(data,status):
    temporary=data/'sync-status.json.tmp'
    temporary.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temporary,data/'sync-status.json')

def check_connection():
    config=configured_game()
    release=version_metadata(config)
    manifest=master_manifest(config)
    entry=next((row for row in manifest['master_versions']+manifest['daily_versions'] if row.get('name')=='stages'),None)
    if entry is None:raise SyncError('Stage master missing from current manifest')
    raw=download(entry['uri'],32*1024*1024)
    stages=table_from_archive(raw,entry,base64.b64decode(config['password_b64'],validate=True))
    if not stages or any(type(row.get('id')) is not int or type(row.get('stage_group_id')) is not int for row in stages):raise SyncError('Stage master schema changed')
    report={'state':'verified','checkedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'versionInfo':release,'masterTableCount':len(manifest['master_versions']),'dailyTableCount':len(manifest['daily_versions']),'verifiedArchive':{'table':'stages','version':entry['version'],'rows':len(stages),'crc':entry['crc'],'sha256':hashlib.sha256(raw).hexdigest()}}
    report['assetManifest']={}
    for name in ['resources','patch_resources']:
        rows=manifest.get(name,[])
        if not isinstance(rows,list):raise SyncError('Asset manifest schema changed')
        samples=[]
        for row in rows[:3]:
            sample={key:value for key,value in row.items() if key in {'path','version','size','decompressed_size','crc','type_id','disable','old_version','current_version','status'} and isinstance(value,(str,int,float,bool))}
            for key in ['uri','url']:
                if isinstance(row.get(key),str):
                    address=urllib.parse.urlsplit(row[key])
                    sample[key+'Path']=address.path
                    sample[key+'Origin']=urllib.parse.urlunsplit((address.scheme,address.netloc,'','',''))
                    sample[key+'QueryKeys']=sorted(urllib.parse.parse_qs(address.query))
            samples.append(sample)
        report['assetManifest'][name]={'count':len(rows),'keys':sorted({str(key) for row in rows for key in row}),'samples':samples,'paths':[row.get('path') for row in rows]}
    if config.get('signing_seed_b64'):
        details=read_game(config,'/information/list')
        if not isinstance(details.get('gacha_group_events'),list):raise SyncError('Gacha schedule schema changed')
        report['gachaEventCount']=len(details['gacha_group_events'])
    target=Path(__file__).resolve().parents[1]/'data'/'sync-check.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

def run():
    data=Path(__file__).resolve().parents[1]/'data'
    previous=json.loads((data/'catalog.json').read_text(encoding='utf-8'))
    attempt=datetime.datetime.now(datetime.timezone.utc).isoformat()
    release={}
    try:
        config=configured_game()
        release=version_metadata(config,previous)
        with tempfile.TemporaryDirectory(prefix='.sync-',dir=data) as temporary:
            destination=Path(temporary)
            snapshot=build_snapshot(config,previous,destination,release)
            catalog=snapshot.pop('catalog')
            for name,value in [('catalog.json',catalog),('events.json',snapshot)]:
                (destination/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
            files=sorted((path for path in destination.rglob('*') if path.is_file()),key=lambda path:(path.name in {'index.json','catalog.json','events.json'},str(path)))
            for path in files:
                target=data/path.relative_to(destination)
                target.parent.mkdir(parents=True,exist_ok=True)
                os.replace(path,target)
        save_status(data,{'schemaVersion':1,'state':'success','lastAttemptAt':attempt,'lastSuccessAt':snapshot['updatedAt'],'versionInfo':release})
    except Exception as error:
        reason='connection-config' if getattr(error,'code',None) in {2,200} else 'sync-error'
        save_status(data,{'schemaVersion':1,'state':'error','reason':reason,'errorType':type(error).__name__,'lastAttemptAt':attempt,'lastSuccessAt':previous.get('updatedAt'),'versionInfo':release})
        raise
    print(json.dumps({'result':'success','events':len(snapshot['events']),'chars':len(snapshot['charProfiles']),'updatedAt':snapshot['updatedAt'],'tables':snapshot['verification'],'catalogRelations':catalog['relations'],'gimmickLabels':catalog['gimmicks']},ensure_ascii=False))

if __name__=='__main__':
    try:
        if sys.argv[1:]==['--check']:check_connection()
        elif not sys.argv[1:]:run()
        else:raise SyncError('Unknown synchronization command')
    except SyncError as error:
        print(f'Synchronization stopped: {error}',file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f'Synchronization stopped: {type(error).__name__}',file=sys.stderr)
        sys.exit(1)
