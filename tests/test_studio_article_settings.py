import copy
import tempfile
import unittest
from pathlib import Path
from threading import RLock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from studio_hypit_canvas import (
    ARTICLE_SETTINGS_CANVAS_ID,
    ARTICLE_SETTINGS_CANVAS_URL,
    HypitSettingsCanvasService,
    create_hypit_settings_canvas_router,
)


TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / "cache" / "studio-tests" / "tmp"


class ArticleSettingsCanvasTests(unittest.TestCase):
    def test_blank_article_settings_canvas_reuses_get_put_agent_and_reset_contract(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as temporary:
            saved = {}
            lock = RLock()
            legacy_reads = []
            projected_ids = []
            broadcasts = []

            def load_canvas(canvas_id):
                current = saved.get(canvas_id)
                if current is None:
                    raise HTTPException(status_code=404, detail="missing")
                return copy.deepcopy(current)

            def save_canvas(canvas, *, increment_revision=True, touch_updated_at=True):
                current = saved.get(canvas["id"])
                result = copy.deepcopy(canvas)
                if current is not None and increment_revision:
                    result["revision"] = int(current.get("revision") or 1) + 1
                elif current is not None:
                    result["revision"] = int(current.get("revision") or 1)
                saved[result["id"]] = copy.deepcopy(result)
                return result

            def validate(canvas, *, canvas_id=None, module_id=None):
                self.assertEqual(canvas_id, ARTICLE_SETTINGS_CANVAS_ID)
                self.assertEqual(module_id, "article")
                self.assertEqual(canvas.get("id"), ARTICLE_SETTINGS_CANVAS_ID)
                self.assertIsInstance(canvas.get("nodes"), list)
                self.assertIsInstance(canvas.get("connections"), list)

            def load_legacy():
                legacy_reads.append(True)
                return {"defaults": {"image": {"provider": "must-not-import"}}}

            def statuses(canvas_id, canvas):
                projected_ids.append(canvas_id)
                return {}

            service = HypitSettingsCanvasService(
                load_canvas=load_canvas,
                save_canvas=save_canvas,
                lock=lock,
                load_legacy_settings=load_legacy,
                backup_legacy_settings=lambda _record: self.fail("article graph must not migrate Hypit settings"),
                migrate_legacy_settings=lambda _defaults, _canvas_id: self.fail("article graph must stay blank on first open"),
                validate_canvas=validate,
                test_statuses=statuses,
                broadcast_canvas_updated=lambda *args: broadcasts.append(args),
                now_ms=lambda: 1234,
                canvas_id=ARTICLE_SETTINGS_CANVAS_ID,
                module_id="article",
                canvas_url=ARTICLE_SETTINGS_CANVAS_URL,
                migrate_legacy=False,
            )
            app = FastAPI()
            app.include_router(create_hypit_settings_canvas_router(
                service=service,
                base_path="/api/studio/articles/settings-canvas",
                include_test_routes=False,
            ))

            @app.get("/api/canvases/{canvas_id}")
            async def standard_get(canvas_id):
                current = service.ensure_canvas()
                if canvas_id != ARTICLE_SETTINGS_CANVAS_ID:
                    raise HTTPException(404)
                return {"canvas": await service.projected_canvas(current)}

            @app.put("/api/canvases/{canvas_id}")
            async def standard_put(canvas_id, payload: dict):
                if canvas_id != ARTICLE_SETTINGS_CANVAS_ID:
                    raise HTTPException(404)
                with lock:
                    current = service.ensure_canvas()
                    candidate = service.prepare_update_candidate(current, payload)
                    result = service.save_agent_canvas(candidate)
                return {"canvas": await service.projected_canvas(result)}

            @app.post("/api/agent/article-settings/write")
            async def agent_write():
                current = service.ensure_canvas()
                candidate = copy.deepcopy(current)
                candidate["nodes"] = [{"id": "writer-node", "type": "smart-image-generator"}]
                result = service.save_agent_canvas(candidate)
                return {"canvas": result}

            with TestClient(app) as client:
                opened = client.get("/api/studio/articles/settings-canvas")
                self.assertEqual(opened.status_code, 200, opened.text)
                opened_payload = opened.json()
                self.assertEqual(opened_payload["id"], ARTICLE_SETTINGS_CANVAS_ID)
                self.assertEqual(opened_payload["url"], ARTICLE_SETTINGS_CANVAS_URL)
                canvas = opened_payload["canvas"]
                self.assertEqual(canvas["nodes"], [])
                self.assertEqual(canvas["connections"], [])
                self.assertTrue(canvas["article_settings_initialized"])
                self.assertEqual(legacy_reads, [])

                standard = client.get(f"/api/canvases/{ARTICLE_SETTINGS_CANVAS_ID}")
                self.assertEqual(standard.status_code, 200, standard.text)
                self.assertEqual(standard.json()["canvas"]["revision"], canvas["revision"])
                saved_graph = client.put(f"/api/canvases/{ARTICLE_SETTINGS_CANVAS_ID}", json={
                    "base_revision": canvas["revision"],
                    "nodes": [{"id": "image-node", "type": "smart-image-generator"}],
                    "connections": [],
                    "viewport": {"x": 2, "y": 3, "scale": 1},
                    "logs": [],
                    "settings": {},
                })
                self.assertEqual(saved_graph.status_code, 200, saved_graph.text)
                revision = saved_graph.json()["canvas"]["revision"]

                agent_result = client.post("/api/agent/article-settings/write")
                self.assertEqual(agent_result.status_code, 200, agent_result.text)
                self.assertEqual(agent_result.json()["canvas"]["nodes"][0]["id"], "writer-node")
                self.assertEqual(client.get("/api/studio/articles/settings-canvas").json()["canvas"]["nodes"][0]["id"], "writer-node")

                reset = client.post("/api/studio/articles/settings-canvas/reset", json={
                    "base_revision": revision + 1,
                    "client_id": "test-client",
                })
                self.assertEqual(reset.status_code, 200, reset.text)
                reset_canvas = reset.json()["canvas"]
                self.assertEqual(reset_canvas["nodes"], [])
                self.assertEqual(reset_canvas["connections"], [])
                self.assertEqual(reset_canvas["revision"], revision + 2)
                self.assertEqual(saved[ARTICLE_SETTINGS_CANVAS_ID]["revision"], reset_canvas["revision"])
                self.assertTrue(saved[ARTICLE_SETTINGS_CANVAS_ID]["article_settings_initialized"])
                self.assertIn(ARTICLE_SETTINGS_CANVAS_ID, projected_ids)
                self.assertTrue(any(event[0] == ARTICLE_SETTINGS_CANVAS_ID for event in broadcasts))


if __name__ == "__main__":
    unittest.main()
