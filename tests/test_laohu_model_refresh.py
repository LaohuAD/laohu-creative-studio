"""2026-11 laohu contracts: no live or paid provider requests."""
import unittest
from unittest.mock import patch, AsyncMock
import main
from model_capabilities import ai_money_profile_from_model_id, ModelCapabilityError


class LaohuModelRefreshTests(unittest.TestCase):
    def test_image_profiles_have_model_specific_fields(self):
        for model,refs in [('flux-3-image-i2i',10),('krea-v3-i2i',8),('laohu-image-muse',9),('laohu-image-hy-v3.5-preview',5),('moss-image',1)]:
            with self.subTest(model=model):
                profile=ai_money_profile_from_model_id(model,'image_generation')
                self.assertEqual(profile['inputs']['reference']['max'],refs)
                self.assertEqual(profile['platform']['endpoint'],'/v1/image/generations')
        low=ai_money_profile_from_model_id('laohu-image-g-v2.6-lowprice','image_generation')
        self.assertEqual(low['parameters']['resolution']['options'],['1k'])
        self.assertNotIn('output_format',low['parameters'])

    def test_muse_and_motion_use_native_body_not_seconds(self):
        for model in ('laohu-video-muse','laohu/motion-video'):
            body=main.ai_money_video_request_body(model,'animate',10,capability_parameters={'duration':10,'resolution':'720p'})
            self.assertNotIn('seconds',body)
            self.assertEqual(body['duration'],10)

    def test_kling4_preserves_ordered_reference_fields(self):
        body=main.ai_money_video_request_body('kling-v4-omni','scene',6,image_urls=['a','b'],video_urls=['v'],capability_parameters={'metadata':{'elementIds':['e']}})
        self.assertEqual(body['image_urls'],['a','b'])
        self.assertEqual(body['video_urls'],['v'])
        self.assertNotIn('images',body)
        self.assertNotIn('generate_audio',body.get('metadata',{}))

    def test_doubao2_keeps_metadata_zero_false_and_public_model_id(self):
        body=main.ai_money_audio_request_body('doubao-seed-tts-2.0','hello',capability_parameters={'metadata':{'speaker':'voice','speech_rate':0,'disable_markdown_filter':False}})
        self.assertEqual(body['model'],'doubao-seed-tts-2.0')
        self.assertIs(body['metadata']['disable_markdown_filter'],False)
        self.assertEqual(body['metadata']['speech_rate'],0)

    def test_text_image_support_and_unconfirmed_aliases(self):
        for model in ('laohu-op-5.5','laohu/gm-4-argon','deepseek/deepseek-v4.1-flash'):
            profile=ai_money_profile_from_model_id(model,'text_generation')
            self.assertIn('reference',profile['inputs'])
        for model in ('laohu-hk-5.5','laohu-sn-5.5'):
            profile=ai_money_profile_from_model_id(model,'text_generation')
            self.assertFalse(profile.get('runnable',True))

class LaohuVideoTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_muse_submit_and_poll_share_documented_endpoint(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        client=MagicMock();client.post=AsyncMock()
        response=MagicMock();response.json.return_value={'data':{'id':'test-task','status':'PENDING'}};client.post.return_value=response
        context=MagicMock();context.__aenter__=AsyncMock(return_value=client);context.__aexit__=AsyncMock(return_value=False)
        poll=AsyncMock(return_value={'data':{'status':'SUCCESS','result_url':'https://example.com/result.mp4'}})
        payload=SimpleNamespace(model='laohu-video-muse',prompt='animate',duration=10,images=[],videos=[],audios=[],aspect_ratio='',resolution='',generate_audio=False,return_last_frame=False,seed=None)
        with patch.object(main.httpx,'AsyncClient',return_value=context),patch.object(main,'api_headers',return_value={}),patch.object(main,'wait_for_video_task',poll),patch.object(main,'save_remote_video_to_output',AsyncMock(return_value='/api/results/test')):
            result=await main.generate_ai_money_video(payload,{'id':'ai-money','base_url':'https://api.lao-hu.com'}, {'duration':10,'resolution':'720p'})
        self.assertEqual(client.post.call_args.args[0],'https://api.lao-hu.com/v1/video/generations')
        self.assertEqual(poll.call_args.args[-1],'https://api.lao-hu.com/v1/video/generations')
        self.assertEqual(result['videos'],['/api/results/test'])

class LaohuValidationRefreshTests(unittest.TestCase):
    def test_zero_false_and_cross_field_rejections(self):
        from laohu_protocols import validate_parameters
        validate_parameters('mai-image-2-6', {'width':1536,'height':1024,'web_grounding':False})
        for model,params,counts in [
            ('mai-image-2-6',{'width':1536},{}),
            ('laohu-image-hy-v3.5-preview',{'width':8192,'height':8192},{}),
            ('krea-v3-i2i',{'size':'40*50'},{}),
            ('kling-v4-custom-element',{'reference_type':'image_refer'},{'image':1}),
        ]:
            with self.subTest(model=model), self.assertRaises(ValueError):
                validate_parameters(model,params,counts)

    def test_muse_total_input_bytes_are_enforced(self):
        from model_capabilities import ModelCapabilityRegistry, ModelCapabilityError
        profile=ai_money_profile_from_model_id('laohu-image-muse','image_generation')
        with self.assertRaises(ModelCapabilityError):
            ModelCapabilityRegistry.validate_input_metadata(profile,{'reference':[{'bytes':6*1024*1024},{'bytes':6*1024*1024}]})

    def test_kling_special_operations_do_not_claim_video_results(self):
        for mid in ['kling-v4-custom-voice','kling-v4-custom-element','kling-lip-sync-identify-face','kling-elements-advanced']:
            profile=ai_money_profile_from_model_id(mid,'text_generation')
            self.assertEqual(profile['output']['media_type'],'text')
            self.assertEqual(main.classify_upstream_model(mid),'chat')
        self.assertEqual(main.classify_upstream_model('Topaz-Upscale-LowPirce'),'video')

    def test_new_model_catalog_is_complete_and_keeps_pending_items(self):
        import json
        from pathlib import Path
        source=json.loads((Path(main.BASE_DIR)/'data/model_capabilities/snapshots/ai-money-catalog.json').read_text())
        self.assertEqual(len({r['id'] for r in source['source_models']}),321)
        self.assertIn('laohu-sn-5.5',source['unclassified_models'])
        self.assertNotIn('laohu-sn-5.5',source['image_models'])
        self.assertIn('laohu-image-g-v2.6-lowprice',source['image_models'])

class LaohuCatalogPersistenceTests(unittest.TestCase):
    def test_refresh_retains_raw_identities_without_secret_fields(self):
        import tempfile,json
        from pathlib import Path
        from model_capabilities import save_provider_catalog_snapshot
        root=Path(main.BASE_DIR)/'.cache/tmp/laohu-model-update';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            path=save_provider_catalog_snapshot(Path(folder),'ai-money',{'chat_models':['one'],'source_models':[{'id':'one','supported_endpoint_types':['openai'],'api_key':'must-not-save'}]})
            first=json.loads(path.read_text());self.assertNotIn('api_key',first['source_models'][0])
            save_provider_catalog_snapshot(Path(folder),'ai-money',{'chat_models':['one']})
            second=json.loads(path.read_text());self.assertEqual(first['source_models'],second['source_models'])

class LaohuTextToolEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_face_identification_accepts_media_only_and_returns_text(self):
        provider={'id':'ai-money','name':'laohu','base_url':'https://api.lao-hu.com','enabled':True,'chat_models':['kling-lip-sync-identify-face'],'image_models':[],'video_models':[],'audio_models':[]}
        payload=main.CanvasLLMRequest(provider='ai-money',model='kling-lip-sync-identify-face',message='',videos=['https://example.com/video.mp4'])
        with patch.object(main,'get_api_provider',return_value=provider),patch.object(main,'load_api_providers',return_value=[provider]),patch.object(main,'generate_ai_money_special_text',AsyncMock(return_value={'text':'{"faces": []}'})) as submit:
            result=await main.canvas_llm(payload)
        self.assertIn('faces',result['text'])
        self.assertEqual(submit.call_args.args[2]['operation'],'asset_creation')
