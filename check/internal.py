import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from internal import SCHEMAS,internal_rows,write_internal

class InternalTests(unittest.TestCase):
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
