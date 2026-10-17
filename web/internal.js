import {queryInternal,recordIdentity} from './internalsdk.js';
import {cleanText} from './hubsdk.js?v=gacha5';
import {createMasterStore} from './masterdata.js';
import {createRecordView,primaryPeriod} from './record-view.js?v=icons2';
import {categoryNames,tableLabel,fieldLabel} from './data-labels.js';
const $=id=>document.getElementById(id);
const titles={chars:'キャラクター',stage_groups:'クエスト',stages:'ステージ',events:'イベント',items:'アイテム',assets:'画像候補',tables:'すべてのゲームデータ'};
const state={index:null,store:null,view:null,assets:{},events:[],orphans:[],kind:'chars',filter:'all',text:'',category:'',table:'',chunk:0,limit:36,tableRows:[],tableSearch:false};
let detailRequest=0,tableRequest=0,searchTimer;
const el=(tag,text='',cls='')=>{const node=document.createElement(tag);node.textContent=cleanText(text);if(cls)node.className=cls;return node;};
const button=(text,fn,cls='subtle')=>{const node=el('button',text,cls);node.type='button';node.onclick=fn;return node;};
const error=message=>{$('internal-error').hidden=!message;$('internal-error').textContent=message||'';};
async function json(url){const response=await fetch(url,{cache:'no-cache'});if(!response.ok)throw new Error('データ取得エラー ('+response.status+')');return response.json();}
function updateUrl(){const p=new URLSearchParams({kind:state.kind});if(state.table&&state.kind==='tables')p.set('table',state.table);if(state.category)p.set('category',state.category);history.replaceState(null,'','?'+p);}
async function showRecord(table,id){
  const token=++detailRequest,dialog=$('internal-detail'),body=$('internal-detail-body');body.replaceChildren(el('h2','読み込み中…'));if(!dialog.open)dialog.showModal();
  try{const row=await state.store.record(table,id);if(!row)throw new Error('このレコードは配信データ内で確認できません。');const content=await state.view.render(table,row);if(token!==detailRequest)return;const h2=content.querySelector('h2');if(h2)h2.id='internal-detail-title';body.replaceChildren(content);dialog.querySelector('.dialog-top span').textContent=tableLabel(table);dialog.scrollTop=0;const a=el('a','この情報へのリンク ↗','external');a.href='?kind=tables&table='+encodeURIComponent(table)+'&id='+id;body.append(a);}
  catch(exception){if(token===detailRequest)body.replaceChildren(el('p',exception.message,'error'));}
}
function showAsset(row){++detailRequest;const body=$('internal-detail-body');body.replaceChildren(el('h2',row.name));const image=el('img','','internal-detail-image');image.src=row.image;image.alt=row.name;body.append(image);if(!$('internal-detail').open)$('internal-detail').showModal();}
function option(value,text){const node=el('option',text);node.value=value;return node;}
function refreshFilters(){
  const selector=$('internal-filter'),old=state.filter;
  selector.replaceChildren(...(state.kind==='events'?[['all','すべての期間'],['active','開催中'],['upcoming','開催予定'],['ended','終了したイベント']]:[['all','すべての登録情報'],['candidate','マスク・未来・テスト'],['future','公開時刻が未来'],['info-mask','情報マスク条件'],['test','テスト設定あり'],['unlisted','出現一覧に参照なし'],['special-range','特殊ID範囲']]).map(([v,t])=>option(v,t)));
  selector.value=[...selector.options].some(o=>o.value===old)?old:'all';state.filter=selector.value;
  selector.hidden=!['chars','stage_groups','stages','events'].includes(state.kind);
}
function chooseTable(name){state.kind='tables';state.table=name;state.chunk=0;state.limit=36;state.text='';$('internal-search').value='';$('internal-table').value=name;refreshFilters();updateUrl();loadTable();}
function tableCard(name,meta){
  const card=button('',()=>chooseTable(name),'card internal-card table-card'),body=el('div','','card-body');
  body.append(el('span',categoryNames[meta.category]||'ゲームデータ','eyebrow'),el('h3',tableLabel(name)),el('span',name,'internal-evidence'));
  const status=meta.status==='error'?'取得エラー':meta.status==='not-distributed'?'サーバー未配信':(meta.rows??0).toLocaleString('ja-JP')+'件';
  body.append(el('strong',status,'table-count'),el('span',(meta.fields?.length??0)+'項目','internal-evidence'));
  if(meta.fields?.length)body.append(el('p',meta.fields.slice(0,8).map(fieldLabel).join('・'),'table-field-preview'));
  body.append(el('span','情報を見る →','arrow'));card.append(body);return card;
}
function collectionEntries(){
  const now=Date.now()/1000;
  return (state.index.collections?.[state.kind]||[]).filter(row=>{const period=primaryPeriod(row);return state.kind!=='events'||state.filter==='all'||(state.filter==='active'?period.start!==null&&period.end!==null&&period.start<=now&&period.end>=now:state.filter==='upcoming'?period.start>now:period.end>0&&period.end<now);}).sort((a,b)=>(primaryPeriod(b).start||b.updated_at||0)-(primaryPeriod(a).start||a.updated_at||0));
}
async function render(){
  if(!state.index)return;const token=++tableRequest,kind=state.kind,grid=$('internal-grid');grid.setAttribute('aria-busy','true');
  $('internal-title').textContent=kind==='tables'&&state.table?tableLabel(state.table):titles[kind];
  document.querySelectorAll('[data-kind]').forEach(node=>node.setAttribute('aria-pressed',String(node.dataset.kind===kind)));
  $('internal-category').hidden=kind!=='tables';$('internal-table').hidden=kind!=='tables';$('internal-chunk').hidden=kind!=='tables'||!state.table||state.tableSearch;
  const term=state.text.normalize('NFKC').toLowerCase();let cards,total;
  if(kind==='tables'&&!state.table){
    const rows=Object.entries(state.index.tables).filter(([name,meta])=>(!state.category||meta.category===state.category)&&(!term||(name+' '+tableLabel(name)+' '+(meta.fields||[]).map(fieldLabel).join(' ')).normalize('NFKC').toLowerCase().includes(term)));
    total=rows.length;cards=rows.slice(0,state.limit).map(([name,meta])=>tableCard(name,meta));
  }else if(kind==='assets'){
    const rows=state.orphans.filter(row=>!term||JSON.stringify(row).normalize('NFKC').toLowerCase().includes(term));total=rows.length;cards=rows.slice(0,state.limit).map(row=>{const b=button(row.name||row.resourceNameCandidate||'画像候補',()=>showAsset(row),'card internal-card');if(/^assets\/internal\/\d+\.webp$/.test(row.image)){const image=el('img','','internal-image');image.src=row.image;image.alt=row.name||'画像候補';b.prepend(image);}return b;});
  }else{
    let rows;
    if(kind==='tables')rows=state.tableRows.map(row=>({table:state.table,row}));
    else if(['events','items'].includes(kind))rows=collectionEntries().map(row=>({table:row.table,row}));
    else rows=queryInternal(state.index.entities[kind]||[],{kind,filter:state.filter,text:state.text,events:state.events,groups:state.index.entities.stage_groups||[]}).map(entry=>({table:kind,...entry}));
    rows=rows.filter(entry=>!term||(JSON.stringify(entry.row)+' '+tableLabel(entry.table)).normalize('NFKC').toLowerCase().includes(term));
    total=rows.length;cards=await Promise.all(rows.slice(0,state.limit).map(async entry=>{const card=await state.view.preview(entry.table,entry.row);card.classList.add('catalog-record');for(const reason of entry.reasons||[])card.append(el('span',reason.label,'tag'));return card;}));
  }
  if(token!==tableRequest)return;
  grid.className=kind==='tables'&&!state.table?'grid table-grid':['chars','stage_groups','stages','events','items'].includes(kind)?'record-catalog-grid':'grid table-record-grid';
  grid.replaceChildren(...cards);if(!total)grid.append(el('p','条件に一致する情報はありません。','internal-empty'));grid.setAttribute('aria-busy','false');$('internal-count').textContent=total.toLocaleString('ja-JP')+'件 · '+Math.min(total,state.limit)+'件表示';$('internal-more').hidden=total<=state.limit;
}
async function loadTable(){
  if(!state.table){state.tableRows=[];state.tableSearch=false;render();return;}
  const table=state.table,request=++tableRequest;error('');
  try{
    const meta=state.index.tables[table];$('internal-chunk').replaceChildren(...meta.chunks.map((part,i)=>option(String(i),(meta.identityField==='_recordIndex'?'レコード ':'ID ')+part.firstId+' 〜 '+part.lastId)));$('internal-chunk').value=String(state.chunk);
    state.tableSearch=Boolean(state.text);$('internal-count').textContent=state.tableSearch?'テーブル全体を検索しています…':'読み込み中…';
    const rows=state.tableSearch?await state.store.all(table):meta.chunks.length?await state.store.chunk(table,meta.chunks[state.chunk]):[];
    if(request!==tableRequest)return;state.tableRows=rows;await render();
  }catch(exception){if(request===tableRequest)error(exception.message);}
}
document.querySelectorAll('[data-kind]').forEach(node=>node.onclick=()=>{state.kind=node.dataset.kind;state.limit=36;state.filter='all';state.text='';$('internal-search').value='';refreshFilters();updateUrl();if(state.kind==='tables')loadTable();else render();});
$('internal-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.text=$('internal-search').value;state.limit=36;if(state.kind==='tables'&&state.table)loadTable();else render();},250);};
$('internal-filter').onchange=()=>{state.filter=$('internal-filter').value;state.limit=36;render();};
$('internal-category').onchange=()=>{state.category=$('internal-category').value;state.table='';$('internal-table').value='';state.limit=36;updateUrl();render();};
$('internal-table').onchange=()=>{state.table=$('internal-table').value;state.chunk=0;state.limit=36;updateUrl();loadTable();};
$('internal-chunk').onchange=()=>{state.chunk=Number($('internal-chunk').value);state.limit=36;loadTable();};
$('internal-more').onclick=()=>{state.limit+=36;render();};
$('internal-close').onclick=()=>{$('internal-detail').close();detailRequest++;};
$('internal-detail').onclick=event=>{if(event.target===$('internal-detail')){$('internal-detail').close();detailRequest++;}};
try{
  const [index,assets,events,orphans]=await Promise.all([json('./data/internal/index.json'),json('./data/assets.json'),json('./data/events.json'),json('./data/orphanassets.json')]);
  if(index.schemaVersion!==1||!index.tables||!index.entities)throw new Error('配信データの形式が一致しません。');
  state.index=index;state.assets=assets;state.events=events.events||[];state.orphans=orphans.rows||[];state.store=createMasterStore(index);state.view=createRecordView({store:state.store,assets,navigate:showRecord});
  const parameters=new URLSearchParams(location.search),kind=parameters.get('kind');if(Object.hasOwn(titles,kind))state.kind=kind;const table=parameters.get('table');if(Object.hasOwn(index.tables,table))state.table=table;state.category=parameters.get('category')||'';
  $('internal-table').replaceChildren(option('','すべての種類を見る'),...Object.keys(index.tables).map(name=>option(name,tableLabel(name)+' · '+(index.tables[name].rows??'取得エラー')+'件')));$('internal-table').value=state.table;
  $('internal-category').replaceChildren(option('','すべてのカテゴリ'),...Object.entries(categoryNames).map(([name,label])=>option(name,label)));$('internal-category').value=state.category;
  refreshFilters();if(state.kind==='tables')await loadTable();else await render();const id=parameters.get('id');if(state.table&&/^\d+$/.test(id||''))await showRecord(state.table,Number(id));
}catch(exception){error(exception.message);$('internal-grid').setAttribute('aria-busy','false');}
