import {displayName,decodeGimmicks} from './sdk.js';
export function createLibrary(data){
  if(data.schemaVersion!==1||!data.tables||!Number.isFinite(Date.parse(data.updatedAt)))throw new Error('図鑑データの形式を確認してください');
  const tables=data.tables;
  for(const name of ['stages','stage_groups','chars','gacha_groups','gachas','stage_gimmicks'])if(!Array.isArray(tables[name]))throw new Error('必要な図鑑データがありません');
  const indexes={};
  for(const name of ['stages','stage_groups','chars','gacha_groups','items','strike_shots']){
    indexes[name]=new Map((tables[name]||[]).map(row=>[row.id,row]));
    if(indexes[name].size!==(tables[name]||[]).length)throw new Error('図鑑データのIDが重複しています');
  }
  function related(name,key,id){return (tables[name]||[]).filter(row=>row[key]===id);}
  function stage(id){
    const row=indexes.stages.get(Number(id));if(!row)return null;
    const group=indexes.stage_groups.get(row.stage_group_id)||null;
    const entries=related('stage_gimmicks','stage_id',row.id);
    const flags=entries.reduce((sum,g)=>[sum[0]|g.gimmick_flag,sum[1]|g.highlight_gimmick_flag],[0,0]);
    const gimmicks=decodeGimmicks(...flags).filter(g=>g.status!=='absent').map(g=>{const text=data.gimmicks?.find(v=>v.mask===g.mask);return {...g,label:text?.label||null,description:text?.description||null};});
    return {row,group,gimmicks,gimmickDataAvailable:entries.length>0,phases:related('stage_phases','stage_id',row.id),notes:[...related('stage_notes','stage_id',row.id),...related('stage_group_notes','stage_group_id',row.stage_group_id)],schedules:(data.stageEvents||[]).filter(e=>e.stageGroupId===row.stage_group_id),community:(data.recommendations||[]).find(r=>r.stage_id===row.id)||null};
  }
  function gacha(id){
    const row=indexes.gacha_groups.get(Number(id));if(!row)return null;
    const entries=related('gachas','gacha_group_id',row.id);
    return {row,characters:[...new Set(entries.map(e=>e.char_id))].map(cid=>indexes.chars.get(cid)).filter(Boolean),unresolvedCharacterIds:[...new Set(entries.map(e=>e.char_id))].filter(cid=>!indexes.chars.has(cid)),features:related('gacha_group_feature_chars','gacha_group_id',row.id),extraCosts:related('gacha_group_extra_cost_items','gacha_group_id',row.id),schedules:(data.gachaEvents||[]).filter(e=>e.gacha_group_id===row.id)};
  }
  function character(id){const row=indexes.chars.get(Number(id));return row?{row,skills:related('char_skills','char_id',row.id),strikeShot:indexes.strike_shots.get(row.strike_shot_id)||null}:null;}
  function search(kind,{text='',attribute='',groupId=null,limit=48,offset=0}={}){
    const names={stage:'stages',gacha:'gacha_groups',char:'chars'};const name=names[kind];if(!name)throw new Error('不明な図鑑カテゴリ');
    const term=text.normalize('NFKC').toLocaleLowerCase('ja').trim();
    const rows=tables[name].filter(row=>{
      if(kind==='stage'&&groupId!==null&&row.stage_group_id!==Number(groupId))return false;
      if(attribute&&row.attribute_id!==Number(attribute))return false;
      const group=kind==='stage'?indexes.stage_groups.get(row.stage_group_id)?.name||'':'';
      return !term||`${displayName(row.name)} ${group} ${row.id}`.normalize('NFKC').toLocaleLowerCase('ja').includes(term);
    }).sort((a,b)=>b.id-a.id);
    return {total:rows.length,rows:rows.slice(offset,offset+limit)};
  }
  return {data,tables,indexes,stage,gacha,character,search};
}
export async function loadLibrary(url='./catalog.json'){
  const response=await fetch(url,{cache:'no-cache'});if(!response.ok)throw new Error(`図鑑の取得に失敗しました (${response.status})`);
  return createLibrary(await response.json());
}
