import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from internal import SCHEMAS,internal_rows,write_internal
from sync import fetch_published,SyncError

class InternalTests(unittest.TestCase):
    def test_expanded_public_catalog_is_accepted_for_cache_restore(self):
        def download(url,limit):
            if limit<128*1024*1024:raise SyncError('Resource response rejected')
            return b'{"schemaVersion":1,"updatedAt":"2026-10-15T00:00:00Z"}'
        with patch('sync.download',side_effect=download):
            self.assertEqual(fetch_published('catalog')['schemaVersion'],1)

    def test_schema_fields_are_kept_and_unregistered_fields_are_omitted(self):
        row=internal_rows('chars',[{'id':1,'collection_enable_at':200,'sort_id':0,'user_token':'private'}])[0]
        self.assertEqual(row['collection_enable_at'],200)
        self.assertNotIn('user_token',row)

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
