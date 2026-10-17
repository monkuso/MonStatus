import {cleanText,assetImageUrl} from './hubsdk.js?v=gacha5';
import {tableLabel,fieldLabel} from './data-labels.js';
import {recordIdentity} from './internalsdk.js';
import {loadCharacterInfo} from './charactersdk.js';
import {renderCharacter} from './character-view.js?v=icons2';
import {characterImageElement} from './character-image.js?v=icons2';
const el=(tag,text='',cls='')=>{const node=document.createElement(tag);node.textContent=cleanText(text);if(cls)node.className=cls;return node;};
const date=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
export const recordDate=seconds=>seconds==null?'未設定':typeof seconds==='number'&&Number.isFinite(seconds)&&seconds>0?date.format(new Date(seconds*1000))+' JST':String(seconds);
export function recordName(table,row){return cleanText(row.name||row.title||row.summary||row.description||row.message||`${tableLabel(table)} · No.${row.id??row._recordIndex??'—'}`).slice(0,180);}
export function primaryPeriod(row){for(const [start,end] of [['start_at','end_at'],['play_start_at','play_end_at'],['gacha_start_at','gacha_end_at']])if(row[start]!=null||row[end]!=null)return {start:row[start]??null,end:row[end]??null};return {start:null,end:null};}
export function recordImage(table,row,assets,store){
  if(table==='chars')return assets.characters?.[String(row.skin_id||row.id)];
  if(table==='stage_groups')return assets.quests?.[row.banner_file_name]||assets.bosses?.[String(row.boss_skin_id)]||assets.characters?.[String(row.boss_skin_id)];
  if(table==='stages'){const group=store.summary('stage_groups',row.stage_group_id);return group?recordImage('stage_groups',group,assets,store):null;}
  if(table==='items'){const charId=store.characterItemId(row.id),character=charId!==null?store.summary('chars',charId):null;return assets.items?.[row.image_name]||assets.items?.[String(row.id)]||(character?assets.characters?.[String(character.skin_id||character.id)]:null);}
  return assets.events?.[row.banner_file_name||row.file_name||row.banner_name||row.icon_name]||assets.quests?.[row.banner_file_name||row.file_name]||assets.gachas?.[row.banner_file_name||row.file_name]||assets.characters?.[String(row.char_id)]||null;
}
export function createRecordView({store,assets={},navigate}){
  const index=store.index;
  function picture(parent,table,row,cls='record-avatar'){const variants=table==='items'?assets.itemVariants?.[row.image_name]:assets.eventVariants?.[row.banner_file_name||row.file_name||row.banner_name||row.icon_name];if(variants?.length){const group=el('span','',cls+' record-image-variants');for(const [position,variant] of variants.entries()){const url=assetImageUrl(variant.path,assets);if(!url)continue;const image=el('img');image.src=url;image.alt=recordName(table,row)+' '+(position+1);image.loading='lazy';image.decoding='async';group.append(image);}parent.append(group);return;}const source=recordImage(table,row,assets,store);if(table==='chars'){const icon=characterImageElement(row,{assets,source,className:cls});if(icon)parent.append(icon);return;}if(table==='items'){const id=store.characterItemId(row.id),character=id!==null?store.summary('chars',id):null;if(character&&!assets.items?.[row.image_name]&&!assets.items?.[String(row.id)]){const icon=characterImageElement(character,{assets,source,className:cls});if(icon)parent.append(icon);return;}}const src=assetImageUrl(source,assets);if(!src)return;const image=el('img','',cls);image.src=src;image.alt=recordName(table,row);image.loading='lazy';image.decoding='async';parent.append(image);}
  function action(text,fn,cls='record-link'){const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;}
  async function reference(parent,target,id,field){
    const resolved=await store.resolve(target,id);if(!resolved){parent.append(el('span',`${fieldLabel(field)}：${id}（参照先未取得・未解決）`,'reference-missing'));return;}
    const button=action(recordName(resolved.table,resolved.row),()=>navigate(resolved.table,resolved.id));picture(button,resolved.table,resolved.row);button.append(el('small',resolved.table!==target?`報酬ID ${id} / モンスターID ${resolved.id} →`:`No.${id} →`));parent.append(button);
  }
  async function value(parent,table,key,v){
    if(v===null){parent.append(el('span','未設定（null）','data-empty'));return;}
    const target=store.target(table,key);
    if(typeof v==='number'&&v>0&&target){await reference(parent,target,v,key);return;}
    if(Array.isArray(v)){
      if(!v.length){parent.append(el('span','登録なし（0件）','data-empty'));return;}
      const list=el('div','','record-values');let offset=0;const more=action('さらに表示',append,'subtle');
      async function append(){const selected=v.slice(offset,offset+24);offset+=selected.length;more.hidden=offset>=v.length;for(const [i,item] of selected.entries()){const entry=el('div','','record-value');if(item&&typeof item==='object'){entry.append(el('small',`${offset-selected.length+i+1}`));entry.append(await fields(table,item));}else await value(entry,table,key.endsWith('_ids')?key.slice(0,-1):key,item);list.append(entry);}}
      await append();parent.append(list,more);return;
    }
    if(typeof v==='object'){parent.append(await fields(table,v));return;}
    if(typeof v==='boolean'){parent.append(el('span',v?'有効':'無効',`value-badge ${v?'enabled':''}`));return;}
    if(typeof v==='number'){parent.append(el('span',key.endsWith('_at')?recordDate(v):new Intl.NumberFormat('ja-JP',{maximumFractionDigits:12}).format(v),'record-number'));return;}
    if(/^https?:\/\//.test(v)){try{const url=new URL(v);const a=el('a',v,'external');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);return;}catch{}}
    parent.append(el('span',v===''?'空の文字列':v));
  }
  async function fields(table,row,keys=Object.keys(row)){
    const list=el('dl','','record-fields');
    for(const key of keys){const term=el('dt',fieldLabel(key)),definition=el('dd');term.title=key;await value(definition,table,key,row[key]);list.append(term,definition);}return list;
  }
  async function preview(table,row){
    const card=action('',()=>navigate(table,recordIdentity(index,table,row)),'record-preview');picture(card,table,row);const text=el('span','','record-preview-text');text.append(el('strong',recordName(table,row)));
    const referenceFields=['char_id','next_char_id','prev_char_id','item_id','stage_group_id','stage_id','stage_phase_id'];
    const references=await Promise.all(referenceFields.filter(key=>row[key]>0&&store.target(table,key)).map(async key=>{const target=store.target(table,key),resolved=await store.resolve(target,row[key]);return {key,target:resolved?.table||target,row:resolved?.row||null};}));
    const names=references.map(ref=>ref.row?`${fieldLabel(ref.key)}：${recordName(ref.target,ref.row)}`:`${fieldLabel(ref.key)}：${row[ref.key]}（未解決）`);
    if(!recordImage(table,row,assets,store)){const source=references.find(ref=>ref.row&&recordImage(ref.target,ref.row,assets,store));if(source)picture(card,source.target,source.row);}
    for(const name of names)text.append(el('small',name));
    if(row.cnt!==undefined)text.append(el('span',`個数 ${row.cnt}`,'reward-count'));
    const period=primaryPeriod(row);
    if(period.start>0&&period.end>0)text.append(el('small',`${recordDate(period.start)} 〜 ${recordDate(period.end)}`));
    else if(period.start>0)text.append(el('small',`開始 ${recordDate(period.start)}`));
    else if(period.end>0)text.append(el('small',`終了 ${recordDate(period.end)}`));
    if(row.assign_at>0)text.append(el('small',recordDate(row.assign_at)));
    for(const key of ['level','clear_count','required_luck','turn','first_attack_turn','cost','experience','order_id','enemy_max','x','y','param'])if(row[key]!=null)text.append(el('small',`${fieldLabel(key)} ${row[key]}`));
    if(!names.length&&(row.name||row.title||row.summary||row.description||row.message))text.append(el('small',`${tableLabel(table)} · No.${recordIdentity(index,table,row)}`));card.append(text,el('span','→','arrow'));return card;
  }
  async function recordList(parent,table,rows,heading=tableLabel(table)){
    const section=el('section','','record-section');section.append(el('h3',`${heading} · ${rows.length.toLocaleString('ja-JP')}件`));const list=el('div','','record-preview-list');let count=0;const more=action('続きを表示',append,'subtle');
    async function append(){const selected=rows.slice(count,count+12);count+=selected.length;more.hidden=count>=rows.length;list.append(...await Promise.all(selected.map(row=>preview(table,row))));}
    await append();section.append(list,more);parent.append(section);
  }
  async function layoutDiagram(parent,phase){
    const rows=await store.related('stage_phases',phase.id,'stage_phase_layouts');if(!rows.length)return;
    const points=rows.filter(r=>Number.isFinite(r.x)&&Number.isFinite(r.y));if(!points.length)return;
    const minX=Math.min(...points.map(r=>r.x)),maxX=Math.max(...points.map(r=>r.x)),minY=Math.min(...points.map(r=>r.y)),maxY=Math.max(...points.map(r=>r.y)),width=Math.max(100,maxX-minX),height=Math.max(100,maxY-minY),pad=Math.max(width,height)*.12;
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`${minX-pad} ${minY-pad} ${width+pad*2} ${height+pad*2}`);svg.setAttribute('class','battle-layout');svg.setAttribute('role','img');svg.setAttribute('aria-label',`バトル ${phase.id} の配信座標による配置図`);
    for(const [i,row] of points.entries()){const circle=document.createElementNS(svg.namespaceURI,'circle');circle.setAttribute('cx',row.x);circle.setAttribute('cy',row.y);circle.setAttribute('r',String(Math.max(width,height)*.026));circle.setAttribute('class','placement-dot');const title=document.createElementNS(svg.namespaceURI,'title');title.textContent=`配置${i+1} · 種別${row.type_id} · X ${row.x} / Y ${row.y} · パラメーター ${row.param}`;circle.append(title);svg.append(circle);const number=document.createElementNS(svg.namespaceURI,'text');number.setAttribute('x',row.x);number.setAttribute('y',row.y);number.setAttribute('font-size',String(Math.max(width,height)*.026));number.setAttribute('text-anchor','middle');number.setAttribute('dominant-baseline','central');number.textContent=String(i+1);svg.append(number);}
    parent.append(svg);await recordList(parent,'stage_phase_layouts',rows,'配置ごとの位置・設定');
  }
  async function timeline(parent,table,row){
    if(table!=='login_stamp_groups')return;
    const stamps=(await store.related(table,row.id,'login_stamps')).sort((a,b)=>a.order_id-b.order_id);if(!stamps.length)return;
    const section=el('section','','record-section');section.append(el('h3','ログイン日ごとの報酬'));
    for(const stamp of stamps){const day=el('article','','timeline-day');day.append(el('h4',`${stamp.order_id}日目${stamp.title?' · '+cleanText(stamp.title):''}`));if(stamp.assign_at)day.append(el('p',recordDate(stamp.assign_at),'internal-hint'));const rewards=await store.related('login_stamps',stamp.id,'login_stamp_items');for(const reward of rewards)day.append(await preview('login_stamp_items',reward));day.append(action('対象日の詳細',()=>navigate('login_stamps',stamp.id),'subtle'));section.append(day);}parent.append(section);
  }
  async function related(parent,table,row){
    const sets=index.relations?.[table]?.[String(row.id??recordIdentity(index,table,row))]||{};
    const prominent=new Set(['char_evolutions','char_mutations','stage_phases','stage_group_playing_conditions','stage_group_stage_required_items','stage_clear_bonus_items','apron_card_rewards','campaign_item_conditions','login_stamp_items','char_enemy_attacks']);
    for(const [target,ids] of Object.entries(sets)){
      const box=el('details','','record-relation');box.append(el('summary',`${tableLabel(target)} · ${new Set(ids).size.toLocaleString('ja-JP')}件`));let built=false;
      const load=async()=>{if(built)return;built=true;try{await recordList(box,target,await store.related(table,row.id??recordIdentity(index,table,row),target));}catch(error){box.append(el('p',error.message,'error'));}};
      box.addEventListener('toggle',()=>{if(box.open)load();});parent.append(box);if(prominent.has(target)){box.open=true;await load();}
    }
  }
  async function render(table,row,{profile=true,relations=true}={}){
    const body=el('div','','master-record');
    if(table==='chars'&&profile){const info=await loadCharacterInfo(row,store);body.append(renderCharacter(info,{assets,image:recordImage(table,row,assets,store),attributeImage:assets.attributes?.[String(row.attribute_id)]}));}
    else {const hero=el('div','','record-hero');picture(hero,table,row,index.tables[table]?.category==='events'?'record-hero-image record-event-banner':'record-hero-image');hero.append(el('h2',recordName(table,row)));body.append(hero);}
    for(const [key,v] of Object.entries(row))if(['description','message','summary','text','detail_text','gacha_rate_text','cannot_text'].includes(key)&&typeof v==='string'&&v)body.append(el('p',v,'readable-description'));
    const dates=Object.keys(row).filter(key=>key.endsWith('_at')&&typeof row[key]==='number'&&!['created_at','updated_at'].includes(key));if(dates.length){const period=el('div','','record-dates');for(const key of dates){const pair=el('div');pair.append(el('small',fieldLabel(key)),el('strong',recordDate(row[key])));period.append(pair);}body.append(period);}
    if(table==='stage_phases')await layoutDiagram(body,row);
    if(table==='connect_skills')for(const slot of [1,2,3]){const group=row['connect_skill_effect_group_id_'+slot];if(group>0)for(const target of ['connect_skill_effects','char_sort_abilities']){const matches=await store.matching(target,'group_id',group);if(matches.length)await recordList(body,target,matches,`コネクト効果 ${slot} · ${tableLabel(target)}`);}}
    if(table==='stages'){
      const phases=await store.related(table,row.id,'stage_phases');for(const [i,phase] of phases.entries()){const section=el('section','','battle-phase');section.append(el('h3',`バトル ${i+1} · No.${phase.id}`),el('p',`敵の上限 ${phase.enemy_max??'未設定'}`));await layoutDiagram(section,phase);section.append(action('バトルの全設定・関連情報',()=>navigate('stage_phases',phase.id),'subtle'));body.append(section);}
      if(row.clear_bonus_group_id>0)await recordList(body,'stage_clear_bonus_items',await store.matching('stage_clear_bonus_items','clear_bonus_group_id',row.clear_bonus_group_id),'クリア回数ごとの報酬');
      const rates=await store.related('stages',row.id,'stage_phase_enemy_char_group_rates'),enemies=new Set();for(const rate of rates)for(const entry of await store.matching('stage_phase_enemy_rate_char_groups','group_id',rate.group_id))if(entry.char_id)enemies.add(entry.char_id);const enemyRows=(await Promise.all([...enemies].map(id=>store.record('chars',id)))).filter(Boolean);if(enemyRows.length)await recordList(body,'chars',enemyRows,'敵差し替え定義で参照されるモンスター');
    }
    await timeline(body,table,row);
    const fieldsBox=el('section','','record-section');fieldsBox.append(el('h3',`登録された全項目 · ${Object.keys(row).filter(k=>k!=='_recordIndex').length}項目`),await fields(table,row));body.append(fieldsBox);
    if(relations)await related(body,table,row);
    return body;
  }
  return {render,preview,recordList,fields,picture};
}
