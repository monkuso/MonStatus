import {loadMasterStore} from './masterdata.js';
import {createRecordView} from './record-view.js?v=icons3';
export function attachMasterRecord(parent,table,id,assets){
  const slot=document.createElement('section');slot.className='master-loading';slot.textContent='能力・条件・報酬・関連データを読み込み中…';parent.append(slot);
  (async()=>{try{const store=await loadMasterStore(),row=await store.record(table,id);if(!row)throw new Error('この登録情報は詳細データ内にありません。');const view=createRecordView({store,assets,navigate:(table,id)=>{location.href='./internal.html?kind=tables&table='+encodeURIComponent(table)+'&id='+id;}});const content=await view.render(table,row);if(!slot.isConnected)return;slot.className='';slot.replaceChildren(content);}catch(error){if(slot.isConnected){slot.className='error';slot.textContent=error.message;}}})();
}
