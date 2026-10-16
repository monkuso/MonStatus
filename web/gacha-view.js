import {cleanText} from './hubsdk.js';
import {gachaTables,gachaTableNames,gachaBrowseTables,fieldLabels,relatedGachaData} from './gachadetails.js';
const el=(tag,text,cls='')=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const label=key=>fieldLabels[key]||key.replaceAll('_',' ');
export function renderGachaRecords(parent,rows,{hub,detail,date,characterTiles},title='登録情報'){
  const shell=el('section',null,'gacha-records');shell.append(el('h3',`${title} · ${rows.length.toLocaleString('ja-JP')}件`));
  let offset=0;const list=el('div',null,'record-list'),more=el('button','さらに表示する','subtle');more.type='button';
  function value(parent,key,v){
    const target=key==='char_id'?'char':['gacha_group_id','parent_group_id','child_gacha_group_id','initialize_gacha_group_id','previous_step_gacha_group_id','required_gacha_group_id'].includes(key)?'gacha':null;
    const found=target==='char'?hub.library.indexes.chars.get(v):target==='gacha'?hub.library.indexes.gacha_groups.get(v):null;
    if(found){if(target==='char'){characterTiles(parent,[v],1);return;}const b=el('button',`${cleanText(found.name)} · No.${v} →`,'subtle');b.type='button';b.onclick=()=>detail(target,v);parent.append(b);return;}
    const item=['item_id','cost_item_id'].includes(key)?hub.library.indexes.items.get(v):null;
    if(item){parent.append(el('span',`${cleanText(item.name)} · No.${v}`));const texts=(hub.library.tables.item_texts||[]).filter(r=>r.item_id===v);for(const t of texts)parent.append(el('p',cleanText(t.text),'notes'));return;}
    if(v&&typeof v==='object'){if(Array.isArray(v)&&!v.length){parent.append(el('span','なし'));return;}const dl=el('dl',null,'record-fields');for(const [k,x] of Object.entries(v)){dl.append(el('dt',Array.isArray(v)?String(Number(k)+1):label(k)));const dd=el('dd');value(dd,k,x);dl.append(dd);}parent.append(dl);return;}
    const text=v==null?'未設定':(/_at$/.test(key)||['startAt','endAt'].includes(key))&&Number.isFinite(v)&&v>0?date(v):['observedAt'].includes(key)?date(Date.parse(v)/1000):typeof v==='boolean'?(v?'はい':'いいえ'):cleanText(v);
    parent.append(el('span',text||'空欄'));
  }
  function append(){for(const row of rows.slice(offset,offset+20)){const card=el('details',null,'record-card'),caption=row.name||row.title||row.description||titleFor(row),start=row.start_at??row.startAt;card.append(el('summary',cleanText(caption).slice(0,150)+(start?` · ${date(start)}`:'')));const dl=el('dl',null,'record-fields');for(const [key,v] of Object.entries(row)){dl.append(el('dt',label(key)));const dd=el('dd');value(dd,key,v);dl.append(dd);}card.append(dl);list.append(card);}offset+=20;more.hidden=offset>=rows.length;}
  function titleFor(row){const char=hub.library.indexes.chars.get(row.char_id),item=hub.library.indexes.items.get(row.item_id),group=hub.library.indexes.gacha_groups.get(row.gacha_group_id??row.gachaGroupId);return char?char.name:item?`${item.name} · 数量 ${row.cnt??row.cost_cnt??'—'}`:group?`${hub.gachaDisplayTitle(group.id)} · No.${group.id}${row.level!=null?` · 段階${row.level}`:''}`:row.gacha_group_event_id?`開催ID ${row.gacha_group_event_id} · No.${row.id}`:`No.${row.id??row.messageId??'—'}`;}
  more.onclick=append;append();shell.append(list,more);parent.append(shell);
}
export function renderGachaExtras(parent,id,context){
  const {hub,detail}=context,{sections,relations}=relatedGachaData(hub,id),group=hub.library.indexes.gacha_groups.get(id);
  const refs=[['親ガチャ','parent_group_id'],['前のステップ','previous_step_gacha_group_id'],['参加条件の参照ガチャ','required_gacha_group_id']];
  const facts=el('div',null,'facts');for(const [text,key] of [['必要ランク','request_rank'],['前ステップの必要回数','require_previous_step_cnt'],['ガチャポイント','gacha_point'],['特殊回数','gacha_special_cnt'],['参加条件コード（意味未確認）','enable_condition_id']])if(Object.hasOwn(group,key)){const f=el('div',text,'fact');f.append(el('strong',group[key]==null?'未設定':String(group[key])));facts.append(f);}parent.append(facts);
  for(const [text,key] of refs)if(group[key]){const r=hub.library.indexes.gacha_groups.get(group[key]),b=el('button',`${text}：${cleanText(r?.name||'名称未取得')} · No.${group[key]} →`,'quest-stage');b.type='button';b.onclick=()=>detail('gacha',group[key]);parent.append(b);}
  if(relations.length)renderGachaRecords(parent,relations,context,'子ガチャ・次のステップ・関連する参加条件');
  for(const section of sections){if(section.name==='box_gacha_items')parent.append(el('p','BOXの登録内容・登録数です。プレイヤー個別の現在の残数とは異なります。','notes'));renderGachaRecords(parent,section.rows,context,section.title);}
  renderGachaRecords(parent,[group],context,'全登録項目');
}
export function renderGachaArchive(parent,context,text='',selection={}){
  const tables=gachaBrowseTables(context.hub),select=el('select'),search=el('input'),output=el('div'),intro=el('p','取得済みのガチャ関連テーブルをすべて確認できます。開催IDが現在の一覧にない特殊イベントも保持しています。表示重み・登録数を提供割合として扱いません。','notice');
  select.setAttribute('aria-label','ガチャ関連情報の種類');search.type='search';search.placeholder='この種類の中で名前・ID・説明を検索';search.setAttribute('aria-label',search.placeholder);if(selection.outerText!==text){selection.text=text;selection.outerText=text;}search.value=selection.text||'';
  for(const name of [...gachaTableNames(tables),...(tables.item_texts?['item_texts']:[])]){const option=el('option',`${gachaTables[name]||name} · ${tables[name].length.toLocaleString('ja-JP')}件`);option.value=name;select.append(option);}
  if(selection.table&&Object.hasOwn(tables,selection.table))select.value=selection.table;
  function draw(){selection.table=select.value;selection.text=search.value;const needle=search.value.normalize('NFKC').toLowerCase();const rows=tables[select.value].filter(r=>!needle||JSON.stringify(r).normalize('NFKC').toLowerCase().includes(needle));output.replaceChildren();const evidence=context.hub.data.verification?.find(v=>v.table===select.value);if(evidence?.status==='not-distributed')output.append(el('p','サーバーの一覧にはありますが、サイズ0・配信URLなしのためデータが配信されていません。','notice'));renderGachaRecords(output,rows,context,gachaTables[select.value]||select.value);}
  select.onchange=draw;search.oninput=draw;parent.append(intro,select,search,output);draw();
}
