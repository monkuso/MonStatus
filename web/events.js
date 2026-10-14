import {loadEvents,queryEvents,eventStatus,isLongTerm,displayName,jstDay,decodeGimmicks,hasAnyGimmick,attributeMeta,lookupChars,RARITY_SYMBOLS} from './sdk.js';
const $=id=>document.getElementById(id);
const dateFormat=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false});
const fullDate=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const format=seconds=>dateFormat.format(new Date(seconds*1000));
let snapshot=null,view='active',limit=24,refreshing=false;
function element(tag,className,text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;}
function gimmickRow(event){
  if(!hasAnyGimmick(event))return null;
  const row=element('div','gimmick-row');
  row.setAttribute('role','list');
  row.setAttribute('aria-label','ステージギミック');
  for(const slot of decodeGimmicks(event.gimmickFlag,event.highlightGimmickFlag)){
    const chip=element('span',`gimmick-icon gimmick-${slot.status}`,String(slot.index+1));
    chip.setAttribute('role','listitem');
    chip.setAttribute('aria-label',`${slot.label} ${slot.status==='featured'?'(重要)':slot.status==='present'?'(あり)':'(なし)'}`);
    chip.title=`${slot.label} · ${slot.status==='featured'?'重要':slot.status==='present'?'あり':'なし'}`;
    chip.dataset.slot=String(slot.index);
    row.append(chip);
  }
  return row;
}
function charTile(profile){
  const meta=attributeMeta(profile.attributeId);
  const tile=element('span','char-tile');
  if(meta){tile.classList.add(`char-${meta.key}`);tile.style.setProperty('--char-color',meta.color);}
  const badge=element('span','char-attr',meta?meta.symbol:'？');
  const label=element('span','char-name',profile.name);
  const rarity=element('span','char-rarity',RARITY_SYMBOLS[profile.rarity] || '');
  tile.append(badge,label,rarity);
  tile.title=`${profile.name} · ${meta?meta.label:'属性不明'}${profile.rarity?' · '+RARITY_SYMBOLS[profile.rarity]:''}`;
  return tile;
}
function charRow(label,profiles,note){
  if(!profiles.length)return null;
  const row=element('section','char-row');
  const header=element('div','char-row-header');
  header.append(element('span','char-row-label',label));
  if(note)header.append(element('span','char-row-note',note));
  row.append(header);
  const list=element('div','char-list');list.setAttribute('role','list');
  for(const p of profiles){const tile=charTile(p);tile.setAttribute('role','listitem');list.append(tile);}
  row.append(list);
  return row;
}
function card(event){
  const status=eventStatus(event),labels={active:'開催中',upcoming:'開催予定',ended:'終了',unknown:'日程未設定'};
  const article=element('article','event-card');
  const top=element('div','card-top');top.append(element('span',`badge ${status}`,labels[status]));
  const body=element('div','card-content');body.append(element('h3','',displayName(event.name)));if(event.questName && event.questName!==event.name)body.append(element('p','quest',displayName(event.questName)));
  const stageAttr=attributeMeta(event.attributeId);
  if(stageAttr){const chip=element('span',`stage-attr char-${stageAttr.key}`,`ステージ属性 ${stageAttr.label}`);chip.style.setProperty('--char-color',stageAttr.color);body.append(chip);}
  const times=element('div','card-date');for(const [label,time] of [['開始',event.startAt],['終了',event.endAt]]){const row=element('div');row.append(element('span','',label));const stamp=element('time','',format(time));stamp.dateTime=new Date(time*1000).toISOString();stamp.title=fullDate.format(new Date(time*1000));row.append(stamp);times.append(row);}body.append(times);
  const gim=gimmickRow(event);if(gim)body.append(gim);
  const recommended=lookupChars(snapshot,event.recommendedCharIds);
  const recRow=charRow('属性相性の候補',recommended,'クリア実績とは別の候補です');
  if(recRow)body.append(recRow);
  if(event.stageGroupId){const detail=element('a','event-detail-link','ステージ詳細・ギミックを見る ↗');detail.href=`./library.html?group=${event.stageGroupId}`;body.append(detail);}
  const foot=element('div','card-foot');foot.append(element('span','',event.sourceTable==='stage_group_events'?'イベント日程':'条件付き日程'));
  let remaining=labels[status];if(isLongTerm(event))remaining='長期開催';else if(status==='active'){const hours=Math.ceil((event.endAt-Date.now()/1000)/3600);remaining=hours<=24?`終了まで約${Math.max(1,hours)}時間`:`終了まで約${Math.ceil(hours/24)}日`;}else if(status==='upcoming'){const hours=Math.ceil((event.startAt-Date.now()/1000)/3600);remaining=hours<=24?`開始まで約${Math.max(1,hours)}時間`:`開始まで約${Math.ceil(hours/24)}日`;}foot.append(element('span','remaining',remaining));article.append(top,body,foot);return article;
}
function render(){
  if(!snapshot)return;
  const settings={view,text:$('search').value,includeLongTerm:$('permanent').checked,includeConditional:$('conditional').checked,sort:$('sort').value,day:$('date').value || null};
  const results=queryEvents(snapshot.events,settings);
  $('grid').replaceChildren(...results.slice(0,limit).map(card));$('result-count').textContent=`${results.length.toLocaleString()}件`; $('message').hidden=results.length>0;$('message').textContent='条件に一致するイベントはありません。検索や表示条件を変更してください。';$('more').hidden=results.length<=limit;
  const base={includeLongTerm:settings.includeLongTerm,includeConditional:settings.includeConditional};$('active-count').textContent=queryEvents(snapshot.events,{...base,view:'active'}).length.toLocaleString();$('upcoming-count').textContent=queryEvents(snapshot.events,{...base,view:'upcoming'}).length.toLocaleString();
  const next=queryEvents(snapshot.events,{view:'upcoming',sort:'starting'})[0];$('next-name').textContent=next?displayName(next.name):'新しい予定を待っています';$('next-time').textContent=next?`${format(next.startAt)} 開始`:'新しいデータで予定をチェック';
  $('date-hint').textContent=$('date').value?`${$('date').value.replaceAll('-','/')} に開催期間が重なるイベント`:'いまの開催状況で表示しています';
}
async function refresh({background=false}={}){
  if(refreshing)return;refreshing=true;
  try{snapshot=await loadEvents();if(!background)limit=24;render();$('load-error').hidden=true;}
  catch{if(snapshot)render();else $('message').hidden=true;$('load-error').hidden=false;$('load-error').textContent=snapshot?'最新データの読み込みに失敗しました。前回の取得データを表示しています。':'データを読み込めませんでした。時間をおいて「更新」をお試しください。';}
  finally{refreshing=false;}
}
function selectView(next){view=next;limit=24;for(const tab of document.querySelectorAll('[data-view]')){const selected=tab.dataset.view===view;tab.classList.toggle('selected',selected);tab.setAttribute('aria-pressed',String(selected));}}
for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>{$('date').value='';selectView(button.dataset.view);render();});
for(const id of ['search','sort','permanent','conditional'])$(id).addEventListener(id==='search'?'input':'change',()=>{limit=24;render();});
$('date').addEventListener('change',()=>{selectView($('date').value?'all':'active');render();});
for(const button of document.querySelectorAll('[data-day]'))button.addEventListener('click',()=>{$('date').value=jstDay(Date.now(),Number(button.dataset.day));selectView('all');render();});
$('clear-date').addEventListener('click',()=>{$('date').value='';selectView('active');render();});$('more').addEventListener('click',()=>{limit+=24;render();});
document.addEventListener('keydown',event=>{if(event.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();$('search').focus();}});
setInterval(()=>{if(snapshot)render();},60000);
setInterval(()=>{if(!document.hidden)refresh({background:true});},300000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh({background:true});});
refresh();
