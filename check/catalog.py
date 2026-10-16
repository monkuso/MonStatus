import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from catalog import FIELDS,build_catalog

class CatalogTests(unittest.TestCase):
    def tables(self):
        rows={name:[] for name in FIELDS}
        rows.update({'stages':[{'id':1,'name':'クエスト','stage_group_id':99,'user_token':'private'}],'stage_groups':[{'id':2,'name':'グループ'}],'gacha_groups':[{'id':3,'name':'ガチャ'}],'chars':[{'id':4,'name':'モンスター'}],'gachas':[{'id':5,'gacha_group_id':3,'char_id':4}]})
        return rows
    def test_unresolved_stage_preserved_and_private_fields_omitted(self):
        result=build_catalog(self.tables(),'2026-10-14T00:00:00Z',[],[])
        self.assertEqual(len(result['tables']['stages']),1)
        self.assertNotIn('user_token',result['tables']['stages'][0])
        self.assertEqual(result['relations'][0]['unresolved'],[99])
    def test_duplicate_identity_rejected(self):
        tables=self.tables()
        tables['stages'].append(tables['stages'][0])
        with self.assertRaises(ValueError):build_catalog(tables,'2026-10-14T00:00:00Z',[],[])
    def test_all_gacha_fields_and_new_tables_preserved_without_credentials(self):
        tables=self.tables()
        tables['gacha_groups'][0].update({'gacha_point':100,'new_version_field':{'value':12,'session':'private'},'secret':'private'})
        tables['new_special_gachas']=[{'id':9,'gacha_group_id':3,'new_field':'説明'}]
        tables['item_texts']=[{'id':1,'item_id':2,'text':'アイテムの説明'}]
        result=build_catalog(tables,'2026-10-16T00:00:00Z',[],[])
        self.assertEqual(result['tables']['gacha_groups'][0]['new_version_field'],{'value':12})
        self.assertNotIn('secret',result['tables']['gacha_groups'][0])
        self.assertEqual(result['tables']['new_special_gachas'],tables['new_special_gachas'])
        self.assertEqual(result['tables']['item_texts'],tables['item_texts'])
    def test_text_label_requires_matching_game_id(self):
        tables=self.tables();tables['texts']=[{'id':1356,'label':'eTEXTS_DEF_ME_STAGE_MAIN_GIMMICK_HELP_1','text':'[GIMMICK:重力バリア][LF]説明[GIMMICK_END]'}]
        result=build_catalog(tables,'2026-10-14T00:00:00Z',[],[])
        self.assertEqual(result['gimmicks'][0]['label'],'重力バリア')
        self.assertIsNone(result['gimmicks'][1]['label'])

if __name__=='__main__':unittest.main()
