import io
import unittest
from unittest.mock import patch
import zipfile
import zlib
import msgpack
from cloud_sync import SyncError,table_from_archive,normalize_events,build_gimmick_index,union_gimmicks_for_group,build_char_index,recommended_char_ids,build_wanted_boss_index,active_wanted_bosses,ADVANTAGE,clear_group_ids,merge_clear_results,sync_clear_groups

EMPTY_TABLES={'stage_groups':[],'stage_group_events':[],'stage_group_kind_events':[],'stage_group_cycle_events':[],'stages':[],'stage_gimmicks':[],'chars':[],'wanted_bosses':[],'wanted_boss_groups':[]}

class CloudSyncTests(unittest.TestCase):
    def test_clear_groups_select_current_and_permanent_groups_once(self):
        rows=[{'sourceTable':'stage_group_events','stageGroupId':1,'startAt':100,'endAt':200}]
        rows.extend([{**rows[0]}, {**rows[0],'stageGroupId':2,'startAt':201}, {**rows[0],'stageGroupId':3,'endAt':99}, {**rows[0],'stageGroupId':4,'endAt':4102444800}])
        self.assertEqual(clear_group_ids({'stageEvents':rows},150),[1,4])

    def test_premium_clear_results_preserve_server_order_and_public_fields(self):
        catalog={'tables':{'stages':[{'id':10}]},'recommendations':[],'community':{}}
        row={'stage_id':10,'gacha_char_ids':[33,11,22],'event_char_ids':[44],'aggregate_range':30,'private_field':'discard'}
        merge_clear_results(catalog,{'recommends':[row]},'2026-10-15T00:00:00+00:00')
        self.assertEqual(catalog['recommendations'][0]['gacha_char_ids'],[33,11,22])
        self.assertNotIn('private_field',catalog['recommendations'][0])
        with self.assertRaises(SyncError):merge_clear_results(catalog,{'recommends':[{**row,'stage_id':999}]},'2026-10-15T00:00:00+00:00')

    def test_group_failures_are_reported_without_invented_clear_results(self):
        catalog={'stageEvents':[{'sourceTable':'stage_group_events','stageGroupId':1,'startAt':0,'endAt':2000000000}], 'recommendations':[],'community':{}}
        with patch('cloud_sync.read_game',side_effect=SyncError('failed')):sync_clear_groups(catalog,{},'2026-10-15T00:00:00+00:00')
        self.assertEqual(catalog['recommendations'],[])
        self.assertEqual(catalog['community']['status'],'partial')
        self.assertEqual(catalog['community']['failedGroups'],[{'stageGroupId':1,'errorType':'SyncError'}])

    def archive(self,value):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('data',msgpack.packb(value))
        raw=buffer.getvalue()
        return raw,{'name':'stage_group_events','size':len(raw),'crc':zlib.crc32(raw)&0xFFFFFFFF}
    def test_daily_envelope_and_crc(self):
        raw,entry=self.archive({'result':0,'masters':[],'daily_masters':[{'stage_group_events':[{'id':1}]}]})
        self.assertEqual(table_from_archive(raw,entry,b''),[{'id':1}])
        with self.assertRaises(SyncError):table_from_archive(raw,{**entry,'crc':entry['crc']^1},b'')
    def test_application_error_is_not_success(self):
        raw,entry=self.archive({'result':2,'masters':[],'daily_masters':[]})
        with self.assertRaises(SyncError):table_from_archive(raw,entry,b'')
    def test_private_fields_not_exported(self):
        tables={**EMPTY_TABLES,'stage_groups':[{'id':9,'name':'クエスト','private_example':'ignore'}],'stage_group_events':[{'id':1,'name':'開催','stage_group_id':9,'start_at':100,'end_at':200,'user_group_set_id':77}]}
        events,_=normalize_events(tables)
        self.assertEqual(events[0]['questName'],'クエスト')
        self.assertNotIn('user_group_set_id',events[0])
        self.assertNotIn('private_example',events[0])
    def test_invalid_period_stops_publication(self):
        tables={**EMPTY_TABLES,'stage_group_events':[{'id':1,'name':'開催','start_at':200,'end_at':100}]}
        with self.assertRaises(SyncError):normalize_events(tables)
    def test_gimmick_index_rejects_corrupt_structure(self):
        with self.assertRaises(SyncError):build_gimmick_index({'stages':[{'id':'x','stage_group_id':1}],'stage_gimmicks':[]})
        with self.assertRaises(SyncError):build_gimmick_index({'stages':[],'stage_gimmicks':[{'stage_id':1,'gimmick_flag':-1,'highlight_gimmick_flag':0}]})
    def test_union_merges_bits_across_stages_in_group(self):
        stages_by_group={9:[101,102,103]}
        gimmicks_by_stage={101:(0x1,0x0),102:(0x4,0x2),103:(0x0,0x8)}
        flag,highlight,count=union_gimmicks_for_group(9,stages_by_group,gimmicks_by_stage)
        self.assertEqual(flag,0x5)
        self.assertEqual(highlight,0xA)
        self.assertEqual(count,3)
        self.assertEqual(union_gimmicks_for_group(9999,stages_by_group,gimmicks_by_stage),(0,0,0))
    def test_normalize_includes_gimmick_union_per_event(self):
        tables={**EMPTY_TABLES,'stage_groups':[{'id':9,'name':'クエスト'}],'stage_group_events':[{'id':1,'name':'開催','stage_group_id':9,'start_at':100,'end_at':200}],'stages':[{'id':101,'stage_group_id':9},{'id':102,'stage_group_id':9}],'stage_gimmicks':[{'stage_id':101,'gimmick_flag':0x3,'highlight_gimmick_flag':0x0},{'stage_id':102,'gimmick_flag':0x4,'highlight_gimmick_flag':0x1}]}
        [event],profiles=normalize_events(tables)
        self.assertEqual(event['gimmickFlag'],0x7)
        self.assertEqual(event['highlightGimmickFlag'],0x1)
        self.assertEqual(event['stageCount'],2)
        self.assertEqual(event['stagesWithGimmicks'],2)
    def test_event_without_group_has_zero_gimmicks(self):
        tables={**EMPTY_TABLES,'stage_group_events':[{'id':1,'name':'開催','start_at':100,'end_at':200}]}
        [event],_=normalize_events(tables)
        self.assertEqual(event['gimmickFlag'],0)
        self.assertEqual(event['highlightGimmickFlag'],0)
        self.assertEqual(event['stageCount'],0)
    def test_build_char_index_builds_profile_by_id(self):
        tables={'chars':[{'id':1,'name':'A','rarity':6,'attribute_id':2},{'id':2,'name':'B','rarity':5,'attribute_id':4}]}
        index=build_char_index(tables)
        self.assertEqual(index[1]['name'],'A')
        self.assertEqual(index[1]['attributeId'],2)
        self.assertEqual(index[2]['rarity'],5)
    def test_build_char_index_rejects_invalid_rows(self):
        with self.assertRaises(SyncError):build_char_index({'chars':[{'id':'x','name':'A'}]})
        with self.assertRaises(SyncError):build_char_index({'chars':[{'id':1,'name':None}]})
    def test_recommended_chars_pick_advantaged_attribute_sorted_by_rarity(self):
        index={1:{'id':1,'name':'A','rarity':5,'attributeId':2},2:{'id':2,'name':'B','rarity':6,'attributeId':2},3:{'id':3,'name':'C','rarity':4,'attributeId':4},4:{'id':4,'name':'D','rarity':6,'attributeId':2}}
        result=recommended_char_ids(1,index,limit=10)
        self.assertEqual(result,[2,4,1])
        self.assertEqual(recommended_char_ids(0,index),[])
        for stage_attr,target in ADVANTAGE.items():
            self.assertNotEqual(stage_attr,target)
    def test_active_wanted_bosses_respect_time_window(self):
        groups_by_id={100:{'startAt':50},200:{'startAt':5000}}
        bosses_by_group={100:[{'charId':11,'order':2,'startAt':60},{'charId':12,'order':1,'startAt':70}],200:[{'charId':21,'order':1,'startAt':5000}]}
        self.assertEqual(active_wanted_bosses(60,200,groups_by_id,bosses_by_group),[12,11])
        self.assertEqual(active_wanted_bosses(0,40,groups_by_id,bosses_by_group),[])
    def test_normalize_exports_recommended_and_wanted_chars(self):
        tables={**EMPTY_TABLES,
            'stage_groups':[{'id':9,'name':'クエスト','attribute_id':1}],
            'stage_group_events':[{'id':1,'name':'開催','stage_group_id':9,'start_at':100,'end_at':200}],
            'chars':[{'id':777,'name':'水キャラ','rarity':6,'attribute_id':2},{'id':778,'name':'火キャラ','rarity':6,'attribute_id':1}],
            'wanted_boss_groups':[{'id':50,'start_at':50}],
            'wanted_bosses':[{'id':1,'wanted_boss_group_id':50,'char_id':777,'order':1,'start_at':70}],
        }
        [event],profiles=normalize_events(tables)
        self.assertEqual(event['recommendedCharIds'],[777])
        self.assertEqual(event['wantedBossCharIds'],[777])
        self.assertIn('777',profiles)
        self.assertNotIn('778',profiles)
        self.assertEqual(profiles['777']['name'],'水キャラ')

if __name__=='__main__':unittest.main()
