import {cleanText} from './hubsdk.js';
import {occurrenceTime} from './gachadetails.js';
import {renderGachaExtras,renderGachaRecords} from './gacha-view.js';
export function renderGachaDetail(parent,id,occurrence,ui){
  const {hub,view,detail,title,appendPicture,facts,heading,paragraph,button,element,characterTiles,appendCharacter,external,gachaDate,gachaPeriod}=ui;
  const info=hub.library.gacha(id);if(!info)return;
  const {row}=info,event=occurrence||hub.gachaSchedule(id,view),now=Date.now()/1000,at=occurrenceTime(event,now),historical=Boolean(event?.retainedForHistory)||event?.end_at<now;
  title(parent,event?.header_title||event?.name||hub.gachaDisplayTitle(id,view),'ガチャ',id);appendPicture(parent,hub.gachaImage(row,at),cleanText(row.name),'detail-banner');paragraph(parent,row.description,'notes');
  const item=hub.library.indexes.items.get(row.cost_item_id);facts(parent,[['必要アイテム',item?.name||`ID ${row.cost_item_id}`],['必要数',row.cost_cnt],['形式',row.name],['必要ランク',row.request_rank]]);
  if(event){paragraph(parent,`選択中 ${gachaPeriod(event.start_at,event.end_at)}`,'lead');if(event.retainedForHistory)paragraph(parent,'過去に観測した記録です。現在の開催一覧には含まれていません。','notice');}
  else paragraph(parent,'開催日未確認の定義です。過去の形式・ステップ・未使用の情報も含みます。','notice');
  if(info.schedules.length){heading(parent,'すべての開催期間');for(const e of [...info.schedules].sort((a,b)=>b.start_at-a.start_at))parent.append(button(`${gachaPeriod(e.start_at,e.end_at)}${e.retainedForHistory?' · 過去の観測記録':''} →`,()=>detail('gacha',id,true,e),'quest-stage'));}
  heading(parent,'提供割合');const rates=hub.providedRates(id,at,historical);
  if(!rates.length)paragraph(parent,hub.gachaMessages(id,at,historical).length?'この期間の案内は取得済みですが、提供割合の数値は配信されていません。':'この開催期間に対応する提供割合の案内は未取得です。','notice');
  function showRate(target,rate){
    if(rate.title)paragraph(target,rate.title,'lead');paragraph(target,`適用期間 ${gachaPeriod(rate.startAt,rate.endAt)}${rate.retainedForHistory?' · 過去の観測記録':''}`,'notes');
    const table=element('table',null,'data-table'),head=element('tr');head.append(element('th','対象'),element('th','提供割合'));table.append(head);
    for(const entry of rate.entries||[]){const tr=element('tr'),name=element('td'),char=hub.library.indexes.chars.get(entry.charId);if(char)appendCharacter(name,char);name.append(element('span',char?cleanText(char.name):cleanText(entry.name)));tr.append(name,element('td',String(entry.rate),'rate'));table.append(tr);}target.append(table);
    if(rate.notes)paragraph(target,rate.notes,'notes');if(rate.observedAt)paragraph(target,`実サーバーで確認 ${gachaDate(Date.parse(rate.observedAt)/1000)}`,'lead');external(target,rate.sourceUrl,'公式の提供割合を見る ↗');
  }
  for(const rate of rates)showRate(parent,rate);
  // The native client inherits from parents except category 50008.
  const chainIds=new Set([id]);let g=row;
  while(g.category_id!==50008&&g.parent_group_id&&!chainIds.has(g.parent_group_id)){chainIds.add(g.parent_group_id);g=hub.library.indexes.gacha_groups.get(g.parent_group_id);if(!g)break;}
  const archive=(hub.data.gachaRates||[]).filter(r=>chainIds.has(r.gachaGroupId)&&r.entries?.length&&!rates.includes(r)).sort((a,b)=>b.startAt-a.startAt);
  if(archive.length){const box=element('details',null,'notes');box.append(element('summary',`別期間・過去に取得した提供割合 ${archive.length}件`));let built=false;box.addEventListener('toggle',()=>{if(box.open&&!built){built=true;for(const r of archive)showRate(box,r);}});parent.append(box);}
  const messages=hub.gachaMessages(id,at,historical);
  for(const m of messages)if(m.detailText){const box=element('details',null,'notes');box.append(element('summary',`ゲーム内の対象・特典・注意事項 · No.${m.messageId}`));paragraph(box,m.detailText,'notes');parent.append(box);}
  const featured=hub.gachaFeaturedIds(id,at);if(featured.length){heading(parent,'登録ピックアップ');characterTiles(parent,featured);}
  const chars=hub.gachaCharacterIds(id,at).filter(cid=>!featured.includes(cid));if(chars.length){heading(parent,'登録・案内に登場するモンスター');paragraph(parent,'マスターの登録・ピックアップ・案内中の参照を表示します。完全な排出対象や提供割合を示すものではありません。','notes');characterTiles(parent,chars,120);}
  heading(parent,'参加条件・ステップ・アイテム・特殊情報');const context={hub,detail,date:gachaDate,characterTiles};renderGachaExtras(parent,id,context);
  if(info.schedules.length)renderGachaRecords(parent,info.schedules,context,'開催の全登録項目');
  const banners=hub.gachaBanners.filter(b=>chainIds.has(b.gacha_group_id));if(banners.length)renderGachaRecords(parent,banners,context,'配信バナーの全登録項目');
  const allMessages=(hub.data.gachaMessages||[]).filter(m=>chainIds.has(m.gachaGroupId));
  if(allMessages.length)renderGachaRecords(parent,allMessages,context,'取得済みの案内・確認履歴');
}
