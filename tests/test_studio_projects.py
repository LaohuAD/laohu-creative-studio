import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio_projects import create_studio_projects_router


TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / "cache" / "studio-tests" / "tmp"


def isolated_temp_directory():
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT)


class FakeCanvasAdapter:
    """只模拟现有画布真源，不创建第二份项目数据。"""

    def __init__(self):
        self.items = {
            "canvas-old": {
                "id": "canvas-old",
                "title": "旧画布",
                "updated_at": 10,
                "revision": 2,
            }
        }
        self.next_id = 1

    def list(self):
        return [dict(item) for item in self.items.values()]

    def get(self, project_id):
        item = self.items.get(project_id)
        return dict(item) if item else None

    def create(self, name):
        project_id = f"canvas-new-{self.next_id}"
        self.next_id += 1
        item = {"id": project_id, "title": name, "updated_at": 20, "revision": 1}
        self.items[project_id] = item
        return dict(item)

    def rename(self, project_id, name, expected_revision=None):
        item = self.items[project_id]
        if expected_revision is not None and item["revision"] != expected_revision:
            raise AssertionError("adapter revision should have been checked before rename")
        item["title"] = name
        item["updated_at"] += 1
        item["revision"] += 1
        return dict(item)

    def delete(self, project_id, expected_revision=None):
        item = self.items[project_id]
        if expected_revision is not None and item["revision"] != expected_revision:
            raise AssertionError("adapter revision should have been checked before delete")
        self.items.pop(project_id)


def make_client(root, adapter=None):
    app = FastAPI()
    app.include_router(create_studio_projects_router(root, adapter or FakeCanvasAdapter()))
    return TestClient(app)


class StudioProjectsTests(unittest.TestCase):
    def test_canvas_adapter_is_the_source_and_both_modules_have_crud(self):
        with isolated_temp_directory() as folder:
            adapter = FakeCanvasAdapter()
            with make_client(folder, adapter) as client:
                response = client.get("/api/studio/projects?module=canvas")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["projects"][0]["id"], "canvas-old")
                self.assertEqual(response.json()["projects"][0]["module"], "canvas")

                created = client.post("/api/studio/projects", json={"module": "canvas", "name": "新画布"})
                self.assertEqual(created.status_code, 200)
                canvas = created.json()["project"]
                self.assertEqual(canvas["name"], "新画布")
                self.assertIn("smart-canvas.html", canvas["url"])
                self.assertFalse((Path(folder) / "data" / "studio_projects").exists())

                renamed = client.patch(
                    f"/api/studio/projects/{canvas['id']}?module=canvas",
                    json={"module": "canvas", "name": "改名画布", "revision": 1},
                )
                self.assertEqual(renamed.status_code, 200)
                self.assertEqual(renamed.json()["project"]["name"], "改名画布")

                hypit = client.post("/api/studio/projects", json={"module": "hypit", "name": "实验工程"})
                self.assertEqual(hypit.status_code, 200)
                hypit_project = hypit.json()["project"]
                self.assertEqual(hypit_project["module"], "hypit")
                self.assertTrue((Path(folder) / "workflows" / "hypit" / hypit_project["id"]).is_dir())
                self.assertTrue((Path(folder) / "data" / "studio_projects" / f"{hypit_project['id']}.json").exists())

                all_projects = client.get("/api/studio/projects")
                self.assertEqual(all_projects.status_code, 200)
                self.assertEqual({item["module"] for item in all_projects.json()["projects"]}, {"canvas", "hypit"})

    def test_connection_prompts_link_to_complete_markdown(self):
        from studio_connection import create_connection_router
        app = FastAPI()
        app.include_router(create_connection_router(lambda project_id, module: {'id':project_id,'module':module,'name':'作品'}))
        with TestClient(app) as client:
            for module in ('canvas','hypit'):
                for lang in ('zh','en'):
                    prompt = client.get(f'/api/studio/projects/sample/connection?module={module}&lang={lang}').json()
                    self.assertIn('sample', prompt['text'])
                    self.assertIn(prompt['document_url'], prompt['text'])
                    self.assertLess(len(prompt['text']), 420)
                    document = client.get(prompt['document_url'])
                    self.assertEqual(document.status_code,200)
                    self.assertIn('text/markdown',document.headers['content-type'])
                    self.assertIn('request_id',document.text)
                    if module=='hypit':self.assertIn('studio:Image',document.text)
                    prep=client.get(f'/api/studio/modules/{module}/preparation?lang={lang}').json()
                    self.assertIn(prep['document_url'],prep['text'])
                    detail=client.get(prep['document_url'])
                    self.assertEqual(detail.status_code,200)
                    if module=='hypit':
                        self.assertIn('https://github.com/LaohuAD/laohu-creative-skills.git', detail.text)
                        self.assertIn('tools/install.py', detail.text)

    def test_create_ui_stays_on_management_page(self):
        import subprocess, shutil
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is needed for the UI behavior test')
        script = Path(__file__).resolve().parents[1] / 'static/js/studio-projects.js'
        source = script.read_text()
        function = source.split('    async function createProject(){', 1)[1].split('    async function renameProject', 1)[0]
        program = """
const assert=require('node:assert/strict');
let answer='测试项目', saves=0, reloads=0, opened=0;
const module='hypit', L=(zh)=>zh, moduleText=()=>({newName:'新项目'});
const dialogPrompt=async()=>answer;
const api=async(path,options)=>{saves++;assert.equal(JSON.parse(options.body).name,'测试项目');return {project:{id:'new'}};};
const loadProjects=async()=>{reloads++;};
const openProject=()=>{opened++;};
const dialogAlert=async(message)=>{throw Error(message);};
const copy=()=>({operationFailed:'failed'});
async function createProject(){""" + function + """
(async()=>{await createProject();assert.equal(saves,1);assert.equal(reloads,1);assert.equal(opened,0);
answer=null;await createProject();assert.equal(saves,1);assert.equal(opened,0);})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        subprocess.run([node, '-e', program], check=True, capture_output=True, text=True)

    def test_hypit_opens_project_page_without_agent_connection(self):
        with isolated_temp_directory() as folder:
            with make_client(folder) as client:
                project = client.post('/api/studio/projects', json={'module':'hypit', 'name':'未接入项目'}).json()['project']
                expected = '/static/hypit.html?id=' + project['id']
                self.assertEqual(project['url'], expected)
                listed = client.get('/api/studio/projects?module=hypit').json()['projects']
                self.assertEqual(listed[0]['url'], expected)
                loaded = client.get('/api/studio/projects/'+project['id']+'?module=hypit').json()['project']
                self.assertEqual(loaded['url'], expected)

    def test_article_module_uses_shared_project_crud_and_only_creates_a_card(self):
        with isolated_temp_directory() as folder:
            with make_client(folder) as client:
                response = client.post(
                    "/api/studio/projects",
                    json={"module": "article", "name": "一篇新文章"},
                )
                self.assertEqual(response.status_code, 200, response.text)
                project = response.json()["project"]
                self.assertEqual(project["module"], "article")
                self.assertEqual(project["name"], "一篇新文章")
                self.assertEqual(project["url"], f"/static/article.html?id={project['id']}")

                record_path = Path(folder) / "data" / "studio_projects" / f"{project['id']}.json"
                self.assertTrue(record_path.is_file())
                record = json.loads(record_path.read_text(encoding="utf-8"))
                self.assertEqual(record["module"], "article")
                self.assertNotIn("canvas", record)
                self.assertFalse((Path(folder) / "workflows" / "hypit" / project["id"]).exists())

                listed = client.get("/api/studio/projects?module=article").json()["projects"]
                self.assertEqual([item["id"] for item in listed], [project["id"]])
                self.assertEqual(client.get(f"/api/studio/projects/{project['id']}?module=article").status_code, 200)

                renamed = client.patch(
                    f"/api/studio/projects/{project['id']}?module=article",
                    json={"module": "article", "name": "改名后", "revision": project["revision"]},
                )
                self.assertEqual(renamed.status_code, 200, renamed.text)
                self.assertEqual(renamed.json()["project"]["name"], "改名后")

    def test_hypit_delete_moves_project_to_backup_and_keeps_assets(self):
        with isolated_temp_directory() as folder:
            asset = Path(folder) / "assets" / "input" / "asset.txt"
            asset.parent.mkdir(parents=True)
            asset.write_text("keep me", encoding="utf-8")
            with make_client(folder) as client:
                created = client.post("/api/studio/projects", json={"module": "hypit", "name": "待归档"}).json()["project"]
                project_id = created["id"]
                workflow = Path(folder) / "workflows" / "hypit" / project_id
                (workflow / "notes.txt").write_text("工程内容", encoding="utf-8")

                response = client.delete(
                    f"/api/studio/projects/{project_id}?module=hypit&revision={created['revision']}"
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(workflow.exists())
                self.assertTrue(asset.exists())
                self.assertFalse((Path(folder) / "data" / "studio_projects" / f"{project_id}.json").exists())
                backups = list((Path(folder) / "backups" / "studio-projects" / "hypit").glob(f"{project_id}-*"))
                self.assertEqual(len(backups), 1)
                self.assertTrue((backups[0] / "workflow" / "notes.txt").exists())
                self.assertTrue((backups[0] / "project.json").exists())

    def test_path_validation_corrupt_record_and_revision_conflict(self):
        with isolated_temp_directory() as folder:
            with make_client(folder) as client:
                created = client.post("/api/studio/projects", json={"module": "hypit", "name": "并发工程"}).json()["project"]
                project_id = created["id"]
                conflict = client.patch(
                    f"/api/studio/projects/{project_id}?module=hypit",
                    json={"module": "hypit", "name": "不应覆盖", "revision": 99},
                )
                self.assertEqual(conflict.status_code, 409)
                stored = json.loads((Path(folder) / "data" / "studio_projects" / f"{project_id}.json").read_text(encoding="utf-8"))
                self.assertEqual(stored["name"], "并发工程")

                invalid = client.get("/api/studio/projects/not.valid?module=hypit")
                self.assertEqual(invalid.status_code, 400)

                record_path = Path(folder) / "data" / "studio_projects" / f"{project_id}.json"
                original = record_path.read_bytes()
                record_path.write_bytes(b"{broken json")
                broken = client.get(f"/api/studio/projects/{project_id}?module=hypit")
                self.assertEqual(broken.status_code, 500)
                self.assertEqual(record_path.read_bytes(), b"{broken json")
                self.assertNotEqual(original, record_path.read_bytes())

    def test_writes_reject_cross_site_origin(self):
        with isolated_temp_directory() as folder:
            with make_client(folder) as client:
                response = client.post(
                    "/api/studio/projects",
                    headers={"Origin": "https://external.example"},
                    json={"module": "hypit", "name": "不应写入"},
                )
                self.assertEqual(response.status_code, 403)
                self.assertFalse((Path(folder) / "data" / "studio_projects").exists())


if __name__ == "__main__":
    unittest.main()
