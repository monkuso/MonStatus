import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizePlayerId,formatPlayerId,fetchPlayer} from './profile-sdk.js';
test('公開IDの桁と全角・区切りを処理し、無効な入力を拒否する',()=>{
  assert.equal(normalizePlayerId('５５１,６８２,８７９,７６９'),'551682879769');
  assert.equal(formatPlayerId('551682879769'),'551,682,879,769');
  assert.equal(normalizePlayerId('123 456 789'),'123456789');
  for(const value of ['000000000','551682879769123','abc123456789','123456789/'])assert.throws(()=>normalizePlayerId(value));
});
test('別IDの応答やHTMLの起動ページをプロフィールとして採用しない',async()=>{
  const original=globalThis.fetch;
  try{
    globalThis.fetch=async()=>({ok:true,json:async()=>({schemaVersion:1,name:'別ユーザー',rank:1,characters:[],playerId:'123456789'})});
    await assert.rejects(fetchPlayer('https://example.com','551682879769'),/応答/);
    globalThis.fetch=async()=>({ok:true,json:async()=>{throw new Error('HTML');}});
    await assert.rejects(fetchPlayer('https://example.com','551682879769'),/起動/);
  }finally{globalThis.fetch=original;}
});
