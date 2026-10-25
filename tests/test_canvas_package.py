import io
import json
import tempfile
import unittest
import zipfile
import copy
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException, UploadFile
import main
from project_storage import ProjectStorage


class CanvasPackageTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_import_receipt_maps_fail_closed(self):
        with self.assertRaises(HTTPException) as stored:
            main.canvas_script_imports_for_user_save({"schema_version": 1, "snapshots": [], "requests": {}}, {})
        self.assertEqual(stored.exception.status_code, 500)
        with self.assertRaises(HTTPException) as incoming:
            main.canvas_script_imports_for_user_save({}, {"schema_version": 1, "snapshots": [], "advisorySnapshots": {}})
        self.assertEqual(incoming.exception.status_code, 422)

    async def test_canvas_save_persists_import_provenance_and_older_clients_preserve_it(self):
        canvas_id = "canvas_script_provenance"
        trusted_request = {"server_trusted": True, "fingerprint": "trusted-fingerprint",
                           "receipt": {"request_id": "trusted-request", "status": "succeeded"}}
        trusted_snapshot = {"server_trusted": True, "source_project_id": "trusted-script",
                            "episodes": [{"source_episode_id": "trusted-episode", "segments": []}]}
        state = {"id": canvas_id, "kind": "smart", "revision": 4, "updated_at": 400,
                 "title": "Script canvas", "icon": "layers", "nodes": [], "connections": [],
                 "viewport": {"x": 0, "y": 0, "scale": 1}, "logs": [], "settings": {},
                 "scriptImports": {"schema_version": 1, "requests": {"trusted-request": trusted_request},
                                   "snapshots": {"trusted-import": trusted_snapshot}, "advisorySnapshots": {}}}
        imports = {"schema_version": 1, "requests": {"trusted-request": {"server_trusted": True,
                     "fingerprint": "forged", "receipt": {"status": "succeeded", "added_count": 999}},
                     "forged-request": {"server_trusted": True, "fingerprint": "fake",
                     "receipt": {"status": "succeeded", "added_count": 999}}}, "snapshots": {"import-1": {
            "import_id": "import-1", "source_project_id": "script-1", "source_revision": 9,
            "episodes": [{"source_node_id": "episode-node", "segments": [
                {"node_id": "segment-node", "source_segment_id": "segment-1", "content_sha256": "a" * 64}
            ]}],
        }}, "advisorySnapshots": {}, "untrustedIgnored": "unexpected"}
        imports["snapshots"]["trusted-import"] = {"server_trusted": True, "source_project_id": "attacker",
                                                     "episodes": [{"source_episode_id": "fake"}]}

        def load(_canvas_id):
            return copy.deepcopy(state)

        def save(canvas):
            canvas["revision"] = int(state["revision"]) + 1
            canvas["updated_at"] = int(state["updated_at"]) + 1
            state.clear()
            state.update(copy.deepcopy(canvas))

        with patch.object(main, "studio_settings_canvas_service", return_value=None), \
                patch.object(main, "load_canvas", side_effect=load), \
                patch.object(main, "save_canvas", side_effect=save), \
                patch.object(main, "sync_canvas_result_origins"), \
                patch.object(main.manager, "broadcast_canvas_updated", new_callable=AsyncMock):
            saved = await main.update_canvas(canvas_id, main.CanvasSaveRequest(
                title="Script canvas", icon="layers", nodes=[], connections=[],
                script_imports=imports, base_revision=4,
            ))
            saved_imports = saved["canvas"]["scriptImports"]
            self.assertEqual(saved_imports["requests"], {"trusted-request": trusted_request})
            self.assertEqual(saved_imports["snapshots"], {"trusted-import": trusted_snapshot})
            self.assertNotIn("forged-request", saved_imports["requests"])
            self.assertNotIn("attacker", json.dumps(saved_imports["snapshots"], ensure_ascii=False))
            self.assertTrue(saved_imports["advisorySnapshots"])
            self.assertTrue(all(value.get("server_trusted") is not True
                                for value in saved_imports["advisorySnapshots"].values()))
            self.assertEqual(saved["canvas"]["revision"], 5)

            # Older clients that do not know this optional field must not wipe it.
            saved_again = await main.update_canvas(canvas_id, main.CanvasSaveRequest(
                title="Script canvas", icon="layers", nodes=[], connections=[], base_revision=5,
            ))
        self.assertEqual(saved_again["canvas"]["scriptImports"], saved_imports)
        self.assertEqual(saved_again["canvas"]["revision"], 6)

        openapi = main.app.openapi()
        request_schema = openapi["paths"]["/api/canvases/{canvas_id}"]["put"]["requestBody"]["content"]["application/json"]["schema"]
        canvas_schema = openapi["components"]["schemas"][request_schema["$ref"].rsplit("/", 1)[-1]]
        self.assertIn("script_imports", canvas_schema["properties"])

    async def test_roundtrip_names_media_history_settings_and_dedup(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source=ProjectStorage(source_dir);source.ensure_layout()
            material=source.store_material_bytes(b'input picture','角色.png','temporary')
            path=Path(source_dir)/'音乐.wav';path.write_bytes(b'music output')
            result=source.store_result_file(path,'音乐.wav');source.update_result_metadata(result['id'],media_category='music')
            old_input=source.material_url(material['id']);old_result=source.result_url(result['id'])
            nodes=[{'id':'a','type':'smart-material','images':[{'url':old_input,'name':'角色.png'}]}, {'id':'b','type':'smart-material','sourceKind':'result','images':[{'url':old_result,'name':'音乐.wav'}],'resultVersions':[{'images':[{'url':old_result}],'runInputRefs':[{'url':old_input,'nodeId':'a'}]}],'promptDraftHtml':f'<span data-url="{old_input}">参考</span>'}]
            payload=main.CanvasWorkflowExportRequest(nodes=nodes,connections=[{'from':'a','to':'b'}],settings={'api_key':'not-exported','agentDefaults':{'image':{'model':'test'}}})
            with patch.object(main,'PROJECT_STORAGE',source):
                data,meta=main.build_canvas_workflow_archive(payload)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertIn('resources/角色.png',archive.namelist())
                self.assertIn('resources/音乐.wav',archive.namelist())
                self.assertNotIn('not-exported',archive.read('workflow.json').decode())
                self.assertEqual(len(meta['resources']),2)
            target=ProjectStorage(target_dir);target.ensure_layout()
            with patch.object(main,'PROJECT_STORAGE',target):
                imported=await main.import_canvas_workflow(UploadFile(filename='完整画布.zip',file=io.BytesIO(data)))
                again=await main.import_canvas_workflow(UploadFile(filename='完整画布.zip',file=io.BytesIO(data)))
            self.assertEqual(imported['nodes'],again['nodes'])
            self.assertEqual(len(target.list_materials()),1)
            self.assertEqual(len(target.list_results()),1)
            self.assertEqual(target.list_results()[0]['media_category'],'music')
            self.assertEqual(imported['connections'],[{'from':'a','to':'b'}])
            self.assertEqual(imported['settings']['agentDefaults']['image']['model'],'test')
            self.assertEqual(imported['nodes'][1]['resultVersions'][0]['runInputRefs'][0]['url'],imported['nodes'][0]['images'][0]['url'])

    async def test_legacy_canvas_zip_can_import(self):
        blob=io.BytesIO()
        with zipfile.ZipFile(blob,'w') as z:
            z.writestr('canvas.json',json.dumps({'nodes':[{'id':'n','images':[{'url':'/assets/old.png'}]}],'connections':[]}))
            z.writestr('resources-manifest.json',json.dumps({'resources':[{'url':'/assets/old.png','file':'resources/原图.png'}]}))
            z.writestr('resources/原图.png',b'image')
        with tempfile.TemporaryDirectory() as directory:
            storage=ProjectStorage(directory);storage.ensure_layout()
            with patch.object(main,'PROJECT_STORAGE',storage):
                imported=await main.import_canvas_workflow(UploadFile(filename='旧包.zip',file=io.BytesIO(blob.getvalue())))
            self.assertTrue(imported['nodes'][0]['images'][0]['url'].startswith('/api/materials/'))

    async def test_script_provenance_and_selected_import_snapshots_survive_workflow_zip_roundtrip(self):
        source_ref = {
            "module": "script", "projectId": "script_project_1", "projectRevision": 7,
            "importId": "script_import_1", "sourceNodeId": "source_episode_1",
            "sourceContentSha256": "a" * 64, "sourceStart": 0, "sourceEnd": 3,
        }
        imports = {"schema_version": 1, "snapshots": {"script_import_1": {
            "import_id": "script_import_1", "source_project_id": "script_project_1",
            "source_revision": 7, "episodes": [{"source_node_id": "source_episode_1",
                "segments": [{"node_id": "segment_node_1", "source_segment_id": "segment_1",
                              "content_sha256": "b" * 64}]}],
        }}}
        payload = main.CanvasWorkflowExportRequest(
            nodes=[{"id": "source_episode_1", "type": "smart-material", "sourceRef": source_ref,
                    "images": [{"kind": "text", "text": "原文"}]},
                   {"id": "segment_node_1", "type": "smart-material", "sourceRef": source_ref,
                    "production": {"role": "segment", "order": 1},
                    "images": [{"kind": "text", "text": "分段"}]}],
            connections=[{"from": "source_episode_1", "to": "segment_node_1", "kind": "story"}],
            include_resources=False, script_imports=imports,
        )
        data, _ = main.build_canvas_workflow_archive(payload)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            workflow = json.loads(archive.read("workflow.json"))
        self.assertEqual(workflow["nodes"][1]["sourceRef"], source_ref)
        portable_imports = {**imports, "advisorySnapshots": {}}
        self.assertEqual(workflow["scriptImports"], portable_imports)

        with tempfile.TemporaryDirectory() as target_dir:
            target = ProjectStorage(target_dir)
            target.ensure_layout()
            with patch.object(main, "PROJECT_STORAGE", target):
                imported = await main.import_canvas_workflow(
                    UploadFile(filename="剧本导入.zip", file=io.BytesIO(data)))
            self.assertEqual(imported["nodes"][1]["sourceRef"], source_ref)
            self.assertEqual(imported["workflow"]["scriptImports"], portable_imports)
            self.assertEqual(imported["connections"], [{"from": "source_episode_1", "to": "segment_node_1", "kind": "story"}])

    async def test_missing_or_unsafe_resources_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            storage=ProjectStorage(directory);storage.ensure_layout()
            with patch.object(main,'PROJECT_STORAGE',storage):
                with self.assertRaises(HTTPException):
                    main.build_canvas_workflow_archive(main.CanvasWorkflowExportRequest(nodes=[{'images':[{'url':'/api/results/missing'}]}]))
                for name,body in [('resources/missing.png',None),('../escape.png',b'x')]:
                    blob=io.BytesIO()
                    with zipfile.ZipFile(blob,'w') as z:
                        z.writestr('workflow.json',json.dumps({'nodes':[],'resources':[{'url':'/assets/x.png','archive':name}]}))
                        if body:z.writestr(name,body)
                    with self.assertRaises(HTTPException):
                        await main.import_canvas_workflow(UploadFile(filename='bad.zip',file=io.BytesIO(blob.getvalue())))
                self.assertEqual(storage.list_materials(),[])
