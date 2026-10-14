import {loadLibrary} from './librarysdk.js';
import {displayName,attributeMeta} from './sdk.js';
const $=id=>document.getElementById(id);
const date=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
let library=null,kind='stage',limit=48,groupId=new URLSearchParams(location.search).get('group');
let assets=null;
function node(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function name(value){return displayName(String(value||'')).replace(/\[LF\]/g,'\n').replace(/\[GIMMICK:([^\]]+)\]/g,'$1').replace(/\[(?:LC|RC|WIDTH\d+|GIMMICK_END)\]/g,'').replace(/\[IMG:[^\]]*\]/g,'').trim();}
function time(value){return Number.isFinite(value)&&value>0?date.format(new Date(value*1000))+' JST':'日程未設定';}
function section(title){const e=node('section','detail-section');e.append(node('h2','',title));return e;}
function metrics(entries){const list=node('dl','detail-metrics');for(const [label,value] of entries){if(value===undefined||value===null)continue;const e=node('div');e.append(node('dt','',label),node('dd','',String(value)));list.append(e);}return list;}
function link(kind,id){location.hash=`${kind}:${id}`;}
function characters(ids){const list=node('div','character-links');for(const id of ids){const char=library.indexes.chars.get(Number(id));if(!char)continue;const button=node('button','');const image=assets.characters?.[String(char.skin_id||char.id)];if(typeof image==='string'&&/^assets\/characters\/\d{2}\/\d+\.webp$/.test(image)){const img=node('img','clear-monster-image');img.src=image;img.alt=name(char.name);img.loading='lazy';img.decoding='async';button.append(img);}button.append(node('span','',`${name(char.name)}\n★${char.rarity} · ${attributeMeta(char.attribute_id)?.label||'属性未設定'}`));button.type='button';button.addEventListener('click',()=>link('char',char.id));list.append(button);}return list;}
function schedules(rows){const list=node('ul','schedule-list');for(const row of rows){const start=row.start_at??row.startAt,end=row.end_at??row.endAt;list.append(node('li','',`${name(row.name)}\n${time(start)} 〜 ${time(end)}`));}return list;}
function head(title,description){const e=node('div','detail-head');e.append(node('span','eyebrow','GAME DATA / DETAILS'),node('h1','',name(title)));if(description)e.append(node('p','',name(description)));return e;}
function showStage(id){
  const detail=library.stage(id);if(!detail)return null;
  const {row,group}=detail;const fragment=document.createDocumentFragment();fragment.append(head(group?.name||row.name,row.name));
  const info=section('ステージ情報');info.append(metrics([['ステージID',row.id],['属性',attributeMeta(row.attribute_id)?.label||'未設定'],['消費コスト',row.cost],['獲得経験値',row.experience],['バトル数',detail.phases.length||'未取得'],['スピードクリアのターン',row.bonus_turn],['必要ランク',group?.required_rank]]));fragment.append(info);
  const gimmicks=section('ギミック・クエストの注意点');const chips=node('div','detail-chips');
  for(const g of detail.gimmicks){const chip=node('span',`detail-chip ${g.status==='featured'?'featured':''}`,g.label?`${g.label}${g.status==='featured'?' · 重要':''}`:'名称確認中');chip.title=g.label||'配信されたギミック種別の名称を確認中です';chips.append(chip);}
  if(chips.childElementCount)gimmicks.append(chips);else gimmicks.append(node('p','muted',detail.gimmickDataAvailable?'配信されたギミック指定はありません。':'このステージのギミック情報は未取得です。'));
  for(const note of detail.notes)gimmicks.append(node('p','',name(note.message)));
  for(const g of detail.gimmicks){if(!g.description)continue;const help=node('details');help.append(node('summary','muted',`${g.label}について`),node('p','',name(g.description)));gimmicks.append(help);}
  fragment.append(gimmicks);
  if(detail.schedules.length){const calendar=section('イベント開催期間');calendar.append(schedules(detail.schedules));fragment.append(calendar);}
  const community=section('みんなのクリアモンスター');
  if(detail.community){for(const [title,key] of [['プレミアムガチャ','gacha_char_ids'],['その他のモンスター','event_char_ids']]){community.append(node('h3','',title),characters((detail.community[key]||[]).filter(id=>id>0)));}community.append(node('p','muted','ゲームの集計結果に含まれる並び順です。未配信の使用率を補っていません。'));}
  else community.append(node('p','availability',detail.clearCheck?.status==='not-published'?'このステージのクリアモンスター集計はゲーム側で配信されていません。':detail.clearCheck?.status==='error'?'このステージの集計取得に失敗しました。次の同期で再取得します。':'このステージのクリア実績はまだ取得されていません。'));
  fragment.append(community);
  const drops=[row.clear_bonus_char_id].filter(id=>id>0&&library.indexes.chars.has(id));if(drops.length){const rewards=section('クリアボーナスのモンスター');rewards.append(characters(drops));fragment.append(rewards);}
  return fragment;
}
function showGacha(id){
  const detail=library.gacha(id);if(!detail)return null;const {row}=detail;const fragment=document.createDocumentFragment();fragment.append(head(row.name,row.description));
  const item=library.indexes.items.get(row.cost_item_id);const info=section('ガチャ情報');info.append(metrics([['ガチャID',row.id],['必要アイテム',item?.name||`アイテム ${row.cost_item_id}`],['消費数',row.cost_cnt],['排出数',row.output_cnt],['レアリティ範囲',`★${row.rarity_min} 〜 ★${row.rarity_max}`],['必要ランク',row.request_rank],['回数条件（配信値）',row.enable_count]]));
  for(const extra of detail.extraCosts){const extraItem=library.indexes.items.get(extra.item_id);info.append(node('p','',`追加コスト：${name(extraItem?.name)||`アイテム ${extra.item_id}`} × ${extra.cost_cnt}`));}
  fragment.append(info);
  const calendar=section('開催期間');calendar.append(detail.schedules.length?schedules(detail.schedules):node('p','availability','開催日程は未取得です。登録されているガチャの情報を表示しています。'));fragment.append(calendar);
  const odds=section('提供割合・注意事項');odds.append(node('p','','キャラクターの数から提供確率を計算していません。個別の提供割合はゲームの案内をご確認ください。'));
  if(row.popup_url){try{const url=new URL(row.popup_url);if(url.protocol==='https:'||url.protocol==='http:'){const a=node('a','detail-chip','ゲーム配信の詳細・提供割合ページ ↗');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';odds.append(a);}}catch{}}
  for(const key of ['header_title','footer_title','button_footer_text'])if(row[key])odds.append(node('p','',name(row[key])));fragment.append(odds);
  if(detail.features.length){const features=section('注目・ピックアップ表示のモンスター');for(const f of detail.features){features.append(characters([f.char_id]),node('p','muted',`${time(f.start_at)} 〜 ${time(f.end_at)}`));}fragment.append(features);}
  const lineup=section(`提供キャラクターの登録情報 · ${detail.characters.length.toLocaleString()}体`);lineup.append(detail.characters.length?characters(detail.characters.map(c=>c.id)):node('p','availability','このガチャの提供キャラクター一覧は未配信です。'));if(detail.unresolvedCharacterIds.length)lineup.append(node('p','muted',`${detail.unresolvedCharacterIds.length}体のキャラクター情報が未取得です。`));fragment.append(lineup);
  return fragment;
}
function showCharacter(id){
  const detail=library.character(id);if(!detail)return null;const {row}=detail;const fragment=document.createDocumentFragment();fragment.append(head(row.name));const info=section('モンスター情報');info.append(metrics([['モンスターID',row.id],['レアリティ',`★${row.rarity}`],['属性',attributeMeta(row.attribute_id)?.label||'未設定'],['最大レベル',row.level_max],['最大HP',row.hp_max],['最大攻撃力',row.attack_max],['最大スピード（配信値）',row.power_max]]));fragment.append(info);
  const skills=section('友情コンボ・スキルの配信情報');for(const skill of detail.skills){skills.append(node('h3','',name(skill.name)),node('p','',name(skill.description)));}if(!detail.skills.length)skills.append(node('p','muted','スキル情報は未配信です。'));fragment.append(skills);
  if(detail.strikeShot){const ss=section('ストライクショット');ss.append(node('h3','',name(detail.strikeShot.name)),node('p','',name(detail.strikeShot.description)),metrics([['必要ターン',detail.strikeShot.require_cnt]]));fragment.append(ss);}return fragment;
}
function renderList(){
  if(!library)return;const result=library.search(kind,{text:$('library-search').value,attribute:kind==='gacha'?'':$('library-attribute').value,groupId,limit});
  const rows=result.rows.map(row=>{const card=node('button','library-card');card.type='button';card.append(node('span','card-id',`${kind==='stage'?'STAGE':kind==='gacha'?'GACHA':'MONSTER'} / ${row.id}`));const group=kind==='stage'?library.indexes.stage_groups.get(row.stage_group_id):null;card.append(node('h2','',name(group?.name||row.name)));if(group)card.append(node('p','',name(row.name)));if(kind==='gacha')card.append(node('p','',`${row.output_cnt??'—'}体排出 · 提供情報を見る`));else card.append(node('p','',`${attributeMeta(row.attribute_id)?.label||'属性未設定'}${kind==='char'?` · ★${row.rarity}`:` · コスト ${row.cost}`}`));card.addEventListener('click',()=>link(kind,row.id));return card;});
  $('library-grid').replaceChildren(...rows);$('library-count').textContent=`${result.total.toLocaleString()}件 · ${Math.min(limit,result.total)}件表示`;$('library-more').hidden=result.total<=limit;$('library-attribute').disabled=kind==='gacha';$('library-note').textContent=kind==='gacha'?'過去・条件付きの登録ガチャも含みます。開催日程・提供割合の取得状態は詳細で確認できます。':kind==='stage'?'すべての登録ステージを検索できます。参加条件やクリア実績の取得状態は詳細で確認できます。':'敵キャラクターなどを含む配信マスターの登録情報です。';
}
function renderRoute(){
  if(!library)return;const match=location.hash.match(/^#(stage|gacha|char):(\d+)$/);
  if(!match){$('catalog-list').hidden=false;$('catalog-detail').hidden=true;renderList();return;}
  const result={stage:showStage,gacha:showGacha,char:showCharacter}[match[1]](Number(match[2]));
  if(!result){$('library-error').hidden=false;$('library-error').textContent='指定された登録情報が見つかりません。';return;}
  $('library-error').hidden=true;$('catalog-list').hidden=true;$('catalog-detail').hidden=false;$('detail-content').replaceChildren(result);$('catalog-detail').scrollIntoView({block:'start'});
}
for(const button of document.querySelectorAll('[data-kind]'))button.addEventListener('click',()=>{kind=button.dataset.kind;limit=48;groupId=null;location.hash='';for(const tab of document.querySelectorAll('[data-kind]')){const active=tab===button;tab.classList.toggle('selected',active);tab.setAttribute('aria-pressed',String(active));}renderRoute();});
$('library-search').addEventListener('input',()=>{limit=48;renderList();});$('library-attribute').addEventListener('change',()=>{limit=48;renderList();});$('library-more').addEventListener('click',()=>{limit+=48;renderList();});$('library-back').addEventListener('click',()=>{location.hash='';});window.addEventListener('hashchange',renderRoute);
try{const response=await fetch('./data/assets.json',{cache:'no-cache'});if(!response.ok)throw new Error('モンスター画像の一覧を取得できていません。');assets=await response.json();library=await loadLibrary();for(const [name,table] of [['stage','stages'],['gacha','gacha_groups'],['char','chars']])$(name+'-total').textContent=library.tables[table].length.toLocaleString();$('library-updated').hidden=true;renderRoute();}catch(error){$('library-error').hidden=false;$('library-error').textContent=error.message;$('library-updated').textContent='図鑑データを取得できていません';}
