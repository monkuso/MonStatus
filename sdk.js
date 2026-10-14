export const isLongTerm = event => Number.isFinite(event.endAt) && event.endAt >= 4102444800;
export const displayName = name => name.replace(/\[C\d+:([^\]]*)\]/g,'$1');
export const jstDay = (now=Date.now(), offset=0) => new Date(now+9*3600000+offset*86400000).toISOString().slice(0,10);
export function syncStatus(snapshot, now=Date.now()) {
  const age=now-Date.parse(snapshot.updatedAt);
  if(!Number.isFinite(age))return {state:'stale',label:'取得日時を確認してください'};
  if(snapshot.sync?.mode!=='github-actions')return {state:'saved',label:'保存済みデータ'};
  if(age>90*60000)return {state:'stale',label:'同期が遅れています · 最終取得を確認'};
  return {state:'fresh',label:'クラウド同期 · 30分間隔'};
}
export const eventStatus = (event, seconds = Date.now()/1000) => {
  if (!Number.isFinite(event.startAt) || !Number.isFinite(event.endAt)) return 'unknown';
  if (seconds < event.startAt) return 'upcoming';
  if (seconds > event.endAt) return 'ended';
  return 'active';
};
export const GIMMICK_SLOT_MASKS = Object.freeze([0x2, 0x1, 0x4, 0x18, 0x20, 0x40, 0x80, 0x100, 0x800, 0x1000, 0x200, 0x400]);
export const GIMMICK_SLOT_META = Object.freeze(GIMMICK_SLOT_MASKS.map((mask, index) => Object.freeze({
  index,
  mask,
  label: `ギミック${index+1}`,
  spriteFrameId: [546,545,551,544,543,547,552,548,550,549,542,541][index],
  textIdHex: ['0x144df23b','0x8d44a381','0xfa439317','0x642706b4','0x13203622','0x8a296798','0xfd2e570e','0x6d914a9f','0x32c34b61','0xe5711e67','0x1a967a09','0x45c47bf7'][index],
})));
export function decodeGimmicks(flag = 0, highlightFlag = 0) {
  const normal=Number.isInteger(flag) ? flag>>>0 : 0;
  const featured=Number.isInteger(highlightFlag) ? highlightFlag>>>0 : 0;
  return GIMMICK_SLOT_META.map(meta => {
    const inNormal=(normal & meta.mask)!==0;
    const inFeatured=(featured & meta.mask)!==0;
    const status = inNormal && inFeatured ? 'featured' : (inNormal || inFeatured) ? 'present' : 'absent';
    return {...meta, status};
  });
}
export const hasAnyGimmick = event => (event?.gimmickFlag>>>0) !== 0 || (event?.highlightGimmickFlag>>>0) !== 0;
export const ATTRIBUTE_META = Object.freeze({
  1:{id:1,key:'fire',label:'火',symbol:'火',color:'#d94747'},
  2:{id:2,key:'water',label:'水',symbol:'水',color:'#2a6fd1'},
  4:{id:4,key:'wood',label:'木',symbol:'木',color:'#3f9c47'},
  8:{id:8,key:'light',label:'光',symbol:'光',color:'#d8a93a'},
  16:{id:16,key:'dark',label:'闇',symbol:'闇',color:'#6c4bb2'},
});
export const ATTRIBUTE_ADVANTAGE = Object.freeze({1:2,2:4,4:1,8:16,16:8});
export const attributeAdvantage = id => ATTRIBUTE_ADVANTAGE[id] ?? null;
export const attributeMeta = id => ATTRIBUTE_META[id] ?? null;
export const RARITY_SYMBOLS = Object.freeze({1:'★1',2:'★2',3:'★3',4:'★4',5:'★5',6:'★6'});
export function lookupChars(snapshot, ids) {
  if(!Array.isArray(ids) || !snapshot?.charProfiles) return [];
  return ids.map(id => snapshot.charProfiles[String(id)]).filter(Boolean);
}
export function queryEvents(events, {view='active', now=Date.now()/1000, text='', includeLongTerm=false, includeConditional=false, favorites=new Set(), sort='ending', day=null}={}) {
  const search=text.trim().normalize('NFKC').toLocaleLowerCase('ja');
  const dayStart=day ? Date.parse(`${day}T00:00:00+09:00`)/1000 : null;
  const dayEnd=dayStart === null ? null : dayStart+86400-1;
  const selected=events.filter(event=>{
    if (!includeLongTerm && isLongTerm(event)) return false;
    if (!includeConditional && event.sourceTable !== 'stage_group_events') return false;
    if (search && !`${event.name} ${event.questName ?? ''}`.normalize('NFKC').toLocaleLowerCase('ja').includes(search)) return false;
    if (view==='favorites' && !favorites.has(event.id)) return false;
    if (day && !(event.startAt<=dayEnd && event.endAt>=dayStart)) return false;
    const status=eventStatus(event,day ? dayStart : now);
    if (!day && (view==='active' || view==='upcoming') && status!==view) return false;
    return true;
  });
  const unique=new Map();
  for(const event of selected){const key=JSON.stringify([event.sourceTable,event.stageGroupId,event.name,event.questName,event.startAt,event.endAt]);if(!unique.has(key))unique.set(key,event);}
  return [...unique.values()].sort((a,b)=> sort==='name' ? a.name.localeCompare(b.name,'ja') : (sort==='starting' ? a.startAt-b.startAt : a.endAt-b.endAt) || a.id.localeCompare(b.id));
}
export async function loadEvents(url='./events.json') {
  const response=await fetch(url,{cache:'no-cache'});
  if(!response.ok) throw new Error(`HTTP ${response.status}`);
  const snapshot=await response.json();
  if(![1,2,3].includes(snapshot.schemaVersion) || !Array.isArray(snapshot.events)) throw new Error('イベントデータの形式が一致しません');
  if(snapshot.events.some(e=>typeof e.id!=='string' || typeof e.name!=='string' || !Number.isFinite(e.startAt) || !Number.isFinite(e.endAt))) throw new Error('イベントデータに不正な項目があります');
  return snapshot;
}
