export const seconds=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
export function classifyCharacter(row,now=Date.now()/1000){
  const reasons=[];
  if(row.id>=26000&&row.id<27000)reasons.push({kind:'special-range',label:'特殊ID範囲',field:'id',value:row.id});
  if(seconds(row.collection_enable_at)!==null&&row.collection_enable_at>now)reasons.push({kind:'future',label:row.collection_enable_at>now+366*86400?'遠未来の公開時刻':'図鑑公開時刻が未来',field:'collection_enable_at',value:row.collection_enable_at});
  if(row.sort_id===0&&typeof row.virtual_char_id==='number'&&row.virtual_char_id===0)reasons.push({kind:'info-mask',label:'情報マスク条件',field:'sort_id / virtual_char_id',value:'0 / 0'});
  return {reasons,masked:reasons.length?true:seconds(row.collection_enable_at)!==null&&typeof row.sort_id==='number'&&typeof row.virtual_char_id==='number'?false:null};
}
export function classifyQuest(row,events=[],now=Date.now()/1000){
  const reasons=[];
  if(seconds(row.released_at)!==null&&row.released_at>now)reasons.push({kind:'future',label:row.released_at>now+366*86400?'遠未来の公開時刻':'公開時刻が未来',field:'released_at',value:row.released_at});
  if(typeof row.test_flag==='number'&&row.test_flag!==0)reasons.push({kind:'test',label:'test_flag 設定あり',field:'test_flag',value:row.test_flag});
  const schedules=events.filter(e=>e.sourceTable==='stage_group_events'&&e.stageGroupId===row.id);
  if(events.length&&!schedules.length)reasons.push({kind:'unlisted',label:'取得した出現一覧に参照なし',field:'stage_group_events',value:'参照なし'});
  if(schedules.some(e=>e.startAt>now))reasons.push({kind:'upcoming',label:'今後の出現期間あり',field:'stage_group_events.start_at',value:Math.min(...schedules.filter(e=>e.startAt>now).map(e=>e.startAt))});
  return {reasons};
}
export function queryInternal(rows,{text='',filter='candidate',kind='chars',events=[],groups=[],now=Date.now()/1000}={}){
  const term=text.normalize('NFKC').toLocaleLowerCase('ja');
  const groupMap=new Map(groups.map(row=>[row.id,row]));
  return rows.map(row=>({row,...(kind==='chars'?classifyCharacter(row,now):classifyQuest(kind==='stages'?groupMap.get(row.stage_group_id)||{id:row.stage_group_id}:row,events,now))})).filter(entry=>(!term||`${entry.row.id} ${entry.row.name||''} ${groupMap.get(entry.row.stage_group_id)?.name||''}`.normalize('NFKC').toLocaleLowerCase('ja').includes(term))&&(filter==='all'||(filter==='candidate'?entry.reasons.some(r=>['future','info-mask','test'].includes(r.kind)):entry.reasons.some(r=>r.kind===filter)))).sort((a,b)=>(b.row.updated_at||0)-(a.row.updated_at||0)||b.row.id-a.row.id);
}
export function rawChunk(index,table,id){
  if(!/^[a-z_]+$/.test(table))return null;
  const entry=index.tables[table]?.chunks.find(chunk=>chunk.firstId<=id&&chunk.lastId>=id);
  if(!entry||!new RegExp(`^${table}-[0-9]{4}\\.json$`).test(entry.file))return null;
  return entry;
}
export function recordIdentity(index,table,row){return row[index.tables[table]?.identityField||'id'];}
