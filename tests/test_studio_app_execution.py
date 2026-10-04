import asyncio
import copy
import unittest
from threading import RLock

from studio_app_execution import StudioAppExecution
from studio_execution import input_media, request_for


class Store:
    def __init__(self):
        self.tasks = {}

    def get_canvas_task(self, key):
        return copy.deepcopy(self.tasks.get(key))

    def create_canvas_task(self, task):
        self.tasks[task['id']] = copy.deepcopy(task)

    def update_canvas_task(self, key, **changes):
        self.tasks[key].update(copy.deepcopy(changes))


def app_fields():
    return [
        {'nodeId': '1', 'fieldName': 'prompt', 'fieldType': 'TEXT', 'inputRole': 'prompt', 'required': True, 'schemaOrder': 0},
        {'nodeId': '2', 'fieldName': 'image', 'fieldType': 'IMAGE', 'required': True, 'schemaOrder': 1},
        {'nodeId': '3', 'fieldName': 'strength', 'fieldType': 'NUMBER', 'required': True, 'schemaOrder': 2},
    ]


def comfy_fields():
    return [
        {'id': 'prompt-field', 'node': '10', 'input': 'text', 'type': 'textarea', 'default': ''},
        {'id': 'image-field', 'node': '20', 'input': 'image', 'type': 'image'},
        {'id': 'steps-field', 'node': '30', 'input': 'steps', 'type': 'number', 'default': 20, 'step': 1},
    ]


class RequestProjectionTests(unittest.TestCase):
    def test_runninghub_region_is_preserved_for_regular_model_requests(self):
        canvas = {
            'id': 'project',
            'nodes': [{
                'id': 'run', 'type': 'smart-image-generator', 'promptDraftText': '一只猫',
                'runSettings': {
                    'provider_id': 'runninghub', 'model': 'cn-model', 'region': 'cn',
                },
            }],
            'connections': [],
        }

        request = request_for(canvas, canvas['nodes'][0])

        self.assertEqual(request['region'], 'cn')

    def test_runninghub_app_projects_prompt_bound_media_and_parameters(self):
        canvas = {
            'id': 'project',
            'nodes': [
                {'id': 'text', 'images': [{'kind': 'text', 'text': '来自文本素材'}]},
                {'id': 'image', 'images': [{'kind': 'image', 'url': '/api/results/ref', 'resultId': 'ref-1'}]},
                {'id': 'run', 'type': 'smart-ai-app', 'promptDraftText': '画一个人', 'runSettings': {
                    'engine': 'runninghub', 'rhConfigKey': 'app:app-1', 'rhFields': app_fields(),
                    'rhParams': {'3::strength': {'value': '0.75'}},
                    'rhInputBindings': {'2::image': 'result:ref-1'},
                }, 'images': []},
            ],
            'connections': [
                {'from': 'text', 'to': 'run', 'kind': 'story'},
                {'from': 'image', 'to': 'run', 'kind': 'input', 'targetFieldKey': '2::image', 'sourceMediaKey': 'result:ref-1'},
            ],
        }

        request = request_for(canvas, canvas['nodes'][2])

        self.assertEqual(request['kind'], 'ai_application')
        self.assertEqual(request['app_id'], 'app-1')
        self.assertEqual(request['app_field_values'], {
            '1::prompt': '画一个人',
            '2::image': '/api/results/ref',
            '3::strength': 0.75,
        })
        self.assertEqual(request['inputs']['2::image'], '/api/results/ref')
        self.assertEqual(request['inputs']['1::prompt'], '画一个人')
        self.assertEqual(input_media(canvas, canvas['nodes'][2])[0]['url'], '/api/results/ref')

    def test_local_comfy_projects_schema_fields_into_generate_params(self):
        canvas = {
            'id': 'project',
            'nodes': [
                {'id': 'source', 'images': [{'kind': 'image', 'url': '/assets/ref.png', 'comfy_name': 'ref.png'}]},
                {'id': 'run', 'type': 'smart-comfy-workflow', 'promptDraftText': '一个红色房间', 'runSettings': {
                    'engine': 'comfy', 'comfyMode': 'custom', 'comfyWorkflow': 'custom/room.json',
                    'comfyFields': comfy_fields(), 'comfyParams': {'steps-field': 28},
                }},
            ],
            'connections': [{'from': 'source', 'to': 'run', 'kind': 'input'}],
        }

        request = request_for(canvas, canvas['nodes'][1])

        self.assertEqual(request['kind'], 'comfy')
        self.assertEqual(request['workflow_json'], 'custom/room.json')
        self.assertEqual(request['params'], {
            '10': {'text': '一个红色房间'},
            '20': {'image': 'ref.png'},
            '30': {'steps': 28},
        })

    def test_runninghub_workflow_projects_own_schema(self):
        canvas = {
            'id': 'project',
            'nodes': [
                {'id': 'source', 'images': [{'kind': 'image', 'url': '/assets/ref.png', 'resultId': 'ref-1'}]},
                {'id': 'run', 'type': 'smart-ai-app', 'promptDraftText': '工作流提示', 'runSettings': {
                    'engine': 'runninghub', 'rhMode': 'workflow', 'rhConfigKey': 'workflow:wf-1',
                    'rhWorkflowId': 'wf-1', 'rhFields': app_fields(),
                    'rhParams': {'3::strength': {'value': '0.25'}},
                    'rhWorkflowJson': {
                        '1': {'inputs': {'prompt': '旧提示'}},
                        '2': {'inputs': {'image': '旧图片'}},
                        '3': {'inputs': {'strength': 0}},
                    },
                }},
            ],
            'connections': [{'from': 'source', 'to': 'run', 'kind': 'input',
                             'targetFieldKey': '2::image', 'sourceMediaKey': 'result:ref-1'}],
        }

        request = request_for(canvas, canvas['nodes'][1])

        self.assertEqual(request['kind'], 'runninghub_workflow')
        self.assertEqual(request['workflow_id'], 'wf-1')
        self.assertEqual(request['node_info_list'], [
            {'nodeId': '1', 'fieldName': 'prompt', 'fieldValue': '工作流提示'},
            {'nodeId': '2', 'fieldName': 'image', 'fieldValue': '/assets/ref.png'},
            {'nodeId': '3', 'fieldName': 'strength', 'fieldValue': 0.25},
        ])


class AppExecutionTests(unittest.IsolatedAsyncioTestCase):
    def _canvas(self):
        return {
            'id': 'project',
            'nodes': [
                {'id': 'source', 'images': [{'kind': 'image', 'url': '/api/results/ref', 'resultId': 'ref-1'}]},
                {
                'id': 'run', 'type': 'smart-ai-app', 'title': '应用', 'promptDraftText': '测试提示',
                'runSettings': {
                    'engine': 'runninghub', 'rhConfigKey': 'app:app-1', 'rhFields': app_fields(),
                    'rhParams': {'3::strength': {'value': 0.5}},
                }, 'images': [],
                },
            ],
            'connections': [{'from': 'source', 'to': 'run', 'kind': 'input', 'targetFieldKey': '2::image'}],
        }

    async def _service(self, *, submit=None, query=None, local=None, collect=None, preflight=None, poll_interval=0):
        self.canvas = self._canvas()
        self.store = Store()
        self.submissions = []
        self.queries = []

        async def fake_preflight(canvas, node, request, request_id):
            return await preflight(canvas, node, request, request_id) if preflight else {'run_id': 'run-1'}

        async def fake_submit(request):
            self.submissions.append(copy.deepcopy(request))
            return await submit(request) if submit else {'success': True, 'data': {'taskId': 'rh-1'}}

        async def fake_query(task_id, context):
            self.queries.append((task_id, copy.deepcopy(context)))
            return await query(task_id, context) if query else {'status': 'SUCCESS', 'urls': ['/api/results/out']}

        async def fake_local(request):
            return await local(request) if local else {'outputs': ['/api/results/out']}

        async def fake_collect(result, request, task):
            return await collect(result, request, task) if collect else [{'kind': 'image', 'url': '/api/results/out'}]

        async def notify(_canvas):
            pass

        return StudioAppExecution(
            load_canvas=lambda _canvas_id: copy.deepcopy(self.canvas),
            save_canvas=self._save,
            lock=RLock(),
            storage=self.store,
            preflight=fake_preflight,
            runninghub_submit=fake_submit,
            runninghub_query=fake_query,
            local_comfy_generate=fake_local,
            collect=fake_collect,
            notify=notify,
            poll_interval=poll_interval,
            max_polls=5,
        )

    def _save(self, canvas):
        self.canvas = copy.deepcopy(canvas)

    async def test_runninghub_submit_queries_once_per_task_and_saves_result(self):
        states = iter([{'status': 'RUNNING'}, {'status': 'SUCCESS', 'urls': ['/api/results/out']}])
        service = await self._service(query=lambda _task_id, _context: asyncio.sleep(0, result=next(states)))

        result = await service.submit(self.canvas, self.canvas['nodes'][1], 'request-1')
        await asyncio.gather(*list(service.handles.values()))

        task = self.store.get_canvas_task(result['task_ids'][0])
        self.assertEqual(len(self.submissions), 1)
        self.assertEqual(len(self.queries), 2)
        self.assertEqual(task['status'], 'succeeded')
        self.assertEqual(self.canvas['nodes'][1]['images'][0]['url'], '/api/results/out')
        self.assertEqual(task['result']['media'][0]['kind'], 'image')

    async def test_runninghub_workflow_applies_node_values_to_workflow_before_submit(self):
        service = await self._service()
        node = self.canvas['nodes'][1]
        workflow_json = {
            '1': {'inputs': {'prompt': '旧提示'}},
            '2': {'inputs': {'image': '旧图片'}},
            '3': {'inputs': {'strength': 0}},
        }
        node['runSettings'].update({
            'rhMode': 'workflow',
            'rhConfigKey': 'workflow:wf-1',
            'rhWorkflowId': 'wf-1',
        })
        service.resolve_runninghub_fields = lambda *_: {
            'fields': app_fields(), 'workflowJson': workflow_json,
        }
        result = await service.submit(self.canvas, node, 'request-workflow')
        await asyncio.gather(*list(service.handles.values()))

        submitted = self.submissions[0]
        workflow = submitted['platform_request']['workflow']
        self.assertEqual(workflow['1']['inputs']['prompt'], '测试提示')
        self.assertEqual(workflow['2']['inputs']['image'], '/api/results/ref')
        self.assertEqual(workflow['3']['inputs']['strength'], 0.5)
        self.assertEqual(self.store.get_canvas_task(result['task_ids'][0])['status'], 'succeeded')

    async def test_local_comfy_uses_projected_params_and_saves_result(self):
        captured = {}

        def local(request):
            captured.update(copy.deepcopy(request))
            return {'outputs': ['/api/results/local']}

        service = await self._service()
        service.local_comfy_generate = local
        self.canvas['nodes'] = [{
            'id': 'run', 'type': 'smart-comfy-workflow', 'title': '本地', 'promptDraftText': '房间',
            'runSettings': {'engine': 'comfy', 'comfyMode': 'custom', 'comfyWorkflow': 'custom/room.json',
                            'comfyFields': comfy_fields(), 'comfyParams': {'steps-field': 24}}, 'images': [],
        }]
        self.canvas['connections'] = []
        result = await service.submit(self.canvas, self.canvas['nodes'][0], 'request-comfy')
        await asyncio.gather(*list(service.handles.values()))

        self.assertEqual(captured['params']['10']['text'], '房间')
        self.assertEqual(captured['params']['30']['steps'], 24)
        self.assertEqual(self.store.get_canvas_task(result['task_ids'][0])['status'], 'succeeded')

    async def test_cancelled_runninghub_wait_does_not_resubmit(self):
        gate = asyncio.Event()

        async def query(_task_id, _context):
            await gate.wait()
            return {'status': 'RUNNING'}

        service = await self._service(query=query)
        result = await service.submit(self.canvas, self.canvas['nodes'][1], 'request-cancel')
        await asyncio.sleep(0)
        cancelled = await service.cancel(self.canvas, self.canvas['nodes'][1], result['task_ids'][0])

        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(len(self.submissions), 1)
        self.assertFalse(service.handles)

    async def test_query_failure_marks_failed_without_resubmitting(self):
        async def query(_task_id, _context):
            return {'status': 'FAILED', 'failReason': 'fixture failed'}

        service = await self._service(query=query)
        result = await service.submit(self.canvas, self.canvas['nodes'][1], 'request-failed')
        await asyncio.gather(*list(service.handles.values()))

        task = self.store.get_canvas_task(result['task_ids'][0])
        self.assertEqual(task['status'], 'failed')
        self.assertIn('fixture failed', task['error'])
        self.assertTrue(task['result']['creation_snapshot'].get('providerTaskId'))
        self.assertEqual(len(self.submissions), 1)


if __name__ == '__main__':
    unittest.main()
