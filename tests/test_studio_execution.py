import asyncio
import copy
import unittest
from threading import RLock

from studio_execution import StudioExecution, input_media, request_for


class Store:
    def __init__(self):
        self.tasks = {}
    def get_canvas_task(self, key):
        return copy.deepcopy(self.tasks.get(key))
    def create_canvas_task(self, task):
        self.tasks[task['id']] = copy.deepcopy(task)
    def update_canvas_task(self, key, **changes):
        self.tasks[key].update(copy.deepcopy(changes))


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.canvas = {'id': 'project', 'nodes': [{'id': 'a', 'type': 'smart-image-generator',
                       'title': '人物', 'promptDraftText': 'portrait', 'creationId': 'shared',
                       'creationOwnerNodeId': 'a', 'runSettings': {'provider_id': 'fake', 'model': 'm'}}], 'connections': []}
        self.store = Store()
        self.calls = 0
        self.gate = asyncio.Event()
        async def preflight(*args):
            return {'run_id': 'run'}
        async def generate(request):
            self.calls += 1
            await self.gate.wait()
            return {'images': ['/api/results/result']}
        async def collect(*args):
            return [{'kind': 'image', 'url': '/api/results/result'}]
        async def notify(*args):
            pass
        self.service = StudioExecution(load_canvas=lambda _: copy.deepcopy(self.canvas), save_canvas=self.save,
            lock=RLock(), storage=self.store, preflight=preflight, generate=generate, collect=collect, notify=notify)

    def save(self, canvas):
        self.canvas = copy.deepcopy(canvas)

    async def finish(self):
        self.gate.set()
        await asyncio.gather(*list(self.service.handles.values()))

    async def test_shared_results_publish_and_replay_never_resubmits(self):
        self.canvas['nodes'].append({**copy.deepcopy(self.canvas['nodes'][0]), 'id': 'b'})
        result = await self.service.submit(self.canvas, self.canvas['nodes'][0], 'one')
        repeat = await self.service.submit(self.canvas, self.canvas['nodes'][0], 'one')
        self.assertEqual(result['task_ids'], repeat['task_ids'])
        await self.finish()
        self.assertEqual(self.calls, 1)
        for node in self.canvas['nodes']:
            self.assertEqual(node['images'][0]['url'], '/api/results/result')
            self.assertEqual(len(node['resultVersions']), 1)

    async def test_task_metadata_callback_is_persisted_server_side(self):
        self.service.task_metadata = lambda canvas, node, request: {
            'hypit_source_node_id': node['id'],
            'hypit_source_recipe_fingerprint': 'a' * 64,
            'hypit_supported_output_slots': ['image'],
        }
        result = await self.service.submit(self.canvas, self.canvas['nodes'][0], 'metadata')
        task = self.store.get_canvas_task(result['task_ids'][0])
        self.assertEqual(task['hypit_source_node_id'], 'a')
        self.assertEqual(task['hypit_source_recipe_fingerprint'], 'a' * 64)
        self.assertEqual(task['hypit_supported_output_slots'], ['image'])
        await self.finish()

    async def test_copy_run_forks_and_edit_during_run_keeps_new_recipe(self):
        self.canvas['nodes'].append({**copy.deepcopy(self.canvas['nodes'][0]), 'id': 'b'})
        await self.service.submit(self.canvas, self.canvas['nodes'][1], 'two')
        self.assertNotEqual(self.canvas['nodes'][1]['creationId'], 'shared')
        self.canvas['nodes'][1]['promptDraftText'] = 'new prompt'
        await self.finish()
        self.assertNotIn('images', self.canvas['nodes'][0])
        self.assertNotIn('images', self.canvas['nodes'][1])
        self.assertEqual(self.canvas['nodes'][1]['creationTasks'][0]['runStatus'], 'succeeded')

    async def test_cancel_is_scoped_and_not_replayed(self):
        result = await self.service.submit(self.canvas, self.canvas['nodes'][0], 'three')
        await asyncio.sleep(0)
        with self.assertRaises(ValueError):
            await self.service.cancel({'id': 'other'}, self.canvas['nodes'][0], result['task_ids'][0])
        await self.service.cancel(self.canvas, self.canvas['nodes'][0], result['task_ids'][0])
        self.assertEqual(self.store.tasks[result['task_ids'][0]]['status'], 'cancelled')
        self.assertFalse(self.service.handles)

    def test_story_is_not_input_and_manual_references_are_supported(self):
        self.canvas['nodes'].append({'id': 'script', 'images': [{'kind': 'text', 'text': 'excluded'}]})
        self.canvas['connections'] = [{'from': 'script', 'to': 'a', 'kind': 'story'}]
        node = self.canvas['nodes'][0]
        node['manualInputRefs'] = [{'kind': 'image', 'url': '/api/results/reference'}]
        self.assertEqual(len(input_media(self.canvas, node)), 1)
        request = request_for(self.canvas, node)
        self.assertEqual(request['prompt'], 'portrait')
        self.assertEqual(request['inputs']['reference'], ['/api/results/reference'])

    def test_source_media_key_selects_stable_result_reference(self):
        self.canvas['nodes'].append({
            'id': 'source',
            'images': [
                {'kind': 'image', 'url': '/api/results/one', 'resultId': 'result-one'},
                {'kind': 'image', 'url': '/api/results/two', 'resultId': 'result-two'},
            ],
        })
        self.canvas['connections'] = [{
            'from': 'source',
            'to': 'a',
            'kind': 'input',
            'sourceMediaKey': 'result:result-two',
        }]

        refs = input_media(self.canvas, self.canvas['nodes'][0])

        self.assertEqual([item['url'] for item in refs], ['/api/results/two'])


if __name__ == '__main__':
    unittest.main()
