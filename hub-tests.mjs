import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHub,gachaTitle,permanentGacha} from './hub-sdk.js';
const load=name=>JSON.parse(fs.readFileSync(new URL(name,import.meta.url),'utf8'));
const catalog=load('catalog.json'),events=load('events.json'),live=load('live-data.json'),assets=load('assets.json'),rates=load('gacha-rates.json');
const hub=createHub(catalog,events,assets,live);
test('常設ガチャを日付スケジュールから除き、実際の開催名で検索する',()=>{
  assert.ok(hub.gachaEvents.some(permanentGacha));
  assert.ok(hub.querySchedule({view:'all'}).filter(r=>r.kind==='gacha').every(r=>!permanentGacha(r.source)));
  const event=hub.gachaEvents.find(e=>e.header_title&&e.end_at<4102444800);
  assert.equal(gachaTitle(event,{name:'シングルガチャ'}),event.header_title);
  assert.ok(hub.gachas({text:event.header_title,now:event.start_at}).some(g=>g.id===event.gacha_group_id));
});
test('ラキモンをドロップIDから解決し、アイコンと入手先を関連付ける',()=>{
  const week=hub.lucky.find(w=>w.drop_ids.length);
  assert.ok(week);
  for(const entry of hub.luckyCharacters(week)){
    assert.ok(entry.forms.length);
    assert.ok(entry.forms.every(c=>c.drop_id===entry.dropId));
    assert.ok(hub.characterImage(entry.forms[0]));
  }
});
test('取得した割合は原文の精度と初回10連の条件を保持する',()=>{
  assert.ok(rates.rates.length>200);
  const row=rates.rates.find(r=>r.gachaGroupId===11173);
  assert.equal(row.entries.find(e=>e.name==='★5-6').rate,'12.0 %');
  assert.equal(row.entries.find(e=>e.name.includes('その他 ★5-6')).rate,'0.012 %');
  assert.ok(rates.rates.every(r=>r.title==='通常の提供割合'||r.title==='初回10連の提供割合（対象条件あり）'));
  assert.ok(rates.rates.every(r=>!r.entries.some(e=>/[\[\]]/.test(e.name))));
});
test('未取得のクリア集計を生成せず、公開画像参照が実在する',()=>{
  const observed=new Set((hub.data.recommendations||[]).map(r=>r.stage_id));
  const absent=hub.library.tables.stages.find(s=>!observed.has(s.id));
  assert.equal(hub.library.stage(absent.id).community,null);
  for(const paths of Object.values(assets))if(paths&&typeof paths==='object'&&!Array.isArray(paths))for(const path of Object.values(paths))if(typeof path==='string'&&path.startsWith('assets/'))assert.ok(fs.existsSync(new URL(path,import.meta.url)),path);
});
