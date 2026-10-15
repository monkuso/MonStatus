import {displayName,eventStatus,isLongTerm,jstDay} from './sdk.js';
import {createLibrary} from './librarysdk.js';
export const cleanText=value=>displayName(String(value??'')).replace(/\[LF\]/g,'\n').replace(/\[GIMMICK:([^\]]+)\]/g,'$1').replace(/\[GIMMICK_END\]/g,'').replace(/\[(?:IMG|LC|LR|L|S|B|C_END)[^\]]*\]/g,'').trim();
export const normalized=value=>cleanText(value).normalize('NFKC').toLocaleLowerCase('ja');
export const visibleAt=(row,now)=>!Number.isFinite(row.visible_at)||row.visible_at<=now;
export const overlapDay=(start,end,day)=>{const a=Date.parse(`${day}T00:00:00+09:00`)/1000;return start<=a+86399&&end>=a;};
export const permanentGacha=event=>event.end_at>=4102444800;
export const gachaTitle=(event,group)=>event?.header_title||event?.name||group?.name||'ガチャ';
export function createHub(catalog,events,assets={},live=null){
  const data={...catalog,tables:{...catalog.tables}};
  if(live?.tables){
    data.detailObservedAt=data.detailObservedAt||live.updatedAt;
    if(data.gachaScheduleStatus!=='verified'&&Array.isArray(live.tables.gacha_group_events))data.gachaEvents=live.tables.gacha_group_events;
    if(data.weeklyMaxLuckBonusesStatus!=='verified'&&Array.isArray(live.tables.weekly_max_luck_bonuses))data.weeklyMaxLuckBonuses=live.tables.weekly_max_luck_bonuses;
    if(Array.isArray(live.tables.recommends)){const rows=new Map(live.tables.recommends.map(r=>[r.stage_id,r]));for(const r of data.recommendations||[])rows.set(r.stage_id,r);data.recommendations=[...rows.values()];}
    if(data.gachaBannersStatus!=='verified'&&Array.isArray(live.tables.gacha_group_banners))data.gachaBanners=live.tables.gacha_group_banners;
  }
  const library=createLibrary(data),stagesByGroup=new Map();
  for(const stage of library.tables.stages){if(!stagesByGroup.has(stage.stage_group_id))stagesByGroup.set(stage.stage_group_id,[]);stagesByGroup.get(stage.stage_group_id).push(stage);}
  const stageEvents=events?.events||data.stageEvents||[],gachaEvents=data.gachaEvents||[],lucky=data.weeklyMaxLuckBonuses||[],gachaBanners=data.gachaBanners||[];
  const bannersByGroup=new Map();
  for(const b of gachaBanners){if(!bannersByGroup.has(b.gacha_group_id))bannersByGroup.set(b.gacha_group_id,[]);bannersByGroup.get(b.gacha_group_id).push(b);}
  const names={schedule:'スケジュール',gacha:'ガチャ',quest:'クエスト',lucky:'ラキモン',char:'モンスター'};
  function image(kind,value){const url=assets[kind]?.[String(value)];return typeof url==='string'&&/^assets\/[a-zA-Z0-9_./-]+$/.test(url)?url:null;}
  function characterImage(char){return image('characters',char.skin_id||char.id);}
  function attributeImage(aid){return image('attributes',aid);}
  function gachaBannerFile(gachaGroupId,now=Date.now()/1000){const group=library.indexes.gacha_groups.get(gachaGroupId);const list=bannersByGroup.get(gachaGroupId)||bannersByGroup.get(group?.parent_group_id)||[];const active=list.filter(b=>!Number.isFinite(b.start_at)||b.start_at<=now).filter(b=>!Number.isFinite(b.end_at)||b.end_at>=now);const chosen=(active.length?active:list).slice().sort((a,b)=>(b.priority||0)-(a.priority||0)||(b.id||0)-(a.id||0))[0];return chosen?.file_name||null;}
  function gachaImage(group,now=Date.now()/1000){const file=gachaBannerFile(group.id,now);if(file){const direct=image('gachas',file);if(direct)return direct;}return image('gachas',group.image_id);}
  function scheduleRows(){
    const rows=stageEvents.filter(e=>e.sourceTable==='stage_group_events'&&!isLongTerm(e)&&Number.isFinite(e.startAt)&&Number.isFinite(e.endAt)).map(e=>({kind:'quest',key:e.id,id:e.stageGroupId,name:library.indexes.stage_groups.get(e.stageGroupId)?.name||e.questName||e.name,startAt:e.startAt,endAt:e.endAt,attributeId:e.attributeId,source:e})).sort((a,b)=>a.id-b.id||a.startAt-b.startAt||a.endAt-b.endAt);
    const distinct=[];
    for(const row of rows){const previous=distinct.at(-1);if(previous?.id===row.id&&row.startAt<=previous.endAt+1){previous.endAt=Math.max(previous.endAt,row.endAt);}else distinct.push({...row});}
    const appearances=new Map();
    for(const row of distinct){const group=library.indexes.stage_groups.get(row.id);const key=JSON.stringify([normalized(row.name),group?.stage_class_id,row.startAt,row.endAt]);const existing=appearances.get(key);if(existing){existing.groupIds.push(row.id);}else appearances.set(key,{...row,groupIds:[row.id]});}
    return [...appearances.values()];
  }
  function querySchedule({day=null,text='',view='active',now=Date.now()/1000}={}){return scheduleRows().filter(e=>Number.isFinite(e.startAt)&&Number.isFinite(e.endAt)&&(!day||overlapDay(e.startAt,e.endAt,day))&&(!text||normalized(e.name).includes(normalized(text)))&&(day||view==='all'||eventStatus(e,now)===view)).sort((a,b)=>(view==='upcoming'?a.startAt-b.startAt:a.endAt-b.endAt)||a.key.localeCompare(b.key));}
  function quests({text='',attribute='',now=Date.now()/1000}={}){const ids=new Set(stageEvents.filter(e=>eventStatus(e,now)==='active'&&e.sourceTable==='stage_group_events').map(e=>e.stageGroupId));return library.tables.stage_groups.filter(g=>ids.has(g.id)&&(!attribute||g.attribute_id===Number(attribute))&&(!text||normalized(`${g.name} ${g.id}`).includes(normalized(text)))).sort((a,b)=>b.id-a.id);}
  function gachas({text='',all=false,now=Date.now()/1000}={}){const ids=new Set(gachaEvents.filter(e=>!permanentGacha(e)&&visibleAt(e,now)&&eventStatus({startAt:e.start_at,endAt:e.end_at},now)!=='ended').map(e=>e.gacha_group_id));return library.tables.gacha_groups.filter(g=>(all||ids.has(g.id))&&(!text||normalized(`${g.name} ${g.description} ${g.id} ${gachaEvents.filter(e=>e.gacha_group_id===g.id).map(e=>gachaTitle(e,g)).join(' ')}`).includes(normalized(text)))).sort((a,b)=>b.id-a.id);}
  function luckyCharacters(week){return (week.drop_ids||[]).filter(id=>id>0).map(dropId=>({dropId,forms:library.tables.chars.filter(c=>c.drop_id===dropId).sort((a,b)=>(b.rarity||0)-(a.rarity||0)||b.id-a.id)}));}
  function gachaGroupChain(id){const chain=[];let current=library.indexes.gacha_groups.get(id);const seen=new Set();while(current&&!seen.has(current.id)){seen.add(current.id);chain.push(current);if(current.category_id===50008||!current.parent_group_id)break;current=library.indexes.gacha_groups.get(current.parent_group_id);}return chain;}
  function gachaMessages(id,now=Date.now()/1000){const chain=gachaGroupChain(id);const ids=new Set(chain.map(g=>g.id));return (data.gachaMessages||[]).filter(r=>ids.has(r.gachaGroupId)&&r.startAt<=now&&r.endAt>=now);}
  function providedRates(id,now=Date.now()/1000){const messageIds=new Set(gachaMessages(id,now).map(m=>m.messageId));return (data.gachaRates||[]).filter(r=>messageIds.has(r.messageId)&&(r.entries||[]).length);}
  function gachaCharacterIds(id,now=Date.now()/1000){const result=new Set();for(const m of gachaMessages(id,now))for(const cid of m.detailCharacterIds||[])result.add(cid);for(const f of library.gacha(id)?.features||[]){const start=Number.isFinite(f.start_at)?f.start_at:null,end=Number.isFinite(f.end_at)?f.end_at:null;if((start===null||start<=now)&&(end===null||end>=now))result.add(f.char_id);}for(const c of library.gacha(id)?.characters||[])result.add(c.id);if(!result.size){const children=library.tables.gacha_groups.filter(g=>g.parent_group_id===id);for(const child of children){for(const m of (data.gachaMessages||[]).filter(m=>m.gachaGroupId===child.id&&m.startAt<=now&&m.endAt>=now))for(const cid of m.detailCharacterIds||[])result.add(cid);for(const f of library.gacha(child.id)?.features||[]){const start=Number.isFinite(f.start_at)?f.start_at:null,end=Number.isFinite(f.end_at)?f.end_at:null;if((start===null||start<=now)&&(end===null||end>=now))result.add(f.char_id);}}}return [...result].filter(cid=>library.indexes.chars.has(cid));}
  function gachaFeaturedIds(id,now=Date.now()/1000){const result=[];for(const f of library.gacha(id)?.features||[]){const start=Number.isFinite(f.start_at)?f.start_at:null,end=Number.isFinite(f.end_at)?f.end_at:null;if((start===null||start<=now)&&(end===null||end>=now))result.push(f.char_id);}return [...new Set(result)].filter(cid=>library.indexes.chars.has(cid));}
  return {data,library,assets,names,image,characterImage,attributeImage,gachaBannerFile,gachaImage,stagesByGroup,stageEvents,gachaEvents,lucky,gachaBanners,querySchedule,quests,gachas,luckyCharacters,providedRates,gachaMessages,gachaCharacterIds,gachaFeaturedIds,today:jstDay()};
}
