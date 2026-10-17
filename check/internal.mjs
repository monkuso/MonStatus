import test from 'node:test';
import assert from 'node:assert/strict';
import {abilityNames,characterStats,loadCharacterInfo} from '../web/charactersdk.js';
import {classifyCharacter,classifyQuest,queryInternal,rawChunk,recordIdentity} from '../web/internalsdk.js';
import {createMasterStore} from '../web/masterdata.js';
import {createHash} from 'node:crypto';
import {recordImageNames,recordImagePaths} from '../web/record-images.js';

test('複数の画像パーツと同名の別絵柄を表示し、数値や拡張子を推測しない',()=>{
  const row={base_image:'base.png',frame_image:'frame.png',icon_name_1:'icon1.png',icon_name_2:'icon2.png',image_id:12,texture_name:'extensionless',file_name:'scene.ccbi'};
  assert.deepEqual(recordImageNames(row),['base.png','frame.png','icon1.png','icon2.png']);
  assert.deepEqual(recordImagePaths(row,{events:{'base.png':'assets/base.webp','frame.png':'assets/frame.webp'},items:{'icon1.png':'assets/icon.webp'},eventVariants:{'icon2.png':[{path:'assets/a.webp'},{path:'assets/b.webp'}]}}),['assets/base.webp','assets/frame.webp','assets/icon.webp','assets/a.webp','assets/b.webp']);
});

test('全テーブルの詳細取得はSHA256を照合し、不一致後の再取得も検証する',async()=>{
  const bytes=new TextEncoder().encode(JSON.stringify({schemaVersion:1,table:'new_system2',rows:[{id:1,name:'追加情報'}]}));
  const part={file:'new_system2-0000.json',firstId:1,lastId:1,sha256:createHash('sha256').update(bytes).digest('hex')};
  const index={tables:{new_system2:{identityField:'id',chunks:[part]}}};let calls=0;
  const store=createMasterStore(index,async()=>{calls++;return calls===1?new TextEncoder().encode('broken').buffer:bytes.buffer;});
  await assert.rejects(store.record('new_system2',1),/整合性/);
  assert.equal((await store.record('new_system2',1)).name,'追加情報');
  await store.record('new_system2',1);assert.equal(calls,2);
});

test('コネクト条件は親の条件IDを、効果は実在する二つのgroup参照元を保持する',async()=>{
  const condition={id:11,type_id:4,value_1:2},assist={id:22,effect_param_2:5000};
  const info=await loadCharacterInfo({id:1},{record:async(table,id)=>table==='connect_skill_conditions'&&id===11?condition:table==='assist_skill_effects'&&id===22?assist:null,all:async table=>table==='connect_skill_effects'?[{id:1,group_id:35,value:100}]:table==='char_sort_abilities'?[{id:2,group_id:1901,name:'連撃キラー',description:'攻撃力がアップ'}]:[],related:async(table,id,target)=>target==='connect_skills'?[{id:10,char_id:1,connect_skill_conditions_id_1_1:11,connect_skill_effect_group_id_1:35,connect_skill_effect_group_id_2:1901}]:target==='assist_skills'?[{id:20,char_id:1,assist_skill_effect_id_1:22}]:[]});
  assert.equal(info.connectSkills[0].conditions[0].row,condition);
  assert.equal(info.connectSkills[0].conditions[0].sourceField,'connect_skill_conditions_id_1_1');
  assert.equal(info.connectSkills[0].effects[0].sources[0].table,'connect_skill_effects');
  assert.equal(info.connectSkills[0].effects[1].sources[0].row.name,'連撃キラー');
  assert.equal(info.assistSkills[0].effects[0],assist);
});

test('nativeで確認したキャラ報酬IDだけを解決し、元IDと境界を保持する',async()=>{
  const character={id:13112,name:'下界をエンジョイ オシラサマ'};
  const index={tables:{items:{identityField:'id',chunks:[]},chars:{identityField:'id',chunks:[]}},entities:{chars:[character]},referenceRules:{characterItem:{minimum:10000,maximum:9999999,offset:10000}}};
  const store=createMasterStore(index);
  assert.deepEqual(await store.resolve('items',23112),{table:'chars',id:13112,row:character,sourceTable:'items',sourceId:23112});
  assert.equal(store.characterItemId(9999),null);assert.equal(store.characterItemId(10000),0);
  assert.equal(store.characterItemId(9999999),9989999);assert.equal(store.characterItemId(10000000),null);
  assert.equal(await store.resolve('items',10000),null);
  assert.equal(await store.resolve('items',9999999),null);
});
test('最近更新された公開済みキャラを未公開扱いしない',()=>{const row={id:2674,rarity:6,sort_id:10,virtual_char_id:0,collection_enable_at:50,updated_at:999};assert.equal(classifyCharacter(row,100).masked,false);assert.equal(queryInternal([row],{now:100}).length,0);});
test('図鑑マスクを時刻・仮想キャラ例外・特殊範囲から分類する',()=>{assert.equal(classifyCharacter({id:1,sort_id:0,virtual_char_id:1,collection_enable_at:50},100).masked,false);assert.ok(classifyCharacter({id:1,collection_enable_at:101},100).reasons.some(r=>r.kind==='future'));assert.equal(classifyCharacter({id:26000},100).reasons[0].kind,'special-range');assert.ok(classifyCharacter({id:1,sort_id:0,virtual_char_id:0},100).reasons.some(r=>r.kind==='info-mask'));assert.equal(classifyCharacter({id:1},100).masked,null);});
test('クエストの未参照を実装予定や未公開と同一視しない',()=>{const events=[{sourceTable:'stage_group_events',stageGroupId:2,startAt:50}];assert.deepEqual(classifyQuest({id:1},events,100).reasons.map(r=>r.kind),['unlisted']);assert.equal(classifyQuest({id:1},[],100).reasons.length,0);assert.match(classifyQuest({id:1,released_at:4753368000},[],100).reasons[0].label,/遠未来/);});
test('raw chunk の範囲とパスを検証する',()=>{const index={tables:{chars:{chunks:[{firstId:1,lastId:100,file:'chars-0000.json'}]}}};assert.equal(rawChunk(index,'chars',5).file,'chars-0000.json');assert.equal(rawChunk(index,'chars',200),null);index.tables.chars.chunks[0].file='../private.json';assert.equal(rawChunk(index,'chars',5),null);});
test('ゲームIDを持たない配置テーブルのレコード0を識別する',()=>{const index={tables:{stage_phase_blocks:{identityField:'_recordIndex'}}};assert.equal(recordIdentity(index,'stage_phase_blocks',{_recordIndex:0,stage_phase_id:20}),0);assert.equal(recordIdentity(index,'chars',{id:5}),5);});
test('複合アビリティを属性別の単品より優先し重複させない',()=>{const effects=[1,2,3,4,5].map(target_id=>({type_id:14,target_id,value:150,name_id:null}));const combined=effects.map((row,index)=>({...row,id:1005+index,group_id:1005,name:'全属性キラー',description:'全属性への攻撃力アップ'}));const singles=effects.map((row,index)=>({...row,id:1031+index,group_id:1031+index,name:`属性${index}`,description:'単属性'}));assert.deepEqual(abilityNames(effects,[...singles,...combined]).normal.map(row=>row.name),['全属性キラー']);assert.equal(abilityNames(effects.slice(0,1),[...singles,...combined]).normal[0].name,'属性0');});
test('値とtargetを厳密に合わせ、ゲージを分離する',()=>{const definition={id:1,group_id:1,type_id:1,target_id:0,value:100,name_id:0,name:'アンチ重力バリア',description:'重力バリアで減速しない'};assert.equal(abilityNames([{type_id:1,target_id:null,value:150}], [definition]).normal.length,0);assert.equal(abilityNames([{type_id:1,target_id:null,value:100,shot_gauge_level:4}], [definition]).gauge[0].name,'アンチ重力バリア');});
test('速度をゲームの表示単位に換算しLv120の最終値と混同しない',()=>{const stats=characterStats({hp_max:10000,attack_max:20000,power_max:11939,extend_power_max:1950,level_max:120});assert.ok(Math.abs(stats[2].base-397.9666667)<0.00001);assert.equal(stats[2].plusRaw,66.3);assert.equal(stats[0].base,10000);});
test('友情・SS・種族などを名前のあるレコードへ関連付ける',async()=>{const records={'strike_shots:10':{id:10,name:'光の一撃',require_cnt:12,description:'攻撃アップ'},'strike_shots:11':{id:11,name:'光の一撃',require_cnt:20},'char_species:7':{id:7,name:'亜人'}};const info=await loadCharacterInfo({id:1,species_id:7,fight_type:12,strike_shot_id:10,enhanced_strike_shot_id:11},{record:async(t,id)=>records[t+':'+id]||null,all:async(table)=>table==='fight_types'?[{id:7,type_id:12,name:'超スピード型'}]:[],related:async(t,id,target)=>target==='char_skills'?[{name:'ラジアルエッジ',description:'貫通弾を発射'}]:[]});assert.equal(info.friendships[0].name,'ラジアルエッジ');assert.equal(info.strikeShot.name,'光の一撃');assert.equal(info.enhancedStrikeShot.require_cnt,20);assert.equal(info.species.name,'亜人');assert.equal(info.fight.name,'超スピード型');});
