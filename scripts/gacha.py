def merge_history(current,previous,keys,timestamp):
    result={}
    for row in previous:
        key=tuple(row.get(field) for field in keys)
        result[key]={**row,'retainedForHistory':True}
    for row in current:
        key=tuple(row.get(field) for field in keys)
        result[key]={**row,'observedAt':row.get('observedAt') or timestamp,'retainedForHistory':False}
    return list(result.values())

def retain_gacha_history(catalog,previous,timestamp):
    previous=previous or {}
    for name,keys in [('gachaEvents',['id','gacha_group_id','start_at','end_at']),('gachaMessages',['messageId','gachaGroupId','startAt','endAt']),('gachaRates',['messageId','gachaGroupId','startAt','endAt','title'])]:
        catalog[name]=merge_history(catalog.get(name,[]),previous.get(name,[]),keys,timestamp)
    groups={row['id'] for row in catalog['tables']['gacha_groups']}
    catalog['gachaCoverage']={'observedAt':timestamp,'definitions':len(groups),'scheduleRecords':len(catalog['gachaEvents']),'currentScheduleRecords':sum(not row.get('retainedForHistory') for row in catalog['gachaEvents']),'rateRecords':len(catalog['gachaRates']),'messageRecords':len(catalog['gachaMessages']),'unresolvedScheduleGroupIds':sorted({row['gacha_group_id'] for row in catalog['gachaEvents'] if row['gacha_group_id'] not in groups}),'tables':{name:len(rows) for name,rows in catalog['tables'].items() if 'gacha' in name}}
