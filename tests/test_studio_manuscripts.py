from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio_manuscripts import StudioManuscriptStore, create_studio_manuscripts_router
from studio_projects import StudioProjectConflict, StudioProjectStore, create_studio_projects_router


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_ROOT = PROJECT_ROOT / ".cache" / "validation" / "studio-manuscripts"


class CanvasAdapter:
    def list(self):
        return []

    def get(self, _project_id):
        return None

    def create(self, _name):
        raise AssertionError("manuscript project creation must not create a canvas")

    def rename(self, *_args, **_kwargs):
        raise AssertionError("manuscript project rename must not touch a canvas")

    def delete(self, *_args, **_kwargs):
        raise AssertionError("manuscript project deletion must not touch a canvas")


def client_for(path: str):
    project_store = StudioProjectStore(path, CanvasAdapter())
    manuscript_store = StudioManuscriptStore(path, project_store)
    app = FastAPI()
    app.include_router(create_studio_projects_router(path, CanvasAdapter(), store=project_store))
    app.include_router(create_studio_manuscripts_router(manuscript_store))
    return TestClient(app, client=("127.0.0.1", 42000)), project_store


class StudioManuscriptStoreTests(unittest.TestCase):
    def setUp(self):
        VALIDATION_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=VALIDATION_ROOT)
        self.client, self.projects = client_for(self.tmp.name)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def create_project(self, module: str) -> dict:
        response = self.client.post("/api/studio/projects", json={"module": module, "name": "测试作品"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project"]

    def command(self, module: str, project_id: str, revision: int, request_id: str, action: str,
                args: dict, **extra):
        return self.client.post(f"/api/studio/{'scripts' if module == 'script' else 'novels'}/{project_id}/commands",
            json={"request_id": request_id, "expected_revision": revision, "action": action, "args": args, **extra})

    def test_generation_capabilities_describe_explicit_text_optimization(self):
        script = self.create_project("script")
        script_capabilities = self.client.get(f"/api/studio/scripts/{script['id']}").json()["capabilities"]
        self.assertEqual(script_capabilities["generation"], True)
        self.assertEqual(script_capabilities["generation_purposes"], ["optimize"])
        self.assertEqual(script_capabilities["generation_slot"], "text")
        self.assertEqual(script_capabilities["generation_scopes"], ["scene", "segment", "episode_outline"])
        self.assertTrue(script_capabilities["generation_requires_explicit_request"])
        self.assertEqual(script_capabilities["generation_apply"], "explicit_review")

        novel = self.create_project("novel")
        novel_capabilities = self.client.get(f"/api/studio/novels/{novel['id']}").json()["capabilities"]
        manifest_capabilities = self.client.get(f"/api/studio/novels/{novel['id']}/manifest").json()["capabilities"]
        for capabilities in (novel_capabilities, manifest_capabilities):
            self.assertEqual(capabilities["generation"], True)
            self.assertEqual(capabilities["generation_purposes"], ["optimize"])
            self.assertEqual(capabilities["generation_slot"], "text")
            self.assertEqual(capabilities["generation_scopes"], ["chapter", "chapter_outline"])
            self.assertTrue(capabilities["generation_requires_explicit_request"])
            self.assertEqual(capabilities["generation_apply"], "explicit_review")

    def test_script_unicode_codepoint_ranges_and_segment_replacement_offsets(self):
        project = self.create_project("script")
        project_id = project["id"]
        result = self.command("script", project_id, 1, "draft", "set_draft", {"body_markdown": "😀A中文B"})
        self.assertEqual(result.status_code, 200, result.text)
        result = self.command("script", project_id, 2, "structure", "structure_draft", {"episodes": [
            {"client_ref": "ep1", "title": "第 1 集", "scenes": [
                {"client_ref": "s1", "title": "第 1 场", "body_markdown": "😀A", "start": 0, "end": 2},
                {"client_ref": "s2", "title": "第 2 场", "body_markdown": "中文B", "start": 2, "end": 5},
            ]}
        ]})
        self.assertEqual(result.status_code, 200, result.text)
        created = result.json()["created_ids"]
        self.assertTrue({"ep1", "s1", "s2"}.issubset(created))
        scene = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{created['s1']}").json()["scene"]
        self.assertEqual(scene["body_markdown"], "😀A")
        self.assertEqual(len(scene["body_markdown"]), 2)
        digest = hashlib.sha256("😀A".encode()).hexdigest()
        result = self.command("script", project_id, 3, "segments", "set_scene_segments", {
            "scene_id": created["s1"], "source_sha256": digest,
            "segments": [
                {"client_ref": "g1", "title": "第 1 段", "start": 0, "end": 1, "exact_text": "😀"},
                {"client_ref": "g2", "title": "第 2 段", "start": 1, "end": 2, "exact_text": "A"},
            ]})
        self.assertEqual(result.status_code, 200, result.text)
        ids = result.json()["created_ids"]
        result = self.command("script", project_id, 4, "replace", "replace_segment_text", {
            "segment_id": ids["g1"], "body_markdown": "🙂🪴"})
        self.assertEqual(result.status_code, 200, result.text)
        scene = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{created['s1']}").json()["scene"]
        self.assertEqual(scene["body_markdown"], "🙂🪴A")
        self.assertEqual([(item["start"], item["end"]) for item in scene["segments"]], [(0, 2), (2, 3)])
        self.assertEqual([item["body_markdown"] for item in scene["segments"]], ["🙂🪴", "A"])
        self.assertTrue(all(item["source_sha256"] == scene["content_sha256"] for item in scene["segments"]))

    def test_novel_batch_aliases_are_usable_and_replay_is_idempotent(self):
        project = self.create_project("novel")
        project_id = project["id"]
        payload = {"request_id": "novel-batch", "expected_revision": 1, "action": "batch", "args": {"operations": [
            {"action": "create_volume", "args": {"title": "第一卷", "client_ref": "vol"}},
            {"action": "create_chapter", "args": {"volume_id": "vol", "title": "第一章", "body_markdown": "开篇", "client_ref": "chapter"}},
            {"action": "create_setting_entry", "args": {"category_id": "characters", "body_markdown": "# 林澈\n冷静。", "use_state": "confirmed", "client_ref": "hero"}},
        ]}}
        first = self.client.post(f"/api/studio/novels/{project_id}/commands", json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        receipt = first.json()
        self.assertEqual(set(receipt["created_ids"]), {"vol", "chapter", "hero"})
        second = self.client.post(f"/api/studio/novels/{project_id}/commands", json=payload)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json(), receipt)
        # A fresh store instance is the restart boundary: the durable receipt must
        # survive process-local caches and keep the original client_ref mapping.
        restarted, _ = client_for(self.tmp.name)
        with restarted:
            recovered = restarted.post(f"/api/studio/novels/{project_id}/commands", json=payload)
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json(), receipt)
            stale = restarted.post(f"/api/studio/novels/{project_id}/commands", json={
                "request_id": "old-revision", "expected_revision": 1,
                "action": "create_volume", "args": {"title": "不应覆盖"}})
            self.assertEqual(stale.status_code, 409, stale.text)
            self.assertEqual(stale.json()["detail"]["current_revision"], 2)
        changed = json.loads(json.dumps(payload))
        changed["args"]["operations"][0]["args"]["title"] = "另一卷"
        mismatch = self.client.post(f"/api/studio/novels/{project_id}/commands", json=changed)
        self.assertEqual(mismatch.status_code, 409, mismatch.text)
        summary = self.client.get(f"/api/studio/novels/{project_id}").json()
        self.assertEqual(summary["revision"], 2)
        self.assertEqual(len(summary["directory"]["volumes"]), 1)
        self.assertEqual(summary["directory"]["volumes"][0]["chapters"][0]["title"], "第一章")

    def test_missing_or_corrupt_blob_fails_closed_instead_of_returning_blank_text(self):
        project_id = self.create_project("script")["id"]
        saved = self.command("script", project_id, 1, "draft", "set_draft", {"body_markdown": "正文不能消失"})
        self.assertEqual(saved.status_code, 200, saved.text)
        digest = self.projects.read_manuscript_record(project_id, "script")["script"]["draft_sha256"]
        blob = Path(self.tmp.name) / "data" / "studio_manuscripts" / "blobs" / f"{digest}.md"
        blob.unlink()
        missing = self.client.get(f"/api/studio/scripts/{project_id}/view?scope=root")
        self.assertEqual(missing.status_code, 500, missing.text)
        self.assertIn("缺失", missing.json()["detail"])
        blob.write_bytes(b"different text")
        corrupt = self.client.get(f"/api/studio/scripts/{project_id}/view?scope=root")
        self.assertEqual(corrupt.status_code, 500, corrupt.text)
        self.assertIn("校验失败", corrupt.json()["detail"])

    def test_setting_archive_restore_revision_history_pagination_and_basis_review(self):
        project_id = self.create_project("novel")["id"]
        result = self.command("novel", project_id, 1, "create-character", "create_setting_entry", {
            "category_id": "characters", "body_markdown": "# 林澈\n最初冷淡。", "use_state": "confirmed"})
        self.assertEqual(result.status_code, 200, result.text)
        record = self.projects.read_manuscript_record(project_id, "novel")
        entry = record["novel"]["settings"]["entries"][0]
        version = entry["versions"][0]
        entry_id, version_id = entry["id"], version["id"]

        revision = 2
        for number, body in enumerate(("# 林澈\n后来冷静。", "# 林澈\n开始信任。", "# 林澈\n学会求助。"), 1):
            result = self.command("novel", project_id, revision, f"edit-{number}", "revise_setting_version", {
                "entry_id": entry_id, "version_id": version_id, "body_markdown": body})
            self.assertEqual(result.status_code, 200, result.text)
            revision += 1
        history = self.client.get(f"/api/studio/novels/{project_id}/settings/{entry_id}/revisions"
                                  f"?version_id={version_id}&limit=1")
        self.assertEqual(history.status_code, 200, history.text)
        self.assertTrue(history.json()["has_more"])
        cursor = history.json()["next_cursor"]
        # Any project write invalidates the cursor, even if the edited object differs.
        moved = self.command("novel", project_id, revision, "move-setting", "move_setting_entry", {
            "entry_id": entry_id, "category_id": "relationships"})
        self.assertEqual(moved.status_code, 200, moved.text)
        stale_page = self.client.get(f"/api/studio/novels/{project_id}/settings/{entry_id}/revisions"
                                     f"?version_id={version_id}&limit=1&cursor={cursor}")
        self.assertEqual(stale_page.status_code, 409, stale_page.text)

        restored_revision = self.command("novel", project_id, revision + 1, "restore-edit-1", "restore_setting_revision", {
            "entry_id": entry_id, "version_id": version_id, "revision": 1})
        self.assertEqual(restored_revision.status_code, 200, restored_revision.text)
        detail = self.client.get(f"/api/studio/novels/{project_id}/settings/{entry_id}?version_id={version_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["selected_version"]["body_markdown"], "# 林澈\n最初冷淡。")
        self.assertEqual(detail.json()["selected_version"]["selected_edit_revision"], 5)

        archived = self.command("novel", project_id, revision + 2, "archive-setting", "archive_setting_entry", {
            "entry_id": entry_id})
        self.assertEqual(archived.status_code, 200, archived.text)
        missing = self.client.get(f"/api/studio/novels/{project_id}/settings/{entry_id}")
        self.assertEqual(missing.status_code, 404, missing.text)
        restored = self.command("novel", project_id, revision + 3, "restore-setting", "restore_setting_entry", {
            "entry_id": entry_id})
        self.assertEqual(restored.status_code, 200, restored.text)
        detail = self.client.get(f"/api/studio/novels/{project_id}/settings/{entry_id}?version_id={version_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["selected_version"]["body_markdown"], "# 林澈\n最初冷淡。")

        record = self.projects.read_manuscript_record(project_id, "novel")
        version = next(item for item in record["novel"]["settings"]["entries"][0]["versions"]
                       if item["id"] == version_id)
        volume = self.command("novel", project_id, revision + 4, "volume", "create_volume", {"title": "卷一"})
        volume_id = volume.json()["created_ids"]["chapter"] if "chapter" in volume.json()["created_ids"] else volume.json()["changed_ids"][-1]
        chapter = self.command("novel", project_id, revision + 5, "chapter", "create_chapter", {
            "volume_id": volume_id, "title": "第一章", "body_markdown": "正文必须保留。",
            "basis_refs": [{"kind": "setting", "entry_id": entry_id, "version_id": version_id,
                            "content_sha256": version["content_sha256"]}]})
        self.assertEqual(chapter.status_code, 200, chapter.text)
        chapter_id = chapter.json()["created_ids"].get("chapter") or chapter.json()["changed_ids"][-1]
        basis_changed = self.command("novel", project_id, revision + 6, "basis-change", "revise_setting_version", {
            "entry_id": entry_id, "version_id": version_id, "body_markdown": "# 林澈\n后续修订改变了基线。"})
        self.assertEqual(basis_changed.status_code, 200, basis_changed.text)
        chapter_read = self.client.get(f"/api/studio/novels/{project_id}/chapters/{chapter_id}")
        self.assertEqual(chapter_read.status_code, 200, chapter_read.text)
        self.assertTrue(chapter_read.json()["chapter"]["needs_review"])
        self.assertEqual(chapter_read.json()["chapter"]["body_markdown"], "正文必须保留。")

    def test_project_recycle_restores_manuscript_and_refuses_missing_blob(self):
        project = self.create_project("script")
        project_id = project["id"]
        saved = self.command("script", project_id, 1, "draft", "set_draft", {"body_markdown": "归档正文"})
        self.assertEqual(saved.status_code, 200, saved.text)
        digest = self.projects.read_manuscript_record(project_id, "script")["script"]["draft_sha256"]
        deleted = self.client.delete(f"/api/studio/projects/{project_id}?module=script&revision=2")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get(f"/api/studio/scripts/{project_id}").status_code, 404)
        restored = self.client.post(f"/api/studio/projects/{project_id}/restore?module=script")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["project"]["revision"], 3)
        stale_write = self.command("script", project_id, 2, "pre-delete-tab", "set_draft", {
            "body_markdown": "旧标签不得覆盖恢复后的正文"})
        self.assertEqual(stale_write.status_code, 409, stale_write.text)
        read = self.client.get(f"/api/studio/scripts/{project_id}/view?scope=root")
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["blocks"][0]["body_markdown"], "归档正文")

        deleted = self.client.delete(f"/api/studio/projects/{project_id}?module=script&revision=3")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        (Path(self.tmp.name) / "data" / "studio_manuscripts" / "blobs" / f"{digest}.md").unlink()
        corrupt_restore = self.client.post(f"/api/studio/projects/{project_id}/restore?module=script")
        self.assertEqual(corrupt_restore.status_code, 500, corrupt_restore.text)
        self.assertEqual(self.client.get(f"/api/studio/scripts/{project_id}").status_code, 404)

    def test_batch_failure_is_atomic_and_unknown_fields_are_rejected(self):
        project = self.create_project("novel")
        project_id = project["id"]
        failed = self.client.post(f"/api/studio/novels/{project_id}/commands", json={
            "request_id": "bad-batch", "expected_revision": 1, "action": "batch", "args": {"operations": [
                {"action": "create_volume", "args": {"title": "临时卷", "client_ref": "v"}},
                {"action": "create_chapter", "args": {"volume_id": "missing", "title": "章", "body_markdown": "正文"}},
            ]}})
        self.assertIn(failed.status_code, (400, 404))
        self.assertEqual(self.client.get(f"/api/studio/novels/{project_id}").json()["revision"], 1)
        self.assertEqual(self.client.get(f"/api/studio/novels/{project_id}").json()["directory"]["volumes"], [])
        malformed = self.command("script", self.create_project("script")["id"], 1, "bad-prod", "set_draft",
                                 {"body_markdown": "safe", "production": {"status": "succeeded"}})
        self.assertEqual(malformed.status_code, 422, malformed.text)
        schema = self.client.get("/openapi.json").json()
        body = schema["paths"]["/api/studio/scripts/{project_id}/commands"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(len(body["oneOf"]), 16)
        self.assertEqual(body["discriminator"]["propertyName"], "action")
        restore_args = schema["components"]["schemas"]["RestoreDraftArgs"]
        self.assertEqual(restore_args["required"], ["source_sha256", "replace_structured"])
        self.assertEqual(restore_args["properties"]["source_sha256"]["pattern"], "^[a-f0-9]{64}$")
        self.assertIs(restore_args["properties"]["replace_structured"]["const"], True)

        import_args = schema["components"]["schemas"]["ImportMarkdownArgs"]
        self.assertEqual(set(import_args["required"]), {"body_markdown", "replace"})
        self.assertEqual(import_args["properties"]["replace"]["type"], "boolean")
        segment_args = schema["components"]["schemas"]["CreateSegmentArgs"]
        self.assertEqual(set(segment_args["required"]), {"scene_id", "body_markdown"})
        self.assertIn("title", segment_args["properties"])
        export_schema = schema["components"]["schemas"]["ManuscriptMarkdownExport"]
        self.assertEqual(set(export_schema["required"]), {
            "project_id", "revision", "format_version", "source_sha256", "body_markdown"})
        self.assertEqual(export_schema["properties"]["format_version"]["const"], "laohu-manuscript-v1")
        receipt_schema = schema["components"]["schemas"]["ManuscriptCommandReceipt"]
        self.assertIn("source_sha256", receipt_schema["properties"])
        self.assertEqual(schema["paths"]["/api/studio/scripts/{project_id}/commands"]
                         ["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
                         "#/components/schemas/ManuscriptCommandReceipt")
        self.assertIn("GET", {method.upper() for path, item in schema["paths"].items()
                               if path in {"/api/studio/scripts/{project_id}/markdown",
                                           "/api/studio/novels/{project_id}/markdown"}
                               for method in item})

    def test_script_markdown_roundtrip_preserves_unicode_whitespace_empty_segments_and_history(self):
        project_id = self.create_project("script")["id"]
        source = "# 灰色回声\r\n## 2A · 屋顶\r\n---\r\n😀前缀  \r\n---\r\n---\r\n末尾\r\n---\r\n"
        first = self.command("script", project_id, 1, "markdown-first", "import_markdown", {
            "body_markdown": source, "replace": False})
        self.assertEqual(first.status_code, 200, first.text)
        receipt = first.json()
        self.assertEqual(receipt["revision"], 2)
        history_digest = hashlib.sha256(source.replace("\r\n", "\n").encode()).hexdigest()
        self.assertEqual(receipt["source_sha256"], history_digest)
        exported = self.client.get(f"/api/studio/scripts/{project_id}/markdown")
        self.assertEqual(exported.status_code, 200, exported.text)
        normalized = source.replace("\r\n", "\n")
        self.assertEqual(exported.json()["format_version"], "laohu-manuscript-v1")
        self.assertEqual(exported.json()["body_markdown"], normalized)
        self.assertEqual(exported.json()["source_sha256"], hashlib.sha256(normalized.encode()).hexdigest())

        view = self.client.get(f"/api/studio/scripts/{project_id}/view?scope=root")
        self.assertEqual(view.status_code, 200, view.text)
        scene = view.json()["blocks"][0]
        self.assertEqual(scene["editable_markdown"], "---\n😀前缀  \n---\n---\n末尾\n---\n")
        self.assertEqual([item["body_markdown"] for item in scene["segments"]], ["", "😀前缀  ", "", "末尾", ""])
        self.assertEqual([item["end"] - item["start"] for item in scene["segments"]], [0, 5, 0, 2, 0])

        replay = self.command("script", project_id, 1, "markdown-first", "import_markdown", {
            "body_markdown": source, "replace": False})
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), receipt)
        no_replace = self.command("script", project_id, 2, "markdown-no-replace", "import_markdown", {
            "body_markdown": "# 替换\n## 空\n", "replace": False})
        self.assertEqual(no_replace.status_code, 409, no_replace.text)
        self.assertEqual(self.client.get(f"/api/studio/scripts/{project_id}").json()["revision"], 2)

        replacement = "# 新集\n## 新场\n新正文\n"
        replaced = self.command("script", project_id, 2, "markdown-replace", "import_markdown", {
            "body_markdown": replacement, "replace": True})
        self.assertEqual(replaced.status_code, 200, replaced.text)
        record = self.projects.read_manuscript_record(project_id, "script")["script"]
        original_scene_id = receipt["changed_ids"][0]
        self.assertEqual(record["archive"][-1]["episodes"][0]["scenes"][0]["id"], original_scene_id)
        historical = self.client.get(f"/api/studio/scripts/{project_id}/markdown/history/{history_digest}")
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertEqual(historical.json()["body_markdown"], normalized)

    def test_script_manual_segment_create_scene_edit_and_empty_replacement_contract(self):
        project_id = self.create_project("script")["id"]
        created = self.command("script", project_id, 1, "episode", "create_episode", {
            "title": "E", "client_ref": "ep"})
        episode_id = created.json()["created_ids"]["ep"]
        scene = self.command("script", project_id, 2, "scene", "create_scene", {
            "episode_id": episode_id, "title": "S", "body_markdown": "😀原文", "client_ref": "scene"})
        self.assertEqual(scene.status_code, 200, scene.text)
        scene_id = scene.json()["created_ids"]["scene"]
        base_segment_id = scene.json()["changed_ids"][-1]
        added = self.command("script", project_id, 3, "add-segment", "create_segment", {
            "scene_id": scene_id, "body_markdown": "", "after_segment_id": base_segment_id,
            "title": "用户命名", "client_ref": "empty-segment"})
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(added.json()["created_ids"]["empty-segment"], added.json()["changed_ids"][-1])
        segments = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]["segments"]
        self.assertEqual([item["title"] for item in segments], ["第 1 段", "用户命名"])
        self.assertEqual([item["body_markdown"] for item in segments], ["😀原文", ""])

        updated = self.command("script", project_id, 4, "edit-scene-markdown", "update_scene", {
            "scene_id": scene_id, "body_markdown": "😀原文\n---\n新段\n---\n尾段"})
        self.assertEqual(updated.status_code, 200, updated.text)
        current = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(current["editable_markdown"], "😀原文\n---\n新段\n---\n尾段")
        self.assertEqual(current["segments"][0]["id"], base_segment_id)
        self.assertNotIn(added.json()["created_ids"]["empty-segment"], {item["id"] for item in current["segments"]})
        self.assertEqual(updated.json()["revision"], 5)

        target_id = current["segments"][0]["id"]
        empty = self.command("script", project_id, 5, "empty-segment-body", "replace_segment_text", {
            "segment_id": target_id, "body_markdown": ""})
        self.assertEqual(empty.status_code, 200, empty.text)
        current = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(current["segments"][0]["body_markdown"], "")
        self.assertTrue(all(item["source_sha256"] == current["content_sha256"] for item in current["segments"]))
        bad_segment = self.command("script", project_id, 6, "delimiter-in-segment", "replace_segment_text", {
            "segment_id": current["segments"][0]["id"], "body_markdown": "---\n正文"})
        self.assertIn(bad_segment.status_code, (400, 422))

        empty_scene = self.command("script", project_id, 6, "empty-scene", "create_scene", {
            "episode_id": episode_id, "title": "空场", "body_markdown": ""})
        self.assertEqual(empty_scene.status_code, 200, empty_scene.text)
        empty_scene_id = empty_scene.json()["changed_ids"][1]
        blank_segment = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{empty_scene_id}").json()["scene"]["segments"]
        self.assertEqual(len(blank_segment), 1)
        self.assertEqual((blank_segment[0]["start"], blank_segment[0]["end"], blank_segment[0]["body_markdown"]), (0, 0, ""))
        summary_scene = next(scene for item in self.client.get(f"/api/studio/scripts/{project_id}").json()["directory"]["episodes"]
                             for scene in item["scenes"] if scene["id"] == empty_scene_id)
        self.assertEqual(summary_scene["segments"][0]["id"], blank_segment[0]["id"])

    def test_script_segment_delete_removes_body_preserves_survivors_and_restores_idempotently(self):
        project_id = self.create_project("script")["id"]
        parts = ["😀首段\n\n", "中间第一行\n中间第二行\n", "尾段🪴  \n"]
        source = "# Episode\n## Scene\n" + "\n---\n".join(parts)
        imported = self.command("script", project_id, 1, "delete-segment-import", "import_markdown", {
            "body_markdown": source, "replace": False})
        self.assertEqual(imported.status_code, 200, imported.text)
        scene_id = self.client.get(f"/api/studio/scripts/{project_id}").json()["directory"]["episodes"][0]["scenes"][0]["id"]
        original = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        original_ids = [segment["id"] for segment in original["segments"]]
        self.assertEqual([segment["body_markdown"] for segment in original["segments"]], parts)

        deleted = self.command("script", project_id, 2, "delete-middle", "delete_item", {
            "item_type": "segment", "item_id": original_ids[1]})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        receipt = deleted.json()
        self.assertEqual(receipt["revision"], 3)
        current = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        expected_after_delete = parts[0] + "\n---\n" + parts[2]
        self.assertEqual(current["body_markdown"], expected_after_delete)
        self.assertEqual(current["editable_markdown"], expected_after_delete)
        self.assertEqual([segment["id"] for segment in current["segments"]], [original_ids[0], original_ids[2]])
        self.assertEqual([segment["body_markdown"] for segment in current["segments"]], [parts[0], parts[2]])
        self.assertEqual([segment["order"] for segment in current["segments"]], [1, 2])
        self.assertEqual([(segment["start"], segment["end"]) for segment in current["segments"]],
                         [(0, len(parts[0])), (len(parts[0]) + 5, len(expected_after_delete))])
        self.assertTrue(all(segment["source_sha256"] == current["content_sha256"]
                            for segment in current["segments"]))
        whole_markdown = self.client.get(f"/api/studio/scripts/{project_id}/markdown")
        self.assertEqual(whole_markdown.status_code, 200, whole_markdown.text)
        self.assertEqual(whole_markdown.json()["body_markdown"],
                         "# Episode\n## Scene\n" + expected_after_delete)
        snapshot = StudioManuscriptStore(self.tmp.name, self.projects).script_import_snapshot(
            project_id, 3, {"type": "scene", "ids": [scene_id]})
        self.assertEqual([segment["id"] for segment in snapshot["episodes"][0]["segments"]],
                         [original_ids[0], original_ids[2]])
        self.assertEqual([segment["body_markdown"] for segment in snapshot["episodes"][0]["segments"]],
                         [parts[0], parts[2]])
        prior_scene = self.client.get(
            f"/api/studio/scripts/{project_id}/scenes/{scene_id}?edit_revision=1").json()["scene"]
        self.assertEqual(prior_scene["body_markdown"], "\n".join(source.split("\n")[2:]))
        self.assertEqual([segment["id"] for segment in prior_scene["segments"]], original_ids)

        replay = self.command("script", project_id, 2, "delete-middle", "delete_item", {
            "item_type": "segment", "item_id": original_ids[1]})
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), receipt)

        restored = self.command("script", project_id, 3, "restore-middle", "restore_item", {
            "item_id": original_ids[1]})
        self.assertEqual(restored.status_code, 200, restored.text)
        restored_scene = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(restored_scene["body_markdown"], "\n".join(source.split("\n")[2:]))
        self.assertEqual([segment["id"] for segment in restored_scene["segments"]], original_ids)
        self.assertEqual([segment["body_markdown"] for segment in restored_scene["segments"]], parts)
        self.assertEqual([segment["order"] for segment in restored_scene["segments"]], [1, 2, 3])
        self.assertTrue(all(segment["source_sha256"] == restored_scene["content_sha256"]
                            for segment in restored_scene["segments"]))
        deleted_history = self.client.get(
            f"/api/studio/scripts/{project_id}/scenes/{scene_id}?edit_revision=2").json()["scene"]
        self.assertEqual(deleted_history["body_markdown"], expected_after_delete)
        self.assertEqual([segment["id"] for segment in deleted_history["segments"]],
                         [original_ids[0], original_ids[2]])
        restore_replay = self.command("script", project_id, 3, "restore-middle", "restore_item", {
            "item_id": original_ids[1]})
        self.assertEqual(restore_replay.status_code, 200, restore_replay.text)
        self.assertEqual(restore_replay.json(), restored.json())
        archived = self.projects.read_manuscript_record(project_id, "script")["script"]["archive"]
        removed = next(item for item in archived if (item.get("item") or {}).get("id") == original_ids[1])
        self.assertEqual(removed["item"]["source_sha256"], original["content_sha256"])
        self.assertEqual(removed["item"]["start"], len(parts[0]) + 5)
        self.assertIn("restored_at", removed)

    def test_script_segment_delete_edges_and_last_segment_leaves_empty_scene(self):
        for position in (0, 2):
            with self.subTest(position=position):
                project_id = self.create_project("script")["id"]
                parts = ["😀首段\n", "中间段\n\n", "尾段🪴  "]
                source = "# Episode\n## Scene\n" + "\n---\n".join(parts)
                imported = self.command("script", project_id, 1, f"edge-import-{position}", "import_markdown", {
                    "body_markdown": source, "replace": False})
                self.assertEqual(imported.status_code, 200, imported.text)
                scene_id = self.client.get(f"/api/studio/scripts/{project_id}").json()["directory"]["episodes"][0]["scenes"][0]["id"]
                before = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
                removed_id = before["segments"][position]["id"]
                remaining = [segment for index, segment in enumerate(before["segments"]) if index != position]
                expected_parts = [parts[index] for index in range(3) if index != position]
                deleted = self.command("script", project_id, 2, f"edge-delete-{position}", "delete_item", {
                    "item_type": "segment", "item_id": removed_id})
                self.assertEqual(deleted.status_code, 200, deleted.text)
                after = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
                expected_body = "\n---\n".join(expected_parts)
                self.assertEqual(after["body_markdown"], expected_body)
                self.assertEqual([segment["id"] for segment in after["segments"]],
                                 [segment["id"] for segment in remaining])
                self.assertEqual([segment["body_markdown"] for segment in after["segments"]], expected_parts)

        project_id = self.create_project("script")["id"]
        source = "# Episode\n## Scene\n唯一🙂\n多行正文\n"
        imported = self.command("script", project_id, 1, "only-import", "import_markdown", {
            "body_markdown": source, "replace": False})
        self.assertEqual(imported.status_code, 200, imported.text)
        scene_id = self.client.get(f"/api/studio/scripts/{project_id}").json()["directory"]["episodes"][0]["scenes"][0]["id"]
        before = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        only_id = before["segments"][0]["id"]
        deleted = self.command("script", project_id, 2, "only-delete", "delete_item", {
            "item_type": "segment", "item_id": only_id})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        empty = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(empty["body_markdown"], "")
        self.assertEqual(empty["editable_markdown"], "")
        self.assertEqual(empty["segments"], [])
        with self.assertRaises(StudioProjectConflict) as no_segments:
            StudioManuscriptStore(self.tmp.name, self.projects).script_import_snapshot(
                project_id, 3, {"type": "scene", "ids": [scene_id]})
        self.assertEqual(no_segments.exception.detail["code"], "SCENE_NOT_SEGMENTED")
        exported = self.client.get(f"/api/studio/scripts/{project_id}/markdown")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(exported.json()["body_markdown"], "# Episode\n## Scene\n")

        restored = self.command("script", project_id, 3, "only-restore", "restore_item", {"item_id": only_id})
        self.assertEqual(restored.status_code, 200, restored.text)
        restored_scene = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(restored_scene["body_markdown"], "唯一🙂\n多行正文\n")
        self.assertEqual([segment["id"] for segment in restored_scene["segments"]], [only_id])

        deleted_again = self.command("script", project_id, 4, "only-delete-again", "delete_item", {
            "item_type": "segment", "item_id": only_id})
        self.assertEqual(deleted_again.status_code, 200, deleted_again.text)
        empty_again = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(empty_again["body_markdown"], "")
        self.assertEqual(empty_again["segments"], [])

        added = self.command("script", project_id, 5, "after-last-delete", "create_segment", {
            "scene_id": scene_id, "body_markdown": "新段正文", "title": "新段"})
        self.assertEqual(added.status_code, 200, added.text)
        reloaded = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(len(reloaded["segments"]), 1)
        self.assertEqual(reloaded["segments"][0]["body_markdown"], "新段正文")
        self.assertEqual(reloaded["segments"][0]["title"], "新段")

    def test_script_segment_restore_conflicts_after_scene_edit(self):
        project_id = self.create_project("script")["id"]
        source = "# Episode\n## Scene\n第一段\n---\n第二段😀"
        imported = self.command("script", project_id, 1, "restore-conflict-import", "import_markdown", {
            "body_markdown": source, "replace": False})
        self.assertEqual(imported.status_code, 200, imported.text)
        scene_id = self.client.get(f"/api/studio/scripts/{project_id}").json()["directory"]["episodes"][0]["scenes"][0]["id"]
        segment_id = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]["segments"][0]["id"]
        deleted = self.command("script", project_id, 2, "conflict-delete", "delete_item", {
            "item_type": "segment", "item_id": segment_id})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        edited = self.command("script", project_id, 3, "after-delete-edit", "update_scene", {
            "scene_id": scene_id, "body_markdown": "后续编辑内容"})
        self.assertEqual(edited.status_code, 200, edited.text)
        after_edit = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        rejected = self.command("script", project_id, 4, "unsafe-restore", "restore_item", {
            "item_id": segment_id})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json()["detail"]["code"], "SEGMENT_RESTORE_CONFLICT")
        unchanged = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(unchanged["body_markdown"], after_edit["body_markdown"])
        self.assertEqual(unchanged["content_sha256"], after_edit["content_sha256"])
        self.assertEqual(self.client.get(f"/api/studio/scripts/{project_id}").json()["revision"], 4)

    def test_script_markdown_delimiter_is_standalone_and_legacy_segments_roundtrip(self):
        project_id = self.create_project("script")["id"]
        episode = self.command("script", project_id, 1, "plain-episode", "create_episode", {
            "title": "序幕", "client_ref": "episode"})
        episode_id = episode.json()["created_ids"]["episode"]
        created = self.command("script", project_id, 2, "plain-scene", "create_scene", {
            "episode_id": episode_id, "title": "屋顶", "body_markdown": "AB", "client_ref": "scene"})
        scene_id = created.json()["created_ids"]["scene"]
        original_segment_id = created.json()["created_ids"].get("segment") or created.json()["changed_ids"][-1]
        added = self.command("script", project_id, 3, "append-empty-segment", "create_segment", {
            "scene_id": scene_id, "body_markdown": "", "after_segment_id": original_segment_id})
        self.assertEqual(added.status_code, 200, added.text)
        scene = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(scene["editable_markdown"], "AB\n---\n")
        self.assertEqual([item["body_markdown"] for item in scene["segments"]], ["AB", ""])
        self.assertEqual(scene["segments"][0]["id"], original_segment_id)
        updated = self.command("script", project_id, 4, "roundtrip-legacy", "update_scene", {
            "scene_id": scene_id, "body_markdown": scene["editable_markdown"]})
        self.assertEqual(updated.status_code, 200, updated.text)
        after = self.client.get(f"/api/studio/scripts/{project_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual([item["body_markdown"] for item in after["segments"]], ["AB", ""])
        self.assertEqual(after["segments"][0]["id"], original_segment_id)

        raw_project = self.create_project("script")["id"]
        raw = "#第一集\n##第一场\n无空格标题按正文保存\n### 正文小标题\n"
        imported = self.command("script", raw_project, 1, "unspaced-hash", "import_markdown", {
            "body_markdown": raw, "replace": False})
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(self.client.get(f"/api/studio/scripts/{raw_project}/markdown").json()["body_markdown"], raw)
        bad_type = self.command("script", raw_project, 2, "strict-replace", "import_markdown", {
            "body_markdown": raw, "replace": 1})
        self.assertEqual(bad_type.status_code, 422, bad_type.text)

        conflict_project = self.create_project("script")["id"]
        episode = self.command("script", conflict_project, 1, "conflict-episode", "create_episode", {
            "title": "卷轴", "client_ref": "episode"})
        self.command("script", conflict_project, 2, "conflict-scene", "create_scene", {
            "episode_id": episode.json()["created_ids"]["episode"], "title": "雨夜",
            "body_markdown": "# 旧正文标题\n正文"})
        conflict = self.client.get(f"/api/studio/scripts/{conflict_project}/markdown")
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["detail"]["code"], "MARKDOWN_FORMAT_CONFLICT")

        legacy_project = self.create_project("script")["id"]
        episode = self.command("script", legacy_project, 1, "legacy-episode", "create_episode", {
            "title": "序幕", "client_ref": "episode"})
        episode_id = episode.json()["created_ids"]["episode"]
        scene_create = self.command("script", legacy_project, 2, "legacy-scene", "create_scene", {
            "episode_id": episode_id, "title": "旧分段", "body_markdown": "AB", "client_ref": "scene"})
        scene_id = scene_create.json()["created_ids"]["scene"]
        detail = self.client.get(f"/api/studio/scripts/{legacy_project}/scenes/{scene_id}").json()["scene"]
        separated = self.command("script", legacy_project, 3, "legacy-boundaries", "set_scene_segments", {
            "scene_id": scene_id, "source_sha256": detail["content_sha256"], "segments": [
                {"title": "A", "start": 0, "end": 1, "exact_text": "A"},
                {"title": "B", "start": 1, "end": 2, "exact_text": "B"},
            ]})
        self.assertEqual(separated.status_code, 200, separated.text)
        legacy_detail = self.client.get(f"/api/studio/scripts/{legacy_project}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(legacy_detail["editable_markdown"], "A\n---\nB")
        old_ids = [item["id"] for item in legacy_detail["segments"]]
        restored = self.command("script", legacy_project, 4, "legacy-roundtrip", "update_scene", {
            "scene_id": scene_id, "body_markdown": legacy_detail["editable_markdown"]})
        self.assertEqual(restored.status_code, 200, restored.text)
        restored_scene = self.client.get(f"/api/studio/scripts/{legacy_project}/scenes/{scene_id}").json()["scene"]
        self.assertEqual([item["body_markdown"] for item in restored_scene["segments"]], ["A", "B"])
        self.assertEqual([item["id"] for item in restored_scene["segments"]], old_ids)

    def test_markdown_closed_atx_headings_and_fenced_hash_lines_roundtrip_for_script_and_novel(self):
        script_project = self.create_project("script")["id"]
        script_raw = "# Episode ###\n## Scene ##\n```md\n# literal\n## literal\n```\nBody\n"
        script_import = self.command("script", script_project, 1, "closed-script-headings", "import_markdown", {
            "body_markdown": script_raw, "replace": False})
        self.assertEqual(script_import.status_code, 200, script_import.text)
        script_summary = self.client.get(f"/api/studio/scripts/{script_project}").json()
        script_episode = script_summary["directory"]["episodes"][0]
        script_scene = script_episode["scenes"][0]
        self.assertEqual(script_episode["title"], "Episode")
        self.assertEqual(script_scene["title"], "Scene")
        script_detail = self.client.get(
            f"/api/studio/scripts/{script_project}/scenes/{script_scene['id']}").json()["scene"]
        self.assertEqual(script_detail["body_markdown"], "```md\n# literal\n## literal\n```\nBody\n")
        script_export = self.client.get(f"/api/studio/scripts/{script_project}/markdown").json()
        self.assertEqual(script_export["body_markdown"],
                         "# Episode\n## Scene\n```md\n# literal\n## literal\n```\nBody\n")
        script_history = self.client.get(
            f"/api/studio/scripts/{script_project}/markdown/history/{script_import.json()['source_sha256']}")
        self.assertEqual(script_history.status_code, 200, script_history.text)
        self.assertEqual(script_history.json()["body_markdown"], script_raw)

        novel_project = self.create_project("novel")["id"]
        novel_raw = "# Volume#\n## Chapter ###\n~~~md\n# literal\n## literal\n~~~\nBody\n"
        novel_import = self.command("novel", novel_project, 1, "closed-novel-headings", "import_markdown", {
            "body_markdown": novel_raw, "replace": False})
        self.assertEqual(novel_import.status_code, 200, novel_import.text)
        novel_summary = self.client.get(f"/api/studio/novels/{novel_project}").json()
        novel_volume = novel_summary["directory"]["volumes"][0]
        novel_chapter = novel_volume["chapters"][0]
        self.assertEqual(novel_volume["title"], "Volume#")
        self.assertEqual(novel_chapter["title"], "Chapter")
        novel_detail = self.client.get(
            f"/api/studio/novels/{novel_project}/chapters/{novel_chapter['id']}").json()["chapter"]
        self.assertEqual(novel_detail["body_markdown"], "~~~md\n# literal\n## literal\n~~~\nBody\n")
        novel_export = self.client.get(f"/api/studio/novels/{novel_project}/markdown").json()
        self.assertEqual(novel_export["body_markdown"],
                         "# Volume#\n## Chapter\n~~~md\n# literal\n## literal\n~~~\nBody\n")

    def test_novel_markdown_roundtrip_empty_outline_replacement_and_reserved_heading_conflict(self):
        project_id = self.create_project("novel")["id"]
        source = "# 第一卷\r\n## 空章一\r\n\r\n## 正文章\r\n\r\n😀段落  \r\n\r\n# 空卷\r\n# 第三卷\r\n## 末章\r\n尾行\r\n"
        imported = self.command("novel", project_id, 1, "novel-markdown-import", "import_markdown", {
            "body_markdown": source, "replace": False})
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["source_sha256"], hashlib.sha256(source.replace("\r\n", "\n").encode()).hexdigest())
        exported = self.client.get(f"/api/studio/novels/{project_id}/markdown")
        self.assertEqual(exported.status_code, 200, exported.text)
        normalized = source.replace("\r\n", "\n")
        self.assertEqual(exported.json()["body_markdown"], normalized)
        self.assertEqual(exported.json()["format_version"], "laohu-manuscript-v1")
        directory = self.client.get(f"/api/studio/novels/{project_id}").json()["directory"]["volumes"]
        self.assertEqual([len(item["chapters"]) for item in directory], [2, 0, 1])
        blocks = self.client.get(f"/api/studio/novels/{project_id}/view?scope=root").json()["blocks"]
        self.assertEqual([item["body_markdown"] for item in blocks], ["", "\n😀段落  \n", "尾行\n"])
        no_replace = self.command("novel", project_id, 2, "novel-markdown-no-replace", "import_markdown", {
            "body_markdown": "# 另一卷\n", "replace": False})
        self.assertEqual(no_replace.status_code, 409, no_replace.text)
        replaced = self.command("novel", project_id, 2, "novel-markdown-replace", "import_markdown", {
            "body_markdown": "# 新卷\n## 新章\n新正文", "replace": True})
        self.assertEqual(replaced.status_code, 200, replaced.text)
        old_sha = hashlib.sha256(normalized.encode()).hexdigest()
        historic = self.client.get(f"/api/studio/novels/{project_id}/markdown/history/{old_sha}")
        self.assertEqual(historic.status_code, 200, historic.text)
        self.assertEqual(historic.json()["body_markdown"], normalized)
        archive = self.projects.read_manuscript_record(project_id, "novel")["novel"]["archive"][-1]
        self.assertEqual(len(archive["volumes"]), 3)

        bad = self.command("novel", project_id, 3, "novel-h1-conflict", "create_volume", {"title": "格式冲突"})
        self.assertEqual(bad.status_code, 200, bad.text)
        volume_id = bad.json()["changed_ids"][0]
        chapter = self.command("novel", project_id, 4, "novel-h1-chapter", "create_chapter", {
            "volume_id": volume_id, "title": "章节", "body_markdown": "# 不兼容的小标题"})
        self.assertEqual(chapter.status_code, 200, chapter.text)
        conflict = self.client.get(f"/api/studio/novels/{project_id}/markdown")
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["detail"]["code"], "MARKDOWN_FORMAT_CONFLICT")

    def test_markdown_import_keeps_repeated_titles_as_distinct_items(self):
        project_id = self.create_project("novel")["id"]
        source = "# 序\n## 同名\n甲\n\n## 同名\n乙\n"
        imported = self.command("novel", project_id, 1, "repeated-heading", "import_markdown", {
            "body_markdown": source, "replace": False})
        self.assertEqual(imported.status_code, 200, imported.text)
        volumes = self.client.get(f"/api/studio/novels/{project_id}").json()["directory"]["volumes"]
        chapters = volumes[0]["chapters"]
        self.assertEqual([chapter["title"] for chapter in chapters], ["同名", "同名"])
        self.assertNotEqual(chapters[0]["id"], chapters[1]["id"])
        self.assertEqual(self.client.get(f"/api/studio/novels/{project_id}/markdown").json()["body_markdown"], source)

    def test_story_versions_keep_separate_edit_revisions_and_validate_actual_anchors(self):
        project = self.create_project("novel")
        project_id = project["id"]
        result = self.command("novel", project_id, 1, "create-vol", "create_volume", {"title": "卷一", "client_ref": "v"})
        self.assertEqual(result.status_code, 200, result.text)
        volume_id = result.json()["created_ids"]["v"]
        result = self.command("novel", project_id, 2, "chapter", "create_chapter", {
            "volume_id": volume_id, "title": "第一章", "body_markdown": "开场正文"})
        chapter_id = result.json()["created_ids"].get("chapter")
        if chapter_id is None:
            chapter_id = result.json()["changed_ids"][-1]
        result = self.command("novel", project_id, 3, "event", "create_setting_entry", {
            "category_id": "timeline", "body_markdown": "# 雨夜\n林澈离开。", "use_state": "confirmed"})
        self.assertEqual(result.status_code, 200, result.text)
        record = self.projects.read_manuscript_record(project_id, "novel")
        timeline_entry = record["novel"]["settings"]["entries"][0]
        event_version = timeline_entry["versions"][0]
        result = self.command("novel", project_id, 4, "entry", "create_setting_entry", {
            "category_id": "characters", "body_markdown": "# 林澈\n原本疏离。", "use_state": "confirmed"})
        self.assertEqual(result.status_code, 200, result.text)
        record = self.projects.read_manuscript_record(project_id, "novel")
        hero = next(item for item in record["novel"]["settings"]["entries"] if item["category_id"] == "characters")
        initial = hero["versions"][0]
        self.assertEqual(initial["story_anchor"], {"kind": "unspecified"})
        result = self.command("novel", project_id, 5, "add-version", "add_setting_version", {
            "entry_id": hero["id"], "based_on_version_id": initial["id"], "body_markdown": "# 林澈\n经历雨夜后，愿意信任同伴。",
            "use_state": "confirmed", "story_anchor": {"kind": "event", "event_entry_id": timeline_entry["id"],
                "event_version_id": event_version["id"], "chapter_id": chapter_id, "side": "after"}},
            expected_sources=[{"entry_id": hero["id"], "version_id": initial["id"], "content_sha256": initial["content_sha256"]}])
        self.assertEqual(result.status_code, 200, result.text)
        version_id = result.json()["created_ids"].get("version")
        if version_id is None:
            version_id = result.json()["changed_ids"][-1]
        record = self.projects.read_manuscript_record(project_id, "novel")
        hero = next(item for item in record["novel"]["settings"]["entries"] if item["id"] == hero["id"])
        evolved = next(item for item in hero["versions"] if item["id"] == version_id)
        self.assertEqual(evolved["based_on_content_sha256"], initial["content_sha256"])
        self.assertEqual(evolved["story_anchor"]["event_content_sha256"], event_version["content_sha256"])
        stale_source = self.command("novel", project_id, 6, "stale-source", "add_setting_version", {
            "entry_id": hero["id"], "based_on_version_id": initial["id"], "body_markdown": "# bad", "use_state": "draft"},
            expected_sources=[{"entry_id": hero["id"], "version_id": initial["id"], "content_sha256": "0" * 64}])
        self.assertEqual(stale_source.status_code, 409, stale_source.text)
        result = self.command("novel", project_id, 6, "revise", "revise_setting_version", {
            "entry_id": hero["id"], "version_id": version_id, "body_markdown": "# 林澈\n更细微的变化。"})
        self.assertEqual(result.status_code, 200, result.text)
        detail = self.client.get(f"/api/studio/novels/{project_id}/settings/{hero['id']}?version_id={version_id}").json()
        self.assertEqual(detail["selected_version"]["edit_revision"], 2)
        summary = self.client.get(f"/api/studio/novels/{project_id}/settings?category_id=characters").json()
        self.assertEqual(len(summary["entries"][0]["versions"]), 2)
        invalid_event = self.command("novel", project_id, 7, "fake-event", "set_setting_version_anchor", {
            "entry_id": hero["id"], "version_id": version_id,
            "story_anchor": {"kind": "event", "event_entry_id": "not-a-timeline-entry", "event_version_id": "missing", "side": "after"}})
        self.assertIn(invalid_event.status_code, (400, 404))

    def test_context_is_an_unranked_candidate_index_and_manifest_omits_revision_blobs(self):
        project = self.create_project("novel")
        project_id = project["id"]
        result = self.command("novel", project_id, 1, "volume", "create_volume", {"title": "第一卷", "client_ref": "v"})
        volume_id = result.json()["created_ids"]["v"]
        result = self.command("novel", project_id, 2, "chapter", "create_chapter", {
            "volume_id": volume_id, "title": "第一章", "body_markdown": "章正文", "client_ref": "ch"})
        chapter_id = result.json()["created_ids"]["ch"]
        result = self.command("novel", project_id, 3, "setting", "create_setting_entry", {
            "category_id": "characters", "body_markdown": "# 角色\n初始设定。", "use_state": "confirmed",
            "story_anchor": {"kind": "baseline"}, "client_ref": "character"})
        entry_id = result.json()["created_ids"]["character"]
        record = self.projects.read_manuscript_record(project_id, "novel")
        entry = next(item for item in record["novel"]["settings"]["entries"] if item["id"] == entry_id)
        version = entry["versions"][0]
        result = self.command("novel", project_id, 4, "later-version", "add_setting_version", {
            "entry_id": entry_id, "based_on_version_id": version["id"], "body_markdown": "# 角色\n后续变化。",
            "use_state": "confirmed", "story_anchor": {"kind": "chapter_boundary", "chapter_id": chapter_id, "side": "after"},
            "client_ref": "latest"}, expected_sources=[{"entry_id": entry_id, "version_id": version["id"], "content_sha256": version["content_sha256"]}])
        self.assertEqual(result.status_code, 200, result.text)
        context = self.client.get(f"/api/studio/novels/{project_id}/context?chapter_id={chapter_id}").json()
        self.assertEqual(context["documents"], [])
        self.assertEqual(len(context["candidate_index"]), 2)
        self.assertIn("不由目录顺序", context["guidance"])
        self.assertNotIn("适用", json.dumps(context["candidate_index"], ensure_ascii=False))
        manifest = self.client.get(f"/api/studio/novels/{project_id}/manifest").json()
        encoded = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn("history", encoded)
        self.assertNotIn("body_markdown", encoded)
        self.assertEqual(manifest["inventory"]["volumes"][0]["chapters"][0]["id"], chapter_id)
        search = self.client.get(f"/api/studio/novels/{project_id}/search?q=后续变化&scope=settings").json()
        self.assertEqual(search["results"][0]["version_id"], result.json()["created_ids"]["latest"])

        draft = self.command("novel", project_id, 5, "draft-character", "create_setting_entry", {
            "category_id": "characters", "body_markdown": "# 草稿角色\n仅草稿中的独特检索词。", "use_state": "draft"})
        self.assertEqual(draft.status_code, 200, draft.text)
        default_search = self.client.get(f"/api/studio/novels/{project_id}/search?q=独特检索词&scope=settings")
        self.assertEqual(default_search.status_code, 200, default_search.text)
        self.assertEqual(default_search.json()["results"], [])
        draft_search = self.client.get(f"/api/studio/novels/{project_id}/search?q=独特检索词&scope=settings&include_drafts=true")
        self.assertEqual(draft_search.status_code, 200, draft_search.text)
        self.assertEqual(draft_search.json()["results"][0]["use_state"], "draft")

    def test_script_draft_history_read_restore_preserves_structured_snapshot(self):
        project_id = self.create_project("script")["id"]
        original = "😀完整草稿·旧版本"
        first = self.command("script", project_id, 1, "draft-original", "set_draft", {"body_markdown": original})
        self.assertEqual(first.status_code, 200, first.text)
        structured = self.command("script", project_id, 2, "structure-original", "structure_draft", {"episodes": [
            {"client_ref": "ep", "title": "第一集", "scenes": [
                {"client_ref": "scene", "title": "第一场", "body_markdown": original, "start": 0, "end": len(original)}]}
        ]})
        self.assertEqual(structured.status_code, 200, structured.text)
        scene_id = structured.json()["created_ids"]["scene"]
        edited = self.command("script", project_id, 3, "edit-scene", "update_scene", {
            "scene_id": scene_id, "body_markdown": "结构化场次已修改。"})
        self.assertEqual(edited.status_code, 200, edited.text)

        history = self.client.get(f"/api/studio/scripts/{project_id}/history?limit=1")
        self.assertEqual(history.status_code, 200, history.text)
        old_digest = next(item["content_sha256"] for item in history.json()["history"]
                          if item["content_sha256"] == hashlib.sha256(original.encode()).hexdigest())
        old_document = self.client.get(f"/api/studio/scripts/{project_id}/history/{old_digest}")
        self.assertEqual(old_document.status_code, 200, old_document.text)
        self.assertEqual(old_document.json()["body_markdown"], original)
        self.assertEqual(old_document.json()["char_count"], len(original))

        restore = self.command("script", project_id, 4, "restore-old-draft", "restore_draft", {
            "source_sha256": old_digest, "replace_structured": True})
        self.assertEqual(restore.status_code, 200, restore.text)
        current = self.client.get(f"/api/studio/scripts/{project_id}/view?scope=root")
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["blocks"][0]["body_markdown"], original)
        record = self.projects.read_manuscript_record(project_id, "script")
        archived = next(item for item in record["script"]["archive"]
                        if item.get("kind") == "structured_script_snapshot")
        self.assertEqual(archived["episodes"][0]["scenes"][0]["id"], scene_id)
        archived_scene = archived["episodes"][0]["scenes"][0]
        self.assertEqual(self.projects.read_manuscript_record(project_id, "script")["script"]["state"], "draft")
        self.assertTrue(archived_scene["history"])
        archive_reader = StudioManuscriptStore(self.tmp.name, self.projects)
        self.assertEqual(archive_reader._read_blob(archived_scene["history"][0]["content_sha256"]), original)

    def test_script_and_novel_views_read_only_the_requested_page_bodies(self):
        novel_id = self.create_project("novel")["id"]
        operations = [{"action": "create_volume", "args": {"title": "一卷", "client_ref": "v"}}]
        operations.extend({"action": "create_chapter", "args": {
            "volume_id": "v", "title": f"第{i}章", "body_markdown": f"小说正文{i}", "client_ref": f"c{i}"}}
            for i in range(35))
        created = self.command("novel", novel_id, 1, "many-chapters", "batch", {"operations": operations})
        self.assertEqual(created.status_code, 200, created.text)
        novel_store = StudioManuscriptStore(self.tmp.name, self.projects)
        read_blob = novel_store._read_blob
        with patch.object(novel_store, "_read_blob", wraps=read_blob) as counted:
            first_page = novel_store.novel_view(novel_id, "root", limit=2)
        self.assertEqual(len(first_page["blocks"]), 2)
        self.assertEqual(counted.call_count, 2)
        with patch.object(novel_store, "_read_blob", wraps=read_blob) as counted:
            second_page = novel_store.novel_view(novel_id, "root", cursor=first_page["next_cursor"], limit=2)
        self.assertEqual(len(second_page["blocks"]), 2)
        self.assertEqual(counted.call_count, 2)
        self.assertEqual(second_page["revision"], first_page["revision"])

        script_id = self.create_project("script")["id"]
        episode = self.command("script", script_id, 1, "many-scene-episode", "create_episode", {
            "title": "第一集", "client_ref": "ep"})
        self.assertEqual(episode.status_code, 200, episode.text)
        episode_id = episode.json()["created_ids"]["ep"]
        scene_ops = [{"action": "create_scene", "args": {"episode_id": episode_id, "title": f"场{i}",
                      "body_markdown": f"场次正文{i}", "client_ref": f"s{i}"}} for i in range(35)]
        scenes = self.command("script", script_id, 2, "many-scenes", "batch", {"operations": scene_ops})
        self.assertEqual(scenes.status_code, 200, scenes.text)
        script_store = StudioManuscriptStore(self.tmp.name, self.projects)
        read_blob = script_store._read_blob
        with patch.object(script_store, "_read_blob", wraps=read_blob) as counted:
            first_scene_page = script_store.script_view(script_id, "root", limit=2)
        self.assertEqual(len(first_scene_page["blocks"]), 2)
        self.assertEqual(counted.call_count, 2)
        self.assertTrue(first_scene_page["has_more"])
        with patch.object(script_store, "_read_blob", wraps=read_blob) as counted:
            next_scene_page = script_store.script_view(script_id, "root", cursor=first_scene_page["next_cursor"], limit=2)
        self.assertEqual(len(next_scene_page["blocks"]), 2)
        self.assertEqual(counted.call_count, 2)
        self.assertEqual(next_scene_page["revision"], first_scene_page["revision"])

    def test_reordered_chapter_boundary_is_flagged_without_applicability_inference(self):
        project_id = self.create_project("novel")["id"]
        outline = self.command("novel", project_id, 1, "outline", "batch", {"operations": [
            {"action": "create_volume", "args": {"title": "第一卷", "client_ref": "v"}},
            {"action": "create_chapter", "args": {"volume_id": "v", "title": "第一章", "body_markdown": "一", "client_ref": "ch1"}},
            {"action": "create_chapter", "args": {"volume_id": "v", "title": "第二章", "body_markdown": "二", "client_ref": "ch2"}},
        ]})
        self.assertEqual(outline.status_code, 200, outline.text)
        ids = outline.json()["created_ids"]
        setting = self.command("novel", project_id, 2, "anchored-person", "create_setting_entry", {
            "category_id": "characters", "body_markdown": "# 人物\n阶段变化。", "use_state": "confirmed",
            "story_anchor": {"kind": "chapter_boundary", "chapter_id": ids["ch1"], "side": "after"},
            "client_ref": "person"})
        self.assertEqual(setting.status_code, 200, setting.text)
        entry_id = setting.json()["created_ids"]["person"]
        record = self.projects.read_manuscript_record(project_id, "novel")
        entry = next(item for item in record["novel"]["settings"]["entries"] if item["id"] == entry_id)
        version = entry["versions"][0]
        before = self.client.get(f"/api/studio/novels/{project_id}/settings/{entry_id}?version_id={version['id']}").json()
        self.assertFalse(before["selected_version"]["needs_review"])
        reordered = self.command("novel", project_id, 3, "reorder-chapters", "reorder_items", {
            "parent_type": "volume", "parent_id": ids["v"], "ordered_ids": [ids["ch2"], ids["ch1"]]})
        self.assertEqual(reordered.status_code, 200, reordered.text)
        after = self.client.get(f"/api/studio/novels/{project_id}/settings/{entry_id}?version_id={version['id']}").json()
        self.assertTrue(after["selected_version"]["needs_review"])
        self.assertEqual(after["selected_version"]["body_markdown"], "# 人物\n阶段变化。")

    def test_handoff_empty_state_is_normal_and_historical_source_refs_are_snapshot_bound(self):
        project_id = self.create_project("novel")["id"]
        empty = self.client.get(f"/api/studio/novels/{project_id}/handoff")
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json()["exists"], False)
        self.assertIsNone(empty.json()["record"])
        unknown_record = self.client.get(f"/api/studio/novels/{project_id}/handoff?record_id=missing")
        self.assertEqual(unknown_record.status_code, 404, unknown_record.text)

        volume = self.command("novel", project_id, 1, "volume", "create_volume", {"title": "第一卷", "client_ref": "v"})
        volume_id = volume.json()["created_ids"]["v"]
        chapter = self.command("novel", project_id, 2, "chapter", "create_chapter", {
            "volume_id": volume_id, "title": "第一章", "body_markdown": "最初章节正文。", "client_ref": "ch"})
        chapter_id = chapter.json()["created_ids"]["ch"]
        chapter_doc = self.client.get(f"/api/studio/novels/{project_id}/chapters/{chapter_id}").json()["chapter"]
        original_ref = {"kind": "chapter", "chapter_id": chapter_id,
                        "content_sha256": chapter_doc["content_sha256"]}
        handoff = self.command("novel", project_id, 3, "handoff", "update_handoff_record", {
            "body_markdown": "# 接续\n继续第一章。", "source_refs": [original_ref]})
        self.assertEqual(handoff.status_code, 200, handoff.text)
        record_id = self.client.get(f"/api/studio/novels/{project_id}/handoff").json()["record"]["id"]

        changed = self.command("novel", project_id, 4, "chapter-change", "update_chapter", {
            "chapter_id": chapter_id, "body_markdown": "章节正文已变化。"})
        self.assertEqual(changed.status_code, 200, changed.text)
        historical = self.client.get(f"/api/studio/novels/{project_id}/handoff?record_id={record_id}&edit_revision=1")
        self.assertEqual(historical.status_code, 200, historical.text)
        saved = historical.json()["record"]
        self.assertEqual(saved["body_markdown"], "# 接续\n继续第一章。")
        self.assertEqual(saved["source_refs"], [original_ref])
        self.assertTrue(saved["needs_review"])

    def test_episode_and_chapter_outlines_use_batch_history_without_changing_body(self):
        script_id = self.create_project("script")["id"]
        created_script = self.command("script", script_id, 1, "script-outline-setup", "batch", {"operations": [
            {"action": "create_episode", "args": {"title": "试写集", "client_ref": "ep"}},
            {"action": "create_scene", "args": {"episode_id": "ep", "title": "试写场",
                "body_markdown": "场次正文🙂", "client_ref": "scene"}},
            {"action": "set_episode_outline", "args": {"episode_id": "ep", "body_markdown": "初版章纲\r\n人物目标"}},
            {"action": "set_episode_outline", "args": {"episode_id": "ep", "body_markdown": "最终章纲🙂\n冲突升级"}},
        ]})
        self.assertEqual(created_script.status_code, 200, created_script.text)
        script_receipt = created_script.json()
        episode_id = script_receipt["created_ids"]["ep"]
        scene_id = script_receipt["created_ids"]["scene"]
        self.assertEqual(script_receipt["revision"], 2)
        replay = self.command("script", script_id, 1, "script-outline-setup", "batch", {"operations": [
            {"action": "create_episode", "args": {"title": "试写集", "client_ref": "ep"}},
            {"action": "create_scene", "args": {"episode_id": "ep", "title": "试写场",
                "body_markdown": "场次正文🙂", "client_ref": "scene"}},
            {"action": "set_episode_outline", "args": {"episode_id": "ep", "body_markdown": "初版章纲\r\n人物目标"}},
            {"action": "set_episode_outline", "args": {"episode_id": "ep", "body_markdown": "最终章纲🙂\n冲突升级"}},
        ]})
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), script_receipt)
        stale = self.command("script", script_id, 1, "script-outline-stale", "set_episode_outline", {
            "episode_id": episode_id, "body_markdown": "过期草稿"})
        self.assertEqual(stale.status_code, 409, stale.text)
        current = self.client.get(f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline")
        self.assertEqual(current.status_code, 200, current.text)
        current_doc = current.json()
        self.assertEqual(current_doc["outline_markdown"], "最终章纲🙂\n冲突升级")
        self.assertEqual(current_doc["outline_revision"], 2)
        self.assertEqual(current_doc["current_outline_revision"], 2)
        self.assertEqual(current_doc["selected_revision"], "current")
        prior = self.client.get(f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline?outline_revision=1")
        self.assertEqual(prior.status_code, 200, prior.text)
        self.assertEqual(prior.json()["outline_markdown"], "初版章纲\n人物目标")
        self.assertEqual(prior.json()["selected_revision"], "history")
        blank = self.client.get(f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline?outline_revision=0")
        self.assertEqual(blank.status_code, 200, blank.text)
        self.assertEqual(blank.json()["outline_markdown"], "")
        self.assertEqual(blank.json()["outline_sha256"], "")

        scene_before = self.client.get(f"/api/studio/scripts/{script_id}/scenes/{scene_id}").json()["scene"]
        summary = self.client.get(f"/api/studio/scripts/{script_id}").json()
        self.assertEqual(summary["directory"]["episodes"][0]["outline_revision"], 2)
        self.assertEqual(summary["statistics"]["characters"], len("场次正文🙂"))
        exported = self.client.get(f"/api/studio/scripts/{script_id}/markdown").json()["body_markdown"]
        self.assertNotIn("最终章纲", exported)
        snapshot = StudioManuscriptStore(self.tmp.name, self.projects).script_import_snapshot(
            script_id, 2, {"type": "episode", "ids": [episode_id]})
        self.assertNotIn("最终章纲", json.dumps(snapshot, ensure_ascii=False))
        self.assertNotIn("outline_markdown", snapshot["episodes"][0])

        cleared_outline = self.command("script", script_id, 2, "clear-episode-outline", "set_episode_outline", {
            "episode_id": episode_id, "body_markdown": ""})
        self.assertEqual(cleared_outline.status_code, 200, cleared_outline.text)
        cleared = self.client.get(f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline").json()
        self.assertEqual(cleared["outline_revision"], 3)
        self.assertEqual(cleared["outline_markdown"], "")
        self.assertEqual(cleared["outline_sha256"], "")
        self.assertEqual(self.client.get(
            f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline?outline_revision=2").json()["outline_markdown"],
            "最终章纲🙂\n冲突升级")

        changed_scene = self.command("script", script_id, 3, "scene-body-after-outline", "update_scene", {
            "scene_id": scene_id, "body_markdown": "场次正文改写🙂"})
        self.assertEqual(changed_scene.status_code, 200, changed_scene.text)
        scene_after = self.client.get(f"/api/studio/scripts/{script_id}/scenes/{scene_id}").json()["scene"]
        self.assertEqual(scene_after["body_markdown"], "场次正文改写🙂")
        self.assertNotEqual(scene_after["content_sha256"], scene_before["content_sha256"])
        self.assertEqual(self.client.get(f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline").json()["outline_markdown"], "")

        novel_id = self.create_project("novel")["id"]
        setup_novel = self.command("novel", novel_id, 1, "novel-outline-setup", "batch", {"operations": [
            {"action": "create_volume", "args": {"title": "试写卷", "client_ref": "vol"}},
            {"action": "create_chapter", "args": {"volume_id": "vol", "title": "试写章",
                "body_markdown": "章节正文📚", "client_ref": "chapter"}},
        ]})
        self.assertEqual(setup_novel.status_code, 200, setup_novel.text)
        chapter_id = setup_novel.json()["created_ids"]["chapter"]
        chapter_before = self.client.get(f"/api/studio/novels/{novel_id}/chapters/{chapter_id}").json()["chapter"]
        outline_batch = {"request_id": "novel-outline-batch", "expected_revision": 2, "action": "batch", "args": {"operations": [
            {"action": "set_chapter_outline", "args": {"chapter_id": chapter_id, "body_markdown": "章节章纲初版"}},
            {"action": "set_chapter_outline", "args": {"chapter_id": chapter_id, "body_markdown": "章节章纲终版📚"}},
        ]}}
        first_outline_save = self.client.post(f"/api/studio/novels/{novel_id}/commands", json=outline_batch)
        self.assertEqual(first_outline_save.status_code, 200, first_outline_save.text)
        outline_receipt = first_outline_save.json()
        replay_outline_save = self.client.post(f"/api/studio/novels/{novel_id}/commands", json=outline_batch)
        self.assertEqual(replay_outline_save.status_code, 200, replay_outline_save.text)
        self.assertEqual(replay_outline_save.json(), outline_receipt)
        chapter_outline = self.client.get(f"/api/studio/novels/{novel_id}/chapters/{chapter_id}/outline")
        self.assertEqual(chapter_outline.status_code, 200, chapter_outline.text)
        self.assertEqual(chapter_outline.json()["outline_markdown"], "章节章纲终版📚")
        self.assertEqual(chapter_outline.json()["outline_revision"], 2)
        chapter_outline_history = self.client.get(
            f"/api/studio/novels/{novel_id}/chapters/{chapter_id}/outline?outline_revision=1")
        self.assertEqual(chapter_outline_history.json()["outline_markdown"], "章节章纲初版")
        chapter_after_outline = self.client.get(f"/api/studio/novels/{novel_id}/chapters/{chapter_id}").json()["chapter"]
        self.assertEqual(chapter_after_outline["body_markdown"], chapter_before["body_markdown"])
        self.assertEqual(chapter_after_outline["content_sha256"], chapter_before["content_sha256"])
        self.assertEqual(chapter_after_outline["revision"], chapter_before["revision"])
        novel_summary = self.client.get(f"/api/studio/novels/{novel_id}").json()
        self.assertEqual(novel_summary["directory"]["volumes"][0]["chapters"][0]["outline_revision"], 2)
        self.assertEqual(novel_summary["statistics"]["characters"], len("章节正文📚"))
        manifest = self.client.get(f"/api/studio/novels/{novel_id}/manifest").json()
        manifest_chapter = manifest["inventory"]["chapters"][0]
        self.assertEqual(manifest_chapter["outline_revision"], 2)
        self.assertEqual(manifest_chapter["outline_sha256"], chapter_outline.json()["outline_sha256"])
        self.assertNotIn("outline_markdown", manifest_chapter)
        novel_export = self.client.get(f"/api/studio/novels/{novel_id}/markdown").json()["body_markdown"]
        self.assertNotIn("章节章纲", novel_export)
        chapter_body_update = self.command("novel", novel_id, 3, "chapter-body-after-outline", "update_chapter", {
            "chapter_id": chapter_id, "body_markdown": "章节正文改写📚"})
        self.assertEqual(chapter_body_update.status_code, 200, chapter_body_update.text)
        renamed_and_reordered = self.command("novel", novel_id, 4, "chapter-rename-reorder-with-outline", "batch", {
            "operations": [
                {"action": "rename_item", "args": {"item_type": "chapter", "item_id": chapter_id, "title": "改名章节"}},
                {"action": "reorder_items", "args": {"parent_type": "volume",
                    "parent_id": setup_novel.json()["created_ids"]["vol"], "ordered_ids": [chapter_id]}},
            ]})
        self.assertEqual(renamed_and_reordered.status_code, 200, renamed_and_reordered.text)
        self.assertEqual(self.client.get(f"/api/studio/novels/{novel_id}/chapters/{chapter_id}/outline").json()["outline_markdown"],
                         "章节章纲终版📚")

    def test_outline_legacy_empty_reads_and_parent_delete_restore_and_replace_archive(self):
        script_id = self.create_project("script")["id"]
        created_episode = self.command("script", script_id, 1, "legacy-ep", "create_episode", {
            "title": "待整理集", "client_ref": "ep"})
        self.assertEqual(created_episode.status_code, 200, created_episode.text)
        episode_id = created_episode.json()["created_ids"]["ep"]
        # Simulate a pre-feature project record: missing outline fields read as an empty outline.
        with self.projects.lock:
            record = self.projects.read_manuscript_record(script_id, "script")
            for key in ("outline_revision", "outline_sha256", "outline_char_count", "outline_history"):
                record["script"]["episodes"][0].pop(key, None)
            self.projects.write_manuscript_record(record)
        legacy = self.client.get(f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline")
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.assertEqual(legacy.json()["outline_revision"], 0)
        self.assertEqual(legacy.json()["outline_sha256"], "")
        self.assertEqual(legacy.json()["outline_markdown"], "")
        saved = self.command("script", script_id, 2, "save-episode-outline", "set_episode_outline", {
            "episode_id": episode_id, "body_markdown": "集章纲🙂"})
        self.assertEqual(saved.status_code, 200, saved.text)
        deleted = self.command("script", script_id, 3, "delete-episode-with-outline", "delete_item", {
            "item_type": "episode", "item_id": episode_id})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get(f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline").status_code, 404)
        restored = self.command("script", script_id, 4, "restore-episode-outline", "restore_item", {"item_id": episode_id})
        self.assertEqual(restored.status_code, 200, restored.text)
        restored_outline = self.client.get(f"/api/studio/scripts/{script_id}/episodes/{episode_id}/outline").json()
        self.assertEqual(restored_outline["outline_markdown"], "集章纲🙂")
        replaced = self.command("script", script_id, 5, "replace-script-with-outline", "import_markdown", {
            "body_markdown": "# 新集\n## 新场\n新场正文", "replace": True})
        self.assertEqual(replaced.status_code, 200, replaced.text)
        script_record = self.projects.read_manuscript_record(script_id, "script")["script"]
        archived_episode = next(item for item in script_record["archive"][-1]["episodes"] if item["id"] == episode_id)
        self.assertEqual(archived_episode["outline_sha256"], restored_outline["outline_sha256"])
        self.assertEqual(StudioManuscriptStore(self.tmp.name, self.projects)._read_blob(archived_episode["outline_sha256"]),
                         "集章纲🙂")

        novel_id = self.create_project("novel")["id"]
        setup_novel = self.command("novel", novel_id, 1, "archive-volume", "batch", {"operations": [
            {"action": "create_volume", "args": {"title": "卷", "client_ref": "vol"}},
            {"action": "create_chapter", "args": {"volume_id": "vol", "title": "章",
                "body_markdown": "正文", "client_ref": "ch"}},
        ]})
        self.assertEqual(setup_novel.status_code, 200, setup_novel.text)
        chapter_id = setup_novel.json()["created_ids"]["ch"]
        with self.projects.lock:
            record = self.projects.read_manuscript_record(novel_id, "novel")
            chapter = record["novel"]["volumes"][0]["chapters"][0]
            for key in ("outline_revision", "outline_sha256", "outline_char_count", "outline_history"):
                chapter.pop(key, None)
            self.projects.write_manuscript_record(record)
        legacy_chapter_outline = self.client.get(f"/api/studio/novels/{novel_id}/chapters/{chapter_id}/outline")
        self.assertEqual(legacy_chapter_outline.status_code, 200, legacy_chapter_outline.text)
        self.assertEqual(legacy_chapter_outline.json()["outline_revision"], 0)
        self.assertEqual(legacy_chapter_outline.json()["outline_markdown"], "")
        save_chapter_outline = self.command("novel", novel_id, 2, "save-chapter-outline", "set_chapter_outline", {
            "chapter_id": chapter_id, "body_markdown": "章纲历史🙂"})
        self.assertEqual(save_chapter_outline.status_code, 200, save_chapter_outline.text)
        delete_chapter = self.command("novel", novel_id, 3, "delete-chapter-with-outline", "delete_item", {
            "item_type": "chapter", "item_id": chapter_id})
        self.assertEqual(delete_chapter.status_code, 200, delete_chapter.text)
        restore_chapter = self.command("novel", novel_id, 4, "restore-chapter-outline", "restore_item", {"item_id": chapter_id})
        self.assertEqual(restore_chapter.status_code, 200, restore_chapter.text)
        self.assertEqual(self.client.get(f"/api/studio/novels/{novel_id}/chapters/{chapter_id}/outline").json()["outline_markdown"],
                         "章纲历史🙂")
        replace_novel = self.command("novel", novel_id, 5, "replace-novel-with-outline", "import_markdown", {
            "body_markdown": "# 新卷\n## 新章\n新正文", "replace": True})
        self.assertEqual(replace_novel.status_code, 200, replace_novel.text)
        novel_record = self.projects.read_manuscript_record(novel_id, "novel")["novel"]
        archived_chapter = novel_record["archive"][-1]["volumes"][0]["chapters"][0]
        self.assertEqual(StudioManuscriptStore(self.tmp.name, self.projects)._read_blob(archived_chapter["outline_sha256"]),
                         "章纲历史🙂")

    def test_outline_command_and_read_routes_are_discoverable_in_openapi(self):
        schema = self.client.get("/openapi.json").json()
        components = schema["components"]["schemas"]
        self.assertEqual(components["SetEpisodeOutlineArgs"]["required"], ["episode_id", "body_markdown"])
        self.assertEqual(components["SetChapterOutlineArgs"]["required"], ["chapter_id", "body_markdown"])
        self.assertIn("SetEpisodeOutlineBatchOperation", components)
        self.assertIn("SetChapterOutlineBatchOperation", components)
        self.assertEqual(schema["paths"]["/api/studio/scripts/{project_id}/episodes/{episode_id}/outline"]
                         ["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
                         "#/components/schemas/ManuscriptOutlineDocument")
        self.assertEqual(schema["paths"]["/api/studio/novels/{project_id}/chapters/{chapter_id}/outline"]
                         ["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
                         "#/components/schemas/ManuscriptOutlineDocument")
        outline_schema = components["ManuscriptOutlineDocument"]
        self.assertEqual(outline_schema["properties"]["selected_revision"]["enum"], ["current", "history"])
        self.assertEqual(outline_schema["properties"]["outline_revision"]["type"], "integer")
        self.assertEqual(outline_schema["properties"]["outline_markdown"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
