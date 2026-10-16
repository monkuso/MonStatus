import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHub,gachaTitle,permanentGacha,assetImageUrl} from '../web/hubsdk.js';
import {relatedGachaData,occurrenceTime,rateCoverage,gachaTableNames} from '../web/gachadetails.js';
const load=name=>JSON.parse(fs.readFileSync(new URL('../data/'+name,import.meta.url),'utf8'));
const catalog=load('catalog.json'),events=load('events.json'),live=load('livedata.json'),assets=load('assets.json'),rates=load('gacharates.json');
catalog.gachaRates=rates.rates;
catalog.gachaMessages=rates.messages;
const hub=createHub(catalog,events,assets,live);

test('同じガチャの別開催を保持し、履歴の予定を開催中・予定へ混入させない',()=>{
  const base={schemaVersion:1,updatedAt:'2026-10-16T00:00:00Z',tables:{stages:[],stage_groups:[],chars:[],gachas:[],stage_gimmicks:[],gacha_groups:[{id:1,name:'繰り返し'},{id:2,name:'常設'},{id:3,name:'未開催'}]},gachaEvents:[{id:10,gacha_group_id:1,start_at:200,end_at:250},{id:11,gacha_group_id:1,start_at:300,end_at:350},{id:12,gacha_group_id:1,start_at:400,end_at:450,retainedForHistory:true},{id:13,gacha_group_id:2,start_at:0,end_at:4102444800}]};
  const fixture=createHub(base,{events:[]});
  assert.deepEqual(fixture.gachaAppearances({view:'upcoming',now:100}).map(r=>r.occurrence.id),[11,10]);
  assert.equal(fixture.gachaAppearances({view:'permanent',now:100}).length,1);
  assert.equal(fixture.gachaAppearances({view:'all',now:100}).length,4);
  assert.equal(fixture.gachaAppearances({view:'all',all:true,now:100}).length,5);
  assert.equal(fixture.gachaAppearances({view:'active',now:425}).length,0);
  assert.equal(occurrenceTime(base.gachaEvents[0],100),200);
  assert.equal(occurrenceTime(base.gachaEvents[0],999),250);
});

test('配信済み全開催記録を日付別に表示し、同一IDの開催回を省略しない',()=>{
  const rows=hub.gachaAppearances({view:'all'});
  const expected=new Set(hub.gachaEvents.filter(e=>hub.library.indexes.gacha_groups.has(e.gacha_group_id)).map(e=>JSON.stringify([e.gacha_group_id,e.id,e.start_at,e.end_at,e.type_id,e.kind_id])));
  assert.equal(rows.length,expected.size);
  assert.equal(new Set(rows.map(r=>r.occurrenceKey)).size,rows.length);
});

test('過去の提供割合は現在の提供割合として使わず、履歴として参照できる',()=>{
  const fixture=createHub({...catalog,tables:{...catalog.tables,gacha_groups:[{id:11252,name:'履歴テスト'}]},gachaMessages:[{messageId:1,gachaGroupId:11252,startAt:1,endAt:9999,retainedForHistory:true}],gachaRates:[{messageId:1,gachaGroupId:11252,startAt:1,endAt:9999,retainedForHistory:true,entries:[{name:'★5-6',rate:'12.0 %'}]}]},events);
  assert.equal(fixture.providedRates(11252,100).length,0);
  assert.equal(fixture.providedRates(11252,100,true).length,1);
  assert.equal(rateCoverage(fixture,[{id:11252,occurrence:{start_at:1,end_at:150,retainedForHistory:true}}],100).withRates,1);
});

test('特殊ガチャは実在の外部キーだけで結合し、表示重みを割合やガチャIDとして解釈しない',()=>{
  const fixture=createHub({...catalog,tables:{...catalog.tables,login_power_up_gachas:[{id:99,gacha_group_id:11252,login_power_up_gacha_event_id:7}],login_power_up_gacha_events:[{id:7,description:'説明'}],selectable_pickup_gacha_display_weights:[{id:1,group_id:11252,display_weight:24000}],unknown_gacha_events:[{id:22,gacha_group_id:11252,new_field:'new'}]}},events);
  const sections=relatedGachaData(fixture,11252).sections;
  assert.equal(sections.find(s=>s.name==='unknown_gacha_events').rows[0].new_field,'new');
  assert.equal(sections.find(s=>s.name==='login_power_up_gachas').rows[0].id,99);
  assert.ok(!sections.some(s=>s.name==='selectable_pickup_gacha_display_weights'));
  assert.ok(gachaTableNames(fixture.library.tables).includes('selectable_pickup_gacha_display_weights'));
});
test('更新された画像には内容ハッシュを付け、外部URLや親ディレクトリを拒否する',()=>{
  const path='assets/characters/03/13103.webp';
  assert.equal(assetImageUrl(path,{imageVersions:{[path]:'1234567890abcdef'}}),path+'?v=1234567890abcdef');
  assert.equal(assetImageUrl(path),path);
  assert.equal(assetImageUrl('https://example.test/image.png'),null);
  assert.equal(assetImageUrl('assets/../private.json'),null);
});
test('スケジュールはイベントクエストだけを表示し、ガチャはガチャ一覧で検索する',()=>{
  assert.ok(hub.gachaEvents.some(permanentGacha));
  assert.ok(hub.querySchedule({view:'all'}).length>0);
  assert.ok(hub.querySchedule({view:'all'}).every(r=>r.kind==='quest'&&r.endAt<4102444800));
  const event=hub.gachaEvents.find(e=>e.header_title&&e.end_at<4102444800);
  assert.equal(gachaTitle(event,{name:'シングルガチャ'}),event.header_title);
  assert.ok(hub.gachas({text:event.header_title,now:event.start_at}).some(g=>g.id===event.gacha_group_id));
});
test('ガチャ内部定義は表示開始前・古い未参照定義も保持し、予定を開始順に表示する',()=>{
  const fixture=createHub({schemaVersion:1,updatedAt:'2026-10-16T00:00:00Z',tables:{stages:[],stage_groups:[],chars:[],gachas:[],stage_gimmicks:[],gacha_groups:[{id:1,name:'通常',updated_at:1},{id:2,name:'次回',updated_at:2},{id:3,name:'後日',updated_at:3},{id:4,name:'未参照',updated_at:1},{id:5,name:'常設',updated_at:1}]},gachaEvents:[{id:1,gacha_group_id:1,start_at:50,end_at:150,visible_at:0},{id:2,gacha_group_id:1,start_at:250,end_at:350,visible_at:200},{id:3,gacha_group_id:2,start_at:200,end_at:300,visible_at:190},{id:4,gacha_group_id:3,start_at:400,end_at:500,visible_at:390},{id:5,gacha_group_id:5,start_at:0,end_at:4102444800}]},{events:[]});
  assert.deepEqual(fixture.gachas({view:'active',now:100}).map(g=>g.id),[1]);
  assert.deepEqual(fixture.gachas({view:'upcoming',now:100}).map(g=>g.id),[3,1,2]);
  assert.deepEqual(fixture.gachas({view:'internal',now:100}).map(g=>g.id),[3,2,1,5,4]);
  assert.deepEqual(fixture.gachas({view:'leaked',now:100}).map(g=>g.id),[4]);
  assert.equal(fixture.gachaSchedule(1,'upcoming',100).start_at,250);
  assert.equal(fixture.gachaSchedule(1,'active',100).start_at,50);
  assert.equal(fixture.gachaSchedule(4,'internal',100),null);
  assert.equal(fixture.gachaSchedule(5,'internal',100),null);
});

test('ガチャをJSTの開始日YYYY/MM/DDでまとめ、日付不明は末尾に置く',()=>{
  const stamp=value=>Date.parse(value)/1000;
  const fixture=createHub({schemaVersion:1,updatedAt:'2026-10-16T00:00:00Z',tables:{stages:[],stage_groups:[],chars:[],gachas:[],stage_gimmicks:[],gacha_groups:[{id:1},{id:2},{id:3},{id:4,updated_at:9999999999}]},gachaEvents:[{id:1,gacha_group_id:1,start_at:stamp('2026-10-15T15:00:00Z'),end_at:stamp('2026-11-01T00:00:00Z')},{id:2,gacha_group_id:2,start_at:stamp('2026-10-16T14:59:00Z'),end_at:stamp('2026-11-01T00:00:00Z')},{id:3,gacha_group_id:3,start_at:stamp('2026-10-16T15:00:00Z'),end_at:stamp('2026-11-01T00:00:00Z')}]},{events:[]});
  const rows=fixture.library.tables.gacha_groups,now=stamp('2026-10-14T00:00:00Z');
  const upcoming=fixture.gachaDateSections([rows[2],rows[1],rows[3],rows[0]],'upcoming',now);
  assert.deepEqual(upcoming.map(group=>group.day),['2026/10/17','2026/10/16',null]);
  assert.deepEqual(upcoming[1].rows.map(row=>row.id),[2,1]);
  assert.deepEqual(fixture.gachaDateSections(rows,'internal',now).map(group=>group.day),['2026/10/17','2026/10/16',null]);
  assert.deepEqual(upcoming.flatMap(group=>group.rows.map(row=>row.id)),[3,2,1,4]);
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
  if(absent)assert.equal(hub.library.stage(absent.id).community,null);
  assert.ok((hub.data.recommendations||[]).every(row=>hub.library.indexes.stages.has(row.stage_id)));
  for(const paths of Object.values(assets))if(paths&&typeof paths==='object'&&!Array.isArray(paths))for(const path of Object.values(paths))if(typeof path==='string'&&path.startsWith('assets/'))assert.ok(fs.existsSync(new URL('../'+path,import.meta.url)),path);
});
