import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from internal import SCHEMAS,internal_rows,write_internal,reference_tables

class InternalTests(unittest.TestCase):
    def test_exact_master_references_take_priority_over_item_and_character_suffixes(self):
        tables={name:[] for name in ['items','chars','purchase_items','boost_items','campaign_items','support_chars']}
        tables['source']=[{'purchase_item_id':11,'boost_item_id':12,'campaign_item_id':13,'support_char_id':14,'prev_char_id':15,'cost_item_id':16}]
        refs=reference_tables(tables)['source']
        self.assertEqual(refs,{'purchase_item_id':'purchase_items','boost_item_id':'boost_items','campaign_item_id':'campaign_items','support_char_id':'support_chars','prev_char_id':'chars','cost_item_id':'items'})
    def test_character_reward_encoding_adds_reverse_links_without_changing_source(self):
        tables={'chars':[{'id':13112,'name':'オシラサマ'}],'login_stamp_items':[{'id':2968,'item_id':23112,'cnt':9}]}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            write_internal(tables,'2026-10-17T00:00:00Z',[],directory)
            index=json.loads((Path(directory)/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['relations']['chars']['13112']['login_stamp_items'],[2968])
            self.assertEqual(index['relations']['items']['23112']['login_stamp_items'],[2968])
            self.assertEqual(index['referenceRules']['characterItem']['offset'],10000)
            source=json.loads((Path(directory)/'login_stamp_items-0000.json').read_text(encoding='utf-8'))
            self.assertEqual(source['rows'][0]['item_id'],23112)
    def test_all_master_names_and_distinct_verification_states_are_retained(self):
        tables={'chars':[{'id':1,'name':'モンスター'}],'login_stamp_groups':[{'id':5,'title':'ログイン','start_at':100,'end_at':200}],'login_stamps':[{'id':6,'login_stamp_group_id':5}],'login_stamp_items':[{'id':7,'login_stamp_id':6,'item_id':8,'cnt':2}],'items':[{'id':8,'name':'オーブ','image_name':'uiitem_0001.png'}],'unknown_system2':[{'id':1,'new_value':9}]}
        proofs=[{'table':'legacy','status':'manifest-integrity-unavailable','crc':123,'sha256':'a'*64}]
        tables['legacy']=[];tables['empty_events']=[]
        proofs.append({'table':'empty_events','status':'not-distributed','crc':0})
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            write_internal(tables,'2026-10-16T00:00:00Z',proofs,directory,[{'name':name} for name in [*tables,'failed_events']],[{'table':'failed_events','errorType':'HTTPError'}])
            index=json.loads((Path(directory)/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['coverage']['expected'],9)
            self.assertEqual(index['coverage']['missing'],[])
            self.assertEqual(index['coverage']['limitedIntegrity'],1)
            self.assertEqual(index['tables']['failed_events']['status'],'error')
            self.assertIsNone(index['tables']['failed_events']['rows'])
            self.assertEqual(index['relations']['login_stamp_groups']['5']['login_stamps'],[6])
            self.assertEqual(index['relations']['login_stamps']['6']['login_stamp_items'],[7])
            self.assertEqual(index['relations']['items']['8']['login_stamp_items'],[7])
            self.assertEqual(index['collections']['items'][0]['image_name'],'uiitem_0001.png')
            self.assertEqual(index['tables']['unknown_system2']['fields'],['id','new_value'])

    def test_duplicate_native_ids_get_record_identity_without_losing_original_ids(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            write_internal({'unknown_groups':[{'id':1,'name':'A'},{'id':1,'name':'B'}]},'2026-10-16T00:00:00Z',[],directory)
            index=json.loads((Path(directory)/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['tables']['unknown_groups']['identityField'],'_recordIndex')
            rows=json.loads((Path(directory)/'unknown_groups-0000.json').read_text(encoding='utf-8'))['rows']
            self.assertEqual([r['id'] for r in rows],[1,1])
            self.assertEqual([r['_recordIndex'] for r in rows],[0,1])
    def test_schema_fields_are_kept_and_unregistered_fields_are_omitted(self):
        row=internal_rows('chars',[{'id':1,'collection_enable_at':200,'sort_id':0,'user_token':'private'}])[0]
        self.assertEqual(row['collection_enable_at'],200)
        self.assertNotIn('user_token',row)

    def test_character_summaries_include_friendship_names_and_skill_relations(self):
        tables={'chars':[{'id':1,'name':'キャラ','hp_max':10000}],'char_skills':[{'id':9,'char_id':1,'name':'ラジアルエッジ'}],'fight_types':[{'id':7,'type_id':12,'name':'超スピード型'}],'assist_skills':[{'id':2,'char_id':1,'description':'攻撃力アップ'}]}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            write_internal(tables,'2026-10-15T00:00:00Z',[],directory)
            index=json.loads((Path(directory)/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['entities']['chars'][0]['friendshipNames'],['ラジアルエッジ'])
            self.assertEqual(index['relations']['chars']['1']['assist_skills'],[2])
            self.assertEqual(index['tables']['fight_types']['rows'],1)

    def test_chunks_cover_ids_and_match_declared_hashes(self):
        tables={name:[] for name in SCHEMAS}
        tables['chars']=[{'id':i,'name':f'キャラ{i}','collection_enable_at':200} for i in range(1,260)]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            write_internal(tables,'2026-10-15T00:00:00Z',[],directory)
            index=json.loads((Path(directory)/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(len(index['entities']['chars']),259)
            self.assertEqual(len(index['tables']['chars']['chunks']),2)
            for chunk in index['tables']['chars']['chunks']:
                self.assertEqual(hashlib.sha256((Path(directory)/chunk['file']).read_bytes()).hexdigest(),chunk['sha256'])

    def test_non_id_tables_keep_source_values_and_use_explicit_record_indices(self):
        tables={'stage_phase_blocks':[{'stage_phase_id':20,'x':4},{'stage_phase_id':20,'x':8}], 'char_ability_descriptions':[{'id':2,'description':'内部アビリティ','new_content_field':7}]}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            write_internal(tables,'2026-10-15T00:00:00Z',[],directory)
            index=json.loads((Path(directory)/'index.json').read_text(encoding='utf-8'))
            self.assertEqual(index['tables']['stage_phase_blocks']['identityField'],'_recordIndex')
            payload=json.loads((Path(directory)/'stage_phase_blocks-0000.json').read_text(encoding='utf-8'))
            self.assertNotIn('id',payload['rows'][0])
            self.assertEqual(payload['rows'][1]['_recordIndex'],1)
            self.assertEqual(index['relations']['stage_phases']['20']['stage_phase_blocks'],[0,1])
            self.assertIn('new_content_field',index['tables']['char_ability_descriptions']['fields'])
