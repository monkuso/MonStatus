import {assetImageUrl,cleanText} from './hubsdk.js';
import {attributeMeta} from './sdk.js';
export function characterImageElement(row,{assets={},source,className=''}={}){
  const path=source||assets.characters?.[String(row.skin_id||row.id)],url=assetImageUrl(path,assets);if(!url)return null;
  const wrap=document.createElement('span');wrap.className=('character-icon '+className).trim();wrap.dataset.characterId=String(row.id);
  const kind=assets.characterImageKinds?.[String(row.skin_id||row.id)]||'ball';wrap.dataset.imageKind=kind;
  const frameSource=kind==='ball'?assetImageUrl(assets.characterFrames?.[String(row.attribute_id)],assets):null;
  if(frameSource){const frame=document.createElement('img');frame.className='character-icon-frame';frame.src=frameSource;frame.alt=(attributeMeta(row.attribute_id)?.label||'無')+'属性';frame.loading='lazy';frame.decoding='async';wrap.append(frame);}
  const image=document.createElement('img');image.className='character-icon-art';image.src=url;image.alt=cleanText(row.name||'モンスター');image.loading='lazy';image.decoding='async';wrap.append(image);
  const attribute=assetImageUrl(assets.attributes?.[String(row.attribute_id)],assets);
  if(attribute&&!frameSource){const badge=document.createElement('img');badge.className='character-icon-attribute';badge.src=attribute;badge.alt=(attributeMeta(row.attribute_id)?.label||'無')+'属性';badge.loading='lazy';badge.decoding='async';wrap.append(badge);}
  return wrap;
}
