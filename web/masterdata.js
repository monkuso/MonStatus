import {rawChunk,recordIdentity} from './internalsdk.js';
let shared;
export function createMasterStore(index,fetchBytes=async url=>{const response=await fetch(url,{cache:'no-cache'});if(!response.ok)throw new Error(`データ取得エラー (${response.status})`);return response.arrayBuffer();}){
  const cache=new Map(),whole=new Map();
  const referenceNames=new Map(Object.keys(index.tables).map(name=>[(name.endsWith('ies')?name.slice(0,-3)+'y':name.endsWith('s')?name.slice(0,-1):name)+'_id',name]));
  const summaryMaps=new Map(Object.entries(index.entities||{}).map(([name,rows])=>[name,new Map(rows.map(row=>[row.id,row]))]));
  for(const rows of Object.values(index.collections||{}))for(const row of rows){if(!summaryMaps.has(row.table))summaryMaps.set(row.table,new Map());summaryMaps.get(row.table).set(recordIdentity(index,row.table,row),row);}
  async function chunk(table,part){
    if(!part||!rawChunk(index,table,part.firstId))throw new Error('対象の配信データ範囲がありません。');
    const key=table+':'+part.sha256;if(cache.has(key))return cache.get(key);
    const pending=(async()=>{const bytes=await fetchBytes('./data/internal/'+part.file),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');if(hash!==part.sha256)throw new Error('データの整合性が一致しません。再読み込みしてください。');const result=JSON.parse(new TextDecoder().decode(bytes));if(result.schemaVersion!==1||result.table!==table||!Array.isArray(result.rows))throw new Error('データ形式が一致しません。');return result.rows;})();cache.set(key,pending);try{return await pending;}catch(error){cache.delete(key);throw error;}
  }
  async function record(table,id){const part=rawChunk(index,table,id);return part?(await chunk(table,part)).find(row=>recordIdentity(index,table,row)===id)||null:null;}
  async function all(table){if(!index.tables[table])return [];if(index.tables[table].status==='error')throw new Error('このテーブルは取得エラーのため表示できません。');if(!whole.has(table))whole.set(table,Promise.all(index.tables[table].chunks.map(part=>chunk(table,part))).then(parts=>parts.flat()).catch(error=>{whole.delete(table);throw error;}));return whole.get(table);}
  async function related(table,id,target){const ids=[...new Set(index.relations?.[table]?.[String(id)]?.[target]||[])];return (await Promise.all(ids.map(id=>record(target,id)))).filter(Boolean);}
  const summary=(table,id)=>summaryMaps.get(table)?.get(id)||null;
  async function lookup(table,id){if(!index.tables[table]||index.tables[table].identityField==='_recordIndex')return null;return summary(table,id)||record(table,id);}
  function characterItemId(id){const rule=index.referenceRules?.characterItem;return rule&&Number.isInteger(id)&&id>=rule.minimum&&id<=rule.maximum?id-rule.offset:null;}
  async function resolve(table,id){const direct=await lookup(table,id);if(direct)return {table,id,row:direct,sourceTable:table,sourceId:id};if(table==='items'){const charId=characterItemId(id);if(charId!==null){const row=await lookup('chars',charId);if(row)return {table:'chars',id:charId,row,sourceTable:table,sourceId:id};}}return null;}
  function target(table,field){const explicit=index.references?.[table]?.[field]||referenceNames.get(field);if(explicit)return explicit;if(/(^|_)char_id\d*$/.test(field))return 'chars';if(/(^|_)item_id\d*$/.test(field))return 'items';if(/^connect_skill_conditions_id_[12]_[12]$/.test(field))return 'connect_skill_conditions';if(/^assist_skill_effect_id_[123]$/.test(field))return 'assist_skill_effects';return null;}
  async function matching(table,field,id){return (await all(table)).filter(row=>row[field]===id);}
  return {index,chunk,record,all,related,summary,lookup,resolve,characterItemId,target,matching};
}
export async function loadMasterStore(){if(!shared)shared=(async()=>{const response=await fetch('./data/internal/index.json',{cache:'no-cache'});if(!response.ok)throw new Error('詳細データの索引を取得できませんでした。');return createMasterStore(await response.json());})().catch(error=>{shared=null;throw error;});return shared;}
