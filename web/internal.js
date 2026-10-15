import {queryInternal,rawChunk,recordIdentity} from './internalsdk.js';
import {cleanText,assetImageUrl} from './hubsdk.js?v=assets1';
import {attributeMeta} from './sdk.js';
import {loadCharacterInfo} from './charactersdk.js';
import {renderCharacter} from './character-view.js?v=assets1';
const $=id=>document.getElementById(id);
const titles={chars:'キャラクター',stage_groups:'クエスト',stages:'ステージ',assets:'画像候補',tables:'全内部テーブル'};
const labels={chars:'キャラ定義',stage_groups:'クエスト定義',stages:'ステージ定義',char_skills:'友情・スキル',strike_shots:'ストライクショット',shot_skills:'ショットスキル',char_evolutions:'進化・形態',stage_phases:'バトルフェーズ',stage_gimmicks:'ギミック',stage_notes:'ステージ注記',stage_group_notes:'クエスト注記',stage_phase_blocks:'ブロック',stage_phase_layouts:'フェーズ配置',stage_phase_images:'フェーズ画像',stage_class_catalogs:'クエスト分類'};
const state={index:null,assets:null,events:[],orphans:[],kind:'chars',filter:'candidate',text:'',table:'chars',chunk:0,limit:36,tableRows:[]};
const date=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const cache=new Map();
let requestId=0;
let tableRequestId=0;
const el=(tag,text='',className='')=>{const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;return node;};
const button=(text,action,className='subtle')=>{const node=el('button',text,className);node.type='button';node.addEventListener('click',action);return node;};
const link=(text,url)=>{const node=el('a',text,'external');node.href=url;return node;};
const stamp=value=>typeof value==='number'&&Number.isFinite(value)&&value>0?date.format(new Date(value*1000))+' JST':String(value);
const error=message=>{$('internal-error').hidden=!message;$('internal-error').textContent=message||'';};
async function json(url){const response=await fetch(url,{cache:'no-cache'});if(!response.ok)throw new Error(`データ取得に失敗しました (${response.status})。更新後に再度確認してください。`);return response.json();}
function imageFor(table,row){if(table==='assets')return /^assets\/internal\/\d+\.webp$/.test(row.image)?row.image:null;if(table==='chars')return state.assets.characters?.[String(row.skin_id||row.id)]||null;if(table==='stage_groups')return state.assets.quests?.[row.banner_file_name]||null;return null;}
function picture(parent,source,alt,className){if(typeof source!=='string'||!/^assets\/[a-zA-Z0-9_./-]+$/.test(source))return;const image=el('img','',className);image.src=assetImageUrl(source,state.assets);image.alt=cleanText(alt);image.loading='lazy';image.decoding='async';parent.append(image);}
async function loadChunk(table,chunk){
  if(!chunk||!rawChunk(state.index,table,chunk.firstId))throw new Error('対象のデータ範囲がありません。');
  const key=table+':'+chunk.sha256;
  if(cache.has(key))return cache.get(key);
  const pending=(async()=>{
  const response=await fetch('./data/internal/'+chunk.file,{cache:'no-cache'});
  if(!response.ok)throw new Error('内部データを取得できませんでした。');
  const bytes=await response.arrayBuffer();
  const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(value=>value.toString(16).padStart(2,'0')).join('');
  if(digest!==chunk.sha256)throw new Error('内部データの整合性が一致しません。ページを再読み込みしてください。');
  const data=JSON.parse(new TextDecoder().decode(bytes));
  if(data.schemaVersion!==1||data.table!==table||!Array.isArray(data.rows))throw new Error('内部データの形式が一致しません。');
  return data.rows;
  })();
  cache.set(key,pending);
  try{return await pending;}catch(exception){cache.delete(key);throw exception;}
}
async function record(table,id){const chunk=rawChunk(state.index,table,id);if(!chunk)return null;return (await loadChunk(table,chunk)).find(row=>recordIdentity(state.index,table,row)===id)||null;}
async function relatedRecords(table,id,target){const ids=state.index.relations?.[table]?.[String(id)]?.[target]||[];return (await Promise.all(ids.map(id=>record(target,id)))).filter(Boolean);}
async function allRecords(table){const meta=state.index.tables[table];if(!meta)return [];return (await Promise.all(meta.chunks.map(chunk=>loadChunk(table,chunk)))).flat();}
function rawTable(row){const table=el('table','','internal-raw');for(const [key,value] of Object.entries(row)){const tr=el('tr'),cell=el('td');if(value!==null&&typeof value==='object')cell.append(el('pre',JSON.stringify(value,null,2)));else cell.append(el('span',String(value)));if(key.endsWith('_at')&&typeof value==='number'&&value>0)cell.append(el('p',stamp(value),'internal-hint'));tr.append(el('th',key),cell);table.append(tr);}return table;}
function related(parent,table,row){
  const sets=state.index.relations?.[table]?.[String(recordIdentity(state.index,table,row))]||{};
  for(const [target,ids] of Object.entries(sets)){const details=el('details');details.append(el('summary',`${labels[target]||target} · ${ids.length}件`));const links=el('div','','internal-related');for(const id of ids)links.append(button(`ID ${id}`,()=>showRecord(target,id)));details.append(links);parent.append(details);}
  const direct={virtual_char_id:'chars',char_id:'chars',stage_id:'stages',stage_group_id:'stage_groups',entry_stage_group_id:'stage_groups',strike_shot_id:'strike_shots',enhanced_strike_shot_id:'strike_shots',shot_skill_id:'shot_skills',stage_phase_id:'stage_phases'};
  const links=el('div','','internal-related');
  for(const [field,target] of Object.entries(direct))if(typeof row[field]==='number'&&row[field]>0&&rawChunk(state.index,target,row[field]))links.append(button(`${field}: ${row[field]} →`,()=>showRecord(target,row[field])));
  if(links.children.length)parent.append(el('h3','関連定義'),links);
}
async function showRecord(table,id){
  const token=++requestId,dialog=$('internal-detail'),body=$('internal-detail-body');body.replaceChildren(el('h2','読み込み中…'));if(!dialog.open)dialog.showModal();
  try{
    const chunk=rawChunk(state.index,table,id),rows=await loadChunk(table,chunk);
    if(token!==requestId)return;
    const row=rows.find(value=>recordIdentity(state.index,table,value)===id);if(!row)throw new Error('このID・レコード番号の内部定義は見つかりません。');
    const title=el('h2',cleanText(row.name||labels[table]||'データ情報'));title.id='internal-detail-title';body.replaceChildren(title);
    dialog.querySelector('.dialog-top span').textContent=table==='chars'?'キャラクター情報':labels[table]||'詳細情報';
    if(table==='chars'){
      const profile=await loadCharacterInfo(row,{record,related:relatedRecords,all:allRecords});
      if(token!==requestId)return;
      body.replaceChildren(renderCharacter(profile,{assets:state.assets,image:imageFor(table,row),attributeImage:state.assets.attributes?.[String(row.attribute_id)]}));
    }else{
      picture(body,imageFor(table,row),row.name||String(id),'internal-detail-image');
      if(row.description)body.append(el('p',cleanText(row.description),'readable-description'));
      const information=el('div','','readable-facts');
      for(const [field,label] of [['cost','消費スタミナ'],['experience','獲得経験値'],['bonus_turn','スピードクリア'],['required_rank','必要ランク'],['require_cnt','必要ターン']])if(typeof row[field]==='number'){
        const item=el('div');item.append(el('span',label),el('strong',new Intl.NumberFormat('ja-JP').format(row[field])));information.append(item);
      }
      if(information.children.length)body.append(information);
    }
    if(state.index.tables[table].identityField==='_recordIndex')body.append(el('p','このテーブルにはゲームID列がないため、サイト側のレコード番号を使っています。_recordIndexはゲーム由来の値ではありません。','internal-hint'));
    if(table==='stage_groups'){const stages=(state.index.entities.stages||[]).filter(stage=>stage.stage_group_id===id);const links=el('div','','internal-related');for(const stage of stages)links.append(button(cleanText(stage.name||String(stage.id)),()=>showRecord('stages',stage.id)));body.append(el('h3',`ステージ · ${stages.length}件`),links);}
    body.append(el('p',`データ確認 ${date.format(new Date(state.index.updatedAt))} JST`,'internal-hint'));
    const technical=el('details','','character-technical');technical.append(el('summary','解析用データを見る（上級者向け）'));related(technical,table,row);technical.append(el('h3',`配信フィールド · ${Object.keys(row).length}項目`),rawTable(row));
    const raw=el('details');raw.append(el('summary','元のJSON'),el('pre',JSON.stringify(row,null,2),'raw-json'));technical.append(raw,link('配信JSONを開く ↗','./data/internal/'+chunk.file));body.append(technical);dialog.scrollTop=0;
  }catch(exception){if(token===requestId)body.replaceChildren(el('p',exception.message,'error'));}
}
function showAsset(row){++requestId;const body=$('internal-detail-body'),title=el('h2',row.name);title.id='internal-detail-title';body.replaceChildren(title);picture(body,imageFor('assets',row),row.name,'internal-detail-image');body.append(el('p','画像自体はPNGとして検証済みです。仮想ファイル名はハッシュ一致による候補です。未実装キャラであるとは断定していません。','internal-hint'),rawTable(row));if(!$('internal-detail').open)$('internal-detail').showModal();}
function card(entry,table){
  const row=entry.row,id=table==='assets'?row.id:recordIdentity(state.index,table,row),identity=state.index.tables[table]?.identityField==='_recordIndex'?'レコード':'ID',node=button('',()=>table==='assets'?showAsset(row):showRecord(table,id),'card internal-card');picture(node,imageFor(table,row),row.name||String(id),'internal-image');const body=el('div','','card-body');body.append(el('span',`${labels[table]||titles[table]||table} / ${identity} ${id}`,'eyebrow'),el('h3',cleanText(row.name||`${identity} ${id}`)));
  if(table==='chars'){
    const attribute=attributeMeta(row.attribute_id);body.querySelector('.eyebrow').textContent=[typeof row.rarity==='number'&&row.rarity<=6?'★'.repeat(row.rarity):null,attribute?attribute.label+'属性':null].filter(Boolean).join(' · ')||'キャラクター';
    if(row.friendshipNames?.length){const preview=el('div','','character-card-skills');preview.append(el('small','友情コンボ'));for(const name of row.friendshipNames)preview.append(el('span',cleanText(name)));body.append(preview);}
  }
  for(const reason of entry.reasons||[]){body.append(el('span',reason.label,'tag'));if(reason.field.endsWith('_at'))body.append(el('span',stamp(reason.value),'internal-evidence'));}
  if(table==='assets'){body.append(el('span',row.otherKnownReferences?.length?'別用途の参照あり・名前ハッシュ衝突':'キャラ定義から未参照の候補','tag'),el('span',`${row.width} × ${row.height} · PNG検証済み`,'internal-evidence'));}
  if(!entry.reasons?.length&&table!=='assets')body.append(el('span','配信データの登録情報','internal-evidence'));body.append(el('span',table==='chars'?'能力・スキルを見る →':'詳細を見る →','arrow'));node.append(body);return node;
}
function render(){
  if(!state.index)return;
  const kind=state.kind,table=kind==='tables'?state.table:kind;
  $('internal-title').textContent=titles[kind];document.querySelectorAll('[data-kind]').forEach(node=>node.setAttribute('aria-pressed',String(node.dataset.kind===kind)));
  $('internal-filter').hidden=kind==='tables'||kind==='assets';$('internal-table').hidden=kind!=='tables';$('internal-chunk').hidden=kind!=='tables';
  let rows;
  if(kind==='assets')rows=state.orphans.filter(row=>!state.text||`${row.id} ${row.resourceNameCandidate} ${row.member}`.toLocaleLowerCase().includes(state.text.toLocaleLowerCase())).map(row=>({row}));
  else if(kind==='tables'){const term=state.text.normalize('NFKC').toLocaleLowerCase('ja');rows=state.tableRows.filter(row=>!term||JSON.stringify(row).normalize('NFKC').toLocaleLowerCase('ja').includes(term)).map(row=>({row}));}
  else rows=queryInternal(state.index.entities[kind]||[],{kind,filter:state.filter,text:state.text,events:state.events,groups:state.index.entities.stage_groups||[]});
  $('internal-note').textContent=kind==='assets'?'既存のキャラ画像探索範囲を広げて見つけた照合候補です。旧画像・特殊用途・ハッシュ衝突を含みます。':kind==='tables'?'選択したID範囲の内部レコードを検索します。全フィールドはレコードを押して確認できます。':'候補の根拠を併記しています。「すべての内部定義」で公開済み・敵用なども含めて検索できます。';
  $('internal-count').textContent=`${rows.length.toLocaleString('ja-JP')}件 · ${Math.min(rows.length,state.limit)}件表示`;
  const grid=$('internal-grid');grid.replaceChildren(...rows.slice(0,state.limit).map(row=>card(row,table)));if(!rows.length)grid.append(el('p','条件に合う定義がありません。判定根拠や名前を変更してください。','internal-empty'));grid.setAttribute('aria-busy','false');$('internal-more').hidden=rows.length<=state.limit;
}
async function loadTable(){
  const token=++tableRequestId,table=state.table,chunkIndex=state.chunk;
  try{error('');const meta=state.index.tables[table],identity=meta.identityField==='_recordIndex'?'レコード':'ID';$('internal-chunk').replaceChildren(...meta.chunks.map((chunk,index)=>{const option=el('option',`${identity} ${chunk.firstId} 〜 ${chunk.lastId}`);option.value=String(index);return option;}));$('internal-chunk').value=String(chunkIndex);const rows=meta.chunks.length?await loadChunk(table,meta.chunks[chunkIndex]):[];if(token!==tableRequestId)return;state.tableRows=rows;render();}catch(exception){if(token===tableRequestId)error(exception.message);}
}
document.querySelectorAll('[data-kind]').forEach(node=>node.addEventListener('click',()=>{state.kind=node.dataset.kind;state.limit=36;history.replaceState(null,'',`?kind=${state.kind}`);if(state.kind==='tables')loadTable();else render();}));
$('internal-search').addEventListener('input',()=>{state.text=$('internal-search').value;state.limit=36;render();});$('internal-filter').addEventListener('change',()=>{state.filter=$('internal-filter').value;state.limit=36;render();});$('internal-table').addEventListener('change',()=>{state.table=$('internal-table').value;state.chunk=0;state.limit=36;loadTable();});$('internal-chunk').addEventListener('change',()=>{state.chunk=Number($('internal-chunk').value);state.limit=36;loadTable();});$('internal-more').addEventListener('click',()=>{state.limit+=36;render();});$('internal-close').addEventListener('click',()=>{$('internal-detail').close();requestId++;});$('internal-detail').addEventListener('click',event=>{if(event.target===$('internal-detail')){$('internal-detail').close();requestId++;}});
try{
  const [index,assets,events,orphans]=await Promise.all([json('./data/internal/index.json'),json('./data/assets.json'),json('./data/events.json'),json('./data/orphanassets.json')]);
  if(index.schemaVersion!==1||!index.entities||!index.tables)throw new Error('内部データの形式が一致しません。');
  Object.assign(state,{index,assets,events:events.events||[],orphans:orphans.rows||[]});const parameters=new URLSearchParams(location.search),kind=parameters.get('kind');if(Object.hasOwn(titles,kind))state.kind=kind;
  $('internal-status').textContent=`配信確認 ${date.format(new Date(index.updatedAt))} JST · キャラ ${(index.entities.chars||[]).length.toLocaleString()}件 / ステージ ${index.tables.stages.rows.toLocaleString()}件`;
  $('internal-table').replaceChildren(...Object.keys(index.tables).map(name=>{const option=el('option',`${labels[name]||name} · ${index.tables[name].rows.toLocaleString()}件`);option.value=name;return option;}));$('internal-table').value=state.table;if(state.kind==='tables')await loadTable();else render();
  const table=parameters.get('table'),id=parameters.get('id');if(Object.hasOwn(index.tables,table)&&/^\d+$/.test(id||''))await showRecord(table,Number(id));
}catch(exception){error(exception.message);$('internal-status').textContent='内部データの初回同期・公開状態を確認してください。';$('internal-grid').setAttribute('aria-busy','false');}
