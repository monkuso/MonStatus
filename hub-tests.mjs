import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHub,gachaTitle,permanentGacha} from './hub-sdk.js';
const load=name=>JSON.parse(fs.readFileSync(new URL(name,import.meta.url),'utf8'));
const catalog=load('catalog.json'),events=load('events.json'),live=load('live-data.json'),assets=load('assets.json'),rates=load('gacha-rates.json');
catalog.gachaRates=rates.rates;
catalog.gachaMessages=rates.messages;
const hub=createHub(catalog,events,assets,live);
test('スケジュールはイベントクエストだけを表示し、ガチャはガチャ一覧で検索する',()=>{
  assert.ok(hub.gachaEvents.some(permanentGacha));
  assert.ok(hub.querySchedule({view:'all'}).length>0);
  assert.ok(hub.querySchedule({view:'all'}).every(r=>r.kind==='quest'&&r.endAt<4102444800));
  const event=hub.gachaEvents.find(e=>e.header_title&&e.end_at<4102444800);
  assert.equal(gachaTitle(event,{name:'シングルガチャ'}),event.header_title);
  assert.ok(hub.gachas({text:event.header_title,now:event.start_at}).some(g=>g.id===event.gacha_group_id));
});
test('同一クエストの重複・重なる期間を統合し、別時間帯と別クエストを保持する',()=>{
  const event=events.events.find(e=>e.sourceTable==='stage_group_events'&&e.endAt<4102444800);
  const another=events.events.find(e=>e.sourceTable==='stage_group_events'&&e.stageGroupId!==event.stageGroupId);
  const make=(id,startAt,endAt,extra={})=>({...event,id,startAt,endAt,...extra});
  const fixture=createHub(catalog,{events:[make('a',100,200),make('b',100,200,{questName:'別の案内文'}),make('c',150,250),make('d',300,400),make('e',100,200,{stageGroupId:another.stageGroupId})]});
  const rows=fixture.querySchedule({view:'all',now:175});
  assert.deepEqual(rows.filter(r=>r.id===event.stageGroupId).map(r=>[r.startAt,r.endAt]),[[100,250],[300,400]]);
  assert.equal(rows.length,3);
  assert.equal(fixture.querySchedule({view:'upcoming',now:275}).length,1);
  assert.deepEqual(fixture.quests({now:275}).map(g=>g.id),[]);
  assert.equal(fixture.quests({now:175,all:true}).length,2);
  assert.equal(fixture.quests({now:401,all:true}).length,0);
});
test('実データで同じクエストの重なる出現時間が別カードにならない',()=>{
  const groups=new Map();
  for(const row of hub.querySchedule({view:'all'})){const previous=groups.get(row.id);if(previous)assert.ok(previous.endAt<row.startAt||row.endAt<previous.startAt);groups.set(row.id,row);}
});
test('覇者の塔の階層別IDを一つの出現日程にまとめ、各階層への参照を保持する',()=>{
  const rows=hub.querySchedule({view:'all'}).filter(r=>r.name==='覇者の塔'&&r.groupIds.includes(97681));
  assert.equal(rows.length,1);
  assert.ok(rows[0].groupIds.includes(97682));
  assert.ok(rows[0].groupIds.every(id=>hub.stagesByGroup.get(id)?.length));
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
test('ゲームの結合規則で子ガチャへ割合を共有し、50008の例外を守る',()=>{
  const time=1792000000;
  assert.equal(hub.providedRates(11174,time)[0]?.messageId,hub.providedRates(11173,time)[0]?.messageId);
  assert.ok(hub.providedRates(11175,time).length);
  const parent=catalog.tables.gacha_groups.find(g=>g.id===11173);
  const child={...parent,id:999999,parent_group_id:11173,category_id:50008};
  const fixture=createHub({...catalog,tables:{...catalog.tables,gacha_groups:[...catalog.tables.gacha_groups,child]}},events,assets,live);
  assert.equal(fixture.providedRates(child.id,time).length,0);
});
test('未取得のクリア集計を生成せず、公開画像参照が実在する',()=>{
  const observed=new Set((hub.data.recommendations||[]).map(r=>r.stage_id));
  const absent=hub.library.tables.stages.find(s=>!observed.has(s.id));
  assert.equal(hub.library.stage(absent.id).community,null);
  for(const paths of Object.values(assets))if(paths&&typeof paths==='object'&&!Array.isArray(paths))for(const path of Object.values(paths))if(typeof path==='string'&&path.startsWith('assets/'))assert.ok(fs.existsSync(new URL(path,import.meta.url)),path);
});
