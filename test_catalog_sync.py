import unittest
from catalog_sync import FIELDS,build_catalog,GIMMICK_TEXT_IDS

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
    def test_text_label_requires_matching_game_id(self):
        tables=self.tables();tables['texts']=[{'id':1356,'label':'eTEXTS_DEF_ME_STAGE_MAIN_GIMMICK_HELP_1','text':'[GIMMICK:重力バリア][LF]説明[GIMMICK_END]'}]
        result=build_catalog(tables,'2026-10-14T00:00:00Z',[],[])
        self.assertEqual(result['gimmicks'][0]['label'],'重力バリア')
        self.assertIsNone(result['gimmicks'][1]['label'])

if __name__=='__main__':unittest.main()
