import io
import json
import os
import unittest
from unittest.mock import patch
import profile_service as service
from game_protocol import signed_headers, GameReadError


class ProfileTests(unittest.TestCase):
    def call(self,path,origin='https://monkuso.github.io',method='GET'):
        result={}
        def start(status,headers):
            result['status']=status
            result['headers']=dict(headers)
        body=b''.join(service.app({'PATH_INFO':path,'REQUEST_METHOD':method,'HTTP_ORIGIN':origin,'REMOTE_ADDR':'test','wsgi.input':io.BytesIO()},start))
        return result,json.loads(body)

    def test_only_public_fields_are_returned(self):
        user={'name':'公開名','invitation_id':551682879769,'rank':1010,'id':91,'session':'private',
              'charball':{'char_id':11594,'level':120,'id':992,'user_id':91,'created_at':100},
              'attribute_helper_user_charballs':[],'played_at':1,'cnt_of_login':100,'inventory':['private']}
        data=service.public_profile(user,'551682879769')
        self.assertEqual(data['characters'][0]['id'],11594)
        text=json.dumps(data)
        for field in ['private','session','user_id','inventory','cnt_of_login','created_at']:
            self.assertNotIn(field,text)

    def test_wrong_identity_is_not_returned(self):
        with self.assertRaises(LookupError):service.public_profile({'invitation_id':123456789},'551682879769')

    def test_validation_blocks_paths_and_all_zero_ids(self):
        for value in ['0'*12,'123','123456789/../../','１２３４５６７８９']:
            with self.assertRaises(ValueError):service.normalize_id(value)
        result,_=self.call('/api/profiles/123?secret=1')
        self.assertEqual(result['status'],'400 Bad Request')

    def test_origin_and_mutating_methods_rejected(self):
        result,_=self.call('/health',origin='https://example.com')
        self.assertEqual(result['status'],'403 Forbidden')
        result,_=self.call('/api/profiles/551682879769',method='POST')
        self.assertEqual(result['status'],'405 Method Not Allowed')

    def test_cors_does_not_forward_secrets(self):
        with patch.dict(os.environ,{'MS_PROFILE_CONFIG':'secret'}):
            result,data=self.call('/health')
        self.assertTrue(data['configured'])
        self.assertEqual(result['headers']['Access-Control-Allow-Origin'],'https://monkuso.github.io')
        self.assertNotIn('secret',json.dumps(data))

    def test_cache_preserves_verification_time_and_avoids_second_read(self):
        service.CACHE.clear()
        user={'name':'公開名','invitation_id':551682879769,'rank':100,'charball':{},'attribute_helper_user_charballs':[]}
        with patch.dict(os.environ,{'MS_PROFILE_CONFIG':'{}'}),patch.object(service,'read_game',return_value={'user':user}) as read:
            first=service.lookup('551682879769')
            second=service.lookup('551682879769')
        self.assertEqual(first['fetchedAt'],second['fetchedAt'])
        self.assertEqual(read.call_count,1)

    def test_signer_rejects_nonread_routes(self):
        for route in ['/gacha/draw','https://example.com/user/get','/user/get#fragment']:
            with self.assertRaises(ValueError):signed_headers({},route)

    def test_verified_missing_user_code_is_a_not_found_result(self):
        service.CACHE.clear()
        with patch.dict(os.environ,{'MS_PROFILE_CONFIG':'{}'}),patch.object(service,'read_game',side_effect=GameReadError(6)):
            with self.assertRaises(LookupError):service.lookup('999999999999')


if __name__=='__main__':unittest.main()
