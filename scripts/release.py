import datetime
import json
import re
import urllib.request

RELEASE_URL='https://itunes.apple.com/lookup?id=658511662&country=jp'

def latest_release():
    request=urllib.request.Request(RELEASE_URL,headers={'User-Agent':'MonStatus release monitor'})
    with urllib.request.urlopen(request,timeout=20) as response:
        raw=response.read(1024*1024+1)
        if response.status!=200 or len(raw)>1024*1024:raise ValueError('Release response rejected')
    result=json.loads(raw)
    rows=result.get('results')
    if not isinstance(rows,list) or len(rows)!=1:raise ValueError('Release identity missing')
    row=rows[0]
    if row.get('trackId')!=658511662 or row.get('bundleId')!='jp.co.mixi.monsterstrike' or not re.fullmatch(r'\d+\.\d+\.\d+',str(row.get('version',''))):raise ValueError('Release identity rejected')
    return {'status':'verified','version':row['version'],'platform':'ios','releasedAt':row.get('currentVersionReleaseDate'),'source':RELEASE_URL}

def version_metadata(config,previous=None):
    try:metadata=latest_release()
    except Exception as error:metadata={'status':'unavailable','platform':'ios','source':RELEASE_URL,'errorType':type(error).__name__}
    metadata['checkedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata['configuredClientVersion']=config.get('app_version')
    old=(previous or {}).get('versionInfo',{}).get('version')
    metadata['changedSinceLastSync']=bool(old and metadata.get('version') and old!=metadata['version'])
    return metadata
